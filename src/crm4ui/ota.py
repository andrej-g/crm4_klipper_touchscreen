"""Screen UI update over the serial link (the Creality bootloader's "DWIN_TO_DACAI" path).

Protocol (from the bootloader RE, ``Hardware/Touchscreen/CR-M4 Stock Touchscreen -
Screen OTA protocol.md`` in the project notes); everything at 115200 8N1:

* ASCII commands, no line ending, each answered by exactly ``$ok#``::

    $cfgenter#                                   enter download mode, then wait 1 s
    $file,3:<dir>\\<name>,<size>,2052,115200#     per file; <dir> is '', \\bin, \\icon, \\image, \\truefont
    $reboot#                                     after all files (1 s pause before)
    $cfgexit#                                    leave download mode (1 s pause before)

* after ``$file``: floor(size/2048)+1 packets of 2052 bytes::

    id, ~id, 2048 data bytes (zero padded), ~sum16 big-endian (sum of bytes 0..2049)

  each answered by the echo ``id ~id``.

Only ``.txt .bin .zico .zbmp .ttf .ini`` files are sent, directory by directory:
the root of ``private/`` (``config.txt``), then ``bin``, ``icon``, ``image``,
``truefont``. ``firmware.zlib`` is never sent.

Unverified on the real screen: whether files that are not sent survive, whether
order matters, how fast ``$ok#`` comes back. Keep the stock files on an SD card.
"""
import os
import socket
import time

PKT_DATA = 2048
PKT_SIZE = PKT_DATA + 4
DIRS = (('', ''), ('bin', '\\bin'), ('icon', '\\icon'), ('image', '\\image'), ('truefont', '\\truefont'))
EXTS = ('.txt', '.bin', '.zico', '.zbmp', '.ttf', '.ini')
OK = b'$ok#'


class OtaError(Exception):
    pass


# ---- packets -------------------------------------------------------------------------
def packet(i, chunk):
    if len(chunk) > PKT_DATA:
        raise ValueError('chunk too long')
    body = bytes([i & 0xFF, ~i & 0xFF]) + chunk.ljust(PKT_DATA, b'\0')
    s = sum(body)
    return body + bytes([~(s >> 8) & 0xFF, ~s & 0xFF])


def check_packet(data):
    """(id, payload) of a received packet, or None if the id or checksum is wrong."""
    if len(data) != PKT_SIZE or data[1] != (~data[0] & 0xFF):
        return None
    s = sum(data[:PKT_DATA + 2])
    if data[PKT_DATA + 2] != (~(s >> 8) & 0xFF) or data[PKT_DATA + 3] != (~s & 0xFF):
        return None
    return data[0], data[2:PKT_DATA + 2]


def packet_count(size):
    return size // PKT_DATA + 1                    # stock: always one more (possibly empty)


def plan(private, only=None):
    """[(local path, screen dir, name)] in the bootloader's order. ``only``: set of
    paths relative to private/ (forward slashes) to restrict the update to."""
    out = []
    for sub, dst in DIRS:
        d = os.path.join(private, sub) if sub else private
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            p = os.path.join(d, name)
            rel = f'{sub}/{name}' if sub else name
            if not os.path.isfile(p) or not any(e in name for e in EXTS):
                continue
            if only is not None and rel not in only:
                continue
            out.append((p, dst, name))
    return out


# ---- transport -------------------------------------------------------------------------
class Port:
    """``serial:/dev/ttyAMA0[@115200]`` (the real screen) or ``tcp:host:port`` (the emulator)."""

    def __init__(self, spec):
        self.spec = spec
        kind, _, arg = spec.partition(':')
        if kind == 'serial':
            import serial
            dev, _, baud = arg.partition('@')
            self._ser = serial.Serial(dev, int(baud or 115200), timeout=0)
            self.write = self._ser.write
            self._read = lambda: self._ser.read(4096)
            self.close = self._ser.close
        elif kind == 'tcp':
            host, _, port = arg.rpartition(':')
            self._sock = socket.create_connection((host or '127.0.0.1', int(port)), timeout=5)
            self._sock.setblocking(False)
            self.write = self._sock.sendall
            self._read = self._sock_read
            self.close = self._sock.close
        else:
            raise ValueError(f'bad port {spec!r} (serial:PORT[@baud] or tcp:HOST:PORT)')

    @classmethod
    def from_socket(cls, sock):
        self = cls.__new__(cls)
        self.spec, self._sock = 'socket', sock
        sock.setblocking(False)
        self.write, self._read, self.close = sock.sendall, self._sock_read, sock.close
        return self

    def _sock_read(self):
        try:
            data = self._sock.recv(4096)
        except (BlockingIOError, InterruptedError):
            return b''
        if not data:
            raise OtaError('connection closed')
        return data

    def drain(self):
        while self._read():
            pass

    def read_until(self, want, timeout):
        """Read until ``want(buffer)`` is true or the timeout passes; returns the buffer."""
        buf, end = b'', time.monotonic() + timeout
        while True:
            buf += self._read()
            if want(buf) or time.monotonic() >= end:
                return buf
            time.sleep(0.002)


# ---- sender ----------------------------------------------------------------------------
class Sender:
    def __init__(self, port, log=print, cmd_timeout=0.3, ack_timeout=0.7, tries=3, pause=1.0):
        self.port, self.log = port, log
        self.cmd_timeout, self.ack_timeout, self.tries, self.pause = cmd_timeout, ack_timeout, tries, pause

    def command(self, text):
        for _ in range(self.tries):
            self.port.drain()
            self.port.write(text.encode('ascii'))
            rx = self.port.read_until(lambda b: OK in b, self.cmd_timeout)
            if OK in rx:
                return True
        return False

    def send_file(self, path, dst_dir, name, progress=None):
        with open(path, 'rb') as fh:
            data = fh.read()
        if not self.command(f'$file,3:{dst_dir}\\{name},{len(data)},2052,115200#'):
            raise OtaError(f'{dst_dir}\\{name}: $file not acknowledged')
        n = packet_count(len(data))
        for i in range(n):
            pkt = packet(i, data[i * PKT_DATA:(i + 1) * PKT_DATA])   # fresh checksum on every try
            for _ in range(self.tries):
                self.port.drain()
                self.port.write(pkt)
                rx = self.port.read_until(lambda b: len(b) >= 2, self.ack_timeout)
                if rx[:2] == pkt[:2] or pkt[:2] in rx:
                    break
            else:
                raise OtaError(f'{dst_dir}\\{name}: packet {i}/{n} not acknowledged')
            if progress:
                progress(i + 1, n)

    def run(self, files, dry_run=False):
        total = sum(os.path.getsize(p) for p, _, _ in files)
        self.log(f'{len(files)} files, {total / 1024:.0f} KiB, about {total / 10240 / 60:.1f} min at 115200')
        if dry_run:
            for p, d, name in files:
                self.log(f'  would send 3:{d}\\{name} ({os.path.getsize(p)} B)')
            return
        self.command('$cfgexit#')                  # like the bootloader: leave a stale download mode
        if not self.command('$cfgenter#'):
            raise OtaError('screen did not answer $cfgenter# (bridge still running? wrong port?)')
        time.sleep(self.pause)
        failed = []
        for k, (p, d, name) in enumerate(files, 1):
            t = time.monotonic()
            try:
                self.send_file(p, d, name)
                self.log(f'[{k}/{len(files)}] 3:{d}\\{name} ok ({time.monotonic() - t:.1f} s)')
            except OtaError as e:
                self.log(f'[{k}/{len(files)}] FAILED: {e}')
                failed.append(name)
                break                              # stop: the rest would likely fail too
        time.sleep(self.pause)
        if not self.command('$reboot#'):
            self.log('warning: $reboot# not acknowledged')
        time.sleep(self.pause)
        if not self.command('$cfgexit#'):
            self.log('warning: $cfgexit# not acknowledged')
        if failed:
            raise OtaError(f'update incomplete (failed at {failed[0]}); the screen may show a mixed UI')


# ---- receiver (emulator and tests) --------------------------------------------------------
class Receiver:
    """Screen side of the protocol. ``feed(data)`` returns ``(replies, passthrough)``:
    bytes to send back, and bytes that were not OTA traffic (DGUS frames).

    ``on_file(screen_path, data)`` gets each completed file (``3:\\bin\\13.bin``),
    ``on_reboot()`` is called on ``$reboot#``.
    """

    def __init__(self, on_file=None, on_reboot=None):
        self.on_file, self.on_reboot = on_file, on_reboot
        self.active = False                       # inside $cfgenter# ... $cfgexit#
        self.buf = bytearray()
        self.file = None                          # [path, size, packets left, next id, bytearray]
        self.bad_packets = 0

    def feed(self, data):
        replies, passthrough = bytearray(), bytearray()
        self.buf += data
        while self.buf:
            if self.file:
                if len(self.buf) < PKT_SIZE:
                    break
                pkt = bytes(self.buf[:PKT_SIZE])
                del self.buf[:PKT_SIZE]
                got = check_packet(pkt)
                path, size, left, nxt, content = self.file
                if got is not None and got[0] == (nxt - 1) & 0xFF and nxt > 0:
                    replies += pkt[:2]            # repeat of the last packet (our echo got lost)
                    continue
                if got is None or got[0] != nxt & 0xFF:
                    self.bad_packets += 1
                    continue                      # no echo -> sender retries
                replies += pkt[:2]
                content += got[1]
                self.file[2] -= 1
                self.file[3] += 1
                if self.file[2] == 0:
                    if self.on_file:
                        self.on_file(path, bytes(content[:size]))
                    self.file = None
                continue
            if self.buf[0] == 0x24:               # '$'
                end = self.buf.find(b'#')
                if end < 0:
                    if len(self.buf) > 300:
                        passthrough += self.buf
                        self.buf.clear()
                    break
                cmd = bytes(self.buf[:end + 1]).decode('ascii', 'replace')
                del self.buf[:end + 1]
                replies += self._command(cmd)
                continue
            if self.active:
                del self.buf[:1]                  # stray byte in download mode
                continue
            passthrough += self.buf                # not OTA: DGUS traffic (may contain '$' bytes)
            self.buf.clear()
        return bytes(replies), bytes(passthrough)

    def _command(self, cmd):
        if cmd in ('$hmiask#', '$cfgexit#'):
            self.active = False if cmd == '$cfgexit#' else self.active
            return OK
        if cmd == '$cfgenter#':
            self.active = True
            return OK
        if cmd == '$reboot#' and self.active:
            if self.on_reboot:
                self.on_reboot()
            return OK
        if cmd.startswith('$file,') and self.active:
            try:
                path, size, pkt, _baud = cmd[6:-1].rsplit(',', 3)
                size = int(size)
                if int(pkt) != PKT_SIZE:
                    return b'$err#'
            except ValueError:
                return b'$err#'
            self.file = [path, size, packet_count(size), 0, bytearray()]
            return OK
        return b'$err#'


def screen_path_to_rel(path):
    """``3:\\bin\\13.bin`` -> ``bin/13.bin``."""
    p = path.split(':', 1)[-1].replace('\\', '/').lstrip('/')
    return p
