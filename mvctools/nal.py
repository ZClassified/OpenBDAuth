"""Annex-B-Parser: NAL-Units aus einer Elementary-Stream-Datei lesen (inkl. MVC-NAL-Header)."""

import mmap
import os

NAL_TYPE_NAMES = {
    1: "Slice",
    2: "Slice-DPA",
    3: "Slice-DPB",
    4: "Slice-DPC",
    5: "IDR-Slice",
    6: "SEI",
    7: "SPS",
    8: "PPS",
    9: "AUD",
    10: "End-of-Seq",
    11: "End-of-Stream",
    12: "Filler",
    13: "SPS-Ext",
    14: "Prefix-NAL",
    15: "Subset-SPS",
    19: "Aux-Slice",
    20: "MVC-Slice",
    21: "3D-Slice",
    24: "Dependent-Delimiter",
}

VCL_TYPES = {1, 5, 20}
MVC_HEADER_TYPES = {14, 20, 21}


def nal_name(t):
    return NAL_TYPE_NAMES.get(t, f"Typ{t}")


class NalUnit:
    __slots__ = ("offset", "size", "ref_idc", "type", "mvc", "header_len", "data")

    def payload_ebsp(self):
        return self.data[self.header_len:]


def parse_mvc_ext(b):
    """nal_unit_header_mvc_extension (3 Byte nach dem 1-Byte-NAL-Header)."""
    v = int.from_bytes(b[:3], "big")
    if v >> 23:
        return {"svc_extension_flag": 1}
    return {
        "non_idr_flag": (v >> 22) & 1,
        "priority_id": (v >> 16) & 0x3F,
        "view_id": (v >> 6) & 0x3FF,
        "temporal_id": (v >> 3) & 0x7,
        "anchor_pic_flag": (v >> 2) & 1,
        "inter_view_flag": (v >> 1) & 1,
        "reserved_one_bit": v & 1,
    }


def iter_nal_units(path, vcl_limit=1024):
    """Liefert alle NAL-Units einer Annex-B-Datei.

    Von Slices werden nur die ersten `vcl_limit` Bytes geladen (reicht für den Slice-Header;
    None = vollständig), alle anderen NAL-Units vollständig. Die Datei wird per mmap gelesen, damit auch
    Spielfilm-große Streams nicht komplett in den RAM müssen.
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
            if end > start:
                nal = NalUnit()
                nal.offset = start
                nal.size = end - start
                h = mm[start]
                nal.ref_idc = (h >> 5) & 3
                nal.type = h & 0x1F
                nal.mvc = None
                nal.header_len = 1
                if nal.type in MVC_HEADER_TYPES and end - start >= 4:
                    nal.mvc = parse_mvc_ext(mm[start + 1:start + 4])
                    nal.header_len = 4
                if vcl_limit is not None and (nal.type in VCL_TYPES or nal.type in (19, 21)):
                    nal.data = mm[start:min(end, start + vcl_limit)]
                else:
                    nal.data = mm[start:end]
                yield nal
            sc = nxt
