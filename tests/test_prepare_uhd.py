"""
Vorbereiten für Ultra HD Blu-ray (UHD-Plan, Phase 3): HEVC mit x265 --uhd-bd.
- Quelle: Größe, Bildrate, Bittiefe, Interlaced, Dynamikbereich (SDR BT.709/BT.2020, HDR10), HLG, Dolby Vision,
  fehlende Kennzeichnung, HDR10 ohne Metadaten – abgelehnt mit Grund, umgewandelt wird nichts
- Befehle: zwei Durchläufe („Genau“) oder einer („Schnell“), Spitzenrate, Keyframe-Abstand, Statistik ohne
  Doppelpunkt im Namen, Skalierung für 1080p, Platzbedarf
- mit x265: echte Aufträge aus selbst erzeugten Quellen, Ergebnis besteht die Prüfung von hevctools
"""

import os
import shutil
import tempfile
import unittest

from modules.prepare import jobs, uhd
from tests.prepare_util import ffmpeg, make_hevc, needs_x265, setUpModule, tearDownModule  # noqa: F401

SIDE_DATA = [
    {"side_data_type": "H.26[45] User Data Unregistered SEI message"},
    {"side_data_type": "Mastering display metadata", "red_x": "34000/50000", "red_y": "16000/50000",
     "green_x": "13250/50000", "green_y": "34500/50000", "blue_x": "7500/50000", "blue_y": "3000/50000",
     "white_point_x": "15635/50000", "white_point_y": "16450/50000", "min_luminance": "1/10000",
     "max_luminance": "10000000/10000"},
    {"side_data_type": "Content light level metadata", "max_content": 1000, "max_average": 400},
]
HDR = uhd.hdr_meta_from_side_data(SIDE_DATA)
TAGS = {"sdr709": ("bt709", "bt709", "bt709"), "sdr2020": ("bt2020", "bt2020-10", "bt2020nc"),
        "hdr10": ("bt2020", "smpte2084", "bt2020nc")}


def source(width=3840, height=2160, fps="23.976", bits=10, colour="hdr10", **extra):
    prim, trc, space = TAGS.get(colour, ("", "", ""))
    fps_val = {"23.976": 24000 / 1001, "59.94": 60000 / 1001}.get(fps, float(fps))
    values = dict(path=os.path.join("C:\\Filme", "Mein Film.mov"), width=width, height=height, fps_val=fps_val,
                  fps_str=fps, gop=24, duration=7200.0, color_primaries=prim, color_transfer=trc,
                  color_space=space, bit_depth=bits, pix_fmt="yuv422p10le")
    values.update(extra)
    return jobs.SourceInfo(**values)


def codes(problems):
    return {code for code, _ in problems}


class Source(unittest.TestCase):
    def test_hdr_metadata_from_ffprobe(self):
        self.assertEqual((HDR.green, HDR.blue, HDR.red, HDR.white), ((13250, 34500), (7500, 3000), (34000, 16000),
                                                                     (15635, 16450)))
        self.assertEqual((HDR.max_luminance, HDR.min_luminance, HDR.max_cll, HDR.max_fall), (10000000, 1, 1000, 400))
        self.assertEqual(HDR.x265_params(), ["master-display=G(13250,34500)B(7500,3000)R(34000,16000)"
                                             "WP(15635,16450)L(10000000,1)", "max-cll=1000,400"])
        self.assertIsNone(uhd.hdr_meta_from_side_data(SIDE_DATA[:2]))       # ohne MaxCLL/MaxFALL

    def test_detect_range(self):
        for colour in TAGS:
            self.assertEqual(uhd.detect_range(source(colour=colour)), colour)
        self.assertIsNone(uhd.detect_range(source(colour="")))
        self.assertEqual(uhd.detect_range(source(colour="", color_primaries="bt2020", color_transfer="bt709",
                                                 color_space="bt2020nc")), "sdr2020")

    def test_good_sources(self):
        self.assertEqual(uhd.source_problems(source(), "2160", "hdr10", HDR), [])
        self.assertEqual(uhd.source_problems(source(colour="sdr709"), "2160"), [])
        self.assertEqual(uhd.source_problems(source(1920, 1080, colour="sdr709"), "1080"), [])
        self.assertEqual(uhd.source_problems(source(fps="59.94", colour="sdr2020"), "1080", "sdr2020"), [])

    def test_rejected_sources(self):
        self.assertEqual(codes(uhd.source_problems(source(1920, 1080), "2160", hdr=HDR)), {"uhd_size"})
        self.assertEqual(codes(uhd.source_problems(source(4096, 2160), "1080", hdr=HDR)), {"uhd_size"})
        self.assertEqual(codes(uhd.source_problems(source(fps="30"), hdr=HDR)), {"uhd_fps"})
        self.assertEqual(codes(uhd.source_problems(source(fps="29.97"), hdr=HDR)), {"uhd_fps"})
        self.assertEqual(codes(uhd.source_problems(source(bits=8, colour="sdr709"))), {"uhd_bit_depth"})
        self.assertEqual(codes(uhd.source_problems(source(field_order="tt", colour="sdr709"))), {"interlaced"})
        self.assertEqual(codes(uhd.source_problems(source(colour="", color_primaries="bt2020",
                                                          color_transfer="arib-std-b67",
                                                          color_space="bt2020nc"))), {"uhd_hlg"})
        self.assertEqual(codes(uhd.source_problems(source(dolby_vision=True), hdr=HDR)), {"uhd_dolby_vision"})
        self.assertEqual(codes(uhd.source_problems(source(colour=""))), {"uhd_colour"})
        self.assertEqual(codes(uhd.source_problems(source(), "2160", "sdr709", HDR)), {"uhd_range"})
        self.assertEqual(codes(uhd.source_problems(source())), {"uhd_hdr_meta"})           # HDR10 ohne Angaben
        broken = uhd.HdrMeta(HDR.green, HDR.blue, HDR.red, HDR.white, 1000, 5000, 400, 1000)
        self.assertEqual(codes(uhd.source_problems(source(), hdr=broken)), {"uhd_hdr_meta"})


class Commands(unittest.TestCase):
    def params(self, step):
        return step.cmd[step.cmd.index('-x265-params') + 1].split(":")

    def test_exact_two_passes(self):
        job = uhd.build_uhd_job(source(), "2160", 45, uhd.MODE_EXACT, hdr=HDR, out_dir="D:\\Ausgabe")
        self.assertEqual(job.outputs, [os.path.join("D:\\Ausgabe", "Mein Film_2160p.hevc")])
        self.assertEqual(job.cwd, "D:\\Ausgabe")                     # Statistik relativ zum Zielordner
        enc = [s for s in job.steps if s.cmd]
        self.assertEqual(len(enc), 2)
        p1, p2 = self.params(enc[0]), self.params(enc[1])
        self.assertIn("pass=1", p1)
        self.assertIn("pass=2", p2)
        stats = next(p for p in p1 if p.startswith("stats="))
        self.assertEqual(stats, "stats=Mein_Film_2160p.x265stats")    # ohne Leerzeichen und Doppelpunkt
        self.assertIn(stats, p2)
        for p in ("uhd-bd=1", "aud=1", "hrd=1", "repeat-headers=1", "keyint=24", "min-keyint=1",
                  "colorprim=bt2020", "transfer=smpte2084", "colormatrix=bt2020nc", "hdr10=1",
                  "vbv-maxrate=72000", "max-cll=1000,400"):
            self.assertIn(p, p2)
        self.assertEqual(enc[0].cmd[-3:-1], ['-f', 'null'])
        self.assertIn('45M', enc[1].cmd)
        self.assertEqual(enc[1].cmd[-1], "Mein Film_2160p.hevc")
        self.assertNotIn('-vf', enc[1].cmd)                         # 3840×2160 bleibt
        self.assertEqual(job.steps[-1].cmd, None)                    # Prüfung mit hevctools
        self.assertEqual(job.temp_prefixes, [os.path.join("D:\\Ausgabe", "Mein_Film_2160p.x265stats")])

    def test_fast_one_pass_and_1080(self):
        job = uhd.build_uhd_job(source(fps="50", colour="sdr709"), "1080", 15, uhd.MODE_FAST)
        enc = [s for s in job.steps if s.cmd]
        self.assertEqual(len(enc), 1)
        params = self.params(enc[0])
        self.assertFalse(any(p.startswith(("pass=", "stats=")) for p in params))
        self.assertIn("keyint=50", params)
        self.assertIn("vbv-maxrate=40000", params)
        self.assertNotIn("hdr10=1", params)
        self.assertIn("scale=1920:1080:flags=lanczos", enc[0].cmd)
        self.assertTrue(job.outputs[0].endswith("Mein Film_1080p.hevc"))

    def test_space_and_bitrate(self):
        exact = uhd.build_uhd_job(source(), "2160", 45, uhd.MODE_EXACT, hdr=HDR)
        fast = uhd.build_uhd_job(source(), "2160", 45, uhd.MODE_FAST, hdr=HDR)
        video = 7200 * 45 * 125_000
        self.assertGreater(exact.space_needed, video + 7200 * 24 * 30_000)   # dazu die x265-Statistik
        self.assertGreater(fast.space_needed, video)
        self.assertLess(fast.space_needed, exact.space_needed)
        self.assertEqual(uhd.estimated_size(7200, 45), video)
        with self.assertRaises(ValueError):
            uhd.build_uhd_job(source(), "2160", 30, hdr=HDR)            # keine angebotene Stufe
        with self.assertRaises(ValueError):
            uhd.build_uhd_job(source(1920, 1080), "2160", hdr=HDR)      # ungeeignete Quelle

    def test_offered_rates_stay_below_peak(self):
        for res, rates in uhd.BITRATES.items():
            self.assertIn(uhd.DEFAULT_BITRATE[res], rates)
            self.assertLess(max(rates) * 1000, uhd.PEAK_KBPS[res])


@needs_x265
class Encode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="prepare_uhd_")
        cls.prores = os.path.join(cls.dir, "Mezzanine SDR.mov")
        # Farbkennzeichnung über setparams: die Ausgabeoptionen allein schreibt ffmpeg bei ProRes nicht ganz
        ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=1920x1080:r=24000/1001:d=0.5',
               '-vf', 'setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709', '-pix_fmt', 'yuv422p10le',
               '-c:v', 'prores_ks', '-profile:v', '3', cls.prores)
        cls.hdr = os.path.join(cls.dir, "Mezzanine HDR.mkv")
        make_hevc(cls.hdr, seconds=0.5, size="3840x2160", colour="hdr10", fmt="matroska")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def run_job(self, job):
        lines = []
        ret = jobs.run_job(job, log=lambda text, is_progress=False: None if is_progress else lines.append(text))
        return ret, lines

    def test_prores_sdr_to_1080p_exact(self):
        src = jobs.probe_video(self.prores)
        self.assertEqual((src.bit_depth, uhd.detect_range(src)), (10, "sdr709"))
        job = uhd.build_uhd_job(src, "1080", 15, uhd.MODE_EXACT, "sdr709", out_dir=self.dir)
        ret, lines = self.run_job(job)
        self.assertEqual(ret, 0, "\n".join(lines[-20:]))
        self.assertTrue(any(line.startswith("OK:") for line in lines))
        self.assertTrue(os.path.isfile(job.outputs[0]))
        self.assertFalse([f for f in os.listdir(self.dir) if "x265stats" in f])     # Statistik aufgeräumt

    def test_hdr10_metadata_carried_over(self):
        src = jobs.probe_video(self.hdr)
        self.assertEqual(uhd.probe_hdr_meta(self.hdr), HDR)
        job = uhd.build_uhd_job(src, "2160", 25, uhd.MODE_FAST, "hdr10", out_dir=self.dir)
        ret, lines = self.run_job(job)
        self.assertEqual(ret, 0, "\n".join(lines[-20:]))
        from hevctools.check import check_stream
        _findings, info = check_stream(job.outputs[0], "hdr10")
        self.assertEqual(info["hdr"]["content_light_level"], {"max_cll": 1000, "max_fall": 400})
        self.assertAlmostEqual(info["fps"], 24000 / 1001)


if __name__ == "__main__":
    unittest.main()
