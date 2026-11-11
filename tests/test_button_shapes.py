# tests/test_button_shapes.py
"""
Tests für Form-Buttons (v1.11.0):
- Grafik: Größe (mindestens 8 px), Farben und Deckkraft pro Zustand, wenige Palettenfarben
- Projektmodell: alte Projekte bleiben Text-Buttons, der Stil wird gespeichert
- Layout: einheitliche Größe, mittig im Platz, feste Positionen bleiben
- Palette: Formfarben bleiben neben farbreichen Text-Buttons exakt; ohne Formen byte-gleich
- Simulation und Oberfläche (Inspektor, Viewer, Rückgängig)
"""
import os
import sys
import tempfile
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from core.disc_adapter import build_export_plan, preview_menu_specs
from core.disc_edit import starter_project, add_nav_button
from core.disc_model import DiscProject, STYLE_SHAPE, STYLE_TEXT
from modules.button_shapes import (
    ShapeStyle, create_shape_image, SHAPES, SHAPE_LINE, SHAPE_CIRCLE, MIN_SIZE,
)
from modules.igs.compiler import IGSCompiler, MenuButton, MenuPage
from modules.menu_author import create_button_image
from tests.project_factory import text_starter

app_instance = QApplication.instance() or QApplication(sys.argv)

RED = "#EF4444"


def colors(img):
    return set(img.get_flattened_data() if hasattr(img, "get_flattened_data") else img.getdata())


def shape_project(**style):
    project = text_starter()
    project.films[0].video_base = "film.264"
    menu = project.main_menu
    add_nav_button(project, menu.id, "EXTRAS", target=project.films[0].id)
    menu.button_style.kind = STYLE_SHAPE
    for k, v in style.items():
        setattr(menu.button_style, k, v)
    return project, menu


class TestShapeImage(unittest.TestCase):
    def test_minimum_size(self):
        self.assertEqual(create_shape_image(ShapeStyle(), 300, 3, "selected").size, (300, MIN_SIZE))
        self.assertEqual(create_shape_image(ShapeStyle(), 2, 2, "selected").size, (MIN_SIZE, MIN_SIZE))

    def test_invisible_normal_state(self):
        img = create_shape_image(ShapeStyle(opacity_normal=0), 300, 8, "normal")
        self.assertTrue(all(p[3] == 0 for p in colors(img)))

    def test_line_is_one_solid_color(self):
        img = create_shape_image(ShapeStyle(color_selected=RED), 300, 8, "selected")
        self.assertEqual(colors(img), {(0xEF, 0x44, 0x44, 255)})

    def test_opacity(self):
        img = create_shape_image(ShapeStyle(opacity_activated=50), 100, 10, "activated")
        self.assertEqual(colors(img), {(255, 255, 255, 128)})

    def test_few_palette_colors_per_state(self):
        for shape in SHAPES:
            for state in ("normal", "selected", "activated"):
                img = create_shape_image(ShapeStyle(shape=shape, opacity_normal=60), 61, 41, state)
                self.assertLessEqual(len(colors(img)), 4, (shape, state))

    def test_triangle_points_the_right_way(self):
        right = create_shape_image(ShapeStyle(shape="triangle_right"), 40, 40, "selected")
        left = create_shape_image(ShapeStyle(shape="triangle_left"), 40, 40, "selected")
        self.assertEqual(right.getpixel((1, 20))[3], 255)     # breite Seite links
        self.assertEqual(right.getpixel((38, 2))[3], 0)
        self.assertEqual(left.getpixel((38, 20))[3], 255)
        self.assertEqual(left.getpixel((1, 2))[3], 0)

    def test_circle_corners_transparent(self):
        img = create_shape_image(ShapeStyle(shape=SHAPE_CIRCLE), 40, 40, "selected")
        self.assertEqual(img.getpixel((0, 0))[3], 0)
        self.assertEqual(img.getpixel((20, 20))[3], 255)


class TestModel(unittest.TestCase):
    def test_old_project_stays_text(self):
        project = starter_project()
        data = project.to_dict()
        for menu in data["menus"]:
            menu.pop("button_style")
        loaded = DiscProject.from_dict(data)
        self.assertEqual(loaded.main_menu.button_style.kind, STYLE_TEXT)

    def test_round_trip(self):
        project, _ = shape_project(shape=SHAPE_CIRCLE, width=40, height=40, color_selected=RED)
        loaded = DiscProject.from_dict(project.to_dict())
        self.assertEqual(loaded.main_menu.button_style, project.main_menu.button_style)


class TestLayout(unittest.TestCase):
    def test_text_specs_unchanged(self):
        project = text_starter()
        add_nav_button(project, project.main_menu.id, "EXTRAS", target=project.films[0].id)
        for spec in preview_menu_specs(project, project.main_menu):
            self.assertIsNone(spec.shape)
            self.assertEqual((spec.width, spec.height), (380, 70))

    def test_shapes_centred_in_place(self):
        """Wechsel Text → Kreis: jede Form sitzt mittig dort, wo der Text-Button war (v1.12: core.menu_design.set_style)."""
        from core import menu_design
        project, menu = shape_project(shape=SHAPE_CIRCLE, width=40, height=40)
        menu.button_style.kind = STYLE_TEXT
        text_specs = preview_menu_specs(project, menu)
        menu_design.set_style(project, menu.id, kind=STYLE_SHAPE)
        specs = preview_menu_specs(project, menu)
        for text, spec in zip(text_specs, specs):
            self.assertIsNotNone(spec.shape)
            self.assertEqual((spec.width, spec.height), (40, 40))
            self.assertEqual(spec.x, text.x + (380 - 40) // 2)
            self.assertEqual(spec.y, text.y + (70 - 40) // 2)

    def test_line_underlines_text_and_back(self):
        """Text ↔ Linie (v1.14.5): Unterstreichung an der Unterkante, eigene Breite bleibt, hin und zurück wie vorher."""
        from core import menu_design
        project, menu = shape_project(width=300, height=8)
        menu.button_style.kind = STYLE_TEXT
        menu.buttons[1].size = [489, 70]
        text_boxes = [(s.x, s.y, s.width, s.height) for s in preview_menu_specs(project, menu)]
        menu_design.set_style(project, menu.id, kind=STYLE_SHAPE)
        line_boxes = [(s.x, s.y, s.width, s.height) for s in preview_menu_specs(project, menu)]
        (x0, y0, _w, _h), (x1, y1, _w1, _h1) = text_boxes
        self.assertEqual(line_boxes[0], (x0 + (380 - 300) // 2, y0 + 70 - 8, 300, 8))   # Größe aus dem Stil
        self.assertEqual(line_boxes[1], (x1, y1 + 70 - 8, 489, 8))                     # eigene Breite bleibt
        self.assertEqual(menu.buttons[1].size, [489, 8])
        menu_design.set_style(project, menu.id, kind=STYLE_TEXT)
        self.assertEqual([(s.x, s.y, s.width, s.height) for s in preview_menu_specs(project, menu)], text_boxes)

    def test_fixed_position_wins(self):
        project, menu = shape_project()
        menu.buttons[0].position = [100, 200]
        spec = preview_menu_specs(project, menu)[0]
        self.assertEqual((spec.x, spec.y), (100, 200))

    def test_size_is_clamped(self):
        project, menu = shape_project(width=3, height=2)
        spec = preview_menu_specs(project, menu)[0]
        self.assertEqual((spec.width, spec.height), (MIN_SIZE, MIN_SIZE))

    @staticmethod
    def _as_text(project, menu):
        clone = DiscProject.from_dict(project.to_dict())
        clone.main_menu.button_style.kind = STYLE_TEXT
        return clone, clone.main_menu


class TestPalette(unittest.TestCase):
    def _text_page(self):
        buttons = []
        for n, text in enumerate(("FILM STARTEN", "KAPITEL", "SPRACHE", "EXTRAS"), start=1):
            imgs = [create_button_image(text, 380, 70, s) for s in ("normal", "selected", "activated")]
            buttons.append(MenuButton(n, 100, 100 * n, *imgs, n, n, n, n))
        return MenuPage(page_id=0, buttons=buttons)

    def test_without_priority_byte_identical(self):
        page = self._text_page()
        compiler = IGSCompiler()
        self.assertEqual(compiler.compile_pages([page]), compiler.compile_pages([page], priority_images=None))

    def test_shape_color_exact_next_to_text_buttons(self):
        from modules.igs.palette import PaletteBuilder, rgba_to_ycrcba
        style = ShapeStyle(shape=SHAPE_CIRCLE, color_selected=RED)
        shape = create_shape_image(style, 60, 40, "selected")
        builder = PaletteBuilder()
        builder.quantize_image(shape)                 # wie priority_images im Compiler
        for btn in self._text_page().buttons:
            for img in (btn.normal_image, btn.selected_image, btn.activated_image):
                builder.quantize_image(img)
        indices, _, _ = builder.quantize_image(shape)
        full = next(i for i, p in zip(indices, colors_list(shape)) if p[3] == 255)
        self.assertEqual(builder.palette.entries[full], rgba_to_ycrcba(0xEF, 0x44, 0x44, 255))


def colors_list(img):
    return list(img.get_flattened_data() if hasattr(img, "get_flattened_data") else img.getdata())


class TestSimulation(unittest.TestCase):
    def test_shape_menu_on_simulated_disc(self):
        from modules.bdsim.disc import load_disc
        from modules.bdsim.graphics import ButtonImages
        from modules.sim_disc import build_simulation_disc

        from core.disc_edit import set_chapter_times
        from core.menu_templates import create_chapter_menus

        # Hauptmenü (Seite 0) mit Text-Buttons, Kapitelmenü mit roten Linien:
        # die farbreichen Text-Buttons kommen zuerst, die Formfarbe muss trotzdem exakt bleiben
        project = text_starter()
        film = project.films[0]
        film.video_base = "film.264"
        set_chapter_times(film, ["00:00:00.000", "00:00:04.000", "00:00:08.000"])
        chapters = create_chapter_menus(project, film.id)[0]
        chapters.button_style.kind = STYLE_SHAPE
        chapters.button_style.color_selected = RED
        chapters.button_style.opacity_normal = 0
        with tempfile.TemporaryDirectory() as tmp:
            sim = build_simulation_disc(project, os.path.join(tmp, "SIM"))
            disc = load_disc(sim.root)
            comp = disc.compositions[0]
            page = comp.page(build_export_plan(project).page_ids[chapters.id])
            images = ButtonImages(comp)
            for button in page.buttons():
                w, h, data = images.rgba(button.selected[0], page.palette_id)
                self.assertEqual((w, h), (300, 8))
                r, g, b, a = data[0:4]
                self.assertEqual(a, 255)
                self.assertLessEqual(max(abs(r - 0xEF), abs(g - 0x44), abs(b - 0x44)), 3)
                w, h, data = images.rgba(button.normal[0], page.palette_id)
                self.assertTrue(all(data[i] == 0 for i in range(3, len(data), 4)))   # unsichtbar


class TestStudioUI(unittest.TestCase):
    def setUp(self):
        from gui.studio.main_window import StudioWindow
        self.win = StudioWindow(persist_layout=False)
        self.ctrl = self.win.controller
        self.menu = self.ctrl.project.main_menu

    def tearDown(self):
        self.ctrl.undo_stack.setClean()
        self.win.close()

    def test_inspector_style_and_undo(self):
        self.win.scene.select_node(self.menu.id)
        app_instance.processEvents()
        page = self.win.inspector.menu_page
        self.assertEqual(self.menu.button_style.kind, STYLE_SHAPE)        # Startvorlage ab v1.14.5
        self.assertTrue(page.shape_box.isVisibleTo(page))
        page.switch_style.buttons[STYLE_TEXT].click()                     # Umschalter Text | Form
        app_instance.processEvents()
        self.assertEqual(self.ctrl.project.main_menu.button_style.kind, STYLE_TEXT)
        self.assertFalse(page.shape_box.isVisibleTo(page))
        self.assertEqual(page.switch_style.value(), STYLE_TEXT)
        self.ctrl.set_button_style(self.menu.id, kind=STYLE_SHAPE)
        app_instance.processEvents()
        self.assertTrue(page.shape_box.isVisibleTo(page))
        self.assertEqual(page.switch_style.value(), STYLE_SHAPE)
        self.ctrl.set_button_style(self.menu.id, color_selected=RED, width=200)
        self.assertEqual(page.state_rows["selected"][1].color(), RED)
        self.ctrl.undo_stack.undo()
        self.ctrl.undo_stack.undo()
        self.assertEqual(self.ctrl.project.main_menu.button_style.kind, STYLE_TEXT)

    def test_look_switch_with_selected_button(self):
        """v1.14.5: mit ausgewähltem Button zeigt der Inspektor den Stil des Menüs und kann ihn umschalten."""
        self.win.scene.select_node(self.menu.id)
        self.ctrl.select_button(self.menu.id, self.menu.buttons[0].id)
        app_instance.processEvents()
        page = self.win.inspector.menu_page
        self.assertTrue(page.style_bar.isVisibleTo(page))
        self.assertFalse(page.card_style.isVisibleTo(page))
        self.assertIn("Hauptmenü", page.lbl_look_hint.text())
        self.assertEqual(page.switch_look.value(), STYLE_SHAPE)
        page.switch_look.buttons[STYLE_TEXT].click()
        app_instance.processEvents()
        self.assertEqual(self.ctrl.project.main_menu.button_style.kind, STYLE_TEXT)
        self.assertEqual(page.switch_look.value(), STYLE_TEXT)
        page.btn_look_more.click()                                        # „Form & Farben …“: zur Menü-Karte
        app_instance.processEvents()
        self.assertTrue(page.card_style.isVisibleTo(page))
        self.assertFalse(page.style_bar.isVisibleTo(page))

    def test_viewer_shows_invisible_shape_dotted(self):
        self.win.scene.select_node(self.menu.id)
        self.ctrl.set_button_style(self.menu.id, kind=STYLE_SHAPE, width=300, height=8, opacity_normal=0)
        app_instance.processEvents()
        preview = self.win.viewer.menu_preview
        preview.show_menu(self.ctrl.project, self.ctrl.project.main_menu)
        items = list(preview.items.values())
        self.assertTrue(items)
        for item in items:
            self.assertEqual((item.pixmap().width(), item.pixmap().height()), (300, 8))
            self.assertGreaterEqual(item.hit_rect().height(), 24)
        preview.state = "normal"
        preview.show_menu(self.ctrl.project, self.ctrl.project.main_menu)
        self.assertTrue(all(i.show_outline for i in preview.items.values()))   # unsichtbar: gepunktet


if __name__ == "__main__":
    unittest.main()
