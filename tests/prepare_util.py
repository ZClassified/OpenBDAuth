"""Gemeinsame Hilfen für die Vorbereiten-Tests (aus BD3DEnc): ffmpeg-Verfügbarkeit und synthetisches
Testmaterial. Wie das Programm nutzen die Tests das mitgelieferte ffmpeg (tools/<plattform>/), sonst den PATH.
Module, die jobs.run_job mit echtem ffmpeg aufrufen, übernehmen setUpModule/tearDownModule von hier."""

import subprocess
import unittest

from modules.external_tools import find_tool, FFMPEG, FFPROBE
from modules.prepare import jobs, use_bundled_tools

FFMPEG_PATH = find_tool(FFMPEG) or "ffmpeg"
FFPROBE_PATH = find_tool(FFPROBE) or "ffprobe"


def _has_libx264():
    try:
        out = subprocess.run([FFMPEG_PATH, '-hide_banner', '-encoders'], capture_output=True, text=True,
                             creationflags=jobs.NO_WINDOW).stdout
    except OSError:
        return False
    return "libx264" in out


HAS_FFMPEG = _has_libx264()
needs_ffmpeg = unittest.skipUnless(HAS_FFMPEG, "ffmpeg mit libx264 nicht gefunden")


def setUpModule():
    use_bundled_tools()


def tearDownModule():
    jobs.configure_tools(None)     # die Befehlstests (test_prepare_jobs) erwarten nacktes "ffmpeg"


def ffmpeg(*args):
    subprocess.run([FFMPEG_PATH, '-v', 'error', '-y', *args], check=True, creationflags=jobs.NO_WINDOW)


# 3 s (72 Bilder bei 23,976): harte Schnitte und kurze chaotische Einschübe („life“, fester Startwert).
# Die Einschübe lösen bei x264 Szenenwechsel mitten in einer B-Bild-Gruppe aus – genau dort weichen die
# Bildtypen ab, wenn nur ein Auge die IDR-Positionen erzwungen bekommt (Fehler aus Testlauf 2).
TAB_SEGMENTS = [("testsrc2", 0.9), ("life", 0.3), ("smptehdbars", 0.5), ("life", 0.2), ("testsrc2", 1.1)]


def make_tab_source(path, segments=TAB_SEGMENTS, shift=16, rate="24000/1001", stack="vstack"):
    """Full-TAB (1920×2160): oben das linke Auge, unten dasselbe Bild um `shift` Pixel verschoben (simulierte
    Disparität). Mit stack="hstack" Full-SBS (3840×1080, links das linke Auge). Verlustfrei (FFV1), damit nur
    x264 Bitrate kostet."""
    parts, labels = [], []
    for i, (name, seconds) in enumerate(segments):
        extra = ":seed=1:mold=10:ratio=0.3" if name == "life" else ""
        parts.append(f"{name}=s=1920x1080:r={rate}{extra},trim=duration={seconds},setpts=PTS-STARTPTS,"
                     f"format=yuv420p[s{i}]")
        labels.append(f"[s{i}]")
    graph = (";".join(parts) + ";" + "".join(labels) + f"concat=n={len(segments)}:v=1,split[l][r0];"
             f"[r0]crop=1920-{shift}:1080:{shift}:0,pad=1920:1080:0:0[r];[l][r]{stack}[v]")
    ffmpeg('-f', 'lavfi', '-i', 'nullsrc', '-filter_complex', graph, '-map', '[v]', '-c:v', 'ffv1', path)


def make_h264(path, seconds=1.0, keyint=12, size="320x240", rate="24000/1001", pattern="testsrc2"):
    """Kleiner H.264-Elementary-Stream wie ein Auge aus dem 3D-Weg (CABAC, AUD, NAL-HRD, 3 B-Bilder)."""
    opts = (f"keyint={keyint}:min-keyint={keyint}:scenecut=0:open-gop=0:bframes=3:b-adapt=0:b-pyramid=none:"
            f"ref=3:slices=2:weightp=0:nal-hrd=vbr:vbv-maxrate=4000:vbv-bufsize=4000:aud=1:pic-struct=1")
    ffmpeg('-f', 'lavfi', '-i', f"{pattern}=s={size}:r={rate}:d={seconds}", '-pix_fmt', 'yuv420p',
           '-c:v', 'libx264', '-preset', 'veryfast', '-b:v', '1000k', '-x264-params', opts, '-f', 'h264', path)
