"""VP addresses, key codes and page ids of the stock CR-M4 screen UI V2.0.3.

Derived from the screen package with ``crm4ui dump`` (see
docs/klipper-mapping.md). Scaled values: ``x10`` / ``x100`` mean the screen
shows the integer divided by 10 / 100.
"""

# ---- pages ----------------------------------------------------------------------
PAGE_BOOT = 0
PAGE_MAIN = 1
PAGE_FILES = (2, 3, 4, 5)          # 6 rows each
PAGE_PAUSE_CONFIRM = 7
PAGE_STOP_CONFIRM = 8
PAGE_PRINT_DONE = 9
PAGE_PRINTING_NOPAUSE = 10
PAGE_PRINTING = 11
PAGE_PAUSED = 12
PAGE_TUNE = 14                     # "Parameter settings" during/outside a print
PAGE_PREPARE = 15
PAGE_PREHEAT_MORE = 17
PAGE_MANUAL = 19
PAGE_SETTINGS = 21
PAGE_AUTOLEVEL = 22
PAGE_NEED_HEAT = 24
PAGE_RELEVEL_CONFIRM = 25
PAGE_MOVE = (29, 30, 31)           # step 10 / 1 / 0.1 mm
PAGE_HOMING = 32
PAGE_LANGUAGE = 33
PAGE_ABOUT = 35
PAGE_KEYPAD = 40
PAGE_LEVELING = 43
PAGE_RUNOUT = 44
PAGE_BUSY = 86
PAGE_FEED = 91
PAGE_NOT_SUPPORTED = 108
PAGE_ERROR = 109
PAGE_ZOFFSET_TUNE = 110
PAGE_PID_MANUAL = 114
PAGE_ZOFFSET_PREPARE = 115
PAGE_FILE_PREVIEW = 119
PAGE_SETTINGS_2 = 121
PAGE_PID_NOZZLE, PAGE_PID_NOZZLE_RUN, PAGE_PID_NOZZLE_DONE = 122, 123, 124
PAGE_PID_BED, PAGE_PID_BED_RUN, PAGE_PID_BED_DONE = 125, 126, 127
PAGE_MACHINE = 45                  # custom page from examples/machine_page
PAGE_HOST_SHUTDOWN, PAGE_HOST_REBOOT = 53, 54

PRINT_FLOW_PAGES = {PAGE_PAUSE_CONFIRM, PAGE_STOP_CONFIRM, PAGE_PRINT_DONE, PAGE_PRINTING_NOPAUSE,
                    PAGE_PRINTING, PAGE_PAUSED, PAGE_TUNE, PAGE_ZOFFSET_TUNE, PAGE_RUNOUT}

# ---- display VPs ------------------------------------------------------------------
VP_LANGUAGE = 0x5247               # 0 zh, 1 en, 2 de, 3 es, 4 fr, 5 it, 6 pt, 7 ru, 8 tr
VP_BOOT_PROGRESS = 0x4200          # 0..100
VP_MASCOT = 0x4227                 # 4 = normal, 5 = dimmed
VP_NOZZLE, VP_NOZZLE_TARGET = 0x7046, 0x7048
VP_BED, VP_BED_TARGET = 0x704A, 0x704C
VP_SPEED = 0x704E                  # %
VP_ZOFFSET = 0x7050                # x100, signed
VP_PROGRESS_BAR = 0x4226           # 0..100
VP_PROGRESS = 0x7052               # %
VP_ELAPSED_H, VP_ELAPSED_M = 0x7054, 0x7056
VP_REMAIN_H, VP_REMAIN_M = 0x7058, 0x705A
VP_POS_X, VP_POS_Y, VP_POS_Z = 0x705C, 0x705E, 0x7060    # x10
VP_FEED_LEN, VP_RETRACT_LEN = 0x7062, 0x7064             # x10 mm
VP_LEVEL_PROGRESS = 0x7066
VP_PID_NOZZLE_TEMP, VP_PID_NOZZLE_CYCLES = 0x7070, 0x7072
VP_PID_BED_TEMP, VP_PID_BED_CYCLES = 0x7074, 0x7076
VP_PID = {'extruder': (0x7000, 0x7002, 0x7004), 'heater_bed': (0x7006, 0x7008, 0x700A)}   # x100; 0x7006/0x700A 32-bit
VP_MAX_ACCEL = (0x7014, 0x7016, 0x7018, 0x701A)          # X Y Z E; all velocity VPs x10 (1 decimal)
VP_MAX_SPEED = (0x701C, 0x701E, 0x7020, 0x7022)
VP_MAX_CORNER = (0x7024, 0x7026, 0x7028)
VP_STEPS = (0x702A, 0x702C, 0x702E, 0x7030)              # x100, 32-bit
VP_TOTAL_HOURS = 0x7132                                  # x10

# toggles (icon variables): value 2 = on, 3 = off
TOGGLE_ON, TOGGLE_OFF = 2, 3
VP_TOGGLE_FAN = 0x4219
VP_TOGGLE_RUNOUT = 0x421A
VP_TOGGLE_SLEEP = 0x421B
VP_TOGGLE_AUTOLEVEL = 0x421C
VP_TOGGLE_MOTORS = 0x421D          # value 10 = on, 11 = off
VP_TOGGLE_VOLUME = 0x4224
VP_TOGGLE_WIFI = 0x4220
VP_SYS_CONFIG = 0x0080              # DGUS system config: 5A 00 00 6C = touch beep on, 64 = off
VP_HOME_OFFSET_Z = 0x707C
VP_LANG_CHECK = tuple(range(0x4229, 0x4232))             # page 120: 1 shows the tick

# presets: (nozzle VP, bed VP)
PRESETS = {'PLA': (0x700C, 0x700E), 'ABS': (0x7010, 0x7012), 'PETG': (0x7032, 0x7034),
           'TPU': (0x7036, 0x7038), 'Nylon': (0x703A, 0x703C), 'PA': (0x703E, 0x7040),
           'Custom': (0x7042, 0x7044)}

# texts: (VP, max bytes)
TXT_FILENAME = (0x3000, 20)
TXT_FILENAME_LONG = (0x4390, 32)
TXT_EST_TIME = (0x3140, 20)
TXT_FILAMENT = (0x314A, 20)
TXT_LAYERS = (0x3154, 20)
TXT_ERROR = (0x3168, 20)
TXT_FILE_ROWS = [(0x300A + 10 * i, 20) for i in range(24)]
VP_FILE_ICONS = [0x4201 + i for i in range(24)]          # 1 = show file icon
TXT_ABOUT = {'model': (0x30FA, 20), 'hw': (0x3104, 20), 'fw': (0x310E, 20), 'size': (0x3122, 20),
             'mac': (0x312C, 20), 'web': (0x3136, 20)}
# custom machine page (examples/machine_page)
TXT_MACHINE_STATE = (0x9010, 40)
TXT_MACHINE_MSG = (0x9040, 40)
TXT_SHUTDOWN_NOTE = (0x9050, 40)

# ---- key VPs (screen -> host) -------------------------------------------------------
K_MAIN = 0x4002        # 1 file, 2 finish(done page), 3 prepare, 4 settings, 5 Print (Home) tab, 6 language ok
K_TUNE = 0x4004        # 1 tune tile, 2 back, 3 fan, 4 autolevel, 5 boot touch, 6 unused, 7 runout, 8 save, 9 sleep
K_STOP = 0x4008        # 0 stop button, F1 yes, F0 no
K_PAUSE = 0x400A       # 0 pause button, F1 yes, F0 no
K_RESUME = 0x400C      # 1 resume, 2 runout yes
K_RESET_CFG = 0x400B   # 0 tile, F1 yes
K_RESTORE_NET = 0x4009  # 0 tile, F1 yes
K_PREHEAT = 0x4030     # 0 back, 1 more, 3 fan, 4 cooldown, 5 PLA, 6 ABS, 7 PETG, 8 TPU, 9 Nylon, 10 PA, 11 custom
K_PREPARE = 0x403E     # 1 autolevel, 2 feed, 3 move, 4 language, 5 about, 6 motors off, 7 feedback, 9 wifi, A usb ok, B not-supported ok
K_BACK = 0x4040        # 0 / 1 back
K_LEVEL = 0x4044       # 0 start, F1 yes, F0 no
K_HOME = 0x4046        # 0..2 step pages, 3 X, 4 Y, 5 all axes, 6 X+Y (stock V2.0.3)
K_EXTRUDE = 0x4056     # 1 retract, 2 feed, 5 need-heat yes, 6 need-heat no
K_FILES = 0x40D2       # 0 back, 1 start (preview), 9 preview back, paging keys handled by the screen
K_FILE_ROW = 0x40D3    # 1..24
K_ADV = 0x4104         # 4 steps/mm, 7 auto-leveling data page, 8 toggle 0x4228, 9 CR-touch, 0 back
K_ADV2 = 0x4105        # 1/2 mesh points, 3..5 CR-touch, 6 volume, 8 home offsets, 9 more preheat
K_PID_NAV = 0x401F
K_PID = 0x410F         # 1 start nozzle, 3 start bed, 2/4 yes (save), 5/6 back
K_LANGUAGE = 0x4248    # 0..8
K_MACHINE = 0x9000     # custom page: 1 e-stop, 2 firmware restart, 3 restart, 4 host reboot, 5 host shutdown, 0 no

LANG_KEY_TO_INDEX = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 7, 8: 8}

# ---- Spoolman tile (examples/spoolman) ---------------------------------------------------------
VP_SPOOL_BADGE = 0x9100            # crm4bridge.spoolman.MATERIALS index
VP_SPOOL_SWATCH = 0x9101           # crm4bridge.spoolman.COLOURS index
TXT_SPOOL_NAME = (0x9110, 28)
TXT_SPOOL_DETAIL = (0x9120, 28)
TXT_SPOOL_SHORT = (0x9130, 22)
TXT_SPOOL_WEIGHT = (0x9140, 8)

# spool picker (page 56, examples/spoolman)
PAGE_SPOOLS = 56
K_SPOOL = 0x9060                   # 0x20 open, 1..6 row, 0x10 / 0x11 prev / next, 0 back
TXT_SPOOL_PAGE = (0x9068, 8)
SPOOL_ROWS = 6
VP_SPOOL_ROW_SWATCH = [0x9201 + i for i in range(SPOOL_ROWS)]     # value = swatch + 1, 0 = empty
VP_SPOOL_ROW_BADGE = [0x9211 + i for i in range(SPOOL_ROWS)]      # value = badge + 1
TXT_SPOOL_ROW_NAME = [(0x9220 + 16 * i, 28) for i in range(SPOOL_ROWS)]
TXT_SPOOL_ROW_DETAIL = [(0x9280 + 16 * i, 28) for i in range(SPOOL_ROWS)]

# fan speed in percent (examples/fan_speed)
VP_FAN_PCT = 0x9070

# Where the "not developed yet" popup's Ok returns to, by the event that opened it:
# (vp, key) or (vp, None) for any value. The screen switches pages locally, so the
# bridge can't know the current page; the page an event comes from is fixed by the UI.
PAGE_TUNE, PAGE_TUNE2, PAGE_ADV = 21, 121, 132
NOT_SUPPORTED_RETURN = {
    (K_ADV, 4): PAGE_TUNE,                                   # Steps-per-mm tile (stock UI)
    (K_ADV, 7): PAGE_ADV, (K_ADV, 8): PAGE_ADV, (K_ADV, 9): PAGE_ADV,
    (K_ADV2, 1): PAGE_ADV, (K_ADV2, 2): PAGE_ADV,            # mesh points (133)
    (K_ADV2, 3): PAGE_ADV, (K_ADV2, 4): PAGE_ADV, (K_ADV2, 5): PAGE_ADV,   # CR-Touch test (136)
    (K_ADV2, 8): PAGE_ADV,
    (0x410C, None): PAGE_ADV,                                # home offsets (140-142)
    (K_PREPARE, 7): PAGE_TUNE2, (K_PREPARE, 9): PAGE_TUNE2,  # Feedback, WiFi
    (K_RESET_CFG, None): PAGE_TUNE2, (K_RESTORE_NET, None): PAGE_TUNE2,
    (K_PID_NAV, 5): PAGE_TUNE,                               # Manual Set PID tab
    (VP_PID_NOZZLE_CYCLES, None): 122, (VP_PID_BED_CYCLES, None): 125,
    (VP_MAX_ACCEL[2], None): 128, (VP_MAX_ACCEL[3], None): 128,
    (VP_MAX_SPEED[2], None): 129, (VP_MAX_SPEED[3], None): 129,
    (VP_MAX_CORNER[2], None): 130,
    (VP_HOME_OFFSET_Z, None): PAGE_ADV,                      # home offsets (140-142)
}
for _vp in VP_PID['extruder'] + VP_PID['heater_bed']:
    NOT_SUPPORTED_RETURN[(_vp, None)] = PAGE_TUNE            # manual PID page (114)
for _vp in VP_STEPS:
    NOT_SUPPORTED_RETURN[(_vp, None)] = PAGE_TUNE            # steps page (131)

# thumbnail picture (crm4bridge.thumbnail): pages that show the 0xC000 picture
THUMB_PREVIEW_PAGES = {119}
THUMB_PRINT_PAGES = {9, 10, 11, 12}
MASCOT_SHOWN, MASCOT_HIDDEN = 4, 0

# ---- screen system VPs (screen firmware RE, stage 2) ---------------------------------------------
VP_CUR_PAGE = 0x0014               # read: current page (refreshed by the screen on each read)
VP_BACKLIGHT = 0x0082              # hi = brightness 0-100, lo = standby brightness 0-100
VP_STANDBY_TIME = 0x0083           # standby delay in 10 ms units
SYS_CONFIG_BASE = 0x60             # VP 0x0081 bits used: 3 = touch beep, 2 = backlight auto-standby
SYS_BEEP, SYS_STANDBY = 0x08, 0x04

# print-progress dim over the thumbnail (type 0x26 field, VP 0x8800, description at SP 0x9000)
VP_DIM_ALPHA = 0x8800
SP_DIM = 0x9000                    # +1 x0, +2 y0, +3 x1, +4 y1
DIM_RECT = (88, 264, 388, 564)
DIM_ALPHA = 0x78                   # stock: ~47 % toward black

# file list rows: description pointers, colour at SP+3 (stock highlights the picked row)
SP_FILE_ROW = [0x6010 + 0x10 * i for i in range(24)]
ROW_COLOR, ROW_COLOR_SELECTED = 0xFFFF, 0xB166     # white; Klipper red #B12F35
