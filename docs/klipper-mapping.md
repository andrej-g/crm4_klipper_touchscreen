# CR-M4 stock touchscreen: what maps to Klipper (2026-10-04)

> Copied from the 3D Printer project notes. References to `ui_map_screen_v2.0.3/` and `page_NNN_render.png` mean the output of `crm4ui dump` / `crm4ui render` on the stock package. The bridge implementation status is in [bridge.md](bridge.md).

Basis: the screen V2.0.3 UI map (`ui_map_screen_v2.0.3/`). Page renders with English labels and the touch/VP overlay are in `page_NNN_render.png` (`tools/crm4_render_pages.py`). The Klipper side is the current `Klipper/Current/printer.cfg` (eddy-ng probe, 50×50 rapid mesh, filament switch sensor, `PRINT_START` with `per_print_mesh`, Mainsail macros).

Architecture assumed: a Python service on the Pi. It talks to the screen over UART (DGUS II frames) and to Klipper through Moonraker's websocket (status subscriptions and `printer.gcode.script` / `printer.print.*`). The screen keeps its stock UI. Page navigation that the UI does by itself (`page_next` in the map) needs no bridge code. Everything else does.

Legend: **Map** = direct Klipper equivalent. **Adapt** = works with a translation or reduced meaning. **Local** = handled by the bridge or screen, no Klipper call. **Ignore** = no sensible Klipper meaning (leave inert, or show page 108 "This feature has not been developed yet").

Value encoding: numeric VPs are 16-bit integers with implied decimals (`dec_digits` in the map). For example, Z offset `0x7050` is ×100 and positions `0x705C/5E/60` are ×10. Numeric entry boxes (`data_input`) send the new value; `inc`/`dec` arrows change the VP on the screen and report the result.

## 1. Core: map these first

| Page(s) | Element | VP / key | Klipper / Moonraker | Class |
|---|---|---|---|---|
| 0 boot | progress bar | `0x4200` | Klippy startup state (`server.info` → `klippy_state`); jump to page 1 when ready | Adapt |
| 1, 9–12, 14, 19 | nozzle actual / target | `0x7046` / `0x7048` | `extruder.temperature` / `.target`; input → `SET_HEATER_TEMPERATURE HEATER=extruder TARGET=` | Map |
| same | bed actual / target | `0x704A` / `0x704C` | `heater_bed.temperature` / `.target`; input → `SET_HEATER_TEMPERATURE HEATER=heater_bed` | Map |
| 1, 9–12, 14 | speed % | `0x704E` | `gcode_move.speed_factor`×100; input → `M220 S` | Map |
| 1, 9–12 | Z offset | `0x7050` (×100) | `gcode_move.homing_origin[2]` | Map (display) |
| 1 | File / Prepare / Tune | `0x4002` 1/3/4 | navigation (Prepare = page 15) | Local |
| 2–5 | file list, 4 pages × 6 | names `0x300A`… (step 0x0A, 20 chars); rows `0x40D3` 1–24; page arrows `0x40D2` | `server.files.list` (gcodes, newest first). The bridge pages virtually past 24 files and truncates names to 20 chars. | Adapt |
| 119 | file preview | `0x3000` name, `0x4390` long name (32), `0x3140` est. time, `0x314A` filament, `0x3154` layers, thumbnail `0xC000` | `server.files.metadata` (`estimated_time`, `filament_total`, `layer_count`, thumbnails) | Map. Thumbnail is Adapt (format unconfirmed). |
| 119 | Start | `0x40D2` 9 | `printer.print.start filename=` | Map |
| 9–12 printing / paused / finished | filename, progress, times | `0x3000`; `0x4226` bar + `0x7052` %; `0x7054:0x7056` elapsed h:m; `0x7058:0x705A` remaining h:m | `print_stats.filename`, `display_status.progress` (or `virtual_sdcard.progress`), `print_stats.print_duration`, remaining from metadata estimate × (1 − progress) or file-relative | Map |
| 9–12 | thumbnail area | `0x8800` (+`0xC000`) | G-code thumbnail from Moonraker | Adapt (write format unconfirmed) |
| 9–12 | page choice | page 11 printing, 12 paused, 9 finished, 10 printing with pause disabled | `print_stats.state` (`printing` / `paused` / `complete` / `cancelled` / `error`) | Map |
| 7 / 11 | Pause → confirm | `0x400A` F1/F0 | `PAUSE` (Mainsail macro) | Map |
| 12 | Resume | | `RESUME` | Map |
| 8 | Stop → confirm | `0x4008` F1/F0 | `CANCEL_PRINT` | Map |
| 14 (tune) | nozzle / bed / speed inputs | as above | as above | Map |
| 14 | fan toggle | `0x4004` 3, icon `0x4219` | `fan.speed`; toggle → `M106 S255` / `M107` (on/off only) | Adapt |
| 14 | runout sensor toggle | `0x4004` 7, icon `0x421A` | `SET_FILAMENT_SENSOR SENSOR=filament_sensor ENABLE=0/1`; state from `filament_switch_sensor filament_sensor.enabled` | Map |
| 14 | "Print auto leveling" toggle | `0x4004` 4, icon `0x421C` | your `per_print_mesh` variable used by `PRINT_START` (via `SET_GCODE_VARIABLE` or `save_variables`) | Adapt (good fit) |
| 14 / 15 → 110 / 115 | Z-offset page | `0x7050` inc/dec (0.01 steps) | `SET_GCODE_OFFSET Z_ADJUST=±0.01 MOVE=1` (babystep). Not persisted; saving to eddy-ng (`tap_adjust_z`) stays a deliberate manual step. | Adapt |
| 15 Prepare | Move / Feed-Return / Manual / Auto-level | `0x403E` 3/2/1, `0x4030` 2 | navigation | Local |
| 29–31 Move | X/Y/Z position (×10) | `0x705C/5E/60` | `gcode_move.gcode_position` (or `toolhead.position`) | Map |
| 29–31 | arrows (inc/dec) | `0x705C/5E/60` inc/dec | screen reports the new absolute value → `G90` + `G1 X/Y/Z… F…` (check `toolhead.homed_axes` first) | Map |
| 29–31 | step 0.1 / 1 / 10 | `0x4046`, pages 29/30/31 | sets the increment (screen-side) | Local |
| 29–31 | home X / Y / Z / all | `0x4046` 3/4/5/6 | `G28 X` / `G28 Y` / `G28 Z` / `G28`. Z homing goes through your `homing_override`. | Map |
| 29–31 | motors off | `0x403E` 6, icon `0x421D` | `M84` | Map |
| 91 Feed/Return | lengths (×10) | `0x7062` / `0x7064` | stored by the bridge | Local |
| 91 | Feed / Retract | `0x4056` 2 / 1 | `M83` + `G1 E±len F…`. Below `min_extrude_temp`, show page 24 ("temperature insufficient"). Yes there → heat to a preset. | Map |
| 19 Manual | PLA / ABS preheat | `0x4030` 5/6; values `0x700C/0E`, `0x7010/12` | `SET_HEATER_TEMPERATURE` with stored preset values | Map |
| 17 / 139 | more presets (PETG/TPU/Nylon/PA/custom) | `0x4030` 7–11; values `0x7032…0x7044` | same; the presets are kept by the bridge (Moonraker DB or a JSON file), seeded from your KlipperScreen presets | Map |
| 19 | fan toggle / Cooldown | `0x4030` 3 / 4 | `M106`/`M107`; `TURN_OFF_HEATERS` | Map |
| 22 / 43 | Auto-leveling start | `0x4044` 0 → page 25 confirm | `BED_MESH_CALIBRATE` (your eddy-ng rapid scan or wrapper); page 43 while running, page 32 during homing. `0x7066` = progress or point counter. | Adapt |
| 27/28, 134/135 | mesh value grids 4×4 / 5×5 | `0x7100…0x711E` / `0x7100…0x7130` (`0x7100`-based, ×100?) | `bed_mesh.probed_matrix` / `mesh_matrix`, down-sampled from 50×50 to 4×4 or 5×5 | Adapt (display only) |
| 44 | filament runout popup | `0x400C` 2 / `0x4008` 0 | shown when the runout sensor pauses (`print_stats.state=paused` + sensor `filament_detected=false`). Yes → page 91; No → `CANCEL_PRINT`. | Map |
| 86 / 32 / 43 | "Processing / homing / leveling, please wait" | | shown while a long command runs (`printer.gcode.script` pending, `idle_timeout.state=Printing` outside a job) | Local |
| 109 | error popup with text | `0x3168` (20 chars) | Klippy `shutdown` / `error` state message, `gcode_response` `!!` lines | Adapt (20-char limit) |
| 21 / 121 → 35 | About fields | `0x30FA` model, `0x3104` H/W, `0x310E` F/W, `0x3118` screen ver, `0x3122` size, `0x312C` "MAC", `0x3136` "website", `0x7132` total print time | F/W ← Klipper version; total time ← `server.history.totals`; repurpose MAC → Pi IP, website → Mainsail URL | Adapt |
| 33 / 120 | language | `0x4248` 0–8 → write `0x5247` | screen-side; the bridge just echoes the choice and stores it | Local |

## 2. Tune/settings pages: partial mapping

| Page | Element | Klipper | Class |
|---|---|---|---|
| 21 → 114 / 122–127 Temp PID | auto PID nozzle / bed: target `0x7070` / `0x7074`, Start | `PID_CALIBRATE HEATER=extruder TARGET=` / `HEATER=heater_bed`, then `SAVE_CONFIG` on confirm (restarts Klipper; warn first). Pages 123/126 while running, 124/127 done. | Map |
| 122–127 | cycle count `0x7072` / `0x7076` | Klipper's `PID_CALIBRATE` has no cycle parameter | Ignore (show fixed) |
| 122–127 | live temp curve (type `0x20`, 2 channels) | feed `extruder` / `heater_bed` temperature and target | Adapt (curve-buffer write format still to confirm) |
| 114 manual PID | P/I/D for nozzle `0x7000/02/04`, bed `0x7006/08/0A` | read from `configfile.settings.<heater>.pid_kp/ki/kd`. Mainline Klipper has no runtime PID setter. | Display only. Ignore edits. |
| 128 Max acceleration X/Y/Z/E | `0x7014/16/18/1A` | X/Y → `max_accel` (one value: `SET_VELOCITY_LIMIT ACCEL=`). Z → `max_z_accel` and E: config only. | Adapt X/Y; Z/E display only |
| 129 Max speed X/Y/Z/E | `0x701C/1E/20/22` | X/Y → `max_velocity` (`SET_VELOCITY_LIMIT VELOCITY=`). Z → `max_z_velocity` (config). E has no equivalent. | Adapt X/Y; Z display; E ignore |
| 130 Max corner (jerk) X/Y/Z | `0x7024/26/28` | X/Y → `square_corner_velocity` (`SET_VELOCITY_LIMIT SQUARE_CORNER_VELOCITY=`) | Adapt X/Y; Z ignore |
| 131 Steps-per-mm X/Y/Z/E | `0x702A/2C/2E/30` | computed from `rotation_distance`, microsteps and full steps; not runtime-editable | Display only |
| 116 / 117 / 132 | PLA / ABS preset editing | bridge preset store | Local |
| 132 → 133 | 4×4 / 5×5 leveling points | your mesh is a 50×50 rapid scan | Ignore (or treat as "mesh view resolution") |
| 132 | "Improved accuracy" toggle (`0x4104` 8) | Creality-specific | Ignore |
| 132 → 136 | CR-Touch testing (protrude / retract / auto) | BLTouch commands; you run an Eddy probe | Ignore (page 108) |
| 132 → 140–142 | set home offsets X/Y (`0x7078/7A`) | no runtime home offset. `SET_GCODE_OFFSET X/Y` is not persistent; the real fix is `position_endstop` in config. | Ignore |
| 132 | volume toggle (`0x4105` 6, icon `0x4224`) | screen buzzer only | Local |
| 14 | "Auto sleep" toggle (`0x4004` 9, icon `0x421B`) | screen backlight sleep (`config.txt` R8 time / DGUS backlight register). Could also drive `idle_timeout` but needn't. | Local |
| 121 | Reset configuration (111) | Creality EEPROM reset | Ignore, or repurpose (see §4) |
| 121 | WiFi toggle, Restore network (112) | Creality Box/WiFi module | Ignore, or repurpose |
| 121 → 143 | Feedback (QR code) | static Creality QR | Ignore (could be redrawn as a Mainsail-URL QR in a later UI edit) |
| 36 | "Resume previous print?" (power-loss recovery) | Klipper has no built-in power-loss resume | Ignore (never show) |
| 118 | "USB flash drive removed" | Klipper prints from the Pi's `virtual_sdcard` | Ignore |
| 26 | "min time to select this leveling point" | Creality manual-leveling flow | Ignore |
| 108 | "This feature has not been developed yet" | | Local, as the catch-all for ignored buttons |

## 3. Klipper features the stock UI cannot reach (without UI edits)

- **Emergency stop** (`M112`) and **FIRMWARE_RESTART / RESTART**. There is no button for them. This is the most important gap.
- Klippy state beyond a 20-character error line: shutdown reason, MCU disconnects. Relevant to your ongoing MCU-reset issue; the bridge should at least jump to page 109 with a short reason.
- Macros: `CLEAN_NOZZLE`, `SCREWS_TILT_CALCULATE`, `SET_PAUSE_AT_LAYER`, input-shaper / resonance tests, `LOAD_MESH_FOR_TEMP`.
- Second probe workflows (eddy-ng tap calibration, `tap_adjust_z` saving), mesh profile selection.
- Exclude object, console, job queue, history, webcam.
- Power device (`output_pin power`, PD0).

Mainsail / Mobileraker remain the tool for these. The screen covers day-to-day operation: heat, move, load, start, monitor, pause, cancel.

## 4. Optional phase 2: repurposing via UI edits

The labels are images in icon library 19, with 9 languages per label. The formats are understood (`crm4_dgus_dump.py`, `crm4_render_pages.py`), so some dead tiles could be relabelled without new touch logic:

- Tune 2/2 page (121): **WiFi → "E-STOP"** (with a confirm page reusing page 8's layout), **Restore network → "Firmware restart"**, **Reset configuration → "Restart Klipper"**, **Feedback → "Macros"**. A simple macro list could reuse the file-list pages 2–5 (24 slots).
- ADV.SET (132): **CR-Touch testing → "Clean nozzle"**, **Improved accuracy → "Screws tilt"**.
- Leave Creality's page structure intact. Only replace the label icons, and the QR image on page 143.

This needs the screen upload path (Creality bootloader from USB, or the `$cfgenter#` protocol from the Pi) to be proven first.

## 5. Bridge implementation notes

- Subscribe in Moonraker to `extruder`, `heater_bed`, `fan`, `gcode_move`, `toolhead`, `print_stats`, `display_status`, `virtual_sdcard`, `idle_timeout`, `filament_switch_sensor filament_sensor`, `bed_mesh`, `webhooks`. Push only changed VPs. Temperatures at 1 Hz are plenty.
- Track the current page yourself. The screen switches pages locally for `page_next` buttons, and the bridge forces pages via VP `0x0084` for state changes (print started / paused / finished, errors).
- Treat `0xFD05` touch entries like `0xFE05` return keys until proven otherwise.
- Gate motion and extrusion commands on `homed_axes`, `min_extrude_temp` and `print_stats.state`. Refuse moves while printing.
- Prefer V2.0.3 (map extracted, nicer UI). V1.2.2 is the fallback: its VPs follow Creality's public `lcd_rts` source if a meaning is unclear.
