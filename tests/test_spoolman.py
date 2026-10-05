"""Spool -> screen values, and the bridge against the mock Moonraker's Spoolman endpoints."""
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

from crm4bridge import spoolman, ui
from crm4bridge.bridge import Bridge
from crm4bridge.config import Config
from crm4bridge.mock_moonraker import Printer, make_handler
from crm4bridge.moonraker import Moonraker


class ClassifyTest(unittest.TestCase):
    def badge(self, material, name=''):
        return spoolman.MATERIALS[spoolman.classify(material, name)[0]]

    def test_materials(self):
        self.assertEqual(self.badge('PLA', 'Basic White'), 'PLA')
        self.assertEqual(self.badge('PLA', 'Matte HS BLUE'), 'PLA-M')
        self.assertEqual(self.badge('PLA Matte'), 'PLA-M')
        self.assertEqual(self.badge('PLA-CF'), 'PLA-CF')
        self.assertEqual(self.badge('PLA+CF'), 'PLA-CF')
        self.assertEqual(self.badge('PLA', 'Carbon Fibre Black'), 'PLA-CF')
        self.assertEqual(self.badge('PLA', 'Black CF'), 'PLA-CF')
        self.assertEqual(self.badge('PETG'), 'PETG')
        self.assertEqual(self.badge('PETG-CF', 'Matte'), 'PETG-CF')
        self.assertEqual(self.badge('petg', 'Tough Grey CF'), 'PETG-CF')
        self.assertEqual(spoolman.classify('ASA', 'Red'), (0, 'ASA'))

    def test_colours(self):
        name = lambda h: spoolman.COLOURS[spoolman.nearest_colour(h)][0]
        self.assertEqual(name('FFFFFF'), 'white')
        self.assertEqual(name('#313131'), 'black')
        self.assertEqual(name('666465'), 'anthracite')
        self.assertEqual(name('5FB0C7'), 'light blue')
        self.assertEqual(name('E06640'), 'orange')
        self.assertEqual(name('AA846F'), 'wood')
        self.assertEqual(name(''), 'none')
        self.assertEqual(name('zz'), 'none')

    def test_describe(self):
        d = spoolman.describe({'id': 13, 'remaining_weight': 227.4, 'remaining_length': 73247,
                               'filament': {'name': 'Hyper Speed BLACK', 'material': 'PETG',
                                            'color_hex': '313131', 'vendor': {'name': 'AzureFilm'}}})
        self.assertEqual((spoolman.MATERIALS[d['badge']], d['name'], d['weight']),
                         ('PETG', 'Hyper Speed BLACK', '227 g'))
        self.assertEqual(d['detail'], '227 g | 73 m | AzureFilm')
        d = spoolman.describe({'id': 7, 'remaining_weight': 5, 'filament': {
            'name': 'Glitter Transparent Sample', 'material': 'ASA', 'multi_color_hexes': 'BF4140,FFFFFF'}},
            short_len=22)
        self.assertEqual(d['badge'], 0)
        self.assertEqual(d['short'], 'ASA Glitter Transpar..')
        self.assertEqual(len(d['short']), 22)
        self.assertEqual(spoolman.COLOURS[d['swatch']][0], 'red')
        self.assertEqual(spoolman.describe(None)['name'], 'No active spool')


class FakeLink:
    def __init__(self):
        self.sent = []

    def send(self, f):
        self.sent.append(f)
        return True

    def start(self):
        pass


class BridgeSpoolmanTest(unittest.TestCase):
    def setUp(self):
        self.pr = Printer(600)
        self.srv = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(self.pr))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.tmp = tempfile.TemporaryDirectory()
        url = f'http://127.0.0.1:{self.srv.server_address[1]}'
        self.moon = Moonraker(url)
        cfg = Config(None, {'dry_run': 'false', 'state_file': os.path.join(self.tmp.name, 's.json'),
                            'moonraker': url})
        self.link = FakeLink()
        self.b = Bridge(cfg, self.moon, self.link)

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.tmp.cleanup()

    def screen(self):
        words, texts = {}, {}
        for f in self.link.sent:
            p = f.payload()
            if len(p) == 2:
                words[f.vp] = int.from_bytes(p, 'big')
            else:
                texts[f.vp] = p.split(b'\0')[0].decode('gbk')
        return words, texts

    def test_client(self):
        self.assertEqual(self.moon.spoolman_status()['spool_id'], 3)
        self.assertEqual(self.moon.spoolman_spool(3)['filament']['material'], 'PETG')
        self.moon.spoolman_set_spool(4)
        self.assertEqual(self.pr.spool_id, 4)

    def test_active_spool_tile(self):
        self.b.poll_spoolman(force=True)
        w, t = self.screen()
        self.assertEqual(spoolman.MATERIALS[w[ui.VP_SPOOL_BADGE]], 'PETG')
        self.assertEqual(spoolman.COLOURS[w[ui.VP_SPOOL_SWATCH]][0], 'black')
        self.assertEqual(t[ui.TXT_SPOOL_NAME[0]], 'Hyper Speed Black')
        self.assertEqual(t[ui.TXT_SPOOL_WEIGHT[0]], '227 g')

        self.pr.spool_id = 4                           # changed in Mainsail
        self.b.poll_spoolman(force=True)
        w, t = self.screen()
        self.assertEqual(spoolman.MATERIALS[w[ui.VP_SPOOL_BADGE]], 'PLA-CF')

        self.pr.spool_id = None
        self.b.poll_spoolman(force=True)
        self.assertEqual(self.screen()[1][ui.TXT_SPOOL_NAME[0]], 'No active spool')

        self.pr.spool_id = 99
        self.b.poll_spoolman(force=True)
        self.assertEqual(self.screen()[1][ui.TXT_SPOOL_NAME[0]], 'Spool 99: not found')

        self.pr.spoolman_connected = False
        self.b.poll_spoolman(force=True)
        self.assertEqual(self.screen()[1][ui.TXT_SPOOL_NAME[0]], 'Spoolman offline')

    def test_interval(self):
        self.b.poll_spoolman()
        n = len(self.link.sent)
        self.pr.spool_id = 1
        self.b.poll_spoolman()                         # within spoolman_interval: no request, no change
        self.assertEqual(len(self.link.sent), n)


if __name__ == '__main__':
    unittest.main()
