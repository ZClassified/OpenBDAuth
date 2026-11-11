# tests/test_ui_platform.py
"""Plattformgleiche Darstellung (v1.30.1): Schriften in Pixeln, Zahlenfelder mit eigenem Stil, Fortschritt lesbar."""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from gui import theme

app_instance = QApplication.instance() or QApplication(sys.argv)


class TestFonts(unittest.TestCase):
    def test_ui_font_in_pixels_like_windows(self):
        """9 pt wie unter Windows (96 dpi) = 12 px – auf dem Mac (72 dpi) waren es vorher nur 9 px."""
        font = theme.ui_font(9, bold=True)
        self.assertEqual(font.pixelSize(), 12)
        self.assertTrue(font.bold())
        self.assertEqual(theme.ui_font(7, italic=True).pixelSize(), 9)
        self.assertTrue(theme.ui_font(7, italic=True).italic())

    def test_node_font_uses_pixels(self):
        from gui.node_editor.scene import _font
        self.assertEqual(_font(10).pixelSize(), 13)
        self.assertEqual(_font(10).family(), QApplication.font().family())   # Systemschrift statt fest „Segoe UI“

    def test_mono_font_is_fixed_pitch(self):
        font = theme.mono_font(10)
        self.assertEqual(font.pixelSize(), 13)


class TestSpinBoxStyle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ui_theme_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_stylesheet_has_spinbox_rules_and_arrow_files(self):
        qss = theme.app_stylesheet(self.tmp)
        self.assertTrue(qss.startswith(theme.DARK_THEME_QSS))
        self.assertIn("QAbstractSpinBox::up-arrow", qss)
        for kind in ("up", "down"):
            for state in ("on", "off"):
                path = os.path.join(self.tmp, theme.ARROW_FILES.format(kind=kind, state=state))
                self.assertTrue(os.path.isfile(path))
                self.assertIn(path.replace("\\", "/"), qss)
        self.assertNotIn("{{", qss)            # Platzhalter vollständig ersetzt

    def test_arrow_files_are_reused(self):
        theme.app_stylesheet(self.tmp)
        path = os.path.join(self.tmp, theme.ARROW_FILES.format(kind="up", state="on"))
        before = os.path.getmtime(path)
        theme.app_stylesheet(self.tmp)
        self.assertEqual(os.path.getmtime(path), before)

    def test_fusion_and_dark_palette_only_on_macos(self):
        class FakeApp:
            def __init__(self):
                self.style = self.palette = self.qss = None

            def setStyle(self, name):
                self.style = name

            def setPalette(self, palette):
                self.palette = palette

            def setStyleSheet(self, qss):
                self.qss = qss

        with mock.patch.object(sys, "platform", "darwin"):
            fake = FakeApp()
            theme.apply_theme(fake)
            self.assertEqual(fake.style, "Fusion")
            self.assertIsNotNone(fake.palette)
            self.assertIn("QAbstractSpinBox", fake.qss)
        with mock.patch.object(sys, "platform", "win32"):
            fake = FakeApp()
            theme.apply_theme(fake)
            self.assertIsNone(fake.style)
            self.assertIsNone(fake.palette)
            self.assertIn("QAbstractSpinBox", fake.qss)     # Zahlenfelder überall gleich

    def test_checkboxes_have_no_own_background(self):
        self.assertRegex(theme.DARK_THEME_QSS, r"QCheckBox \{[^}]*background: transparent")


class TestReadableProgress(unittest.TestCase):
    def test_export_percent_in_activity_line(self):
        from gui.node_editor.controller import GraphController
        from gui.studio.export_dialog import ExportDialog
        from tests.project_factory import text_starter
        dialog = ExportDialog(GraphController(text_starter()))
        try:
            self.assertFalse(dialog.progress.isTextVisible())
            dialog.progress.setValue(42)
            dialog._start_activity(tempfile.gettempdir())
            self.assertIn("42 %", dialog.lbl_activity.text())
        finally:
            dialog._activity_timer.stop()
            dialog.close()

    def test_about_rows_are_not_cramped(self):
        from gui.studio import about_dialog
        self.assertGreaterEqual(about_dialog.ROW_HEIGHT, 40)


if __name__ == "__main__":
    unittest.main()
