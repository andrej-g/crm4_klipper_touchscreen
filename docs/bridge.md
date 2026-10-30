# Bridge and emulator

Production setup: [installation and user service](installation.md), [Pi configuration](raspberry-pi.md).
Hardware-tested features and remaining validation are summarized in the [README](../README.md).


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
python -m crm4bridge --moonraker http://printer.local:7125
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
- **Failed commands:** a command Moonraker rejects shows its error on page 109 for 8 s (the page has no button) and then returns to the page it was started from; leveling and PID return to their start pages instead of the "in progress" ones.
- **Touches:** see `KEYS` / `VALUES` in `src/crm4bridge/bridge.py`. Highlights:
  - **Files:** the newest 24 files, then a preview with estimated time, filament and layers, then Start.
  - **Print control:** pause, resume and cancel, with the stock confirm dialogs.
  - **Temperatures and speed:** keypad input for temperatures and speed.
  - **Preheat:** the PLA / ABS / PETG / TPU / Nylon / PA / custom presets, and cooldown.
  - **Move page:** jog via the screen's own increment buttons (refused when the axis isn't homed or a print is active), homing (X, Y, all axes, X+Y as in the stock V2.0.3 firmware), motors off.
  - **Filament:** feed / retract with lengths remembered between sessions; when the nozzle is too cold, the "temperature insufficient" popup.
  - **Tune:** Z-offset babystepping (`SET_GCODE_OFFSET`), the runout sensor toggle, the `per_print_mesh` toggle, fan speed in % (`M106 S…` / `M107`; with the `fan_speed` UI, otherwise on/off).
  - **Bed mesh:** `mesh_gcode` from the auto-leveling page, then the **mesh grid** (page 28) as stock: the loaded mesh (`bed_mesh.mesh_matrix`, Klipper's interpolated surface; `probed_matrix` as fallback) is sampled at the 5×5 positions that span `mesh_min`..`mesh_max` (corners = mesh corners, bilinear in between) and written as mm×1000 to VP `0x7100 + 2·i` in the UI's serpentine field order: `0x7100` bottom-left = front-left of the bed, `0x7108` bottom-right, `0x710A` right end of the next row, ... `0x7130` top-right (`crm4bridge/mesh.py`). Advanced → "auto leveling data" shows the same grid on page 135. With no mesh loaded, "No bed mesh loaded" appears on the error page for 3 s and the previous page returns. `mesh_grid = 4` uses the 4×4 pages 27/134 of the same layout. A failed `mesh_gcode` shows its error for 8 s and returns to the auto-leveling page. The `klipper_ui` build draws all grid values in white (`examples/mesh_grid`; stock mixes white, light grey and, on the 4×4 pages, dark grey). Display only; the bridge reads `bed_mesh` once per request, never while polling.
  - **PID:** autotune for nozzle and bed (`PID_CALIBRATE`, then `SAVE_CONFIG` on Yes). The Temp PID tile opens the nozzle autotune page; save / back return to the autotune page of the same heater. **Temperature graph:** while the autotune runs the bridge feeds the page's curve as the stock firmware does: both channels of the heater are cleared (VP `0x0301`/`0x0303` nozzle, `0x0305`/`0x0307` bed = 0), then every `curve_interval` (1 s) one curve-buffer write per channel with one value, `5A A5 0B 82 03 10 5A A5 01 00 <ch> 01 <current>`. Stock sends two values, `... <ch> 02 <previous> <current>`, so every point appears twice and the 387 px graph holds only ~3 minutes; with one value it holds ~6.5 minutes (channel 0 nozzle temperature, 1 the autotune target; 2/3 for the bed), with the bytes `curve_byte_gap` (800 µs) apart on a serial link (`crm4bridge/curve.py`). The stream stops when `PID_CALIBRATE` returns, fails (its error shows for 8 s, then the autotune page), or the screen leaves the "in progress" page; save / back clear the channels, as stock.
  - **Velocity limits:** X/Y max acceleration, speed and corner velocity (`SET_VELOCITY_LIMIT`). The screen fields have one decimal, so values are sent ×10 (16-bit: at most 6553.5) and keypad input is divided by 10.
  - **Thumbnails:** the file's largest Moonraker thumbnail, re-encoded as a 300×300 baseline JPEG and written to VP `0xC000` the stock way (240-byte chunks to `0xC002+`, 25 ms apart, then `5A A5 <len>` to `0xC000`). Shown on the file preview (119) and the printing pages (9–12); the Benchy (VP `0x4227`) is hidden there while a picture is loaded. About 1–2 s per picture; `thumbnails = false` turns it off.
  - **Volume and Auto Sleep:** the ADV.SET volume toggle switches the touch beep, the Tune Auto Sleep toggle the backlight auto-standby: VP `0x0080` = `5A 00 00 XX`, XX = `0x60` + `0x08` (beep) + `0x04` (standby); stock writes `6C` / `64`. Both are remembered in the state file.
  - **Backlight:** optional `brightness` and `standby_brightness` (0–100, VP `0x0082`) and `standby_timeout` (seconds, VP `0x0083` in 10 ms units); left empty, the screen keeps its own values.
  - **Current page:** every poll reads VP `0x0014` (the page the screen shows), so pages the screen changes by itself (return keys, keypads) are tracked: the popup Ok and the Benchy/thumbnail follow the real page. A reply to a read that was sent before the bridge's own last page switch describes the old page and is ignored (`page_seq`), so it can't undo a switch the bridge just made (e.g. stop the PID graph right after Start).
  - **Print progress dim:** on the printing pages the not-yet-printed top of the thumbnail is dimmed, as stock: the 0x26 field's description pointer (SP `0x9001`–`0x9004` = rectangle) and VP `0x8800` = alpha `0x78`.
  - **Selected file:** the picked file row is drawn in Klipper red (its text colour at SP `0x6010 + 0x10·i + 3`).
  - **Language:** fixed by `language` in the config (English by default). Picks on the screen's language page are ignored and undone.
  - **Spoolman:** the active spool (`/server/spoolman/status`, then `GET /v1/spool/<id>` through `/server/spoolman/proxy`) every `spoolman_interval` seconds: material badge, nearest colour swatch, name, remaining weight / length and vendor. "No active spool", "Spoolman offline" and "Spoolman not available" (no `[spoolman]` in Moonraker) are shown in the name line. `spoolman = false` turns it off. Badges: PLA, PETG, PLA-M (material or name says matte), PLA-CF and PETG-CF (CF or carbon), PLA-W (wood or bamboo), ABS, ASA, TPU (also TPE / flex) and PA (also nylon); any other material gets no badge and its name in front of the spool name. See `crm4bridge/spoolman.py`. Tapping the tile opens the spool picker (active spool first, then most recently used; six per page); a tap on a spool sets it active (`POST /server/spoolman/spool_id`) and returns to the page it came from.
  - **Machine page (custom, Tune 2/2 in place of WiFi):** Klipper `RESTART` and `FIRMWARE_RESTART`, host reboot and shutdown (`/machine/reboot`, `/machine/shutdown`), each after a Yes/No dialog, and an immediate EMERGENCY STOP. Firmware restart is also on Tune page 1 (`examples/firmware_restart_tile`). Host actions are refused while a print is running or paused. With `shutdown_plug` set (a Tasmota plug that powers the printer and the Pi), the bridge first sends the plug `Backlog Delay <n>; Power1 Off`, so the plug switches itself off `shutdown_plug_delay` seconds after the Pi has halted; if the plug can't be reached, the host is not shut down.
  - **Everything else** shows the "not developed yet" popup (its Ok returns to the page the tap came from, `ui.NOT_SUPPORTED_RETURN`): Creality Wi-Fi/cloud, restore network, reset configuration, feedback, CR-Touch tests, improved accuracy, power-loss recovery, home offsets (X/Y/Z), manual PID and PID cycle counts, steps/mm, and Z/E velocity limits. With the `klipper_ui` build these tiles no longer open their own pages first (`examples/unsupported_features`).

## Protocol evidence and remaining hardware checks

Most of these are now confirmed from the stock mainboard firmware (V1.5.1 and V2.0.3, see the project notes "CR-M4 Stock Touchscreen - Mainboard Firmware RE"); what's left needs the real screen.

| Assumption | Status |
|---|---|
| No CRC; no write acks | Confirmed on both sides: `config.txt` `R2=6C` has CRC (bit 4) off and register RC (write ack) is unset, so the screen sends no `4F 4B`. The emulator matches (`--ack` turns acks on). |
| Touch / keypad / increment events arrive as `83 VP 01 value` | Confirmed; 32-bit fields (PID `0x7006`/`0x700A`, steps) send `83 VP 02 hi lo`, handled. |
| Page switch through VP `0x0084` = `5A 01 00 PP` | Confirmed. |
| Toggle icons 2 = on, 3 = off; motors 10 = on, 11 = off | Confirmed. |
| Start-up handshake | None in the stock firmware: it waits 500 ms after power-up, then writes. |
| UART: 115200 8N1 on the mainboard's USART6 (PC6 TX / PC7 RX), 3.3 V | Confirmed from the firmware; TX measured 3.3 V on the tested unit; verify other board revisions before wiring. |
| Thumbnail JPEG at `0xC000`, displayed by the screen | Format from the firmware; display on the real screen untested. |
| Print-progress dim over the thumbnail (`0x8800`, SP `0x9001–0x9004`) | Driven (see above); display on the real screen untested. |
| Mesh grid: VP `0x7100 + 2i`, mm×1000 as signed 16-bit, serpentine from the bottom-left | Write order and scale from the V2.0.3 firmware; the field layout (2.3 digits, `var_type` 0, serpentine positions) from the stock `14.bin`. Sign handling of negative values on the real screen untested. |
| PID graph: curve-buffer write `0x0310` = `5A A5 01 00 <ch> 02 <old> <new>`, cleared through `0x0301 + 2·ch` = 0 | Frame and timing from the V2.0.3 firmware; ring buffers and registers from the screen firmware. Whether the real screen needs the 800 µs byte spacing (and whether pyserial achieves it) is untested; `curve_byte_gap = 0` turns it off. The curve field's scale decoding (Y_Central / VD_Central / Mul_Y / Dis_HOR) is inferred from the DGUS-II layout and only matters for the emulator. |
| Font sizes and number alignment in the emulator are approximate | |

## Hardware test checklist: mesh grid and PID graph

First time on the real screen (bridge in `--live` against the real Moonraker, or dry-run plus a loaded mesh; nothing here heats or moves anything except the autotune itself):

1. **Grid, static.** With a mesh loaded (`BED_MESH_PROFILE LOAD=default`), tap Advanced → "auto leveling data". Page 135 must show 25 numbers with 3 decimals. Compare the four corners and the centre with `BED_MESH_OUTPUT` / Mainsail's mesh view: bottom-left of the screen = front-left of the bed (mesh_min), top-right = back-right. Check that a negative value shows a minus sign (if the screen shows 65.xxx instead, the field is unsigned and `mesh.encode` must offset).
2. **Grid, after levelling.** Prepare → Auto leveling → Start → Yes. After `mesh_gcode` the screen must switch to page 28 with the fresh values; its back arrow returns to Prepare by itself.
3. **No mesh.** `BED_MESH_CLEAR`, then "auto leveling data": the error page with "No bed mesh loaded" for 3 s, then back to the Advanced page.
4. **PID graph.** Set a nozzle autotune temperature, Start. On page 123 both traces must advance from the left, one point (pixel) per second: the yellow trace following the temperature, the red one (cyan on a stock UI) flat at the target. If the traces advance two pixels per second, the screen does not take a one-value write the way the emulator assumes: report it (the stock two-value form is `curve.write_frame(ch, previous, current)`). If the traces stay empty: try `curve_byte_gap = 0` (no pacing) and, failing that, a larger gap (the stock spacing is ~800 µs; pyserial on the Pi cannot guarantee it); use the emulator log format to compare against the stock frame bytes. If the traces look right but the curve is drawn upside down or clipped, the screen's Y mapping differs from the emulator's assumption; the bridge frame is unaffected.
5. **End of autotune.** When Klipper finishes, page 124 must appear with the final curve still visible; Yes (SAVE_CONFIG) or back must clear it (channels 0/1).
6. **Bed.** Same with the bed autotune (page 126/127, channels 2/3).

Record the result of each step, with the bridge log, in the project's Engineering Log.


## Startup readiness

Screen specs are validated before workers start. The link must answer a read of VP 0x0014 within `screen_startup_timeout` (default 5 s); opening a UART without a powered screen is insufficient. Failures exit in the main process. See [failure codes and retry policy](installation.md#startup-checks-and-failure-behavior). This is a startup check, not a continuous UART power-loss watchdog.
