# tests/test_igs_compiler.py
import unittest
from PIL import Image, ImageDraw
from modules.igs.compiler import IGSCompiler, MenuButton
from modules.igs.segments import SEGMENT_ICS, SEGMENT_PDS, SEGMENT_ODS, SEGMENT_END

class TestIGSCompiler(unittest.TestCase):
    def test_compile_two_button_menu(self):
        # Erzeuge 3 Test-Grafiken für Button 1 (Normal, Selected, Activated)
        w, h = 120, 40
        btn1_norm = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d1 = ImageDraw.Draw(btn1_norm)
        d1.rectangle([0, 0, w-1, h-1], outline=(200, 200, 200, 255), fill=(40, 40, 40, 200))

        btn1_sel = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d2 = ImageDraw.Draw(btn1_sel)
        d2.rectangle([0, 0, w-1, h-1], outline=(255, 215, 0, 255), fill=(80, 80, 20, 220)) # Gold

        btn1_act = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d3 = ImageDraw.Draw(btn1_act)
        d3.rectangle([0, 0, w-1, h-1], outline=(255, 255, 255, 255), fill=(255, 215, 0, 255))

        btn1 = MenuButton(
            button_id=1,
            x=800, y=500,
            normal_image=btn1_norm,
            selected_image=btn1_sel,
            activated_image=btn1_act,
            upper_id=2, lower_id=2, left_id=1, right_id=1,
            target_playlist_id=1
        )

        btn2 = MenuButton(
            button_id=2,
            x=800, y=600,
            normal_image=btn1_norm,
            selected_image=btn1_sel,
            activated_image=btn1_act,
            upper_id=1, lower_id=1, left_id=2, right_id=2,
            target_playlist_id=2
        )

        compiler = IGSCompiler()
        pes_stream = compiler.compile_menu([btn1, btn2])

        # Prüfe PES-Header und dass jedes Segment in einem eigenen PES-Paket liegt
        self.assertGreater(len(pes_stream), 0)
        pes_prefix = bytes([0x00, 0x00, 0x01, 0xBD])
        self.assertEqual(pes_stream[:4], pes_prefix)
        # 1x ICS, 1x PDS, 6x ODS (3 pro Button), 1x END -> mindestens 9 PES Pakete
        self.assertGreaterEqual(pes_stream.count(pes_prefix), 9)

        # Prüfe, dass Segmente im Stream vorkommen
        # ICS (0x18), PDS (0x14), ODS (0x15), END (0x80)
        self.assertIn(bytes([SEGMENT_ICS]), pes_stream)
        self.assertIn(bytes([SEGMENT_PDS]), pes_stream)
        self.assertIn(bytes([SEGMENT_ODS]), pes_stream)
        self.assertIn(bytes([SEGMENT_END, 0x00, 0x00]), pes_stream)

if __name__ == '__main__':
    unittest.main()
