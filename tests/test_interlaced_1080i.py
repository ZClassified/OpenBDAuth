# tests/test_interlaced_1080i.py
"""
Unit-Tests für die 1080i/25PsF tsMuxeR-Timing-Korrektur und
den BD-ROM Part 3 Stream-Attribut-Patcher (v1.2.1).
"""

import os
import tempfile
import unittest
from core.project_state import ProjectState, MediaTitle
from core.meta_builder import MetaBuilder
from modules.mux_engine import fix_1080i_stream_attributes


class TestInterlaced1080i(unittest.TestCase):
    def setUp(self):
        self.project = ProjectState()
        self.builder = MetaBuilder(self.project)

    def test_get_tsmuxer_fps_str_1080i_25psf(self):
        """1080i50 / 25PsF muss für tsMuxeR als fps=25 formatiert werden (Vollbildrate)."""
        title = MediaTitle(name="Test 25PsF")
        title.fps = 25.0
        title.video_details = {"is_interlaced": True, "height": 1080, "width": 1920}

        fps_str = self.builder._get_tsmuxer_fps_str(title)
        self.assertEqual(fps_str, "25")

        # Auch falls 50.0 als Halbbild-Rohwert übergeben wurde, muss auf 25 normalisiert werden
        title.fps = 50.0
        self.assertEqual(self.builder._get_tsmuxer_fps_str(title), "25")

    def test_get_tsmuxer_fps_str_1080i_2997psf(self):
        """1080i59.94 / 29.97PsF muss für tsMuxeR als fps=29.97 formatiert werden."""
        title = MediaTitle(name="Test 29PsF")
        title.fps = 29.97
        title.video_details = {"is_interlaced": True, "height": 1080, "width": 1920}

        fps_str = self.builder._get_tsmuxer_fps_str(title)
        self.assertEqual(fps_str, "29.97")

        # Auch falls 59.94 als Halbbild-Rohwert übergeben wurde, muss auf 29.97 normalisiert werden
        title.fps = 59.94
        self.assertEqual(self.builder._get_tsmuxer_fps_str(title), "29.97")

    def test_get_tsmuxer_fps_str_1080i_30psf(self):
        """1080i60 / 30PsF muss für tsMuxeR als fps=30 formatiert werden."""
        title = MediaTitle(name="Test 30PsF")
        title.fps = 30.0
        title.video_details = {"is_interlaced": True, "height": 1080, "width": 1920}

        fps_str = self.builder._get_tsmuxer_fps_str(title)
        self.assertEqual(fps_str, "30")

    def test_get_tsmuxer_fps_str_progressive(self):
        """Progressive Streams dürfen NICHT verdoppelt werden."""
        # 1080p23.976
        t23 = MediaTitle(name="Film 24p")
        t23.fps = 23.976
        t23.video_details = {"is_interlaced": False, "height": 1080, "width": 1920}
        self.assertEqual(self.builder._get_tsmuxer_fps_str(t23), "23.976")

        # 1080p24
        t24 = MediaTitle(name="Film 24")
        t24.fps = 24.0
        t24.video_details = {"is_interlaced": False, "height": 1080, "width": 1920}
        self.assertEqual(self.builder._get_tsmuxer_fps_str(t24), "24")

        # 1080p25 (progressiv)
        t25 = MediaTitle(name="Film 25p")
        t25.fps = 25.0
        t25.video_details = {"is_interlaced": False, "height": 1080, "width": 1920}
        self.assertEqual(self.builder._get_tsmuxer_fps_str(t25), "25")

        # 720p50 (progressiv)
        t720 = MediaTitle(name="Film 720p")
        t720.fps = 50.0
        t720.video_details = {"is_interlaced": False, "height": 720, "width": 1280}
        self.assertEqual(self.builder._get_tsmuxer_fps_str(t720), "50")

    def test_meta_generation_with_interlaced_title(self):
        """Stellt sicher, dass generate_title_meta_content() fps=25 bei 1080i schreibt."""
        title = MediaTitle(name="Hauptfilm 25PsF")
        title.video_base = "C:/Video/film_25psf.264"
        title.fps = 25.0
        title.video_details = {"is_interlaced": True, "height": 1080, "width": 1920}

        meta = self.builder.generate_title_meta_content(title)
        self.assertIn('V_MPEG4/ISO/AVC, "C:/Video/film_25psf.264", fps=25, insertSEI, contSPS', meta)

    def test_fix_1080i_stream_attributes(self):
        """Testet das Patchen von CLPI- und MPLS-Headern von 0x46 auf 0x43 und 0x47 auf 0x44."""
        with tempfile.TemporaryDirectory() as tmp:
            bdmv = os.path.join(tmp, "BDMV")
            clipinf = os.path.join(bdmv, "CLIPINF")
            playlist = os.path.join(bdmv, "PLAYLIST")
            backup_c = os.path.join(bdmv, "BACKUP", "CLIPINF")
            backup_p = os.path.join(bdmv, "BACKUP", "PLAYLIST")

            for d in [clipinf, playlist, backup_c, backup_p]:
                os.makedirs(d, exist_ok=True)

            # Mock CLPI Datei mit 0x1B46 (1080i50) und progressivem 0x1B61 (1080p23.976)
            clpi_file = os.path.join(clipinf, "00000.clpi")
            clpi_data = b"\x00\x01\x10\x11\x15\x1b\x46\x30\x00\x1b\x61\x00"
            with open(clpi_file, "wb") as f:
                f.write(clpi_data)

            # Mock MPLS Datei mit 0x1B47 (1080i59.94) und progressivem 0x1B56 (720p50)
            mpls_file = os.path.join(playlist, "00001.mpls")
            mpls_data = b"\x05\x1b\x47\x00\x00\x05\x1b\x56\x00"
            with open(mpls_file, "wb") as f:
                f.write(mpls_data)

            # Mock Backup Datei
            backup_clpi = os.path.join(backup_c, "00000.clpi")
            with open(backup_clpi, "wb") as f:
                f.write(clpi_data)

            # Ausführen
            patched = fix_1080i_stream_attributes(tmp)
            self.assertEqual(patched, 3)

            # Prüfen der CLPI Datei
            with open(clpi_file, "rb") as f:
                patched_clpi = f.read()
            self.assertIn(b"\x1b\x43", patched_clpi)
            self.assertNotIn(b"\x1b\x46", patched_clpi)
            self.assertIn(b"\x1b\x61", patched_clpi)  # Progressives Attribut unverändert!

            # Prüfen der MPLS Datei
            with open(mpls_file, "rb") as f:
                patched_mpls = f.read()
            self.assertIn(b"\x1b\x44", patched_mpls)
            self.assertNotIn(b"\x1b\x47", patched_mpls)
            self.assertIn(b"\x1b\x56", patched_mpls)  # 720p50 unverändert!

            # Prüfen der Backup CLPI Datei
            with open(backup_clpi, "rb") as f:
                patched_bclpi = f.read()
            self.assertIn(b"\x1b\x43", patched_bclpi)


if __name__ == "__main__":
    unittest.main()
