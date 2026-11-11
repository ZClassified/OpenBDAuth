# tests/test_bdmv_navigation.py
import unittest
import struct
import os
import tempfile
from modules.bdmv.movie_object_generator import (
    cmd_play_playlist, cmd_jump_title, cmd_jump_object,
    build_standard_movie_objects, write_movie_object_file
)
from modules.bdmv.index_generator import (
    build_index_bdmv, write_index_bdmv_file
)

class TestBDMVNavigation(unittest.TestCase):
    def test_hdmv_commands(self):
        play_cmd = cmd_play_playlist(1)
        self.assertEqual(len(play_cmd), 12)
        # dst ist playlist_id an Byte 4..7
        pl_id = struct.unpack(">I", play_cmd[4:8])[0]
        self.assertEqual(pl_id, 1)

        jump_cmd = cmd_jump_title(0)
        self.assertEqual(len(jump_cmd), 12)
        title_id = struct.unpack(">I", jump_cmd[4:8])[0]
        self.assertEqual(title_id, 0)

    def test_movie_object_bdmv(self):
        mobj_bytes = build_standard_movie_objects(num_titles=2)
        self.assertEqual(mobj_bytes[:8], b"MOBJ0200")

        # Prüfe num_objects an Offset 48 (40B Header + 4B data_len + 4B reserved)
        num_objs = struct.unpack(">H", mobj_bytes[48:50])[0]
        # 1 FirstPlayback + 1 TopMenu + 2 Titel-Objekte = 4 Objekte
        self.assertEqual(num_objs, 4)

        # Dateitest
        with tempfile.TemporaryDirectory() as tmp:
            out_file = os.path.join(tmp, "MovieObject.bdmv")
            write_movie_object_file(out_file, num_titles=2)
            self.assertTrue(os.path.exists(out_file))
            self.assertEqual(os.path.getsize(out_file), len(mobj_bytes))
            # Erstes Objekt beginnt bei Offset 50 (Header 40 + len 4 + res 4 + num_objs 2)
            # Prüfe, dass Objekt-Flags 0x8000 (resume_intention = 1 nach tsMuxeR / BD-ROM) gesetzt sind
            obj0_flags = struct.unpack(">H", mobj_bytes[50:52])[0]
            self.assertEqual(obj0_flags, 0x8000)

    def test_3d_movie_objects(self):
        mobj_bytes = build_standard_movie_objects(num_titles=1, titles_3d=[1])
        # MovieObject #2 (Titel 1) muss SetOutputMode(1) enthalten
        # 0..39: Header, 40..43: data_len, 44..47: res, 48..49: num_objs=3
        pos = 50
        # Obj 0: flags(2) + num_cmds(2) + cmds
        for obj_idx in range(3):
            flags = struct.unpack(">H", mobj_bytes[pos:pos+2])[0]
            n_cmds = struct.unpack(">H", mobj_bytes[pos+2:pos+4])[0]
            pos += 4
            cmd_data = mobj_bytes[pos:pos+n_cmds*12]
            pos += n_cmds*12
            if obj_idx == 2: # Titel 1
                # 10 Befehle: [3D-Profilprüfung] SetOutputMode(1), PlayPL(1), [3D-Profilprüfung] SetOutputMode(0), JumpObject(1)
                self.assertEqual(n_cmds, 10)
                cmd0 = cmd_data[36:48]
                cmd1 = cmd_data[48:60]
                cmd2 = cmd_data[96:108]
                cmd3 = cmd_data[108:120]
                # Profilprüfung: EQ GPR6 == 0x130240 direkt vor SetOutputMode
                self.assertEqual(cmd_data[24:36], bytes.fromhex("48 40 02 00 00 00 00 06 00 13 02 40"))
                # Cmd 0: SetOutputMode 1 (0x31 0x80 0x00 0x0A, dst=1)
                self.assertEqual(cmd0[:4], bytes([0x31, 0x80, 0x00, 0x0A]))
                self.assertEqual(struct.unpack(">II", cmd0[4:12]), (1, 0))
                # Cmd 1: PlayPL 1 (0x22 0x80 0x00 0x00, dst=1)
                self.assertEqual(cmd1[:4], bytes([0x22, 0x80, 0x00, 0x00]))
                self.assertEqual(struct.unpack(">II", cmd1[4:12]), (1, 0))
                # Cmd 2: SetOutputMode 0 (0x31 0x80 0x00 0x0A, dst=0)
                self.assertEqual(cmd2[:4], bytes([0x31, 0x80, 0x00, 0x0A]))
                self.assertEqual(struct.unpack(">II", cmd2[4:12]), (0, 0))
                # Cmd 3: JumpObject 1
                self.assertEqual(cmd3[:4], bytes([0x21, 0x80, 0x00, 0x00]))
                self.assertEqual(struct.unpack(">II", cmd3[4:12]), (1, 0))

    def test_index_bdmv(self):
        indx_bytes = build_index_bdmv(num_titles=2)
        self.assertEqual(indx_bytes[:8], b"INDX0200")

        # Offsets im 40-Byte Header nach BD-ROM Spezifikation
        indexes_start, ext_start = struct.unpack(">II", indx_bytes[8:16])
        self.assertEqual(indexes_start, 78) # AppInfo (40..74) + 4B padding -> 78
        self.assertEqual(ext_start, 0)

        # AppInfo an Offset 44..78 muss 34 Nullbytes sein (tsMuxeR Standard)
        app_info_len = struct.unpack(">I", indx_bytes[40:44])[0]
        self.assertEqual(app_info_len, 34)
        self.assertEqual(indx_bytes[44:78], b"\x00" * 34)

        # Dateitest
        with tempfile.TemporaryDirectory() as tmp:
            out_file = os.path.join(tmp, "index.bdmv")
            write_index_bdmv_file(out_file, num_titles=2)
            self.assertTrue(os.path.exists(out_file))
            self.assertEqual(os.path.getsize(out_file), len(indx_bytes))

    def test_fps_to_bd_video_attr(self):
        from modules.mpls.mpls_generator import fps_to_bd_video_attr
        # 25 fps muss immer 1080i (0x43) sein (1080p25 existiert nicht auf BD-ROM)
        self.assertEqual(fps_to_bd_video_attr(25.0), 0x43)
        self.assertEqual(fps_to_bd_video_attr(50.0), 0x43)
        # 29.97 fps muss 1080i (0x44) sein
        self.assertEqual(fps_to_bd_video_attr(29.97), 0x44)
        # 23.976 / 24.0 fps ist 1080p (0x61 / 0x62)
        self.assertEqual(fps_to_bd_video_attr(23.976), 0x61)
        self.assertEqual(fps_to_bd_video_attr(24.0), 0x62)

    def test_subpath_type_and_appinfo_length(self):
        from modules.mpls.mpls_generator import build_menu_mpls, build_movie_mpls
        menu_bytes = build_menu_mpls("00001", "00002", duration_sec=10.0, fps=25.0)
        movie_bytes = build_movie_mpls("00001", duration_sec=10.0, fps=25.0)

        # 1. AppInfoPlayList muss exakt 14 Bytes lang sein
        menu_ai_len = struct.unpack(">I", menu_bytes[40:44])[0]
        movie_ai_len = struct.unpack(">I", movie_bytes[40:44])[0]
        self.assertEqual(menu_ai_len, 14, "Menu AppInfoPlayList muss 14 Bytes lang sein")
        self.assertEqual(movie_ai_len, 14, "Movie AppInfoPlayList muss 14 Bytes lang sein")

        # 2. SubPath_type muss 3 sein (Interactive Graphics Presentation / Menus nach BD-ROM Part 3)
        pl_offset, = struct.unpack(">I", menu_bytes[8:12])
        pi_len, = struct.unpack(">H", menu_bytes[pl_offset+10:pl_offset+12])
        sp_start = pl_offset + 12 + pi_len
        sp_data = menu_bytes[sp_start+4:]
        subpath_type = sp_data[1]
        self.assertEqual(subpath_type, 3, "SubPath_type muss 3 sein (Interactive Graphics Menu)")

if __name__ == '__main__':
    unittest.main()
