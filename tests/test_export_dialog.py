# tests/test_export_dialog.py
"""Tests für Preflight-Check und den Dialog „Disc erstellen“ (v1.7.0)."""

import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from core.disc_edit import starter_project, add_film, set_chapter_times, add_track, TRACK_AUDIO
from core.disc_model import MenuNode, MenuButton, BUTTON_NAV, START_NODE_ID
from core.preflight import run_preflight, has_errors, ERROR, WARNING, INFO
from gui.node_editor.controller import GraphController
from tests.project_factory import text_starter, temp_media

app_instance = QApplication.instance() or QApplication(sys.argv)


def ready_project():
    project = text_starter()
    project.films[0].video_base = "C:/v/film.264"
    return project


class TestPreflight(unittest.TestCase):
    def levels(self, project):
        return [(i.level, i.node_id) for i in run_preflight(project, check_files=False)]

    def test_ready_project_has_no_issues(self):
        self.assertEqual(run_preflight(ready_project(), check_files=False), [])

    def test_film_without_video_is_an_error(self):
        project = starter_project()
        self.assertIn((ERROR, project.films[0].id), self.levels(project))
        self.assertTrue(has_errors(run_preflight(project)))

    def test_missing_start_is_an_error(self):
        project = ready_project()
        project.start_target = None
        self.assertIn((ERROR, START_NODE_ID), self.levels(project))

    def test_unconnected_button_and_unreachable_menu_are_warnings(self):
        project = ready_project()
        project.main_menu.buttons.append(MenuButton(id="b_x", kind=BUTTON_NAV, label="EXTRAS"))
        orphan = MenuNode(id="m_orphan", name="Waise", buttons=[
            MenuButton(id="b_o", kind=BUTTON_NAV, label="ZURÜCK", target=project.main_menu.id)])
        project.menus.append(orphan)
        levels = self.levels(project)
        self.assertIn((WARNING, project.main_menu.id), levels)
        self.assertIn((WARNING, "m_orphan"), levels)
        self.assertFalse(has_errors(run_preflight(project, check_files=False)))

    def test_film_end_in_another_menu_is_fine(self):
        project = ready_project()
        extra = MenuNode(id="m_extra", name="Extras", buttons=[
            MenuButton(id="b_back", kind=BUTTON_NAV, label="ZURÜCK", target=project.main_menu.id)])
        project.menus.append(extra)
        project.main_menu.buttons.append(MenuButton(id="b_e", kind=BUTTON_NAV, label="EXTRAS", target="m_extra"))
        project.films[0].end_target = "m_extra"                                  # ab v1.18 erlaubt
        self.assertNotIn((ERROR, project.films[0].id), self.levels(project))
        project.films[0].end_target = project.films[0].id                     # Film wiederholt sich (v1.18.1)
        self.assertIn((WARNING, project.films[0].id), self.levels(project))
        self.assertNotIn((ERROR, project.films[0].id), self.levels(project))

    def test_suggestions_for_chapter_and_language_menus(self):
        project = ready_project()
        film = project.films[0]
        set_chapter_times(film, ["00:00:00.000", "00:05:00.000"])
        add_track(film, TRACK_AUDIO, "a.ac3", "deu")
        add_track(film, TRACK_AUDIO, "b.ac3", "eng")
        infos = [i for i in run_preflight(project, check_files=False) if i.level == INFO]
        self.assertEqual(len(infos), 2)
        film.dismissed_hints = ["chapter_menu", "language_menu"]
        self.assertEqual(run_preflight(project, check_files=False), [])

    def test_unacknowledged_compliance_is_a_warning(self):
        project = ready_project()
        project.films[0].compliance_warnings = [{"title": "25p"}]
        self.assertIn((WARNING, project.films[0].id), self.levels(project))


class TestExportDialog(unittest.TestCase):
    def setUp(self):
        from gui.studio.export_dialog import ExportDialog
        project = ready_project()
        project.films[0].video_base = temp_media(self, "film.264")
        self.ctrl = GraphController(project)
        self.dialog = ExportDialog(self.ctrl)

    def tearDown(self):
        self.dialog.close()

    def test_start_needs_destination(self):
        self.assertFalse(self.dialog.btn_start.isEnabled())
        self.ctrl.set_settings("Ziel", output_path="C:/Ziel")
        app_instance.processEvents()
        self.assertTrue(self.dialog.btn_start.isEnabled())

    def test_errors_block_export_and_issue_selects_node(self):
        self.ctrl.set_settings("Ziel", output_path="C:/Ziel")
        film_id = self.ctrl.project.films[0].id
        self.ctrl.set_film_fields(film_id, "Video weg", video_base=None)
        app_instance.processEvents()
        self.assertFalse(self.dialog.btn_start.isEnabled())
        selected = []
        self.dialog.select_node.connect(selected.append)
        item = self.dialog.issue_list.item(0)
        self.dialog._on_issue_clicked(item)
        self.assertEqual(selected, [film_id])

    def test_format_choice_is_stored(self):
        self.dialog.btn_iso.setChecked(True)
        self.assertEqual(self.ctrl.project.settings.export_format, "iso")
        self.assertTrue(self.dialog.chk_clean.isVisibleTo(self.dialog))

    def test_disc_title_choice_is_stored_and_undoable(self):
        """Häkchen „Disc-Titel im Player anzeigen“, ab v1.11.2 standardmäßig an; Ausschalten landet im Export."""
        self.assertTrue(self.dialog.chk_disc_title.isChecked())
        self.dialog.chk_disc_title.setChecked(False)
        self.assertFalse(self.ctrl.project.settings.disc_title_meta)
        from core.disc_adapter import build_export_plan
        self.assertFalse(build_export_plan(self.ctrl.project).project_state.disc_title_meta)
        self.ctrl.undo_stack.undo()
        app_instance.processEvents()
        self.assertTrue(self.ctrl.project.settings.disc_title_meta)
        self.assertTrue(self.dialog.chk_disc_title.isChecked())

    def test_export_passes_graph_pages(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ctrl.set_settings("Ziel", output_path=os.path.join(tmp.name, "ziel"))
        captured = {}

        from tests.test_bdsim import build_test_disc, main_and_extras_pages
        disc_root = build_test_disc(os.path.join(tmp.name, "fertig"), main_and_extras_pages(), num_titles=3)

        def fake_export(project_state, log, progress, pages_specs=None, on_disc_ready=None):
            captured["state"], captured["pages"] = project_state, pages_specs
            log("läuft")
            on_disc_ready(disc_root)
            return True, "ok"

        self.assertFalse(self.dialog.btn_simulate.isVisibleTo(self.dialog))
        with mock.patch("modules.disc_export.export_disc", side_effect=fake_export):
            self.dialog.start_export()
            self.dialog.thread.wait()
            app_instance.processEvents()
        self.assertEqual(captured["pages"][0][1][0].text, "FILM STARTEN")
        self.assertTrue(captured["state"].enable_menu)
        log_text = self.dialog.log_view.toPlainText()
        self.assertIn("läuft", log_text)
        self.assertIn("Simulator: 0 Fehler, 0 Warnungen", log_text)
        self.assertTrue(self.dialog.btn_start.isEnabled())
        # Nach dem Export lässt sich die Disc im Simulator öffnen
        self.assertTrue(self.dialog.btn_simulate.isVisibleTo(self.dialog))
        self.dialog.open_simulator()
        self.assertEqual(self.dialog._sim_window.player.state, "menu")
        self.dialog._sim_window.close()


if __name__ == "__main__":
    unittest.main()
