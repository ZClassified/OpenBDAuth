# modules/igs/palette.py
"""
Farbraum- und Paletten-Management für Blu-ray HDMV Interactive Graphics (IGS)
und Presentation Graphics (PGS) nach BD-ROM Part 3 Spezifikation.

- Farbraum: ITU-R BT.709 (HDTV) YCrCbA (Reihenfolge im Stream: Y, Cr, Cb, T)
- Palette: Max 256 Einträge. Index 0 und Index 255 sind fest als transparent (T=0) reserviert.
  Manche Player (Panasonic DMP-BDT111) löschen die Grafikebene mit Eintrag 255; eine Farbe dort
  legte sich als Schleier über das ganze Menü außerhalb der Buttons.
"""

from typing import List, Tuple, Dict
from PIL import Image

def rgba_to_ycrcba(r: int, g: int, b: int, a: int) -> Tuple[int, int, int, int]:
    """
    Konvertiert ein RGBA-Pixel (je 0..255) in Blu-ray BT.709 YCrCbA.
    Rückgabe: (Y, Cr, Cb, T)
    - Y:  16..235
    - Cr: 16..240
    - Cb: 16..240
    - T:  0..255 (Alpha: 0 = transparent, 255 = voll deckend)
    """
    if a == 0:
        # Vollständig transparent: neutrales Schwarz mit T=0
        return (16, 128, 128, 0)

    # Normiert auf 0.0 .. 1.0
    rn, gn, bn = r / 255.0, g / 255.0, b / 255.0

    # ITU-R BT.709 Koeffizienten
    y_norm = 0.2126 * rn + 0.7152 * gn + 0.0722 * bn
    cb_norm = (bn - y_norm) / 1.8556
    cr_norm = (rn - y_norm) / 1.5748

    # Quantisierung auf Blu-ray Studio-Range
    y = int(round(16.0 + 219.0 * y_norm))
    cb = int(round(128.0 + 224.0 * cb_norm))
    cr = int(round(128.0 + 224.0 * cr_norm))
    t = max(0, min(255, int(a)))

    # Wertebereiche absichern
    y = max(16, min(235, y))
    cb = max(16, min(240, cb))
    cr = max(16, min(240, cr))

    return (y, cr, cb, t)

class Palette:
    """Verwaltet eine 256-Farben Blu-ray Palette (Y, Cr, Cb, T)."""

    def __init__(self, palette_id: int = 0, palette_version: int = 0):
        self.palette_id = palette_id
        self.palette_version = palette_version
        # Index 0 ist standardmäßig transparent
        self.entries: List[Tuple[int, int, int, int]] = [(16, 128, 128, 0)] * 256

    def set_entry(self, index: int, y: int, cr: int, cb: int, t: int):
        if not (0 <= index < 256):
            raise ValueError(f"Paletten-Index {index} liegt außerhalb von 0..255.")
        self.entries[index] = (y, cr, cb, t)

    def to_pds_payload(self) -> bytes:
        """
        Erzeugt den Payload für ein PDS (Palette Definition Segment):
        - palette_id: 1 Byte
        - palette_version: 1 Byte
        - Einträge: pro Eintrag 5 Bytes (entry_id, Y, Cr, Cb, T)
        """
        data = bytearray()
        data.append(self.palette_id & 0xFF)
        data.append(self.palette_version & 0xFF)

        for idx, (y, cr, cb, t) in enumerate(self.entries):
            data.append(idx & 0xFF)
            data.append(y & 0xFF)
            data.append(cr & 0xFF)
            data.append(cb & 0xFF)
            data.append(t & 0xFF)

        return bytes(data)

TRANSPARENT_INDEX = 0
RESERVED_CLEAR_INDEX = 255  # bleibt transparent, wird nie für Farben vergeben
MAX_COLOR_INDEX = 254


class PaletteBuilder:
    """
    Quantisiert ein oder mehrere RGBA-Bilder in eine gemeinsame 256-Farben Palette,
    wobei Index 0 und Index 255 transparent bleiben (Farben: 1..254).
    """

    def __init__(self, palette_id: int = 0):
        self.palette = Palette(palette_id=palette_id)
        # Mapping von (R, G, B, A) -> Paletten-Index (1..254)
        self.color_map: Dict[Tuple[int, int, int, int], int] = {}
        # Nächster freier Index
        self.next_index = 1

    def get_color_index(self, r: int, g: int, b: int, a: int) -> int:
        """Gibt den Paletten-Index für eine RGBA-Farbe zurück."""
        if a < 16:
            # Transparenzschwelle: fast transparent gilt als transparent (Index 0)
            return 0

        # Leicht quantisieren für Farbkompression (z. B. auf 5-Bit / Schrittweite 8)
        rgba_key = (r, g, b, a)
        if rgba_key in self.color_map:
            return self.color_map[rgba_key]

        if self.next_index <= MAX_COLOR_INDEX:
            idx = self.next_index
            self.next_index += 1
            y, cr, cb, t = rgba_to_ycrcba(r, g, b, a)
            self.palette.set_entry(idx, y, cr, cb, t)
            self.color_map[rgba_key] = idx
            return idx
        else:
            # Notfall-Fallback bei > 254 Farben: Suche den nächstliegenden existierenden Eintrag
            return self._find_closest_index(r, g, b, a)

    def _find_closest_index(self, r: int, g: int, b: int, a: int) -> int:
        target_y, target_cr, target_cb, target_t = rgba_to_ycrcba(r, g, b, a)
        best_idx = 1
        min_dist = float('inf')

        for idx in range(1, self.next_index):
            y, cr, cb, t = self.palette.entries[idx]
            dist = (target_y - y) ** 2 + (target_cr - cr) ** 2 + (target_cb - cb) ** 2 + (target_t - t) ** 2
            if dist < min_dist:
                min_dist = dist
                best_idx = idx

        self.color_map[(r, g, b, a)] = best_idx
        return best_idx

    def quantize_image(self, image: Image.Image) -> Tuple[List[int], int, int]:
        """
        Wandelt ein Pillow RGBA-Image in eine Liste von 8-bit Paletten-Indizes
        sowie (width, height) um.
        """
        img = image.convert("RGBA")
        width, height = img.size
        raw_bytes = img.tobytes("raw", "RGBA")
        pixels = [(raw_bytes[i], raw_bytes[i+1], raw_bytes[i+2], raw_bytes[i+3]) for i in range(0, len(raw_bytes), 4)]
        indexed_pixels = [self.get_color_index(r, g, b, a) for (r, g, b, a) in pixels]
        return indexed_pixels, width, height
