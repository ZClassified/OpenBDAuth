# tests/test_studio.py
"""
Tests für die neue Arbeitsoberfläche (v1.6.0):
- Dateityp- und Spracherkennung, Kapitelzeiten
- Bearbeitungs-Operationen am Graphen (disc_edit) und Film-Operationen im Controller
- Import in Film-Knoten (Video-Analyse gestubbt, Tonspur-Vorbereitung im Hintergrund)
- Studio-Fenster: Auswahl steuert Viewer & Inspektor, Drag & Drop, Speichern/Öffnen
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QApplication

from core.chapter_time import is_valid_chapter_time, next_chapter_time, format_chapter_time
from core.media_import import classify_file, guess_language, prepare_audio_file, KIND_VIDEO, KIND_AUDIO
from core.disc_model import load_disc_project, START_NODE_ID
from core.disc_edit import starter_project, remove_nodes, set_chapter_times, add_track, move_track, TRACK_AUDIO
from core.disc_adapter import build_export_plan, preview_menu_specs
from gui.node_editor.controller import GraphController
from gui.studio.importer import FilmImporter
from tests.project_factory import temp_media

app_instance = QApplication.instance() or QApplication(sys.argv)

FAKE_DETAILS = {"width": 1920, "height": 1080, "fps": 24.0, "warnings": []}

EDL = """TITLE: Test
FCM: NON-DROP FRAME

001  001      V     C        00:00:00:00 00:00:00:01 00:00:00:00 00:00:00:01
002  001      V     C        00:05:00:00 00:05:00:01 00:05:00:00 00:05:00:01
003  001      V     C        00:10:00:12 00:10:00:13 00:10:00:12 00:10:00:13
"""


class TestMediaHelpers(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(classify_file("C:/x/film.264"), KIND_VIDEO)
        self.assertEqual(classify_file("C:/x/ton.AC3"), KIND_AUDIO)
        self.assertIsNone(classify_file("C:/x/bild.png"))

    def test_guess_language(self):
        self.assertEqual(guess_language("C:/film_ger_51.ac3"), "deu")
        self.assertEqual(guess_language("movie.en.srt"), "eng")
        self.assertEqual(guess_language("Final_Mix.ac3", "deu"), "deu")   # keine Fehlerkennung
        self.assertEqual(guess_language("The_Film.ac3", "eng"), "eng")

    def test_prepare_audio_passthrough(self):
        self.assertEqual(prepare_audio_file("C:/ton.ac3"), "C:/ton.ac3")

    def test_chapter_times(self):
        self.assertTrue(is_valid_chapter_time("00:05:00.000"))
        self.assertTrue(is_valid_chapter_time("1:05:00"))
        self.assertFalse(is_valid_chapter_time("00:75:00.000"))
        self.assertFalse(is_valid_chapter_time("abc"))
        self.assertEqual(next_chapter_time([]), "00:00:00.000")
        self.assertEqual(next_chapter_time(["00:00:00.000", "00:12:30.500"]), "00:17:30.500")
        self.assertEqual(format_chapter_time(3723.5), "01:02:03.500")


class TestDiscEdit(unittest.TestCase):
    def test_starter_project_is_exportable(self):
        project = starter_project()
        plan = build_export_plan(project)
        self.assertEqual([s.text for s in plan.pages_specs[0][1]], ["FILM STARTEN"])
        self.assertEqual(plan.pages_specs[0][1][0].action_type, "jump_title")

    def test_remove_film_drops_references(self):
        project = starter_project()
        film = project.films[0]
        remove_nodes(project, [film.id])
        self.assertEqual(project.films, [])
        self.assertIsNone(project.main_menu.buttons[0].target)

    def test_chapter_ids_survive_edits(self):
        project = starter_project()
        film = project.films[0]
        set_chapter_times(film, ["00:00:00.000", "00:05:00.000"])
        ids = [c.id for c in film.chapters]
        set_chapter_times(film, ["00:00:00.000", "00:06:00.000", "00:10:00.000"])
        self.assertEqual([c.id for c in film.chapters][:2], ids)

    def test_move_track(self):
        film = starter_project().films[0]
        a = add_track(film, TRACK_AUDIO, "a.ac3", "deu")
        b = add_track(film, TRACK_AUDIO, "b.ac3", "eng")
        move_track(film, TRACK_AUDIO, b.id, -1)
        self.assertEqual([t.id for t in film.audio_tracks], [b.id, a.id])

    def test_preview_tolerates_unfinished_projects(self):
        project = starter_project()
        remove_nodes(project, [project.films[0].id])
        specs = preview_menu_specs(project, project.main_menu)
        self.assertEqual(specs[0].text, "FILM STARTEN")


class TestControllerFilms(unittest.TestCase):
    def setUp(self):
        self.ctrl = GraphController(starter_project())
        self.film_id = self.ctrl.project.films[0].id

    def test_remove_chapter_keeps_other_ids(self):
        self.ctrl.set_chapter_times(self.film_id, ["00:00:00.000", "00:05:00.000", "00:10:00.000"])
        first, middle, last = [c.id for c in self.ctrl.project.film(self.film_id).chapters]
        self.ctrl.remove_chapters(self.film_id, [middle])
        self.assertEqual([c.id for c in self.ctrl.project.film(self.film_id).chapters], [first, last])
        self.ctrl.undo_stack.undo()
        self.assertEqual(len(self.ctrl.project.film(self.film_id).chapters), 3)

    def test_track_operations_are_undoable(self):
        track_id = self.ctrl.add_track(self.film_id, TRACK_AUDIO, "C:/a.ac3", "deu")
        self.ctrl.set_track_lang(self.film_id, TRACK_AUDIO, track_id, "eng")
        self.assertEqual(self.ctrl.project.film(self.film_id).audio_tracks[0].lang, "eng")
        self.ctrl.undo_stack.undo()
        self.assertEqual(self.ctrl.project.film(self.film_id).audio_tracks[0].lang, "deu")
        self.ctrl.remove_track(self.film_id, TRACK_AUDIO, track_id)
        self.assertEqual(self.ctrl.project.film(self.film_id).audio_tracks, [])


class TestImporter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ctrl = GraphController(starter_project())
        self.importer = FilmImporter(self.ctrl, lambda: "deu")
        self.importer.probe = lambda path, is_3d: dict(FAKE_DETAILS)
        self.importer.check_pair = lambda base, mvc: []      # Dateien gibt es nicht (Prüfung: test_mvc_import)
        self.edl = os.path.join(self.tmp.name, "marker.edl")
        with open(self.edl, "w", encoding="utf-8") as f:
            f.write(EDL)

    def tearDown(self):
        self.importer.wait_for_workers()
        self.tmp.cleanup()

    def test_import_into_existing_film(self):
        film_id = self.ctrl.project.films[0].id
        self.importer.import_files(film_id, ["C:/v/film.264", "C:/v/film.mvc", "C:/a/ton_eng.ac3",
                                             "C:/s/film_ger.sup", self.edl, "C:/x/bild.png"])
        film = self.ctrl.project.film(film_id)
        self.assertEqual((film.video_base, film.video_mvc, film.fps), ("C:/v/film.264", "C:/v/film.mvc", 24.0))
        self.assertEqual([(t.path, t.lang) for t in film.audio_tracks], [("C:/a/ton_eng.ac3", "eng")])
        self.assertEqual([t.lang for t in film.subtitle_tracks], ["deu"])
        self.assertEqual([c.time for c in film.chapters], ["00:00:00.000", "00:05:00.000", "00:10:00.500"])

    def test_drop_video_on_empty_space_creates_film(self):
        film_id = self.importer.import_files(None, ["C:/v/Making_of.264"], QPointF(900, 400))
        film = self.ctrl.project.film(film_id)
        self.assertEqual(film.name, "Making_of")
        self.assertEqual(self.ctrl.project.view.node_positions[film_id], [900.0, 400.0])

    def test_drop_without_video_on_empty_space_does_nothing(self):
        messages = []
        self.importer.status.connect(messages.append)
        self.assertIsNone(self.importer.import_files(None, ["C:/a/ton.ac3"]))
        self.assertEqual(len(self.ctrl.project.films), 1)
        self.assertTrue(messages)

    def test_wav_is_prepared_in_background(self):
        film_id = self.ctrl.project.films[0].id
        with mock.patch("gui.studio.importer.prepare_audio_file", side_effect=lambda p: p[:-4] + "_clean.wav"):
            self.importer.add_audio(film_id, "C:/a/mix_de.wav")
            self.importer.wait_for_workers()
            app_instance.processEvents()
        film = self.ctrl.project.film(film_id)
        self.assertEqual([(t.path, t.lang) for t in film.audio_tracks], [("C:/a/mix_de_clean.wav", "deu")])

    def _raw_3d_probe(self, path, is_3d):
        """Wie ein roher 3D-Stream: meldet 25 fps, nur mit 3D-Hinweis korrigiert auf 23.976."""
        return dict(FAKE_DETAILS, fps=23.976 if is_3d else 25.0)

    def test_3d_import_uses_3d_hint_regardless_of_file_order(self):
        self.importer.probe = self._raw_3d_probe
        film_id = self.ctrl.project.films[0].id
        self.importer.import_files(film_id, ["C:/v/film.264", "C:/v/film.mvc"])
        self.assertEqual(self.ctrl.project.film(film_id).fps, 23.976)

    def test_adding_or_removing_mvc_reprobes_video(self):
        self.importer.probe = self._raw_3d_probe
        film_id = self.ctrl.project.films[0].id
        self.importer.set_video(film_id, "C:/v/film.264")
        self.assertEqual(self.ctrl.project.film(film_id).fps, 25.0)      # noch 2D
        self.importer.set_mvc(film_id, "C:/v/film.mvc")
        self.assertEqual(self.ctrl.project.film(film_id).fps, 23.976)    # jetzt 3D
        self.importer.set_mvc(film_id, None)
        self.assertEqual(self.ctrl.project.film(film_id).fps, 25.0)

    def test_compliance_warnings_are_reported(self):
        warned = []
        self.importer.compliance_warnings.connect(warned.append)
        self.importer.probe = lambda path, is_3d: dict(FAKE_DETAILS, warnings=[{"title": "x"}])
        film_id = self.ctrl.project.films[0].id
        self.importer.set_video(film_id, "C:/v/film.264")
        self.assertEqual(warned, [film_id])


class TestStudioWindow(unittest.TestCase):
    def setUp(self):
        from gui.studio.main_window import StudioWindow
        self.win = StudioWindow(persist_layout=False)
        self.win.importer.probe = lambda path, is_3d: dict(FAKE_DETAILS)
        self.project = self.win.controller.project

    def tearDown(self):
        self.win.controller.undo_stack.setClean()
        self.win.close()

    def _select(self, node_id):
        self.win.scene.select_node(node_id)
        app_instance.processEvents()

    def test_floating_viewer_has_dock_button_and_fills_screen(self):
        """v1.17.2: abgekoppelt „Andocken“ oben rechts; Doppelklick füllt den Bildschirm und stellt wieder her."""
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QMouseEvent
        self.win.show()
        dock = self.win.dock_viewer
        bar = dock.titleBarWidget()
        self.assertIn("Abkoppeln", bar.button.text())
        bar.button.click()
        app_instance.processEvents()
        self.assertTrue(dock.isFloating())
        self.assertIn("Andocken", bar.button.text())
        dock.setGeometry(100, 100, 900, 600)
        double = lambda: bar.mouseDoubleClickEvent(QMouseEvent(
            QMouseEvent.MouseButtonDblClick, QPointF(20, 5), QPointF(20, 5), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        double()
        self.assertEqual(dock.geometry(), dock.screen().availableGeometry())
        double()
        self.assertEqual(dock.geometry().size().toTuple(), (900, 600))
        bar.button.click()
        app_instance.processEvents()
        self.assertFalse(dock.isFloating())

    def test_selection_drives_viewer_and_inspector(self):
        film = self.project.films[0]
        self._select(film.id)
        self.assertIs(self.win.inspector.stack.currentWidget(), self.win.inspector.film_page)
        self.assertIs(self.win.viewer.stack.currentWidget(), self.win.viewer.card)
        self._select(self.project.main_menu.id)
        self.assertIs(self.win.inspector.stack.currentWidget(), self.win.inspector.menu_page)
        self.assertIs(self.win.viewer.stack.currentWidget(), self.win.viewer.menu_preview)
        self._select(START_NODE_ID)
        self.assertIs(self.win.inspector.stack.currentWidget(), self.win.inspector.start_page)

    def test_inspector_follows_imports_and_undo(self):
        film = self.project.films[0]
        self._select(film.id)
        self.win.importer.import_files(film.id, [temp_media(self, "film.264")])
        app_instance.processEvents()
        page = self.win.inspector.film_page
        self.assertEqual(page.lbl_base.text(), "film.264")
        self.assertIn("24.000 fps", page.lbl_info.text())
        self.assertTrue(self.win.isWindowModified())
        self.win.controller.undo_stack.undo()
        app_instance.processEvents()
        self.assertNotEqual(page.lbl_base.text(), "film.264")

    def test_dropping_video_on_canvas_creates_and_selects_film(self):
        self.win._on_files_dropped("", ["C:/v/Trailer.264"], QPointF(1000, 300))
        app_instance.processEvents()
        selected = self.win.scene.selected_node_id()
        self.assertEqual(self.win.controller.project.film(selected).name, "Trailer")
        self.assertIs(self.win.inspector.stack.currentWidget(), self.win.inspector.film_page)

    def test_invalid_chapter_time_is_rejected(self):
        film = self.project.films[0]
        self.win.controller.set_chapter_times(film.id, ["00:00:00.000"])
        self._select(film.id)
        table = self.win.inspector.film_page.table
        table.item(0, 0).setText("kaputt")
        app_instance.processEvents()
        self.assertEqual(self.win.controller.project.film(film.id).chapters[0].time, "00:00:00.000")
        self.assertEqual(table.item(0, 0).text(), "00:00:00.000")

    def test_save_and_open(self):
        self.win.controller.set_settings("Name", project_name="MEINE_DISC")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "disc.bdproj")
            self.assertTrue(self.win._write(path))
            self.assertFalse(self.win.isWindowModified())
            loaded = load_disc_project(path)
            self.assertEqual(loaded.settings.project_name, "MEINE_DISC")
            self.win.set_project(loaded, path)
            self.assertIn("MEINE_DISC", self.win.windowTitle())

    def test_disc_name_is_sanitized(self):
        from gui.studio.inspector import sanitize_disc_name
        self.assertEqual(sanitize_disc_name("my disc: 2026!"), "MY_DISC__2026_")

    def test_player_title_in_disc_inspector(self):
        """v1.10.1: Titel im Player als freier Text; leer = Disc-Name mit Leerzeichen (Platzhalter zeigt ihn)."""
        from core.disc_model import START_NODE_ID
        self.win.controller.set_settings("Name", project_name="MEINE_DISC")
        self._select(START_NODE_ID)
        page = self.win.inspector.start_page
        page.refresh()
        self.assertEqual(page.edit_title.text(), "")
        self.assertEqual(page.edit_title.placeholderText(), "MEINE DISC")
        page.edit_title.setText("  Mein Film – Teil Ä  ")
        page.edit_title.editingFinished.emit()
        settings = self.win.controller.project.settings
        self.assertEqual(settings.disc_title, "Mein Film – Teil Ä")
        self.assertEqual(settings.player_title(), "Mein Film – Teil Ä")
        self.assertEqual(settings.project_name, "MEINE_DISC")          # Label bleibt UDF-konform
        self.win.controller.undo_stack.undo()
        self.assertEqual(self.win.controller.project.settings.player_title(), "MEINE DISC")

    def test_fit_button_in_node_view(self):
        from unittest import mock
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        view = self.win.view
        self.assertEqual(view.fit_button.toolTip(), "Alles anzeigen (F)")
        self.assertFalse(view.fit_button.icon().isNull())
        with mock.patch.object(view, "fit_all") as fit:
            view.fit_button.clicked.disconnect()
            view.fit_button.clicked.connect(view.fit_all)
            view.fit_button.click()
            view.setFocus()
            QTest.keyClick(view, Qt.Key_F)
        self.assertEqual(fit.call_count, 2)

    def test_fit_all_on_first_show(self):
        """Beim Programmstart ist der Graph eingepasst – nach Maximieren, nicht auf die Größe vor dem Anzeigen."""
        from gui.node_editor.scene import NodeItem
        view = self.win.view
        self.assertFalse(view.isVisible())
        self.assertTrue(view._fit_pending)   # Konstruktor hat „Alles anzeigen“ nur vorgemerkt
        self.win.resize(2400, 1400)
        self.win.show()
        app_instance.processEvents()
        app_instance.processEvents()
        visible = view.mapToScene(view.viewport().rect()).boundingRect()
        for item in (i for i in view.scene().items() if isinstance(i, NodeItem)):
            self.assertTrue(visible.contains(item.sceneBoundingRect()))
        # Nach eigenem Zoomen passt eine Größenänderung nicht mehr neu ein
        view._fit_pending = False
        zoom = view.zoom()
        self.win.resize(1200, 800)
        app_instance.processEvents()
        self.assertEqual(view.zoom(), zoom)
        self.win.close()

    def test_language_switch_retranslates(self):
        from core.translations import tr, set_ui_language
        self.addCleanup(set_ui_language, "de")
        self.win.set_ui_lang("en")
        app_instance.processEvents()
        self.assertEqual(self.win.act_save.text(), tr("studio_save", "en"))
        self.assertNotEqual(tr("studio_save", "en"), tr("studio_save", "de"))
        self.assertIn("Undock", self.win.dock_viewer.titleBarWidget().button.text())


if __name__ == "__main__":
    unittest.main()
