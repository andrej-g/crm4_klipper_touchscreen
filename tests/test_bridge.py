"""Bridge logic against fake Moonraker / screen objects (no network)."""
import os
import queue
import tempfile
import unittest

from crm4ui import dgus
from crm4bridge import ui
from crm4bridge.bridge import Bridge
from crm4bridge.config import Config


class FakeLink:
    def __init__(self):
        self.sent = []
        self.rx = queue.Queue()

    def send(self, f):
        self.sent.append(f)
        return True

    def start(self):
        pass

    def pages(self):
        return [f.payload()[3] for f in self.sent if f.vp == dgus.VP_PAGE]

    def words(self):
        return {f.vp: int.from_bytes(f.payload()[:2], 'big') for f in self.sent
                if f.cmd == dgus.CMD_WRITE and len(f.payload()) == 2}


class FakeMoon:
    def __init__(self):
        self.calls = []
        self.status = {
            'extruder': {'temperature': 210.4, 'target': 215, 'can_extrude': True},
            'heater_bed': {'temperature': 59.6, 'target': 60},
            'fan': {'speed': 0.0},
            'gcode_move': {'speed_factor': 1.0, 'homing_origin': [0, 0, -0.05, 0], 'gcode_position': [10, 20, 0.3, 0]},
            'toolhead': {'homed_axes': 'xyz', 'max_accel': 1700, 'max_velocity': 500, 'square_corner_velocity': 5},
            'print_stats': {'state': 'standby', 'filename': '', 'print_duration': 0},
            'display_status': {'progress': 0},
            'filament_switch_sensor filament_sensor': {'enabled': True, 'filament_detected': True},
            'gcode_macro PRINT_START': {'per_print_mesh': 0},
        }

    def server_info(self):
        return {'klippy_state': 'ready'}

    def printer_info(self):
        return {'software_version': 'v0.13', 'hostname': 'pi', 'state_message': ''}

    def history_totals(self):
        return {'job_totals': {'total_print_time': 3600}}

    def spoolman_status(self):
        return {'spoolman_connected': False, 'spool_id': None}       # see test_spoolman.py

    def query(self, objects):
        return {k: v for k, v in self.status.items() if k in objects}

    def files(self):
        return [{'path': 'a.gcode', 'modified': 2}, {'path': 'sub/b.gcode', 'modified': 3}]

    def metadata(self, fn):
        return {'estimated_time': 3720, 'filament_total': 1500.0, 'object_height': 10, 'layer_height': 0.2}

    def gcode(self, script):
        self.calls.append(('gcode', script))

    def __getattr__(self, name):
        def call(*a):
            self.calls.append((name,) + a)
        return call


class BridgeTest(unittest.TestCase):
    def make(self, dry_run=False):
        self.tmp = tempfile.TemporaryDirectory()
        cfg = Config(None, {'dry_run': 'true' if dry_run else 'false',
                            'state_file': os.path.join(self.tmp.name, 's.json')})
        self.moon, self.link = FakeMoon(), FakeLink()
        b = Bridge(cfg, self.moon, self.link)
        b.jobs = _Inline()
        b.poll()
        return b

    def tearDown(self):
        self.tmp.cleanup()

    def key(self, b, vp, v):
        b.handle_frame(dgus.reply_words(vp, v))

    def test_status_pushed(self):
        b = self.make()
        w = self.link.words()
        self.assertEqual(w[ui.VP_NOZZLE], 210)
        self.assertEqual(w[ui.VP_NOZZLE_TARGET], 215)
        self.assertEqual(dgus.to_signed(w[ui.VP_ZOFFSET]), -5)
        self.assertEqual(w[ui.VP_POS_Y], 200)
        self.assertEqual(self.link.pages()[-1], ui.PAGE_MAIN)

    def test_temperature_input(self):
        b = self.make()
        self.key(b, ui.VP_BED_TARGET, 70)
        self.assertIn(('gcode', 'SET_HEATER_TEMPERATURE HEATER=heater_bed TARGET=70'), self.moon.calls)

    def test_dry_run_sends_nothing(self):
        b = self.make(dry_run=True)
        self.key(b, ui.VP_BED_TARGET, 70)
        self.key(b, ui.K_MACHINE, 1)
        self.assertEqual(self.moon.calls, [])

    def test_file_flow(self):
        b = self.make()
        self.key(b, ui.K_MAIN, 1)
        self.assertEqual(self.link.pages()[-1], 2)
        self.key(b, ui.K_FILE_ROW, 1)                # newest first: sub/b.gcode
        self.assertEqual(self.link.pages()[-1], ui.PAGE_FILE_PREVIEW)
        self.key(b, ui.K_FILES, 1)
        self.assertIn(('print_start', 'sub/b.gcode'), self.moon.calls)

    def test_print_state_pages(self):
        b = self.make()
        self.moon.status['print_stats'] = {'state': 'printing', 'filename': 'a.gcode', 'print_duration': 600}
        self.moon.status['display_status'] = {'progress': 0.25}
        b.poll()
        self.assertEqual(self.link.pages()[-1], ui.PAGE_PRINTING)
        w = self.link.words()
        self.assertEqual(w[ui.VP_PROGRESS], 25)
        self.assertEqual((w[ui.VP_REMAIN_H], w[ui.VP_REMAIN_M]), (0, 52))   # 3720 - 600 s
        self.moon.status['print_stats'] = {'state': 'paused', 'filename': 'a.gcode', 'print_duration': 600}
        self.moon.status['filament_switch_sensor filament_sensor']['filament_detected'] = False
        b.poll()
        self.assertEqual(self.link.pages()[-1], ui.PAGE_RUNOUT)

    def test_move_requires_homing(self):
        b = self.make()
        self.moon.status['toolhead']['homed_axes'] = ''
        b.poll()
        self.key(b, ui.VP_POS_X, 300)
        self.assertFalse(any('G1' in c[1] for c in self.moon.calls if c[0] == 'gcode'))
        self.moon.status['toolhead']['homed_axes'] = 'xyz'
        b.poll()
        self.key(b, ui.VP_POS_X, 300)
        self.assertIn(('gcode', 'G90\nG1 X30.0 F6000'), self.moon.calls)

    def test_toggles(self):
        b = self.make()
        self.key(b, ui.K_TUNE, 7)
        self.key(b, ui.K_TUNE, 4)
        self.assertIn(('gcode', 'SET_FILAMENT_SENSOR SENSOR=filament_sensor ENABLE=0'), self.moon.calls)
        self.assertIn(('gcode', 'SET_GCODE_VARIABLE MACRO=PRINT_START VARIABLE=per_print_mesh VALUE=1'),
                      self.moon.calls)

    def test_machine_keys(self):
        b = self.make()
        for k in (1, 2, 3):
            self.key(b, ui.K_MACHINE, k)
        self.assertEqual([c[0] for c in self.moon.calls], ['emergency_stop', 'firmware_restart', 'restart'])

    def test_creality_only_tiles(self):
        b = self.make()
        for vp, k in ((ui.K_RESET_CFG, 0), (ui.K_RESTORE_NET, 0), (ui.K_ADV, 9), (ui.K_ADV, 4),
                      (ui.K_ADV2, 8), (ui.K_PREPARE, 7),
                      (ui.K_PID_NAV, 5), (ui.VP_PID_NOZZLE_CYCLES, 5)):
            self.link.sent.clear()
            self.key(b, vp, k)
            self.assertEqual(self.link.pages(), [ui.PAGE_NOT_SUPPORTED])
        self.assertEqual(self.moon.calls, [])

    def test_language_is_fixed(self):
        b = self.make()
        self.key(b, ui.K_LANGUAGE, 2)                # tap "Deutsch" on a stock UI
        w = self.link.words()
        self.assertEqual(w[ui.VP_LANGUAGE], 1)
        self.assertEqual(w[ui.VP_LANG_CHECK[1]], 1)
        self.assertEqual(w[ui.VP_LANG_CHECK[2]], 0)
        self.assertIsNone(b.state.get('language'))

    def test_ok_returns_to_origin_page(self):
        cases = [((ui.K_ADV, 8), ui.PAGE_ADV), ((ui.K_ADV2, 8), ui.PAGE_ADV), ((ui.K_PREPARE, 7), ui.PAGE_TUNE2),
                 ((ui.K_PID_NAV, 5), ui.PAGE_TUNE), ((ui.VP_MAX_SPEED[3], 50), 129)]
        b = self.make()
        for (vp, v), page in cases:
            b.set_page(ui.PAGE_MAIN)                 # stale page the bridge last set itself
            self.key(b, vp, v)
            self.assertEqual(self.link.pages()[-1], ui.PAGE_NOT_SUPPORTED)
            self.key(b, ui.K_PREPARE, 0xB)           # Ok
            self.assertEqual(self.link.pages()[-1], page, (hex(vp), v))


    def test_homing_keys(self):
        b = self.make()
        for k, cmd in ((3, 'G28 X'), (4, 'G28 Y'), (5, 'G28'), (6, 'G28 X Y')):
            self.moon.calls.clear()
            self.key(b, ui.K_HOME, k)
            self.assertEqual(self.moon.calls[0], ('gcode', cmd))

    def test_velocity_scaled_by_10(self):
        b = self.make()
        self.assertEqual(self.link.words()[ui.VP_MAX_ACCEL[0]], 17000)        # 1700 mm/s^2 -> 1700.0
        self.assertEqual(self.link.words()[ui.VP_MAX_CORNER[0]], 50)
        self.key(b, ui.VP_MAX_ACCEL[0], 25000)                                # keypad 2500.0
        self.key(b, ui.VP_MAX_CORNER[1], 75)                                  # 7.5
        self.assertIn(('gcode', 'SET_VELOCITY_LIMIT ACCEL=2500'), self.moon.calls)
        self.assertIn(('gcode', 'SET_VELOCITY_LIMIT SQUARE_CORNER_VELOCITY=7.5'), self.moon.calls)

    def test_pid_pages_return_to_autotune(self):
        b = self.make()
        for k, page in ((2, ui.PAGE_PID_NOZZLE), (4, ui.PAGE_PID_BED), (5, ui.PAGE_PID_NOZZLE), (6, ui.PAGE_PID_BED)):
            self.key(b, ui.K_PID, k)
            self.assertEqual(self.link.pages()[-1], page)

    def test_two_word_event(self):
        from crm4ui import dgus
        b = self.make()
        b.handle_frame(dgus.reply_words(0x7006, 0x0001, 0x86A0))              # 100000, a 32-bit PID field
        self.assertEqual(self.link.pages()[-1], ui.PAGE_NOT_SUPPORTED)
        self.assertEqual(dgus.reply_words(0x7006, 0xFFFF, 0xFFFE).signed_value, -2)
        self.key(b, ui.VP_HOME_OFFSET_Z, 5)
        self.assertEqual(self.link.pages()[-1], ui.PAGE_NOT_SUPPORTED)

    def test_volume_toggles_touch_beep(self):
        b = self.make()
        b.push_static()
        sent = {f.vp: f.payload() for f in self.link.sent if f.cmd == 0x82}
        self.assertEqual(sent[ui.VP_SYS_CONFIG], bytes([0x5A, 0, 0, 0x6C]))
        self.assertEqual(self.link.words()[ui.VP_TOGGLE_VOLUME], ui.TOGGLE_ON)
        self.key(b, ui.K_ADV2, 6)
        sent = {f.vp: f.payload() for f in self.link.sent if f.cmd == 0x82}
        self.assertEqual(sent[ui.VP_SYS_CONFIG], bytes([0x5A, 0, 0, 0x64]))
        self.assertEqual(self.link.words()[ui.VP_TOGGLE_VOLUME], ui.TOGGLE_OFF)
        self.assertEqual(b.state.get('volume'), False)

    def sys_config(self):
        sent = {f.vp: f.payload() for f in self.link.sent if f.cmd == 0x82}
        return sent[ui.VP_SYS_CONFIG][3]

    def test_auto_sleep_toggles_standby(self):
        b = self.make()
        b.push_static()
        self.assertEqual(self.sys_config(), 0x6C)
        self.key(b, ui.K_TUNE, 9)                                   # Auto Sleep off
        self.assertEqual(self.sys_config(), 0x68)
        self.assertEqual(self.link.words()[ui.VP_TOGGLE_SLEEP], ui.TOGGLE_OFF)
        self.key(b, ui.K_ADV2, 6)                                   # and Volume off
        self.assertEqual(self.sys_config(), 0x60)
        self.key(b, ui.K_TUNE, 9)
        self.assertEqual(self.sys_config(), 0x64)
        self.assertNotIn(ui.PAGE_NOT_SUPPORTED, self.link.pages())

    def test_backlight_config(self):
        b = self.make()
        b.push_static()
        self.assertNotIn(ui.VP_BACKLIGHT, {f.vp for f in self.link.sent})   # untouched by default
        b.cfg.brightness, b.cfg.standby_brightness, b.cfg.standby_timeout = 60, 10, 120
        b.push_static()
        sent = {f.vp: f.payload() for f in self.link.sent if f.cmd == 0x82}
        self.assertEqual(sent[ui.VP_BACKLIGHT], bytes([60, 10]))
        self.assertEqual(self.link.words()[ui.VP_STANDBY_TIME], 12000)

    def test_screen_reported_page(self):
        b = self.make()
        b.request_page()
        self.assertEqual(self.link.sent[-1].cmd, 0x83)
        self.assertEqual(self.link.sent[-1].vp, ui.VP_CUR_PAGE)
        b.set_page(ui.PAGE_MAIN)
        self.key(b, ui.VP_CUR_PAGE, ui.PAGE_ADV)                    # the screen moved by itself
        self.assertEqual(b.page, ui.PAGE_ADV)
        self.key(b, ui.K_ADV, 9)                                    # unsupported tile
        self.key(b, ui.VP_CUR_PAGE, ui.PAGE_NOT_SUPPORTED)
        self.key(b, ui.K_PREPARE, 0xB)                              # Ok
        self.assertEqual(self.link.pages()[-1], ui.PAGE_ADV)

    def test_progress_dim(self):
        b = self.make()
        x0, y0, x1, y1 = ui.DIM_RECT
        self.assertEqual(self.link.words()[ui.SP_DIM + 4], y0)                 # idle: nothing dimmed
        self.moon.status['print_stats'] = {'state': 'printing', 'filename': 'a.gcode', 'print_duration': 60}
        self.moon.status['display_status'] = {'progress': 0.25}
        b.poll()
        w = self.link.words()
        self.assertEqual([w[ui.SP_DIM + i] for i in (1, 2, 3, 4)], [x0, y0, x1, y0 + (y1 - y0) * 75 // 100])
        self.assertEqual(w[ui.VP_DIM_ALPHA], ui.DIM_ALPHA)

    def test_file_row_highlight(self):
        b = self.make()
        b.load_files()
        self.key(b, ui.K_FILE_ROW, 2)
        w = self.link.words()
        self.assertEqual(w[ui.SP_FILE_ROW[1] + 3], ui.ROW_COLOR_SELECTED)
        self.assertEqual(w[ui.SP_FILE_ROW[0] + 3], ui.ROW_COLOR)


class _Inline:
    def submit(self, fn):
        fn()


if __name__ == '__main__':
    unittest.main()
