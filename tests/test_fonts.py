# tests/test_fonts.py
"""
Mitgelieferte Schriften für alles, was auf die Disc gerendert wird (v1.7.3):
Menü-Buttons und Untertitel dürfen nicht von installierten Systemschriften abhängen.
"""

import os
import unittest
from unittest import mock

from PIL import ImageFont

from modules import fonts
from modules.menu_author import create_button_image
from modules.subtitles.srt_to_sup import get_subtitle_font


class TestBundledFonts(unittest.TestCase):
    def test_font_files_and_licenses_are_bundled(self):
        for name in ("LiberationSans-Regular.ttf", "NotoSans-Regular.ttf",
                     "LICENSE-LiberationSans.txt", "LICENSE-NotoSans.txt"):
            self.assertTrue(os.path.isfile(os.path.join(fonts.FONTS_DIR, name)), name)

    def test_menu_buttons_do_not_need_system_fonts(self):
        real_truetype = ImageFont.truetype

        def only_bundled(path, *args, **kwargs):
            if not str(path).startswith(fonts.FONTS_DIR):
                raise OSError(f"Systemschrift verwendet: {path}")
            return real_truetype(path, *args, **kwargs)

        with mock.patch("PIL.ImageFont.truetype", side_effect=only_bundled):
            for state in ("normal", "selected", "activated"):
                img = create_button_image("TON & UNTERTITEL", 380, 70, state)
                self.assertEqual(img.size, (380, 70))

    def test_liberation_matches_arial_widths(self):
        """Liberation Sans ist metrisch identisch mit Arial: gleiches Button-Layout wie bis v1.7.2."""
        try:
            arial = {size: ImageFont.truetype("arial.ttf", size) for size in (14, 20, 26)}
        except OSError:
            self.skipTest("Arial ist auf diesem System nicht installiert")
        for size, reference in arial.items():
            ours = fonts.load_menu_font(size)
            for text in ("FILM STARTEN", "TON & UNTERTITEL", "AUDIO: DEUTSCH", "ZURÜCK", "KAPITEL 12"):
                self.assertEqual(ours.getlength(text), reference.getlength(text), (size, text))

    def test_subtitles_use_bundled_font_for_latin_text(self):
        font = get_subtitle_font("Grüß Gott – Straße", 48)
        self.assertEqual(font.path, fonts.SUBTITLE_FONT_PATH)

    def test_cjk_falls_back_to_bundled_font_without_system_font(self):
        with mock.patch.object(fonts, "cjk_font_candidates", return_value=["/gibt/es/nicht.ttc"]):
            self.assertEqual(get_subtitle_font("日本語", 48).path, fonts.SUBTITLE_FONT_PATH)

    def test_cjk_candidates_for_every_platform(self):
        for platform in ("win32", "darwin", "linux"):
            with mock.patch.object(fonts.sys, "platform", platform):
                self.assertTrue(fonts.cjk_font_candidates(), platform)


if __name__ == "__main__":
    unittest.main()
