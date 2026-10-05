"""Tests against a real Creality screen package (not in the repo).

Set CRM4_STOCK_PRIVATE to the package's private/ directory, e.g.
    CRM4_STOCK_PRIVATE=/path/to/CR-M4_..._V2.0.3_NEW_UI/private python -m unittest
"""
import os
import tempfile
import unittest

from crm4ui.project import Project, tree_digest
from crm4ui.spec import apply, load_spec

STOCK = os.environ.get('CRM4_STOCK_PRIVATE')
EXAMPLES = os.path.join(os.path.dirname(__file__), '..', 'examples')


@unittest.skipUnless(STOCK and os.path.isdir(STOCK), 'CRM4_STOCK_PRIVATE not set')
class StockTest(unittest.TestCase):
    def test_unchanged_roundtrip_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            Project(STOCK).save(tmp)
            self.assertEqual(tree_digest(STOCK), tree_digest(tmp))

    def test_forced_reencode_is_byte_identical(self):
        prj = Project(STOCK)
        for z in prj.images.values():
            z._packed = None
        for lib in prj.icons.values():
            lib.modified = True
            for ic in lib.icons:
                ic.set_raw(ic.raw)
        with tempfile.TemporaryDirectory() as tmp:
            prj.save(tmp)
            self.assertEqual(tree_digest(STOCK), tree_digest(tmp))

    def test_examples_build(self):
        for name in ('splash', 'machine_page', 'recolor_amber', 'klipper_branding', 'print_page_shortcuts', 'keypad_titles', 'english_only', 'input_limits', 'popup_cleanup', 'unsupported_features', 'spoolman', 'klipper_ui'):
            with self.subTest(example=name):
                prj = Project(STOCK)
                apply(prj, load_spec(os.path.join(EXAMPLES, name, 'spec.yaml')), log=lambda *a: None)
                with tempfile.TemporaryDirectory() as tmp:
                    prj.save(tmp)
                    again = Project(tmp)          # output must parse cleanly
                    self.assertEqual(again.touch.to_bytes(), prj.touch.to_bytes())
                    self.assertEqual(again.vars.to_bytes(), prj.vars.to_bytes())

    def test_branding(self):
        prj = Project(STOCK)
        apply(prj, load_spec(os.path.join(EXAMPLES, 'klipper_branding', 'spec.yaml')), log=lambda *a: None)
        with tempfile.TemporaryDirectory() as tmp:
            written = set(prj.save(tmp, changed_only=True))
        self.assertTrue({'image/0.zbmp', 'image/1.zbmp', 'image/108.zbmp', 'image/109.zbmp',
                         'icon/18.zico', 'bin/14.bin'} <= written, written)
        # no green status text and no stock cyan accent left in the field colours
        colours = {r.color for _, r in prj.vars.all() if r.color is not None}
        self.assertNotIn(0x87F0, colours)
        self.assertNotIn(0x87FF, colours)
        self.assertIn(0xFFFF, {r.color for r in prj.vars.pages[11] if r.vp == 0x3000})

    def test_print_page_shortcuts(self):
        prj = Project(STOCK)
        apply(prj, load_spec(os.path.join(EXAMPLES, 'klipper_ui', 'spec.yaml')), log=lambda *a: None)
        kinds = {(r.kind, r.vp, r.page_next) for r in prj.touch.page(1)}
        for vp in (0x7048, 0x704C, 0x704E):
            self.assertIn(('data_input', vp, None), kinds)
        self.assertIn(('return_key', 0x0000, 46), kinds)
        self.assertEqual(prj.touch.find(page=46, vp=0x4004, key=8)[0].page_next, 1)
        self.assertEqual(prj.touch.find(page=115, vp=0x4004, key=8)[0].page_next, 15)   # stock page untouched

    def test_keypad_titles(self):
        prj = Project(STOCK)
        apply(prj, load_spec(os.path.join(EXAMPLES, 'klipper_ui', 'spec.yaml')), log=lambda *a: None)
        self.assertIn(47, prj.images)
        self.assertIn(48, prj.images)
        self.assertEqual(len([r for r in prj.touch.page(47) if r.kind == 'keyboard_key']),
                         len([r for r in prj.touch.page(40) if r.kind == 'keyboard_key']))
        target = {0x7048: 47, 0x704C: 48, 0x9070: 55}           # 0x9070: fan_speed
        for r in prj.touch.records:
            if r.kind == 'data_input':
                self.assertEqual(r.keyboard_page, target.get(r.vp, 40), r.describe())
        self.assertEqual({r.page for r in prj.touch.records if r.kind == 'data_input' and r.vp == 0x7048},
                         {1, 14, 19, 91})
        # the title strip changed, the keypad itself did not
        a = prj.images[40].to_image(upright=True)
        b = prj.images[47].to_image(upright=True)
        self.assertNotEqual(a.crop((0, 0, 480, 100)).tobytes(), b.crop((0, 0, 480, 100)).tobytes())
        self.assertEqual(a.crop((0, 100, 480, 800)).tobytes(), b.crop((0, 100, 480, 800)).tobytes())

    def test_english_only(self):
        prj = Project(STOCK)
        apply(prj, load_spec(os.path.join(EXAMPLES, 'klipper_ui', 'spec.yaml')), log=lambda *a: None)
        self.assertEqual(prj.vpmem.get_word(0x5247), 1)
        self.assertEqual(prj.touch.find(page=121, vp=0x403E, key=4), [])
        self.assertEqual(len(prj.touch.find(page=121, vp=0x403E, key=5)), 1)      # other tiles stay
        self.assertFalse([r for r in prj.touch.records if r.page_next in (33, 120)])
        self.assertEqual(sum(1 for r in prj.vars.pages[121] if r.vp == 0x5247), 7)

    def test_input_limits(self):
        prj = Project(STOCK)
        apply(prj, load_spec(os.path.join(EXAMPLES, 'klipper_ui', 'spec.yaml')), log=lambda *a: None)
        for page in (1, 14):
            self.assertEqual(prj.touch.find(page=page, vp=0x7048)[0].limits, (0, 300))
        self.assertEqual(prj.touch.find(page=19, vp=0x7048)[0].limits, (0, 300))
        self.assertEqual(prj.touch.find(page=122, vp=0x7070)[0].limits, (185, 300))   # PID untouched

    def test_popup_cleanup(self):
        prj = Project(STOCK)
        apply(prj, load_spec(os.path.join(EXAMPLES, 'klipper_ui', 'spec.yaml')), log=lambda *a: None)
        self.assertEqual([r for r in prj.vars.pages[108] if list(r.pos) == [176, 458]], [])
        self.assertEqual(sum(1 for r in prj.vars.pages[26] if r.vp == 0x5247 and list(r.pos) != [0, 0]) > 0, True)
        im = prj.images[108].to_image(upright=True).convert('RGB')
        card = im.getpixel((400, 250))
        self.assertEqual(card, (0, 0, 0))                                              # card starts lower now
        self.assertTrue(all(im.getpixel((x, 330)) == im.getpixel((400, 330)) for x in range(40, 76)))
        self.assertNotEqual(im.getpixel((400, 330)), (0, 0, 0))
        self.assertEqual(len(prj.touch.page(108)), 1)                                   # button kept
        im = prj.images[109].to_image(upright=True).convert('RGB')
        self.assertEqual(im.getpixel((200, 250)), (0, 0, 0))                           # mascot / old card top
        self.assertEqual(prj.vars.pages[109][0].box, [118, 413, 440, 441])
        for page, vp, key in ((121, 0x400B, 0), (121, 0x4009, 0), (121, 0x403E, 7), (21, 0x4104, 4),
                              (132, 0x4104, 9), (132, 0x4105, 8), (122, 0x401F, 5), (125, 0x401F, 5)):
            self.assertIsNone(prj.touch.find(page=page, vp=vp, key=key)[0].page_next)
        self.assertEqual(prj.touch.find(page=21, vp=0x403E, key=8)[0].page_next, 122)

    def test_spoolman_tile(self):
        from crm4bridge import spoolman
        prj = Project(STOCK)
        apply(prj, load_spec(os.path.join(EXAMPLES, 'klipper_ui', 'spec.yaml')), log=lambda *a: None)
        for i in range(len(spoolman.COLOURS)):
            self.assertIsNotNone(prj.icons[18].get(20 + i))
        for i in range(len(spoolman.MATERIALS)):
            self.assertIsNotNone(prj.icons[18].get(50 + i))
        vps = {r.vp for r in prj.vars.pages[1]}
        self.assertTrue({0x9100, 0x9101, 0x9110, 0x9120} <= vps)
        for page in (9, 10, 11, 12):
            self.assertTrue({0x9100, 0x9101, 0x9130, 0x9140} <= {r.vp for r in prj.vars.pages[page]})
        sw = [r for r in prj.vars.pages[1] if r.vp == 0x9101][0].describe()
        self.assertEqual((sw['v_min'], sw['v_max'], sw['icon_min'], sw['icon_max'], sw['icon_lib']),
                         (0, len(spoolman.COLOURS) - 1, 20, 20 + len(spoolman.COLOURS) - 1, 18))
        self.assertEqual([r.pos for r in prj.vars.pages[1] if r.vp == 0x4227], [[90, 280]])

    def test_fan_speed_and_spool_picker(self):
        prj = Project(STOCK)
        apply(prj, load_spec(os.path.join(EXAMPLES, 'klipper_ui', 'spec.yaml')), log=lambda *a: None)
        for page in (14, 19):
            fan = prj.touch.find(page=page, vp=0x9070)
            self.assertEqual([(r.kind, r.keyboard_page, r.limits) for r in fan], [('data_input', 55, (0, 100))])
            self.assertEqual(prj.touch.find(page=page, vp=0x4004 if page == 14 else 0x4030,
                                            key=7 if page == 14 else 3), [])
        self.assertEqual(sorted(r.key for r in prj.touch.page(56)), [0, 1, 2, 3, 4, 5, 6, 0x10, 0x11])
        self.assertTrue(all(r.vp == 0x9060 for r in prj.touch.page(56)))
        self.assertTrue(all(r.page_next is None for r in prj.touch.page(56)))
        for page in (1, 9, 10, 11, 12):
            self.assertEqual(len(prj.touch.find(page=page, vp=0x9060, key=0x20)), 1)
        self.assertNotIn(0x40D3, {r.vp for r in prj.touch.page(56)})
        self.assertEqual(len([r for r in prj.vars.pages[56] if 0x9200 <= r.vp < 0x9300]), 24)

    def test_machine_page_contents(self):
        prj = Project(STOCK)
        apply(prj, load_spec(os.path.join(EXAMPLES, 'machine_page', 'spec.yaml')), log=lambda *a: None)
        self.assertIn(45, prj.images)
        keys = sorted(r.key for r in prj.touch.page(45) if r.vp == 0x9000)
        self.assertEqual(keys, [1])                     # E-STOP; the rest go through Yes/No pages
        self.assertEqual(prj.vpmem.get_text(0x9010, 40), 'waiting for host')
        self.assertEqual(prj.touch.find(page=121, vp=0x403E, key=9)[0].page_next, 45)
        for page, key, nxt in ((49, 3, 45), (50, 2, 45), (51, 4, None), (52, 5, None)):
            yes = prj.touch.find(page=page, vp=0x9000, key=key)
            self.assertEqual([r.page_next for r in yes], [nxt])
            self.assertEqual(prj.touch.find(page=page, vp=0x9000, key=0)[0].page_next, 45)
        self.assertEqual({r.page_next for r in prj.touch.page(45) if r.kind != 'return_key' or r.vp == 0}, {121, 49, 50, 51, 52})
        self.assertIn(0x9050, {r.vp for r in prj.vars.pages[53]})


if __name__ == '__main__':
    unittest.main()
