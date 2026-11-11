# core/chapter_time.py
"""Hilfsfunktionen für Kapitel-Zeitstempel im Format HH:MM:SS.mmm (wie tsMuxeR --custom-chapters)."""

import re
from typing import List

from modules.mpls.mpls_reader import parse_chapter_time

_TIME_RE = re.compile(r"^\d{1,2}:\d{2}:\d{2}(\.\d{1,3})?$")


def is_valid_chapter_time(text: str) -> bool:
    if not _TIME_RE.match(text.strip()):
        return False
    _h, m, s = text.strip().split(":")
    return int(m) < 60 and float(s) < 60


def format_chapter_time(seconds: float) -> str:
    total_ms = int(round(max(0.0, seconds) * 1000))
    h, rest = divmod(total_ms, 3600 * 1000)
    m, rest = divmod(rest, 60 * 1000)
    s, ms = divmod(rest, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def next_chapter_time(existing: List[str], step_seconds: float = 300.0) -> str:
    """Vorschlag für ein neues Kapitel: 5 Minuten nach dem spätesten bestehenden (sonst 00:00:00.000)."""
    seconds = [parse_chapter_time(t) for t in existing]
    seconds = [s for s in seconds if s is not None]
    return format_chapter_time(max(seconds) + step_seconds) if seconds else "00:00:00.000"
