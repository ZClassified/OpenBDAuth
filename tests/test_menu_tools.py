# tests/test_menu_tools.py
"""
Werkzeuge: Strg+D (Kopie versetzt, Ziele weiterzählen, Versatz wiederholen) und
„Ziele der Reihe nach“ (Inhalts-Buttons in Lesereihenfolge ab einem Ziel belegen).
"""

import unittest

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from core import menu_tools
from core.disc_model import (
    MenuButton, BUTTON_NAV, BUTTON_CHAPTER, BUTTON_AUDIO, BUTTON_SUBTITLE, SUBTITLE_OFF, STYLE_TEXT,
)
from core.disc_rules import target_marker
from core.menu_layout import button_box, CANVAS_W
from gui.node_editor.controller import GraphController
from modules.sim_disc import build_simulation_disc
from tests.project_factory import make_project
from tests.test_inspector_selection import InspectorCase, choose
from tests.test_menu_designer import app_instance


def chapter_page(chapters=12, per_page=8):
    """Kapitelseite 1 (Text-Stil, 4 Spalten) mit K1–K8 und ZURÜCK/WEITER."""
    project = make_project(chapters=chapters, audio=2, subs=2)
    from core.menu_templates import create_chapter_menus
    pages = create_chapter_menus(project, project.films[0].id, per_page=per_page)
    for p in pages:
        p.button_style.kind = STYLE_TEXT
    return project, pages[0]


def markers(project, menu, ids):
    return [target_marker(project, menu, menu.button(i)) for i in ids]


class TestCounting(unittest.TestCase):
    def test_next_target(self):
        project, page = chapter_page()
        film = project.films[0]
        k4 = page.buttons[3]
        self.assertEqual(menu_tools.next_target(project, k4), film.chapters[4].id)
        self.assertEqual(menu_tools.next_target(project, k4, 8), film.chapters[11].id)    # K12, das letzte
        self.assertIsNone(menu_tools.next_target(project, k4, 9))
        u = MenuButton(id="u", kind=BUTTON_SUBTITLE, film_id=film.id, content_ref=film.subtitle_tracks[1].id)
        self.assertEqual(menu_tools.next_target(project, u), SUBTITLE_OFF)      # U2 → Aus
        u.content_ref = SUBTITLE_OFF
        self.assertIsNone(menu_tools.next_target(project, u))
        a = MenuButton(id="a", kind=BUTTON_AUDIO, film_id=film.id, content_ref=film.audio_tracks[0].id)
        self.assertEqual(menu_tools.next_target(project, a), film.audio_tracks[1].id)
        self.assertIsNone(menu_tools.next_target(project, MenuButton(id="n", kind=BUTTON_NAV)))

    def test_reading_order_keeps_skewed_rows(self):
        project, page = chapter_page()
        k = page.buttons[:8]                               # 2 Reihen à 4
        k[1].position[1] += 20                             # leicht schief: bleibt in Reihe 1
        k[4].position[1] -= 20
        shuffled = [k[6], k[1], k[4], k[0], k[7], k[3], k[2], k[5]]
        self.assertEqual([b.id for b in menu_tools.reading_order(page, shuffled)], [b.id for b in k])


class TestDuplicate(unittest.TestCase):
    def test_single_copy_counts_up(self):
        project, page = chapter_page()
        k2 = page.buttons[1]
        k2.size = [300, 50]
        k2.dpad = {"up": page.buttons[0].id}
        (new,) = menu_tools.duplicate_buttons(project, page.id, [k2.id])
        copy = page.button(new)
        x, y, w, _h = button_box(page, k2)
        self.assertEqual(copy.position, [x + 24, y + 24])                       # Versatz ohne Angabe
        self.assertEqual(markers(project, page, [new]), ["K3"])
        self.assertEqual((copy.size, copy.dpad, copy.label), ([300, 50], {}, None))

    def test_first_offset_next_to_or_below(self):
        project, page = chapter_page()
        k1 = page.buttons[0]
        x, y, w, h = button_box(page, k1)
        self.assertEqual(menu_tools.first_offset(page, [k1.id]), (w + 40, 0))
        row = [b.id for b in page.buttons[:4]]                     # ganze Reihe: rechts kein Platz → darunter
        self.assertEqual(menu_tools.first_offset(page, row), (0, h + 40))

    def test_row_counts_by_row_and_stops_at_end(self):
        project, page = chapter_page()
        row = [b.id for b in page.buttons[4:8]]           # K5–K8
        new = menu_tools.duplicate_buttons(project, page.id, row, (0, 100))
        self.assertEqual(markers(project, page, new), ["K9", "K10", "K11", "K12"])
        again = menu_tools.duplicate_buttons(project, page.id, new, (0, 100))
        self.assertEqual(markers(project, page, again), ["K?"] * 4)          # keine Kapitel mehr

    def test_nav_copy_is_unconnected_and_stays_in_picture(self):
        project, page = chapter_page()
        back = next(b for b in page.buttons if b.kind == BUTTON_NAV)
        (new,) = menu_tools.duplicate_buttons(project, page.id, [back.id], (5000, 0))
        copy = page.button(new)
        self.assertEqual((copy.kind, copy.label, copy.target), (BUTTON_NAV, back.label, None))
        x, _y, w, _h = button_box(page, copy)
        self.assertEqual(x + w, CANVAS_W)


class TestSequence(unittest.TestCase):
    def test_assign_in_reading_order(self):
        project, page = chapter_page()
        film = project.films[0]
        content = page.buttons[:8]
        nav = [b for b in page.buttons if b.kind == BUTTON_NAV]
        ids = [b.id for b in content + nav]
        result = menu_tools.assign_sequence(project, page.id, ids, BUTTON_CHAPTER, film.id, film.chapters[6].id)
        self.assertEqual(markers(project, page, [b.id for b in content]),
                         ["K7", "K8", "K9", "K10", "K11", "K12", "K?", "K?"])
        self.assertEqual(len(result), 8)
        self.assertTrue(all(b.target is not None for b in nav))                 # Navigation unberührt

    def test_assign_changes_kind(self):
        project, page = chapter_page()
        film = project.films[0]
        ids = [b.id for b in page.buttons[:3]]
        page.buttons[0].label = "EIGEN"
        menu_tools.assign_sequence(project, page.id, ids, BUTTON_SUBTITLE, film.id, None)
        self.assertEqual(markers(project, page, ids), ["U1", "U2", "U–"])
        self.assertIsNone(page.buttons[0].label)


class TestController(unittest.TestCase):
    def setUp(self):
        self.project, self.page = chapter_page()
        self.ctrl = GraphController(self.project)
        self.hints = []
        self.ctrl.tool_hint.connect(self.hints.append)

    @property
    def menu(self):
        return self.ctrl.project.menu(self.page.id)

    def test_chain_repeats_offset(self):
        k1 = self.menu.buttons[0]
        self.ctrl.select_button(self.page.id, k1.id)
        steps = self.ctrl.undo_stack.count()
        (c1,) = self.ctrl.duplicate_selection(self.page.id)
        self.assertEqual(self.ctrl.undo_stack.count(), steps + 1)
        self.assertEqual(self.ctrl.selection_in(self.page.id), [c1])
        self.assertIn("Kopie liegt daneben", self.hints[-1])
        self.assertIn("(K3)", self.hints[-1])
        # Kopie an ihren Platz: 500 px rechts vom Original
        x, y, w, _h = button_box(self.menu, self.menu.button(k1.id))
        self.assertEqual(self.menu.button(c1).position, [x + w + 40, y])       # erste Kopie direkt daneben
        self.ctrl.move_menu_items(self.page.id, positions={c1: (x + 500, y)})
        (c2,) = self.ctrl.duplicate_selection(self.page.id)
        self.assertEqual(self.menu.button(c2).position, [x + 1000, y])
        self.assertEqual(markers(self.ctrl.project, self.menu, [c1, c2]), ["K2", "K3"])
        self.assertTrue(self.hints[-1].startswith("Strg+D: nächste im gleichen Abstand (K4)"))
        # andere Auswahl: Folge zu Ende, Hinweis weg, nächste Kopie wieder leicht versetzt
        self.ctrl.select_button(self.page.id, k1.id)
        self.assertEqual(self.hints[-1], "")
        (c3,) = self.ctrl.duplicate_selection(self.page.id)
        self.assertEqual(self.menu.button(c3).position, [x + w + 40, y])

    def test_assign_one_step(self):
        film = self.ctrl.project.films[0]
        ids = [b.id for b in self.menu.buttons[:4]]
        steps = self.ctrl.undo_stack.count()
        self.ctrl.assign_sequence(self.page.id, ids, BUTTON_CHAPTER, film.id, film.chapters[8].id)
        self.assertEqual(self.ctrl.undo_stack.count(), steps + 1)
        self.assertEqual(markers(self.ctrl.project, self.menu, ids), ["K9", "K10", "K11", "K12"])
        self.ctrl.undo_stack.undo()
        self.assertEqual(markers(self.ctrl.project, self.menu, ids), ["K1", "K2", "K3", "K4"])


class TestSimulation(unittest.TestCase):
    def test_duplicated_page_simulates_clean(self):
        import tempfile, os
        from modules.bdsim.disc import load_disc
        from modules.bdsim.explore import explore, format_report
        project, page = chapter_page(chapters=12, per_page=4)       # 3 Seiten à 4 Kapitel
        row = [b.id for b in page.buttons[:4]]
        menu_tools.duplicate_buttons(project, page.id, row, (0, 120))    # K5–K8 zusätzlich auf Seite 1
        with tempfile.TemporaryDirectory() as tmp:
            sim = build_simulation_disc(project, os.path.join(tmp, "SIM"))
            disc = load_disc(sim.root)
            report = explore(disc)
            self.assertTrue(report.ok, format_report(disc, [report]))


class TestStudio(InspectorCase):
    def test_ctrl_d_in_viewer_and_copy_hint(self):
        k1 = self.menu.buttons[0]
        self._pick(k1.id)
        self.designer.setFocus()
        QTest.keyClick(self.designer, Qt.Key_D, Qt.ControlModifier)
        app_instance.processEvents()
        (copy,) = self.ctrl.selection_in(self.page_id)
        self.assertEqual(target_marker(self.project, self.menu, self.menu.button(copy)), "K2")
        self.assertIn("Kopie liegt daneben", self.win.viewer.caption.text())
        QTest.keyClick(self.designer, Qt.Key_C, Qt.ControlModifier)
        app_instance.processEvents()
        self.assertIn("Kopieren: Strg+D", self.win.viewer.caption.text())
        self.assertEqual(len(self.menu.buttons), 8)              # 6 Kapitel + ZURÜCK + Kopie

    def test_duplicate_button_in_inspector(self):
        self._pick(self.menu.buttons[2].id)
        self.page.btn_duplicate.click()
        app_instance.processEvents()
        (copy,) = self.ctrl.selection_in(self.page_id)
        self.assertEqual(target_marker(self.project, self.menu, self.menu.button(copy)), "K4")

    def test_sequence_row(self):
        content = [b.id for b in self.menu.buttons if b.is_content]
        nav = [b.id for b in self.menu.buttons if not b.is_content]
        self._pick(*(content + nav))
        page = self.page
        self.assertEqual(page.mode, "multi")
        self.assertEqual(page.lbl_seq_preview.text(), "6 Buttons → K1–K6 · Navigations-Buttons bleiben (1)")
        film = self.project.films[0]
        choose(page.combo_seq_start, film.chapters[3].id)
        self.assertEqual(page.lbl_seq_preview.text(),
                         "6 Buttons → K4–K6 · 3 ohne Ziel (keine weiteren) · Navigations-Buttons bleiben (1)")
        # Maus über der Zeile: Nummern im Viewer
        page._preview_order(True)
        self.assertEqual(len(self.designer.order_items), 6)
        page._preview_order(False)
        self.assertEqual(self.designer.order_items, [])
        choose(page.combo_seq_kind, BUTTON_AUDIO)
        self.assertEqual(page.lbl_seq_preview.text(),
                         "6 Buttons → A1–A2 · 4 ohne Ziel (keine weiteren) · Navigations-Buttons bleiben (1)")
        page.btn_seq_assign.click()
        app_instance.processEvents()
        self.assertEqual(markers(self.project, self.menu, content), ["A1", "A2", "A?", "A?", "A?", "A?"])


if __name__ == "__main__":
    unittest.main()


class TestGridAndDistribute(unittest.TestCase):
    """v1.14.1: Als Raster anordnen, verteilen."""

    def test_grid_defaults_from_existing_layout(self):
        project, page = chapter_page()
        ids = [b.id for b in page.buttons[:8]]                      # Vorlage: 2 Reihen à 4, Abstände 40/25
        self.assertEqual(menu_tools.grid_defaults(page, ids), (4, 40, 25))
        single_row = ids[:3]
        self.assertEqual(menu_tools.grid_defaults(page, single_row)[0], 3)

    def test_grid_from_scattered_buttons(self):
        project, page = chapter_page()
        k = page.buttons[:6]
        scattered = [(900, 700), (100, 120), (700, 130), (300, 690), (1300, 110), (120, 400)]
        for b, pos in zip(k, scattered):
            b.position = list(pos)
        k[0].size = [200, 40]                                       # kleiner: sitzt mittig in seiner Zelle
        menu_tools.arrange_grid(project, page.id, [b.id for b in k], 3, 20, 10)
        # Lesereihenfolge vorher: K2, K3, K5 | K6 | K4, K1 → Raster 3 Spalten ab (100, 110)
        cell_w, cell_h = 380, 70
        expected = {k[1].id: (100, 110), k[2].id: (100 + cell_w + 20, 110), k[4].id: (100 + 2 * (cell_w + 20), 110),
                    k[5].id: (100, 110 + cell_h + 10), k[3].id: (100 + cell_w + 20, 110 + cell_h + 10),
                    k[0].id: (100 + 2 * (cell_w + 20) + 90, 110 + cell_h + 10 + 15)}
        for bid, pos in expected.items():
            self.assertEqual(tuple(page.button(bid).position), pos)

    def test_grid_stays_in_picture(self):
        project, page = chapter_page()
        ids = [b.id for b in page.buttons[:8]]
        page.buttons[0].position = [1800, 1000]
        for b in page.buttons[1:8]:
            b.position = [1700, 1000]
        menu_tools.arrange_grid(project, page.id, ids, 2, 40, 25)
        for b in page.buttons[:8]:
            x, y, w, h = button_box(page, b)
            self.assertTrue(0 <= x and x + w <= 1920 and 0 <= y and y + h <= 1080, (x, y))

    def test_distribute_keeps_ends(self):
        project, page = chapter_page()
        a, b, c, d = page.buttons[:4]
        for btn, x in zip((a, b, c, d), (100, 520, 600, 1400)):
            btn.position = [x, 300]
        menu_tools.distribute(project, page.id, [d.id, b.id, a.id, c.id], horizontal=True)
        xs = [page.button(x.id).position[0] for x in (a, b, c, d)]
        self.assertEqual((xs[0], xs[3]), (100, 1400))
        gaps = [xs[i + 1] - (xs[i] + 380) for i in range(3)]
        self.assertLessEqual(max(gaps) - min(gaps), 1)
        self.assertEqual({page.button(x.id).position[1] for x in (a, b, c, d)}, {300})
        self.assertEqual(menu_tools.distribute_positions(page, [a.id, b.id], True), {})   # erst ab drei


class TestGridInStudio(InspectorCase):
    def test_grid_and_distribute_buttons(self):
        content = [b.id for b in self.menu.buttons if b.is_content]      # K1–K6 im Raster 4 + 2
        self._pick(*content)
        page = self.page
        self.assertEqual((page.spin_grid_cols.value(), page.spin_gap_x.value(), page.spin_gap_y.value()),
                         (4, 40, 25))
        self.assertTrue(page.btn_dist_h.isEnabled())
        page.spin_grid_cols.setValue(3)
        steps = self.ctrl.undo_stack.count()
        page.btn_grid.click()
        app_instance.processEvents()
        self.assertEqual(self.ctrl.undo_stack.count(), steps + 1)
        rows = menu_tools.reading_rows(self.menu, [self.menu.button(b) for b in content])
        self.assertEqual([len(r) for r in rows], [3, 3])
        self.assertEqual(page.spin_grid_cols.value(), 3)                  # eigene Eingabe bleibt stehen
        page._preview_order(True, content_only=False)
        self.assertEqual(len(self.designer.order_items), 6)
        page._preview_order(False)
        self._pick(*content[:2])
        self.assertFalse(page.btn_dist_h.isEnabled())
