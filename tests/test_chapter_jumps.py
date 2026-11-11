# tests/test_chapter_jumps.py
"""
Tests für Kapitelsprünge aus dem Menü (Stufe 0):
- PlayPLatPM verwendet den 0-basierten PlayListMark-Index (Kapitel 1 = Marke 0)
- Zuordnung von Kapitel-Zeitstempeln zu den tatsächlich geschriebenen Marken der Film-Playlist
- Kapitel-Buttons merken die Marke in GPR_CHAPTER und starten den Film per JumpTitle; das MovieObject
  des Titels springt an die Marke (Playlist-Befehle sind in Buttons nicht erlaubt, JumpObject hinterließ
  eine nie verworfene Unterbrechung)
"""

import os
import struct
import tempfile
import unittest

from modules.igs.layout import MenuButtonSpec, build_chapter_menu_specs
from modules.mpls.mpls_reader import read_mpls_marks, parse_chapter_time, find_mark_for_time
from modules.menu_author import resolve_chapter_jumps
from modules.bdmv.movie_object_generator import (
    build_standard_movie_objects,
    chapter_jump_commands,
    title_commands,
    cmd_set_output_mode,
    cmd_play_playlist,
    cmd_jump_object,
)

PTS_IN = 27000000  # typischer tsMuxeR-Startwert (45 kHz)


def build_test_mpls(mark_seconds, duration_sec=600.0, pts_in=PTS_IN, extra_link_point_sec=None) -> bytes:
    """Erzeugt eine minimale MPLS mit einem PlayItem und Entry Marks an den angegebenen Sekunden."""
    pts_out = pts_in + int(duration_sec * 45000)

    app_info = bytes(14)
    app_info_payload = struct.pack(">I", len(app_info)) + app_info

    pi = bytearray()
    pi.extend(b"00001")
    pi.extend(b"M2TS")
    pi.extend(struct.pack(">H", 0x0001))
    pi.append(0)
    pi.extend(struct.pack(">II", pts_in, pts_out))
    pi.extend(bytes(12))  # uo_mask, flags, still (Rest für den Leser irrelevant)
    pi_payload = struct.pack(">H", len(pi)) + bytes(pi)

    pl = bytearray()
    pl.extend(struct.pack(">H", 0))
    pl.extend(struct.pack(">HH", 1, 0))
    pl.extend(pi_payload)
    playlist_payload = struct.pack(">I", len(pl)) + bytes(pl)

    marks = [(1, s) for s in mark_seconds]
    if extra_link_point_sec is not None:
        marks.append((2, extra_link_point_sec))
    marks.sort(key=lambda m: m[1])
    md = bytearray()
    md.extend(struct.pack(">H", len(marks)))
    for mark_type, sec in marks:
        md.append(0)
        md.append(mark_type)
        md.extend(struct.pack(">H", 0))
        md.extend(struct.pack(">I", pts_in + int(sec * 45000)))
        md.extend(struct.pack(">HI", 0xFFFF, 0))
    mark_payload = struct.pack(">I", len(md)) + bytes(md)

    playlist_offset = 40 + len(app_info_payload)
    mark_offset = playlist_offset + len(playlist_payload)
    header = b"MPLS0200" + struct.pack(">III", playlist_offset, mark_offset, 0) + bytes(20)
    return header + app_info_payload + playlist_payload + mark_payload


def count_movie_objects(mobj: bytes) -> int:
    return struct.unpack(">H", mobj[48:50])[0]


class TestChapterMarkIndex(unittest.TestCase):
    def test_chapter_one_is_mark_zero(self):
        spec = MenuButtonSpec(button_id=1, text="K1", action_type="play_chapter", target_title_id=1, target_chapter_id=1)
        self.assertEqual(spec.get_nav_commands(), chapter_jump_commands(1, 0))

    def test_resolved_mark_overrides_chapter_number(self):
        spec = MenuButtonSpec(button_id=1, text="K1", action_type="play_chapter",
                              target_title_id=1, target_chapter_id=1, target_mark_id=3)
        self.assertEqual(spec.get_nav_commands(), chapter_jump_commands(1, 3))

    def test_chapter_specs_carry_time(self):
        specs = build_chapter_menu_specs(["00:00:00.000", "00:15:30.000"])
        chapter_specs = [s for s in specs if s.action_type == "play_chapter"]
        self.assertEqual([s.chapter_time for s in chapter_specs], ["00:00:00.000", "00:15:30.000"])


class TestMplsReader(unittest.TestCase):
    def test_parse_chapter_time(self):
        self.assertAlmostEqual(parse_chapter_time("01:02:03.500"), 3723.5)
        self.assertAlmostEqual(parse_chapter_time("00:00:00.000"), 0.0)
        self.assertIsNone(parse_chapter_time("abc"))

    def test_read_marks_relative_to_play_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "00001.mpls")
            with open(path, "wb") as f:
                f.write(build_test_mpls([0, 60, 125.5]))
            marks = read_mpls_marks(path)
        self.assertEqual([m["index"] for m in marks], [0, 1, 2])
        self.assertAlmostEqual(marks[2]["time_sec"], 125.5, places=3)

    def test_link_points_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "00001.mpls")
            with open(path, "wb") as f:
                f.write(build_test_mpls([0, 60], extra_link_point_sec=59.8))
            marks = read_mpls_marks(path)
        self.assertEqual(find_mark_for_time(marks, 60.0), 2)

    def test_missing_file_returns_none(self):
        self.assertIsNone(read_mpls_marks(os.path.join(tempfile.gettempdir(), "gibt_es_nicht.mpls")))


class TestResolveChapterJumps(unittest.TestCase):
    def _write_playlist(self, tmp, playlist_id, mark_seconds):
        with open(os.path.join(tmp, f"{playlist_id:05d}.mpls"), "wb") as f:
            f.write(build_test_mpls(mark_seconds))

    def _chapter_marks(self, specs):
        return [s.target_mark_id for s in specs if s.action_type == "play_chapter"]

    def test_2d_marks_match_chapter_times(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write_playlist(tmp, 1, [0, 60, 120])
            specs = build_chapter_menu_specs(["00:00:00.000", "00:01:00.000", "00:02:00.000"], return_page_id=0)
            titles = resolve_chapter_jumps([(1, specs)], tmp)
        self.assertEqual(self._chapter_marks(specs), [0, 1, 2])
        self.assertEqual(titles, [1])
        self.assertEqual(specs[1].get_nav_commands(), chapter_jump_commands(1, 1))

    def test_extra_start_mark_in_playlist(self):
        # Kapitel ohne 00:00 eingetragen, Playlist enthält trotzdem eine Startmarke
        with tempfile.TemporaryDirectory() as tmp:
            self._write_playlist(tmp, 1, [0, 60, 120])
            specs = build_chapter_menu_specs(["00:01:00.000", "00:02:00.000"], return_page_id=0)
            resolve_chapter_jumps([(1, specs)], tmp)
        self.assertEqual(self._chapter_marks(specs), [1, 2])

    def test_fallback_without_playlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            specs = build_chapter_menu_specs(["00:00:00.000", "00:01:00.000"], return_page_id=0)
            resolve_chapter_jumps([(1, specs)], tmp)
        self.assertEqual(self._chapter_marks(specs), [0, 1])

    def test_back_button_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            specs = build_chapter_menu_specs(["00:00:00.000", "00:01:00.000"], return_page_id=0)
            resolve_chapter_jumps([(1, specs)], tmp)
        self.assertEqual(specs[-1].action_type, "set_page")


class TestTitleObjects(unittest.TestCase):
    def test_default_output_unchanged(self):
        """Titel ohne Kapitel- und Sprachmenü: nur PlayPL; 3D-Titel mit Profilprüfung vor SetOutputMode (v1.8.7)."""
        self.assertEqual(
            build_standard_movie_objects(num_titles=2, titles_3d=[1], has_3d=True),
            build_standard_movie_objects(num_titles=2, titles_3d=[1], has_3d=True, chapter_titles=[], stream_titles=[])
        )
        from modules.bdmv.movie_object_generator import output_mode_commands
        self.assertEqual(title_commands(1, True), output_mode_commands(1) + [cmd_play_playlist(1)]
                         + output_mode_commands(0) + [cmd_jump_object(1)])
        self.assertEqual(title_commands(2, False), [cmd_play_playlist(2), cmd_jump_object(1)])
        # Ohne Sprachmenü bleibt auch das TopMenu-Objekt unverändert: PlayPL(0), JumpObject(1)
        mobj = build_standard_movie_objects(num_titles=1, chapter_titles=[1])
        self.assertIn(cmd_play_playlist(0) + cmd_jump_object(1) + b"", mobj)
        self.assertNotIn(bytes.fromhex("48 40 03 00 00 00 00 05"), mobj)

    def test_chapter_title_object(self):
        mobj = build_standard_movie_objects(num_titles=2, titles_3d=[1], has_3d=True, chapter_titles=[1])
        self.assertEqual(count_movie_objects(mobj), 2 + 2)
        commands = title_commands(1, True, with_chapters=True)
        self.assertIn(b"".join(commands), mobj)
        self.assertEqual(commands[3], cmd_set_output_mode(1))
        self.assertEqual(commands[-2:], [cmd_set_output_mode(0), cmd_jump_object(1)])


if __name__ == "__main__":
    unittest.main()
