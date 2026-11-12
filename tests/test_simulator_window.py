# tests/test_simulator_window.py
"""
Tests für das Simulator-Fenster (gui/studio/simulator.py) und die Bild-Hilfen (modules/bdsim/graphics.py).
Die Test-Disc entsteht aus den Generatoren (siehe tests/test_bdsim.py); Standbilder per ffmpeg sind aus.
"""

import os
import sys
import tempfile
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from modules.bdsim.disc import load_disc
from modules.bdsim.graphics import ButtonImages, ycrcb_to_rgba, extract_frame, clip_position
from modules.bdsim.player import STATE_MENU, STATE_FILM
from gui.studio.simulator import SimulatorWindow
from tests.test_bdsim import build_test_disc, main_and_extras_pages

app_instance = QApplication.instance() or QApplication(sys.argv)


class TestGraphics(unittest.TestCase):
    def test_ycrcb_to_rgba(self):
        self.assertEqual(ycrcb_to_rgba(235, 128, 128, 255), (255, 255, 255, 255))
        self.assertEqual(ycrcb_to_rgba(16, 128, 128, 0), (0, 0, 0, 0))

    def test_missing_clip_has_no_frame(self):
        self.assertIsNone(extract_frame(os.path.join(tempfile.gettempdir(), "gibt_es_nicht.m2ts"), 1.0))


class TestSimulatorWindow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.disc = load_disc(build_test_disc(self.tmp.name, main_and_extras_pages(), num_titles=3))
        self.window = SimulatorWindow(self.disc, frames=False)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.tmp.cleanup()

    def test_button_graphics_decode(self):
        comp = self.disc.compositions[0]
        images = ButtonImages(comp)
        for page in comp.pages:
            for button in page.buttons():
                for start, _end in (button.normal, button.selected, button.activated):
                    w, h, rgba = images.rgba(start, page.palette_id)
                    self.assertEqual(len(rgba), w * h * 4)
                    self.assertTrue(any(rgba[3::4]), "Grafik ist vollständig transparent")

    def test_hint_without_frames(self):
        # isHidden statt isVisible: Das Fenster ist im Test nicht gezeigt
        self.assertFalse(self.window.preview_hint.isHidden())
        with_frames = SimulatorWindow(self.disc, frames=True)
        self.addCleanup(with_frames.deleteLater)
        self.assertTrue(with_frames.preview_hint.isHidden())

    def test_starts_in_main_menu(self):
        w = self.window
        self.assertEqual(w.player.state, STATE_MENU)
        self.assertEqual(sorted(w.screen_view.button_rects), [1, 2, 3])
        self.assertIn("Seite 0", w.status.text())
        self.assertFalse(w.btn_next.isEnabled())
        self.assertTrue(w.btn_ok.isEnabled())

    def test_remote_navigates_pages_and_films(self):
        w = self.window
        w.press("down")
        w.press("down")
        w.press("ok")
        self.assertEqual(w.player.page_id, 1)
        self.assertEqual(sorted(w.screen_view.button_rects), [1, 2])
        w.press("ok")
        self.assertEqual((w.player.state, w.player.playlist_id), (STATE_FILM, 3))
        self.assertEqual(w.screen_view.button_rects, {})
        self.assertTrue(w.btn_next.isEnabled())
        self.assertFalse(w.btn_ok.isEnabled())
        w.playlist_end()
        self.assertEqual((w.player.state, w.player.page_id), (STATE_MENU, 0))
        log = [w.log.item(i).text() for i in range(w.log.count())]
        self.assertIn("Button: SetButtonPage(Seite 1)", log)
        self.assertIn("Button: JumpTitle(3)", log)

    def test_status_shows_remembered_stream_choice(self):
        from modules.igs.layout import MenuButtonSpec
        from tests.test_bdsim import build_test_disc
        pages = [(0, [MenuButtonSpec(button_id=1, text="FILM", target_title_id=1),
                      MenuButtonSpec(button_id=2, text="TON 2", action_type="set_stream", target_audio_id=2)])]
        root = build_test_disc(os.path.join(self.tmp.name, "spur"), pages, num_titles=1)
        w = SimulatorWindow(load_disc(root), frames=False)
        self.assertNotIn("Im Menü gewählt", w.status.text())
        w._on_button_clicked(2)
        self.assertIn("Im Menü gewählt (gilt beim Filmstart): Tonspur 2", w.status.text())
        w.close()

    def test_mouse_hover_and_click(self):
        w = self.window
        w._on_button_hovered(2)
        self.assertEqual(w.player.selected_button, 2)
        w._on_button_clicked(2)
        self.assertEqual((w.player.state, w.player.playlist_id), (STATE_FILM, 2))

    def test_top_menu_and_reinsert(self):
        w = self.window
        w._on_button_clicked(1)
        w.press("top_menu")
        self.assertEqual((w.player.state, w.player.playlist_id), (STATE_MENU, 0))
        w._on_button_clicked(3)
        w.insert_disc()
        self.assertEqual(w.player.page_id, 0)

    def test_tv_switch_reinserts_disc(self):
        w = self.window
        w._on_button_clicked(1)
        w.tv_select.setCurrentIndex(1)
        self.assertFalse(w.tv_3d)
        self.assertEqual(w.player.state, STATE_MENU)
        self.assertFalse(w.player.tv_3d)

    def test_clip_position_of_menu(self):
        path, seconds = clip_position(self.disc, self.disc.playlists[0], None)
        self.assertIsNone(path)  # Die Test-Disc enthält keine Video-Clips
        self.assertEqual(seconds, 0.0)


if __name__ == "__main__":
    unittest.main()


class TestSimulatorIntegration(unittest.TestCase):
    """Studio-Knopf „Disc simulieren“, Export-Hook und Öffnen aus Ordner oder index.bdmv."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = build_test_disc(self.tmp.name, main_and_extras_pages(), num_titles=3)

    def tearDown(self):
        self.tmp.cleanup()

    def test_open_disc_from_folder_or_index(self):
        from modules.bdsim.source import open_disc
        for path in (self.root, os.path.join(self.root, "BDMV", "index.bdmv")):
            disc, close = open_disc(path)
            self.assertEqual(len(disc.index.titles), 3)
            close()

    def test_studio_opens_simulator_and_closes_it_with_the_studio(self):
        from gui.studio.main_window import StudioWindow
        studio = StudioWindow(persist_layout=False)
        closed = []
        window = studio.open_simulator(os.path.join(self.root, "BDMV", "index.bdmv"))
        window._on_close = lambda: closed.append(True)
        window.frames = False
        self.assertEqual(window.player.state, STATE_MENU)
        self.assertIn(window, studio._sim_windows)
        studio.close()
        self.assertEqual(closed, [True])

    def test_studio_reports_unreadable_disc(self):
        from unittest import mock
        from gui.studio.main_window import StudioWindow
        studio = StudioWindow(persist_layout=False)
        with mock.patch("gui.studio.main_window.QMessageBox.critical") as critical:
            self.assertIsNone(studio.open_simulator(self.tmp.name + "_gibt_es_nicht"))
        critical.assert_called_once()
        studio.close()

    def test_export_thread_simulates_finished_disc(self):
        from gui.studio.export_dialog import _ExportThread
        thread = _ExportThread(None, None, "de")
        lines = []
        thread.log.connect(lines.append)
        thread._simulate(self.root)
        self.assertIsNotNone(thread.disc)
        self.assertTrue(any("0 Fehler, 0 Warnungen" in line for line in lines), lines)


class TestSimulateProject(unittest.TestCase):
    """v1.10.0: „Disc simulieren“ im Studio öffnet das aktuelle Projekt, ohne Disc zu erstellen."""

    def setUp(self):
        from gui.studio.main_window import StudioWindow
        self.studio = StudioWindow(persist_layout=False)
        self.project = self.studio.controller.project
        self.project.films[0].video_base = "film.264"     # wird für die Simulation nie gelesen

    def tearDown(self):
        self.studio.close()

    def test_opens_project_and_removes_disc_on_close(self):
        self.project.settings.project_name = "MEINE_DISC"
        window = self.studio.simulate_project()
        self.assertIsNotNone(window)
        self.assertEqual(window.player.state, STATE_MENU)
        self.assertFalse(window.frames)
        self.assertIn("MEINE_DISC (aus dem Projekt)", window.windowTitle())
        root = os.path.dirname(window.disc.bdmv_dir)
        self.assertTrue(os.path.isdir(root))
        window.close()
        self.assertFalse(os.path.exists(root))

    def test_preflight_errors_are_shown(self):
        from unittest import mock
        self.project.films[0].video_base = None
        with mock.patch("gui.studio.main_window.QMessageBox.information") as info:
            self.assertIsNone(self.studio.simulate_project())
        info.assert_called_once()
        self.assertIn("Simulieren geht erst", info.call_args[0][2])
        self.assertEqual(self.studio._sim_windows, [])

    def test_disc_without_menu(self):
        from unittest import mock
        self.project.start_target = self.project.films[0].id
        with mock.patch("gui.studio.main_window.QMessageBox.information") as info:
            self.assertIsNone(self.studio.simulate_project())
        self.assertIn("kein Menü", info.call_args[0][2])

    def test_toolbar_button_simulates_and_arrow_opens_finished_disc(self):
        from PySide6.QtWidgets import QToolButton
        button = self.studio.toolbar.widgetForAction(self.studio.act_simulate)
        self.assertEqual(button.popupMode(), QToolButton.MenuButtonPopup)
        self.assertEqual(button.menu().actions(), [self.studio.act_simulate_open])
        self.assertEqual(self.studio.act_simulate.text(), "Disc simulieren")
        self.studio.act_simulate.trigger()
        self.assertEqual(len(self.studio._sim_windows), 1)
