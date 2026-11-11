# tests/test_button_sizes.py
"""
Größe einzelner Buttons (v1.11.1):
- Modell: eigene Größe an der festen Position (obere linke Ecke, v1.12), mindestens 8 px
- Bearbeiten: Größe mit/ohne Position, Zurücksetzen behält die Mitte, Stilwechsel verwirft Größen
- Griffe: Rechenregel (gegenüberliegende Kante, Mitte, Seitenverhältnis, Mehrfachauswahl)
- Viewer und Inspektor mit echten Mausereignissen, Rückgängig als ein Schritt
- Export: eigene Größe landet im Menüstrom; ohne eigene Größe byte-gleich
"""
import os
import tempfile
import unittest

from PySide6.QtCore import Qt, QEvent, QPointF

from core import menu_design
from core.disc_adapter import preview_menu_specs
from core.disc_edit import starter_project, add_nav_button
from core.disc_model import DiscProject, STYLE_SHAPE, TEXT_MIN_HEIGHT
from gui.studio.viewer import resized_rects, _SizeHandleItem
from tests.project_factory import text_starter
from tests.test_menu_designer import DesignerCase, app_instance


def two_button_project():
    project = text_starter()
    project.films[0].video_base = "film.264"
    menu = project.main_menu
    add_nav_button(project, menu.id, "EXTRAS", target=project.films[0].id)
    return project, menu


def box(project, menu, index):
    s = preview_menu_specs(project, menu)[index]
    return s.x, s.y, s.width, s.height


class TestModelAndLayout(unittest.TestCase):
    def test_size_at_fixed_position(self):
        project, menu = two_button_project()
        x, y, w, h = box(project, menu, 0)
        self.assertEqual((w, h), (380, 70))                      # Standardgröße für Text
        menu.buttons[0].size = [200, 40]
        self.assertEqual(box(project, menu, 0), (x, y, 200, 40))
        self.assertEqual(box(project, menu, 1)[2:], (w, h))      # der andere bleibt

    def test_fixed_position_and_minimum(self):
        project, menu = two_button_project()
        menu.buttons[0].position = [100, 200]
        menu.buttons[0].size = [3, 2]
        self.assertEqual(box(project, menu, 0), (100, 200, 8, 8))

    def test_size_overrides_shape_size(self):
        project, menu = two_button_project()
        menu.button_style.kind = STYLE_SHAPE
        menu.buttons[1].size = [120, 12]
        specs = preview_menu_specs(project, menu)
        self.assertEqual((specs[0].width, specs[0].height), (300, 8))
        self.assertEqual((specs[1].width, specs[1].height), (120, 12))
        self.assertIsNotNone(specs[1].shape)

    def test_round_trip(self):
        project, menu = two_button_project()
        menu.buttons[0].size = [200, 40]
        loaded = DiscProject.from_dict(project.to_dict())
        self.assertEqual(loaded.main_menu.buttons[0].size, [200, 40])


class TestEditing(unittest.TestCase):
    def test_resize_keeps_center_of_fixed_button(self):
        project, menu = two_button_project()
        menu.buttons[0].position = [100, 200]                  # 380 × 70
        menu_design.resize_items(project, menu.id, {menu.buttons[0].id: (180, 30)})
        self.assertEqual(box(project, menu, 0), (200, 220, 180, 30))

    def test_resize_with_positions(self):
        project, menu = two_button_project()
        bid = menu.buttons[0].id
        menu_design.resize_items(project, menu.id, {bid: (150, 20)}, positions={bid: (50, 60)})
        self.assertEqual(box(project, menu, 0), (50, 60, 150, 20))

    def test_text_buttons_keep_min_height(self):
        """Text-Buttons nicht flacher als TEXT_MIN_HEIGHT: darunter lässt sich der Button nicht zeichnen (die
        Vorschau brach bei 8 px ab); eine Linie darf 8 px hoch sein."""
        project, menu = two_button_project()
        bid = menu.buttons[0].id
        menu_design.resize_items(project, menu.id, {bid: (300, 8)})
        self.assertEqual(menu.buttons[0].size, [300, TEXT_MIN_HEIGHT])
        from modules.menu_author import create_button_image
        for state in ("normal", "selected", "activated"):     # zeichnen geht
            self.assertEqual(create_button_image("KAPITEL 1", 300, TEXT_MIN_HEIGHT, state).size, (300, TEXT_MIN_HEIGHT))
        menu.button_style.kind, menu.button_style.shape = STYLE_SHAPE, "line"
        menu_design.resize_items(project, menu.id, {bid: (300, 8)})
        self.assertEqual(menu.buttons[0].size, [300, 8])

    def test_clear_keeps_center(self):
        project, menu = two_button_project()
        bid = menu.buttons[0].id
        menu_design.resize_items(project, menu.id, {bid: (180, 30)}, positions={bid: (200, 220)})
        menu_design.clear_sizes(project, menu.id, [bid])
        self.assertEqual(box(project, menu, 0), (100, 200, 380, 70))


class TestHandleMath(unittest.TestCase):
    rects = {"a": (100, 100, 300, 8), "b": (100, 300, 200, 8)}

    def test_right_edge_keeps_left(self):
        r = resized_rects(self.rects, "a", "r", 50, 999)
        self.assertEqual(r["a"], (100, 100, 350, 8))
        self.assertEqual(r["b"], (100, 300, 350, 8))          # gleiche Breite, linke Kante bleibt

    def test_left_edge_keeps_right(self):
        r = resized_rects(self.rects, "a", "l", -20, 0)
        self.assertEqual(r["a"], (80, 100, 320, 8))
        self.assertEqual(r["b"], (0, 300, 320, 8))             # rechte Kante bliebe bei 300, im Bild gehalten

    def test_symmetric_keeps_center(self):
        r = resized_rects({"a": (100, 100, 300, 8)}, "a", "r", 10, 0, symmetric=True)
        self.assertEqual(r["a"], (90, 100, 320, 8))

    def test_minimum_and_ratio(self):
        r = resized_rects({"a": (100, 100, 40, 40)}, "a", "b", 0, -100)
        self.assertEqual(r["a"][3], 8)
        r = resized_rects({"a": (100, 100, 40, 40)}, "a", "br", 40, 0, keep_ratio=True)
        self.assertEqual(r["a"], (100, 100, 80, 80))

    def test_stays_in_picture(self):
        r = resized_rects({"a": (1800, 100, 100, 20)}, "a", "r", 500, 0)
        x, _y, w, _h = r["a"]
        self.assertLessEqual(x + w, 1920)


class TestViewer(DesignerCase):
    """Kapitelmenü aus DesignerCase; erster Button wird an seinem rechten Griff gezogen."""

    def _handle(self, code):
        return next(h for h in self.designer.size_handles if h.code == code)

    def test_handles_follow_selection(self):
        self.assertEqual(self.designer.size_handles, [])
        menu = self.project.menu(self.page_id)
        self.ctrl.select_button(self.page_id, menu.buttons[0].id)
        app_instance.processEvents()
        self.assertEqual(len(self.designer.size_handles), 8)
        self.ctrl.select_button(None, None)
        app_instance.processEvents()
        self.assertEqual(self.designer.size_handles, [])

    def test_drag_right_handle_one_undo_step(self):
        menu = self.project.menu(self.page_id)
        bid = menu.buttons[0].id
        self.ctrl.select_button(self.page_id, bid)
        app_instance.processEvents()
        x, y, w, h = box(self.project, menu, 0)
        start = self._handle("r").pos()
        steps = self.ctrl.undo_stack.count()
        self._mouse(QEvent.MouseButtonPress, start)
        self._mouse(QEvent.MouseMove, start + QPointF(30, 0))
        self.assertAlmostEqual(self.designer.items[bid].pixmap().width(), w + 30, delta=3)   # Live-Vorschau
        self._mouse(QEvent.MouseMove, start + QPointF(60, 0))
        self._mouse(QEvent.MouseButtonRelease, start + QPointF(60, 0), buttons=Qt.NoButton)
        self.assertEqual(self.ctrl.undo_stack.count(), steps + 1)
        menu = self.project.menu(self.page_id)
        nx, ny, nw, nh = box(self.project, menu, 0)
        self.assertEqual((nx, ny, nh), (x, y, h))
        self.assertAlmostEqual(nw, w + 60, delta=3)            # Bildschirm-Pixel im verkleinerten Viewer
        self.ctrl.undo_stack.undo()
        self.assertIsNone(self.project.menu(self.page_id).buttons[0].size)

    def test_multi_selection_same_width(self):
        menu = self.project.menu(self.page_id)
        ids = [b.id for b in menu.buttons[:2]]
        self.designer._select_many(set(ids))
        app_instance.processEvents()
        start = self._handle("r").pos()
        self._mouse(QEvent.MouseButtonPress, start)
        self._mouse(QEvent.MouseMove, start + QPointF(-100, 0))
        self._mouse(QEvent.MouseButtonRelease, start + QPointF(-100, 0), buttons=Qt.NoButton)
        menu = self.project.menu(self.page_id)
        widths = {box(self.project, menu, i)[2] for i in range(2)}
        self.assertEqual(len(widths), 1)

    def test_inspector_size_fields(self):
        menu = self.project.menu(self.page_id)
        bid = menu.buttons[0].id
        self.ctrl.select_button(self.page_id, bid)
        app_instance.processEvents()
        page = self.win.inspector.menu_page
        self.assertTrue(page.size_row.isVisibleTo(page))
        self.assertFalse(page.btn_size_reset.isEnabled())
        page.spin_btn_w.setValue(222)
        page.spin_btn_h.setValue(33)
        page._commit_button_size()
        self.assertEqual(self.project.menu(self.page_id).button(bid).size, [222, 33])
        self.assertTrue(page.btn_size_reset.isEnabled())
        page.btn_size_reset.click()
        self.assertIsNone(self.project.menu(self.page_id).button(bid).size)

    def test_style_change_clears_sizes(self):
        """Text → Kreis verwirft eigene Größen; Text → Linie behält die eigene Breite (v1.14.5)."""
        from modules.button_shapes import SHAPE_CIRCLE
        menu = self.project.menu(self.page_id)
        bid = menu.buttons[0].id
        self.ctrl.resize_menu_items(self.page_id, {bid: (100, 20)})
        self.ctrl.set_button_style(self.page_id, kind=STYLE_SHAPE, shape=SHAPE_CIRCLE)
        custom = lambda: any(b.size is not None for b in self.project.menu(self.page_id).buttons)
        self.assertFalse(custom())
        self.ctrl.undo_stack.undo()
        self.assertTrue(custom())
        self.ctrl.set_button_style(self.page_id, kind=STYLE_SHAPE)
        self.assertEqual(self.project.menu(self.page_id).button(bid).size, [100, 8])


class TestExport(unittest.TestCase):
    def test_size_on_simulated_disc(self):
        from modules.bdsim.disc import load_disc
        from modules.sim_disc import build_simulation_disc

        project, menu = two_button_project()
        menu.button_style.kind = STYLE_SHAPE
        menu.buttons[1].size = [120, 12]
        with tempfile.TemporaryDirectory() as tmp:
            disc = load_disc(build_simulation_disc(project, os.path.join(tmp, "SIM")).root)
            comp = disc.compositions[0]
            sizes = [(comp.objects[b.selected[0]].width, comp.objects[b.selected[0]].height)
                     for b in comp.pages[0].buttons()]
        self.assertEqual(sizes, [(300, 8), (120, 12)])


if __name__ == "__main__":
    unittest.main()
