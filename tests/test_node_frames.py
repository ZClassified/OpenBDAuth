# tests/test_node_frames.py
"""
Rahmen im Node-Editor (v1.15.0, Konzept 3.5, wie Underlays in Fusion): Zugehörigkeit nach Lage, Strg+G um die
Auswahl, am Titel ziehen verschiebt den Inhalt mit (ein Rückgängig-Schritt), Kanten ändern die Größe, die Fläche
bleibt frei für den Auswahlrahmen, Löschen lässt die Knoten stehen.
"""

import os
import sys
import unittest
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu

from core import node_frames
from core.disc_model import DiscProject, START_NODE_ID
from gui.node_editor.controller import GraphController
from gui.node_editor.scene import NodeScene, FrameItem, FRAME_TITLE_H
from gui.node_editor.view import NodeView
from tests.project_factory import make_project

app_instance = QApplication.instance() or QApplication(sys.argv)


def make_graph():
    project = make_project(chapters=3, audio=2, subs=1, chapter_menu=True, language_menu=True)
    main, chapters, audio = project.menus
    film = project.films[0]
    project.view.node_positions.update({START_NODE_ID: [-400.0, 0.0], main.id: [0.0, 0.0],
                                        chapters.id: [600.0, 0.0], audio.id: [600.0, 400.0],
                                        film.id: [1200.0, 0.0]})
    return project


class TestModel(unittest.TestCase):
    def test_around_members_and_move(self):
        project = make_graph()
        main, chapters, audio = project.menus
        boxes = {chapters.id: (600, 0, 250, 150), audio.id: (600, 400, 250, 200), main.id: (0, 0, 250, 150)}
        rect = node_frames.around([boxes[chapters.id], boxes[audio.id]])
        self.assertEqual(rect, [570.0, -60.0, 310.0, 690.0])                  # Rand 30, Titel 30
        frame = node_frames.add_frame(project, rect, "Kapitel")
        inner = node_frames.add_frame(project, [600, 380, 200, 100], "Innen")
        node_frames.add_frame(project, [500, -100, 900, 900], "Außen")         # umschließt, gehört nicht dazu
        nodes, frames = node_frames.members(project, frame.id, boxes)
        self.assertEqual((set(nodes), frames), ({chapters.id, audio.id}, [inner.id]))
        node_frames.move_frame(project, frame.id, 100, 50, nodes, frames)
        self.assertEqual(frame.rect, [670.0, -10.0, 310.0, 690.0])
        self.assertEqual(inner.rect, [700.0, 430.0, 200.0, 100.0])
        self.assertEqual(project.view.node_positions[chapters.id], [700.0, 50.0])
        self.assertEqual(project.view.node_positions[main.id], [0.0, 0.0])

    def test_colours_minimum_size_and_save(self):
        project = make_graph()
        a = node_frames.add_frame(project, [0, 0, 10, 10], "A")
        b = node_frames.add_frame(project, [0, 0, 300, 200], "B")
        self.assertEqual(a.rect[2:], [node_frames.MIN_W, node_frames.MIN_H])
        self.assertNotEqual(a.color, b.color)
        loaded = DiscProject.from_dict(project.to_dict())
        self.assertEqual(loaded.view.groups, project.view.groups)
        data = project.to_dict()
        data["view"]["groups"] = [{"id": "g1", "name": "Alt", "color": "#64748B", "node_ids": [], "collapsed": False}]
        self.assertEqual(DiscProject.from_dict(data).view.groups[0].name, "Alt")   # alte Gruppen ohne rect


class TestFrameUI(unittest.TestCase):
    def setUp(self):
        self.ctrl = GraphController(make_graph())
        self.scene = NodeScene(self.ctrl)
        self.view = NodeView(self.scene)
        self.view.resize(1400, 900)
        self.view.show()
        app_instance.processEvents()
        self.view.resetTransform()
        self.view.scale(0.5, 0.5)
        self.view.centerOn(600, 300)
        self.main, self.chapters, self.audio = self.ctrl.project.menus

    def tearDown(self):
        self.view.close()

    def settle(self):
        for _ in range(3):
            app_instance.processEvents()

    def frame_around(self, *node_ids, name="Kapitel"):
        boxes = self.scene.node_boxes([self.scene.nodes[n] for n in node_ids])
        frame_id = self.ctrl.add_frame(node_frames.around(boxes.values()), name)
        self.settle()
        return frame_id

    def drag(self, start: QPointF, end: QPointF):
        viewport = self.view.viewport()
        a, b = self.view.mapFromScene(start), self.view.mapFromScene(end)
        QTest.mousePress(viewport, Qt.LeftButton, Qt.NoModifier, a)
        QTest.mouseMove(viewport, (a + b) / 2)
        QTest.mouseMove(viewport, b)
        QTest.mouseRelease(viewport, Qt.LeftButton, Qt.NoModifier, b)
        self.settle()

    def pos(self, node_id):
        return self.ctrl.project.view.node_positions[node_id]

    def test_ctrl_g_frames_the_selection(self):
        self.scene.clearSelection()
        for node_id in (self.chapters.id, self.audio.id):
            self.scene.nodes[node_id].setSelected(True)
        with mock.patch.object(NodeScene, "_ask_frame_name", return_value="Kapitel"):
            QTest.keyClick(self.view, Qt.Key_G, Qt.ControlModifier)
        self.settle()
        (group,) = self.ctrl.project.view.groups
        self.assertEqual(group.name, "Kapitel")
        nodes, _frames = node_frames.members(self.ctrl.project, group.id, self.scene.node_boxes())
        self.assertEqual(set(nodes), {self.chapters.id, self.audio.id})
        self.assertIn(group.id, self.scene.frames)

    def test_drag_title_moves_contents_in_one_step(self):
        frame_id = self.frame_around(self.chapters.id, self.audio.id)
        before = {n: list(self.pos(n)) for n in (self.main.id, self.chapters.id, self.audio.id)}
        rect = list(node_frames.frame(self.ctrl.project, frame_id).rect)
        steps = self.ctrl.undo_stack.count()
        title = QPointF(rect[0] + 60, rect[1] + FRAME_TITLE_H / 2)
        self.drag(title, title + QPointF(200, 120))
        self.assertEqual(self.ctrl.undo_stack.count(), steps + 1)
        dx = node_frames.frame(self.ctrl.project, frame_id).rect[0] - rect[0]
        dy = node_frames.frame(self.ctrl.project, frame_id).rect[1] - rect[1]
        self.assertAlmostEqual(dx, 200, delta=4)
        self.assertAlmostEqual(dy, 120, delta=4)
        for node_id in (self.chapters.id, self.audio.id):
            self.assertAlmostEqual(self.pos(node_id)[0], before[node_id][0] + dx, delta=0.5)
            self.assertAlmostEqual(self.pos(node_id)[1], before[node_id][1] + dy, delta=0.5)
        self.assertEqual(self.pos(self.main.id), before[self.main.id])           # liegt außerhalb
        self.ctrl.undo_stack.undo()
        self.settle()
        self.assertEqual({n: list(self.pos(n)) for n in before}, before)
        self.assertEqual(node_frames.frame(self.ctrl.project, frame_id).rect, rect)

    def test_node_dragged_in_moves_along(self):
        frame_id = self.frame_around(self.chapters.id)
        rect = node_frames.frame(self.ctrl.project, frame_id).rect
        self.ctrl.move_nodes({self.main.id: (rect[0] + 20, rect[1] + 40)})      # hineingezogen
        self.settle()
        before = list(self.pos(self.main.id))
        title = QPointF(rect[0] + 60, rect[1] + FRAME_TITLE_H / 2)
        self.drag(title, title + QPointF(0, 200))
        self.assertAlmostEqual(self.pos(self.main.id)[1], before[1] + 200, delta=4)

    def test_resize_right_edge_keeps_nodes(self):
        frame_id = self.frame_around(self.chapters.id)
        x, y, w, h = node_frames.frame(self.ctrl.project, frame_id).rect
        before = list(self.pos(self.chapters.id))
        edge = QPointF(x + w - 2, y + h / 2)
        self.drag(edge, edge + QPointF(150, 0))
        nx, ny, nw, nh = node_frames.frame(self.ctrl.project, frame_id).rect
        self.assertEqual((nx, ny, nh), (x, y, h))
        self.assertAlmostEqual(nw, w + 150, delta=4)
        self.assertEqual(self.pos(self.chapters.id), before)

    def test_inside_is_free_for_selection_frame(self):
        frame_id = self.frame_around(self.chapters.id, self.audio.id)
        x, y, w, h = node_frames.frame(self.ctrl.project, frame_id).rect
        frames_at = lambda p: [i for i in self.scene.items(p) if isinstance(i, FrameItem)]
        self.assertEqual(frames_at(QPointF(x + 12, y + h - 20)), [])            # Fläche: frei
        self.assertEqual(len(frames_at(QPointF(x + 60, y + 10))), 1)            # Titel

    def test_delete_frame_keeps_nodes(self):
        frame_id = self.frame_around(self.chapters.id)
        self.scene.clearSelection()
        self.scene.frames[frame_id].setSelected(True)
        QTest.keyClick(self.view, Qt.Key_Delete)
        self.settle()
        self.assertEqual(self.ctrl.project.view.groups, [])
        self.assertIsNotNone(self.ctrl.project.menu(self.chapters.id))

    def test_menu_colour_and_rename(self):
        frame_id = self.frame_around(self.chapters.id)
        menu = QMenu()
        self.scene._fill_frame_menu(menu, self.scene.frames[frame_id])
        colours = next(a.menu() for a in menu.actions() if a.menu() is not None)
        next(a for a in colours.actions() if a.text() == "Violett").trigger()
        self.assertEqual(node_frames.frame(self.ctrl.project, frame_id).color, "#A855F7")
        with mock.patch("gui.node_editor.scene.QInputDialog.getText", return_value=("Extras", True)):
            self.scene.rename_frame(frame_id)
        self.assertEqual(node_frames.frame(self.ctrl.project, frame_id).name, "Extras")


class TestFrameInspector(unittest.TestCase):
    """v1.15.1: ein ausgewählter Rahmen zeigt Name und Farbe im Inspektor."""

    def setUp(self):
        from gui.studio.main_window import StudioWindow
        self.win = StudioWindow(persist_layout=False)
        self.ctrl = self.win.controller
        self.frame_id = self.ctrl.add_frame([0, 300, 400, 300], "Kapitel")
        self.settle()

    def tearDown(self):
        self.ctrl.undo_stack.setClean()
        self.win.close()

    def settle(self):
        for _ in range(3):
            app_instance.processEvents()

    def select_frame(self):
        self.win.scene.clearSelection()
        self.win.scene.frames[self.frame_id].setSelected(True)
        self.settle()

    def test_name_colour_and_delete(self):
        page = self.win.inspector.frame_page
        self.select_frame()
        self.assertIs(self.win.inspector.stack.currentWidget(), page)
        self.assertEqual(page.edit_name.text(), "Kapitel")
        page.edit_name.setText("Extras")
        page._commit_name()
        page.btn_color.color_chosen.emit("#22C55E")
        self.settle()
        group = node_frames.frame(self.ctrl.project, self.frame_id)
        self.assertEqual((group.name, group.color), ("Extras", "#22C55E"))
        self.assertIs(self.win.inspector.stack.currentWidget(), page)         # bleibt nach dem Neuaufbau
        self.assertEqual(page.btn_color.color(), "#22C55E")
        page.btn_delete.click()
        self.settle()
        self.assertIsNone(node_frames.frame(self.ctrl.project, self.frame_id))
        self.assertIsNot(self.win.inspector.stack.currentWidget(), page)

    def test_empty_name_is_restored(self):
        page = self.win.inspector.frame_page
        self.select_frame()
        page.edit_name.setText("   ")
        page._commit_name()
        self.assertEqual(page.edit_name.text(), "Kapitel")
        self.assertEqual(node_frames.frame(self.ctrl.project, self.frame_id).name, "Kapitel")


if __name__ == "__main__":
    unittest.main()
