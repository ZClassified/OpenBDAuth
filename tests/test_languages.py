# tests/test_languages.py
"""
Sprache der Oberfläche und Sprache der Disc (v1.27.0): Die Oberfläche folgt einer Programm-Einstellung, die
Beschriftungen auf der Disc der Sprache im Projekt. Ein Sprachwechsel der Oberfläche ändert keine Disc.
"""

import sys
import unittest

from PySide6.QtWidgets import QApplication

from core import menu_generator as gen
from core.disc_edit import add_menu, add_nav_button, starter_project
from core.disc_labels import is_label
from core.disc_model import BUTTON_NAV, SUBTITLE_OFF, START_NODE_ID
from core.disc_rules import auto_label, button_label
from core.menu_templates import LABEL_BACK, LABEL_NEXT, create_chapter_menus, create_language_menus
from core.translations import set_ui_language, tr, ui_language, undo_text
from tests.project_factory import make_project

app_instance = QApplication.instance() or QApplication(sys.argv)


def english(project):
    project.settings.app_lang = "en"
    return project


class LanguageCase(unittest.TestCase):
    def setUp(self):
        self.addCleanup(set_ui_language, "de")


class TestUiLanguage(LanguageCase):
    def test_tr_follows_the_ui_language(self):
        self.assertEqual(tr("graph_end"), "Ende")
        set_ui_language("en")
        self.assertEqual((ui_language(), tr("graph_end")), ("en", "End"))
        self.assertEqual(tr("graph_end", "de"), "Ende")                  # ausdrücklich angegeben
        self.assertEqual(tr("graph_n_chapters", n=3), "3 chapters")
        set_ui_language("xx")
        self.assertEqual(ui_language(), "de")

    def test_undo_texts(self):
        self.assertEqual(undo_text("Verschieben"), "Verschieben")
        set_ui_language("en")
        self.assertEqual(undo_text("Verschieben"), "Move")
        self.assertEqual(undo_text("Menü „Extras“ anlegen"), "Create menu “Extras”")
        self.assertEqual(undo_text("3 Knoten löschen"), "Delete 3 nodes")
        self.assertEqual(undo_text("Unbekannt"), "Unbekannt")

    def test_every_key_exists_in_both_languages(self):
        from core.translations import TEXTS
        self.assertEqual(sorted(set(TEXTS["de"]) ^ set(TEXTS["en"])), [])


class TestDiscLanguage(LanguageCase):
    def test_starter_project_in_english(self):
        project = starter_project("en")
        menu = project.main_menu
        self.assertEqual((project.settings.app_lang, menu.name, project.films[0].name), ("en", "Main menu", "Main movie"))
        self.assertEqual([b.label for b in menu.buttons], ["PLAY MOVIE"])
        self.assertEqual(starter_project().main_menu.buttons[0].label, "FILM STARTEN")

    def test_new_menu_back_button(self):
        menu = add_menu(english(starter_project()), "Extras", (0.0, 0.0))
        self.assertEqual(menu.buttons[0].label, "BACK")

    def test_auto_labels_follow_the_disc_not_the_ui(self):
        project = make_project(chapters=2, audio=2, subs=1, chapter_menu=True, language_menu=True)
        found = {}
        for menu in project.menus:
            for b in menu.buttons:
                if b.is_content:
                    found.setdefault((b.kind, b.content_ref == SUBTITLE_OFF), (menu, b))
        labels = lambda: sorted(button_label(project, menu, b) for menu, b in found.values())
        german = labels()
        set_ui_language("en")                                   # die Oberfläche allein ändert nichts
        self.assertEqual(labels(), german)
        self.assertIn("UNTERTITEL AUS", german)
        english(project)
        self.assertEqual(labels(), sorted(["CHAPTER 1", "AUDIO: GERMAN", "SUBTITLES: ENGLISH", "SUBTITLES OFF"]))
        menu, b = next(iter(found.values()))
        self.assertEqual(auto_label(project, menu, b), button_label(project, menu, b))

    def test_language_names_in_english(self):
        from core.constants import language_menu_name
        self.assertEqual((language_menu_name("jpn"), language_menu_name("jpn", "en")), ("JAPANISCH", "JAPANESE"))
        self.assertEqual(language_menu_name("qaa", "en"), "QAA")

    def test_templates_in_english(self):
        project = english(make_project(chapters=20, audio=2, subs=1))
        film = project.films[0]
        pages = create_chapter_menus(project, film.id, per_page=12)
        self.assertEqual([p.name for p in pages], ["Chapters 1/2", "Chapters 2/2"])
        labels = {b.label for p in pages for b in p.buttons if b.kind == BUTTON_NAV}
        self.assertEqual(labels, {"BACK", "MAIN MENU", "NEXT"})
        self.assertIn("CHAPTERS", [b.label for b in project.main_menu.buttons])
        (menu,) = create_language_menus(project, film.id)
        self.assertEqual(menu.name, "Audio & Subtitles")
        self.assertEqual({b.label for b in menu.buttons if b.kind == BUTTON_NAV}, {"BACK", "PLAY MOVIE"})

    def test_generator_recognizes_both_languages(self):
        self.assertTrue(is_label("NEXT", LABEL_NEXT) and is_label("WEITER", LABEL_NEXT))
        self.assertFalse(is_label("BACK", LABEL_NEXT))
        project = english(make_project(chapters=30))
        main = project.main_menu
        menu = add_menu(project, "Chapters", (720.0, 300.0))
        add_nav_button(project, main.id, "CHAPTERS", menu.id)
        menu.buttons[0].target = main.id
        later = add_menu(project, "Extras", (1100.0, 300.0))
        add_nav_button(project, menu.id, "NEXT", later.id)          # vorhandenes englisches WEITER
        s = gen.default_settings(project, menu, (200, 150, 1500, 600))
        s.cols, s.rows = 4, 5
        (p2,) = gen.generate(project, menu.id, s)
        page = project.menu(p2)
        nexts = [b for b in menu.buttons if b.kind == BUTTON_NAV and is_label(b.label, LABEL_NEXT)]
        self.assertEqual([b.target for b in nexts], [p2])                 # kein zweites WEITER
        self.assertEqual({b.label for b in page.buttons if b.kind == BUTTON_NAV}, {"BACK", "MAIN MENU", "NEXT"})
        self.assertTrue(any(is_label(b.label, LABEL_BACK) for b in page.buttons))


class TestWindow(LanguageCase):
    def setUp(self):
        super().setUp()
        from gui.studio.main_window import StudioWindow
        self.win = StudioWindow(persist_layout=False)
        self.addCleanup(self.win.close)

    def test_switch_is_not_a_project_change(self):
        win = self.win
        win.controller.rename_node(win.controller.project.films[0].id, "Film A")
        steps = win.controller.undo_stack.count()
        win.set_ui_lang("en")
        app_instance.processEvents()
        self.assertEqual(win.controller.undo_stack.count(), steps)
        self.assertEqual(win.controller.project.settings.app_lang, "de")    # die Disc bleibt deutsch
        self.assertEqual(win.btn_ui_lang.text(), "EN")
        self.assertEqual(win.scene.nodes[START_NODE_ID].title, "Disc start")
        win.controller.undo_stack.undo()                                    # Rückgängig stellt die Sprache nicht um
        app_instance.processEvents()
        self.assertEqual(ui_language(), "en")
        self.assertEqual(win.scene.nodes[START_NODE_ID].title, "Disc start")

    def test_new_project_uses_the_ui_language(self):
        self.win.set_ui_lang("en")
        self.win.set_project(starter_project(ui_language()))
        self.assertEqual(self.win.controller.project.main_menu.buttons[0].label, "PLAY MOVIE")


class TestMessages(LanguageCase):
    """v1.27.2: Prüfungen, Simulator, Kompatibilitätshinweise und Vorbereiten melden sich in der Oberflächensprache."""

    def test_preflight(self):
        from core.preflight import run_preflight
        project = make_project(video=False)
        german = [i.message for i in run_preflight(project, check_files=False)]
        self.assertIn("Film „Hauptfilm“ hat kein Video.", german)
        set_ui_language("en")
        english_ = [i.message for i in run_preflight(project, check_files=False)]
        self.assertIn("Movie “Hauptfilm” has no video.", english_)
        self.assertEqual(len(german), len(english_))

    def test_compliance_warning_follows_the_ui(self):
        from modules.video_tools import ComplianceWarning, warning_text
        w = ComplianceWarning.of("NON_STANDARD_RESOLUTION", width=1440, height=600).to_dict()
        self.assertEqual(w["title"], "Nicht-standardkonforme Auflösung (1440×600)")      # gespeichert beim Import
        self.assertEqual(w["params"], {"width": 1440, "height": 600})
        set_ui_language("en")
        self.assertEqual(warning_text(w, "title"), "Non-standard resolution (1440×600)")
        old = dict(w)
        del old["params"]                                                 # Projekt aus v1.27.1 oder älter
        self.assertEqual(warning_text(old, "title"), "Nicht-standardkonforme Auflösung (1440×600)")

    def test_simulator_report(self):
        import os
        import tempfile
        from modules.bdsim.disc import load_disc
        from modules.bdsim.explore import explore, format_report
        from modules.sim_disc import build_simulation_disc
        set_ui_language("en")
        with tempfile.TemporaryDirectory() as tmp:
            disc = load_disc(build_simulation_disc(make_project(chapters=2), os.path.join(tmp, "SIM")).root)
            report = format_report(disc, [explore(disc)])
        self.assertIn("Run with 3D TV", report)
        self.assertNotIn("Durchlauf", report)

    def test_prepare_texts(self):
        from gui.prepare.inspector import audio_option_label
        from modules.prepare import jobs
        option = "AC3 (Downmix auf 5.1, 640 kbps)"
        self.assertEqual(audio_option_label(option), option)
        set_ui_language("en")
        self.assertEqual(audio_option_label(option), "AC3 (downmix to 5.1, 640 kbps)")
        self.assertIn("23.976", jobs.PROBLEM_TEXT["fps_3d"].format(fps="25"))

    def test_file_filter_and_language_list(self):
        from core.constants import get_language_display_items
        from core.translations import tr_file_filter
        text = "Untertitel (*.srt *.sup);;Alle Dateien (*.*)"
        self.assertEqual(tr_file_filter(text), text)
        self.assertIn(("Schwedisch [swe]", "swe"), get_language_display_items())
        set_ui_language("en")
        self.assertEqual(tr_file_filter(text), "Subtitles (*.srt *.sup);;All files (*.*)")
        self.assertIn(("Swedish [swe]", "swe"), get_language_display_items())


if __name__ == "__main__":
    unittest.main()
