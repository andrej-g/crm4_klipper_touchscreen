# Install and operate the bridge

## Install from a clone

On the Pi, as your ordinary login user:

```sh
sudo apt-get update
sudo apt-get install -y git
git clone https://github.com/andrej-g/crm4_klipper_touchscreen.git
cd crm4_klipper_touchscreen
bash scripts/install.sh --install-deps
```

This installs apt dependencies (sudo), adds the login user to `dialout`, creates
an editable `.venv`, installs `.[serial]`, and creates a **user systemd unit**.
The unit is **neither enabled nor started** by default. The clone must remain
at that path because both the editable install and unit refer to it. No stock
firmware is needed just to run the bridge; stock assets are required to build or
emulate the screen UI.

Options: `--no-service` installs Python software only; `--enable` enables the
unit; `--start` starts it; `--linger` uses sudo to enable the user manager at boot.
Run `bash scripts/install.sh --help`. Do not run the entire installer as root.
Without `--install-deps`, install Python 3.9+, venv and build/image dependencies
yourself; this is useful on non-apt Linux distributions. The package itself can
also be installed manually with `python3 -m venv .venv` then
`.venv/bin/python -m pip install -e '.[serial]'`.

The installer preserves existing config. A previously configured service may
still be live; inspect it before explicitly starting it. Reinstalling while
the user service is active is refused: stop it first. Default paths (respecting
`XDG_CONFIG_HOME` at install time):

- `~/.config/crm4bridge/crm4bridge.cfg`: private local configuration.
- `~/.config/systemd/user/crm4bridge.service`: generated user unit.
- `~/.local/state/crm4bridge/state.json`: screen preferences, separate from code.
- `<clone>/.venv`: Python environment.

The installer will not replace an existing unit it did not generate. Keep API
keys/passwords out of Git and keep private config permissions at 600.

## Configure, then test

First complete [Pi UART and wiring configuration](raspberry-pi.md). Reboot after
adding `dialout`, especially if using linger: a user manager already running
may still have its old group membership.

Edit the installed config, e.g.:

```ini
[bridge]
moonraker = http://PRINTER_IP:7125
screen = serial:/dev/serial0@115200
screen_startup_timeout = 5
dry_run = true
machine_page = true
state_file = ~/.local/state/crm4bridge/state.json
```

Replace `PRINTER_IP`. Use `machine_page = false` with an untouched stock UI;
true is for the full `examples/klipper_ui` build. Additional settings are in
`crm4bridge.example.cfg`. To migrate the bench install, copy only the settings
you actually use into this file; the service does not read the old bench config
or shell `env.sh` automatically. Preserve the separate mock state file.

Power the screen before starting. First run interactively:

```sh
.venv/bin/python -m crm4bridge \
  -c ~/.config/crm4bridge/crm4bridge.cfg --dry-run
```

Dry-run reads Moonraker and updates the screen, but logs printer actions instead
of sending them. Compare displayed state and test navigation. Ctrl-C exits.
Then start the user unit (still dry-run because it reads the same config):

```sh
systemctl --user start crm4bridge
systemctl --user status crm4bridge
journalctl --user -u crm4bridge -f
```

After manual validation, set `dry_run = false` in the private config and run
`systemctl --user restart crm4bridge`. Temperature, motion, PID, spool activation
and host-control buttons now perform real actions. Host reboot/shutdown target
the **Moonraker host**, which may be a different machine from the touchscreen Pi.
No `--live` is embedded in the service; the config controls the mode.

To start on boot, even without a login:

```sh
systemctl --user enable crm4bridge
sudo loginctl enable-linger "$USER"
```

Equivalent install-time options are `--enable --linger`; use `--start` only after
the configuration and screen are ready. If changing config/venv paths or moving
the clone, stop the service and rerun the installer to regenerate the unit.

## Startup checks and failure behavior

`screen` must be nonempty and have a valid `serial:PORT[@baud]` or `tcp:HOST:PORT`
format. Invalid config exits **2** in the main process, without starting link
threads, polling Moonraker or processing actions. The service does not retry
configuration errors; fix the config and start it again.

Opening the UART is insufficient: an unpowered screen does not remove a Pi's
UART device. Before normal bridge operation, the bridge reads current-page VP
`0x0014` and requires a valid one-word reply within `screen_startup_timeout`
(default 5 seconds). This query changes no UI or printer state. Missing device,
permissions, connection refused or no screen reply exits **1**, with one useful
error instead of an uncaught worker exception. A daemon is not left running.

The unit uses **Type=notify**: it becomes ready only after that screen check.
`Restart=on-failure` retries operational startup failures after 10 seconds,
including a screen that powers up later. Each failed attempt exits; the user
manager supervises the retries. `RestartPreventExitStatus=2` prevents invalid
config loops. Its start timeout is 30 seconds; increase it with a user-unit
override if you raise `screen_startup_timeout` beyond that window.

The readiness check establishes a responding screen, not a ready Moonraker;
Moonraker may be unavailable at boot and normal polling handles that. No
system-manager `network-online.target` ordering is assumed for this user unit.
After startup, transport failures reconnect and re-check the screen. Power loss
that leaves an open serial device silent is **not continuously detected** by a
watchdog; this is a startup gate, not a promise of ongoing liveness detection.

Troubleshooting:

- `bad screen spec ''` / empty screen: the setting was blank; this is not proof
  the physical screen was off. Set the serial/TCP endpoint explicitly.
- Permission denied: check `ls -l /dev/serial0`, `id`, then reboot after changing
  groups. Do not run the bridge as root or make the UART world-writable.
- No reply: verify screen power, crossed TX/RX, baud, common GND and that no other
  process owns the UART. Stop the service before terminal/flash tools.
- No user bus: log in normally via SSH/local session, and run `systemctl --user`
  without sudo. Linger allows future boot operation without that session.

## Upgrade, flash and uninstall

```sh
systemctl --user stop crm4bridge
git pull --ff-only
bash scripts/install.sh
systemctl --user start crm4bridge
```

Existing config/state are retained; existing enable/linger settings are retained.
Review code and config changes before restarting a live installation. UI changes
also require rebuilding/flashing the relevant screen files; `git pull` alone does
not change the physical screen. Stop the unit before `crm4ui flash`, and start it
again only after the upload completes and the screen has rebooted.

`bash scripts/uninstall.sh` stops/disables and removes only this installer's user
unit. It preserves private config, state, venv, clone and linger. Linger belongs
to the user and may also be needed by other user services; change it separately
only when appropriate. No installer flashes firmware or controls the printer.

References: [systemd service semantics](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html),
[loginctl linger](https://www.freedesktop.org/software/systemd/man/latest/loginctl.html).
