"""Screen link: a serial port (real screen) or TCP (the emulator)."""
import logging
import queue
import socket
import threading
import time
import math

from crm4ui import dgus

log = logging.getLogger('crm4bridge.link')


def parse_screen_spec(spec):
    """Validate before starting threads or opening a device."""
    if not isinstance(spec, str) or not spec.strip():
        raise ValueError('screen must not be empty (use serial:PORT[@baud] or tcp:HOST:PORT)')
    kind, _, arg = spec.strip().partition(':')
    if kind == 'serial':
        port, sep, baud = arg.partition('@')
        try:
            speed = int(baud) if sep else 115200
        except ValueError:
            raise ValueError('screen serial baud must be a positive integer') from None
        if not port.strip() or speed <= 0:
            raise ValueError('screen serial port and positive baud are required')
        return kind, port.strip(), speed
    if kind == 'tcp':
        host, sep, port = arg.rpartition(':')
        try:
            number = int(port)
        except ValueError:
            raise ValueError('screen TCP port must be an integer from 1 to 65535') from None
        if not sep or not host.strip() or not 1 <= number <= 65535:
            raise ValueError('screen TCP host and port (1..65535) are required')
        host = host.strip()
        if host.startswith('[') != host.endswith(']'):
            raise ValueError('screen TCP IPv6 brackets are unbalanced')
        host = host.strip('[]')
        if not host:
            raise ValueError('screen TCP host is required')
        return kind, host, number
    raise ValueError('bad screen spec (use serial:PORT[@baud] or tcp:HOST:PORT)')


class ScreenLink:
    """Sends DGUS frames and delivers received frames to ``self.rx`` (a Queue).

    spec: ``serial:/dev/ttyAMA0[@115200]`` or ``tcp:host:port``. Reconnects
    automatically; ``on_connect`` is called after every (re)connection so the
    bridge can repaint the screen.
    """

    def __init__(self, spec, on_connect=None, startup_timeout=5.0):
        self.spec = spec
        self.endpoint = parse_screen_spec(spec)
        if not math.isfinite(startup_timeout) or startup_timeout <= 0:
            raise ValueError('screen_startup_timeout must be finite and greater than zero')
        self.startup_timeout = startup_timeout
        self.rx = queue.Queue()
        self.on_connect = on_connect
        self._io = None
        self._lock = threading.Lock()
        self.connected = threading.Event()
        self.tx_bytes = 0

    def start(self):
        # Refuse startup synchronously: a UART can open even with no powered screen.
        io = self._ready_io()
        threading.Thread(target=self._run, args=(io,), name='screen-link', daemon=True).start()

    def send(self, frame: dgus.Frame, byte_gap=0.0):
        """Send one frame. ``byte_gap`` > 0 writes the bytes one at a time with that
        many seconds between them (serial links only: the stock mainboard spaces the
        bytes of its curve-buffer writes ~800 us apart; see crm4bridge.curve). On TCP
        the kernel coalesces writes anyway, so the frame goes out as a whole."""
        data = frame.to_bytes()
        with self._lock:
            io = self._io
            if io is None:
                return False
            try:
                if byte_gap > 0 and io.get('paced'):
                    for i in range(len(data)):
                        io['write'](data[i:i + 1])
                        io['flush']()
                        time.sleep(byte_gap)
                else:
                    io['write'](data)
                self.tx_bytes += len(data)
                return True
            except OSError as e:
                log.warning('screen write failed: %s', e)
                self._io = None
                self.connected.clear()
                return False

    def _open(self):
        kind, address, number = self.endpoint
        if kind == 'tcp':
            s = socket.create_connection((address, number), timeout=self.startup_timeout)
            s.settimeout(0.1)
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            def read():
                try:
                    return s.recv(4096)
                except socket.timeout:
                    return _EMPTY_OK
            return {'write': s.sendall, 'read': read, 'close': s.close, 'paced': False}
        if kind == 'serial':
            import serial
            ser = serial.Serial(address, number, timeout=0.1, write_timeout=self.startup_timeout)
            return {'write': ser.write, 'read': lambda: ser.read(256) or _EMPTY_OK, 'close': ser.close,
                    'flush': ser.flush, 'paced': True}
        raise AssertionError('unvalidated screen endpoint')

    def _ready_io(self):
        io = self._open()
        try:
            parser = dgus.Parser()
            deadline = time.monotonic() + self.startup_timeout
            next_query = 0.0
            while time.monotonic() < deadline:
                now = time.monotonic()
                if now >= next_query:
                    io['write'](dgus.read_words(0x0014, 1).to_bytes())
                    next_query = now + 0.5
                data = io['read']()
                if data is _EMPTY_OK:
                    continue
                if not data:
                    raise OSError('screen connection closed during startup')
                for frame in parser.feed(data):
                    if (frame.cmd == dgus.CMD_READ and frame.vp == 0x0014
                            and len(frame.data) == 5 and frame.data[2] == 1):
                        return io
            raise OSError(f'screen did not answer the page query within {self.startup_timeout:g}s; '
                          'check screen power, UART wiring and baud')
        except BaseException:
            io['close']()
            raise

    def _run(self, io=None):
        while True:
            if io is None:
                try:
                    io = self._ready_io()
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
            io = None
            time.sleep(1)


class _Empty(bytes):
    """Marker for 'serial read timed out' (distinct from a closed TCP socket)."""


_EMPTY_OK = _Empty()
