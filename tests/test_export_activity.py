# tests/test_export_activity.py
"""Lebenszeichen beim Export: geschriebene Bytes, Zeitangaben, Statuszeile im Dialog (v1.17.6)."""

import os
import shutil
import sys
import tempfile
import time
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from gui.studio.export_activity import WriteMeter, format_clock, format_bytes

app_instance = QApplication.instance() or QApplication(sys.argv)


def write(path: str, size: int, mtime: float = None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"\0" * size)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


class TestWriteMeter(unittest.TestCase):
    def setUp(self):
        self.dest = tempfile.mkdtemp()
        self.temp_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dest, True)
        self.addCleanup(shutil.rmtree, self.temp_root, True)

    def test_counts_new_files_in_dest_and_ignores_old_ones(self):
        old = time.time() - 3600
        write(os.path.join(self.dest, "Quelle.264"), 5000, mtime=old)          # liegt schon im Zielordner
        write(os.path.join(self.dest, "BDMV", "STREAM", "00001.m2ts"), 700, mtime=old)
        meter = WriteMeter(self.dest, self.temp_root)
        self.assertEqual(meter.measure(), 0)
        write(os.path.join(self.dest, "BDMV", "STREAM", "00000.m2ts"), 1000)
        write(os.path.join(self.dest, "job.meta"), 10)
        self.assertEqual(meter.measure(), 1010)

    def test_ignores_unrelated_subfolders(self):
        meter = WriteMeter(self.dest, self.temp_root)
        write(os.path.join(self.dest, "_backup", "kopie.wav"), 999)
        self.assertEqual(meter.measure(), 0)

    def test_deleted_files_keep_counting(self):
        meter = WriteMeter(self.dest, self.temp_root)
        stream = os.path.join(self.dest, "BDMV", "STREAM", "00000.m2ts")
        write(stream, 1000)
        self.assertEqual(meter.measure(), 1000)
        write(os.path.join(self.dest, "DISC.iso"), 1200)
        shutil.rmtree(os.path.join(self.dest, "BDMV"))   # Aufräumen nach der ISO
        self.assertEqual(meter.measure(), 2200)

    def test_extra_titles_in_temp_folder(self):
        meter = WriteMeter(self.dest, self.temp_root)
        extra = os.path.join(self.temp_root, "tmpabc")
        write(os.path.join(extra, "title_2.meta"), 20)
        write(os.path.join(extra, "bdmv_title_2", "BDMV", "STREAM", "00000.m2ts"), 3000)
        write(os.path.join(self.temp_root, "fremd", "irgendwas.bin"), 4000)   # anderer Temp-Ordner
        self.assertEqual(meter.measure(), 3020)

    def test_result_is_the_iso_not_everything_written(self):
        """v1.18.3: BDMV (1000) + ISO daraus (1200), BDMV danach gelöscht – Ergebnis ist die ISO."""
        old = time.time() - 3600
        write(os.path.join(self.dest, "ALT.iso"), 9999, mtime=old)               # ISO eines früheren Exports
        meter = WriteMeter(self.dest, self.temp_root)
        write(os.path.join(self.dest, "BDMV", "STREAM", "00000.m2ts"), 1000)
        meter.measure()
        write(os.path.join(self.dest, "DISC.iso"), 1200)
        shutil.rmtree(os.path.join(self.dest, "BDMV"))
        self.assertEqual(meter.measure(), 2200)                                  # Lebenszeichen zählt alles
        self.assertEqual(meter.result(), ("iso", 1200))

    def test_result_of_a_folder_export(self):
        meter = WriteMeter(self.dest, self.temp_root)
        write(os.path.join(self.dest, "BDMV", "STREAM", "00000.m2ts"), 1000)
        write(os.path.join(self.dest, "CERTIFICATE", "id.bdmv"), 100)
        write(os.path.join(self.dest, "job.meta"), 10)
        self.assertEqual(meter.result(), ("folder", 1100))

    def test_missing_dest_is_zero(self):
        meter = WriteMeter(os.path.join(self.dest, "gibt_es_nicht"), self.temp_root)
        self.assertEqual(meter.measure(), 0)


class TestFormatting(unittest.TestCase):
    def test_clock(self):
        self.assertEqual(format_clock(0), "0:00")
        self.assertEqual(format_clock(134), "2:14")
        self.assertEqual(format_clock(3723), "1:02:03")

    def test_bytes(self):
        self.assertEqual(format_bytes(3_650_722_201, "de"), "3,7 GB")      # dezimal (v1.30.4)
        self.assertEqual(format_bytes(3_650_722_201, "en"), "3.7 GB")
        self.assertEqual(format_bytes(52_000_000, "de"), "52 MB")
        self.assertEqual(format_bytes(7_923_499_008, "de"), "7,9 GB")      # D4A-ISO: wie unter Brennen


class TestActivityLine(unittest.TestCase):
    def setUp(self):
        from core.disc_edit import starter_project
        from gui.node_editor.controller import GraphController
        from gui.studio.export_dialog import ExportDialog
        self.dest = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dest, True)
        self.dialog = ExportDialog(GraphController(starter_project()))
        self.addCleanup(self.dialog.close)

    def test_running_then_done(self):
        self.dialog._start_activity(self.dest)
        self.assertTrue(self.dialog.lbl_activity.isVisibleTo(self.dialog))
        self.assertEqual(self.dialog.lbl_activity.property("state"), "run")
        self.assertIn("0:00", self.dialog.lbl_activity.text())
        self.assertNotIn("Meldung", self.dialog.lbl_activity.text())             # v1.18.3
        write(os.path.join(self.dest, "BDMV", "STREAM", "00000.m2ts"), 3 * 1024 ** 2)
        self.dialog._tick_activity()
        write(os.path.join(self.dest, "DISC.iso"), 2 * 1024 ** 2)
        self.dialog._finish_activity(True)
        self.assertFalse(self.dialog._activity_timer.isActive())
        self.assertEqual(self.dialog.lbl_activity.property("state"), "ok")
        self.assertTrue(self.dialog.lbl_activity.text().endswith("· ISO 2 MB"), self.dialog.lbl_activity.text())

    def test_failure_is_red(self):
        self.dialog._start_activity(self.dest)
        self.dialog._finish_activity(False)
        self.assertEqual(self.dialog.lbl_activity.property("state"), "fail")
        self.assertIn("#DC2626", self.dialog.progress.styleSheet())

    def test_stall_after_long_silence(self):
        from gui.studio.export_dialog import STALL_SECONDS
        self.dialog._start_activity(self.dest)
        self.dialog._last_signal = self.dialog._last_growth = time.monotonic() - STALL_SECONDS - 1
        self.dialog._tick_activity()
        self.assertEqual(self.dialog.lbl_activity.property("state"), "stall")
        self.dialog._mark_signal("neue Zeile von tsMuxeR")
        self.dialog._tick_activity()
        self.assertEqual(self.dialog.lbl_activity.property("state"), "run")
        self.dialog._finish_activity(True)


if __name__ == "__main__":
    unittest.main()
