# tests/test_multipage_menu.py
import unittest
import os
import tempfile
from core.project_state import ProjectState
from modules.menu_author import (
    build_project_menu_pages,
    generate_menu_subclip,
    inject_menu_into_bdmv
)
from modules.igs.compiler import IGSCompiler, MenuPage, MenuButton
from modules.igs.layout import MenuButtonSpec
from PIL import Image

class TestMultiPageMenu(unittest.TestCase):

    def test_build_project_menu_pages_simple(self):
        proj = ProjectState()
        pages = build_project_menu_pages(proj)
        self.assertEqual(len(pages), 1) # Nur Page 0 (Hauptmenü)
        page_id, buttons = pages[0]
        self.assertEqual(page_id, 0)
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0].text, "FILM STARTEN")

    def test_build_project_menu_pages_full(self):
        proj = ProjectState()
        proj.menu_show_chapters = True
        proj.chapters = ["00:00:00.000", "00:15:00.000", "00:30:00.000"]
        
        proj.menu_show_audio = True
        proj.audio_tracks = [{"path": "dummy.ac3", "lang": "deu"}, {"path": "dummy2.ac3", "lang": "eng"}]
        proj.subtitle_tracks = [{"path": "dummy.sup", "lang": "deu"}]

        proj.menu_show_btn2 = True
        proj.menu_btn2_text = "BONUS"

        pages = build_project_menu_pages(proj)
        self.assertEqual(len(pages), 3) # Page 0 (Main), Page 1 (Chap), Page 2 (Audio)

        # Page 0: Film starten, Kapitel, Sprache, Bonus = 4 Buttons
        p0_id, p0_btns = pages[0]
        self.assertEqual(p0_id, 0)
        self.assertEqual(len(p0_btns), 4)
        p0_texts = [b.text for b in p0_btns]
        self.assertEqual(p0_texts, ["FILM STARTEN", "KAPITEL", "SPRACHE", "BONUS"])

        # Page 1: 3 Kapitel + Zurück = 4 Buttons
        p1_id, p1_btns = pages[1]
        self.assertEqual(p1_id, 1)
        self.assertEqual(len(p1_btns), 4)
        self.assertEqual(p1_btns[-1].text, "ZURÜCK")
        self.assertEqual(p1_btns[-1].action_type, "set_page")
        self.assertEqual(p1_btns[-1].target_page_id, 0)

        # Page 2: 2 Audio + 1 Sub + 1 Sub Aus + 1 Zurück = 5 Buttons
        p2_id, p2_btns = pages[2]
        self.assertEqual(p2_id, 2)
        self.assertEqual(len(p2_btns), 5)
        p2_texts = [b.text for b in p2_btns]
        self.assertIn("TON: DEUTSCH", p2_texts)
        self.assertIn("TON: ENGLISCH", p2_texts)
        self.assertIn("UNTERTITEL: DEUTSCH", p2_texts)
        self.assertIn("UNTERTITEL AUS", p2_texts)
        self.assertIn("ZURÜCK", p2_texts)

    def test_compile_pages_multipage(self):
        compiler = IGSCompiler(width=1920, height=1080)
        img = Image.new("RGBA", (200, 50), (255, 0, 0, 255))
        
        btn1 = MenuButton(1, 100, 100, img, img, img, 1, 1, 1, 1, target_playlist_id=1)
        btn2 = MenuButton(2, 100, 200, img, img, img, 2, 2, 2, 2, target_playlist_id=1)
        
        p0 = MenuPage(page_id=0, buttons=[btn1])
        p1 = MenuPage(page_id=1, buttons=[btn2])

        pes = compiler.compile_pages([p0, p1])
        self.assertGreater(len(pes), 0)
        # Muss gültigen PES Startcode enthalten: 0x00 0x00 0x01
        self.assertEqual(pes[:3], b"\x00\x00\x01")

    def test_generate_menu_subclip_with_project(self):
        proj = ProjectState()
        proj.menu_show_chapters = True
        proj.chapters = ["00:00:00.000", "00:10:00.000"]
        proj.menu_show_audio = True
        proj.audio_tracks = [{"path": "a.ac3", "lang": "deu"}]

        pages_specs = build_project_menu_pages(proj)

        with tempfile.TemporaryDirectory() as tmp:
            m2ts_path = os.path.join(tmp, "00002.m2ts")
            clpi_path = os.path.join(tmp, "00002.clpi")

            ok = generate_menu_subclip(
                output_m2ts_path=m2ts_path,
                output_clpi_path=clpi_path,
                pages_specs=pages_specs,
                duration_sec=5.0
            )
            self.assertTrue(ok)
            self.assertTrue(os.path.exists(m2ts_path))
            self.assertTrue(os.path.exists(clpi_path))
            self.assertEqual(os.path.getsize(m2ts_path) % 192, 0)

    def test_inject_menu_with_project(self):
        proj = ProjectState()
        proj.menu_show_chapters = True
        proj.chapters = ["00:00:00.000", "00:20:00.000"]
        proj.menu_show_audio = True
        proj.audio_tracks = [{"path": "a.ac3", "lang": "deu"}]

        with tempfile.TemporaryDirectory() as tmp:
            bdmv_dir = os.path.join(tmp, "BDMV")
            os.makedirs(os.path.join(bdmv_dir, "PLAYLIST"), exist_ok=True)
            
            ok = inject_menu_into_bdmv(
                bdmv_dir=bdmv_dir,
                duration_sec=2.0,
                project=proj
            )
            self.assertTrue(ok)
            self.assertTrue(os.path.exists(os.path.join(bdmv_dir, "STREAM", "00002.m2ts")))
            self.assertTrue(os.path.exists(os.path.join(bdmv_dir, "CLIPINF", "00002.clpi")))

if __name__ == "__main__":
    unittest.main()
