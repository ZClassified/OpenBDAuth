"""
Vorbereiten für Ultra HD Blu-ray in der Oberfläche (UHD-Plan, Phase 3):
- Aufträge: auf einer UHD-Disc wird jedes Video ein UHD-Auftrag (2160p bei 4K, sonst 1080p), HDR10-Angaben aus der
  Datei; fehlen sie, entsteht der Auftrag trotzdem, startet aber erst mit eingetragenen Werten. Auf einer Blu-ray
  nennt die Ablehnung einer 4K-HDR-Quelle den Weg über den Disc-Typ. Speichern und Laden der Warteschlange.
- Inspektor: Auflösung, Datenrate mit „passt bis …“ und Ausweg, Genau/Schnell, Dynamik, HDR10-Eingabe,
  Hinweis bei anderem Disc-Typ mit „An den Disc-Typ anpassen“
- Übernehmen: .hevc wird Video eines Film-Knotens, Bildrate aus dem Strom
Alle Quellen erzeugt ffmpeg selbst (Testbild).
"""

import os
import shutil
import tempfile
import unittest
from unittest import mock

from PySide6.QtWidgets import QMessageBox

from modules.prepare import tasks, uhd
from tests.prepare_util import ffmpeg, make_hevc, needs_x265, setUpModule, tearDownModule  # noqa: F401
from tests.test_menu_designer import app_instance

HDR_TAGS = "setparams=color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc"
SDR_TAGS = "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709"


def prores(path, size, tags, seconds=0.3):
    ffmpeg('-f', 'lavfi', '-i', f'testsrc2=s={size}:r=24000/1001:d={seconds}', '-vf', tags,
           '-pix_fmt', 'yuv422p10le', '-c:v', 'prores_ks', '-profile:v', '3', path)


@needs_x265
class Sources(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="prepare_uhd_page_")
        cls.sdr_1080 = os.path.join(cls.dir, "SDR 1080.mov")
        prores(cls.sdr_1080, "1920x1080", SDR_TAGS)
        cls.hdr_nometa = os.path.join(cls.dir, "HDR ohne Angaben.mov")
        prores(cls.hdr_nometa, "3840x2160", HDR_TAGS)
        cls.hdr_meta = os.path.join(cls.dir, "HDR mit Angaben.mkv")
        make_hevc(cls.hdr_meta, seconds=0.3, size="3840x2160", colour="hdr10", fmt="matroska")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)


class Tasks(Sources):
    def test_uhd_disc_creates_uhd_tasks(self):
        sdr = tasks.create_task(self.sdr_1080, disc_type="uhd")
        self.assertEqual((sdr.kind, sdr.uhd_resolution, sdr.uhd_bitrate), ("uhd", "1080", 15))
        self.assertEqual(sdr.dynamic_range, "sdr709")
        hdr = tasks.create_task(self.hdr_meta, disc_type="uhd")
        self.assertEqual((hdr.kind, hdr.uhd_resolution, hdr.uhd_bitrate), ("uhd", "2160", 45))
        self.assertTrue(hdr.uhd_hdr_from_file)
        self.assertEqual(hdr.hdr_meta().max_cll, 1000)
        self.assertFalse(hdr.needs_hdr_meta())
        self.assertTrue(tasks.planned_outputs(hdr)[0].endswith("HDR mit Angaben_2160p.hevc"))
        self.assertEqual(tasks.estimated_size(hdr), uhd.estimated_size(hdr.duration, 45))

    def test_missing_hdr_values_block_only_the_start(self):
        task = tasks.create_task(self.hdr_nometa, disc_type="uhd")
        self.assertTrue(task.needs_hdr_meta())
        with self.assertRaises(ValueError):
            tasks.build_job(task)
        meta = uhd.HdrMeta((13250, 34500), (7500, 3000), (34000, 16000), (15635, 16450), 10000000, 50, 1000, 400)
        task.uhd_hdr = tasks.hdr_to_dict(meta)
        self.assertFalse(task.needs_hdr_meta())
        self.assertIn("max-cll=1000,400", ":".join(tasks.build_job(task).steps[1].cmd))

    def test_bluray_rejection_names_uhd(self):
        with self.assertRaises(tasks.SourceRejected) as ctx:
            tasks.create_task(self.hdr_meta)
        self.assertIn("uhd_possible", [code for code, _ in ctx.exception.problems])

    def test_switch_kind_and_resolution(self):
        task = tasks.create_task(self.sdr_1080)                          # Blu-ray: 2D
        self.assertEqual(task.kind, "2d")
        self.assertEqual(tasks.set_kind(task, "uhd"), [])
        self.assertEqual((task.kind, task.uhd_resolution), ("uhd", "1080"))
        self.assertEqual([c for c, _ in tasks.set_uhd_resolution(task, "2160")], ["uhd_size"])
        self.assertEqual(task.uhd_resolution, "1080")
        self.assertEqual(tasks.set_kind(task, "2d"), [])
        self.assertEqual(task.kind, "2d")
        hdr = tasks.create_task(self.hdr_meta, disc_type="uhd")
        self.assertEqual(tasks.set_uhd_resolution(hdr, "1080"), [])
        self.assertEqual((hdr.uhd_resolution, hdr.uhd_bitrate), ("1080", 15))

    def test_queue_roundtrip(self):
        task = tasks.create_task(self.hdr_meta, disc_type="uhd")
        task.uhd_mode = "fast"
        path = os.path.join(self.dir, "queue.json")
        tasks.save_queue(path, [task])
        (loaded,) = tasks.load_queue(path)
        self.assertEqual((loaded.kind, loaded.uhd_mode, loaded.uhd_bitrate), ("uhd", "fast", 45))
        self.assertEqual(loaded.hdr_meta(), task.hdr_meta())
        self.assertEqual(tasks.planned_outputs(loaded), tasks.planned_outputs(task))


class Page(Sources):
    def setUp(self):
        from gui.studio.main_window import StudioWindow
        self.win = StudioWindow(persist_layout=False)
        self.win.resize(1400, 900)
        self.win.show()
        self.page = self.win.prepare_page
        self.ctrl = self.win.controller
        self.inspector = self.page.inspector
        self.ctrl.set_settings("Disc-Typ ändern", disc_type="uhd")
        patcher = mock.patch.object(QMessageBox, "warning")
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.ctrl.undo_stack.setClean()
        self.win.close()

    def select(self, task):
        self.page.list.setCurrentItem(None)
        self.inspector.show_task(task)
        app_instance.processEvents()

    def test_inspector_shows_uhd_settings(self):
        (task,) = self.page.add_files([self.hdr_meta])
        self.select(task)
        ins = self.inspector
        self.assertTrue(ins.row_uhd_res.isVisibleTo(ins))
        self.assertFalse(ins.row_kind.isVisibleTo(ins))
        self.assertEqual(ins.switch_uhd_res.value(), "2160")
        self.assertEqual([ins.combo_bitrate.itemData(i) for i in range(ins.combo_bitrate.count())], [60, 45, 35, 25])
        self.assertIn("auf BD-25", ins.combo_bitrate.itemText(1))
        self.assertIn("passt bis ca.", ins.combo_bitrate.itemText(1))
        self.assertIn("HDR10", ins.lbl_range.text())
        self.assertIn("MaxCLL 1000", ins.lbl_range.text())
        self.assertFalse(ins.box_hdr.isVisibleTo(ins))                  # Angaben aus der Datei
        ins.switch_uhd_mode.buttons["fast"].click()
        self.assertEqual(task.uhd_mode, "fast")
        ins.combo_bitrate.setCurrentIndex(3)
        ins.combo_bitrate.activated.emit(3)
        self.assertEqual(task.uhd_bitrate, 25)
        self.assertEqual(self.page.list.topLevelItem(0).text(1), "Ultra HD")

    def test_too_long_for_the_disc_names_the_way_out(self):
        (task,) = self.page.add_files([self.hdr_meta])
        task.video.duration = 90 * 60                                    # 1,5 h bei 45 Mbit/s: über 25 GB
        self.select(task)
        ins = self.inspector
        self.assertTrue(ins.lbl_fit.isVisibleTo(ins))
        self.assertIn("BD-25", ins.lbl_fit.text())
        self.assertIn("35 Mbit/s", ins.lbl_fit.text())

    def test_hdr_values_entered(self):
        (task,) = self.page.add_files([self.hdr_nometa])
        self.select(task)
        ins = self.inspector
        self.assertTrue(ins.box_hdr.isVisibleTo(ins))
        self.assertTrue(ins.lbl_hdr_needed.isVisibleTo(ins))
        self.assertTrue(task.needs_hdr_meta())
        ins.spin_hdr["max_luminance"][1].setValue(1000)
        ins.spin_hdr["max_cll"][1].setValue(800)
        ins.spin_hdr["max_fall"][1].setValue(300)
        ins._commit_hdr()
        self.assertFalse(task.needs_hdr_meta())
        meta = task.hdr_meta()
        self.assertEqual((meta.max_luminance, meta.min_luminance, meta.max_cll, meta.max_fall), (10000000, 1, 800, 300))
        self.assertEqual(meta.green, (13250, 34500))                     # DCI-P3 D65
        self.assertIn("(eingegeben)", ins.lbl_range.text())

    def test_disc_type_changed_after_adding(self):
        (task,) = self.page.add_files([self.sdr_1080])
        self.ctrl.set_settings("Disc-Typ ändern", disc_type="bluray")
        self.select(task)
        ins = self.inspector
        self.assertTrue(ins.lbl_disc_mismatch.isVisibleTo(ins))
        ins.btn_fit_disc.click()
        self.assertEqual(task.kind, "2d")
        self.assertFalse(ins.lbl_disc_mismatch.isVisibleTo(ins))

    def test_hevc_into_film_node(self):
        raw = os.path.join(self.dir, "Film_2160p.hevc")
        make_hevc(raw, seconds=0.3, size="3840x2160", colour="hdr10")
        film_id = self.win.importer.import_files(None, [raw])
        film = self.ctrl.project.film(film_id)
        self.assertTrue(film.is_hevc)
        self.assertAlmostEqual(film.fps, 24000 / 1001, places=3)           # aus dem SPS, nicht geraten
        self.assertEqual(film.video_details["dynamic_range"], "hdr10")
        app_instance.processEvents()                                     # Graph baut den Knoten verzögert auf
        self.win.scene.select_node(film_id)
        app_instance.processEvents()
        self.assertIn("Ultra HD", self.win.inspector.film_page.lbl_info.text())


if __name__ == "__main__":
    unittest.main()
