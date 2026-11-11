# tests/test_srt_to_sup.py
import unittest
import tempfile
import os
import struct

from modules.subtitles.srt_to_sup import (
    parse_timestamp_to_seconds, parse_srt_file,
    build_sup_cue_bytes, convert_srt_to_sup,
    render_subtitle_image, has_cjk, fps_to_pgs_rate_byte
)
from modules.bdmv.index_generator import build_index_bdmv
from modules.bdmv.movie_object_generator import build_standard_movie_objects
from core.meta_builder import MetaBuilder
from core.project_state import ProjectState, MediaTitle


class TestSrtToSup(unittest.TestCase):
    def test_parse_timestamp(self):
        self.assertAlmostEqual(parse_timestamp_to_seconds("00:00:01,500"), 1.5)
        self.assertAlmostEqual(parse_timestamp_to_seconds("01:02:03.250"), 3723.25)
        self.assertAlmostEqual(parse_timestamp_to_seconds("02:15,000"), 135.0)

    def test_fps_to_pgs_rate_byte(self):
        # 24.000 darf nicht als 23.976 eingeordnet werden (liegen nur 0.024 auseinander)
        self.assertEqual(fps_to_pgs_rate_byte(23.976), 0x10)
        self.assertEqual(fps_to_pgs_rate_byte(24000 / 1001), 0x10)
        self.assertEqual(fps_to_pgs_rate_byte(24.0), 0x20)
        self.assertEqual(fps_to_pgs_rate_byte(25.0), 0x30)
        self.assertEqual(fps_to_pgs_rate_byte(29.97), 0x40)
        self.assertEqual(fps_to_pgs_rate_byte(50.0), 0x60)
        self.assertEqual(fps_to_pgs_rate_byte(59.94), 0x70)
        self.assertEqual(fps_to_pgs_rate_byte(12.0), 0x10)  # unbekannt -> Fallback

    def test_parse_srt_file_formatting(self):
        srt_text = """1
00:00:01,000 --> 00:00:04,500
Hallo <i>Welt</i>! <b>Wichtig!</b>

2
00:00:05,200 --> 00:00:08,000
<font color="#ffff00">Zweite Zeile</font>
Mit Absatz & Sonderzeichen: äöü ÄÖÜ ß!
"""
        with tempfile.TemporaryDirectory() as tmp:
            srt_path = os.path.join(tmp, "sub.srt")
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write(srt_text)

            cues = parse_srt_file(srt_path)
            self.assertEqual(len(cues), 2)
            self.assertAlmostEqual(cues[0][0], 1.0)
            self.assertAlmostEqual(cues[0][1], 4.5)
            self.assertEqual(cues[0][2], "Hallo Welt! Wichtig!")

            self.assertAlmostEqual(cues[1][0], 5.2)
            self.assertAlmostEqual(cues[1][1], 8.0)
            self.assertIn("äöü ÄÖÜ ß!", cues[1][2])

    def test_convert_srt_to_sup_binary(self):
        srt_text = """1
00:00:02,000 --> 00:00:05,000
Erster Test-Untertitel für OpenBDAuth
"""
        with tempfile.TemporaryDirectory() as tmp:
            srt_path = os.path.join(tmp, "test.srt")
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write(srt_text)

            sup_path = os.path.join(tmp, "test.sup")
            res_path = convert_srt_to_sup(srt_path, sup_path)
            self.assertEqual(res_path, sup_path)
            self.assertTrue(os.path.exists(sup_path))

            with open(sup_path, "rb") as f_sup:
                sup_bytes = f_sup.read()
            self.assertGreater(len(sup_bytes), 100)

            # Prüfe, dass Segmente mit b"PG" beginnen
            self.assertEqual(sup_bytes[:2], b"PG")

            # Segmente durchlaufen und Typen validieren
            offset = 0
            seg_types = []
            while offset < len(sup_bytes):
                magic = sup_bytes[offset:offset+2]
                self.assertEqual(magic, b"PG")
                pts, dts, seg_type, seg_len = struct.unpack(">IIBH", sup_bytes[offset+2:offset+13])
                seg_types.append(seg_type)
                offset += 13 + seg_len

            # Es müssen PCS (0x16), WDS (0x17), PDS (0x14), ODS (0x15), END (0x80) vorkommen
            self.assertIn(0x16, seg_types)
            self.assertIn(0x17, seg_types)
            self.assertIn(0x14, seg_types)
            self.assertIn(0x15, seg_types)
            self.assertIn(0x80, seg_types)

    def test_meta_builder_converts_srt_to_sup(self):
        proj = ProjectState()
        proj.video_base = "C:/test/video.264"
        with tempfile.TemporaryDirectory() as tmp:
            srt_path = os.path.join(tmp, "dialog.srt")
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write("1\n00:00:01,000 --> 00:00:03,000\nHallo\n")

            proj.add_subtitle_track(srt_path, "deu")
            mb = MetaBuilder(proj)

            meta_file = os.path.join(tmp, "test.meta")
            mb.save_meta_file(meta_file)

            with open(meta_file, "r", encoding="utf-8") as f_meta:
                meta_content = f_meta.read()
            # tsMuxeR bekommt S_HDMV/PGS, nicht S_TEXT/SRT oder S_TEXT/UTF8
            self.assertNotIn("S_TEXT/SRT", meta_content)
            self.assertNotIn("S_TEXT/UTF8", meta_content)
            self.assertIn("S_HDMV/PGS", meta_content)
            self.assertIn(".sup", meta_content)
            self.assertIn("lang=deu", meta_content)

    def test_index_bdmv_playback_types(self):
        # 3 Titel generieren
        raw_indx = build_index_bdmv(num_titles=3)
        self.assertEqual(raw_indx[:8], b"INDX0200")

        # Offsets
        indexes_start, = struct.unpack(">I", raw_indx[8:12])
        idx_payload = raw_indx[indexes_start:]
        # data_len (4B)
        first_play = idx_payload[4:16]
        top_menu = idx_payload[16:28]

        # FirstPlayback muss 0x0000 (Movie/Standard nach BD-ROM Part 3) und TopMenu 0x4000 (interaktiv) aufweisen
        fp_pt = struct.unpack(">H", first_play[4:6])[0]
        tm_pt = struct.unpack(">H", top_menu[4:6])[0]
        self.assertEqual(fp_pt, 0x0000, "FirstPlayback muss standardkonform 0x0000 aufweisen")
        self.assertEqual(tm_pt, 0x4000, "TopMenu muss interaktiv 0x4000 aufweisen")

        # Titles 1..3
        num_titles = struct.unpack(">H", idx_payload[28:30])[0]
        self.assertEqual(num_titles, 3)

        for t in range(3):
            t_entry = idx_payload[30 + t*12 : 30 + (t+1)*12]
            # Filmtitel MÜSSEN 0x0000 (indx_hdmv_playback_type_movie) aufweisen!
            # Nur dann zeigt VLC Gesamtlänge und mitlaufenden Playhead!
            pt_flags = struct.unpack(">H", t_entry[4:6])[0]
            self.assertEqual(pt_flags, 0x0000, f"Titel {t+1} muss Movie-Flag 0x0000 haben")

    def test_movie_object_return_to_menu(self):
        # MovieObjects prüfen
        mobj_bytes = build_standard_movie_objects(num_titles=2)
        self.assertEqual(mobj_bytes[:8], b"MOBJ0200")

        # Titel-Objekt 1 (Hauptfilm) führt JumpObject(1) nach Filmende aus, um sauber ins TopMenu (MovieObject 1) zurückzuspringen
        # Suche nach JumpObject(1) Bytecode:
        # sub_grp=1 (BRANCH_JUMP), branch_opt=0 (INSN_JUMP_OBJECT), dst=1
        # b0 = 0x21, b1 = 0x80
        expected_jump_object_1 = bytes([0x21, 0x80, 0x00, 0x00, 0, 0, 0, 1, 0, 0, 0, 0])
        self.assertIn(expected_jump_object_1, mobj_bytes)

    def test_palette_transparency_and_cjk(self):
        # 1. CJK Detektion
        self.assertTrue(has_cjk("こんにちは世界！"))
        self.assertTrue(has_cjk("日本語字幕"))
        self.assertFalse(has_cjk("La princesse s'est encore enfuie !"))
        self.assertFalse(has_cjk("Das ist ein normaler deutscher Untertitel."))

        # 2. Rendering mit Alphatransparenz testen
        w, h, pds_bytes, rle = render_subtitle_image("Bonjour le monde !", font_size=48)
        self.assertGreater(w, 0)
        self.assertGreater(h, 0)
        self.assertGreater(len(rle), 0)
        # PDS Payload: Palette ID (1B) + Version (1B) + Entries (je 5 Bytes: id, y, cr, cb, a)
        # Eintrag 0 ist transparent (Alpha = 0)
        entry_0_id = pds_bytes[0]
        # PDS entries in render_subtitle_image begin with Entry 0: [0, 0, 128, 128, 0]
        entry_0_alpha = pds_bytes[4]
        self.assertEqual(entry_0_id, 0)
        self.assertEqual(entry_0_alpha, 0, "Index 0 MUSS 100% transparent sein (Alpha=0)!")

        # 3. Japanisches Rendering testen (kein Absturz, CJK-Font)
        w_jp, h_jp, pds_jp, rle_jp = render_subtitle_image("こんにちは世界！", font_size=48)
        self.assertGreater(w_jp, 0)
        self.assertGreater(h_jp, 0)
        self.assertGreater(len(rle_jp), 0)
        self.assertEqual(pds_jp[4], 0, "Japanischer Hintergrund muss transparent sein!")


if __name__ == "__main__":
    unittest.main()
