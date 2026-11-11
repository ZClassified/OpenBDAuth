# tests/test_bdsim.py
"""
Tests für den Disc-Simulator (modules/bdsim): Befehle, HDMV-Maschine, Player und automatischer
Durchlauf. Die Test-Discs entstehen aus den Generatoren des Projekts (ohne tsMuxeR).
"""

import os
import struct
import tempfile
import unittest

from modules.bdmv.index_generator import build_index_bdmv
from modules.bdmv.movie_object_generator import (
    build_standard_movie_objects, cmd_set_button_page, cmd_set_stream, cmd_jump_title, cmd_jump_object,
    cmd_play_playlist_at_mark, make_hdmv_cmd, INSN_GROUP_SET, title_commands,
    GPR_CHAPTER, GPR_AUDIO, GPR_SUBTITLE, GPR_SUBTITLE_MODE, SUB_ON, SUB_OFF,
)
from modules.bdsim.disc import load_disc, DiscReadError
from modules.bdsim.explore import explore, format_report
from modules.bdsim.hdmv import decode_command, Machine, PSR_PRIMARY_AUDIO, PSR_PG_STREAM, PSR_3D_STATUS
from modules.bdsim.player import Player, STATE_MENU, STATE_FILM
from modules.igs.layout import MenuButtonSpec
from modules.menu_author import generate_menu_subclip, resolve_chapter_jumps, stream_choice_titles
from modules.mpls.mpls_generator import build_movie_mpls, write_menu_mpls_file

# SetButtonPage(1), wie ihn v1.7.6 geschrieben hat (Register-Arithmetik statt SetSystem)
OLD_SET_BUTTON_PAGE_1 = bytes([0x30, 0x80, 0x00, 0x03]) + struct.pack(">II", 1, 0)


def codes(report, level=None):
    return {f.code for f in report.findings if level is None or f.level == level}


def build_test_disc(root: str, pages_specs, num_titles: int, titles_3d=None):
    """Legt eine BDMV-Struktur an: Menü (00000.mpls + IG-Clip 00002) und Filme 00001..0000N.
    Kapitel- und Spur-Titel werden wie in inject_menu_into_bdmv aus den Buttons ermittelt."""
    bdmv = os.path.join(root, "BDMV")
    for sub in ("PLAYLIST", "STREAM", "CLIPINF"):
        os.makedirs(os.path.join(bdmv, sub), exist_ok=True)
    for t in range(1, num_titles + 1):
        with open(os.path.join(bdmv, "PLAYLIST", f"{t:05d}.mpls"), "wb") as f:
            f.write(build_movie_mpls(clip_id=f"{t + 2:05d}", duration_sec=20.0, audio_pid=0x1100))
    chapter_titles = resolve_chapter_jumps(pages_specs, os.path.join(bdmv, "PLAYLIST"))
    with open(os.path.join(bdmv, "index.bdmv"), "wb") as f:
        f.write(build_index_bdmv(num_titles=num_titles, has_3d=bool(titles_3d)))
    with open(os.path.join(bdmv, "MovieObject.bdmv"), "wb") as f:
        f.write(build_standard_movie_objects(num_titles=num_titles, titles_3d=titles_3d or [],
                                             chapter_titles=chapter_titles,
                                             stream_titles=stream_choice_titles(pages_specs)))
    generate_menu_subclip(
        output_m2ts_path=os.path.join(bdmv, "STREAM", "00002.m2ts"),
        output_clpi_path=os.path.join(bdmv, "CLIPINF", "00002.clpi"),
        pages_specs=pages_specs)
    write_menu_mpls_file(os.path.join(bdmv, "PLAYLIST", "00000.mpls"), bg_clip_id="00001", igs_clip_id="00002")
    return root


def main_and_extras_pages(extras_command=None):
    """Hauptmenü: Film 1, Film 2, EXTRAS -> Seite 1: Film 3, ZURÜCK."""
    extras = MenuButtonSpec(button_id=3, text="EXTRAS", action_type="set_page", target_page_id=1)
    if extras_command is not None:
        extras.nav_commands = [extras_command]
    return [
        (0, [MenuButtonSpec(button_id=1, text="FILM 1", target_title_id=1),
             MenuButtonSpec(button_id=2, text="FILM 2", target_title_id=2),
             extras]),
        (1, [MenuButtonSpec(button_id=1, text="MAKING-OF", target_title_id=3),
             MenuButtonSpec(button_id=2, text="ZURÜCK", action_type="set_page", target_page_id=0)]),
    ]


class TestCommands(unittest.TestCase):
    def test_text_of_system_commands(self):
        self.assertEqual(decode_command(cmd_set_button_page(1)).text(), "SetButtonPage(Seite 1)")
        self.assertEqual(decode_command(cmd_jump_title(2)).text(), "JumpTitle(2)")
        self.assertEqual(decode_command(cmd_set_stream(audio_id=2)).text(), "SetStream(Ton 2, Untertitel aus)")
        self.assertEqual(decode_command(cmd_play_playlist_at_mark(1, 3)).text(), "PlayPLatPM(1, 3)")

    def test_old_set_button_page_is_arithmetic(self):
        cmd = decode_command(OLD_SET_BUTTON_PAGE_1)
        self.assertEqual(cmd.name, "Add")


class TestMachine(unittest.TestCase):
    def _run_button(self, *raw_cmds):
        findings = []
        m = Machine([], title_count=2, report=lambda lvl, code, text: findings.append(code))
        m.start_button([decode_command(c) for c in raw_cmds])
        return m, m.run(), findings

    def test_register_arithmetic_and_compare_skip(self):
        move_5 = make_hdmv_cmd(op_cnt=2, grp=INSN_GROUP_SET, sub_grp=0, imm_op1=0, imm_op2=1, set_opt=1, dst=7, src=5)
        add_3 = make_hdmv_cmd(op_cnt=2, grp=INSN_GROUP_SET, sub_grp=0, imm_op1=0, imm_op2=1, set_opt=3, dst=7, src=3)
        # EQ GPR7 == 5 ist falsch -> nächster Befehl (Add) wird übersprungen
        eq_5 = make_hdmv_cmd(op_cnt=2, grp=1, sub_grp=0, imm_op1=0, imm_op2=1, cmp_opt=2, dst=7, src=5)
        m, events, findings = self._run_button(move_5, add_3, eq_5, add_3)
        self.assertEqual(m.regs.gpr[7], 8)
        self.assertEqual([e.kind for e in events], ["ig_end"])
        self.assertEqual(findings, [])

    def test_set_stream_writes_psr(self):
        m, _, _ = self._run_button(cmd_set_stream(audio_id=2), cmd_set_stream(subtitle_id=1, subtitle_on=True))
        self.assertEqual(m.regs.psr[PSR_PRIMARY_AUDIO], 2)
        self.assertEqual(m.regs.psr[PSR_PG_STREAM] & 0xFFF, 1)
        self.assertTrue(m.regs.psr[PSR_PG_STREAM] & 0x80000000)

    def test_audio_only_set_stream_turns_subtitles_off_like_libbluray(self):
        m, _, _ = self._run_button(cmd_set_stream(subtitle_id=1, subtitle_on=True), cmd_set_stream(audio_id=2))
        self.assertFalse(m.regs.psr[PSR_PG_STREAM] & 0x80000000)

    def test_set_button_page_ends_button_commands(self):
        m, events, _ = self._run_button(cmd_set_button_page(1), cmd_jump_title(1))
        self.assertEqual([(e.kind, e.b) for e in events], [("button_page", 0x80000001)])

    def test_old_set_button_page_is_reported(self):
        _, events, findings = self._run_button(OLD_SET_BUTTON_PAGE_1)
        self.assertIn("rechnen_mit_festem_ziel", findings)
        self.assertEqual([e.kind for e in events], ["ig_end"])

    def test_playlist_command_in_button_is_rejected(self):
        _, events, findings = self._run_button(cmd_play_playlist_at_mark(1, 0))
        self.assertIn("playlist_im_button", findings)
        self.assertNotIn("play", [e.kind for e in events])

    def test_set_stream_needs_two_operands(self):
        """v1.8.4 schrieb SetStream mit einem Operanden (0x31 …); der Sony ignorierte ihn."""
        old = bytes([0x31, 0x80, 0x00, 0x01]) + struct.pack(">II", 0x80020000, 0)
        _, _, findings = self._run_button(old)
        self.assertIn("operandenzahl", findings)
        _, _, findings = self._run_button(cmd_set_stream(audio_id=2))
        self.assertNotIn("operandenzahl", findings)

    def test_ignored_operand_is_reported(self):
        # PlayPLatPM mit Operandenzahl 1 (bis v1.7.7): der Player liest die Marke nicht
        old = bytes([0x22, 0xC2, 0x00, 0x00]) + struct.pack(">II", 1, 3)
        findings = []
        m = Machine([], title_count=1, report=lambda lvl, code, text: findings.append(code))
        m.movie_objects = [type("MO", (), {"commands": [decode_command(old)]})()]
        m.start_object(0)
        events = m.run()
        self.assertIn("operand_ignoriert", findings)
        self.assertEqual([(e.kind, e.a, e.c) for e in events], [("play", 1, 0)])

    def test_jump_to_missing_title_is_reported(self):
        _, _, findings = self._run_button(cmd_jump_title(5))
        self.assertIn("titel_fehlt", findings)

    def _run_title(self, gprs, **options):
        m = Machine([type("MO", (), {"commands": [decode_command(c) for c in title_commands(1, **options)]})()],
                    title_count=1)
        for reg, value in gprs.items():
            m.regs.gpr[reg] = value
        m.start_object(0)
        return m, m.run()

    def test_title_applies_chapter_and_stream_choice(self):
        m, events = self._run_title({GPR_CHAPTER: 4, GPR_AUDIO: 2, GPR_SUBTITLE: 3, GPR_SUBTITLE_MODE: SUB_ON},
                                    is_3d=False, with_chapters=True, with_streams=True)
        self.assertEqual([(e.kind, e.a, e.b, e.c) for e in events], [("play", 1, 2, 3)])   # PlayPLatPM(1, Marke 3)
        self.assertEqual(m.regs.gpr[GPR_CHAPTER], 0)          # Kapitelwunsch verbraucht
        self.assertEqual(m.regs.psr[PSR_PRIMARY_AUDIO], 2)
        self.assertEqual(m.regs.psr[PSR_PG_STREAM], 0x80000003)

    def test_title_without_choice_plays_from_start(self):
        m, events = self._run_title({}, is_3d=True, with_chapters=True, with_streams=True)
        self.assertEqual([(e.kind, e.a, e.b) for e in events], [("play", 1, 0)])       # PlayPL(1)
        self.assertEqual(m.regs.psr[PSR_PRIMARY_AUDIO], 1)
        self.assertEqual(m.regs.psr[PSR_PG_STREAM], 0x0FFF)
        m.playlist_ended()
        m.run()
        executed = [line.split(": ", 1)[1] for line in m.log]
        self.assertEqual(executed[-3:], ["SetOutputMode(2D)", "JumpObject(1)", "Ende der Befehlsliste"])
        self.assertEqual(m.regs.psr[PSR_3D_STATUS] & 1, 0)

    def test_menu_takes_over_streams_of_last_film(self):
        from modules.bdmv.movie_object_generator import menu_capture_commands, GPR_FILM_PLAYED, cmd_play_playlist
        commands = menu_capture_commands() + [cmd_play_playlist(0)]
        cases = [
            # (Film lief, PSR1, PSR2) -> (GPR1, GPR2, GPR3)
            (1, 2, 0x80000002, (2, 2, SUB_ON)),
            (1, 1, 0x00000002, (1, 2, SUB_OFF)),
            (0, 2, 0x80000002, (0, 0, 0)),          # ohne vorherigen Film: nichts übernehmen
        ]
        for played, audio, pg, expected in cases:
            m = Machine([type("MO", (), {"commands": [decode_command(c) for c in commands]})()], title_count=1)
            m.regs.gpr[GPR_FILM_PLAYED] = played
            m.regs.psr[PSR_PRIMARY_AUDIO], m.regs.psr[PSR_PG_STREAM] = audio, pg
            m.start_object(0)
            events = m.run()
            self.assertEqual([(e.kind, e.a) for e in events], [("play", 0)])
            self.assertEqual((m.regs.gpr[GPR_AUDIO], m.regs.gpr[GPR_SUBTITLE], m.regs.gpr[GPR_SUBTITLE_MODE]), expected)
            self.assertEqual(m.regs.gpr[GPR_FILM_PLAYED], 0)

    def test_title_turns_subtitles_off(self):
        m, _ = self._run_title({GPR_SUBTITLE_MODE: SUB_OFF}, is_3d=False, with_streams=True)
        self.assertFalse(m.regs.psr[PSR_PG_STREAM] & 0x80000000)

    def test_guarded_output_mode_skipped_on_2d_player(self):
        from modules.bdmv.movie_object_generator import output_mode_commands
        for player_3d, expected in ((True, 1), (False, 0)):
            m = Machine([], title_count=1, player_3d=player_3d)
            m.start_button([decode_command(c) for c in output_mode_commands(1)])
            m.run()
            self.assertEqual(m.regs.psr[PSR_3D_STATUS] & 1, expected)

    def test_set_output_mode_needs_3d_player(self):
        from modules.bdmv.movie_object_generator import cmd_set_output_mode
        for player_3d, expected in ((True, 1), (False, 0)):
            m = Machine([], title_count=1, player_3d=player_3d)
            m.start_button([decode_command(cmd_set_output_mode(1))])
            m.run()
            self.assertEqual(m.regs.psr[PSR_3D_STATUS] & 1, expected)


class TestDiscSimulation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def _disc(self, pages_specs, num_titles=3, **kwargs):
        return load_disc(build_test_disc(self.tmp.name, pages_specs, num_titles, **kwargs))

    def test_reads_structure(self):
        disc = self._disc(main_and_extras_pages())
        self.assertEqual(len(disc.index.titles), 3)
        self.assertEqual(disc.index.titles[0].mobj_id, 2)
        self.assertEqual(sorted(disc.playlists), [0, 1, 2, 3])
        comp = disc.compositions[0]
        self.assertEqual([p.page_id for p in comp.pages], [0, 1])
        self.assertEqual([b.button_id for b in comp.page(0).buttons()], [1, 2, 3])
        self.assertEqual(comp.page(0).button(3).commands[0].text(), "SetButtonPage(Seite 1)")
        self.assertEqual(len(comp.objects), 15)
        self.assertEqual(disc.playlists[1].count("audio"), 1)

    def test_player_keys(self):
        disc = self._disc(main_and_extras_pages())
        p = Player(disc)
        p.insert_disc()
        self.assertEqual((p.state, p.playlist_id, p.page_id, p.selected_button), (STATE_MENU, 0, 0, 1))
        p.press("down")
        p.press("down")
        self.assertEqual(p.selected_button, 3)
        p.press("ok")
        self.assertEqual((p.page_id, p.selected_button), (1, 1))
        p.press("ok")
        self.assertEqual((p.state, p.playlist_id, p.title), (STATE_FILM, 3, 3))
        p.playlist_end()
        self.assertEqual((p.state, p.playlist_id, p.page_id), (STATE_MENU, 0, 0))

    def test_top_menu_key_from_film(self):
        disc = self._disc(main_and_extras_pages())
        p = Player(disc)
        p.insert_disc()
        p.activate_button(2)
        self.assertEqual(p.state, STATE_FILM)
        p.press("top_menu")
        self.assertEqual((p.state, p.playlist_id), (STATE_MENU, 0))

    def test_clean_disc_has_no_errors_or_warnings(self):
        report = explore(self._disc(main_and_extras_pages()))
        self.assertTrue(report.ok, format_report(self._disc(main_and_extras_pages()), [report]))
        self.assertEqual(report.titles_reached, {1, 2, 3})
        self.assertEqual(report.pages_reached, {(0, 0), (0, 1)})
        self.assertIn("menue_schleife_seite", codes(report, "hinweis"))

    def test_regression_v176_extras_button(self):
        report = explore(self._disc(main_and_extras_pages(extras_command=OLD_SET_BUTTON_PAGE_1)))
        found = codes(report)
        self.assertIn("rechnen_mit_festem_ziel", found)
        self.assertIn("button_ohne_wirkung", found)
        self.assertIn("seite_unerreichbar", found)
        self.assertIn("titel_unerreichbar", found)
        self.assertFalse(report.ok)
        path = next(f.path for f in report.findings if f.code == "button_ohne_wirkung")
        self.assertEqual(path[0], "Disc einlegen")

    def test_chapter_button_with_playlist_command_is_reported(self):
        # So sahen 2D-Kapitel-Buttons bis v1.7.7 aus
        chapter = MenuButtonSpec(button_id=2, text="KAPITEL 1", action_type="play_chapter", target_title_id=1)
        chapter.nav_commands = [cmd_play_playlist_at_mark(1, 0)]
        pages = [(0, [MenuButtonSpec(button_id=1, text="FILM", target_title_id=1), chapter])]
        report = explore(self._disc(pages, num_titles=1))
        self.assertIn("playlist_im_button", codes(report, "fehler"))
        self.assertIn("button_ohne_wirkung", codes(report))

    def _chapter_pages(self):
        return [(0, [MenuButtonSpec(button_id=1, text="FILM", target_title_id=1),
                     MenuButtonSpec(button_id=2, text="KAPITEL 1", action_type="play_chapter",
                                    target_title_id=1, target_chapter_id=1),
                     MenuButtonSpec(button_id=3, text="KAPITEL 2", action_type="play_chapter",
                                    target_title_id=1, target_chapter_id=2)])]

    def test_chapter_buttons_start_the_title(self):
        disc = self._disc(self._chapter_pages(), num_titles=1)
        report = explore(disc)
        # build_movie_mpls schreibt nur eine Marke: Kapitel 2 (Marke 1) fehlt, Kapitel 1 ist sauber
        self.assertEqual(codes(report, "fehler"), {"marke_fehlt"})
        self.assertNotIn("unterbrechung_bleibt", codes(report))
        p = Player(disc)
        p.insert_disc()
        p.activate_button(2)
        self.assertEqual((p.state, p.playlist_id, p.start_mark, p.title), (STATE_FILM, 1, 0, 1))
        self.assertEqual(p.regs.gpr[GPR_CHAPTER], 0)
        p.playlist_end()
        self.assertEqual((p.state, p.playlist_id), (STATE_MENU, 0))
        # „Film starten“ danach beginnt von vorn
        p.activate_button(1)
        self.assertEqual((p.state, p.start_mark), (STATE_FILM, None))

    def test_top_menu_resume_after_chapter_start(self):
        """Disc A (v1.8.3, Sony UBP-X700): Kapitel über JumpObject hinterließen eine nie verworfene Unterbrechung."""
        disc = self._disc(self._chapter_pages(), num_titles=1)
        p = Player(disc)
        p.insert_disc()
        p.activate_button(2)                 # Kapitel 1 als Titel
        p.press("top_menu")                  # Unterbrechung merken, Menü
        self.assertEqual(p.state, STATE_MENU)
        p.activate_button(1)                 # Film starten: JumpTitle verwirft die Unterbrechung
        self.assertIsNone(p.machine.suspended)
        p.press("top_menu")
        p.press("top_menu")                  # Top Menu im Menü setzt den Film fort
        self.assertEqual((p.state, p.playlist_id), (STATE_FILM, 1))

        # Alter Weg: Kapitel-Button springt per JumpObject in ein Einstiegsobjekt
        from modules.bdsim.disc import MovieObject as SimObject
        old = self._disc(self._chapter_pages(), num_titles=1)
        old.movie_objects.append(SimObject(len(old.movie_objects), [
            decode_command(cmd_play_playlist_at_mark(1, 0)), decode_command(cmd_jump_object(1))], True))
        entry = len(old.movie_objects) - 1
        for button in old.compositions[0].page(0).buttons():
            if button.button_id in (2, 3):
                button.commands[:] = [decode_command(cmd_jump_object(entry))]
        self.assertIn("unterbrechung_bleibt", codes(explore(old)))

    def test_3d_film_without_output_mode_is_reported_on_3d_tv_only(self):
        pages = [(0, [MenuButtonSpec(button_id=1, text="FILM", target_title_id=1)])]
        for titles_3d, expect_warning in (([], True), ([1], False)):
            disc = self._disc(pages, num_titles=1, titles_3d=titles_3d)
            disc.playlists[1].is_3d = True
            self.assertEqual("3d_ohne_umschaltung" in codes(explore(disc, tv_3d=True)), expect_warning)
            self.assertNotIn("3d_ohne_umschaltung", codes(explore(disc, tv_3d=False)))

    def test_language_page_checks(self):
        pages = [
            (0, [MenuButtonSpec(button_id=1, text="FILM", target_title_id=1),
                 MenuButtonSpec(button_id=2, text="SPRACHE", action_type="set_page", target_page_id=1)]),
            (1, [MenuButtonSpec(button_id=1, text="AUDIO 2", action_type="set_stream", target_audio_id=2),
                 MenuButtonSpec(button_id=2, text="ZURÜCK", action_type="set_page", target_page_id=0)]),
        ]
        disc = self._disc(pages, num_titles=1)
        self.assertEqual(disc.compositions[0].page(1).button(1).commands[0].text(), f"Move(GPR{GPR_AUDIO}, 2)")
        report = explore(disc)
        found = codes(report)
        # Die Wahl wird nur gemerkt (kein Umschalten im Menü); der Film hat aber nur 1 Tonspur
        self.assertNotIn("spurwahl_im_menue", found)
        self.assertIn("tonspur_fehlt", found)

    def test_remote_choice_survives_return_to_menu(self):
        """v1.8.6: Im Film per Fernbedienung gewählte Spuren gelten beim nächsten Start weiter."""
        pages = [
            (0, [MenuButtonSpec(button_id=1, text="FILM", target_title_id=1),
                 MenuButtonSpec(button_id=2, text="SPRACHE", action_type="set_page", target_page_id=1)]),
            (1, [MenuButtonSpec(button_id=1, text="UT 1", action_type="set_stream", target_subtitle_id=1,
                                target_subtitle_on=True),
                 MenuButtonSpec(button_id=2, text="ZURÜCK", action_type="set_page", target_page_id=0)]),
        ]
        disc = self._disc(pages, num_titles=1)
        disc.playlists[1].items[0].streams.append(type(disc.playlists[1].items[0].streams[0])("pg", 1, 0x1200))
        disc.playlists[1].items[0].streams.append(type(disc.playlists[1].items[0].streams[0])("pg", 1, 0x1201))
        p = Player(disc)
        p.insert_disc()
        self.assertEqual(p.regs.gpr[GPR_AUDIO], 0)          # Disc eingelegt: nichts übernommen
        p.activate_button(2)
        p.activate_button(1)                                # Untertitel 1 merken
        p.activate_button(2)
        p.activate_button(1)                                # Film starten
        self.assertEqual(p.regs.psr[PSR_PG_STREAM], 0x80000001)
        p.press("subtitle")                                 # Fernbedienung: Untertitel 2
        p.press("top_menu")
        self.assertEqual((p.regs.gpr[GPR_SUBTITLE], p.regs.gpr[GPR_SUBTITLE_MODE]), (2, SUB_ON))
        p.activate_button(1)                                # Film erneut starten
        self.assertEqual(p.regs.psr[PSR_PG_STREAM], 0x80000002)

    def test_stream_choice_in_menu_is_warned(self):
        """Disc A (v1.8.3): SetStream im Menü verwirft der Sony, wenn die Menü-Playlist die Spur nicht hat."""
        audio = MenuButtonSpec(button_id=1, text="TON 2", action_type="set_stream", target_audio_id=2)
        audio.nav_commands = [cmd_set_stream(audio_id=2)]
        pages = [(0, [MenuButtonSpec(button_id=2, text="FILM", target_title_id=1), audio])]
        self.assertIn("spurwahl_im_menue", codes(explore(self._disc(pages, num_titles=1)), "warnung"))

    def test_unreachable_button_by_arrows(self):
        pages = [(0, [MenuButtonSpec(button_id=1, text="A", target_title_id=1, x=100, y=100,
                                     upper_id=1, lower_id=1, left_id=1, right_id=1),
                      MenuButtonSpec(button_id=2, text="B", target_title_id=1, x=100, y=300,
                                     upper_id=1, lower_id=9, left_id=2, right_id=2)])]
        report = explore(self._disc(pages, num_titles=1))
        found = codes(report, "warnung")
        self.assertIn("pfeiltasten_unerreichbar", found)
        self.assertIn("nachbar_fehlt", found)

    def test_unguarded_output_mode_is_hinted(self):
        pages = [(0, [MenuButtonSpec(button_id=1, text="FILM", target_title_id=1)])]
        disc = self._disc(pages, num_titles=1, titles_3d=[1])
        self.assertNotIn("3d_ohne_profilpruefung", codes(explore(disc)))
        from modules.bdsim.disc import MovieObject as SimObject
        disc.movie_objects.append(SimObject(len(disc.movie_objects), [
            decode_command(bytes.fromhex("31 80 00 0a 00 00 00 01 00 00 00 00"))]))
        self.assertIn("3d_ohne_profilpruefung", codes(explore(disc), "hinweis"))

    def test_missing_bdmv(self):
        with self.assertRaises(DiscReadError):
            load_disc(self.tmp.name)


if __name__ == "__main__":
    unittest.main()
