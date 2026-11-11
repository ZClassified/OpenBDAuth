# tests/test_export_next_step.py
"""Nach dem Export (v1.30.3): Der nächste Schritt ist die Hauptaktion – „Zum Brennen ▸“ nach einer ISO, „Fertig“ nach
einem BDMV-Ordner; „Erneut exportieren“ wird grau. Ändert sich das Projekt, ist wieder „Export starten“ dran."""

import os
import shutil
import sys
import tempfile
import time
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from core.translations import tr

app_instance = QApplication.instance() or QApplication(sys.argv)


class TestExportNextStep(unittest.TestCase):
    def setUp(self):
        from gui.node_editor.controller import GraphController
        from gui.studio.export_dialog import ExportDialog
        from tests.project_factory import text_starter
        self.dest = tempfile.mkdtemp(prefix="export_next_")
        self.addCleanup(shutil.rmtree, self.dest, True)
        project = text_starter()
        project.settings.output_path = self.dest
        project.settings.export_format = "iso"
        self.controller = GraphController(project)
        self.dialog = ExportDialog(self.controller)
        self.dialog._blocked_by_errors = False
        self.addCleanup(self.dialog.close)
        self.burned = []
        self.dialog.burn_iso.connect(self.burned.append)

    def finish(self, kind: str, ok: bool = True, write_iso: bool = True):
        """Wie ein echter Export: Aktivität starten, Ergebnis schreiben, _on_done."""
        d = self.dialog
        d._export_kind = kind
        d._export_dest = self.dest
        d._start_activity(self.dest)
        if kind == "iso" and write_iso:
            with open(os.path.join(self.dest, "MY_DISC.iso"), "wb") as f:
                f.write(b"\0" * 2 * 1024 ** 2)
        d._on_done(ok, "" if ok else "kaputt")

    def primary(self, button) -> bool:
        return button.objectName() == "primary_btn"

    def test_before_export_start_is_primary(self):
        d = self.dialog
        d._update_start_button()
        self.assertTrue(self.primary(d.btn_start))
        self.assertEqual(d.btn_start.text(), tr("btn_start_export", "de"))
        self.assertFalse(d.btn_burn.isVisibleTo(d))
        self.assertFalse(d.btn_done.isVisibleTo(d))

    def test_after_iso_burn_is_primary(self):
        d = self.dialog
        self.finish("iso")
        self.assertTrue(d.result_is_current())
        self.assertTrue(d.btn_burn.isVisibleTo(d))
        self.assertTrue(self.primary(d.btn_burn))
        self.assertFalse(self.primary(d.btn_start))
        self.assertEqual(d.btn_start.text(), tr("export_again", "de"))
        self.assertTrue(d.btn_start.icon().isNull())
        self.assertIn("MY_DISC.iso", d.lbl_hint.text())
        self.assertIn("2 MB", d.lbl_hint.text())
        d.btn_burn.click()
        self.assertEqual(self.burned, [os.path.join(self.dest, "MY_DISC.iso")])

    def test_burn_button_is_rightmost(self):
        d = self.dialog
        layout = d.btn_start.parentWidget().layout()
        row = next(l for l in layout.children() if l.indexOf(d.btn_start) >= 0)
        self.assertGreater(row.indexOf(d.btn_burn), row.indexOf(d.btn_start))
        self.assertGreater(row.indexOf(d.btn_start), row.indexOf(d.btn_close))

    def test_after_folder_done_is_primary(self):
        d = self.dialog
        self.finish("folder")
        self.assertTrue(d.btn_done.isVisibleTo(d))
        self.assertTrue(self.primary(d.btn_done))
        self.assertFalse(d.btn_close.isVisibleTo(d))
        self.assertFalse(d.btn_burn.isVisibleTo(d))
        self.assertFalse(self.primary(d.btn_start))
        self.assertIn(self.dest, d.lbl_hint.text())

    def test_project_change_brings_export_back(self):
        d = self.dialog
        self.finish("iso")
        self.controller.set_settings("Exportformat ändern", export_format="folder")
        self.assertFalse(d.result_is_current())
        self.assertTrue(self.primary(d.btn_start))
        self.assertEqual(d.btn_start.text(), tr("btn_start_export", "de"))
        self.assertFalse(d.btn_burn.isVisibleTo(d))
        self.assertNotIn("MY_DISC", d.lbl_hint.text())
        self.controller.undo_stack.undo()              # zurück zum exportierten Stand: ISO gilt wieder
        self.assertTrue(d.result_is_current())
        self.assertTrue(self.primary(d.btn_burn))

    def test_merged_steps_count_as_change(self):
        """Mehrere gleiche Änderungen hintereinander sind ein Rückgängig-Schritt – trotzdem gilt die ISO nicht mehr."""
        d = self.dialog
        film_id = self.controller.project.films[0].id
        self.controller.execute("Name", lambda p: setattr(p.film(film_id), "name", "A"), merge_key=("t",))
        self.finish("iso")
        index = self.controller.undo_stack.index()
        self.controller.execute("Name", lambda p: setattr(p.film(film_id), "name", "B"), merge_key=("t",))
        self.assertEqual(self.controller.undo_stack.index(), index)     # zusammengefasst
        self.assertFalse(d.result_is_current())

    def test_moving_nodes_keeps_result(self):
        d = self.dialog
        self.finish("iso")
        film_id = self.controller.project.films[0].id
        self.controller.move_nodes({film_id: (123.0, 456.0)})
        self.assertTrue(d.result_is_current())
        self.assertTrue(self.primary(d.btn_burn))

    def test_failed_export_keeps_export_primary(self):
        d = self.dialog
        self.finish("iso", ok=False)
        self.assertFalse(d.result_is_current())
        self.assertTrue(self.primary(d.btn_start))
        self.assertFalse(d.btn_burn.isVisibleTo(d))

    def test_iso_not_found_keeps_export_primary(self):
        d = self.dialog
        self.finish("iso", write_iso=False)
        self.assertFalse(d.result_is_current())
        self.assertFalse(d.btn_burn.isVisibleTo(d))

    def test_other_project_is_not_current(self):
        from tests.project_factory import text_starter
        d = self.dialog
        self.finish("iso")
        self.controller.set_project(text_starter())
        self.controller.changed.emit()
        self.assertFalse(d.result_is_current())


if __name__ == "__main__":
    unittest.main()
