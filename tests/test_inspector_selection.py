# tests/test_inspector_selection.py
"""
Inspektor nach Auswahl (v1.12.1): nichts ausgewählt → Menü, ein Button → Typ, Name, Ziel, Form & Position,
Fernbedienung; mehrere Buttons → Film, gleiche Größe, ausrichten, entfernen. Viewer, Node-Ansicht und Inspektor
teilen sich die Auswahl. Kapitelmenü aus DesignerCase (6 Kapitel, 2 Tonspuren, 1 Untertitel).
"""

import unittest

from PySide6.QtCore import Qt, QPointF
from PySide6.QtTest import QTest

from core.disc_model import BUTTON_NAV, BUTTON_CHAPTER, BUTTON_AUDIO
from tests.test_menu_designer import DesignerCase, app_instance


def choose(combo, data):
    """Eintrag wie mit der Maus wählen (löst activated aus)."""
    index = combo.findData(data)
    assert index >= 0, (data, [combo.itemData(i) for i in range(combo.count())])
    combo.setCurrentIndex(index)
    combo.activated.emit(index)
    app_instance.processEvents()


class InspectorCase(DesignerCase):
    @property
    def page(self):
        return self.win.inspector.menu_page

    @property
    def menu(self):
        return self.project.menu(self.page_id)

    def _pick(self, *button_ids):
        if len(button_ids) == 1:
            self.ctrl.select_button(self.page_id, button_ids[0])
        else:
            self.ctrl.select_buttons(self.page_id, button_ids)
        app_instance.processEvents()


class TestModes(InspectorCase):
    def test_menu_mode_and_default_button(self):
        self.assertEqual(self.page.mode, "menu")
        self.assertTrue(self.page.card.isVisibleTo(self.page))
        self.assertFalse(self.page.sec_head.isVisibleTo(self.page))
        self.assertFalse(self.page.film_row.isVisibleTo(self.page))         # nur ein Film
        back = self.menu.buttons[-1]
        steps = self.ctrl.undo_stack.count()
        choose(self.page.combo_default_button, back.id)
        self.assertEqual(self.menu.default_button_id, back.id)
        self.assertEqual(self.ctrl.undo_stack.count(), steps + 1)
        choose(self.page.combo_default_button, "")
        self.assertIsNone(self.menu.default_button_id)

    def test_selection_switches_modes_and_back(self):
        a, b = self.menu.buttons[:2]
        self._pick(a.id)
        self.assertEqual(self.page.mode, "button")
        self.assertTrue(self.page.sec_target.isVisibleTo(self.page))
        self.assertFalse(self.page.card_bg.isVisibleTo(self.page))
        self.assertFalse(self.page.sec_remote.body.isVisibleTo(self.page))   # Fernbedienung eingeklappt
        self._pick(a.id, b.id)
        self.assertEqual(self.page.mode, "multi")
        self.assertIn("2 Buttons", self.page.lbl_selection.text())
        self.assertEqual(self.designer.selection, {a.id, b.id})              # Viewer zeigt dieselbe Auswahl
        self.assertEqual(self.win.scene.nodes[self.page_id].selected_button_ids, {a.id, b.id})
        self.page.btn_back.click()
        app_instance.processEvents()
        self.assertEqual((self.page.mode, self.designer.selection), ("menu", set()))


class TestOneButton(InspectorCase):
    def test_name_edit_and_auto(self):
        chapter = self.menu.buttons[0]
        self._pick(chapter.id)
        self.assertEqual(self.page.edit_button_name.text(), "KAPITEL 1")
        self.assertFalse(self.page.btn_name_auto.isEnabled())
        self.page.edit_button_name.setText("PROLOG")
        self.page.edit_button_name.editingFinished.emit()
        self.assertEqual(self.menu.button(chapter.id).label, "PROLOG")
        self.page.edit_button_name.setText("   ")
        self.page.edit_button_name.editingFinished.emit()
        self.assertEqual(self.page.edit_button_name.text(), "PROLOG")      # leer wird verworfen
        app_instance.processEvents()
        self.assertTrue(self.page.btn_name_auto.isEnabled())
        self.page.btn_name_auto.click()
        self.assertIsNone(self.menu.button(chapter.id).label)

    def test_kind_change_is_one_step_and_drops_the_wire(self):
        back = self.menu.buttons[-1]
        self.assertIsNotNone(back.target)
        self._pick(back.id)
        steps = self.ctrl.undo_stack.count()
        choose(self.page.combo_kind, BUTTON_CHAPTER)
        button = self.menu.button(back.id)
        self.assertEqual((button.kind, button.target, button.film_id), (BUTTON_CHAPTER, None, self.film_id))
        self.assertEqual(self.ctrl.undo_stack.count(), steps + 1)
        self.assertTrue(self.page.lbl_target_missing.isVisibleTo(self.page))
        self.assertFalse(self.page.target_film_row.isVisibleTo(self.page))   # nur ein Film
        choose(self.page.combo_target_item, self.project.film(self.film_id).chapters[4].id)
        self.assertEqual(self.menu.button(back.id).content_ref, self.project.film(self.film_id).chapters[4].id)
        self.assertFalse(self.page.lbl_target_missing.isVisibleTo(self.page))
        self.ctrl.undo_stack.undo()
        self.ctrl.undo_stack.undo()
        self.assertEqual(self.menu.button(back.id).kind, BUTTON_NAV)
        self.assertIsNotNone(self.menu.button(back.id).target)

    def test_nav_target_is_shown_not_edited(self):
        back = self.menu.buttons[-1]
        self._pick(back.id)
        self.assertEqual(self.page.lbl_nav_target.text(), "→ Hauptmenü")
        self.assertFalse(self.page.target_item_row.isVisibleTo(self.page))

    def test_film_end_shows_its_menu(self):
        """Film-Inspektor, Karte „Nach dem Film“ (v1.18): das verbundene Menü, sonst das Hauptmenü."""
        from core.disc_rules import Source
        self._select_node(self.film_id)
        film_page = self.win.inspector.film_page
        self.assertEqual(film_page.lbl_end.text(), "↩ Zurück ins Hauptmenü")
        self.ctrl.connect(Source.film_end(self.film_id), self.page_id)
        app_instance.processEvents()
        self.assertEqual(film_page.lbl_end.text(), f"↩ Ins Menü „{self.menu.name}“")
        other = self.ctrl.add_film("Making-of", (0.0, 300.0))                 # v1.18.1: Film → Film
        self.ctrl.connect(Source.film_end(self.film_id), other)
        app_instance.processEvents()
        self.assertEqual(film_page.lbl_end.text(), "▶ Danach: Making-of")

    def test_film_change_with_two_films(self):
        other = self.ctrl.add_film("Folge 2", (0.0, 300.0))
        self.ctrl.set_chapter_times(other, ["00:00:00.000", "00:00:30.000", "00:01:00.000"])
        chapter = self.menu.buttons[2]
        self._pick(chapter.id)
        self.assertTrue(self.page.target_film_row.isVisibleTo(self.page))
        choose(self.page.combo_target_film, other)
        button = self.menu.button(chapter.id)
        self.assertEqual((button.film_id, button.content_ref),
                         (other, self.project.film(other).chapters[2].id))   # Kapitel 3 → Kapitel 3

    def test_position_and_size_fields(self):
        chapter = self.menu.buttons[0]
        self._pick(chapter.id)
        self.page.spin_x.setValue(222)
        self.page.spin_y.setValue(111)
        self.page.spin_x.editingFinished.emit()
        self.assertEqual(self.menu.button(chapter.id).position, [222, 111])
        self.page.spin_btn_w.setValue(150)
        self.page.spin_btn_w.editingFinished.emit()
        self.assertEqual(self.menu.button(chapter.id).size[0], 150)
        app_instance.processEvents()
        self.assertTrue(self.page.btn_size_reset.isEnabled())

    def test_remote_directions(self):
        chapter = self.menu.buttons[0]
        self._pick(chapter.id)
        _caption, combo = self.page.dpad_rows["up"]
        self.assertTrue(combo.itemText(0).startswith("Automatisch (→ "))
        choose(combo, chapter.id)
        self.assertEqual(self.menu.button(chapter.id).dpad, {"up": chapter.id})   # bleibt stehen
        back = self.menu.buttons[-1]
        choose(combo, back.id)
        self.assertEqual(self.menu.button(chapter.id).dpad, {"up": back.id})
        choose(combo, "")
        self.assertEqual(self.menu.button(chapter.id).dpad, {})

    def test_remove_button(self):
        chapter = self.menu.buttons[0]
        self._pick(chapter.id)
        self.page.btn_remove_button.click()
        app_instance.processEvents()
        self.assertIsNone(self.menu.button(chapter.id))
        self.assertEqual(self.page.mode, "menu")


class TestManyButtons(InspectorCase):
    def test_numbers_for_all(self):
        """v1.15.3: X/Y/B/H bei Mehrfachauswahl – gleiche Werte stehen da, unterschiedliche bleiben leer."""
        from core import menu_layout
        ids = [b.id for b in self.menu.buttons[:3]]
        self.ctrl.move_menu_items(self.page_id, {ids[0]: (100, 418), ids[1]: (650, 422), ids[2]: (1200, 418)})
        self.ctrl.resize_menu_items(self.page_id, {ids[0]: (534, 40), ids[1]: (529, 40), ids[2]: (530, 40)})
        self._pick(*ids)
        geo = {f: edit for f, (_caption, edit) in self.page.multi_geo.items()}
        self.assertEqual((geo["y"].text(), geo["w"].text(), geo["h"].text()), ("", "", "40"))
        steps = self.ctrl.undo_stack.count()
        x_before = menu_layout.button_box(self.menu, self.menu.button(ids[1]))[0]
        geo["y"].setText("418")
        self.page._commit_multi_geo("y", geo["y"])
        geo["w"].setText("530")
        self.page._commit_multi_geo("w", geo["w"])
        app_instance.processEvents()
        self.assertEqual(self.ctrl.undo_stack.count(), steps + 2)
        boxes = [menu_layout.button_box(self.menu, self.menu.button(i)) for i in ids]
        self.assertEqual({(y, w, h) for _x, y, w, h in boxes}, {(418, 530, 40)})
        self.assertEqual(boxes[1][0], x_before + (529 - 530) // 2)            # Breite: Mitte bleibt
        self.assertEqual((geo["y"].text(), geo["w"].text()), ("418", "530"))
        geo["x"].setText("")                                                # leer: nichts ändern
        self.page._commit_multi_geo("x", geo["x"])
        self.assertEqual(self.ctrl.undo_stack.count(), steps + 2)

    def test_align_same_size_and_remove(self):
        ids = [b.id for b in self.menu.buttons[:3]]
        self.ctrl.move_menu_items(self.page_id, {ids[0]: (100, 100), ids[1]: (300, 250), ids[2]: (500, 400)})
        self.ctrl.resize_menu_items(self.page_id, {ids[0]: (200, 40)})
        self._pick(*ids)
        self.assertIn("KAPITEL 1", self.page.lbl_same_hint.text())          # Referenz: zuerst ausgewählt
        left = min(self.menu.button(i).position[0] for i in ids)          # 190: der verkleinerte behielt seine Mitte
        self.page.align_buttons["left"].click()
        self.assertEqual({self.menu.button(i).position[0] for i in ids}, {left})
        steps = self.ctrl.undo_stack.count()
        self.page.btn_same_width.click()
        self.assertEqual(self.ctrl.undo_stack.count(), steps + 1)
        self.assertEqual({self.menu.button(i).size[0] for i in ids}, {200})
        self.page.btn_remove_many.click()
        app_instance.processEvents()
        self.assertTrue(all(self.menu.button(i) is None for i in ids))
        self.assertEqual(self.page.mode, "menu")

    def test_film_for_all_content_buttons(self):
        other = self.ctrl.add_film("Folge 2", (0.0, 300.0))
        self.ctrl.set_chapter_times(other, ["00:00:00.000", "00:00:30.000"])
        ids = [b.id for b in self.menu.buttons]                              # Kapitel und Navigation
        self._pick(*ids)
        self.assertTrue(self.page.multi_film_row.isVisibleTo(self.page))
        self.assertEqual(self.page.combo_multi_film.currentData(), self.film_id)
        choose(self.page.combo_multi_film, other)
        content = [b for b in self.menu.buttons if b.is_content]
        self.assertTrue(all(b.film_id == other for b in content))
        self.assertEqual([b.content_ref is not None for b in content], [True, True] + [False] * (len(content) - 2))

    def test_delete_key_in_viewer(self):
        a, b = self.menu.buttons[:2]
        self._pick(a.id, b.id)
        self.designer.setFocus()
        QTest.keyClick(self.designer, Qt.Key_Delete)
        app_instance.processEvents()
        self.assertIsNone(self.menu.button(a.id))
        self.assertIsNone(self.menu.button(b.id))

    def test_node_row_selects_the_whole_group(self):
        item = self.win.scene.nodes[self.page_id]
        (index, row) = next((i, r) for i, r in enumerate(item.rows) if r.button_ids)
        from gui.node_editor.scene import HEADER_H, ROW_H
        point = item.mapToScene(QPointF(item.width / 2, HEADER_H + 4 + index * ROW_H + ROW_H / 2))
        view = self.win.view
        view.centerOn(point)
        app_instance.processEvents()
        QTest.mouseClick(view.viewport(), Qt.LeftButton, pos=view.mapFromScene(point))
        app_instance.processEvents()
        self.assertEqual(set(self.ctrl.selection_in(self.page_id)), set(row.button_ids))
        self.assertEqual(self.page.mode, "multi")


if __name__ == "__main__":
    unittest.main()
