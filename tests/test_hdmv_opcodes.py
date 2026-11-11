# tests/test_hdmv_opcodes.py
import unittest
import struct
from modules.bdmv.movie_object_generator import (
    cmd_play_playlist,
    cmd_play_playlist_at_mark,
    cmd_jump_title,
    cmd_jump_object,
    cmd_set_stream,
    cmd_set_button_page,
    cmd_set_output_mode
)
from modules.igs.segments import (
    build_play_playlist_cmd,
    build_play_playlist_at_mark_cmd,
    build_jump_title_cmd,
    build_set_stream_cmd,
    build_set_button_page_cmd
)

class TestHDMVOpcodes(unittest.TestCase):
    def test_play_playlist(self):
        cmd = cmd_play_playlist(1)
        self.assertEqual(len(cmd), 12)
        # Byte 0: 0x22 (op_cnt=1, grp=0, sub_grp=2)
        # Byte 1: 0x80 (imm=1, PlayPL=0)
        self.assertEqual(cmd[:4], bytes([0x22, 0x80, 0x00, 0x00]))
        dst, src = struct.unpack(">II", cmd[4:])
        self.assertEqual(dst, 1)
        self.assertEqual(src, 0)
        # Verifiziere IGS Builder Alias
        self.assertEqual(build_play_playlist_cmd(1), cmd)

    def test_play_playlist_at_mark(self):
        cmd = cmd_play_playlist_at_mark(playlist_id=2, mark_id=5)
        self.assertEqual(len(cmd), 12)
        # Byte 0: 0x42 (op_cnt=2: sonst liest der Player die Marke nicht)
        # Byte 1: 0xC2 (imm_op1=1, imm_op2=1, PlayPLatPM=2)
        self.assertEqual(cmd[:4], bytes([0x42, 0xC2, 0x00, 0x00]))
        dst, src = struct.unpack(">II", cmd[4:])
        self.assertEqual(dst, 2)
        self.assertEqual(src, 5)
        # Verifiziere IGS Builder Alias
        self.assertEqual(build_play_playlist_at_mark_cmd(2, 5), cmd)

    def test_jump_title(self):
        cmd = cmd_jump_title(3)
        self.assertEqual(len(cmd), 12)
        # Byte 0: 0x21 (op_cnt=1, grp=0, sub_grp=1)
        # Byte 1: 0x81 (imm=1, JumpTitle=1)
        self.assertEqual(cmd[:4], bytes([0x21, 0x81, 0x00, 0x00]))
        dst, src = struct.unpack(">II", cmd[4:])
        self.assertEqual(dst, 3)
        self.assertEqual(src, 0)
        self.assertEqual(build_jump_title_cmd(3), cmd)

    def test_jump_object(self):
        cmd = cmd_jump_object(0)
        self.assertEqual(len(cmd), 12)
        self.assertEqual(cmd[:4], bytes([0x21, 0x80, 0x00, 0x00]))
        dst, src = struct.unpack(">II", cmd[4:])
        self.assertEqual(dst, 0)
        self.assertEqual(src, 0)

    def test_set_stream_audio_only(self):
        cmd = cmd_set_stream(audio_id=2)
        self.assertEqual(len(cmd), 12)
        # Byte 0: 0x51 (op_cnt=2, grp=2 Set, sub_grp=1 SetSystem) – mit op_cnt=1 ignorierte der Sony den Befehl
        # Byte 1: 0xC0 (imm_op1, imm_op2; Operand 2 = 0)
        # Byte 3: 0x01 (INSN_SET_STREAM)
        self.assertEqual(cmd[:4], bytes([0x51, 0xC0, 0x00, 0x01]))
        dst, src = struct.unpack(">II", cmd[4:])
        # Audio stream 2 -> 0x80020000
        self.assertEqual(dst, 0x80020000)
        self.assertEqual(src, 0)
        self.assertEqual(build_set_stream_cmd(audio_id=2), cmd)

    def test_set_stream_subtitle_on(self):
        cmd = cmd_set_stream(subtitle_id=1, subtitle_on=True)
        self.assertEqual(len(cmd), 12)
        dst, src = struct.unpack(">II", cmd[4:])
        # Subtitle valid (bit 15 = 0x8000), Subtitle on (bit 14 = 0x4000), Subtitle id 1
        self.assertEqual(dst, 0x0000C001)
        self.assertEqual(src, 0)
        self.assertEqual(build_set_stream_cmd(subtitle_id=1, subtitle_on=True), cmd)

    def test_set_stream_subtitle_off(self):
        cmd = cmd_set_stream(subtitle_on=False)
        self.assertEqual(len(cmd), 12)
        dst, src = struct.unpack(">II", cmd[4:])
        # Subtitle valid (bit 15 = 0x8000), Subtitle off (bit 14 = 0), Subtitle id 0
        self.assertEqual(dst, 0x00008000)
        self.assertEqual(src, 0)
        self.assertEqual(build_set_stream_cmd(subtitle_on=False), cmd)

    def test_set_stream_audio_and_subtitle(self):
        cmd = cmd_set_stream(audio_id=1, subtitle_id=2, subtitle_on=True)
        self.assertEqual(len(cmd), 12)
        dst, src = struct.unpack(">II", cmd[4:])
        self.assertEqual(dst, 0x8001C002)

    def test_set_button_page(self):
        cmd = cmd_set_button_page(page_id=3)
        self.assertEqual(len(cmd), 12)
        # Byte 0: 0x51 (op_cnt=2, grp=2 Set, sub_grp=1 SetSystem)
        # Byte 1: 0xC0 (imm_op1=1, imm_op2=1), Byte 3: 0x03 (INSN_SET_BUTTON_PAGE)
        self.assertEqual(cmd[:4], bytes([0x51, 0xC0, 0x00, 0x03]))
        dst, src = struct.unpack(">II", cmd[4:])
        # dst: kein button_flag -> Standard-Button der Zielseite
        self.assertEqual(dst, 0)
        # src: page_flag (Bit 31) + Page ID
        self.assertEqual(src, 0x80000003)
        self.assertEqual(build_set_button_page_cmd(page_id=3), cmd)

    def test_set_system_commands_are_not_register_arithmetic(self):
        # Regression v1.7.6: SetButtonPage/SetStream lagen in Sub-Group 0 (Move/Add auf
        # Register) und wurden vom Player ohne Wirkung ausgeführt.
        for cmd in (cmd_set_button_page(1), build_set_button_page_cmd(1),
                    cmd_set_stream(audio_id=1), build_set_stream_cmd(audio_id=1),
                    cmd_set_output_mode(1)):
            op_cnt, grp, sub_grp = cmd[0] >> 5, (cmd[0] >> 3) & 0x03, cmd[0] & 0x07
            self.assertEqual(grp, 2)
            self.assertEqual(sub_grp, 1)
            self.assertGreaterEqual(op_cnt, 1)
        # SetButtonPage liest die Page aus dem zweiten Operanden: op_cnt=2 und imm_op2 nötig
        cmd = cmd_set_button_page(1)
        self.assertEqual(cmd[0] >> 5, 2)
        self.assertTrue(cmd[1] & 0x40)

    def test_register_commands(self):
        from modules.bdmv.movie_object_generator import (
            cmd_move_gpr, cmd_copy_gpr, cmd_compare_gpr, cmd_goto, cmd_play_playlist_at_mark_register,
            cmd_set_audio_from_register, cmd_show_subtitle_from_register, CMP_NE,
        )
        # Move GPR0 = 5: op_cnt=2, grp=2 Set, sub_grp=0; imm_op2; set_opt=1
        self.assertEqual(cmd_move_gpr(0, 5), bytes([0x50, 0x40, 0x00, 0x01]) + struct.pack(">II", 0, 5))
        self.assertEqual(cmd_copy_gpr(4, 0)[:4], bytes([0x50, 0x00, 0x00, 0x01]))
        # NE GPR1, 0: op_cnt=2, grp=1 Compare; imm_op2; cmp_opt=3
        self.assertEqual(cmd_compare_gpr(CMP_NE, 1, 0), bytes([0x48, 0x40, 0x03, 0x00]) + struct.pack(">II", 1, 0))
        # Goto 7: op_cnt=1, Branch/Goto, imm_op1, branch_opt=1
        self.assertEqual(cmd_goto(7), bytes([0x20, 0x81, 0x00, 0x00]) + struct.pack(">II", 7, 0))
        # PlayPLatPM(1, GPR4): Marke aus Register (imm_op2 = 0)
        self.assertEqual(cmd_play_playlist_at_mark_register(1, 4), bytes([0x42, 0x82, 0x00, 0x00]) + struct.pack(">II", 1, 4))
        # SetStream mit Register-Operand: Flags im Befehl, Registernummer an der Stelle der Spurnummer
        self.assertEqual(cmd_set_audio_from_register(1), bytes([0x51, 0x40, 0x00, 0x01]) + struct.pack(">II", 0x80010000, 0))
        self.assertEqual(cmd_show_subtitle_from_register(2), bytes([0x51, 0x40, 0x00, 0x01]) + struct.pack(">II", 0xC002, 0))

    def test_matches_reference_commands(self):
        """Byte-genaue Form der Befehle, wie sie Player erwarten (auf dem Sony UBP-X700 geprüft)."""
        from modules.bdmv.movie_object_generator import (
            cmd_set_audio_from_register, cmd_move_gpr, cmd_compare_gpr, cmd_goto,
            cmd_play_playlist_at_mark_register, CMP_EQ,
        )
        ref = bytes.fromhex
        self.assertEqual(cmd_set_audio_from_register(205), ref("51 40 00 01 80 cd 00 00 00 00 00 00"))
        self.assertEqual(cmd_set_stream(subtitle_id=1, subtitle_on=True), ref("51 c0 00 01 00 00 c0 01 00 00 00 00"))
        self.assertEqual(cmd_move_gpr(205, 1), ref("50 40 00 01 00 00 00 cd 00 00 00 01"))
        self.assertEqual(cmd_compare_gpr(CMP_EQ, 4094, 1), ref("48 40 02 00 00 00 0f fe 00 00 00 01"))
        self.assertEqual(cmd_goto(6), ref("20 81 00 00 00 00 00 06 00 00 00 00"))
        self.assertEqual(cmd_play_playlist_at_mark_register(4, 4095), ref("42 82 00 00 00 00 00 04 00 00 0f ff"))
        self.assertEqual(cmd_play_playlist(4), ref("22 80 00 00 00 00 00 04 00 00 00 00"))

    def test_3d_profile_check(self):
        """3D-Profilprüfung vor SetOutputMode (Maske wie in libbluray)."""
        from modules.bdmv.movie_object_generator import (
            cmd_copy_gpr, cmd_and_gpr, cmd_compare_gpr, CMP_EQ, PSR_PROFILE_VERSION, PROFILE_5_3D,
            output_mode_commands, GPR_PROFILE,
        )
        ref = bytes.fromhex
        self.assertEqual(cmd_copy_gpr(10, PSR_PROFILE_VERSION), ref("50 00 00 01 00 00 00 0a 80 00 00 1f"))
        self.assertEqual(cmd_and_gpr(10, PROFILE_5_3D), ref("50 40 00 09 00 00 00 0a 00 13 02 40"))
        self.assertEqual(cmd_compare_gpr(CMP_EQ, 10, PROFILE_5_3D), ref("48 40 02 00 00 00 00 0a 00 13 02 40"))
        self.assertEqual(output_mode_commands(1)[-1], cmd_set_output_mode(1))
        self.assertEqual(len(output_mode_commands(1)), 4)
        self.assertEqual(GPR_PROFILE, 6)

    def test_set_output_mode(self):
        # 3D Stereoscopic Output Mode: mode = 1
        cmd_3d = cmd_set_output_mode(mode=1)
        self.assertEqual(len(cmd_3d), 12)
        # Opcode: 0x31 0x80 0x00 0x0A (SetOutputMode immediate)
        self.assertEqual(cmd_3d[:4], bytes([0x31, 0x80, 0x00, 0x0A]))
        dst, src = struct.unpack(">II", cmd_3d[4:])
        self.assertEqual(dst, 1)
        self.assertEqual(src, 0)

        # 2D Output Mode: mode = 0
        cmd_2d = cmd_set_output_mode(mode=0)
        self.assertEqual(len(cmd_2d), 12)
        self.assertEqual(cmd_2d[:4], bytes([0x31, 0x80, 0x00, 0x0A]))
        dst, src = struct.unpack(">II", cmd_2d[4:])
        self.assertEqual(dst, 0)
        self.assertEqual(src, 0)

if __name__ == "__main__":
    unittest.main()
