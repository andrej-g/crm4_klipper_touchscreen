"""Thumbnail JPEG to VP 0xC000: frame layout, and the bridge against the mock Moonraker."""
import io
import os
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer

from crm4bridge import thumbnail, ui
from crm4bridge.bridge import Bridge
from crm4bridge.config import Config
from crm4bridge.mock_moonraker import Printer, make_handler
from crm4bridge.moonraker import Moonraker
from crm4ui import dgus


class FramesTest(unittest.TestCase):
    def test_layout(self):
        jpeg = bytes(range(256)) * 3 + b'\xff\xd9'                     # 770 bytes
        clear, chunks, header = thumbnail.frames(jpeg)
        self.assertEqual(clear.to_bytes(), bytes.fromhex('5aa50582c0000000'))
        self.assertEqual(len(chunks), 4)
        self.assertEqual([c.vp for c in chunks], [0xC002, 0xC07A, 0xC0F2, 0xC16A])
        self.assertTrue(all(len(c.to_bytes()) == 246 and c.to_bytes()[2] == 0xF3 for c in chunks))
        self.assertEqual(b''.join(c.payload() for c in chunks)[:770], jpeg)
        self.assertEqual(header.to_bytes(), bytes.fromhex('5aa50782c0005aa50302'))

    def test_to_jpeg(self):
        from PIL import Image
        png = io.BytesIO()
        Image.new('RGBA', (300, 200), (255, 0, 0, 255)).save(png, 'PNG')
        data = thumbnail.to_jpeg(png.getvalue())
        im = Image.open(io.BytesIO(data))
        self.assertEqual((im.format, im.size), ('JPEG', (300, 300)))
        self.assertNotIn('progressive', im.info)
        self.assertEqual(im.getpixel((150, 150))[0] > 200, True)       # red middle
        self.assertEqual(max(im.getpixel((150, 10))) < 30, True)       # black letterbox

    def test_pick_largest(self):
        meta = {'thumbnails': [{'width': 32, 'height': 32, 'relative_path': 'a'},
                               {'width': 300, 'height': 300, 'relative_path': 'b'}]}
        self.assertEqual(thumbnail.pick(meta), 'b')
        self.assertIsNone(thumbnail.pick({}))


class FakeLink:
    def __init__(self):
        self.sent, self.lock = [], threading.Lock()

    def send(self, f):
        with self.lock:
            self.sent.append(f)
        return True

    def start(self):
        pass


class BridgeThumbnailTest(unittest.TestCase):
    def setUp(self):
        thumbnail.GAP_S = 0.0
        self.pr = Printer(600)
        self.srv = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(self.pr))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.tmp = tempfile.TemporaryDirectory()
        url = f'http://127.0.0.1:{self.srv.server_address[1]}'
        cfg = Config(None, {'dry_run': 'true', 'moonraker': url, 'spoolman': 'false',
                            'state_file': os.path.join(self.tmp.name, 's.json')})
        self.link = FakeLink()
        self.b = Bridge(cfg, Moonraker(url), self.link)

    def tearDown(self):
        thumbnail.GAP_S = 0.025
        self.srv.shutdown()
        self.srv.server_close()
        self.tmp.cleanup()

    def wait_header(self, timeout=5):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            with self.link.lock:
                if any(f.vp == thumbnail.VP_THUMB and f.payload()[:2] == b'\x5a\xa5' for f in self.link.sent):
                    return True
            time.sleep(0.02)
        return False

    def mascot(self):
        vals = [int.from_bytes(f.payload(), 'big') for f in self.link.sent if f.vp == ui.VP_MASCOT]
        return vals[-1] if vals else None

    def test_preview_uploads_jpeg_and_hides_mascot(self):
        self.b.show_preview({'path': 'benchy.gcode'})
        self.assertTrue(self.wait_header())
        with self.link.lock:
            sent = list(self.link.sent)
        data = b''.join(f.payload() for f in sent if f.vp and 0xC002 <= f.vp < 0x10000 and f.cmd == 0x82)
        n = int.from_bytes(next(f.payload()[2:4] for f in sent if f.vp == thumbnail.VP_THUMB
                                and f.payload()[:2] == b'\x5a\xa5'), 'big')
        self.assertEqual(data[:2], b'\xff\xd8')                               # JPEG SOI
        self.assertEqual(data[n - 2:n], b'\xff\xd9')                          # ... and EOI at the stated length
        time.sleep(0.1)
        self.assertEqual(self.mascot(), ui.MASCOT_HIDDEN)
        self.assertEqual(self.b.thumb_file, 'benchy.gcode')

    def test_no_thumbnail_keeps_mascot(self):
        self.b.show_preview({'path': 'calibration cube.gcode'})
        time.sleep(0.5)
        self.assertFalse(any(f.vp == thumbnail.VP_THUMB for f in self.link.sent))
        self.assertEqual(self.mascot(), ui.MASCOT_SHOWN)

    def test_main_page_shows_mascot(self):
        self.b.show_preview({'path': 'benchy.gcode'})
        self.assertTrue(self.wait_header())
        time.sleep(0.1)
        self.b.set_page(ui.PAGE_MAIN)
        self.assertEqual(self.mascot(), ui.MASCOT_SHOWN)

    def test_emulator_shows_picture(self):
        stock = os.environ.get('CRM4_STOCK_PRIVATE')
        if not (stock and os.path.isdir(stock)):
            self.skipTest('CRM4_STOCK_PRIVATE not set')
        from crm4ui.emulator.screen import ScreenSim
        from crm4ui.project import Project
        self.b.show_preview({'path': 'benchy.gcode'})
        self.assertTrue(self.wait_header())
        sim = ScreenSim(Project(stock), start_page=11, lang=1)
        for f in list(self.link.sent):
            sim.handle_host(f)
        sim.page = 11
        im = sim.render()
        self.assertNotEqual(im.crop((88, 264, 388, 564)).getextrema(), ((0, 0), (0, 0), (0, 0)))


if __name__ == '__main__':
    unittest.main()
