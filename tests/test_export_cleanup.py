# tests/test_export_cleanup.py
"""
Unit-Tests für die Export-Bereinigung und Untertitel-Ablage (v1.2.0).
"""

import os
import shutil
import tempfile
import unittest
from core.project_state import ProjectState, MediaTitle
from core.meta_builder import MetaBuilder


class TestExportCleanup(unittest.TestCase):
    def test_sup_saved_in_srt_directory(self):
        """Prüft, dass konvertierte .sup-Dateien direkt im Ordner der Quell-.srt-Datei abgelegt werden."""
        with tempfile.TemporaryDirectory() as srt_dir, tempfile.TemporaryDirectory() as export_dir:
            srt_path = os.path.join(srt_dir, "film_dialog.srt")
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write("1\n00:00:01,000 --> 00:00:03,000\nHallo Welt\n")

            proj = ProjectState()
            proj.video_base = "C:/dummy/video.264"
            proj.add_subtitle_track(srt_path, "deu")

            meta_file = os.path.join(export_dir, "job.meta")
            mb = MetaBuilder(proj)
            mb.save_meta_file(meta_file)

            # Die .sup-Datei liegt in srt_dir, nicht in export_dir
            expected_sup = os.path.join(srt_dir, "film_dialog_deu.sup")
            self.assertTrue(os.path.exists(expected_sup), f"SUP-Datei sollte in {srt_dir} liegen, existiert aber nicht.")

            # In export_dir darf KEINE .sup-Datei liegen
            export_sups = [f for f in os.listdir(export_dir) if f.endswith(".sup")]
            self.assertEqual(len(export_sups), 0, f"Keine .sup-Dateien sollten im Exportordner liegen: {export_sups}")

    def test_sup_clean_name_when_lang_already_present(self):
        """Wenn der Dateiname der SRT bereits die Sprache enthält (z. B. film_deu.srt), soll kein doppeltes deu_deu entstehen."""
        with tempfile.TemporaryDirectory() as srt_dir, tempfile.TemporaryDirectory() as export_dir:
            srt_path = os.path.join(srt_dir, "film_deu.srt")
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write("1\n00:00:01,000 --> 00:00:03,000\nHallo\n")

            proj = ProjectState()
            proj.video_base = "C:/dummy/video.264"
            proj.add_subtitle_track(srt_path, "deu")

            meta_file = os.path.join(export_dir, "job.meta")
            mb = MetaBuilder(proj)
            mb.save_meta_file(meta_file)

            expected_sup = os.path.join(srt_dir, "film_deu.sup")
            self.assertTrue(os.path.exists(expected_sup))

    def test_iso_temp_files_cleanup_logic(self):
        """Simuliert die Bereinigung von BDMV, CERTIFICATE und job.meta nach erfolgreicher ISO-Erstellung."""
        with tempfile.TemporaryDirectory() as dest:
            bdmv_dir = os.path.join(dest, "BDMV")
            cert_dir = os.path.join(dest, "CERTIFICATE")
            os.makedirs(os.path.join(bdmv_dir, "STREAM"), exist_ok=True)
            os.makedirs(cert_dir, exist_ok=True)

            # Dummy-Dateien erzeugen
            with open(os.path.join(bdmv_dir, "STREAM", "00000.m2ts"), "wb") as f:
                f.write(b"M2TS_DATA")
            meta_file = os.path.join(dest, "job.meta")
            with open(meta_file, "w", encoding="utf-8") as f:
                f.write("MUXOPT --blu-ray")
            iso_file = os.path.join(dest, "DISC.iso")
            with open(iso_file, "wb") as f:
                f.write(b"ISO_DATA")

            # Bereinigungslogik ausführen
            if os.path.exists(bdmv_dir):
                shutil.rmtree(bdmv_dir, ignore_errors=True)
            if os.path.exists(cert_dir):
                shutil.rmtree(cert_dir, ignore_errors=True)
            if os.path.exists(meta_file):
                os.remove(meta_file)

            # Verifizieren: Nur die ISO darf übrig bleiben!
            remaining = os.listdir(dest)
            self.assertIn("DISC.iso", remaining)
            self.assertNotIn("BDMV", remaining)
            self.assertNotIn("CERTIFICATE", remaining)
            self.assertNotIn("job.meta", remaining)
            self.assertEqual(remaining, ["DISC.iso"])


if __name__ == "__main__":
    unittest.main()
