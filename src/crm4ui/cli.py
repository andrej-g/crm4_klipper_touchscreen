"""crm4ui command line.

    crm4ui verify  STOCK_PRIVATE                 rebuild unchanged, compare byte for byte
    crm4ui dump    PRIVATE OUT                   ui_map.json / ui_map.md
    crm4ui render  PRIVATE OUT [--lang N]        page previews with labels and overlay
    crm4ui export  PRIVATE OUT                   upright PNGs of all pages and icons
    crm4ui build   STOCK_PRIVATE SPEC OUT        apply a spec, write a new private/
"""
import argparse
import os
import sys
import tempfile

from . import __version__
from .project import Project, tree_digest
from .render import export_assets, render_all, write_map
from .spec import SpecError, apply, load_spec


def cmd_verify(a):
    prj = Project(a.private)
    with tempfile.TemporaryDirectory() as tmp:
        prj.save(tmp)
        src, out = tree_digest(a.private), tree_digest(tmp)
    bad = [k for k in sorted(set(src) | set(out)) if src.get(k) != out.get(k)]
    print(f'{len(src)} files, {len(src) - len(bad)} identical')
    for k in bad:
        print(f'  DIFFERS: {k}')
    return 1 if bad else 0


def cmd_dump(a):
    m = write_map(Project(a.private), a.out)
    print(f'{len(m)} pages -> {a.out}')
    return 0


def cmd_render(a):
    prj = Project(a.private)
    pages = [int(x, 0) for x in a.pages.split(',')] if a.pages else None
    done = render_all(prj, a.out, lang=a.lang, overlay=not a.no_overlay, pages=pages)
    print(f'{len(done)} pages rendered -> {a.out}')
    return 0


def cmd_export(a):
    export_assets(Project(a.private), a.out)
    print(f'assets -> {a.out}')
    return 0


def cmd_build(a):
    prj = Project(a.private)
    try:
        spec = load_spec(a.spec)
        apply(prj, spec, log=(lambda *x: None) if a.quiet else print)
    except SpecError as e:
        print(f'spec error: {e}', file=sys.stderr)
        return 2
    if os.path.exists(a.out) and os.listdir(a.out) and not a.force:
        print(f'{a.out} is not empty (use --force)', file=sys.stderr)
        return 2
    written = prj.save(a.out, changed_only=a.changed_only)
    print(f'{len(written)} files written -> {a.out}')
    if a.preview:
        changed = sorted({int(w.split('/')[1].split('.')[0]) for w in written if w.startswith('image/')})
        pages = changed or None
        render_all(prj, a.preview, lang=a.lang, pages=pages)
        print(f'previews -> {a.preview}')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog='crm4ui', description='Edit the Creality CR-M4 (DACAI) touchscreen UI project.')
    ap.add_argument('--version', action='version', version=__version__)
    sub = ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('verify', help='round-trip a private/ dir and report any byte differences')
    p.add_argument('private')
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser('dump', help='write ui_map.json and ui_map.md')
    p.add_argument('private')
    p.add_argument('out')
    p.set_defaults(fn=cmd_dump)

    p = sub.add_parser('render', help='render pages to PNG with labels and touch/VP overlay')
    p.add_argument('private')
    p.add_argument('out')
    p.add_argument('--lang', type=int, default=1, help='label language index (0=zh, 1=en, ...; default 1)')
    p.add_argument('--pages', help='comma-separated page ids (default: all)')
    p.add_argument('--no-overlay', action='store_true')
    p.set_defaults(fn=cmd_render)

    p = sub.add_parser('export', help='export page backgrounds and icons as upright PNGs')
    p.add_argument('private')
    p.add_argument('out')
    p.set_defaults(fn=cmd_export)

    p = sub.add_parser('build', help='apply a spec to a stock private/ dir')
    p.add_argument('private')
    p.add_argument('spec')
    p.add_argument('out')
    p.add_argument('--changed-only', action='store_true', help='write only files that differ from the input')
    p.add_argument('--preview', help='also render the pages whose images changed into this dir')
    p.add_argument('--lang', type=int, default=1)
    p.add_argument('--force', action='store_true')
    p.add_argument('--quiet', action='store_true')
    p.set_defaults(fn=cmd_build)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == '__main__':
    sys.exit(main())
