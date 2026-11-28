# tests/test_frame_rate.py
"""
Bildrate roher H.264-Ströme (v1.40.0): Sie kommt aus dem SPS (time_scale / 2 · num_units_in_tick), nicht aus
ffprobe. ffprobe meldet bei rohem H.264 als r_frame_rate die doppelte Rate und als avg_frame_rate immer 25.

Anlass (Meldung zu v1.36.0): Ein Trailer mit 720p und 29,97 fps (ffprobe: 2997/50) wurde als 720p59,94 gemuxt und
lief doppelt so schnell (bestätigt auf dem Sony UBP-X700); ein Trailer mit 23,976 fps (ffprobe: 48000/1001) wurde
wegen der Grenze ±0,1 zu 24 fps. Ältere Projekte werden beim Öffnen korrigiert.
"""

import os
import shutil
import tempfile
import unittest
from fractions import Fraction
from unittest.mock import patch

from core.disc_edit import starter_project
from core.meta_builder import MetaBuilder
from gui.node_editor.controller import GraphController
from gui.studio.importer import FilmImporter
from modules.video_tools import VideoTools, bd_fps, doubled_rate_to_fps, is_raw_h264
from tests.prepare_util import ffmpeg, make_h264, needs_ffmpeg
from tests.test_menu_designer import app_instance  # noqa: F401 (QApplication für den Controller)

# (Größe, Rate für x264) → (ffprobe r_frame_rate, Rate aus dem SPS, Wert für tsMuxeR); ffprobe 8.1 gemessen
CASES = [
    ("1920x1080", "24000/1001", "48000/1001", "24000/1001", 23.976),
    ("1920x1080", "24/1", "48/1", "24/1", 24.0),
    ("1920x1080", "25/1", "50/1", "25/1", 25.0),
    ("1280x720", "24000/1001", "48000/1001", "24000/1001", 23.976),
    ("1280x720", "30000/1001", "60000/1001", "30000/1001", 29.97),
    ("1280x720", "50/1", "100/1", "50/1", 50.0),
    ("1280x720", "60000/1001", "120000/1001", "60000/1001", 59.94),
]


@needs_ffmpeg
class TestRawStreams(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="obda_fps_")
        cls.paths = {}
        for size, rate, *_ in CASES:
            path = os.path.join(cls.tmp, f"{size}_{rate.replace('/', '_')}.264")
            make_h264(path, seconds=0.5, size=size, rate=rate)
            cls.paths[(size, rate)] = path

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_rate_from_sps(self):
        for size, rate, _raw, sps, fps in CASES:
            with self.subTest(size=size, rate=rate):
                path = self.paths[(size, rate)]
                self.assertEqual(VideoTools.h264_frame_rate(path), Fraction(sps))
                self.assertEqual(VideoTools().get_fps(path), fps)

    def test_probe_uses_sps_not_ffprobe(self):
        """ffprobe meldet die doppelte Rate; fps folgt dem SPS, fps_raw bleibt der Wert von ffprobe."""
        for size, rate, raw, sps, fps in CASES:
            with self.subTest(size=size, rate=rate):
                details = VideoTools().probe_video_details(self.paths[(size, rate)])
                self.assertEqual(details["fps_raw"], raw)
                self.assertEqual(details["fps_sps"], sps)
                self.assertEqual(details["fps"], fps)

    def test_720p_29_97_warns(self):
        """Der Fall aus der Meldung: 720p mit 29,97 fps ist auf der Blu-ray nicht erlaubt."""
        codes = [w["code"] for w in VideoTools().probe_video_details(self.paths[("1280x720", "30000/1001")])["warnings"]]
        self.assertIn("UNOFFICIAL_720P_RATE", codes)
        for rate in ("24000/1001", "50/1", "60000/1001"):
            details = VideoTools().probe_video_details(self.paths[("1280x720", rate)])
            self.assertNotIn("UNOFFICIAL_720P_RATE", [w["code"] for w in details["warnings"]], rate)

    def test_interlaced_rate_is_frame_rate(self):
        """1080i25: Im SPS stehen 50 Halbbilder, die Bildrate für tsMuxeR ist 25."""
        path = os.path.join(self.tmp, "1080i25.264")
        ffmpeg('-f', 'lavfi', '-i', "testsrc2=s=1920x1080:r=25:d=0.5", '-pix_fmt', 'yuv420p', '-c:v', 'libx264',
               '-preset', 'ultrafast', '-flags', '+ildct+ilme', '-x264-params', 'tff=1', '-f', 'h264', path)
        details = VideoTools().probe_video_details(path)
        self.assertEqual(details["fps_sps"], "25/1")
        self.assertEqual(details["fps"], 25.0)
        self.assertTrue(details["is_interlaced"])

    def test_container_keeps_ffprobe(self):
        """In m2ts meldet ffprobe die echte Rate; das SPS wird dort nicht gelesen."""
        path = os.path.join(self.tmp, "720p5994.m2ts")
        ffmpeg('-f', 'lavfi', '-i', "testsrc2=s=1280x720:r=60000/1001:d=0.5", '-pix_fmt', 'yuv420p',
               '-c:v', 'libx264', '-preset', 'ultrafast', '-f', 'mpegts', path)
        self.assertIsNone(VideoTools.h264_frame_rate(path))
        self.assertEqual(VideoTools().probe_video_details(path)["fps"], 59.94)


class TestRules(unittest.TestCase):
    def test_bd_fps(self):
        self.assertEqual(bd_fps(Fraction(24000, 1001)), 23.976)
        self.assertEqual(bd_fps(Fraction(2997, 100)), 29.97)       # Trailer aus der Meldung: 2997/50 halbiert
        self.assertEqual(bd_fps(Fraction(30)), 29.97)              # exakt 30: Blu-ray kennt nur 29,97
        self.assertEqual(bd_fps(Fraction(60)), 59.94)
        self.assertEqual(bd_fps(Fraction(12)), 12.0)

    def test_doubled_rate_tolerance(self):
        """47,952 (doppelte 23,976) war bis v1.36.0 zu 24 geworden."""
        self.assertEqual(doubled_rate_to_fps(48000 / 1001), 23.976)
        self.assertEqual(doubled_rate_to_fps(48.0), 24.0)
        self.assertIsNone(doubled_rate_to_fps(50.0))
        self.assertEqual(VideoTools()._compute_effective_fps("48000/1001", 720), 23.976)

    def test_meta_builder_tolerance(self):
        class Title:
            fps = 48000 / 1001
            video_details = {"height": 1080, "is_interlaced": False}
            video_mvc = None
        self.assertEqual(MetaBuilder(None)._get_tsmuxer_fps_str(Title()), "23.976")

    def test_without_timing_falls_back(self):
        """Ohne timing_info im SPS bleibt es bei ffprobe und dem bisherigen Veto-System."""
        with patch.object(VideoTools, "_read_h264_header", return_value=b"x"), \
                patch.object(VideoTools, "_first_sps", return_value={"frame_mbs_only": 1}):
            self.assertIsNone(VideoTools.h264_frame_rate("film.264"))

    def test_3d_veto(self):
        self.assertEqual(VideoTools._sps_fps(Fraction(25), True), 23.976)
        self.assertEqual(VideoTools._sps_fps(Fraction(25), False), 25.0)

    def test_exact_rates_from_sps(self):
        """Exakt 60 fps bei 720p (ffprobe: 120/1) bekommt den Hinweis auf den Tonversatz."""
        vt = VideoTools()
        base = {"width": 1280, "height": 720, "fps": 59.94, "is_interlaced": False, "sar": "1:1", "dar": "16:9"}
        warnings = vt.check_compliance(dict(base, fps_raw="120/1", fps_sps="60/1"))
        exact = [w for w in warnings if w.code == "EXACT_30_FPS"]
        self.assertEqual(len(exact), 1)
        self.assertEqual(exact[0].params["fps"], "60")
        self.assertFalse([w for w in vt.check_compliance(dict(base, fps_raw="120000/1001", fps_sps="60000/1001"))
                          if w.code == "EXACT_30_FPS"])

    def test_raw_extensions(self):
        for name in ("a.264", "a.H264", "a.avc"):
            self.assertTrue(is_raw_h264(name))
        for name in ("a.m2ts", "a.mkv", "", None):
            self.assertFalse(is_raw_h264(name))


@needs_ffmpeg
class TestCorrectOnOpen(unittest.TestCase):
    """Ältere Projekte: Die gespeicherte Rate wird beim Öffnen korrigiert (ein Rückgängig-Schritt je Film)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="obda_fps_open_")
        cls.trailer = os.path.join(cls.tmp, "trailer_720p2997.264")
        make_h264(cls.trailer, seconds=0.5, size="1280x720", rate="30000/1001")
        cls.film = os.path.join(cls.tmp, "film_23976.264")
        make_h264(cls.film, seconds=0.5, size="1920x1080", rate="24000/1001")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.ctrl = GraphController(starter_project())
        self.importer = FilmImporter(self.ctrl, lambda: "deu")
        self.film_id = self.ctrl.project.films[0].id

    def _old_project(self, path, fps):
        """Wie bis v1.36.0 gespeichert: Pfad und falsche Rate, ohne Analyse dieser Version."""
        film = self.ctrl.project.film(self.film_id)
        film.video_base, film.fps, film.video_details, film.compliance_warnings = path, fps, None, []
        self.ctrl.undo_stack.setClean()

    def test_wrong_rate_is_corrected(self):
        self._old_project(self.trailer, 59.94)
        fixes = self.importer.correct_frame_rates()
        film = self.ctrl.project.film(self.film_id)
        self.assertEqual(fixes, [(film.name, 59.94, 29.97)])
        self.assertEqual(film.fps, 29.97)
        self.assertIn("UNOFFICIAL_720P_RATE", [w["code"] for w in film.compliance_warnings])
        self.assertFalse(self.ctrl.undo_stack.isClean())            # Projekt gilt als geändert
        self.ctrl.undo_stack.undo()
        self.assertEqual(self.ctrl.project.film(self.film_id).fps, 59.94)

    def test_23976_from_24(self):
        self._old_project(self.film, 24.0)
        self.assertEqual(self.importer.correct_frame_rates()[0][1:], (24.0, 23.976))

    def test_right_rate_stays(self):
        self._old_project(self.film, 23.976)
        self.assertEqual(self.importer.correct_frame_rates(), [])
        self.assertTrue(self.ctrl.undo_stack.isClean())

    def test_missing_file_is_skipped(self):
        self._old_project(os.path.join(self.tmp, "fehlt.264"), 24.0)
        self.assertEqual(self.importer.correct_frame_rates(), [])


if __name__ == "__main__":
    unittest.main()
