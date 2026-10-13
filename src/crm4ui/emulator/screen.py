"""A software model of the CR-M4 DACAI screen running a stock ``private/`` project.

It keeps VP memory, the current page and the on-screen keypad state, reacts
to host frames (VP writes/reads, page switches) and to touches, and renders
the current page. The behaviour follows DWIN DGUS-II conventions; details
the real DACAI screen may do differently are marked ASSUMPTION.
"""
import collections
import io
import os
import struct
import threading
import time

from PIL import Image, ImageDraw, ImageFont

from .. import dgus

KEYBOARD_BACKSPACE, KEYBOARD_ESC, KEYBOARD_OK = 0xF2, 0xF0, 0xF1

# curve buffers (screen firmware RE, section 2a): 8 rings of 0x800 words; VP 0x0300 + 2n is
# channel n's write pointer, 0x0301 + 2n its length (0 clears); VP 0x0310 = 5AA5, 0x0311 hi =
# block count, then per block a word (channel << 8 | n) and n data words
CURVE_CHANNELS, CURVE_RING = 8, 0x800
VP_CURVE_REG, VP_CURVE_WRITE, CURVE_MAGIC = 0x0300, 0x0310, 0x5AA5


class ScreenSim:
    def __init__(self, project, start_page=0, lang=None, ack_writes=False, font_path=None):
        self.project = project
        self.mem = bytearray(project.vpmem.data)
        self.mem += bytes(max(0, 2 * 0x10000 - len(self.mem)))        # full 64 Ki-word space
        self.page = start_page
        self.ack_writes = ack_writes          # the CR-M4 screen sends no acks (config RC bit 3 = 0)
        self.keypad = None
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        self.version = 0
        self.log = collections.deque(maxlen=400)
        self.log_seq = 0
        self.send = lambda frame: None                                 # set by the transport
        self._bg = {}
        self._fonts = {}
        self.font_path = font_path or os.path.join(project.root, 'truefont', 'font.ttf')
        self._font_bytes = None
        self._pictures = {}
        self.curves = [collections.deque(maxlen=CURVE_RING) for _ in range(CURVE_CHANNELS)]
        self._seed_sp()
        if lang is not None:
            self.set_word(0x5247, lang)

    def _seed_sp(self):
        """At boot the screen copies each field's description to VP RAM at its SP."""
        for _, r in self.project.vars.all():
            sp, n = struct.unpack('>HH', bytes(r.data[2:6]))
            if sp < 0xFF00 and 1 <= n <= 16:
                self.mem[2 * sp:2 * sp + 2 * n] = r.data[6:6 + 2 * n]

    def _live(self, r):
        """The field as the screen draws it: description words reloaded from VP RAM at SP."""
        sp, n = struct.unpack('>HH', bytes(r.data[2:6]))
        if sp >= 0xFF00 or not 1 <= n <= 16:
            return r
        from ..formats.variables import VarRecord
        data = bytearray(r.data)
        data[6:6 + 2 * n] = self.mem[2 * sp:2 * sp + 2 * n]
        return VarRecord(bytes(data))

    def reload(self, project):
        """Restart with a new UI project, as the screen does after an OTA update."""
        with self.lock:
            lang = self.word(0x5247)
            self.project = project
            self.mem = bytearray(project.vpmem.data)
            self.mem += bytes(max(0, 2 * 0x10000 - len(self.mem)))
            self.set_word(0x5247, lang)
            self.page, self.keypad = 0, None
            self._bg, self._fonts, self._pictures = {}, {}, {}
            self.curves = [collections.deque(maxlen=CURVE_RING) for _ in range(CURVE_CHANNELS)]
            self.font_path = os.path.join(project.root, 'truefont', 'font.ttf')
            self._font_bytes = None
            self._seed_sp()
            self._note('local', None, f'rebooted with {project.root}')
            self._bump()

    # ---- memory -------------------------------------------------------------------
    def word(self, vp):
        return struct.unpack('>H', self.mem[2 * vp:2 * vp + 2])[0]

    def set_word(self, vp, value):
        self.mem[2 * vp:2 * vp + 2] = struct.pack('>H', value & 0xFFFF)

    def text(self, vp, max_bytes):
        raw = bytes(self.mem[2 * vp:2 * vp + max_bytes])
        for stop in (b'\x00', b'\xff'):
            raw = raw.split(stop)[0]
        return raw.decode(dgus.TEXT_ENCODING, 'replace')

    # ---- bookkeeping ----------------------------------------------------------------
    log_file = None                     # optional text file every log entry is appended to

    def _note(self, direction, frame, note=''):
        self.log_seq += 1
        entry = (self.log_seq, time.strftime('%H:%M:%S'), direction,
                 frame.to_bytes().hex(' ') if frame else '', note)
        self.log.append(entry)
        if self.log_file:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(f'{entry[1]} {direction:9} page={self.page:<3} {note:30} {entry[3]}\n')

    def _bump(self):
        self.version += 1
        self.changed.notify_all()

    def _emit(self, frame, note=''):
        self._note('scr->host', frame, note)
        self.send(frame)

    def set_page(self, page, why='touch'):
        with self.lock:
            self.page = page
            self._keep_keypad()
            self._note('local', None, f'page {page} ({why})')
            self._bump()

    # ---- host frames ------------------------------------------------------------------
    def handle_host(self, frame: dgus.Frame):
        with self.lock:
            if frame.cmd == dgus.CMD_WRITE and frame.vp is not None:
                vp, payload = frame.vp, frame.payload()
                if vp == dgus.VP_PAGE and payload[:2] == b'\x5a\x01' and len(payload) >= 4:
                    self.page = struct.unpack('>H', payload[2:4])[0]
                    self.keypad = None
                    note = f'page -> {self.page}'
                else:
                    o = 2 * vp
                    self.mem[o:o + len(payload)] = payload
                    note = f'write 0x{vp:04X} ({len(payload)} B)'
                    note = self._curve_host_write(vp, payload) or note
                self._note('host->scr', frame, note)
                if self.ack_writes:
                    self._emit(dgus.ACK, 'ack')
                self._bump()
            elif frame.cmd == dgus.CMD_READ and len(frame.data) >= 3:
                vp, n = frame.vp, frame.data[2]
                if vp < 0x1000:
                    self.set_word(0x0014, self.page)      # the screen refreshes the current page first
                self._note('host->scr', frame, f'read 0x{vp:04X} x{n}')
                self._emit(dgus.reply_words(vp, *[self.word(vp + i) for i in range(n)]), 'read reply')
            else:
                self._note('host->scr', frame, 'ignored')
                self._bump()

    def _curve_host_write(self, vp, payload):
        """Curve-buffer writes (VP 0x0310) and channel clears (VP 0x0301 + 2n <- 0)."""
        if vp == VP_CURVE_WRITE:
            n = len(payload) // 2
            words = list(struct.unpack(f'>{n}H', payload[:2 * n]))
            if len(words) < 3 or words[0] != CURVE_MAGIC:
                return 'curve write: bad magic, ignored'
            pos, added = 2, []
            for _ in range(words[1] >> 8):
                if pos >= len(words):
                    break
                ch, cnt = words[pos] >> 8, words[pos] & 0xFF
                vals = words[pos + 1:pos + 1 + cnt]
                pos += 1 + cnt
                if ch < CURVE_CHANNELS:
                    self.curves[ch].extend(dgus.to_signed(v) for v in vals)
                    added.append(f'ch{ch}+{len(vals)}')
            return 'curve ' + ' '.join(added) if added else 'curve write: nothing'
        if VP_CURVE_REG < vp < VP_CURVE_REG + 2 * CURVE_CHANNELS and (vp - VP_CURVE_REG) % 2 == 1:
            ch = (vp - VP_CURVE_REG) // 2
            if payload[:2] == b'\x00\x00':
                self.curves[ch].clear()
                return f'curve ch{ch} cleared'
        return None

    # ---- touch ------------------------------------------------------------------------
    def touch(self, x, y):
        with self.lock:
            hit = None
            for r in self.project.touch.page(self.page):
                x0, y0, x1, y1 = r.area
                if min(x0, x1) <= x <= max(x0, x1) and min(y0, y1) <= y <= max(y0, y1):
                    hit = r
                    break
            if hit is None:
                self._note('local', None, f'touch ({x},{y}) on page {self.page}: nothing')
                self._bump()
                return None
            d = hit.describe()
            kind = hit.kind
            self._note('local', None, f'touch ({x},{y}) page {self.page}: {kind}')
            if kind == 'return_key':
                self.set_word(hit.vp, hit.key)
                self._emit(dgus.reply_words(hit.vp, hit.key), f'key 0x{hit.vp:04X}={hit.key}')
            elif kind == 'increment':
                cur = dgus.to_signed(self.word(hit.vp))
                new = cur + d['step'] if d['op'] == 'inc' else cur - d['step']
                new = max(dgus.to_signed(d['min']), min(dgus.to_signed(d['max']), new))
                self.set_word(hit.vp, new)
                # ASSUMPTION: increment controls upload the new value like a key
                self._emit(dgus.reply_words(hit.vp, new), f'inc 0x{hit.vp:04X}={new}')
            elif kind == 'data_input':
                self.keypad = {'vp': hit.vp, 'min': d['min'], 'max': d['max'], 'text': '',
                               'return_page': self.page, 'dec': self._dec_digits(hit.vp),
                               'page': d['keyboard_page']}
                self.page = d['keyboard_page']
                self._note('local', None, f'keypad for 0x{hit.vp:04X}')
            elif kind == 'keyboard_key':
                self._keypad_key(hit.code & 0xFF)
            if hit.page_next is not None and kind != 'data_input':
                self.page = hit.page_next
                self._keep_keypad()
                self._note('local', None, f'page {self.page} (button)')
            self._bump()
            return d

    def _keep_keypad(self):
        # the keypad state only survives on its own keyboard page (40, or a titled copy)
        if self.keypad and self.page != self.keypad['page']:
            self.keypad = None

    def _dec_digits(self, vp):
        for p in (self.page,):
            for r in self.project.vars.pages.get(p, []):
                if r.type == 0x10 and r.vp == vp:
                    return r.digits[1]
        for _, r in self.project.vars.all():
            if r.type == 0x10 and r.vp == vp:
                return r.digits[1]
        return 0

    def _keypad_key(self, code):
        kp = self.keypad
        if kp is None:
            return
        if code == KEYBOARD_BACKSPACE:
            kp['text'] = kp['text'][:-1]
        elif code == KEYBOARD_ESC:
            self.page, self.keypad = kp['return_page'], None
        elif code == KEYBOARD_OK:
            try:
                v = round(float(kp['text'] or '0') * 10 ** kp['dec'])
            except ValueError:
                v = None
            if v is not None and kp['min'] <= v <= kp['max']:
                self.set_word(kp['vp'], v)
                self._emit(dgus.reply_words(kp['vp'], v), f'input 0x{kp["vp"]:04X}={v}')
                self.page, self.keypad = kp['return_page'], None
            else:
                kp['text'] = ''
                self._note('local', None, f'input out of range {kp["min"]}..{kp["max"]}')
        elif len(kp['text']) < 8:
            kp['text'] += chr(code)

    # ---- rendering --------------------------------------------------------------------------
    def _font(self, px):
        if px not in self._fonts:
            try:
                # load from memory: FreeType maps a font opened by path, and on Windows a
                # mapped file can't be overwritten, which broke `crm4ui build --force`
                # into the folder the emulator was showing
                if self._font_bytes is None:
                    with open(self.font_path, 'rb') as fh:
                        self._font_bytes = fh.read()
                self._fonts[px] = ImageFont.truetype(io.BytesIO(self._font_bytes), px)
            except OSError:
                self._fonts[px] = ImageFont.load_default(px)
        return self._fonts[px]

    def _background(self, page):
        if page not in self._bg:
            z = self.project.images.get(page)
            self._bg[page] = z.to_image(upright=True) if z else Image.new('RGB', (480, 800), (60, 0, 60))
        return self._bg[page]

    def render(self, overlay=False):
        with self.lock:
            page = self.page
            im = self._background(page).copy()
            dr = ImageDraw.Draw(im)
            for r in self.project.vars.pages.get(page, []):
                r = self._live(r)
                if r.vp >= 0xFF00:                          # hidden through its SP
                    continue
                self._draw_var(im, dr, r)
            if self.keypad and page == self.keypad['page']:
                kp = self.keypad                                  # input box (page 40 and copies): 20,128..459,295
                dr.text((40, 175), kp['text'] or ' ', font=self._font(64), fill=(0, 0, 0))
                lim = f"{kp['min'] / 10 ** kp['dec']:g} .. {kp['max'] / 10 ** kp['dec']:g}"
                dr.text((40, 255), lim, font=self._font(22), fill=(120, 120, 120))
            if overlay:
                for t in self.project.touch.page(page):
                    x0, y0, x1, y1 = t.area
                    dr.rectangle([min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)], outline=(255, 60, 60))
            return im

    def _picture(self, vp):
        """JPEG written by the host: VP = 5A A5, VP+1 = length, data from VP+2 (stock format)."""
        if self.word(vp) != 0x5AA5:
            return None
        n = self.word(vp + 1)
        data = bytes(self.mem[2 * (vp + 2):2 * (vp + 2) + n])
        key = (vp, hash(data))
        if self._pictures.get('key') != key:
            try:
                pic = Image.open(io.BytesIO(data)).convert('RGB')
                pic.load()
            except Exception:
                pic = None
            self._pictures = {'key': key, 'img': pic}
        return self._pictures['img']

    def _draw_var(self, im, dr, r):
        x = r.data
        if r.type == 0x00:                                      # icon variable
            d = r.describe()
            v = self.word(r.vp)
            if d['v_min'] <= v <= d['v_max']:
                lib = self.project.icons.get(d['icon_lib'])
                ic = lib.get(d['icon_min'] + v - d['v_min']) if lib else None
                if ic is not None:
                    img = ic.to_image()
                    im.paste(img, tuple(r.pos), img.convert('L').point(lambda p: 255 if p > 8 else 0))
        elif r.type == 0x10:                                    # number
            ints, decs = r.digits
            v = dgus.to_signed(self.word(r.vp))
            s = f'{v / 10 ** decs:.{decs}f}' if decs else str(v)
            px = max(10, int(x[15] * 1.6))                      # ASSUMPTION: font size -> pixels
            dr.text(tuple(r.pos), s, font=self._font(px), fill=_rgb(r.color))
        elif r.type == 0x11:                                    # text
            s = self.text(r.vp, r.text_len)
            if s:
                b = r.box
                px = max(10, int(x[27] * 0.85))                 # ASSUMPTION: y dot size -> pixels
                dr.text((min(b[0], b[2]), min(b[1], b[3])), s, font=self._font(px), fill=_rgb(r.color))
        elif r.type == 0x08:                                    # JPEG picture control (thumbnail)
            img = self._picture(r.vp)
            if img is not None:
                im.paste(img, tuple(r.pos))
        elif r.type == 0x20:                                    # trend curve from a ring buffer
            self._draw_curve(dr, r)
        elif r.type == 0x26:                                    # dim area: blend toward black by VP value
            b = r.box
            x0, y0, x1, y1 = min(b[0], b[2]), min(b[1], b[3]), max(b[0], b[2]), max(b[1], b[3])
            alpha = min(255, self.word(r.vp))
            if alpha and x1 > x0 and y1 > y0:
                region = im.crop((x0, y0, x1, y1))
                im.paste(Image.blend(region, Image.new('RGB', region.size, (0, 0, 0)), alpha / 255), (x0, y0))

    def _draw_curve(self, dr, r):
        """Polyline of the channel's newest points. ASSUMPTION: points are Dis_HOR pixels
        apart from the left edge and the view scrolls once the area is full (DGUS-II
        real-time curve); y = Y_Central - (value - VD_Central) * Mul_Y / 256."""
        d = r.describe()
        pts = list(self.curves[d['channel']]) if d['channel'] < CURVE_CHANNELS else []
        if len(pts) < 2:
            return
        b = d['box']
        x0, y0, x1, y1 = min(b[0], b[2]), min(b[1], b[3]), max(b[0], b[2]), max(b[1], b[3])
        step = max(1, d['dis_hor'])
        pts = pts[-((x1 - x0) // step + 1):]
        scale = d['mul_y'] / 256.0
        xy = [(x0 + i * step, max(y0, min(y1, round(d['y_center'] - (v - d['vd_central']) * scale))))
              for i, v in enumerate(pts)]
        dr.line(xy, fill=_rgb(r.color), width=2)


def _rgb(c):
    r, g, b = (c >> 11) & 0x1F, (c >> 5) & 0x3F, c & 0x1F
    return ((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2))
