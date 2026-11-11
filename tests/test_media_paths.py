# tests/test_media_paths.py
"""Tests für relative Pfade in der Projektdatei, das Wiederfinden beim Laden und „Medien neu verknüpfen“ (v1.17.0)."""

import json
import os
import string
import sys
import tempfile
import unittest

from core.disc_model import Track, load_disc_project
from core.media_paths import (
    MediaRef, MEDIA_VIDEO, MEDIA_AUDIO, MEDIA_BG_IMAGE, media_refs, missing_media, set_media_path,
    to_stored, resolve_stored, index_folder, plan_relink, apply_relink)
from core.preflight import run_preflight, ERROR, ACTION_RELINK
from tests.project_factory import text_starter


def touch(path: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").close()
    return path.replace("\\", "/")


class MediaPathsBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name.replace("\\", "/")

    def tearDown(self):
        self._tmp.cleanup()

    def project_with_files(self):
        """Projektordner „projekt“ mit Video und Ton darin, Hintergrund in einem Nachbarordner „cover“."""
        project = text_starter()
        film = project.films[0]
        film.video_base = touch(f"{self.root}/projekt/film.264")
        film.audio_tracks = [Track(id="a1", path=touch(f"{self.root}/projekt/ton/de.wav"), lang="deu")]
        project.main_menu.background.image = touch(f"{self.root}/cover/Menü.jpg")
        return project, f"{self.root}/projekt/disc.bdproj"


class TestStoredPaths(MediaPathsBase):
    def test_saved_relative_to_project_folder(self):
        project, path = self.project_with_files()
        project.save_to_file(path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["films"][0]["video_base"], "film.264")
        self.assertEqual(data["films"][0]["audio_tracks"][0]["path"], "ton/de.wav")
        self.assertEqual(data["menus"][0]["background"]["image"], "../cover/Menü.jpg")

    def test_memory_stays_absolute(self):
        project, path = self.project_with_files()
        project.save_to_file(path)
        self.assertEqual(project.films[0].video_base, f"{self.root}/projekt/film.264")

    def test_load_resolves_to_absolute(self):
        project, path = self.project_with_files()
        project.save_to_file(path)
        loaded = load_disc_project(path)
        self.assertEqual(loaded, project)
        self.assertEqual(missing_media(loaded), [])

    def test_whole_folder_moved(self):
        """Projekt und Medien zusammen verschoben (anderer Rechner, anderer Ordner): alles wird gefunden."""
        project, path = self.project_with_files()
        project.save_to_file(path)
        os.rename(self.root, self.root + "_neu")
        try:
            loaded = load_disc_project(f"{self.root}_neu/projekt/disc.bdproj")
            self.assertEqual(missing_media(loaded), [])
            self.assertEqual(loaded.films[0].video_base, f"{self.root}_neu/projekt/film.264")
        finally:
            os.rename(self.root + "_neu", self.root)

    def test_other_drive_stays_absolute(self):
        if sys.platform != "win32":
            self.skipTest("Laufwerksbuchstaben gibt es nur unter Windows")
        own = os.path.splitdrive(self.root)[0].upper()
        other = next(f"{d}:" for d in "QRSTUVWXYZ" if f"{d}:" != own)
        self.assertEqual(to_stored(f"{other}/clips/film.264", f"{self.root}/projekt"), f"{other}/clips/film.264")

    def test_empty_and_output_path(self):
        project, path = self.project_with_files()
        project.films[0].video_mvc = None
        project.settings.output_path = f"{self.root}/projekt/ausgabe"
        project.save_to_file(path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertIsNone(data["films"][0]["video_mvc"])
        self.assertEqual(data["settings"]["output_path"], "ausgabe")
        self.assertEqual(load_disc_project(path).settings.output_path, f"{self.root}/projekt/ausgabe")


class TestDriveLetter(MediaPathsBase):
    def test_absolute_path_found_on_project_drive(self):
        """Externe SSD auf Rechner A als G:, auf Rechner B als F: – ein alter absoluter Pfad wird auf dem Laufwerk des Projekts gesucht."""
        if sys.platform != "win32":
            self.skipTest("Laufwerksbuchstaben gibt es nur unter Windows")
        drive, rest = os.path.splitdrive(touch(f"{self.root}/projekt/film.264"))
        absent = next(f"{d}:" for d in reversed(string.ascii_uppercase)
                      if f"{d}:".lower() != drive.lower() and not os.path.exists(f"{d}:/"))
        self.assertEqual(resolve_stored(absent + rest, f"{self.root}/projekt"), drive + rest)

    def test_missing_everywhere_keeps_path(self):
        self.assertEqual(resolve_stored("C:/gibt/es/nicht.264", self.root), "C:/gibt/es/nicht.264")


class TestRelink(MediaPathsBase):
    def ref(self, path, kind=MEDIA_VIDEO, owner="f1", track=None):
        return MediaRef(kind, owner, track, path)

    def test_found_by_name_in_subfolder(self):
        new = touch(f"{self.root}/Backup/Kurzfilme/film.264")
        result = plan_relink([self.ref("G:/Kurzfilme/film.264")], index_folder(self.root))
        self.assertEqual(result.found, {(MEDIA_VIDEO, "f1", None): new})

    def test_not_found(self):
        touch(f"{self.root}/anders.264")
        result = plan_relink([self.ref("G:/film.264")], index_folder(self.root))
        self.assertEqual(result.not_found, [(MEDIA_VIDEO, "f1", None)])

    def test_name_is_case_insensitive(self):
        new = touch(f"{self.root}/FILM.264")
        result = plan_relink([self.ref("G:/x/film.264")], index_folder(self.root))
        self.assertEqual(result.found[(MEDIA_VIDEO, "f1", None)], new)

    def test_longer_matching_folders_win(self):
        touch(f"{self.root}/Alt/menu.jpg")
        right = touch(f"{self.root}/Cover/menu.jpg")
        result = plan_relink([self.ref("G:/Cover/menu.jpg", MEDIA_BG_IMAGE, "m1")], index_folder(self.root))
        self.assertEqual(result.found[(MEDIA_BG_IMAGE, "m1", None)], right)

    def test_tie_resolved_by_move_of_other_files(self):
        """Zwei gleich gute Treffer: die Verschiebung, die eine eindeutige Datei zeigt, entscheidet."""
        touch(f"{self.root}/v1/ton/de.wav")
        right = touch(f"{self.root}/v2/ton/de.wav")
        touch(f"{self.root}/v2/film.264")
        refs = [self.ref("G:/Projekt/film.264"), self.ref("G:/Projekt/ton/de.wav", MEDIA_AUDIO, "f1", "a1")]
        result = plan_relink(refs, index_folder(self.root))
        self.assertEqual(result.found[(MEDIA_AUDIO, "f1", "a1")], right)
        self.assertEqual(result.ambiguous, {})

    def test_unresolved_tie_is_ambiguous(self):
        a = touch(f"{self.root}/v1/de.wav")
        b = touch(f"{self.root}/v2/de.wav")
        result = plan_relink([self.ref("G:/de.wav", MEDIA_AUDIO, "f1", "a1")], index_folder(self.root))
        self.assertEqual(sorted(result.ambiguous[(MEDIA_AUDIO, "f1", "a1")]), sorted([a, b]))
        self.assertEqual(result.found, {})

    def test_recycle_bin_is_skipped(self):
        touch(f"{self.root}/$RECYCLE.BIN/film.264")
        result = plan_relink([self.ref("G:/film.264")], index_folder(self.root))
        self.assertEqual(result.not_found, [(MEDIA_VIDEO, "f1", None)])

    def test_apply_sets_all_kinds(self):
        project, _path = self.project_with_files()
        film, menu = project.films[0], project.main_menu
        apply_relink(project, {(MEDIA_VIDEO, film.id, None): "X:/v.264",
                               (MEDIA_AUDIO, film.id, "a1"): "X:/a.wav",
                               (MEDIA_BG_IMAGE, menu.id, None): "X:/b.jpg"})
        self.assertEqual([r.path for r in media_refs(project)], ["X:/v.264", "X:/a.wav", "X:/b.jpg"])
        self.assertFalse(set_media_path(project, (MEDIA_AUDIO, film.id, "gibt_es_nicht"), "X:/c.wav"))


class TestPreflightMissing(MediaPathsBase):
    def test_missing_file_is_an_error_with_relink_action(self):
        project, _path = self.project_with_files()
        os.remove(project.main_menu.background.image)
        issues = [i for i in run_preflight(project) if i.action == ACTION_RELINK]
        self.assertEqual([(i.level, i.node_id) for i in issues], [(ERROR, project.main_menu.id)])
        self.assertIn("Menü.jpg", issues[0].message)


class TestRelinkDialog(MediaPathsBase):
    def setUp(self):
        super().setUp()
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication(sys.argv)
        from gui.node_editor.controller import GraphController
        project = text_starter()
        project.films[0].video_base = "G:/Kurzfilme/film.264"
        project.main_menu.background.image = "G:/Cover/Menü.jpg"
        self.ctrl = GraphController(project)
        self.film, self.menu = project.films[0], project.main_menu

    def dialog(self):
        from gui.studio.relink_dialog import RelinkDialog
        dialog = RelinkDialog(self.ctrl)
        self.addCleanup(dialog.close)
        return dialog

    def test_search_and_apply_is_one_undo_step(self):
        video = touch(f"{self.root}/Kurzfilme/film.264")
        image = touch(f"{self.root}/Cover/Menü.jpg")
        dialog = self.dialog()
        self.assertEqual(dialog.tree.topLevelItemCount(), 2)
        self.assertFalse(dialog.btn_apply.isEnabled())
        dialog.search_in(self.root)
        self.assertTrue(dialog.btn_apply.isEnabled())
        self.assertTrue(dialog.tree.topLevelItem(0).text(2).startswith("✓"))
        dialog.accept()
        self.assertEqual(self.ctrl.project.films[0].video_base, video)
        self.assertEqual(self.ctrl.project.main_menu.background.image, image)
        self.assertEqual(missing_media(self.ctrl.project), [])
        self.assertEqual(self.ctrl.undo_stack.count(), 1)
        self.ctrl.undo_stack.undo()
        self.assertEqual(self.ctrl.project.films[0].video_base, "G:/Kurzfilme/film.264")

    def test_partly_found_and_manual_pick(self):
        touch(f"{self.root}/Kurzfilme/film.264")
        dialog = self.dialog()
        dialog.search_in(self.root)
        self.assertEqual(dialog.tree.topLevelItem(1).text(2), "fehlt")
        image = touch(f"{self.root}/woanders/Menü.jpg")
        dialog.set_path((MEDIA_BG_IMAGE, self.menu.id, None), image)
        self.assertEqual(dialog.lbl_info.text(), dialog.t("relink_all_found"))
        dialog.accept()
        self.assertEqual(self.ctrl.project.main_menu.background.image, image)

    def test_cancel_changes_nothing(self):
        touch(f"{self.root}/Kurzfilme/film.264")
        dialog = self.dialog()
        dialog.search_in(self.root)
        dialog.reject()
        self.assertEqual(self.ctrl.project.films[0].video_base, "G:/Kurzfilme/film.264")
        self.assertEqual(self.ctrl.undo_stack.count(), 0)

    def test_missing_file_marked_in_inspector(self):
        from PySide6.QtWidgets import QLabel
        from gui.studio.inspector import show_file
        t = lambda key, **kw: {"studio_none": "–", "studio_file_missing": "{name} – fehlt"}[key].format(**kw)
        label = QLabel()
        show_file(label, "G:/Kurzfilme/film.264", t)
        self.assertEqual(label.text(), "film.264 – fehlt")
        show_file(label, touch(f"{self.root}/film.264"), t)
        self.assertEqual(label.text(), "film.264")
        show_file(label, None, t)
        self.assertEqual(label.text(), "–")

    def test_issue_click_opens_relink(self):
        from gui.studio.export_dialog import ExportDialog
        dialog = ExportDialog(self.ctrl)
        self.addCleanup(dialog.close)
        opened = []
        dialog.open_relink.connect(lambda: opened.append(True))
        items = [dialog.issue_list.item(i) for i in range(dialog.issue_list.count())]
        relink = [it for it in items if "Datei fehlt" in it.text()]
        self.assertEqual(len(relink), 2)
        dialog._on_issue_clicked(relink[0])
        self.assertEqual(opened, [True])


if __name__ == "__main__":
    unittest.main()
