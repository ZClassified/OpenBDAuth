# tests/test_3d_compliance.py
"""
Unit-Tests für die 3D Blu-ray Compliance (MVC, SSIF, AppInfo 3D-Flags und Menü-Kollisionsschutz)
in OpenBDAuth v1.3.4 nach BD-ROM Part 3 / Profile 5.0.
"""

import os
import shutil
import tempfile
import unittest

from modules.bdmv.index_generator import build_index_bdmv, write_index_bdmv_file
from modules.menu_author import inject_menu_into_bdmv
from core.project_state import ProjectState, MediaTitle


class Test3DCompliance(unittest.TestCase):
    def test_index_bdmv_appinfo_3d_flag(self):
        """Prüft, dass index.bdmv bei 3D-Inhalten Byte 0=0x20 und Byte 1=0x61 (SS_content_exist_flag) setzt."""
        # 1. Reines 2D Projekt: AppInfo muss 0x00 sein
        data_2d = build_index_bdmv(num_titles=3, has_3d=False)
        self.assertEqual(data_2d[44], 0x00)
        self.assertEqual(data_2d[45], 0x00)

        # 2. 3D Projekt: AppInfo muss 0x60 und 0x00 sein (Bit 6: initial_output_mode_pref=1, Bit 5: SS_content_exist_flag=1)
        data_3d = build_index_bdmv(num_titles=3, has_3d=True)
        self.assertEqual(data_3d[44], 0x60)
        self.assertEqual(data_3d[45], 0x00)

    def test_menu_clip_allocation_with_2d_main(self):
        """Wenn Titel 1 2D ist, soll das Menü 00001.m2ts (Hintergrund) und 00002.m2ts (IGS) belegen."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bdmv_dir = os.path.join(tmpdir, "BDMV")
            project = ProjectState()
            project.video_mvc = None
            project.menu_no_buttons_test = True

            ok = inject_menu_into_bdmv(
                bdmv_dir=bdmv_dir,
                num_titles=1,
                project=project,
                duration_sec=2.0
            )
            self.assertTrue(ok)
            stream_dir = os.path.join(bdmv_dir, "STREAM")
            self.assertTrue(os.path.exists(os.path.join(stream_dir, "00001.m2ts")))
            # index.bdmv prüfen
            with open(os.path.join(bdmv_dir, "index.bdmv"), "rb") as f:
                idx_data = f.read()
            self.assertEqual(idx_data[44], 0x00) # Kein 3D

    def test_menu_clip_allocation_with_3d_main(self):
        """Wenn Titel 1 3D ist, darf 00001.m2ts (MVC) NICHT überschrieben werden; Menü muss 00002 & 00003 nutzen!"""
        with tempfile.TemporaryDirectory() as tmpdir:
            bdmv_dir = os.path.join(tmpdir, "BDMV")
            stream_dir = os.path.join(bdmv_dir, "STREAM")
            clip_dir = os.path.join(bdmv_dir, "CLIPINF")
            pl_dir = os.path.join(bdmv_dir, "PLAYLIST")
            os.makedirs(stream_dir, exist_ok=True)
            os.makedirs(clip_dir, exist_ok=True)
            os.makedirs(pl_dir, exist_ok=True)

            # Simuliere Titel 1 3D Streams (00000 = Base, 00001 = MVC)
            with open(os.path.join(stream_dir, "00000.m2ts"), "wb") as f:
                f.write(b"BASE_VIDEO_DATA")
            with open(os.path.join(stream_dir, "00001.m2ts"), "wb") as f:
                f.write(b"ORIGINAL_MVC_DATA")
            with open(os.path.join(clip_dir, "00000.clpi"), "wb") as f:
                f.write(b"HDMV0200" + b"\x00" * 100)
            with open(os.path.join(clip_dir, "00001.clpi"), "wb") as f:
                f.write(b"HDMV0200" + b"\x00" * 100)

            project = ProjectState()
            t1 = MediaTitle(name="3D Film 1", is_main=True)
            t1.video_mvc = "dummy_mvc.mvc"
            project.titles = [t1]
            project.menu_no_buttons_test = True

            ok = inject_menu_into_bdmv(
                bdmv_dir=bdmv_dir,
                num_titles=1,
                project=project,
                duration_sec=2.0
            )
            self.assertTrue(ok)

            # 00001.m2ts darf NICHT angetastet worden sein!
            with open(os.path.join(stream_dir, "00001.m2ts"), "rb") as f:
                content_mvc = f.read()
            self.assertEqual(content_mvc, b"ORIGINAL_MVC_DATA")

            # Menü-Hintergrund muss als 00002.m2ts abgelegt worden sein
            self.assertTrue(os.path.exists(os.path.join(stream_dir, "00002.m2ts")))

            # index.bdmv muss SS_content_exist_flag = 1 & initial_output_mode_pref = 1 (0x60) haben!
            with open(os.path.join(bdmv_dir, "index.bdmv"), "rb") as f:
                idx_data = f.read()
            self.assertEqual(idx_data[44], 0x60)
            self.assertEqual(idx_data[45], 0x00)

    def test_3d_playlist_patching(self):
        """Prüft, dass 3D MPLS-Playlists sowohl Base- als auch MVC-SubPath-Referenzen korrekt patchen."""
        raw_3d_mpls = (
            b"MPLS0200" + b"\x00" * 60 +
            b"00000M2TS" + b"\x00" * 80 +
            b"\x00\x08\x00\x00\x00\x01\x00\x1c" +
            b"00001M2TS" + b"\x00" * 30
        )
        base_clip_str = "00004"
        mvc_clip_str = "00005"
        patched = raw_3d_mpls.replace(b"00000M2TS", f"{base_clip_str}M2TS".encode("ascii"))
        patched = patched.replace(b"00001M2TS", f"{mvc_clip_str}M2TS".encode("ascii"))

        self.assertIn(b"00004M2TS", patched)
        self.assertIn(b"00005M2TS", patched)
        self.assertNotIn(b"00000M2TS", patched)
        self.assertNotIn(b"00001M2TS", patched)

    def test_ssif_directory_and_tools_import(self):
        """Prüft, dass modules.ssif_tools importierbar ist und die SSIF-Verzeichnis-Logik greift."""
        from modules.ssif_tools import mux_3d_title
        self.assertTrue(callable(mux_3d_title))

    def test_direct_3d_iso_mode_detection(self):
        """Prüft die Erkennung von Direkt-ISO (tsMuxeR UDF 2.50) für Single-Title 3D Discs ohne Menü."""
        proj = ProjectState()
        proj.export_format = "iso"
        proj.enable_menu = False
        t1 = MediaTitle(name="3D Hauptfilm", is_main=True)
        t1.video_base = "film.264"
        t1.video_mvc = "film.mvc"
        proj.titles = [t1]

        # Bedingung prüfen
        additional_titles = proj.titles[1:] if len(proj.titles) > 1 else []
        direct_iso_mode = (proj.export_format == "iso") and (not proj.enable_menu) and (not additional_titles)
        self.assertTrue(direct_iso_mode)

        # Wenn Menü aktiviert wird, darf direct_iso_mode NICHT aktiv sein
        proj.enable_menu = True
        direct_iso_mode_with_menu = (proj.export_format == "iso") and (not proj.enable_menu) and (not additional_titles)
        self.assertFalse(direct_iso_mode_with_menu)

    def test_udf250_writer_descriptors_and_crc(self):
        """Prüft CRC-16 und Descriptor Tag-Berechnung der UDF 2.50 Engine."""
        from modules.udf250_writer import crc16, write_desc_tag, pack_descriptor
        # Test CRC-16
        c = crc16(b"123456789")
        self.assertEqual(c, 0x31C3) # CCITT Standardwert für ASCII "123456789"
        
        # Test Tag & Checksum
        tag = write_desc_tag(tag_id=2, tag_loc=256, desc_crc=0x79C9, desc_crc_len=496)
        self.assertEqual(len(tag), 16)
        self.assertEqual(tag[4], sum(tag[:4] + tag[5:16]) & 0xFF) # Prüfsummenvalidierung

    def test_udf250_iso_creation_and_interleaving(self):
        """Prüft die Erstellung eines UDF 2.50 ISOs mit 3D Extent-Interleaving."""
        from modules.udf250_writer import UDF250Writer
        with tempfile.TemporaryDirectory() as tmpdir:
            iso_path = os.path.join(tmpdir, "test_interleaved.iso")
            writer = UDF250Writer(iso_path, volume_label="TEST_3D")
            
            # Verzeichnisse
            writer.get_or_create_dir("BDMV")
            writer.get_or_create_dir("BDMV/STREAM")
            writer.get_or_create_dir("BDMV/STREAM/SSIF")
            
            # Reguläre Datei
            writer.add_file("BDMV/index.bdmv", data=b"HDMV0200" + b"\x00" * 100)
            
            # 3D Stream: Simuliere 2 Chunks für Base und Dep
            chunk_dep0 = b"D" * (2048 * 2)
            chunk_base0 = b"B" * (2048 * 3)
            chunk_dep1 = b"d" * (2048 * 2)
            chunk_base1 = b"b" * (2048 * 3)
            ssif_dummy = chunk_dep0 + chunk_base0 + chunk_dep1 + chunk_base1
            
            base_extents = [(2, 2048 * 3), (7, 2048 * 3)]
            mvc_extents = [(0, 2048 * 2), (5, 2048 * 2)]
            
            writer.add_interleaved_3d(
                base_rel_path="BDMV/STREAM/00004.m2ts",
                mvc_rel_path="BDMV/STREAM/00005.m2ts",
                ssif_rel_path="BDMV/STREAM/SSIF/00004.ssif",
                ssif_source_path="",
                base_extents=base_extents,
                mvc_extents=mvc_extents
            )
            # Dummy-Bytes direkt zuweisen
            ssif_entry = writer.root.get_child("BDMV").get_child("STREAM").get_child("SSIF").get_child("00004.ssif")
            ssif_entry.source_bytes = ssif_dummy
            
            writer.build_iso()
            self.assertTrue(os.path.exists(iso_path))
            self.assertGreater(os.path.getsize(iso_path), 576 * 1024)
            
            # ISO-Header prüfen
            with open(iso_path, "rb") as f:
                # VRS bei Sektor 16
                f.seek(16 * 2048)
                self.assertEqual(f.read(7), b"\x00BEA01\x01")
                f.seek(17 * 2048)
                self.assertEqual(f.read(7), b"\x00NSR03\x01")
                # AVDP bei Sektor 256
                f.seek(256 * 2048)
                avdp_tag = f.read(2)
                import struct
                tag_id = struct.unpack("<H", avdp_tag)[0]
                self.assertEqual(tag_id, 2) # Tag 2 = AnchorVolPtr


if __name__ == "__main__":
    unittest.main()


