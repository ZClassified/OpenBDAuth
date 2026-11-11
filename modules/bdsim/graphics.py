# modules/bdsim/graphics.py
"""
Bilder für den Disc-Simulator:
- Button-Grafiken aus dem IG-Menüstrom (RLE + Palette, BT.709 YCrCb -> RGBA)
- Standbilder aus Menü- und Film-Clips per ffmpeg (zwischengespeichert)
"""

import hashlib
import os
import subprocess
import tempfile
from typing import Dict, List, Optional, Tuple

from modules.bdsim.disc import Composition, Disc, Playlist, NO_BUTTON, TICKS_PER_SECOND
from modules.igs.rle import decode_rle
from modules.external_tools import find_tool, FFMPEG

TRANSPARENT = (0, 0, 0, 0)


def ycrcb_to_rgba(y: int, cr: int, cb: int, t: int) -> Tuple[int, int, int, int]:
    """BT.709, Studio-Bereich (Y 16..235) -> RGBA 0..255."""
    yy = 1.164 * (y - 16)
    r = yy + 1.793 * (cr - 128)
    g = yy - 0.213 * (cb - 128) - 0.533 * (cr - 128)
    b = yy + 2.112 * (cb - 128)
    clamp = lambda v: max(0, min(255, int(round(v))))
    return clamp(r), clamp(g), clamp(b), t


def palette_rgba(comp: Composition, palette_id: int) -> List[Tuple[int, int, int, int]]:
    table = [TRANSPARENT] * 256
    for entry_id, y, cr, cb, t in comp.palettes.get(palette_id, []):
        table[entry_id] = ycrcb_to_rgba(y, cr, cb, t)
    return table


class ButtonImages:
    """Decodiert Button-Grafiken einer Composition als RGBA-Bytes und merkt sie sich."""

    def __init__(self, comp: Composition):
        self.comp = comp
        self._palettes: Dict[int, List[Tuple[int, int, int, int]]] = {}
        self._cache: Dict[Tuple[int, int], Optional[Tuple[int, int, bytes]]] = {}

    def rgba(self, object_id: int, palette_id: int) -> Optional[Tuple[int, int, bytes]]:
        """Gibt (Breite, Höhe, RGBA-Bytes) zurück oder None, wenn die Grafik fehlt oder defekt ist."""
        key = (object_id, palette_id)
        if key in self._cache:
            return self._cache[key]
        result = None
        obj = self.comp.objects.get(object_id)
        if obj is not None and object_id != NO_BUTTON:
            if palette_id not in self._palettes:
                self._palettes[palette_id] = palette_rgba(self.comp, palette_id)
            table = self._palettes[palette_id]
            try:
                pixels = decode_rle(obj.rle, obj.width, obj.height)
                data = bytearray(len(pixels) * 4)
                for i, idx in enumerate(pixels):
                    data[4 * i:4 * i + 4] = bytes(table[idx])
                result = (obj.width, obj.height, bytes(data))
            except (ValueError, IndexError):
                result = None
        self._cache[key] = result
        return result


# ─────────────────────────────── Standbilder ───────────────────────────────

def clip_position(disc: Disc, playlist: Playlist, mark: Optional[int]) -> Tuple[Optional[str], float]:
    """Clip-Datei und Sekunde im Clip für den Beginn einer Playlist oder einer Marke."""
    if not playlist.items:
        return None, 0.0
    item_index, offset = 0, 0
    if mark is not None and 0 <= mark < len(playlist.marks):
        m = playlist.marks[mark]
        if m.item_ref < len(playlist.items):
            item_index = m.item_ref
            offset = max(0, m.time - playlist.items[item_index].in_time)
    item = playlist.items[item_index]
    path = os.path.join(disc.bdmv_dir, "STREAM", f"{item.clip}.m2ts")
    return (path if os.path.exists(path) else None), offset / TICKS_PER_SECOND


def extract_frame(m2ts_path: str, seconds: float, cache_dir: Optional[str] = None,
                  ffmpeg: Optional[str] = None) -> Optional[str]:
    """Holt ein Standbild (PNG, 960×540) per ffmpeg; Ergebnis wird zwischengespeichert. None bei Fehlern."""
    try:
        stat = os.stat(m2ts_path)
    except OSError:
        return None
    cache_dir = cache_dir or os.path.join(tempfile.gettempdir(), "openbdauth_sim")
    os.makedirs(cache_dir, exist_ok=True)
    key = hashlib.sha1(f"{os.path.abspath(m2ts_path)}|{stat.st_size}|{stat.st_mtime}|{seconds:.3f}".encode()).hexdigest()
    out = os.path.join(cache_dir, f"{key}.png")
    if os.path.exists(out):
        return out
    ffmpeg = ffmpeg or find_tool(FFMPEG)
    if ffmpeg is None:
        return None
    cmd = [ffmpeg, "-loglevel", "error", "-y", "-ss", f"{max(0.0, seconds):.3f}", "-i", m2ts_path,
           "-frames:v", "1", "-vf", "scale=960:540", out]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20, creationflags=flags)
    except (OSError, subprocess.SubprocessError):
        return None
    return out if os.path.exists(out) and os.path.getsize(out) > 0 else None
