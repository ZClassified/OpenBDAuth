# tests/test_about_dialog.py
"""Info-Fenster (v1.19.0): Überblick, Neuerungen (v1.28.0), Tastenkürzel, Lizenzen; erreichbar über „ⓘ“ in der
oberen Leiste und F1."""

import os
import sys
import unittest
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6 import QtGui
from PySide6.QtWidgets import QApplication, QLabel

from core.constants import APP_VERSION
from core.release_notes import RELEASES, Notes, Release
from gui.studio.about_dialog import (
    AboutDialog, TAB_LICENSES, TAB_NEWS, TAB_OVERVIEW, TAB_SHORTCUTS, components, news_html, shortcut_groups,
)

app_instance = QApplication.instance() or QApplication(sys.argv)


class TestAboutDialog(unittest.TestCase):
    def test_tabs_and_version(self):
        dialog = AboutDialog("de", TAB_LICENSES)
        self.addCleanup(dialog.close)
        self.assertEqual(dialog.stack.count(), 4)
        self.assertEqual(dialog.stack.currentIndex(), TAB_LICENSES)
        self.assertTrue(dialog.tab_group.button(TAB_LICENSES).isChecked())
        dialog.tab_group.button(TAB_SHORTCUTS).click()
        self.assertEqual(dialog.stack.currentIndex(), TAB_SHORTCUTS)
        self.assertIn(f"Version {APP_VERSION}", [label.text() for label in dialog.findChildren(QLabel)])

    def test_news_in_the_interface_language(self):
        """v1.28.0: Neuerungen, neueste oben, die laufende Version markiert."""
        for lang, label, title in (("de", "Diese Version", RELEASES[0].de.title),
                                   ("en", "This version", RELEASES[0].en.title)):
            dialog = AboutDialog(lang, TAB_NEWS)
            self.addCleanup(dialog.close)
            self.assertEqual(dialog.stack.currentIndex(), TAB_NEWS)
            text = dialog.stack.currentWidget().toPlainText().strip()
            self.assertTrue(text.startswith(APP_VERSION), text[:40])
            self.assertIn(label, text)
            self.assertIn(title, text)
            self.assertLess(text.index(RELEASES[0].version), text.index(RELEASES[-1].version))

    def test_news_escapes_text(self):
        release = Release("9.9.9", "2026-01-02", de=Notes("A < B", ("<b>fett</b> & mehr",)), en=Notes("x", ("y",)))
        with mock.patch("gui.studio.about_dialog.RELEASES", (release,)):
            page = news_html("de")
        self.assertIn("A &lt; B", page)
        self.assertIn("&lt;b&gt;fett&lt;/b&gt; &amp; mehr", page)
        self.assertNotIn("<b>", page)

    def test_licenses_cover_what_the_program_uses(self):
        names = [c[0] for c in components("de")]
        for name in ("Qt / PySide6", "Pillow", "tsMuxeR", "FFmpeg", "Liberation Sans", "Noto Sans", "Python"):
            self.assertIn(name, names)
        self.assertTrue(all(len(c) == 4 and all(c) for c in components("en")))

    def test_both_languages_have_the_same_shortcuts(self):
        de, en = shortcut_groups(True), shortcut_groups(False)
        self.assertEqual([len(items) for _, items in de], [len(items) for _, items in en])
        self.assertIn(("F1", "Dieses Fenster"), de[0][1])


class TestOpenFromStudio(unittest.TestCase):
    def setUp(self):
        from gui.studio.main_window import StudioWindow
        self.win = StudioWindow(persist_layout=False)
        self.addCleanup(self.win.close)
        self.opened = []
        self.win.about_dialog = lambda tab: mock.Mock(exec=lambda: self.opened.append(tab))

    def test_brand_opens_news(self):
        """v1.29.0: Klick auf Logo, Name oder Version öffnet die Neuerungen; ⓘ ist aus der Leiste verschwunden."""
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        self.win.show()
        QTest.mouseClick(self.win.brand.version, Qt.LeftButton)
        QTest.mouseClick(self.win.brand, Qt.LeftButton, pos=QPoint(4, 4))
        self.assertEqual(self.opened, [TAB_NEWS, TAB_NEWS])
        self.assertNotIn(self.win.act_about, self.win.toolbar.actions())
        self.assertIn("F1", self.win.brand.toolTip())

    def test_f1_opens_overview(self):
        self.assertEqual(self.win.act_about.shortcut(), QtGui.QKeySequence(QtGui.QKeySequence.HelpContents))
        self.assertIn(self.win.act_about, self.win.actions())
        self.win.act_about.trigger()
        self.assertEqual(self.opened, [TAB_OVERVIEW])


if __name__ == "__main__":
    unittest.main()
