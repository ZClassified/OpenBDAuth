"""Einen Elementary Stream (Base View oder Dependent View) parsen und in Access Units gliedern."""

from collections import Counter

from .bitstream import BitReader, ebsp_to_rbsp
from .nal import VCL_TYPES, iter_nal_units
from .pps import parse_pps
from .sei import parse_sei_messages, sei_keys
from .slice import parse_slice_header
from .sps import hrd_context, parse_sps, parse_subset_sps

AU_DELIMITERS = {9, 24}


class PocState:
    """Picture Order Count nach H.264 8.2.1 (Typ 0 und 2), getrennt pro View."""

    def __init__(self):
        self.prev_msb = 0
        self.prev_lsb = 0
        self.prev_frame_num = 0
        self.prev_frame_num_offset = 0

    def compute(self, h, sps, ref_idc):
        t = sps["pic_order_cnt_type"]
        mmco5 = any(m[0] == 5 for m in h["mmco"])
        if t == 0:
            max_lsb = 1 << sps["log2_max_pic_order_cnt_lsb"]
            if h["idr"]:
                self.prev_msb = self.prev_lsb = 0
            lsb = h["pic_order_cnt_lsb"]
            if lsb < self.prev_lsb and self.prev_lsb - lsb >= max_lsb // 2:
                msb = self.prev_msb + max_lsb
            elif lsb > self.prev_lsb and lsb - self.prev_lsb > max_lsb // 2:
                msb = self.prev_msb - max_lsb
            else:
                msb = self.prev_msb
            top = msb + lsb
            bottom = top + h["delta_pic_order_cnt_bottom"]
            poc = min(top, bottom)
            if ref_idc:
                if mmco5:
                    self.prev_msb, self.prev_lsb = 0, top - poc
                else:
                    self.prev_msb, self.prev_lsb = msb, lsb
            return poc
        if t == 2:
            max_fn = 1 << sps["log2_max_frame_num"]
            if h["idr"]:
                offset = 0
            elif self.prev_frame_num > h["frame_num"]:
                offset = self.prev_frame_num_offset + max_fn
            else:
                offset = self.prev_frame_num_offset
            poc = 0 if h["idr"] else 2 * (offset + h["frame_num"]) - (0 if ref_idc else 1)
            self.prev_frame_num = 0 if mmco5 else h["frame_num"]
            self.prev_frame_num_offset = 0 if mmco5 else offset
            return poc
        return None


def picture_type(slice_types):
    s = set(slice_types)
    if "B" in s:
        return "B"
    if "P" in s or "SP" in s:
        return "P"
    return "I"


class StreamParser:
    def __init__(self, path, label):
        self.path = path
        self.label = label
        self.sps = {}
        self.subset_sps = {}
        self.pps = {}
        self.param_sets = {}       # (nal_type, rohbytes) -> Eintrag
        self.nal_stats = Counter()
        self.nal_bytes = Counter()
        self.sei_catalog = {}      # schlüssel -> {count, first_au, example}
        self.aus = []
        self.errors = []
        self.total_bytes = 0
        self._poc = PocState()
        self._last_sps = None      # für SEI-HRD im Base View
        self._last_subset = None   # für SEI-HRD im Dependent View

    # --- Kontext für SEI-Parser ---
    def hrd_for_sps(self, sps_id, view):
        s = None
        if view is not None:
            s = self.subset_sps.get(sps_id)
            if s is not None:
                return hrd_context(s, view)
        s = self.sps.get(sps_id) or self.subset_sps.get(sps_id)
        return hrd_context(s)

    def hrd_active(self, view):
        if view is not None and self._last_subset is not None:
            return hrd_context(self._last_subset, view)
        return hrd_context(self._last_sps or self._last_subset)

    def _sps_lookup(self, sps_id):
        return self.subset_sps.get(sps_id) or self.sps.get(sps_id)

    # --- Parsing ---
    def _new_au(self, nal):
        au = {"index": len(self.aus), "offset": nal.offset, "bytes": 0, "nals": [], "sei": [], "pic": None}
        self.aus.append(au)
        return au

    def _record_param(self, nal, decoded, au):
        key = (nal.type, bytes(nal.data))
        entry = self.param_sets.get(key)
        if entry is None:
            self.param_sets[key] = {"nal_type": nal.type, "count": 1, "first_au": au["index"],
                                    "fields": decoded}
        else:
            entry["count"] += 1

    def parse(self, progress=None):
        au = None
        for nal in iter_nal_units(self.path):
            self.total_bytes += nal.size
            self.nal_stats[nal.type] += 1
            self.nal_bytes[nal.type] += nal.size
            is_vcl = nal.type in VCL_TYPES
            hdr = None
            if is_vcl:
                try:
                    hdr = self._parse_slice(nal)
                except Exception as e:
                    self.errors.append(f"AU {len(self.aus)}: Slice-Header @0x{nal.offset:x}: {e}")
            # Neue AU: Delimiter, oder (falls ohne Delimiter) erster Slice eines neuen Bildes bzw.
            # Parameter-Sets/SEI direkt nach den Slices des vorigen Bildes.
            after_vcl = au is not None and au["nals"][-1] in VCL_TYPES
            if au is None or nal.type in AU_DELIMITERS:
                starts_au = True
            elif is_vcl:
                starts_au = after_vcl and hdr is not None and hdr["first_mb_in_slice"] == 0
            else:
                starts_au = after_vcl and nal.type in (6, 7, 8, 14, 15)
            if starts_au:
                au = self._new_au(nal)
            au["nals"].append(nal.type)
            au["bytes"] += nal.size
            try:
                if is_vcl and hdr is not None:
                    self._add_slice(au, nal, hdr)
                elif nal.type == 7:
                    s = parse_sps(ebsp_to_rbsp(nal.payload_ebsp()))
                    self.sps[s["seq_parameter_set_id"]] = s
                    self._last_sps = s
                    self._record_param(nal, s, au)
                elif nal.type == 15:
                    s = parse_subset_sps(ebsp_to_rbsp(nal.payload_ebsp()))
                    self.subset_sps[s["seq_parameter_set_id"]] = s
                    self._last_subset = s
                    self._record_param(nal, s, au)
                elif nal.type == 8:
                    p = parse_pps(ebsp_to_rbsp(nal.payload_ebsp()), self._sps_lookup)
                    self.pps[p["pic_parameter_set_id"]] = p
                    self._record_param(nal, p, au)
                elif nal.type == 6:
                    msgs = parse_sei_messages(ebsp_to_rbsp(nal.payload_ebsp()), self)
                    for m in msgs:
                        keys = sei_keys([m])
                        au["sei"].extend(keys)
                        for k in keys:
                            c = self.sei_catalog.get(k)
                            if c is None:
                                self.sei_catalog[k] = {"count": 1, "first_au": au["index"], "example": m}
                            else:
                                c["count"] += 1
                elif nal.type == 14:
                    au.setdefault("prefix_mvc", nal.mvc)
                elif nal.type in AU_DELIMITERS and nal.size > 1:
                    au["primary_pic_type"] = nal.data[1] >> 5
            except Exception as e:
                self.errors.append(f"AU {au['index']}: NAL {nal.type} @0x{nal.offset:x}: {e}")
            if progress and starts_au and len(self.aus) % 500 == 0:
                progress(self.label, nal.offset)
        return self

    def _parse_slice(self, nal):
        rbsp = ebsp_to_rbsp(nal.payload_ebsp())
        # first_mb / slice_type / pps_id vorab lesen, um das passende PPS/SPS zu finden
        r = BitReader(rbsp)
        r.ue()
        r.ue()
        pps_id = r.ue()
        pps = self.pps.get(pps_id)
        if pps is None:
            raise ValueError(f"PPS {pps_id} unbekannt")
        sid = pps["seq_parameter_set_id"]
        sps = self.subset_sps.get(sid) if nal.type == 20 else self.sps.get(sid)
        if sps is None:
            raise ValueError(f"SPS {sid} unbekannt")
        h = parse_slice_header(rbsp, nal, sps, pps)
        h["_sps"] = sps
        return h

    def _add_slice(self, au, nal, h):
        sps = h.pop("_sps")
        pic = au["pic"]
        if pic is None:
            pic = au["pic"] = {
                "nal_type": nal.type,
                "ref_idc": nal.ref_idc,
                "idr": h["idr"],
                "frame_num": h["frame_num"],
                "field_pic": h["field_pic_flag"],
                "pps_id": h["pic_parameter_set_id"],
                "slice_types": [],
                "slices": 0,
                "vcl_bytes": 0,
                "num_ref_idx_l0": [],
                "num_ref_idx_l1": [],
                "mods": [],
                "mmco": h["mmco"],
                "qp": [],
                "header_bits": [],
                "cabac_align_ok": True,
                "mvc": nal.mvc,
            }
            pic["poc"] = self._poc.compute(h, sps, nal.ref_idc)
        pic["slice_types"].append(h["slice_type"])
        pic["slices"] += 1
        pic["vcl_bytes"] += nal.size
        pic["num_ref_idx_l0"].append(h["num_ref_idx_l0_active"])
        pic["num_ref_idx_l1"].append(h["num_ref_idx_l1_active"])
        pic["mods"].extend([("l0",) + m for m in h["mods_l0"]] + [("l1",) + m for m in h["mods_l1"]])
        pic["qp"].append(h["slice_qp"])
        pic["header_bits"].append(h["header_bits"])
        if h.get("cabac_align_ok") is False:
            pic["cabac_align_ok"] = False
        pic["type"] = picture_type(pic["slice_types"])

    def pictures(self):
        return [au["pic"] for au in self.aus if au["pic"] is not None]
