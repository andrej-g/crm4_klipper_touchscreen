"""Bed mesh -> screen grid: sampling, serpentine VP order, encoding (no network)."""
import unittest

from crm4bridge import mesh, ui


def plane(ny, nx, a=0.001, b=0.002, c=-0.05):
    """z = a*x_index + b*y_index + c: bilinear sampling of a plane is exact."""
    return [[round(a * i + b * j + c, 6) for i in range(nx)] for j in range(ny)]


class SampleTest(unittest.TestCase):
    def test_plane_is_exact(self):
        m = plane(50, 50)
        g = mesh.sample(m, 5)
        self.assertEqual(len(g), 5)
        self.assertTrue(all(len(r) == 5 for r in g))
        for j in range(5):
            for i in range(5):
                self.assertAlmostEqual(g[j][i], 0.001 * 49 * i / 4 + 0.002 * 49 * j / 4 - 0.05, places=6)

    def test_corners_are_mesh_corners(self):
        m = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]]
        g = mesh.sample(m, 2)
        self.assertEqual(g, [[1.0, 3.0], [7.0, 9.0]])
        self.assertEqual(mesh.sample(m, 3), m)

    def test_midpoint_interpolates(self):
        m = [[0.0, 1.0], [2.0, 3.0]]
        g = mesh.sample(m, 3)
        self.assertAlmostEqual(g[1][1], 1.5)
        self.assertAlmostEqual(g[0][1], 0.5)

    def test_degenerate_sizes(self):
        self.assertEqual(mesh.sample([[0.5]], 4), [[0.5] * 4] * 4)
        self.assertEqual(mesh.sample([[1.0, 2.0]], 2), [[1.0, 2.0], [1.0, 2.0]])
        with self.assertRaises(ValueError):
            mesh.sample([[1.0, 2.0], [3.0]], 2)

    def test_status_prefers_mesh_matrix(self):
        st = {'profile_name': 'default', 'mesh_matrix': plane(10, 10, c=0.1), 'probed_matrix': plane(3, 3)}
        self.assertAlmostEqual(mesh.grid_from_status(st, 5)[0][0], 0.1)
        st = {'profile_name': 'default', 'mesh_matrix': [[]], 'probed_matrix': plane(3, 3)}
        self.assertAlmostEqual(mesh.grid_from_status(st, 5)[0][0], -0.05)
        self.assertIsNone(mesh.grid_from_status({'profile_name': '', 'mesh_matrix': [[]], 'probed_matrix': [[]]}, 5))
        self.assertIsNone(mesh.grid_from_status({}, 5))


class OrderTest(unittest.TestCase):
    def test_serpentine(self):
        g = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
        self.assertEqual(mesh.serpentine(g), [1, 2, 3, 6, 5, 4, 7, 8, 9])

    def test_vp_layout_matches_the_stock_pages(self):
        # 14.bin, pages 28/135: bottom row 0x7100..0x7108 left to right, the row above
        # 0x7112..0x710A left to right, i.e. 0x710A is at the right end (serpentine)
        g = [[f'r{r}c{c}' for c in range(5)] for r in range(5)]
        vps = {vp: v for vp, v in zip(range(ui.VP_MESH, ui.VP_MESH + 50, 2), mesh.serpentine(g))}
        self.assertEqual(vps[0x7100], 'r0c0')
        self.assertEqual(vps[0x7108], 'r0c4')
        self.assertEqual(vps[0x710A], 'r1c4')
        self.assertEqual(vps[0x7112], 'r1c0')
        self.assertEqual(vps[0x7114], 'r2c0')
        self.assertEqual(vps[0x7126], 'r3c0')
        self.assertEqual(vps[0x7128], 'r4c0')
        self.assertEqual(vps[0x7130], 'r4c4')
        # pages 27/134 (4x4): 0x7108 is the right end of row 1, 0x711E the left end of row 3
        g4 = [[f'r{r}c{c}' for c in range(4)] for r in range(4)]
        vps = {vp: v for vp, v in zip(range(ui.VP_MESH, ui.VP_MESH + 32, 2), mesh.serpentine(g4))}
        self.assertEqual((vps[0x7106], vps[0x7108], vps[0x710E], vps[0x7110], vps[0x711E], vps[0x7118]),
                         ('r0c3', 'r1c3', 'r1c0', 'r2c0', 'r3c0', 'r3c3'))


class EncodeTest(unittest.TestCase):
    def test_scale_and_sign(self):
        self.assertEqual(mesh.encode(0.0536), 54)
        self.assertEqual(mesh.encode(-0.0536), -54)
        self.assertEqual(mesh.encode(-0.1234567), -123)
        self.assertEqual(mesh.encode(40.0), 0x7FFF)
        self.assertEqual(mesh.encode(-40.0), -0x8000)

    def test_words(self):
        w = mesh.words([[0.001, -0.002], [0.003, 0.004]], ui.VP_MESH)
        self.assertEqual(w, [(0x7100, 1), (0x7102, -2), (0x7104, 4), (0x7106, 3)])


if __name__ == '__main__':
    unittest.main()
