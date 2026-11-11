# tests/test_menu_groups.py
"""
Eigene Hintergründe pro Menü (v1.13.0): Menügruppen im Export-Adapter, unsichtbare Startseite, Sprung zwischen
Gruppen über Register, Menü-Schleife ohne Rücksprung (11.2.4), Menü-Objekte ohne resume_intention (11.2.5),
Standard-Button auf der Disc. Durchlauf mit der Simulations-Disc (ohne tsMuxeR); die Gegenprobe mit tsMuxeR steht
in tests/test_e2e_export.py.
"""

import os
import struct
import unittest

from core.disc_adapter import build_export_plan, menu_group_index, background_key
from modules.bdmv.movie_object_generator import (
    build_standard_movie_objects, start_page_commands, jump_menu_commands, menu_loop_commands,
    cmd_set_button_page_from_registers, menu_group_object, menu_group_playlist, GPR_MENU_PAGE, GPR_PAGE_NOW,
    GPR_BUTTON_NOW,
)
from modules.bdsim.disc import load_disc
from modules.bdsim.explore import explore
from modules.bdsim.player import Player, STATE_MENU, STATE_FILM
from modules.sim_disc import build_simulation_disc
from tests.project_factory import make_project
from tests.test_sim_disc import SimDiscTestCase


def two_backgrounds(language: bool = True):
    """Hauptmenü (+ Sprachmenü) auf Bild 1, Kapitelmenü (2 Seiten) auf Bild 2."""
    project = make_project(chapters=5, audio=2, subs=1, chapter_menu=False, language_menu=False)
    from core.menu_templates import create_chapter_menus, create_language_menus
    film = project.films[0]
    main = project.main_menu
    main.background.image = "C:/bild1.png"
    pages = create_chapter_menus(project, film.id, per_page=3)
    for p in pages:
        p.background.image = "C:/bild2.png"
    lang = create_language_menus(project, film.id)[0] if language else None
    return project, main, pages, lang


class TestGroups(unittest.TestCase):
    def test_single_page_menu_is_unchanged(self):
        """Ein Menü, eine Seite: keine Gruppenangaben, keine Startseite – Navigation wie bisher."""
        plan = build_export_plan(make_project())
        self.assertIsNone(getattr(plan.project_state, "menu_groups", None))
        self.assertEqual([p for p, _ in plan.pages_specs], [0])

    def test_groups_by_effective_background(self):
        project, main, pages, lang = two_backgrounds()
        groups = menu_group_index(project)
        self.assertEqual(groups[main.id], 0)
        self.assertEqual(groups[lang.id], 0)                 # ohne eigenen Hintergrund: wie Hauptmenü
        self.assertEqual({groups[p.id] for p in pages}, {1})
        self.assertEqual(background_key(project, lang), background_key(project, main))
        plan = build_export_plan(project)
        g0, g1 = plan.menu_groups
        self.assertEqual((g0["bg_image"], g1["bg_image"]), ("C:/bild1.png", "C:/bild2.png"))
        self.assertTrue(g0["keep_page"] and g1["keep_page"])
        self.assertEqual([p for p, _ in g1["pages_specs"]], [0, 1, 2])   # Startseite + 2 Kapitelseiten
        self.assertEqual(plan.project_state.menu_groups, plan.menu_groups)

    def test_buttons_between_groups_jump_via_register(self):
        project, main, pages, lang = two_backgrounds()
        plan = build_export_plan(project)
        n = len(project.films)
        link = next(s for s in dict(plan.pages_specs)[plan.page_ids[main.id]] if s.text == "KAPITEL")
        self.assertEqual(link.nav_commands, jump_menu_commands(menu_group_object(n, 1), plan.page_ids[pages[0].id]))
        lang_link = next(s for s in dict(plan.pages_specs)[plan.page_ids[main.id]] if s.text == "SPRACHE")
        self.assertIsNone(lang_link.nav_commands)            # gleiche Gruppe: SetButtonPage ohne Pause
        back = next(s for s in dict(plan.menu_groups[1]["pages_specs"])[plan.page_ids[pages[0].id]]
                    if s.text == "ZURÜCK")
        self.assertEqual(back.nav_commands, jump_menu_commands(1, plan.page_ids[main.id]))

    def test_default_button_reaches_the_disc(self):
        project, main, pages, lang = two_backgrounds()
        main.default_button_id = main.buttons[1].id
        plan = build_export_plan(project)
        specs = dict(plan.pages_specs)[plan.page_ids[main.id]]
        self.assertEqual([s.is_default for s in specs], [False, True, False])


class TestCommands(unittest.TestCase):
    def test_set_button_page_with_registers_like_libbluray(self):
        """Flags im Befehl, Nummer im Register (libbluray _fetch_operand)."""
        raw = cmd_set_button_page_from_registers(GPR_PAGE_NOW)
        b0, b1 = raw[0], raw[1]
        self.assertEqual((b0 >> 5, (b0 >> 3) & 3, b0 & 7), (2, 2, 1))     # op_cnt 2, SET, SetSystem
        self.assertEqual((bool(b1 & 0x80), bool(b1 & 0x40)), (True, False))  # Button fest (keiner), Seite Register
        dst, src = struct.unpack(">II", raw[4:12])
        self.assertEqual((dst, src), (0, 0x80000000 | GPR_PAGE_NOW))

    def test_start_page_clears_the_wish_before_switching(self):
        """SetButtonPage beendet ein Button-Programm: GPR 7 muss vorher zurückgesetzt sein."""
        cmds = start_page_commands(1)
        self.assertEqual(cmds[-2:], [cmd_set_button_page_from_registers(GPR_PAGE_NOW),
                                     cmd_set_button_page_from_registers(GPR_PAGE_NOW, GPR_BUTTON_NOW)])
        self.assertEqual(len(cmds), 9)

    def test_movie_objects(self):
        plain = build_standard_movie_objects(num_titles=2)
        self.assertEqual(plain, build_standard_movie_objects(num_titles=2, menu_groups=[(0, False)]))
        grouped = build_standard_movie_objects(num_titles=2, menu_groups=[(0, True), (3, True)])
        self.assertEqual(struct.unpack(">H", grouped[48:50])[0], 5)       # FirstPlay, TopMenu, 2 Titel, Gruppe 1
        self.assertEqual((menu_group_object(2, 1), menu_group_playlist(2, 1)), (4, 3))
        self.assertEqual(menu_loop_commands(3, 0, True, 4)[1][4:8], struct.pack(">I", GPR_MENU_PAGE))
        no_resume = build_standard_movie_objects(num_titles=1, menu_resume=False)
        self.assertEqual(no_resume[50:52], b"\x60\x00")                    # First Play ohne resume_intention


class TestSimulatedDisc(SimDiscTestCase):
    def _disc(self, project):
        sim = build_simulation_disc(project, os.path.join(self.tmp.name, "SIM"))
        return load_disc(sim.root)

    def test_two_backgrounds_navigate_and_keep_the_page(self):
        project, main, pages, lang = two_backgrounds()
        disc = self._disc(project)
        n = len(project.films)
        group_pl = menu_group_playlist(n, 1)
        self.assertEqual(sorted(disc.compositions), [0, group_pl])
        for tv_3d in (True, False):
            report = explore(disc, tv_3d=tv_3d)
            self.assertTrue(report.ok)
            self.assertEqual([f.code for f in report.findings if f.level == "warnung"], [])
            self.assertNotIn("menue_schleife_seite", [f.code for f in report.findings])   # 11.2.4 behoben
            self.assertIn(group_pl, report.playlists_reached)

        plan = build_export_plan(project)
        p = Player(disc)
        p.insert_disc()
        self.assertEqual((p.state, p.playlist_id, p.page_id), (STATE_MENU, 0, plan.page_ids[main.id]))
        # Hauptmenü → KAPITEL: andere Playlist, erste Kapitelseite
        link = next(i for i, b in enumerate(main.buttons, start=1) if b.label == "KAPITEL")
        p.activate_button(link)
        self.assertEqual((p.playlist_id, p.page_id), (group_pl, plan.page_ids[pages[0].id]))
        # WEITER auf Seite 2 (gleiche Gruppe), dann läuft die Schleife ab: Seite bleibt
        weiter = next(i for i, b in enumerate(pages[0].buttons, start=1) if b.label == "WEITER")
        p.activate_button(weiter)
        self.assertEqual(p.page_id, plan.page_ids[pages[1].id])
        p.select_button(2)                                      # Auswahl auf einem anderen Button
        p.playlist_end()
        self.assertEqual((p.playlist_id, p.page_id), (group_pl, plan.page_ids[pages[1].id]))
        self.assertEqual(p.selected_button, 2)                  # Seite und Button bleiben (Hardware-Test v1.13.0)
        self.assertEqual(p.regs.gpr[GPR_MENU_PAGE], 0)
        p.select_button(1)
        # Kapitel starten, Film zu Ende: zurück ins Hauptmenü (Gruppe 0)
        p.activate_button(1)
        self.assertEqual(p.state, STATE_FILM)
        p.playlist_end()
        self.assertEqual((p.playlist_id, p.page_id), (0, plan.page_ids[main.id]))
        # Sprachmenü bleibt in Gruppe 0 (ohne Ladepause)
        lang_link = next(i for i, b in enumerate(main.buttons, start=1) if b.label == "SPRACHE")
        p.activate_button(lang_link)
        self.assertEqual((p.playlist_id, p.page_id), (0, plan.page_ids[lang.id]))

    def test_single_group_loop_keeps_the_page(self):
        """Eine Gruppe mit Kapitelmenü: die Schleife zeigt danach dieselbe Seite (bisher: Hauptmenü, 11.2.4)."""
        project = make_project(chapters=3, chapter_menu=True)
        disc = self._disc(project)
        plan = build_export_plan(project)
        page = project.menus[1]
        p = Player(disc)
        p.insert_disc()
        p.activate_button(2)                                   # KAPITEL
        self.assertEqual(p.page_id, plan.page_ids[page.id])
        p.playlist_end()
        self.assertEqual(p.page_id, plan.page_ids[page.id])

    def test_menu_objects_without_resume(self):
        project, *_ = two_backgrounds(language=False)
        project.settings.menu_resume = False
        disc = self._disc(project)
        menu_objects = [0, 1, menu_group_object(len(project.films), 1)]
        self.assertTrue(all(not disc.movie_objects[i].resume_intention and disc.movie_objects[i].menu_call_mask
                            for i in menu_objects))
        self.assertTrue(disc.movie_objects[2].resume_intention)          # Titel unverändert
        self.assertTrue(explore(disc).ok)


if __name__ == "__main__":
    unittest.main()
