#!/usr/bin/env python3
"""Build the replacement for the stock mascot icon (lib 18, icons 4 and 5)
from a boat (Benchy) silhouette image.

The source is a flat-colour drawing: the coloured area is the boat, and white
areas enclosed by it (window, porthole, deck line) are details. The outline
is traced from the image and redrawn in the UI's style:
- light grey with print layer lines and dark details;
- a cyan accent outline, like the stock mascot;
- icon 5 is the same, dimmed.
Both icons are 300x300 on black (black = transparency key).

    python make_boat.py SOURCE_IMAGE [--color "#0596c8"]  -> boat.png, boat_dim.png

The source image is not kept in this repository (see .gitignore); only the
generated icons are.
"""
import argparse
import os

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
W = H = 300
FIT_W, FIT_H = 264, 236          # drawing area inside the icon
ACCENT = (66, 190, 214)


def masks(src, color, tol, closing=6):
    """(body, details): body = coloured area with holes filled, details = holes."""
    a = np.asarray(src.convert('RGB')).astype(np.int32)
    c = np.array(color)
    dist = np.sqrt(((a - c) ** 2).sum(-1))
    paint = np.clip((tol * 1.6 - dist) / (tol * 0.6), 0, 1)          # soft edge
    hard = Image.fromarray(((paint > 0.5) * 255).astype(np.uint8), 'L')
    # close the thin white lines (deck line, window frame) that run out to the
    # edge, so they count as details rather than as outside
    k = closing * 2 + 1
    hard = hard.filter(ImageFilter.MaxFilter(k)).filter(ImageFilter.MinFilter(k))
    # outside = everything reachable from the border without crossing paint
    pad = Image.new('L', (hard.width + 2, hard.height + 2), 0)
    pad.paste(hard, (1, 1))
    ImageDraw.floodfill(pad, (0, 0), 128)
    outside = np.asarray(pad)[1:-1, 1:-1] == 128
    body = ~outside
    details = body & (paint < 0.5)
    soft_body = np.where(outside, 0.0, 1.0)
    return (Image.fromarray((soft_body * 255).astype(np.uint8), 'L'),
            Image.fromarray((details * 255).astype(np.uint8), 'L'))


def render(body, details, dim=False, scale=4):
    """body/details: 'L' masks already cropped to the boat; returns a 300x300 RGB icon."""
    s = min(FIT_W / body.width, FIT_H / body.height)
    bw, bh = round(body.width * s * scale), round(body.height * s * scale)
    body = body.resize((bw, bh), Image.LANCZOS)
    details = details.resize((bw, bh), Image.LANCZOS)
    big = (W * scale, H * scale)
    ox, oy = (big[0] - bw) // 2, (big[1] - bh) // 2 + 8 * scale
    B = Image.new('L', big, 0)
    B.paste(body, (ox, oy))
    D = Image.new('L', big, 0)
    D.paste(details, (ox, oy))

    shade = Image.linear_gradient('L').resize(big)
    top, bottom = (236, 176) if not dim else (110, 80)
    fill = Image.merge('RGB', [shade.point(lambda v: top - (top - bottom) * v // 255)] * 3)
    lines = Image.new('L', big, 0)
    ld = ImageDraw.Draw(lines)
    for y in range(oy, oy + bh, 6 * scale):                         # printed layer lines
        ld.line([(0, y), (big[0], y)], fill=55 if not dim else 28, width=scale)
    fill = ImageChops.subtract(fill, Image.merge('RGB', [lines] * 3))

    img = Image.new('RGB', big, (0, 0, 0))
    img.paste(fill, (0, 0), B)
    img.paste((22, 26, 30) if not dim else (11, 13, 15), (0, 0), D)
    edge = ImageChops.subtract(B.filter(ImageFilter.MaxFilter(4 * scale + 1)), B)
    img.paste(ACCENT if not dim else tuple(c // 2 for c in ACCENT), (0, 0), edge)
    img = img.resize((W, H), Image.LANCZOS)
    return img.point(lambda v: 0 if v < 6 else v)                   # clean transparency key


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('source', help='flat-colour boat image (e.g. a Benchy sticker)')
    ap.add_argument('--color', default='#0596c8', help='boat colour in the source (default: auto)')
    ap.add_argument('--tol', type=float, default=70, help='colour tolerance')
    ap.add_argument('--closing', type=int, default=6, help='px: bridge white lines up to ~2x this wide')
    ap.add_argument('--auto', action='store_true', default=True)
    a = ap.parse_args()

    src = Image.open(a.source).convert('RGB')
    arr = np.asarray(src).astype(np.int32)
    if a.auto:
        # most saturated common colour = the boat
        sat = arr.max(-1) - arr.min(-1)
        sel = arr[sat > 100]
        color = tuple(int(x) for x in np.median(sel, 0)) if len(sel) else (5, 150, 200)
    else:
        color = tuple(int(a.color[i:i + 2], 16) for i in (1, 3, 5))
    body, details = masks(src, color, a.tol, a.closing)
    box = body.getbbox()
    body, details = body.crop(box), details.crop(box)
    render(body, details).save(os.path.join(HERE, 'boat.png'))
    render(body, details, dim=True).save(os.path.join(HERE, 'boat_dim.png'))
    print(f'boat colour {color}, outline bbox {box} -> boat.png, boat_dim.png')


if __name__ == '__main__':
    main()
