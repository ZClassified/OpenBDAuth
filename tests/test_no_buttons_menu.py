# tests/test_no_buttons_menu.py
"""
Unit-Test für den Diagnose-Modus: Menü ohne Buttons (Hintergrund als Intro abspielen).
Verifiziert, dass:
1. Kein IGS-SubClip (00002.m2ts / 00002.clpi) erzeugt wird.
2. 00000.mpls keine SubPaths besitzt (num_sub_paths = 0).
3. MovieObject 0 die Befehle PlayPL(0) und danach PlayPL(1) ausführt.
"""

import os
import struct
import tempfile
import unittest
from core.project_state import ProjectState, MediaTitle
from modules.menu_author import inject_menu_into_bdmv


class TestNoButtonsMenu(unittest.TestCase):
    def test_no_buttons_menu_authoring(self):
        with tempfile.TemporaryDirectory() as tmp:
            bdmv = os.path.join(tmp, "BDMV")
            os.makedirs(os.path.join(bdmv, "PLAYLIST"), exist_ok=True)
            os.makedirs(os.path.join(bdmv, "STREAM"), exist_ok=True)
            os.makedirs(os.path.join(bdmv, "CLIPINF"), exist_ok=True)

            # Dummy Hauptfilm-Playlist anlegen (00000.mpls vor dem Rename)
            orig_pl = os.path.join(bdmv, "PLAYLIST", "00000.mpls")
            with open(orig_pl, "wb") as f:
                f.write(b"DUMMY_ORIG_PL")

            project = ProjectState()
            project.enable_menu = True
            project.menu_no_buttons_test = True
            project.menu_duration = 5.0

            t1 = MediaTitle(name="Hauptfilm", is_main=True)
            t1.video_base = "C:/media/film.264"
            project.titles = [t1]

            success = inject_menu_into_bdmv(
                bdmv_dir=bdmv,
                duration_sec=5.0,
                num_titles=1,
                project=project
            )
            self.assertTrue(success)

            # 1. Prüfen, dass 00002.m2ts (IGS) NICHT existiert
            igs_m2ts = os.path.join(bdmv, "STREAM", "00002.m2ts")
            igs_clpi = os.path.join(bdmv, "CLIPINF", "00002.clpi")
            self.assertFalse(os.path.exists(igs_m2ts))
            self.assertFalse(os.path.exists(igs_clpi))

            # 2. Prüfen, dass 00000.mpls und 00001.mpls existieren
            pl_0 = os.path.join(bdmv, "PLAYLIST", "00000.mpls")
            pl_1 = os.path.join(bdmv, "PLAYLIST", "00001.mpls")
            self.assertTrue(os.path.exists(pl_0))
            self.assertTrue(os.path.exists(pl_1))

            # 3. Prüfen, dass 00000.mpls num_sub_paths == 0 hat
            with open(pl_0, "rb") as f:
                pl_data = f.read()
            pl_offset, = struct.unpack(">I", pl_data[8:12])
            app_info_len, = struct.unpack(">I", pl_data[pl_offset:pl_offset+4])
            playlist_block_pos = pl_offset + 4 + app_info_len
            # Header des Playlist-Blocks: length (4B) + reserved (2B) + num_play_items (2B) + num_sub_paths (2B)
            num_pi, num_sp = struct.unpack(">HH", pl_data[playlist_block_pos+6:playlist_block_pos+10])
            self.assertEqual(num_pi, 1)
            self.assertEqual(num_sp, 0, "00000.mpls darf im Diagnosemodus keinen SubPath besitzen!")

            # 4. Prüfen, dass MovieObject.bdmv existiert und PlayPL(0) gefolgt von PlayPL(1) enthält
            mobj_path = os.path.join(bdmv, "MovieObject.bdmv")
            self.assertTrue(os.path.exists(mobj_path))
            with open(mobj_path, "rb") as f:
                mobj_data = f.read()

            # Offset 40: data_len(4B), reserved(4B), num_objects(2B) -> 3 Objekte
            num_objects, = struct.unpack(">H", mobj_data[48:50])
            self.assertEqual(num_objects, 3)

            # MovieObject 0: FirstPlayback -> PlayPL(0) direkt (ohne illegales JumpTitle(0))
            obj0_flags, obj0_num_cmds = struct.unpack(">HH", mobj_data[50:54])
            self.assertEqual(obj0_flags, 0x8000)
            self.assertEqual(obj0_num_cmds, 2)
            cmd_fp = mobj_data[54:66]
            self.assertEqual(cmd_fp[:2], bytes([0x22, 0x80])) # PlayPL(0)

            # MovieObject 1: TopMenu -> PlayPL(0), JumpObject(1)
            obj1_flags, obj1_num_cmds = struct.unpack(">HH", mobj_data[78:82])
            self.assertEqual(obj1_flags, 0x8000)
            self.assertEqual(obj1_num_cmds, 2)
            cmd1_0 = mobj_data[82:94]
            cmd1_1 = mobj_data[94:106]
            dst0, = struct.unpack(">I", cmd1_0[4:8])
            dst1, = struct.unpack(">I", cmd1_1[4:8])
            self.assertEqual(dst0, 0)
            self.assertEqual(dst1, 1)


if __name__ == "__main__":
    unittest.main()
