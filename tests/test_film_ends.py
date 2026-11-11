# tests/test_film_ends.py
"""
Freie Film-Enden (v1.18.0, Stufe 2.1): Ein Film endet in einem beliebigen Menü statt im Hauptmenü, z. B. das
Making-of im Extras-Menü. Auf der Disc wie ein Button in ein anderes Menü (v1.13): Seite in GPR 7, Button in
GPR 8, Menü-Objekt der Gruppe starten; dessen Startseite zeigt beides. Unverbundene Enden bleiben byte-gleich.
v1.18.1: Film → Film (JumpTitle am Filmende, z. B. „Alle Folgen“) und Start → Film (Trailer vor dem Menü,
JumpTitle in First Play); das Hauptmenü ist das Menü am Ende der Start-Kette.
"""

import os
import unittest

from core.disc_adapter import build_export_plan, reachable_menus, return_button
from core.disc_edit import add_film, add_menu, add_nav_button
from core.disc_model import STYLE_TEXT, START_NODE_ID
from core.disc_rules import start_chain_problems, film_cycles
from core.preflight import run_preflight, WARNING, ERROR
from modules.bdmv.movie_object_generator import (
    build_standard_movie_objects, film_end_commands, title_commands, stream_capture_commands,
    menu_group_object, menu_group_playlist, cmd_jump_object, cmd_jump_title, output_mode_commands,
    GPR_MENU_PAGE, GPR_MENU_BUTTON, GPR_AUDIO, GPR_FILM_PLAYED,
)
from modules.bdsim.explore import explore
from modules.bdsim.player import Player, STATE_MENU, STATE_FILM
from tests.project_factory import make_project
from tests.test_sim_disc import SimDiscTestCase


def extras_project(own_background: bool = True, language: bool = False):
    """Hauptmenü mit FILM STARTEN und EXTRAS; Extras-Menü mit ZURÜCK, TRAILER und MAKING-OF.
    Das Making-of endet im Extras-Menü, der Trailer (unverbunden) im Hauptmenü."""
    project = make_project(audio=3 if language else 0, language_menu=language)
    main = project.main_menu
    trailer = add_film(project, "Trailer", (700.0, 200.0))
    making_of = add_film(project, "Making-of", (700.0, 400.0))
    trailer.video_base, making_of.video_base = "C:/clips/trailer.264", "C:/clips/making_of.264"
    extras = add_menu(project, "Extras", (400.0, 300.0))
    extras.button_style.kind = STYLE_TEXT
    extras.buttons[0].target = main.id                                    # ZURÜCK
    add_nav_button(project, extras.id, "TRAILER", trailer.id)
    add_nav_button(project, extras.id, "MAKING-OF", making_of.id)
    add_nav_button(project, main.id, "EXTRAS", extras.id)
    if own_background:
        main.background.image = "C:/haupt.png"
        extras.background.image = "C:/extras.png"
    making_of.end_target = extras.id
    return project, main, extras, trailer, making_of


def button_no(menu, label: str) -> int:
    return next(i for i, b in enumerate(menu.buttons, start=1) if b.label == label)


class TestCommands(unittest.TestCase):
    def test_default_title_is_unchanged(self):
        self.assertEqual(title_commands(1, False), title_commands(1, False, end_commands=None))
        self.assertEqual(title_commands(1, False)[-1], cmd_jump_object(1))
        self.assertEqual(build_standard_movie_objects(num_titles=2),
                         build_standard_movie_objects(num_titles=2, title_ends={}))

    def test_end_in_other_menu(self):
        end = film_end_commands(4, 1, 3)
        self.assertEqual(len(end), 3)
        self.assertEqual(film_end_commands(4, 1), [end[0], end[2]])       # ohne Button-Wunsch kein GPR 8
        cmds = title_commands(2, False, end_commands=end)
        self.assertEqual(cmds[-3:], end)
        self.assertNotIn(cmd_jump_object(1), cmds)

    def test_streams_are_captured_before_leaving(self):
        """Nur das TopMenu-Objekt übernimmt die Spuren beim Menüeintritt – bei einem anderen Ziel der Titel selbst."""
        end = film_end_commands(4, 1)
        cmds = title_commands(1, False, with_streams=True, end_commands=end)
        capture = stream_capture_commands()
        self.assertEqual(cmds[-len(end) - len(capture):-len(end)], capture)
        self.assertNotIn(capture[0], title_commands(1, False, with_streams=True))


class TestAdapter(unittest.TestCase):
    def test_unconnected_and_main_menu_end_are_unchanged(self):
        project, main, extras, trailer, making_of = extras_project()
        making_of.end_target = None
        plain = build_export_plan(project)
        self.assertIsNone(plain.project_state.title_ends)
        making_of.end_target = main.id
        to_main = build_export_plan(project)
        self.assertIsNone(to_main.project_state.title_ends)
        self.assertEqual([p for p, _ in to_main.menu_groups[1]["pages_specs"]],
                         [p for p, _ in plain.menu_groups[1]["pages_specs"]])

    def test_end_in_menu_with_own_background(self):
        project, main, extras, trailer, making_of = extras_project()
        plan = build_export_plan(project)
        n = len(project.films)
        self.assertEqual(plan.group_of[extras.id], 1)
        # Eine Seite, trotzdem Startseite: sie wählt nach dem Film Seite und Button
        self.assertTrue(plan.menu_groups[1]["keep_page"])
        self.assertEqual([p for p, _ in plan.menu_groups[1]["pages_specs"]], [0, 1])
        self.assertEqual(plan.page_ids[extras.id], 1)
        title = plan.title_ids[making_of.id]
        self.assertEqual(plan.project_state.title_ends,
                         {title: film_end_commands(menu_group_object(n, 1), 1, button_no(extras, "MAKING-OF"))})

    def test_end_in_menu_like_main_menu(self):
        project, main, extras, trailer, making_of = extras_project(own_background=False)
        plan = build_export_plan(project)
        self.assertEqual(plan.group_of[extras.id], 0)
        title = plan.title_ids[making_of.id]
        self.assertEqual(plan.project_state.title_ends[title],
                         film_end_commands(1, plan.page_ids[extras.id], button_no(extras, "MAKING-OF")))

    def test_return_button_only_if_unique(self):
        project, main, extras, trailer, making_of = extras_project()
        self.assertEqual(return_button(project, extras, making_of).label, "MAKING-OF")
        self.assertIsNone(return_button(project, extras, project.films[0]))
        add_nav_button(project, extras.id, "NOCHMAL", making_of.id)
        self.assertIsNone(return_button(project, extras, making_of))
        plan = build_export_plan(project)
        self.assertEqual(plan.project_state.title_ends[plan.title_ids[making_of.id]],
                         film_end_commands(menu_group_object(len(project.films), 1), 1))

    def test_menu_reached_only_by_film_end(self):
        """Ein Menü, in das nur ein Filmende führt, landet auf der Disc und gilt als erreichbar."""
        project, main, extras, trailer, making_of = extras_project()
        bonus = add_menu(project, "Danke", (900.0, 600.0))
        bonus.button_style.kind = STYLE_TEXT
        bonus.buttons[0].target = main.id
        trailer.end_target = bonus.id
        self.assertIn(bonus.id, reachable_menus(project))
        self.assertNotIn((WARNING, bonus.id),
                         [(i.level, i.node_id) for i in run_preflight(project, check_files=False)])
        plan = build_export_plan(project)
        self.assertIn(bonus.id, plan.page_ids)
        self.assertEqual(len(plan.project_state.title_ends), 2)


class TestSimulatedDisc(SimDiscTestCase):
    def _play_making_of(self, project, extras):
        sim, disc = self.simulate(project)
        self.assert_clean(disc)
        main = project.main_menu
        p = Player(disc)
        p.insert_disc()
        p.activate_button(button_no(main, "EXTRAS"))
        p.activate_button(button_no(extras, "MAKING-OF"))
        self.assertEqual(p.state, STATE_FILM)
        p.playlist_end()
        return p

    def test_making_of_returns_to_extras(self):
        project, main, extras, trailer, making_of = extras_project()
        plan = build_export_plan(project)
        p = self._play_making_of(project, extras)
        self.assertEqual((p.state, p.playlist_id, p.page_id),
                         (STATE_MENU, menu_group_playlist(len(project.films), 1), plan.page_ids[extras.id]))
        self.assertEqual(p.selected_button, button_no(extras, "MAKING-OF"))
        self.assertEqual((p.regs.gpr[GPR_MENU_PAGE], p.regs.gpr[GPR_MENU_BUTTON]), (0, 0))
        # Die Menü-Schleife behält Seite und Button
        p.playlist_end()
        self.assertEqual((p.page_id, p.selected_button), (plan.page_ids[extras.id], button_no(extras, "MAKING-OF")))
        # Trailer (unverbunden): zurück ins Hauptmenü
        p.activate_button(button_no(extras, "TRAILER"))
        p.playlist_end()
        self.assertEqual((p.playlist_id, p.page_id), (0, plan.page_ids[main.id]))

    def test_making_of_returns_to_extras_like_main_menu(self):
        project, main, extras, trailer, making_of = extras_project(own_background=False)
        plan = build_export_plan(project)
        p = self._play_making_of(project, extras)
        self.assertEqual((p.playlist_id, p.page_id), (0, plan.page_ids[extras.id]))
        self.assertEqual(p.selected_button, button_no(extras, "MAKING-OF"))

    def test_film_track_survives_ending_in_extras(self):
        """Hauptfilm mit Sprachmenü endet im Extras-Menü: die im Film gewählte Tonspur gilt beim nächsten Start."""
        project, main, extras, trailer, making_of = extras_project(language=True)
        film = project.films[0]
        film.end_target = extras.id
        sim, disc = self.simulate(project)
        p = Player(disc)
        p.insert_disc()
        p.activate_button(button_no(main, "FILM STARTEN"))
        p.press("audio")                                                  # Tonspur 1 → 2 im Film
        p.playlist_end()
        self.assertEqual((p.state, p.page_id), (STATE_MENU, build_export_plan(project).page_ids[extras.id]))
        self.assertEqual((p.regs.gpr[GPR_AUDIO], p.regs.gpr[GPR_FILM_PLAYED]), (2, 0))


# ─────────────────────────────── v1.18.1: Film → Film, Start → Film ───────────────────────────────

def object_commands(data: bytes, object_id: int) -> bytes:
    """Befehle (Rohbytes) eines MovieObjects aus MovieObject.bdmv."""
    import struct
    pos = 50
    for _ in range(object_id):
        pos += 4 + 12 * struct.unpack(">H", data[pos + 2:pos + 4])[0]
    count = struct.unpack(">H", data[pos + 2:pos + 4])[0]
    return data[pos + 4:pos + 4 + 12 * count]


class TestFilmAfterFilm(unittest.TestCase):
    def test_next_title_and_3d(self):
        """Nummer statt Befehlen: JumpTitle; zwischen zwei 3D-Filmen kein Umschalten auf 2D."""
        data = build_standard_movie_objects(num_titles=3, titles_3d=[1, 2], title_ends={1: 2, 2: 3})
        to_3d = title_commands(1, True, end_commands=[cmd_jump_title(2)], stay_3d=True)
        to_2d = title_commands(2, True, end_commands=[cmd_jump_title(3)])
        self.assertEqual(object_commands(data, 2), b"".join(to_3d))
        self.assertEqual(object_commands(data, 3), b"".join(to_2d))
        self.assertEqual(to_3d[-1], cmd_jump_title(2))
        self.assertNotIn(output_mode_commands(0)[-1], to_3d)
        self.assertIn(output_mode_commands(0)[-1], to_2d)

    def test_first_play_title(self):
        data = build_standard_movie_objects(num_titles=2, first_play_title=2)
        self.assertEqual(object_commands(data, 0), cmd_jump_title(2))

    def test_adapter(self):
        project, main, extras, trailer, making_of = extras_project()
        film = project.films[0]
        film.end_target = making_of.id                                     # Hauptfilm → Making-of → Extras
        plan = build_export_plan(project)
        ends = plan.project_state.title_ends
        self.assertEqual(ends[plan.title_ids[film.id]], plan.title_ids[making_of.id])
        self.assertIsInstance(ends[plan.title_ids[making_of.id]], list)
        self.assertIsNone(getattr(plan.project_state, "first_play_title", None))

    def test_menu_after_film_chain_is_reachable(self):
        project, main, extras, trailer, making_of = extras_project()
        bonus = add_menu(project, "Danke", (900.0, 600.0))
        bonus.buttons[0].target = main.id
        making_of.end_target = trailer.id                                  # Making-of → Trailer → Danke
        trailer.end_target = bonus.id
        self.assertIn(bonus.id, reachable_menus(project))

    def test_cycle_is_a_warning(self):
        project, main, extras, trailer, making_of = extras_project()
        trailer.end_target = making_of.id
        making_of.end_target = trailer.id
        self.assertEqual([[f.name for f in c] for c in film_cycles(project)], [["Trailer", "Making-of"]])
        issues = run_preflight(project, check_files=False)
        self.assertIn((WARNING, trailer.id), [(i.level, i.node_id) for i in issues])
        self.assertFalse([i for i in issues if i.level == ERROR])


class TestStartWithFilm(unittest.TestCase):
    def test_main_menu_follows_the_chain(self):
        project, main, extras, trailer, making_of = extras_project()
        project.start_target = trailer.id
        self.assertIsNone(project.main_menu)                                # Trailer-Ende noch offen
        self.assertTrue(start_chain_problems(project))
        trailer.end_target = main.id
        self.assertIs(project.main_menu, main)
        self.assertEqual(start_chain_problems(project), [])
        plan = build_export_plan(project)
        self.assertEqual(plan.project_state.first_play_title, plan.title_ids[trailer.id])
        self.assertNotIn(plan.title_ids[trailer.id], plan.project_state.title_ends)   # Ende = Hauptmenü

    def test_disc_without_menu_is_unchanged(self):
        project = make_project()
        project.start_target = project.films[0].id
        self.assertIsNone(project.main_menu)
        self.assertEqual(start_chain_problems(project), [])
        self.assertIsNone(build_export_plan(project).pages_specs)

    def test_chain_without_menu_is_an_error(self):
        project, main, extras, trailer, making_of = extras_project()
        project.start_target = trailer.id
        trailer.end_target = making_of.id
        making_of.end_target = None
        problems = start_chain_problems(project)
        self.assertEqual(len(problems), 1)
        self.assertIn("Making-of", problems[0])
        self.assertIn((ERROR, START_NODE_ID),
                      [(i.level, i.node_id) for i in run_preflight(project, check_files=False)])


class TestSimulatedChains(SimDiscTestCase):
    def test_trailer_before_menu(self):
        project, main, extras, trailer, making_of = extras_project()
        project.start_target = trailer.id
        trailer.end_target = main.id
        sim, disc = self.simulate(project)
        self.assert_clean(disc)
        plan = build_export_plan(project)
        p = Player(disc)
        p.insert_disc()
        self.assertEqual((p.state, p.title), (STATE_FILM, plan.title_ids[trailer.id]))
        p.playlist_end()
        self.assertEqual((p.state, p.playlist_id, p.page_id), (STATE_MENU, 0, plan.page_ids[main.id]))
        # Top Menu überspringt den Trailer
        p = Player(disc)
        p.insert_disc()
        p.press("top_menu")
        self.assertEqual((p.state, p.page_id), (STATE_MENU, plan.page_ids[main.id]))

    def test_main_film_then_making_of_then_extras(self):
        project, main, extras, trailer, making_of = extras_project(language=True)
        project.films[0].end_target = making_of.id
        sim, disc = self.simulate(project)
        self.assert_clean(disc)
        plan = build_export_plan(project)
        p = Player(disc)
        p.insert_disc()
        p.activate_button(button_no(main, "FILM STARTEN"))
        p.press("audio")                                                  # Tonspur 2 im Hauptfilm
        p.playlist_end()
        self.assertEqual((p.state, p.title), (STATE_FILM, plan.title_ids[making_of.id]))
        self.assertEqual(p.regs.gpr[GPR_AUDIO], 2)                         # vor dem Wechsel gesichert
        p.playlist_end()
        self.assertEqual((p.state, p.page_id, p.selected_button),
                         (STATE_MENU, plan.page_ids[extras.id], button_no(extras, "MAKING-OF")))

    def test_film_cycle_runs_and_top_menu_leads_out(self):
        project, main, extras, trailer, making_of = extras_project()
        trailer.end_target = making_of.id
        making_of.end_target = trailer.id
        sim, disc = self.simulate(project)
        for tv_3d in (True, False):
            self.assertTrue(explore(disc, tv_3d=tv_3d).ok)


if __name__ == "__main__":
    unittest.main()
