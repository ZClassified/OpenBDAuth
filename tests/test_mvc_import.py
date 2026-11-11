# tests/test_mvc_import.py
"""
3D-Paar beim Import prüfen (v1.21): Basis-Video und MVC müssen Bild für Bild zusammenpassen (mvctools.verify,
in einem eigenen Prozess mit Fortschritt und Abbrechen). Ein Paar, das nicht passt, ist ein Fehler im Preflight,
der sich nicht bestätigen lässt; ein ungewöhnliches 3D-Format nur ein Hinweis.
"""

import os
import shutil
import tempfile
import time
import unittest

from core.disc_edit import starter_project
from core.preflight import run_preflight, ERROR, WARNING
from gui.node_editor.controller import GraphController
from gui.studio.importer import FilmImporter
from modules.prepare.background import BackgroundTask
from modules.prepare.checks import check_pair, stereo_format_warnings, unchecked_warning
from mvctools.rewrite import MvcRewriter
from tests.prepare_util import make_h264, needs_ffmpeg
from tests.test_menu_designer import app_instance

DETAILS_3D = {"width": 1920, "height": 1080, "fps": 23.976, "warnings": []}


def wait(task: BackgroundTask, seconds: float = 60.0) -> BackgroundTask:
    end = time.time() + seconds
    while not task.poll():
        if time.time() > end:
            task.cancel()
            raise AssertionError("BackgroundTask wurde nicht fertig")
        time.sleep(0.05)
    return task


def _slow(seconds, progress=None):
    """Für den Abbruch-Test (Modulebene, damit der Prozess sie bekommt)."""
    progress(0.5)
    time.sleep(seconds)
    return "fertig"


class TestFormat(unittest.TestCase):
    def test_bluray_3d_formats_pass(self):
        self.assertEqual(stereo_format_warnings(DETAILS_3D), [])
        self.assertEqual(stereo_format_warnings(dict(DETAILS_3D, fps=24.0)), [])
        self.assertEqual(stereo_format_warnings({"width": 1280, "height": 720, "fps": 50.0}), [])

    def test_other_formats_are_a_hint(self):
        (w,) = stereo_format_warnings(dict(DETAILS_3D, fps=25.0))
        self.assertEqual((w["code"], w["severity"]), ("STEREO_FORMAT", "warning"))
        self.assertTrue(stereo_format_warnings({"width": 1920, "height": 2160, "fps": 23.976}))

    def test_unknown_is_skipped(self):
        self.assertEqual(stereo_format_warnings({"width": 0, "height": 0}), [])
        self.assertEqual(stereo_format_warnings(None), [])


@needs_ffmpeg
class TestPair(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="openbdauth_mvc_")
        cls.left = os.path.join(cls.dir, "film_3D.264")
        right = os.path.join(cls.dir, "right.264")
        cls.mvc = os.path.join(cls.dir, "film_3D.mvc")
        cls.other = os.path.join(cls.dir, "other.264")
        make_h264(cls.left, seconds=2.0, keyint=12)
        make_h264(right, seconds=2.0, keyint=12, pattern="smptehdbars")
        make_h264(cls.other, seconds=2.0, keyint=8)
        MvcRewriter().run(right, cls.mvc)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_matching_pair(self):
        shares = []
        self.assertEqual(check_pair(self.left, self.mvc, progress=shares.append), [])
        self.assertTrue(all(0.0 <= s <= 1.0 for s in shares))

    def test_mismatch_is_an_error(self):
        (w,) = check_pair(self.other, self.mvc)
        self.assertEqual((w["code"], w["severity"]), ("MVC_PAIR_MISMATCH", "error"))
        self.assertIn("passen nicht zusammen", w["message"])

    def test_in_own_process(self):
        task = wait(BackgroundTask(check_pair, self.other, self.mvc))
        self.assertIsNone(task.error)
        self.assertEqual([w["code"] for w in task.result], ["MVC_PAIR_MISMATCH"])

    def test_importer_dialog(self):
        """Echter Ablauf im Importer: Prozess, Fortschrittsfenster, Ergebnis im selben Schritt wie die Datei."""
        ctrl = GraphController(starter_project())
        importer = FilmImporter(ctrl, lambda: "deu")
        importer.probe = lambda path, is_3d: dict(DETAILS_3D)
        film_id = ctrl.project.films[0].id
        importer.import_files(film_id, [self.other, self.mvc])
        film = ctrl.project.film(film_id)
        self.assertEqual([w["code"] for w in film.compliance_warnings], ["MVC_PAIR_MISMATCH"])
        ctrl.undo_stack.undo()
        self.assertEqual(ctrl.project.film(film_id).compliance_warnings, [])
        importer.set_video(film_id, self.left)
        self.assertEqual(ctrl.project.film(film_id).compliance_warnings, [])
        app_instance.processEvents()


class TestBackgroundTask(unittest.TestCase):
    def test_error_comes_back_as_message(self):
        task = wait(BackgroundTask(check_pair, "fehlt.264", "fehlt.mvc"))
        self.assertIsNone(task.result)
        self.assertIn("FileNotFoundError", task.error)

    def test_cancel(self):
        task = BackgroundTask(_slow, 30)
        end = time.time() + 30
        while task.progress < 0.5 and time.time() < end:
            task.poll()
            time.sleep(0.05)
        task.cancel()
        self.assertTrue(task.finished and task.cancelled)
        self.assertIsNone(task.error)


class TestImporter(unittest.TestCase):
    def setUp(self):
        self.ctrl = GraphController(starter_project())
        self.importer = FilmImporter(self.ctrl, lambda: "deu")
        self.importer.probe = lambda path, is_3d: dict(DETAILS_3D)
        self.calls = []
        self.film_id = self.ctrl.project.films[0].id

    def _check(self, result):
        def check(base, mvc):
            self.calls.append((base, mvc))
            return result
        self.importer.check_pair = check

    def test_pair_checked_once_both_are_there(self):
        self._check([])
        self.importer.import_files(self.film_id, ["C:/v/film.264", "C:/v/film.mvc"])
        self.assertEqual(self.calls, [("C:/v/film.264", "C:/v/film.mvc")])     # MVC zuerst: noch kein Basis-Video
        self.importer.set_mvc(self.film_id, None)
        self.assertEqual(len(self.calls), 1)                                    # 2D: keine Prüfung

    def test_2d_film_is_not_checked(self):
        self._check([])
        self.importer.set_video(self.film_id, "C:/v/film.264")
        self.assertEqual(self.calls, [])

    def test_cancelled_check_is_a_confirmable_hint(self):
        self._check([unchecked_warning("Die Prüfung wurde abgebrochen.")])
        self.importer.import_files(self.film_id, ["C:/v/film.264", "C:/v/film.mvc"])
        film = self.ctrl.project.film(self.film_id)
        film.warnings_acknowledged = True
        self.assertFalse([i for i in run_preflight(self.ctrl.project, check_files=False)
                          if i.node_id == self.film_id and i.level in (ERROR, WARNING)])


class TestPreflight(unittest.TestCase):
    def test_errors_cannot_be_acknowledged(self):
        project = starter_project()
        film = project.films[0]
        film.video_base = "film.264"
        film.compliance_warnings = [{"code": "MVC_PAIR_MISMATCH", "title": "3D-Video und MVC passen nicht zusammen",
                                     "message": "Bildanzahl unterschiedlich", "severity": "error"},
                                    {"code": "STEREO_FORMAT", "title": "x", "message": "y", "severity": "warning"}]
        issues = [(i.level, i.message) for i in run_preflight(project, check_files=False) if i.node_id == film.id]
        self.assertIn(ERROR, [lvl for lvl, _ in issues])
        self.assertTrue(any("1 Kompatibilitätshinweis" in m for _, m in issues))
        film.warnings_acknowledged = True
        issues = [(i.level, i.message) for i in run_preflight(project, check_files=False) if i.node_id == film.id]
        self.assertEqual([lvl for lvl, _ in issues], [ERROR])


if __name__ == "__main__":
    unittest.main()
