"""Bed mesh -> the screen's 5x5 (or 4x4) grid of numbers, VP 0x7100+.

Stock behaviour (mainboard firmware RE, V2.0.3 section 2 step 5): after
levelling the firmware writes the 25 mesh values, mm x 1000, to VP
``0x7100 + 2*i`` in probe (serpentine) order, and shows page 28. The UI
places those VPs serpentine on pages 28/135 (``14.bin``): ``0x7100`` at the
bottom left, ``0x7108`` bottom right, ``0x710A`` at the right end of the row
above, and so on up to ``0x7130`` top right. So grid row 0 is the bottom row
of the screen, which is the front of the bed (Y = mesh_min), and a value
written in that order lands at the right place. Pages 27/134 are the 4x4
variant of the same layout (``0x7100``..``0x711E``).

Each field is a 16-bit number with 2 integer and 3 decimal digits
(``var_type`` 0), so the value is a signed ``int16`` of micrometres.
"""
SCALE = 1000                    # mm -> field units (3 decimals)
MAX_VALUE = 0x7FFF              # int16


def grid_from_status(status, n):
    """``bed_mesh`` status (Moonraker) -> n x n grid, or None when no mesh is loaded.

    Uses ``mesh_matrix`` (Klipper's interpolated surface, the one it applies) and
    falls back to ``probed_matrix``. Rows are Y from ``mesh_min`` to ``mesh_max``.
    """
    for key in ('mesh_matrix', 'probed_matrix'):
        m = status.get(key) or []
        rows = [list(r) for r in m if r]
        if rows:
            return sample(rows, n)
    return None


def sample(matrix, n):
    """n x n grid sampled from ``matrix[y][x]`` by bilinear interpolation at the
    positions that divide the mesh into n-1 equal steps in X and Y (the corners
    are the mesh corners). ``n`` = 1 returns the first value."""
    ny = len(matrix)
    nx = len(matrix[0])
    if any(len(r) != nx for r in matrix) or not nx:
        raise ValueError('ragged mesh matrix')
    out = []
    for j in range(n):
        fy = (ny - 1) * j / (n - 1) if n > 1 else 0.0
        y0 = min(int(fy), max(ny - 2, 0))
        ty = fy - y0
        row = []
        for i in range(n):
            fx = (nx - 1) * i / (n - 1) if n > 1 else 0.0
            x0 = min(int(fx), max(nx - 2, 0))
            tx = fx - x0
            row.append(_bilinear(matrix, x0, y0, tx, ty))
        out.append(row)
    return out


def _bilinear(m, x0, y0, tx, ty):
    x1 = min(x0 + 1, len(m[0]) - 1)
    y1 = min(y0 + 1, len(m) - 1)
    z0 = m[y0][x0] * (1 - tx) + m[y0][x1] * tx
    z1 = m[y1][x0] * (1 - tx) + m[y1][x1] * tx
    return z0 * (1 - ty) + z1 * ty


def serpentine(grid):
    """Grid (row 0 = front) -> the values in VP order: row 0 left to right, row 1
    right to left, ... (stock write order = the UI's field layout)."""
    out = []
    for r, row in enumerate(grid):
        out.extend(row if r % 2 == 0 else list(reversed(row)))
    return out


def encode(z):
    """mm -> signed 16-bit field value (x1000, rounded, clamped). The stock firmware
    truncates instead of rounding; the difference is at most 1 um."""
    v = int(round(z * SCALE))
    return max(-MAX_VALUE - 1, min(MAX_VALUE, v))


def words(grid, base_vp):
    """[(vp, value)] for every cell, ready for the bridge's ``word()``."""
    return [(base_vp + 2 * i, encode(z)) for i, z in enumerate(serpentine(grid))]
