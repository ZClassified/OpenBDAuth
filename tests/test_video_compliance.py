# tests/test_video_compliance.py
"""
Tests für den Blu-ray Video Compliance & Format Pre-Flight Checker (v1.1.9).
"""

import unittest
from modules.video_tools import VideoTools, ComplianceWarning
from core.project_state import ProjectState, MediaTitle


class TestVideoCompliance(unittest.TestCase):
    def setUp(self):
        self.vt = VideoTools()

    def test_compliant_1080p24(self):
        """Ein standardkonformer 1080p24 Film (16:9, SAR 1:1) darf keine Warnungen erzeugen."""
        details = {
            "width": 1920,
            "height": 1080,
            "fps": 23.976,
            "is_interlaced": False,
            "sar": "1:1",
            "dar": "16:9"
        }
        warnings = self.vt.check_compliance(details)
        self.assertEqual(len(warnings), 0)

    def test_compliant_1080i50(self):
        """1080i50 (Interlaced 25 fps / 50 Halbbilder) ist voll BD-ROM konform und erzeugt keine Warnung."""
        details = {
            "width": 1920,
            "height": 1080,
            "fps": 25.0,
            "is_interlaced": True,
            "sar": "1:1",
            "dar": "16:9"
        }
        warnings = self.vt.check_compliance(details)
        self.assertEqual(len(warnings), 0)

    def test_compliant_720p50(self):
        """720p50 ist ein gültiges BD-Format (1280x720 50p)."""
        details = {
            "width": 1280,
            "height": 720,
            "fps": 50.0,
            "is_interlaced": False,
            "sar": "1:1",
            "dar": "16:9"
        }
        warnings = self.vt.check_compliance(details)
        self.assertEqual(len(warnings), 0)

    def test_unofficial_1080p25(self):
        """1080p25 (Progressive) ist außerhalb der BD-ROM Spezifikation und muss gewarnt werden."""
        details = {
            "width": 1920,
            "height": 1080,
            "fps": 25.0,
            "is_interlaced": False,
            "sar": "1:1",
            "dar": "16:9"
        }
        warnings = self.vt.check_compliance(details)
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].code, "UNOFFICIAL_1080P25")
        self.assertIn("1080p25", warnings[0].title)
        self.assertIn("1080i50", warnings[0].recommendation)

    def test_unofficial_1080p30(self):
        """1080p30 (Progressive 29.97/30 fps) muss gewarnt werden."""
        details = {
            "width": 1920,
            "height": 1080,
            "fps": 29.97,
            "is_interlaced": False,
            "sar": "1:1",
            "dar": "16:9"
        }
        warnings = self.vt.check_compliance(details)
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].code, "UNOFFICIAL_1080P30")

    def test_anamorphic_aspect_ratio_dar(self):
        """1920x1080 mit DAR 2.39:1 (oder 1312:549) muss als anamorph erkannt werden."""
        details = {
            "width": 1920,
            "height": 1080,
            "fps": 23.976,
            "is_interlaced": False,
            "sar": "1:1",
            "dar": "2.39:1"
        }
        warnings = self.vt.check_compliance(details)
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].code, "ANAMORPHIC_ASPECT_RATIO")
        self.assertIn("2.39:1", warnings[0].title)

    def test_anamorphic_aspect_ratio_sar(self):
        """1920x1080 mit ungleichem SAR (z. B. 82:61) muss als anamorph erkannt werden."""
        details = {
            "width": 1920,
            "height": 1080,
            "fps": 23.976,
            "is_interlaced": False,
            "sar": "82:61",
            "dar": "16:9"
        }
        warnings = self.vt.check_compliance(details)
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].code, "ANAMORPHIC_ASPECT_RATIO")

    def test_non_standard_resolution(self):
        """Ein beschnittener Stream wie 1920x800 muss als unkonform gemeldet werden."""
        details = {
            "width": 1920,
            "height": 800,
            "fps": 23.976,
            "is_interlaced": False,
            "sar": "1:1",
            "dar": ""
        }
        warnings = self.vt.check_compliance(details)
        self.assertTrue(any(w.code == "NON_STANDARD_RESOLUTION" for w in warnings))

    def test_multiple_warnings(self):
        """Ein Stream mit 1080p25 UND 2.39:1 anamorph erzeugt beide Warnungen."""
        details = {
            "width": 1920,
            "height": 1080,
            "fps": 25.0,
            "is_interlaced": False,
            "sar": "82:61",
            "dar": "1312:549"
        }
        warnings = self.vt.check_compliance(details)
        codes = [w.code for w in warnings]
        self.assertIn("UNOFFICIAL_1080P25", codes)
        self.assertIn("ANAMORPHIC_ASPECT_RATIO", codes)

    def test_project_state_warnings_aggregation(self):
        """Prüft get_all_compliance_warnings() im ProjectState."""
        proj = ProjectState()
        # Titel 1: Hat Warnungen
        proj.titles[0].name = "Hauptfilm"
        proj.titles[0].compliance_warnings = [{"code": "UNOFFICIAL_1080P25", "title": "1080p25"}]

        # Titel 2: Keine Warnungen
        proj.add_title("Bonus", is_main=False)
        proj.titles[1].compliance_warnings = []

        # Titel 3: Hat Warnungen
        proj.add_title("Episode 2", is_main=False)
        proj.titles[2].compliance_warnings = [{"code": "ANAMORPHIC_ASPECT_RATIO", "title": "Anamorph"}]

        all_warns = proj.get_all_compliance_warnings()
        self.assertEqual(len(all_warns), 2)
    def test_detect_h264_psf(self):
        """Testet die Erkennung von Fake-Interlaced / 25PsF anhand von SEI Optionen und SPS Header."""
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(suffix=".264", delete=False) as f:
            f.write(b"\x00\x00\x00\x01\x06\x05x264 - core 165 - options: interlaced=fake bluray_compat=1\x00")
            tmp_name = f.name
        try:
            self.assertTrue(VideoTools._detect_h264_psf(tmp_name))
        finally:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)

    def test_exact_30_fps_hint(self):
        """Exakt 30/60 fps (statt 30000/1001) bekommt einen Hinweis auf den Tonversatz, NTSC-Raten nicht."""
        base = {"width": 1920, "height": 1080, "fps": 29.97, "is_interlaced": True, "sar": "1:1", "dar": "16:9"}
        for raw in ("60/1", "30/1"):
            codes = [w.code for w in self.vt.check_compliance(dict(base, fps_raw=raw))]
            self.assertIn("EXACT_30_FPS", codes, raw)
        for raw in ("60000/1001", "30000/1001", "50/1", ""):
            codes = [w.code for w in self.vt.check_compliance(dict(base, fps_raw=raw))]
            self.assertNotIn("EXACT_30_FPS", codes, raw)

    def test_probe_video_details_on_instance(self):
        """Die Videoanalyse beim Import liest die ffprobe-Werte (v1.17.5: verwaistes @classmethod ließ jeden Import scheitern)."""
        import json
        import subprocess
        from unittest.mock import patch
        stream = {"width": 1920, "height": 1080, "r_frame_rate": "24000/1001", "codec_name": "hevc",
                  "sample_aspect_ratio": "1:1", "display_aspect_ratio": "16:9", "field_order": "progressive"}
        done = subprocess.CompletedProcess([], 0, stdout=json.dumps({"streams": [stream]}), stderr="")
        with patch("modules.video_tools.subprocess.run", return_value=done):
            details = VideoTools().probe_video_details("film.m2ts")
        self.assertEqual((details["width"], details["height"]), (1920, 1080))
        self.assertAlmostEqual(details["fps"], 23.976, places=3)
        self.assertEqual(details["warnings"], [])


if __name__ == "__main__":
    unittest.main()
