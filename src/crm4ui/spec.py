"""Apply a build spec (YAML or JSON) to a Project.

See ``docs/spec.md`` for the full reference. Paths in a spec are relative to the
spec file. Integers may be written as ``0x9010`` (YAML) or ``"0x9010"`` (JSON).
"""
import json
import os

from PIL import Image

from .formats import TouchRecord, VarRecord
from .recolor import HueRule, recolor_project

PANEL_W, PANEL_H = 480, 800
NO_SP = 0xFFFF


class SpecError(ValueError):
    pass


def load_spec(path):
    with open(path, 'r', encoding='utf-8') as f:
        text = f.read()
    if path.lower().endswith(('.yaml', '.yml')):
        import yaml
        spec = yaml.safe_load(text) or {}
    else:
        spec = json.loads(text)
    spec['_base_dir'] = os.path.dirname(os.path.abspath(path))
    return spec


def _int(v):
    if isinstance(v, str):
        return int(v, 0)
    return int(v)


def _color565(v):
    """RGB565 int from 0xRRRR (int / '0x..') or '#rrggbb'."""
    if isinstance(v, str) and v.startswith('#'):
        r, g, b = (int(v[i:i + 2], 16) for i in (1, 3, 5))
        return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
    return _int(v)


def _opt_int(v):
    return None if v is None else _int(v)


def _path(spec, p):
    return p if os.path.isabs(p) else os.path.join(spec['_base_dir'], p)


def _check_area(a, what):
    a = [_int(x) for x in a]
    if len(a) != 4 or not (0 <= a[0] <= PANEL_W and 0 <= a[2] <= PANEL_W and
                           0 <= a[1] <= PANEL_H and 0 <= a[3] <= PANEL_H):
        raise SpecError(f'{what}: area/box {a} outside the 480x800 panel')
    return a


def _load_png(spec, p, size=None):
    img = Image.open(_path(spec, p)).convert('RGB')
    if size and img.size != size:
        raise SpecError(f'{p}: expected {size[0]}x{size[1]}, got {img.size[0]}x{img.size[1]}')
    return img


# ---- record builders ------------------------------------------------------------
def build_text(project, d):
    t = project.vars.template(0x11).copy()
    box = _check_area(d['box'], 'text')
    t.data[2:4] = NO_SP.to_bytes(2, 'big')
    t.vp = _int(d['vp'])
    t.pos = box[:2]
    t.box = box
    t.color = _int(d.get('color', 0xFFFF))
    t.text_len = _int(d.get('length', 20))
    return t


def build_number(project, d):
    t = project.vars.template(0x10).copy()
    t.data[2:4] = NO_SP.to_bytes(2, 'big')
    t.vp = _int(d['vp'])
    t.pos = [_int(x) for x in d['pos']]
    t.color = _int(d.get('color', 0xFFFF))
    t.digits = (_int(d.get('int_digits', 3)), _int(d.get('dec_digits', 0)))
    if 'font_size' in d:
        t.data[15] = _int(d['font_size'])
    if 'align' in d:
        t.data[16] = _int(d['align'])
    return t


def build_clone(project, d):
    src = None
    for r in project.vars.pages.get(_int(d['from_page']), []):
        if r.vp == _int(d['vp']):
            src = r
            break
    if src is None:
        raise SpecError(f"clone: no record VP {d['vp']} on page {d['from_page']}")
    r = src.copy()
    if 'pos' in d:
        r.pos = [_int(x) for x in d['pos']]
    if 'new_vp' in d:
        r.vp = _int(d['new_vp'])
    return r


VAR_BUILDERS = {'text': build_text, 'number': build_number, 'clone': build_clone}


def build_touch(page, d, project=None):
    typ = d.get('type', 'return_key')
    area = _check_area(d['area'], 'touch')
    if typ == 'clone':
        # copy an existing record (numeric input, increment, ...) onto this page
        src = project.touch.find(page=_int(d['from_page']), vp=_int(d['vp']),
                                 key=_opt_int(d.get('key')))
        if len(src) != 1:
            raise SpecError(f'touch clone: page {d["from_page"]} VP {d["vp"]} matches {len(src)} records')
        r = src[0].copy()
        r.page, r.area = page, area
        if 'page_next' in d:
            r.page_next = _opt_int(d['page_next'])
        if 'keyboard_page' in d:
            if r.kind != 'data_input':
                raise SpecError('touch clone: keyboard_page needs a numeric input record')
            r.keyboard_page = _int(d['keyboard_page'])
        return r
    flags = _int(d.get('flags', 0x0C))
    if typ == 'return_key':
        return TouchRecord.return_key(page, area, _int(d['vp']), _int(d['key']),
                                      page_next=_opt_int(d.get('page_next')),
                                      page_on=_opt_int(d.get('page_on')), flags=flags)
    if typ == 'page_jump':
        return TouchRecord.page_jump(page, area, _int(d['page']), flags=flags)
    raise SpecError(f'unknown touch type {typ!r} (supported: return_key, page_jump, clone)')


# ---- spec sections ----------------------------------------------------------------
def apply(project, spec, log=print):
    for inc in spec.get('include') or []:
        path = _path(spec, inc)
        log(f'include {inc}')
        apply(project, load_spec(path), log)

    # copies first, so the rest of this spec (retouch, fields, touches) can edit them
    for d in spec.get('copy_pages') or []:
        copy_page(project, _int(d['from']), _int(d['to']))
        log(f'page {d["from"]} copied to {d["to"]}')

    for k, p in (spec.get('images') or {}).items():
        page = _int(k)
        img = _load_png(spec, p, (PANEL_W, PANEL_H))
        if page in project.images:
            project.images[page].set_image(img)
        else:
            from .formats import ZBmp
            project.images[page] = ZBmp.from_image(img)
        log(f'image {page}: replaced from {p}')

    for d in spec.get('image_patches') or []:
        page = _int(d['page'])
        if page not in project.images:
            raise SpecError(f'image_patches: page {page} has no image')
        z = project.images[page]
        img = z.to_image(upright=True)
        patch = _load_png(spec, d['png'])
        pos = [_int(x) for x in d['pos']]
        _check_area([pos[0], pos[1], pos[0] + patch.size[0], pos[1] + patch.size[1]], 'image_patches')
        img.paste(patch, tuple(pos))
        z.set_image(img)
        log(f'image {page}: patched {d["png"]} at {tuple(pos)}')

    for d in spec.get('retouch') or []:
        apply_retouch(project, spec, d)
        log(f'retouch {d.get("target", "page")} {d.get("page", "")}{d.get("lib", "")}'
            f'{"/" + str(d["id"]) if "id" in d else ""} -> {d.get("text", "")!r}')

    for d in spec.get('remove_vars') or []:
        page, vp = _int(d['page']), _int(d['vp'])
        before = project.vars.pages.get(page, [])
        after = [r for r in before if r.vp != vp]
        if len(after) == len(before):
            raise SpecError(f'remove_vars: no VP 0x{vp:04X} on page {page}')
        project.vars.pages[page] = after
        log(f'page {page}: removed {len(before) - len(after)} field(s) on VP 0x{vp:04X}')

    for d in spec.get('icons') or []:
        lib_id, icon_id = _int(d['lib']), _int(d['id'])
        if lib_id not in project.icons:
            raise SpecError(f'icon library {lib_id} does not exist')
        project.icons[lib_id].put(icon_id, _load_png(spec, d['png']))
        log(f'icon {lib_id}/{icon_id}: replaced from {d["png"]}')

    for d in spec.get('pages') or []:
        apply_page(project, spec, d, log)

    for e in spec.get('touch_edits') or []:
        m = e.get('match') or {}
        hits = project.touch.find(page=_opt_int(m.get('page')), vp=_opt_int(m.get('vp')),
                                  key=_opt_int(m.get('key')))
        if 'kind' in m:
            hits = [r for r in hits if r.kind == m['kind']]
        if e.get('all') and not hits:
            raise SpecError(f'touch_edits match {m} hit no records')
        if not e.get('all') and len(hits) != 1:
            raise SpecError(f'touch_edits match {m} hit {len(hits)} records (need exactly 1, or all: true)')
        s = e.get('set') or {}
        for r in hits:
            if 'vp' in s:
                r.vp = _int(s['vp'])
            if 'key' in s:
                r.key = _int(s['key'])
            if 'page_next' in s:
                r.page_next = _opt_int(s['page_next'])
            if 'area' in s:
                r.area = _check_area(s['area'], 'touch_edits')
            if 'keyboard_page' in s:
                if r.kind != 'data_input':
                    raise SpecError(f'touch_edits {m}: keyboard_page needs a numeric input, '
                                    f'page {r.page} has a {r.kind}')
                r.keyboard_page = _int(s['keyboard_page'])
        log(f'touch edit {m} -> {s} ({len(hits)} record(s))')

    for d in spec.get('field_colors') or []:
        n = 0
        color = _color565(d['color'])
        for p, r in project.vars.all():
            if 'page' in d and p != _int(d['page']):
                continue
            if r.color is None:
                continue
            if ('vp' in d and r.vp == _int(d['vp'])) or ('from' in d and r.color == _color565(d['from'])):
                r.color = color
                n += 1
        if not n:
            raise SpecError(f'field_colors {d}: no matching record')
        log(f'field colour {d.get("vp", d.get("from"))}: {n} record(s)')

    rc = spec.get('recolor')
    if rc:
        rules = [HueRule.from_spec(r) for r in rc['rules']]
        n = recolor_project(project, rules, images=rc.get('images', True), icons=rc.get('icons', True),
                            fields=rc.get('fields', True),
                            skip_icon_libs=[_int(x) for x in rc.get('skip_icon_libs', [])])
        log(f'recolour: {n}')

    for d in spec.get('vp_defaults') or []:
        vp = _int(d['vp'])
        if 'text' in d:
            project.vpmem.set_text(vp, d['text'], _int(d['bytes']))
        else:
            project.vpmem.set_word(vp, _int(d['word']))
        log(f'vp default 0x{vp:04X}')


def _font(project, spec, name, size):
    from PIL import ImageFont
    if name in (None, 'stock'):
        path = os.path.join(project.root, 'truefont', 'font.ttf')
    else:
        path = _path(spec, name)
    try:
        return ImageFont.truetype(path, size)
    except OSError as e:
        raise SpecError(f'font {path}: {e}')


def _border_color(img, rect):
    x0, y0, x1, y1 = rect
    px = []
    for x in range(max(0, x0 - 1), min(img.size[0], x1 + 2)):
        for y in (y0 - 1, y1 + 1):
            if 0 <= y < img.size[1]:
                px.append(img.getpixel((x, y)))
    for y in range(max(0, y0), min(img.size[1], y1 + 1)):
        for x in (x0 - 1, x1 + 1):
            if 0 <= x < img.size[0]:
                px.append(img.getpixel((x, y)))
    if not px:
        return (0, 0, 0)
    return tuple(sorted(c[i] for c in px)[len(px) // 2] for i in range(3))


def _interpolate_rows(img, rect):
    """Fill rect from its four edges (bilinear Coons patch): keeps the shading
    gradient of curved surfaces such as the mascot's chest."""
    x0, y0, x1, y1 = rect
    W, H = img.size
    L = [img.getpixel((max(0, x0 - 1), y)) for y in range(y0, y1 + 1)]
    R = [img.getpixel((min(W - 1, x1 + 1), y)) for y in range(y0, y1 + 1)]
    T = [img.getpixel((x, max(0, y0 - 1))) for x in range(x0, x1 + 1)]
    B = [img.getpixel((x, min(H - 1, y1 + 1))) for x in range(x0, x1 + 1)]
    c00, c10 = img.getpixel((max(0, x0 - 1), max(0, y0 - 1))), img.getpixel((min(W - 1, x1 + 1), max(0, y0 - 1)))
    c01, c11 = img.getpixel((max(0, x0 - 1), min(H - 1, y1 + 1))), img.getpixel((min(W - 1, x1 + 1), min(H - 1, y1 + 1)))
    nw, nh = x1 - x0 + 2, y1 - y0 + 2
    for j, y in enumerate(range(y0, y1 + 1)):
        v = (j + 1) / nh
        for i, x in enumerate(range(x0, x1 + 1)):
            u = (i + 1) / nw
            px = []
            for k in range(3):
                lin_u = L[j][k] * (1 - u) + R[j][k] * u
                lin_v = T[i][k] * (1 - v) + B[i][k] * v
                bil = (c00[k] * (1 - u) * (1 - v) + c10[k] * u * (1 - v) +
                       c01[k] * (1 - u) * v + c11[k] * u * v)
                px.append(max(0, min(255, round(lin_u + lin_v - bil))))
            img.putpixel((x, y), tuple(px))


def retouch_image(img, project, spec, d):
    """Clear ``rect`` (fill colour or 'auto' = median of the surrounding pixels) and
    optionally draw ``text`` centred in it."""
    from PIL import ImageDraw
    rect = [_int(x) for x in d['rect']]
    if not (0 <= rect[0] <= rect[2] < img.size[0] and 0 <= rect[1] <= rect[3] < img.size[1]):
        raise SpecError(f'retouch rect {rect} outside the {img.size[0]}x{img.size[1]} image')
    fill = d.get('fill', 'auto')
    dr = ImageDraw.Draw(img)
    if fill == 'interpolate':
        _interpolate_rows(img, rect)
    else:
        dr.rectangle(rect, fill=_border_color(img, rect) if fill == 'auto' else fill)
    text = d.get('text')
    if text:
        f = _font(project, spec, d.get('font'), _int(d.get('size', 24)))
        spacing = _int(d.get('spacing', 0))
        stroke = _int(d.get('bold', 0))
        widths = [dr.textlength(ch, font=f) for ch in text]
        total = sum(widths) + spacing * (len(text) - 1)
        asc, desc = f.getmetrics()
        x = (rect[0] + rect[2]) / 2 - total / 2
        y = (rect[1] + rect[3]) / 2 - (asc + desc) / 2 + _int(d.get('dy', 0))
        color = d.get('color', '#FFFFFF')
        for ch, w in zip(text, widths):
            dr.text((x, y), ch, font=f, fill=color, stroke_width=stroke, stroke_fill=color)
            x += w + spacing
    return img


def apply_retouch(project, spec, d):
    target = d.get('target', 'page')
    if target == 'page':
        page = _int(d['page'])
        if page not in project.images:
            raise SpecError(f'retouch: page {page} has no image')
        z = project.images[page]
        z.set_image(retouch_image(z.to_image(upright=True), project, spec, d))
    elif target == 'icon':
        lib = project.icons.get(_int(d['lib']))
        ic = lib.get(_int(d['id'])) if lib else None
        if ic is None:
            raise SpecError(f'retouch: icon {d.get("lib")}/{d.get("id")} not found')
        lib.put(ic.id, retouch_image(ic.to_image(), project, spec, d))
    else:
        raise SpecError(f'retouch target must be page or icon, not {target!r}')


def copy_page(project, src, dst):
    """Duplicate a page (background, touch areas, fields) under a new id."""
    from .formats import ZBmp
    if not 0 <= dst <= 255:
        raise SpecError('page id must be 0..255')
    if dst in project.images or dst in project.vars.pages or project.touch.page(dst):
        raise SpecError(f'copy_pages: page {dst} already exists')
    if src not in project.images:
        raise SpecError(f'copy_pages: page {src} does not exist')
    z = project.images[src]
    project.images[dst] = ZBmp(z.width, z.height, z.raw, z.header_tail)
    for r in project.touch.page(src):
        c = r.copy()
        c.page = dst
        project.touch.add(c)
    for r in project.vars.pages.get(src, []):
        project.vars.add(dst, r.copy())
    if dst > project.vars.max_page:
        project.vars.max_page = dst


def apply_page(project, spec, d, log):
    page = _int(d['id'])
    if not 0 <= page <= 255:
        raise SpecError('page id must be 0..255')
    existing = page in project.images or page in project.vars.pages or project.touch.page(page)
    if existing and not (d.get('replace') or d.get('extend')):
        raise SpecError(f'page {page} already exists; set replace: true to rebuild it '
                        'or extend: true to add to it')
    if d.get('replace'):
        project.touch.remove_page(page)
        project.vars.pages.pop(page, None)

    from .formats import ZBmp
    if 'background' in d:
        project.images[page] = ZBmp.from_image(_load_png(spec, d['background'], (PANEL_W, PANEL_H)))
    elif 'copy_background' in d:
        src = project.images[_int(d['copy_background'])]
        project.images[page] = ZBmp(src.width, src.height, src.raw, src.header_tail)
    elif 'fill' in d:
        project.images[page] = ZBmp.from_image(Image.new('RGB', (PANEL_W, PANEL_H), d['fill']))
    elif page not in project.images:
        raise SpecError(f'page {page}: needs background, copy_background or fill')

    for t in d.get('touch') or []:
        project.touch.add(build_touch(page, t, project))
    for v in d.get('vars') or []:
        typ = v.get('type')
        if typ not in VAR_BUILDERS:
            raise SpecError(f'unknown var type {typ!r} (supported: {", ".join(VAR_BUILDERS)})')
        project.vars.add(page, VAR_BUILDERS[typ](project, v))
    if page > project.vars.max_page:
        project.vars.max_page = page
    log(f'page {page}: {len(d.get("touch") or [])} touch, {len(d.get("vars") or [])} vars')
