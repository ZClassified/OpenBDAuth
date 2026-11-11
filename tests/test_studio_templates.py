# tests/test_studio_templates.py
"""
Inhalts-Menüs in der Oberfläche: Vorschläge, Anlege-Fenster, „＋ Button“, Inspektor, Rückgängig
(v1.9.1, ab v1.9.8 nach den Bedienregeln aus Konzept 2.1).
"""

import os
import sys
import unittest
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from core.disc_edit import add_track, set_chapter_times, TRACK_AUDIO, TRACK_SUBTITLE
from core.disc_model import BUTTON_CHAPTER
from core.menu_templates import (
    TemplateError, chapter_menus, suggestions, LANG_SEPARATE, LANG_SUBTITLES,
    ACTION_CHAPTER_MENU, ACTION_LANGUAGE_MENU,
)
from gui.node_editor.rows import film_rows, menu_rows, ROW_SUGGEST, ROW_OUTPUT

app_instance = QApplication.instance() or QApplication(sys.argv)


class StudioCase(unittest.TestCase):
    def setUp(self):
        from gui.studio.main_window import StudioWindow
        self.win = StudioWindow(persist_layout=False)
        self.ctrl = self.win.controller
        film = self.ctrl.project.films[0]
        film.video_base = "film.264"
        set_chapter_times(film, [f"00:{i:02d}:00.000" for i in range(12)])
        for lang in ("deu", "eng"):
            add_track(film, TRACK_AUDIO, f"{lang}.ac3", lang)
        add_track(film, TRACK_SUBTITLE, "deu.sup", "deu")
        self.film_id = film.id
        self.ctrl.changed.emit()
        app_instance.processEvents()

    def tearDown(self):
        self.ctrl.undo_stack.setClean()
        self.win.close()

    @property
    def project(self):
        return self.ctrl.project

    def _select(self, node_id):
        self.win.scene.rebuild()
        self.win.scene.select_node(node_id)
        app_instance.processEvents()

    def _suggestion(self, menu_id, action):
        return next(s for s in suggestions(self.project, self.project.menu(menu_id)) if s.action == action)


class TestControllerAndRows(StudioCase):
    def test_template_is_one_undo_step(self):
        steps = self.ctrl.undo_stack.count()
        menus_before = len(self.project.menus)
        pages = self.ctrl.create_chapter_menus(self.film_id)
        self.assertEqual(len(pages), 2)
        self.assertEqual(self.ctrl.undo_stack.count(), steps + 1)
        self.assertEqual(self.project.main_menu.buttons[-1].target, pages[0])
        self.ctrl.undo_stack.undo()
        self.assertEqual(len(self.project.menus), menus_before)
        self.assertEqual(len(self.project.main_menu.buttons), 1)
        self.ctrl.undo_stack.redo()
        self.assertEqual([m.id for m in chapter_menus(self.project, self.film_id)], pages)

    def test_error_leaves_no_step(self):
        set_chapter_times(self.project.films[0], [])
        steps = self.ctrl.undo_stack.count()
        with self.assertRaises(TemplateError):
            self.ctrl.create_chapter_menus(self.film_id)
        self.assertEqual(self.ctrl.undo_stack.count(), steps)

    def test_film_node_has_no_chips(self):
        # v1.9.8: Menüs schlägt das Menü vor, das zum Film führt – der Film-Knoten zeigt nur „Ende“
        rows = film_rows(self.project.film(self.film_id), self.project)
        self.assertEqual([(r.kind, r.text) for r in rows], [(ROW_OUTPUT, "Ende")])

    def test_deleting_a_menu_takes_its_link_button(self):
        pages = self.ctrl.create_chapter_menus(self.film_id)
        main = self.project.main_menu
        self.assertEqual([b.label for b in main.buttons], ["FILM STARTEN", "KAPITEL"])
        own = self.ctrl.add_nav_button(main.id, "EXTRAS")
        from core.disc_rules import Source
        self.ctrl.connect(Source.button(main.id, own), pages[1])      # selbst verbunden: bleibt beim Löschen
        self.ctrl.remove_menus([pages[0]])
        main = self.project.main_menu
        self.assertEqual([b.label for b in main.buttons], ["FILM STARTEN", "EXTRAS"])
        self.assertEqual(self._suggestions(), ["＋ SPRACHE"])          # Kapitelseite 2 zeigt noch Kapitel
        self.ctrl.remove_menus([pages[1]])
        self.assertIsNone(self.project.main_menu.buttons[-1].target)   # EXTRAS bleibt, unverbunden
        self.assertEqual(self._suggestions(), ["＋ KAPITEL", "＋ SPRACHE"])   # Vorschlag ist wieder da
        self.ctrl.undo_stack.undo()
        self.ctrl.undo_stack.undo()
        self.assertEqual([b.label for b in self.project.main_menu.buttons], ["FILM STARTEN", "KAPITEL", "EXTRAS"])

    def _suggestions(self):
        return [r.text for r in menu_rows(self.project, self.project.main_menu) if r.kind == ROW_SUGGEST]


class TestSuggestions(StudioCase):
    def _suggestions(self, menu=None):
        menu = menu or self.project.main_menu
        return [(r.text, r.action) for r in menu_rows(self.project, menu) if r.kind == ROW_SUGGEST]

    def test_main_menu_suggests_until_created(self):
        self.assertEqual(self._suggestions(), [("＋ KAPITEL", ACTION_CHAPTER_MENU), ("＋ SPRACHE", ACTION_LANGUAGE_MENU)])
        self.ctrl.create_chapter_menus(self.film_id)
        self.assertEqual(self._suggestions(), [("＋ SPRACHE", ACTION_LANGUAGE_MENU)])
        # aus dem Vorschlag wird ein echter Button im Hauptmenü
        self.assertEqual(self.project.main_menu.buttons[-1].label, "KAPITEL")

    def test_not_needed_hides_suggestion_and_preflight_hint(self):
        from core.preflight import run_preflight, INFO
        infos = lambda: [i.message for i in run_preflight(self.project)
                         if i.level == INFO and "Form-Buttons" not in i.message]   # Startvorlage: Form ohne Bild
        self.assertEqual(len(infos()), 2)
        self.ctrl.dismiss_hint(self.film_id, ACTION_LANGUAGE_MENU)
        self.assertEqual(self._suggestions(), [("＋ KAPITEL", ACTION_CHAPTER_MENU)])
        self.assertEqual(len(infos()), 1)
        self.ctrl.undo_stack.undo()
        self.assertEqual(len(self._suggestions()), 2)

    def test_click_on_suggestion_row_opens_popup_and_creates(self):
        from PySide6.QtCore import Qt, QPointF
        from PySide6.QtTest import QTest
        self.win.show()
        self.win.scene.rebuild()
        app_instance.processEvents()
        item = self.win.scene.nodes[self.project.main_menu.id]
        index = next(i for i, r in enumerate(item.rows) if r.kind == ROW_SUGGEST and r.action == ACTION_LANGUAGE_MENU)
        point = item.mapToScene(QPointF(item.width / 2, item.row_center_y(index)))
        self.win.view.centerOn(point)
        app_instance.processEvents()
        with mock.patch("gui.node_editor.create_popup.CreatePopup.exec_at", return_value=True):
            QTest.mouseClick(self.win.view.viewport(), Qt.LeftButton, pos=self.win.view.mapFromScene(point))
            app_instance.processEvents()
        (menu,) = [m for m in self.project.menus if m.name == "Ton & Untertitel"]
        self.assertEqual(self.win.scene.selected_node_id(), menu.id)
        self.assertEqual(self.project.main_menu.buttons[-1].label, "SPRACHE")

    def test_popup_dismiss_hides_suggestion(self):
        from gui.node_editor.create_popup import CreatePopup

        def dismiss(popup, _pos):
            popup.btn_dismiss.click()
            return False
        with mock.patch.object(CreatePopup, "exec_at", dismiss):
            self.win.scene.activate_suggestion(self._suggestion(self.project.main_menu.id, ACTION_CHAPTER_MENU))
        self.assertEqual(self._suggestions(), [("＋ SPRACHE", ACTION_LANGUAGE_MENU)])
        self.assertEqual(len(self.project.menus), 1)

    def test_language_menu_suggests_nothing_to_add(self):
        """v1.12 (Vorschlag B): fehlende Spuren schlägt das Menü nicht mehr vor; ergänzt wird von Hand."""
        (subs,) = self.ctrl.create_language_menus(self.film_id, LANG_SUBTITLES)
        self.assertEqual(self.project.main_menu.buttons[-1].label, "UNTERTITEL")
        menu = self.project.menu(subs)
        add_track(self.project.film(self.film_id), TRACK_SUBTITLE, "eng.sup", "eng")
        self.assertEqual(self._suggestions(menu), [])


class TestPopup(StudioCase):
    def test_chapters_preview_and_create(self):
        from gui.node_editor.create_popup import CreatePopup, apply_suggestion
        popup = CreatePopup(self.ctrl, self._suggestion(self.project.main_menu.id, ACTION_CHAPTER_MENU))
        self.assertEqual(popup.lbl_title.text(), "Kapitelmenü für „Hauptfilm“")
        self.assertEqual(popup.lbl_preview.text(), "12 Kapitel, 8 pro Seite → 2 Seite(n)")
        popup.spin_per_page.setValue(4)
        self.assertIn("→ 3 Seite(n)", popup.lbl_preview.text())
        created, text = apply_suggestion(self.ctrl, popup.suggestion, popup.options())
        self.assertEqual((len(created), text), (3, "Kapitelmenü angelegt: 3 Seiten"))

    def test_language_modes_follow_tracks(self):
        from gui.node_editor.create_popup import CreatePopup, apply_suggestion
        s = self._suggestion(self.project.main_menu.id, ACTION_LANGUAGE_MENU)
        self.assertTrue(s.needs_choice)
        popup = CreatePopup(self.ctrl, s)
        self.assertEqual(list(popup.radios), ["combined", "separate", "subtitles", "audio"])
        self.assertEqual(popup.radios["combined"].text(), "Eine Seite – Ton links, Untertitel rechts")
        self.assertTrue(popup.radios["combined"].isChecked())
        popup.radios[LANG_SEPARATE].setChecked(True)
        created, _text = apply_suggestion(self.ctrl, s, popup.options())
        self.assertEqual([self.project.menu(m).name for m in created], ["Ton", "Untertitel"])
        # nur eine Tonspur: nur „Nur Untertitel“ – nichts zu entscheiden, der Klick legt direkt an
        self.ctrl.undo_stack.undo()
        film = self.project.film(self.film_id)
        film.audio_tracks = film.audio_tracks[:1]
        s = self._suggestion(self.project.main_menu.id, ACTION_LANGUAGE_MENU)
        self.assertEqual((s.label, s.needs_choice), ("UNTERTITEL", False))

    def test_real_popup_stays_open_and_closes_on_outside_click(self):
        # v1.9.10-Fehler: das Fenster schloss sich sofort wieder. Jetzt ohne natives Popup: Loslassen der
        # Maus schließt nichts, ein Klick daneben schon, „Anlegen“ legt an.
        from PySide6.QtCore import Qt, QPoint, QTimer
        from PySide6.QtTest import QTest
        from gui.node_editor.create_popup import CreatePopup
        self.win.show()
        app_instance.processEvents()
        viewport = self.win.view.viewport()
        s = self._suggestion(self.project.main_menu.id, ACTION_CHAPTER_MENU)
        popup = CreatePopup(self.ctrl, s, parent=self.win.view)
        seen = []

        def outside():
            seen.append(popup.isVisible())
            QTest.mouseRelease(viewport, Qt.LeftButton, pos=QPoint(5, 5))   # Loslassen daneben: bleibt offen
            seen.append(popup.isVisible())
            QTest.mousePress(viewport, Qt.LeftButton, pos=QPoint(5, 5))     # Klick daneben: schließt
            seen.append(popup.isVisible())
        QTimer.singleShot(100, outside)
        self.assertFalse(popup.exec_at(QPoint(900, 40)))
        self.assertEqual(seen, [True, True, False])
        self.assertEqual(len(self.project.menus), 1)                     # nichts angelegt
        popup = CreatePopup(self.ctrl, s, parent=self.win.view)
        QTimer.singleShot(100, popup.btn_create.click)
        self.assertTrue(popup.exec_at(QPoint(900, 40)))

    def test_offers_of_add_button(self):
        scene = self.win.scene
        main = self.project.main_menu
        chosen = []

        def choose(offers, screen):
            chosen.append([(o.action, o.film_id) for o in offers])
            return next(o for o in offers if o.action == ACTION_LANGUAGE_MENU)
        scene._choose_offer = choose
        with mock.patch("gui.node_editor.create_popup.CreatePopup.exec_at", return_value=True):
            scene.offer_add(main.id)
        self.assertEqual(chosen, [[(ACTION_CHAPTER_MENU, self.film_id), (ACTION_LANGUAGE_MENU, self.film_id)]])
        self.assertEqual(self.project.main_menu.buttons[-1].label, "SPRACHE")
        # nichts mehr anzubieten außer dem Kapitelmenü; ohne Angebote fragt „＋ Button“ gleich nach dem Text
        self.ctrl.create_chapter_menus(self.film_id)
        prompted = []
        scene._prompt_add_button = prompted.append
        scene.offer_add(main.id)
        self.assertEqual(prompted, [main.id])


class TestSceneActions(StudioCase):
    def test_activate_creates_and_selects(self):
        scene = self.win.scene
        with mock.patch("gui.node_editor.create_popup.CreatePopup.exec_at", return_value=True):
            scene.activate_suggestion(self._suggestion(self.project.main_menu.id, ACTION_LANGUAGE_MENU))
        app_instance.processEvents()
        (menu,) = [m for m in self.project.menus if m.name == "Ton & Untertitel"]
        self.assertEqual(scene.selected_node_id(), menu.id)
        self.assertIs(self.win.inspector.stack.currentWidget(), self.win.inspector.menu_page)

    def test_error_goes_to_status_bar(self):
        messages = []
        self.win.scene.status_message.connect(messages.append)
        s = self._suggestion(self.project.main_menu.id, ACTION_LANGUAGE_MENU)
        film = self.project.film(self.film_id)
        film.audio_tracks, film.subtitle_tracks = film.audio_tracks[:1], []
        from core.menu_templates import Suggestion
        stale = Suggestion(s.action, s.label, s.menu_id, s.film_id)   # veralteter Vorschlag, keine Spuren mehr
        self.win.scene.activate_suggestion(stale)
        self.assertEqual(len(messages), 1)
        self.assertIn("keine Spuren", messages[0])


class TestInspector(StudioCase):
    def test_film_page_creates_nothing(self):
        # Konzept 2.1, Regel 1: der Inspektor zeigt Eigenschaften, Menüs entstehen in der Node-Ansicht
        from PySide6.QtWidgets import QPushButton
        self._select(self.film_id)
        page = self.win.inspector.film_page
        texts = [b.text() for b in page.findChildren(QPushButton)]
        self.assertFalse(any("menü" in t.lower() or "Vorlage" in t for t in texts), texts)

    def test_menu_page_content_and_layout(self):
        p1, p2 = self.ctrl.create_chapter_menus(self.film_id)
        self._select(p1)
        page = self.win.inspector.menu_page
        self.assertTrue(page.card_content.isVisibleTo(page))
        self.assertIn("Hauptfilm", page.lbl_source.text())
        # v1.12: kein Kapitelbereich und keine Layout-Art mehr; Buttons sind frei
        for gone in ("btn_range", "combo_layout", "grid_row", "btn_reset_layout", "btn_add_missing"):
            self.assertFalse(hasattr(page, gone), gone)

    def test_main_menu_has_no_content_card(self):
        self._select(self.project.main_menu.id)
        page = self.win.inspector.menu_page
        self.assertFalse(page.card_content.isVisibleTo(page))
        self.assertFalse(page.sec_geometry.isVisibleTo(page))         # Form & Position nur mit ausgewähltem Button
        main = self.project.main_menu
        self.ctrl.select_button(main.id, main.buttons[0].id)
        app_instance.processEvents()
        self.assertTrue(page.sec_geometry.isVisibleTo(page))
        self.assertFalse(page.card_content.isVisibleTo(page))


class TestFilmColor(StudioCase):
    def test_pick_palette_and_custom_colour(self):
        from PySide6.QtGui import QColor
        from core.disc_model import FILM_COLORS
        self._select(self.film_id)
        page = self.win.inspector.film_page
        film = self.project.film(self.film_id)
        self.assertEqual(page.btn_color.color(), film.color)
        steps = self.ctrl.undo_stack.count()
        page.btn_color.swatches[3].click()
        app_instance.processEvents()
        self.assertEqual(self.project.film(self.film_id).color, FILM_COLORS[3])
        self.assertEqual(self.ctrl.undo_stack.count(), steps + 1)
        self.assertIn(FILM_COLORS[3], page.card_name.title_label.styleSheet())
        with mock.patch("PySide6.QtWidgets.QColorDialog.getColor", return_value=QColor("#123456")):
            page.btn_color.act_custom.trigger()
        app_instance.processEvents()
        self.assertEqual(self.project.film(self.film_id).color, "#123456")
        self.ctrl.undo_stack.undo()
        self.assertEqual(self.project.film(self.film_id).color, FILM_COLORS[3])
        # neue Filme bekommen ihre Farbe weiterhin automatisch
        second = self.ctrl.add_film("Zweiter", (0, 400))
        self.assertEqual(self.project.film(second).color, FILM_COLORS[1])


if __name__ == "__main__":
    unittest.main()
