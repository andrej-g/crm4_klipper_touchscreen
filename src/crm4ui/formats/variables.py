"""Display-variable configuration (``private/bin/14.bin``), DWIN DGUS-II style.

Layout::

    0x0000  header, 16 bytes: 0x14 'DGUS_2' 0x10, u16 BE highest page id, zeros
    0x0010  page index, 4092 entries x 4 bytes: u16 LE record count,
            u16 BE byte offset of the page's first record. Pages without
            records point at where the next records start (after the last
            page: the end-of-records position).
    0x4000  records, 32 bytes each, grouped by page in page order
    end     32 x 0xFF

Record (32 bytes, big-endian fields)::

    [0]=0x5A  [1]=type  [2:4]=SP (0xFFFF none)  [4:6]=description length
    [6:8]=VP  [8:12]=x, y  then type-specific fields

Known types: 0x00 icon variable, 0x10 number, 0x11 text, 0x20 trend curve,
0x08 / 0x26 image area (print thumbnail). Unknown bytes are kept verbatim.

Trend curve (0x20) fields beyond the colour and channel follow the DGUS-II
"real-time curve" layout (inferred, consistent with the stock PID pages: the
nozzle graph's 0-350 C axis is 208 px tall and its record says Mul_Y 153/256
with VD_Central 175 at Y_Central 387; the bed graph has 70 / 380/256 for
0-140 C): ``[16:18]`` Y_Central, ``[18:20]`` VD_Central, ``[20:22]`` colour,
``[22:24]`` Mul_Y (pixels per unit, /256), ``[24]`` channel, ``[25]`` Dis_HOR
(pixels between points).
"""
import struct

HEADER_LEN = 0x10
INDEX_START = 0x10
RECORDS_START = 0x4000
INDEX_ENTRIES = (RECORDS_START - INDEX_START) // 4
REC_LEN = 32
TRAILER = b'\xff' * 32

KIND = {0x00: 'icon_var', 0x10: 'number', 0x11: 'text', 0x20: 'curve',
        0x08: 'image_ctl', 0x26: 'image_area'}


class VarRecord:
    def __init__(self, data: bytes):
        if len(data) != REC_LEN:
            raise ValueError('variable record must be 32 bytes')
        self.data = bytearray(data)

    @property
    def type(self): return self.data[1]

    @property
    def kind(self): return KIND.get(self.type, f'type{self.type:02x}')

    @property
    def vp(self): return struct.unpack('>H', self.data[6:8])[0]
    @vp.setter
    def vp(self, v): self.data[6:8] = struct.pack('>H', v)

    @property
    def pos(self): return list(struct.unpack('>HH', self.data[8:12]))
    @pos.setter
    def pos(self, p): self.data[8:12] = struct.pack('>HH', *p)

    @property
    def color(self):
        if self.type in (0x10, 0x11):
            return struct.unpack('>H', self.data[12:14])[0]
        if self.type == 0x20:
            return struct.unpack('>H', self.data[20:22])[0]
        return None
    @color.setter
    def color(self, c):
        if self.type in (0x10, 0x11):
            self.data[12:14] = struct.pack('>H', c)
        elif self.type == 0x20:
            self.data[20:22] = struct.pack('>H', c)
        else:
            raise ValueError(f'{self.kind} has no colour field')

    # text (0x11)
    @property
    def box(self):
        if self.type == 0x11:
            return list(struct.unpack('>4H', self.data[14:22]))
        if self.type in (0x20, 0x26):
            return list(struct.unpack('>4H', self.data[8:16]))
        return None
    @box.setter
    def box(self, b):
        if self.type != 0x11:
            raise ValueError('only text records have a settable box here')
        self.data[14:22] = struct.pack('>4H', *b)

    @property
    def text_len(self): return struct.unpack('>H', self.data[22:24])[0]
    @text_len.setter
    def text_len(self, n): self.data[22:24] = struct.pack('>H', n)

    # number (0x10)
    @property
    def digits(self): return self.data[17], self.data[18]
    @digits.setter
    def digits(self, d): self.data[17], self.data[18] = d

    def describe(self) -> dict:
        d = {'kind': self.kind, 'type': self.type, 'vp': f'0x{self.vp:04X}', 'pos': self.pos}
        x = self.data
        if self.type == 0x10:
            d.update(color=f'0x{self.color:04X}', lib=x[14], font_size=x[15], align=x[16],
                     int_digits=x[17], dec_digits=x[18], var_type=x[19])
        elif self.type == 0x11:
            d.update(color=f'0x{self.color:04X}', box=self.box, text_len=self.text_len)
        elif self.type == 0x00:
            d.update(v_min=struct.unpack('>H', x[12:14])[0], v_max=struct.unpack('>H', x[14:16])[0],
                     icon_min=struct.unpack('>H', x[16:18])[0], icon_max=struct.unpack('>H', x[18:20])[0],
                     icon_lib=x[20])
        elif self.type == 0x20:
            d.update(box=self.box, y_center=struct.unpack('>H', x[16:18])[0],
                     vd_central=struct.unpack('>h', x[18:20])[0],            # inferred, see module doc
                     color=f'0x{self.color:04X}', mul_y=struct.unpack('>H', x[22:24])[0],
                     channel=x[24], dis_hor=x[25])
        elif self.type == 0x26:
            d.update(box=self.box)
        return d

    def copy(self) -> 'VarRecord':
        return VarRecord(bytes(self.data))


class VarConfig:
    def __init__(self, header: bytes, pages: dict, data=None):
        self.header = bytearray(header)
        self.pages = pages          # page id -> [VarRecord]
        self._data = data

    @classmethod
    def from_bytes(cls, data: bytes) -> 'VarConfig':
        if data[1:7] != b'DGUS_2':
            raise ValueError('not a DGUS_2 variable file')
        pages = {}
        for p in range(INDEX_ENTRIES):
            e = INDEX_START + 4 * p
            count = struct.unpack('<H', data[e:e + 2])[0]
            off = struct.unpack('>H', data[e + 2:e + 4])[0]
            if count:
                pages[p] = [VarRecord(data[off + REC_LEN * k: off + REC_LEN * (k + 1)])
                            for k in range(count)]
        return cls(data[:HEADER_LEN], pages, data)

    @classmethod
    def load(cls, path) -> 'VarConfig':
        with open(path, 'rb') as f:
            return cls.from_bytes(f.read())

    @property
    def max_page(self): return struct.unpack('>H', self.header[8:10])[0]
    @max_page.setter
    def max_page(self, v): self.header[8:10] = struct.pack('>H', v)

    def to_bytes(self) -> bytes:
        index = bytearray()
        body = bytearray()
        for p in range(INDEX_ENTRIES):
            recs = self.pages.get(p, [])
            off = RECORDS_START + len(body)
            if off > 0xFFFF:
                raise ValueError('14.bin record area exceeds 64 KiB offset range')
            index += struct.pack('<H', len(recs)) + struct.pack('>H', off)
            for r in recs:
                body += r.data
        return bytes(self.header) + bytes(index) + bytes(body) + TRAILER

    def save(self, path):
        with open(path, 'wb') as f:
            f.write(self.to_bytes())

    def all(self):
        for p in sorted(self.pages):
            for r in self.pages[p]:
                yield p, r

    def add(self, page, rec: VarRecord):
        self.pages.setdefault(page, []).append(rec)
        if page > self.max_page:
            self.max_page = page
        return rec

    def template(self, kind_type: int, vp=None):
        """First stock record of a type (optionally with a given VP), for cloning."""
        for _, r in self.all():
            if r.type == kind_type and (vp is None or r.vp == vp):
                return r
        raise KeyError(f'no record of type 0x{kind_type:02x}' + (f' with VP 0x{vp:04X}' if vp else ''))
