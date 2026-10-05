# Build spec reference

A spec is YAML (`.yaml` / `.yml`) or JSON. Paths are relative to the spec file. Integers may be written as `0x9010` (YAML) or `"0x9010"` (JSON).

Coordinates are panel coordinates: 480×800 portrait, origin top-left, as you see the screen. Images are supplied upright; the tool handles the 180° storage rotation.

Sections are applied in this order:

0. `include`: other specs applied first, in order (paths relative to this spec)
1. `copy_pages`, so the sections below can edit the copies
2. `images`
3. `image_patches`
4. `retouch`
5. `remove_vars`, then `remove_touch`
6. `icons`
7. `pages`
8. `touch_edits`
9. `field_colors`
10. `recolor`
11. `vp_defaults`

## `images`: replace page backgrounds

```yaml
images:
  0: splash.png        # page id: 480x800 upright PNG
```

## `image_patches`: paste a PNG onto an existing background

```yaml
image_patches:
  - {page: 121, png: tile.png, pos: [255, 38]}
```

## `retouch`: erase an area of a page or icon and redraw text

```yaml
retouch:
  - {target: page, page: 1, rect: [148, 20, 332, 54], fill: "#000000",
     text: KLIPPER, size: 30, spacing: 5, bold: 1, color: "#FFFFFF"}
  - {target: icon, lib: 18, id: 4, rect: [109, 195, 149, 206], fill: interpolate,
     text: KLIPPER, size: 9, color: "#8C8C8C"}
```

- `rect` is inclusive: upright panel coordinates for pages, icon pixels for icons.
- `fill` is a colour, `auto` (median of the surrounding pixels) or `interpolate` (blends the four edges, which keeps shading gradients).
- `font` defaults to `stock`, the input package's `truefont/font.ttf`, so labels match the UI. A path to any TTF also works.
- `size` is in pixels, `spacing` is extra pixels between letters, `bold` is the stroke width, and `dy` nudges the text vertically.

## `remove_vars`: drop display fields

```yaml
remove_vars:
  - {page: 121, vp: 0x4220}                  # all fields on that VP on that page
  - {page: 121, vp: 0x5247, pos: [16, 245]}  # only the one at that position
```

## `remove_touch`: drop touch areas

```yaml
remove_touch:
  - {page: 121, vp: 0x403E, key: 4}    # every record on the page matching vp/key (both optional)
```

Combine with `remove_vars` and `retouch` to take a tile off a page entirely (see `examples/english_only`).

## `icons`: replace or add icons

```yaml
icons:
  - {lib: 18, id: 4, png: mascot.png}    # PNG in viewing orientation; pure black = transparent
```

Labels are icons in library 19 (and 29), one per language. An icon variable on VP `0x5247` shows `icon_min + language` (0 = Chinese, 1 = English, …, 8 = Turkish). Find ids with `crm4ui dump`.

## `include`: compose specs

```yaml
include:
  - ../klipper_branding/spec.yaml
  - ../print_page_shortcuts/spec.yaml
```

## `copy_pages`: duplicate a page under a new id

```yaml
copy_pages:
  - {from: 115, to: 46}     # background, touch areas and fields
```

Typical uses:

- a variant of a stock page whose back button goes somewhere else (combine with `touch_edits`);
- a titled copy of the shared keypad (page 40) for one input (combine with `retouch` and `touch_edits` … `keyboard_page`; see `examples/keypad_titles`).

The copy is taken from the page as it is after `include`, so it carries any branding applied there.

## `pages`: new pages, or rebuild (`replace: true`) or add to (`extend: true`) an existing one

```yaml
pages:
  - id: 45                       # 0..255, pick a free id (crm4ui dump lists used ones)
    background: page45.png       # or: copy_background: 121   or: fill: "#101010"
    replace: false
    touch:
      - {type: page_jump,  area: [0, 0, 200, 80], page: 121}
      - {type: return_key, area: [12, 100, 468, 220], vp: 0x9000, key: 1, page_next: null}
    vars:
      - {type: text,   vp: 0x9010, box: [28, 530, 460, 575], color: 0xFFFF, length: 40}
      - {type: number, vp: 0x9020, pos: [100, 300], color: 0xFFFF, int_digits: 3, dec_digits: 1}
      - {type: clone,  from_page: 1, vp: 0x7046, pos: [100, 400], new_vp: 0x9030}
```

- `clone` copies an existing touch record (numeric input, increment, …) onto this page with a new area: `{type: clone, from_page: 14, vp: 0x7048, area: [14, 80, 234, 139]}`, optionally with `key` to disambiguate, `page_next` to override, and `keyboard_page` to open a different keypad page.
- `return_key` sends `5A A5 06 83 <vp> 01 <key>` to the host when released. `page_next` switches page locally as well.
- `text` / `number` are cloned from a stock record of the same type (font, alignment), with the given fields replaced. Colours are RGB565.
- Use VPs `0x9000–0x9FFF` for custom content. Neither the stock UI nor the Creality firmware uses them.

## `touch_edits`: change existing touch records

```yaml
touch_edits:
  - match: {page: 121, vp: 0x403E, key: 9}     # must match exactly one record
    set: {page_next: 45}                       # any of: vp, key, page_next, area, keyboard_page, min, max
  - match: {vp: 0x7048, kind: data_input}      # every nozzle-target input, on any page
    all: true
    set: {keyboard_page: 47}
```

- `match` takes any of `page`, `vp`, `key`, `kind` (`return_key`, `data_input`, `increment`, `keyboard_key`), and the current `min` / `max` of a numeric input.
- Without `all: true` the match must hit exactly one record; with it, at least one.
- `keyboard_page` is the page a numeric input (`data_input`) opens as its keypad.
- `min` / `max` are the limits of a numeric input, in raw units (value × 10^decimals of the field). The screen rejects anything outside them.

## `field_colors`: set number/text/curve colours

```yaml
field_colors:
  - {vp: 0x7048, color: 0xFFE0}            # every page
  - {page: 1, vp: 0x704C, color: 0xFFE0}   # one page
  - {from: 0x87F0, color: "#B12F35"}       # every field currently in that colour
```

Colours are RGB565 integers or `"#rrggbb"`.

## `recolor`: hue remap across images, icons and field colours

```yaml
recolor:
  rules:
    - {hue_from: [170, 210], hue_to: 35, min_saturation: 0.25, saturation_scale: 1.0, value_scale: 1.0}
  images: true
  icons: true
  fields: true
  skip_icon_libs: []
```

Instead of `hue_to` and the scales, a rule can map one reference colour exactly: `{hue_from: [165, 215], from_color: "#42BED6", to_color: "#B12F35"}`. Pixels at the reference colour become exactly `to_color`, and other pixels in the range keep their relative saturation and brightness (anti-aliasing, dimmed variants).

Only pixels inside the hue range and above `min_saturation` change. Greys, black (the icon transparency key) and white are never affected.

## `vp_defaults`: initial values in `22.bin`

```yaml
vp_defaults:
  - {vp: 0x9010, text: "waiting for host", bytes: 40}    # GBK, NUL-padded
  - {vp: 0x9020, word: 0}
```
