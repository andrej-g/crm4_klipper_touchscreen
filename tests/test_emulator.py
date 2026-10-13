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


if __name__ == '__main__':
    unittest.main()
