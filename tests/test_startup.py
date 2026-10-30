"""Startup must fail in the main process before any printer commands or worker."""
import contextlib
import io
import socket
import threading
import unittest
from unittest import mock

from crm4bridge.config import Config
from crm4bridge.link import ScreenLink, _EMPTY_OK, parse_screen_spec
from crm4bridge.__main__ import main
from crm4bridge.bridge import Bridge
from crm4ui import dgus


class ConfigurationTest(unittest.TestCase):
    def test_invalid_specs_rejected_before_thread_creation(self):
        for spec in ('', ' ', 'serial:', 'serial:/dev/serial0@', 'serial:x@bad',
                     'serial:x@0', 'tcp:localhost', 'tcp::7901', 'tcp:host:0',
                     'tcp:host:65536', 'tcp:[]:7901', 'tcp:[::1:7901', 'http://host:7901'):
            with self.subTest(spec=spec), mock.patch('crm4bridge.link.threading.Thread') as thread:
                with self.assertRaises(ValueError):
                    Config(None, {'screen': spec})
                thread.assert_not_called()

    def test_valid_specs(self):
        self.assertEqual(parse_screen_spec('serial:/dev/serial0'), ('serial', '/dev/serial0', 115200))
        self.assertEqual(parse_screen_spec('tcp:[::1]:7901'), ('tcp', '::1', 7901))

    def test_bad_timeout(self):
        for value in ('0', '-1', 'nan', 'inf'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Config(None, {'screen_startup_timeout': value})

    def test_bad_or_credential_bearing_moonraker_url(self):
        for url in ('', 'file:/tmp/x', 'http://host:bad', 'http://host:65536',
                    'http://user:secret@host', 'http://host?token=secret'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                Config(None, {'moonraker': url})

    def test_cli_empty_screen_exits_without_bridge(self):
        with mock.patch('crm4bridge.__main__.Bridge') as bridge:
            with self.assertLogs('crm4bridge', level='ERROR') as logs:
                result = main(['--screen', ''])
            self.assertEqual(result, 2)
            self.assertIn('screen must not be empty', logs.output[-1])
            bridge.assert_not_called()

    def test_cli_missing_device_exits_nonzero(self):
        with mock.patch('crm4bridge.link.ScreenLink._open', side_effect=OSError('missing UART')):
            with self.assertLogs('crm4bridge', level='ERROR') as logs:
                result = main(['--screen', 'serial:/missing'])
            self.assertEqual(result, 1)
            self.assertIn('missing UART', logs.output[-1])

    def test_no_readiness_or_printer_poll_on_link_start_failure(self):
        moon, link = mock.Mock(), mock.Mock()
        link.start.side_effect = OSError('screen is off')
        bridge = Bridge(Config(None, {'state_file': ''}), moon, link)
        with mock.patch('crm4bridge.bridge.notify_ready') as ready:
            with self.assertRaises(OSError):
                bridge.run()
            ready.assert_not_called()
        self.assertEqual(moon.mock_calls, [])


class ReadinessTest(unittest.TestCase):
    def transport(self, reads):
        self.closed = False
        self.sent = []
        iterator = iter(reads)
        def close():
            self.closed = True
        return {'write': self.sent.append, 'read': lambda: next(iterator, _EMPTY_OK), 'close': close}

    def test_unpowered_screen_never_starts_worker(self):
        link = ScreenLink('serial:/fake', startup_timeout=0.01)
        transport = self.transport([])
        with mock.patch.object(link, '_open', return_value=transport):
            with mock.patch('crm4bridge.link.threading.Thread') as thread:
                with self.assertRaisesRegex(OSError, 'screen did not answer'):
                    link.start()
                thread.assert_not_called()
        self.assertTrue(self.closed)
        self.assertEqual(self.sent[0], dgus.read_words(0x0014, 1).to_bytes())

    def test_ack_noise_and_wrong_register_are_not_readiness(self):
        frames = [dgus.ACK.to_bytes(), dgus.reply_words(0x9060, 0x11).to_bytes(),
                  bytes.fromhex('5aa50483001401')]
        link = ScreenLink('serial:/fake', startup_timeout=0.01)
        with mock.patch.object(link, '_open', return_value=self.transport(frames)):
            with self.assertRaises(OSError):
                link._ready_io()
        self.assertTrue(self.closed)

    def test_fragmented_reply_then_worker(self):
        reply = dgus.reply_words(0x0014, 56).to_bytes()
        link = ScreenLink('serial:/fake')
        transport = self.transport([reply[:4], reply[4:]])
        with mock.patch.object(link, '_open', return_value=transport):
            with mock.patch('crm4bridge.link.threading.Thread') as thread:
                link.start()
                thread.return_value.start.assert_called_once()
        self.assertFalse(self.closed)

    def test_loopback_tcp_readiness(self):
        with socket.socket() as server:
            server.bind(('127.0.0.1', 0))
            server.listen()
            def serve():
                with server.accept()[0] as connection:
                    query = bytearray()
                    while len(query) < 7:
                        query.extend(connection.recv(7))
                    if query == dgus.read_words(0x0014, 1).to_bytes():
                        connection.sendall(dgus.reply_words(0x0014, 1).to_bytes())
            worker = threading.Thread(target=serve)
            worker.start()
            link = ScreenLink(f'tcp:127.0.0.1:{server.getsockname()[1]}', startup_timeout=1)
            transport = link._ready_io()
            transport['close']()
            worker.join(timeout=2)
            self.assertFalse(worker.is_alive())


if __name__ == '__main__':
    unittest.main()
