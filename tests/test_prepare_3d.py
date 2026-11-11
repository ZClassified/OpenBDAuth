"""Ende-zu-Ende: synthetischer Full-TAB-Clip mit Schnitten durch den kompletten 3D-Weg
(Analyse → 2-Pass beide Augen → Rewrite → Verify), adaptiv und mit fester GOP."""

import os
import re
import shutil
import subprocess
import tempfile
import unittest

from modules.prepare import jobs
from mvctools.stream import StreamParser
from tests.prepare_util import HAS_FFMPEG, FFMPEG_PATH, make_tab_source, needs_ffmpeg, setUpModule, tearDownModule

FRAMES = 72          # 3 s bei 23,976 fps


def quiet(*args, **kwargs):
    pass


def idr_positions(path):
    # Closed GOP: ein IDR steht in Decodier- und Anzeigereihenfolge an derselben Stelle
    return [i for i, p in enumerate(StreamParser(path, path).parse().pictures()) if p["idr"]]


def colour(sps):
    vui = sps["vui"]
    return vui.get("colour_primaries"), vui.get("transfer_characteristics"), vui.get("matrix_coefficients")


def hrd(sps):
    cpb = sps["vui"]["nal_hrd"]["cpbs"][0]
    return cpb["bit_rate"], cpb["cpb_size"]


def _supports_option_files():
    # Beim Import ist der Werkzeug-Resolver noch nicht gesetzt (erst setUpModule): mitgeliefertes ffmpeg direkt fragen
    out = subprocess.run([FFMPEG_PATH, '-hide_banner', '-version'], capture_output=True, text=True,
                         creationflags=jobs.NO_WINDOW).stdout
    major = jobs.ffmpeg_major_version(out)
    return major >= 7 if major is not None else "version N-" in out


ADAPTIVE = HAS_FFMPEG and _supports_option_files()


@needs_ffmpeg
class Pipeline3D(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="bd3d_e2e_")
        cls.source = os.path.join(cls.dir, "Test TAB.mkv")
        make_tab_source(cls.source)
        cls.src = jobs.probe_video(cls.source)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def build(self, sub, adaptive):
        out_dir = os.path.join(self.dir, sub)
        os.mkdir(out_dir)
        return jobs.build_3d_job(self.src, 25000, out_dir=out_dir, adaptive=adaptive)

    def run_ok(self, job):
        self.assertEqual(jobs.run_job(job, log=quiet), 0)
        # nur die beiden Ergebnisdateien bleiben übrig, keine Pass-Logs/Zwischendateien
        self.assertEqual(sorted(os.listdir(os.path.dirname(job.outputs[0]))), ["Test TAB_3D.264", "Test TAB_3D.mvc"])
        self.assertEqual(os.listdir(self.dir).count("Test TAB.mkv"), 1)
        return job.outputs

    def test_source(self):
        self.assertEqual((self.src.width, self.src.height, self.src.fps_str, self.src.gop), (1920, 2160, "23.976", 24))

    @unittest.skipUnless(ADAPTIVE, "ffmpeg < 7: kein adaptiver Weg")
    def test_adaptive_idr_at_scene_changes(self):
        base, dep = self.run_ok(self.build("adaptiv", adaptive=True))
        idr_base, idr_dep = idr_positions(base), idr_positions(dep)
        self.assertEqual(idr_base, idr_dep)
        self.assertEqual(idr_base[0], 0)
        self.assertTrue(any(i % 24 for i in idr_base), f"keine IDR an Szenenwechseln: {idr_base}")
        self.assertTrue(all(b - a <= 24 for a, b in zip(idr_base, idr_base[1:])), idr_base)

        bp = StreamParser(base, "Base").parse()
        dp = StreamParser(dep, "Dependent").parse()
        self.assertEqual(len(bp.pictures()), FRAMES)
        self.assertEqual(hrd(bp.sps[0]), (28_000_000, 30_000_000))
        self.assertEqual(hrd(dp.subset_sps[1]), (28_000_000, 30_000_000))
        self.assertEqual([p["slices"] for p in bp.pictures()], [6] * FRAMES)
        # Farbkennzeichnung BT.709 (Primärfarben, Transfer, Matrix) in beiden Views
        for sps in (bp.sps[0], dp.subset_sps[1]):
            self.assertEqual(colour(sps), (1, 1, 1))

    @unittest.skipUnless(ADAPTIVE, "ffmpeg < 7: kein adaptiver Weg")
    def test_verify_catches_asymmetric_eyes(self):
        # Gegenprobe zum Fehler aus Testlauf 2: linkes Auge mit eigener Szenenwechsel-Erkennung, nur das rechte
        # bekommt die IDR-Positionen erzwungen -> abweichende B/P-Typen vor Schnitten -> Prüfschritt schlägt an
        job = self.build("asymmetrisch", adaptive=True)
        for step in job.steps:
            if step.cmd and '[right]' in step.cmd:
                i = step.cmd.index('-x264-params')                  # erstes Vorkommen = linkes Auge
                step.cmd[i + 1] = step.cmd[i + 1].replace("scenecut=0", "scenecut=40")
                j = step.cmd.index('-/force_key_frames')
                del step.cmd[j:j + 2]
        log = []
        self.assertEqual(jobs.run_job(job, log=lambda text, is_progress=False: log.append(text)), 1)
        self.assertTrue(any("passen nicht zusammen" in line for line in log), log[-5:])

    def test_fixed_gop(self):
        base, dep = self.run_ok(self.build("fest", adaptive=False))
        self.assertEqual(idr_positions(base), [0, 24, 48])
        self.assertEqual(idr_positions(dep), [0, 24, 48])


def psnr(a, b, filter_b):
    """Mittlerer PSNR zwischen dem Video a und einem Ausschnitt (filter_b) des Videos b."""
    out = subprocess.run([FFMPEG_PATH, '-hide_banner', '-i', a, '-i', b, '-lavfi', f"[1:v]{filter_b}[r];[0:v][r]psnr",
                          '-f', 'null', '-'], capture_output=True, text=True, creationflags=jobs.NO_WINDOW).stderr
    return float(re.search(r"average:([\d.]+|inf)", out).group(1))


@needs_ffmpeg
class Pipeline3DSbs(unittest.TestCase):
    """Full-SBS (3840×1080): linke Bildhälfte wird zum linken Auge (Base View)."""

    def test_sbs_left_half_is_base_view(self):
        tmp = tempfile.mkdtemp(prefix="bd3d_sbs_")
        self.addCleanup(shutil.rmtree, tmp, True)
        source = os.path.join(tmp, "Test SBS.mkv")
        make_tab_source(source, segments=[("testsrc2", 1.0)], shift=64, stack="hstack")
        src = jobs.probe_video(source)
        self.assertEqual((src.width, src.height, jobs.stereo_layout(src.width, src.height)), (3840, 1080, "sbs"))
        job = jobs.build_3d_job(src, 25000, adaptive=ADAPTIVE)
        self.assertEqual(jobs.run_job(job, log=quiet), 0)
        base, dep = job.outputs
        self.assertEqual(sorted(os.listdir(tmp)), ["Test SBS.mkv", "Test SBS_3D.264", "Test SBS_3D.mvc"])
        left, right = psnr(base, source, "crop=1920:1080:0:0"), psnr(base, source, "crop=1920:1080:1920:0")
        self.assertGreater(left, 25)
        self.assertGreater(left, right + 5)


if __name__ == "__main__":
    unittest.main()
