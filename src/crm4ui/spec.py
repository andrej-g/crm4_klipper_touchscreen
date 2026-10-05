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


def build_touch(page, d):
    typ = d.get('type', 'return_key')
    area = _check_area(d['area'], 'touch')
    flags = _int(d.get('flags', 0x0C))
    if typ == 'return_key':
        return TouchRecord.return_key(page, area, _int(d['vp']), _int(d['key']),
                                      page_next=_opt_int(d.get('page_next')),
                                      page_on=_opt_int(d.get('page_on')), flags=flags)
    if typ == 'page_jump':
        return TouchRecord.page_jump(page, area, _int(d['page']), flags=flags)
    raise SpecError(f'unknown touch type {typ!r} (supported: return_key, page_jump)')


# ---- spec sections ----------------------------------------------------------------
def apply(project, spec, log=print):
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
        if len(hits) != 1:
            raise SpecError(f'touch_edits match {m} hit {len(hits)} records (need exactly 1)')
        r, s = hits[0], e.get('set') or {}
        if 'vp' in s:
            r.vp = _int(s['vp'])
        if 'key' in s:
            r.key = _int(s['key'])
        if 'page_next' in s:
            r.page_next = _opt_int(s['page_next'])
        if 'area' in s:
            r.area = _check_area(s['area'], 'touch_edits')
        log(f'touch edit {m} -> {s}')

    for d in spec.get('field_colors') or []:
        n = 0
        for p, r in project.vars.all():
            if 'page' in d and p != _int(d['page']):
                continue
            if r.vp == _int(d['vp']) and r.color is not None:
                r.color = _int(d['color'])
                n += 1
        if not n:
            raise SpecError(f'field_colors {d}: no matching record')
        log(f'field colour VP {d["vp"]}: {n} record(s)')

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


def apply_page(project, spec, d, log):
    page = _int(d['id'])
    if not 0 <= page <= 255:
        raise SpecError('page id must be 0..255')
    existing = page in project.images or page in project.vars.pages or project.touch.page(page)
    if existing and not d.get('replace'):
        raise SpecError(f'page {page} already exists; set replace: true to rebuild it')
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
        project.touch.add(build_touch(page, t))
    for v in d.get('vars') or []:
        typ = v.get('type')
        if typ not in VAR_BUILDERS:
            raise SpecError(f'unknown var type {typ!r} (supported: {", ".join(VAR_BUILDERS)})')
        project.vars.add(page, VAR_BUILDERS[typ](project, v))
    if page > project.vars.max_page:
        project.vars.max_page = page
    log(f'page {page}: {len(d.get("touch") or [])} touch, {len(d.get("vars") or [])} vars')
