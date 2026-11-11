# tests/test_play_2d.py
"""
3D-Filme wahlweise in 2D (v1.20): Ein Button, der direkt einen 3D-Film startet, wählt 3D oder 2D. Auf der Disc
merkt er die Wahl in GPR 16, die 3D-Titel schalten danach mit SetOutputMode auf 3D oder ausdrücklich auf 2D.
Kapitel, Film → Film und Top Menu behalten die zuletzt gewählte Wiedergabe. Ohne 2D-Button byte-gleich.
"""

import unittest

from core.disc_adapter import build_export_plan
from core.disc_edit import add_film, add_nav_button
from core.disc_model import BUTTON_CHAPTER
from core.disc_rules import starts_3d_film
from core.menu_templates import create_chapter_menus
from modules.bdmv.movie_object_generator import (
    title_commands, output_mode_commands, output_choice_commands, play_mode_commands, cmd_jump_title,
    GPR_PLAY_2D,
)
from modules.bdsim.explore import explore
from modules.bdsim.hdmv import Machine, decode_command, PSR_3D_STATUS
from modules.bdsim.player import Player, STATE_FILM, STATE_MENU
from modules.igs.layout import MenuButtonSpec
from tests.test_inspector_selection import InspectorCase, choose
from tests.test_sim_disc import SimDiscTestCase, make_project


def project_3d(play_2d_button: bool = True):
    """3D-Hauptfilm mit Kapitelmenü; im Hauptmenü FILM STARTEN (3D) und auf Wunsch FILM 2D."""
    project, film = make_project(chapters=3, audio=("deu",), subs=())
    film.video_mvc = "film.mvc"
    create_chapter_menus(project, film.id, parent_id=project.main_menu.id)
    if play_2d_button:
        add_nav_button(project, project.main_menu.id, "FILM 2D", film.id).play_2d = True
    return project, film


def button_no(menu, label: str) -> int:
    return next(i for i, b in enumerate(menu.buttons, start=1) if b.label == label)


class TestCommands(unittest.TestCase):
    def _run(self, play_2d: int, player_3d: bool = True):
        commands = title_commands(1, True, with_2d_choice=True)
        m = Machine([type("MO", (), {"commands": [decode_command(c) for c in commands]})()], title_count=1,
                    player_3d=player_3d)
        m.regs.gpr[GPR_PLAY_2D] = play_2d
        m.regs.psr[PSR_3D_STATUS] = 1                       # Player steht nach dem Einlegen schon in 3D
        m.start_object(0)
        return m, m.run()

    def test_choice_switches_3d_or_2d(self):
        m, events = self._run(0)
        self.assertEqual([(e.kind, e.a) for e in events], [("play", 1)])
        self.assertEqual(m.regs.psr[PSR_3D_STATUS] & 1, 1)
        self.assertFalse(m.wants_2d)
        m, events = self._run(1)
        self.assertEqual([(e.kind, e.a) for e in events], [("play", 1)])
        self.assertEqual(m.regs.psr[PSR_3D_STATUS] & 1, 0)  # aktiv auf 2D, nicht nur ohne Umschaltung
        self.assertTrue(m.wants_2d)

    def test_player_without_3d_skips_both(self):
        m, events = self._run(1, player_3d=False)
        self.assertEqual([(e.kind, e.a) for e in events], [("play", 1)])
        self.assertFalse(m.wants_2d)                        # SetOutputMode nicht ausgeführt (Profilprüfung)

    def test_both_branches_are_guarded(self):
        cmds = output_choice_commands(0)
        self.assertEqual(cmds[2:6], output_mode_commands(1))
        self.assertEqual(cmds[7:11], output_mode_commands(0))
        self.assertEqual(len(cmds), 11)

    def test_without_choice_unchanged(self):
        self.assertEqual(title_commands(1, True), title_commands(1, True, with_2d_choice=False))
        self.assertEqual(title_commands(2, False, with_2d_choice=True), title_commands(2, False))

    def test_button_commands(self):
        spec = MenuButtonSpec(button_id=1, text="FILM", action_type="jump_title", target_title_id=2)
        self.assertEqual(spec.get_nav_commands(), [cmd_jump_title(2)])
        spec.play_2d = False
        self.assertEqual(spec.get_nav_commands(), play_mode_commands(False) + [cmd_jump_title(2)])
        spec.play_2d = True
        self.assertEqual(spec.get_nav_commands(), play_mode_commands(True) + [cmd_jump_title(2)])


class TestAdapter(unittest.TestCase):
    def _specs(self, plan):
        return [s for _page, specs in plan.pages_specs for s in specs]

    def test_no_2d_button_is_unchanged(self):
        project, film = project_3d(play_2d_button=False)
        plan = build_export_plan(project)
        self.assertFalse(plan.project_state.with_2d_choice)
        self.assertTrue(all(s.play_2d is None for s in self._specs(plan)))

    def test_all_3d_starts_remember_their_choice(self):
        project, film = project_3d()
        bonus = add_film(project, "Bonus", (0.0, 0.0))
        bonus.video_base = "bonus.264"
        add_nav_button(project, project.main_menu.id, "BONUS", bonus.id).play_2d = True   # 2D-Film: ohne Wirkung
        plan = build_export_plan(project)
        self.assertTrue(plan.project_state.with_2d_choice)
        by_text = {s.text: s.play_2d for s in self._specs(plan)}
        self.assertEqual((by_text["FILM STARTEN"], by_text["FILM 2D"], by_text["BONUS"]), (False, True, None))

    def test_2d_flag_on_a_2d_film_only(self):
        project, film = project_3d(play_2d_button=False)
        film.video_mvc = None
        project.main_menu.buttons[0].play_2d = True
        self.assertFalse(starts_3d_film(project, project.main_menu.buttons[0]))
        self.assertFalse(build_export_plan(project).project_state.with_2d_choice)


class TestSimulatedDisc(SimDiscTestCase):
    def _chapter_button(self, project):
        """(Button im Hauptmenü zum Kapitelmenü, Kapitel-1-Button im Kapitelmenü)"""
        main = project.main_menu
        to_chapters = next(i for i, b in enumerate(main.buttons, start=1) if project.menu(b.target) is not None)
        chapters = project.menu(main.buttons[to_chapters - 1].target)
        first = next(i for i, b in enumerate(chapters.buttons, start=1) if b.kind == BUTTON_CHAPTER)
        return to_chapters, first

    def test_2d_then_chapter_then_3d(self):
        project, film = project_3d()
        _, disc = self.simulate(project)
        self.assert_clean(disc)
        main = project.main_menu
        film_3d, film_2d = button_no(main, "FILM STARTEN"), button_no(main, "FILM 2D")
        to_chapters, chapter_1 = self._chapter_button(project)

        p = Player(disc, tv_3d=True)
        p.insert_disc()
        p.activate_button(film_2d)
        self.assertEqual(p.state, STATE_FILM)
        self.assertFalse(p.output_3d)
        p.press("top_menu")
        self.assertEqual(p.state, STATE_MENU)
        self.assertFalse(p.output_3d)
        p.activate_button(to_chapters)
        p.activate_button(chapter_1)                         # Kapitel behalten die 2D-Wahl
        self.assertEqual(p.state, STATE_FILM)
        self.assertFalse(p.output_3d)
        p.playlist_end()
        self.assertEqual(p.state, STATE_MENU)
        p.activate_button(film_3d)
        self.assertTrue(p.output_3d)
        p.playlist_end()
        self.assertFalse(p.output_3d)                        # Menü wieder in 2D
        p.activate_button(to_chapters)
        p.activate_button(chapter_1)
        self.assertTrue(p.output_3d)

    def test_report_names_the_2d_start(self):
        project, film = project_3d()
        _, disc = self.simulate(project)
        codes = [f.code for f in explore(disc, tv_3d=True).findings]
        self.assertIn("3d_film_in_2d", codes)
        self.assertNotIn("3d_ohne_umschaltung", codes)


class TestInspector(InspectorCase):
    def test_play_mode_only_for_a_3d_film(self):
        main = self.project.main_menu
        button_id = next(b.id for b in main.buttons if b.target == self.film_id)
        self.page_id = main.id
        self._select_node(main.id)
        self._pick(button_id)
        self.assertFalse(self.page.play_mode_row.isVisibleTo(self.page))         # 2D-Film: keine Wahl
        self.project.film(self.film_id).video_mvc = "film.mvc"
        self.page.refresh()
        self.assertTrue(self.page.play_mode_row.isVisibleTo(self.page))
        self.assertEqual(self.page.combo_play_mode.currentData(), "3d")
        steps = self.ctrl.undo_stack.count()
        choose(self.page.combo_play_mode, "2d")
        self.assertTrue(self.project.main_menu.button(button_id).play_2d)
        self.assertEqual(self.ctrl.undo_stack.count(), steps + 1)
        self.ctrl.undo_stack.undo()
        self.assertFalse(self.project.main_menu.button(button_id).play_2d)


if __name__ == "__main__":
    unittest.main()
