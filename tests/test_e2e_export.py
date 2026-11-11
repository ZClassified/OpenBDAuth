# tests/test_e2e_export.py
"""
Ende-zu-Ende-Test des Exports mit echtem tsMuxeR und ffmpeg: Projekte aus dem Node-Graphen werden über den
Export-Adapter exportiert und im Disc-Simulator durchgespielt; die Simulations-Disc ohne tsMuxeR entspricht
dem echten Export. (Bis v1.11 zusätzlich: byte-gleich zum Weg der früheren Oberfläche; entfällt mit den
freien Buttons in v1.12.)

Wird übersprungen, wenn tsMuxeR oder ffmpeg nicht verfügbar sind.
"""

import copy
import filecmp
import os
import subprocess
import tempfile
import unittest

from core.disc_adapter import build_export_plan
from core.disc_edit import starter_project, add_film, add_nav_button
from core.disc_model import Chapter, Track
from core import menu_templates
from modules.external_tools import find_tool, FFMPEG
from modules.mux_engine import find_tsmuxer

# Wie das Programm: mitgeliefertes ffmpeg (tools/<plattform>/), sonst PATH
FFMPEG_PATH = find_tool(FFMPEG)


def _tools_available() -> bool:
    return bool(find_tsmuxer()) and FFMPEG_PATH is not None


def _ff(*args):
    subprocess.run([FFMPEG_PATH, "-loglevel", "error", "-y", *args], check=True)


@unittest.skipUnless(_tools_available(), "tsMuxeR und ffmpeg werden für den Ende-zu-Ende-Test benötigt")
class TestEndToEndExport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        work = cls.tmp.name
        main_264, bonus_264 = os.path.join(work, "main.264"), os.path.join(work, "bonus.264")
        for path, seconds, pattern in ((main_264, 12, "testsrc2"), (bonus_264, 6, "smptebars")):
            _ff("-f", "lavfi", "-i", f"{pattern}=size=1920x1080:rate=24000/1001", "-t", str(seconds),
                "-c:v", "libx264", "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p",
                "-x264-params", "keyint=24:min-keyint=1:bframes=0", "-bsf:v", "h264_mp4toannexb", "-f", "h264", path)
        audio = []
        for lang, freq in (("deu", 440), ("eng", 660)):
            path = os.path.join(work, f"ton_{lang}.ac3")
            _ff("-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=48000", "-t", "12", "-ac", "2",
                "-c:a", "ac3", "-b:a", "192k", path)
            audio.append(Track(id=f"a_{lang}", path=path, lang=lang))
        srt = os.path.join(work, "untertitel_eng.srt")
        with open(srt, "w", encoding="utf-8") as f:
            f.write("1\n00:00:01,000 --> 00:00:03,000\nHello\n\n2\n00:00:05,000 --> 00:00:07,000\nWorld\n")

        # Start → Hauptmenü („FILM STARTEN“ → Hauptfilm, „BONUS“ → Bonus), Menü-Schleife 10 s
        graph = starter_project()
        graph.settings.project_name = "E2E_TEST"
        graph.settings.export_format = "folder"
        main = graph.main_menu
        main.background.duration = 10.0
        film = graph.films[0]
        film.name = "Hauptfilm"
        film.video_base = main_264
        film.fps = 23.976
        film.audio_tracks = audio
        film.subtitle_tracks = [Track(id="s_eng", path=srt, lang="eng")]
        film.chapters = [Chapter(id=f"ch{i}", time=t)
                         for i, t in enumerate(["00:00:00.000", "00:00:04.000", "00:00:08.000"])]
        bonus = add_film(graph, "Bonus", (720.0, 200.0))
        bonus.video_base = bonus_264
        bonus.fps = 23.976
        add_nav_button(graph, main.id, "BONUS", bonus.id)
        cls.base = graph

    def _graph(self, menus: bool = True):
        """Kopie des Grundprojekts; mit menus ein Kapitel- und ein Sprachmenü aus den Vorlagen."""
        graph = copy.deepcopy(self.base)
        if menus:
            film = graph.films[0]
            menu_templates.create_chapter_menus(graph, film.id)
            menu_templates.create_language_menus(graph, film.id)
        return graph

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_simulated_navigation(self):
        """Der Disc-Simulator spielt die exportierte Disc durch: keine Fehler oder Warnungen, alle Titel und Kapitel erreichbar."""
        from modules.disc_export import export_disc
        from modules.bdsim.disc import load_disc
        from modules.bdsim.explore import explore, format_report
        from modules.bdsim.player import Player, STATE_FILM
        root = os.path.join(self.tmp.name, "SIM")
        os.makedirs(root)
        graph = self._graph()
        graph.settings.output_path = root
        plan = build_export_plan(graph)
        ready = []
        ok, msg = export_disc(plan.project_state, lambda m: None, lambda p: None, plan.pages_specs,
                              on_disc_ready=ready.append)
        self.assertTrue(ok, msg)
        self.assertEqual(ready, [root])

        disc = load_disc(root)
        for tv_3d in (True, False):
            report = explore(disc, tv_3d=tv_3d)
            self.assertTrue(report.ok, format_report(disc, [report]))
            self.assertEqual(report.titles_reached | {1}, {1, 2})

        # Jeder Kapitel-Button startet den Hauptfilm an seiner eigenen Marke
        chapter_starts = set()
        for page in disc.compositions[0].pages:
            for button in page.buttons():
                p = Player(disc)
                p.insert_disc()
                p._select_page(page.page_id)
                p.activate_button(button.button_id)
                if p.state == STATE_FILM and p.start_mark is not None:
                    chapter_starts.add((p.playlist_id, p.start_mark))
        self.assertEqual(chapter_starts, {(1, 0), (1, 1), (1, 2)})

    def test_template_menus(self):
        """v1.9.0: Kapitel- und Sprachmenü aus Vorlagen. Simulator ohne Fehler und Warnungen, Blättern,
        jeder Kapitel-Button startet an seiner Marke, die Spurwahl gilt beim Filmstart."""
        from modules.disc_export import export_disc
        from modules.bdsim.disc import load_disc
        from modules.bdsim.explore import explore, format_report
        from modules.bdsim.hdmv import PSR_PRIMARY_AUDIO, PSR_PG_STREAM
        from modules.bdsim.player import Player, STATE_FILM
        from core.menu_templates import create_chapter_menus, create_language_menus

        graph = self._graph(menus=False)
        film = graph.films[0]
        pages = create_chapter_menus(graph, film.id, per_page=2)   # 3 Kapitel -> 2 Seiten
        (language,) = create_language_menus(graph, film.id)
        root = os.path.join(self.tmp.name, "TEMPLATES")
        os.makedirs(root)
        graph.settings.output_path = root
        plan = build_export_plan(graph)
        ok, msg = export_disc(plan.project_state, lambda m: None, lambda p: None, plan.pages_specs)
        self.assertTrue(ok, msg)

        disc = load_disc(root)
        for tv_3d in (True, False):
            report = explore(disc, tv_3d=tv_3d)
            self.assertTrue(report.ok, format_report(disc, [report]))
            self.assertEqual([f.code for f in report.findings if f.level == "warnung"], [])

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

    def test_moved_buttons(self):
        """v1.9.3/v1.12: Buttons verschoben – Pfeiltasten aus der Lage, Simulator ohne Warnungen."""
        from modules.disc_export import export_disc
        from modules.bdsim.disc import load_disc
        from modules.bdsim.explore import explore, format_report
        from core.menu_templates import create_chapter_menus, create_language_menus
        from core.menu_design import move_items

        graph = self._graph(menus=False)
        film = graph.films[0]
        (chapters,) = create_chapter_menus(graph, film.id)
        (language,) = create_language_menus(graph, film.id)
        move_items(graph, chapters.id, positions={b.id: (b.position[0] - 100, b.position[1] - 250)
                                                  for b in chapters.buttons if b.is_content})
        move_items(graph, language.id, positions={language.buttons[-1].id: (1500, 80)})   # FILM STARTEN oben rechts
        move_items(graph, graph.main_menu.id, positions={graph.main_menu.buttons[0].id: (120, 120)})
        from core.menu_design import set_dpad
        set_dpad(graph, language.id, language.buttons[0].id, "left", language.buttons[-1].id)   # v1.9.5
        root = os.path.join(self.tmp.name, "MOVED")
        os.makedirs(root)
        graph.settings.output_path = root
        plan = build_export_plan(graph)
        ok, msg = export_disc(plan.project_state, lambda m: None, lambda p: None, plan.pages_specs)
        self.assertTrue(ok, msg)
        disc = load_disc(root)
        page = disc.compositions[0].page(plan.page_ids[language.id])
        self.assertEqual((page.button(len(language.buttons)).x, page.button(len(language.buttons)).y), (1500, 80))
        self.assertEqual(page.button(1).left, len(language.buttons))   # überschriebene Pfeiltaste im IG-Strom
        for tv_3d in (True, False):
            report = explore(disc, tv_3d=tv_3d)
            self.assertTrue(report.ok, format_report(disc, [report]))
            self.assertEqual([f.code for f in report.findings if f.level == "warnung"], [])

    def test_simulation_matches_export(self):
        """v1.10.0: Die Simulations-Disc aus dem Projekt (ohne tsMuxeR) entspricht dem echten Export:
        Navigation byte-gleich, Menüstrom und Menü-Playlist byte-gleich, Film-Playlists mit denselben
        Marken und Spuren, derselbe Simulator-Befund."""
        from modules.disc_export import export_disc
        from modules.sim_disc import build_simulation_disc
        from modules.bdsim.disc import load_disc
        from modules.bdsim.explore import explore
        from core.menu_templates import create_chapter_menus, create_language_menus

        graph = self._graph(menus=False)
        film = graph.films[0]
        create_chapter_menus(graph, film.id, per_page=2)
        create_language_menus(graph, film.id)

        real = os.path.join(self.tmp.name, "SIMCMP_REAL")
        os.makedirs(real)
        exported = copy.deepcopy(graph)
        exported.settings.output_path = real
        plan = build_export_plan(exported)
        ok, msg = export_disc(plan.project_state, lambda m: None, lambda p: None, plan.pages_specs)
        self.assertTrue(ok, msg)
        sim = build_simulation_disc(copy.deepcopy(graph), os.path.join(self.tmp.name, "SIMCMP_SIM"))

        same = lambda rel: filecmp.cmp(os.path.join(real, "BDMV", rel), os.path.join(sim.root, "BDMV", rel),
                                       shallow=False)
        for rel in ("index.bdmv", "MovieObject.bdmv", os.path.join("PLAYLIST", "00000.mpls"),
                    os.path.join("STREAM", "00002.m2ts")):
            self.assertTrue(same(rel), rel)

        disc_real, disc_sim = load_disc(real), load_disc(sim.root)
        self.assertEqual(sorted(disc_real.playlists), sorted(disc_sim.playlists))
        for pid, pl in disc_real.playlists.items():
            other = disc_sim.playlists[pid]
            marks = lambda p: [m.time - p.items[0].in_time for m in p.marks]
            streams = lambda p: [(s.kind, s.pid, s.coding_type, s.lang) for s in p.items[0].streams]
            self.assertEqual((pl.items[0].clip, marks(pl), streams(pl), pl.is_3d),
                             (other.items[0].clip, marks(other), streams(other), other.is_3d), pid)
        for tv_3d in (True, False):
            codes = lambda d: sorted((f.level, f.code) for f in explore(d, tv_3d=tv_3d).findings)
            self.assertEqual(codes(disc_real), codes(disc_sim))

    def test_two_backgrounds(self):
        """v1.13.0: Kapitelmenü mit eigenem Hintergrund (zweite Menü-Playlist). Echter Export: Simulator ohne Fehler
        und Warnungen, beide Menü-Playlists erreicht, Sprung hin und zurück; Simulation = Export (Navigation,
        Menüströme und Menü-Playlists byte-gleich)."""
        from PIL import Image
        from modules.disc_export import export_disc
        from modules.sim_disc import build_simulation_disc
        from modules.bdsim.disc import load_disc
        from modules.bdsim.explore import explore, format_report
        from core.menu_templates import create_chapter_menus, create_language_menus

        images = []
        for name, color in (("bild1.png", (20, 40, 90)), ("bild2.png", (90, 30, 20))):
            path = os.path.join(self.tmp.name, name)
            Image.new("RGB", (1920, 1080), color).save(path)
            images.append(path)
        graph = self._graph(menus=False)
        film = graph.films[0]
        graph.main_menu.background.image = images[0]
        for page in create_chapter_menus(graph, film.id, per_page=2):
            page.background.image = images[1]
            page.background.duration = 10.0
        create_language_menus(graph, film.id)

        real = os.path.join(self.tmp.name, "GROUPS_REAL")
        os.makedirs(real)
        exported = copy.deepcopy(graph)
        exported.settings.output_path = real
        plan = build_export_plan(exported)
        self.assertEqual(len(plan.menu_groups), 2)
        ok, msg = export_disc(plan.project_state, lambda m: None, lambda p: None, plan.pages_specs)
        self.assertTrue(ok, msg)
        disc = load_disc(real)
        group_pl = len(graph.films) + 1
        self.assertEqual(sorted(disc.compositions), [0, group_pl])
        for tv_3d in (True, False):
            report = explore(disc, tv_3d=tv_3d)
            self.assertTrue(report.ok, format_report(disc, [report]))
            self.assertEqual([f.code for f in report.findings if f.level == "warnung"], [])
            self.assertIn(group_pl, report.playlists_reached)

        sim = build_simulation_disc(copy.deepcopy(graph), os.path.join(self.tmp.name, "GROUPS_SIM"))
        for rel in ("index.bdmv", "MovieObject.bdmv", os.path.join("PLAYLIST", "00000.mpls"),
                    os.path.join("PLAYLIST", f"{group_pl:05d}.mpls")):
            self.assertTrue(filecmp.cmp(os.path.join(real, "BDMV", rel), os.path.join(sim.root, "BDMV", rel),
                                        shallow=False), rel)

    def test_film_end_in_extras(self):
        """v1.18.0: Der Bonus-Film endet im Extras-Menü (eigener Hintergrund). Echter Export: Simulator ohne Fehler
        und Warnungen, nach dem Bonus Extras-Menü mit „BONUS“ ausgewählt; Navigation byte-gleich mit der Simulation."""
        from PIL import Image
        from modules.disc_export import export_disc
        from modules.sim_disc import build_simulation_disc
        from modules.bdsim.disc import load_disc
        from modules.bdsim.explore import explore, format_report
        from modules.bdsim.player import Player, STATE_MENU
        from core.disc_edit import add_menu

        images = []
        for name, color in (("haupt.png", (20, 40, 90)), ("extras.png", (90, 30, 20))):
            path = os.path.join(self.tmp.name, name)
            Image.new("RGB", (1920, 1080), color).save(path)
            images.append(path)
        graph = self._graph(menus=False)
        main = graph.main_menu
        main.background.image = images[0]
        bonus = graph.films[1]
        main.buttons = [b for b in main.buttons if b.target != bonus.id]
        extras = add_menu(graph, "Extras", (400.0, 300.0))
        extras.background.image = images[1]
        extras.background.duration = 10.0
        extras.buttons[0].target = main.id                                   # ZURÜCK
        add_nav_button(graph, extras.id, "BONUS", bonus.id)
        add_nav_button(graph, main.id, "EXTRAS", extras.id)
        bonus.end_target = extras.id

        real = os.path.join(self.tmp.name, "END_REAL")
        os.makedirs(real)
        exported = copy.deepcopy(graph)
        exported.settings.output_path = real
        plan = build_export_plan(exported)
        self.assertTrue(plan.project_state.title_ends)
        ok, msg = export_disc(plan.project_state, lambda m: None, lambda p: None, plan.pages_specs)
        self.assertTrue(ok, msg)
        disc = load_disc(real)
        for tv_3d in (True, False):
            report = explore(disc, tv_3d=tv_3d)
            self.assertTrue(report.ok, format_report(disc, [report]))
            self.assertEqual([f.code for f in report.findings if f.level == "warnung"], [])

        p = Player(disc)
        p.insert_disc()
        p.activate_button(next(i for i, b in enumerate(main.buttons, start=1) if b.label == "EXTRAS"))
        p.activate_button(2)                                                  # BONUS
        p.playlist_end()
        self.assertEqual((p.state, p.page_id, p.selected_button), (STATE_MENU, plan.page_ids[extras.id], 2))

        sim = build_simulation_disc(copy.deepcopy(graph), os.path.join(self.tmp.name, "END_SIM"))
        for rel in ("index.bdmv", "MovieObject.bdmv"):
            self.assertTrue(filecmp.cmp(os.path.join(real, "BDMV", rel), os.path.join(sim.root, "BDMV", rel),
                                        shallow=False), rel)

    def test_trailer_and_film_after_film(self):
        """v1.18.1: Start → Bonus (als Trailer) → Hauptmenü, Hauptfilm → Bonus. Echter Export: Simulator ohne
        Fehler und Warnungen, Disc beginnt mit dem Bonus, nach dem Hauptfilm läuft der Bonus; Navigation byte-gleich
        mit der Simulation."""
        from modules.disc_export import export_disc
        from modules.sim_disc import build_simulation_disc
        from modules.bdsim.disc import load_disc
        from modules.bdsim.explore import explore, format_report
        from modules.bdsim.player import Player, STATE_FILM, STATE_MENU

        graph = self._graph(menus=False)
        main = graph.main_menu
        film, bonus = graph.films
        graph.start_target = bonus.id
        bonus.end_target = main.id
        film.end_target = bonus.id

        real = os.path.join(self.tmp.name, "CHAIN_REAL")
        os.makedirs(real)
        exported = copy.deepcopy(graph)
        exported.settings.output_path = real
        plan = build_export_plan(exported)
        ok, msg = export_disc(plan.project_state, lambda m: None, lambda p: None, plan.pages_specs)
        self.assertTrue(ok, msg)
        disc = load_disc(real)
        for tv_3d in (True, False):
            report = explore(disc, tv_3d=tv_3d)
            self.assertTrue(report.ok, format_report(disc, [report]))
            self.assertEqual([f.code for f in report.findings if f.level == "warnung"], [])

        p = Player(disc)
        p.insert_disc()
        self.assertEqual((p.state, p.title), (STATE_FILM, 2))
        p.playlist_end()
        self.assertEqual(p.state, STATE_MENU)
        p.activate_button(1)                                                  # FILM STARTEN
        self.assertEqual(p.title, 1)
        p.playlist_end()
        self.assertEqual((p.state, p.title), (STATE_FILM, 2))
        p.playlist_end()
        self.assertEqual(p.state, STATE_MENU)

        sim = build_simulation_disc(copy.deepcopy(graph), os.path.join(self.tmp.name, "CHAIN_SIM"))
        for rel in ("index.bdmv", "MovieObject.bdmv"):
            self.assertTrue(filecmp.cmp(os.path.join(real, "BDMV", rel), os.path.join(sim.root, "BDMV", rel),
                                        shallow=False), rel)

    def test_disc_title_meta(self):
        """v1.10.1: Disc-Titel im Player (ab v1.11.2 Standard). Ohne Häkchen kein META/DL, mit Häkchen
        bdmt_eng.xml und bdmt_deu.xml mit dem Titel im Player (Unicode); Navigation unverändert."""
        from modules.disc_export import export_disc
        from tests.test_meta_generator import disc_name

        roots = {}
        for flag in (False, True):
            root = os.path.join(self.tmp.name, f"META_{flag}")
            os.makedirs(root)
            graph = self._graph()
            graph.settings.output_path = root
            graph.settings.disc_title_meta = flag
            graph.settings.disc_title = "Mein Film – Teil Ä"
            plan = build_export_plan(graph)
            ok, msg = export_disc(plan.project_state, lambda m: None, lambda p: None, plan.pages_specs)
            self.assertTrue(ok, msg)
            roots[flag] = root

        dl = lambda root: os.path.join(root, "BDMV", "META", "DL")
        self.assertFalse(os.path.exists(dl(roots[False])))
        self.assertEqual(sorted(os.listdir(dl(roots[True]))), ["bdmt_deu.xml", "bdmt_eng.xml"])
        for name in os.listdir(dl(roots[True])):
            with open(os.path.join(dl(roots[True]), name), "rb") as f:
                self.assertEqual(disc_name(f.read()), "Mein Film – Teil Ä")
        for rel in ("index.bdmv", "MovieObject.bdmv"):
            self.assertTrue(filecmp.cmp(os.path.join(roots[False], "BDMV", rel),
                                        os.path.join(roots[True], "BDMV", rel), shallow=False), rel)

    def test_failed_iso_fails_export(self):
        """Scheitert die ISO-Erstellung, meldet der Export einen Fehler (bis v1.8.2: Erfolg) und räumt nicht auf."""
        from unittest import mock
        from modules.disc_export import export_disc
        root = os.path.join(self.tmp.name, "ISOFAIL")
        os.makedirs(root)
        graph = self._graph()
        graph.settings.output_path = root
        graph.settings.export_format = "iso"
        plan = build_export_plan(graph)
        with mock.patch("modules.iso_tools.create_udf_iso", return_value=False):
            ok, msg = export_disc(plan.project_state, lambda m: None, lambda p: None, plan.pages_specs)
        self.assertFalse(ok)
        self.assertTrue(os.path.isdir(os.path.join(root, "BDMV")))


if __name__ == "__main__":
    unittest.main()
