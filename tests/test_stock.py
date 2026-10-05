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
        for name in ('splash', 'machine_page', 'recolor_amber', 'klipper_branding'):
            with self.subTest(example=name):
                prj = Project(STOCK)
                apply(prj, load_spec(os.path.join(EXAMPLES, name, 'spec.yaml')), log=lambda *a: None)
                with tempfile.TemporaryDirectory() as tmp:
                    prj.save(tmp)
                    again = Project(tmp)          # output must parse cleanly
                    self.assertEqual(again.touch.to_bytes(), prj.touch.to_bytes())
                    self.assertEqual(again.vars.to_bytes(), prj.vars.to_bytes())

    def test_branding_only_touches_listed_files(self):
        prj = Project(STOCK)
        apply(prj, load_spec(os.path.join(EXAMPLES, 'klipper_branding', 'spec.yaml')), log=lambda *a: None)
        with tempfile.TemporaryDirectory() as tmp:
            written = prj.save(tmp, changed_only=True)
        expected = {'image/1.zbmp', 'image/108.zbmp', 'image/109.zbmp', 'icon/18.zico'}
        if os.path.exists(os.path.join(EXAMPLES, 'klipper_branding', 'splash.png')):
            expected.add('image/0.zbmp')
        self.assertTrue(set(written) <= expected | {'image/0.zbmp'}, written)
        self.assertTrue(expected - {'image/0.zbmp'} <= set(written), written)

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
