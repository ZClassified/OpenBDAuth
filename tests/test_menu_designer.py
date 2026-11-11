# tests/test_menu_designer.py
"""Viewer als Menü-Designer (v1.9.3): echte Grafiken, Auswahl, Ziehen, Pfeiltasten, Vorschläge."""

import os
import sys
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import Qt, QEvent, QPointF
from PySide6.QtGui import QMouseEvent, QContextMenuEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core.disc_edit import add_track, set_chapter_times, TRACK_AUDIO, TRACK_SUBTITLE
from core.disc_model import BUTTON_CHAPTER, STYLE_TEXT
from core.menu_templates import chapter_menus

app_instance = QApplication.instance() or QApplication(sys.argv)


class DesignerCase(unittest.TestCase):
    def setUp(self):
        from gui.studio.main_window import StudioWindow
        self.win = StudioWindow(persist_layout=False)
        self.ctrl = self.win.controller
        film = self.ctrl.project.films[0]
        film.video_base = "film.264"
        set_chapter_times(film, [f"00:{i:02d}:00.000" for i in range(6)])
        for lang in ("deu", "eng"):
            add_track(film, TRACK_AUDIO, f"{lang}.ac3", lang)
        add_track(film, TRACK_SUBTITLE, "deu.sup", "deu")
        self.film_id = film.id
        self.win.resize(1400, 900)
        self.win.show()
        self.page_id = self.ctrl.create_chapter_menus(self.film_id)[0]
        # Text-Stil wie bis v1.13.1: die Tests rechnen mit Text-Buttons (380×70); neue Menüs haben „Form“
        self.ctrl.project.menu(self.page_id).button_style.kind = STYLE_TEXT
        self._select_node(self.page_id)
        self.designer = self.win.viewer.menu_preview

    def tearDown(self):
        self.ctrl.undo_stack.setClean()
        self.win.close()

    @property
    def project(self):
        return self.ctrl.project

    def _select_node(self, node_id):
        self.win.scene.rebuild()
        self.win.scene.select_node(node_id)
        app_instance.processEvents()

    def _view_pos(self, scene_point: QPointF):
        return self.designer.mapFromScene(scene_point)

    def _center(self, button_id):
        return self.designer.items[button_id].sceneBoundingRect().center()

    def _mouse(self, kind, scene_point, buttons=Qt.LeftButton, modifiers=Qt.NoModifier):
        pos = QPointF(self._view_pos(scene_point))
        button = Qt.LeftButton if kind != QEvent.MouseMove else Qt.NoButton
        event = QMouseEvent(kind, pos, self.designer.viewport().mapToGlobal(pos), button, buttons, modifiers)
        QApplication.sendEvent(self.designer.viewport(), event)
        app_instance.processEvents()

    def _drag(self, button_id, dx, dy, modifiers=Qt.NoModifier):
        start = self._center(button_id)
        end = start + QPointF(dx, dy)
        self._mouse(QEvent.MouseButtonPress, start, modifiers=modifiers)
        self._mouse(QEvent.MouseMove, end, modifiers=modifiers)
        self._mouse(QEvent.MouseButtonRelease, end, buttons=Qt.NoButton, modifiers=modifiers)


class TestDesigner(DesignerCase):
    def test_alt_drag_without_snapping(self):
        """v1.15.3: 6 px neben der Spalte rastet zurück ein; mit Alt bleibt der Button genau dort."""
        menu = self.project.menu(self.page_id)
        first = menu.buttons[0]
        x0 = first.position[0]
        self.assertTrue(any(b.position[0] == x0 for b in menu.buttons[1:]))     # Spalte: gleiche linke Kante
        self._drag(first.id, 6, 0)
        self.assertEqual(self.project.menu(self.page_id).buttons[0].position[0], x0)
        self._drag(first.id, 6, 0, modifiers=Qt.AltModifier)
        moved = self.project.menu(self.page_id).buttons[0].position[0]
        self.assertNotEqual(moved, x0)
        self.assertAlmostEqual(moved, x0 + 6, delta=3)          # verkleinerte Ansicht: Bildschirmpixel gerundet

    def test_real_button_graphics(self):
        menu = self.project.menu(self.page_id)
        self.assertEqual(set(self.designer.items), {b.id for b in menu.buttons})
        item = next(iter(self.designer.items.values()))
        self.assertEqual((item.pixmap().width(), item.pixmap().height()), (int(item.spec.width), int(item.spec.height)))
        first = self.designer.items[menu.buttons[0].id].pixmap().toImage()
        combo = self.win.viewer.combo_state
        combo.setCurrentIndex(combo.findData("activated"))
        app_instance.processEvents()
        self.assertNotEqual(self.designer.items[menu.buttons[0].id].pixmap().toImage(), first)

    def test_click_selects_everywhere(self):
        menu = self.project.menu(self.page_id)
        back = menu.buttons[-1]
        self._mouse(QEvent.MouseButtonPress, self._center(back.id))
        self._mouse(QEvent.MouseButtonRelease, self._center(back.id), buttons=Qt.NoButton)
        self.assertEqual(self.ctrl.selected_button, (self.page_id, back.id))
        self.assertTrue(self.designer.items[back.id].chosen)
        self.assertEqual(self.win.scene.nodes[self.page_id].selected_button_ids, {back.id})
        page = self.win.inspector.menu_page
        self.assertEqual(page.mode, "button")                      # Inspektor zeigt den Button (v1.12.1)
        self.assertIn("ZURÜCK", page.lbl_selection.text())
        self.assertEqual(self.project.menu(self.page_id).button(back.id).position,
                         [self.designer.items[back.id].spec.x, self.designer.items[back.id].spec.y])   # Klick ohne Ziehen ändert nichts

    def test_drag_moves_only_the_grabbed_chapter(self):
        # v1.9.10 (Konzept 2.1 Regel 4): ein Button ist ein Button – auch Kapitel ziehen einzeln
        menu = self.project.menu(self.page_id)
        chapter = menu.buttons[0]
        steps = self.ctrl.undo_stack.count()
        before = {bid: (i.spec.x, i.spec.y) for bid, i in self.designer.items.items()}
        self._drag(chapter.id, 50, -80)
        self.assertEqual(self.ctrl.undo_stack.count(), steps + 1)
        menu = self.project.menu(self.page_id)
        px, py = menu.button(chapter.id).position
        x, y = before[chapter.id]
        # Maus-Rundung plus Einrasten der Abstands-/Ausrichtungs-Hilfe (bis 12 px je Achse)
        self.assertLessEqual(abs(px - x - 50), 15)
        self.assertLessEqual(abs(py - y + 80), 15)
        for button in menu.buttons[1:]:
            self.assertEqual(tuple(button.position), before[button.id])
            self.assertEqual((self.designer.items[button.id].spec.x, self.designer.items[button.id].spec.y),
                             before[button.id])
        self.ctrl.undo_stack.undo()
        self.assertEqual(tuple(self.project.menu(self.page_id).button(chapter.id).position), before[chapter.id])

    def test_shift_click_and_frame_select_several_and_move_together(self):
        menu = self.project.menu(self.page_id)
        first, second, third = menu.buttons[:3]
        self._mouse(QEvent.MouseButtonPress, self._center(first.id))
        self._mouse(QEvent.MouseButtonRelease, self._center(first.id), buttons=Qt.NoButton)
        self._mouse(QEvent.MouseButtonPress, self._center(second.id), modifiers=Qt.ShiftModifier)
        self._mouse(QEvent.MouseButtonRelease, self._center(second.id), buttons=Qt.NoButton, modifiers=Qt.ShiftModifier)
        self.assertEqual(self.designer.selection, {first.id, second.id})
        self.assertTrue(self.designer.items[second.id].chosen)
        before = {bid: (i.spec.x, i.spec.y) for bid, i in self.designer.items.items()}
        steps = self.ctrl.undo_stack.count()
        self._drag(first.id, 0, 120)                                   # zieht beide
        menu = self.project.menu(self.page_id)
        dy1 = menu.button(first.id).position[1] - before[first.id][1]
        dy2 = menu.button(second.id).position[1] - before[second.id][1]
        self.assertEqual(dy1, dy2)
        self.assertGreater(dy1, 90)
        self.assertEqual(tuple(menu.button(third.id).position), before[third.id])
        self.assertEqual(self.ctrl.undo_stack.count(), steps + 1)
        # Pfeiltasten verschieben die ganze Auswahl, als ein Schritt
        self.designer.setFocus()
        QTest.keyClick(self.designer, Qt.Key_Left)
        QTest.keyClick(self.designer, Qt.Key_Left)
        app_instance.processEvents()
        menu = self.project.menu(self.page_id)
        self.assertEqual(menu.button(first.id).position[0], before[first.id][0] - 2)
        self.assertEqual(menu.button(second.id).position[0], before[second.id][0] - 2)
        self.assertEqual(self.ctrl.undo_stack.count(), steps + 2)
        # Auswahlrahmen auf freier Fläche: alle Buttons, die er berührt
        self._mouse(QEvent.MouseButtonPress, QPointF(5, 5))
        self.assertEqual(self.designer.selection, set())
        self._mouse(QEvent.MouseMove, QPointF(1915, 1075))
        self._mouse(QEvent.MouseButtonRelease, QPointF(1915, 1075), buttons=Qt.NoButton)
        self.assertEqual(self.designer.selection, {b.id for b in menu.buttons})
        self.assertEqual(self.ctrl.selected_button, (self.page_id, menu.buttons[0].id))

    def test_title_safe_frame_and_warning_while_dragging(self):
        from gui.studio.viewer import TITLE_SAFE
        frames = [i for i in self.designer.scene().items() if hasattr(i, "rect") and i.rect() == TITLE_SAFE]
        self.assertEqual(len(frames), 1)
        back = self.project.menu(self.page_id).buttons[-1]
        start = self._center(back.id)
        self._mouse(QEvent.MouseButtonPress, start)
        self._mouse(QEvent.MouseMove, QPointF(start.x(), 1070))
        self.assertTrue(self.designer.items[back.id].outside_safe)     # ragt über Title Safe hinaus
        self._mouse(QEvent.MouseMove, QPointF(start.x(), 600))
        self.assertFalse(self.designer.items[back.id].outside_safe)
        self._mouse(QEvent.MouseButtonRelease, QPointF(start.x(), 600), buttons=Qt.NoButton)

    def test_context_menu_resets_own_size(self):
        """v1.12: Rechtsklick verwirft die eigene Größe der Auswahl („Auf Vorlage zurücksetzen“ entfällt)."""
        from PySide6.QtWidgets import QMenu
        menu = self.project.menu(self.page_id)
        first, second = menu.buttons[:2]
        self.ctrl.resize_menu_items(self.page_id, {first.id: (200, 40), second.id: (200, 40)})
        self.designer._select_many({first.id})
        qmenu = QMenu()
        self.designer.fill_button_menu(qmenu)
        duplicate, reset_one = [a for a in qmenu.actions() if not a.isSeparator()]
        self.assertEqual(duplicate.text(), "Duplizieren (Strg+D)")              # v1.14
        self.assertEqual(reset_one.text(), "Eigene Größe zurücksetzen")
        self.assertTrue(reset_one.isEnabled())
        reset_one.trigger()
        menu = self.project.menu(self.page_id)
        self.assertIsNone(menu.button(first.id).size)
        self.assertEqual(menu.button(second.id).size, [200, 40])

    def test_nav_button_moves_alone_and_stays_inside(self):
        back = self.project.menu(self.page_id).buttons[-1]
        self._drag(back.id, -5000, -5000)
        self.assertEqual(self.project.menu(self.page_id).button(back.id).position, [0, 0])

    def test_arrow_keys_nudge_in_one_undo_step(self):
        back = self.project.menu(self.page_id).buttons[-1]
        x, y = self.designer.items[back.id].spec.x, self.designer.items[back.id].spec.y
        self.ctrl.select_button(self.page_id, back.id)
        steps = self.ctrl.undo_stack.count()
        self.designer.setFocus()
        for _ in range(3):
            QTest.keyClick(self.designer, Qt.Key_Right)
        QTest.keyClick(self.designer, Qt.Key_Down, Qt.ShiftModifier)
        app_instance.processEvents()
        self.assertEqual(self.project.menu(self.page_id).button(back.id).position, [x + 3, y + 10])
        self.assertEqual(self.ctrl.undo_stack.count(), steps + 1)

    def test_node_row_click_selects_button(self):
        from PySide6.QtCore import QPointF as P
        item = self.win.scene.nodes[self.page_id]
        index = next(i for i, r in enumerate(item.rows) if r.button_id)
        point = item.mapToScene(P(40, item.row_center_y(index)))
        self.win.view.centerOn(point)
        app_instance.processEvents()
        QTest.mouseClick(self.win.view.viewport(), Qt.LeftButton, pos=self.win.view.mapFromScene(point))
        app_instance.processEvents()
        self.assertEqual(self.ctrl.selected_button, (self.page_id, item.rows[index].button_id))
        self.assertTrue(self.designer.items[item.rows[index].button_id].chosen)


class TestRemoteMode(DesignerCase):
    """Viewer-Modus Fernbedienung (v1.9.9, Konzept 2.1 Regel 5)."""

    def setUp(self):
        super().setUp()
        from gui.studio.viewer import MODE_REMOTE
        self.win.viewer.set_mode(MODE_REMOTE)
        app_instance.processEvents()

    def _key(self, key):
        self.designer.setFocus()
        QTest.keyClick(self.designer, key)
        app_instance.processEvents()

    def _current(self):
        return self.ctrl.selected_button[1]

    def test_mode_switch_and_start_button(self):
        from gui.studio.viewer import MODE_DESIGN
        viewer = self.win.viewer
        self.assertFalse(viewer.combo_state.isVisibleTo(viewer))
        self.assertFalse(viewer.chk_guides.isVisibleTo(viewer))
        self.assertIn("wie auf der Fernbedienung", viewer.caption.text())
        menu = self.project.menu(self.page_id)
        self.assertEqual(self._current(), menu.buttons[0].id)        # Start-Button ist der aktuelle
        self.assertEqual(set(self.designer.handle_items), {"up", "down", "left", "right"})
        self.assertEqual(self.win.inspector.menu_page.findChildren(type(viewer.combo_state), "dpad"), [])
        viewer.set_mode(MODE_DESIGN)
        app_instance.processEvents()
        self.assertTrue(viewer.combo_state.isVisibleTo(viewer))
        self.assertEqual(self.designer.handle_items, {})

    def test_arrow_keys_follow_dpad_targets(self):
        from core import menu_design
        menu = self.project.menu(self.page_id)
        targets = menu_design.dpad_targets(self.project, menu)
        first = menu.buttons[0].id
        self._key(Qt.Key_Right)
        self.assertEqual(self._current(), targets[first]["right"])
        self._key(Qt.Key_Down)
        self.assertEqual(self._current(), targets[targets[first]["right"]]["down"])
        # Klick auf einen Griff = Taste drücken
        now = self._current()
        handle = self.designer.handle_items["up"]
        self._mouse(QEvent.MouseButtonPress, handle.center)
        self._mouse(QEvent.MouseButtonRelease, handle.center, buttons=Qt.NoButton)
        self.assertEqual(self._current(), menu_design.dpad_targets(self.project, menu)[now]["up"])

    def test_enter_on_menu_button_switches_menu(self):
        menu = self.project.menu(self.page_id)
        back = next(b for b in menu.buttons if b.label == "ZURÜCK")
        self.ctrl.select_button(self.page_id, back.id)
        app_instance.processEvents()
        self._key(Qt.Key_Return)
        QTest.qWait(300)
        app_instance.processEvents()
        main = self.project.main_menu
        self.assertEqual(self.win.scene.selected_node_id(), main.id)
        self.assertEqual(self.win.viewer.current_id, main.id)
        self.assertEqual(self.ctrl.selected_button, (main.id, main.buttons[0].id))
        self.assertIn("Hauptmenü", self.win.viewer.caption.text())

    def test_enter_on_chapter_describes_what_happens(self):
        self._key(Qt.Key_Return)
        QTest.qWait(300)
        app_instance.processEvents()
        self.assertIn("startet bei Kapitel 1", self.win.viewer.caption.text())

    def test_drag_handle_sets_direction_and_right_click_resets(self):
        from PySide6.QtWidgets import QMenu
        from gui.studio.viewer import C_SELECT
        menu = self.project.menu(self.page_id)
        first = menu.buttons[0]
        back = next(b for b in menu.buttons if b.label == "ZURÜCK")
        steps = self.ctrl.undo_stack.count()
        handle = self.designer.handle_items["up"]
        self._mouse(QEvent.MouseButtonPress, handle.center)
        self._mouse(QEvent.MouseMove, self._center(back.id))
        self._mouse(QEvent.MouseButtonRelease, self._center(back.id), buttons=Qt.NoButton)
        self.assertEqual(self.project.menu(self.page_id).button(first.id).dpad, {"up": back.id})
        self.assertEqual(self.ctrl.undo_stack.count(), steps + 1)
        self.assertTrue(self.designer.handle_items["up"].overridden)
        self.assertEqual(self.designer.handle_items["up"].color, C_SELECT)       # gold
        # auf den eigenen Button gezogen: bleibt stehen
        handle = self.designer.handle_items["left"]
        self._mouse(QEvent.MouseButtonPress, handle.center)
        self._mouse(QEvent.MouseMove, self._center(first.id))
        self._mouse(QEvent.MouseButtonRelease, self._center(first.id), buttons=Qt.NoButton)
        self.assertEqual(self.project.menu(self.page_id).button(first.id).dpad["left"], first.id)
        self.assertTrue(self.designer.handle_items["left"].stays)
        # Rechtsklick-Menü: „Automatisch (→ …)“ setzt zurück
        qmenu = QMenu()
        self.designer.fill_handle_menu(qmenu, "up")
        auto, stay = qmenu.actions()
        self.assertTrue(auto.text().startswith("Automatisch (→ "))
        self.assertFalse(auto.isChecked())
        auto.trigger()
        self.assertNotIn("up", self.project.menu(self.page_id).button(first.id).dpad)
        # der Export übernimmt die festgelegte Richtung
        from core.disc_adapter import preview_menu_specs
        spec = preview_menu_specs(self.project, self.project.menu(self.page_id))[0]
        self.assertEqual(spec.left_id, 1)                                          # bleibt auf Button 1

    def test_unreachable_buttons_are_marked(self):
        menu = self.project.menu(self.page_id)
        self.assertEqual(self.designer.unreachable_items, [])
        # alle Wege auf den ersten Button selbst umlenken: nichts anderes ist mehr erreichbar
        for direction in ("up", "down", "left", "right"):
            self.ctrl.set_button_dpad(self.page_id, menu.buttons[0].id, direction, menu.buttons[0].id)
        app_instance.processEvents()
        self.assertEqual(len(self.designer.unreachable_items), len(menu.buttons) - 1)

    def test_removing_target_button_resets_override(self):
        menu = self.project.menu(self.page_id)
        first, back = menu.buttons[0], menu.buttons[-1]
        self.ctrl.set_button_dpad(self.page_id, first.id, "down", back.id)
        self.ctrl.remove_button(self.page_id, back.id)
        self.assertEqual(self.project.menu(self.page_id).button(first.id).dpad, {})


class TestGhostSuggestions(DesignerCase):
    def _ghosts(self):
        from gui.studio.viewer import _GhostItem
        return [i for i in self.designer.scene().items() if isinstance(i, _GhostItem)]

    def test_main_menu_shows_and_creates_suggestion(self):
        from unittest import mock
        self._select_node(self.project.main_menu.id)
        ghosts = self._ghosts()
        self.assertEqual([g.text for g in ghosts], ["＋ SPRACHE"])     # Kapitelmenü gibt es schon
        # Klick öffnet das Anlege-Fenster (Art des Sprachmenüs); hier gleich „Anlegen“ mit dem Vorschlag
        with mock.patch("gui.node_editor.create_popup.CreatePopup.exec_at", return_value=True):
            center = ghosts[0].sceneBoundingRect().center()
            self._mouse(QEvent.MouseButtonPress, center)
            self.assertEqual(len(self.project.menus), 2)               # beim Drücken passiert noch nichts
            self._mouse(QEvent.MouseButtonRelease, center, buttons=Qt.NoButton)
            app_instance.processEvents()
        self.assertEqual(self.project.main_menu.buttons[-1].label, "SPRACHE")
        self.assertEqual(len([m for m in self.project.menus if m.name == "Ton & Untertitel"]), 1)

    def test_content_menu_offers_nothing_to_add(self):
        """v1.12 (Vorschlag B): Inhalts-Menüs schlagen keine fehlenden Spuren mehr vor."""
        from core.menu_templates import LANG_SUBTITLES
        (subs,) = self.ctrl.create_language_menus(self.film_id, LANG_SUBTITLES)
        self._select_node(subs)
        self.assertEqual(self._ghosts(), [])


if __name__ == "__main__":
    unittest.main()
