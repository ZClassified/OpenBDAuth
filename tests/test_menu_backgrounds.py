# tests/test_menu_backgrounds.py
"""
Eigene Hintergründe im Studio (v1.13.2): „wie Hauptmenü“ oder eigenes Bild/Video/Musik, Drag & Drop auf
Viewer und Menü-Knoten (wirkt immer aufs Menü), Pausen-Symbol an Verbindungen zwischen Menügruppen,
Simulator-Hintergrund je Menü-Playlist und „Form“ als Stil neuer Menüs.
"""

import os
import unittest
from unittest import mock

from PySide6.QtCore import Qt, QMimeData, QPointF, QUrl
from PySide6.QtGui import QDropEvent

from core import disc_edit
from core.disc_edit import (
    background_field, follows_main_background, set_background_file, clear_background, add_menu, starter_project,
    BG_IMAGE, BG_VIDEO, BG_AUDIO,
)
from core.disc_model import STYLE_SHAPE, STYLE_TEXT
from core.menu_templates import create_chapter_menus, create_language_menus, create_titles_menu
from gui.node_editor.controller import GraphController
from gui.node_editor.scene import NodeScene, WireItem, MarkerItem, PAUSE_TOOLTIP
from core.translations import tr
from gui.studio.backgrounds import apply_background_files
from modules.bdmv.movie_object_generator import menu_group_playlist
from tests.project_factory import make_project, temp_media
from tests.test_inspector_selection import InspectorCase
from tests.test_menu_designer import app_instance
from tests.test_menu_groups import two_backgrounds
from tests.test_sim_disc import SimDiscTestCase


def file_mime(*paths) -> QMimeData:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
    return mime


class TestModel(unittest.TestCase):
    def test_background_field(self):
        self.assertEqual(background_field("C:/x/Bild.PNG"), BG_IMAGE)
        self.assertEqual(background_field("C:/x/loop.264"), BG_VIDEO)
        self.assertEqual(background_field("C:/x/musik.ac3"), BG_AUDIO)
        self.assertIsNone(background_field("C:/x/untertitel.sup"))

    def test_own_background_starts_from_main(self):
        project = make_project(chapters=4, chapter_menu=True)
        main, page = project.main_menu, project.menus[1]
        main.background.video, main.background.audio, main.background.duration = "C:/loop.264", "C:/m.ac3", 40.0
        self.assertTrue(follows_main_background(project, page))
        self.assertFalse(follows_main_background(project, main))
        set_background_file(project, page.id, BG_IMAGE, "C:/kapitel.png")
        bg = page.background
        # Bild ersetzt das Video des Hauptmenüs (sonst unsichtbar), Musik und Dauer bleiben
        self.assertEqual((bg.image, bg.video, bg.audio, bg.duration), ("C:/kapitel.png", None, "C:/m.ac3", 40.0))
        self.assertFalse(follows_main_background(project, page))
        self.assertEqual(main.background.video, "C:/loop.264")          # Hauptmenü unverändert
        clear_background(project, page.id)
        self.assertTrue(follows_main_background(project, page))

    def test_video_replaces_main_image(self):
        project = make_project(chapters=4, chapter_menu=True)
        project.main_menu.background.image = "C:/haupt.png"
        page = project.menus[1]
        set_background_file(project, page.id, BG_VIDEO, "C:/kapitel.264", duration=12.0)
        self.assertEqual((page.background.image, page.background.video, page.background.duration),
                         (None, "C:/kapitel.264", 12.0))
        set_background_file(project, page.id, BG_AUDIO, "C:/musik.wav")    # eigener: nur das Feld
        self.assertEqual(page.background.video, "C:/kapitel.264")

    def test_new_menus_use_shape_style(self):
        project = starter_project()
        self.assertEqual(project.main_menu.button_style.kind, STYLE_SHAPE)  # ab v1.14.5 auch die Startvorlage
        film = project.films[0]
        film.chapters = make_project(chapters=3).films[0].chapters
        film.audio_tracks = make_project(audio=2).films[0].audio_tracks
        menus = [add_menu(project, "Extras", (0, 0))]
        menus += create_chapter_menus(project, film.id)
        menus += create_language_menus(project, film.id)
        disc_edit.add_film(project, "Bonus", (0, 0))
        menus.append(create_titles_menu(project))
        self.assertEqual({m.button_style.kind for m in menus}, {STYLE_SHAPE})


class TestControllerAndScene(unittest.TestCase):
    def setUp(self):
        project, self.main, self.pages, self.lang = two_backgrounds()
        self.ctrl = GraphController(project)
        self.scene = NodeScene(self.ctrl)

    def _pause_wires(self):
        return {(w.source.node_id, w.target_id) for w in self.scene.items()
                if isinstance(w, WireItem) and w.pause_badge is not None}

    def test_pause_symbol_between_groups(self):
        first = self.pages[0]
        # Hauptmenü → Kapitelmenü (Bild 2): Pause; Hauptmenü → Sprachmenü (wie Hauptmenü) und Seite → Seite nicht
        self.assertIn((self.main.id, first.id), self._pause_wires())
        self.assertNotIn((self.main.id, self.lang.id), self._pause_wires())
        self.assertNotIn((first.id, self.pages[1].id), self._pause_wires())
        wire = next(w for w in self.scene.items() if isinstance(w, WireItem) and w.pause_badge is not None)
        self.assertEqual(wire.pause_badge.toolTip(), tr(PAUSE_TOOLTIP))
        # Rücksprünge als Marken: der Hinweis steht im Tooltip
        self.ctrl.project.view.return_wire_mode = "markers"
        self.scene.rebuild()
        back = [m for m in self.scene.items() if isinstance(m, MarkerItem) and m.target_id == self.main.id
                and m.source.node_id == first.id]
        self.assertTrue(back and tr(PAUSE_TOOLTIP) in back[0].toolTip())
        # gleicher Hintergrund: kein Symbol mehr
        for page in self.pages:
            page.background.image = None
        self.ctrl.project.view.return_wire_mode = "lines"
        self.scene.rebuild()
        self.assertEqual(self._pause_wires(), set())

    def test_drop_files_one_undo_step(self):
        steps = self.ctrl.undo_stack.count()
        with mock.patch("modules.menu_author.probe_media_duration", return_value=33.0):
            rejected = apply_background_files(self.ctrl, self.lang.id, ["C:/ton.png", "C:/ton.wav", "C:/x.sup"])
        lang = self.ctrl.project.menu(self.lang.id)
        self.assertEqual(rejected, ["x.sup"])
        self.assertEqual((lang.background.image, lang.background.audio, lang.background.duration),
                         ("C:/ton.png", "C:/ton.wav", 33.0))
        self.assertEqual(self.ctrl.undo_stack.count(), steps + 1)
        self.ctrl.undo_stack.undo()
        self.assertFalse(self.ctrl.project.menu(self.lang.id).background.is_set)

    def test_drop_on_menu_node(self):
        item = self.scene.nodes[self.lang.id]
        mime, pos = file_mime("C:/sprachen.jpg"), item.sceneBoundingRect().center()
        # QGraphicsSceneDragDropEvent lässt sich in PySide6 nicht füllen: nur was dropEvent abfragt
        event = mock.Mock(mimeData=lambda: mime, scenePos=lambda: pos)
        messages = []
        self.scene.status_message.connect(messages.append)
        self.scene.dropEvent(event)
        self.assertTrue(self.ctrl.project.menu(self.lang.id).background.image.endswith("sprachen.jpg"))
        self.assertEqual(messages, [f"Hintergrund von „{self.lang.name}“ gesetzt."])


class TestInspectorAndViewer(InspectorCase):
    def test_follow_main_and_own(self):
        page = self.page
        self.assertTrue(follows_main_background(self.project, self.menu))
        self.assertEqual(page.lbl_bg_mode.text(), "Wie Hauptmenü")
        self.assertFalse(page.btn_bg_follow.isVisibleTo(page))
        self.assertFalse(page.bg_rows["image"][3].isVisibleTo(page))      # ✕ erst bei eigenem Hintergrund
        self.assertTrue(page.bg_rows["image"][2].isEnabled())             # Wählen geht immer
        page.set_background_file("image", temp_media(self, "kapitel.png"))
        app_instance.processEvents()
        self.assertEqual(page.lbl_bg_mode.text(), "Eigener Hintergrund")
        self.assertTrue(page.btn_bg_follow.isVisibleTo(page))
        self.assertEqual(page.bg_rows["image"][1].text(), "kapitel.png")
        page.btn_bg_follow.click()
        app_instance.processEvents()
        self.assertFalse(self.menu.background.is_set)
        self.assertEqual(page.lbl_bg_mode.text(), "Wie Hauptmenü")

    def test_main_menu_has_no_mode_row(self):
        self._select_node(self.project.main_menu.id)
        self.assertFalse(self.page.lbl_bg_mode.isVisibleTo(self.page))
        self.assertFalse(self.page.btn_bg_follow.isVisibleTo(self.page))

    def test_back_button_names_the_menu_settings(self):
        self._pick(self.menu.buttons[0].id)
        self.assertEqual(self.page.btn_back.text(), "← Menü (Hintergrund, Stil …)")

    def test_drop_on_viewer_sets_menu_background_with_button_selected(self):
        button = self.menu.buttons[0]
        self._pick(button.id)
        mime = file_mime("C:/kapitel.png")
        point = self.designer.mapFromScene(QPointF(960, 540))
        event = QDropEvent(QPointF(point), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        self.designer.dropEvent(event)
        app_instance.processEvents()
        self.assertTrue(self.menu.background.image.endswith("kapitel.png"))
        self.assertEqual(self.ctrl.selected_button, (self.page_id, button.id))    # Auswahl bleibt


class TestSimulatorBackgrounds(SimDiscTestCase):
    def test_background_per_menu_playlist(self):
        from PIL import Image
        project, main, pages, _lang = two_backgrounds()
        images = []
        for name, color in (("bild1.png", "navy"), ("bild2.png", "darkred")):
            path = os.path.join(self.tmp.name, name)
            Image.new("RGB", (64, 36), color).save(path)
            images.append(path)
        main.background.image = images[0]
        for p in pages:
            p.background.image = images[1]
        sim, _disc = self.simulate(project)
        group_pl = menu_group_playlist(len(project.films), 1)
        self.assertEqual(sim.menu_backgrounds, {0: images[0], group_pl: images[1]})
        self.assertEqual(sim.menu_background, images[0])


if __name__ == "__main__":
    unittest.main()
