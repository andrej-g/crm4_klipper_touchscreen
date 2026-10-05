"""Screen link: a serial port (real screen) or TCP (the emulator)."""
import logging
import queue
import socket
import threading
import time

from crm4ui import dgus

log = logging.getLogger('crm4bridge.link')


class ScreenLink:
    """Sends DGUS frames and delivers received frames to ``self.rx`` (a Queue).

    spec: ``serial:/dev/ttyAMA0[@115200]`` or ``tcp:host:port``. Reconnects
    automatically; ``on_connect`` is called after every (re)connection so the
    bridge can repaint the screen.
    """

    def __init__(self, spec, on_connect=None):
        self.spec = spec
        self.rx = queue.Queue()
        self.on_connect = on_connect
        self._io = None
        self._lock = threading.Lock()
        self.connected = threading.Event()
        self.tx_bytes = 0

    def start(self):
        threading.Thread(target=self._run, name='screen-link', daemon=True).start()

    def send(self, frame: dgus.Frame):
        data = frame.to_bytes()
        with self._lock:
            io = self._io
            if io is None:
                return False
            try:
                io['write'](data)
                self.tx_bytes += len(data)
                return True
            except OSError as e:
                log.warning('screen write failed: %s', e)
                self._io = None
                self.connected.clear()
                return False

    def _open(self):
        kind, _, arg = self.spec.partition(':')
        if kind == 'tcp':
            host, _, port = arg.rpartition(':')
            s = socket.create_connection((host or '127.0.0.1', int(port)), timeout=5)
            s.settimeout(None)
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            return {'write': s.sendall, 'read': lambda: s.recv(4096), 'close': s.close}
        if kind == 'serial':
            import serial
            port, _, baud = arg.partition('@')
            ser = serial.Serial(port, int(baud or 115200), timeout=0.1)
            return {'write': ser.write, 'read': lambda: ser.read(256) or _EMPTY_OK, 'close': ser.close}
        raise ValueError(f'bad screen spec {self.spec!r} (use serial:PORT[@baud] or tcp:HOST:PORT)')

    def _run(self):
        while True:
            try:
                io = self._open()
            except OSError as e:
                log.info('screen link %s not available (%s); retrying', self.spec, e)
                time.sleep(2)
                continue
            with self._lock:
                self._io = io
            self.connected.set()
            log.info('screen link up: %s', self.spec)
            if self.on_connect:
                self.on_connect()
            parser = dgus.Parser()
            try:
                while True:
                    data = io['read']()
                    if data is _EMPTY_OK:
                        continue
                    if not data:
                        raise OSError('connection closed')
                    for f in parser.feed(data):
                        if not f.is_ack:
                            self.rx.put(f)
            except OSError as e:
                log.warning('screen link lost: %s', e)
            with self._lock:
                self._io = None
            self.connected.clear()
            try:
                io['close']()
            except OSError:
                pass
            time.sleep(1)


class _Empty(bytes):
    """Marker for 'serial read timed out' (distinct from a closed TCP socket)."""


_EMPTY_OK = _Empty()
