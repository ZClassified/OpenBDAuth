# modules/mpls/mpls_reader.py
"""
Minimaler MPLS-Leser (BD-ROM Part 3, PlayList File) für OpenBDAuth.

Liest die PlayListMarks (Kapitelmarken) einer von tsMuxeR erzeugten Film-Playlist,
damit Kapitel-Buttons im Menü exakt auf die tatsächlich geschriebenen Marken zeigen.
"""

import struct
from typing import List, Optional

TICKS_PER_SECOND = 45000  # MPLS-Zeitstempel laufen mit 45 kHz
MARK_TYPE_ENTRY = 1       # Entry Mark (Kapitel); 2 = Link Point


def read_mpls_marks(mpls_path: str) -> Optional[List[dict]]:
    """
    Gibt alle PlayListMarks in Dateireihenfolge zurück:
    [{"index": int, "type": int, "time_sec": float}, ...]
    time_sec ist relativ zum Beginn der PlayList (Summe der vorherigen PlayItems + Offset im PlayItem).
    Gibt None zurück, falls die Datei fehlt oder nicht lesbar ist.
    """
    try:
        with open(mpls_path, "rb") as f:
            data = f.read()
    except OSError:
        return None

    if len(data) < 20 or data[0:4] != b"MPLS":
        return None

    try:
        playlist_start, mark_start = struct.unpack(">II", data[8:16])

        # PlayList(): length(4) + reserved(2) + num_play_items(2) + num_sub_paths(2)
        num_items = struct.unpack(">H", data[playlist_start + 6:playlist_start + 8])[0]
        pos = playlist_start + 10
        item_in_times = []
        item_offsets = []   # Startzeit jedes PlayItems innerhalb der PlayList (45 kHz)
        acc = 0
        for _ in range(num_items):
            item_len = struct.unpack(">H", data[pos:pos + 2])[0]
            body = pos + 2
            # clip_name(5) + codec(4) + flags(2) + ref_to_STC_id(1) + IN_time(4) + OUT_time(4)
            in_time, out_time = struct.unpack(">II", data[body + 12:body + 20])
            item_in_times.append(in_time)
            item_offsets.append(acc)
            acc += max(0, out_time - in_time)
            pos = body + item_len

        # PlayListMark(): length(4) + num_marks(2) + marks à 14 Bytes
        num_marks = struct.unpack(">H", data[mark_start + 4:mark_start + 6])[0]
        marks = []
        mpos = mark_start + 6
        for idx in range(num_marks):
            mark_type = data[mpos + 1]
            item_ref = struct.unpack(">H", data[mpos + 2:mpos + 4])[0]
            stamp = struct.unpack(">I", data[mpos + 4:mpos + 8])[0]
            if item_ref < len(item_in_times):
                rel = item_offsets[item_ref] + (stamp - item_in_times[item_ref])
            else:
                rel = stamp
            marks.append({"index": idx, "type": mark_type, "time_sec": rel / TICKS_PER_SECOND})
            mpos += 14
        return marks
    except (struct.error, IndexError):
        return None


def parse_chapter_time(value: str) -> Optional[float]:
    """Wandelt 'HH:MM:SS.mmm' (oder 'MM:SS', 'SS.mmm') in Sekunden um."""
    try:
        parts = [p.strip() for p in str(value).strip().split(":")]
        seconds = 0.0
        for p in parts:
            seconds = seconds * 60 + float(p)
        return seconds
    except ValueError:
        return None


def find_mark_for_time(marks: List[dict], time_sec: float, tolerance_sec: float = 1.0) -> Optional[int]:
    """
    Sucht die Entry Mark, die am nächsten an time_sec liegt (innerhalb der Toleranz),
    und gibt ihren PlayListMark-Index (0-basiert, wie von PlayPLatPM erwartet) zurück.
    """
    best = None
    best_diff = None
    for m in marks:
        if m["type"] != MARK_TYPE_ENTRY:
            continue
        diff = abs(m["time_sec"] - time_sec)
        if diff <= tolerance_sec and (best_diff is None or diff < best_diff):
            best, best_diff = m["index"], diff
    return best
