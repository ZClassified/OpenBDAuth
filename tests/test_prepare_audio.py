"""Ton-Weg mit echtem ffmpeg: Jedes angebotene Zielformat muss eine Datei mit der erwarteten Kanalzahl ergeben."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest

from modules.prepare import jobs
from tests.prepare_util import FFPROBE_PATH, ffmpeg, needs_ffmpeg, setUpModule, tearDownModule

LAYOUTS = {1: "mono", 2: "stereo", 6: "5.1", 8: "7.1"}


def probe_audio(path):
    out = subprocess.run([FFPROBE_PATH, '-v', 'error', '-select_streams', 'a:0', '-show_entries',
                          'stream=codec_name,channels,sample_rate', '-of', 'json', path],
                         capture_output=True, text=True, creationflags=jobs.NO_WINDOW).stdout
    return json.loads(out)['streams'][0]


@needs_ffmpeg
class AudioFormats(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="bd3denc_audio_")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_every_offered_format_encodes(self):
        for channels, layout in LAYOUTS.items():
            src = os.path.join(self.dir, f"Ton{channels}.wav")
            # 44,1 kHz, damit auch die Umrechnung auf 48 kHz geprüft wird
            ffmpeg('-f', 'lavfi', '-i', 'sine=d=1:r=44100', '-af', f'aformat=channel_layouts={layout}', src)
            for sel in jobs.audio_format_options(channels):
                with self.subTest(sel):
                    job = jobs.build_audio_job(src, sel, 1.0)
                    lines = []
                    ret = jobs.run_job(job, log=lambda text, is_progress=False: lines.append(text))
                    self.assertEqual(ret, 0, "\n".join(lines))
                    out = job.outputs[0]
                    self.assertNotEqual(os.path.abspath(out), os.path.abspath(src))
                    self.assertGreater(os.path.getsize(out), 1000)
                    info = probe_audio(out)
                    self.assertEqual(info['sample_rate'], "48000")
                    expected = 6 if "Downmix auf 5.1" in sel else channels
                    if "Generic" not in sel:
                        self.assertEqual(info['channels'], expected)
                    os.remove(out)

    def test_lpcm_is_24bit_wav(self):
        src = os.path.join(self.dir, "Film.wav")
        ffmpeg('-f', 'lavfi', '-i', 'sine=d=1:r=48000', '-af', 'aformat=channel_layouts=5.1', src)
        job = jobs.build_audio_job(src, "LPCM (5.1 Surround, Uncompressed)", 1.0)
        self.assertEqual(jobs.run_job(job, log=lambda *a, **k: None), 0)
        self.assertEqual(probe_audio(job.outputs[0])['codec_name'], "pcm_s24le")


if __name__ == "__main__":
    unittest.main()
