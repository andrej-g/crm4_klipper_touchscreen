"""Emulator behaviour on the real stock project (skipped without CRM4_STOCK_PRIVATE)."""
import os
import unittest

from crm4ui import dgus
from crm4ui.project import Project

STOCK = os.environ.get('CRM4_STOCK_PRIVATE')


@unittest.skipUnless(STOCK and os.path.isdir(STOCK), 'CRM4_STOCK_PRIVATE not set')
class EmulatorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project = Project(STOCK)

    def sim(self, page):
        from crm4ui.emulator import ScreenSim
        s = ScreenSim(self.project, start_page=page, lang=1)
        self.sent = []
        s.send = self.sent.append
        return s

    def test_host_writes_and_page_switch(self):
        s = self.sim(0)
        s.handle_host(dgus.write_words(0x7046, 215))
        s.handle_host(dgus.set_page(1))
        self.assertEqual((s.word(0x7046), s.page), (215, 1))
        self.assertNotIn(dgus.ACK, self.sent)                    # the CR-M4 screen sends no acks
        s.handle_host(dgus.read_words(0x0014, 1))
        self.assertEqual(self.sent[-1], dgus.reply_words(0x0014, 1))   # current page
        s.render()                                    # must not raise

    def test_description_pointer_and_dim(self):
        s = self.sim(11)                              # printing page: thumbnail dim field
        dims = [r for r in self.project.vars.pages[11] if r.type == 0x26]
        self.assertTrue(dims)
        sp = int.from_bytes(dims[0].data[2:4], 'big')
        self.assertEqual(s.word(sp + 1), int.from_bytes(dims[0].data[8:10], 'big'))   # seeded from 14.bin
        img = s.render()
        before = img.getpixel((238, 300))
        s.handle_host(dgus.write_words(0x8800, 0xFF))
        for i, v in enumerate((88, 264, 388, 564), 1):
            s.handle_host(dgus.write_words(sp + i, v))
        after = s.render().getpixel((238, 300))
        self.assertLessEqual(sum(after[:3]), sum(before[:3]))
        s.handle_host(dgus.write_words(sp + 1, 0xFFFF))  # >= FF00 hides the field
        s.render()

    def test_return_key(self):
        s = self.sim(1)
        s.touch(240, 610)                             # "+ File"
        self.assertEqual(self.sent[-1], dgus.reply_words(0x4002, 1))

    def test_keypad_input(self):
        s = self.sim(14)
        s.touch(120, 150)                             # nozzle target -> keypad page 40
        self.assertEqual(s.page, 40)
        for xy in ((182, 364), (70, 365), (182, 488), (410, 665)):   # 2 1 5 OK
            s.touch(*xy)
        self.assertEqual(s.page, 14)
        self.assertEqual(self.sent[-1], dgus.reply_words(0x7048, 215))

    def test_titled_keypad_page(self):
        import os as _os
        from crm4ui.emulator import ScreenSim
        from crm4ui.spec import apply, load_spec
        prj = Project(STOCK)
        spec = _os.path.join(_os.path.dirname(__file__), '..', 'examples', 'keypad_titles', 'spec.yaml')
        apply(prj, load_spec(spec), log=lambda *a: None)
        s = ScreenSim(prj, start_page=14, lang=1)
        sent = []
        s.send = sent.append
        s.touch(360, 150)                             # bed target -> titled keypad page 48
        self.assertEqual(s.page, 48)
        self.assertIsNotNone(s.keypad)
        s.render()
        for xy in ((295, 488), (182, 488), (410, 665)):   # 6 5 OK
            s.touch(*xy)
        self.assertEqual(s.page, 14)
        self.assertEqual(sent[-1], dgus.reply_words(0x704C, 65))

    def test_increment(self):
        s = self.sim(110)
        s.touch(240, 200)                             # Z up
        self.assertEqual(self.sent[-1].vp, 0x7050)

    def test_mesh_grid_pages(self):
        from crm4bridge import mesh, ui
        for grid, (page_done, page_data) in ui.MESH_PAGES.items():
            fields = {r.vp: r for r in self.project.vars.pages[page_data] if r.type == 0x10 and r.vp >= 0x7100}
            self.assertEqual(len(fields), grid * grid, page_data)
            self.assertEqual(set(fields), {ui.VP_MESH + 2 * i for i in range(grid * grid)})
            self.assertTrue(all(r.digits == (2, 3) and r.data[19] == 0 for r in fields.values()))   # 2.3 digits, int16
            # the UI lays the VPs out serpentine from the bottom left, as crm4bridge.mesh assumes
            rows = []                                                 # distinct y positions (one field sits 2 px off)
            for y in sorted({r.pos[1] for r in fields.values()}, reverse=True):
                if not rows or rows[-1] - y > 10:
                    rows.append(y)
            self.assertEqual(len(rows), grid)
            for rnum, y in enumerate(rows):
                cols = sorted((r.pos[0], r.vp) for r in fields.values() if abs(r.pos[1] - y) <= 10)
                vps = [vp for _, vp in cols]
                expect = [ui.VP_MESH + 2 * (rnum * grid + (c if rnum % 2 == 0 else grid - 1 - c)) for c in range(grid)]
                self.assertEqual(vps, expect, (page_data, rnum))
            s = self.sim(page_done)
            for vp, v in mesh.words([[0.001 * (i - j) for i in range(grid)] for j in range(grid)], ui.VP_MESH):
                s.handle_host(dgus.write_words(vp, v))
            self.assertEqual(dgus.to_signed(s.word(ui.VP_MESH + 2)), 1)
            s.render()

    def test_curve_buffers_and_pid_page(self):
        from crm4bridge import curve
        s = self.sim(123)
        curves = [r for r in self.project.vars.pages[123] if r.type == 0x20]
        self.assertEqual(sorted(r.describe()['channel'] for r in curves), [0, 1])
        d = curves[0].describe()
        self.assertEqual((d['y_center'], d['vd_central'], d['mul_y'], d['dis_hor']), (387, 175, 153, 1))
        s.handle_host(curve.clear_frame(0))
        for i in range(60):
            for f in curve.CurveStream('extruder', 200).frames(100 + i * 2):
                s.handle_host(f)
        self.assertEqual(len(s.curves[0]), 60)                                    # one point per frame
        self.assertEqual(list(s.curves[0])[:3], [100, 102, 104])
        self.assertEqual(len(s.curves[1]), 60)
        before = s.render().copy()
        s.handle_host(curve.clear_frame(0))
        self.assertEqual(len(s.curves[0]), 0)
        after = s.render()
        # the current-value trace (yellow 0xFFE0) was drawn inside the graph box before, not after
        box = (d['box'][0], d['box'][1], d['box'][2], d['box'][3])
        def yellow(im):
            raw = im.crop(box).convert('RGB').tobytes()
            return sum(1 for r, g, b in zip(raw[0::3], raw[1::3], raw[2::3]) if r > 200 and g > 200 and b < 60)
        self.assertGreater(yellow(before), 50)
        self.assertLess(yellow(after), yellow(before))
        s.handle_host(dgus.write_words(0x0310, 0x1234, 0x0100, 0x0001, 5))        # bad magic: ignored
        self.assertEqual(len(s.curves[0]), 0)


if __name__ == '__main__':
    unittest.main()
