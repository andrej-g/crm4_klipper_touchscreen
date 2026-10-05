#!/usr/bin/env python3
"""Draw the replacement for the stock mascot icon (lib 18, icons 4 and 5):
an original little printed tugboat, with layer lines, in the UI's palette.

Icon 4 is the normal state, icon 5 the dimmed one. Both are 300x300 on black,
because black is the icon transparency key.

    python make_boat.py            -> boat.png, boat_dim.png
"""
import os

from PIL import Image, ImageChops, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
S = 4                       # supersampling
W = H = 300
ACCENT = (66, 190, 214)


DY = 22                     # vertical offset that centres the drawing in the icon


def P(*pts):
    return [(x * S, (y + DY) * S) for x, y in pts]


def silhouette():
    """White-on-black mask of the boat."""
    m = Image.new('L', (W * S, H * S), 0)
    d = ImageDraw.Draw(m)
    # hull: flat stern on the left, raised bow on the right
    d.polygon(P((30, 168), (236, 166), (258, 156), (270, 146), (262, 172), (236, 212), (64, 212), (42, 196)), fill=255)
    # bulwark rail along the deck
    d.rectangle([*P((36, 160))[0], *P((240, 170))[0]], fill=255)
    # cabin and wheelhouse
    d.rounded_rectangle([*P((86, 112))[0], *P((186, 168))[0]], radius=8 * S, fill=255)
    d.rounded_rectangle([*P((104, 66))[0], *P((172, 116))[0]], radius=8 * S, fill=255)
    d.rectangle([*P((96, 58))[0], *P((180, 68))[0]], fill=255)                     # roof overhang
    # funnel, slightly raked
    d.polygon(P((194, 74), (216, 70), (222, 150), (196, 150)), fill=255)
    # mast
    d.rectangle([*P((136, 36))[0], *P((141, 60))[0]], fill=255)
    return m


def windows():
    m = Image.new('L', (W * S, H * S), 0)
    d = ImageDraw.Draw(m)
    for x in (112, 140):
        d.rounded_rectangle([*P((x, 76))[0], *P((x + 22, 98))[0]], radius=4 * S, fill=255)
    for x in (100, 126, 152):
        d.ellipse([*P((x, 128))[0], *P((x + 16, 144))[0]], fill=255)               # portholes
    d.ellipse([*P((222, 176))[0], *P((234, 188))[0]], fill=255)                     # hawse hole
    d.polygon(P((195, 82), (217, 78), (218, 90), (196, 94)), fill=255)            # funnel band
    return m


def draw(dim=False):
    body = silhouette()
    win = windows()
    # vertical shading, light at the top
    shade = Image.linear_gradient('L').resize((W * S, H * S))
    top, bottom = (238, 178) if not dim else (110, 80)
    fill = Image.merge('RGB', [shade.point(lambda v: top - (top - bottom) * v // 255)] * 3)
    # printed layer lines every 6 px
    lines = Image.new('L', (W * S, H * S), 0)
    ld = ImageDraw.Draw(lines)
    for y in range(36 + DY, 216 + DY, 6):
        ld.line([(0, y * S), (W * S, y * S)], fill=60 if not dim else 30, width=S)
    fill = ImageChops.subtract(fill, Image.merge('RGB', [lines] * 3))
    img = Image.new('RGB', (W * S, H * S), (0, 0, 0))
    img.paste(fill, (0, 0), body)
    img.paste((20, 24, 28) if not dim else (10, 12, 14), (0, 0), ImageChops.multiply(win, body))
    # accent outline, like the stock mascot
    edge = ImageChops.subtract(body.filter(ImageFilter.MaxFilter(4 * S + 1)), body)
    acc = ACCENT if not dim else tuple(c // 2 for c in ACCENT)
    img.paste(acc, (0, 0), edge)
    img = img.resize((W, H), Image.LANCZOS)
    # keep the transparency key clean: near-black -> pure black
    return img.point(lambda v: 0 if v < 6 else v)


if __name__ == '__main__':
    draw().save(os.path.join(HERE, 'boat.png'))
    draw(dim=True).save(os.path.join(HERE, 'boat_dim.png'))
    print('boat.png, boat_dim.png written')
