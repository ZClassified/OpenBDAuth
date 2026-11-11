"""Befehlsaufbau (jobs.py) ohne ffmpeg: Die erzeugten Befehle sind hardware-geprüft – Änderungen hier
bedeuten einen neuen Player-Test (siehe docs/mvc/phase-1-simulcast.md)."""

import os
import tempfile
import unittest

from modules.prepare import jobs

COLOR = ['-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709']


def src(w=1920, h=1080, rate="24000/1001", name="Mein Film.mov", **kw):
    fps_val, fps_str, gop = jobs.parse_fps({"avg_frame_rate": rate})
    return jobs.SourceInfo(path=os.path.join("C:\\Filme", name), width=w, height=h,
                           fps_val=fps_val, fps_str=fps_str, gop=gop, duration=60.0, **kw)


class ParseFps(unittest.TestCase):
    def test_bluray_rates(self):
        cases = {"24000/1001": ("23.976", 24), "24/1": ("24", 24), "25/1": ("25", 25),
                 "30000/1001": ("29.97", 30), "30/1": ("30", 30), "50/1": ("50", 50),
                 "60000/1001": ("59.94", 60), "60/1": ("60", 60)}
        for rate, (text, gop) in cases.items():
            self.assertEqual(jobs.parse_fps({"avg_frame_rate": rate})[1:], (text, gop), rate)

    def test_fallbacks(self):
        self.assertEqual(jobs.parse_fps({"avg_frame_rate": "0/0", "r_frame_rate": "25/1"})[1:], ("25", 25))
        self.assertEqual(jobs.parse_fps({})[1:], ("24", 24))
        self.assertEqual(jobs.parse_fps({"avg_frame_rate": "12/1"})[1:], ("12.0", 12))


class Build2D(unittest.TestCase):
    def test_1080p23976_no_scaling(self):
        job = jobs.build_2d_job(src(), bitrate=20)
        self.assertEqual(job.steps[0].cmd, [
            'ffmpeg', '-y', '-stats', '-i', 'Mein Film.mov', '-map', '0:v:0', '-an', '-sn', '-pix_fmt', 'yuv420p',
            '-fps_mode', 'cfr', '-c:v', 'libx264', '-profile:v', 'high', '-level', '4.1',
            '-b:v', '20M', '-maxrate', '35M', '-bufsize', '30M', '-x264-params',
            'bluray-compat=1:open-gop=0:slices=4:keyint=24:min-keyint=1:vbv-maxrate=35000:vbv-bufsize=30000:'
            'nal-hrd=vbr:b-pyramid=strict:sar=1/1:colorprim=bt709:transfer=bt709:colormatrix=bt709', *COLOR,
            '-f', 'h264', 'Mein Film.264'])
        self.assertEqual(job.cwd, "C:\\Filme")
        self.assertEqual(job.outputs, [os.path.join("C:\\Filme", "Mein Film.264")])

    def test_25p_psf_with_scaling(self):
        job = jobs.build_2d_job(src(3840, 2160, "25/1"), bitrate=25, psf_25=True)
        cmd = job.steps[0].cmd
        self.assertEqual(cmd[5:7], ['-vf', 'scale=1920:1080:force_original_aspect_ratio=decrease:force_divisible_by=2,'
                                           'pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1/1'])
        self.assertEqual(cmd[cmd.index('-x264-params') + 1],
                         'bluray-compat=1:open-gop=0:slices=4:keyint=25:min-keyint=1:vbv-maxrate=40000:'
                         'vbv-bufsize=30000:nal-hrd=vbr:b-pyramid=strict:sar=1/1:colorprim=bt709:transfer=bt709:'
                         'colormatrix=bt709:fake-interlaced=1:weightp=0:pic-struct=1')
        self.assertIn('-b:v', cmd)
        self.assertEqual(cmd[cmd.index('-b:v') + 1:cmd.index('-b:v') + 4], ['25M', '-maxrate', '40M'])
        self.assertTrue(any("PsF" in n for n in job.notes))

    def test_25p_native(self):
        cmd = jobs.build_2d_job(src(rate="25/1"), psf_25=False).steps[0].cmd
        self.assertNotIn("fake-interlaced", cmd[cmd.index('-x264-params') + 1])

    def test_2997_always_psf(self):
        cmd = jobs.build_2d_job(src(rate="30000/1001"), psf_25=False).steps[0].cmd
        self.assertIn("fake-interlaced=1", cmd[cmd.index('-x264-params') + 1])

    def test_resolution_follows_frame_rate(self):
        # 50/60 fps nur als 720p, 25/29,97/30 fps nur als 1080, 23,976/24 fps beides
        for rate, forced in (("24000/1001", None), ("24/1", None), ("25/1", False), ("30000/1001", False),
                             ("30/1", False), ("50/1", True), ("60000/1001", True), ("60/1", True)):
            s = src(rate=rate)
            self.assertEqual(jobs.forced_720p(s.fps_str), forced, rate)
            for target_720p in (False, True):
                if forced is None or forced == target_720p:
                    self.assertTrue(jobs.build_2d_job(s, target_720p=target_720p).steps, rate)
                else:
                    with self.assertRaises(ValueError, msg=f"{rate} 720p={target_720p}"):
                        jobs.build_2d_job(s, target_720p=target_720p)

    def test_sd_source_converted_to_bt709(self):
        vf = lambda s: (lambda c: c[c.index('-vf') + 1])(jobs.build_2d_job(s).steps[0].cmd)
        self.assertIn(":in_color_matrix=bt601:out_color_matrix=bt709,pad=", vf(src(720, 576, "25/1")))
        self.assertNotIn("color_matrix", vf(src(720, 576, "25/1", color_space="bt709")))
        self.assertNotIn("color_matrix", vf(src(1280, 720)))

    def test_out_dir(self):
        job = jobs.build_2d_job(src(), out_dir="D:\\Ausgabe")
        self.assertEqual(job.steps[0].cmd[-1], os.path.join("D:\\Ausgabe", "Mein Film.264"))
        self.assertEqual(job.outputs, [os.path.join("D:\\Ausgabe", "Mein Film.264")])
        self.assertEqual(job.cwd, "C:\\Filme")
        self.assertGreater(job.space_needed, 60 * 20e6 / 8)

    def test_720p_scaling_and_bitrate_15(self):
        cmd = jobs.build_2d_job(src(rate="50/1"), bitrate=15, target_720p=True).steps[0].cmd
        self.assertIn('scale=1280:720', cmd[cmd.index('-vf') + 1])
        self.assertEqual(cmd[cmd.index('-b:v') + 1:cmd.index('-b:v') + 4], ['15M', '-maxrate', '30M'])
        self.assertIn('keyint=50:', cmd[cmd.index('-x264-params') + 1])

    def test_30p_conformed_to_2997_psf(self):
        job = jobs.build_2d_job(src(rate="30/1"))
        cmd = job.steps[0].cmd
        self.assertEqual(cmd[5:7], ['-vf', 'fps=30000/1001'])
        self.assertIn("fake-interlaced=1", cmd[cmd.index('-x264-params') + 1])
        self.assertIn('keyint=30:', cmd[cmd.index('-x264-params') + 1])
        self.assertEqual([s.title for s in job.steps][1:], ["Bildraten-Prüfung"])
        self.assertTrue(any("30 fps -> 29.97 fps" in n for n in job.notes))

    def test_60p_conformed_before_scaling(self):
        cmd = jobs.build_2d_job(src(rate="60/1"), target_720p=True).steps[0].cmd
        self.assertEqual(cmd[cmd.index('-vf') + 1],
                         'fps=60000/1001,scale=1280:720:force_original_aspect_ratio=decrease:force_divisible_by=2,'
                         'pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1/1')

    def test_30p_kept_when_not_wanted(self):
        job = jobs.build_2d_job(src(rate="30/1"), conform_fps=False)
        self.assertNotIn('-vf', job.steps[0].cmd)
        self.assertEqual(len(job.steps), 1)

    def test_bd_rates_never_conformed(self):
        for rate in ("24000/1001", "24/1", "25/1", "30000/1001", "50/1", "60000/1001"):
            s = src(rate=rate)
            job = jobs.build_2d_job(s, target_720p=bool(jobs.forced_720p(s.fps_str)))
            self.assertFalse(any("fps=" in a for a in job.steps[0].cmd), rate)
            self.assertEqual(len(job.steps), 1, rate)


class BuildAudio(unittest.TestCase):
    def cmd(self, selection):
        return jobs.build_audio_job(os.path.join("C:\\Ton", "Ton.wav"), selection).steps[0].cmd

    def test_stereo_bitrates(self):
        self.assertEqual(self.cmd("AC3 (Stereo, 192 kbps)"),
                         ['ffmpeg', '-y', '-i', 'Ton.wav', '-ar', '48000', '-c:a', 'ac3', '-b:a', '192k', 'Ton.ac3'])
        self.assertIn('320k', self.cmd("AC3 (Stereo, 320 kbps)"))
        self.assertEqual(self.cmd("DTS (Stereo, 768 kbps)")[6:], ['-c:a', 'dts', '-b:a', '768k', '-strict', '-2', 'Ton.dts'])

    def test_surround_formats(self):
        self.assertEqual(self.cmd("LPCM (5.1 Surround, Uncompressed)")[6:], ['-c:a', 'pcm_s24le', 'Ton_lpcm.wav'])
        self.assertEqual(self.cmd("LPCM (7.1 Surround, Uncompressed)")[6:], ['-c:a', 'pcm_s24le', 'Ton_lpcm.wav'])
        self.assertEqual(self.cmd("LPCM (Stereo, Uncompressed)")[6:], ['-c:a', 'pcm_s24le', 'Ton_lpcm.wav'])
        self.assertEqual(self.cmd("AC3 (Downmix auf 5.1, 640 kbps)")[6:], ['-c:a', 'ac3', '-b:a', '640k', '-ac', '6', 'Ton.ac3'])

    def test_track_from_video(self):
        film = os.path.join("C:\\Filme", "Film.mkv")
        ac3 = jobs.AudioTrack(index=1, codec="ac3", channels=6, sample_rate=48000, language="deu")
        options = jobs.audio_track_options(ac3)
        self.assertEqual(options[0], "AC3 1:1 übernehmen (unverändert / unchanged)")
        self.assertEqual(options[1:], jobs.audio_format_options(6))
        job = jobs.build_audio_job(film, options[0], 60.0, track=ac3)
        self.assertEqual(job.steps[0].cmd, ['ffmpeg', '-y', '-i', 'Film.mkv', '-map', '0:a:1', '-c:a', 'copy',
                                            'Film_ton2_deu.ac3'])
        self.assertEqual(job.outputs, [os.path.join("C:\\Filme", "Film_ton2_deu.ac3")])
        self.assertEqual(job.notes, [])
        # Umwandeln: Spur wählen, 48 kHz, Name mit Spurnummer (ohne Sprache, wenn keine bekannt)
        aac = jobs.AudioTrack(index=0, codec="aac", channels=2, sample_rate=44100)
        self.assertEqual(jobs.audio_track_options(aac), jobs.audio_format_options(2))
        cmd = jobs.build_audio_job(film, "AC3 (Stereo, 320 kbps)", track=aac, out_dir="D:\\Aus").steps[0].cmd
        self.assertEqual(cmd, ['ffmpeg', '-y', '-i', 'Film.mkv', '-map', '0:a:0', '-ar', '48000', '-c:a', 'ac3',
                               '-b:a', '320k', os.path.join("D:\\Aus", "Film_ton1.ac3")])

    def test_copy_only_when_bluray_ready(self):
        for codec, rate, ok in (("ac3", 48000, True), ("dts", 48000, True), ("ac3", 44100, False),
                                ("eac3", 48000, False), ("truehd", 48000, False), ("pcm_s24le", 48000, False)):
            track = jobs.AudioTrack(index=0, codec=codec, channels=6, sample_rate=rate)
            self.assertEqual("1:1" in jobs.audio_track_options(track)[0], ok, (codec, rate))
        with self.assertRaises(ValueError):
            jobs.build_audio_job("Ton.wav", "AC3 1:1 übernehmen (unverändert / unchanged)")

    def test_offset_warning(self):
        late = jobs.AudioTrack(index=0, codec="ac3", channels=2, sample_rate=48000, offset=0.120)
        notes = jobs.build_audio_job("Film.mp4", "AC3 (Stereo, 192 kbps)", track=late).notes
        self.assertEqual(len(notes), 1)
        self.assertIn("120 ms später", notes[0])
        small = jobs.AudioTrack(index=0, codec="ac3", channels=2, sample_rate=48000, offset=-0.010)
        self.assertEqual(jobs.build_audio_job("Film.mp4", "AC3 (Stereo, 192 kbps)", track=small).notes, [])

    def test_every_offered_format_builds(self):
        for ch in (1, 2, 6, 8):
            for sel in jobs.audio_format_options(ch):
                self.assertEqual(self.cmd(sel)[:6], ['ffmpeg', '-y', '-i', 'Ton.wav', '-ar', '48000'], sel)


class Build3D(unittest.TestCase):
    def test_stereo_filter(self):
        self.assertEqual(jobs.stereo_filter(1920, 2160),
                         "[0:v]crop=1920:1080:0:0[left];[0:v]crop=1920:1080:0:1080[right]")
        self.assertEqual(jobs.stereo_filter(3840, 1080),
                         "[0:v]crop=1920:1080:0:0[left];[0:v]crop=1920:1080:1920:0[right]")
        for size in ((1920, 1080), (3840, 2160), (1920, 2156), (1280, 1440)):
            with self.assertRaises(ValueError, msg=size):
                jobs.stereo_filter(*size)

    def test_only_full_tab_and_sbs(self):
        self.assertTrue(jobs.build_3d_job(src(3840, 1080)).steps)
        for size in ((1920, 1080), (3840, 2160)):
            self.assertEqual([c for c, _ in jobs.source_problems(src(*size), "3d")], ["layout_3d"])
            with self.assertRaises(ValueError):
                jobs.build_3d_job(src(*size))

    def test_adaptive_steps(self):
        job = jobs.build_3d_job(src(1920, 2160), 25000)
        kinds = ["cmd" if s.cmd else "py" for s in job.steps]
        self.assertEqual(kinds, ["cmd", "py", "cmd", "cmd", "py", "py"])
        scan, _, p1, p2 = job.steps[:4]
        opts = lambda c, i=0: [c[k + 1] for k, a in enumerate(c) if a == '-x264-params'][i]
        self.assertIn("scenecut=40", opts(scan.cmd))
        self.assertIn("min-keyint=1", opts(scan.cmd))
        for step in (p1, p2):
            # beide Augen identisch, IDR-Positionen erzwungen
            self.assertEqual(opts(step.cmd, 0), opts(step.cmd, 1))
            self.assertIn("scenecut=0", opts(step.cmd))
            self.assertEqual(step.cmd.count('-/force_key_frames'), 2)
            self.assertIn("vbv-maxrate=28000:vbv-bufsize=30000", opts(step.cmd))
            self.assertTrue(opts(step.cmd).endswith(":colorprim=bt709:transfer=bt709:colormatrix=bt709"))
            self.assertEqual(step.cmd.count('12500k'), 2)
        self.assertEqual([os.path.basename(p) for p in job.outputs], ["Mein Film_3D.264", "Mein Film_3D.mvc"])
        self.assertEqual(job.outputs, list(jobs.outputs_3d(src(1920, 2160))))

    def test_fixed_gop_fallback(self):
        job = jobs.build_3d_job(src(1920, 2160, "24/1"), 30000, adaptive=False)
        self.assertEqual(["cmd" if s.cmd else "py" for s in job.steps], ["cmd", "cmd", "py", "py"])
        p1 = job.steps[0].cmd
        self.assertNotIn('-/force_key_frames', p1)
        self.assertIn("keyint=24:min-keyint=24:scenecut=0", p1[p1.index('-x264-params') + 1])
        self.assertTrue(job.notes)

    def test_only_bd3d_rates(self):
        for rate in ("24000/1001", "24/1"):
            self.assertTrue(jobs.build_3d_job(src(1920, 2160, rate)).steps, rate)
        for rate in ("25/1", "30000/1001", "30/1", "50/1", "60000/1001", "60/1"):
            with self.assertRaises(ValueError, msg=rate):
                jobs.build_3d_job(src(1920, 2160, rate))

    def test_out_dir(self):
        job = jobs.build_3d_job(src(1920, 2160), out_dir="D:\\Ausgabe")
        self.assertEqual(job.outputs, [os.path.join("D:\\Ausgabe", "Mein Film_3D.264"),
                                       os.path.join("D:\\Ausgabe", "Mein Film_3D.mvc")])
        self.assertEqual(job.cwd, "C:\\Filme")      # ffmpeg liest die Quelle relativ zum Quellordner


class SourceChecks(unittest.TestCase):
    def codes(self, mode="2d", **kw):
        return [code for code, _ in jobs.source_problems(src(**kw), mode)]

    def test_bluray_sources_pass(self):
        for rate in ("24000/1001", "24/1", "25/1", "30000/1001", "30/1", "50/1", "60000/1001", "60/1"):
            self.assertEqual(self.codes(rate=rate, field_order="progressive", color_transfer="bt709"), [], rate)
        self.assertEqual(self.codes("3d", w=1920, h=2160), [])
        self.assertEqual(self.codes("3d", w=3840, h=1080, rate="24/1"), [])

    def test_unusual_frame_rates(self):
        # z. B. variable Bildrate vom Handy (Mittelwert 29,87) oder Zeitraffer
        for rate in ("2987/100", "15/1", "25/2", "48/1", "120/1"):
            self.assertEqual(self.codes(rate=rate), ["fps"], rate)
        self.assertEqual(self.codes("3d", w=1920, h=2160, rate="25/1"), ["fps_3d"])

    def test_hdr(self):
        self.assertEqual(self.codes(color_transfer="smpte2084"), ["hdr"])
        self.assertEqual(self.codes(color_transfer="arib-std-b67"), ["hdr"])
        self.assertEqual(self.codes(color_primaries="bt2020"), ["hdr"])
        self.assertEqual(self.codes("3d", w=1920, h=2160, dolby_vision=True), ["hdr"])
        self.assertIn("HLG", jobs.describe_problems(jobs.source_problems(src(color_transfer="arib-std-b67"), "2d")))
        with self.assertRaises(ValueError):
            jobs.build_2d_job(src(color_transfer="smpte2084"))

    def test_interlaced(self):
        for order in ("tt", "bb", "tb", "bt"):
            self.assertEqual(self.codes(field_order=order), ["interlaced"], order)
        self.assertEqual(self.codes(field_order="unknown"), [])
        with self.assertRaises(ValueError):
            jobs.build_3d_job(src(1920, 2160, field_order="tt"))


class Tools(unittest.TestCase):
    def tearDown(self):
        jobs.configure_tools(None)

    def test_resolver_used_for_commands(self):
        paths = {"ffmpeg": os.path.join("C:\\OpenBDAuth", "tools", "ffmpeg.exe")}
        jobs.configure_tools(paths.get)
        self.assertEqual(jobs.tool("ffprobe"), "ffprobe")      # nicht gefunden -> PATH
        for job in (jobs.build_2d_job(src()), jobs.build_3d_job(src(1920, 2160)),
                    jobs.build_audio_job("Ton.wav", "AC3 (Stereo, 192 kbps)")):
            self.assertTrue(all(s.cmd[0] == paths["ffmpeg"] for s in job.steps if s.cmd), job.kind)


class FreeSpace(unittest.TestCase):
    def test_3d_estimate_includes_temp_files(self):
        job = jobs.build_3d_job(src(1920, 2160), 25000)
        self.assertGreater(job.space_needed, 60 * 25e6 / 8 * 1.5)
        job.outputs = [os.path.join(tempfile.gettempdir(), "x_3D.264")]
        self.assertIsNone(jobs.free_space_shortfall(job))
        job.space_needed = 10 ** 18
        need, free = jobs.free_space_shortfall(job)
        self.assertEqual(need, 10 ** 18)
        self.assertLess(free, need)


class Keyframes(unittest.TestCase):
    def write(self, text):
        fd, path = tempfile.mkstemp(suffix=".log")
        with os.fdopen(fd, "w") as f:
            f.write(text)
        self.addCleanup(os.remove, path)
        return path

    def test_reads_idr_positions(self):
        path = self.write("#options: x\nin:0 out:0 type:I dur:2\nin:4 out:1 type:P\nin:1 out:2 type:b\n"
                          "in:30 out:30 type:I\nin:7 out:5 type:I\n")
        self.assertEqual(jobs.read_x264_keyframes(path), [0, 7, 30])

    def test_non_idr_i_is_rejected(self):
        self.assertIsNone(jobs.read_x264_keyframes(self.write("in:0 out:0 type:I\nin:9 out:9 type:i\n")))

    def test_missing_or_empty(self):
        self.assertIsNone(jobs.read_x264_keyframes(self.write("#options\n")))
        self.assertIsNone(jobs.read_x264_keyframes(os.path.join(tempfile.gettempdir(), "gibt-es-nicht.log")))

    def test_ffmpeg_version(self):
        self.assertEqual(jobs.ffmpeg_major_version("ffmpeg version 8.1-essentials_build-www.gyan.dev"), 8)
        self.assertEqual(jobs.ffmpeg_major_version("ffmpeg version n6.1.1 Copyright"), 6)
        self.assertIsNone(jobs.ffmpeg_major_version("ffmpeg version N-118000-gabc Copyright"))


class RunJob(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.out = os.path.join(self.dir, "out.264")
        self.tmp = os.path.join(self.dir, "x.tmp")
        self.prefix = os.path.join(self.dir, "pass[1]")      # Sonderzeichen: Präfix wird escaped
        for f in (self.tmp, self.prefix + "-0.log", self.prefix + "-0.log.mbtree"):
            open(f, "w").close()

    def tearDown(self):
        for f in os.listdir(self.dir):
            os.remove(os.path.join(self.dir, f))
        os.rmdir(self.dir)

    def job(self, *funcs):
        steps = [jobs.Step(f"Schritt {i}", func=f) for i, f in enumerate(funcs)]
        return jobs.Job("test", self.dir, 1.0, steps, outputs=[self.out], temp=[self.tmp], temp_prefixes=[self.prefix])

    def write_out(self, ctx):
        open(self.out, "w").close()
        ctx.progress(1.0)
        return 0

    def test_success_keeps_outputs_and_removes_temp(self):
        seen = []
        ret = jobs.run_job(self.job(self.write_out), log=lambda *a, **k: None, progress=seen.append)
        self.assertEqual(ret, 0)
        self.assertEqual(os.listdir(self.dir), ["out.264"])
        self.assertEqual(seen, [0.0, 1.0])

    def test_failure_stops(self):
        calls = []
        ret = jobs.run_job(self.job(lambda ctx: 3, lambda ctx: calls.append(1) or 0), log=lambda *a, **k: None)
        self.assertEqual(ret, 3)
        self.assertEqual(calls, [])
        self.assertFalse(os.path.exists(self.tmp))

    def test_cancel_removes_outputs(self):
        state = {"cancel": False}

        def write_and_cancel(ctx):
            self.write_out(ctx)
            state["cancel"] = True
            return 0
        ret = jobs.run_job(self.job(write_and_cancel, self.write_out), log=lambda *a, **k: None,
                           cancelled=lambda: state["cancel"])
        self.assertEqual(ret, jobs.CANCELLED)
        self.assertEqual(os.listdir(self.dir), [])

    def test_commands_go_through_run_cmd(self):
        job = jobs.Job("test", self.dir, 1.0, [jobs.Step("a", cmd=["ffmpeg", "-version"])], outputs=[])
        seen = []
        ret = jobs.run_job(job, run_cmd=lambda step, j: seen.append(step.cmd) or 0, log=lambda *a, **k: None)
        self.assertEqual((ret, seen), (0, [["ffmpeg", "-version"]]))


if __name__ == "__main__":
    unittest.main()
