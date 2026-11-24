"""
UHD-Plan, Weg B: fertiger HEVC-Strom direkt in einen Film-Knoten.
- Prüfung mit hevctools in eigenem Prozess: Fehler als nicht bestätigbarer Hinweis (Vorprüfung blockiert),
  Warnungen bestätigbar, Abbruch als Hinweis „nicht geprüft“; Dauer und Dynamikbereich in den Kenndaten
- Ergebnisse aus Vorbereiten werden beim Übernehmen nicht ein zweites Mal geprüft
- Vorprüfung: verschiedene Dynamikbereiche auf einer UHD-Disc vorerst ein Fehler (bis Phase 0.9)
"""

import os
import shutil
import tempfile
import unittest
from unittest import mock

from core import preflight
from core.disc_edit import starter_project
from core.translations import tr
from modules.prepare import tasks
from modules.prepare.checks import check_hevc, hevc_unchecked_warning
from tests.prepare_util import make_hevc, needs_x265, setUpModule, tearDownModule  # noqa: F401
from tests.test_menu_designer import app_instance


class Preflight(unittest.TestCase):
    def test_mixed_dynamic_range_on_uhd(self):
        project = starter_project()
        project.settings.disc_type = "uhd"
        film = project.films[0]
        film.video_base, film.video_details = "a_2160p.hevc", {"dynamic_range": "hdr10"}
        from core.disc_edit import add_film
        other = add_film(project, "Extra", (700.0, 300.0))
        other.video_base, other.video_details = "b_1080p.hevc", {"dynamic_range": "sdr709"}
        errors = [i.message for i in preflight.run_preflight(project, check_files=False)
                  if i.level == preflight.ERROR]
        self.assertTrue(any("HDR10" in e and "SDR BT.709" in e for e in errors), errors)
        other.video_details = {"dynamic_range": "hdr10"}
        errors = [i.message for i in preflight.run_preflight(project, check_files=False)
                  if i.level == preflight.ERROR]
        self.assertFalse(any("HDR10" in e and "SDR BT.709" in e for e in errors))

    def test_unchecked_warning(self):
        w = hevc_unchecked_warning("abgebrochen")
        self.assertEqual((w["code"], w["severity"]), ("HEVC_UNCHECKED", "warning"))


@needs_x265
class Import(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="hevc_import_")
        cls.good = os.path.join(cls.dir, "Gut_2160p.hevc")
        make_hevc(cls.good, seconds=0.3, size="3840x2160", colour="hdr10")
        cls.bad = os.path.join(cls.dir, "Ohne Regeln.hevc")
        make_hevc(cls.bad, seconds=0.3, uhd_bd=False)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        from gui.studio.main_window import StudioWindow
        self.win = StudioWindow(persist_layout=False)
        self.ctrl = self.win.controller
        self.importer = self.win.importer
        self.ctrl.set_settings("Disc-Typ ändern", disc_type="uhd")
        # Hinweise öffnen sonst das (modale) Fenster mit den Kompatibilitätshinweisen
        patcher = mock.patch("gui.widgets.compliance_dialog.ComplianceWarningDialog.exec", return_value=0)
        self.dialog = patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.ctrl.undo_stack.setClean()
        self.win.close()

    def test_check_function(self):
        good = check_hevc(self.good)
        self.assertEqual(good["warnings"], [])
        self.assertEqual(good["details"]["dynamic_range"], "hdr10")
        self.assertAlmostEqual(good["details"]["duration_s"], 0.3, delta=0.05)
        bad = check_hevc(self.bad)
        (warning,) = [w for w in bad["warnings"] if w["severity"] == "error"]
        self.assertEqual(warning["code"], "HEVC_UHD_ERROR")
        self.assertIn("Access Unit Delimiter", warning["message"])

    def test_bad_stream_blocks_preflight(self):
        film_id = self.importer.import_files(None, [self.bad])            # Prüfung im eigenen Prozess
        film = self.ctrl.project.film(film_id)
        self.assertTrue(any(w["severity"] == "error" for w in film.compliance_warnings))
        self.assertTrue(self.dialog.called)                               # der Hinweis wird gezeigt
        errors = [i for i in preflight.run_preflight(self.ctrl.project, check_files=False)
                  if i.level == preflight.ERROR and i.node_id == film_id]
        self.assertTrue(errors)

    def test_good_stream_and_details(self):
        film_id = self.importer.import_files(None, [self.good])
        film = self.ctrl.project.film(film_id)
        self.assertEqual(film.compliance_warnings, [])
        self.assertEqual(film.video_details["dynamic_range"], "hdr10")
        self.assertIn("duration_s", film.video_details)

    def test_cancelled_check(self):
        self.importer.check_hevc = lambda path: {"warnings": [hevc_unchecked_warning(tr("cw_check_cancelled"))]}
        film_id = self.importer.import_files(None, [self.good])
        (warning,) = self.ctrl.project.film(film_id).compliance_warnings
        self.assertEqual(warning["code"], "HEVC_UNCHECKED")

    def test_prepare_results_are_not_checked_twice(self):
        calls = []
        self.importer.check_hevc = lambda path: calls.append(path) or {"warnings": []}
        task = tasks.PrepareTask(id="t1", source=self.good, kind=tasks.KIND_UHD, status=tasks.DONE,
                                 outputs=[self.good])
        self.win.prepare_page.take_over([task], None)
        app_instance.processEvents()
        self.assertEqual(calls, [])
        self.assertTrue(any(f.video_base == self.good for f in self.ctrl.project.films))
        with mock.patch("os.stat", side_effect=OSError):                  # Datei verändert/unlesbar: wieder prüfen
            self.assertFalse(self.importer._already_checked(self.good))
        self.importer.import_files(None, [self.bad])
        self.assertEqual(calls, [self.bad])


if __name__ == "__main__":
    unittest.main()
