# tests/test_button_edit.py
"""
Freie Buttons bearbeiten (v1.12.1), Qt-frei: Typ wechseln, Ziel setzen, Film mehrerer Buttons wechseln
(Ziel wandert mit seiner Nummer), ausrichten, gleiche Größe, Ziel-Marker und Zielauswahl.
"""

import unittest

from core import disc_edit, menu_design, menu_layout
from core.disc_adapter import build_export_plan
from core.disc_edit import add_film, set_button_kind, set_button_content, set_buttons_film, default_film
from core.disc_model import (
    Chapter, Track, BUTTON_NAV, BUTTON_CHAPTER, BUTTON_AUDIO, BUTTON_SUBTITLE, SUBTITLE_OFF,
)
from core.disc_rules import target_options, target_marker, has_target
from core.menu_templates import create_chapter_menus, create_language_menus
from tests.project_factory import make_project


class TestKindAndTarget(unittest.TestCase):
    def setUp(self):
        self.project = make_project(chapters=4, audio=2, subs=1, chapter_menu=True)
        self.main, self.page = self.project.menus
        self.film = self.project.films[0]

    def test_nav_to_chapter_drops_target_and_takes_default_film(self):
        play = self.main.buttons[0]
        self.assertEqual(play.target, self.film.id)
        set_button_kind(self.project, self.main.id, play.id, BUTTON_CHAPTER)
        self.assertEqual((play.kind, play.target, play.content_ref), (BUTTON_CHAPTER, None, None))
        self.assertEqual(play.film_id, self.film.id)                   # Standard-Film des Hauptmenüs
        self.assertFalse(has_target(self.project, self.main, play))
        set_button_content(self.project, self.main.id, play.id, self.film.id, "ch3")
        self.assertEqual(target_marker(self.project, self.main, play), "K3")
        self.assertTrue(has_target(self.project, self.main, play))

    def test_content_to_nav_and_link_button_no_longer_created_with(self):
        link = self.main.buttons[-1]                                     # „KAPITEL“, entstand mit der Seite
        self.assertEqual(link.created_with, self.page.id)
        set_button_kind(self.project, self.main.id, link.id, BUTTON_AUDIO)
        self.assertIsNone(link.created_with)
        self.assertIsNone(link.target)
        chapter = self.page.buttons[0]
        set_button_kind(self.project, self.page.id, chapter.id, BUTTON_NAV)
        self.assertEqual((chapter.film_id, chapter.content_ref), (None, None))
        self.assertEqual(target_marker(self.project, self.page, chapter), "→ ?")

    def test_default_film(self):
        self.assertEqual(default_film(self.project, self.page), self.film)
        self.page.default_film_id = None
        self.assertEqual(default_film(self.project, self.page), self.film)   # nur ein Film
        add_film(self.project, "Bonus", (0.0, 0.0))
        self.assertIsNone(default_film(self.project, self.page))

    def test_options_and_markers(self):
        self.film.chapters[1].name = "PROLOG"
        self.assertEqual([t for _r, t in target_options(self.film, BUTTON_CHAPTER)][:2],
                         ["1 · 00:00:00", "2 · PROLOG"])
        self.assertEqual(target_options(self.film, BUTTON_AUDIO), [("a1", "1 · DEUTSCH"), ("a2", "2 · ENGLISCH")])
        self.assertEqual(target_options(self.film, BUTTON_SUBTITLE)[0], (SUBTITLE_OFF, "Aus"))
        self.assertEqual(target_options(None, BUTTON_CHAPTER), [])
        (lang,) = create_language_menus(self.project, self.film.id)
        self.assertEqual([target_marker(self.project, lang, b) for b in lang.buttons],
                         ["A1", "A2", "U1", "U–", "→ Hauptmenü", "→ Hauptfilm"])

    def test_changed_kind_exports_new_action(self):
        chapter = self.page.buttons[1]
        set_button_kind(self.project, self.page.id, chapter.id, BUTTON_AUDIO)
        set_button_content(self.project, self.page.id, chapter.id, self.film.id, "a2")
        plan = build_export_plan(self.project)
        spec = dict(plan.pages_specs)[plan.page_ids[self.page.id]][1]
        self.assertEqual((spec.action_type, spec.target_audio_id), ("set_stream", 2))


class TestFilmChange(unittest.TestCase):
    def test_target_follows_its_number(self):
        project = make_project(chapters=3, audio=2, subs=1, chapter_menu=True, language_menu=True)
        main, page, lang = project.menus
        other = add_film(project, "Folge 2", (0.0, 0.0))
        other.chapters = [Chapter("x1", "00:00:00.000"), Chapter("x2", "00:01:00.000")]
        other.audio_tracks = [Track("y1", "a.ac3", "eng")]
        set_buttons_film(project, page.id, [b.id for b in page.buttons], other.id)
        refs = [(b.film_id, b.content_ref) for b in page.buttons if b.is_content]
        self.assertEqual(refs, [(other.id, "x1"), (other.id, "x2"), (other.id, None)])   # Kapitel 3 gibt es dort nicht
        self.assertIsNone(page.buttons[-1].film_id)                                       # Navigation unberührt
        set_buttons_film(project, lang.id, [b.id for b in lang.buttons], other.id)
        self.assertEqual([b.content_ref for b in lang.buttons if b.is_content], ["y1", None, None, SUBTITLE_OFF])


class TestAlignAndSize(unittest.TestCase):
    def setUp(self):
        self.project = make_project(chapters=6, chapter_menu=True)
        self.page = self.project.menus[1]
        self.ids = [b.id for b in self.page.buttons[:3]]
        menu_design.move_items(self.project, self.page.id, {self.ids[0]: (100, 100), self.ids[1]: (300, 200),
                                                             self.ids[2]: (500, 400)})

    def boxes(self):
        return {bid: menu_layout.button_box(self.page, self.page.button(bid)) for bid in self.ids}

    def test_align_edges_and_centres(self):
        menu_design.align_items(self.project, self.page.id, self.ids, "left")
        self.assertEqual({b[0] for b in self.boxes().values()}, {100})
        menu_design.align_items(self.project, self.page.id, self.ids, "bottom")
        self.assertEqual({b[1] + b[3] for b in self.boxes().values()}, {470})
        self.page.button(self.ids[1]).size = [200, 30]
        menu_design.align_items(self.project, self.page.id, self.ids, "vcenter")
        centres = {b[1] + b[3] / 2 for b in self.boxes().values()}
        self.assertEqual(len(centres), 1)
        before = self.boxes()
        menu_design.align_items(self.project, self.page.id, self.ids[:1], "right")   # ein Button: nichts
        self.assertEqual(self.boxes(), before)

    def test_match_size_keeps_centres(self):
        self.page.button(self.ids[0]).size = [200, 30]
        centre = lambda b: (b[0] + b[2] / 2, b[1] + b[3] / 2)
        before = {bid: centre(b) for bid, b in self.boxes().items()}
        menu_design.match_size(self.project, self.page.id, self.ids, self.ids[0], width=True, height=False)
        after = self.boxes()
        self.assertEqual({b[2] for b in after.values()}, {200})
        self.assertEqual({b[3] for b in list(after.values())[1:]}, {70})
        for bid in self.ids:
            self.assertAlmostEqual(centre(after[bid])[0], before[bid][0], delta=1)


if __name__ == "__main__":
    unittest.main()
