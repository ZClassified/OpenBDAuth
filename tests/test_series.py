# tests/test_series.py
"""Mehrere Filme (v1.9.6): Filmauswahl, „wie bei …“, Vorschläge nur für direkt verlinkte Filme."""

import os
import sys
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from core.disc_adapter import build_export_plan
from core.disc_edit import starter_project, add_film, add_track, set_chapter_times, add_nav_button, TRACK_AUDIO, TRACK_SUBTITLE
from core.disc_model import BUTTON_NAV, STYLE_SHAPE
from core.menu_design import move_items, set_dpad
from core.menu_guides import add_guide, guides
from core.menu_templates import (
    TemplateError, create_chapter_menus, create_language_menus, create_titles_menu, create_menus_like,
    chapter_menus, main_links_to, suggest_titles_menu, titles_menu, film_language_menu,
    KIND_CHAPTERS, KIND_LANGUAGE, HINT_TITLES_MENU,
)
from core.preflight import run_preflight, INFO


def series(n=3, chapters=10):
    project = starter_project()
    films = [project.films[0]]
    films[0].name = "Folge 1"
    for i in range(2, n + 1):
        films.append(add_film(project, f"Folge {i}", (720.0, i * 200.0)))
    for f in films:
        f.video_base = f"{f.name}.264"
        set_chapter_times(f, [f"00:{i:02d}:00.000" for i in range(chapters)])
        for lang in ("deu", "eng"):
            add_track(f, TRACK_AUDIO, f"{lang}.ac3", lang)
        add_track(f, TRACK_SUBTITLE, "deu.sup", "deu")
    return project, films


def suggestion_texts(project, menu=None):
    from gui.node_editor.rows import suggestion_rows
    return [r.text for r in suggestion_rows(project, menu or project.main_menu)]


class TestSingleFilmUnchanged(unittest.TestCase):
    def test_single_film_sees_nothing_new(self):
        project, (film,) = series(n=1)
        self.assertFalse(suggest_titles_menu(project))
        self.assertEqual(suggestion_texts(project), ["＋ KAPITEL", "＋ SPRACHE"])
        create_chapter_menus(project, film.id, link_from_main=None)
        self.assertEqual(project.main_menu.buttons[-1].label, "KAPITEL")   # direkt verlinkter Film: wie bisher


class TestTitlesMenu(unittest.TestCase):
    def test_suggest_create_and_export(self):
        project, films = series(n=3)
        self.assertIn("＋ FILME", suggestion_texts(project))
        menu = create_titles_menu(project)
        self.assertEqual(titles_menu(project), menu)
        self.assertEqual([(b.label, b.target) for b in menu.buttons],
                         [("FOLGE 1", films[0].id), ("FOLGE 2", films[1].id), ("FOLGE 3", films[2].id),
                          ("ZURÜCK", project.main_menu.id)])
        self.assertEqual((project.main_menu.buttons[-1].label, project.main_menu.buttons[-1].target), ("FILME", menu.id))
        self.assertNotIn("＋ FILME", suggestion_texts(project))
        plan = build_export_plan(project)
        specs = dict(plan.pages_specs)[plan.page_ids[menu.id]]
        self.assertEqual([(s.action_type, s.target_title_id) for s in specs[:3]],
                         [("jump_title", 1), ("jump_title", 2), ("jump_title", 3)])

    def test_dismiss_and_minimum(self):
        project, _ = series(n=3)
        project.settings.dismissed_hints.append(HINT_TITLES_MENU)
        self.assertFalse(suggest_titles_menu(project))
        two, _ = series(n=2)
        self.assertFalse(suggest_titles_menu(two))
        one, _ = series(n=1)
        with self.assertRaises(TemplateError):
            create_titles_menu(one)


class TestLinkRule(unittest.TestCase):
    def test_only_directly_linked_films_get_main_buttons_and_suggestions(self):
        project, films = series(n=3)
        self.assertTrue(main_links_to(project, films[0].id))
        self.assertFalse(main_links_to(project, films[1].id))
        self.assertEqual([t for t in suggestion_texts(project) if "KAPITEL" in t], ["＋ KAPITEL"])
        before = len(project.main_menu.buttons)
        create_chapter_menus(project, films[1].id, link_from_main=None)
        self.assertEqual(len(project.main_menu.buttons), before)                 # Folge 2: kein Button im Hauptmenü
        infos = [i.message for i in run_preflight(project) if i.level == INFO]
        self.assertFalse(any("Folge 3" in m for m in infos))                     # keine Hinweise pro Folge


class TestCreateLike(unittest.TestCase):
    def test_chapters_take_over_split_and_design(self):
        project, films = series(n=2, chapters=6)
        src_pages = create_chapter_menus(project, films[0].id, per_page=4)
        first = src_pages[0]
        first.button_style.kind = STYLE_SHAPE
        move_items(project, first.id, positions={first.buttons[0].id: (300, 120), first.buttons[-1].id: (100, 900)})
        first.buttons[1].size = [200, 20]
        set_dpad(project, first.id, first.buttons[0].id, "up", first.buttons[-1].id)
        g = add_guide(project, first.id, ("left", 0.382), ("right", 0.382))
        set_chapter_times(films[1], [f"00:{i:02d}:00.000" for i in range(10)])
        pages = create_menus_like(project, films[0].id, films[1].id, KIND_CHAPTERS)
        self.assertEqual(len(pages), 3)                                            # 10 Kapitel, 4 pro Seite
        self.assertEqual(chapter_menus(project, films[1].id), pages)
        copy = pages[0]
        self.assertEqual(copy.button_style, first.button_style)
        self.assertEqual([b.position for b in copy.buttons], [b.position for b in first.buttons])
        self.assertEqual(copy.buttons[1].size, [200, 20])
        self.assertEqual(copy.buttons[0].dpad, {"up": copy.buttons[-1].id})
        self.assertEqual(len(guides(project, copy.id)), 1)
        self.assertNotEqual(guides(project, copy.id)[0].id, g.id)
        self.assertTrue(all(b.film_id == films[1].id for b in copy.buttons if b.is_content))

    def test_language_mode_follows_source(self):
        project, films = series(n=2)
        (combined,) = create_language_menus(project, films[0].id)
        (copy,) = create_menus_like(project, films[0].id, films[1].id, KIND_LANGUAGE)
        self.assertEqual(copy.name, combined.name)
        self.assertEqual(copy.default_film_id, films[1].id)
        self.assertEqual(film_language_menu(project, films[1].id), copy)
        self.assertIn(("FILM STARTEN", films[1].id), [(b.label, b.target) for b in copy.buttons if b.kind == BUTTON_NAV])
        films[1].subtitle_tracks = []
        project2, films2 = series(n=2)
        create_language_menus(project2, films2[0].id, mode="separate")
        films2[1].subtitle_tracks = []
        with self.assertRaises(TemplateError):
            create_menus_like(project2, films2[0].id, films2[1].id, KIND_LANGUAGE)


class TestSeriesUI(unittest.TestCase):
    def setUp(self):
        from PySide6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication(sys.argv)
        from gui.studio.main_window import StudioWindow
        project, self.films = series(n=3)
        self.win = StudioWindow(project, persist_layout=False)
        self.ctrl = self.win.controller

    def tearDown(self):
        self.ctrl.undo_stack.setClean()
        self.win.close()

    def _select(self, node_id):
        self.win.scene.rebuild()
        self.win.scene.select_node(node_id)
        self.app.processEvents()

    def test_like_option_only_where_it_helps(self):
        from core.menu_templates import button_offers, ACTION_CHAPTER_MENU
        from gui.node_editor.create_popup import CreatePopup, apply_suggestion, CHOICE_LIKE
        project = self.ctrl.project
        main = project.main_menu
        offer = lambda film: next(o for o in button_offers(project, main)
                                  if o.action == ACTION_CHAPTER_MENU and o.film_id == film.id)
        popup = CreatePopup(self.ctrl, offer(self.films[1]))
        self.assertNotIn(CHOICE_LIKE, popup.radios)                               # noch kein Vorbild
        self.ctrl.create_chapter_menus(self.films[0].id)
        popup = CreatePopup(self.ctrl, offer(self.films[1]))
        self.assertIn(CHOICE_LIKE, popup.radios)
        self.assertEqual(popup.radios[CHOICE_LIKE].text(), "Wie bei „Folge 1“ – Aufteilung und Gestaltung übernehmen")
        popup.radios[CHOICE_LIKE].setChecked(True)
        self.assertFalse(popup.spin_per_page.isEnabled())                          # Aufteilung kommt vom Vorbild
        steps = self.ctrl.undo_stack.count()
        created, _text = apply_suggestion(self.ctrl, popup.suggestion, popup.options())
        self.assertEqual(self.ctrl.undo_stack.count(), steps + 1)
        self.assertEqual(len(chapter_menus(self.ctrl.project, self.films[1].id)), 2)
        back = next(b for b in self.ctrl.project.menu(created[0]).buttons if b.label == "ZURÜCK")
        self.assertEqual(back.target, main.id)
        # von „＋ Button“ im Hauptmenü angelegt: dort verlinkt
        self.assertEqual(self.ctrl.project.main_menu.buttons[-1].target, created[0])

    def test_titles_suggestion_and_not_needed(self):
        from core.menu_templates import suggestions, ACTION_TITLES_MENU
        project = self.ctrl.project
        (films,) = [s for s in suggestions(project, project.main_menu) if s.action == ACTION_TITLES_MENU]
        self.assertFalse(films.needs_choice)                                      # nichts zu entscheiden: direkt
        self.win.scene.activate_suggestion(films)
        self.app.processEvents()
        menu = titles_menu(self.ctrl.project)
        self.assertEqual(self.win.scene.selected_node_id(), menu.id)
        self.ctrl.undo_stack.undo()
        self.ctrl.dismiss_hint(None, "titles_menu")
        self.assertNotIn("＋ FILME", suggestion_texts(self.ctrl.project))
        self.ctrl.undo_stack.undo()
        self.assertIn("＋ FILME", suggestion_texts(self.ctrl.project))


class TestSuggestionRule(unittest.TestCase):
    """Konzept 2.1, Regel 2: Vorschläge im Menü, das zu genau einem Film mit Kapiteln/Spuren führt."""

    def test_film_plus_bonus_without_content_still_suggests(self):
        project, (film,) = series(n=1)
        bonus = add_film(project, "Bonus", (720.0, 400.0))
        add_track(bonus, TRACK_AUDIO, "b.ac3", "deu")                            # nichts zu wählen
        add_nav_button(project, project.main_menu.id, "BONUS", bonus.id)
        self.assertEqual(suggestion_texts(project), ["＋ KAPITEL", "＋ SPRACHE"])

    def test_menu_leading_to_several_films_suggests_nothing(self):
        project, films = series(n=2)
        add_nav_button(project, project.main_menu.id, "FOLGE 2", films[1].id)
        self.assertEqual(suggestion_texts(project), [])                         # alles über „＋ Button“
        from core.menu_templates import button_offers
        offers = [(o.action, o.film_id) for o in button_offers(project, project.main_menu)]
        self.assertIn(("chapter_menu", films[1].id), offers)
        self.assertIn(("titles_menu", None), offers)

    def test_episode_menu_suggests_and_links_there(self):
        from core.disc_edit import add_menu
        project, films = series(n=3)
        episode = add_menu(project, "Folge 2", (800.0, 600.0))
        add_nav_button(project, episode.id, "FILM STARTEN", films[1].id)
        self.assertEqual(suggestion_texts(project, episode), ["＋ KAPITEL", "＋ SPRACHE"])
        pages = create_chapter_menus(project, films[1].id, per_page=4, parent_id=episode.id)
        self.assertEqual((episode.buttons[-1].label, episode.buttons[-1].target), ("KAPITEL", pages[0].id))
        self.assertEqual(pages[0].buttons[[b.label for b in pages[0].buttons].index("ZURÜCK")].target, episode.id)
        self.assertEqual(suggestion_texts(project, episode), ["＋ SPRACHE"])
        infos = [i.message for i in run_preflight(project) if i.level == INFO]
        self.assertTrue(any("Folge 2" in m and "Sprachmenü" in m for m in infos))  # Hinweis nach derselben Regel

    def test_content_menus_do_not_suggest_other_menus(self):
        project, (film,) = series(n=1)
        (language,) = create_language_menus(project, film.id)
        self.assertEqual(suggestion_texts(project, language), [])               # führt zum Film, zeigt aber Inhalte


if __name__ == "__main__":
    unittest.main()
