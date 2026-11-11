"""Bit-Ebene: RBSP lesen/schreiben (Exp-Golomb), Emulation-Prevention."""

import re


class BitstreamError(Exception):
    pass


def ebsp_to_rbsp(data):
    """Entfernt Emulation-Prevention-Bytes (0x00 0x00 0x03 -> 0x00 0x00)."""
    data = bytes(data)
    if b"\x00\x00\x03" not in data:
        return data
    out = bytearray()
    start = 0
    while True:
        i = data.find(b"\x00\x00\x03", start)
        if i < 0:
            out += data[start:]
            return bytes(out)
        out += data[start:i + 2]
        start = i + 3


_EP_PATTERN = re.compile(b"\x00\x00(?=[\x00-\x03])")


def rbsp_to_ebsp(data):
    """Fügt Emulation-Prevention-Bytes ein (Gegenstück zu ebsp_to_rbsp)."""
    out = _EP_PATTERN.sub(b"\x00\x00\x03", data)
    if out.endswith(b"\x00"):
        out += b"\x03"
    return out


class BitWriter:
    __slots__ = ("buf", "acc", "n")

    def __init__(self):
        self.buf = bytearray()
        self.acc = 0
        self.n = 0

    def u(self, n, v):
        if n == 0:
            return
        self.acc = (self.acc << n) | (v & ((1 << n) - 1))
        self.n += n
        while self.n >= 8:
            self.n -= 8
            self.buf.append((self.acc >> self.n) & 0xFF)
        self.acc &= (1 << self.n) - 1

    def u1(self, b):
        self.u(1, b)

    def ue(self, v):
        v += 1
        length = v.bit_length()
        self.u(length - 1, 0)
        self.u(length, v)

    def se(self, v):
        self.ue(2 * v - 1 if v > 0 else -2 * v)

    def byte_aligned(self):
        return self.n == 0

    def copy_bits(self, data, start, end):
        """Kopiert die Bits [start, end) aus data."""
        r = BitReader(data, start)
        while end - r.pos >= 32:
            self.u(32, r.u(32))
        self.u(end - r.pos, r.u(end - r.pos))

    def align(self, bit):
        while self.n:
            self.u1(bit)

    def rbsp_trailing_bits(self):
        self.u1(1)
        self.align(0)

    def append_bytes(self, b):
        assert self.n == 0, "append_bytes nur an Bytegrenze"
        self.buf += b

    def getvalue(self):
        assert self.n == 0, "Bitstrom nicht byte-aligned"
        return bytes(self.buf)


class BitReader:
    __slots__ = ("data", "pos", "end", "_stop_pos")

    def __init__(self, data, pos=0):
        self.data = data
        self.pos = pos
        self.end = len(data) * 8
        self._stop_pos = None

    def u1(self):
        p = self.pos
        if p >= self.end:
            raise BitstreamError("Lesen über Datenende hinaus")
        self.pos = p + 1
        return (self.data[p >> 3] >> (7 - (p & 7))) & 1

    def u(self, n):
        if n == 0:
            return 0
        p = self.pos
        if p + n > self.end:
            raise BitstreamError("Lesen über Datenende hinaus")
        first = p >> 3
        last = (p + n - 1) >> 3
        chunk = int.from_bytes(self.data[first:last + 1], "big")
        self.pos = p + n
        return (chunk >> ((last + 1) * 8 - (p + n))) & ((1 << n) - 1)

    def ue(self):
        zeros = 0
        while self.u1() == 0:
            zeros += 1
            if zeros > 31:
                raise BitstreamError("ungültiger Exp-Golomb-Code")
        return (1 << zeros) - 1 + self.u(zeros)

    def se(self):
        k = self.ue()
        return (k + 1) >> 1 if k & 1 else -(k >> 1)

    def byte_aligned(self):
        return self.pos & 7 == 0

    def bits_left(self):
        return self.end - self.pos

    def stop_bit_pos(self):
        """Bitposition des rbsp_stop_one_bit (letztes gesetztes Bit)."""
        if self._stop_pos is None:
            i = len(self.data) - 1
            while i >= 0 and self.data[i] == 0:
                i -= 1
            if i < 0:
                self._stop_pos = 0
            else:
                b = self.data[i]
                low = (b & -b).bit_length() - 1
                self._stop_pos = i * 8 + (7 - low)
        return self._stop_pos

    def more_rbsp_data(self):
        return self.pos < self.stop_bit_pos()
