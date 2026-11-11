# tests/test_prepare_tasks.py
"""
Aufträge im Arbeitsbereich Vorbereiten (v1.22) ohne Oberfläche: Vorbelegung aus der Quelle, Ablehnung
ungeeigneter Quellen, Ausführung im eigenen Prozess. Encodiert wird in _unfertig/; im Ausgabeordner erscheinen
nur fertige, geprüfte Dateien, bei Abbruch oder Fehler bleibt nichts liegen.
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest import mock

from modules.prepare import jobs, tasks
from modules.prepare.background import BackgroundTask
from modules.prepare.runner import run_task
from tests.prepare_util import ffmpeg, make_tab_source, needs_ffmpeg, setUpModule, tearDownModule  # noqa: F401


def run(task, seconds=180.0, cancel_at=None):
    bg = BackgroundTask(run_task, task, log=True, cancellable=True)
    lines, end = [], time.time() + seconds
    while not bg.poll():
        lines += bg.take_log()
        if cancel_at is not None and bg.progress >= cancel_at:
            bg.cancel()
        if time.time() > end:
            bg.cancel()
            raise AssertionError("Auftrag wurde nicht fertig")
        time.sleep(0.1)
    return bg, lines + bg.take_log()


@needs_ffmpeg
class TestTasks(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="openbdauth_prepare_")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def path(self, name):
        return os.path.join(self.dir, name)

    def assert_clean_staging(self, task):
        self.assertFalse(os.path.exists(os.path.join(task.out_dir, tasks.STAGING_DIR_NAME)))

    def test_2d(self):
        src = self.path("Trailer.mp4")
        ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=1280x720:r=24:d=2', '-pix_fmt', 'yuv420p', '-c:v', 'libx264',
               '-preset', 'ultrafast', src)
        task = tasks.create_task(src)
        self.assertEqual((task.kind, task.target_720p, task.out_dir),
                         (tasks.KIND_2D, False, self.path(tasks.OUT_DIR_NAME)))
        self.assertEqual(tasks.resolution_choice(task), None)              # 24 fps: 720p und 1080 wählbar
        self.assertEqual(tasks.planned_outputs(task), [self.path(os.path.join("Disc-fertig", "Trailer.264"))])
        bg, log = run(task)
        self.assertIsNone(bg.error, "\n".join(log[-20:]))
        self.assertEqual(bg.result, tasks.planned_outputs(task))
        self.assertGreater(os.path.getsize(bg.result[0]), 0)
        self.assertGreaterEqual(bg.progress, 0.99)
        self.assertTrue(any("libx264" in line for line in log))
        self.assert_clean_staging(task)

    def test_3d(self):
        src = self.path("Film.mkv")
        make_tab_source(src)
        task = tasks.create_task(src)
        self.assertEqual((task.kind, task.layout), (tasks.KIND_3D, "tab"))
        bg, log = run(task)
        self.assertIsNone(bg.error, "\n".join(log[-20:]))
        self.assertEqual([os.path.basename(p) for p in bg.result], ["Film_3D.264", "Film_3D.mvc"])
        self.assert_clean_staging(task)

    def test_audio(self):
        src = self.path("Mix.wav")
        ffmpeg('-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=1', '-ac', '2', src)
        task = tasks.create_task(src)
        self.assertEqual((task.kind, task.audio_format), (tasks.KIND_AUDIO, "AC3 (Stereo, 192 kbps)"))
        bg, log = run(task)
        self.assertIsNone(bg.error, "\n".join(log[-20:]))
        self.assertEqual([os.path.basename(p) for p in bg.result], ["Mix.ac3"])

    def test_cancel_leaves_nothing(self):
        src = self.path("Lang.mp4")
        ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=1920x1080:r=24:d=40', '-pix_fmt', 'yuv420p', '-c:v', 'libx264',
               '-preset', 'ultrafast', src)
        task = tasks.create_task(src)
        task.bitrate_2d = 25
        bg, _ = run(task, cancel_at=0.02)
        self.assertTrue(bg.cancelled)
        self.assertIsNone(bg.error)
        self.assertIsNone(bg.result)
        self.assertEqual(os.listdir(task.out_dir), [])                     # keine halbe Datei, kein _unfertig

    def test_unsuitable_source_is_rejected(self):
        src = self.path("Handy.mp4")
        ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=1920x1080:r=12:d=1', '-pix_fmt', 'yuv420p', '-c:v', 'libx264',
               '-preset', 'ultrafast', src)
        with self.assertRaises(tasks.SourceRejected) as ctx:
            tasks.create_task(src)
        self.assertEqual([code for code, _ in ctx.exception.problems], ["fps"])

    def test_panorama_can_switch_to_2d(self):
        src = self.path("Panorama.mp4")
        ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=3840x1080:r=24:d=1', '-pix_fmt', 'yuv420p', '-c:v', 'libx264',
               '-preset', 'ultrafast', src)
        task = tasks.create_task(src)
        self.assertEqual((task.kind, task.layout), (tasks.KIND_3D, "sbs"))
        self.assertEqual(tasks.set_kind(task, tasks.KIND_2D), [])
        self.assertEqual(task.kind, tasks.KIND_2D)

    def test_neither_video_nor_audio(self):
        src = self.path("notiz.txt")
        with open(src, "w") as f:
            f.write("kein Film")
        with self.assertRaises(ValueError):
            tasks.create_task(src)


class TestProbeErrors(unittest.TestCase):
    """v1.27.3: Scheitert ffprobe, kommt seine Meldung an statt „weder Bild noch Ton“ (ohne ffmpeg)."""

    def fake_run(self, returncode, stdout="", stderr=""):
        done = subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)
        return mock.patch("modules.prepare.jobs.subprocess.run", return_value=done)

    def test_failure_keeps_ffprobe_message(self):
        path = os.path.join("media", "film.mkv")
        with self.fake_run(1, stdout="{\n\n}\n", stderr=f"{path}: Permission denied\n"):
            with self.assertRaises(jobs.ProbeError) as ctx:
                jobs.probe(path)
        self.assertEqual(ctx.exception.message, "Permission denied")
        self.assertIsInstance(ctx.exception, ValueError)

    def test_failure_without_text_names_exit_code(self):
        with self.fake_run(1, stdout="nicht json"):
            with self.assertRaises(jobs.ProbeError) as ctx:
                jobs.probe("film.mkv")
        self.assertEqual(ctx.exception.message, "exit code 1")

    def test_streams_despite_error_count(self):
        out = json.dumps({"streams": [{"codec_type": "audio"}]})
        with self.fake_run(1, stdout=out, stderr="decode error\n"):
            self.assertEqual(jobs.probe("film.mkv")["streams"], [{"codec_type": "audio"}])

    def test_warnings_on_success_are_ignored(self):
        with self.fake_run(0, stdout="{}", stderr="some warning\n"):
            self.assertEqual(jobs.probe("film.mkv"), {})

    def test_create_task_passes_probe_error_on(self):
        with self.fake_run(1, stderr="Invalid data found when processing input\n") as run_mock:
            with self.assertRaises(jobs.ProbeError):
                tasks.create_task("film.mkv")
        self.assertEqual(run_mock.call_count, 1)            # nicht noch einmal als Tondatei versucht

    def test_missing_ffprobe_raises_os_error(self):
        missing = os.path.join(tempfile.gettempdir(), "gibt_es_nicht", "ffprobe")
        self.addCleanup(jobs.configure_tools, jobs._tool_resolver)
        with mock.patch("modules.external_tools.find_tool", return_value=missing):
            with self.assertRaises(OSError):
                tasks.create_task("film.mkv")

    def test_create_task_uses_bundled_ffprobe(self):
        """v1.27.4: Das Hinzufügen läuft im Hauptprozess, der die Werkzeuge bisher nicht eingestellt hatte – es nahm
        das ffprobe aus dem PATH statt des mitgelieferten (Linux-Betatest)."""
        bundled = os.path.join("OpenBDAuth", "tools", "linux", "ffprobe")
        self.addCleanup(jobs.configure_tools, jobs._tool_resolver)
        jobs.configure_tools(None)                       # Zustand beim Programmstart
        with mock.patch("modules.external_tools.find_tool", return_value=bundled):
            with self.fake_run(0, stdout=json.dumps({"streams": [{"codec_type": "audio", "channels": 2,
                                                                  "sample_rate": "48000"}]})) as run_mock:
                tasks.create_task("Mix.wav")
        self.assertEqual(run_mock.call_args[0][0][0], bundled)


class TestQueueFile(unittest.TestCase):
    """Warteschlange getrennt vom Disc-Projekt speichern (v1.23), ohne ffmpeg."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="openbdauth_queue_")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def _video_task(self, name="Film.mov", status=tasks.WAITING):
        from modules.prepare import jobs
        src = os.path.join(self.dir, name)
        info = jobs.SourceInfo(path=src, width=1920, height=1080, fps_val=24.0, fps_str="24", gop=24, duration=600)
        return tasks.PrepareTask(id=name[:4], source=src, kind=tasks.KIND_2D, video=info, status=status,
                                 out_dir=tasks.default_out_dir(src), confirmed=True)

    def test_roundtrip_running_becomes_waiting(self):
        from modules.prepare import jobs
        running = self._video_task("Lauf.mov", tasks.RUNNING)
        audio = tasks.PrepareTask(id="ton1", source="Ton.mkv", kind=tasks.KIND_AUDIO, audio_format="AC3 (Stereo, 192 kbps)",
                                  audio=jobs.AudioSource("Ton.mkv", [jobs.AudioTrack(0, "aac", 2, 48000, "deu")], 60.0,
                                                         True))
        path = os.path.join(self.dir, "queue.json")
        tasks.save_queue(path, [running, audio])
        loaded = tasks.load_queue(path)
        self.assertEqual([t.status for t in loaded], [tasks.WAITING, tasks.WAITING])
        self.assertEqual((loaded[0].video.fps_str, loaded[0].confirmed), ("24", True))
        self.assertEqual(loaded[1].track().language, "deu")
        self.assertEqual(tasks.planned_outputs(loaded[0]), tasks.planned_outputs(running))

    def test_leftover_staging_is_removed(self):
        task = self._video_task()
        os.makedirs(tasks.staging_dir(task))
        path = os.path.join(self.dir, "queue.json")
        tasks.save_queue(path, [task])
        tasks.load_queue(path)
        self.assertFalse(os.path.exists(os.path.join(task.out_dir, tasks.STAGING_DIR_NAME)))

    def test_fields_of_older_versions_are_ignored(self):
        path = os.path.join(self.dir, "queue.json")
        tasks.save_queue(path, [self._video_task()])
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        data["tasks"][0]["conform_fps"] = False             # gab es bis v1.24
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        self.assertEqual(len(tasks.load_queue(path)), 1)

    def test_unreadable_file_gives_empty_queue(self):
        path = os.path.join(self.dir, "queue.json")
        with open(path, "w") as f:
            f.write("{kaputt")
        self.assertEqual(tasks.load_queue(path), [])
        self.assertEqual(tasks.load_queue(os.path.join(self.dir, "fehlt.json")), [])

    def test_estimates_and_duplicates(self):
        a = self._video_task("A.mov")
        self.assertEqual(tasks.estimated_size(a), 600 * 20 * 125_000)
        b = self._video_task("A.mkv")                      # gleicher Name, gleicher Ordner -> A.264 doppelt
        self.assertEqual([os.path.basename(p) for p in tasks.duplicate_outputs([a, b])], ["A.264"])
        self.assertIsNone(tasks.queue_space_shortfall([a]))
        a.total_kbps, a.kind = 25000, tasks.KIND_3D
        self.assertEqual(tasks.estimated_size(a), 600 * 25000 * 125)


if __name__ == "__main__":
    unittest.main()
