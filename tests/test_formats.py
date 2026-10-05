"""Format tests that need no Creality files."""
import struct
import unittest

from PIL import Image

from crm4ui.formats import IconLib, TouchConfig, TouchRecord, VarConfig, VarRecord, VpMemory, ZBmp
from crm4ui.formats import rgb565, variables
from crm4ui.recolor import HueRule, recolor_rgb565


def gradient(w, h):
    im = Image.new('RGB', (w, h))
    im.putdata([((x * 7) % 256, (y * 5) % 256, ((x + y) * 3) % 256) for y in range(h) for x in range(w)])
    return im


class Rgb565Test(unittest.TestCase):
    def test_roundtrip_bytes(self):
        raw = bytes(range(256)) * 8          # every byte pattern, 1024 pixels
        im = rgb565.decode(raw, 32, 32)
        self.assertEqual(rgb565.encode(im), raw)

    def test_scalar(self):
        for c in (0x0000, 0xFFFF, 0xF800, 0x07E0, 0x001F, 0xFC00, 0x87F0):
            self.assertEqual(rgb565.from_rgb888(rgb565.to_rgb888(c)), c)


class ZBmpTest(unittest.TestCase):
    def test_image_roundtrip(self):
        img = gradient(480, 800)
        z = ZBmp.from_image(img)
        data = z.to_bytes()
        self.assertEqual(struct.unpack('<HH', data[:4]), (480, 800))
        z2 = ZBmp.from_bytes(data)
        self.assertEqual(z2.raw, z.raw)
        self.assertEqual(z2.to_bytes(), data)
        # upright conversion is a 180 degree rotation
        self.assertEqual(z2.to_image(upright=False).getpixel((0, 0)), z2.to_image().getpixel((479, 799)))

    def test_wrong_size(self):
        with self.assertRaises(ValueError):
            ZBmp.from_image(Image.new('RGB', (100, 100)))


class ZicoTest(unittest.TestCase):
    def test_build_and_parse(self):
        lib = IconLib()
        lib.put(2, gradient(10, 6))
        lib.put(1, gradient(4, 4))
        data = lib.to_bytes()
        self.assertEqual(data[:4], b'ZICO')
        back = IconLib.from_bytes(data)
        self.assertEqual([i.id for i in back.icons], [1, 2])
        self.assertEqual(back.get(2).raw, lib.get(2).raw)
        self.assertEqual(back.to_bytes(), data)


class TouchTest(unittest.TestCase):
    def test_return_key_fields(self):
        r = TouchRecord.return_key(45, [1, 2, 300, 400], 0x9000, 3, page_next=121)
        self.assertEqual(len(r.data), 32)
        self.assertEqual((r.page, r.area, r.vp, r.key, r.page_next, r.page_on),
                         (45, [1, 2, 300, 400], 0x9000, 3, 121, None))
        self.assertEqual(r.kind, 'return_key')

    def test_sorted_serialisation(self):
        cfg = TouchConfig()
        cfg.add(TouchRecord.return_key(9, [0, 0, 10, 10], 0x9000, 1))
        cfg.add(TouchRecord.page_jump(2, [0, 0, 10, 10], 5))
        data = cfg.to_bytes()
        self.assertTrue(data.endswith(b'\xff\xff'))
        back = TouchConfig.from_bytes(data)
        self.assertEqual([r.page for r in back.records], [2, 9])
        self.assertEqual(back.to_bytes(), data)


def minimal_var_file():
    header = b'\x14DGUS_2\x10' + struct.pack('>H', 3) + b'\x00' * 6
    rec = bytearray(32)
    rec[0], rec[1] = 0x5A, 0x10
    rec[2:4] = b'\xff\xff'
    rec[4:6] = b'\x00\x0d'
    cfg = VarConfig(header, {3: [VarRecord(bytes(rec))]})
    cfg.pages[3][0].vp = 0x7046
    return cfg.to_bytes()


class VarTest(unittest.TestCase):
    def test_layout(self):
        data = minimal_var_file()
        self.assertEqual(len(data), variables.RECORDS_START + 32 + 32)
        # page 3 index entry: count 1 (LE), offset 0x4000 (BE)
        e = variables.INDEX_START + 4 * 3
        self.assertEqual(data[e:e + 4], b'\x01\x00\x40\x00')
        # empty pages after the last one point at the end of the records
        e = variables.INDEX_START + 4 * 10
        self.assertEqual(data[e:e + 4], b'\x00\x00\x40\x20')
        back = VarConfig.from_bytes(data)
        self.assertEqual(back.pages[3][0].vp, 0x7046)
        self.assertEqual(back.to_bytes(), data)

    def test_add_raises_max_page(self):
        cfg = VarConfig.from_bytes(minimal_var_file())
        cfg.add(45, cfg.pages[3][0].copy())
        self.assertEqual(cfg.max_page, 45)


class VpMemoryTest(unittest.TestCase):
    def test_text_and_word(self):
        m = VpMemory(bytes(131076))
        m.set_text(0x9010, 'hello', 40)
        m.set_word(0x9000, 0x1234)
        self.assertEqual(m.get_text(0x9010, 40), 'hello')
        self.assertEqual(m.data[2 * 0x9000:2 * 0x9000 + 2], b'\x12\x34')
        with self.assertRaises(ValueError):
            m.set_text(0x9010, 'x' * 41, 40)


class RecolorTest(unittest.TestCase):
    def test_accent_moves_greys_stay(self):
        rules = [HueRule([170, 210], 35, 0.25)]
        cyan = rgb565.from_rgb888((66, 190, 214))
        self.assertNotEqual(recolor_rgb565(cyan, rules), cyan)
        for grey in (0x0000, 0xFFFF, rgb565.from_rgb888((33, 32, 33))):
            self.assertEqual(recolor_rgb565(grey, rules), grey)


if __name__ == '__main__':
    unittest.main()
