"""
Ultra HD Blu-ray ohne Menü (UHD-Plan, vor Phase 4): Start-Knoten direkt auf den einzigen Film, tsMuxeR schreibt die
ganze Disc in Version 3 (--blu-ray-v3, HEVC-Spur). Mit Menü oder mehreren Filmen sperrt die Vorprüfung weiter.
Blu-ray-Projekte bleiben unverändert.
"""

import os
import shutil
import tempfile
import unittest

from core import preflight
from core.disc_adapter import build_export_plan
from core.disc_edit import add_film, starter_project
from core.meta_builder import MetaBuilder
from core.translations import tr
from modules.mux_engine import find_tsmuxer
from tests.prepare_util import make_hevc, needs_x265, setUpModule, tearDownModule  # noqa: F401


def uhd_project(video="film_2160p.hevc"):
    project = starter_project()
    project.settings.disc_type = "uhd"
    film = project.films[0]
    film.video_base, film.fps = video, 24000 / 1001
    film.video_details = {"width": 3840, "height": 2160, "fps": film.fps, "dynamic_range": "hdr10"}
    project.start_target = film.id
    project.menus = []
    return project


def errors(project):
    return [i.message for i in preflight.run_preflight(project, check_files=False) if i.level == preflight.ERROR]


class Rules(unittest.TestCase):
    def test_without_menu_allowed(self):
        self.assertNotIn(tr("pf_uhd_not_ready"), errors(uhd_project()))

    def test_menu_or_several_films_locked(self):
        project = starter_project()
        project.settings.disc_type = "uhd"
        project.films[0].video_base = "film_2160p.hevc"
        self.assertIn(tr("pf_uhd_not_ready"), errors(project))              # Start → Hauptmenü
        project = uhd_project()
        extra = add_film(project, "Extra", (700.0, 300.0))
        extra.video_base = "extra_1080p.hevc"
        self.assertIn(tr("pf_uhd_not_ready"), errors(project))

    def test_meta_file(self):
        state = build_export_plan(uhd_project()).project_state
        meta = MetaBuilder(state).generate_meta_content()
        self.assertTrue(meta.startswith("MUXOPT --blu-ray-v3"))
        self.assertIn('V_MPEGH/ISO/HEVC, "film_2160p.hevc", fps=23.976', meta)
        self.assertNotIn("insertSEI", meta.splitlines()[1])

    def test_bluray_meta_unchanged(self):
        project = starter_project()
        project.films[0].video_base = "film.264"
        state = build_export_plan(project).project_state
        meta = MetaBuilder(state).generate_meta_content()
        self.assertTrue(meta.startswith("MUXOPT --blu-ray "))
        self.assertIn("V_MPEG4/ISO/AVC", meta)


@needs_x265
@unittest.skipUnless(find_tsmuxer(), "tsMuxeR nicht gefunden")
class Export(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="uhd_export_")
        cls.clip = os.path.join(cls.dir, "Film_2160p.hevc")
        make_hevc(cls.clip, seconds=1, size="3840x2160", colour="hdr10")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def export(self, fmt):
        from modules.disc_export import export_disc
        project = uhd_project(self.clip)
        out = os.path.join(self.dir, fmt)
        os.makedirs(out, exist_ok=True)
        project.settings.output_path, project.settings.export_format = out, fmt
        plan = build_export_plan(project)
        logs = []
        ok, _msg = export_disc(plan.project_state, logs.append, lambda _r: None, plan.pages_specs,
                               on_disc_ready=lambda _d: self.fail("Simulator darf UHD noch nicht lesen"))
        self.assertTrue(ok, "\n".join(logs[-15:]))
        return out, logs

    def test_folder_is_version_3(self):
        out, logs = self.export("folder")
        for rel, magic in (("index.bdmv", b"INDX0300"), ("MovieObject.bdmv", b"MOBJ0300"),
                           ("PLAYLIST/00000.mpls", b"MPLS0300"), ("CLIPINF/00000.clpi", b"HDMV0300")):
            with open(os.path.join(out, "BDMV", rel), "rb") as f:
                self.assertEqual(f.read(8), magic, rel)
        self.assertIn(tr("log_uhd_no_simulation", "de"), logs)

    def test_iso_written_by_tsmuxer(self):
        out, logs = self.export("iso")
        self.assertEqual([f for f in os.listdir(out) if f.endswith(".iso")], ["Untitled_Project.iso"])
        self.assertIn(tr("log_uhd_direct", "de"), logs)


if __name__ == "__main__":
    unittest.main()
