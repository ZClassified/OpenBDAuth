"""MVC-Rewriter (Phase 1): wandelt einen normalen H.264-Stream des rechten Auges in einen
Blu-ray-3D-Dependent-View (.mvc) um – ohne Neucodierung der Bilddaten.

Vorlage ist der Output des Referenz-Encoders (siehe docs/mvc/mvc-wissen.md):
  AUD (9)        -> Dependent-Delimiter (24)
  SPS (7)        -> Subset-SPS (15), Profil Stereo High, eigene ID, MVC-Extension
  PPS (8)        -> PPS mit eigener ID (ID-Raum wird mit dem Base View geteilt)
  SEI (6)        -> Buffering Period / Pic Timing einzeln in MVC Scalable Nesting (37)
  Slice (1/5)    -> MVC-Slice (20) mit MVC-NAL-Header, Slice-Header mit neuer PPS-ID
  vor jedem IDR  -> End of Sequence (10) am Ende der vorherigen AU

Voraussetzungen an den Eingangsstream: CABAC, AUD in jeder AU, Bildstruktur identisch zum Base View.

Aufruf:
    python -m mvctools.rewrite right.264 right.mvc [--interview-refs]
"""

import argparse
import os
import sys
from collections import Counter

from .bitstream import BitReader, BitWriter, ebsp_to_rbsp, rbsp_to_ebsp
from .nal import iter_nal_units, nal_name
from .pps import parse_pps
from .slice import parse_slice_header
from .sps import parse_sps_data

START_CODE = b"\x00\x00\x00\x01"
NAL_DEP_DELIMITER = 24
NAL_SUBSET_SPS = 15
NAL_MVC_SLICE = 20
NAL_EOS = 10


class RewriteError(Exception):
    pass


def _nal(header_byte, rbsp):
    return START_CODE + bytes([header_byte]) + rbsp_to_ebsp(rbsp)


def _mvc_header(non_idr, view_id, anchor, inter_view=0, priority_id=0, temporal_id=0):
    v = (0 << 23) | (non_idr << 22) | (priority_id << 16) | (view_id << 6) \
        | (temporal_id << 3) | (anchor << 2) | (inter_view << 1) | 1
    return v.to_bytes(3, "big")


def _sei_varlen(w, v):
    while v >= 255:
        w.u(8, 255)
        v -= 255
    w.u(8, v)


def _split_sei(rbsp):
    msgs = []
    pos = 0
    n = len(rbsp)
    while pos < n and not (pos == n - 1 and rbsp[pos] == 0x80):
        ptype = psize = 0
        while rbsp[pos] == 0xFF:
            ptype += 255
            pos += 1
        ptype += rbsp[pos]
        pos += 1
        while rbsp[pos] == 0xFF:
            psize += 255
            pos += 1
        psize += rbsp[pos]
        pos += 1
        msgs.append((ptype, rbsp[pos:pos + psize]))
        pos += psize
    return msgs


class MvcRewriter:
    def __init__(self, view_id=1, sps_id=1, pps_id=1, interview_refs=False, level_idc=None, end_of_seq=True):
        self.view_id = view_id
        self.sps_id = sps_id
        self.pps_id = pps_id
        self.interview_refs = interview_refs
        self.level_idc = level_idc
        self.end_of_seq = end_of_seq
        self.sps = {}   # Eingangs-SPS (AVC)
        self.pps = {}   # Eingangs-PPS
        self.stats = Counter()
        self.dropped = Counter()

    # --- Parameter-Sets ---
    def subset_sps(self, rbsp):
        r = BitReader(rbsp)
        r.u(8)
        r.u(8)
        level = r.u(8)
        r.ue()
        after_id = r.pos
        r2 = BitReader(rbsp)
        sps = parse_sps_data(r2)
        end = r2.pos
        w = BitWriter()
        w.u(8, 128)                         # profile_idc: Stereo High
        w.u(8, 0)                           # constraint_set-Flags (wie beim Referenz-Encoder)
        w.u(8, self.level_idc or level)
        w.ue(self.sps_id)
        w.copy_bits(rbsp, after_id, end)    # Rest von seq_parameter_set_data unverändert
        w.u1(1)                             # bit_equal_to_one
        # seq_parameter_set_mvc_extension
        w.ue(1)                             # num_views_minus1
        w.ue(0)                             # view_id[0]
        w.ue(self.view_id)                  # view_id[1]
        refs = 1 if self.interview_refs else 0
        for _ in range(2):                  # anchor, dann non-anchor
            w.ue(refs)                      # num_*_refs_l0
            if refs:
                w.ue(0)                     # Referenz auf view_id 0
            w.ue(0)                         # num_*_refs_l1
        w.ue(0)                             # num_level_values_signalled_minus1
        w.u(8, self.level_idc or level)
        w.ue(0)                             # num_applicable_ops_minus1
        w.u(3, 0)                           # applicable_op_temporal_id
        w.ue(1)                             # applicable_op_num_target_views_minus1
        w.ue(0)
        w.ue(self.view_id)
        w.ue(1)                             # applicable_op_num_views_minus1
        w.u1(0)                             # mvc_vui_parameters_present_flag
        w.u1(0)                             # additional_extension2_flag
        w.rbsp_trailing_bits()
        return sps, w.getvalue()

    def rewrite_pps(self, rbsp):
        r = BitReader(rbsp)
        r.ue()
        r.ue()
        w = BitWriter()
        w.ue(self.pps_id)
        w.ue(self.sps_id)
        w.copy_bits(rbsp, r.pos, r.stop_bit_pos())
        w.rbsp_trailing_bits()
        return w.getvalue()

    # --- SEI ---
    def _rewrite_buffering_period(self, payload, sps):
        r = BitReader(payload)
        r.ue()
        start = r.pos
        bits = 0
        vui = sps.get("vui", {})
        for key in ("nal_hrd", "vcl_hrd"):
            h = vui.get(key)
            if h:
                bits += 2 * h["initial_cpb_removal_delay_length"] * len(h["cpbs"])
        w = BitWriter()
        w.ue(self.sps_id)
        w.copy_bits(payload, start, start + bits)
        if not w.byte_aligned():
            w.u1(1)
            w.align(0)
        return w.getvalue()

    def nested_sei(self, ptype, payload):
        w = BitWriter()
        w.u1(1)                     # operation_point_flag
        w.ue(0)                     # num_view_components_op_minus1
        w.u(10, self.view_id)       # sei_op_view_id
        w.u(3, 0)                   # sei_op_temporal_id
        w.align(0)                  # sei_nesting_zero_bit
        _sei_varlen(w, ptype)
        _sei_varlen(w, len(payload))
        w.append_bytes(payload)
        nesting = w.getvalue()
        o = BitWriter()
        _sei_varlen(o, 37)
        _sei_varlen(o, len(nesting))
        o.append_bytes(nesting)
        o.rbsp_trailing_bits()
        return o.getvalue()

    # --- Slices ---
    def rewrite_slice(self, nal, rbsp):
        r = BitReader(rbsp)
        first_mb = r.ue()
        slice_type = r.ue()
        pps_id = r.ue()
        after_pps = r.pos
        pps = self.pps.get(pps_id)
        if pps is None:
            raise RewriteError(f"PPS {pps_id} unbekannt")
        if not pps["entropy_coding_mode_flag"]:
            raise RewriteError("CAVLC wird nicht unterstützt (CABAC erforderlich)")
        sps = self.sps[pps["seq_parameter_set_id"]]
        h = parse_slice_header(rbsp, nal, sps, pps)
        if not h["cabac_align_ok"]:
            raise RewriteError("Slice-Header inkonsistent (CABAC-Alignment)")
        data_start = (h["header_bits"] + 7) // 8
        w = BitWriter()
        w.ue(first_mb)
        w.ue(slice_type)
        w.ue(self.pps_id)
        w.copy_bits(rbsp, after_pps, h["header_bits"])
        w.align(1)                  # cabac_alignment_one_bit
        w.append_bytes(rbsp[data_start:])
        return h, w.getvalue()

    # --- Haupt-Schleife ---
    def _convert_au(self, nals):
        out = []
        idr = False
        for nal in nals:
            rbsp = ebsp_to_rbsp(nal.payload_ebsp())
            t = nal.type
            if t == 9:
                out.append(_nal(NAL_DEP_DELIMITER, rbsp))
            elif t == 7:
                sps, sub = self.subset_sps(rbsp)
                self.sps[sps["seq_parameter_set_id"]] = sps
                out.append(_nal((nal.ref_idc << 5) | NAL_SUBSET_SPS, sub))
            elif t == 8:
                p = parse_pps(rbsp, lambda i: self.sps.get(i))
                self.pps[p["pic_parameter_set_id"]] = p
                out.append(_nal((nal.ref_idc << 5) | 8, self.rewrite_pps(rbsp)))
            elif t == 6:
                sps = next(iter(self.sps.values()), None)
                for ptype, payload in _split_sei(rbsp):
                    if ptype == 0 and sps is not None:
                        payload = self._rewrite_buffering_period(payload, sps)
                    elif ptype != 1:
                        self.dropped[f"SEI {ptype}"] += 1
                        continue
                    out.append(_nal(6, self.nested_sei(ptype, payload)))
                    self.stats[f"SEI {ptype} -> 37>{ptype}"] += 1
            elif t in (1, 5):
                h, body = self.rewrite_slice(nal, rbsp)
                idr = idr or t == 5
                anchor = 1 if t == 5 else 0
                hdr = bytes([(nal.ref_idc << 5) | NAL_MVC_SLICE]) + _mvc_header(
                    non_idr=0 if t == 5 else 1, view_id=self.view_id, anchor=anchor)
                out.append(START_CODE + hdr + rbsp_to_ebsp(body))
                self.stats[f"{nal_name(t)} -> MVC-Slice"] += 1
            else:
                self.dropped[nal_name(t)] += 1
                continue
            self.stats[nal_name(t)] += 1
        return idr, out

    def run(self, src, dst, progress=None, cancel=None):
        """Konvertiert src -> dst. progress(au_count, bytes_gelesen, bytes_gesamt); cancel() -> True bricht ab."""
        total = os.path.getsize(src)
        au = []
        pending = None      # konvertierte vorherige AU (wartet auf EOS-Entscheidung)
        count = 0
        with open(dst, "wb") as f:
            def flush(next_is_idr):
                if pending is not None:
                    f.write(b"".join(pending))
                    if next_is_idr and self.end_of_seq:
                        f.write(START_CODE + bytes([NAL_EOS]))
                        self.stats["End-of-Seq eingefügt"] += 1

            def finish_au():
                nonlocal pending, count
                if not au:
                    return
                idr, out = self._convert_au(au)
                flush(idr)
                pending = out
                count += 1
                if progress and count % 250 == 0:
                    progress(count, au[-1].offset, total)

            for nal in iter_nal_units(src, vcl_limit=None):
                if nal.type == 9 and au:
                    finish_au()
                    au = []
                    if cancel and cancel():
                        return None
                au.append(nal)
            finish_au()
            flush(False)
        return count


def main(argv=None):
    ap = argparse.ArgumentParser(description="H.264 (rechtes Auge) -> Blu-ray-3D-MVC-Dependent-View")
    ap.add_argument("src", help="H.264-Stream des rechten Auges (CABAC, mit AUD)")
    ap.add_argument("dst", help="Ausgabe .mvc")
    ap.add_argument("--interview-refs", action="store_true",
                    help="Inter-View-Referenzen im Subset-SPS deklarieren (wie beim Referenz-Encoder), aber nicht nutzen")
    ap.add_argument("--no-eos", action="store_true", help="kein End-of-Sequence vor IDR einfügen")
    ap.add_argument("--level", type=int, help="level_idc im Subset-SPS überschreiben (z. B. 41)")
    args = ap.parse_args(argv)

    rw = MvcRewriter(interview_refs=args.interview_refs, end_of_seq=not args.no_eos, level_idc=args.level)
    n = rw.run(args.src, args.dst,
               progress=lambda c, pos, total: print(f"\r  {c} Access Units ({pos / total:.0%})", end="",
                                                    file=sys.stderr, flush=True))
    print(file=sys.stderr)
    print(f"{n} Access Units geschrieben -> {args.dst}")
    for k, v in sorted(rw.stats.items()):
        print(f"  {k}: {v}")
    if rw.dropped:
        print("Verworfen:", dict(rw.dropped))


if __name__ == "__main__":
    main()
