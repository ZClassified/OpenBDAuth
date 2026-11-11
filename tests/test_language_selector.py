# tests/test_language_selector.py
"""
Unit-Tests für den erweiterten ISO 639-2 Sprachkatalog, die resolve_language_code Logik
und das interaktive LanguageComboBox Widget in OpenBDAuth (v1.1.2).
"""

import os
import sys
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication
from core.constants import (
    LANGUAGES,
    PINNED_LANGUAGES,
    ISO_639_2_CATALOG,
    get_language_display_items,
    resolve_language_code,
)
from core.project_state import ProjectState
from gui.widgets.language_combo import LanguageComboBox

app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)


class TestLanguageResolver(unittest.TestCase):
    def test_catalog_size_and_pinned(self):
        """Prüft, dass der Katalog über 80 Sprachen umfasst und Pinned-Sprachen vorhanden sind."""
        self.assertGreaterEqual(len(ISO_639_2_CATALOG), 80)
        self.assertEqual(len(PINNED_LANGUAGES), 6)
        items = get_language_display_items()
        self.assertGreater(len(items), 85)
        # Erstes Item muss Deutsch sein
        self.assertEqual(items[0], ("Deutsch [deu]", "deu"))

    def test_resolve_formatted_string(self):
        """Prüft Auflösung von Strings im Format 'Sprache [iso]'."""
        self.assertEqual(resolve_language_code("Deutsch [deu]"), "deu")
        self.assertEqual(resolve_language_code("Schwedisch [swe]"), "swe")
        self.assertEqual(resolve_language_code("Chinesisch (Mandarin) [zho]"), "zho")
        self.assertEqual(resolve_language_code("Originalton (O-Ton) [qaa]"), "qaa")

    def test_resolve_direct_codes(self):
        """Prüft direkte Eingabe von 3-Buchstaben ISO-Codes (auch Groß/Klein)."""
        self.assertEqual(resolve_language_code("deu"), "deu")
        self.assertEqual(resolve_language_code("ENG"), "eng")
        self.assertEqual(resolve_language_code("swe"), "swe")
        self.assertEqual(resolve_language_code("kor"), "kor")

    def test_resolve_plain_names_case_insensitive(self):
        """Prüft reine Sprachnamen ohne Klammern, auch case-insensitive."""
        self.assertEqual(resolve_language_code("Deutsch"), "deu")
        self.assertEqual(resolve_language_code("deutsch"), "deu")
        self.assertEqual(resolve_language_code("Schwedisch"), "swe")
        self.assertEqual(resolve_language_code("schwedisch"), "swe")
        self.assertEqual(resolve_language_code("koreanisch"), "kor")
        self.assertEqual(resolve_language_code("FRANZÖSISCH"), "fra")

    def test_resolve_fallback(self):
        """Prüft Fallback auf 'und' bei unbekannten oder ungültigen Eingaben."""
        self.assertEqual(resolve_language_code(""), "und")
        self.assertEqual(resolve_language_code(None), "und")
        self.assertEqual(resolve_language_code("Klingonisch123"), "und")
        self.assertEqual(resolve_language_code("────────────────────────────"), "und")


class TestLanguageComboBoxWidget(unittest.TestCase):
    def test_widget_initialization_and_default(self):
        """Prüft Initialisierung des LanguageComboBox Widgets."""
        combo = LanguageComboBox(default_code="deu")
        self.assertEqual(combo.get_selected_lang_code(), "deu")
        self.assertIn("Deutsch", combo.currentText())
        self.assertTrue(combo.isEditable())

    def test_set_selected_code(self):
        """Prüft programmatisches Setzen per ISO-Code."""
        combo = LanguageComboBox(default_code="deu")

        ok = combo.set_selected_code("swe")
        self.assertTrue(ok)
        self.assertEqual(combo.get_selected_lang_code(), "swe")

    def test_typing_and_auto_snap_back(self):
        """Prüft Auto-Snap-Back bei fehlerhafter Freitexteingabe und Bestätigung."""
        combo = LanguageComboBox(default_code="deu")

        # 1. Gültige Eingabe tippen
        combo.lineEdit().setText("Schwedisch")
        combo._on_editing_finished()
        self.assertEqual(combo.get_selected_lang_code(), "swe")

        # 2. Ungültigen Müll tippen -> muss auf letzten gültigen Wert (swe) zurücksnappen
        combo.lineEdit().setText("Abcdefg12345")
        combo._on_editing_finished()
        self.assertEqual(combo.get_selected_lang_code(), "swe")


class TestProjectStateLanguageIntegration(unittest.TestCase):
    def test_add_tracks_with_various_language_formats(self):
        """Prüft, dass ProjectState Audio- und Subtitle-Tracks unabhängig vom Format sauber auflöst."""
        project = ProjectState()

        # Audio mit formatiertem Namen
        project.add_audio_track("C:/audio/de.ac3", "Deutsch [deu]")
        self.assertEqual(project.titles[0].audio_tracks[-1]["lang"], "deu")

        # Audio mit reinem Namen
        project.add_audio_track("C:/audio/sw.dts", "Schwedisch")
        self.assertEqual(project.titles[0].audio_tracks[-1]["lang"], "swe")

        # Untertitel mit direktem ISO-Code
        project.add_subtitle_track("C:/subs/kr.srt", "kor")
        self.assertEqual(project.titles[0].subtitle_tracks[-1]["lang"], "kor")

        # Untertitel mit case-insensitivem Namen
        project.add_subtitle_track("C:/subs/it.sup", "italienisch")
        self.assertEqual(project.titles[0].subtitle_tracks[-1]["lang"], "ita")


if __name__ == "__main__":
    unittest.main()
