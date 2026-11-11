# tests/test_igs_rle.py
import unittest
from modules.igs.rle import encode_rle, decode_rle, encode_line_rle

class TestIGSRLE(unittest.TestCase):
    def test_single_pixels(self):
        # 3 einzelne verschiedene Pixel (nicht 0)
        line = [1, 2, 3]
        encoded = encode_line_rle(line)
        # Erwartet: 0x01, 0x02, 0x03 gefolgt von 0x00, 0x00 (EOL)
        self.assertEqual(encoded, bytes([1, 2, 3, 0x00, 0x00]))

    def test_short_zero_run(self):
        # 5 Nullen (L <= 63)
        line = [0, 0, 0, 0, 0]
        encoded = encode_line_rle(line)
        self.assertEqual(encoded, bytes([0x00, 5, 0x00, 0x00]))

    def test_long_zero_run(self):
        # 100 Nullen (L > 63): 100 = 0x64
        line = [0] * 100
        encoded = encode_line_rle(line)
        # 0x00, (0x40 | (100 >> 8)), (100 & 0xFF), 0x00, 0x00
        expected = bytes([0x00, 0x40, 100, 0x00, 0x00])
        self.assertEqual(encoded, expected)

    def test_short_color_run(self):
        # 10 Pixel mit Farbe 77
        line = [77] * 10
        encoded = encode_line_rle(line)
        # 0x00, (0x80 | 10), 77, 0x00, 0x00
        expected = bytes([0x00, 0x80 | 10, 77, 0x00, 0x00])
        self.assertEqual(encoded, expected)

    def test_long_color_run(self):
        # 500 Pixel mit Farbe 123 (500 = 0x01F4)
        line = [123] * 500
        encoded = encode_line_rle(line)
        # 0x00, (0xC0 | (500 >> 8)), (500 & 0xFF), 123, 0x00, 0x00
        expected = bytes([0x00, 0xC0 | 1, 0xF4, 123, 0x00, 0x00])
        self.assertEqual(encoded, expected)

    def test_roundtrip_2d_bitmap(self):
        # Erstelle ein 100x20 Testbild mit gemischten Mustern
        width = 100
        height = 20
        pixels = []
        for y in range(height):
            for x in range(width):
                if y % 2 == 0:
                    pixels.append(0 if x < 50 else (x % 250 + 1))
                else:
                    pixels.append((x * y) % 256)

        encoded = encode_rle(pixels, width, height)
        decoded = decode_rle(encoded, width, height)
        self.assertEqual(pixels, decoded)

    def test_full_hd_line_roundtrip(self):
        # Typische Menü-Scanline in 1080p (Breite 1920): Links transparent, Mitte Button, Rechts transparent
        width = 1920
        height = 2
        line1 = [0] * 600 + [45] * 720 + [0] * 600
        line2 = [0] * 1920
        pixels = line1 + line2

        encoded = encode_rle(pixels, width, height)
        decoded = decode_rle(encoded, width, height)
        self.assertEqual(pixels, decoded)

if __name__ == '__main__':
    unittest.main()
