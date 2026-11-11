# tests/test_start_button.py
"""
Start-Button und Standard-Auswahl:
- Start-Button ohne festgelegten Standard-Button: erster Inhalts-Button in Lesereihenfolge (Kapitel 1), nicht der
  zuerst angelegte ZURÜCK; ohne Inhalts-Buttons der erste oben links. Gilt in Viewer, Preflight und auf der Disc.
- Farbe für einen unsichtbaren Zustand (0 %) wählen macht ihn sichtbar (100 %).
"""

import os
import sys
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from core import menu_design
from core.disc_adapter import build_export_plan
from core.disc_edit import add_menu, add_nav_button, add_button_of_kind, set_chapter_times
from core.disc_model import BUTTON_CHAPTER
from gui.node_editor.controller import GraphController
from modules.bdsim.player import Player, STATE_MENU
from tests.project_factory import text_starter
from tests.test_sim_disc import SimDiscTestCase

app_instance = QApplication.instance() or QApplication(sys.argv)


def chapter_page():
    """Hauptmenü → Kapitelseite: ZURÜCK (zuerst angelegt, unten) und drei Kapitel oben in einer Reihe."""
    project = text_starter()
    film = project.films[0]
    film.video_base = "film.264"
    set_chapter_times(film, ["00:00:00.000", "00:01:00.000", "00:02:00.000"])
    main = project.main_menu
    page = add_menu(project, "Kapitel", (600.0, 0.0))
    page.default_film_id = film.id
    page.buttons[0].target = main.id
    page.buttons[0].position = [100, 900]
    chapters = [add_button_of_kind(project, page.id, BUTTON_CHAPTER) for _ in range(3)]
    for i, b in enumerate(chapters):
        b.position = [200 + 400 * (2 - i), 300]                 # in der Liste rückwärts, im Bild von links
    add_nav_button(project, main.id, "KAPITEL", page.id)
    return project, main, page, chapters


class TestStartButton(unittest.TestCase):
    def test_first_content_button_in_reading_order(self):
        _project, _main, page, chapters = chapter_page()
        self.assertEqual(page.buttons[0].label, "ZURÜCK")
        self.assertEqual(menu_design.start_button_id(page), chapters[2].id)   # oben links
        page.default_button_id = page.buttons[0].id                          # festgelegt gewinnt
        self.assertEqual(menu_design.start_button_id(page), page.buttons[0].id)

    def test_without_content_top_left(self):
        project, main, _page, _chapters = chapter_page()
        main.buttons[1].position = [100, 100]                   # KAPITEL über FILM STARTEN
        self.assertEqual(menu_design.start_button_id(main), main.buttons[1].id)

    def test_start_button_reaches_the_disc(self):
        project, _main, page, chapters = chapter_page()
        plan = build_export_plan(project)
        specs = dict(plan.pages_specs)[plan.page_ids[page.id]]
        self.assertEqual([s.is_default for s in specs], [b.id == chapters[2].id for b in page.buttons])


class TestStartButtonOnSimulatedDisc(SimDiscTestCase):
    def test_player_selects_chapter_one(self):
        project, main, page, chapters = chapter_page()
        _sim, disc = self.simulate(project)
        p = Player(disc)
        p.insert_disc()
        self.assertEqual(p.state, STATE_MENU)
        p.activate_button(next(n for n, b in enumerate(main.buttons, start=1) if b.label == "KAPITEL"))
        self.assertEqual(p.selected_button, page.buttons.index(chapters[2]) + 1)


class TestOpacity(unittest.TestCase):
    def test_choosing_a_colour_makes_invisible_state_visible(self):
        project, _main, page, _chapters = chapter_page()
        ctrl = GraphController(project)
        style = page.button_style
        self.assertEqual(style.opacity_normal, 100)                          # Standard ab v1.14.7
        style.opacity_normal = 0                                             # Menü aus älterer Version
        ctrl.set_button_style(page.id, color_normal=style.color_normal)        # dieselbe Farbe noch einmal
        self.assertEqual(ctrl.project.menu(page.id).button_style.opacity_normal, 100)
        ctrl.undo_stack.undo()
        self.assertEqual(ctrl.project.menu(page.id).button_style.opacity_normal, 0)
        ctrl.set_button_style(page.id, color_selected="#EF4444")                # schon sichtbar: bleibt
        self.assertEqual(ctrl.project.menu(page.id).button_style.opacity_selected, 100)
        ctrl.set_button_style(page.id, opacity_normal=0, color_normal="#00FF00")  # beides angegeben: wie gewollt
        self.assertEqual(ctrl.project.menu(page.id).button_style.opacity_normal, 0)
        ctrl.undo_stack.setClean()


if __name__ == "__main__":
    unittest.main()
