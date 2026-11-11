# tests/test_sim_disc.py
"""
Simulation direkt aus dem Projekt (v1.10.0, modules/sim_disc.py): Simulations-Disc ohne tsMuxeR und
ffmpeg, Platzhalter für Film-Playlists und Menü-Hintergrund, Durchlauf im Simulator.
Die Gegenprobe gegen einen echten Export steht in tests/test_e2e_export.py.
"""

import os
import subprocess
import tempfile
import unittest
from unittest import mock

from core.disc_adapter import DiscExportError
from core.disc_edit import starter_project, add_film, add_nav_button, add_track, set_chapter_times, \
    TRACK_AUDIO, TRACK_SUBTITLE
from core.menu_templates import create_chapter_menus, create_language_menus
from modules.bdsim.disc import load_disc, read_playlist
from modules.bdsim.explore import explore, format_report
from modules.bdsim.hdmv import PSR_PRIMARY_AUDIO, PSR_PG_STREAM
from modules.bdsim.player import Player, STATE_FILM
from modules.menu_author import get_clpi_stc_range
from modules.sim_disc import (
    build_simulation_disc, build_film_mpls, placeholder_background, NoMenuError, PTS_START_45K,
)


def make_project(chapters=3, audio=("deu", "eng"), subs=("eng",)):
    project = starter_project()
    film = project.films[0]
    film.video_base = "film.264"            # wird für die Simulation nie gelesen
    set_chapter_times(film, [f"00:00:{4 * i:02d}.000" for i in range(chapters)])
    for lang in audio:
        add_track(film, TRACK_AUDIO, f"ton_{lang}.ac3", lang)
    for lang in subs:
        add_track(film, TRACK_SUBTITLE, f"ut_{lang}.sup", lang)
    return project, film


class SimDiscTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def simulate(self, project):
        sim = build_simulation_disc(project, os.path.join(self.tmp.name, "SIM"))
        return sim, load_disc(sim.root)

    def assert_clean(self, disc):
        for tv_3d in (True, False):
            report = explore(disc, tv_3d=tv_3d)
            self.assertTrue(report.ok, format_report(disc, [report]))
            self.assertEqual([f.code for f in report.findings if f.level == "warnung"], [])


class TestSimulationDisc(SimDiscTestCase):
    def test_starter_project(self):
        project, _ = make_project(chapters=0, audio=(), subs=())
        sim, disc = self.simulate(project)
        self.assertEqual(disc.read_problems, [])
        self.assertEqual(sorted(disc.playlists), [0, 1])        # Menü, Hauptfilm
        self.assertIn(0, disc.compositions)
        self.assert_clean(disc)

    def test_disc_a_chapters_and_languages(self):
        """Disc A: Kapitelmenü über zwei Seiten, Ton & Untertitel. Jeder Kapitel-Button startet an
        seiner Marke, die Spurwahl gilt beim Filmstart."""
        project, film = make_project()
        pages = create_chapter_menus(project, film.id, per_page=2)
        (language,) = create_language_menus(project, film.id)
        _, disc = self.simulate(project)
        self.assert_clean(disc)

        film_pl = disc.playlists[1]
        self.assertEqual((film_pl.count("audio"), film_pl.count("pg")), (2, 1))
        self.assertEqual([m.time - film_pl.items[0].in_time for m in film_pl.marks], [0, 180000, 360000])

        from core.disc_adapter import build_export_plan
        plan = build_export_plan(project)
        chapter_starts = set()
        for page in (plan.page_ids[p.id] for p in pages):
            for button in disc.compositions[0].page(page).buttons():
                p = Player(disc)
                p.insert_disc()
                p._select_page(page)
                p.activate_button(button.button_id)
                if p.state == STATE_FILM and p.start_mark is not None:
                    chapter_starts.add((p.playlist_id, p.start_mark))
        self.assertEqual(chapter_starts, {(1, 0), (1, 1), (1, 2)})

        # Ton 2 und Untertitel 1 wählen, dann „FILM STARTEN“ (Buttons: Ton 1, Ton 2, UT 1, AUS, ZURÜCK, FILM)
        p = Player(disc)
        p.insert_disc()
        p._select_page(plan.page_ids[language.id])
        for button_id in (2, 3, 6):
            p.activate_button(button_id)
        self.assertEqual(p.state, STATE_FILM)
        self.assertEqual(p.regs.psr[PSR_PRIMARY_AUDIO], 2)
        self.assertEqual(p.regs.psr[PSR_PG_STREAM], 0x80000001)

    def test_3d_film(self):
        """Disc B: 3D-Hauptfilm – Playlist mit 3D-Erweiterung, Clip-Nummern wie nach dem 3D-Muxen."""
        project, film = make_project(chapters=3, audio=("deu",), subs=())
        film.video_mvc = "film.mvc"
        create_chapter_menus(project, film.id)
        _, disc = self.simulate(project)
        self.assertTrue(disc.playlists[1].is_3d)
        self.assertFalse(disc.playlists[0].is_3d)
        self.assertTrue(disc.index.has_3d_content)
        self.assertEqual(disc.playlists[0].items[0].clip, "00002")      # Menü hinter Basis- und MVC-Clip
        self.assert_clean(disc)
        p = Player(disc, tv_3d=True)
        p.insert_disc()
        p.activate_button(1)                                            # FILM STARTEN
        self.assertEqual(p.state, STATE_FILM)
        self.assertTrue(p.output_3d)

    def test_several_films(self):
        project, film = make_project(chapters=0, audio=("deu",), subs=())
        main = project.main_menu
        for name in ("Bonus", "Trailer"):
            extra = add_film(project, name, (0.0, 0.0))
            extra.video_base = f"{name}.264"
            add_nav_button(project, main.id, name.upper(), extra.id)
        _, disc = self.simulate(project)
        self.assertEqual(sorted(disc.playlists), [0, 1, 2, 3])
        self.assertEqual([disc.playlists[i].items[0].clip for i in (1, 2, 3)], ["00000", "00003", "00004"])
        self.assert_clean(disc)
        report = explore(disc, tv_3d=False)
        self.assertEqual(report.titles_reached | {1}, {1, 2, 3})

    def test_disc_without_menu(self):
        project, film = make_project()
        project.start_target = film.id          # Start → Film: Disc ohne Hauptmenü
        self.assertIsNone(project.main_menu)
        with self.assertRaises(NoMenuError):
            build_simulation_disc(project, os.path.join(self.tmp.name, "SIM"))

    def test_export_problems_are_reported(self):
        project, film = make_project()
        film.video_base = None
        with self.assertRaises(DiscExportError):
            build_simulation_disc(project, os.path.join(self.tmp.name, "SIM"))

    def test_runs_without_external_tools(self):
        """Weder tsMuxeR noch ffmpeg/ffprobe: kein Prozess wird gestartet."""
        project, film = make_project()
        create_chapter_menus(project, film.id)
        with mock.patch.object(subprocess, "run", side_effect=AssertionError("Prozess gestartet")), \
                mock.patch.object(subprocess, "Popen", side_effect=AssertionError("Prozess gestartet")):
            _, disc = self.simulate(project)
        self.assert_clean(disc)

    def test_menu_background_image(self):
        project, _ = make_project(chapters=0)
        image = os.path.join(self.tmp.name, "bg.png")
        from PIL import Image
        Image.new("RGB", (1920, 1080), "navy").save(image)
        project.main_menu.background.image = image
        sim, _ = self.simulate(project)
        self.assertEqual(sim.menu_background, image)
        root = sim.root
        sim.cleanup()
        self.assertFalse(os.path.exists(root))


class TestPlaceholders(SimDiscTestCase):
    def test_film_playlist_like_tsmuxer(self):
        path = os.path.join(self.tmp.name, "00001.mpls")
        with open(path, "wb") as f:
            f.write(build_film_mpls("00000", 12.0, 23.976, [(0x81, "deu"), (0x84, "eng")], ["eng", "deu"],
                                    [0.0, 4.0, 8.0]))
        pl = read_playlist(path, 1)
        item = pl.items[0]
        self.assertEqual((item.clip, item.in_time), ("00000", PTS_START_45K))
        self.assertAlmostEqual(pl.duration_sec, 12.0, places=3)
        self.assertEqual([(s.kind, s.pid, s.lang) for s in item.streams],
                         [("video", 0x1011, ""), ("audio", 0x1100, "deu"), ("audio", 0x1101, "eng"),
                          ("pg", 0x1200, "eng"), ("pg", 0x1201, "deu")])
        self.assertEqual([m.time - item.in_time for m in pl.marks], [0, 180000, 360000])
        self.assertEqual(pl.chapter_marks, [0, 1, 2])
        self.assertFalse(pl.is_3d)

    def test_film_playlist_3d(self):
        path = os.path.join(self.tmp.name, "00001.mpls")
        with open(path, "wb") as f:
            f.write(build_film_mpls("00000", 12.0, 23.976, [], [], [0.0], is_3d=True))
        self.assertTrue(read_playlist(path, 1).is_3d)

    def test_background_duration_in_whole_frames(self):
        """Wie ffmpeg/tsMuxeR: 10 s bei 23,976 fps sind 240 Bilder = 450450 Takte (gemessen am echten Export)."""
        for fps, seconds, ticks in ((23.976, 10.0, 450450), (24.0, 7.3, 330000), (25.0, 30.0, 1350000)):
            m2ts, clpi = (os.path.join(self.tmp.name, n) for n in ("bg.m2ts", "bg.clpi"))
            placeholder_background(None, m2ts, clpi, duration_sec=seconds, fps=fps)
            start, end = get_clpi_stc_range(clpi)
            self.assertEqual((start, end - start), (PTS_START_45K, ticks))


if __name__ == "__main__":
    unittest.main()
