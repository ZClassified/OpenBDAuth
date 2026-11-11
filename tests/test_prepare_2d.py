"""2D-Weg mit echtem ffmpeg: Anpassung von 30 fps an 29,97 fps – Laufzeit bleibt, Prüfung schlägt an."""

import os
import shutil
import tempfile
import unittest

from modules.prepare import jobs
from mvctools.stream import StreamParser
from tests.test_prepare_3d import colour
from tests.prepare_util import ffmpeg, needs_ffmpeg, setUpModule, tearDownModule

SECONDS = 4


@needs_ffmpeg
class Conform2D(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="bd3denc_2d_")
        cls.path = os.path.join(cls.dir, "src30.mkv")
        ffmpeg('-f', 'lavfi', '-i', f"testsrc2=s=1920x1080:r=30:d={SECONDS}", '-c:v', 'ffv1', cls.path)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def encode(self, **kw):
        lines = []
        src = jobs.probe_video(self.path)
        job = jobs.build_2d_job(src, **kw)
        ret = jobs.run_job(job, log=lambda text, is_progress=False: lines.append(text))
        self.assertEqual(ret, 0, "\n".join(lines))
        return src, job.outputs[0], lines

    def test_conformed_keeps_duration(self):
        src, out, lines = self.encode()
        self.assertEqual(src.fps_str, "30")
        self.assertTrue(any(l.startswith("[OK] Bildrate 29.97 fps") for l in lines), "\n".join(lines))
        self.assertTrue(jobs.check_fps_conform(out, jobs.NON_BD_FPS["30"], SECONDS, lambda t: None))
        # Farbkennzeichnung BT.709 (Primärfarben, Transfer, Matrix) im SPS
        self.assertEqual(colour(StreamParser(out, "2D").parse().sps[0]), (1, 1, 1))

    def test_check_catches_unconverted_30p(self):
        _, out, _ = self.encode(conform_fps=False)
        msgs = []
        self.assertFalse(jobs.check_fps_conform(out, jobs.NON_BD_FPS["30"], SECONDS, msgs.append))
        self.assertTrue(msgs[0].startswith("[WARNUNG]"))


if __name__ == "__main__":
    unittest.main()
