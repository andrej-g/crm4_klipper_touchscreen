"""Spoolman spool -> what the screen shows: material badge, colour swatch, two text lines.

The screen can't draw arbitrary colours or text badges, so both are icons
(``examples/spoolman``): a material badge index and the nearest of a fixed set
of colour swatches. ``examples/spoolman/make_icons.py`` draws the icons from the
same tables, so the indices here and in the icon library always agree.
"""
import re

# Material badges, icon value = index. 0 = no badge (other materials: the
# material name is put in front of the spool name instead). Append only: the
# icon ids in examples/spoolman follow this order.
MATERIALS = ('', 'PLA', 'PETG', 'PLA-M', 'PLA-CF', 'PETG-CF', 'ABS', 'ASA', 'TPU', 'PA', 'PLA-W')

# Swatches, icon value = index. 0 = empty ring (no active spool / no colour).
COLOURS = (
    ('none', None),
    ('white', 'FFFFFF'), ('natural', 'F2EBD3'), ('light grey', 'C0C0C0'), ('grey', '808080'),
    ('anthracite', '555555'), ('black', '1A1A1A'), ('red', 'D32F2F'), ('dark red', '8B1A1A'),
    ('orange', 'F57C00'), ('yellow', 'FFD600'), ('gold', 'C9A227'), ('wood', 'B08A6A'),
    ('brown', '6D4C41'), ('lime', '9CCC65'), ('green', '2E9D44'), ('dark green', '1B5E20'),
    ('teal', '00897B'), ('light blue', '64B5F6'), ('blue', '1E63D0'), ('navy', '1A237E'),
    ('purple', '7B1FA2'), ('pink', 'F48FB1'), ('magenta', 'D81B60'),
)


def _rgb(hexstr):
    h = hexstr.strip().lstrip('#')[:6]
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def nearest_colour(hexstr):
    """Index into COLOURS of the closest swatch ('redmean' weighted RGB distance)."""
    if not hexstr:
        return 0
    try:
        r1, g1, b1 = _rgb(hexstr)
    except ValueError:
        return 0
    best, best_d = 0, None
    for i, (_, h) in enumerate(COLOURS):
        if h is None:
            continue
        r2, g2, b2 = _rgb(h)
        rm = (r1 + r2) / 2
        d = (2 + rm / 256) * (r1 - r2) ** 2 + 4 * (g1 - g2) ** 2 + (2 + (255 - rm) / 256) * (b1 - b2) ** 2
        if best_d is None or d < best_d:
            best, best_d = i, d
    return best


_CF = re.compile(r'(^|[^A-Z])(CF|GF?CF|CARBON)([^A-Z]|$)')


def classify(material, name=''):
    """(badge index, material text) for a Spoolman filament."""
    m = (material or '').upper().replace('+', '-').replace(' ', '-')
    n = (name or '').upper()
    cf = bool(_CF.search(m)) or bool(_CF.search(n))
    matte = 'MATTE' in m or 'MATTE' in n or m.endswith('-M')
    wood = any(w in m or w in n for w in ('WOOD', 'BAMBOO')) or m.endswith('-W')
    if m.startswith('PETG'):
        return MATERIALS.index('PETG-CF' if cf else 'PETG'), 'PETG'
    if m.startswith('PLA'):
        if cf:
            return MATERIALS.index('PLA-CF'), 'PLA'
        if wood:
            return MATERIALS.index('PLA-W'), 'PLA'
        return MATERIALS.index('PLA-M' if matte else 'PLA'), 'PLA'
    for prefix, badge in (('ABS', 'ABS'), ('ASA', 'ASA'), ('TPU', 'TPU'), ('TPE', 'TPU'), ('FLEX', 'TPU'),
                          ('PA', 'PA'), ('NYLON', 'PA')):
        if m.startswith(prefix):
            return MATERIALS.index(badge), badge
    return 0, (material or '').strip()


def fit(text, n):
    """Cut text to n characters, marking the cut with '..'."""
    text = ' '.join(str(text).split())
    return text if len(text) <= n else text[:n - 2].rstrip() + '..'


def describe(spool, name_len=28, detail_len=28, short_len=22):
    """Screen values for a Spoolman spool dict (None = no active spool)."""
    if not spool:
        return {'badge': 0, 'swatch': 0, 'name': 'No active spool', 'detail': '',
                'short': 'No active spool', 'weight': ''}
    fil = spool.get('filament') or {}
    badge, mat = classify(fil.get('material'), fil.get('name'))
    name = fil.get('name') or f'Spool {spool.get("id")}'
    if not badge and mat:
        name = f'{mat} {name}'
    colour = fil.get('color_hex') or (fil.get('multi_color_hexes') or '').split(',')[0]
    parts = []
    w = spool.get('remaining_weight')
    if w is not None:
        parts.append(f'{w:.0f} g')
    ln = spool.get('remaining_length')
    if ln is not None:
        parts.append(f'{ln / 1000:.0f} m')
    vendor = (fil.get('vendor') or {}).get('name')
    if vendor:
        parts.append(vendor)
    return {'badge': badge, 'swatch': nearest_colour(colour), 'name': fit(name, name_len),
            'detail': fit(' | '.join(parts), detail_len), 'short': fit(name, short_len),
            'weight': f'{w:.0f} g' if w is not None else ''}
