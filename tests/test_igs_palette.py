# tests/test_igs_palette.py
import unittest
from PIL import Image
from modules.igs.palette import rgba_to_ycrcba, Palette, PaletteBuilder

class TestIGSPalette(unittest.TestCase):
    def test_transparency(self):
        y, cr, cb, t = rgba_to_ycrcba(255, 255, 255, 0)
        self.assertEqual(t, 0)
        self.assertEqual(y, 16)
        self.assertEqual(cr, 128)
        self.assertEqual(cb, 128)

    def test_white_pixel(self):
        y, cr, cb, t = rgba_to_ycrcba(255, 255, 255, 255)
        self.assertEqual(t, 255)
        # Reines Weiß sollte nahe Maximum Y=235 und neutralem Farbdifferenzwert 128 liegen
        self.assertEqual(y, 235)
        self.assertEqual(cr, 128)
        self.assertEqual(cb, 128)

    def test_black_pixel(self):
        y, cr, cb, t = rgba_to_ycrcba(0, 0, 0, 255)
        self.assertEqual(t, 255)
        self.assertEqual(y, 16)
        self.assertEqual(cr, 128)
        self.assertEqual(cb, 128)

    def test_pds_payload_length(self):
        palette = Palette(palette_id=0, palette_version=0)
        payload = palette.to_pds_payload()
        # 1 Byte ID + 1 Byte Version + 256 Einträge * 5 Bytes = 1282 Bytes
        self.assertEqual(len(payload), 1 + 1 + 256 * 5)
        self.assertEqual(payload[0], 0) # ID
        self.assertEqual(payload[1], 0) # Version
        # Erster Eintrag: Index 0, Y=16, Cr=128, Cb=128, T=0
        self.assertEqual(payload[2:7], bytes([0, 16, 128, 128, 0]))

    def test_palette_builder_image(self):
        builder = PaletteBuilder()
        # Erstelle ein kleines 2x2 RGBA Testbild
        img = Image.new("RGBA", (2, 2))
        img.putpixel((0, 0), (0, 0, 0, 0))       # Transparent
        img.putpixel((1, 0), (255, 255, 255, 255)) # Weiß
        img.putpixel((0, 1), (255, 0, 0, 255))     # Rot
        img.putpixel((1, 1), (0, 0, 0, 0))       # Transparent

        indices, w, h = builder.quantize_image(img)
        self.assertEqual((w, h), (2, 2))
        self.assertEqual(len(indices), 4)
        # Transparent muss Index 0 sein
        self.assertEqual(indices[0], 0)
        self.assertEqual(indices[3], 0)
        # Sichtbare Farben müssen Indizes > 0 haben
        self.assertGreater(indices[1], 0)
        self.assertGreater(indices[2], 0)
        self.assertNotEqual(indices[1], indices[2])

    def test_entry_255_stays_transparent(self):
        """Eintrag 255 wird nie vergeben (Panasonic löscht die Grafikebene damit)."""
        builder = PaletteBuilder()
        img = Image.new("RGBA", (300, 1))
        for x in range(300):
            img.putpixel((x, 0), (x % 256, (x * 7) % 256, 200, 255))
        indices, _, _ = builder.quantize_image(img)
        self.assertNotIn(255, indices)
        self.assertEqual(max(indices), 254)
        self.assertEqual(builder.palette.entries[255], (16, 128, 128, 0))
        payload = builder.palette.to_pds_payload()
        self.assertEqual(payload[2 + 255 * 5:2 + 256 * 5], bytes([255, 16, 128, 128, 0]))

if __name__ == '__main__':
    unittest.main()
