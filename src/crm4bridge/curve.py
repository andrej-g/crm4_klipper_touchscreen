"""PID-autotune temperature graph: curve-buffer writes to the screen (VP 0x0310).

Stock behaviour (mainboard firmware RE, V2.0.3 section 6): while an autotune
runs, once per 1000 ms and per channel::

    5A A5 0D 82 03 10 5A A5 01 00 <ch> 02 <old16> <new16>

that is VP ``0x0310`` = ``5AA5`` (magic), ``0x0311`` = ``0100`` (one block),
``0x0312`` = ``<channel> 02`` (two data words), then the previous and the
current value. Channels: 0 nozzle temperature, 1 nozzle PID target (VP
``0x7070``), 2 bed temperature, 3 bed PID target (VP ``0x7074``). The bytes of
these frames leave the mainboard about 800 us apart (every other frame is sent
back to back). When PID is saved or aborted the firmware writes 0 to VP
``0x0301`` / ``0x0303`` / ``0x0305`` / ``0x0307``.

Screen side (screen firmware RE, section 2a): eight ring buffers of 0x800
words; VP ``0x0300 + 2n`` is channel n's write pointer and ``0x0301 + 2n``
its length, and writing 0 to the length clears the channel. The curve fields
(type 0x20) on pages 123/124 (nozzle, channels 0/1) and 126/127 (bed, 2/3)
draw from those buffers.
"""
from crm4ui import dgus

VP_CURVE_WRITE = 0x0310
VP_CURVE_LEN = 0x0301           # + 2 * channel
MAGIC = 0x5AA5
BLOCKS = 0x0100                 # one block per frame, as stock
CHANNELS = {'extruder': (0, 1), 'heater_bed': (2, 3)}     # (temperature, target)
POINTS_PER_FRAME = 2            # stock sends the previous and the current value
BYTE_GAP_S = 0.0008             # inter-byte spacing seen in the stock firmware
INTERVAL_S = 1.0


def write_frame(channel, *values):
    """One curve-buffer write: ``values`` appended to ``channel``."""
    if not 0 <= channel < 8 or not 1 <= len(values) <= 0x6E:
        raise ValueError('curve channel 0-7, 1-110 values')
    return dgus.write_words(VP_CURVE_WRITE, MAGIC, BLOCKS, (channel << 8) | len(values), *values)


def clear_frame(channel):
    """Empty ``channel``: its length register <- 0 (what stock does after PID)."""
    return dgus.write_words(VP_CURVE_LEN + 2 * channel, 0)


def as_word(temp):
    return max(0, min(0xFFFF, int(round(temp))))


class CurveStream:
    """The two channels of one heater's autotune; ``frames(temp)`` gives the frames
    for one tick, each carrying (previous, current) like the stock firmware."""

    def __init__(self, heater, target):
        self.heater = heater
        self.ch_temp, self.ch_target = CHANNELS[heater]
        self.target = as_word(target)
        self.last = {}

    def clear_frames(self):
        return [clear_frame(self.ch_temp), clear_frame(self.ch_target)]

    def frames(self, temp):
        out = []
        for ch, value in ((self.ch_temp, as_word(temp)), (self.ch_target, self.target)):
            old = self.last.get(ch, value)
            self.last[ch] = value
            out.append(write_frame(ch, old, value))
        return out
