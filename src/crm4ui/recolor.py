"""Hue-based recolouring of page images, icons and field colours.

A rule moves pixels whose hue lies in ``hue_from`` (degrees, inclusive range,
may wrap through 0) and whose saturation is at least ``min_saturation`` to
``hue_to``, optionally scaling saturation and value. Greys, black and white
have (near) zero saturation and are never touched, so anti-aliasing and the
pure-black transparency key in icons survive.
"""
import numpy as np
from PIL import Image

from .formats import rgb565


class HueRule:
    def __init__(self, hue_from, hue_to, min_saturation=0.2, saturation_scale=1.0, value_scale=1.0):
        self.h0, self.h1 = (float(hue_from[0]) % 360, float(hue_from[1]) % 360)
        self.to = float(hue_to) % 360
        self.min_s = float(min_saturation)
        self.s_scale = float(saturation_scale)
        self.v_scale = float(value_scale)

    @classmethod
    def from_spec(cls, d):
        return cls(d['hue_from'], d['hue_to'], d.get('min_saturation', 0.2),
                   d.get('saturation_scale', 1.0), d.get('value_scale', 1.0))

    def mask(self, h, s):
        inside = (h >= self.h0) & (h <= self.h1) if self.h0 <= self.h1 else (h >= self.h0) | (h <= self.h1)
        return inside & (s >= self.min_s)


def _rgb_to_hsv(a):
    a = a.astype(np.float32) / 255.0
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mx, mn = a.max(-1), a.min(-1)
    d = mx - mn
    h = np.zeros_like(mx)
    nz = d > 1e-6
    rm = nz & (mx == r)
    gm = nz & (mx == g) & ~rm
    bm = nz & ~rm & ~gm
    h[rm] = ((g - b)[rm] / d[rm]) % 6
    h[gm] = (b - r)[gm] / d[gm] + 2
    h[bm] = (r - g)[bm] / d[bm] + 4
    h *= 60.0
    s = np.where(mx > 1e-6, d / np.maximum(mx, 1e-6), 0)
    return h, s, mx


def _hsv_to_rgb(h, s, v):
    h = (h % 360) / 60.0
    i = np.floor(h).astype(int) % 6
    f = h - np.floor(h)
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    choices = [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)]
    out = np.zeros(h.shape + (3,), np.float32)
    for k, (r, g, b) in enumerate(choices):
        m = i == k
        out[m] = np.stack([r[m], g[m], b[m]], -1)
    return np.clip(np.rint(out * 255), 0, 255).astype(np.uint8)


def recolor_array(a: np.ndarray, rules) -> np.ndarray:
    h, s, v = _rgb_to_hsv(a)
    out = a.copy()
    for rule in rules:
        m = rule.mask(h, s)
        if not m.any():
            continue
        nh = np.full(m.sum(), rule.to, np.float32)
        ns = np.clip(s[m] * rule.s_scale, 0, 1)
        nv = np.clip(v[m] * rule.v_scale, 0, 1)
        out[m] = _hsv_to_rgb(nh, ns, nv)
    return out


def recolor_image(img: Image.Image, rules) -> Image.Image:
    a = np.asarray(img.convert('RGB'))
    return Image.fromarray(recolor_array(a, rules), 'RGB')


def recolor_rgb565(c: int, rules) -> int:
    a = np.array([[rgb565.to_rgb888(c)]], np.uint8)
    return rgb565.from_rgb888(tuple(int(x) for x in recolor_array(a, rules)[0, 0]))


def recolor_project(project, rules, images=True, icons=True, fields=True, skip_icon_libs=()):
    """Apply rules everywhere. Returns counts of changed items."""
    n = {'images': 0, 'icons': 0, 'fields': 0}
    if images:
        for z in project.images.values():
            raw = rgb565.encode(recolor_image(z.to_image(upright=False), rules))
            if raw != z.raw:
                z.raw, z._packed = raw, None
                n['images'] += 1
    if icons:
        for lib_id, lib in project.icons.items():
            if lib_id in skip_icon_libs:
                continue
            for ic in lib.icons:
                before = ic.raw
                new = recolor_image(ic.to_image(), rules)
                raw = rgb565.encode(new)
                if raw != before:
                    ic.set_raw(raw)
                    lib.modified = True
                    n['icons'] += 1
    if fields:
        for _, r in project.vars.all():
            c = r.color
            if c is None:
                continue
            nc = recolor_rgb565(c, rules)
            if nc != c:
                r.color = nc
                n['fields'] += 1
    return n
