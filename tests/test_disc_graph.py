# tests/test_disc_graph.py
"""
Tests für das Node-basierte Disc-Modell:
- Verbindungsregeln der Stufe 1
- Export-Adapter: Seiten, Aktionen, Lage und Größe direkt vom Button, Pfeiltasten nach der Lage (v1.12)
- feste IDs: Ziele hängen an Kapitel und Spur, nicht an ihrer Position
- Speichern und Laden (Schema 2); ältere Projekte werden mit einer klaren Meldung abgelehnt
"""

import json
import os
import tempfile
import unittest

from core.disc_model import (
    DiscProject, FilmNode, MenuNode, MenuButton, Chapter, Track, load_disc_project, ProjectFormatError,
    BUTTON_NAV, BUTTON_CHAPTER, BUTTON_AUDIO, BUTTON_SUBTITLE, SUBTITLE_OFF, START_NODE_ID, STYLE_SHAPE,
)
from core.disc_adapter import build_export_plan, DiscExportError
from core.disc_rules import Source, check_connection, connect, button_label
from tests.project_factory import make_project


class TestStructure(unittest.TestCase):
    def test_template_menus_are_free_buttons(self):
        project = make_project(chapters=3, audio=2, subs=1, chapter_menu=True, language_menu=True)
        main, chapters, language = project.menus
        film = project.films[0]
        self.assertEqual(project.start_target, main.id)
        self.assertEqual([b.label for b in main.buttons], ["FILM STARTEN", "KAPITEL", "SPRACHE"])
        self.assertEqual([b.kind for b in chapters.buttons], [BUTTON_CHAPTER] * 3 + [BUTTON_NAV])
        self.assertEqual({b.film_id for b in chapters.buttons if b.is_content}, {film.id})
        self.assertEqual(chapters.default_film_id, film.id)
        off = [b for b in language.buttons if b.content_ref == SUBTITLE_OFF]
        self.assertEqual([b.kind for b in off], [BUTTON_SUBTITLE])
        # jeder Button hat eine feste Position
        for menu in project.menus:
            for b in menu.buttons:
                self.assertIsNotNone(b.position, (menu.name, b.label))
        self.assertTrue(all(b.label is None for b in chapters.buttons[:3]))
        self.assertEqual(button_label(project, chapters, chapters.buttons[0]), "KAPITEL 1")
        self.assertEqual(button_label(project, language, language.buttons[0]), "TON: DEUTSCH")
        self.assertEqual(button_label(project, language, off[0]), "UNTERTITEL AUS")
        self.assertIn(START_NODE_ID, project.view.node_positions)

    def test_chapter_label_follows_film(self):
        project = make_project(chapters=3, chapter_menu=True)
        chapters_menu = project.menus[1]
        project.films[0].chapters[0].name = "PROLOG"
        self.assertEqual(button_label(project, chapters_menu, chapters_menu.buttons[0]), "PROLOG")

    def test_inserted_chapter_keeps_targets(self):
        """Feste IDs: ein eingefügtes Kapitel verschiebt kein Ziel; die Nummer auf der Disc folgt dem Kapitel."""
        project = make_project(chapters=3, chapter_menu=True)
        film, page = project.films[0], project.menus[1]
        third = page.buttons[2]
        self.assertEqual(third.content_ref, "ch3")
        film.chapters.insert(1, Chapter(id="new", time="00:02:00.000"))
        plan = build_export_plan(project)
        specs = dict(plan.pages_specs)[plan.page_ids[page.id]]
        self.assertEqual(third.content_ref, "ch3")
        self.assertEqual((specs[2].target_chapter_id, specs[2].chapter_time), (4, "00:10:00.000"))


class TestConnectionRules(unittest.TestCase):
    def setUp(self):
        self.project = make_project(chapters=3, extra_films=1, chapter_menu=True)
        self.main, self.chapters = self.project.menus
        self.film1, self.film2 = self.project.films

    def test_start(self):
        p = self.project
        self.assertTrue(check_connection(p, Source.start(), self.chapters.id).allowed)
        self.assertTrue(check_connection(p, Source.start(), self.film1.id).allowed)
        self.assertTrue(check_connection(p, Source.start(), self.film2.id).allowed)       # v1.18.1: Trailer
        self.assertFalse(check_connection(p, Source.start(), "gibt_es_nicht").allowed)

    def test_film_end(self):
        p = self.project
        self.assertTrue(check_connection(p, Source.film_end(self.film1.id), None).allowed)
        self.assertTrue(check_connection(p, Source.film_end(self.film1.id), self.main.id).allowed)
        self.assertTrue(check_connection(p, Source.film_end(self.film1.id), self.chapters.id).allowed)   # v1.18
        self.assertTrue(check_connection(p, Source.film_end(self.film1.id), self.film2.id).allowed)      # v1.18.1
        self.assertFalse(check_connection(p, Source.film_end(self.film1.id), "gibt_es_nicht").allowed)

    def test_buttons(self):
        p = self.project
        nav = self.main.buttons[0]
        self.assertTrue(check_connection(p, Source.button(self.main.id, nav.id), self.film2.id).allowed)
        self.assertTrue(check_connection(p, Source.button(self.main.id, nav.id), self.chapters.id).allowed)
        self.assertFalse(check_connection(p, Source.button(self.main.id, nav.id), self.main.id).allowed)
        content = self.chapters.buttons[0]
        self.assertFalse(check_connection(p, Source.button(self.chapters.id, content.id), self.main.id).allowed)

    def test_connect_applies_only_allowed(self):
        p = self.project
        self.assertFalse(connect(p, Source.film_end(self.film1.id), "gibt_es_nicht").allowed)
        self.assertIsNone(self.film1.end_target)
        self.assertTrue(connect(p, Source.button(self.main.id, self.main.buttons[0].id), self.film2.id).allowed)
        self.assertEqual(self.main.buttons[0].target, self.film2.id)


class TestAdapter(unittest.TestCase):
    def _project(self) -> DiscProject:
        film = FilmNode(id="f1", name="Film", video_base="C:/f.264",
                        chapters=[Chapter("c1", "00:00:00.000"), Chapter("c2", "00:10:00.000")],
                        audio_tracks=[Track("a1", "C:/a.ac3", "deu")],
                        subtitle_tracks=[Track("s1", "C:/s.sup", "eng")])
        main = MenuNode(id="m_main", name="Hauptmenü", default_film_id="f1", buttons=[
            MenuButton(id="b1", label="START", target="f1", position=[100, 100]),
            MenuButton(id="b2", label="SZENEN", target="m_ch", position=[100, 300], size=[200, 50]),
        ])
        ch = MenuNode(id="m_ch", name="Kapitel", default_film_id="f1", buttons=[
            MenuButton(id="c_b1", kind=BUTTON_CHAPTER, film_id="f1", content_ref="c1", position=[100, 100]),
            MenuButton(id="c_b2", kind=BUTTON_CHAPTER, film_id="f1", content_ref="c2", label="FINALE",
                       position=[600, 100]),
            MenuButton(id="c_a1", kind=BUTTON_AUDIO, film_id="f1", content_ref="a1", position=[100, 400]),
            MenuButton(id="c_off", kind=BUTTON_SUBTITLE, film_id="f1", content_ref=SUBTITLE_OFF,
                       position=[600, 400]),
            MenuButton(id="c_back", label="ZURÜCK", target="m_main", position=[350, 700]),
        ])
        orphan = MenuNode(id="m_orphan", name="Unbenutzt")
        return DiscProject(films=[film], menus=[ch, orphan, main], start_target="m_main")

    def test_page_order_and_actions(self):
        plan = build_export_plan(self._project())
        # zwei Seiten in einer Gruppe: unsichtbare Startseite 0, die Menüs ab Seite 1 (v1.13)
        self.assertEqual(plan.page_ids, {"m_main": 1, "m_ch": 2})
        (start,) = dict(plan.pages_specs)[0]
        self.assertTrue(start.invisible and start.auto_action and start.is_default)
        self.assertEqual(plan.unreachable_menus, ["m_orphan"])
        main_specs = dict(plan.pages_specs)[1]
        self.assertEqual((main_specs[1].action_type, main_specs[1].target_page_id), ("set_page", 2))
        ch_specs = dict(plan.pages_specs)[2]
        self.assertEqual([s.text for s in ch_specs], ["KAPITEL 1", "FINALE", "TON: DEUTSCH", "UNTERTITEL AUS", "ZURÜCK"])
        self.assertEqual(ch_specs[1].chapter_time, "00:10:00.000")
        self.assertEqual(ch_specs[1].target_chapter_id, 2)
        self.assertEqual((ch_specs[3].action_type, ch_specs[3].target_subtitle_on), ("set_stream", False))

    def test_position_and_size_come_from_the_button(self):
        main_specs = dict(build_export_plan(self._project()).pages_specs)[1]
        self.assertEqual((main_specs[0].x, main_specs[0].y, main_specs[0].width, main_specs[0].height),
                         (100, 100, 380, 70))
        self.assertEqual((main_specs[1].x, main_specs[1].y, main_specs[1].width, main_specs[1].height),
                         (100, 300, 200, 50))

    def test_shape_style_uses_style_size(self):
        project = self._project()
        main = project.menu("m_main")
        main.button_style.kind = STYLE_SHAPE
        main.button_style.width, main.button_style.height = 240, 10
        specs = dict(build_export_plan(project).pages_specs)[1]
        self.assertEqual((specs[0].width, specs[0].height), (240, 10))
        self.assertIsNotNone(specs[0].shape)
        self.assertEqual((specs[1].width, specs[1].height), (200, 50))   # eigene Größe gilt weiter

    def test_dpad_follows_position(self):
        specs = dict(build_export_plan(self._project()).pages_specs)[2]
        first, second, audio = specs[0], specs[1], specs[2]
        self.assertEqual(first.right_id, second.button_id)
        self.assertEqual(first.lower_id, audio.button_id)
        project = self._project()
        project.menu("m_ch").buttons[0].dpad["right"] = "c_back"
        specs = dict(build_export_plan(project).pages_specs)[2]
        self.assertEqual(specs[0].right_id, 5)

    def test_missing_content_is_an_error(self):
        project = self._project()
        project.films[0].chapters.pop()
        with self.assertRaises(DiscExportError) as ctx:
            build_export_plan(project)
        self.assertIn("FINALE", str(ctx.exception))

    def test_button_without_film_is_an_error(self):
        project = self._project()
        project.menu("m_ch").buttons[2].film_id = None
        with self.assertRaises(DiscExportError):
            build_export_plan(project)

    def test_start_chain_without_menu_is_an_error(self):
        """Start → Film → Film ohne Menü am Ende: keine Disc ohne Menü (die spielt nur einen Film)."""
        project = self._project()
        project.start_target = "f1"
        project.films[0].end_target = "f1"
        with self.assertRaises(DiscExportError) as ctx:
            build_export_plan(project)
        self.assertIn("im Kreis", str(ctx.exception))

    def test_missing_start_is_an_error(self):
        project = self._project()
        project.start_target = None
        with self.assertRaises(DiscExportError):
            build_export_plan(project)


class TestSerialization(unittest.TestCase):
    def test_round_trip(self):
        project = make_project(chapters=3, audio=2, subs=1, extra_films=1, chapter_menu=True, language_menu=True)
        project.films[0].audio_tracks[0].extra["delay"] = 120
        data = json.loads(json.dumps(project.to_dict()))
        self.assertEqual(data["schema"], 2)
        restored = DiscProject.from_dict(data)
        self.assertEqual(restored, project)
        self.assertEqual(build_export_plan(restored).pages_specs, build_export_plan(project).pages_specs)

    def test_save_and_load(self):
        project = make_project(chapters=3, chapter_menu=True)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "neu.bdproj")
            project.save_to_file(path)
            self.assertEqual(load_disc_project(path), project)

    def test_older_projects_are_rejected(self):
        """Ab v1.12 öffnen sich ältere Projekte nicht mehr: Schema 1 und Projekte der früheren Oberfläche."""
        data = make_project().to_dict()
        data["schema"], data["version"] = 1, "1.11.3"
        with tempfile.TemporaryDirectory() as tmp:
            old = os.path.join(tmp, "alt.bdproj")
            with open(old, "w", encoding="utf-8") as f:
                json.dump(data, f)
            with self.assertRaises(ProjectFormatError) as ctx:
                load_disc_project(old)
            self.assertIn("1.11.3", str(ctx.exception))
            legacy = os.path.join(tmp, "oberflaeche.bdproj")
            with open(legacy, "w", encoding="utf-8") as f:
                json.dump({"project_name": "ALT", "titles": []}, f)
            with self.assertRaises(ProjectFormatError):
                load_disc_project(legacy)


if __name__ == "__main__":
    unittest.main()
