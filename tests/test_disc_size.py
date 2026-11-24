# tests/test_disc_size.py
"""
Disc-Größe gehört zum Projekt (v1.36): einstellen im Start-Knoten, Vorbereiten zeigt sie nur an („ändern“ springt
zum Start-Knoten). Bis v1.35 war sie eine App-Einstellung in Vorbereiten; Projekte ohne Größe übernehmen sie
einmal beim Öffnen, ohne als geändert zu gelten.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from core.disc_edit import starter_project
from core.disc_model import DiscProject, DiscSettings, START_NODE_ID, load_disc_project

app_instance = QApplication.instance() or QApplication(sys.argv)


class TestModel(unittest.TestCase):
    def test_default_and_unknown_is_bd25(self):
        self.assertEqual(DiscSettings().disc_size, "")
        self.assertEqual(DiscSettings().disc_size_key(), "bd25")
        self.assertEqual(DiscSettings(disc_size="bd99").disc_size_key(), "bd25")
        self.assertEqual(DiscSettings(disc_size="bd50").disc_size_key(), "bd50")

    def test_saved_with_project(self):
        project = starter_project()
        project.settings.disc_size = "bd50"
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "disc.bdproj")
            project.save_to_file(path)
            self.assertEqual(load_disc_project(path).settings.disc_size, "bd50")

    def test_older_project_without_size(self):
        data = starter_project().to_dict()
        del data["settings"]["disc_size"]
        self.assertEqual(DiscProject.from_dict(data).settings.disc_size, "")


class TestStudio(unittest.TestCase):
    def setUp(self):
        from gui.studio.main_window import StudioWindow
        self.win = StudioWindow(persist_layout=False)
        self.ctrl = self.win.controller
        self.page = self.win.prepare_page

    def tearDown(self):
        self.ctrl.undo_stack.setClean()
        self.win.close()

    def test_new_project_has_a_size(self):
        self.assertEqual(self.ctrl.project.settings.disc_size, "bd25")
        self.assertTrue(self.ctrl.undo_stack.isClean())

    def test_start_node_sets_size_and_prepare_shows_it(self):
        self.win.scene.select_node(START_NODE_ID)
        app_instance.processEvents()
        start = self.win.inspector.start_page
        self.assertIs(self.win.inspector.stack.currentWidget(), start)
        self.assertEqual(start.combo_size.currentData(), "bd25")
        self.assertEqual(self.page.lbl_disc_size.text(), "BD-25")
        start.combo_size.setCurrentIndex(start.combo_size.findData("bd50"))
        start.combo_size.activated.emit(start.combo_size.currentIndex())
        app_instance.processEvents()
        self.assertEqual(self.ctrl.project.settings.disc_size, "bd50")
        self.assertEqual(self.page.lbl_disc_size.text(), "BD-50")
        self.assertIn("50,0 GB", self.page.lbl_gauge.text())
        self.ctrl.undo_stack.undo()                                     # ein Rückgängig-Schritt
        self.assertEqual(self.ctrl.project.settings.disc_size, "bd25")
        self.assertEqual(self.page.lbl_disc_size.text(), "BD-25")

    def test_change_jumps_to_start_node(self):
        from gui.studio.main_window import PAGE_DISC, PAGE_PREPARE
        self.win.show_page(PAGE_PREPARE)
        self.page.btn_disc_change.click()
        app_instance.processEvents()
        self.assertEqual(self.win.page, PAGE_DISC)
        self.assertTrue(self.win.page_actions[PAGE_DISC].isChecked())
        self.assertEqual(self.win.scene.selected_node_id(), START_NODE_ID)
        self.assertIs(self.win.inspector.stack.currentWidget(), self.win.inspector.start_page)

    def test_older_project_adopts_app_setting(self):
        project = starter_project()
        self.assertEqual(project.settings.disc_size, "")
        self.win._persist_layout = True
        with mock.patch("gui.studio.main_window.QSettings") as settings:
            settings.return_value.value.return_value = "bd50"
            self.win.set_project(project)
        self.assertEqual(self.ctrl.project.settings.disc_size, "bd50")
        self.assertTrue(self.ctrl.undo_stack.isClean())                 # gilt nicht als geändert
        kept = starter_project()
        kept.settings.disc_size = "bd25"                                # eigene Größe bleibt
        with mock.patch("gui.studio.main_window.QSettings") as settings:
            settings.return_value.value.return_value = "bd50"
            self.win.set_project(kept)
        self.assertEqual(self.ctrl.project.settings.disc_size, "bd25")
        self.win._persist_layout = False


if __name__ == "__main__":
    unittest.main()
