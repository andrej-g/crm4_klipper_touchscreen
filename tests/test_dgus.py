import unittest

from crm4ui import dgus


class DgusTest(unittest.TestCase):
    def test_builders(self):
        self.assertEqual(dgus.write_words(0x7046, 215).to_bytes().hex(), '5aa505827046' '00d7')
        self.assertEqual(dgus.set_page(11).to_bytes().hex(), '5aa50782' '0084' '5a01000b')
        self.assertEqual(dgus.read_words(0x7046, 2).to_bytes().hex(), '5aa5048370460' '2')
        self.assertEqual(dgus.reply_words(0x4002, 1).to_bytes().hex(), '5aa50683400201' '0001')
        f = dgus.write_text(0x3000, 'ab', 4)
        self.assertEqual(f.payload(), b'ab\x00\x00')

    def test_parser_resync_and_split(self):
        p = dgus.Parser()
        a = dgus.reply_words(0x4002, 3).to_bytes()
        b = dgus.ACK.to_bytes()
        stream = b'\x00\x13\x5a' + a + b
        out = p.feed(stream[:5]) + p.feed(stream[5:9]) + p.feed(stream[9:])
        self.assertEqual(out, [dgus.reply_words(0x4002, 3), dgus.ACK])
        self.assertEqual(out[0].vp, 0x4002)
        self.assertEqual(out[0].value, 3)
        self.assertTrue(out[1].is_ack)

    def test_signed(self):
        self.assertEqual(dgus.to_signed(0xFFFB), -5)
        self.assertEqual(dgus.to_signed(5), 5)


if __name__ == '__main__':
    unittest.main()
