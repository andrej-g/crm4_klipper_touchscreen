"""Page background images (``private/image/N.zbmp``).

Layout: 16-byte header (u16 LE width, u16 LE height, then ``ff 00`` and zero
padding in every stock file), followed by one zlib stream (level 6) of raw
little-endian RGB565 pixels. Pages are stored rotated 180 degrees relative to
how the panel is viewed and touched; ``upright=True`` converts between the two.
"""
import struct
import zlib

from PIL import Image

from . import rgb565

ZLIB_LEVEL = 6
DEFAULT_HEADER_TAIL = b'\xff\x00' + b'\x00' * 10


class ZBmp:
    def __init__(self, width, height, raw, header_tail=DEFAULT_HEADER_TAIL, packed=None):
        self.width = width
        self.height = height
        self.raw = raw                  # uncompressed RGB565 LE, stored orientation
        self.header_tail = header_tail  # header bytes 4..15, kept verbatim
        self._packed = packed           # original file bytes, reused while unmodified

    # ---- file I/O -------------------------------------------------------
    @classmethod
    def from_bytes(cls, data: bytes) -> 'ZBmp':
        w, h = struct.unpack('<HH', data[:4])
        raw = zlib.decompress(data[16:])
        if len(raw) != w * h * 2:
            raise ValueError(f'zbmp size mismatch: {len(raw)} != {w}x{h}x2')
        return cls(w, h, raw, data[4:16], packed=data)

    @classmethod
    def load(cls, path) -> 'ZBmp':
        with open(path, 'rb') as f:
            return cls.from_bytes(f.read())

    def to_bytes(self) -> bytes:
        if self._packed is not None:
            return self._packed
        return struct.pack('<HH', self.width, self.height) + self.header_tail + \
            zlib.compress(self.raw, ZLIB_LEVEL)

    def save(self, path):
        with open(path, 'wb') as f:
            f.write(self.to_bytes())

    # ---- pixels ----------------------------------------------------------
    def to_image(self, upright=True) -> Image.Image:
        im = rgb565.decode(self.raw, self.width, self.height)
        return im.rotate(180) if upright else im

    @classmethod
    def from_image(cls, img: Image.Image, upright=True, size=(480, 800),
                   header_tail=DEFAULT_HEADER_TAIL) -> 'ZBmp':
        img = img.convert('RGB')
        if img.size != size:
            raise ValueError(f'page image must be {size[0]}x{size[1]}, got {img.size[0]}x{img.size[1]}')
        if upright:
            img = img.rotate(180)
        return cls(img.size[0], img.size[1], rgb565.encode(img), header_tail)

    def set_image(self, img: Image.Image, upright=True):
        new = ZBmp.from_image(img, upright, (self.width, self.height), self.header_tail)
        self.raw, self._packed = new.raw, None
