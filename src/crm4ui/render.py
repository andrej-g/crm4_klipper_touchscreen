"""UI map dumps and page previews."""
import json
import os

from PIL import Image, ImageDraw

LANG_VP = 0x5247   # icon variables on this VP pick a label per UI language (0=zh, 1=en, ...)


def ui_map(project) -> dict:
    pages = {}
    for p in project.page_ids():
        pages[p] = {'image': p in project.images,
                    'touch': [r.describe() for r in project.touch.page(p)],
                    'vars': [r.describe() for r in project.vars.pages.get(p, [])]}
    return pages


def write_map(project, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    m = ui_map(project)
    with open(os.path.join(out_dir, 'ui_map.json'), 'w', encoding='utf-8') as f:
        json.dump({str(k): v for k, v in m.items()}, f, indent=1)
    lines = ['# Screen UI map', '',
             'Coordinates are panel coordinates (480x800 portrait, as viewed).', '']
    for p, pg in m.items():
        lines.append(f'## Page {p}' + ('' if pg['image'] else ' (no background image)'))
        for v in pg['vars']:
            extra = {k: v[k] for k in v if k not in ('kind', 'type', 'vp', 'pos')}
            lines.append(f"- var `{v['vp']}` {v['kind']} at {tuple(v['pos'])} {extra}")
        for t in pg['touch']:
            what = t.get('key') or t.get('ascii') or t.get('op') or ''
            nxt = f" -> page {t['page_next']}" if t['page_next'] is not None else ''
            rng = f" range {t['min']}..{t['max']}" if 'min' in t else ''
            lines.append(f"- touch {tuple(t['area'])} {t['kind']} vp `{t.get('vp', '-')}` {what}{nxt}{rng}")
        lines.append('')
    with open(os.path.join(out_dir, 'ui_map.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    return m


def _paste_icon(im, project, lib_id, icon_id, pos):
    lib = project.icons.get(lib_id)
    ic = lib.get(icon_id) if lib else None
    if ic is None:
        return
    img = ic.to_image()
    mask = img.convert('L').point(lambda x: 255 if x > 8 else 0)   # black = transparent
    im.paste(img, tuple(pos), mask)


def render_page(project, page, lang=1, overlay=True) -> Image.Image:
    z = project.images.get(page)
    im = z.to_image(upright=True) if z else Image.new('RGB', (480, 800), (40, 0, 40))
    recs = project.vars.pages.get(page, [])
    for r in recs:
        if r.type == 0x00:
            d = r.describe()
            icon = d['icon_min'] + lang if r.vp == LANG_VP else d['icon_min']
            _paste_icon(im, project, d['icon_lib'], icon, r.pos)
    if overlay:
        dr = ImageDraw.Draw(im)
        for r in recs:
            b = r.box
            if b:
                dr.rectangle([min(b[0], b[2]), min(b[1], b[3]), max(b[0], b[2]), max(b[1], b[3])],
                             outline=(80, 200, 255))
            if r.type != 0x00:
                dr.text((r.pos[0] + 2, r.pos[1] + 12), f'0x{r.vp:04X}', fill=(120, 255, 120))
        for t in project.touch.page(page):
            x0, y0, x1, y1 = t.area
            dr.rectangle([min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)], outline=(255, 60, 60))
            d = t.describe()
            lab = f"{d.get('vp', '')}:{d.get('key', d.get('ascii', d.get('op', '')))}"
            if t.page_next is not None:
                lab += f'>{t.page_next}'
            dr.text((min(x0, x1) + 2, min(y0, y1) + 1), lab, fill=(255, 120, 120))
    return im


def render_all(project, out_dir, lang=1, overlay=True, pages=None, sheet=True):
    os.makedirs(out_dir, exist_ok=True)
    pages = pages or sorted(project.images)
    done = []
    for p in pages:
        render_page(project, p, lang, overlay).save(os.path.join(out_dir, f'page_{p:03d}.png'))
        done.append(p)
    if sheet and done:
        for s in range(0, len(done), 8):
            sh = Image.new('RGB', (4 * 240, 2 * 420), 'white')
            dr = ImageDraw.Draw(sh)
            for k, p in enumerate(done[s:s + 8]):
                x, y = (k % 4) * 240, (k // 4) * 420
                sh.paste(Image.open(os.path.join(out_dir, f'page_{p:03d}.png')).resize((240, 400)), (x, y + 20))
                dr.text((x + 4, y + 4), f'page {p}', fill='black')
            sh.save(os.path.join(out_dir, f'sheet_{s // 8:02d}.png'))
    return done


def export_assets(project, out_dir):
    """Upright PNGs of every page background and every icon, as editing sources."""
    os.makedirs(os.path.join(out_dir, 'image'), exist_ok=True)
    for p, z in project.images.items():
        z.to_image(upright=True).save(os.path.join(out_dir, 'image', f'{p}.png'))
    for lib_id, lib in project.icons.items():
        d = os.path.join(out_dir, 'icon', str(lib_id))
        os.makedirs(d, exist_ok=True)
        for ic in lib.icons:
            ic.to_image().save(os.path.join(d, f'{ic.id}.png'))
