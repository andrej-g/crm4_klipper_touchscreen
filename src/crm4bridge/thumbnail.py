"""G-code thumbnail -> the screen's JPEG picture (VP 0xC000).

How the stock firmware does it (mainboard firmware RE, V1.5.1 and V2.0.3):

* the picture is a 300x300 **baseline JPEG** (the screen decodes it itself);
* ``VP 0xC000 = 0`` first (clears the header), then the JPEG bytes in file order as
  240-byte ``0x82`` writes to ``0xC002 + 0x78*n`` (0x78 words = 240 bytes, the last
  chunk zero-padded), 25 ms before each frame;
* finally ``VP 0xC000 = 5A A5`` and ``VP 0xC001 = byte count`` tells the screen to decode
  and show it in the picture control (pages 9-12 and 119, 300x300 at 88,264);
* the mascot icon ``0x4227`` is set to 0 while a picture is shown (4 = mascot).
"""
import io

from crm4ui import dgus

VP_THUMB = 0xC000
CHUNK = 240
SIZE = 300
MAX_BYTES = (0x10000 - (VP_THUMB + 2)) * 2 - CHUNK      # stay inside the VP space
GAP_S = 0.025


def pick(meta):
    """The largest thumbnail Moonraker lists for a file (``relative_path``), or None."""
    thumbs = [t for t in (meta or {}).get('thumbnails') or [] if t.get('relative_path')]
    if not thumbs:
        return None
    return max(thumbs, key=lambda t: (t.get('width') or 0) * (t.get('height') or 0))['relative_path']


def to_jpeg(image_bytes, size=SIZE, max_bytes=MAX_BYTES):
    """Any image (Moonraker serves PNG) -> size x size baseline JPEG on black."""
    from PIL import Image
    im = Image.open(io.BytesIO(image_bytes))
    if im.mode in ('RGBA', 'LA', 'P'):
        im = im.convert('RGBA')
        bg = Image.new('RGBA', im.size, (0, 0, 0, 255))
        im = Image.alpha_composite(bg, im)
    im = im.convert('RGB')
    im.thumbnail((size, size), Image.LANCZOS)
    canvas = Image.new('RGB', (size, size), (0, 0, 0))
    canvas.paste(im, ((size - im.width) // 2, (size - im.height) // 2))
    for quality in (85, 75, 60, 45, 30):
        out = io.BytesIO()
        canvas.save(out, 'JPEG', quality=quality, progressive=False, optimize=False)
        data = out.getvalue()
        if len(data) <= max_bytes:
            return data
    raise ValueError(f'thumbnail does not fit in {max_bytes} bytes')


def frames(jpeg):
    """(clear frame, [chunk frames], header frame) for one JPEG."""
    if len(jpeg) > MAX_BYTES:
        raise ValueError('JPEG too large for the screen picture buffer')
    clear = dgus.write_words(VP_THUMB, 0)
    chunks = []
    for n, off in enumerate(range(0, len(jpeg), CHUNK)):
        part = jpeg[off:off + CHUNK].ljust(CHUNK, b'\0')
        chunks.append(dgus.write_bytes(VP_THUMB + 2 + 0x78 * n, part))
    header = dgus.write_words(VP_THUMB, 0x5AA5, len(jpeg) & 0xFFFF)
    return clear, chunks, header
