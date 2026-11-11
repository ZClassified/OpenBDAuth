# tests/test_multititle_export.py
"""
Unit-Tests für die dynamische Multi-Title Menü-Generierung,
HDMV-Navigation und Disc-Authoring-Pipeline in OpenBDAuth (Release 1.1.0).
"""

import os
import sys
import tempfile
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication
from core.project_state import ProjectState, MediaTitle
from core.meta_builder import MetaBuilder
from modules.igs.layout import build_main_menu_specs, MenuLayoutEngine
from modules.menu_author import build_project_menu_pages, inject_menu_into_bdmv
from modules.bdmv.index_generator import build_index_bdmv
from modules.bdmv.movie_object_generator import build_standard_movie_objects

app_instance = QApplication.instance()
if app_instance is None:
    app_instance = QApplication(sys.argv)


class TestMultiTitleSpecs(unittest.TestCase):
    def test_three_titles_menu_specs(self):
        """Prüft Erzeugung von 3 JumpTitle-Buttons für 3 Titles."""
        titles = [
            MediaTitle(name="Episode 1: Pilot", is_main=True),
            MediaTitle(name="Episode 2: Der Aufbruch", is_main=False),
            MediaTitle(name="Episode 3: Das Finale", is_main=False),
        ]
        specs = build_main_menu_specs(
            play_text="EPISODE 1: PILOT",
            titles=titles
        )
        self.assertEqual(len(specs), 3)

        # Button 1
        b1 = specs[0]
        self.assertEqual(b1.button_id, 1)
        self.assertEqual(b1.text, "EPISODE 1: PILOT")
        self.assertEqual(b1.action_type, "jump_title")
        self.assertEqual(b1.target_title_id, 1)

        # Button 2
        b2 = specs[1]
        self.assertEqual(b2.button_id, 2)
        self.assertEqual(b2.text, "EPISODE 2: DER AUFBRUCH")
        self.assertEqual(b2.action_type, "jump_title")
        self.assertEqual(b2.target_title_id, 2)

        # Button 3
        b3 = specs[2]
        self.assertEqual(b3.button_id, 3)
        self.assertEqual(b3.text, "EPISODE 3: DAS FINALE")
        self.assertEqual(b3.action_type, "jump_title")
        self.assertEqual(b3.target_title_id, 3)

        # 4-Wege Navigation (1-Spalten-Wrap-Around bei 3 Buttons)
        self.assertEqual(b1.upper_id, 3)
        self.assertEqual(b1.lower_id, 2)
        self.assertEqual(b2.upper_id, 1)
        self.assertEqual(b2.lower_id, 3)
        self.assertEqual(b3.upper_id, 2)
        self.assertEqual(b3.lower_id, 1)

    def test_five_titles_grid_layout(self):
        """Prüft automatisches 2-Spalten Grid-Layout bei > 4 Titeln."""
        titles = [MediaTitle(name=f"Folge {i}", is_main=(i == 1)) for i in range(1, 6)]
        specs = build_main_menu_specs(
            play_text="FOLGE 1",
            titles=titles
        )
        self.assertEqual(len(specs), 5)
        # Alle 5 Buttons müssen gültige D-Pad-Nachbarn haben
        for b in specs:
            self.assertIsNotNone(b.upper_id)
            self.assertIsNotNone(b.lower_id)
            self.assertIsNotNone(b.left_id)
            self.assertIsNotNone(b.right_id)


class TestMultiTitleBdmvNav(unittest.TestCase):
    def test_index_bdmv_three_titles(self):
        """Prüft, dass index.bdmv 3 Titles mit HDMV Playback-Objekten enthält."""
        data = build_index_bdmv(num_titles=3)
        self.assertTrue(data.startswith(b"INDX0200"))
        # Header (40) + AppInfo (38) = 78 Bytes Offset für Index-Daten
        # An Offset 78 + 4 (data_len) + 12 (FirstPlayback) + 12 (TopMenu) = 106
        # uint16 an Offset 106: num_titles
        import struct
        num_titles = struct.unpack(">H", data[106:108])[0]
        self.assertEqual(num_titles, 3)

    def test_movie_object_three_titles(self):
        """Prüft, dass MovieObject.bdmv 5 MovieObjects enthält (0: FirstPlayback, 1: TopMenu, 2..4: Titles)."""
        data = build_standard_movie_objects(num_titles=3)
        self.assertTrue(data.startswith(b"MOBJ0200"))
        # Header (40) + data_len (4) + reserved (4) = 48
        import struct
        num_objects = struct.unpack(">H", data[48:50])[0]
        self.assertEqual(num_objects, 5)


class TestMultiTitleMetaBuilder(unittest.TestCase):
    def test_title_meta_generation(self):
        """Prüft Erzeugung einer tsMuxeR Meta-Datei für einen beliebigen Titel."""
        project = ProjectState()
        project.project_name = "SERIES_DISC"

        title = MediaTitle(name="Episode 2", is_main=False)
        title.video_base = "C:/media/ep2.264"
        title.fps = 24.0
        title.audio_tracks = [{"path": "C:/media/ep2_audio.ac3", "lang": "deu"}]
        title.subtitle_tracks = [
            {"path": "C:/media/ep2_sub.srt", "lang": "deu"},
            {"path": "C:/media/ep2_sub.sup", "lang": "eng"},
        ]
        title.chapters = ["00:00:00.000", "00:10:00.000"]

        builder = MetaBuilder(project)
        meta = builder.generate_title_meta_content(title)

        self.assertIn("MUXOPT --blu-ray", meta)
        self.assertIn('--label="SERIES_DISC"', meta)
        self.assertIn("--custom-chapters=00:00:00.000;00:10:00.000", meta)
        self.assertIn('V_MPEG4/ISO/AVC, "C:/media/ep2.264", fps=24, insertSEI, contSPS', meta)
        self.assertIn('A_AC3, "C:/media/ep2_audio.ac3", lang=deu', meta)
        self.assertIn('S_HDMV/PGS, "C:/media/ep2_sub.sup", lang=deu', meta)
        self.assertIn('S_HDMV/PGS, "C:/media/ep2_sub.sup", lang=eng', meta)
        self.assertNotIn("S_TEXT/SRT", meta)
        self.assertNotIn("S_TEXT/UTF8", meta)

    def test_srt_subtitle_meta_syntax(self):
        """Stellt sicher, dass SRT-Dateien automatisch zu BD-ROM PGS (S_HDMV/PGS) konvertiert werden."""
        project = ProjectState()
        title = MediaTitle(name="Film", is_main=True)
        title.video_base = "C:/media/film.264"
        title.subtitle_tracks = [{"path": "C:/subs/german.srt", "lang": "deu"}]

        builder = MetaBuilder(project)
        meta = builder.generate_title_meta_content(title)

        self.assertIn("S_HDMV/PGS", meta)
        self.assertIn("german.sup", meta)
        self.assertNotIn("S_TEXT/SRT", meta)
        self.assertNotIn("S_TEXT/UTF8", meta)


class TestMultiTitleDiscAssembly(unittest.TestCase):
    def test_inject_menu_three_titles(self):
        """Prüft Erzeugung aller Playlists und Backups für 3 Titel."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bdmv_dir = os.path.join(tmpdir, "BDMV")
            pl_dir = os.path.join(bdmv_dir, "PLAYLIST")
            stream_dir = os.path.join(bdmv_dir, "STREAM")
            clip_dir = os.path.join(bdmv_dir, "CLIPINF")
            os.makedirs(pl_dir, exist_ok=True)
            os.makedirs(stream_dir, exist_ok=True)
            os.makedirs(clip_dir, exist_ok=True)

            # Simuliere Titel 1
            with open(os.path.join(stream_dir, "00000.m2ts"), "wb") as f: f.write(b"M2TS" * 48)
            with open(os.path.join(clip_dir, "00000.clpi"), "wb") as f: f.write(b"CLPI" * 10)
            with open(os.path.join(pl_dir, "00000.mpls"), "wb") as f: f.write(b"MPLS" * 10)

            project = ProjectState()
            project.titles = [
                MediaTitle(name="Episode 1", is_main=True),
                MediaTitle(name="Episode 2", is_main=False),
                MediaTitle(name="Episode 3", is_main=False),
            ]
            project.titles[0].video_base = "C:/dummy/ep1.264"
            project.titles[1].video_base = "C:/dummy/ep2.264"
            project.titles[2].video_base = "C:/dummy/ep3.264"

            ok = inject_menu_into_bdmv(
                bdmv_dir=bdmv_dir,
                num_titles=3,
                project=project,
                duration_sec=2.0
            )
            self.assertTrue(ok)

            # Menü-Playlist (00000) und 3 Titel-Playlists (00001, 00002, 00003)
            self.assertTrue(os.path.exists(os.path.join(pl_dir, "00000.mpls")))
            self.assertTrue(os.path.exists(os.path.join(pl_dir, "00001.mpls")))
            self.assertTrue(os.path.exists(os.path.join(pl_dir, "00002.mpls")))
            self.assertTrue(os.path.exists(os.path.join(pl_dir, "00003.mpls")))

            # Backup Playlists
            backup_pl = os.path.join(bdmv_dir, "BACKUP", "PLAYLIST")
            self.assertTrue(os.path.exists(os.path.join(backup_pl, "00000.mpls")))
            self.assertTrue(os.path.exists(os.path.join(backup_pl, "00001.mpls")))
            self.assertTrue(os.path.exists(os.path.join(backup_pl, "00002.mpls")))
            self.assertTrue(os.path.exists(os.path.join(backup_pl, "00003.mpls")))


if __name__ == "__main__":
    unittest.main()
