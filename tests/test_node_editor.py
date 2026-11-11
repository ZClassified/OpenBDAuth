# tests/test_node_editor.py
"""
Tests für den Node-Editor:
- Zeilen-Darstellung der Knoten
- GraphController mit Rückgängig/Wiederholen
- NodeScene: Aufbau, Sprungmarken, Verbinden per Ziehen
"""

import os
import sys
import tempfile
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from core.disc_model import DiscProject, START_NODE_ID, BUTTON_NAV
from tests.project_factory import make_project
from core.disc_rules import Source
from gui.node_editor.controller import GraphController
from gui.node_editor.rows import menu_rows, ROW_OUTPUT, ROW_CONTENT, ROW_ADD
from gui.node_editor.scene import NodeScene, WireItem, MarkerItem, NodeItem, CHOICE_DISCONNECT
from core.disc_edit import NODE_FILM, NODE_MENU, check_new_node_connection
from core.disc_rules import check_connection

app_instance = QApplication.instance() or QApplication(sys.argv)


def make_graph():
    """Hauptfilm mit 3 Kapiteln, 2 Tonspuren, 1 Untertitel, ein Bonus-Film; Kapitel- und Sprachmenü."""
    return make_project(chapters=3, audio=2, subs=1, extra_films=1, chapter_menu=True, language_menu=True)


class TestRows(unittest.TestCase):
    def test_content_buttons_are_grouped(self):
        project = make_graph()
        chapters, audio = project.menus[1], project.menus[2]
        rows = menu_rows(project, chapters)
        self.assertEqual([r.kind for r in rows], [ROW_CONTENT, ROW_OUTPUT, ROW_ADD])
        self.assertEqual(rows[0].text, "▸ Kapitel 1–3 → Hauptfilm")
        audio_rows = menu_rows(project, audio)
        self.assertEqual([r.text for r in audio_rows[:2]],
                         ["▸ Ton: DEUTSCH, ENGLISCH", "▸ Untertitel: ENGLISCH, Aus"])

    def test_missing_content_is_flagged(self):
        project = make_graph()
        project.films[0].chapters.pop()
        rows = menu_rows(project, project.menus[1])
        self.assertTrue(rows[0].warning)


class TestController(unittest.TestCase):
    def setUp(self):
        self.ctrl = GraphController(make_graph())
        self.main, self.chapters, self.audio = self.ctrl.project.menus

    def test_connect_undo_redo(self):
        button = self.main.buttons[0]
        bonus = self.ctrl.project.films[1].id
        self.assertTrue(self.ctrl.connect(Source.button(self.main.id, button.id), bonus).allowed)
        self.assertEqual(self.ctrl.project.menu(self.main.id).button(button.id).target, bonus)
        self.ctrl.undo_stack.undo()
        self.assertEqual(self.ctrl.project.menu(self.main.id).button(button.id).target, self.ctrl.project.films[0].id)
        self.ctrl.undo_stack.redo()
        self.assertEqual(self.ctrl.project.menu(self.main.id).button(button.id).target, bonus)

    def test_invalid_connection_is_not_applied(self):
        check = self.ctrl.connect(Source.button(self.main.id, self.main.buttons[0].id), self.main.id)
        self.assertFalse(check.allowed)
        self.assertEqual(self.ctrl.undo_stack.count(), 0)

    def test_film_after_film(self):
        """v1.18.1: Film-Ende → Film (z. B. „Alle Folgen“), ein Rückgängig-Schritt."""
        films = self.ctrl.project.films
        self.assertTrue(self.ctrl.connect(Source.film_end(films[0].id), films[1].id).allowed)
        self.assertEqual(films[0].end_target, films[1].id)
        self.assertEqual(self.ctrl.undo_stack.count(), 1)

    def test_remove_menu_clears_references_and_undo_restores(self):
        self.ctrl.remove_menus([self.chapters.id])
        self.assertIsNone(self.ctrl.project.menu(self.chapters.id))
        self.assertNotIn(self.chapters.id, [b.target for b in self.ctrl.project.main_menu.buttons])
        self.ctrl.undo_stack.undo()
        self.assertIsNotNone(self.ctrl.project.menu(self.chapters.id))
        self.assertIn(self.chapters.id, [b.target for b in self.ctrl.project.main_menu.buttons])

    def test_add_menu_and_buttons(self):
        menu_id = self.ctrl.add_menu("Extras", (900, 300))
        menu = self.ctrl.project.menu(menu_id)
        self.assertEqual([b.kind for b in menu.buttons], [BUTTON_NAV])
        button_id = self.ctrl.add_nav_button(menu_id, "MAKING-OF")
        self.ctrl.rename_button(menu_id, button_id, "BEHIND THE SCENES")
        self.assertEqual(self.ctrl.project.menu(menu_id).button(button_id).label, "BEHIND THE SCENES")
        self.ctrl.remove_button(menu_id, button_id)
        self.assertIsNone(self.ctrl.project.menu(menu_id).button(button_id))
        self.assertEqual(self.ctrl.undo_stack.count(), 4)

    def test_first_menu_becomes_main_menu(self):
        ctrl = GraphController(DiscProject())
        menu_id = ctrl.add_menu("Hauptmenü", (300, 0))
        self.assertEqual(ctrl.project.start_target, menu_id)

    def test_new_node_rules_match_connection_rules(self):
        p = self.ctrl.project
        button = Source.button(self.main.id, self.main.buttons[0].id)
        self.assertTrue(check_new_node_connection(p, button, NODE_FILM).allowed)
        self.assertTrue(check_new_node_connection(p, button, NODE_MENU).allowed)
        film_end = Source.film_end(p.films[0].id)
        self.assertTrue(check_new_node_connection(p, film_end, NODE_MENU).allowed)          # v1.18
        self.assertTrue(check_new_node_connection(p, film_end, NODE_FILM).allowed)          # v1.18.1
        # Probe-Anlage verändert das Projekt nicht
        self.assertEqual((len(p.films), len(p.menus)), (2, 3))

    def test_film_end_on_disc_without_menu_can_create_main_menu(self):
        ctrl = GraphController(DiscProject())
        film_id = ctrl.add_film("Hauptfilm", (0, 0))
        menu_id = ctrl.add_connected_node(Source.film_end(film_id), NODE_MENU, "Neues Menü", (300, 0))
        self.assertIsNotNone(menu_id)
        self.assertEqual(ctrl.project.start_target, menu_id)   # erstes Menü = Hauptmenü
        self.assertEqual(ctrl.project.film(film_id).end_target, menu_id)

    def test_new_film_after_film_end(self):
        count = self.ctrl.undo_stack.count()
        node_id = self.ctrl.add_connected_node(Source.film_end(self.ctrl.project.films[0].id),
                                               NODE_FILM, "Neuer Film", (0, 0))
        self.assertIsNotNone(node_id)
        self.assertEqual(self.ctrl.project.films[0].end_target, node_id)
        self.assertEqual(self.ctrl.undo_stack.count(), count + 1)

    # --- „＋ Button“ -------------------------------------------------------------
    def test_new_button_rules_match_nav_button_rules(self):
        p = self.ctrl.project
        src = Source.new_button(self.main.id)
        self.assertTrue(check_connection(p, src, p.films[1].id).allowed)
        self.assertTrue(check_connection(p, src, self.chapters.id).allowed)
        self.assertFalse(check_connection(p, src, self.main.id).allowed)   # eigenes Menü
        self.assertFalse(check_connection(p, src, None).allowed)           # ohne Ziel kein Button

    def test_new_button_connect_creates_labelled_button(self):
        bonus = self.ctrl.project.films[1]
        count = len(self.main.buttons)
        self.assertTrue(self.ctrl.connect(Source.new_button(self.main.id), bonus.id).allowed)
        buttons = self.ctrl.project.main_menu.buttons
        self.assertEqual(len(buttons), count + 1)
        self.assertEqual((buttons[-1].label, buttons[-1].target), (bonus.name.upper(), bonus.id))
        self.ctrl.undo_stack.undo()
        self.assertEqual(len(self.ctrl.project.main_menu.buttons), count)

    def test_new_button_to_new_node_is_one_step(self):
        count = self.ctrl.undo_stack.count()
        film_id = self.ctrl.add_connected_node(Source.new_button(self.main.id), NODE_FILM, "Neuer Film", (900, 0))
        button = self.ctrl.project.main_menu.buttons[-1]
        self.assertEqual((button.label, button.target), ("NEUER FILM", film_id))
        self.assertEqual(self.ctrl.undo_stack.count(), count + 1)
        self.ctrl.undo_stack.undo()
        self.assertIsNone(self.ctrl.project.film(film_id))
        self.assertNotIn(film_id, [b.target for b in self.ctrl.project.main_menu.buttons])

    def test_move_nodes(self):
        self.ctrl.move_nodes({self.main.id: (10, 20)})
        self.assertEqual(self.ctrl.project.view.node_positions[self.main.id], [10.0, 20.0])
        self.ctrl.undo_stack.undo()
        self.assertNotEqual(self.ctrl.project.view.node_positions[self.main.id], [10.0, 20.0])


class TestScene(unittest.TestCase):
    def setUp(self):
        self.ctrl = GraphController(make_graph())
        self.scene = NodeScene(self.ctrl)
        self.messages = []
        self.scene.status_message.connect(self.messages.append)

    def _wires(self):
        return [i for i in self.scene.items() if isinstance(i, WireItem)]

    def _markers(self):
        return [i for i in self.scene.items() if isinstance(i, MarkerItem)]

    def _drag(self, source, target_pos, choice=None):
        """Zieht eine Verbindung; `choice` simuliert die Auswahl in den Vorschlägen beim Loslassen im Leeren."""
        offered = []

        def choose(screen_pos, checks, connected):
            offered.append((checks, connected))
            return choice

        self.scene._choose_new_node = choose
        self.scene._start_drag(source, target_pos)
        self.scene._update_drag(target_pos)
        self.scene._finish_drag(target_pos)
        app_instance.processEvents()
        app_instance.processEvents()
        return offered

    def test_nodes_and_wires(self):
        p = self.ctrl.project
        self.assertEqual(set(self.scene.nodes), {START_NODE_ID} | {f.id for f in p.films} | {m.id for m in p.menus})
        # Start→Hauptmenü, Hauptmenü→Film/Bonus/Kapitel/Ton, Kapitel→Zurück, Ton→Zurück und →Film starten
        explicit = [w for w in self._wires() if not w.implicit]
        self.assertEqual(len(explicit), 8)
        # Linien-Ansicht: nicht verbundene Film-Enden als blasse Standard-Linie ins Hauptmenü, keine Marken
        implicit = [w for w in self._wires() if w.implicit]
        self.assertEqual(len(implicit), 2)
        self.assertTrue(all(w.target_id == self.ctrl.project.main_menu.id for w in implicit))
        self.assertEqual(self._markers(), [])

    def test_marker_mode_replaces_return_wires(self):
        self.ctrl.set_return_wire_mode("markers")
        app_instance.processEvents()
        markers = [m for m in self._markers() if not m.is_default]
        self.assertEqual(len(markers), 3)  # „Zurück“ aus Kapitel- und Tonmenü, „FILM STARTEN“ aus dem Tonmenü
        self.assertEqual(sorted(m.text for m in markers), ["↩ Hauptfilm", "↩ Hauptmenü", "↩ Hauptmenü"])
        self.assertEqual(len([m for m in self._markers() if m.is_default]), 2)  # Film-Enden
        self.assertEqual(len(self._wires()), 5)
        self.assertFalse(any(w.implicit for w in self._wires()))

    def test_switching_views_changes_display(self):
        """Regression v1.7.2: Beide Ansichten zeigten dieselben Sprungmarken."""
        def snapshot():
            app_instance.processEvents()
            return (len(self._wires()), len(self._markers()))
        lines = snapshot()
        self.ctrl.set_return_wire_mode("markers")
        markers = snapshot()
        self.ctrl.set_return_wire_mode("lines")
        self.assertNotEqual(lines, markers)
        self.assertEqual(snapshot(), lines)

    def test_hovering_a_wire_highlights_its_target(self):
        from gui.node_editor.scene import HL_TARGET, HL_NONE
        wire = next(w for w in self._wires() if w.implicit)
        self.scene.highlight_target(wire.target_id, True)
        self.assertEqual(self.scene.nodes[wire.target_id].highlight, HL_TARGET)
        self.scene.highlight_target(wire.target_id, False)
        self.assertEqual(self.scene.nodes[wire.target_id].highlight, HL_NONE)

    def test_drag_connects_and_empty_drop_offers_disconnect(self):
        main = self.ctrl.project.main_menu
        button = main.buttons[0]
        bonus_item = self.scene.nodes[self.ctrl.project.films[1].id]
        target_pos = bonus_item.mapToScene(QPointF(40, 20))
        self._drag(Source.button(main.id, button.id), target_pos)
        self.assertEqual(self.ctrl.project.main_menu.buttons[0].target, self.ctrl.project.films[1].id)

        offered = self._drag(Source.button(main.id, button.id), QPointF(-3000, -3000), CHOICE_DISCONNECT)
        self.assertTrue(offered[0][1])  # „Verbindung lösen“ wurde angeboten
        self.assertIsNone(self.ctrl.project.main_menu.buttons[0].target)

    def test_empty_drop_cancelled_keeps_connection(self):
        """Escape bzw. Klick daneben: nichts ändert sich (früher löste Loslassen im Leeren sofort)."""
        main = self.ctrl.project.main_menu
        button = main.buttons[0]
        before = button.target
        count = self.ctrl.undo_stack.count()
        self._drag(Source.button(main.id, button.id), QPointF(-3000, -3000), None)
        self.assertEqual(self.ctrl.project.main_menu.buttons[0].target, before)
        self.assertEqual(self.ctrl.undo_stack.count(), count)
        self.assertIsNone(self.scene._pending_wire)

    def test_empty_drop_creates_connected_menu(self):
        main = self.ctrl.project.main_menu
        button = main.buttons[0]
        drop = QPointF(1500, 900)
        films, menus = len(self.ctrl.project.films), len(self.ctrl.project.menus)
        self._drag(Source.button(main.id, button.id), drop, NODE_MENU)

        p = self.ctrl.project
        self.assertEqual((len(p.films), len(p.menus)), (films, menus + 1))
        new_menu = p.menus[-1]
        self.assertEqual(p.main_menu.buttons[0].target, new_menu.id)
        # Eingang des neuen Knotens liegt an der Stelle des Loslassens, Knoten ist ausgewählt
        item = self.scene.nodes[new_menu.id]
        self.assertAlmostEqual(item.input_point().x(), drop.x())
        self.assertAlmostEqual(item.input_point().y(), drop.y())
        self.assertTrue(item.isSelected())
        # Ein einziger Undo-Schritt nimmt Knoten und Verbindung zurück
        self.ctrl.undo_stack.undo()
        self.assertEqual(len(self.ctrl.project.menus), menus)
        self.assertNotEqual(self.ctrl.project.main_menu.buttons[0].target, new_menu.id)

    def test_empty_drop_creates_connected_film(self):
        main = self.ctrl.project.main_menu
        button = main.buttons[0]
        self._drag(Source.button(main.id, button.id), QPointF(1500, 900), NODE_FILM)
        new_film = self.ctrl.project.films[-1]
        self.assertEqual(self.ctrl.project.main_menu.buttons[0].target, new_film.id)
        self.assertEqual(new_film.name, "Neuer Film")

    def test_empty_drop_offers_only_allowed_nodes(self):
        # Start-Knoten: neues Menü und ab v1.18.1 auch ein neuer Film (z. B. Trailer vor dem Menü)
        offered = self._drag(Source.start(), QPointF(1500, 900), None)
        checks = offered[0][0]
        self.assertTrue(checks[NODE_MENU].allowed)
        self.assertTrue(checks[NODE_FILM].allowed)

    def test_empty_drop_from_film_end_offers_new_menu(self):
        # Film-Ende: neues Menü (v1.18) und neuer Film (v1.18.1)
        film = self.ctrl.project.films[0]
        offered = self._drag(Source.film_end(film.id), QPointF(1500, 900), NODE_MENU)
        checks = offered[0][0]
        self.assertTrue(checks[NODE_MENU].allowed)
        self.assertTrue(checks[NODE_FILM].allowed)
        self.assertEqual(len(self.ctrl.project.menus), 4)
        self.assertEqual(self.ctrl.project.films[0].end_target, self.ctrl.project.menus[-1].id)

    def test_drag_to_invalid_target_reports_reason(self):
        main = self.ctrl.project.main_menu
        button = main.buttons[0]
        target = button.target
        main_item = self.scene.nodes[main.id]
        self._drag(Source.button(main.id, button.id), main_item.mapToScene(QPointF(40, 20)))
        self.assertEqual(main.button(button.id).target, target)
        self.assertTrue(any("eigenes Menü" in m for m in self.messages))

    def test_drag_film_end_onto_film(self):
        film = self.ctrl.project.films[0]
        bonus_item = self.scene.nodes[self.ctrl.project.films[1].id]
        self._drag(Source.film_end(film.id), bonus_item.mapToScene(QPointF(40, 20)))
        self.assertEqual(self.ctrl.project.films[0].end_target, self.ctrl.project.films[1].id)

    def _add_port(self, menu_id):
        return self.scene.nodes[menu_id].ports[Source.new_button(menu_id)]

    def test_menu_nodes_have_add_port_without_wire(self):
        for menu in self.ctrl.project.menus:
            self.assertTrue(self._add_port(menu.id).is_add)
        self.assertFalse(any(w.source.kind == "new_button" for w in self._wires()))

    def test_drag_add_port_onto_film_creates_button(self):
        main = self.ctrl.project.main_menu
        bonus = self.ctrl.project.films[1]
        self._drag(Source.new_button(main.id), self.scene.nodes[bonus.id].mapToScene(QPointF(40, 20)))
        self.assertEqual(self.ctrl.project.main_menu.buttons[-1].target, bonus.id)

    def test_click_on_add_port_asks_for_label(self):
        # v1.9.8: gibt es Menüs anzubieten, zeigt „＋ Button“ zuerst die Liste; „Neuer Button …“ fragt nach dem Text
        main = self.ctrl.project.main_menu
        prompted = []
        self.scene._prompt_add_button = prompted.append
        self.scene._choose_offer = lambda offers, screen: "new"
        port_pos = self._add_port(main.id).scenePos()
        self._drag(Source.new_button(main.id), port_pos)
        self.assertEqual(prompted, [main.id])

    def test_drag_add_port_into_empty_creates_button_and_film(self):
        main = self.ctrl.project.main_menu
        offered = self._drag(Source.new_button(main.id), QPointF(1500, 900), NODE_FILM)
        self.assertFalse(offered[0][1])   # kein „Verbindung lösen“ für einen neuen Button
        new_film = self.ctrl.project.films[-1]
        self.assertEqual(self.ctrl.project.main_menu.buttons[-1].target, new_film.id)

    def test_selection_survives_rebuild(self):
        main_item = self.scene.nodes[self.ctrl.project.main_menu.id]
        main_item.setSelected(True)
        self.scene.rebuild()
        self.assertTrue(self.scene.nodes[self.ctrl.project.main_menu.id].isSelected())


if __name__ == "__main__":
    unittest.main()
