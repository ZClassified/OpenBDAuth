# tests/test_menu_generator.py
"""
Generator: Buttons im aufgezogenen Bereich, Folgeseiten mit ZURÜCK/HAUPTMENÜ/
WEITER, freie Plätze beim Ergänzen, Grenzen des Menüstroms, Preflight „Ergänzen …“, Fenster und Viewer.
"""

import os
import tempfile
import unittest
from unittest import mock

from PySide6.QtCore import Qt, QEvent, QPointF, QTimer

from core import menu_generator as gen
from core.disc_edit import add_menu, set_chapter_times
from core.disc_model import BUTTON_NAV, BUTTON_CHAPTER, BUTTON_AUDIO, STYLE_SHAPE
from core.disc_rules import Source, target_marker
from core.menu_layout import button_box
from core.menu_templates import LABEL_BACK, LABEL_MAIN, LABEL_NEXT, missing_chapters
from core.preflight import run_preflight, WARNING, ERROR, ACTION_GENERATOR
from gui.node_editor.controller import GraphController
from modules.sim_disc import build_simulation_disc
from tests.project_factory import make_project
from tests.test_inspector_selection import InspectorCase
from tests.test_menu_designer import app_instance

AREA = (200, 150, 1500, 600)          # ZURÜCK eines neuen Menüs liegt oben links außerhalb


def chapter_project(chapters=30):
    """Hauptmenü → leeres Menü „Kapitel“ (Stil Form, nur ZURÜCK)."""
    project = make_project(chapters=chapters)
    main = project.main_menu
    menu = add_menu(project, "Kapitel", (720.0, 300.0))
    from core.disc_edit import add_nav_button
    add_nav_button(project, main.id, "KAPITEL", menu.id)
    menu.buttons[0].target = main.id                      # ZURÜCK
    menu.buttons[0].position = [96, 900]
    return project, menu


def nav(menu, label):
    return next((b for b in menu.buttons if b.kind == BUTTON_NAV and b.label == label), None)


def markers(project, menu):
    return [target_marker(project, menu, b) for b in menu.buttons if b.is_content]


class TestSettings(unittest.TestCase):
    def test_defaults_fill_area_evenly(self):
        project, menu = chapter_project(30)
        s = gen.default_settings(project, menu, AREA)
        self.assertEqual((s.kind, s.first_ref, s.last_ref), (BUTTON_CHAPTER, "ch1", "ch30"))
        self.assertEqual(s.cols, 4)                        # 300 px breite Linien, 40 px Abstand
        self.assertEqual(s.rows, 8)                        # nur so viele Zeilen wie nötig (30 / 4)
        project.films[0].chapters = []
        project.films[0].audio_tracks = make_project(audio=2).films[0].audio_tracks
        self.assertEqual(gen.default_settings(project, menu, AREA).kind, BUTTON_AUDIO)

    def test_only_missing_and_reversed_range(self):
        project, menu = chapter_project(10)
        s = gen.default_settings(project, menu, AREA)
        s.first_ref, s.last_ref = "ch8", "ch3"
        self.assertEqual(gen.target_range(project, s, menu), [f"ch{i}" for i in range(3, 9)])
        gen.generate(project, menu.id, s)
        s2 = gen.default_settings(project, menu, AREA)       # K3–K8 sind vergeben
        self.assertEqual(gen.target_range(project, s2, menu), ["ch1", "ch2", "ch9", "ch10"])
        s2.only_missing = False
        self.assertEqual(len(gen.target_range(project, s2, menu)), 10)


class TestGenerate(unittest.TestCase):
    def test_pages_wiring_and_simulation(self):
        project, menu = chapter_project(30)
        s = gen.default_settings(project, menu, AREA)
        s.cols, s.rows = 4, 3
        result = gen.plan(project, menu, s)
        self.assertEqual([len(c) for c in result.chunks], [12, 12, 6])
        self.assertEqual(result.page_names, ["Kapitel 1/3", "Kapitel 2/3", "Kapitel 3/3"])
        menu.background.image = "C:/kapitel.png"
        new = gen.generate(project, menu.id, s)
        p2, p3 = (project.menu(i) for i in new)
        self.assertEqual(menu.name, "Kapitel 1/3")
        self.assertEqual(markers(project, menu), [f"K{i}" for i in range(1, 13)])
        self.assertEqual(markers(project, p3), [f"K{i}" for i in range(25, 31)])
        self.assertEqual(nav(menu, LABEL_NEXT).target, p2.id)
        self.assertEqual((nav(p2, LABEL_BACK).target, nav(p2, LABEL_MAIN).target, nav(p2, LABEL_NEXT).target),
                         (menu.id, project.main_menu.id, p3.id))
        self.assertIsNone(nav(p3, LABEL_NEXT))
        self.assertEqual(nav(p2, LABEL_BACK).position, nav(menu, LABEL_BACK).position)   # wie auf Seite 1
        self.assertEqual((p2.background.image, p2.button_style.kind), ("C:/kapitel.png", STYLE_SHAPE))
        self.assertEqual(gen.remembered(project, p3.id).area, AREA)
        self.assertIn(p3.id, project.view.node_positions)
        # Raster: gleichmäßig im Bereich, alles im Bild
        xs = sorted({button_box(menu, b)[0] for b in menu.buttons if b.is_content})
        self.assertEqual(len(xs), 4)
        with tempfile.TemporaryDirectory() as tmp:
            from modules.bdsim.disc import load_disc
            from modules.bdsim.explore import explore, format_report
            disc = load_disc(build_simulation_disc(project, os.path.join(tmp, "SIM")).root)
            report = explore(disc)
            self.assertTrue(report.ok, format_report(disc, [report]))
        self.assertEqual(missing_chapters(project, project.films[0].id), [])

    def test_inserted_before_existing_next_page(self):
        project, menu = chapter_project(30)
        later = add_menu(project, "Extras", (1100.0, 300.0))
        later.buttons[0].target = menu.id                  # ZURÜCK → Kapitel
        from core.disc_edit import add_nav_button
        add_nav_button(project, menu.id, LABEL_NEXT, later.id)
        nav(menu, LABEL_NEXT).position = [1500, 900]
        s = gen.default_settings(project, menu, AREA)
        s.cols, s.rows = 4, 5
        (p2,) = gen.generate(project, menu.id, s)
        page = project.menu(p2)
        self.assertEqual(nav(menu, LABEL_NEXT).target, p2)
        self.assertEqual(nav(page, LABEL_NEXT).target, later.id)
        self.assertEqual(later.buttons[0].target, p2)        # Extras führt zur neuen Seite zurück

    def test_fills_free_cells_only(self):
        project, menu = chapter_project(30)
        s = gen.default_settings(project, menu, AREA)
        s.cols, s.rows = 4, 3
        s.last_ref = "ch6"
        gen.generate(project, menu.id, s)                  # K1–K6 in den ersten 6 Plätzen
        s.first_ref, s.last_ref = "ch7", "ch30"
        self.assertEqual(len(gen.free_cells(menu, s)), 6)
        result = gen.plan(project, menu, s)
        self.assertEqual([len(c) for c in result.chunks], [6, 12, 6])
        gen.generate(project, menu.id, s)
        boxes = [button_box(menu, b) for b in menu.buttons if b.is_content]
        self.assertEqual(len(set(boxes)), 12)               # nichts übereinander


class TestLimits(unittest.TestCase):
    def test_page_limit(self):
        project, menu = chapter_project(30)
        s = gen.default_settings(project, menu, AREA)
        s.cols, s.rows = 6, 8                              # 48 + Navigation > 50
        self.assertTrue(gen.plan(project, menu, s).over_page_limit)
        s.cols, s.rows = 5, 9                              # 45 + 3 = 48
        self.assertFalse(gen.plan(project, menu, s).over_page_limit)
        cols, rows = gen.suggest_grid(menu, (0, 0, 1920, 1080))
        self.assertLessEqual(cols * rows, 47)

    def test_source_page_never_exceeds_limit(self):
        project, menu = chapter_project(60)
        from core.disc_model import MenuButton
        for i in range(45):                                # 45 Buttons + ZURÜCK = 46 auf der Seite
            menu.buttons.append(MenuButton(id=f"x{i}", kind=BUTTON_NAV, label="X", position=[0, 0], size=[8, 8]))
        s = gen.default_settings(project, menu, AREA)
        s.cols, s.rows = 5, 8
        result = gen.plan(project, menu, s)
        self.assertEqual(len(result.chunks[0]), 3)         # 46 + 3 + WEITER = 50
        gen.generate(project, menu.id, s)
        self.assertEqual(len(menu.buttons), 50)
        self.assertTrue(all(len(m.buttons) <= 50 for m in project.menus))

    def test_graphics_budget_warning(self):
        project, menu = chapter_project(30)
        s = gen.default_settings(project, menu, AREA)
        gen.generate(project, menu.id, s)
        self.assertFalse([i for i in run_preflight(project) if "Button-Grafik" in i.message])
        with mock.patch.object(gen, "GRAPHICS_BUDGET", 100_000):
            self.assertTrue(gen.plan(project, menu, s).over_graphics_budget)
            (issue,) = [i for i in run_preflight(project) if "Button-Grafik" in i.message]
            self.assertEqual(issue.level, WARNING)

    def test_many_buttons_hint_and_limit(self):
        from core.disc_model import MenuButton
        from core.preflight import INFO
        project, menu = chapter_project(60)
        s = gen.default_settings(project, menu, (0, 0, 1920, 1080))
        s.only_missing = False
        refs = gen.target_range(project, s, menu)

        def page_issues():
            start = f"Menü „{menu.name}“ hat "
            return [(i.level, i.message) for i in run_preflight(project)
                    if i.message.startswith(start) and "Form-Buttons" not in i.message]

        for ref in refs[:40]:                              # 40 + ZURÜCK = 41
            menu.buttons.append(MenuButton(id=f"b{ref}", kind=BUTTON_CHAPTER, film_id=project.films[0].id,
                                           content_ref=ref, position=[0, 0]))
        ((level, text),) = page_issues()
        self.assertEqual(level, INFO)
        self.assertIn("mit der Fernbedienung mühsam", text)
        for ref in refs[40:50]:                            # 51
            menu.buttons.append(MenuButton(id=f"b{ref}", kind=BUTTON_CHAPTER, film_id=project.films[0].id,
                                           content_ref=ref, position=[0, 0]))
        ((level, text),) = page_issues()
        self.assertEqual(level, ERROR)
        self.assertIn("höchstens 50", text)


class TestPreflightAction(unittest.TestCase):
    def test_missing_chapters_opens_generator_preset(self):
        project, menu = chapter_project(20)
        s = gen.default_settings(project, menu, AREA)
        s.cols, s.rows, s.last_ref = 4, 3, "ch12"
        gen.generate(project, menu.id, s)
        (issue,) = [i for i in run_preflight(project) if i.action == ACTION_GENERATOR]
        self.assertEqual((issue.node_id, issue.film_id), (menu.id, project.films[0].id))
        self.assertIn("Kapitel 13–20", issue.message)
        refs = [ch.id for ch in missing_chapters(project, issue.film_id)]
        preset = gen.preset_for_missing(project, menu, issue.film_id, refs)
        self.assertEqual((preset.area, preset.cols, preset.rows, preset.first_ref, preset.last_ref),
                         (AREA, 4, 3, "ch13", "ch20"))
        new = gen.generate(project, menu.id, preset)       # Seite voll → alles auf eine neue Seite
        self.assertEqual(markers(project, project.menu(new[0])), [f"K{i}" for i in range(13, 21)])
        self.assertFalse([i for i in run_preflight(project) if i.action == ACTION_GENERATOR])


class TestStudio(InspectorCase):
    def setUp(self):
        super().setUp()
        film = self.project.films[0]
        set_chapter_times(film, [f"00:{i:02d}:00.000" for i in range(20)])   # K7–K20 fehlen im Menü
        self.ctrl.changed.emit()
        app_instance.processEvents()

    def _drag_area(self, a: QPointF, b: QPointF):
        self._mouse(QEvent.MouseButtonPress, a)
        self._mouse(QEvent.MouseMove, b, buttons=Qt.LeftButton)
        self._mouse(QEvent.MouseButtonRelease, b, buttons=Qt.NoButton)

    def test_area_pick_dialog_and_create(self):
        areas = []
        self.designer.generator_area.disconnect()
        self.designer.generator_area.connect(lambda m, area: areas.append((m, area)))
        self.win.viewer.btn_generator.click()
        self.assertIn("Bereich aufziehen", self.win.viewer.caption.text())
        self._drag_area(QPointF(200, 700), QPointF(1700, 1000))
        app_instance.processEvents()
        ((menu_id, area),) = areas
        self.assertEqual(menu_id, self.page_id)
        for got, want in zip(area, (200, 700, 1500, 300)):
            self.assertAlmostEqual(got, want, delta=4)          # Umrechnung Bildschirm → 1920×1080
        self.assertNotIn("Bereich aufziehen", self.win.viewer.caption.text())

        def accept():
            dialog = self.win._generator_dialog
            self.texts.append(dialog.lbl_summary.text())
            dialog.spin_cols.setValue(4)
            dialog.spin_rows.setValue(2)
            self.texts.append(dialog.lbl_summary.text())
            self.texts.append(dialog.lbl_notes.text())
            dialog.accept()

        self.texts = []
        steps = self.ctrl.undo_stack.count()
        QTimer.singleShot(0, accept)
        pages = self.win.open_generator(self.page_id, area=areas[0][1])
        self.assertEqual(self.ctrl.undo_stack.count(), steps + 1)
        self.assertTrue(self.texts[0].startswith("14 Buttons"))
        # ZURÜCK liegt im Bereich und belegt zwei Plätze: sie bleiben frei
        self.assertEqual(self.texts[1], "14 Buttons: 6 auf dieser Seite, 8 auf einer neuen Seite „Kapitel 2/2“.")
        self.assertIn("2 Plätze im Bereich sind schon belegt", self.texts[2])
        self.assertEqual(len(pages), 1)
        self.assertEqual(len(self.ctrl.selection_in(self.page_id)), 6)        # neue Buttons ausgewählt
        self.ctrl.undo_stack.undo()
        self.assertEqual(len(self.project.menus), 2)

    def test_escape_cancels_area_pick(self):
        from PySide6.QtTest import QTest
        self.win.viewer.btn_generator.click()
        QTest.keyClick(self.designer, Qt.Key_Escape)
        self.assertIsNone(self.designer._area_pick)
        self.assertNotIn("Bereich aufziehen", self.win.viewer.caption.text())

    def test_preflight_click_opens_preset(self):
        self.win.open_export_dialog()
        dialog = self.win._export_dialog
        app_instance.processEvents()
        items = [dialog.issue_list.item(i) for i in range(dialog.issue_list.count())]
        (item,) = [it for it in items if "Ergänzen" in it.text()]
        seen = []

        def cancel():
            gen_dialog = self.win._generator_dialog
            seen.append((gen_dialog.combo_first.currentData(), gen_dialog.combo_last.currentData()))
            gen_dialog.reject()

        QTimer.singleShot(50, cancel)
        dialog._on_issue_clicked(item)
        for _ in range(20):
            app_instance.processEvents()
            if seen:
                break
            QTimer.singleShot(20, lambda: None)
            from PySide6.QtTest import QTest
            QTest.qWait(30)
        film = self.project.films[0]
        self.assertEqual(seen, [(film.chapters[6].id, film.chapters[19].id)])
        dialog.close()


if __name__ == "__main__":
    unittest.main()
