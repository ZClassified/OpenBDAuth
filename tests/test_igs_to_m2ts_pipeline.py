# tests/test_igs_to_m2ts_pipeline.py
import unittest
import os
import tempfile
from PIL import Image, ImageDraw
from modules.igs.compiler import IGSCompiler, MenuButton
from modules.m2ts.m2ts_writer import build_igs_m2ts, write_igs_m2ts_file, M2TS_PACKET_SIZE
from modules.m2ts.ts_packetizer import SYNC_BYTE, PID_PAT, PID_PMT, PID_IGS

class TestIGSToM2TSPipeline(unittest.TestCase):
    def test_full_pipeline(self):
        # 1. Erstelle zwei Buttons mit echten Grafiken
        w, h = 150, 50
        norm = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d1 = ImageDraw.Draw(norm)
        d1.rectangle([0, 0, w-1, h-1], outline=(200, 200, 200, 255), fill=(30, 30, 30, 220))

        sel = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d2 = ImageDraw.Draw(sel)
        d2.rectangle([0, 0, w-1, h-1], outline=(255, 215, 0, 255), fill=(70, 70, 0, 240))

        act = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d3 = ImageDraw.Draw(act)
        d3.rectangle([0, 0, w-1, h-1], outline=(255, 255, 255, 255), fill=(255, 215, 0, 255))

        btn1 = MenuButton(1, 800, 450, norm, sel, act, upper_id=2, lower_id=2, left_id=1, right_id=1, target_playlist_id=1)
        btn2 = MenuButton(2, 800, 550, norm, sel, act, upper_id=1, lower_id=1, left_id=2, right_id=2, target_playlist_id=2)

        # 2. IGS Kompilierung
        compiler = IGSCompiler()
        pes_stream = compiler.compile_menu([btn1, btn2])
        self.assertGreater(len(pes_stream), 0)

        # 3. M2TS Paketierung
        m2ts_bytes = build_igs_m2ts(pes_stream, igs_pid=PID_IGS)
        self.assertGreater(len(m2ts_bytes), 0)
        self.assertEqual(len(m2ts_bytes) % M2TS_PACKET_SIZE, 0)

        # 4. Datei-Export im Temp-Verzeichnis testen
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = os.path.join(tmpdir, "00001.m2ts")
            write_igs_m2ts_file(out_file, pes_stream, igs_pid=PID_IGS)
            self.assertTrue(os.path.exists(out_file))
            self.assertEqual(os.path.getsize(out_file), len(m2ts_bytes))

        # 5. Struktur-Validierung
        num_pkts = len(m2ts_bytes) // M2TS_PACKET_SIZE
        # Paket 0: PAT
        p0 = m2ts_bytes[:M2TS_PACKET_SIZE]
        self.assertEqual(p0[4], SYNC_BYTE)
        pid0 = ((p0[5] & 0x1F) << 8) | p0[6]
        self.assertEqual(pid0, PID_PAT)

        # Paket 1: PMT
        p1 = m2ts_bytes[M2TS_PACKET_SIZE:2*M2TS_PACKET_SIZE]
        self.assertEqual(p1[4], SYNC_BYTE)
        pid1 = ((p1[5] & 0x1F) << 8) | p1[6]
        self.assertEqual(pid1, PID_PMT)

        # Paket 2+: IGS
        p2 = m2ts_bytes[2*M2TS_PACKET_SIZE:3*M2TS_PACKET_SIZE]
        self.assertEqual(p2[4], SYNC_BYTE)
        pid2 = ((p2[5] & 0x1F) << 8) | p2[6]
        self.assertEqual(pid2, PID_IGS)

if __name__ == '__main__':
    unittest.main()
