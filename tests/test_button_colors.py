# tests/test_button_colors.py
"""
Eigene Farben für den Button-Stil (v1.14.4): Hex-Code, Hauptfarben des Hintergrunds, Pipette im Viewer
(aus dem Original in voller Auflösung), „Im Projekt benutzt“.
"""

import os
import tempfile
import unittest

from PySide6.QtCore import Qt, QEvent, QPointF
from PySide6.QtTest import QTest

from core import color_tools
from core.disc_model import STYLE_SHAPE
from tests.test_inspector_selection import InspectorCase
from tests.test_menu_designer import app_instance


def stripes(path, colors, size=(1920, 1080)):
    """Bild mit senkrechten Streifen gleicher Breite in den angegebenen Farben."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", size)
    draw = ImageDraw.Draw(img)
    w = size[0] // len(colors)
    for i, color in enumerate(colors):
        draw.rectangle([i * w, 0, (i + 1) * w - 1, size[1]], fill=color)
    img.save(path)
    return path


class TestColorTools(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_parse_hex(self):
        self.assertEqual(color_tools.parse_hex("c8a060"), "#C8A060")
        self.assertEqual(color_tools.parse_hex(" #C8A060 "), "#C8A060")
        self.assertEqual(color_tools.parse_hex("#ca6"), "#CCAA66")
        for bad in ("", "#12345", "gold", "#GGGGGG"):
            self.assertIsNone(color_tools.parse_hex(bad))

    def test_dominant_colors_and_color_at(self):
        path = stripes(os.path.join(self.tmp.name, "bg.png"), ["#102030", "#C8A060", "#F0F0F0"])
        colors = color_tools.dominant_colors(path, 8)
        self.assertEqual(set(colors), {"#102030", "#C8A060", "#F0F0F0"})
        self.assertEqual(color_tools.color_at(path, 960, 540), "#C8A060")
        # kleineres Bild: wie im Viewer auf 1920×1080 gestreckt
        small = stripes(os.path.join(self.tmp.name, "small.png"), ["#000000", "#FF0000"], size=(200, 100))
        self.assertEqual(color_tools.color_at(small, 1900, 10), "#FF0000")
        self.assertEqual(color_tools.dominant_colors(None), [])
        self.assertIsNone(color_tools.color_at(os.path.join(self.tmp.name, "fehlt.png"), 1, 1))

    def test_project_colors(self):
        from tests.project_factory import make_project
        project = make_project(chapters=4, chapter_menu=True)
        for menu in project.menus:
            menu.button_style.color_selected = "#c8a060"
        self.assertEqual(color_tools.project_colors(project)[0], "#C8A060")


class TestColorsInStudio(InspectorCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.image = stripes(os.path.join(self.tmp.name, "kapitel.png"), ["#102030", "#C8A060", "#F0F0F0"])
        self.ctrl.set_button_style(self.page_id, kind=STYLE_SHAPE)
        self.ctrl.set_background_file(self.page_id, "image", self.image)
        app_instance.processEvents()

    def tearDown(self):
        super().tearDown()
        self.tmp.cleanup()

    @property
    def style(self):
        return self.menu.button_style

    def test_hex_field(self):
        hex_edit = self.page.color_tools["selected"][0]
        self.assertEqual(hex_edit.text(), "#FFD700")
        hex_edit.setText("c8a060")
        hex_edit.editingFinished.emit()
        app_instance.processEvents()
        self.assertEqual(self.style.color_selected, "#C8A060")
        self.assertEqual(hex_edit.text(), "#C8A060")
        hex_edit.setText("gold")
        hex_edit.editingFinished.emit()
        self.assertEqual(self.style.color_selected, "#C8A060")             # ungültig: bleibt, Feld zurück
        self.assertEqual(hex_edit.text(), "#C8A060")

    def test_menu_offers_background_and_recent_colors(self):
        swatch = self.page.state_rows["normal"][1]
        swatch._build_menu()
        tips = [s.toolTip() for s in swatch.swatches]
        for color in ("#102030", "#C8A060", "#F0F0F0"):                      # aus dem Hintergrund
            self.assertIn(color, tips)
        self.assertEqual(swatch.act_custom.text(), "Weitere Farben …")
        swatch.swatches[tips.index("#C8A060")].click()
        self.assertEqual(self.style.color_normal, "#C8A060")

    def test_pipette_reads_original_image(self):
        _hex, pipette = self.page.color_tools["activated"]
        pipette.click()
        self.assertIn("Pipette", self.win.viewer.caption.text())
        point = QPointF(self.designer.mapFromScene(QPointF(1800, 60)))      # dritter Streifen
        event = QEvent  # noqa: F841 – nur für die Lesbarkeit
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication
        press = QMouseEvent(QEvent.MouseButtonPress, point, self.designer.viewport().mapToGlobal(point),
                            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(self.designer.viewport(), press)
        app_instance.processEvents()
        self.assertEqual(self.style.color_activated, "#F0F0F0")
        self.assertIsNone(self.designer._color_pick)
        self.assertNotIn("Pipette", self.win.viewer.caption.text())

    def test_pipette_escape_and_no_image(self):
        _hex, pipette = self.page.color_tools["normal"]
        pipette.click()
        QTest.keyClick(self.designer, Qt.Key_Escape)
        self.assertIsNone(self.designer._color_pick)
        self.ctrl.clear_background(self.page_id)                           # wie Hauptmenü: ohne Bild
        app_instance.processEvents()
        pipette.click()
        self.designer._finish_color_pick(QPointF(10, 10))
        self.assertIn("kein Hintergrundbild", self.win.viewer.caption.text())


if __name__ == "__main__":
    unittest.main()
