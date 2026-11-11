# tests/test_project_io.py
"""
Unit-Tests für die Projektverwaltung (.bdproj / JSON) und das Titel-Datenmodell (MediaTitle).
"""

import os
import tempfile
import unittest
from core.project_state import ProjectState, MediaTitle

class TestProjectIO(unittest.TestCase):
    def test_media_title_dict(self):
        """Prüft Serialisierung und Deserialisierung eines MediaTitle Objekts."""
        title = MediaTitle(name="Episode 1: Anfang", is_main=True)
        title.video_base = "C:/movies/ep1.264"
        title.fps = 24.0
        title.audio_tracks = [{"path": "C:/audio/de.ac3", "lang": "deu"}]
        title.subtitle_tracks = [{"path": "C:/subs/de.sup", "lang": "deu"}]
        title.chapters = ["00:00:00.000", "00:15:00.000"]

        d = title.to_dict()
        loaded = MediaTitle.from_dict(d)

        self.assertEqual(loaded.name, "Episode 1: Anfang")
        self.assertTrue(loaded.is_main)
        self.assertEqual(loaded.video_base, "C:/movies/ep1.264")
        self.assertEqual(loaded.fps, 24.0)
        self.assertEqual(len(loaded.audio_tracks), 1)
        self.assertEqual(len(loaded.subtitle_tracks), 1)
        self.assertEqual(len(loaded.chapters), 2)

    def test_backward_compatibility_properties(self):
        """Prüft, dass bestehende Properties direkt auf Title 0 und Title 1 delegieren."""
        proj = ProjectState()
        proj.video_base = "C:/movies/main.264"
        proj.video_mvc = "C:/movies/mvc.mvc"
        proj.fps = 23.976
        proj.chapters = ["00:00:00.000", "00:30:00.000"]
        proj.video_extra = "C:/movies/extra.264"

        self.assertEqual(proj.titles[0].video_base, "C:/movies/main.264")
        self.assertEqual(proj.titles[0].video_mvc, "C:/movies/mvc.mvc")
        self.assertEqual(len(proj.titles), 2)
        self.assertEqual(proj.titles[1].video_base, "C:/movies/extra.264")
        self.assertEqual(proj.video_extra, "C:/movies/extra.264")

    def test_add_and_remove_titles(self):
        """Prüft das Hinzufügen und Entfernen von Titeln sowie den Schutz von Titel 0."""
        proj = ProjectState()
        self.assertEqual(len(proj.titles), 1)

        t2 = proj.add_title(name="Making-Of")
        self.assertEqual(len(proj.titles), 2)
        self.assertEqual(t2.name, "Making-Of")
        self.assertFalse(t2.is_main)

        # Titel 0 (Hauptfilm) darf nicht gelöscht werden
        success = proj.remove_title(0)
        self.assertFalse(success)
        self.assertEqual(len(proj.titles), 2)

        # Titel 1 darf gelöscht werden
        success = proj.remove_title(1)
        self.assertTrue(success)
        self.assertEqual(len(proj.titles), 1)

    def test_save_and_load_project_file(self):
        """Prüft Speichern und Laden eines gesamten Projekts als .bdproj JSON-Datei."""
        proj = ProjectState()
        proj.project_name = "MEIN_MEISTERWERK"
        proj.video_base = "C:/content/film.264"
        proj.audio_tracks = [{"path": "C:/content/de.ac3", "lang": "deu"}]
        proj.chapters = ["00:00:00.000", "00:10:00.000"]
        proj.custom_button_positions[(0, 1)] = (550, 480)
        proj.custom_button_positions[(1, 2)] = (300, 200)

        # Zweiter Titel
        t2 = proj.add_title("Bonus Interview")
        t2.video_base = "C:/content/interview.264"

        with tempfile.TemporaryDirectory() as tmpdir:
            proj_path = os.path.join(tmpdir, "test.bdproj")
            proj.save_to_file(proj_path)
            self.assertTrue(os.path.exists(proj_path))

            # Neues leeres Projekt lädt die Datei
            loaded_proj = ProjectState()
            loaded_proj.load_from_file(proj_path)

            self.assertEqual(loaded_proj.project_name, "MEIN_MEISTERWERK")
            self.assertEqual(loaded_proj.video_base, "C:/content/film.264")
            self.assertEqual(len(loaded_proj.audio_tracks), 1)
            self.assertEqual(len(loaded_proj.titles), 2)
            self.assertEqual(loaded_proj.titles[1].name, "Bonus Interview")
            self.assertEqual(loaded_proj.titles[1].video_base, "C:/content/interview.264")
            self.assertEqual(loaded_proj.custom_button_positions[(0, 1)], (550, 480))
            self.assertEqual(loaded_proj.custom_button_positions[(1, 2)], (300, 200))

if __name__ == "__main__":
    unittest.main()
