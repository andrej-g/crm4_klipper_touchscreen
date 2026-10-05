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

    def test_language_is_fixed(self):
        b = self.make()
        self.key(b, ui.K_LANGUAGE, 2)                # tap "Deutsch" on a stock UI
        w = self.link.words()
        self.assertEqual(w[ui.VP_LANGUAGE], 1)
        self.assertEqual(w[ui.VP_LANG_CHECK[1]], 1)
        self.assertEqual(w[ui.VP_LANG_CHECK[2]], 0)
        self.assertIsNone(b.state.get('language'))


class _Inline:
    def submit(self, fn):
        fn()


if __name__ == '__main__':
    unittest.main()
