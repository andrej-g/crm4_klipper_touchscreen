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


class ScreenSim:
    def __init__(self, project, start_page=0, lang=None, ack_writes=True, font_path=None):
        self.project = project
        self.mem = bytearray(project.vpmem.data)
        self.mem += bytes(max(0, 2 * 0x10000 - len(self.mem)))        # full 64 Ki-word space
        self.page = start_page
        self.ack_writes = ack_writes                                   # ASSUMPTION: DGUS-II "OK" acks
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
        if lang is not None:
            self.set_word(0x5247, lang)

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
                self._note('host->scr', frame, note)
                if self.ack_writes:
                    self._emit(dgus.ACK, 'ack')
                self._bump()
            elif frame.cmd == dgus.CMD_READ and len(frame.data) >= 3:
                vp, n = frame.vp, frame.data[2]
                self._note('host->scr', frame, f'read 0x{vp:04X} x{n}')
                self._emit(dgus.reply_words(vp, *[self.word(vp + i) for i in range(n)]), 'read reply')
            else:
                self._note('host->scr', frame, 'ignored')
                self._bump()

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
        elif r.type == 0x26:                                    # thumbnail area: placeholder
            b = r.box
            dr.rectangle([b[0], b[1], b[2], b[3]], outline=(90, 90, 90))


def _rgb(c):
    r, g, b = (c >> 11) & 0x1F, (c >> 5) & 0x3F, c & 0x1F
    return ((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2))
