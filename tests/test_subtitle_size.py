# tests/test_subtitle_size.py
"""
Untertitel in der Größe des Films (v1.40.1, Plan docs/plaene/untertitel-aufloesung.md).

- SRT → SUP rendert in der Untertitel-Fläche des Films (bis v1.40.0 immer 1920×1080) und mit dessen Bildrate (bis
  v1.40.0 die des ersten Films). Größen wie tsMuxeR: 1440×1080 → 1920×1080, SD nach der Höhe.
- Fertige .sup in anderer Größe als das Video: Warnung im Preflight (Anlass: Trailer 720p mit .sup in 1920×1080).
"""

import os
import shutil
import struct
import tempfile
import unittest

from core.disc_edit import starter_project
from core.disc_model import Track
from core.meta_builder import MetaBuilder
from core.preflight import run_preflight, WARNING
from core.project_state import MediaTitle, ProjectState
from modules.subtitles.srt_to_sup import (
    convert_srt_to_sup, pgs_canvas, pgs_squeeze, read_sup_size, build_sup_cue_bytes,
)

SRT = "1\n00:00:01,000 --> 00:00:03,000\nHallo Welt\n\n2\n00:00:04,000 --> 00:00:06,000\nZweite Zeile\n"
LONG = "Eine sehr lange Untertitelzeile, die auf einer kleinen Fläche niemals in voller Größe Platz hätte"


def segments(data: bytes):
    """(Typ, Nutzdaten) aller Segmente einer .sup."""
    out, pos = [], 0
    while pos + 13 <= len(data) and data[pos:pos + 2] == b"PG":
        seg_type = data[pos + 10]
        length = struct.unpack(">H", data[pos + 11:pos + 13])[0]
        out.append((seg_type, data[pos + 13:pos + 13 + length]))
        pos += 13 + length
    return out


def first_cue(data: bytes) -> dict:
    """PCS-Größe, Bildrate, Position und Bildgröße der ersten Einblendung."""
    segs = segments(data)
    pcs = next(p for t, p in segs if t == 0x16)
    ods = next(p for t, p in segs if t == 0x15)
    w, h, rate = struct.unpack(">HHB", pcs[:5])
    x, y = struct.unpack(">HH", pcs[15:19])
    img_w, img_h = struct.unpack(">HH", ods[7:11])
    return {"canvas": (w, h), "rate": rate, "pos": (x, y), "img": (img_w, img_h)}


class TestCanvas(unittest.TestCase):
    def test_sizes_like_tsmuxer(self):
        self.assertEqual(pgs_canvas(1920, 1080), (1920, 1080))
        self.assertEqual(pgs_canvas(1440, 1080), (1920, 1080))     # anamorph: volle Fläche
        self.assertEqual(pgs_canvas(1280, 720), (1280, 720))
        self.assertEqual(pgs_canvas(720, 576), (720, 576))         # nach der Höhe, nicht nach der Bildrate
        self.assertEqual(pgs_canvas(720, 480), (720, 480))
        self.assertEqual(pgs_canvas(0, 0), (1920, 1080))           # unbekannt: wie bis v1.40.0

    def test_squeeze_only_for_sd(self):
        self.assertAlmostEqual(pgs_squeeze(720, 576, "64:45"), 45 / 64)
        self.assertAlmostEqual(pgs_squeeze(720, 480, "32:27"), 27 / 32)
        self.assertAlmostEqual(pgs_squeeze(720, 576, "16:15"), 15 / 16)
        self.assertEqual(pgs_squeeze(1440, 1080, "4:3"), 1.0)      # Fläche 1920×1080, nicht gestaucht
        self.assertEqual(pgs_squeeze(1920, 1080, "1:1"), 1.0)
        self.assertEqual(pgs_squeeze(720, 576, None), 1.0)
        self.assertEqual(pgs_squeeze(720, 576, "0:1"), 1.0)


class TestConvert(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="obda_subsize_")
        self.srt = os.path.join(self.tmp, "film.srt")
        with open(self.srt, "w", encoding="utf-8") as f:
            f.write(SRT)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def convert(self, **kwargs) -> dict:
        sup = os.path.join(self.tmp, "out.sup")
        convert_srt_to_sup(self.srt, sup, **kwargs)
        with open(sup, "rb") as f:
            return first_cue(f.read())

    def test_without_size_like_before(self):
        cue = self.convert(fps=23.976)
        self.assertEqual(cue["canvas"], (1920, 1080))
        self.assertEqual(cue["rate"], 0x10)

    def test_each_format(self):
        heights = {}
        for size, canvas in (((1920, 1080), (1920, 1080)), ((1440, 1080), (1920, 1080)), ((1280, 720), (1280, 720)),
                             ((720, 576), (720, 576)), ((720, 480), (720, 480))):
            with self.subTest(size=size):
                cue = self.convert(video_size=size)
                self.assertEqual(cue["canvas"], canvas)
                x, y = cue["pos"]
                w, h = cue["img"]
                self.assertLessEqual(x + w, canvas[0])                  # ganz im Bild
                self.assertLessEqual(y + h, canvas[1])
                self.assertAlmostEqual(x + w / 2, canvas[0] / 2, delta=2)   # waagerecht zentriert
                margin = canvas[1] - y - h
                self.assertAlmostEqual(margin, 70 * canvas[1] / 1080, delta=2)
                heights[canvas[1]] = h
        # Schrift mit der Höhe skaliert: Bildhöhe ungefähr proportional (der transparente Rand von 8 px um den Text
        # ist fest, bei kleinen Flächen wiegt er mehr)
        self.assertAlmostEqual(heights[720] / heights[1080], 720 / 1080, delta=0.08)
        self.assertAlmostEqual(heights[480] / heights[1080], 480 / 1080, delta=0.12)
        self.assertLess(heights[480], heights[576])
        self.assertLess(heights[576], heights[720])

    def test_sd_16_9_squeezed(self):
        plain = self.convert(video_size=(720, 576), sar="16:15")
        wide = self.convert(video_size=(720, 576), sar="64:45")
        self.assertEqual(plain["img"][1], wide["img"][1])                # Höhe gleich
        self.assertAlmostEqual(wide["img"][0] / plain["img"][0], (45 / 64) / (15 / 16), delta=0.05)

    def test_frame_rate_byte(self):
        self.assertEqual(self.convert(fps=29.97, video_size=(1280, 720))["rate"], 0x40)
        self.assertEqual(self.convert(fps=59.94, video_size=(1280, 720))["rate"], 0x70)

    def test_long_line_fits(self):
        """Zu lange Zeilen werden kleiner gerendert; ein Bild breiter als die Fläche verwirft der Player."""
        cue = first_cue(build_sup_cue_bytes(LONG, 1.0, 2.0, font_size=23, bottom_margin=31, canvas=(720, 480),
                                            outline_size=1))
        self.assertLessEqual(cue["img"][0], 720 * 0.9 + 8)
        self.assertGreaterEqual(cue["pos"][0], 0)


class TestMetaBuilder(unittest.TestCase):
    """Die SRT eines zweiten Films wird in dessen Größe und Bildrate gewandelt, nicht in der des ersten."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="obda_subsize_meta_")
        self.srt = os.path.join(self.tmp, "trailer.srt")
        with open(self.srt, "w", encoding="utf-8") as f:
            f.write(SRT)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_second_title(self):
        state = ProjectState()
        main = state.titles[0]
        main.video_base, main.fps = os.path.join(self.tmp, "film.264"), 24.0
        main.video_details = {"width": 1920, "height": 1080, "is_interlaced": False}
        trailer = MediaTitle(name="Trailer", is_main=False)
        trailer.video_base, trailer.fps = os.path.join(self.tmp, "trailer.264"), 59.94
        trailer.video_details = {"width": 1280, "height": 720, "sar": "1:1", "is_interlaced": False}
        trailer.subtitle_tracks = [{"path": self.srt, "lang": "por"}]
        state.titles.append(trailer)

        out_dir = os.path.join(self.tmp, "sup")
        os.makedirs(out_dir)
        content = MetaBuilder(state).generate_title_meta_content(trailer, sup_dir=out_dir)
        self.assertIn("S_HDMV/PGS", content)
        sup = os.path.join(out_dir, "trailer_por.sup")
        with open(sup, "rb") as f:
            cue = first_cue(f.read())
        self.assertEqual(cue["canvas"], (1280, 720))
        self.assertEqual(cue["rate"], 0x70)                              # 59,94 des Trailers, nicht 24


class TestPreflight(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="obda_subsize_pf_")
        self.project = starter_project("de")
        self.film = self.project.films[0]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sup(self, name, size):
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as f:
            f.write(build_sup_cue_bytes("Text", 1.0, 2.0, canvas=size))
        return path

    def issues(self):
        return [i for i in run_preflight(self.project) if i.level == WARNING and ".sup" in i.message]

    def test_wrong_size_warns(self):
        """Der Fall aus der Meldung: 720p-Video, .sup in 1920×1080."""
        self.film.video_details = {"width": 1280, "height": 720}
        self.film.subtitle_tracks = [Track(id="t1", path=self.sup("por.sup", (1920, 1080)), lang="por")]
        issues = self.issues()
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].node_id, self.film.id)
        self.assertIn("1920×1080", issues[0].message)
        self.assertIn("1280×720", issues[0].message)

    def test_matching_sizes_are_fine(self):
        for video, sub in (((1280, 720), (1280, 720)), ((1440, 1080), (1920, 1080)), ((720, 576), (720, 576))):
            with self.subTest(video=video):
                self.film.video_details = {"width": video[0], "height": video[1]}
                self.film.subtitle_tracks = [Track(id="t1", path=self.sup("ok.sup", sub), lang="deu")]
                self.assertEqual(self.issues(), [])

    def test_unreadable_or_unknown_is_quiet(self):
        broken = os.path.join(self.tmp, "kaputt.sup")
        with open(broken, "wb") as f:
            f.write(b"kein PGS")
        self.assertIsNone(read_sup_size(broken))
        self.film.video_details = {"width": 1280, "height": 720}
        self.film.subtitle_tracks = [Track(id="t1", path=broken, lang="deu")]
        self.assertEqual(self.issues(), [])
        self.film.video_details = None                                  # Video noch nicht analysiert
        self.film.subtitle_tracks = [Track(id="t1", path=self.sup("x.sup", (1920, 1080)), lang="deu")]
        self.assertEqual(self.issues(), [])


if __name__ == "__main__":
    unittest.main()
