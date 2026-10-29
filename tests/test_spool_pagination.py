"""Real stock arrow semantics and built-UI clicks through to bridge pagination."""
import os
import unittest

from crm4ui import dgus
from crm4ui.project import Project
from crm4ui.formats.touch import TouchConfig
from crm4ui.emulator import ScreenSim
from crm4ui.spec import apply, load_spec
from crm4bridge import ui
from crm4bridge.bridge import Bridge
from crm4bridge.config import Config
from test_bridge import FakeLink, FakeMoon

STOCK = os.environ.get('CRM4_STOCK_PRIVATE')


@unittest.skipUnless(STOCK and os.path.isdir(STOCK), 'CRM4_STOCK_PRIVATE not set')
class SpoolPaginationTest(unittest.TestCase):
    def test_stock_fd_arrow_changes_page_without_upload(self):
        screen = ScreenSim(Project(STOCK), start_page=3, lang=1)
        sent = []
        screen.send = sent.append
        screen.touch(365, 745)
        self.assertEqual(screen.page, 4)
        self.assertEqual(sent, [])

    def test_built_ui_clicks_traverse_three_pages_and_clamp(self):
        project = Project(STOCK)
        spec = os.path.join(os.path.dirname(__file__), '..', 'examples', 'klipper_ui', 'spec.yaml')
        apply(project, load_spec(spec), log=lambda *a: None)
        # Exercise the serialized touch records consumed by the physical screen.
        project.touch = TouchConfig.from_bytes(project.touch.to_bytes())
        for key in (0x10, 0x11):
            records = project.touch.find(page=56, vp=ui.K_SPOOL, key=key)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].code, 0xFE05)
            self.assertIsNone(records[0].page_next)
        self.assertFalse(any(r.data[14] == 0xFD for r in project.touch.page(56)))
        screen = ScreenSim(project, start_page=1, lang=1)
        moon, link = FakeMoon(), FakeLink()
        moon.spoolman_spools = lambda: [
            {'id': i, 'filament': {'name': f'Spool {i}', 'material': 'PLA'}}
            for i in range(1, 14)]
        bridge = Bridge(Config(None, {'dry_run': 'true', 'state_file': ''}), moon, link)
        bridge.page = 1
        screen.send = bridge.handle_frame

        def send(frame, byte_gap=0):
            link.sent.append(frame)
            screen.handle_host(frame)
            return True
        link.send = send
        screen.touch(240, 245)  # Open picker from the actual tile hitbox.
        self.assertEqual(screen.page, 56)
        for expected in (2, 3, 3):
            screen.touch(365, 745)
            self.assertEqual(bridge.spool_page, expected - 1)
            self.assertEqual(screen.text(*ui.TXT_SPOOL_PAGE), f'{expected}/3')
        # Newest first: third page has only spool 1 and five cleared rows.
        self.assertEqual(screen.text(*ui.TXT_SPOOL_ROW_NAME[0]), 'Spool 1')
        self.assertEqual(screen.text(*ui.TXT_SPOOL_ROW_NAME[1]), '')
        for expected in (2, 1, 1):
            screen.touch(110, 745)
            self.assertEqual(bridge.spool_page, expected - 1)
            self.assertEqual(screen.text(*ui.TXT_SPOOL_PAGE), f'{expected}/3')
        screen.touch(70, 35)
        self.assertEqual(screen.page, 1)


if __name__ == '__main__':
    unittest.main()
