# tools/fetch_tools.py
"""
Holt die Werkzeuge, die OpenBDAuth mitliefert (v1.19.2), in fest hinterlegten Versionen nach tools/<plattform>/:
ffmpeg und ffprobe (Windows: gyan.dev „essentials“, Linux: BtbN, macOS: Martin Riedl, alle GPL v3 mit x264) und
tsMuxeR (Apache-2.0),
dazu ihre Lizenztexte nach tools/<plattform>/licenses/. Jede Datei wird gegen ihre SHA-256-Prüfsumme geprüft;
heruntergeladene Archive bleiben in build/downloads/ liegen und werden beim nächsten Mal wiederverwendet.

Aufruf:  python tools/fetch_tools.py [windows|macos|linux]   (ohne Angabe: dieses System)
Nur Python-Standardbibliothek, damit es auch im Build auf GitHub ohne Zusatzpakete läuft.
"""

import hashlib
import os
import shutil
import sys
import tarfile
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from modules.external_tools import platform_dir   # noqa: E402

DOWNLOADS = os.path.join(ROOT, "build", "downloads")

# Je Plattform: Archive bzw. Dateien mit Quelle, Prüfsumme und was daraus wohin kommt ({Name im Archiv: Ziel}).
# Ziele ohne Ordner landen in tools/<plattform>/, Ziele unter licenses/ dort.
TSMUXER_LICENSE = {
    "file": "tsMuxer-2.7.0-LICENSE.txt",
    "url": "https://raw.githubusercontent.com/justdan96/tsMuxer/2.7.0/LICENSE",
    "sha256": "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4",
    "copy": "licenses/tsMuxeR-LICENSE.txt",
}
# Linux-ffmpeg: Monatsbuild von BtbN, statisch gelinkt; die Monatsbuilds bleiben dort dauerhaft liegen,
# die täglichen nicht
FFMPEG_LINUX = "ffmpeg-n9.0.2-17-g2a571b6068-linux64-gpl-9.0"

MANIFEST = {
    "windows": [
        {
            "file": "ffmpeg-9.0.2-essentials_build.zip",
            "url": "https://github.com/GyanD/codexffmpeg/releases/download/9.0.2/ffmpeg-9.0.2-essentials_build.zip",
            "sha256": "60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba",
            "extract": {
                "ffmpeg-9.0.2-essentials_build/bin/ffmpeg.exe": "ffmpeg.exe",
                "ffmpeg-9.0.2-essentials_build/bin/ffprobe.exe": "ffprobe.exe",
                "ffmpeg-9.0.2-essentials_build/LICENSE": "licenses/ffmpeg-LICENSE.txt",
                "ffmpeg-9.0.2-essentials_build/README.txt": "licenses/ffmpeg-README.txt",
            },
        },
        {
            "file": "tsMuxer-2.7.0-win64.zip",
            "url": "https://github.com/justdan96/tsMuxer/releases/download/2.7.0/tsMuxer-2.7.0-win64.zip",
            "sha256": "e3cf117d2c6f01332188123641c63fe38ab9731ae7aa23645f6f9a261a7a301c",
            "extract": {"tsMuxeR.exe": "tsMuxeR.exe"},
        },
        TSMUXER_LICENSE,
    ],
    "linux": [
        {
            "file": f"{FFMPEG_LINUX}.tar.xz",
            "url": f"https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-09-30-13-08/"
                   f"{FFMPEG_LINUX}.tar.xz",
            "sha256": "68ee646831adaae2495618346f3bba94ff207ff83bbd34d643e7004730d66269",
            "extract": {
                f"{FFMPEG_LINUX}/bin/ffmpeg": "ffmpeg",
                f"{FFMPEG_LINUX}/bin/ffprobe": "ffprobe",
                f"{FFMPEG_LINUX}/LICENSE.txt": "licenses/ffmpeg-LICENSE.txt",
            },
        },
        {
            "file": "tsMuxer-2.7.0-linux.zip",
            "url": "https://github.com/justdan96/tsMuxer/releases/download/2.7.0/tsMuxer-2.7.0-linux.zip",
            "sha256": "ceaaa181ab70e201685b1e45260d337d1cbdb0aba1408d4fbc47e232a7e4c987",
            "extract": {"tsMuxeR": "tsMuxeR"},
        },
        TSMUXER_LICENSE,
    ],
    # macOS: nur Apple Silicon (arm64) – tsMuxeR 2.7.0 gibt es für Mac nur so. ffmpeg von Martin Riedl
    # (Release-Build, statisch, GPL v3 mit x264); Lizenztext aus dem FFmpeg-Quellcode derselben Version
    "macos": [
        {
            "file": "ffmpeg-9.0.2-macos-arm64.zip",
            "url": "https://ffmpeg.martin-riedl.de/download/macos/arm64/1789931890_9.0.2/ffmpeg.zip",
            "sha256": "c8ed4c4e6978a03c485edbfe4e0a5dc2380f8a30bba5150531b31b094492d924",
            "extract": {"ffmpeg": "ffmpeg"},
        },
        {
            "file": "ffprobe-9.0.2-macos-arm64.zip",
            "url": "https://ffmpeg.martin-riedl.de/download/macos/arm64/1789931890_9.0.2/ffprobe.zip",
            "sha256": "fcbe839537485eaee7a7a8bc5cbc0f90d53617e80943e8a5b2e31cb851197ea6",
            "extract": {"ffprobe": "ffprobe"},
        },
        {
            "file": "ffmpeg-9.0.2-LICENSE.md",
            "url": "https://raw.githubusercontent.com/FFmpeg/FFmpeg/n9.0.2/LICENSE.md",
            "sha256": "2e1d16c72fd74e12063776371da757322f8b77589386532f4fd8634bde7de1af",
            "copy": "licenses/ffmpeg-LICENSE.md",
        },
        {
            "file": "tsMuxer-2.7.0-mac.zip",
            "url": "https://github.com/justdan96/tsMuxer/releases/download/2.7.0/tsMuxer-2.7.0-mac.zip",
            "sha256": "bf90b608321f491b955fd9432000a8370c048e9c306e3a5833dfd75e5fa530e1",
            "extract": {"tsMuxeR": "tsMuxeR"},
        },
        TSMUXER_LICENSE,
    ],
}


def open_archive(archive: str):
    """ZIP- oder TAR-Archiv (Linux-ffmpeg kommt als .tar.xz) öffnen; liefert (Archiv, Funktion Name -> Datei)."""
    if archive.endswith(".zip"):
        z = zipfile.ZipFile(archive)
        return z, z.open
    t = tarfile.open(archive)
    return t, t.extractfile


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def download(entry: dict) -> str:
    os.makedirs(DOWNLOADS, exist_ok=True)
    path = os.path.join(DOWNLOADS, entry["file"])
    if os.path.exists(path) and sha256(path) == entry["sha256"]:
        print(f"  vorhanden: {entry['file']}")
        return path
    print(f"  lade: {entry['url']}")
    tmp = path + ".part"
    # Eigener Name statt „Python-urllib“: ffmpeg.martin-riedl.de lehnt den mit 403 ab
    request = urllib.request.Request(entry["url"], headers={"User-Agent": "OpenBDAuth-build"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=60) as response, open(tmp, "wb") as out:
                shutil.copyfileobj(response, out, 1 << 20)
            break
        except OSError as ex:
            if attempt == 2:
                raise
            print(f"  erneuter Versuch ({ex})")
    actual = sha256(tmp)
    if actual != entry["sha256"]:
        os.remove(tmp)
        raise SystemExit(f"Prüfsumme falsch für {entry['file']}: {actual}")
    os.replace(tmp, path)
    return path


def install(platform: str) -> str:
    entries = MANIFEST.get(platform)
    if not entries:
        raise SystemExit(f"Für {platform} sind noch keine Werkzeuge hinterlegt.")
    target = os.path.join(ROOT, "tools", platform)
    os.makedirs(os.path.join(target, "licenses"), exist_ok=True)
    for entry in entries:
        archive = download(entry)
        if "copy" in entry:
            shutil.copyfile(archive, os.path.join(target, entry["copy"]))
            continue
        packed, open_member = open_archive(archive)
        with packed:
            for member, dest in entry["extract"].items():
                out = os.path.join(target, dest)
                with open_member(member) as src, open(out, "wb") as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
                if not dest.startswith("licenses/"):
                    os.chmod(out, 0o755)       # ausführbar (macOS, Linux)
    print(f"Werkzeuge in {target}")
    return target


if __name__ == "__main__":
    install(sys.argv[1] if len(sys.argv) > 1 else platform_dir())
