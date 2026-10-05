# CR-M4 screen: file formats and protocol notes

Reverse-engineered from the Creality CR-M4 packages `SW_V1.5.1` (screen V1.2.2) and `SW_V2.0.3_NEW_UI` (screen V2.0.3). Each item is marked **confirmed** (verified, e.g. by byte-identical round trip) or **inferred**.

## Hardware and runtime

- The screen is a **DACAI** 4.3" 800×480 resistive UART HMI. **Confirmed** by bootloader strings (`gDacaiOTA`, "Send commad to Dacai") and `大彩科技` in `22.bin`.
- The runtime is `firmware.zlib`, identical in both packages (md5 `a2d27fe64d475ddfdfefa9ecdfa191e2`). Only `private/` differs between UI versions.
- The UI files follow DWIN DGUS-II conventions (`14.bin` header `DGUS_2`, `config.txt` registers). The mainboard talks DGUS frames: `5A A5 len 82 VP data` (write), page switch by writing `5A 01 00 PP` to VP `0x0084`. Touch events arrive as `5A A5 06 83 VP 01 KEY` (**inferred**, standard DGUS).
- The mainboard is an STM32F401 running Marlin 2.0.9.1. The screen UART is most likely **USART6** (**inferred**; USART1 is the host link).
- `config.txt`: `R1=07; 115200` baud, `R6` / `R7` backlight on/off level, `R8=12C` sleep time.

## `image/N.zbmp`: page backgrounds (confirmed)

| Offset | Content |
|---|---|
| 0 | u16 LE width (480), u16 LE height (800) |
| 4 | `ff 00` + 10 × `00` (identical in every stock file) |
| 16 | zlib stream (level 6) of RGB565 LE pixels |

Pages are stored **rotated 180°** relative to the viewed panel. The page id is the file number.

## `icon/N.zico`: icon libraries (confirmed)

`'ZICO'`, u32 LE `index_len`, then `index_len/16` records `(u16 id, u16 flag=1, u16 w, u16 h, u32 offset, u32 size)` (LE). The data follows: one zlib stream per icon of RGB565 LE pixels; offsets are relative to `8 + index_len`. Icons are in viewing orientation. Black is treated as transparent (**inferred**).

Libraries in V2.0.3:

| Library | Contents |
|---|---|
| 17 | progress bars |
| 18 | small state icons (toggles, mascot) |
| 19, 29 | text labels, 9 languages each |
| 58, 60 | misc |

## `bin/13.bin`: touch areas (confirmed layout; flag meaning unknown)

Records are sorted by page and terminated by `FF FF`. Base record, 16 bytes BE:

| Offset | Field |
|---|---|
| 0 | flags |
| 1 | page |
| 2..10 | x0, y0, x1, y1 |
| 10..12 | page switch on release (`FF00` = none) |
| 12..14 | page while pressed (`FF00` = none) |
| 14..16 | touch code |

| Code | Total length | Fields |
|---|---|---|
| `FE05` / `FD05` return key | 32 | VP at 17..19, key at 20..22 |
| `FE02` increment | 32 | VP 17..19, 20 = inc (1) / dec (0), step 22..24, min 24..26, max 26..28 |
| `FE00` numeric input | 64 | VP 17..19, keyboard page 34..36, min/max i32 at 50..54 / 54..58 |
| other (keyboard keys) | 16 | code = ASCII pair |

Buttons that only switch page are return keys on VP `0x0000`. `FD05` appears on file-list paging buttons; its difference from `FE05` is unknown.

## `bin/14.bin`: display fields (confirmed)

| Offset | Content |
|---|---|
| `0x0000` | `14 'DGUS_2' 10`, u16 BE highest page id, zeros |
| `0x0010` | 4092 index entries: u16 LE count, u16 BE offset; empty pages point at the next free position |
| `0x4000` | 32-byte records grouped by page |
| end | 32 × `FF` |

Record: `[0]=5A [1]=type [2:4]=SP (FFFF none) [4:6]=desc len [6:8]=VP [8:12]=x,y`, then:

| Type | Meaning | Fields |
|---|---|---|
| `0x00` | icon variable | v_min 12, v_max 14, icon_min 16, icon_max 18, library 20 |
| `0x10` | number | colour 12, library 14, font size 15, align 16, int digits 17, dec digits 18, var type 19 |
| `0x11` | text | colour 12, box 14..22, max length 22 |
| `0x20` | trend curve | box 8..16, y centre 16, colour 20, channel 24 |
| `0x26` / `0x08` | print-thumbnail area and its control | **inferred** |

## `bin/22.bin`: initial VP memory (confirmed)

131 076 bytes; VP `v` lives at byte `2v`. Text is GBK, NUL-padded.

## Updating the screen

- **SD card** (V1.2.2 readme): `private/` + `firmware.zlib` in the card root; remove the card after the update.
- **Front USB** (V2.0.3 readme): handled by the Creality bootloader. It looks in `0:/STM32F4_UPDATE/private` and uploads each file over the screen UART with ASCII commands: `$cfgenter#`, `$file,3:<dir>\<name>,<size>,2052,115200#`, data packets, `$reboot#`, `$cfgexit#`. Accepted extensions: `.bin .zico .zbmp .ttf .ini .idx .lua`.
