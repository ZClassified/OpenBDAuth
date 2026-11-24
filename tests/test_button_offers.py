# tests/test_button_offers.py
"""
„＋ Button“ im Menü-Knoten (v1.35): fertige Buttons mit Ziel statt eines leeren Navigations-Buttons, den man
danach im Inspektor umstellen muss.
- Angebot: Film starten, Ton, Untertitel (mit „Aus“), Kapitel des Standard-Films; vorhandene sind markiert
- Anlegen: Inhalts-Button mit Ziel und automatischer Beschriftung; „Film starten“ verbunden und beschriftet
- Controller: ein Rückgängig-Schritt, der neue Button ist ausgewählt
"""
import os
import sys
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from core import disc_edit
from core.disc_model import BUTTON_NAV, BUTTON_AUDIO, BUTTON_SUBTITLE, BUTTON_CHAPTER, SUBTITLE_OFF
from core.disc_rules import button_label
from gui.node_editor.controller import GraphController
from tests.project_factory import make_project

app_instance = QApplication.instance() or QApplication(sys.argv)


class TestButtonOffers(unittest.TestCase):
    def setUp(self):
        self.project = make_project(chapters=3, audio=2, subs=1)
        self.main = self.project.main_menu
        self.film = self.project.films[0]

    def offers(self):
        return disc_edit.button_offers_direct(self.project, self.main)

    def test_offers_everything_of_the_film(self):
        offers = self.offers()
        kinds = [(o.kind, o.ref) for o in offers]
        self.assertIn((BUTTON_NAV, None), kinds)
        self.assertEqual([r for k, r in kinds if k == BUTTON_AUDIO], ["a1", "a2"])
        self.assertEqual([r for k, r in kinds if k == BUTTON_SUBTITLE], ["s1", SUBTITLE_OFF])
        self.assertEqual([r for k, r in kinds if k == BUTTON_CHAPTER], ["ch1", "ch2", "ch3"])
        play = next(o for o in offers if o.kind == BUTTON_NAV)
        self.assertTrue(play.present)                           # FILM STARTEN gibt es in der Startvorlage
        self.assertFalse(any(o.present for o in offers if o.kind != BUTTON_NAV))

    def test_add_audio_buttons(self):
        for ref in ("a1", "a2"):
            offer = next(o for o in self.offers() if o.kind == BUTTON_AUDIO and o.ref == ref)
            button = disc_edit.add_offered_button(self.project, self.main.id, offer)
            self.assertEqual((button.kind, button.film_id, button.content_ref), (BUTTON_AUDIO, self.film.id, ref))
            self.assertIsNone(button.label)                     # Beschriftung automatisch aus der Spur
            self.assertTrue(button_label(self.project, self.main, button))
            self.assertIsNotNone(button.position)
        self.assertTrue(all(o.present for o in self.offers() if o.kind == BUTTON_AUDIO))

    def test_add_play_button(self):
        self.main.buttons.clear()
        offer = next(o for o in self.offers() if o.kind == BUTTON_NAV)
        self.assertFalse(offer.present)
        button = disc_edit.add_offered_button(self.project, self.main.id, offer)
        self.assertEqual((button.kind, button.target, button.label), (BUTTON_NAV, self.film.id, "FILM STARTEN"))

    def test_several_films_named_after_the_film(self):
        project = make_project(audio=1, extra_films=1)
        main = project.main_menu
        offers = disc_edit.button_offers_direct(project, main)
        bonus = project.films[1]
        offer = next(o for o in offers if o.kind == BUTTON_NAV and o.film_id == bonus.id)
        button = disc_edit.add_offered_button(project, main.id, offer)
        self.assertEqual(button.label, bonus.name.upper())

    def test_controller_one_step_and_selected(self):
        ctrl = GraphController(self.project)
        offer = next(o for o in self.offers() if o.kind == BUTTON_AUDIO)
        before = len(ctrl.project.main_menu.buttons)
        button_id = ctrl.add_offered_button(self.main.id, offer)
        self.assertEqual(len(ctrl.project.main_menu.buttons), before + 1)
        self.assertEqual(ctrl.selected_button, (self.main.id, button_id))
        ctrl.undo_stack.undo()
        self.assertEqual(len(ctrl.project.main_menu.buttons), before)
        ctrl.undo_stack.setClean()


if __name__ == "__main__":
    unittest.main()
