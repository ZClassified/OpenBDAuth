"""
Prüfung eines HEVC-Elementarstroms nach den Regeln für Ultra HD Blu-ray (docs/plaene/uhd.md, Phase 2).

Quellen der Regeln: Was x265 4.3 mit --uhd-bd erzwingt bzw. ablehnt (Level 5.1 High Tier, Main 10, 4:2:0,
1920×1080 oder 3840×2160, Primärfarben/Übertragung/Matrix, geschlossene GOPs, Keyframe-Abstand höchstens eine
Sekunde, AUD, HRD, Parameter-Sets an jedem Einstiegspunkt). Was nicht belegt ist, steht unten als „zu prüfen“
und wird nach Phase 0 nachgeschärft. Die Puffer-Prüfung ist eine Näherung (konstanter Bildabstand).

    python -m hevctools.check FILM.hevc [--range sdr709|sdr2020|hdr10]
"""

import argparse
import math
import sys
from dataclasses import dataclass

from .nal import DV_EL, DV_RPU, RASL_TYPES
from .sps import PROFILE_NAMES, frame_rate, hrd_cpb
from .stream import StreamParser

ERROR, WARNING, INFO = "error", "warning", "info"

SIZES = {(1920, 1080), (3840, 2160)}
LEVEL_IDC = 153                               # Level 5.1 (level × 30)
# Bildraten (zu prüfen: vollständige Liste für 2160p und 1080p HEVC, Plan „Umfang“)
FRAME_RATES = {(24000, 1001): "23,976", (24, 1): "24", (25, 1): "25", (50, 1): "50", (60000, 1001): "59,94"}
# Dynamikbereich der Disc → (Primärfarben, erlaubte Übertragungen, Matrix)
RANGES = {"sdr709": (1, {1}, 1), "sdr2020": (9, {1, 14}, 9), "hdr10": (9, {16}, 9)}
ALLOWED_PRIMARIES, ALLOWED_TRANSFER, ALLOWED_MATRIX = {1, 9}, {1, 14, 16}, {1, 9}


@dataclass
class Finding:
    level: str
    code: str
    text: str


def detect_range(sps):
    """Dynamikbereich aus der VUI ("sdr709" | "sdr2020" | "hdr10") oder None."""
    v = (sps or {}).get("vui", {})
    key = (v.get("colour_primaries"), v.get("transfer_characteristics"), v.get("matrix_coeffs"))
    for name, (prim, transfers, matrix) in RANGES.items():
        if key[0] == prim and key[1] in transfers and key[2] == matrix:
            return name
    return None


def _fps_key(sps):
    v = sps.get("vui", {})
    if not v.get("vui_timing_info_present_flag") or not v.get("num_units_in_tick"):
        return None
    g = math.gcd(v["time_scale"], v["num_units_in_tick"])
    return v["time_scale"] // g, v["num_units_in_tick"] // g


def _check_sps(sps, add):
    ptl = sps["ptl"]
    compat_main10 = (ptl["general_profile_compatibility_flags"] >> (31 - 2)) & 1
    if ptl["general_profile_idc"] != 2 and not compat_main10:
        add(ERROR, "profile", f"Profil {PROFILE_NAMES.get(ptl['general_profile_idc'], ptl['general_profile_idc'])}"
                              f" – verlangt ist Main 10")
    if ptl["general_level_idc"] != LEVEL_IDC:
        add(ERROR, "level", f"Level {ptl['general_level_idc'] / 30:g} – verlangt ist Level 5.1")
    if not ptl["general_tier_flag"]:
        add(ERROR, "tier", "Main Tier – verlangt ist High Tier")
    if sps["chroma_format_idc"] != 1:
        add(ERROR, "chroma", "Farbunterabtastung ist nicht 4:2:0")
    if (sps["bit_depth_luma"], sps["bit_depth_chroma"]) != (10, 10):
        add(ERROR, "bit_depth", f"{sps['bit_depth_luma']} Bit – verlangt sind 10 Bit")
    if (sps["width"], sps["height"]) not in SIZES:
        add(ERROR, "size", f"{sps['width']}×{sps['height']} – erlaubt sind 1920×1080 und 3840×2160")
    v = sps.get("vui", {})
    if ptl["general_interlaced_source_flag"] or not ptl["general_progressive_source_flag"] or v.get("field_seq_flag"):
        add(ERROR, "progressive", "Strom ist nicht als progressiv gekennzeichnet")
    if sps["sps_max_sub_layers_minus1"]:
        add(ERROR, "sub_layers", "zeitliche Teilschichten (temporal sub-layers) sind nicht erlaubt")
    fps = _fps_key(sps)
    if fps is None:
        add(ERROR, "timing", "keine Bildrate in der VUI (vui_timing_info)")
    elif fps not in FRAME_RATES:
        add(ERROR, "frame_rate", f"Bildrate {fps[0] / fps[1]:.3f} – erlaubt sind "
                                 f"{', '.join(FRAME_RATES.values())} (zu prüfen)")
    if not v.get("colour_description_present_flag"):
        add(ERROR, "colour_missing", "keine Farbkennzeichnung in der VUI (Primärfarben, Übertragung, Matrix)")
    else:
        if v["colour_primaries"] not in ALLOWED_PRIMARIES:
            add(ERROR, "primaries", f"Primärfarben {v['colour_primaries']} – erlaubt sind BT.709 und BT.2020")
        if v["transfer_characteristics"] not in ALLOWED_TRANSFER:
            add(ERROR, "transfer", f"Übertragung {v['transfer_characteristics']} – erlaubt sind BT.709, "
                                   f"BT.2020 (10 Bit) und PQ (HLG ist nicht vorgesehen)")
        if v["matrix_coeffs"] not in ALLOWED_MATRIX:
            add(ERROR, "matrix", f"Matrix {v['matrix_coeffs']} – erlaubt sind BT.709 und BT.2020")
    if hrd_cpb(sps) is None:
        add(ERROR, "hrd", "keine HRD-Parameter (NAL-HRD) in der VUI")


def _check_structure(sp, fps, add):
    pics = sp.pictures()
    if not pics:
        add(ERROR, "no_pictures", "keine Bilder im Strom")
        return
    if not pics[0]["irap"]:
        add(ERROR, "start", "der Strom beginnt nicht mit einem Einstiegspunkt (IRAP-Bild)")
    no_aud = sum(1 for au in sp.aus if not au["aud"])
    if no_aud:
        add(ERROR, "aud", f"{no_aud} Access Units ohne Access Unit Delimiter")
    irap_aus = [au for au in sp.aus if au["pic"] and au["pic"]["irap"]]
    missing = [au["index"] for au in irap_aus if not (au["vps"] and au["sps"] and au["pps"])]
    if missing:
        add(ERROR, "headers", f"{len(missing)} Einstiegspunkte ohne VPS/SPS/PPS (erster bei AU {missing[0]})")
    if any(sp.nal_stats[t] for t in RASL_TYPES):
        add(ERROR, "open_gop", "offene GOPs (RASL-Bilder) – verlangt sind geschlossene GOPs")
    if any(t > 0 for t in sp.temporal_ids):
        add(ERROR, "temporal_id", "NAL-Units mit TemporalId > 0 (zeitliche Teilschichten)")
    irap = [i for i, p in enumerate(pics) if p["irap"]]
    gaps = [b - a for a, b in zip(irap, irap[1:])] + [len(pics) - irap[-1]] if irap else []
    if fps and gaps:
        limit = math.ceil(fps - 1e-6)
        if max(gaps) > limit:
            add(ERROR, "gop_length", f"Abstand der Einstiegspunkte bis {max(gaps)} Bilder – höchstens {limit} "
                                     f"(eine Sekunde)")
    if sp.layer_nals:
        add(ERROR, "layers", f"{sp.layer_nals} NAL-Units einer Zusatzschicht (nuh_layer_id > 0)")
    if sp.nal_stats[DV_RPU] or sp.nal_stats[DV_EL]:
        add(ERROR, "dolby_vision", "Dolby-Vision-Daten im Strom (nicht vorgesehen)")
    if sp.hdr10plus:
        add(ERROR, "hdr10plus", "HDR10+-Metadaten im Strom (nicht vorgesehen)")


def _check_hdr(sp, dynamic_range, add):
    md, cll = sp.hdr.get("mastering_display"), sp.hdr.get("content_light_level")
    if dynamic_range != "hdr10":
        if md or cll:
            add(WARNING, "hdr_sei_on_sdr", "HDR-Metadaten in einem SDR-Strom")
        return
    if md is None:
        add(ERROR, "mastering_display", "HDR10 ohne Mastering-Display-Angaben (SEI 137)")
    elif md["max_luminance"] <= md["min_luminance"] or md["max_luminance"] < 100 or md["max_luminance"] > 10000:
        add(ERROR, "mastering_values", f"Mastering Display unplausibel: {md['min_luminance']}–"
                                       f"{md['max_luminance']} cd/m²")
    if cll is None:
        add(ERROR, "content_light", "HDR10 ohne MaxCLL/MaxFALL (SEI 144)")
    elif cll["max_fall"] > cll["max_cll"] and cll["max_cll"]:
        add(ERROR, "cll_values", f"MaxFALL {cll['max_fall']} größer als MaxCLL {cll['max_cll']}")
    irap_aus = [au for au in sp.aus if au["pic"] and au["pic"]["irap"]]
    without = sum(1 for au in irap_aus if 137 not in au["sei"] or 144 not in au["sei"])
    if without:
        add(WARNING, "hdr_sei_repeat", f"{without} Einstiegspunkte ohne HDR-Metadaten (zu prüfen: ob jeder "
                                       f"Einstiegspunkt sie tragen muss)")


def simulate_cpb(au_bytes, bit_rate, cpb_size, cbr, fps, initial_delay=None):
    """
    CPB-Füllstand Bild für Bild (Näherung mit gleichem Abstand zwischen den Bildern): Der Puffer füllt sich mit
    der Bitrate, zu jedem Bild wird dessen Größe entnommen. Anfangs gefüllt für initial_delay (90-kHz-Takt aus der
    Buffering-Period-SEI), ohne Angabe voll. Rückgabe: None oder ("underflow"|"overflow", AU, Bild-Bits, Füllstand).
    """
    fullness = cpb_size if initial_delay is None else bit_rate * initial_delay / 90000
    per_picture = bit_rate / fps
    for index, size in enumerate(au_bytes):
        bits = size * 8
        if bits > fullness + 8:
            return "underflow", index, bits, fullness
        fullness = fullness - bits + per_picture
        if fullness > cpb_size:
            if cbr:
                return "overflow", index, bits, fullness
            fullness = cpb_size                       # VBR: die Zufuhr pausiert bei vollem Puffer
    return None


def _check_buffer(sp, fps, add):
    cpb = hrd_cpb(sp.first_sps())
    if cpb is None or not fps or not sp.aus:
        return
    bit_rate, size, cbr = cpb
    delay = (sp.buffering or {}).get("initial_cpb_removal_delay")
    if delay is None:
        add(WARNING, "buffering_period", "keine Buffering-Period-SEI – Puffer-Prüfung mit vollem Puffer")
    result = simulate_cpb([au["bytes"] for au in sp.aus], bit_rate, size, cbr, fps, delay)
    if result and result[0] == "underflow":
        _kind, index, bits, fullness = result
        add(ERROR, "cpb_underflow", f"Puffer-Unterlauf bei AU {index}: Bild {bits / 8e3:.0f} kB, im Puffer "
                                    f"{fullness / 8e3:.0f} kB (Bitrate {bit_rate / 1e6:.1f} Mbit/s)")
    elif result:
        add(ERROR, "cpb_overflow", f"Puffer-Überlauf bei AU {result[1]} (CBR)")


def check_stream(path, dynamic_range=None, progress=None):
    """
    Prüft einen HEVC-Strom. dynamic_range: erwarteter Bereich der Disc ("sdr709" | "sdr2020" | "hdr10") oder None
    (dann nur aus der VUI erkannt und gemeldet). Rückgabe: (findings, info) – Fehler, Warnungen, Hinweise und
    eine Übersicht (Größe, Bildrate, Bilder, Bereich, Bitraten, Encoder).
    """
    return check_parsed(StreamParser(path).parse(progress), dynamic_range)


def check_parsed(sp, dynamic_range=None):
    """Wie check_stream, für einen schon gelesenen Strom (StreamParser)."""
    findings = []

    def add(level, code, text):
        findings.append(Finding(level, code, text))

    for e in sp.errors[:5]:
        add(ERROR, "parse", e)
    sps = sp.first_sps()
    info = {"pictures": len(sp.pictures()), "bytes": sp.total_bytes, "encoder": sp.encoder_info,
            "hdr": sp.hdr}
    if sps is None:
        add(ERROR, "no_sps", "kein Sequence Parameter Set gefunden – ist das ein HEVC-Elementarstrom?")
        return findings, info
    if len({(s["width"], s["height"], s["bit_depth_luma"]) for s in sp.sps.values()}) > 1:
        add(ERROR, "sps_change", "Auflösung oder Bittiefe wechselt innerhalb des Stroms")
    _check_sps(sps, add)
    fps = frame_rate(sps)
    detected = detect_range(sps)
    info.update(width=sps["width"], height=sps["height"], fps=fps, dynamic_range=detected,
                duration=len(sp.pictures()) / fps if fps else None, hrd=hrd_cpb(sps))
    if info["duration"]:
        info["avg_bitrate"] = sp.total_bytes * 8 / info["duration"]
    if dynamic_range and detected != dynamic_range:
        add(ERROR, "range_mismatch", f"Dynamikbereich {detected or 'unbekannt'} – die Disc ist {dynamic_range}")
    _check_structure(sp, fps, add)
    _check_hdr(sp, dynamic_range or detected, add)
    _check_buffer(sp, fps, add)
    return findings, info


def main(argv=None):
    ap = argparse.ArgumentParser(description="HEVC-Prüfung für Ultra HD Blu-ray")
    ap.add_argument("stream", help="HEVC-Elementarstrom (.hevc/.h265)")
    ap.add_argument("--range", choices=sorted(RANGES), help="erwarteter Dynamikbereich der Disc")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    findings, info = check_stream(args.stream, args.range)
    if info.get("width"):
        print(f"{info['width']}×{info['height']}, {info['fps'] or 0:.3f} fps, {info['pictures']} Bilder, "
              f"Bereich: {info['dynamic_range'] or 'unbekannt'}")
    for f in findings:
        print(f"{f.level.upper():8} {f.code}: {f.text}")
    errors = [f for f in findings if f.level == ERROR]
    print("OK" if not errors else f"FEHLER ({len(errors)})")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
