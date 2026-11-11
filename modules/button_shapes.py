# modules/button_shapes.py
"""
Form-Buttons für Menüs (Linie, Kreis, Dreieck), wie man sie aus DVD Studio Pro kennt:
Die Beschriftung steht im Hintergrundbild, der Button ist nur eine Form, die beim Auswählen
aufleuchtet. Farbe und Deckkraft sind pro Zustand (normal, ausgewählt, aktiviert) einstellbar.

Die Grafik ist ein gewöhnliches RGBA-Bild wie bei den Text-Buttons und läuft unverändert durch
den IGS-Compiler. Pro Zustand entstehen höchstens vier Farben (Kanten in drei Deckkraft-Stufen),
damit die gemeinsame Palette des Menüstroms (254 Farben) nicht volläuft.
"""

from dataclasses import dataclass
from typing import Tuple

from PIL import Image, ImageDraw

SHAPE_LINE = "line"
SHAPE_CIRCLE = "circle"
SHAPE_TRIANGLE_RIGHT = "triangle_right"
SHAPE_TRIANGLE_LEFT = "triangle_left"
SHAPES = (SHAPE_LINE, SHAPE_CIRCLE, SHAPE_TRIANGLE_RIGHT, SHAPE_TRIANGLE_LEFT)

MIN_SIZE = 8          # kleinste Kantenlänge eines Grafikobjekts (sicherheitshalber, auch für Linien)
_SUPERSAMPLE = 4      # Kantenglättung: viermal so groß zeichnen, dann verkleinern
_EDGE_LEVELS = 3      # Deckkraft-Stufen an den Kanten (plus voll deckend)


@dataclass(frozen=True)
class ShapeStyle:
    """Form und Farben eines Form-Buttons; unveränderlich, damit die Vorschau Grafiken zwischenspeichern kann."""
    shape: str = SHAPE_LINE
    color_normal: str = "#FFFFFF"
    opacity_normal: int = 100        # Prozent; 0 = im Ruhezustand unsichtbar (Standard bis v1.14.6)
    color_selected: str = "#FFD700"
    opacity_selected: int = 100
    color_activated: str = "#FFFFFF"
    opacity_activated: int = 100

    def state_color(self, state: str) -> Tuple[int, int, int, int]:
        """RGBA für den Zustand ('normal', 'selected', 'activated')."""
        color, opacity = {
            "normal": (self.color_normal, self.opacity_normal),
            "selected": (self.color_selected, self.opacity_selected),
            "activated": (self.color_activated, self.opacity_activated),
        }.get(state, (self.color_normal, self.opacity_normal))
        r, g, b = parse_hex_color(color)
        alpha = round(max(0, min(100, int(opacity))) * 255 / 100)
        return r, g, b, alpha


def parse_hex_color(value: str) -> Tuple[int, int, int]:
    """'#RRGGBB' → (r, g, b); ungültige Angaben werden weiß."""
    text = (value or "").strip().lstrip("#")
    if len(text) != 6:
        return 255, 255, 255
    try:
        return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)
    except ValueError:
        return 255, 255, 255


def clamp_size(width: int, height: int) -> Tuple[int, int]:
    return max(MIN_SIZE, int(width)), max(MIN_SIZE, int(height))


def _coverage_mask(shape: str, width: int, height: int) -> Image.Image:
    """Abdeckung der Form (0..255) in drei Kantenstufen plus voll."""
    s = _SUPERSAMPLE
    big_w, big_h = width * s, height * s
    mask = Image.new("L", (big_w, big_h), 0)
    draw = ImageDraw.Draw(mask)
    if shape == SHAPE_CIRCLE:
        draw.ellipse([0, 0, big_w - 1, big_h - 1], fill=255)
    elif shape == SHAPE_TRIANGLE_RIGHT:
        draw.polygon([(0, 0), (big_w - 1, big_h / 2), (0, big_h - 1)], fill=255)
    elif shape == SHAPE_TRIANGLE_LEFT:
        draw.polygon([(big_w - 1, 0), (0, big_h / 2), (big_w - 1, big_h - 1)], fill=255)
    else:   # Linie: füllt die ganze Fläche, die Höhe ist die Strichstärke
        draw.rectangle([0, 0, big_w - 1, big_h - 1], fill=255)
    mask = mask.resize((width, height), Image.BOX)
    step = 255 / _EDGE_LEVELS
    return mask.point(lambda v: int(round(round(v / step) * step)))


def create_shape_image(style: ShapeStyle, width: int, height: int, state: str = "normal") -> Image.Image:
    """Erzeugt die Grafik eines Form-Buttons (RGBA) für einen Zustand."""
    width, height = clamp_size(width, height)
    r, g, b, alpha = style.state_color(state)
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    if alpha == 0:
        return img
    coverage = _coverage_mask(style.shape, width, height)
    alpha_mask = coverage.point(lambda v: v * alpha // 255)
    img.paste(Image.new("RGBA", (width, height), (r, g, b, 255)), (0, 0))
    img.putalpha(alpha_mask)
    return img
