"""
hevctools (UHD-Plan, Phase 2): HEVC-Ströme lesen und nach den Regeln für Ultra HD Blu-ray prüfen.
- Bausteine ohne ffmpeg: SEI zerlegen, HDR-Metadaten, HDR10+, Encoder-Text, Puffer-Simulation, NAL-Header
- mit x265: gültige Ströme (SDR BT.709, SDR BT.2020, HDR10, 3840×2160) bestehen; was x265 bei --uhd-bd
  stillschweigend nicht einhält oder was ohne --uhd-bd entsteht, wird mit Grund abgelehnt
Alle Clips erzeugt ffmpeg selbst (Testbild), kein fremdes Material.
"""

import os
import shutil
import tempfile
import unittest

from hevctools import sei
from hevctools.check import ERROR, check_stream, simulate_cpb
from hevctools.nal import iter_nal_units
from hevctools.stream import StreamParser
from tests.prepare_util import make_hevc, needs_x265


def codes(findings, level=ERROR):
    return {f.code for f in findings if f.level == level}


class Building(unittest.TestCase):
    def test_split_sei_messages(self):
        # zwei Nachrichten (Typ 137 mit 24 Byte, Typ 144 mit 4 Byte) und rbsp_trailing_bits
        md = bytes(range(24))
        payload = bytes([137, 24]) + md + bytes([144, 4, 0x03, 0xE8, 0x01, 0x90, 0x80])
        msgs = sei.split_sei_messages(payload)
        self.assertEqual([t for t, _ in msgs], [137, 144])
        self.assertEqual(sei.content_light_level(msgs[1][1]), {"max_cll": 1000, "max_fall": 400})

    def test_long_payload_type_and_size(self):
        payload = bytes([0xFF, 0xFF, 2]) + bytes([0xFF, 10]) + bytes(265) + b"\x80"
        ((t, data),) = sei.split_sei_messages(payload)
        self.assertEqual((t, len(data)), (512, 265))

    def test_mastering_display_units(self):
        values = [13250, 34500, 7500, 3000, 34000, 16000, 15635, 16450]
        data = b"".join(v.to_bytes(2, "big") for v in values) + (10000000).to_bytes(4, "big") + (50).to_bytes(4, "big")
        md = sei.mastering_display(data)
        self.assertEqual(md["primaries"][0], (0.265, 0.69))
        self.assertEqual(md["white_point"], (0.3127, 0.329))
        self.assertEqual((md["max_luminance"], md["min_luminance"]), (1000.0, 0.005))

    def test_hdr10plus_and_encoder_text(self):
        self.assertTrue(sei.is_hdr10plus(bytes([0xB5, 0x00, 0x3C, 0x00, 0x01, 0x04, 0x01])))
        self.assertFalse(sei.is_hdr10plus(bytes([0xB5, 0x00, 0x31, 0x00, 0x01, 0x04])))
        self.assertEqual(sei.unregistered_text(bytes(16) + b"x265 - options: crf=18\x00"), "x265 - options: crf=18")
        self.assertIsNone(sei.unregistered_text(bytes(16) + bytes([1, 2, 3])))

    def test_cpb_simulation(self):
        # 10 Mbit/s, 10 Mbit Puffer, 25 fps: 400 kbit je Bild fließen nach
        ok = [50_000] * 50                                  # 400 kbit je Bild: genau die Zufuhr
        self.assertIsNone(simulate_cpb(ok, 10_000_000, 10_000_000, False, 25, 90000 * 0.5))
        big = [50_000] * 10 + [700_000] + [50_000] * 10     # 5,6 Mbit nach 0,5 s Anlauf
        kind, index, _bits, _fullness = simulate_cpb(big, 10_000_000, 10_000_000, False, 25, 90000 * 0.5)
        self.assertEqual((kind, index), ("underflow", 10))
        self.assertIsNone(simulate_cpb(big, 10_000_000, 10_000_000, False, 25, 90000 * 0.9))
        small = [1_000] * 50                                 # CBR: Puffer läuft über, VBR: Zufuhr pausiert
        self.assertEqual(simulate_cpb(small, 10_000_000, 2_000_000, True, 25, 90000 * 0.1)[0], "overflow")
        self.assertIsNone(simulate_cpb(small, 10_000_000, 2_000_000, False, 25, 90000 * 0.1))


@needs_x265
class Streams(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="hevctools_")
        cls.files = {}
        for name, kwargs in {
            "sdr709": {},
            "sdr2020": {"colour": "sdr2020"},
            "hdr10": {"colour": "hdr10"},
            "uhd": {"colour": "hdr10", "size": "3840x2160", "seconds": 0.3},
            "p720": {"size": "1280x720", "rate": "50"},           # x265: „uhd-bd: Disabled“, kodiert trotzdem
            "plain": {"uhd_bd": False, "extra": "keyint=60:open-gop=1", "seconds": 3, "size": "640x360"},
            "hlg": {"colour": "colorprim=bt2020:transfer=arib-std-b67:colormatrix=bt2020nc"},
            "p30": {"rate": "30", "seconds": 1.2},
        }.items():
            cls.files[name] = os.path.join(cls.dir, f"{name}.hevc")
            make_hevc(cls.files[name], **kwargs)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def check(self, name, dynamic_range=None):
        return check_stream(self.files[name], dynamic_range)

    def test_valid_streams_pass(self):
        for name, dynamic_range in (("sdr709", "sdr709"), ("sdr2020", "sdr2020"), ("hdr10", "hdr10"),
                                    ("uhd", "hdr10")):
            with self.subTest(name):
                findings, info = self.check(name, dynamic_range)
                self.assertEqual(codes(findings), set(), [f.text for f in findings])
                self.assertEqual(info["dynamic_range"], dynamic_range)
        _findings, info = self.check("uhd")
        self.assertEqual((info["width"], info["height"]), (3840, 2160))
        self.assertAlmostEqual(info["fps"], 24000 / 1001)
        self.assertIn("x265", info["encoder"])

    def test_hdr10_metadata_read(self):
        _findings, info = self.check("hdr10")
        md, cll = info["hdr"]["mastering_display"], info["hdr"]["content_light_level"]
        self.assertEqual((md["max_luminance"], md["min_luminance"]), (1000.0, 0.0001))
        self.assertEqual(md["primaries"], [(0.265, 0.69), (0.15, 0.06), (0.68, 0.32)])
        self.assertEqual(cll, {"max_cll": 1000, "max_fall": 400})

    def test_wrong_dynamic_range(self):
        findings, _info = self.check("hdr10", "sdr709")
        self.assertIn("range_mismatch", codes(findings))
        findings, _info = self.check("sdr709", "hdr10")
        self.assertTrue({"range_mismatch", "mastering_display", "content_light"} <= codes(findings))

    def test_uhd_bd_silently_disabled(self):
        findings, _info = self.check("p720")
        self.assertTrue({"size", "tier"} <= codes(findings))

    def test_stream_without_uhd_bd_rules(self):
        findings, _info = self.check("plain")
        self.assertTrue({"aud", "open_gop", "gop_length", "hrd"} <= codes(findings), codes(findings))

    def test_hlg_and_frame_rate(self):
        self.assertIn("transfer", codes(self.check("hlg")[0]))
        self.assertIn("frame_rate", codes(self.check("p30")[0]))

    def test_dolby_vision_rpu_rejected(self):
        path = os.path.join(self.dir, "dv.hevc")
        rpu = b"\x00\x00\x01" + bytes([62 << 1, 0x01]) + bytes([0x19, 0x08, 0x09, 0x80])
        with open(self.files["sdr709"], "rb") as src, open(path, "wb") as dst:
            dst.write(src.read() + rpu)
        self.assertIn("dolby_vision", codes(check_stream(path)[0]))

    def test_access_units_and_nal_header(self):
        sp = StreamParser(self.files["sdr709"]).parse()
        self.assertEqual(len(sp.aus), len(sp.pictures()))
        self.assertTrue(all(au["aud"] for au in sp.aus))
        self.assertEqual(sum(au["bytes"] for au in sp.aus) + sp.aus[0]["start"], sp.total_bytes)
        first = next(iter_nal_units(self.files["sdr709"]))
        self.assertEqual((first.type, first.layer_id, first.temporal_id), (35, 0, 0))


if __name__ == "__main__":
    unittest.main()
