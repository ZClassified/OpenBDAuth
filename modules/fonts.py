# modules/fonts.py
"""
Schriften für alles, was auf die Disc gerendert wird (Menü-Buttons, Untertitel aus .srt).

Die Schriften liegen im Projekt (assets/fonts/), damit die Disc auf jedem Rechner und jedem
Betriebssystem identisch aussieht:
- Menü-Buttons: Liberation Sans – metrisch identisch mit Arial (bis v1.7.2 verwendet), daher
  unverändertes Button-Layout
- Untertitel: Noto Sans – sehr gut lesbar, Latein/Griechisch/Kyrillisch
Für Japanisch, Chinesisch und Koreanisch werden Systemschriften verwendet (die CJK-Schriften sind
zum Mitliefern zu groß); ohne passende Systemschrift wird Noto Sans genommen.
"""

import os
import sys
from typing import List, Optional

from PIL import ImageFont

if getattr(sys, "_MEIPASS", None):
    FONTS_DIR = os.path.join(sys._MEIPASS, "assets", "fonts")
else:
    FONTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts")
MENU_FONT_PATH = os.path.join(FONTS_DIR, "LiberationSans-Regular.ttf")
SUBTITLE_FONT_PATH = os.path.join(FONTS_DIR, "NotoSans-Regular.ttf")


def load_menu_font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(MENU_FONT_PATH, size)


def cjk_font_candidates() -> List[str]:
    """Systemschriften mit japanischen/chinesischen/koreanischen Zeichen, je Betriebssystem."""
    if sys.platform == "win32":
        fonts = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts")
        return [os.path.join(fonts, n) for n in ("YuGothM.ttc", "YuGothR.ttc", "msgothic.ttc", "meiryo.ttc",
                                                  "malgun.ttf", "msyh.ttc")]
    if sys.platform == "darwin":
        return ["/System/Library/Fonts/Hiragino Sans GB.ttc",
                "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
                "/System/Library/Fonts/AppleSDGothicNeo.ttc",
                "/Library/Fonts/Arial Unicode.ttf"]
    return ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"]


def subtitle_font_path(needs_cjk: bool) -> str:
    if needs_cjk:
        found = _first_existing(cjk_font_candidates())
        if found:
            return found
    return SUBTITLE_FONT_PATH


def load_subtitle_font(size: int, needs_cjk: bool = False) -> ImageFont.FreeTypeFont:
    if needs_cjk:
        for path in cjk_font_candidates():
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, size)
                except OSError:
                    continue
    return ImageFont.truetype(SUBTITLE_FONT_PATH, size)


def _first_existing(paths: List[str]) -> Optional[str]:
    for p in paths:
        if os.path.exists(p):
            return p
    return None
