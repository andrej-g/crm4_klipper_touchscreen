#!/usr/bin/env python3
"""Draw the Spoolman tile, material badges and colour swatches.

    PYTHONPATH=src python examples/spoolman/make_icons.py

The badge and swatch order comes from crm4bridge.spoolman (MATERIALS, COLOURS),
the same tables the bridge uses to pick the icon. Pure black is the icon
transparency key, so "black" is drawn as a very dark grey and every icon sits
on a black background.
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'src'))
from crm4bridge.spoolman import COLOURS, MATERIALS, _rgb  # noqa: E402

CARD = (33, 32, 33)
RING = (150, 150, 150)
S = 4                                    # supersampling


def font(size):
    for p in ('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
              'C:/Windows/Fonts/segoeuib.ttf', 'C:/Windows/Fonts/arialbd.ttf'):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


def no_black(img):
    """Lift pure-black pixels inside a shape to 1/1/1 so they aren't transparent."""
    px = img.load()
    for y in range(img.size[1]):
        for x in range(img.size[0]):
            if px[x, y] == (0, 0, 0):
                continue
            r, g, b = px[x, y]
            if r < 8 and g < 8 and b < 8:     # anti-aliased edge: keep it visible, not transparent
                px[x, y] = (8, 8, 8)
    return img


def tile(w, h, path):
    im = Image.new('RGB', (w * S, h * S), (0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle([0, 0, w * S - 1, h * S - 1], radius=8 * S, fill=CARD)
    im.resize((w, h), Image.LANCZOS).save(path)


def swatch(colour, d, path):
    im = Image.new('RGB', (d * S, d * S), (0, 0, 0))
    dr = ImageDraw.Draw(im)
    box = [S, S, d * S - S - 1, d * S - S - 1]
    if colour is None:
        dr.ellipse(box, outline=RING, width=2 * S)
    else:
        c = tuple(max(v, 12) for v in _rgb(colour))
        dr.ellipse(box, fill=c, outline=RING, width=S)
    no_black(im.resize((d, d), Image.LANCZOS)).save(path)


def badge(text, w, h, path):
    im = Image.new('RGB', (w * S, h * S), (0, 0, 0))
    if text:
        dr = ImageDraw.Draw(im)
        dr.rounded_rectangle([S, S, w * S - S - 1, h * S - S - 1], radius=6 * S, outline=(230, 230, 230), width=2 * S)
        size = 15 if len(text) <= 5 else 13
        f = font(size * S)
        tw = dr.textlength(text, font=f)
        l, t, r, b = f.getbbox(text)
        dr.text(((w * S - tw) / 2, (h * S - (b - t)) / 2 - t), text, font=f, fill=(255, 255, 255))
    no_black(im.resize((w, h), Image.LANCZOS)).save(path)


def main():
    out = os.path.join(HERE, 'icons')
    os.makedirs(out, exist_ok=True)
    tile(452, 60, os.path.join(HERE, 'tile_print.png'))
    tile(452, 42, os.path.join(HERE, 'tile_status.png'))
    for i, (_, c) in enumerate(COLOURS):
        swatch(c, 32, os.path.join(out, f'swatch_{i:02d}.png'))
    for i, m in enumerate(MATERIALS):
        badge(m, 78, 30, os.path.join(out, f'badge_{i}.png'))
    print('written to', HERE)


if __name__ == '__main__':
    main()
