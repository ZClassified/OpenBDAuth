# tests/test_menu_spacing.py
"""Abstands-Hilfe und gleichmäßiges Verteilen im Menü-Designer (Feinschliff nach v1.9.6)."""

import unittest

from PySide6.QtCore import Qt, QEvent, QPointF

from core.menu_spacing import snap_spacing, existing_gaps
from tests.test_menu_designer import DesignerCase, app_instance

W, H = 380, 70


def column(ys, x=770):
    return [(x, y, W, H) for y in ys]


class TestSnapSpacing(unittest.TestCase):
    def test_existing_gap_below_last(self):
        others = column([100, 210, 320])                     # Abstand 40
        self.assertEqual(sorted(g for g, _ in existing_gaps(others, "y")), [40, 40])
        shift, markers = snap_spacing((770, 437, W, H), others, "y")   # ~7 zu weit unten
        self.assertEqual(shift, -7)                                      # landet bei 430 = 390 + 40
        self.assertEqual(len(markers), 3)                                # zwei vorhandene + der neue Abstand

    def test_middle_between_two(self):
        others = column([100, 400])
        shift, markers = snap_spacing((770, 262, W, H), others, "y")
        self.assertEqual(shift, (100 + H + 400 - H) / 2 - 262 - 0)  # mittig: 250
        self.assertEqual(len(markers), 2)

    def test_nothing_near_and_other_column_ignored(self):
        others = column([100, 210, 320])
        self.assertIsNone(snap_spacing((770, 470, W, H), others, "y"))
        self.assertIsNone(snap_spacing((1400, 437, W, H), others, "y"))     # keine Überlappung quer

    def test_alignment_edges_and_centres(self):
        from core.menu_spacing import snap_alignment
        others = [(100, 100, 380, 70)]
        self.assertEqual(snap_alignment((104, 400, 380, 70), others, "x")[0], -4)     # linke Kanten
        self.assertEqual(snap_alignment((195, 400, 200, 70), others, "x")[0], -5)     # Mitten (295 ↔ 290)
        self.assertIsNone(snap_alignment((300, 400, 200, 70), others, "x"))           # links ↔ Mitte: nicht mehr (v1.15.3)
        self.assertIsNone(snap_alignment((160, 400, 380, 70), others, "x"))

    def test_thin_lines_snap_only_by_centre(self):
        """v1.15.3: Linien (8 px) rasten senkrecht nur Mitte an Mitte ein – ein Ziel statt neun."""
        from core.menu_spacing import snap_alignment
        others = [(100, 418, 530, 8)]                                                # Mitte 422
        self.assertEqual(snap_alignment((700, 425, 530, 8), others, "y")[0], -7)     # Mitte 429 → 422
        self.assertEqual(snap_alignment((700, 413, 530, 8), others, "y")[0], 5)      # Mitte 417 → 422
        # waagerecht sind Linien breit: linke Kanten rasten weiter ein
        self.assertEqual(snap_alignment((103, 700, 530, 8), others, "x")[0], -3)

    def test_horizontal(self):
        others = [(100, 500, 300, 60), (460, 500, 300, 60)]                 # Abstand 60
        shift, _ = snap_spacing((826, 500, 300, 60), others, "x")
        self.assertEqual(shift, -6)


class TestCenterStack(unittest.TestCase):
    def test_snap_center(self):
        from core.menu_spacing import snap_center
        self.assertEqual(snap_center((766, 100, 380, 70), "x")[0], 4)       # Mitte 956 → 960
        self.assertIsNone(snap_center((700, 100, 380, 70), "x"))
        self.assertEqual(snap_center((0, 500, 100, 70), "y")[0], 5)         # Mitte 535 → 540


class TestSpacingInViewer(DesignerCase):
    def test_drag_snaps_to_equal_gap_and_shows_markers(self):
        from core.disc_edit import add_nav_button
        from core.menu_design import move_items
        menu = self.project.menu(self.page_id)
        # drei Navigations-Buttons links untereinander mit Abstand 40, ein vierter irgendwo
        ids = [b.id for b in menu.buttons[-2:]]
        for label in ("X", "Y"):
            ids.append(add_nav_button(self.project, self.page_id, label, self.project.main_menu.id).id)
        move_items(self.project, self.page_id, positions={ids[0]: (100, 100), ids[1]: (100, 210), ids[2]: (100, 320),
                                                          ids[3]: (700, 900)})
        self.ctrl.changed.emit()
        app_instance.processEvents()
        item = self.designer.items[ids[3]]
        h = item.spec.height
        self.assertEqual(h, 70)                                   # Standardgröße der Text-Buttons (v1.12)
        gap = 110 - h                                             # Abstand der ersten drei
        start = item.sceneBoundingRect().center()
        target = QPointF(100 + item.spec.width / 2, 320 + h + gap + h / 2 + 2)   # grob unter dem dritten (48 px gibt es auch)
        self._mouse(QEvent.MouseButtonPress, start)
        self._mouse(QEvent.MouseMove, target)
        self.assertTrue(self.designer.spacing_items)               # Markierungen beim Ziehen sichtbar
        self._mouse(QEvent.MouseButtonRelease, target, buttons=Qt.NoButton)
        self.assertFalse(self.designer.spacing_items)              # nach dem Loslassen weg
        x, y = self.project.menu(self.page_id).button(ids[3]).position
        self.assertEqual(y, 320 + h + gap)                         # gleicher Abstand wie oben (210 − 100 − 70 = 40)
        self.assertEqual(x, 100)                                   # waagerecht bündig mit der Spalte (Ausrichtungs-Hilfe)


if __name__ == "__main__":
    unittest.main()
