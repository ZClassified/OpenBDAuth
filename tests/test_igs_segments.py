# tests/test_igs_segments.py
import unittest
import struct
from modules.igs.segments import (
    SEGMENT_PDS, SEGMENT_ODS, SEGMENT_ICS, SEGMENT_END,
    make_segment, build_end_segment, build_pds_segment,
    build_ods_segment, build_ics_segment, build_play_playlist_cmd,
    ButtonDef
)

class TestIGSSegments(unittest.TestCase):
    def test_make_segment_header(self):
        payload = b"hello"
        seg = make_segment(0x14, payload)
        self.assertEqual(len(seg), 3 + len(payload))
        seg_type, seg_len = struct.unpack(">BH", seg[:3])
        self.assertEqual(seg_type, 0x14)
        self.assertEqual(seg_len, len(payload))

    def test_end_segment(self):
        self.assertEqual(SEGMENT_END, 0x80)
        end_seg = build_end_segment()
        self.assertEqual(end_seg, bytes([SEGMENT_END, 0x00, 0x00]))

    def test_pds_segment(self):
        fake_pds_payload = bytes([0, 0] + [0] * 50)
        pds_seg = build_pds_segment(fake_pds_payload)
        self.assertEqual(pds_seg[0], SEGMENT_PDS)
        seg_len = struct.unpack(">H", pds_seg[1:3])[0]
        self.assertEqual(seg_len, len(fake_pds_payload))

    def test_ods_segment(self):
        rle_dummy = bytes([1, 2, 3, 0x00, 0x00])
        ods_seg = build_ods_segment(object_id=5, width=100, height=50, rle_data=rle_dummy)
        self.assertEqual(ods_seg[0], SEGMENT_ODS)
        seg_len = struct.unpack(">H", ods_seg[1:3])[0]
        self.assertEqual(seg_len, len(ods_seg) - 3)

        # Prüfe Payload-Header
        payload = ods_seg[3:]
        obj_id, version, seq = struct.unpack(">HBB", payload[:4])
        self.assertEqual(obj_id, 5)
        self.assertEqual(version, 0)
        self.assertEqual(seq, 0xC0) # first + last

        # object_data_length (3 bytes)
        obj_data_len = int.from_bytes(payload[4:7], "big")
        self.assertEqual(obj_data_len, 4 + len(rle_dummy))

        w, h = struct.unpack(">HH", payload[7:11])
        self.assertEqual(w, 100)
        self.assertEqual(h, 50)
        self.assertEqual(payload[11:], rle_dummy)

    def test_play_playlist_cmd(self):
        cmd = build_play_playlist_cmd(playlist_id=1)
        self.assertEqual(len(cmd), 12)
        opcode, pl_id, _ = struct.unpack(">III", cmd)
        self.assertEqual(opcode, 0x22800000)
        self.assertEqual(pl_id, 1)

    def test_jump_title_cmd(self):
        from modules.igs.segments import build_jump_title_cmd
        cmd = build_jump_title_cmd(title_id=1)
        self.assertEqual(len(cmd), 12)
        opcode, title_id, _ = struct.unpack(">III", cmd)
        self.assertEqual(opcode, 0x21810000)
        self.assertEqual(title_id, 1)

    def test_ics_segment(self):
        btn1 = ButtonDef(
            button_id=1,
            numeric_select_value=1,
            x=500, y=400, width=300, height=80,
            upper_button_id=2, lower_button_id=2,
            left_button_id=1, right_button_id=1,
            normal_object_id=0,
            selected_object_id=1,
            activated_object_id=2,
            nav_commands=[build_play_playlist_cmd(1)]
        )
        btn2 = ButtonDef(
            button_id=2,
            numeric_select_value=2,
            x=500, y=500, width=300, height=80,
            upper_button_id=1, lower_button_id=1,
            left_button_id=2, right_button_id=2,
            normal_object_id=3,
            selected_object_id=4,
            activated_object_id=5,
            nav_commands=[build_play_playlist_cmd(2)]
        )

        ics_seg = build_ics_segment(buttons=[btn1, btn2], default_selected_button_id=1)
        self.assertEqual(ics_seg[0], SEGMENT_ICS)
        seg_len = struct.unpack(">H", ics_seg[1:3])[0]
        self.assertEqual(seg_len, len(ics_seg) - 3)

        # Video Descriptor
        v_width, v_height = struct.unpack(">HH", ics_seg[3:7])
        self.assertEqual(v_width, 1920)
        self.assertEqual(v_height, 1080)

        # Interactive Composition: stream_model=1 (Out-of-Mux), ui_model=0 (Always-On)
        self.assertEqual(ics_seg[15], 0x80)

if __name__ == '__main__':
    unittest.main()
