# gui/studio/export_activity.py
"""
Lebenszeichen beim Export (v1.17.6): Wie viel hat der laufende Export schon geschrieben?

Gemessen wird nur von außen über Dateigrößen – die Export-Pipeline (modules/disc_export.py)
bleibt unverändert. Erfasst werden der Zielordner (BDMV, CERTIFICATE, ISO, job.meta) und die
temporären Ordner, in denen die Pipeline Extra-Titel muxt (erkennbar an title_N.meta).
Am Ende zählt nur das Ergebnis (v1.18.3): die neue ISO bzw. der BDMV-Ordner, nicht alles, was
unterwegs geschrieben und wieder gelöscht wurde.
"""

import fnmatch
import os
import tempfile
import time
from typing import Dict, Iterator, Optional, Set, Tuple

DEST_SUBDIRS = ("BDMV", "CERTIFICATE")
TEMP_MARKER = "title_*.meta"
CLOCK_SLACK = 2.0  # Sekunden Spielraum für grobe Zeitstempel des Dateisystems


class WriteMeter:
    def __init__(self, dest: str, temp_root: Optional[str] = None, start: Optional[float] = None):
        self.dest = dest
        self.temp_root = temp_root or tempfile.gettempdir()
        self.start = (time.time() if start is None else start) - CLOCK_SLACK
        self._sizes: Dict[str, int] = {}   # Pfad → größte gesehene Größe; gelöschte Dateien zählen weiter
        self._temp_dirs: Set[str] = set()

    def measure(self) -> int:
        """Bytes, die seit dem Start geschrieben wurden (steigt nur, auch wenn aufgeräumt wird)."""
        for path in self._files():
            try:
                st = os.stat(path)
            except OSError:
                continue
            if st.st_mtime >= self.start and st.st_size > self._sizes.get(path, 0):
                self._sizes[path] = st.st_size
        return sum(self._sizes.values())

    def result(self) -> Tuple[str, int]:
        """Ergebnis des Exports: ("iso", Größe der neuen ISO) oder ("folder", Größe von BDMV und CERTIFICATE)."""
        isos = []
        for path in _top_files(self.dest):
            try:
                st = os.stat(path)
            except OSError:
                continue
            if path.lower().endswith(".iso") and st.st_mtime >= self.start:
                isos.append(st.st_size)
        if isos:
            return "iso", max(isos)
        total = 0
        for sub in DEST_SUBDIRS:
            for path in _walk(os.path.join(self.dest, sub)):
                try:
                    total += os.path.getsize(path)
                except OSError:
                    pass
        return "folder", total

    def _files(self) -> Iterator[str]:
        yield from _top_files(self.dest)
        for sub in DEST_SUBDIRS:
            yield from _walk(os.path.join(self.dest, sub))
        self._find_temp_dirs()
        for folder in list(self._temp_dirs):
            yield from _walk(folder)

    def _find_temp_dirs(self):
        try:
            entries = list(os.scandir(self.temp_root))
        except OSError:
            return
        for entry in entries:
            if entry.path in self._temp_dirs:
                continue
            try:
                if not entry.is_dir() or entry.stat().st_mtime < self.start:
                    continue
                names = os.listdir(entry.path)
            except OSError:
                continue
            if any(fnmatch.fnmatch(n, TEMP_MARKER) for n in names):
                self._temp_dirs.add(entry.path)


def _top_files(folder: str) -> Iterator[str]:
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return
    for entry in entries:
        if entry.is_file():
            yield entry.path


def _walk(folder: str) -> Iterator[str]:
    for root, _dirs, files in os.walk(folder):
        for name in files:
            yield os.path.join(root, name)


def format_clock(seconds: float) -> str:
    """134 → '2:14', 3723 → '1:02:03'."""
    s = int(seconds)
    h, rest = divmod(s, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def format_bytes(n: int, lang: str = "de") -> str:
    """Größe für die Oberfläche, dezimal (1 GB = 10⁹ Byte) wie BD-25/BD-50 und der Finder (v1.30.4; vorher binär,
    dieselbe ISO hieß im Export 7,4 GB und unter Brennen 7,9 GB). Überall dieselbe Funktion."""
    text = f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"
    return text.replace(".", ",") if lang == "de" else text
