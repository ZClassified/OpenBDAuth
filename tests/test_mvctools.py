"""mvctools: Bitstream-Grundlagen (ohne ffmpeg) sowie Rewriter und Verify an kleinen x264-Streams."""

import os
import random
import shutil
import tempfile
import unittest

from mvctools.bitstream import BitReader, BitWriter, ebsp_to_rbsp, rbsp_to_ebsp
from mvctools.nal import parse_mvc_ext
from mvctools.rewrite import MvcRewriter, _mvc_header
from mvctools.stream import StreamParser
from mvctools.verify import verify_pair
from tests.prepare_util import make_h264, needs_ffmpeg


class Bitstream(unittest.TestCase):
    def test_exp_golomb_roundtrip(self):
        values = list(range(300)) + [1023, 65535, 2 ** 31 - 2]
        signed = [0, 1, -1, 2, -2, 26, -26, 1000, -1000]
        w = BitWriter()
        for v in values:
            w.ue(v)
        for v in signed:
            w.se(v)
        w.u(5, 0b10110)
        w.rbsp_trailing_bits()
        r = BitReader(w.getvalue())
        self.assertEqual([r.ue() for _ in values], values)
        self.assertEqual([r.se() for _ in signed], signed)
        self.assertEqual(r.u(5), 0b10110)
        self.assertFalse(r.more_rbsp_data())

    def test_emulation_prevention_roundtrip(self):
        rnd = random.Random(1)
        for _ in range(300):
            # viele Nullen, damit 00 00 0x häufig vorkommt; RBSP endet nie auf 0x00
            data = bytes(rnd.choice((0, 0, 0, 1, 2, 3, 0xFF)) for _ in range(rnd.randint(1, 64))) + b"\x80"
            ebsp = rbsp_to_ebsp(data)
            for i in range(len(ebsp) - 2):
                self.assertFalse(ebsp[i] == 0 and ebsp[i + 1] == 0 and ebsp[i + 2] <= 2, ebsp.hex())
            self.assertEqual(ebsp_to_rbsp(ebsp), data)

    def test_known_sequences(self):
        self.assertEqual(rbsp_to_ebsp(b"\x00\x00\x01\x80"), b"\x00\x00\x03\x01\x80")
        self.assertEqual(rbsp_to_ebsp(b"\x00\x00\x00\x00\x80"), b"\x00\x00\x03\x00\x00\x80")
        self.assertEqual(rbsp_to_ebsp(b"\x00\x00\x00\x00\x00\x01"), b"\x00\x00\x03\x00\x00\x03\x00\x01")
        self.assertEqual(ebsp_to_rbsp(b"\x11\x00\x00\x03\x03\x22"), b"\x11\x00\x00\x03\x22")

    def test_mvc_nal_header(self):
        h = parse_mvc_ext(_mvc_header(non_idr=0, view_id=1, anchor=1))
        self.assertEqual((h["non_idr_flag"], h["view_id"], h["anchor_pic_flag"], h["inter_view_flag"],
                          h["priority_id"], h["temporal_id"], h["reserved_one_bit"]), (0, 1, 1, 0, 0, 0, 1))
        h = parse_mvc_ext(_mvc_header(non_idr=1, view_id=1, anchor=0, inter_view=1, priority_id=5, temporal_id=2))
        self.assertEqual((h["non_idr_flag"], h["anchor_pic_flag"], h["inter_view_flag"], h["priority_id"],
                          h["temporal_id"]), (1, 0, 1, 5, 2))


@needs_ffmpeg
class RewriteAndVerify(unittest.TestCase):
    """Linkes und rechtes Auge mit gleicher GOP-Struktur, rechtes per Rewriter zum Dependent View."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="bd3d_test_")
        cls.left = os.path.join(cls.dir, "left.264")
        cls.right = os.path.join(cls.dir, "right.264")
        cls.mvc = os.path.join(cls.dir, "right.mvc")
        make_h264(cls.left, seconds=2.0, keyint=12)
        make_h264(cls.right, seconds=2.0, keyint=12, pattern="smptehdbars")
        cls.rw = MvcRewriter()
        cls.count = cls.rw.run(cls.right, cls.mvc)
        cls.dep = StreamParser(cls.mvc, "Dependent View").parse()
        cls.pics = cls.dep.pictures()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_picture_count(self):
        self.assertEqual(self.count, 48)
        self.assertEqual(len(self.pics), 48)
        self.assertFalse(self.dep.errors)

    def test_nal_types(self):
        types = set(self.dep.nal_stats)
        self.assertTrue({24, 15, 8, 6, 20, 10} <= types, types)
        self.assertFalse(types & {1, 5, 7, 9}, "AVC-NALs im Dependent View")
        # End of Sequence vor jedem IDR außer dem ersten
        self.assertEqual(self.dep.nal_stats[10], sum(1 for p in self.pics if p["idr"]) - 1)

    def test_subset_sps_and_pps(self):
        self.assertEqual(list(self.dep.subset_sps), [1])
        s = self.dep.subset_sps[1]
        self.assertEqual(s["profile_idc"], 128)          # Stereo High
        self.assertEqual(s["mvc"]["num_views"], 2)
        self.assertEqual(s["mvc"]["view_id"], [0, 1])
        self.assertEqual(list(self.dep.pps), [1])        # eigene PPS-ID, Base View hat 0

    def test_mvc_slice_headers(self):
        for p in self.pics:
            self.assertEqual(p["mvc"]["view_id"], 1)
            self.assertEqual(p["mvc"]["anchor_pic_flag"], 1 if p["idr"] else 0)
            self.assertEqual(p["mvc"]["non_idr_flag"], 0 if p["idr"] else 1)
            self.assertEqual(p["mvc"]["inter_view_flag"], 0)
            self.assertTrue(p["cabac_align_ok"])

    def test_hrd_sei_nested(self):
        keys = set(self.dep.sei_catalog)
        self.assertIn("37>0", keys)                       # Buffering Period in MVC Scalable Nesting
        self.assertIn("37>1", keys)                       # Pic Timing in MVC Scalable Nesting
        self.assertFalse({"0", "1"} & keys, "HRD-SEI ohne Nesting")

    def test_verify_accepts_matching_pair(self):
        problems, info = verify_pair(self.left, self.mvc)
        self.assertEqual(problems, [])
        self.assertEqual(info["pictures"], 48)

    def test_verify_rejects_other_gop(self):
        other = os.path.join(self.dir, "left_gop8.264")
        make_h264(other, seconds=2.0, keyint=8)
        problems, _ = verify_pair(other, self.mvc)
        self.assertTrue(any("passen nicht zusammen" in p for p in problems), problems)

    def test_verify_rejects_avc_as_dependent(self):
        problems, _ = verify_pair(self.left, self.right)
        self.assertTrue(problems)


if __name__ == "__main__":
    unittest.main()
