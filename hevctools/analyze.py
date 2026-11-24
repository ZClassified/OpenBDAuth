"""HEVC-Analyzer – ausführlicher Bericht über einen Elementarstrom (mit der Prüfung am Ende).

Aufruf:
    python -m hevctools.analyze FILM.hevc [--range hdr10] [--json out.json]
"""

import argparse
import json
import sys
from collections import Counter

from .check import ERROR, RANGES, check_parsed
from .nal import nal_name
from .sei import sei_name
from .sps import COLOUR_PRIMARIES, MATRIX, PROFILE_NAMES, TRANSFER, frame_rate, hrd_cpb
from .stream import StreamParser


def section(title):
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def report(sp):
    sps = sp.first_sps()
    pics = sp.pictures()
    fps = frame_rate(sps)
    section(f"[{sp.label}] {sp.path}")
    print(f"Dateigröße: {sp.total_bytes:,} Bytes   Access Units: {len(sp.aus)}   Bilder: {len(pics)}")
    if fps and pics:
        dur = len(pics) / fps
        print(f"Dauer: {dur:.2f} s @ {fps:.3f} fps   mittlere Bitrate: {sp.total_bytes * 8 / dur / 1e6:.2f} Mbit/s")
        win = max(1, round(fps))
        sizes = [au["bytes"] for au in sp.aus]
        peak = max(sum(sizes[i:i + win]) for i in range(0, max(1, len(sizes) - win + 1))) * 8 / (win / fps)
        print(f"Spitzen-Bitrate (gleitend über 1 s): {peak / 1e6:.2f} Mbit/s")

    if sps:
        ptl, v = sps["ptl"], sps.get("vui", {})
        print(f"\nProfil: {PROFILE_NAMES.get(ptl['general_profile_idc'], ptl['general_profile_idc'])}, "
              f"Level {ptl['general_level_idc'] / 30:g}, {'High' if ptl['general_tier_flag'] else 'Main'} Tier")
        print(f"Bild: {sps['width']}×{sps['height']} (kodiert {sps['pic_width_in_luma_samples']}×"
              f"{sps['pic_height_in_luma_samples']}), {sps['bit_depth_luma']} Bit, "
              f"{ {0: '4:0:0', 1: '4:2:0', 2: '4:2:2', 3: '4:4:4'}.get(sps['chroma_format_idc'], '?') }, "
              f"{'progressiv' if ptl['general_progressive_source_flag'] else 'nicht progressiv'}")
        if v.get("colour_description_present_flag"):
            print(f"Farbe: Primärfarben {COLOUR_PRIMARIES.get(v['colour_primaries'], v['colour_primaries'])}, "
                  f"Übertragung {TRANSFER.get(v['transfer_characteristics'], v['transfer_characteristics'])}, "
                  f"Matrix {MATRIX.get(v['matrix_coeffs'], v['matrix_coeffs'])}, "
                  f"{'voller' if v.get('video_full_range_flag') else 'begrenzter'} Wertebereich")
        else:
            print("Farbe: keine Kennzeichnung in der VUI")
        cpb = hrd_cpb(sps)
        print("HRD: " + (f"{cpb[0] / 1e6:.1f} Mbit/s, Puffer {cpb[1] / 1e6:.1f} Mbit, {'CBR' if cpb[2] else 'VBR'}"
                         if cpb else "keiner"))
        print(f"Referenzen: max_dec_pic_buffering {sps['sps_max_dec_pic_buffering']}, "
              f"max_num_reorder {sps['sps_max_num_reorder_pics']}")

    md, cll = sp.hdr.get("mastering_display"), sp.hdr.get("content_light_level")
    if md or cll:
        print("\nHDR-Metadaten:")
        if md:
            g, b, r = md["primaries"]
            print(f"  Mastering Display: G{g} B{b} R{r} WP{md['white_point']}, "
                  f"{md['min_luminance']}–{md['max_luminance']} cd/m²")
        if cll:
            print(f"  MaxCLL {cll['max_cll']} cd/m², MaxFALL {cll['max_fall']} cd/m²")
    if sp.encoder_info:
        print(f"\nEncoder: {sp.encoder_info[:300]}{' …' if len(sp.encoder_info) > 300 else ''}")

    print("\nNAL-Statistik:")
    for t, n in sorted(sp.nal_stats.items()):
        print(f"  {t:>3} {nal_name(t):<18} {n:>8}×  {sp.nal_bytes[t]:>14,} Bytes")
    print("\nSEI-Katalog:")
    for t, c in sorted(sp.sei_catalog.items()):
        print(f"  {t:>3} {sei_name(t):<38} {c['count']:>6}×, erstmals AU {c['first_au']}")
    print("\nAU-Aufbau (NAL-Typ-Folgen, häufigste):")
    for p, n in Counter(" ".join(str(t) for t in au["nals"]) for au in sp.aus).most_common(6):
        print(f"  {n:>6}×  {p}")

    if pics:
        print("\nBilder: " + ", ".join(f"{t} {n}×" for t, n in sorted(Counter(p["type"] for p in pics).items())))
        irap = [i for i, p in enumerate(pics) if p["irap"]]
        print("Einstiegspunkte (IRAP): " + ", ".join(f"{nal_name(t)} {n}×" for t, n in
                                                       sorted(Counter(pics[i]["nal_type"] for i in irap).items())))
        gaps = [b - a for a, b in zip(irap, irap[1:])]
        print("Abstand der Einstiegspunkte:", sorted(Counter(gaps).items()) if gaps else "nur einer")
        end = irap[1] if len(irap) > 1 else min(len(pics), 60)
        print("Erster GOP, Decodier-Reihenfolge:", "".join(p["type"] for p in pics[:end]))
    if sp.errors:
        print(f"\nLESEFEHLER ({len(sp.errors)}):")
        for e in sp.errors[:20]:
            print("  " + e)


def main(argv=None):
    ap = argparse.ArgumentParser(description="HEVC-Analyzer für Ultra HD Blu-ray")
    ap.add_argument("stream", help="HEVC-Elementarstrom (.hevc/.h265)")
    ap.add_argument("--range", choices=sorted(RANGES), help="erwarteter Dynamikbereich der Disc")
    ap.add_argument("--json", help="Rohdaten als JSON speichern")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    def progress(label, offset):
        print(f"\r  {label}: {offset / 1e6:,.0f} MB gelesen", end="", file=sys.stderr, flush=True)

    sp = StreamParser(args.stream).parse(progress)
    print(file=sys.stderr)
    report(sp)
    findings, _info = check_parsed(sp, args.range)
    section("Prüfung für Ultra HD Blu-ray")
    for f in findings:
        print(f"  {f.level.upper():8} {f.code}: {f.text}")
    errors = [f for f in findings if f.level == ERROR]
    print("  OK" if not errors else f"  FEHLER ({len(errors)})")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"path": sp.path, "param_sets": list(sp.param_sets.values()), "sei_catalog": sp.sei_catalog,
                       "hdr": sp.hdr, "encoder": sp.encoder_info, "access_units": sp.aus, "errors": sp.errors,
                       "findings": [f.__dict__ for f in findings]}, fh, indent=1, default=str)
        print(f"\nJSON gespeichert: {args.json}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
