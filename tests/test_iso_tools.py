import unittest
import os
import tempfile
from modules.iso_tools import sanitize_volume_label, create_udf_iso

class TestIsoTools(unittest.TestCase):
    def test_sanitize_volume_label(self):
        self.assertEqual(sanitize_volume_label("My Movie (2026)!"), "My_Movie_2026")
        self.assertEqual(sanitize_volume_label(""), "BD_DISC")
        self.assertEqual(sanitize_volume_label("A" * 50), "A" * 30)

    def test_create_udf_iso_mock(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            bdmv = os.path.join(tmp_dir, "BDMV")
            os.makedirs(bdmv, exist_ok=True)
            with open(os.path.join(bdmv, "index.bdmv"), "wb") as f:
                f.write(b"MOCK_BDMV_DATA")
            
            iso_dest = os.path.join(tmp_dir, "test_disc.iso")
            logs = []
            success = create_udf_iso(
                source_dir=tmp_dir,
                iso_path=iso_dest,
                volume_label="TEST_DISC",
                log_callback=logs.append
            )
            self.assertTrue(success, f"ISO creation failed: {logs}")
            self.assertTrue(os.path.exists(iso_dest))
            self.assertGreater(os.path.getsize(iso_dest), 1000000)


class TestUdfLargeFiles(unittest.TestCase):
    """Dateien über 1 GiB müssen auf mehrere Extents verteilt werden (30-Bit-Längenfeld)."""

    def test_split_extent(self):
        from modules.udf250_writer import split_extent, MAX_EXTENT_LEN, SECTOR_SIZE
        self.assertEqual(split_extent(10, 0), [(10, 0)])
        self.assertEqual(split_extent(10, MAX_EXTENT_LEN), [(10, MAX_EXTENT_LEN)])
        for size in (MAX_EXTENT_LEN + 1, 6_279_591_936):
            extents = split_extent(100, size)
            self.assertEqual(sum(s for _, s in extents), size)
            self.assertTrue(all(s <= MAX_EXTENT_LEN for _, s in extents))
            for (lbn, s), (next_lbn, _) in zip(extents, extents[1:]):
                self.assertEqual(s % SECTOR_SIZE, 0)
                self.assertEqual(next_lbn, lbn + s // SECTOR_SIZE)
        self.assertEqual(len(split_extent(0, 6_279_591_936)), 6)
        self.assertLess(MAX_EXTENT_LEN, 1 << 30)

    def test_file_entry_lists_all_extents(self):
        """Mit kleiner Extent-Grenze: Der File Entry beschreibt alle Teile, und sie ergeben die Datei."""
        import struct
        from unittest import mock
        import modules.udf250_writer as udf
        payload = bytes(range(256)) * 80   # 20480 Bytes = 10 Sektoren
        with tempfile.TemporaryDirectory() as tmp_dir, mock.patch.object(udf, "MAX_EXTENT_LEN", 4 * udf.SECTOR_SIZE):
            iso_path = os.path.join(tmp_dir, "split.iso")
            writer = udf.UDF250Writer(iso_path, volume_label="SPLIT")
            entry = writer.add_file("BDMV/STREAM/00000.m2ts", data=payload, is_realtime=True)
            writer.build_iso(progress_callback=lambda m: None)
            self.assertEqual([s for _, s in entry.extents], [8192, 8192, 4096])
            with open(iso_path, "rb") as f:
                f.seek((udf.METADATA_START_ADDR + entry.sector_num) * udf.SECTOR_SIZE)
                efe = f.read(udf.SECTOR_SIZE)
                self.assertEqual(struct.unpack("<H", efe[0:2])[0], 266)
                self.assertEqual(struct.unpack("<Q", efe[56:64])[0], len(payload))
                ad_len = struct.unpack("<I", efe[212:216])[0]
                self.assertEqual(ad_len, 3 * 16)
                data = b""
                for i in range(3):
                    length, pos = struct.unpack("<II", efe[216 + 16 * i:224 + 16 * i])
                    self.assertEqual(length >> 30, 0)   # Extent-Typ: belegt und beschrieben
                    f.seek((udf.PARTITION_START_ADDR + pos) * udf.SECTOR_SIZE)
                    data += f.read(length)
            self.assertEqual(data, payload)

    def test_parent_fid_crc_covers_padding(self):
        """Der Eintrag für den Elternordner ist 40 Bytes lang; die CRC deckt 24 Bytes ab wie bei tsMuxeR."""
        import struct
        import modules.udf250_writer as udf
        with tempfile.TemporaryDirectory() as tmp_dir:
            iso_path = os.path.join(tmp_dir, "fid.iso")
            writer = udf.UDF250Writer(iso_path, volume_label="FID")
            writer.add_file("BDMV/index.bdmv", data=b"INDX0200" + bytes(112))
            writer.build_iso(progress_callback=lambda m: None)
            bdmv = writer.root.get_child("BDMV")
            with open(iso_path, "rb") as f:
                for entry in (writer.root, bdmv):
                    f.seek((udf.METADATA_START_ADDR + entry.sector_num + 1) * udf.SECTOR_SIZE)
                    fids = f.read(udf.SECTOR_SIZE)
                    tag_id, _, _, _, _, crc, crc_len, _ = struct.unpack_from("<HHBBHHHI", fids, 0)
                    self.assertEqual(tag_id, 257)
                    self.assertEqual(fids[18] & 0x08, 0x08)   # Elternordner
                    self.assertEqual(crc_len, 24)
                    self.assertEqual(crc, udf.crc16(fids[16:40]))
                    # Der nächste Eintrag beginnt direkt dahinter
                    self.assertEqual(struct.unpack_from("<H", fids, 40)[0], 257)

    def test_metadata_grows_for_many_files(self):
        """Viele Menü-Clips: Alle File Entries müssen innerhalb der Metadatendatei liegen (sonst 0-Byte-Dateien)."""
        import struct
        import modules.udf250_writer as udf
        with tempfile.TemporaryDirectory() as tmp_dir:
            iso_path = os.path.join(tmp_dir, "many.iso")
            writer = udf.UDF250Writer(iso_path, volume_label="MANY")
            entries = [writer.add_file(f"BDMV/{folder}/{i:05d}.m2ts", data=bytes(6144), is_realtime=True)
                       for folder in ("STREAM", "CLIPINF", "PLAYLIST", "BACKUP")
                       for i in range(30)]
            writer.build_iso(progress_callback=lambda m: None)
            self.assertGreater(writer.metadata_len, 0x30000)
            self.assertEqual(writer.metadata_len % udf.ALLOC_BLOCK_SIZE, 0)
            with open(iso_path, "rb") as f:
                f.seek(udf.PARTITION_START_ADDR * udf.SECTOR_SIZE)
                meta_fe = f.read(udf.SECTOR_SIZE)
                self.assertEqual(struct.unpack("<Q", meta_fe[56:64])[0], writer.metadata_len)
                last = entries[-1]
                self.assertLess(last.sector_num, writer.metadata_len // udf.SECTOR_SIZE)
                f.seek((udf.METADATA_START_ADDR + last.sector_num) * udf.SECTOR_SIZE)
                efe = f.read(udf.SECTOR_SIZE)
                self.assertEqual(struct.unpack("<H", efe[0:2])[0], 266)
                self.assertEqual(struct.unpack("<Q", efe[56:64])[0], 6144)

    def test_small_disc_keeps_metadata_size(self):
        import modules.udf250_writer as udf
        with tempfile.TemporaryDirectory() as tmp_dir:
            writer = udf.UDF250Writer(os.path.join(tmp_dir, "small.iso"))
            writer.add_file("BDMV/index.bdmv", data=b"INDX0200" + bytes(112))
            writer.build_iso(progress_callback=lambda m: None)
            self.assertEqual(writer.metadata_len, 0x30000)

    def test_oversized_extent_is_rejected(self):
        from modules.udf250_writer import UDF250Writer, MAX_EXTENT_LEN
        with tempfile.TemporaryDirectory() as tmp_dir:
            writer = UDF250Writer(os.path.join(tmp_dir, "x.iso"))
            with open(os.path.join(tmp_dir, "efe.bin"), "wb") as fout:
                with self.assertRaises(ValueError):
                    writer._write_extended_file_entry(fout, False, 1, 249, MAX_EXTENT_LEN + 2048, 0, 1,
                                                      [(0, MAX_EXTENT_LEN + 2048)])


class TestDirectoryLimit(unittest.TestCase):
    """Konzept 11.2.6: Ein Ordner passt in einen Sektor – höchstens 38 Clips. Darüber bricht die ISO ab, bevor etwas
    geschrieben wird; es gibt keinen Ausweg mehr über Windows IMAPI2FS (bis v1.18.1)."""

    def _tree(self, tmp_dir, clips):
        stream = os.path.join(tmp_dir, "BDMV", "STREAM")
        os.makedirs(stream)
        for i in range(clips):
            with open(os.path.join(stream, f"{i:05d}.m2ts"), "wb") as f:
                f.write(bytes(192))

    def test_limit_matches_the_directory_layout(self):
        from modules.udf250_writer import MAX_DIR_ENTRIES, PARENT_FID_LEN, SECTOR_SIZE, fid_len
        self.assertEqual(MAX_DIR_ENTRIES, 38)
        self.assertEqual(fid_len("00001.m2ts"), 52)
        self.assertLessEqual(PARENT_FID_LEN + 38 * fid_len("00001.m2ts"), SECTOR_SIZE)
        self.assertGreater(PARENT_FID_LEN + 39 * fid_len("00001.m2ts"), SECTOR_SIZE)

    def test_38_clips_fit(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            self._tree(tmp_dir, 38)
            iso = os.path.join(tmp_dir, "ok.iso")
            self.assertTrue(create_udf_iso(tmp_dir, iso, log_callback=lambda m: None))
            self.assertTrue(os.path.exists(iso))

    def test_39_clips_stop_with_a_clear_message(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            self._tree(tmp_dir, 39)
            iso = os.path.join(tmp_dir, "too_many.iso")
            logs = []
            self.assertFalse(create_udf_iso(tmp_dir, iso, log_callback=logs.append))
            self.assertFalse(os.path.exists(iso))                         # keine halbfertige ISO
            self.assertTrue(any("BDMV/STREAM hat 39 Einträge" in m and "höchstens 38" in m for m in logs), logs)
            self.assertFalse(any("Fallback" in m for m in logs))
            self.assertTrue(os.path.isdir(os.path.join(tmp_dir, "BDMV", "STREAM")))   # Ordner bleibt


class TestPreflightIsoLimit(unittest.TestCase):
    def _project(self, menus_with_background: int):
        from core.disc_edit import add_menu, add_nav_button
        from tests.project_factory import make_project
        project = make_project(extra_films=2)                   # 3 Filme
        project.settings.export_format = "iso"
        main = project.main_menu
        main.background.image = "C:/haupt.png"
        for i in range(menus_with_background):
            menu = add_menu(project, f"Menü {i}", (0.0, 100.0 * i))
            menu.background.image = f"C:/bild{i}.png"
            menu.buttons[0].target = main.id
            add_nav_button(project, main.id, f"M{i}", menu.id)
        return project

    def _iso_errors(self, project):
        from core.preflight import run_preflight, ERROR
        return [i for i in run_preflight(project, check_files=False)
                if i.level == ERROR and "Die ISO fasst" in i.message]

    def test_limit_in_preflight(self):
        from core.preflight import stream_clip_count
        fits = self._project(16)                                # 3 + 2 × 17 = 37
        self.assertEqual(stream_clip_count(fits), 37)
        self.assertEqual(self._iso_errors(fits), [])
        too_many = self._project(17)                            # 3 + 2 × 18 = 39
        self.assertEqual(len(self._iso_errors(too_many)), 1)
        too_many.settings.export_format = "folder"              # als Ordner gibt es die Grenze nicht
        self.assertEqual(self._iso_errors(too_many), [])

    def test_menus_like_main_menu_share_clips(self):
        from core.preflight import stream_clip_count
        project = self._project(17)
        for menu in project.menus[1:]:
            menu.background.image = None
        self.assertEqual(stream_clip_count(project), 5)
