# tests/test_fixed_guides.py
"""
Eigene Linien in allen Menüs (v1.16.0): waagerecht/senkrecht mit Abstand von einer gewählten Kante, in jedem
Menü dieselbe Linie. Ab v1.16.4 reine Einrast-Hilfen: Buttons rasten beim Ziehen ein, nichts bleibt geheftet.
"""

import unittest

from PySide6.QtCore import QEvent, QPointF, Qt

from core import menu_guides, menu_layout
from core.disc_model import DiscProject
from tests.project_factory import make_project
from tests.test_menu_designer import DesignerCase, app_instance


def two_menus():
    project = make_project(chapters=12, chapter_menu=True)     # Hauptmenü + zwei Kapitelseiten
    return project, project.menus[1], project.menus[2]


class TestModel(unittest.TestCase):
    def test_line_is_in_every_menu(self):
        project, page1, page2 = two_menus()
        line = menu_guides.add_fixed_guide(project, "bottom", 70)
        for menu in project.menus:
            g = menu_guides.guide(project, menu.id, line.id)
            self.assertEqual(menu_guides.endpoints(g), ((0.0, 1010.0), (1920.0, 1010.0)))
        side = menu_guides.add_fixed_guide(project, "right", 40)
        self.assertEqual(menu_guides.endpoints(menu_guides.guide(project, page1.id, side.id)),
                         ((1880.0, 0.0), (1880.0, 1080.0)))
        loaded = DiscProject.from_dict(project.to_dict())
        self.assertEqual(loaded.view.fixed_guides, project.view.fixed_guides)

    def test_distance_and_edge_buttons_stay(self):
        project, page1, page2 = two_menus()
        line = menu_guides.add_fixed_guide(project, "bottom", 70)
        back = page1.buttons[-1]
        box = menu_layout.button_box(page1, back)
        menu_guides.set_fixed_guide(project, line.id, distance=80)
        self.assertEqual(menu_guides.fixed_coordinate(line), 1000)
        # Kante wechseln: Linie bleibt liegen, Abstand umgerechnet
        menu_guides.set_fixed_guide(project, line.id, edge="top")
        self.assertEqual((line.edge, line.distance), ("top", 1000))
        self.assertEqual(menu_layout.button_box(page1, back), box)     # Linien bewegen keine Buttons
        with self.assertRaises(menu_guides.GuideError):
            menu_guides.set_fixed_guide(project, line.id, edge="left")

    def test_remove_from_all_menus(self):
        project, page1, page2 = two_menus()
        line = menu_guides.add_fixed_guide(project, "bottom", 70)
        menu_guides.remove_guide(project, page1.id, line.id)          # aus irgendeinem Menü gelöscht
        self.assertEqual(project.view.fixed_guides, [])
        self.assertIsNone(menu_guides.guide(project, page2.id, line.id))

    def test_menu_guides_stay_per_menu(self):
        project, page1, page2 = two_menus()
        own = menu_guides.add_guide(project, page1.id, ["top", 0.5], ["bottom", 0.5])
        menu_guides.add_fixed_guide(project, "bottom", 70)
        self.assertEqual(len(menu_guides.guides(project, page1.id)), 2)
        self.assertEqual(len(menu_guides.guides(project, page2.id)), 1)
        self.assertNotIn(own.id, {g.id for g in menu_guides.guides(project, page2.id)})


class TestViewerAndInspector(DesignerCase):
    """v1.16.4: Linien sind reine Einrast-Hilfen – der Button rastet ein, bleibt aber nicht geheftet."""

    def _drag_button(self, button_id, end: QPointF, modifiers=Qt.NoModifier):
        start = self.designer.items[button_id].sceneBoundingRect().center()
        self._mouse(QEvent.MouseButtonPress, start, modifiers=modifiers)
        self._mouse(QEvent.MouseMove, (start + end) / 2, modifiers=modifiers)
        self._mouse(QEvent.MouseMove, end, modifiers=modifiers)
        self._mouse(QEvent.MouseButtonRelease, end, buttons=Qt.NoButton, modifiers=modifiers)

    def _center(self, button_id):
        menu = self.project.menu(self.page_id)
        x, y, w, h = menu_layout.button_box(menu, menu.button(button_id))
        return x + w / 2, y + h / 2

    def test_snaps_to_crossing_without_binding(self):
        self.ctrl.add_fixed_guide("bottom", 300)                               # y = 780
        v = self.ctrl.add_fixed_guide("left", 700)                            # x = 700
        app_instance.processEvents()
        button = self.project.menu(self.page_id).buttons[0]
        self._drag_button(button.id, QPointF(700 + 6, 780 - 5))
        self.assertEqual(self._center(button.id), (700, 780))
        self.ctrl.set_fixed_guide(v, distance=760)                             # Linie ändern: Button bleibt
        self.assertEqual(self._center(button.id), (700, 780))

    def test_snaps_to_one_line_other_direction_free(self):
        line_id = self.ctrl.add_fixed_guide("bottom", 300)
        app_instance.processEvents()
        self.assertTrue(self.designer.guide_items[line_id].fixed)
        button = self.project.menu(self.page_id).buttons[0]
        start = self.designer.items[button.id].sceneBoundingRect().center()
        self._drag_button(button.id, QPointF(start.x() + 37, 780 + 5))
        cx, cy = self._center(button.id)
        self.assertEqual(cy, 780)
        self.assertNotEqual(cx, 700)
        # weiterziehen: nichts hält ihn an der Linie
        self._drag_button(button.id, QPointF(cx, 600))
        self.assertAlmostEqual(self._center(button.id)[1], 600, delta=14)
        # Alt: gar kein Einrasten
        self._drag_button(button.id, QPointF(cx, 780 + 5), modifiers=Qt.AltModifier)
        self.assertNotEqual(self._center(button.id)[1], 780)

    def test_snap_checkbox(self):
        """v1.17.3: „Einrasten“ ist beim Start an; aus = frei wie mit Alt. Ausgeblendete Linien rasten weiter ein."""
        self.ctrl.add_fixed_guide("bottom", 300)
        app_instance.processEvents()
        viewer = self.win.viewer
        self.assertTrue(viewer.chk_snap.isChecked())
        viewer.chk_guides.setChecked(False)                       # Linien unsichtbar, Einrasten an
        button = self.project.menu(self.page_id).buttons[0]
        start = self.designer.items[button.id].sceneBoundingRect().center()
        self._drag_button(button.id, QPointF(start.x(), 780 + 5))
        self.assertEqual(self._center(button.id)[1], 780)
        viewer.chk_snap.setChecked(False)
        cx = self._center(button.id)[0]
        self._drag_button(button.id, QPointF(cx, 600))
        self._drag_button(button.id, QPointF(cx, 780 + 5))
        self.assertNotEqual(self._center(button.id)[1], 780)
        viewer.chk_snap.setChecked(True)
        self._drag_button(button.id, QPointF(cx, 780 + 6))
        self.assertEqual(self._center(button.id)[1], 780)


if __name__ == "__main__":
    unittest.main()
