# tests/test_prepare_page.py
"""
Arbeitsbereich Vorbereiten im Studio (v1.22, Warteschlange v1.23): Seitenwechsel Vorbereiten | Disc, Aufträge
anlegen und festlegen (Markierung links), „Starten“ arbeitet alle wartenden Aufträge nacheinander im eigenen
Prozess ab, fertige Dateien kommen per Klick über den bestehenden Import in einen Film-Knoten.
Die Seite ändert das Disc-Projekt nie von selbst.
"""

import os
import shutil
import tempfile
import unittest
from unittest import mock

from PySide6.QtWidgets import QMessageBox

from modules.prepare import jobs, tasks
from tests.prepare_util import ffmpeg, needs_ffmpeg, setUpModule, tearDownModule  # noqa: F401
from tests.test_menu_designer import app_instance


@needs_ffmpeg
class PrepareCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media = tempfile.mkdtemp(prefix="openbdauth_page_")
        cls.video = os.path.join(cls.media, "Trailer.mp4")
        cls.long_video = os.path.join(cls.media, "Lang.mp4")
        cls.wav = os.path.join(cls.media, "Mix.wav")
        ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=1280x720:r=24:d=1', '-pix_fmt', 'yuv420p', '-c:v', 'libx264',
               '-preset', 'ultrafast', cls.video)
        ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=1920x1080:r=24:d=40', '-pix_fmt', 'yuv420p', '-c:v', 'libx264',
               '-preset', 'ultrafast', cls.long_video)
        ffmpeg('-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=1', '-ac', '2', cls.wav)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.media, ignore_errors=True)

    def setUp(self):
        from gui.studio.main_window import StudioWindow
        self.win = StudioWindow(persist_layout=False)
        self.win.resize(1400, 900)
        self.win.show()
        self.page = self.win.prepare_page
        self.ctrl = self.win.controller
        self.warnings, self.messages = [], []
        self.page.status.connect(self.messages.append)
        patcher = mock.patch.object(QMessageBox, "warning", side_effect=lambda *a: self.warnings.append(a[2]))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.page.confirm_unconfirmed = lambda unconfirmed: True

    def tearDown(self):
        self.page.stop_queue()
        self.page.wait_until_finished(30)
        shutil.rmtree(os.path.join(self.media, tasks.OUT_DIR_NAME), ignore_errors=True)
        self.ctrl.undo_stack.setClean()
        self.win.close()

    def run_queue(self):
        self.assertTrue(self.page.start_queue())
        self.assertTrue(self.page.wait_until_finished(120))
        app_instance.processEvents()


class TestPages(PrepareCase):
    def test_switch_hides_disc_actions(self):
        self.assertTrue(self.win.act_build.isVisible())
        self.assertFalse(self.page.act_start.isVisible())
        self.win.show_page("prepare")
        self.assertIs(self.win.pages.currentWidget(), self.page)
        self.assertFalse(self.win.act_build.isVisible())
        self.assertFalse(self.win.act_undo.isVisible())        # Strg+Z ändert dort nicht unsichtbar den Graphen
        self.assertFalse(self.win.dock_inspector.isVisible())
        self.assertTrue(self.page.act_start.isVisible())
        self.win.show_page("disc")
        self.assertTrue(self.win.dock_inspector.isVisible() and self.win.act_build.isVisible())


class TestDecided(PrepareCase):
    """Links in der Liste: Ring = Einstellungen noch offen, Haken = festgelegt (Wunsch 2026-10-23)."""

    def test_change_or_confirm_marks_decided(self):
        a, b = self.page.add_files([self.video, self.wav])
        self.assertFalse(a.confirmed or b.confirmed)
        self.assertIn("2 von 2", self.page.lbl_open.text())
        self.page._select(a)
        self.page.inspector.combo_bitrate.setCurrentIndex(self.page.inspector.combo_bitrate.findData(15))
        self.page.inspector.combo_bitrate.activated.emit(0)
        self.assertEqual((a.bitrate_2d, a.confirmed), (15, True))
        self.assertIn("1 von 2", self.page.lbl_open.text())
        self.page._select(b)
        self.assertTrue(self.page.inspector.btn_confirm.isVisibleTo(self.page.inspector))
        self.page.inspector.btn_confirm.click()
        self.assertTrue(b.confirmed)
        self.assertFalse(self.page.inspector.btn_confirm.isVisibleTo(self.page.inspector))
        self.assertEqual(self.page.lbl_open.text(), "Alle Einstellungen festgelegt")

    def test_start_asks_once_for_open_settings(self):
        a, b = self.page.add_files([self.video, self.wav])
        asked = []
        self.page.confirm_unconfirmed = lambda unconfirmed: asked.append([t.name for t in unconfirmed]) or False
        self.assertFalse(self.page.start_queue())
        self.assertEqual(asked, [["Trailer.mp4", "Mix.wav"]])
        a.confirmed = b.confirmed = True
        self.run_queue()
        self.assertEqual(len(asked), 1)

    def test_multi_selection_sets_all(self):
        a, b = self.page.add_files([self.video, self.long_video])     # beide markiert
        self.assertEqual(self.page.inspector.selection, [a, b])
        inspector = self.page.inspector
        inspector.combo_bitrate.setCurrentIndex(inspector.combo_bitrate.findData(25))
        inspector.combo_bitrate.activated.emit(0)
        self.assertEqual((a.bitrate_2d, b.bitrate_2d, a.confirmed, b.confirmed), (25, 25, True, True))


class TestQueue(PrepareCase):
    def test_all_waiting_jobs_in_order(self):
        self.page.add_files([self.video, self.wav])
        self.run_queue()
        self.assertEqual([t.status for t in self.page.tasks], [tasks.DONE, tasks.DONE])
        self.assertIn("2 fertig", self.messages[-1])
        self.assertFalse(self.page.act_cancel.isEnabled())

    def test_stop_keeps_the_rest_waiting(self):
        long_task, short_task = self.page.add_files([self.long_video, self.video])
        self.assertTrue(self.page.start_queue())
        self.page.stop_queue()
        self.assertTrue(self.page.wait_until_finished(60))
        self.assertEqual((long_task.status, short_task.status), (tasks.CANCELLED, tasks.WAITING))

    def test_cancelling_one_job_continues_with_the_next(self):
        long_task, short_task = self.page.add_files([self.long_video, self.video])
        self.assertTrue(self.page.start_queue())
        self.page._select(long_task)
        self.page.cancel_selected_task()
        self.assertTrue(self.page.wait_until_finished(120))
        self.assertEqual((long_task.status, short_task.status), (tasks.CANCELLED, tasks.DONE))
        self.assertEqual(os.listdir(os.path.join(self.media, tasks.OUT_DIR_NAME)), ["Trailer.264"])

    def test_requeue(self):
        long_task, = self.page.add_files([self.long_video])
        self.page.start_queue()
        self.page.stop_queue()
        self.page.wait_until_finished(60)
        self.page._select(long_task)
        self.page.requeue_selected()
        self.assertEqual(long_task.status, tasks.WAITING)

    def test_reorder_changes_queue_order(self):
        a, b = self.page.add_files([self.video, self.wav])
        item = self.page.list.takeTopLevelItem(1)
        self.page.list.insertTopLevelItem(0, item)
        self.page._on_reordered()
        self.assertEqual(self.page.tasks, [b, a])

    def test_common_folder_and_duplicate_names(self):
        common = tempfile.mkdtemp(prefix="openbdauth_common_")
        self.addCleanup(shutil.rmtree, common, True)
        other_dir = tempfile.mkdtemp(prefix="openbdauth_other_")
        self.addCleanup(shutil.rmtree, other_dir, True)
        twin = os.path.join(other_dir, "Trailer.mp4")
        shutil.copy(self.video, twin)
        self.page.set_common_dir(common)
        a, b = self.page.add_files([self.video, twin])
        self.assertEqual((a.out_dir, b.out_dir), (common, common))
        self.assertFalse(self.page.start_queue())                         # beide schrieben Trailer.264
        self.assertIn("Trailer.264", self.warnings[-1])
        self.page.set_common_dir(None)
        self.assertEqual(a.out_dir, os.path.join(self.media, tasks.OUT_DIR_NAME))

    def test_file_used_by_project_is_not_replaced(self):
        (task,) = self.page.add_files([self.video])
        self.ctrl.project.films[0].video_base = tasks.planned_outputs(task)[0]
        self.assertFalse(self.page.start_queue())
        self.assertTrue(self.warnings)
        self.assertEqual(task.status, tasks.WAITING)

    def test_existing_output_needs_confirmation(self):
        (task,) = self.page.add_files([self.video])
        target = tasks.planned_outputs(task)[0]
        os.makedirs(os.path.dirname(target), exist_ok=True)
        open(target, "wb").close()
        self.page.confirm_overwrite = lambda existing: False
        self.assertFalse(self.page.start_queue())
        self.page.confirm_overwrite = lambda existing: True
        self.run_queue()
        self.assertEqual(task.status, tasks.DONE)
        self.assertGreater(os.path.getsize(target), 0)

    def test_disc_gauge(self):
        (task,) = self.page.add_files([self.long_video])
        self.assertEqual(self.page.disc_bytes(), tasks.estimated_size(task))
        self.assertGreater(tasks.estimated_size(task), 40 * 19 * 125_000)
        self.assertIn("von 25,0 GB", self.page.gauge.text())                # dezimal (v1.30.4)
        self.assertFalse(self.page.gauge.isTextVisible())                  # v1.30.1: Text neben dem Balken
        self.assertEqual(self.page.lbl_gauge.text(), self.page.gauge.text())

    def test_unsuitable_source_is_not_added(self):
        handy = os.path.join(self.media, "Handy.mp4")
        ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=1280x720:r=12:d=1', '-pix_fmt', 'yuv420p', '-c:v', 'libx264',
               '-preset', 'ultrafast', handy)
        self.assertEqual(self.page.add_files([handy]), [])
        self.assertEqual(self.page.tasks, [])
        self.assertIn("Handy.mp4", self.warnings[0])

    def test_ffprobe_message_is_shown(self):
        failure = jobs.ProbeError("/media/film.mkv", "Permission denied")
        with mock.patch.object(tasks, "create_task", side_effect=failure):
            self.assertEqual(self.page.add_files(["/media/film.mkv"]), [])
        self.assertIn("film.mkv", self.warnings[0])
        self.assertIn("Permission denied", self.warnings[0])
        self.assertNotIn("weder Bild noch Ton", self.warnings[0])

    def test_ffprobe_not_starting_is_shown(self):
        missing = FileNotFoundError(2, "No such file or directory", "/opt/OpenBDAuth/tools/linux/ffprobe")
        with mock.patch.object(tasks, "create_task", side_effect=missing):
            self.assertEqual(self.page.add_files(["/media/film.mkv"]), [])
        self.assertIn("film.mkv", self.warnings[0])
        self.assertIn("No such file or directory", self.warnings[0])
        self.assertIn("/opt/OpenBDAuth/tools/linux/ffprobe", self.warnings[0])
        self.assertEqual(self.page.tasks, [])

    def test_hint_when_video_has_audio(self):
        """v1.29.1: Der Ton im Video wird bewusst nicht übernommen – ein Hinweis, nur wenn die Datei Ton hat."""
        with_audio = os.path.join(self.media, "MitTon.mp4")
        ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=1280x720:r=24:d=1', '-f', 'lavfi', '-i', 'sine=d=1',
               '-pix_fmt', 'yuv420p', '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac', '-shortest',
               with_audio)
        silent, loud = self.page.add_files([self.video, with_audio])
        hint = self.page.inspector.lbl_no_audio
        self.page._select(silent)
        self.assertFalse(hint.isVisibleTo(self.page.inspector))
        self.page._select(loud)
        self.assertTrue(hint.isVisibleTo(self.page.inspector))
        self.assertIn("eigene Datei", hint.text())
        self.assertEqual([t.kind for t in self.page.tasks], [tasks.KIND_2D, tasks.KIND_2D])   # kein Ton-Auftrag

    def test_remove_selected(self):
        a, b = self.page.add_files([self.video, self.wav])
        self.page._select(b)
        self.page.remove_selected()
        self.assertEqual(self.page.tasks, [a])


class TestTakeOver(PrepareCase):
    def test_encode_and_take_over_into_new_film(self):
        self.win.show_page("prepare")
        (task,) = self.page.add_files([self.video])
        films_before = [f.id for f in self.ctrl.project.films]
        self.run_queue()
        self.assertEqual(task.status, tasks.DONE, task.error)
        self.assertEqual([f.id for f in self.ctrl.project.films], films_before)   # nichts von selbst übernommen
        self.page.take_over([task], None)
        film = self.ctrl.project.films[-1]
        self.assertEqual((film.name, film.video_base), ("Trailer", task.outputs[0]))
        self.ctrl.undo_stack.undo()                                               # ein Schritt
        self.assertEqual([f.id for f in self.ctrl.project.films], films_before)

    def test_video_and_audio_together(self):
        video_task, audio_task = self.page.add_files([self.video, self.wav])
        self.run_queue()
        self.page.take_over([video_task, audio_task], None)
        self.page.importer.wait_for_workers()
        app_instance.processEvents()
        film = self.ctrl.project.films[-1]
        self.assertEqual(os.path.basename(film.video_base), "Trailer.264")
        self.assertEqual([os.path.basename(t.path) for t in film.audio_tracks], ["Mix.ac3"])

    def test_two_videos_are_not_taken_over_at_once(self):
        a, b = self.page.add_files([self.video, self.long_video])
        a.status = b.status = tasks.DONE
        self.page.inspector.show_tasks([a, b])
        self.assertFalse(self.page.inspector.btn_take.isEnabled())

    def test_audio_into_existing_film_by_suggestion(self):
        (task,) = self.page.add_files([self.wav])
        film = self.ctrl.project.films[0]
        task.target_film_id = film.id
        self.run_queue()
        self.page._select(task)
        self.assertEqual(self.page.inspector.combo_take.currentData(), film.id)    # Vorschlag vorausgewählt
        self.page.take_over([task], film.id)
        self.page.importer.wait_for_workers()
        app_instance.processEvents()
        self.assertEqual([os.path.basename(t.path) for t in self.ctrl.project.film(film.id).audio_tracks],
                         ["Mix.ac3"])


class TestFrameRateOptions(PrepareCase):
    """25 fps und 30/60 fps: je zwei sichtbare Optionen statt eines Häkchens (v1.24)."""

    def _source(self, name, rate, size="1920x1080"):
        path = os.path.join(self.media, name)
        ffmpeg('-f', 'lavfi', '-i', f'testsrc2=s={size}:r={rate}:d=1', '-pix_fmt', 'yuv420p', '-c:v', 'libx264',
               '-preset', 'ultrafast', path)
        (task,) = self.page.add_files([path])
        return task, self.page.inspector

    def test_25p(self):
        task, inspector = self._source("PAL.mp4", 25)
        self.assertTrue(inspector.row_25p.isVisibleTo(inspector))
        self.assertEqual(inspector.switch_25p.value(), "psf")
        self.assertIn("Standard", inspector.lbl_25p_hint.text())
        inspector.switch_25p.buttons["p"].click()
        self.assertEqual((task.psf_25, task.confirmed), (False, True))
        self.assertIn("nicht Teil des Blu-ray-Standards", inspector.lbl_25p_hint.text())

    def test_30_fps_is_always_adapted_with_clear_warning(self):
        task, inspector = self._source("NTSC.mp4", 30)
        self.assertFalse(inspector.row_25p.isVisibleTo(inspector))
        self.assertTrue(inspector.row_conform.isVisibleTo(inspector))
        self.assertEqual(inspector.lbl_conform_value.text(), "30 → 29,97 fps (wird angepasst)")
        warning = inspector.lbl_conform_hint.text()
        self.assertIn("ruckeln", warning)
        self.assertIn("alle 33 Sekunden", warning)
        self.assertIn("29,97 fps exportieren", inspector.lbl_conform_tip.text())
        self.assertTrue(inspector.lbl_ntsc_hint.isVisibleTo(inspector))
        self.assertTrue(any("fps=30000/1001" in " ".join(s.cmd) for s in tasks.build_job(task).steps if s.cmd))

    def test_24p_has_neither(self):
        task, inspector = self._source("Kino.mp4", 24)
        self.assertFalse(inspector.row_25p.isVisibleTo(inspector))
        self.assertFalse(inspector.row_conform.isVisibleTo(inspector))


class TestNewFilmNode(PrepareCase):
    """„Für Film“ → „Neuer Film-Knoten …“: leerer Film-Knoten sofort, Datei erst per Übernehmen (v1.24)."""

    def test_create_and_take_over(self):
        (task,) = self.page.add_files([self.video])
        self.page.ask_film_name = lambda default: (self.assertEqual(default, "Trailer"), "Trailer")[1]
        combo = self.page.inspector.combo_suggest
        combo.setCurrentIndex(combo.findData("__new_film__"))
        combo.activated.emit(combo.currentIndex())
        film = self.ctrl.project.film(task.target_film_id)
        self.assertEqual((film.name, film.video_base, task.confirmed), ("Trailer", None, True))
        self.assertEqual(combo.currentData(), film.id)
        self.run_queue()
        self.page._select(task)
        self.assertEqual(self.page.inspector.combo_take.currentData(), film.id)
        self.page.take_over([task], film.id)
        self.assertEqual(os.path.basename(self.ctrl.project.film(film.id).video_base), "Trailer.264")

    def test_undo_removes_the_empty_node(self):
        (task,) = self.page.add_files([self.video])
        self.page.ask_film_name = lambda default: "Extra"
        film_id = self.page.create_film_for([task])
        self.ctrl.undo_stack.undo()
        self.assertIsNone(self.ctrl.project.film(film_id))
        self.page.inspector.refresh()
        self.assertEqual(self.page.inspector.combo_suggest.currentData(), "")      # wieder „– offen –“

    def test_cancelled_name_creates_nothing(self):
        (task,) = self.page.add_files([self.video])
        films = len(self.ctrl.project.films)
        self.page.ask_film_name = lambda default: None
        self.assertIsNone(self.page.create_film_for([task]))
        self.assertEqual((len(self.ctrl.project.films), task.target_film_id), (films, None))

    def test_not_offered_for_two_videos(self):
        self.page.add_files([self.video, self.long_video])
        combo = self.page.inspector.combo_suggest
        self.assertEqual(combo.findData("__new_film__"), -1)


class TestBridge(PrepareCase):
    def test_file_to_prepare_on_a_film_node(self):
        mov = os.path.join(self.media, "Making-of.mov")
        shutil.copy(self.video, mov)
        film = self.ctrl.project.films[0]
        self.win.confirm_prepare = lambda names: True
        self.win.importer.import_files(film.id, [mov])
        self.assertEqual(self.win.page, "prepare")
        (task,) = self.page.tasks
        self.assertEqual((task.name, task.target_film_id, task.status), ("Making-of.mov", film.id, tasks.WAITING))
        self.assertIsNone(self.ctrl.project.film(film.id).video_base)             # nichts übernommen

    def test_declined(self):
        mov = os.path.join(self.media, "Extra.mov")
        shutil.copy(self.video, mov)
        self.win.confirm_prepare = lambda names: False
        self.win.importer.import_files(None, [mov])
        self.assertEqual((self.win.page, self.page.tasks), ("disc", []))


if __name__ == "__main__":
    unittest.main()
