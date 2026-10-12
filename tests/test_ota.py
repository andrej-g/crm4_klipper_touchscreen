"""Screen update protocol: packets, sender against the receiver, and the emulator."""
import os
import shutil
import socket
import tempfile
import threading
import time
import unittest

from crm4ui import ota


def _write(p, data):
    with open(p, 'wb') as fh:
        fh.write(data)


def _read(p):
    with open(p, 'rb') as fh:
        return fh.read()


class PacketTest(unittest.TestCase):
    def test_layout_and_checksum(self):
        p = ota.packet(3, b'\x01\x02')
        self.assertEqual(len(p), 2052)
        self.assertEqual(p[:4], bytes([3, 0xFC, 1, 2]))
        s = sum(p[:2050])
        self.assertEqual(p[2050:], bytes([~(s >> 8) & 0xFF, ~s & 0xFF]))
        self.assertEqual(ota.check_packet(p), (3, b'\x01\x02'.ljust(2048, b'\0')))
        bad = bytearray(p)
        bad[100] ^= 1
        self.assertIsNone(ota.check_packet(bytes(bad)))

    def test_packet_count(self):
        self.assertEqual([ota.packet_count(n) for n in (0, 1, 2047, 2048, 4097)], [1, 1, 1, 2, 3])

    def test_plan_order_and_filter(self):
        with tempfile.TemporaryDirectory() as d:
            for rel in ('config.txt', 'firmware.zlib', 'bin/14.bin', 'bin/13.bin', 'image/1.zbmp',
                        'icon/18.zico', 'truefont/font.ttf', 'truefont/truefont.ini', 'notes.md'):
                os.makedirs(os.path.join(d, os.path.dirname(rel)), exist_ok=True)
                _write(os.path.join(d, rel), b'x')
            names = [(dst, n) for _, dst, n in ota.plan(d)]
            self.assertEqual(names, [('', 'config.txt'), ('\\bin', '13.bin'), ('\\bin', '14.bin'),
                                     ('\\icon', '18.zico'), ('\\image', '1.zbmp'),
                                     ('\\truefont', 'font.ttf'), ('\\truefont', 'truefont.ini')])
            only = [n for _, _, n in ota.plan(d, {'bin/14.bin'})]
            self.assertEqual(only, ['14.bin'])


class FakeScreen(threading.Thread):
    """Receiver on one end of a socket pair; drops packet ``drop`` once to test retries."""

    def __init__(self, sock, drop=None):
        super().__init__(daemon=True)
        self.sock, self.files, self.rebooted, self.drop = sock, {}, False, drop
        self.rx = ota.Receiver(self.files.__setitem__, self._reboot)

    def _reboot(self):
        self.rebooted = True

    def run(self):
        seen = 0
        while True:
            try:
                data = self.sock.recv(65536)
            except OSError:
                return
            if not data:
                return
            if self.drop is not None and self.rx.file and len(data) >= 2052:
                seen += 1
                if seen == self.drop:
                    data = data[:100] + bytes([data[100] ^ 0xFF]) + data[101:]   # corrupt once
            replies, _ = self.rx.feed(data)
            if replies:
                self.sock.sendall(replies)


class SenderTest(unittest.TestCase):
    def run_update(self, files, drop=None):
        a, b = socket.socketpair()
        screen = FakeScreen(b, drop)
        screen.start()
        sender = ota.Sender(ota.Port.from_socket(a), log=lambda *x: None, pause=0.01)
        sender.run(files)
        a.close()
        return screen

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, 'bin'))
            blobs = {'config.txt': b'R1=07\n', 'bin/13.bin': os.urandom(5000), 'bin/22.bin': bytes(4096)}
            for rel, data in blobs.items():
                _write(os.path.join(d, rel), data)
            screen = self.run_update(ota.plan(d), drop=2)
        got = {ota.screen_path_to_rel(k): v for k, v in screen.files.items()}
        self.assertEqual(got, blobs)
        self.assertTrue(screen.rebooted)
        self.assertEqual(screen.rx.bad_packets, 1)
        self.assertFalse(screen.rx.active)

    def test_no_answer(self):
        a, b = socket.socketpair()
        sender = ota.Sender(ota.Port.from_socket(a), log=lambda *x: None, pause=0.01, cmd_timeout=0.05)
        with self.assertRaises(ota.OtaError):
            sender.run([(__file__, '', 'x.txt')])
        a.close()
        b.close()

    def test_receiver_passes_dgus_through(self):
        rx = ota.Receiver()
        frame = bytes.fromhex('5aa5058200245a24')          # contains '$' bytes
        self.assertEqual(rx.feed(frame), (b'', frame))
        self.assertEqual(rx.feed(b'$hmiask#'), (b'$ok#', b''))


STOCK = os.environ.get('CRM4_STOCK_PRIVATE')


@unittest.skipUnless(STOCK and os.path.isdir(STOCK), 'CRM4_STOCK_PRIVATE not set')
class EmulatorFlashTest(unittest.TestCase):
    def test_flash_reloads_emulator(self):
        from crm4ui.emulator.screen import ScreenSim
        from crm4ui.emulator.server import Link
        from crm4ui.project import Project
        with tempfile.TemporaryDirectory() as tmp:
            ui = os.path.join(tmp, 'private')
            shutil.copytree(STOCK, ui)
            sim = ScreenSim(Project(ui), lang=1)
            srv = socket.socket()
            srv.bind(('127.0.0.1', 0))
            port = srv.getsockname()[1]
            srv.close()
            link = Link(sim, f'tcp:127.0.0.1:{port}')
            link.start()
            time.sleep(0.2)
            new = os.path.join(tmp, 'new')
            shutil.copytree(ui, new)
            cfg = _read(os.path.join(new, 'config.txt')) + b'\nRB1=01\n'
            _write(os.path.join(new, 'config.txt'), cfg)
            p = ota.Port(f'tcp:127.0.0.1:{port}')
            ota.Sender(p, log=lambda *x: None, pause=0.01).run(ota.plan(new, {'config.txt'}))
            p.close()
            time.sleep(0.2)
            self.assertEqual(sim.project.root, ui + '.ota')
            self.assertEqual(_read(os.path.join(ui + '.ota', 'config.txt')), cfg)
            self.assertEqual(sim.page, 0)


if __name__ == '__main__':
    unittest.main()
