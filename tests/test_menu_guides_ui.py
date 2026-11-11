# tests/test_menu_guides_ui.py
"""
Linien im Viewer mit echten Maus- und Tastaturereignissen. Ab v1.16.1: Lineale statt Ankerpunkten, ab v1.16.2 direkt
am Bild – ein Klick ins obere Lineal setzt eine senkrechte Linie bei x, ins linke eine waagerechte bei y (gedrückt
ziehen verschiebt vor dem Loslassen), Linie ziehen verschiebt (Einrasten an Mitte, Title Safe …), zurück ins Lineal
löscht, Schild anklicken: Zahl eingeben, ✕ löscht. Ab v1.16.4 sind Linien reine Einrast-Hilfen: kein Heften,
fertige Linien lassen sich nur noch über die Zahl ändern, Klicks gehen durch sie hindurch.
"""

import unittest

from PySide6.QtCore import Qt, QEvent, QPoint, QPointF
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core import menu_guides, menu_layout
from tests.test_menu_designer import DesignerCase, app_instance


class GuideCase(DesignerCase):
    def _drag_points(self, start: QPointF, end: QPointF, modifiers=Qt.NoModifier):
        self._mouse(QEvent.MouseButtonPress, start, modifiers=modifiers)
        self._mouse(QEvent.MouseMove, (start + end) / 2, modifiers=modifiers)
        self._mouse(QEvent.MouseMove, end, modifiers=modifiers)
        self._mouse(QEvent.MouseButtonRelease, end, buttons=Qt.NoButton, modifiers=modifiers)

    def _guides(self):
        return menu_guides.guides(self.project, self.page_id)

    def _fixed(self):
        return self.project.view.fixed_guides

    def _box_center(self, key):
        x, y, w, h = menu_layout.boxes(self.project.menu(self.page_id))[key]
        return x + w / 2, y + h / 2

    def _global(self, scene_point: QPointF) -> QPoint:
        return self.designer.viewport().mapToGlobal(self.designer.mapFromScene(scene_point))

    def _ruler_event(self, ruler, kind, global_pos: QPoint, buttons=Qt.LeftButton, modifiers=Qt.NoModifier):
        local = QPointF(ruler.mapFromGlobal(global_pos))
        button = Qt.LeftButton if kind != QEvent.MouseMove else Qt.NoButton
        QApplication.sendEvent(ruler, QMouseEvent(kind, local, QPointF(global_pos), button, buttons, modifiers))
        app_instance.processEvents()

    def _ruler_point(self, side: str, scene_value: float) -> QPoint:
        """Globale Position im Lineal an der Stelle scene_value (oben: x, links: y im 1920×1080 Raum)."""
        ruler = self.designer.ruler_top if side == "top" else self.designer.ruler_left
        w = int(round(ruler._to_widget(scene_value)))
        return ruler.mapToGlobal(QPoint(w, ruler.height() // 2) if side == "top" else QPoint(ruler.width() // 2, w))

    def _click_ruler(self, side: str, scene_value: float, modifiers=Qt.NoModifier):
        ruler = self.designer.ruler_top if side == "top" else self.designer.ruler_left
        point = self._ruler_point(side, scene_value)
        self._ruler_event(ruler, QEvent.MouseButtonPress, point, modifiers=modifiers)
        self._ruler_event(ruler, QEvent.MouseButtonRelease, point, buttons=Qt.NoButton, modifiers=modifiers)

    def _new_line(self, edge, distance):
        line_id = self.ctrl.add_fixed_guide(edge, distance)
        app_instance.processEvents()
        return menu_guides.guide(self.project, self.page_id, line_id)


class TestRulers(GuideCase):
    def test_rulers_instead_of_anchor_points(self):
        designer = self.designer
        self.assertTrue(designer.ruler_top.isVisibleTo(designer))
        self.assertTrue(designer.ruler_left.isVisibleTo(designer))
        # direkt am Bild (v1.16.2): oberes Lineal endet an der Oberkante, linkes an der linken Kante
        vp = designer.viewport().geometry()
        image = designer.mapFromScene(designer.scene().sceneRect()).boundingRect()
        self.assertAlmostEqual(designer.ruler_left.geometry().right() + 1, vp.left() + image.left(), delta=1)
        self.assertAlmostEqual(designer.ruler_top.geometry().left(), vp.left() + image.left(), delta=1)
        self.assertAlmostEqual(designer.ruler_top.geometry().width(), image.width(), delta=2)
        self.assertLessEqual(designer.ruler_top.geometry().bottom() + 1, vp.top() + image.top())
        # Marken: waagerechte Linie im linken Lineal (y), senkrechte im oberen (x)
        from gui.studio.viewer import C_FIXED_GUIDE
        self._new_line("bottom", 300)
        self._new_line("left", 400)
        designer.ruler_top.hover = designer.ruler_left.hover = None
        top, left = designer.ruler_top.grab().toImage(), designer.ruler_left.grab().toImage()
        violet = lambda c: abs(c.red() - C_FIXED_GUIDE.red()) < 30 and abs(c.blue() - C_FIXED_GUIDE.blue()) < 30 \
            and c.green() < 170
        x = designer.ruler_top._to_widget(400)
        y = designer.ruler_left._to_widget(780)
        self.assertTrue(violet(top.pixelColor(int(x), top.height() - 3)))
        self.assertTrue(violet(left.pixelColor(left.width() - 3, int(y))))
        self.assertFalse(violet(top.pixelColor(int(designer.ruler_top._to_widget(780)), top.height() - 3)))
        self.win.viewer.chk_guides.setChecked(False)
        app_instance.processEvents()
        self.assertFalse(designer.ruler_top.isVisibleTo(designer))
        self.win.viewer.set_mode("remote")
        self.win.viewer.chk_guides.setChecked(True)
        app_instance.processEvents()
        self.assertFalse(designer.ruler_top.isVisibleTo(designer))     # Fernbedienung: keine Lineale

    def test_click_on_ruler_sets_line_there(self):
        steps = self.ctrl.undo_stack.count()
        self._click_ruler("top", 812, modifiers=Qt.AltModifier)       # oben bei x 812: senkrecht (Alt: frei)
        (line,) = self._fixed()
        self.assertEqual(line.edge, "left")
        self.assertAlmostEqual(line.distance, 812, delta=3)            # verkleinerte Ansicht: Pixel gerundet
        self.assertEqual(self.ctrl.undo_stack.count(), steps + 1)
        main = self.project.main_menu
        self.assertIsNotNone(menu_guides.guide(self.project, main.id, line.id))
        self._click_ruler("left", 535)                                # links nahe der Mitte: waagerecht bei 540
        horizontal = self._fixed()[-1]
        self.assertEqual((horizontal.edge, horizontal.distance), ("top", 540))

    def test_hover_preview_and_drag_before_release(self):
        from gui.studio.viewer import _GuideItem
        ruler = self.designer.ruler_top
        self._ruler_event(ruler, QEvent.MouseMove, self._ruler_point("top", 400), buttons=Qt.NoButton,
                          modifiers=Qt.AltModifier)
        (line, _label) = self.designer._ruler_preview
        self.assertAlmostEqual(line.line().x1(), 400, delta=3)
        self.assertEqual(self._fixed(), [])                             # nur Vorschau
        # gedrückt halten und übers Bild ziehen: die neue Linie folgt in x
        self._ruler_event(ruler, QEvent.MouseButtonPress, self._ruler_point("top", 400), modifiers=Qt.AltModifier)
        self.assertIsNone(self.designer._ruler_preview)
        self._ruler_event(ruler, QEvent.MouseMove, self._global(QPointF(1500, 600)), modifiers=Qt.AltModifier)
        self._ruler_event(ruler, QEvent.MouseButtonRelease, self._global(QPointF(1500, 600)), buttons=Qt.NoButton,
                          modifiers=Qt.AltModifier)
        (line,) = self._fixed()
        self.assertEqual(line.edge, "right")
        self.assertAlmostEqual(line.distance, 1920 - 1500, delta=3)
        self.assertTrue(any(isinstance(i, _GuideItem) and i.fixed for i in self.designer.scene().items()))

    def test_drag_beyond_picture_creates_nothing(self):
        ruler = self.designer.ruler_top
        self._ruler_event(ruler, QEvent.MouseButtonPress, self._ruler_point("top", 100))
        outside = ruler.mapToGlobal(QPoint(-200, ruler.height() // 2))  # links neben dem Bild
        self._ruler_event(ruler, QEvent.MouseMove, outside)
        self._ruler_event(ruler, QEvent.MouseButtonRelease, outside, buttons=Qt.NoButton)
        self.assertEqual(self._fixed(), [])

    def test_set_line_is_not_draggable_clicks_go_through(self):
        """v1.16.4: eine gesetzte Linie bleibt liegen; ein Klick auf sie greift den Button bzw. die Fläche darunter."""
        self._new_line("bottom", 300)                                    # y = 780
        before = list(self._fixed())
        steps = self.ctrl.undo_stack.count()
        self._drag_points(QPointF(1700, 780), QPointF(1700, 500))         # auf der Linie, kein Button dort
        self.assertEqual(self._fixed(), before)
        self.assertEqual(self.ctrl.undo_stack.count(), steps)
        # ein Button, der auf der Linie liegt, wird gegriffen – nicht die Linie
        menu = self.project.menu(self.page_id)
        button = menu.buttons[0]
        x, y, w, h = menu_layout.boxes(self.project.menu(self.page_id))[button.id]
        self.ctrl.move_menu_items(self.page_id, {button.id: (x, 780 - h // 2)})
        app_instance.processEvents()
        cx, cy = self._box_center(button.id)
        self._drag_points(QPointF(cx, cy), QPointF(cx, cy - 300), modifiers=Qt.AltModifier)
        self.assertAlmostEqual(self._box_center(button.id)[1], cy - 300, delta=4)
        self.assertEqual(self._fixed(), before)

    def test_badge_number_and_close(self):
        from gui.studio.viewer import _LineLabelItem
        line = self._new_line("bottom", 300)
        label = next(i for i in self.designer.scene().items() if isinstance(i, _LineLabelItem))
        self.assertEqual(label.text, "300 px von unten")
        device = label.deviceTransform(self.designer.viewportTransform())
        click = device.map(label.text_rect.center())
        QTest.mouseClick(self.designer.viewport(), Qt.LeftButton, Qt.NoModifier, click.toPoint())
        editor = self.designer._line_editor
        self.assertIsNotNone(editor)
        self.assertEqual(editor.text(), "300")
        editor.setText("70")
        QTest.keyClick(editor, Qt.Key_Return)
        app_instance.processEvents()
        self.assertEqual(self._fixed()[0].distance, 70)
        label = next(i for i in self.designer.scene().items() if isinstance(i, _LineLabelItem))
        device = label.deviceTransform(self.designer.viewportTransform())
        QTest.mouseClick(self.designer.viewport(), Qt.LeftButton, Qt.NoModifier,
                         device.map(label.close_rect.center()).toPoint())
        app_instance.processEvents()
        self.assertEqual(self._fixed(), [])
        self.assertIsNotNone(line)


if __name__ == "__main__":
    unittest.main()
