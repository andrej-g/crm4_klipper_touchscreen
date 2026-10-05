"""RGB565 little-endian pixel packing used by .zbmp pages and .zico icons."""
import numpy as np
from PIL import Image


def decode(raw: bytes, width: int, height: int) -> Image.Image:
    """Unpack little-endian RGB565 into an RGB PIL image (stored orientation)."""
    v = np.frombuffer(raw, '<u2').reshape(height, width)
    r = (v >> 11) & 0x1F
    g = (v >> 5) & 0x3F
    b = v & 0x1F
    rgb = np.stack([(r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)], -1)
    return Image.fromarray(rgb.astype(np.uint8), 'RGB')


def encode(img: Image.Image) -> bytes:
    """Pack an RGB PIL image into little-endian RGB565 (truncating to 5/6/5 bits).

    decode() followed by encode() reproduces the original bytes exactly.
    """
    a = np.asarray(img.convert('RGB'), dtype=np.uint16)
    v = ((a[..., 0] >> 3) << 11) | ((a[..., 1] >> 2) << 5) | (a[..., 2] >> 3)
    return v.astype('<u2').tobytes()


def to_rgb888(c: int) -> tuple:
    r, g, b = (c >> 11) & 0x1F, (c >> 5) & 0x3F, c & 0x1F
    return ((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2))


def from_rgb888(rgb) -> int:
    r, g, b = rgb
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
