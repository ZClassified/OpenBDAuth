"""
Disc-Typ (UHD-Plan, Phase 1): Blu-ray oder Ultra HD Blu-ray im Start-Knoten.
- Modell: Vorgabe Blu-ray, gespeichert mit dem Projekt, ältere Projekte bleiben Blu-ray; HEVC-Filme an der Endung
- Umstellen mit Rückfrage („nur UHD-Player“, unpassende Filme genannt), Abbrechen lässt alles, wie es war
- Vorprüfung: 3D auf UHD und HEVC auf Blu-ray sind Fehler, H.264 auf UHD ein Hinweis (Phase 0.8); UHD-Export
  vorläufig gesperrt (Phase 4)
- Anzeige: Untertitel des Start-Knotens, Kopfleiste von Vorbereiten
"""
import os
import sys
import tempfile
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from core import preflight
from core.disc_edit import starter_project
from core.disc_model import DiscProject, START_NODE_ID, load_disc_project
from core.disc_rules import films_not_fitting
from core.translations import tr

app_instance = QApplication.instance() or QApplication(sys.argv)


def messages(project, level):
    return [i.message for i in preflight.run_preflight(project, check_files=False) if i.level == level]


class TestModel(unittest.TestCase):
    def test_default_saved_and_older_projects(self):
        project = starter_project()
        self.assertEqual(project.settings.disc_type, "bluray")
        self.assertFalse(project.settings.is_uhd)
        project.settings.disc_type = "uhd"
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "uhd.bdproj")
            project.save_to_file(path)
            self.assertTrue(load_disc_project(path).settings.is_uhd)
        data = starter_project().to_dict()
        del data["settings"]["disc_type"]
        self.assertEqual(DiscProject.from_dict(data).settings.disc_type, "bluray")

    def test_hevc_film_and_misfits(self):
        project = starter_project()
        film = project.films[0]
        self.assertFalse(film.is_hevc)
        film.video_base = "C:/Filme/Film_2160p.HEVC"
        self.assertTrue(film.is_hevc)
        self.assertEqual(films_not_fitting(project, "bluray"), [film])
        self.assertEqual(films_not_fitting(project, "uhd"), [])
        film.video_base, film.video_mvc = "C:/Filme/Film_3D.264", "C:/Filme/Film_3D.mvc"
        self.assertEqual(films_not_fitting(project, "uhd"), [film])
        self.assertEqual(films_not_fitting(project, "bluray"), [])


class TestPreflight(unittest.TestCase):
    def setUp(self):
        self.project = starter_project()
        self.film = self.project.films[0]
        self.film.name = "Hauptfilm"

    def test_bluray_with_hevc_film(self):
        self.film.video_base = "film_2160p.hevc"
        self.assertIn(tr("pf_bluray_hevc_film", film="Hauptfilm"), messages(self.project, preflight.ERROR))

    def test_uhd_with_3d_film(self):
        self.project.settings.disc_type = "uhd"
        self.film.video_base, self.film.video_mvc = "film.264", "film.mvc"
        errors = messages(self.project, preflight.ERROR)
        self.assertIn(tr("pf_uhd_3d_film", film="Hauptfilm"), errors)
        self.assertIn(tr("pf_uhd_not_ready"), errors)                      # vorläufig bis Phase 4

    def test_uhd_with_h264_and_hevc_film(self):
        self.project.settings.disc_type = "uhd"
        self.film.video_base = "film.264"
        self.assertIn(tr("pf_uhd_h264_film", film="Hauptfilm"), messages(self.project, preflight.WARNING))
        self.film.video_base = "film_2160p.hevc"
        self.assertNotIn(tr("pf_uhd_h264_film", film="Hauptfilm"), messages(self.project, preflight.WARNING))
        errors = messages(self.project, preflight.ERROR)
        self.assertNotIn(tr("pf_bluray_hevc_film", film="Hauptfilm"), errors)

    def test_bluray_unchanged(self):
        self.film.video_base = "film.264"
        all_messages = [i.message for i in preflight.run_preflight(self.project, check_files=False)]
        for key in ("pf_uhd_not_ready",):
            self.assertNotIn(tr(key), all_messages)


class TestStartNode(unittest.TestCase):
    def setUp(self):
        from gui.studio.main_window import StudioWindow
        self.win = StudioWindow(persist_layout=False)
        self.ctrl = self.win.controller
        self.win.scene.select_node(START_NODE_ID)
        app_instance.processEvents()
        self.start = self.win.inspector.start_page
        self.asked = []
        self.answer = True
        self.start.confirm_disc_type = lambda text: self.asked.append(text) or self.answer

    def tearDown(self):
        self.ctrl.undo_stack.setClean()
        self.win.close()

    def choose(self, disc_type):
        combo = self.start.combo_type
        combo.setCurrentIndex(combo.findData(disc_type))
        combo.activated.emit(combo.currentIndex())
        app_instance.processEvents()

    def test_switch_to_uhd_asks_and_shows(self):
        self.assertEqual(self.start.combo_type.currentData(), "bluray")
        self.choose("uhd")
        self.assertEqual(len(self.asked), 1)
        self.assertIn(tr("studio_disc_type_uhd_only"), self.asked[0])
        self.assertTrue(self.ctrl.project.settings.is_uhd)
        self.assertEqual(self.win.scene.nodes[START_NODE_ID].subtitle, tr("graph_start_subtitle_uhd"))
        self.assertEqual(self.win.prepare_page.lbl_disc_size.text(), "Ultra HD · BD-25")
        self.choose("bluray")                                              # zurück: nichts passt nicht
        self.assertEqual(len(self.asked), 1)
        self.assertFalse(self.ctrl.project.settings.is_uhd)
        self.assertEqual(self.win.prepare_page.lbl_disc_size.text(), "BD-25")

    def test_cancel_keeps_type_and_names_misfits(self):
        film = self.ctrl.project.films[0]
        film.video_base, film.video_mvc = "film_3D.264", "film_3D.mvc"
        self.answer = False
        self.choose("uhd")
        self.assertIn(f"„{film.name}“", self.asked[0])
        self.assertFalse(self.ctrl.project.settings.is_uhd)
        self.assertEqual(self.start.combo_type.currentData(), "bluray")   # Auswahl zurückgesetzt
        self.assertTrue(self.ctrl.undo_stack.isClean())

    def test_undo(self):
        self.choose("uhd")
        self.ctrl.undo_stack.undo()
        app_instance.processEvents()
        self.assertFalse(self.ctrl.project.settings.is_uhd)
        self.assertEqual(self.start.combo_type.currentData(), "bluray")


if __name__ == "__main__":
    unittest.main()
