"""Bridge logic against fake Moonraker / screen objects (no network)."""
import os
import queue
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

from crm4ui import dgus
from crm4bridge import ui
from crm4bridge.bridge import Bridge
from crm4bridge.config import Config
from crm4bridge.moonraker import MoonrakerError


class FakeLink:
    def __init__(self):
        self.sent = []
        self.gaps = []
        self.rx = queue.Queue()

    def send(self, f, byte_gap=0.0):
        self.sent.append(f)
        self.gaps.append(byte_gap)
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
        self.hold = None                 # threading.Event: PID_CALIBRATE blocks until it is set
        self.fail = False                # ... and then fails
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
            'bed_mesh': {'profile_name': 'default', 'mesh_min': [50, 18], 'mesh_max': [420, 420],
                         'mesh_matrix': [[0.001 * i - 0.01 * j for i in range(9)] for j in range(9)],
                         'probed_matrix': [[]]},
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
        if self.hold is not None and script.startswith('PID_CALIBRATE'):
            self.hold.wait(5)
            if self.fail:
                raise MoonrakerError('pid_calibrate interrupted')

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

    # ---- bed mesh grid ------------------------------------------------------------
    def test_mesh_grid_after_leveling(self):
        b = self.make()
        self.key(b, ui.K_LEVEL, 0xF1)
        self.assertIn(('gcode', b.cfg.mesh_gcode), self.moon.calls)
        self.assertEqual(self.link.pages()[-2:], [ui.PAGE_LEVELING, 28])
        w = self.link.words()
        # 9x9 plane z = 0.001*x - 0.01*y sampled 5x5 (every second node): corners (0,0) -> 0,
        # (8,0) -> 0.008, (0,8) -> -0.08; VP order is serpentine from the front-left
        self.assertEqual(dgus.to_signed(w[0x7100]), 0)
        self.assertEqual(dgus.to_signed(w[0x7108]), 8)                      # front right
        self.assertEqual(dgus.to_signed(w[0x710A]), 8 - 20)                 # row 1 right end
        self.assertEqual(dgus.to_signed(w[0x7112]), -20)                    # row 1 left end
        self.assertEqual(dgus.to_signed(w[0x7128]), -80)                    # back left
        self.assertEqual(dgus.to_signed(w[0x7130]), -72)                    # back right
        self.assertEqual(len([vp for vp in w if 0x7100 <= vp <= 0x7130]), 25)

    def test_mesh_grid_4x4_pages(self):
        b = self.make()
        b.cfg.mesh_grid = 4
        self.key(b, ui.K_ADV, 7)
        self.assertEqual(self.link.pages()[-1], 134)
        w = self.link.words()
        self.assertEqual(len([vp for vp in w if 0x7100 <= vp <= 0x711E]), 16)
        self.assertEqual(dgus.to_signed(w[0x711E]), -80)                    # back left on the 4x4 layout
        self.assertEqual(dgus.to_signed(w[0x7118]), -72)

    def test_auto_leveling_data_page(self):
        b = self.make()
        b.set_page(ui.PAGE_ADV)
        self.key(b, ui.K_ADV, 7)
        self.assertEqual(self.link.pages()[-1], 135)
        self.assertNotIn(ui.PAGE_NOT_SUPPORTED, self.link.pages())
        self.assertEqual(self.moon.calls, [])                               # display only

    def test_no_mesh_loaded(self):
        b = self.make()
        self.moon.status['bed_mesh'] = {'profile_name': '', 'mesh_min': [0, 0], 'mesh_max': [0, 0],
                                        'mesh_matrix': [[]], 'probed_matrix': [[]]}
        b.set_page(ui.PAGE_ADV)
        self.key(b, ui.K_ADV, 7)
        self.assertEqual(self.link.pages()[-1], ui.PAGE_ERROR)
        texts = {f.vp: f.payload() for f in self.link.sent if f.cmd == 0x82 and len(f.payload()) > 2}
        self.assertTrue(texts[ui.TXT_ERROR[0]].startswith(b'No bed mesh loaded'))
        self.assertTrue(b.popup_until)
        b.timers(b.popup_until + 1)                                         # the popup times out
        self.assertEqual(self.link.pages()[-1], ui.PAGE_ADV)
        self.assertEqual(b.popup_until, 0.0)
        # after levelling with nothing to show, the auto-level page is restored by the timeout too
        self.key(b, ui.K_LEVEL, 0xF1)
        self.assertEqual(self.link.pages()[-1], ui.PAGE_ERROR)
        b.timers(b.popup_until + 1)
        self.assertEqual(self.link.pages()[-1], ui.PAGE_AUTOLEVEL)

    # ---- PID graph ------------------------------------------------------------------
    def curve_frames(self):
        return [f for f in self.link.sent if f.vp == 0x0310]

    def pending(self, b):
        """Run jobs on a real worker thread and keep PID_CALIBRATE running until finish()."""
        b.jobs = ThreadPoolExecutor(1)
        self.moon.hold = threading.Event()

    def finish(self, b, ok=True):
        self.moon.fail = not ok
        self.moon.hold.set()
        _wait(lambda: b.curve is None)
        b.jobs.shutdown(wait=True)
        b.jobs = _Inline()
        self.moon.hold, self.moon.fail = None, False

    def test_pid_graph_frames(self):
        b = self.make()
        self.pending(b)                                                     # PID_CALIBRATE still running
        self.key(b, ui.K_PID, 1)
        _wait(lambda: any(c[0] == 'gcode' and 'PID_CALIBRATE' in c[1] for c in self.moon.calls))
        self.assertEqual(self.link.pages()[-1], ui.PAGE_PID_NOZZLE_RUN)
        self.assertIsNotNone(b.curve)
        clears = [f for f in self.link.sent if f.vp in (0x0301, 0x0303)]
        self.assertEqual([f.payload() for f in clears], [b'\0\0', b'\0\0'])  # both channels cleared first
        b.timers(10.0)
        frames = self.curve_frames()
        self.assertEqual(len(frames), 2)
        self.assertEqual(frames[0].to_bytes(), bytes.fromhex('5aa50d8203105aa50100000200d200d2'))   # 210.4 -> 210
        self.assertEqual(frames[1].to_bytes(), bytes.fromhex('5aa50d8203105aa50100010200d200d2'))   # target 210
        self.assertEqual(self.link.gaps[-1], b.cfg.curve_byte_gap)
        b.timers(10.5)                                                      # not yet (curve_interval)
        self.assertEqual(len(self.curve_frames()), 2)
        self.moon.status['extruder']['temperature'] = 213.0
        b.poll()
        b.timers(11.0)
        frames = self.curve_frames()
        self.assertEqual(len(frames), 4)
        self.assertEqual(frames[2].payload()[6:], bytes.fromhex('00d200d5'))          # (previous, current)
        self.finish(b)                                                      # PID_CALIBRATE done
        self.assertIsNone(b.curve)
        self.assertEqual(self.link.pages()[-1], ui.PAGE_PID_NOZZLE_DONE)
        b.timers(12.0)
        self.assertEqual(len(self.curve_frames()), 4)                       # nothing more

    def test_pid_graph_bed_channels_and_clear_on_save(self):
        b = self.make()
        self.pending(b)
        self.key(b, ui.K_PID, 3)
        b.timers(10.0)
        self.assertEqual([f.to_bytes()[10] for f in self.curve_frames()], [2, 3])
        self.assertEqual(self.curve_frames()[0].payload()[6:], bytes.fromhex('003c003c'))     # 59.6 -> 60
        self.finish(b)
        self.link.sent.clear()
        self.key(b, ui.K_PID, 4)                                            # Yes: SAVE_CONFIG
        self.assertEqual([f.vp for f in self.link.sent if f.vp in (0x0305, 0x0307)], [0x0305, 0x0307])

    def test_pid_graph_stops_on_page_change_and_error(self):
        b = self.make()
        self.pending(b)
        self.key(b, ui.K_PID, 1)
        self.key(b, ui.VP_CUR_PAGE, ui.PAGE_MAIN)                          # the screen went elsewhere
        self.assertIsNone(b.curve)
        self.finish(b)
        self.pending(b)
        self.key(b, ui.K_PID, 1)
        self.assertIsNotNone(b.curve)
        self.finish(b, ok=False)                                            # PID_CALIBRATE failed
        self.assertIsNone(b.curve)
        _wait(lambda: self.link.pages()[-1] == ui.PAGE_ERROR)
        self.assertEqual(self.link.pages()[-1], ui.PAGE_ERROR)

    def test_dry_run_pid_graph(self):
        b = self.make(dry_run=True)
        self.key(b, ui.K_PID, 1)                                            # nothing sent; done at once
        self.assertEqual(self.moon.calls, [])
        self.assertIsNone(b.curve)
        self.assertEqual(self.link.pages()[-1], ui.PAGE_PID_NOZZLE_DONE)


class _Inline:
    def submit(self, fn):
        fn()


def _wait(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        time.sleep(0.01)
    return cond()


if __name__ == '__main__':
    unittest.main()
