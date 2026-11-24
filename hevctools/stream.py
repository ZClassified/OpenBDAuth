"""Einen HEVC-Elementarstrom parsen und in Access Units gliedern."""

import hashlib
import os
from collections import Counter

from mvctools.bitstream import BitstreamError

from . import sei as sei_mod
from .nal import (AUD, AU_START_TYPES, DV_EL, DV_RPU, PPS, PREFIX_SEI, SPS, SUFFIX_SEI, VPS, is_irap, is_vcl,
                  iter_nal_units)
from .pps import parse_pps
from .slice import first_slice_flag, parse_first_slice
from .sps import parse_sps


class StreamParser:
    """
    Liest den Strom einmal von vorn nach hinten. Ergebnis:
    - aus: je Access Unit Startposition, Größe (mit Startcodes), NAL-Typen, AUD, Parameter-Sets, SEI, Bild
    - sps/pps: zuletzt gesehene Parameter-Sets je ID; param_sets: eindeutige Inhalte mit Anzahl
    - sei_catalog: je SEI-Typ Anzahl, erste AU und ein Beispiel; hdr: Mastering Display und Lichtwerte
    - encoder_info: Text aus user_data_unregistered (x265: Version und Optionen)
    - errors: Lesefehler (der Strom wird trotzdem weiter gelesen)
    """

    def __init__(self, path, label="HEVC"):
        self.path = path
        self.label = label
        self.aus = []
        self.sps, self.pps = {}, {}
        self.param_sets = {}
        self.sei_catalog = {}
        self.nal_stats, self.nal_bytes = Counter(), Counter()
        self.layer_nals = 0                       # NAL-Units mit nuh_layer_id > 0 (Zusatzschichten)
        self.temporal_ids = Counter()
        self.hdr = {}
        self.hdr10plus = 0
        self.encoder_info = None
        self.buffering = None
        self.errors = []
        self.total_bytes = 0

    def _new_au(self, nal):
        au = {"index": len(self.aus), "start": nal.sc_offset, "bytes": 0, "nals": [], "aud": nal.type == AUD,
              "vps": False, "sps": False, "pps": False, "sei": [], "pic": None}
        self.aus.append(au)
        return au

    def _param_set(self, nal, fields, au):
        digest = hashlib.sha1(bytes(nal.data)).hexdigest()
        entry = self.param_sets.get(digest)
        if entry is None:
            entry = self.param_sets[digest] = {"nal_type": nal.type, "count": 0, "first_au": au["index"],
                                               "fields": fields}
        entry["count"] += 1

    def _sei(self, nal, au):
        for ptype, payload in sei_mod.split_sei_messages(nal.payload_ebsp()):
            au["sei"].append(ptype)
            entry = self.sei_catalog.setdefault(ptype, {"count": 0, "first_au": au["index"], "example": None})
            entry["count"] += 1
            if ptype == sei_mod.MASTERING_DISPLAY and "mastering_display" not in self.hdr:
                self.hdr["mastering_display"] = entry["example"] = sei_mod.mastering_display(payload)
                self.hdr["mastering_display_au"] = au["index"]
            elif ptype == sei_mod.CONTENT_LIGHT_LEVEL and "content_light_level" not in self.hdr:
                self.hdr["content_light_level"] = entry["example"] = sei_mod.content_light_level(payload)
                self.hdr["content_light_level_au"] = au["index"]
            elif ptype == sei_mod.USER_DATA_REGISTERED and sei_mod.is_hdr10plus(payload):
                self.hdr10plus += 1
            elif ptype == sei_mod.USER_DATA_UNREGISTERED and self.encoder_info is None:
                self.encoder_info = sei_mod.unregistered_text(payload)
            elif ptype == sei_mod.BUFFERING_PERIOD and self.buffering is None:
                sps = next(iter(self.sps.values()), None)
                self.buffering = entry["example"] = sei_mod.buffering_period(payload, sps)
            elif ptype == sei_mod.ALTERNATIVE_TRANSFER and entry["example"] is None:
                entry["example"] = {"preferred_transfer_characteristics": payload[0] if payload else None}

    def parse(self, progress=None, progress_step=256 << 20):
        au = None
        next_report = progress_step
        for nal in iter_nal_units(self.path):
            if progress and nal.offset >= next_report:
                progress(self.label, nal.offset)
                next_report += progress_step
            t = nal.type
            self.nal_stats[t] += 1
            self.nal_bytes[t] += nal.size
            self.temporal_ids[nal.temporal_id] += 1
            if nal.layer_id:
                self.layer_nals += 1
            vcl = is_vcl(t)
            first = vcl and nal.layer_id == 0 and first_slice_flag(nal.payload_ebsp())
            if au is None or t == AUD or (au["pic"] is not None and (t in AU_START_TYPES or first)):
                au = self._new_au(nal)
            au["nals"].append(t)
            try:
                if t == VPS:
                    au["vps"] = True
                    self._param_set(nal, {}, au)
                elif t == SPS:
                    sps = parse_sps(nal.payload_ebsp())
                    self.sps[sps["sps_seq_parameter_set_id"]] = sps
                    au["sps"] = True
                    self._param_set(nal, sps, au)
                elif t == PPS:
                    pps = parse_pps(nal.payload_ebsp())
                    self.pps[pps["pps_pic_parameter_set_id"]] = pps
                    au["pps"] = True
                    self._param_set(nal, pps, au)
                elif t in (PREFIX_SEI, SUFFIX_SEI):
                    self._sei(nal, au)
                elif vcl and first and nal.layer_id == 0:
                    head = parse_first_slice(nal.payload_ebsp(), t, self.pps)
                    au["pic"] = {"nal_type": t, "irap": is_irap(t), "temporal_id": nal.temporal_id,
                                 "type": head["slice_type"] if head else "?"}
                    if head is None:
                        self.errors.append(f"AU {au['index']}: Bild ohne bekannten PPS")
                elif t in (DV_RPU, DV_EL):
                    pass                              # nur gezählt (nal_stats); die Prüfung lehnt sie ab
            except (BitstreamError, IndexError, ValueError) as e:
                self.errors.append(f"AU {au['index']}: {e.__class__.__name__} in NAL {t}: {e}")
        self.total_bytes = os.path.getsize(self.path)
        if progress:
            progress(self.label, self.total_bytes)
        for a, b in zip(self.aus, self.aus[1:]):
            a["bytes"] = b["start"] - a["start"]
        if self.aus:
            self.aus[-1]["bytes"] = self.total_bytes - self.aus[-1]["start"]
        return self

    def pictures(self):
        return [au["pic"] for au in self.aus if au["pic"]]

    def first_sps(self):
        return next(iter(self.sps.values()), None)


def quick_info(path, max_nals=200):
    """
    Kenndaten aus dem ersten SPS, ohne den ganzen Strom zu lesen (für den Import in einen Film-Knoten): Größe,
    Bildrate aus der VUI (exakt, anders als ffprobe bei rohen Strömen), Bittiefe, Dynamikbereich. None ohne SPS.
    """
    from .check import detect_range
    from .sps import frame_rate
    for count, nal in enumerate(iter_nal_units(path)):
        if nal.type == SPS:
            try:
                sps = parse_sps(nal.payload_ebsp())
            except (BitstreamError, IndexError, ValueError):
                return None
            return {"codec_name": "hevc", "width": sps["width"], "height": sps["height"], "fps": frame_rate(sps),
                    "bit_depth": sps["bit_depth_luma"], "dynamic_range": detect_range(sps), "is_interlaced": False,
                    "warnings": []}
        if count >= max_nals:
            break
    return None
