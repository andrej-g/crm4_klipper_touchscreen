# Bridge and emulator

```
 browser ──http──► crm4ui.emulator ◄──tcp:7901 (DGUS frames)──► crm4bridge ──http──► Moonraker ──► Klipper
                   (renders the stock UI,                       (state → VPs,
                    clicks = touches)                            touches → G-code)
```

On the printer the emulator is replaced by the real screen on a serial port (`screen = serial:/dev/ttyAMA0@115200`). Nothing else changes.

## Development loop (no printer or screen needed)

```sh
STOCK=/path/to/CR-M4_..._V2.0.3_NEW_UI/private
python -m crm4bridge.mock_moonraker --print-seconds 300          # simulated printer on :7125
python -m crm4ui.emulator $STOCK                                  # http://127.0.0.1:8090
python -m crm4bridge --moonraker http://127.0.0.1:7125 --live     # live against the mock
```

Against the real printer (VPN or LAN), start in the default **dry-run** mode:

```sh
python -m crm4bridge --moonraker http://klipper.lan.gustin.si:7125
```

In dry-run the bridge reads everything (temperatures, files, metadata, print state) but only **logs** commands (`DRY-RUN: SET_HEATER_TEMPERATURE …`). `--live` sends them. Use a config file for the rest (`crm4bridge.example.cfg`).

The emulator can also run a built UI (`crm4ui build <stock> examples/klipper_ui/spec.yaml build/klipper` → `python -m crm4ui.emulator build/x`; untouched files must be present, so build without `--changed-only`). Use this to preview custom pages, for example `examples/machine_page` together with `machine_page = true`.

## Logs for troubleshooting

```sh
python -m crm4ui.emulator build/klipper --log logs/emulator.log
python -m crm4bridge --moonraker http://127.0.0.1:7125 --live --log-file logs/bridge.log
```

The emulator log has every touch (with coordinates), every page change and every frame in both directions, each line tagged with the page shown at the time. The bridge log, always at debug level, has state changes, every screen event, and the commands it sends (or would send).

## What the bridge does

- **Startup / reconnect:**
  - language and other static values;
  - About texts (Klipper version, host name, Mainsail URL);
  - presets;
  - full repaint every 30 s, in case the screen rebooted.
- **Status (every `poll_interval`):**
  - temperatures and targets, speed %, Z offset, positions;
  - velocity limits;
  - fan, runout and auto-level toggles;
  - print file, progress and elapsed / remaining time;
  - Klippy state. Not ready → boot page with an animated bar; shutdown / error → page 109 with the reason.
- **Page changes on print state:** printing → 11, paused → 12 (runout → 44), complete → 9, cancelled → 1, error → 109.
- **Touches:** see `KEYS` / `VALUES` in `src/crm4bridge/bridge.py`. Highlights:
  - **Files:** the newest 24 files, then a preview with estimated time, filament and layers, then Start.
  - **Print control:** pause, resume and cancel, with the stock confirm dialogs.
  - **Temperatures and speed:** keypad input for temperatures and speed.
  - **Preheat:** the PLA / ABS / PETG / TPU / Nylon / PA / custom presets, and cooldown.
  - **Move page:** jog via the screen's own increment buttons (refused when the axis isn't homed or a print is active), homing, motors off.
  - **Filament:** feed / retract with lengths remembered between sessions; when the nozzle is too cold, the "temperature insufficient" popup.
  - **Tune:** Z-offset babystepping (`SET_GCODE_OFFSET`), the runout sensor toggle, the `per_print_mesh` toggle, fan on/off.
  - **Bed mesh:** `mesh_gcode` from the auto-leveling page.
  - **PID:** autotune for nozzle and bed (`PID_CALIBRATE`, then `SAVE_CONFIG` on Yes).
  - **Velocity limits:** X/Y max acceleration, speed and corner velocity (`SET_VELOCITY_LIMIT`).
  - **Language:** fixed by `language` in the config (English by default). Picks on the screen's language page are ignored and undone.
  - **Machine page (custom):** E-STOP, `FIRMWARE_RESTART`, `RESTART`.
  - **Everything else** (Creality Wi-Fi/cloud, restore network, reset configuration, CR-Touch tests, power-loss recovery, home offsets, manual PID, steps/mm) shows the "not developed yet" popup.

## Assumptions to confirm on the real screen

| Assumption | Where |
|---|---|
| No CRC; DGUS-II write acks `5A A5 03 82 4F 4B` (the bridge ignores acks either way) | `crm4ui/dgus.py`, emulator `--no-ack` |
| Touch / keypad / increment events arrive as `83 VP 01 value` | `ScreenSim.touch`, `Bridge.handle_frame` |
| Page switch through VP `0x0084` = `5A 01 00 PP` (seen as a constant in the Creality firmware) | `dgus.set_page` |
| Toggle icons: 2 = on, 3 = off; motors icon 10 = on, 11 = off | `crm4bridge/ui.py` |
| Font sizes and number alignment in the emulator are approximate | `ScreenSim._draw_var` |
| Start-up handshake: unknown; the bridge just repaints on connect and every 30 s | |
| Thumbnails (`0x8800`), the PID temperature graph and the mesh grid are not driven yet | |
