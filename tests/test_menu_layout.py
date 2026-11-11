# tests/test_menu_layout.py
import unittest
from modules.igs.layout import (
    MenuButtonSpec,
    MenuLayoutEngine,
    build_main_menu_specs,
    build_chapter_menu_specs,
    build_audio_menu_specs
)

class TestMenuLayout(unittest.TestCase):
    def test_single_button_column(self):
        buttons = [MenuButtonSpec(button_id=1, text="START")]
        layouted = MenuLayoutEngine.layout_column(buttons)
        self.assertEqual(len(layouted), 1)
        b = layouted[0]
        self.assertEqual(b.x, (1920 - 380) // 2)
        self.assertEqual(b.y, 660)
        self.assertEqual(b.upper_id, 1)
        self.assertEqual(b.lower_id, 1)
        self.assertEqual(b.left_id, 1)
        self.assertEqual(b.right_id, 1)

    def test_two_button_column_wrap_around(self):
        buttons = [
            MenuButtonSpec(button_id=1, text="FILM"),
            MenuButtonSpec(button_id=2, text="EXTRAS")
        ]
        layouted = MenuLayoutEngine.layout_column(buttons)
        self.assertEqual(len(layouted), 2)
        b1, b2 = layouted[0], layouted[1]
        self.assertEqual(b1.upper_id, 2)
        self.assertEqual(b1.lower_id, 2)
        self.assertEqual(b2.upper_id, 1)
        self.assertEqual(b2.lower_id, 1)
        # Horizontale Tasten bleiben auf dem Button
        self.assertEqual(b1.left_id, 1)
        self.assertEqual(b1.right_id, 1)
        self.assertEqual(b2.left_id, 2)
        self.assertEqual(b2.right_id, 2)

    def test_three_button_column(self):
        buttons = [
            MenuButtonSpec(button_id=1, text="B1"),
            MenuButtonSpec(button_id=2, text="B2"),
            MenuButtonSpec(button_id=3, text="B3")
        ]
        layouted = MenuLayoutEngine.layout_column(buttons)
        self.assertEqual(layouted[0].upper_id, 3)
        self.assertEqual(layouted[0].lower_id, 2)
        self.assertEqual(layouted[1].upper_id, 1)
        self.assertEqual(layouted[1].lower_id, 3)
        self.assertEqual(layouted[2].upper_id, 2)
        self.assertEqual(layouted[2].lower_id, 1)

    def test_grid_2x2_navigation(self):
        # 4 Buttons in 2x2 Grid
        buttons = [
            MenuButtonSpec(button_id=1, text="B1"),
            MenuButtonSpec(button_id=2, text="B2"),
            MenuButtonSpec(button_id=3, text="B3"),
            MenuButtonSpec(button_id=4, text="B4")
        ]
        layouted = MenuLayoutEngine.layout_grid(buttons, cols=2)
        b1, b2, b3, b4 = layouted

        # Zeile 0: B1 (c0), B2 (c1)
        # Zeile 1: B3 (c0), B4 (c1)
        # B1 Vertikal: Up -> B3, Down -> B3
        self.assertEqual(b1.upper_id, 3)
        self.assertEqual(b1.lower_id, 3)
        # B1 Horizontal: Left -> B2, Right -> B2
        self.assertEqual(b1.left_id, 2)
        self.assertEqual(b1.right_id, 2)

        # B2:
        self.assertEqual(b2.upper_id, 4)
        self.assertEqual(b2.lower_id, 4)
        self.assertEqual(b2.left_id, 1)
        self.assertEqual(b2.right_id, 1)

        # B4:
        self.assertEqual(b4.upper_id, 2)
        self.assertEqual(b4.lower_id, 2)
        self.assertEqual(b4.left_id, 3)
        self.assertEqual(b4.right_id, 3)

    def test_grid_with_odd_buttons(self):
        # 3 Buttons in 2x2 Grid (ein leerer Platz unten rechts)
        buttons = [
            MenuButtonSpec(button_id=1, text="B1"),
            MenuButtonSpec(button_id=2, text="B2"),
            MenuButtonSpec(button_id=3, text="B3")
        ]
        layouted = MenuLayoutEngine.layout_grid(buttons, cols=2)
        b1, b2, b3 = layouted
        # B3 ist in (r1, c0). Nach rechts gibt es kein B4, sollte sauber auf B3 wrappen
        self.assertEqual(b3.right_id, 3)
        # B2 ist in (r0, c1). Down sollte auf B2 wrappen, da unten rechts leer ist
        self.assertEqual(b2.lower_id, 2)

    def test_button_spec_nav_commands(self):
        # Test command generation
        b_jump = MenuButtonSpec(button_id=1, text="T", action_type="jump_title", target_title_id=2)
        cmds = b_jump.get_nav_commands()
        self.assertEqual(len(cmds), 1)
        self.assertEqual(len(cmds[0]), 12)

        # Kapitel: Marke merken (Move GPR) + JumpTitle
        b_chap = MenuButtonSpec(button_id=2, text="C", action_type="play_chapter", target_title_id=1, target_chapter_id=4)
        cmds = b_chap.get_nav_commands()
        self.assertEqual(len(cmds), 2)
        self.assertTrue(all(len(c) == 12 for c in cmds))

        # Spurwahl: Ton, Untertitel-Spur und Untertitel-Anzeige nur merken (3x Move GPR)
        b_stream = MenuButtonSpec(button_id=3, text="S", action_type="set_stream", target_audio_id=2, target_subtitle_id=1, target_subtitle_on=True)
        cmds = b_stream.get_nav_commands()
        self.assertEqual(len(cmds), 3)
        self.assertTrue(all(len(c) == 12 for c in cmds))

    def test_template_main_menu(self):
        specs = build_main_menu_specs(has_extras=True, has_chapters=True, has_audio=True)
        self.assertEqual(len(specs), 4)
        texts = [b.text for b in specs]
        self.assertIn("FILM STARTEN", texts)
        self.assertIn("KAPITEL", texts)
        self.assertIn("TON & UNTERTITEL", texts)
        self.assertIn("EXTRAS", texts)

    def test_template_chapter_menu(self):
        chapters = ["00:00:00.000", "00:15:30.000", "00:45:00.000"]
        specs = build_chapter_menu_specs(chapters)
        self.assertEqual(len(specs), 4) # 3 Kapitel + 1 Zurück
        self.assertEqual(specs[-1].text, "ZURÜCK")

    def test_template_audio_menu(self):
        audio = [{"lang": "deu"}, {"lang": "eng"}]
        subs = [{"lang": "deu"}]
        specs = build_audio_menu_specs(audio, subs)
        # 2 Audio + 1 Sub + 1 Sub Aus + 1 Zurück = 5 Buttons
        self.assertEqual(len(specs), 5)

if __name__ == "__main__":
    unittest.main()
