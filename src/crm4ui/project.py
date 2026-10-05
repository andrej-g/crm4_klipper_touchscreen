"""A whole screen project (the ``private/`` directory of a Creality screen package)."""
import hashlib
import os
import shutil

from .formats import IconLib, TouchConfig, VarConfig, VpMemory, ZBmp


class Project:
    """Loads every file it understands; everything else is copied verbatim.

    Files are only re-encoded when modified, so saving an untouched project
    reproduces the input byte for byte.
    """

    def __init__(self, root):
        self.root = os.path.abspath(root)
        if not os.path.isdir(os.path.join(self.root, 'bin')):
            raise FileNotFoundError(f'{root} does not look like a screen private/ directory (no bin/)')
        self.touch = TouchConfig.load(self._p('bin/13.bin'))
        self.vars = VarConfig.load(self._p('bin/14.bin'))
        self.vpmem = VpMemory.load(self._p('bin/22.bin'))
        self.images = {}
        for f in os.listdir(self._p('image')):
            if f.endswith('.zbmp'):
                self.images[int(f[:-5])] = ZBmp.load(self._p('image', f))
        self.icons = {}
        for f in os.listdir(self._p('icon')):
            if f.endswith('.zico'):
                self.icons[int(f[:-5])] = IconLib.load(self._p('icon', f))
        self.extra = {}          # relative path -> replacement bytes for verbatim files

    def _p(self, *parts):
        return os.path.join(self.root, *parts)

    # ---- queries --------------------------------------------------------------
    def page_ids(self):
        return sorted(set(self.images) | set(self.vars.pages) | {r.page for r in self.touch.records})

    def free_page_ids(self, limit=256):
        used = set(self.page_ids())
        return [i for i in range(limit) if i not in used]

    # ---- output -----------------------------------------------------------------
    def _generated(self):
        """relative path -> bytes for every file this object owns."""
        out = {'bin/13.bin': self.touch.to_bytes(),
               'bin/14.bin': self.vars.to_bytes(),
               'bin/22.bin': self.vpmem.to_bytes()}
        for n, z in self.images.items():
            out[f'image/{n}.zbmp'] = z.to_bytes()
        for n, lib in self.icons.items():
            out[f'icon/{n}.zico'] = lib.to_bytes()
        out.update(self.extra)
        return out

    def save(self, out_dir, changed_only=False):
        """Write the project. Returns the list of written relative paths."""
        gen = self._generated()
        written = []
        for dirpath, _, files in os.walk(self.root):
            for f in files:
                rel = os.path.relpath(os.path.join(dirpath, f), self.root).replace(os.sep, '/')
                if rel in gen:
                    continue
                if changed_only:
                    continue
                dst = os.path.join(out_dir, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copyfile(os.path.join(dirpath, f), dst)
                written.append(rel)
        for rel, data in gen.items():
            src = os.path.join(self.root, rel)
            if changed_only and os.path.exists(src):
                with open(src, 'rb') as fh:
                    if fh.read() == data:
                        continue
            dst = os.path.join(out_dir, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, 'wb') as fh:
                fh.write(data)
            written.append(rel)
        return sorted(written)


def tree_digest(root):
    """relative path -> sha256 for every file below root."""
    out = {}
    for dirpath, _, files in os.walk(root):
        for f in files:
            p = os.path.join(dirpath, f)
            with open(p, 'rb') as fh:
                out[os.path.relpath(p, root).replace(os.sep, '/')] = hashlib.sha256(fh.read()).hexdigest()
    return out
