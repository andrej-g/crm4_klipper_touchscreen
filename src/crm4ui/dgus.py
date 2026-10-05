"""DWIN DGUS-II style serial protocol, as used between the CR-M4 mainboard and
its DACAI screen.

Frame: ``5A A5 LEN CMD DATA...`` where LEN counts CMD + DATA (no CRC; the
stock ``config.txt`` does not enable one; still unconfirmed on hardware).

Host -> screen
  ``82 VPhi VPlo data...``      write VP memory (words, big-endian)
  ``83 VPhi VPlo N``            read N words starting at VP
  page switch = write ``5A 01 00 PP`` to VP ``0x0084``

Screen -> host
  ``83 VPhi VPlo N words...``   touch event / read reply (key code or value)
  ``82 4F 4B``                  write acknowledge ("OK"), sent by DGUS-II screens
"""
import struct

HEADER = b'\x5a\xa5'
CMD_WRITE = 0x82
CMD_READ = 0x83
VP_PAGE = 0x0084
MAX_DATA = 0xFF - 3          # LEN is one byte: CMD + VP(2) + data
TEXT_ENCODING = 'gbk'


class Frame:
    __slots__ = ('cmd', 'data')

    def __init__(self, cmd, data=b''):
        self.cmd = cmd
        self.data = bytes(data)

    def to_bytes(self) -> bytes:
        if len(self.data) + 1 > 0xFF:
            raise ValueError('DGUS frame too long')
        return HEADER + bytes([len(self.data) + 1, self.cmd]) + self.data

    # ---- interpretation ----------------------------------------------------
    @property
    def vp(self):
        return struct.unpack('>H', self.data[:2])[0] if len(self.data) >= 2 else None

    @property
    def is_ack(self):
        return self.cmd == CMD_WRITE and self.data == b'OK'

    def words(self):
        """For 0x83 frames: the word values after VP and count."""
        if self.cmd != CMD_READ or len(self.data) < 3:
            return []
        n = self.data[2]
        return list(struct.unpack(f'>{n}H', self.data[3:3 + 2 * n]))

    @property
    def value(self):
        w = self.words()
        return w[0] if w else None

    def payload(self):
        """For 0x82 frames: bytes written after the VP."""
        return self.data[2:]

    def __repr__(self):
        return f'Frame({self.cmd:02X} {self.data.hex(" ")})'

    def __eq__(self, other):
        return isinstance(other, Frame) and (self.cmd, self.data) == (other.cmd, other.data)


# ---- builders -------------------------------------------------------------------
def write_bytes(vp: int, payload: bytes) -> Frame:
    if len(payload) > MAX_DATA - 2:
        raise ValueError('payload too long for one frame')
    return Frame(CMD_WRITE, struct.pack('>H', vp) + payload)


def write_words(vp: int, *values: int) -> Frame:
    return write_bytes(vp, b''.join(struct.pack('>H', v & 0xFFFF) for v in values))


def write_text(vp: int, text: str, max_bytes: int) -> Frame:
    """Write a text VP; pads with NULs to ``max_bytes`` so old text is cleared."""
    raw = text.encode(TEXT_ENCODING, 'replace')[:max_bytes]
    return write_bytes(vp, raw + b'\x00' * (max_bytes - len(raw)))


def read_words(vp: int, count: int) -> Frame:
    return Frame(CMD_READ, struct.pack('>HB', vp, count))


def set_page(page: int) -> Frame:
    return write_bytes(VP_PAGE, bytes([0x5A, 0x01, (page >> 8) & 0xFF, page & 0xFF]))


def reply_words(vp: int, *values: int) -> Frame:
    """What the screen sends: touch events and read replies."""
    return Frame(CMD_READ, struct.pack('>HB', vp, len(values)) +
                 b''.join(struct.pack('>H', v & 0xFFFF) for v in values))


ACK = Frame(CMD_WRITE, b'OK')


def to_signed(v: int) -> int:
    return v - 0x10000 if v & 0x8000 else v


# ---- stream parser --------------------------------------------------------------
class Parser:
    """Incremental parser; resynchronises on the 5A A5 header after garbage."""

    def __init__(self):
        self.buf = bytearray()
        self.dropped = 0

    def feed(self, data: bytes):
        self.buf += data
        out = []
        while True:
            i = self.buf.find(HEADER)
            if i < 0:
                keep = 1 if self.buf[-1:] == b'\x5a' else 0
                self.dropped += len(self.buf) - keep
                del self.buf[:len(self.buf) - keep]
                return out
            if i:
                self.dropped += i
                del self.buf[:i]
            if len(self.buf) < 4:
                return out
            n = self.buf[2]
            if n == 0:
                self.dropped += 2
                del self.buf[:2]
                continue
            if len(self.buf) < 3 + n:
                return out
            out.append(Frame(self.buf[3], self.buf[4:3 + n]))
            del self.buf[:3 + n]
