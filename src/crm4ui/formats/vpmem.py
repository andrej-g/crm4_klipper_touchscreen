"""Initial VP memory (``private/bin/22.bin``).

A 131076-byte image of the screen's variable memory at power-up. The byte
offset of VP ``v`` is ``2 * v`` (the first VP words double as a small zero
header). Text is stored GBK-encoded and NUL-padded (stock examples: screen
version ``"2.0.3"`` at VP 0x3118, ``大彩科技`` at VP 0x4390).
"""
import struct

ENCODING = 'gbk'


class VpMemory:
    def __init__(self, data: bytes):
        self.data = bytearray(data)

    @classmethod
    def load(cls, path) -> 'VpMemory':
        with open(path, 'rb') as f:
            return cls(f.read())

    def to_bytes(self) -> bytes:
        return bytes(self.data)

    def save(self, path):
        with open(path, 'wb') as f:
            f.write(self.to_bytes())

    def _span(self, vp, nbytes):
        o = 2 * vp
        if o + nbytes > len(self.data):
            raise ValueError(f'VP 0x{vp:04X} (+{nbytes} bytes) is outside 22.bin')
        return o

    def get_word(self, vp) -> int:
        o = self._span(vp, 2)
        return struct.unpack('>H', self.data[o:o + 2])[0]

    def set_word(self, vp, value: int):
        o = self._span(vp, 2)
        self.data[o:o + 2] = struct.pack('>H', value & 0xFFFF)

    def get_text(self, vp, max_bytes) -> str:
        o = self._span(vp, max_bytes)
        return bytes(self.data[o:o + max_bytes]).split(b'\x00')[0].decode(ENCODING, 'replace')

    def set_text(self, vp, text: str, max_bytes: int):
        raw = text.encode(ENCODING)
        if len(raw) > max_bytes:
            raise ValueError(f'text for VP 0x{vp:04X} longer than {max_bytes} bytes')
        o = self._span(vp, max_bytes)
        self.data[o:o + max_bytes] = raw + b'\x00' * (max_bytes - len(raw))
