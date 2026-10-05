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
        self.assertEqual(self.badge('ABS'), 'ABS')
        self.assertEqual(self.badge('ABS+'), 'ABS')
        self.assertEqual(self.badge('ASA', 'Red'), 'ASA')
        self.assertEqual(self.badge('TPU 95A'), 'TPU')
        self.assertEqual(self.badge('TPE'), 'TPU')
        self.assertEqual(self.badge('PA12-CF'), 'PA')
        self.assertEqual(self.badge('Nylon'), 'PA')
        self.assertEqual(self.badge('PLA', 'AzureFilm BAMBOO sample'), 'PLA-W')
        self.assertEqual(self.badge('PLA', 'Wood Walnut'), 'PLA-W')
        self.assertEqual(self.badge('PLA-W'), 'PLA-W')
        self.assertEqual(spoolman.classify('PC', 'Clear'), (0, 'PC'))
        self.assertEqual(spoolman.classify('HIPS'), (0, 'HIPS'))

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
            'name': 'Glitter Transparent Sample', 'material': 'PC', 'multi_color_hexes': 'BF4140,FFFFFF'}},
            short_len=22)
        self.assertEqual(d['badge'], 0)
        self.assertEqual(d['short'], 'PC Glitter Transpare..')
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



class HostControlTest(BridgeSpoolmanTest):
    """Machine page host actions against the mock Moonraker and a fake Tasmota plug."""

    def setUp(self):
        super().setUp()
        from http.server import BaseHTTPRequestHandler
        self.plug_calls = []
        calls = self.plug_calls

        class Plug(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                calls.append(self.path)
                body = b'{"Delay":600,"POWER1":"OFF"}'
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        self.plug = ThreadingHTTPServer(('127.0.0.1', 0), Plug)
        threading.Thread(target=self.plug.serve_forever, daemon=True).start()
        self.b.jobs = _Inline()

    def tearDown(self):
        self.plug.shutdown()
        self.plug.server_close()
        super().tearDown()

    def pages(self):
        from crm4ui import dgus
        return [f.payload()[3] for f in self.link.sent if f.vp == dgus.VP_PAGE]

    def test_reboot(self):
        self.b.handle_frame(_key(ui.K_MACHINE, 4))
        self.assertEqual(self.pages()[-1], ui.PAGE_HOST_REBOOT)
        self.assertEqual(self.pr.host_actions, ['reboot'])

    def test_shutdown_with_plug(self):
        self.b.cfg.shutdown_plug = f'127.0.0.1:{self.plug.server_address[1]}'
        self.b.cfg.shutdown_plug_user, self.b.cfg.shutdown_plug_password = 'admin', 'pw'
        self.b.handle_frame(_key(ui.K_MACHINE, 5))
        self.assertEqual(self.pages()[-1], ui.PAGE_HOST_SHUTDOWN)
        self.assertEqual(self.pr.host_actions, ['shutdown'])
        self.assertEqual(len(self.plug_calls), 1)
        from urllib.parse import parse_qs, urlparse
        q = parse_qs(urlparse(self.plug_calls[0]).query)
        self.assertEqual(q['cmnd'], ['Backlog Delay 600; Power1 Off'])
        self.assertEqual((q['user'], q['password']), (['admin'], ['pw']))
        self.assertIn('off in 60 s', self.screen()[1][ui.TXT_SHUTDOWN_NOTE[0]])

    def test_plug_unreachable_aborts_shutdown(self):
        self.b.cfg.shutdown_plug = '127.0.0.1:9'
        self.b.handle_frame(_key(ui.K_MACHINE, 5))
        self.assertEqual(self.pr.host_actions, [])
        self.assertEqual(self.pages()[-1], ui.PAGE_ERROR)

    def test_refused_while_printing(self):
        self.b.print_state = 'printing'
        for k in (4, 5):
            self.b.handle_frame(_key(ui.K_MACHINE, k))
        self.assertEqual(self.pr.host_actions, [])
        self.assertEqual(self.pages()[-1], ui.PAGE_MACHINE)
        self.assertEqual(self.screen()[1][ui.TXT_MACHINE_MSG[0]], 'Stop the print first')

    def test_dry_run(self):
        self.b.cfg.dry_run = True
        self.b.cfg.shutdown_plug = f'127.0.0.1:{self.plug.server_address[1]}'
        self.b.handle_frame(_key(ui.K_MACHINE, 5))
        self.assertEqual((self.pr.host_actions, self.plug_calls), ([], []))


class _Inline:
    def submit(self, fn):
        fn()


def _key(vp, k):
    from crm4ui import dgus
    return dgus.reply_words(vp, k)



class SpoolPickerTest(BridgeSpoolmanTest):
    def setUp(self):
        super().setUp()
        self.b.jobs = _Inline()
        self.b.page = 1
        self.b.poll_spoolman(force=True)

    def rows(self):
        w, t = self.screen()
        return [t.get(vpn[0], '') for vpn in ui.TXT_SPOOL_ROW_NAME], w, t

    def test_open_page_and_pick(self):
        from crm4ui import dgus
        self.b.handle_frame(dgus.reply_words(ui.K_SPOOL, 0x20))
        names, w, t = self.rows()
        self.assertEqual(names[0], 'Hyper Speed Black')                      # active first
        self.assertEqual(names[1:3], ['Basic White', 'Matte Sky Blue'])        # then most recently used
        self.assertTrue(t[ui.TXT_SPOOL_ROW_DETAIL[0][0]].startswith('active | 227 g | Dryer'))
        self.assertEqual(spoolman.MATERIALS[w[ui.VP_SPOOL_ROW_BADGE[2]] - 1], 'PLA-M')
        self.assertEqual(t[ui.TXT_SPOOL_PAGE[0]], '1/2')
        self.b.handle_frame(dgus.reply_words(ui.K_SPOOL, 0x11))              # next page: 1 spool
        names, w, t = self.rows()
        self.assertEqual(t[ui.TXT_SPOOL_PAGE[0]], '2/2')
        self.assertEqual([bool(n) for n in names], [True] + [False] * 5)
        self.assertEqual(w[ui.VP_SPOOL_ROW_SWATCH[1]], 0)                    # empty row: no icon
        self.b.handle_frame(dgus.reply_words(ui.K_SPOOL, 1))                 # pick it
        self.assertNotEqual(self.pr.spool_id, 3)
        picked = self.pr.spool_id
        self.assertEqual(self.screen()[1][ui.TXT_SPOOL_NAME[0]],
                         spoolman.describe(self.moon.spoolman_spool(picked))['name'])
        pages = [f.payload()[3] for f in self.link.sent if f.vp == 0x0084]
        self.assertEqual(pages[-2:], [ui.PAGE_SPOOLS, 1])                     # back where it came from

    def test_back(self):
        from crm4ui import dgus
        self.b.page = 11
        self.b.handle_frame(dgus.reply_words(ui.K_SPOOL, 0x20))
        self.b.handle_frame(dgus.reply_words(ui.K_SPOOL, 0))
        pages = [f.payload()[3] for f in self.link.sent if f.vp == 0x0084]
        self.assertEqual(pages[-2:], [ui.PAGE_SPOOLS, 11])
        self.assertEqual(self.pr.spool_id, 3)


class FanTest(unittest.TestCase):
    def test_fan_percent(self):
        import test_bridge as tb
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = Config(None, {'dry_run': 'false', 'state_file': os.path.join(tmp.name, 's.json')})
        moon, link = tb.FakeMoon(), tb.FakeLink()
        b = Bridge(cfg, moon, link)
        b.jobs = _Inline()
        moon.status['fan'] = {'speed': 0.5}
        b.poll()
        self.assertEqual(link.words()[ui.VP_FAN_PCT], 50)
        from crm4ui import dgus
        for v in (40, 0, 100):
            b.handle_frame(dgus.reply_words(ui.VP_FAN_PCT, v))
        self.assertEqual([c[1] for c in moon.calls if c[0] == 'gcode'], ['M106 S102', 'M107', 'M106 S255'])


if __name__ == '__main__':
    unittest.main()
