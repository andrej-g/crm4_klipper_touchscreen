"""The mock Moonraker's printer model: bed mesh and simulated PID autotune (no HTTP)."""
import threading
import time
import unittest

from crm4bridge import mesh
from crm4bridge.mock_moonraker import MESH_MAX, MESH_MIN, MESH_N, Printer


class MockMeshTest(unittest.TestCase):
    def test_mesh_shape_and_status(self):
        pr = Printer(600)
        st = pr.status({'bed_mesh'})['bed_mesh']
        self.assertEqual(st['profile_name'], 'default')
        self.assertEqual((len(st['mesh_matrix']), len(st['mesh_matrix'][0])), (MESH_N, MESH_N))
        self.assertEqual((st['mesh_min'], st['mesh_max']), (list(MESH_MIN), list(MESH_MAX)))
        zs = [z for row in st['mesh_matrix'] for z in row]
        self.assertTrue(-0.25 < min(zs) < max(zs) < 0.1)
        self.assertIsNotNone(mesh.grid_from_status(st, 5))

    def test_clear_calibrate_and_no_mesh(self):
        pr = Printer(600)
        pr.gcode('BED_MESH_CLEAR')
        st = pr.status({'bed_mesh'})['bed_mesh']
        self.assertEqual((st['profile_name'], st['mesh_matrix']), ('', [[]]))
        self.assertIsNone(mesh.grid_from_status(st, 5))
        self.assertIsNone(Printer(600, mesh=False).mesh)
        pr.gcode('BED_MESH_PROFILE LOAD=default-80C')
        self.assertEqual(pr.status({'bed_mesh'})['bed_mesh']['profile_name'], 'default-80C')


class MockPidTest(unittest.TestCase):
    def test_autotune_oscillates_then_finishes(self):
        pr = Printer(600, pid_seconds=1.2)
        temps = []

        def ticker():
            last = time.monotonic()
            for _ in range(40):
                time.sleep(0.05)
                now = time.monotonic()
                pr.tick(now - last)
                last = now
                temps.append(pr.t['extruder'][0])
        th = threading.Thread(target=ticker)
        th.start()
        t0 = time.monotonic()
        pr.gcode('PID_CALIBRATE HEATER=extruder TARGET=200')                 # blocks until done, as Moonraker
        self.assertGreaterEqual(time.monotonic() - t0, 1.0)
        th.join()
        self.assertIsNone(pr.pid)
        self.assertEqual(pr.t['extruder'][1], 200.0)                            # target stays set
        self.assertTrue(any(t > 200 for t in temps) and any(t < 200 for t in temps))
        with self.assertRaises(ValueError):
            pr.gcode('PID_CALIBRATE HEATER=chamber TARGET=50')


if __name__ == '__main__':
    unittest.main()
