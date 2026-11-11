# tests/test_menu_design.py
"""Menü-Designer (v1.9.3; ab v1.12 freie Buttons), Qt-frei: Verschieben, Pfeiltasten aus der Lage."""

import unittest

from core.disc_adapter import build_export_plan
from core.disc_edit import starter_project, set_chapter_times
from core.disc_model import DiscProject
from core.menu_design import move_items
from tests.project_factory import text_starter
from core.menu_templates import create_chapter_menus
from modules.igs.layout import MenuButtonSpec, MenuLayoutEngine


def spec(bid, x, y, w=100, h=50):
    return MenuButtonSpec(button_id=bid, text=str(bid), x=x, y=y, width=w, height=h)


def page_specs(project, menu_id):
    plan = build_export_plan(project)
    return dict(plan.pages_specs)[plan.page_ids[menu_id]]


def geometry(specs):
    return [(s.button_id, s.x, s.y, s.upper_id, s.lower_id, s.left_id, s.right_id) for s in specs]


def reachable(specs):
    by_id = {s.button_id: s for s in specs}
    seen, todo = set(), [specs[0].button_id]
    while todo:
        bid = todo.pop()
        if bid not in seen:
            seen.add(bid)
            s = by_id[bid]
            todo += [s.upper_id, s.lower_id, s.left_id, s.right_id]
    return seen


class TestSpatialDpad(unittest.TestCase):
    def test_grid_neighbours_and_wrap(self):
        # 1 2
        # 3 4
        specs = [spec(1, 100, 100), spec(2, 300, 100), spec(3, 100, 300), spec(4, 300, 300)]
        MenuLayoutEngine.link_spatial(specs)
        s = {x.button_id: x for x in specs}
        self.assertEqual((s[1].right_id, s[1].lower_id, s[1].left_id, s[1].upper_id), (2, 3, 2, 3))
        self.assertEqual((s[4].left_id, s[4].upper_id, s[4].right_id, s[4].lower_id), (3, 2, 3, 2))

    def test_prefers_aligned_over_diagonal(self):
        # 1 liegt über 3 (leicht versetzt); 2 ist diagonal näher, aber seitlich weit weg
        specs = [spec(1, 100, 100), spec(2, 400, 180), spec(3, 110, 330)]
        MenuLayoutEngine.link_spatial(specs)
        self.assertEqual(specs[0].lower_id, 3)

    def test_single_row_and_single_button(self):
        row = [spec(1, 100, 900), spec(2, 400, 903), spec(3, 700, 898)]
        MenuLayoutEngine.link_spatial(row)
        self.assertEqual([(s.upper_id, s.lower_id) for s in row], [(1, 1), (2, 2), (3, 3)])
        self.assertEqual((row[0].right_id, row[2].right_id, row[0].left_id), (2, 1, 3))
        one = [spec(7, 0, 0)]
        MenuLayoutEngine.link_spatial(one)
        self.assertEqual((one[0].upper_id, one[0].left_id), (7, 7))


class TestMove(unittest.TestCase):
    def setUp(self):
        self.project = starter_project()
        film = self.project.films[0]
        film.video_base = "film.264"
        set_chapter_times(film, [f"00:{i:02d}:00.000" for i in range(6)])
        (self.page,) = create_chapter_menus(self.project, film.id)
        self.before = geometry(page_specs(self.project, self.page.id))

    def test_moving_one_button_moves_only_it(self):
        """v1.12: jeder Button ist frei; es gibt kein Raster mehr, das als Ganzes wandert."""
        first = self.page.buttons[0]
        x, y = first.position
        move_items(self.project, self.page.id, positions={first.id: (x + 40, y - 100)})
        after = page_specs(self.project, self.page.id)
        before = {b[0]: b for b in self.before}
        self.assertEqual((after[0].x, after[0].y), (x + 40, y - 100))
        for s in after[1:]:
            self.assertEqual((s.x, s.y), before[s.button_id][1:3])
        self.assertEqual(reachable(after), {s.button_id for s in after})

    def test_moved_back_button_is_reached_by_arrows_from_its_new_place(self):
        back = self.page.buttons[-1]        # ZURÜCK, liegt normal unter dem Raster
        move_items(self.project, self.page.id, positions={back.id: (60, 60)})   # nach oben links
        specs = page_specs(self.project, self.page.id)
        s = {x.button_id: x for x in specs}
        back_no = len(self.page.buttons)
        self.assertEqual((s[back_no].x, s[back_no].y), (60, 60))
        self.assertEqual(s[1].upper_id, back_no)      # Kapitel 1 → hoch → ZURÜCK
        self.assertEqual(s[back_no].lower_id, 1)
        self.assertEqual(reachable(specs), set(s))

    def test_round_trip(self):
        first = self.page.buttons[0]
        move_items(self.project, self.page.id, positions={first.id: (5, 7)})
        loaded = DiscProject.from_dict(self.project.to_dict())
        self.assertEqual(loaded.menu(self.page.id).buttons[0].position, [5, 7])


class TestDpadOverride(unittest.TestCase):
    def setUp(self):
        self.project = starter_project()
        film = self.project.films[0]
        film.video_base = "film.264"
        set_chapter_times(film, [f"00:{i:02d}:00.000" for i in range(6)])
        (self.page,) = create_chapter_menus(self.project, film.id)

    def test_override_reaches_export_and_can_be_reset(self):
        from core.menu_design import set_dpad, auto_dpad_target, dpad_targets
        first, back = self.page.buttons[0], self.page.buttons[-1]
        auto_up = auto_dpad_target(self.project, self.page, first.id, "up")
        set_dpad(self.project, self.page.id, first.id, "up", back.id)
        specs = page_specs(self.project, self.page.id)
        self.assertEqual(specs[0].upper_id, len(self.page.buttons))
        self.assertEqual(dpad_targets(self.project, self.page)[first.id]["up"], back.id)
        self.assertEqual(auto_dpad_target(self.project, self.page, first.id, "up"), auto_up)   # ohne Überschreiben
        set_dpad(self.project, self.page.id, first.id, "up", None)
        self.assertEqual(geometry(page_specs(self.project, self.page.id)), self._geometry_without_override())
        # Überschreiben gilt auch, nachdem Buttons verschoben wurden
        move_items(self.project, self.page.id, positions={first.id: (first.position[0], first.position[1] - 100)})
        set_dpad(self.project, self.page.id, first.id, "left", back.id)
        self.assertEqual(page_specs(self.project, self.page.id)[0].left_id, len(self.page.buttons))

    def _geometry_without_override(self):
        import copy
        clean = copy.deepcopy(self.project)
        for b in clean.menu(self.page.id).buttons:
            b.dpad = {}
        return geometry(page_specs(clean, self.page.id))


class TestPreflightGeometry(unittest.TestCase):
    def _issues(self, project, level):
        from core.preflight import run_preflight
        return [i.message for i in run_preflight(project) if i.level == level]

    def test_overlap_title_safe_and_unreachable(self):
        from core.preflight import WARNING, INFO
        from core.menu_design import set_dpad
        from core.disc_edit import add_nav_button
        project = text_starter()
        project.films[0].video_base = "film.264"
        main = project.main_menu
        extra = add_nav_button(project, main.id, "EXTRAS", project.films[0].id)
        self.assertEqual(self._issues(project, WARNING), [])
        first = main.buttons[0]
        specs = page_specs(project, main.id)
        move_items(project, main.id, positions={extra.id: (specs[0].x + 50, specs[0].y + 20)})
        self.assertIn("Menü „Hauptmenü“: Die Buttons „FILM STARTEN“ und „EXTRAS“ überlappen sich.",
                      self._issues(project, WARNING))
        move_items(project, main.id, positions={extra.id: (0, 0)})
        self.assertEqual(self._issues(project, WARNING), [])
        self.assertTrue(any("„EXTRAS“ liegt außerhalb der Title-Safe-Zone" in m for m in self._issues(project, INFO)))
        main.default_button_id = first.id       # sonst startet EXTRAS (oben links, v1.14.6)
        for direction in ("up", "down", "left", "right"):
            set_dpad(project, main.id, first.id, direction, first.id)
        self.assertIn("Menü „Hauptmenü“: „EXTRAS“ ist mit den Pfeiltasten nicht erreichbar.",
                      self._issues(project, WARNING))


if __name__ == "__main__":
    unittest.main()
