"""Icon libraries (``private/icon/N.zico``).

Layout::

    'ZICO'  u32 LE index_len
    index_len/16 records: u16 id, u16 flag (1 in all stock files), u16 width,
                          u16 height, u32 offset, u32 size        (all LE)
    data: per icon one zlib stream (level 6) of RGB565 LE pixels;
          offsets are relative to 8 + index_len

Icons are stored in the panel's viewing orientation (not rotated like pages).
Pure black (0x0000) is very likely the transparency key; keep it out of
recolouring.
"""
import struct
import zlib

from PIL import Image

from . import rgb565

MAGIC = b'ZICO'
ZLIB_LEVEL = 6


class Icon:
    def __init__(self, icon_id, width, height, packed=None, raw=None, flag=1):
        self.id = icon_id
        self.flag = flag
        self.width = width
        self.height = height
        self._packed = packed   # zlib stream as stored
        self._raw = raw

    @property
    def raw(self) -> bytes:
        if self._raw is None:
            self._raw = zlib.decompress(self._packed)
        return self._raw

    @property
    def packed(self) -> bytes:
        if self._packed is None:
            self._packed = zlib.compress(self._raw, ZLIB_LEVEL)
        return self._packed

    def to_image(self) -> Image.Image:
        return rgb565.decode(self.raw, self.width, self.height)

    def set_image(self, img: Image.Image):
        img = img.convert('RGB')
        self.width, self.height = img.size
        self._raw, self._packed = rgb565.encode(img), None

    def set_raw(self, raw: bytes):
        self._raw, self._packed = raw, None


class IconLib:
    def __init__(self, icons=None, data=None):
        self.icons = icons or []   # keeps file order
        self._data = data          # original bytes, reused while unmodified
        self.modified = False

    @classmethod
    def from_bytes(cls, data: bytes) -> 'IconLib':
        if data[:4] != MAGIC:
            raise ValueError('not a ZICO file')
        index_len = struct.unpack('<I', data[4:8])[0]
        base = 8 + index_len
        icons = []
        for i in range(index_len // 16):
            iid, flag, w, h, off, size = struct.unpack('<HHHHII', data[8 + 16 * i:24 + 16 * i])
            icons.append(Icon(iid, w, h, packed=data[base + off:base + off + size], flag=flag))
        return cls(icons, data)

    @classmethod
    def load(cls, path) -> 'IconLib':
        with open(path, 'rb') as f:
            return cls.from_bytes(f.read())

    def get(self, icon_id):
        for ic in self.icons:
            if ic.id == icon_id:
                return ic
        return None

    def put(self, icon_id, img: Image.Image):
        """Replace (or append) an icon from a PIL image in viewing orientation."""
        ic = self.get(icon_id)
        if ic is None:
            ic = Icon(icon_id, *img.size, raw=b'')
            self.icons.append(ic)
            self.icons.sort(key=lambda x: x.id)
        ic.set_image(img)
        self.modified = True

    def to_bytes(self) -> bytes:
        if self._data is not None and not self.modified:
            return self._data
        index, blobs, off = [], [], 0
        for ic in self.icons:
            p = ic.packed
            index.append(struct.pack('<HHHHII', ic.id, ic.flag, ic.width, ic.height, off, len(p)))
            blobs.append(p)
            off += len(p)
        idx = b''.join(index)
        return MAGIC + struct.pack('<I', len(idx)) + idx + b''.join(blobs)

    def save(self, path):
        with open(path, 'wb') as f:
            f.write(self.to_bytes())
