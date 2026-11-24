"""
Ultra HD Blu-ray: HEVC-Kodierung mit x265 (docs/plaene/uhd.md, Phase 3; Datenrate siehe Abschnitt „Datenrate“).

- Quelle: Mezzanine (ProRes, DNxHR) oder ein anderes Video mit 10/12 Bit, 3840×2160 (für 2160p) bzw. 3840×2160 oder
  1920×1080 (für 1080p), progressiv, Bildrate 23,976 / 24 / 25 / 50 / 59,94. Dynamikbereich aus der
  Farbkennzeichnung (SDR BT.709, SDR BT.2020, HDR10); HLG, Dolby Vision und fehlende Kennzeichnung werden abgelehnt,
  umgewandelt wird nichts. HDR10 braucht Mastering-Display und MaxCLL/MaxFALL (aus der Datei oder angegeben).
- Kodierung: x265 mit --uhd-bd, Datenrate als feste Stufe, „Genau“ (zwei Durchläufe) oder „Schnell“ (einer); die
  Spitzenrate legt das Programm fest. x265 schaltet --uhd-bd bei unpassenden Angaben nur ab und kodiert weiter –
  deshalb prüft hevctools jedes Ergebnis.
- Die Werte für Spitzenrate und Puffer sind Annahmen bis zu den Hardware-Tests 0.10 und 0.11.
"""

import json
import math
import os
import re
import subprocess
from dataclasses import dataclass
from fractions import Fraction

from core.translations import tr
from modules.prepare.jobs import NO_WINDOW, Job, Step, describe_problems, tool

RES_2160, RES_1080 = "2160", "1080"
SIZES = {RES_2160: (3840, 2160), RES_1080: (1920, 1080)}

# Stufen der mittleren Datenrate in Mbit/s und Vorgabe (Plan „Datenrate“; Annahmen bis Phase 0.11)
BITRATES = {RES_2160: (60, 45, 35, 25), RES_1080: (20, 15, 10)}
DEFAULT_BITRATE = {RES_2160: 45, RES_1080: 15}
# Spitzenrate und Puffer des Videos in kbit/s (Annahme: 80 Mbit/s für den ganzen Strom inkl. Ton; Phase 0.10)
PEAK_KBPS = {RES_2160: 72000, RES_1080: 40000}
BUFSIZE_KBITS = {RES_2160: 60000, RES_1080: 30000}

MODE_EXACT, MODE_FAST = "exact", "fast"
X265_PRESET = "medium"                       # 4K mit „slow“ dauert ein Vielfaches; Qualität über die Datenrate
FAST_SIZE_MARGIN = 1.10                      # „Schnell“: Größe nur ungefähr (Annahme ±10 %)
STATS_BYTES_PER_FRAME = {RES_2160: 36_000, RES_1080: 9_000}   # x265-Statistik (.cutree) beim Genau-Weg, gemessen

FPS_UHD = ("23.976", "24", "25", "50", "59.94")   # zu prüfen: vollständige Liste (Plan, offene Frage 3)

SDR709, SDR2020, HDR10 = "sdr709", "sdr2020", "hdr10"
# Dynamikbereich → (Primärfarben, Übertragungen, Matrix) in ffprobe-Namen; x265- und ffmpeg-Namen für die Ausgabe
RANGE_PROBE = {SDR709: ("bt709", ("bt709",), "bt709"),
               SDR2020: ("bt2020", ("bt2020-10", "bt709"), "bt2020nc"),
               HDR10: ("bt2020", ("smpte2084",), "bt2020nc")}
RANGE_X265 = {SDR709: ("bt709", "bt709", "bt709"),
              SDR2020: ("bt2020", "bt2020-10", "bt2020nc"),
              HDR10: ("bt2020", "smpte2084", "bt2020nc")}


@dataclass(frozen=True)
class HdrMeta:
    """
    HDR10-Metadaten in den Einheiten von x265/SEI: Primärfarben und Weißpunkt in 0,00002 (CIE xy × 50 000),
    Helligkeit in 0,0001 cd/m². max_cll/max_fall in cd/m².
    """
    green: tuple
    blue: tuple
    red: tuple
    white: tuple
    max_luminance: int
    min_luminance: int
    max_cll: int
    max_fall: int

    def x265_params(self):
        def xy(p):
            return f"({p[0]},{p[1]})"
        return [f"master-display=G{xy(self.green)}B{xy(self.blue)}R{xy(self.red)}WP{xy(self.white)}"
                f"L({self.max_luminance},{self.min_luminance})", f"max-cll={self.max_cll},{self.max_fall}"]

    def plausible(self):
        return 0 <= self.min_luminance < self.max_luminance and self.max_fall <= self.max_cll


def detect_range(src):
    """Dynamikbereich der Quelle aus der Farbkennzeichnung (ffprobe) oder None."""
    for name, (prim, transfers, matrix) in RANGE_PROBE.items():
        if src.color_primaries == prim and src.color_transfer in transfers and src.color_space == matrix:
            return name
    return None


def _scaled(value, factor):
    try:
        return int(round(Fraction(str(value)) * factor))
    except (ValueError, ZeroDivisionError):
        return None


def hdr_meta_from_side_data(side_data):
    """HdrMeta aus der side_data_list des ersten Bildes (ffprobe), None, wenn etwas fehlt."""
    md = next((d for d in side_data if d.get("side_data_type") == "Mastering display metadata"), None)
    cll = next((d for d in side_data if d.get("side_data_type") == "Content light level metadata"), None)
    if md is None or cll is None:
        return None
    pts = {k: _scaled(md.get(k), 50000) for k in ("green_x", "green_y", "blue_x", "blue_y", "red_x", "red_y",
                                                  "white_point_x", "white_point_y")}
    lum = {k: _scaled(md.get(k), 10000) for k in ("max_luminance", "min_luminance")}
    if None in pts.values() or None in lum.values():
        return None
    return HdrMeta(green=(pts["green_x"], pts["green_y"]), blue=(pts["blue_x"], pts["blue_y"]),
                   red=(pts["red_x"], pts["red_y"]), white=(pts["white_point_x"], pts["white_point_y"]),
                   max_luminance=lum["max_luminance"], min_luminance=lum["min_luminance"],
                   max_cll=int(cll.get("max_content", 0)), max_fall=int(cll.get("max_average", 0)))


def probe_hdr_meta(path):
    """HDR10-Metadaten der Quelle (erstes Bild) oder None."""
    try:
        out = subprocess.run([tool('ffprobe'), '-v', 'error', '-select_streams', 'v:0', '-read_intervals', '%+#1',
                              '-show_frames', '-show_entries', 'frame=side_data_list', '-of', 'json', path],
                             capture_output=True, text=True, creationflags=NO_WINDOW).stdout
        frames = json.loads(out or "{}").get("frames", [])
    except (OSError, ValueError):
        return None
    return hdr_meta_from_side_data(frames[0].get("side_data_list", [])) if frames else None


def source_problems(src, resolution=RES_2160, dynamic_range=None, hdr=None):
    """
    Gründe, warum eine Quelle für UHD nicht angenommen wird, als Liste von (Code, Details); leer = in Ordnung.
    dynamic_range: Bereich der Disc (None = der Quelle folgen). hdr: HdrMeta der Quelle oder angegeben.
    Codes: uhd_size, uhd_fps, uhd_bit_depth, interlaced, uhd_hlg, uhd_dolby_vision, uhd_colour, uhd_range,
    uhd_hdr_meta.
    """
    problems = []
    allowed = [SIZES[RES_2160]] + ([SIZES[RES_1080]] if resolution == RES_1080 else [])
    if (src.width, src.height) not in allowed:
        problems.append(("uhd_size", {"size": f"{src.width}x{src.height}",
                                      "allowed": " / ".join(f"{w}x{h}" for w, h in allowed)}))
    if src.fps_str not in FPS_UHD:
        problems.append(("uhd_fps", {"fps": src.fps_str}))
    if src.bit_depth < 10:
        problems.append(("uhd_bit_depth", {"bits": src.bit_depth}))
    if src.field_order in ("tt", "bb", "tb", "bt"):
        problems.append(("interlaced", {"order": src.field_order}))
    detected = detect_range(src)
    if src.dolby_vision:
        problems.append(("uhd_dolby_vision", {}))
    elif src.color_transfer == "arib-std-b67":
        problems.append(("uhd_hlg", {}))
    elif detected is None:
        problems.append(("uhd_colour", {"prim": src.color_primaries or "?", "trc": src.color_transfer or "?",
                                        "matrix": src.color_space or "?"}))
    elif dynamic_range and detected != dynamic_range:
        problems.append(("uhd_range", {"source": tr(f"uhd_range_{detected}"),
                                       "disc": tr(f"uhd_range_{dynamic_range}")}))
    elif detected == HDR10 and (hdr is None or not hdr.plausible()):
        problems.append(("uhd_hdr_meta", {}))
    return problems


def output_path(src, resolution, out_dir=None):
    """<Quelle>_2160p.hevc bzw. <Quelle>_1080p.hevc (unterscheidet sich von der .264 einer Blu-ray-Fassung)."""
    work_dir, filename = os.path.split(src.path)
    return os.path.join(out_dir or work_dir, f"{os.path.splitext(filename)[0]}_{resolution}p.hevc")


def _safe_name(text):
    """Dateiname ohne Zeichen, die in -x265-params stören (Doppelpunkt trennt dort die Optionen)."""
    return re.sub(r"[^\w.-]", "_", text)


def x265_params(src, resolution, dynamic_range, hdr=None):
    """x265-Optionen für UHD-Blu-ray (ohne Durchlauf/Statistik)."""
    prim, trc, matrix = RANGE_X265[dynamic_range]
    params = ["uhd-bd=1", "aud=1", "hrd=1", "repeat-headers=1", "open-gop=0",
              f"keyint={math.ceil(src.fps_val - 1e-6)}", "min-keyint=1",
              f"colorprim={prim}", f"transfer={trc}", f"colormatrix={matrix}", "range=limited",
              f"vbv-maxrate={PEAK_KBPS[resolution]}", f"vbv-bufsize={BUFSIZE_KBITS[resolution]}", "log-level=warning"]
    if dynamic_range == HDR10:
        params += ["hdr10=1", "hdr10-opt=1"] + hdr.x265_params()
    return params


def build_uhd_job(src, resolution=RES_2160, bitrate=None, mode=MODE_EXACT, dynamic_range=None, hdr=None,
                  out_dir=None):
    """
    UHD-Blu-ray-HEVC (.hevc) aus einem Video. resolution: "2160" | "1080"; bitrate: Stufe aus BITRATES (Mbit/s);
    mode: "exact" (zwei Durchläufe) | "fast" (einer); dynamic_range: Bereich der Disc oder None (wie die Quelle);
    hdr: HdrMeta, wenn die Quelle keine mitbringt (sonst aus der Datei gelesen).
    ValueError bei ungeeigneten Quellen (source_problems) oder unbekannter Stufe.
    """
    if hdr is None and detect_range(src) == HDR10:
        hdr = probe_hdr_meta(src.path)
    problems = source_problems(src, resolution, dynamic_range, hdr)
    if problems:
        raise ValueError(describe_problems(problems))
    bitrate = bitrate or DEFAULT_BITRATE[resolution]
    if bitrate not in BITRATES[resolution]:
        raise ValueError(tr("prep_uhd_bitrate_unknown", mbps=bitrate, res=resolution))
    dynamic_range = detect_range(src)
    out = output_path(src, resolution, out_dir)
    cwd, out_name = os.path.split(out)
    stats = _safe_name(os.path.splitext(out_name)[0]) + ".x265stats"   # relativ zum Zielordner (siehe oben)
    filters = []
    if (src.width, src.height) != SIZES[resolution]:
        w, h = SIZES[resolution]
        filters.append(f"scale={w}:{h}:flags=lanczos")
    prim, trc, matrix = RANGE_X265[dynamic_range]
    base = [tool('ffmpeg'), '-y', '-stats', '-i', src.path, '-map', '0:v:0', '-an', '-sn',
            *(['-vf', ",".join(filters)] if filters else []), '-pix_fmt', 'yuv420p10le', '-fps_mode', 'cfr',
            '-c:v', 'libx265', '-preset', X265_PRESET, '-profile:v', 'main10', '-b:v', f'{bitrate}M',
            '-color_primaries', prim, '-color_trc', trc, '-colorspace', matrix]
    params = x265_params(src, resolution, dynamic_range, hdr)
    label = dict(res=f"{resolution}p", mbps=bitrate, range=tr(f"uhd_range_{dynamic_range}"))
    notes = [tr("prep_note_uhd", **label)]
    if mode == MODE_EXACT:
        steps = [
            Step(tr("prep_step_uhd_pass", n=1, **label), (0.0, 0.35),
                 cmd=[*base, '-x265-params', ":".join(params + ["pass=1", f"stats={stats}"]), '-f', 'null',
                      os.devnull]),
            Step(tr("prep_step_uhd_pass", n=2, **label), (0.35, 0.95),
                 cmd=[*base, '-x265-params', ":".join(params + ["pass=2", f"stats={stats}"]), '-f', 'hevc',
                      out_name]),
        ]
    else:
        steps = [Step(tr("prep_step_uhd_fast", **label), (0.0, 0.95),
                      cmd=[*base, '-x265-params', ":".join(params), '-f', 'hevc', out_name])]
        notes.append(tr("prep_note_uhd_fast"))

    def check(ctx):
        from hevctools.check import ERROR, check_stream

        def on_progress(_label, pos):
            size = os.path.getsize(out) or 1
            ctx.progress(min(1.0, pos / size))
            ctx.log(tr("prep_log_hevc_checking", share=f"{min(1.0, pos / size):.0%}"), is_progress=True)

        findings, info = check_stream(out, dynamic_range, progress=on_progress)
        for f in findings:
            ctx.log(f"[{f.level.upper()}] {f.text}")
        if any(f.level == ERROR for f in findings):
            return 1
        rate = info.get("avg_bitrate") or 0
        ctx.log(tr("prep_log_hevc_ok", n=info["pictures"], gb=f"{info['bytes'] / 1e9:.2f}",
                   mbps=f"{rate / 1e6:.1f}"))
        return 0

    steps.append(Step(tr("prep_step_hevc_check"), (0.95, 1.0), func=check))
    frames = src.duration * src.fps_val
    size = src.duration * bitrate * 125_000 * (FAST_SIZE_MARGIN if mode == MODE_FAST else 1.0)
    stats_space = frames * STATS_BYTES_PER_FRAME[resolution] if mode == MODE_EXACT else 0
    return Job("uhd", cwd, src.duration, steps, outputs=[out], temp_prefixes=[os.path.join(cwd, stats)],
               notes=notes, space_needed=int((size + stats_space) * 1.1))


def estimated_size(duration, bitrate, mode=MODE_EXACT):
    """Erwartete Größe des Videos in Bytes (für Füllanzeige und „passt bis …“)."""
    return int(duration * bitrate * 125_000 * (FAST_SIZE_MARGIN if mode == MODE_FAST else 1.0))
