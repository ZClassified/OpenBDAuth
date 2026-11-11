# tests/test_gui_smoke_windows.py
"""
Rauchtest auf der ECHTEN Windows-Plattform (nicht offscreen): echte Mausereignisse im
Studio-Fenster – Knoten verschieben, Verbindung ziehen, über Sprungmarken fahren, Rückgängig.

Öffnet sichtbare Fenster und läuft deshalb nur auf Anforderung:
    set OPENBDAUTH_GUI_SMOKE=1 && python -m unittest tests.test_gui_smoke_windows
Hintergrund: v1.7.0 lief im Offscreen-Test fehlerfrei, stürzte auf Windows aber ab.
"""

import contextlib
import io
import os
import sys
import unittest

RUN = os.environ.get("OPENBDAUTH_GUI_SMOKE") == "1" and sys.platform == "win32"


@unittest.skipUnless(RUN, "Nur mit OPENBDAUTH_GUI_SMOKE=1 unter Windows (öffnet echte Fenster)")
class TestWindowsSmoke(unittest.TestCase):
    def test_node_editor_interactions(self):
        from PySide6.QtCore import Qt, QPoint, QPointF
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication
        from tests.project_factory import make_project
        from gui.studio.main_window import StudioWindow
        from gui.node_editor.scene import WireItem, MarkerItem

        QApplication.instance() or QApplication(sys.argv)

        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            win = StudioWindow(make_project(chapters=2, extra_films=1, chapter_menu=True), persist_layout=False)
            self.addCleanup(win.close)
            self.addCleanup(win.controller.undo_stack.setClean)
            win.resize(1400, 900)
            win.show()
            QTest.qWaitForWindowExposed(win)
            win.view.resetTransform()
            win.view.centerOn(win.scene.nodes[win.controller.project.main_menu.id])
            QTest.qWait(200)
            vp = win.view.viewport()
            to_view = win.view.mapFromScene

            def wires():
                return len([i for i in win.scene.items() if isinstance(i, WireItem)])

            # 1. Knoten verschieben: Verbindungen müssen erhalten bleiben
            main_item = win.scene.nodes[win.controller.project.main_menu.id]
            before_wires, before_pos = wires(), QPointF(main_item.pos())
            start = to_view(main_item.mapToScene(QPointF(60, 12)))
            QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, start)
            for step in range(1, 11):
                QTest.mouseMove(vp, start + QPoint(step * 6, step * 4))
                QTest.qWait(10)
            QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, start + QPoint(60, 40))
            QTest.qWait(200)
            main_item = win.scene.nodes[win.controller.project.main_menu.id]
            self.assertNotEqual(main_item.pos(), before_pos, "Knoten verschoben")
            self.assertEqual(wires(), before_wires, "Verbindungen nach Verschieben erhalten")

            # 2. Verbindung ziehen: erster Hauptmenü-Button → Bonus-Film
            menu = win.controller.project.main_menu
            source = next(s for s in main_item.ports if s.button_id == menu.buttons[0].id)
            port_pos = to_view(main_item.ports[source].scenePos())
            bonus = win.scene.nodes[win.controller.project.films[1].id]
            target_pos = to_view(bonus.mapToScene(QPointF(50, 20)))
            QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, port_pos)
            for step in range(1, 21):
                QTest.mouseMove(vp, port_pos + (target_pos - port_pos) * step / 20)
                QTest.qWait(10)
            QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, target_pos)
            QTest.qWait(200)
            self.assertEqual(win.controller.project.main_menu.buttons[0].target,
                             win.controller.project.films[1].id, "Verbindung per Ziehen gesetzt")

            # 3. Ansicht über den Symbol-Knopf in der Node-Ansicht umschalten
            def markers():
                return [i for i in win.scene.items() if isinstance(i, MarkerItem)]
            self.assertEqual(markers(), [], "Linien-Ansicht zeigt keine Sprungmarken")
            implicit = [w for w in win.scene.items() if isinstance(w, WireItem) and w.implicit]
            self.assertTrue(implicit, "Linien-Ansicht zeigt Standard-Rücksprünge als Linie")
            btn = win.view.returns_button
            self.assertTrue(btn.isVisible() and not btn.isChecked())
            self.assertLess(btn.geometry().right(), win.view.fit_button.geometry().left(), "links vom Einpassen-Knopf")
            tip_lines = btn.toolTip()
            QTest.mouseClick(btn, Qt.LeftButton)
            QTest.qWait(150)
            self.assertTrue(btn.isChecked())
            self.assertNotEqual(btn.toolTip(), tip_lines, "Tooltip nennt die neue Art")
            self.assertEqual(win.controller.project.view.return_wire_mode, "markers")
            self.assertTrue(markers(), "Sprungmarken-Ansicht zeigt Marken")
            for m in markers()[:3]:
                QTest.mouseMove(vp, to_view(m.mapToScene(m.boundingRect().center())))
                QTest.qWait(50)
            QTest.mouseClick(btn, Qt.LeftButton)
            QTest.qWait(150)
            self.assertFalse(btn.isChecked())
            self.assertEqual(markers(), [], "zurück in der Linien-Ansicht")

            # 4. Rückgängig
            win.controller.undo_stack.undo()
            QTest.qWait(100)
            self.assertEqual(win.controller.project.main_menu.buttons[0].target,
                             win.controller.project.films[0].id, "Rückgängig")

        self.assertNotIn("Traceback", err.getvalue())
        self.assertNotIn("Error calling Python override", err.getvalue())


if __name__ == "__main__":
    unittest.main()
