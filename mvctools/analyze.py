"""MVC-Analyzer – Bericht über Base View (.264) und Dependent View (.mvc).

Aufruf:
    python -m mvctools.analyze BASE.264 [--mvc DEP.mvc] [--frames N] [--json out.json]
"""

import argparse
import json
import sys
from collections import Counter

from .nal import nal_name
from .sei import sei_name
from .sps import frame_rate
from .stream import StreamParser


def _fmt(v, indent):
    pad = "  " * indent
    if isinstance(v, dict):
        lines = []
        for k, x in v.items():
            if isinstance(x, (dict, list)) and x and (isinstance(x, dict) or isinstance(x[0], (dict, list))):
                lines.append(f"{pad}{k}:")
                lines.append(_fmt(x, indent + 1))
            else:
                lines.append(f"{pad}{k}: {x}")
        return "\n".join(lines)
    if isinstance(v, list):
        return "\n".join(f"{pad}- [{i}]\n{_fmt(x, indent + 1)}" if isinstance(x, (dict, list))
                         else f"{pad}- {x}" for i, x in enumerate(v))
    return f"{pad}{v}"


def section(title):
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def _sei_label(key):
    return " > ".join(sei_name(int(p)) + f"({p})" for p in key.split(">"))


def report_stream(sp, fps):
    pics = sp.pictures()
    section(f"[{sp.label}] {sp.path}")
    dur = len(pics) / fps if fps else None
    print(f"Dateigröße: {sp.total_bytes:,} Bytes   Access Units: {len(sp.aus)}   Bilder: {len(pics)}")
    if dur:
        print(f"Dauer: {dur:.2f} s @ {fps:.3f} fps   mittlere Bitrate: {sp.total_bytes * 8 / dur / 1e6:.2f} Mbit/s")
        sizes = [au["bytes"] for au in sp.aus]
        win = max(1, round(fps))
        peak = max(sum(sizes[i:i + win]) for i in range(0, max(1, len(sizes) - win + 1))) * 8 / (win / fps)
        print(f"Spitzen-Bitrate (gleitend über 1 s): {peak / 1e6:.2f} Mbit/s")

    print("\nNAL-Statistik:")
    for t, n in sorted(sp.nal_stats.items()):
        print(f"  {t:>3} {nal_name(t):<22} {n:>8}×  {sp.nal_bytes[t]:>14,} Bytes")

    print("\nParameter-Sets (eindeutige Inhalte):")
    for entry in sp.param_sets.values():
        print(f"\n  -- {nal_name(entry['nal_type'])} ({entry['count']}× gesendet, erstmals AU {entry['first_au']})")
        print(_fmt(entry["fields"], 2))

    print("\nSEI-Katalog:")
    for key, c in sp.sei_catalog.items():
        print(f"\n  -- {_sei_label(key)}: {c['count']}×, erstmals AU {c['first_au']}")
        if ">" not in key:
            print(_fmt(c["example"].get("fields", {}), 2))

    print("\nAU-Aufbau (NAL-Typ-Folgen, häufigste):")
    pat = Counter(" ".join(str(t) for t in au["nals"]) for au in sp.aus)
    for p, n in pat.most_common(6):
        print(f"  {n:>6}×  {p}")
    print("\nSEI-Folgen pro AU (häufigste):")
    sp_pat = Counter(" ".join(au["sei"]) or "-" for au in sp.aus)
    for p, n in sp_pat.most_common(6):
        print(f"  {n:>6}×  {p}")

    print("\nBilder:")
    tc = Counter(p["type"] for p in pics)
    for t in "IPB":
        sel = [p for p in pics if p["type"] == t]
        if sel:
            avg = sum(p["vcl_bytes"] for p in sel) / len(sel)
            qp = sum(sum(p["qp"]) / len(p["qp"]) for p in sel) / len(sel)
            print(f"  {t}: {tc[t]:>6}×   Ø {avg / 1024:8.1f} KiB   Ø QP {qp:5.1f}")
    print(f"  IDR: {sum(p['idr'] for p in pics)}   Referenzbilder: {sum(1 for p in pics if p['ref_idc'])}"
          f"   Slices pro Bild: {sorted(Counter(p['slices'] for p in pics).items())}")
    print(f"  num_ref_idx_l0 aktiv: {sorted(Counter(n for p in pics for n in p['num_ref_idx_l0']).items())}")
    print(f"  num_ref_idx_l1 aktiv: {sorted(Counter(n for p in pics for n in p['num_ref_idx_l1']).items())}")
    mods = Counter((m[0], m[1]) for p in pics for m in p["mods"])
    print(f"  Ref-Listen-Modifikationen (Liste, idc): {sorted(mods.items()) or 'keine'}")
    mm = Counter(m[0] for p in pics for m in p["mmco"])
    print(f"  MMCO-Operationen: {sorted(mm.items()) or 'keine'}")
    ppt = Counter((au["pic"]["type"], au["primary_pic_type"]) for au in sp.aus
                  if au["pic"] and "primary_pic_type" in au)
    if ppt:
        print(f"  Delimiter primary_pic_type je Bildtyp: {sorted(ppt.items())}")
    bad = sum(1 for p in pics if not p["cabac_align_ok"])
    print(f"  Slice-Header-Prüfung (CABAC-Alignment): {'OK' if not bad else f'{bad} Bilder FEHLERHAFT'}"
          f"   max. Headerlänge: {max(b for p in pics for b in p['header_bits'])} Bit")

    keys = [i for i, p in enumerate(pics) if p["type"] == "I"]
    if keys:
        gops = [b - a for a, b in zip(keys, keys[1:])]
        print("\nGOP (Abstand der I-Bilder):", sorted(Counter(gops).items()) if gops else "nur ein GOP")
        end = keys[1] if len(keys) > 1 else min(len(pics), 60)
        print("Erster GOP, Decodier-Reihenfolge:", "".join(p["type"] if p["ref_idc"] else p["type"].lower()
                                                         for p in pics[:end]))
        disp = sorted(pics[:end], key=lambda p: p["poc"] if p["poc"] is not None else 0)
        print("Erster GOP, Anzeige-Reihenfolge: ", "".join(p["type"] if p["ref_idc"] else p["type"].lower()
                                                          for p in disp))
        print("  (Großbuchstabe = Referenzbild, klein = Nicht-Referenz)")

    if pics and pics[0]["mvc"]:
        mv = Counter((p["mvc"]["view_id"], p["mvc"]["anchor_pic_flag"], p["mvc"]["inter_view_flag"],
                      p["mvc"]["temporal_id"], p["mvc"]["priority_id"]) for p in pics)
        print("\nMVC-NAL-Header (view_id, anchor, inter_view, temporal_id, priority_id):")
        for k, n in sorted(mv.items()):
            print(f"  {k}: {n}×")
        anchors = [p for p in pics if p["mvc"]["anchor_pic_flag"]]
        print(f"Anchor-Bilder: {len(anchors)}, Typen: {sorted(Counter(p['type'] for p in anchors).items())}")

    if sp.errors:
        print(f"\nFEHLER ({len(sp.errors)}):")
        for e in sp.errors[:20]:
            print("  " + e)


def report_pair(base, dep, frames):
    bp, dp = base.pictures(), dep.pictures()
    section("Vergleich Base View <-> Dependent View")
    print(f"Bilder: Base {len(bp)}, Dependent {len(dp)}" + ("" if len(bp) == len(dp) else "   <-- UNGLEICH"))
    n = min(len(bp), len(dp))
    mism = Counter()
    examples = {}
    for i in range(n):
        b, d = bp[i], dp[i]
        checks = {
            "POC": b["poc"] == d["poc"],
            # Anchor-Bilder dürfen P sein (nur Inter-View-Referenz), auch wenn Base ein I-Bild ist
            "Bildtyp": b["type"] == d["type"] or (b["type"] == "I" and (d["mvc"] or {}).get("anchor_pic_flag")),
            "IDR": b["idr"] == d["idr"],
            "Referenzbild": bool(b["ref_idc"]) == bool(d["ref_idc"]),
            "frame_num": b["frame_num"] == d["frame_num"],
            "Anchor<->Base-I": (d["mvc"] or {}).get("anchor_pic_flag", 0) == (1 if b["type"] == "I" else 0),
        }
        for k, ok in checks.items():
            if not ok:
                mism[k] += 1
                examples.setdefault(k, i)
    for k in ("POC", "Bildtyp", "IDR", "Referenzbild", "frame_num", "Anchor<->Base-I"):
        status = "identisch" if not mism[k] else f"{mism[k]} Abweichungen (erste bei Bild {examples[k]})"
        print(f"  {k:<16} {status}")

    print("\nGrößenverhältnis Dependent/Base:")
    tb = sum(p["vcl_bytes"] for p in bp[:n])
    td = sum(p["vcl_bytes"] for p in dp[:n])
    print(f"  gesamt (VCL): {td / tb:.1%}")
    for t in "IPB":
        idx = [i for i in range(n) if bp[i]["type"] == t]
        if idx:
            sb = sum(bp[i]["vcl_bytes"] for i in idx)
            sd = sum(dp[i]["vcl_bytes"] for i in idx)
            dt = Counter(dp[i]["type"] for i in idx)
            print(f"  bei Base-{t}-Bildern ({len(idx)}×): {sd / sb:6.1%}   Dependent-Typen dort: {sorted(dt.items())}")

    sub = next(iter(dep.subset_sps.values()), None)
    if sub and "mvc" in sub:
        m = sub["mvc"]
        allowed_a = any(r["l0"] or r["l1"] for r in m["anchor_refs"])
        allowed_n = any(r["l0"] or r["l1"] for r in m["non_anchor_refs"])
        print("\nInter-View-Prädiktion:")
        print(f"  laut Subset-SPS erlaubt: Anchor-Bilder {'JA' if allowed_a else 'nein'},"
              f" Nicht-Anchor-Bilder {'JA' if allowed_n else 'nein'}")
        p_anchor = sum(1 for p in dp if p["mvc"]["anchor_pic_flag"] and p["type"] != "I")
        print(f"  Anchor-Bilder mit P/B-Slices (=> zwingend Inter-View): {p_anchor}")
        iv_mods = sum(1 for p in dp for m_ in p["mods"] if m_[1] in (4, 5))
        print(f"  Slices mit Inter-View-Listenmodifikation (idc 4/5): {iv_mods}")
        print("  Hinweis: Inter-View-Referenzen werden auch ohne Modifikation ans Ende der Ref-Listen")
        print("  angehängt; ob sie tatsächlich genutzt werden, zeigt erst die Makroblock-Ebene.")
        bl0 = Counter(x for p in bp for x in p["num_ref_idx_l0"] if p["type"] == "P")
        dl0 = Counter(x for p in dp for x in p["num_ref_idx_l0"] if p["type"] == "P")
        print(f"  num_ref_idx_l0 bei P: Base {sorted(bl0.items())}  Dependent {sorted(dl0.items())}")

    bpps = set(base.pps)
    dpps = set(dep.pps)
    print(f"\nPPS-IDs: Base {sorted(bpps)}, Dependent {sorted(dpps)}"
          + ("   <-- KOLLISION" if bpps & dpps else "   (getrennt)"))
    print(f"SPS-IDs: Base {sorted(base.sps)}, Subset-SPS {sorted(dep.subset_sps)}")

    if frames:
        section(f"Erste {frames} Access Units")
        print(f"{'AU':>5} | {'Base: Typ ref fn  POC   KiB':<30}| Dependent: Typ ref fn  POC   KiB  anc iv  l0/l1  mods")
        for i in range(min(frames, n)):
            b, d = bp[i], dp[i]
            mv = d["mvc"] or {}
            bt = b["type"] + ("*" if b["idr"] else " ")
            dt = d["type"] + ("*" if d["idr"] else " ")
            print(f"{i:>5} | {bt:<3} {b['ref_idc']:>3} {b['frame_num']:>3} {b['poc']:>5} {b['vcl_bytes'] / 1024:6.1f}"
                  f"     | {dt:<3} {d['ref_idc']:>3} {d['frame_num']:>3} {d['poc']:>5} {d['vcl_bytes'] / 1024:6.1f}"
                  f"  {mv.get('anchor_pic_flag', '-'):>3} {mv.get('inter_view_flag', '-'):>2}"
                  f"  {max(d['num_ref_idx_l0'])}/{max(d['num_ref_idx_l1'])}  {d['mods'] or ''}")
        print("  (* = IDR)")


def main(argv=None):
    ap = argparse.ArgumentParser(description="MVC/H.264-Stream-Analyzer für Blu-ray 3D")
    ap.add_argument("base", help="Base View (.264) oder beliebiger H.264-Stream")
    ap.add_argument("--mvc", help="Dependent View (.mvc)")
    ap.add_argument("--frames", type=int, default=0, help="die ersten N Access Units im Detail auflisten")
    ap.add_argument("--json", help="Rohdaten als JSON speichern")
    args = ap.parse_args(argv)

    def progress(label, offset):
        print(f"\r  {label}: {offset / 1e6:,.0f} MB gelesen", end="", file=sys.stderr, flush=True)

    base = StreamParser(args.base, "Base View").parse(progress)
    print(file=sys.stderr)
    dep = None
    if args.mvc:
        dep = StreamParser(args.mvc, "Dependent View").parse(progress)
        print(file=sys.stderr)

    first_sps = next(iter(base.sps.values()), None) or next(iter(base.subset_sps.values()), None)
    fps = frame_rate(first_sps) if first_sps else None
    report_stream(base, fps)
    if dep:
        report_stream(dep, fps)
        report_pair(base, dep, args.frames)

    if args.json:
        data = {}
        for sp in filter(None, (base, dep)):
            data[sp.label] = {
                "path": sp.path,
                "param_sets": list(sp.param_sets.values()),
                "sei_catalog": sp.sei_catalog,
                "access_units": sp.aus,
                "errors": sp.errors,
            }
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, default=str)
        print(f"\nJSON gespeichert: {args.json}")


if __name__ == "__main__":
    main()
