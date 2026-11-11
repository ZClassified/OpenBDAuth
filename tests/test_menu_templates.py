# tests/test_menu_templates.py
"""Inhalts-Menüs aus Vorlagen (v1.9.0; ab v1.12 einmalig angeordnete, freie Buttons): Seiten, Verdrahtung,
Lage und Pfeiltasten."""

import unittest

from core.disc_adapter import build_export_plan
from tests.project_factory import text_starter
from core.disc_edit import starter_project, add_track, set_chapter_times, TRACK_AUDIO, TRACK_SUBTITLE
from core.disc_model import (
    DiscProject, BUTTON_NAV, BUTTON_CHAPTER, BUTTON_AUDIO, BUTTON_SUBTITLE, SUBTITLE_OFF,
)
from core.menu_templates import (
    TemplateError, create_chapter_menus, create_language_menus, chapter_menus, missing_chapters,
    suggest_language_mode, LANG_COMBINED, LANG_SEPARATE, LANG_AUDIO, LANG_SUBTITLES,
)


def make_project(chapters=0, audio=("deu",), subs=()):
    project = text_starter()
    film = project.films[0]
    film.video_base = "film.264"
    set_chapter_times(film, [f"00:{i:02d}:00.000" for i in range(chapters)])
    for lang in audio:
        add_track(film, TRACK_AUDIO, f"ton_{lang}.ac3", lang)
    for lang in subs:
        add_track(film, TRACK_SUBTITLE, f"ut_{lang}.sup", lang)
    return project, film


def nav_targets(menu):
    return [(b.label, b.target) for b in menu.buttons if b.kind == BUTTON_NAV]


def columns_rows(menu, kind):
    """Anzahl verschiedener Spalten und Reihen der Inhalts-Buttons einer Art."""
    buttons = [b for b in menu.buttons if b.kind == kind]
    return len({b.position[0] for b in buttons}), len({b.position[1] for b in buttons})


def reachable(specs):
    """Alle Buttons, die vom ersten Button aus mit den Pfeiltasten erreichbar sind."""
    by_id = {s.button_id: s for s in specs}
    seen, todo = set(), [specs[0].button_id]
    while todo:
        bid = todo.pop()
        if bid in seen:
            continue
        seen.add(bid)
        s = by_id[bid]
        todo += [s.upper_id, s.lower_id, s.left_id, s.right_id]
    return seen


class TestChapterTemplate(unittest.TestCase):
    def test_pages_and_wiring(self):
        project, film = make_project(chapters=20)
        main = project.main_menu
        pages = create_chapter_menus(project, film.id)
        p1, p2, p3 = pages
        self.assertEqual([p.name for p in pages], ["Kapitel 1/3", "Kapitel 2/3", "Kapitel 3/3"])
        self.assertEqual([len([b for b in p.buttons if b.kind == BUTTON_CHAPTER]) for p in pages], [8, 8, 4])
        self.assertEqual(nav_targets(p1), [("ZURÜCK", main.id), ("WEITER", p2.id)])
        self.assertEqual(nav_targets(p2), [("ZURÜCK", p1.id), ("HAUPTMENÜ", main.id), ("WEITER", p3.id)])
        self.assertEqual(nav_targets(p3), [("ZURÜCK", p2.id), ("HAUPTMENÜ", main.id)])
        self.assertEqual((main.buttons[-1].label, main.buttons[-1].target), ("KAPITEL", p1.id))
        for p in pages:
            self.assertEqual(p.default_film_id, film.id)
            self.assertTrue(all(b.film_id == film.id for b in p.buttons if b.is_content))
            self.assertTrue(all(b.position is not None for b in p.buttons))
            self.assertIn(p.id, project.view.node_positions)
        self.assertEqual(columns_rows(p1, BUTTON_CHAPTER), (4, 2))
        self.assertEqual(chapter_menus(project, film.id), pages)
        self.assertEqual(missing_chapters(project, film.id), [])
        # Knoten liegen nicht übereinander
        positions = [tuple(project.view.node_positions[n]) for n in project.view.node_positions]
        self.assertEqual(len(positions), len(set(positions)))

    def test_single_page_and_errors(self):
        project, film = make_project(chapters=5)
        (page,) = create_chapter_menus(project, film.id, link_from_main=False)
        self.assertEqual(page.name, "Kapitel")
        self.assertEqual(columns_rows(page, BUTTON_CHAPTER), (4, 2))
        few, film3 = make_project(chapters=3)
        (short,) = create_chapter_menus(few, film3.id)
        self.assertEqual(columns_rows(short, BUTTON_CHAPTER), (3, 1))
        self.assertEqual(nav_targets(page), [("ZURÜCK", project.main_menu.id)])
        self.assertEqual(len(project.main_menu.buttons), 1)   # nicht verlinkt
        empty, film2 = make_project(chapters=0)
        with self.assertRaises(TemplateError):
            create_chapter_menus(empty, film2.id)

    def test_export_positions_and_dpad(self):
        project, film = make_project(chapters=11)
        pages = create_chapter_menus(project, film.id)
        plan = build_export_plan(project)
        self.assertEqual(plan.page_ids[project.main_menu.id], 1)   # Seite 0: unsichtbare Startseite (v1.13)
        specs_by_page = dict(plan.pages_specs)
        p1 = specs_by_page[plan.page_ids[pages[0].id]]
        chapters, nav = p1[:8], p1[8:]
        self.assertEqual([s.action_type for s in chapters], ["play_chapter"] * 8)
        self.assertEqual([s.target_chapter_id for s in chapters], list(range(1, 9)))
        self.assertEqual([(s.action_type, s.target_page_id) for s in nav],
                         [("set_page", plan.page_ids[project.main_menu.id]), ("set_page", plan.page_ids[pages[1].id])])
        # Raster 4 × 2, Navigation darunter
        self.assertEqual(len({s.x for s in chapters}), 4)
        self.assertEqual(len({s.y for s in chapters}), 2)
        self.assertTrue(all(n.y > max(s.y for s in chapters) for n in nav))
        # Pfeiltasten: in der Reihe, aus der unteren Reihe in die Navigation und zurück
        c = {s.button_id: s for s in p1}
        self.assertEqual(c[1].right_id, 2)
        self.assertEqual(c[4].right_id, 1)
        self.assertEqual(c[1].lower_id, 5)
        self.assertIn(c[5].lower_id, (9, 10))
        self.assertIn(c[9].upper_id, (5, 6, 7, 8))
        self.assertEqual(c[9].right_id, 10)
        for _, specs in plan.pages_specs:
            self.assertEqual(reachable(specs), {s.button_id for s in specs})
            for s in specs:
                self.assertTrue(0 <= s.x and s.x + s.width <= 1920 and 0 <= s.y and s.y + s.height <= 1080)
        # Letzte Seite mit 3 Kapiteln: Plätze und Navigationszeile stehen wie auf Seite 1
        p2 = specs_by_page[plan.page_ids[pages[1].id]]
        self.assertEqual([(s.x, s.y) for s in p2[:3]], [(s.x, s.y) for s in chapters[:3]])
        self.assertEqual({s.y for s in p2[3:]}, {s.y for s in nav})


class TestLanguageTemplate(unittest.TestCase):
    def test_suggestions(self):
        self.assertEqual(suggest_language_mode(make_project(audio=("deu", "eng"), subs=("deu",))[1]), LANG_COMBINED)
        self.assertEqual(suggest_language_mode(make_project(audio=("deu",) * 5, subs=("deu",))[1]), LANG_SEPARATE)
        self.assertEqual(suggest_language_mode(make_project(audio=("deu",), subs=("deu", "eng"))[1]), LANG_SUBTITLES)
        self.assertEqual(suggest_language_mode(make_project(audio=("deu", "eng"))[1]), LANG_AUDIO)
        self.assertIsNone(suggest_language_mode(make_project(audio=("deu",))[1]))

    def test_combined_page(self):
        project, film = make_project(audio=("deu", "eng"), subs=("deu", "eng"))
        (menu,) = create_language_menus(project, film.id)
        self.assertEqual(menu.name, "Ton & Untertitel")
        self.assertEqual([b.kind for b in menu.buttons],
                         [BUTTON_AUDIO, BUTTON_AUDIO, BUTTON_SUBTITLE, BUTTON_SUBTITLE, BUTTON_SUBTITLE,
                          BUTTON_NAV, BUTTON_NAV])
        self.assertEqual(menu.buttons[4].content_ref, SUBTITLE_OFF)
        self.assertEqual(nav_targets(menu), [("ZURÜCK", project.main_menu.id), ("FILM STARTEN", film.id)])
        self.assertEqual((project.main_menu.buttons[-1].label, project.main_menu.buttons[-1].target),
                         ("SPRACHE", menu.id))

        plan = build_export_plan(project)
        specs = dict(plan.pages_specs)[plan.page_ids[menu.id]]
        audio, subs, nav = specs[:2], specs[2:5], specs[5:]
        self.assertEqual([s.target_audio_id for s in audio], [1, 2])
        self.assertEqual([(s.target_subtitle_id, s.target_subtitle_on) for s in subs],
                         [(1, True), (2, True), (None, False)])
        self.assertEqual([s.action_type for s in nav], ["set_page", "jump_title"])
        self.assertTrue(all(a.x < s.x for a in audio for s in subs))
        self.assertTrue(all(n.y > s.y for n in nav for s in subs))
        # Pfeiltasten: in der Spalte, zwischen den Spalten, Navigation darunter
        c = {s.button_id: s for s in specs}
        self.assertEqual((c[1].lower_id, c[1].right_id, c[2].right_id), (2, 3, 4))
        self.assertIn(c[2].lower_id, (6, 7))
        self.assertEqual(c[5].left_id, 2)          # „UNTERTITEL AUS“ → letzter Ton-Button
        self.assertEqual(c[6].right_id, 7)
        self.assertEqual(reachable(specs), set(c))

    def test_separate_pages(self):
        project, film = make_project(audio=("deu", "eng", "fra", "ita", "spa"), subs=("deu", "eng"))
        audio, subs = create_language_menus(project, film.id)
        self.assertEqual((audio.name, subs.name), ("Ton", "Untertitel"))
        self.assertEqual(columns_rows(audio, BUTTON_AUDIO), (2, 3))
        self.assertEqual(columns_rows(subs, BUTTON_SUBTITLE), (1, 3))
        main = project.main_menu
        self.assertEqual(nav_targets(audio), [("ZURÜCK", main.id), ("UNTERTITEL", subs.id), ("FILM STARTEN", film.id)])
        self.assertEqual(nav_targets(subs), [("ZURÜCK", main.id), ("TON", audio.id), ("FILM STARTEN", film.id)])
        plan = build_export_plan(project)
        for _, specs in plan.pages_specs:
            self.assertEqual(reachable(specs), {s.button_id for s in specs})

    def test_single_modes(self):
        project, film = make_project(audio=("deu", "eng"))
        (menu,) = create_language_menus(project, film.id, mode=LANG_AUDIO)
        self.assertEqual(project.main_menu.buttons[-1].label, "TON")
        self.assertEqual([b.kind for b in menu.buttons][:2], [BUTTON_AUDIO] * 2)
        with self.assertRaises(TemplateError):
            create_language_menus(project, film.id, mode=LANG_SUBTITLES)

    def test_link_button_gets_a_free_place(self):
        """Der Button zum neuen Menü landet unter dem untersten Button des Ausgangsmenüs (v1.12)."""
        project, film = make_project(chapters=4, audio=("deu", "eng"))
        main = project.main_menu
        first = list(main.buttons[0].position)
        create_chapter_menus(project, film.id)
        create_language_menus(project, film.id)
        play, chapters, language = main.buttons
        self.assertEqual(play.position, first)
        self.assertEqual(chapters.position[0], first[0])
        self.assertGreater(chapters.position[1], play.position[1])
        self.assertGreater(language.position[1], chapters.position[1])


class TestPreflight(unittest.TestCase):
    def _messages(self, project, level):
        from core.preflight import run_preflight
        return [i for i in run_preflight(project, check_files=False) if i.level == level]

    def test_template_menus_are_clean(self):
        project, film = make_project(chapters=12, audio=("deu", "eng"), subs=("deu",))
        create_chapter_menus(project, film.id)
        create_language_menus(project, film.id)
        from core.preflight import WARNING, INFO, ERROR
        self.assertEqual(self._messages(project, ERROR), [])
        self.assertEqual(self._messages(project, WARNING), [])
        # Vorlagen-Menüs haben ab v1.13.2 Form-Buttons: nur der Hinweis auf den eigenen Hintergrund
        infos = self._messages(project, INFO)
        self.assertEqual({i.node_id for i in infos}, {m.id for m in project.menus[1:]})
        self.assertTrue(all("Form-Buttons" in i.message for i in infos))
        for i, menu in enumerate(project.menus[1:]):
            menu.background.image = f"C:/menu{i}.png"
        self.assertEqual(self._messages(project, INFO), [])

    def test_missing_chapters(self):
        from core.preflight import WARNING
        project, film = make_project(chapters=10)
        p1, p2 = create_chapter_menus(project, film.id)
        set_chapter_times(film, [f"00:{i:02d}:00.000" for i in range(14)])
        p1.buttons = [b for b in p1.buttons if b.kind != BUTTON_CHAPTER or film.chapter_index(b.content_ref) < 2]
        (issue,) = self._messages(project, WARNING)
        self.assertEqual(issue.message, "Kapitel 3–8, 11–14 von „Hauptfilm“ sind in keinem Menü. Klick: Ergänzen …")
        self.assertEqual(issue.node_id, p2.id)

    def test_language_menu_without_way_to_film(self):
        from core.preflight import INFO
        project, film = make_project(audio=("deu", "eng"))
        (menu,) = create_language_menus(project, film.id)
        menu.buttons = [b for b in menu.buttons if b.label != "FILM STARTEN"]
        menu.background.image = "C:/ton.png"                    # Form-Buttons mit eigenem Bild: kein Hinweis
        self.assertEqual(self._messages(project, INFO), [])     # über ZURÜCK → Hauptmenü → FILM STARTEN
        project.main_menu.buttons[0].target = None
        (issue,) = self._messages(project, INFO)
        self.assertEqual(issue.node_id, menu.id)
        self.assertIn("kein Weg zum Film", issue.message)


if __name__ == "__main__":
    unittest.main()
