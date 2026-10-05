"""Touch configuration (``private/bin/13.bin``), DWIN DGUS-II style.

The file is a sequence of records sorted by page, terminated by ``FF FF``.
Base record (16 bytes, big-endian fields)::

    [0]      flags (unknown meaning; 0x0C most common for buttons)
    [1]      page id
    [2:10]   touch area x0, y0, x1, y1 (panel coordinates, 480x800 portrait)
    [10:12]  page to switch to on release (0xFF00 = none)
    [12:14]  page shown while pressed     (0xFF00 = none)
    [14:16]  touch code

Touch codes ``0xFExx`` / ``0xFDxx`` carry extension blocks:

* ``FE05`` / ``FD05`` return key (+16 bytes): ``[16]=FE, [17:19]=VP, [20:22]=key code``
* ``FE02`` increment (+16 bytes): ``[17:19]=VP, [20]=0 dec / 1 inc, [22:24]=step,
  [24:26]=min, [26:28]=max``
* ``FE00`` numeric input (+48 bytes): ``[17:19]=VP``, keyboard page at ``[34:36]``,
  min/max as i32 at ``[50:54]`` / ``[54:58]``

Anything else (on-screen keyboard keys etc.) is a plain 16-byte record whose
code holds the key's ASCII pair. Unknown bytes are kept verbatim.
"""
import struct

NO_PAGE = 0xFF00
TERMINATOR = b'\xff\xff'


def _rec_len(base: bytes) -> int:
    if base[14] in (0xFE, 0xFD):
        return 64 if base[15] == 0x00 else 32
    return 16


class TouchRecord:
    def __init__(self, data: bytes):
        self.data = bytearray(data)

    # ---- common fields ----------------------------------------------------
    @property
    def flags(self): return self.data[0]
    @flags.setter
    def flags(self, v): self.data[0] = v

    @property
    def page(self): return self.data[1]
    @page.setter
    def page(self, v):
        if not 0 <= v <= 255:
            raise ValueError('page id must be 0..255')
        self.data[1] = v

    @property
    def area(self): return list(struct.unpack('>4H', self.data[2:10]))
    @area.setter
    def area(self, a): self.data[2:10] = struct.pack('>4H', *a)

    @property
    def page_next(self):
        v = struct.unpack('>H', self.data[10:12])[0]
        return None if v == NO_PAGE else v
    @page_next.setter
    def page_next(self, v): self.data[10:12] = struct.pack('>H', NO_PAGE if v is None else v)

    @property
    def page_on(self):
        v = struct.unpack('>H', self.data[12:14])[0]
        return None if v == NO_PAGE else v
    @page_on.setter
    def page_on(self, v): self.data[12:14] = struct.pack('>H', NO_PAGE if v is None else v)

    @property
    def code(self): return struct.unpack('>H', self.data[14:16])[0]

    @property
    def kind(self):
        hi, lo = self.data[14], self.data[15]
        if hi in (0xFE, 0xFD):
            return {0x05: 'return_key', 0x00: 'data_input', 0x02: 'increment'}.get(lo, f'fe{lo:02x}')
        return 'keyboard_key'

    # ---- extension fields ---------------------------------------------------
    @property
    def vp(self):
        return struct.unpack('>H', self.data[17:19])[0] if len(self.data) > 16 else None
    @vp.setter
    def vp(self, v): self.data[17:19] = struct.pack('>H', v)

    @property
    def key(self):
        return struct.unpack('>H', self.data[20:22])[0] if self.kind == 'return_key' else None
    @key.setter
    def key(self, v): self.data[20:22] = struct.pack('>H', v)

    @property
    def keyboard_page(self):
        return struct.unpack('>H', self.data[34:36])[0] if self.kind == 'data_input' else None
    @keyboard_page.setter
    def keyboard_page(self, v):
        if self.kind != 'data_input':
            raise ValueError('keyboard_page only exists on numeric input (FE00) records')
        self.data[34:36] = struct.pack('>H', v)

    def describe(self) -> dict:
        d = {'flags': self.flags, 'page': self.page, 'area': self.area,
             'page_next': self.page_next, 'page_on': self.page_on, 'kind': self.kind}
        if self.data[14] == 0xFD:
            d['fd_variant'] = True
        if len(self.data) > 16:
            d['vp'] = f'0x{self.vp:04X}'
        x = self.data
        if self.kind == 'return_key':
            d['key'] = f'0x{self.key:04X}'
        elif self.kind == 'increment':
            d['op'] = 'inc' if x[20] else 'dec'
            d['step'], d['min'], d['max'] = struct.unpack('>HHH', x[22:28])
        elif self.kind == 'data_input':
            d['keyboard_page'] = self.keyboard_page
            d['min'], d['max'] = struct.unpack('>ii', x[50:58])
        elif self.kind == 'keyboard_key':
            d['ascii'] = bytes(x[14:16]).hex()
        return d

    def copy(self) -> 'TouchRecord':
        return TouchRecord(bytes(self.data))

    # ---- builders -------------------------------------------------------------
    @classmethod
    def return_key(cls, page, area, vp, key, page_next=None, page_on=None, flags=0x0C):
        """Button that reports ``5A A5 06 83 VP 01 KEY`` to the host."""
        b = bytearray(32)
        b[0], b[1] = flags, page
        b[14:16] = b'\xfe\x05'
        b[16] = 0xFE
        r = cls(b)
        r.area, r.page_next, r.page_on, r.vp, r.key = area, page_next, page_on, vp, key
        return r

    @classmethod
    def page_jump(cls, page, area, page_next, flags=0x0C):
        """Button that only switches page (stock files use a return key on VP 0)."""
        return cls.return_key(page, area, 0x0000, 0x0000, page_next=page_next, flags=flags)


class TouchConfig:
    def __init__(self, records=None, trailer=TERMINATOR):
        self.records = records or []
        self.trailer = trailer

    @classmethod
    def from_bytes(cls, data: bytes) -> 'TouchConfig':
        i, recs = 0, []
        while i + 2 <= len(data) and data[i:i + 2] != TERMINATOR:
            L = _rec_len(data[i:i + 16])
            recs.append(TouchRecord(data[i:i + L]))
            i += L
        return cls(recs, data[i:])

    @classmethod
    def load(cls, path) -> 'TouchConfig':
        with open(path, 'rb') as f:
            return cls.from_bytes(f.read())

    def to_bytes(self) -> bytes:
        recs = sorted(self.records, key=lambda r: r.page)   # stable: keeps in-page order
        return b''.join(bytes(r.data) for r in recs) + self.trailer

    def save(self, path):
        with open(path, 'wb') as f:
            f.write(self.to_bytes())

    def page(self, page):
        return [r for r in self.records if r.page == page]

    def find(self, page=None, vp=None, key=None):
        out = []
        for r in self.records:
            if page is not None and r.page != page:
                continue
            if vp is not None and r.vp != vp:
                continue
            if key is not None and r.key != key:
                continue
            out.append(r)
        return out

    def add(self, rec: TouchRecord):
        self.records.append(rec)
        return rec

    def remove_page(self, page):
        self.records = [r for r in self.records if r.page != page]
