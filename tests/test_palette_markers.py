# tests/test_palette_markers.py
"""
v1.12.2: Palette (Buttons nach Art anlegen, Ziel = erstes, das im Menü fehlt), Ziel-Plaketten und roter Rand im
Viewer, Preflight mit betroffenem Button (Klick wählt ihn aus) und Hinweis zu Form-Buttons in Untermenüs.
"""

import unittest

from PySide6.QtCore import Qt, QPointF, QMimeData
from PySide6.QtGui import QDropEvent

from core.disc_edit import add_button_of_kind, next_free_target
from core.disc_model import BUTTON_NAV, BUTTON_CHAPTER, BUTTON_AUDIO, BUTTON_SUBTITLE, SUBTITLE_OFF, STYLE_SHAPE
from core.preflight import run_preflight, ERROR, WARNING, INFO
from tests.project_factory import make_project
from tests.test_menu_designer import DesignerCase, app_instance


class TestAddButtonOfKind(unittest.TestCase):
    def setUp(self):
        self.project = make_project(chapters=3, audio=2, subs=1, chapter_menu=True)
        self.main, self.page = self.project.menus
        self.film = self.project.films[0]

    def test_next_free_target(self):
        self.assertIsNone(next_free_target(self.page, BUTTON_CHAPTER, self.film))      # alle 3 Kapitel da
        self.assertEqual(next_free_target(self.page, BUTTON_AUDIO, self.film), "a1")
        b = add_button_of_kind(self.project, self.page.id, BUTTON_SUBTITLE)
        self.assertEqual((b.film_id, b.content_ref), (self.film.id, "s1"))
        b = add_button_of_kind(self.project, self.page.id, BUTTON_SUBTITLE)
        self.assertEqual(b.content_ref, SUBTITLE_OFF)                                   # nach den Spuren „Aus“
        b = add_button_of_kind(self.project, self.page.id, BUTTON_SUBTITLE)
        self.assertIsNone(b.content_ref)                                                # alles da: ohne Ziel
        b = add_button_of_kind(self.project, self.page.id, BUTTON_CHAPTER)
        self.assertIsNone(b.content_ref)

    def test_position_and_nav(self):
        b = add_button_of_kind(self.project, self.main.id, BUTTON_NAV, center=(960, 540), label="EXTRAS")
        self.assertEqual((b.label, b.target, b.position), ("EXTRAS", None, [770, 505]))   # 380 × 70 mittig
        b = add_button_of_kind(self.project, self.main.id, BUTTON_AUDIO, center=(1919, 0))
        self.assertEqual(b.position, [1920 - 380, 0])                                    # im Bild gehalten
        b = add_button_of_kind(self.project, self.main.id, BUTTON_CHAPTER)
        self.assertEqual(b.content_ref, "ch1")                                           # Hauptmenü hat noch keine
        self.assertIsNotNone(b.position)


class TestPreflight(unittest.TestCase):
    def test_issues_name_the_button(self):
        project = make_project(chapters=3, chapter_menu=True)
        main, page = project.menus
        nav = add_button_of_kind(project, main.id, BUTTON_NAV, label="EXTRAS")
        empty = add_button_of_kind(project, page.id, BUTTON_CHAPTER)
        issues = run_preflight(project, check_files=False)
        (warn,) = [i for i in issues if i.level == WARNING and "EXTRAS" in i.message]
        self.assertEqual((warn.node_id, warn.button_id), (main.id, nav.id))
        (err,) = [i for i in issues if i.level == ERROR]
        self.assertEqual((err.node_id, err.button_id), (page.id, empty.id))
        self.assertIn("hat kein Ziel", err.message)

    def test_shape_submenu_hint(self):
        project = make_project(chapters=3, chapter_menu=True)
        page = project.menus[1]
        hint = lambda: [i for i in run_preflight(project) if i.level == INFO and "Form-Buttons" in i.message]
        self.assertEqual(hint(), [])
        page.button_style.kind = STYLE_SHAPE
        (issue,) = hint()
        self.assertEqual(issue.node_id, page.id)
        self.assertIn("kein Hintergrundbild", issue.message)    # auch das Hauptmenü hat keins
        project.main_menu.button_style.kind = STYLE_SHAPE      # Hauptmenü ohne Bild: auch dort (v1.14.5)
        self.assertEqual({i.node_id for i in hint()}, {page.id, project.main_menu.id})
        project.main_menu.background.image = "C:/haupt.png"    # Hauptmenü mit Bild: nur „wie Hauptmenü“
        (issue,) = hint()
        self.assertEqual(issue.node_id, page.id)
        self.assertIn("Hintergrundbild des Hauptmenüs", issue.message)
        page.background.image = "C:/kapitel.png"               # eigener Hintergrund (v1.13): kein Hinweis
        self.assertEqual(hint(), [])


class TestViewer(DesignerCase):
    @property
    def menu(self):
        return self.project.menu(self.page_id)

    def test_markers_and_missing_border(self):
        texts = sorted(m.text for m in self.designer.marker_items)
        self.assertEqual(texts, sorted(["K1", "K2", "K3", "K4", "K5", "K6", "→ Hauptmenü"]))
        self.assertFalse(any(m.missing for m in self.designer.marker_items))
        chapter = self.menu.buttons[0]
        self.ctrl.set_button_content(self.page_id, chapter.id, self.film_id, None)
        app_instance.processEvents()
        self.assertTrue(self.designer.items[chapter.id].missing)
        (marker,) = [m for m in self.designer.marker_items if m.missing]
        self.assertEqual(marker.text, "K?")
        self.win.viewer.chk_markers.setChecked(False)
        app_instance.processEvents()
        self.assertEqual(self.designer.marker_items, [])
        self.assertTrue(self.designer.items[chapter.id].missing)      # der rote Rand bleibt

    def test_marker_below_left_edge_and_hidden_while_dragging(self):
        """v1.15.2: Plakette unter dem Button, bündig links – verdeckt die Form nicht; beim Ziehen ausgeblendet."""
        from PySide6.QtCore import QEvent, QPointF
        chapter = self.menu.buttons[0]
        item = self.designer.items[chapter.id]
        marker = next(m for m in self.designer.marker_items if m.button_id == chapter.id)
        spec = item.spec
        self.assertEqual(marker.pos(), QPointF(spec.x, spec.y + spec.height))
        self.assertGreater(marker.boundingRect().top(), 0)                      # Abstand nach unten
        self.assertEqual(marker.boundingRect().left(), 0)                       # bündig mit der linken Kante
        start = self._center(chapter.id)
        self._mouse(QEvent.MouseButtonPress, start)
        self._mouse(QEvent.MouseMove, start + QPointF(30, 0))
        hidden = [m.button_id for m in self.designer.marker_items if not m.isVisible()]
        self.assertEqual(hidden, [chapter.id])
        self._mouse(QEvent.MouseButtonRelease, start + QPointF(30, 0), buttons=Qt.NoButton)
        self.assertTrue(all(m.isVisible() for m in self.designer.marker_items))

    def test_palette_click_adds_and_selects(self):
        panel = self.win.viewer
        self.assertTrue(panel.palette_buttons[BUTTON_AUDIO].isVisibleTo(panel))
        steps = self.ctrl.undo_stack.count()
        panel.palette_buttons[BUTTON_AUDIO].click()
        app_instance.processEvents()
        new = self.menu.buttons[-1]
        self.assertEqual((new.kind, new.content_ref), (BUTTON_AUDIO, self.project.films[0].audio_tracks[0].id))
        self.assertEqual(self.ctrl.undo_stack.count(), steps + 1)
        self.assertEqual(self.ctrl.selected_button, (self.page_id, new.id))
        self.assertEqual(self.win.inspector.menu_page.mode, "button")
        panel.set_mode("remote")
        self.assertFalse(panel.palette_buttons[BUTTON_AUDIO].isVisibleTo(panel))
        panel.set_mode("design")

    def test_drop_from_palette_places_at_point(self):
        mime = QMimeData()
        mime.setData("application/x-openbdauth-button-kind", b"subtitle")
        point = self.designer.mapFromScene(QPointF(1500, 200))
        event = QDropEvent(QPointF(point), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        self.designer.dropEvent(event)
        app_instance.processEvents()
        new = self.menu.buttons[-1]
        self.assertEqual(new.kind, BUTTON_SUBTITLE)
        cx, cy = new.position[0] + 190, new.position[1] + 35
        self.assertAlmostEqual(cx, 1500, delta=4)
        self.assertAlmostEqual(cy, 200, delta=4)

    def test_issue_click_selects_the_button(self):
        new_id = self.ctrl.add_button(self.page_id, BUTTON_CHAPTER)        # alle Kapitel schon da: ohne Ziel
        self.ctrl.select_button(None, None)
        self.win.open_export_dialog()
        dialog = self.win._export_dialog
        items = [dialog.issue_list.item(i) for i in range(dialog.issue_list.count())]
        (item,) = [i for i in items if i.data(Qt.UserRole + 1) == new_id]
        dialog._on_issue_clicked(item)
        app_instance.processEvents()
        self.assertEqual(self.ctrl.selected_button, (self.page_id, new_id))
        self.assertEqual(self.win.inspector.menu_page.mode, "button")
        dialog.close()


if __name__ == "__main__":
    unittest.main()
