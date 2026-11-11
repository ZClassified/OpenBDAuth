# tests/test_mpls_clpi_generator.py
import unittest
import struct
import os
import tempfile
from modules.mpls.clpi_generator import build_igs_clpi, write_clpi_file
from modules.mpls.mpls_generator import build_menu_mpls, write_menu_mpls_file

class TestMPLSCLPIGenerator(unittest.TestCase):
    def test_clpi_structure(self):
        num_pkts = 150
        clpi_bytes = build_igs_clpi(num_source_packets=num_pkts, duration_sec=10.0, fps=23.976, igs_pid=0x1400, lang="deu")

        # Prüfe Magic & Version: HDMV0200
        self.assertEqual(clpi_bytes[:8], b"HDMV0200")

        # Prüfe Offsets im 40-Byte Header
        seq_off, prog_off, cpi_off, mark_off, ext_off = struct.unpack(">IIIII", clpi_bytes[8:28])
        self.assertGreater(seq_off, 40)
        self.assertGreater(prog_off, seq_off)
        self.assertGreater(cpi_off, prog_off)
        self.assertGreater(mark_off, cpi_off)

        # Prüfe application_type = 5 (SubTS for preloaded stream nach BD-ROM Part 3)
        self.assertEqual(clpi_bytes[47], 5, "application_type muss 5 (preloaded SubTS) sein")

        # Prüfe SequenceInfo Byte-Layout nach BD-ROM Part 3 Section 5.4.4
        self.assertEqual(clpi_bytes[seq_off + 4], 0, "SequenceInfo Byte 0 muss Reserved=0 sein")
        self.assertEqual(clpi_bytes[seq_off + 5], 1, "num_atc_sequences muss 1 sein")
        self.assertEqual(clpi_bytes[seq_off + 10], 1, "num_stc_sequences muss 1 sein")
        self.assertEqual(clpi_bytes[seq_off + 11], 0, "offset_stc_id muss 0 sein")
        pcr_pid = struct.unpack(">H", clpi_bytes[seq_off + 12 : seq_off + 14])[0]
        self.assertEqual(pcr_pid, 0x1400, "pcr_pid in CLPI SequenceInfo muss 0x1400 (IGS TS PMT PCR) sein")
        pts_start_45k, pts_end_45k = struct.unpack(">II", clpi_bytes[seq_off + 18 : seq_off + 26])
        self.assertEqual(pts_start_45k, 27000000, "presentation_start_time muss 27000000 (45 kHz) sein")
        self.assertEqual(pts_end_45k, 27001876, "presentation_end_time muss 27001876 (exakt 1 Frame bei 23.976 fps) sein")

        # Prüfe, dass CPI für Preload-SubClip leer ist (Länge = 0)
        cpi_len = struct.unpack(">I", clpi_bytes[cpi_off : cpi_off + 4])[0]
        self.assertEqual(cpi_len, 0, "CPI für Preload-SubClip muss Länge 0 haben")

        # Prüfe, dass IGS Stream Typ 0x91 und PID 0x1400 enthalten sind
        self.assertIn(bytes([0x91]), clpi_bytes)
        self.assertIn(struct.pack(">H", 0x1400), clpi_bytes)
        self.assertIn(b"deu", clpi_bytes)

        # Prüfe Dateischreiben
        with tempfile.TemporaryDirectory() as tmp:
            clpi_path = os.path.join(tmp, "00001.clpi")
            write_clpi_file(clpi_path, num_packets=num_pkts, fps=23.976)
            self.assertTrue(os.path.exists(clpi_path))
            self.assertEqual(os.path.getsize(clpi_path), len(clpi_bytes))

    def test_mpls_structure(self):
        mpls_bytes = build_menu_mpls(
            bg_clip_id="00000",
            igs_clip_id="00001",
            duration_sec=10.0,
            fps=23.976,
            video_pid=0x1011,
            igs_pid=0x1400,
            lang="deu"
        )

        # Prüfe Magic & Version: MPLS0200
        self.assertEqual(mpls_bytes[:8], b"MPLS0200")

        # Prüfe die 3 Offsets im 40-Byte Header nach BD-ROM Part 3, Section 5.3.2 / 5.3.3:
        pl_off, mark_off, ext_off = struct.unpack(">III", mpls_bytes[8:20])
        self.assertGreater(pl_off, 40, "PlayList_start_address muss nach AppInfo (40) liegen")
        self.assertGreater(mark_off, pl_off, "PlayListMark_start_address muss nach PlayList liegen")
        self.assertEqual(ext_off, 0, "ExtensionData_start_address = 0 (nicht vorhanden)")
        self.assertEqual(mpls_bytes[20:40], b"\x00" * 20, "Header Bytes 20..39 müssen 20 Bytes Reserved (Nullen) sein")

        # Prüfe Clip-IDs
        self.assertIn(b"00000M2TS", mpls_bytes) # Hintergrund
        self.assertIn(b"00001M2TS", mpls_bytes) # IGS SubClip

        # Prüfe SubPath Type 3 (Interactive Graphics Menu) und is_repeat = 0
        self.assertIn(bytes([0x00, 0x03, 0x00, 0x00]), mpls_bytes)

        # Prüfe SubPlayItem Dauer: Exakt 1 Frame (1876 Ticks bei 23.976 fps)
        self.assertIn(struct.pack(">II", 27000000, 27001876), mpls_bytes)

        # Prüfe sync_play_item_id = 0 und sync_start_pts = 0 (Preload!)
        self.assertIn(struct.pack(">HI", 0, 0), mpls_bytes)

        # Prüfe Dateischreiben
        with tempfile.TemporaryDirectory() as tmp:
            mpls_path = os.path.join(tmp, "00000.mpls")
            write_menu_mpls_file(mpls_path, bg_clip_id="00000", igs_clip_id="00001", fps=23.976)
            self.assertTrue(os.path.exists(mpls_path))
            self.assertEqual(os.path.getsize(mpls_path), len(mpls_bytes))

    def test_stn_entries_have_fixed_size(self):
        """stream_entry immer 9 Bytes, stream_attributes immer 5 Bytes (wie tsMuxeR)."""
        from modules.mpls.mpls_generator import build_movie_mpls
        menu = build_menu_mpls(bg_clip_id="00001", igs_clip_id="00002", fps=25.0, lang="deu")
        movie = build_movie_mpls(clip_id="00003", fps=25.0, audio_pid=0x1100, lang="eng")
        for data, expected_streams in ((menu, 3), (movie, 2)):
            pl_off = struct.unpack(">I", data[8:12])[0]
            pi = pl_off + 10                       # length(4) + reserved(2) + counts(4)
            stn = pi + 2 + 32                      # PlayItem-Länge + fester Teil bis zur STN
            stn_len = struct.unpack(">H", data[stn:stn + 2])[0]
            body = data[stn + 2:stn + 2 + stn_len]
            self.assertEqual(sum(body[2:9]), expected_streams)
            pos, entries = 14, []
            for _ in range(expected_streams):
                self.assertEqual(body[pos], 9)
                entry = body[pos + 1:pos + 10]
                pos += 10
                self.assertEqual(body[pos], 5)
                attr = body[pos + 1:pos + 6]
                pos += 6
                entries.append((entry, attr))
            self.assertEqual(pos, stn_len)
            self.assertEqual(entries[0][0], bytes([1, 0x10, 0x11]) + bytes(6))
            self.assertEqual(entries[0][1], bytes([0x1B, 0x43, 0, 0, 0]))
            self.assertEqual(entries[1][0], bytes([1, 0x11, 0x00]) + bytes(6))
        # IG-Eintrag der Menü-Playlist: SubPath 0, SubClip 0, PID 0x1400; Sprache mit Füllbyte
        self.assertIn(bytes([9, 2, 0, 0, 0x14, 0x00]) + bytes(4) + bytes([5, 0x91]) + b"deu" + bytes(1), menu)
        self.assertIn(bytes([5, 0x81, 0x31]) + b"eng", movie)

if __name__ == '__main__':
    unittest.main()
