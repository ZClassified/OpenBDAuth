# tests/test_drag_spin.py
"""Zahlenfeld zum Ziehen (v1.14.7): Deckkraft eintippen oder mit gedrückter Maustaste verstellen."""

import os
import sys
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from gui.studio.widgets import DragSpinBox

app_instance = QApplication.instance() or QApplication(sys.argv)


def mouse(widget, kind, pos: QPoint, buttons=Qt.LeftButton):
    local = QPointF(pos)
    event = QMouseEvent(kind, local, QPointF(widget.mapToGlobal(pos)), Qt.LeftButton, buttons, Qt.NoModifier)
    QApplication.sendEvent(widget, event)


class TestDragSpinBox(unittest.TestCase):
    def setUp(self):
        self.spin = DragSpinBox()
        self.spin.setRange(0, 100)
        self.spin.setValue(50)
        self.spin.show()
        self.values = []
        self.spin.committed.connect(self.values.append)
        self.edit = self.spin.lineEdit()

    def tearDown(self):
        self.spin.close()

    def drag(self, dx, dy):
        start = QPoint(10, 5)
        mouse(self.edit, QEvent.MouseButtonPress, start)
        mouse(self.edit, QEvent.MouseMove, start + QPoint(dx, dy))
        mouse(self.edit, QEvent.MouseButtonRelease, start + QPoint(dx, dy), buttons=Qt.NoButton)

    def test_drag_right_and_up_increase(self):
        self.drag(40, 0)
        self.assertEqual(self.spin.value(), 70)
        self.drag(0, -20)
        self.assertEqual(self.spin.value(), 80)
        self.assertEqual(self.values, [70, 80])

    def test_drag_left_clamps_at_zero(self):
        self.drag(-400, 0)
        self.assertEqual((self.spin.value(), self.values), (0, [0]))

    def test_click_without_drag_changes_nothing_and_selects_number(self):
        self.drag(2, 0)
        self.assertEqual((self.spin.value(), self.values), (50, []))
        app_instance.processEvents()
        self.assertEqual(self.edit.selectedText(), "50")              # Tippen ersetzt die ganze Zahl

    def test_arrows_step_to_round_values_and_commit(self):
        self.spin.setSingleStep(5)
        self.spin.setValue(37)
        self.spin.stepUp()
        self.assertEqual(self.spin.value(), 40)
        self.spin.stepUp()
        self.assertEqual(self.spin.value(), 45)
        self.spin.setValue(37)
        self.spin.stepDown()
        self.assertEqual(self.spin.value(), 35)
        self.spin.setValue(98)
        self.spin.stepUp()
        self.assertEqual(self.spin.value(), 100)
        self.spin.setValue(3)
        self.spin.stepDown()
        self.assertEqual(self.spin.value(), 0)
        self.assertEqual(self.values, [40, 45, 35, 100, 0])         # jeder Schritt sofort übernommen

    def test_drag_stays_fine_grained_with_step(self):
        self.spin.setSingleStep(5)
        self.drag(6, 0)
        self.assertEqual(self.spin.value(), 53)

    def test_width_fits_largest_value(self):
        hint = self.spin.sizeHint().width()
        self.assertGreaterEqual(hint, self.spin.fontMetrics().horizontalAdvance("100"))


if __name__ == "__main__":
    unittest.main()
