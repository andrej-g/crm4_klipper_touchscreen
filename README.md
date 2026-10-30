# crm4_klipper_touchscreen

Reuse the **Creality CR-M4 stock DACAI touchscreen with Klipper/Moonraker**.

The 4.3-inch resistive serial HMI has its own processor and a DGUS-II-compatible
UI (480×800 portrait coordinates). This project provides:

- **crm4bridge**: Python bridge from Moonraker state/actions to the serial screen.
- **crm4ui**: inspect, customize, rebuild and upload the screen's `private/` UI.
- **Browser emulator and mock Moonraker**: develop/test without printer hardware.

No Creality firmware packages, `private/` projects or runtime `firmware.zlib`
are distributed here. Obtain the appropriate official CR-M4 package separately.
The full custom UI is developed against **V2.0.3 “new UI”**; V1.2.2 is an analysis
reference, not a promise that every custom spec works with that package.

## Install the bridge on a Pi

Use Raspberry Pi OS (64-bit; Lite is sufficient), Python 3.9+ and a configured
UART. The bridge can run on the Klipper host or a separate Pi. Read
[Pi setup and wiring](docs/raspberry-pi.md) before connecting GPIO.

```sh
sudo apt-get update
sudo apt-get install -y git
git clone https://github.com/andrej-g/crm4_klipper_touchscreen.git
cd crm4_klipper_touchscreen
bash scripts/install.sh --install-deps
```

Run as your normal login user. The script creates `.venv` and a **user systemd
service**, preserving existing config. It does not enable/start the unit by
default. On a fresh install edit `~/.config/crm4bridge/crm4bridge.cfg`:

```ini
[bridge]
moonraker = http://PRINTER_IP:7125
screen = serial:/dev/serial0@115200
screen_startup_timeout = 5
dry_run = true
machine_page = true
state_file = ~/.local/state/crm4bridge/state.json
```

Replace the host/device with yours. A separate Pi must address the real Klipper
host rather than localhost. Use `machine_page = false` with the untouched stock
UI. Reboot after adding the user to `dialout`, then power the screen and test:

```sh
.venv/bin/python -m crm4bridge -c ~/.config/crm4bridge/crm4bridge.cfg --dry-run
# Ctrl-C after validation, then:
systemctl --user start crm4bridge
journalctl --user -u crm4bridge -f
```

Dry-run reads state and writes the display, while logging printer actions. After
validation, set `dry_run = false` and restart the unit to enable actual controls.
For boot without login: `systemctl --user enable crm4bridge` and
`sudo loginctl enable-linger "$USER"`.

An empty/malformed screen setting exits with a configuration error. A missing,
unpowered or unresponsive screen fails a bounded read-only startup probe; it
cannot leave a bridge running after a dead link thread. The user service retries
operational failures and becomes ready only when the screen answers.

See [installation, migration, updates and troubleshooting](docs/installation.md)
for options, authentication, failure codes, service lifetime and uninstall.
An existing bench config/venv is not automatically imported into the new service.
For UI tools in a terminal, activate `.venv` with `. .venv/bin/activate`.

## Usage

```sh
STOCK=/path/to/CR-M4_..._V2.0.3_NEW_UI/private

crm4ui verify  $STOCK                       # rebuild unchanged, expect "85 files, 85 identical"
crm4ui dump    $STOCK out/map               # ui_map.json + ui_map.md (pages, buttons, VPs)
crm4ui render  $STOCK out/render            # every page as PNG, English labels, touch/VP overlay
crm4ui export  $STOCK out/assets            # upright PNGs of all backgrounds and icons, for editing
crm4ui build   $STOCK examples/splash/spec.yaml build/splash --changed-only --preview build/splash-prev
```

`build` applies a [spec](docs/spec.md) and writes a new `private/`:

- `--changed-only` writes only the files that differ from stock, for partial updates.
- `--preview` renders the changed pages.

Examples:

- [`examples/splash`](examples/splash): a new boot splash. This is the suggested first hardware test.
- [`examples/recolor_amber`](examples/recolor_amber): the cyan accent becomes amber everywhere.
- [`examples/klipper_branding`](examples/klipper_branding): every "CREALITY" wordmark (main-page header, the 108/109 popup character) redrawn as "KLIPPER" in the screen's own font. The Creality mascot is replaced by a layer-lined Benchy silhouette traced from a source image by `make_boat.py`, and a Klipper-logo splash is rendered from the SVG by `make_splash.py`.
- [`examples/print_page_shortcuts`](examples/print_page_shortcuts): the nozzle, bed, speed and Z-offset tiles on the Print page become tappable (keypad inputs, and a Z-offset page that returns to Print).
- [`examples/keypad_titles`](examples/keypad_titles): the nozzle and bed target inputs open their own copies of the keypad, titled "Nozzle temperature" and "Hot bed temperature" (pages 47 and 48). Every other input keeps the untitled stock keypad.
- [`examples/english_only`](examples/english_only): the screen starts in English and the Language selection tile is removed from the Tune page.
- [`examples/input_limits`](examples/input_limits): the nozzle target on the Tune and Print pages accepts 0–300 °C instead of Creality's 185–300, so 0 turns the heater off.
- [`examples/popup_cleanup`](examples/popup_cleanup): the "not developed yet" and error popups without the Creality mascot, with compact cards; "Ok" instead of "Yes".
- [`examples/unsupported_features`](examples/unsupported_features): Reset configuration, Restore network and CR-Touch testing go straight to the "not developed yet" popup.
- [`examples/spoolman`](examples/spoolman): the active Spoolman spool on the Print page and the printing pages: colour swatch, material badge (PLA, PETG, PLA-M, PLA-CF, PETG-CF, ABS, ASA, TPU, PA, PLA-W), name and remaining filament. Tapping it opens a spool picker that sets the active spool. Icons are drawn by `make_icons.py`.
- [`examples/fan_speed`](examples/fan_speed): the fan tiles on the Tune and Manual pages take a speed in percent (keypad) instead of on/off.
- [`examples/firmware_restart_tile`](examples/firmware_restart_tile): a Firmware restart tile on Tune page 1 (in place of Steps-per-mm), with a Yes/No dialog that returns to the Tune page.
- [`examples/mesh_grid`](examples/mesh_grid): every value on the mesh grid pages (27/28, 134/135) in white.
- [`examples/klipper_ui`](examples/klipper_ui): the full UI for this printer. It includes `klipper_branding`, `print_page_shortcuts`, `keypad_titles`, `english_only`, `input_limits`, `popup_cleanup`, `unsupported_features`, `spoolman`, `machine_page`, `fan_speed`, `firmware_restart_tile` and `mesh_grid`; build this one.
- [`examples/machine_page`](examples/machine_page): a custom page 45 with Klipper restart / firmware restart, host reboot / shutdown (with Yes/No dialogs), E-STOP and the Klipper state. It is reached from the Tune page, where it replaces the WiFi tile. Part of `klipper_ui`.

The example images are generated by `examples/make_assets.py`.

## Emulator and bridge (no hardware needed)

```sh
python -m crm4bridge.mock_moonraker                         # simulated printer (or use your real Moonraker)
python -m crm4ui.emulator $STOCK                            # open http://127.0.0.1:8090
python -m crm4bridge --moonraker http://127.0.0.1:7125 --live
```

Against a real printer, leave out `--live`; the bridge then only logs the commands it would send. Configuration: `crm4bridge.example.cfg`.

## Flashing a build onto the screen

Keep the untouched stock `private/` + `firmware.zlib` on a separate SD card; re-flashing them is the recovery path. **Never modify `firmware.zlib`.**

1. **Screen microSD slot** (DACAI native; the method in Creality's V1.2.2 readme). Copy `private/` and `firmware.zlib` to the root of a FAT32 card (4096-byte clusters). Insert it, power-cycle, and **remove the card when done**, or it updates again on every boot.
2. **Over the screen's serial link** (`crm4ui flash`), the protocol Creality's mainboard bootloader uses (`$cfgenter#`, `$file,…#` + 2052-byte packets, `$reboot#`, `$cfgexit#`). Stop the bridge first; it needs the port.

   ```sh
   crm4ui flash build/klipper --port serial:/dev/ttyAMA0 --dry-run          # list what would be sent
   crm4ui flash build/klipper --port serial:/dev/ttyAMA0                    # everything (see estimated duration)
   crm4ui flash build/klipper --port serial:/dev/ttyAMA0 --changed-from build/klipper.prev   # only what changed
   crm4ui flash build/klipper --port serial:/dev/ttyAMA0 --baud 921600      # faster data phase (untested)
   ```

   `--baud` (230400, 460800, 921600) puts that speed in each `$file` command; the screen switches to it for that file's packets and back to 115200 afterwards. The commands themselves always run at 115200. If it fails, run again without `--baud`.

   About 10 KiB/s. From the screen firmware: each file is overwritten as a whole, nothing else is touched or deleted, and order does not matter, so a failed or partial update can simply be re-run. Serial UI upload at 115200 has been tested on a real CR-M4 screen; higher data-phase baud rates remain unverified. The emulator accepts it too (`--port tcp:127.0.0.1:7901`): received files land in `<private>.ota` and it reboots into them.
3. **Front USB port**, through Creality's mainboard bootloader (`STM32F4_UPDATE/private` on a USB stick). Untested under Klipper.

## Documentation

- [docs/formats.md](docs/formats.md): file formats and protocol notes
- [docs/spec.md](docs/spec.md): build spec reference
- [docs/bridge.md](docs/bridge.md): bridge, emulator, development loop, open assumptions
- [docs/klipper-mapping.md](docs/klipper-mapping.md): which screen element maps to what in Klipper

## Tests

```sh
python3 -m unittest discover -s tests                                # format tests, no Creality files needed
CRM4_STOCK_PRIVATE=$STOCK python3 -m unittest discover -s tests      # plus round-trip/build tests on the real package
```

## License and third-party material

Original project code is licensed under [MIT](LICENSE). Creality firmware and
third-party logos/artwork retain their respective owners' rights; the MIT grant
does not relicense them. Klipper/Creality names identify compatible projects and
hardware; this is an independent integration. Review the provenance/terms of
artwork you redistribute or publish in your own UI build.

Local config, API keys, state, logs and stock/build outputs belong outside Git.
Before making an existing repository public, review its **history** as well as
the current files: removing private values now does not erase older commits.
