# tests/test_menu_guides.py
"""Hilfslinien eines Menüs an Ankerpunkten (v1.9.4), Qt-frei: Geometrie, Anlegen, Löschen, Speichern."""

import unittest

from core.disc_edit import starter_project, remove_nodes
from core.disc_model import DiscProject
from core.menu_guides import GuideError, anchor_xy, endpoints, add_guide, remove_guide, guides


class TestGeometry(unittest.TestCase):
    def test_anchors(self):
        self.assertEqual(anchor_xy(("top", 0.5)), (960.0, 0.0))
        self.assertEqual(anchor_xy(("right", 0.5)), (1920.0, 540.0))
        with self.assertRaises(GuideError):
            anchor_xy(("mitte", 0.5))

    def test_diagonal_and_same_edge(self):
        project = starter_project()
        d = add_guide(project, "m", ("top", 0.5), ("bottom", 1 / 3))
        (x1, y1), (x2, y2) = endpoints(d)
        self.assertEqual((x1, y1), (960.0, 0.0))
        self.assertAlmostEqual(x2, 640.0)
        self.assertEqual(y2, 1080.0)
        with self.assertRaises(GuideError):
            add_guide(project, "m", ("top", 0.2), ("top", 0.8))


class TestEditing(unittest.TestCase):
    def setUp(self):
        self.project = starter_project()
        self.main = self.project.main_menu

    def test_remove(self):
        g = add_guide(self.project, self.main.id, ("left", 0.5), ("right", 0.5))
        remove_guide(self.project, self.main.id, g.id)
        self.assertEqual(guides(self.project, self.main.id), [])

    def test_round_trip_and_cleanup(self):
        add_guide(self.project, self.main.id, ("top", 0.035), ("bottom", 0.035))   # früherer Ankerpunkt (Action Safe): bleibt gültig
        loaded = DiscProject.from_dict(self.project.to_dict())
        self.assertEqual(loaded.view.guides[self.main.id][0].a, ["top", 0.035])
        remove_nodes(self.project, [self.main.id])
        self.assertNotIn(self.main.id, self.project.view.guides)


if __name__ == "__main__":
    unittest.main()
