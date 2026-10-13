"""PID graph: curve-buffer frames, the per-tick stream, and byte pacing on the link."""
import unittest
from unittest import mock

from crm4bridge import curve
from crm4bridge.link import ScreenLink
from crm4ui import dgus


class FrameTest(unittest.TestCase):
    def test_stock_frame_bytes(self):
        # mainboard firmware RE (V2.0.3 section 6): 5A A5 0D 82 03 10 5A A5 01 00 <ch> 02 <old16> <new16>
        f = curve.write_frame(0, 25, 26)
        self.assertEqual(f.to_bytes(), bytes.fromhex('5aa50d8203105aa5010000020019001a'))
        self.assertEqual(curve.write_frame(3, 60, 61).to_bytes()[10:12], b'\x03\x02')
        self.assertEqual(len(f.to_bytes()), 16)

    def test_clear_frames(self):
        # VP 0x0301 + 2*channel <- 0 (the channel length register)
        self.assertEqual(curve.clear_frame(0).to_bytes(), bytes.fromhex('5aa5058203010000'))
        self.assertEqual(curve.clear_frame(1).to_bytes(), bytes.fromhex('5aa5058203030000'))
        self.assertEqual(curve.clear_frame(2).vp, 0x0305)
        self.assertEqual(curve.clear_frame(3).vp, 0x0307)

    def test_limits(self):
        with self.assertRaises(ValueError):
            curve.write_frame(8, 1)
        with self.assertRaises(ValueError):
            curve.write_frame(0)
        self.assertEqual(curve.as_word(-3.2), 0)
        self.assertEqual(curve.as_word(214.6), 215)


class StreamTest(unittest.TestCase):
    def test_channels_and_pairs(self):
        s = curve.CurveStream('extruder', 210)
        self.assertEqual([f.vp for f in s.clear_frames()], [0x0301, 0x0303])
        first = s.frames(25.4)
        self.assertEqual([f.to_bytes()[10] for f in first], [0, 1])          # channels 0 and 1
        self.assertEqual(first[0].payload()[6:], bytes.fromhex('00190019'))     # 25.4 -> 25, twice (no previous)
        self.assertEqual(first[1].payload()[6:], bytes.fromhex('00d200d2'))     # target 210, twice
        second = s.frames(30.0)
        self.assertEqual(second[0].payload()[6:], bytes.fromhex('0019001e'))    # previous, current
        bed = curve.CurveStream('heater_bed', 60)
        self.assertEqual([f.to_bytes()[10] for f in bed.frames(22)], [2, 3])


class PacingTest(unittest.TestCase):
    def link(self, paced):
        link = ScreenLink('tcp:127.0.0.1:1')
        self.writes = []
        link._io = {'write': self.writes.append, 'flush': lambda: None, 'close': lambda: None, 'paced': paced}
        return link

    def test_serial_bytes_are_spaced(self):
        link = self.link(paced=True)
        f = curve.write_frame(0, 25, 26)
        with mock.patch('crm4bridge.link.time.sleep') as sleep:
            self.assertTrue(link.send(f, byte_gap=0.0008))
        self.assertEqual(b''.join(self.writes), f.to_bytes())
        self.assertEqual(len(self.writes), 16)                              # one write per byte
        self.assertEqual(sleep.call_count, 16)
        self.assertTrue(all(c.args == (0.0008,) for c in sleep.call_args_list))

    def test_tcp_and_unpaced_send_whole_frames(self):
        f = dgus.write_words(0x7046, 215)
        for paced, gap in ((False, 0.0008), (True, 0.0), (True, 0)):
            link = self.link(paced)
            with mock.patch('crm4bridge.link.time.sleep') as sleep:
                link.send(f, byte_gap=gap)
            self.assertEqual(self.writes, [f.to_bytes()], (paced, gap))
            self.assertEqual(sleep.call_count, 0)
        link = self.link(True)
        link.send(f)                                                        # default: no pacing
        self.assertEqual(self.writes, [f.to_bytes()])


if __name__ == '__main__':
    unittest.main()
