"""Encoding-Aufträge als reine Funktionen (ohne GUI): Befehlsaufbau für 2D, 3D und Audio.

Ein Auftrag (`Job`) ist eine Folge von Schritten: ffmpeg-Befehle als Argumentlisten oder Python-Schritte
(Keyframe-Datei, MVC-Rewrite, Prüfung). `run_job` arbeitet sie ab – headless für Tests und CLI, oder mit
einem eigenen Befehls-Runner aus der GUI. Rückfragen an den Nutzer (720p, 3D-Bildrate) gehören vor
den Aufbau des Auftrags, nicht hinein.

Quellen, die nicht Blu-ray-tauglich sind (Bildrate, HDR, Interlaced, 3D-Format), prüft `source_problems`;
die build-Funktionen werfen in dem Fall ValueError, damit kein solcher Auftrag entstehen kann.

Hardware-geprüfte Parameter (2D-x264-Optionen, X264_3D_OPTS) nicht ohne neuen Player-Test ändern –
tests/test_jobs.py hält die erzeugten Befehle fest.
"""

import glob
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from core.translations import tr
from mvctools.rewrite import MvcRewriter
from mvctools.verify import verify_pair

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
CANCELLED = -999

# Eigener MVC-Weg (Phase 1, siehe docs/mvc/): beide Augen mit identischer GOP-Struktur, damit Base und
# Dependent View Bild für Bild zusammenpassen. Das linke Auge setzt IDR-Bilder an Szenenwechseln (min-keyint=1:
# jedes I ist IDR, wie für die Anchors nötig), das rechte bekommt genau diese Positionen erzwungen.
# Farbkennzeichnung im SPS (VUI) wie auf Blu-ray üblich: Primärfarben, Transfer und Matrix BT.709 (1/1/1).
# Die ffmpeg-Ausgabeoptionen (COLOR_BT709) allein reichen nicht – ffmpeg 9 übernimmt nur die Matrix, Primärfarben
# und Transfer blieben „nicht angegeben“. Deshalb zusätzlich direkt in den x264-Parametern (seit v0.8.1).
X264_BT709 = "colorprim=bt709:transfer=bt709:colormatrix=bt709"

# VBV: Blu-ray 3D erlaubt bis 40 Mbit/s pro View und 60 Mbit/s gesamt; 2 × 28 Mbit/s lässt Platz für Audio.
X264_3D_OPTS = (
    "keyint={gop}:min-keyint={min_keyint}:scenecut={scenecut}:open-gop=0:bframes=3:b-adapt=0:b-pyramid=none:"
    "ref=3:slices=6:weightp=0:bluray-compat=1:nal-hrd=vbr:vbv-maxrate=28000:vbv-bufsize=30000:"
    "aud=1:level=4.1:pic-struct=1:force-cfr=1:sar=1/1:" + X264_BT709
)
COLOR_BT709 =['-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709']

# 2D-Bitraten-Voreinstellungen: Mittel -> Spitze (Mbit/s)
BITRATE_2D_MAX = {25: 40, 20: 35, 15: 30}

# Bildraten, die Blu-ray nicht kennt -> nächstgelegene BD-Rate (Zähler, Nenner, Anzeige).
# Angepasst wird per fps-Filter (einzelne Bilder entfallen), der Ton bleibt dadurch unverändert synchron.
NON_BD_FPS = {
    "30": (30000, 1001, "29.97"),
    "60": (60000, 1001, "59.94"),
}

# Blu-ray 2D: 1080 nur bis 30 fps (25/29,97 als PsF), 720p nur mit 23,976/24/50/59,94 (60 wird angepasst).
# Alle anderen Bildraten (auch variable Bildraten vom Handy) werden abgelehnt.
FPS_1080 = ("23.976", "24", "25", "29.97", "30")
FPS_720 = ("23.976", "24", "50", "59.94", "60")

# HDR lässt sich nicht verlässlich automatisch nach Rec.709 bringen (das ist Grading-Arbeit) -> abgelehnt
HDR_TRANSFERS = ("smpte2084", "arib-std-b67")
INTERLACED = ("tt", "bb", "tb", "bt")

# 3D: genau zwei Anlieferformate, volle HD-Auflösung pro Auge (oben bzw. links = linkes Auge)
STEREO_LAYOUTS = {(1920, 2160): "tab", (3840, 1080): "sbs"}


def is_bd3d_fps(fps_val):
    """3D-Blu-ray (MVC, 1080p) kennt nur 23,976 und 24 fps – alles andere wird nicht codiert."""
    return abs(fps_val - 24000 / 1001) < 0.05 or abs(fps_val - 24.0) < 0.05


# --- Werkzeuge ------------------------------------------------------------------------------------

_tool_resolver = None


def configure_tools(resolver):
    """Woher ffmpeg und ffprobe kommen: resolver(name) -> Pfad oder None (OpenBDAuth: find_tool mit den
    mitgelieferten Werkzeugen). Ohne Aufruf, wie in BD3DEnc, werden sie über den PATH gefunden."""
    global _tool_resolver
    _tool_resolver = resolver


def tool(name):
    return (_tool_resolver(name) if _tool_resolver else None) or name


def ffmpeg_major_version(version_text):
    """Hauptversion aus `ffmpeg -version`; None bei Git-Builds ohne Versionsnummer („N-12345-g…“)."""
    m = re.match(r"ffmpeg version n?(\d+)\.", version_text)
    return int(m.group(1)) if m else None


def ffmpeg_supports_option_files():
    """Optionswerte aus Dateien laden (`-/option datei`) gibt es ab ffmpeg 7.0."""
    try:
        out = subprocess.run([tool('ffmpeg'), '-hide_banner', '-version'], capture_output=True, text=True,
                             creationflags=NO_WINDOW).stdout
    except Exception:
        return False
    major = ffmpeg_major_version(out)
    # Git-Builds haben keine Versionsnummer und sind in der Regel aktuell
    return major >= 7 if major is not None else "version N-" in out


def ffmpeg_has_libx264():
    try:
        out = subprocess.run([tool('ffmpeg'), '-hide_banner', '-encoders'], capture_output=True, text=True,
                             creationflags=NO_WINDOW).stdout
        return "libx264" in out
    except Exception:
        return False


def read_x264_keyframes(stats_path):
    """I-Bilder (Eingangs-Bildnummern) aus einer x264-Pass-1-Statistik. None, wenn die Datei fehlt oder
    ein Non-IDR-I-Bild enthält – dann gäbe es im Dependent View kein passendes Anchor-Bild."""
    try:
        with open(stats_path, encoding="ascii", errors="replace") as f:
            types = re.findall(r"in:(\d+) out:\d+ type:(\w)", f.read())
    except OSError:
        return None
    if not types or any(t == "i" for _, t in types):
        return None
    return sorted(int(n) for n, t in types if t == "I")


# --- Quelle ---------------------------------------------------------------------------------------

@dataclass
class SourceInfo:
    path: str
    width: int
    height: int
    fps_val: float
    fps_str: str
    gop: int
    duration: float = 0.0
    codec: str = ""
    field_order: str = ""
    color_transfer: str = ""
    color_primaries: str = ""
    color_space: str = ""
    dolby_vision: bool = False
    has_audio: bool = False        # v1.29.1: nur für den Hinweis, dass der Ton nicht übernommen wird


def parse_fps(video):
    """Bildrate (Float), Bildrate (Text) und Blu-ray-GOP-Länge (max. 1 s) aus einem ffprobe-Videostream."""
    fps_str_raw = video.get('avg_frame_rate')
    if not fps_str_raw or fps_str_raw in ("0/0", "0"):
        fps_str_raw = video.get('r_frame_rate')
    if not fps_str_raw or fps_str_raw in ("0/0", "0"):
        fps_str_raw = "24/1"

    try:
        if '/' in fps_str_raw:
            num, den = fps_str_raw.split('/')
            num, den = float(num), float(den)
            fps_val = num / den if den != 0 else 24.0
        else:
            fps_val = float(fps_str_raw)
    except Exception:
        fps_val = 24.0

    if abs(fps_val - 23.976) < 0.005 or abs(fps_val - (24000/1001)) < 0.005:
        return fps_val, "23.976", 24
    if abs(fps_val - 24.0) < 0.005:
        return fps_val, "24", 24
    if abs(fps_val - 25.0) < 0.005:
        return fps_val, "25", 25
    if abs(fps_val - 29.97) < 0.005 or abs(fps_val - (30000/1001)) < 0.005:
        return fps_val, "29.97", 30
    if abs(fps_val - 30.0) < 0.005:
        return fps_val, "30", 30
    if abs(fps_val - 50.0) < 0.005:
        return fps_val, "50", 50
    if abs(fps_val - 59.94) < 0.005 or abs(fps_val - (60000/1001)) < 0.005:
        return fps_val, "59.94", 60
    if abs(fps_val - 60.0) < 0.005:
        return fps_val, "60", 60
    return fps_val, str(round(fps_val, 3)), max(1, round(fps_val))


def _duration(data, stream):
    for src in (data.get('format', {}), stream):
        try:
            d = float(src.get('duration', 0.0))
            if d:
                return d
        except (TypeError, ValueError):
            pass
    return 0.0


def _start_time(stream):
    try:
        return float(stream.get('start_time', 0.0))
    except (TypeError, ValueError):
        return 0.0


class ProbeError(ValueError):
    """ffprobe ist gescheitert, ohne etwas über die Datei zu liefern; message ist ffprobes eigene Meldung.
    Unterklasse von ValueError, damit bestehende Fehlerbehandlung („nicht lesbar“) weiter greift."""

    def __init__(self, path, message):
        super().__init__(f"{os.path.basename(path)}: {message}")
        self.path = path
        self.message = message


def _probe_message(stderr, path, returncode):
    """Letzte Zeile von ffprobes Fehlerausgabe (das Ergebnis, davor stehen Einzelheiten der Demuxer), ohne den
    vorangestellten Dateipfad."""
    lines = [line.strip() for line in (stderr or "").splitlines() if line.strip()]
    if not lines:
        return f"exit code {returncode}"
    last = lines[-1]
    return (last[len(path) + 2:] if last.startswith(path + ": ") else last)[:300]


def probe(path):
    """ffprobe-Ausgabe (format + streams) als dict. ProbeError, wenn ffprobe mit Fehler endet und keine Spuren
    liefert (v1.27.3: bisher sah das aus wie eine Datei ohne Bild und Ton)."""
    result = subprocess.run([tool('ffprobe'), '-v', 'error', '-print_format', 'json', '-show_format', '-show_streams',
                             path], capture_output=True, text=True, encoding='utf-8', errors='replace',
                            creationflags=NO_WINDOW)
    try:
        data = json.loads(result.stdout or "{}")
    except ValueError:
        if result.returncode == 0:
            raise
        data = {}
    if result.returncode != 0 and not data.get('streams'):
        raise ProbeError(path, _probe_message(result.stderr, path, result.returncode))
    return data


def _video_stream(data):
    """Erste echte Videospur (Coverbilder in MKV/MP4 zählen nicht)."""
    return next((s for s in data.get('streams', []) if s.get('codec_type') == 'video'
                 and not s.get('disposition', {}).get('attached_pic')), None)


def probe_video(path):
    """SourceInfo einer Videodatei; ValueError, wenn die Datei keine (lesbare) Videospur hat."""
    data = probe(path)
    video = _video_stream(data)
    if video is None:
        raise ValueError(f"Keine Videospur gefunden: {os.path.basename(path)}")
    fps_val, fps_str, gop = parse_fps(video)
    dovi = any(sd.get('side_data_type') == 'DOVI configuration record' for sd in video.get('side_data_list', []))
    return SourceInfo(path=path, width=int(video.get('width', 1920)), height=int(video.get('height', 1080)),
                      fps_val=fps_val, fps_str=fps_str, gop=gop, duration=_duration(data, video),
                      codec=video.get('codec_name', '').upper(), field_order=video.get('field_order', ''),
                      color_transfer=video.get('color_transfer', ''),
                      color_primaries=video.get('color_primaries', ''),
                      color_space=video.get('color_space', ''), dolby_vision=dovi,
                      has_audio=any(s.get('codec_type') == 'audio' for s in data.get('streams', [])))


def stereo_layout(width, height):
    """"tab" (1920×2160, oben = linkes Auge), "sbs" (3840×1080, links = linkes Auge) oder None."""
    return STEREO_LAYOUTS.get((width, height))


def forced_720p(fps_str):
    """True: nur 720p erlaubt (50/60 fps), False: nur 1080 (25/29,97/30 fps), None: beides (23,976/24 fps)."""
    in_1080, in_720 = fps_str in FPS_1080, fps_str in FPS_720
    return None if in_1080 == in_720 else in_720


def source_problems(src, mode):
    """Gründe, warum eine Quelle nicht angenommen wird, als Liste von (Code, Details); leer = in Ordnung.
    mode: "2d" oder "3d". Codes: fps, fps_3d, hdr, interlaced, layout_3d. Die Texte dazu liefert die
    Oberfläche, PROBLEM_TEXT dieselben Texte (prep_problem_…) fürs Log und für ValueError."""
    problems = []
    if mode == "3d":
        if stereo_layout(src.width, src.height) is None:
            problems.append(("layout_3d", {"size": f"{src.width}x{src.height}"}))
        if not is_bd3d_fps(src.fps_val):
            problems.append(("fps_3d", {"fps": src.fps_str}))
    elif src.fps_str not in FPS_1080 + FPS_720:
        problems.append(("fps", {"fps": src.fps_str}))
    if src.color_transfer in HDR_TRANSFERS or src.color_primaries == "bt2020" or src.dolby_vision:
        kind = "Dolby Vision" if src.dolby_vision else {"smpte2084": "HDR10/PQ", "arib-std-b67": "HLG"}.get(
            src.color_transfer, "BT.2020")
        problems.append(("hdr", {"kind": kind}))
    if src.field_order in INTERLACED:
        problems.append(("interlaced", {"order": src.field_order}))
    return problems


class _ProblemTexts:
    """Texte der Quell-Probleme (v1.27.2: in der Sprache der Oberfläche, core/translations.py prep_problem_…)."""
    def __getitem__(self, code):
        return tr("prep_problem_" + code)


PROBLEM_TEXT = _ProblemTexts()


def describe_problems(problems):
    return " ".join(PROBLEM_TEXT[code].format(**details) for code, details in problems)


# --- Auftrag --------------------------------------------------------------------------------------

@dataclass
class Step:
    title: str
    progress: tuple = (0.0, 1.0)            # Abschnitt des Fortschrittsbalkens
    cmd: Optional[List[str]] = None         # ffmpeg-Aufruf …
    func: Optional[Callable] = None         # … oder Python-Schritt: func(ctx) -> int (0 = ok)


@dataclass
class Job:
    kind: str                               # "2d" | "3d" | "audio"
    cwd: str
    duration: float
    steps: List[Step]
    outputs: List[str]                      # Zieldateien, bei Abbruch gelöscht
    temp: List[str] = field(default_factory=list)   # Zwischendateien, immer gelöscht
    temp_prefixes: List[str] = field(default_factory=list)  # … und alles, was so beginnt (x264-Pass-Logs)
    notes: List[str] = field(default_factory=list)  # Hinweise fürs Log
    space_needed: int = 0                   # geschätzter Platzbedarf im Zielordner (Bytes, inkl. Zwischendateien)

    def remove_temp(self):
        files = list(self.temp)
        for prefix in self.temp_prefixes:
            files += glob.glob(glob.escape(prefix) + "*")
        for f in files:
            try:
                os.remove(f)
            except OSError:
                pass

    def remove_outputs(self):
        for f in self.outputs:
            try:
                os.remove(f)
            except OSError:
                pass


def free_space_shortfall(job):
    """(benötigt, frei) in Bytes, wenn im Zielordner voraussichtlich zu wenig Platz ist, sonst None."""
    try:
        free = shutil.disk_usage(os.path.dirname(job.outputs[0]) or ".").free
    except OSError:
        return None
    return (job.space_needed, free) if job.space_needed > free else None


class StepContext:
    """Was ein Python-Schritt vom Runner bekommt."""

    def __init__(self, log, progress, cancelled):
        self.log = log                      # log(text, is_progress=False)
        self.progress = progress            # progress(anteil 0..1 innerhalb des Schritts)
        self.cancelled = cancelled          # cancelled() -> bool


def banner(title):
    return f"\n=======================================================\n {title}\n" \
           f"======================================================="


def _run_subprocess(step, job, log):
    log(banner(step.title))
    log("> " + subprocess.list2cmdline(step.cmd))
    proc = subprocess.run(step.cmd, cwd=job.cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          creationflags=NO_WINDOW)
    if proc.returncode != 0:
        log(proc.stdout.decode('utf-8', errors='replace')[-3000:])
    return proc.returncode


def run_job(job, run_cmd=None, log=None, progress=None, cancelled=None):
    """Führt die Schritte eines Auftrags nacheinander aus. Rückgabe 0, Fehlercode oder CANCELLED.

    run_cmd(step, job) -> int ersetzt den einfachen Subprozess-Aufruf (die GUI streamt Ausgabe und Fortschritt).
    Zwischendateien werden immer gelöscht, Zieldateien nur bei Abbruch.
    """
    log = log or (lambda text, is_progress=False: None if is_progress else print(text))
    cancelled = cancelled or (lambda: False)
    run_cmd = run_cmd or (lambda step, j: _run_subprocess(step, j, log))
    for note in job.notes:
        log(note)
    try:
        for step in job.steps:
            if cancelled():
                return CANCELLED
            if step.cmd is not None:
                ret = run_cmd(step, job)
            else:
                lo, hi = step.progress
                if progress:
                    progress(lo)
                log(banner(step.title))
                ctx = StepContext(log, (lambda f: progress(lo + (hi - lo) * f)) if progress else (lambda f: None),
                                  cancelled)
                ret = step.func(ctx)
            if cancelled():
                return CANCELLED
            if ret != 0:
                return ret
        return 0
    finally:
        job.remove_temp()
        if cancelled():
            job.remove_outputs()


def _output(work_dir, out_dir, name):
    """Ausgabe für einen ffmpeg-Aufruf mit cwd=work_dir: (Argument im Befehl, voller Pfad)."""
    if out_dir:
        path = os.path.join(out_dir, name)
        return path, path
    return name, os.path.join(work_dir, name)


# --- 2D -------------------------------------------------------------------------------------------

def check_fps_conform(path, conform, duration, log):
    """Prüft nach dem Anpassen von 30/60 fps Bildrate und Bildanzahl des erzeugten Streams gegen die
    Quell-Laufzeit. Nur Hinweis im Log, bricht den Auftrag nicht ab. Rückgabe True = unauffällig."""
    num, den, target_str = conform
    try:
        out = subprocess.run([tool('ffprobe'), '-v', 'error', '-count_packets', '-select_streams', 'v:0',
                              '-show_entries', 'stream=r_frame_rate,nb_read_packets', '-of', 'json', path],
                             capture_output=True, text=True, creationflags=NO_WINDOW).stdout
        stream = json.loads(out)['streams'][0]
        r_num, r_den = (int(x) for x in stream['r_frame_rate'].split('/'))
        frames = int(stream['nb_read_packets'])
    except Exception:
        log(tr("prep_log_fps_check_impossible"))
        return False
    # Rohes H.264 meldet je nach Stream die Bild- oder die Halbbildrate (PsF, x264-Timing)
    rate_ok = r_num * den in (num * r_den, 2 * num * r_den)
    expected = duration * num / den
    count_ok = duration <= 0 or abs(frames - expected) <= max(3, expected * 0.0005)
    if rate_ok and count_ok:
        log(tr("prep_log_fps_ok", fps=target_str, frames=frames))
        return True
    log(tr("prep_log_fps_suspicious", rate=f"{r_num}/{r_den}", frames=frames, fps=target_str,
           expected=f"{expected:.0f}"))
    return False


def build_2d_job(src, bitrate=20, target_720p=False, psf_25=True, conform_fps=True, out_dir=None):
    """Blu-ray-konformes H.264 (.264) aus einem 2D-Video. bitrate: 25 / 20 / 15 Mbit/s (Mittel).
    psf_25: 25p als 1080i50 PsF statt nativ 1080p25. 29.97/30p wird immer PsF (BD-Spec).
    conform_fps: 30/60 fps (nicht BD-konform) per fps-Filter an 29.97/59.94 anpassen und danach prüfen.
    target_720p muss zur Bildrate passen (forced_720p: 50/60 fps nur 720p, 25/29,97/30 fps nur 1080).
    ValueError bei nicht Blu-ray-tauglichen Quellen (source_problems) oder unpassender Auflösung."""
    problems = source_problems(src, "2d")
    if problems:
        raise ValueError(describe_problems(problems))
    forced = forced_720p(src.fps_str)
    if forced is not None and forced != target_720p:
        raise ValueError(tr("prep_fps_only_in", fps=src.fps_str, res="720p" if forced else "1080"))
    b_val = bitrate if bitrate in BITRATE_2D_MAX else 20
    max_val = BITRATE_2D_MAX[b_val]
    target_w, target_h = (1280, 720) if target_720p else (1920, 1080)
    conform = NON_BD_FPS.get(src.fps_str) if conform_fps else None
    # Bildraten-Anpassung zuerst (weniger Bilder zu skalieren), dann Skalierung
    filters = [f"fps={conform[0]}/{conform[1]}"] if conform else []
    if (src.width, src.height) != (target_w, target_h):
        scale = f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease:force_divisible_by=2"
        if src.height < 720 and src.color_space != "bt709":
            # SD ist BT.601: beim Hochskalieren in BT.709 umrechnen, sonst verschieben sich die Farben leicht
            scale += ":in_color_matrix=bt601:out_color_matrix=bt709"
        filters.append(f"{scale},pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2,setsar=1/1")
    vf = ['-vf', ",".join(filters)] if filters else []

    # Blu-ray-konforme x264-Parameter mit dynamischem VBV-Limit
    x264_opts = (f"bluray-compat=1:open-gop=0:slices=4:keyint={src.gop}:min-keyint=1:"
                 f"vbv-maxrate={max_val}000:vbv-bufsize=30000:nal-hrd=vbr:b-pyramid=strict:sar=1/1:{X264_BT709}")
    notes = []
    if conform:
        notes.append(tr("prep_note_conform", fps=src.fps_str, target=conform[2]))
    fps = src.fps_val
    if not target_720p and (abs(fps - 29.97) < 0.05 or abs(fps - 30.0) < 0.05):
        # NTSC-Raten: immer PsF (kein natives 1080p29.97/30 auf BD-Spec)
        x264_opts += ":fake-interlaced=1:weightp=0:pic-struct=1"
        notes.append(tr("prep_note_psf_60"))
    elif not target_720p and abs(fps - 25.0) < 0.05:
        if psf_25:
            # 1080i50 / 25 PsF: fake-interlaced + weightp=0 (kein weighted P auf BD) + pic-struct=1 (PsF-Signal)
            x264_opts += ":fake-interlaced=1:weightp=0:pic-struct=1"
            notes.append(tr("prep_note_psf_25"))
        else:
            notes.append(tr("prep_note_native_25"))

    work_dir, filename = os.path.split(src.path)
    base_name = os.path.splitext(filename)[0]
    out_arg, out = _output(work_dir, out_dir, f"{base_name}.264")
    cmd = [tool('ffmpeg'), '-y', '-stats', '-i', filename, *vf, '-map', '0:v:0', '-an', '-sn', '-pix_fmt', 'yuv420p',
           '-fps_mode', 'cfr', '-c:v', 'libx264', '-profile:v', 'high', '-level', '4.1',
           '-b:v', f'{b_val}M', '-maxrate', f'{max_val}M', '-bufsize', '30M',
           '-x264-params', x264_opts, *COLOR_BT709, '-f', 'h264', out_arg]
    steps = [Step(tr("prep_step_2d", mbps=b_val), (0.0, 1.0), cmd=cmd)]
    if conform:
        def check(ctx):
            check_fps_conform(out, conform, src.duration, ctx.log)
            return 0
        steps.append(Step(tr("prep_step_fps_check"), (1.0, 1.0), func=check))
    # Ergebnis plus x264-Pass-Statistik ist im 1-Pass-Weg klein; 10 % Reserve auf die mittlere Bitrate
    space = int(src.duration * b_val * 125_000 * 1.1)
    return Job("2d", work_dir, src.duration, steps, outputs=[out], notes=notes, space_needed=space)


# --- Audio ----------------------------------------------------------------------------------------

@dataclass
class AudioTrack:
    index: int                              # Position unter den Tonspuren der Datei (ffmpeg 0:a:N)
    codec: str
    channels: int
    sample_rate: int
    language: str = ""
    offset: float = 0.0                     # Beginn relativ zur Videospur in Sekunden (0 ohne Video)


@dataclass
class AudioSource:
    path: str
    tracks: List[AudioTrack]
    duration: float = 0.0
    has_video: bool = False


# 1:1 übernommen werden nur Formate, die sicher Blu-ray-tauglich sind (48 kHz); alles andere wird umgewandelt
COPY_CODECS = {"ac3": ".ac3", "dts": ".dts"}
COPY_LABEL = "{codec} 1:1 übernehmen (unverändert / unchanged)"
# Ab diesem Versatz zwischen Ton- und Bildbeginn warnen (halbes Bild bei 24 fps)
OFFSET_WARN = 0.02


def probe_audio(path):
    """Tonspuren einer WAV- oder Videodatei. ValueError, wenn die Datei keine Tonspur hat."""
    data = probe(path)
    video = _video_stream(data)
    video_start = _start_time(video) if video else 0.0
    tracks = []
    for s in data.get('streams', []):
        if s.get('codec_type') != 'audio':
            continue
        lang = (s.get('tags') or {}).get('language', '').lower()
        tracks.append(AudioTrack(
            index=len(tracks), codec=s.get('codec_name', ''), channels=int(s.get('channels') or 2),
            sample_rate=int(s.get('sample_rate') or 0),
            language=lang if re.fullmatch(r"[a-z]{2,3}", lang) and lang != "und" else "",
            offset=_start_time(s) - video_start if video else 0.0))
    if not tracks:
        raise ValueError(tr("prep_no_audio_track", file=os.path.basename(path)))
    return AudioSource(path, tracks, _duration(data, {}), has_video=video is not None)


def audio_format_options(channels):
    """Zielformate (Anzeigetexte) passend zur Kanalzahl; der erste ist die Vorauswahl.
    Nicht angeboten: E-AC3 (ffmpeg mischt 7.1 still auf 5.1, kein AC-3-Kern) und TrueHD (experimenteller
    ffmpeg-Encoder, nie auf Playern getestet) – verlustfrei geht über LPCM."""
    if channels == 2:
        return ["AC3 (Stereo, 192 kbps)", "AC3 (Stereo, 320 kbps)", "DTS (Stereo, 768 kbps)",
                "LPCM (Stereo, Uncompressed)"]
    if channels == 6:
        return ["AC3 (5.1 Surround, 640 kbps)", "DTS (5.1 Surround, 1536 kbps)", "LPCM (5.1 Surround, Uncompressed)"]
    if channels == 8:
        return ["LPCM (7.1 Surround, Uncompressed)", "AC3 (Downmix auf 5.1, 640 kbps)",
                "DTS (Downmix auf 5.1, 1536 kbps)"]
    return ["AC3 (Generic, 640 kbps)"]


def audio_track_options(track):
    """Zielformate für eine Tonspur: zuerst 1:1-Übernahme, wenn sie Blu-ray-tauglich ist, dann die Umwandlungen."""
    copy = [COPY_LABEL.format(codec=track.codec.upper())] \
        if track.codec in COPY_CODECS and track.sample_rate == 48000 else []
    return copy + audio_format_options(track.channels)


def build_audio_job(path, selection, duration=0.0, track=None, out_dir=None):
    """Blu-ray-konformes Audio (48 kHz) im gewählten Format (Text aus audio_format_options/audio_track_options).
    track: Tonspur aus probe_audio – nötig bei Videodateien und für die 1:1-Übernahme; die Zieldatei heißt
    dann <Quelle>_ton<N>[_<Sprache>].<Endung>. Ohne track: erste Tonspur, Zieldatei <Quelle>.<Endung>."""
    codec, bitrate, ext, strict = "ac3", "640", ".ac3", []
    copy = "1:1" in selection
    if copy:
        if track is None or track.codec not in COPY_CODECS:
            raise ValueError(tr("prep_copy_only_ac3_dts"))
        codec, bitrate, ext = "copy", None, COPY_CODECS[track.codec]
    elif "LPCM" in selection:
        # LPCM als 24-Bit-WAV: Kanalzahl und Abtastrate stehen im Header (tsMuxeR und OpenBDAuth lesen WAV).
        # Eigener Namenszusatz, sonst wäre bei einer WAV-Quelle das Ziel die Quelle selbst.
        codec, bitrate, ext = "pcm_s24le", None, "_lpcm.wav"
    elif "DTS" in selection:
        codec, ext, strict = "dts", ".dts", ['-strict', '-2']
        bitrate = "1536" if "1536" in selection else "768"
    elif "320" in selection:
        bitrate = "320"
    elif "192" in selection:
        bitrate = "192"

    work_dir, filename = os.path.split(path)
    stem = os.path.splitext(filename)[0]
    notes = []
    if track is not None:
        stem += f"_ton{track.index + 1}" + (f"_{track.language}" if track.language else "")
        if abs(track.offset) >= OFFSET_WARN:
            notes.append(tr("prep_note_offset_later" if track.offset > 0 else "prep_note_offset_earlier",
                            n=track.index + 1, ms=f"{abs(track.offset) * 1000:.0f}"))
    out_arg, out = _output(work_dir, out_dir, stem + ext)
    select = ['-map', f'0:a:{track.index}'] if track is not None else []
    mix = ['-ac', '6'] if "Downmix auf 5.1" in selection else []
    # Blu-ray Spec: 48.000 Hz für alle Streams (1:1 nur, wenn die Spur es schon hat)
    cmd = [tool('ffmpeg'), '-y', '-i', filename, *select, *([] if copy else ['-ar', '48000']), '-c:a', codec,
           *(['-b:a', f'{bitrate}k'] if bitrate else []), *strict, *mix, out_arg]
    if "LPCM" in selection:
        channels = 6 if mix else (track.channels if track else 8)
        space = duration * 48000 * 3 * channels
    else:
        space = duration * int(bitrate or 6000) * 125      # 1:1: bis DTS-HD MA (ca. 6 Mbit/s)
    return Job("audio", work_dir, duration, [Step(tr("prep_step_audio"), (0.0, 1.0), cmd=cmd)],
               outputs=[out], notes=notes, space_needed=int(space * 1.05))


# --- 3D -------------------------------------------------------------------------------------------

def stereo_filter(width, height):
    """ffmpeg-Filter, der eine 3D-Quelle in [left] und [right] teilt, je 1920×1080 ohne Skalierung.
    Nur Full-TAB (1920×2160) und Full-SBS (3840×1080), siehe stereo_layout."""
    layout = stereo_layout(width, height)
    if layout is None:
        raise ValueError(PROBLEM_TEXT["layout_3d"].format(size=f"{width}x{height}"))
    right = "0:1080" if layout == "tab" else "1920:0"
    return f"[0:v]crop=1920:1080:0:0[left];[0:v]crop=1920:1080:{right}[right]"


def x264_3d_args(per_eye_kbps, gop, scenecut, min_keyint):
    return ['-an', '-sn', '-pix_fmt', 'yuv420p', '-fps_mode', 'cfr',
            '-c:v', 'libx264', '-preset', 'slow', '-profile:v', 'high', '-b:v', f'{per_eye_kbps}k',
            '-x264-params', X264_3D_OPTS.format(gop=gop, scenecut=scenecut, min_keyint=min_keyint),
            *COLOR_BT709]


def outputs_3d(src, out_dir=None):
    """Zieldateien eines 3D-Auftrags: <Quelle>_3D.264 (Base View) und <Quelle>_3D.mvc (Dependent View).
    Der Zusatz unterscheidet sie von einer 2D-Fassung derselben Quelle."""
    work_dir, filename = os.path.split(src.path)
    stem = os.path.join(out_dir or work_dir, os.path.splitext(filename)[0] + "_3D")
    return f"{stem}.264", f"{stem}.mvc"


def build_3d_job(src, total_kbps=25000, out_dir=None, adaptive=True):
    """Blu-ray-3D-MVC (.264 + .mvc) aus einem Full-TAB- oder Full-SBS-Video, eigener Weg (Phase 1, docs/mvc/):

    1. adaptive: Szenenwechsel-Analyse – x264-Pass-1 nur über das linke Auge legt die IDR-Positionen fest
       (Schnitte, spätestens nach `gop` Bildern); daraus die Keyframe-Datei.
    2. x264-2-Pass für beide Augen gemeinsam, mit identischen Optionen und genau diesen IDR-Positionen
       (`-/force_key_frames`, ab ffmpeg 7) → identische Bildtypen. Ohne adaptive: feste GOP.
    3. MvcRewriter: rechtes Auge → Dependent View (.mvc)
    4. verify_pair: beide Views Bild für Bild gegenprüfen

    ValueError bei nicht Blu-ray-tauglichen Quellen (source_problems: 3D-Format, Bildrate, HDR, Interlaced).
    """
    problems = source_problems(src, "3d")
    if problems:
        raise ValueError(describe_problems(problems))
    work_dir, filename = os.path.split(src.path)
    out_264, out_mvc = outputs_3d(src, out_dir)
    stem = os.path.splitext(out_264)[0]
    tmp_right = f"{stem}.right.tmp.264"
    pass_l, pass_r, pass_scan = f"{stem}.bd3d_passL", f"{stem}.bd3d_passR", f"{stem}.bd3d_scan"
    kf_file = f"{stem}.bd3d_keyframes.txt"
    per_eye = total_kbps // 2
    gop = src.gop
    filter_str = stereo_filter(src.width, src.height)
    ffmpeg = [tool('ffmpeg'), '-y', '-v', 'warning', '-stats', '-i', filename]
    null_out = ['-f', 'null', os.devnull]
    steps, notes = [], []

    if adaptive:
        steps.append(Step(tr("prep_step_3d_analysis"), (0.0, 0.15),
                          cmd=[*ffmpeg, '-filter_complex', filter_str.split(";")[0], '-map', '[left]',
                               *x264_3d_args(per_eye, gop, 40, 1),
                               '-pass', '1', '-passlogfile', pass_scan, *null_out]))

        def write_keyframes(ctx):
            keyframes = read_x264_keyframes(f"{pass_scan}-0.log")
            if keyframes is None:
                ctx.log(tr("prep_log_analysis_unusable"))
                return 1
            with open(kf_file, "w", encoding="ascii") as f:
                # Halbes Bild früher: ffmpeg erzwingt das erste Bild mit Zeitstempel ≥ Wert
                f.write(",".join(f"{max(0.0, (k - 0.5) / src.fps_val):.6f}" for k in keyframes))
            # Analyse-Statistik wird nicht mehr gebraucht – gleich löschen, spart beim Film einige GB
            for f in glob.glob(glob.escape(pass_scan) + "*"):
                os.remove(f)
            cuts = sum(1 for a, b in zip(keyframes, keyframes[1:]) if b - a != gop)
            ctx.log(tr("prep_log_idr", n=len(keyframes), cuts=cuts))
            return 0

        steps.append(Step(tr("prep_step_idr"), (0.15, 0.15), func=write_keyframes))
        enc_both = x264_3d_args(per_eye, gop, 0, 1) + ['-/force_key_frames', kf_file]
        ranges = ((0.15, 0.45), (0.45, 0.85))
    else:
        notes.append(tr("prep_note_old_ffmpeg"))
        enc_both = x264_3d_args(per_eye, gop, 0, gop)
        ranges = ((0.0, 0.35), (0.35, 0.85))

    for n, rng in zip((1, 2), ranges):
        out_l, out_r = (null_out, null_out) if n == 1 else (['-f', 'h264', out_264], ['-f', 'h264', tmp_right])
        steps.append(Step(tr("prep_step_3d_pass", n=n, mbps=f"{total_kbps / 1000:g}"), rng,
                          cmd=[*ffmpeg, '-filter_complex', filter_str,
                               '-map', '[left]', *enc_both, '-pass', str(n), '-passlogfile', pass_l, *out_l,
                               '-map', '[right]', *enc_both, '-pass', str(n), '-passlogfile', pass_r, *out_r]))

    def rewrite(ctx):
        def on_progress(count, pos, size):
            ctx.progress(pos / size if size else 0.0)
            ctx.log(tr("prep_log_rewritten_progress", n=count, share=f"{pos / size:.0%}"), is_progress=True)

        rw = MvcRewriter()
        n_au = rw.run(tmp_right, out_mvc, progress=on_progress, cancel=ctx.cancelled)
        if n_au is None:
            return CANCELLED
        ctx.log(tr("prep_log_rewritten", n=n_au))
        if rw.dropped:
            ctx.log(tr("prep_log_dropped", items=dict(rw.dropped)))
        return 0

    def verify(ctx):
        base_size = os.path.getsize(out_264)
        total = base_size + os.path.getsize(out_mvc)

        def on_progress(label, pos):
            done = pos if label == "Base View" else base_size + pos
            ctx.progress(done / total if total else 0.0)
            ctx.log(tr("prep_log_checking", label=label, share=f"{done / total:.0%}"), is_progress=True)

        problems, info = verify_pair(out_264, out_mvc, progress=on_progress)
        for p in problems:
            ctx.log(f"[PROBLEM] {p}")
        if problems:
            return 1
        ctx.log(tr("prep_log_verify_ok", n=info["pictures"], base=f"{info['base_bytes'] / 1e9:.2f}",
                   dep=f"{info['dep_bytes'] / 1e9:.2f}"))
        return 0

    steps.append(Step(tr("prep_step_rewrite"), (0.85, 0.95), func=rewrite))
    steps.append(Step(tr("prep_step_verify"), (0.95, 1.0), func=verify))
    # Ergebnis + Zwischendatei rechtes Auge (halbe Ergebnisgröße) + x264-Pass-Logs (ca. 8,5 KB pro Bild und
    # Durchlauf, gemessen bei 1080p), 10 % Reserve
    frames = src.duration * src.fps_val
    space = (src.duration * total_kbps * 125 * 1.5 + frames * 8500 * 3) * 1.1
    return Job("3d", work_dir, src.duration, steps, outputs=[out_264, out_mvc],
               temp=[tmp_right, kf_file], temp_prefixes=[pass_l, pass_r, pass_scan], notes=notes,
               space_needed=int(space))
