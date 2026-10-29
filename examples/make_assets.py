#!/usr/bin/env python3
"""Generate the example PNG assets (re-run after changing the drawing code).

All images are drawn upright, in panel coordinates (480x800 portrait).
Colours match the stock V2.0.3 theme: black background, card grey
(33,32,33), accent cyan (66,190,214).
"""
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
BLACK, CARD, ACCENT, WHITE = (0, 0, 0), (33, 32, 33), (66, 190, 214), (255, 255, 255)
RED = (200, 40, 40)


def font(size):
    for p in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
              'C:/Windows/Fonts/segoeui.ttf', 'C:/Windows/Fonts/arial.ttf'):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


def centered(dr, cx, y, text, f, fill):
    w = dr.textlength(text, font=f)
    dr.text((cx - w / 2, y), text, font=f, fill=fill)


def splash():
    im = Image.new('RGB', (480, 800), BLACK)
    dr = ImageDraw.Draw(im)
    centered(dr, 240, 300, 'CR-M4', font(84), WHITE)
    centered(dr, 240, 410, 'Klipper', font(40), ACCENT)
    # y 560..600 stays clear: the stock progress bar (VP 0x4200) draws there
    out = os.path.join(HERE, 'splash')
    os.makedirs(out, exist_ok=True)
    im.save(os.path.join(out, 'splash.png'))


def back_arrow(dr, x, y):
    dr.line([(x, y + 20), (x + 40, y + 20)], fill=WHITE, width=4)
    dr.line([(x, y + 20), (x + 16, y + 4)], fill=WHITE, width=4)
    dr.line([(x, y + 20), (x + 16, y + 36)], fill=WHITE, width=4)


def machine_assets():
    out = os.path.join(HERE, 'machine_page')
    os.makedirs(out, exist_ok=True)

    # Replacement content for the stock "WiFi" tile on page 121 (tile spans 245,31..472,164).
    tile = Image.new('RGB', (210, 120), CARD)
    dr = ImageDraw.Draw(tile)
    # simple "power/restart" glyph
    dr.arc([8, 6, 52, 50], 300, 240, fill=WHITE, width=5)
    dr.line([(30, 2), (30, 26)], fill=WHITE, width=5)
    dr.text((8, 70), 'Machine', font=font(30), fill=WHITE)
    tile.save(os.path.join(out, 'machine_tile.png'))

    # Page 45 background: Klipper and Host sections, E-STOP, status panel.
    # Drawn in the Klipper theme (klipper_branding) since the page is added after its recolour.
    red, grey = (177, 47, 53), (160, 160, 160)
    im = Image.new('RGB', (480, 800), BLACK)
    dr = ImageDraw.Draw(im)
    back_arrow(dr, 24, 20)
    dr.text((90, 18), 'Machine', font=font(34), fill=WHITE)
    dr.text((16, 84), 'Klipper', font=font(22), fill=grey)
    dr.text((16, 228), 'Host', font=font(22), fill=grey)
    cards = [((12, 116, 236, 206), CARD, 'Restart'),
             ((244, 116, 468, 206), CARD, 'Firmware restart'),
             ((12, 260, 236, 350), CARD, 'Reboot'),
             ((244, 260, 468, 350), CARD, 'Shutdown'),
             ((12, 378, 468, 468), red, 'EMERGENCY STOP')]
    for box, col, label in cards:
        dr.rounded_rectangle(box, 14, fill=col)
        f = font(30 if dr.textlength(label, font=font(30)) < box[2] - box[0] - 20 else 24)
        centered(dr, (box[0] + box[2]) / 2, (box[1] + box[3]) / 2 - f.size * 0.6, label, f, WHITE)
    dr.rounded_rectangle((12, 496, 468, 700), 14, fill=CARD)
    dr.text((28, 508), 'Klipper state', font=font(22), fill=grey)
    dr.text((28, 600), 'Message', font=font(22), fill=grey)
    im.save(os.path.join(out, 'page45.png'))


if __name__ == '__main__':
    splash()
    machine_assets()
    print('assets written')
