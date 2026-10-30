"""Readiness notification uses the main process and is optional outside systemd."""
import importlib.util
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location(
    'bridge_service', Path(__file__).resolve().parents[1] / 'src/crm4bridge/service.py')
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)


class NotificationTest(unittest.TestCase):
    def test_no_notification_outside_service(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(service.socket, 'socket') as factory:
            service.notify_ready()
            factory.assert_not_called()

    @unittest.skipUnless(sys.platform == 'linux', 'Unix domain notification socket')
    def test_real_notification_socket(self):
        with tempfile.TemporaryDirectory() as temporary:
            address = str(Path(temporary) / 'notify')
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as listener:
                listener.bind(address)
                listener.settimeout(1)
                with mock.patch.dict(os.environ, {'NOTIFY_SOCKET': address}):
                    service.notify_ready()
                self.assertIn(b'READY=1', listener.recv(512))


if __name__ == '__main__':
    unittest.main()
