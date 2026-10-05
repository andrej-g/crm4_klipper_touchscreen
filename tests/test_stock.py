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
        for name in ('splash', 'machine_page', 'recolor_amber', 'klipper_branding', 'print_page_shortcuts', 'keypad_titles', 'english_only', 'klipper_ui'):
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
        target = {0x7048: 47, 0x704C: 48}
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

    def test_machine_page_contents(self):
        prj = Project(STOCK)
        apply(prj, load_spec(os.path.join(EXAMPLES, 'machine_page', 'spec.yaml')), log=lambda *a: None)
        self.assertIn(45, prj.images)
        keys = sorted(r.key for r in prj.touch.page(45) if r.vp == 0x9000)
        self.assertEqual(keys, [1, 2, 3])
        self.assertEqual(prj.vpmem.get_text(0x9010, 40), 'waiting for host')
        self.assertEqual(prj.touch.find(page=121, vp=0x403E, key=9)[0].page_next, 45)


if __name__ == '__main__':
    unittest.main()
