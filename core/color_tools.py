# core/color_tools.py
"""
Farben für den Button-Stil (v1.14.4), Qt-frei: Hex-Eingabe prüfen, Hauptfarben eines Hintergrundbilds,
Farbe an einer Stelle des Bilds (Pipette, aus dem Original in voller Auflösung) und die im Projekt schon
benutzten Farben.
"""

import os
import re
from collections import Counter
from functools import lru_cache
from typing import List, Optional, Tuple

from core.disc_model import DiscProject

_HEX = re.compile(r"^#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")
STYLE_COLOR_FIELDS = ("color_normal", "color_selected", "color_activated")


def parse_hex(text: str) -> Optional[str]:
    """„c8a060“, „#C8A060“ oder „#ca6“ → „#C8A060“ bzw. „#CCAA66“; sonst None."""
    match = _HEX.match((text or "").strip())
    if not match:
        return None
    digits = match.group(1)
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    return "#" + digits.upper()


def _hex(rgb: Tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb[:3])


def dominant_colors(image_path: Optional[str], count: int = 8) -> List[str]:
    """Die count häufigsten Farben eines Bilds (Median-Cut auf einer verkleinerten Kopie), häufigste zuerst."""
    if not image_path or not os.path.exists(image_path):
        return []
    try:
        stat = os.stat(image_path)
    except OSError:
        return []
    return list(_dominant(os.path.abspath(image_path), stat.st_size, stat.st_mtime, count))


@lru_cache(maxsize=32)
def _dominant(path: str, _size: int, _mtime: float, count: int) -> Tuple[str, ...]:
    """Median-Cut gruppiert ähnliche Farben; je Gruppe zählt die häufigste *echte* Pixelfarbe (kein Mittelwert),
    damit man genau die Farbe aus dem eigenen Bild bekommt. Verkleinert ohne Glätten (keine Mischfarben)."""
    from PIL import Image
    try:
        with Image.open(path) as img:
            small = img.convert("RGB").resize((240, 135), Image.NEAREST)
            groups = small.quantize(colors=count, method=Image.Quantize.MEDIANCUT)
            pixels = _pixels(small)
            indices = _pixels(groups)
    except (OSError, ValueError):
        return ()
    by_group = {}
    for index, rgb in zip(indices, pixels):
        by_group.setdefault(index, Counter())[rgb] += 1
    ranked = sorted(by_group.values(), key=lambda c: sum(c.values()), reverse=True)
    colors = []
    for counter in ranked:
        color = _hex(counter.most_common(1)[0][0])
        if color not in colors:
            colors.append(color)
    return tuple(colors[:count])


def _pixels(img) -> list:
    """Pixel als Liste (get_flattened_data ab Pillow 12, getdata davor; getdata fällt mit Pillow 14 weg)."""
    flat = getattr(img, "get_flattened_data", None)
    return list(flat() if flat else img.getdata())


def color_at(image_path: Optional[str], x: float, y: float, canvas=(1920, 1080)) -> Optional[str]:
    """Farbe des Bilds an der Stelle (x, y) im 1920×1080 Raum (das Bild wird wie im Viewer aufs Bild gestreckt)."""
    if not image_path or not os.path.exists(image_path):
        return None
    from PIL import Image
    try:
        with Image.open(image_path) as img:
            rgb = img.convert("RGB")
            px = min(rgb.width - 1, max(0, int(x * rgb.width / canvas[0])))
            py = min(rgb.height - 1, max(0, int(y * rgb.height / canvas[1])))
            return _hex(rgb.getpixel((px, py)))
    except (OSError, ValueError):
        return None


def project_colors(project: DiscProject, limit: int = 8) -> List[str]:
    """Farben, die Button-Stile im Projekt schon benutzen – eigene vor den Voreinstellungen, jeweils häufigste
    zuerst (für „Im Projekt benutzt“)."""
    from core.disc_model import ButtonStyle
    defaults = {getattr(ButtonStyle(), f).upper() for f in STYLE_COLOR_FIELDS}
    counts = Counter(getattr(m.button_style, f).upper() for m in project.menus for f in STYLE_COLOR_FIELDS)
    ranked = sorted(counts.items(), key=lambda item: (item[0] in defaults, -item[1]))
    return [c for c, _n in ranked[:limit]]
