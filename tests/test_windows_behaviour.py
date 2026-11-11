# tests/test_windows_behaviour.py
"""
Regressionstests für Fehler, die nur auf echtem Windows auftreten (v1.7.1).

Unter Windows fragt Qt bei setCursor/setParentItem/setToolTip sofort boundingRect() eines
Grafikelements ab; im Offscreen-Modus der Tests nicht. Ein Element, das seine Maße erst danach
festlegt, wirft dann bei jeder Mausbewegung eine Ausnahme (v1.7.0: Verbindungen verschwanden,
Ziehen war unmöglich). Diese Tests stellen das Verhalten nach.

Außerdem: Ausnahmen in Python-Überschreibungen (paint, boundingRect, Maus-Events) werden von
PySide nur auf stderr ausgegeben und lassen Tests sonst grün. Deshalb wird stderr geprüft.
"""

import contextlib
import io
import os
import sys
import unittest
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6 import QtGui
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtWidgets import QApplication, QGraphicsItem

from tests.project_factory import make_project
from core.disc_rules import Source
from gui.node_editor.controller import GraphController
from gui.node_editor.scene import NodeScene, WireItem

app_instance = QApplication.instance() or QApplication(sys.argv)


def sample_project():
    return make_project(chapters=2, audio=2, extra_films=1, chapter_menu=True, language_menu=True)


@contextlib.contextmanager
def windows_like_geometry_queries():
    """Wie unter Windows: diese Aufrufe fragen sofort boundingRect() ab."""
    originals = {name: getattr(QGraphicsItem, name) for name in ("setCursor", "setParentItem", "setToolTip")}

    def wrap(name):
        def call(self, *args):
            self.boundingRect()
            return originals[name](self, *args)
        return call

    with contextlib.ExitStack() as stack:
        for name in originals:
            stack.enter_context(mock.patch.object(QGraphicsItem, name, wrap(name)))
        yield


@contextlib.contextmanager
def captured_stderr():
    buffer = io.StringIO()
    with contextlib.redirect_stderr(buffer):
        yield buffer


def render(scene_or_widget):
    """Zeichnet eine Szene oder ein Fenster vollständig (ruft alle paint()-Überschreibungen auf)."""
    if hasattr(scene_or_widget, "itemsBoundingRect"):
        image = QtGui.QImage(1600, 1000, QtGui.QImage.Format_ARGB32)
        painter = QtGui.QPainter(image)
        scene_or_widget.render(painter, QRectF(0, 0, 1600, 1000), scene_or_widget.itemsBoundingRect())
        painter.end()
    else:
        scene_or_widget.grab()


class TestWindowsGeometryQueries(unittest.TestCase):
    def test_scene_builds_with_immediate_geometry_queries(self):
        ctrl = GraphController(sample_project())
        for mode in ("lines", "markers"):
            ctrl.project.view.return_wire_mode = mode
            with windows_like_geometry_queries():
                scene = NodeScene(ctrl)
            wires = [i for i in scene.items() if isinstance(i, WireItem)]
            self.assertGreater(len(wires), 0, mode)

    def test_connections_survive_moving_a_node(self):
        ctrl = GraphController(sample_project())
        with windows_like_geometry_queries():
            scene = NodeScene(ctrl)
            before = len([i for i in scene.items() if isinstance(i, WireItem)])
            main = scene.nodes[ctrl.project.main_menu.id]
            main.setPos(main.pos() + QPointF(40, 30))
            scene._commit_node_positions()
            scene.rebuild()
            after = len([i for i in scene.items() if isinstance(i, WireItem)])
        self.assertEqual(before, after)

    def test_drag_connection_with_immediate_geometry_queries(self):
        ctrl = GraphController(sample_project())
        with windows_like_geometry_queries():
            scene = NodeScene(ctrl)
            main = ctrl.project.main_menu
            bonus = scene.nodes[ctrl.project.films[1].id]
            target = bonus.mapToScene(QPointF(40, 20))
            source = Source.button(main.id, main.buttons[0].id)
            scene._start_drag(source, target)
            scene._update_drag(target)
            scene._finish_drag(target)
        self.assertEqual(ctrl.project.main_menu.buttons[0].target, ctrl.project.films[1].id)


class TestNoSilentOverrideErrors(unittest.TestCase):
    def test_scene_paints_without_errors(self):
        ctrl = GraphController(sample_project())
        with captured_stderr() as err:
            for mode in ("lines", "markers"):
                ctrl.set_return_wire_mode(mode)
                scene = NodeScene(ctrl)
                scene.select_node(ctrl.project.main_menu.id)
                render(scene)
        self.assertNotIn("Error calling Python override", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())

    def test_studio_window_renders_without_errors(self):
        from gui.studio.main_window import StudioWindow
        win = StudioWindow(sample_project(), persist_layout=False)
        self.addCleanup(win.close)
        self.addCleanup(win.controller.undo_stack.setClean)
        with captured_stderr() as err:
            win.resize(1500, 900)
            win.show()
            app_instance.processEvents()
            for node_id in list(win.scene.nodes):
                win.scene.select_node(node_id)
                app_instance.processEvents()
                render(win)
            win.open_export_dialog()
            app_instance.processEvents()
            render(win._export_dialog)
            win._export_dialog.close()
        self.assertNotIn("Error calling Python override", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())


if __name__ == "__main__":
    unittest.main()
