"""Quellprüfung und Ton aus Videodateien mit echtem ffmpeg: Was ffprobe über Interlaced, HDR und Tonspuren
meldet, muss bei source_problems bzw. probe_audio ankommen; SD-Quellen werden mit Farbumrechnung codiert."""

import os
import shutil
import tempfile
import unittest

from modules.prepare import jobs
from tests.test_prepare_audio import probe_audio as probe_stream
from tests.prepare_util import ffmpeg, needs_ffmpeg, setUpModule, tearDownModule

TESTSRC = "testsrc2=s=1920x1080:r=24000/1001:d=1"


@needs_ffmpeg
class Sources(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="bd3denc_src_")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def make(self, name, *args):
        path = os.path.join(self.dir, name)
        ffmpeg('-f', 'lavfi', '-i', TESTSRC, *args, path)
        return jobs.probe_video(path)

    def codes(self, src, mode="2d"):
        return [code for code, _ in jobs.source_problems(src, mode)]

    def test_progressive_sdr_passes(self):
        self.assertEqual(self.codes(self.make("ok.mov", '-c:v', 'ffv1', '-field_order', 'progressive')), [])

    def test_interlaced_flag_detected(self):
        # FFV1 speichert keine Halbbild-Kennzeichnung, x264 (echtes Interlaced) schon
        src = self.make("tt.mkv", '-c:v', 'libx264', '-preset', 'ultrafast', '-flags', '+ildct+ilme',
                        '-x264-params', 'interlaced=1:tff=1')
        self.assertIn(src.field_order, jobs.INTERLACED)
        self.assertEqual(self.codes(src), ["interlaced"])

    def test_hdr_flag_detected(self):
        # ffmpeg 9 übernimmt -color_trc/-color_primaries als Ausgabeoption nicht mehr, setparams schon
        src = self.make("pq.mkv", '-vf', 'setparams=color_trc=smpte2084:color_primaries=bt2020:colorspace=bt2020nc',
                        '-c:v', 'libx264', '-preset', 'ultrafast')
        self.assertEqual((src.color_transfer, src.color_primaries), ("smpte2084", "bt2020"))
        self.assertEqual(self.codes(src), ["hdr"])

    def test_no_video(self):
        path = os.path.join(self.dir, "nur_ton.wav")
        ffmpeg('-f', 'lavfi', '-i', 'sine=d=1:r=48000', path)
        with self.assertRaises(ValueError):
            jobs.probe_video(path)

    def test_sd_upscale_encodes(self):
        # Farbumrechnung BT.601 -> BT.709 im scale-Filter muss ffmpeg auch wirklich annehmen
        path = os.path.join(self.dir, "SD.mkv")
        ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=720x576:r=25:d=1', '-c:v', 'ffv1', path)
        job = jobs.build_2d_job(jobs.probe_video(path), out_dir=self.dir)
        self.assertIn("out_color_matrix=bt709", job.steps[0].cmd[job.steps[0].cmd.index('-vf') + 1])
        self.assertEqual(jobs.run_job(job, log=lambda *a, **k: None), 0)
        self.assertGreater(os.path.getsize(job.outputs[0]), 1000)


@needs_ffmpeg
class AudioFromVideo(unittest.TestCase):
    """Video mit zwei Tonspuren: AC3 5.1 (deutsch, 1:1 übernehmbar) und PCM-Stereo, 100 ms später beginnend."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="bd3denc_avsrc_")
        cls.path = os.path.join(cls.dir, "Film.mkv")
        ffmpeg('-f', 'lavfi', '-i', TESTSRC, '-f', 'lavfi', '-i', 'sine=d=1:r=48000',
               '-itsoffset', '0.1', '-f', 'lavfi', '-i', 'sine=d=1:r=48000:f=880',
               '-filter_complex', '[1:a]aformat=channel_layouts=5.1[a1];[2:a]aformat=channel_layouts=stereo[a2]',
               '-map', '0:v', '-map', '[a1]', '-map', '[a2]', '-c:v', 'ffv1', '-c:a:0', 'ac3', '-c:a:1', 'pcm_s24le',
               '-metadata:s:a:0', 'language=deu', cls.path)
        cls.source = jobs.probe_audio(cls.path)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def run_job(self, job):
        self.assertEqual(jobs.run_job(job, log=lambda *a, **k: None), 0)
        return job.outputs[0]

    def test_tracks(self):
        self.assertTrue(self.source.has_video)
        ac3, pcm = self.source.tracks
        self.assertEqual((ac3.index, ac3.codec, ac3.channels, ac3.language), (0, "ac3", 6, "deu"))
        self.assertEqual((pcm.index, pcm.codec, pcm.channels, pcm.language), (1, "pcm_s24le", 2, ""))

    def test_copy_ac3_unchanged(self):
        track = self.source.tracks[0]
        out = self.run_job(jobs.build_audio_job(self.path, jobs.audio_track_options(track)[0], 1.0, track=track))
        self.assertEqual(os.path.basename(out), "Film_ton1_deu.ac3")
        info = probe_stream(out)
        self.assertEqual((info['codec_name'], info['channels']), ("ac3", 6))

    def test_pcm_to_lpcm_wav(self):
        track = self.source.tracks[1]
        out = self.run_job(jobs.build_audio_job(self.path, "LPCM (Stereo, Uncompressed)", 1.0, track=track))
        self.assertEqual(os.path.basename(out), "Film_ton2_lpcm.wav")
        info = probe_stream(out)
        self.assertEqual((info['codec_name'], info['channels']), ("pcm_s24le", 2))

    def test_offset_warned(self):
        ac3, pcm = self.source.tracks
        self.assertLess(abs(ac3.offset), jobs.OFFSET_WARN)
        self.assertAlmostEqual(pcm.offset, 0.1, delta=0.01)
        notes = jobs.build_audio_job(self.path, "AC3 (Stereo, 192 kbps)", track=pcm).notes
        self.assertTrue(notes and "100 ms später" in notes[0], notes)

    def test_wav_source_unchanged(self):
        path = os.path.join(self.dir, "Ton.wav")
        ffmpeg('-f', 'lavfi', '-i', 'sine=d=1:r=48000', path)
        source = jobs.probe_audio(path)
        self.assertFalse(source.has_video)
        self.assertEqual(source.tracks[0].offset, 0.0)
        self.assertEqual(jobs.audio_track_options(source.tracks[0]), jobs.audio_format_options(1))
