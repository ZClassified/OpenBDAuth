"""Annex-B-Parser: NAL-Units eines HEVC-Elementarstroms (H.265 7.3.1, 2-Byte-NAL-Header)."""

import mmap
import os

NAL_TYPE_NAMES = {
    0: "TRAIL_N", 1: "TRAIL_R", 2: "TSA_N", 3: "TSA_R", 4: "STSA_N", 5: "STSA_R",
    6: "RADL_N", 7: "RADL_R", 8: "RASL_N", 9: "RASL_R",
    16: "BLA_W_LP", 17: "BLA_W_RADL", 18: "BLA_N_LP", 19: "IDR_W_RADL", 20: "IDR_N_LP", 21: "CRA",
    32: "VPS", 33: "SPS", 34: "PPS", 35: "AUD", 36: "EOS", 37: "EOB", 38: "Filler",
    39: "Prefix-SEI", 40: "Suffix-SEI",
    62: "Dolby-Vision-RPU", 63: "Dolby-Vision-EL",
}

VPS, SPS, PPS, AUD, PREFIX_SEI, SUFFIX_SEI = 32, 33, 34, 35, 39, 40
DV_RPU, DV_EL = 62, 63
RASL_TYPES = {8, 9}
IDR_TYPES = {19, 20}
CRA = 21

# Diese NAL-Units beginnen eine neue Access Unit, wenn die laufende schon ein Bild hat (H.265 7.4.2.4.4)
AU_START_TYPES = {VPS, SPS, PPS, AUD, PREFIX_SEI} | set(range(41, 45)) | set(range(48, 56))


def nal_name(t):
    return NAL_TYPE_NAMES.get(t, f"Typ{t}")


def is_vcl(t):
    return t < 32


def is_irap(t):
    return 16 <= t <= 23


class NalUnit:
    __slots__ = ("offset", "sc_offset", "size", "type", "layer_id", "temporal_id", "data")

    def payload_ebsp(self):
        return self.data[2:]


def iter_nal_units(path, vcl_limit=256):
    """
    Liefert alle NAL-Units einer Annex-B-Datei. Von Bild-NAL-Units (VCL) werden nur die ersten `vcl_limit` Bytes
    geladen (reicht für den Anfang des Slice-Headers; None = vollständig), alle anderen vollständig. Die Datei wird
    per mmap gelesen, damit auch Spielfilm-große Ströme nicht komplett in den Speicher müssen. sc_offset ist der
    Beginn des Startcodes (für Größen inklusive Startcodes, wie sie der HRD zählt).
    """
    size = os.path.getsize(path)
    if size == 0:
        return
    with open(path, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        sc = mm.find(b"\x00\x00\x01")
        while sc >= 0:
            start = sc + 3
            nxt = mm.find(b"\x00\x00\x01", start)
            end = nxt if nxt >= 0 else size
            while end > start and mm[end - 1] == 0:
                end -= 1
            if end - start >= 2:
                nal = NalUnit()
                nal.offset = start
                nal.sc_offset = sc - 1 if sc > 0 and mm[sc - 1] == 0 else sc
                nal.size = end - start
                h = (mm[start] << 8) | mm[start + 1]
                nal.type = (h >> 9) & 0x3F
                nal.layer_id = (h >> 3) & 0x3F
                nal.temporal_id = (h & 0x7) - 1
                if vcl_limit is not None and is_vcl(nal.type):
                    nal.data = mm[start:min(end, start + vcl_limit)]
                else:
                    nal.data = mm[start:end]
                yield nal
            sc = nxt
