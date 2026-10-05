#!/usr/bin/env python3
"""Render klipper-logo.svg into the 480x800 boot splash (splash.png).

The SVG is rasterised with cairosvg if installed, otherwise with a headless
Chromium through Playwright (``pip install playwright && playwright install chromium``).
The logo is centred in the upper part of the screen; the band at y 540..620
stays clear for the stock boot progress bar (VP 0x4200).

    python make_splash.py [klipper-logo.svg] [splash.png] [--width 340] [--bg "#000000"]
"""
import argparse
import io
import os

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))


def rasterise(svg_path, width):
    try:
        import cairosvg
        png = cairosvg.svg2png(url=svg_path, output_width=width)
        return Image.open(io.BytesIO(png)).convert('RGBA')
    except ImportError:
        pass
    from playwright.sync_api import sync_playwright
    svg = open(svg_path, 'rb').read().decode('utf-8')
    html = ('<html><body style="margin:0;background:transparent">'
            f'<div id="l" style="width:{width}px;display:inline-block;line-height:0">{svg}</div></body></html>')
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={'width': width + 20, 'height': 2000})
        pg.set_content(html)
        pg.eval_on_selector('#l svg', 'e => { e.setAttribute("width", "%d"); e.removeAttribute("height"); }' % width)
        png = pg.locator('#l').screenshot(omit_background=True)
        b.close()
    return Image.open(io.BytesIO(png)).convert('RGBA')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('svg', nargs='?', default=os.path.join(HERE, 'klipper-logo.svg'))
    ap.add_argument('out', nargs='?', default=os.path.join(HERE, 'splash.png'))
    ap.add_argument('--width', type=int, default=340)
    ap.add_argument('--bg', default='#000000')
    a = ap.parse_args()

    logo = rasterise(a.svg, a.width)
    bbox = logo.getbbox()
    if bbox:
        logo = logo.crop(bbox)
    max_h = 440
    if logo.height > max_h:
        logo = logo.resize((round(logo.width * max_h / logo.height), max_h), Image.LANCZOS)
    splash = Image.new('RGB', (480, 800), a.bg)
    x = (480 - logo.width) // 2
    y = max(40, (520 - logo.height) // 2)
    splash.paste(logo, (x, y), logo)
    splash.save(a.out)
    print(f'{a.out}: logo {logo.width}x{logo.height} at {x},{y}')


if __name__ == '__main__':
    main()
