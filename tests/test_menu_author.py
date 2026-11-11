# tests/test_menu_author.py
import unittest
import os
import tempfile
from PIL import Image

from modules.menu_author import (
    create_button_image,
    create_default_background,
    generate_menu_subclip,
    inject_menu_into_bdmv,
    assemble_hdmv_disc_structure
)

class TestMenuAuthor(unittest.TestCase):

    def test_create_button_image(self):
        w, h = 380, 70
        for state in ["normal", "selected", "activated"]:
            img = create_button_image("TEST BUTTON", width=w, height=h, state=state)
            self.assertIsInstance(img, Image.Image)
            self.assertEqual(img.size, (w, h))
            self.assertEqual(img.mode, "RGBA")

    def test_create_default_background(self):
        bg = create_default_background(width=1920, height=1080)
        self.assertIsInstance(bg, Image.Image)
        self.assertEqual(bg.size, (1920, 1080))
        self.assertEqual(bg.mode, "RGBA")

    def test_generate_menu_subclip_single_button(self):
        with tempfile.TemporaryDirectory() as tmp:
            m2ts_path = os.path.join(tmp, "00002.m2ts")
            clpi_path = os.path.join(tmp, "00002.clpi")

            ok = generate_menu_subclip(
                btn1_text="FILM STARTEN",
                btn2_text=None,
                output_m2ts_path=m2ts_path,
                output_clpi_path=clpi_path,
                duration_sec=10.0,
                lang="deu"
            )
            self.assertTrue(ok)
            self.assertTrue(os.path.exists(m2ts_path))
            self.assertTrue(os.path.exists(clpi_path))

            # M2TS Prüfungen
            m2ts_size = os.path.getsize(m2ts_path)
            self.assertGreater(m2ts_size, 0)
            self.assertEqual(m2ts_size % 192, 0) # M2TS-Pakete sind 192 Bytes lang

            # CLPI Prüfungen
            with open(clpi_path, "rb") as f:
                clpi_bytes = f.read()
            self.assertEqual(clpi_bytes[:8], b"HDMV0200")
            self.assertIn(b"deu", clpi_bytes)

    def test_generate_menu_subclip_two_buttons(self):
        with tempfile.TemporaryDirectory() as tmp:
            m2ts_path = os.path.join(tmp, "00002.m2ts")
            clpi_path = os.path.join(tmp, "00002.clpi")

            ok = generate_menu_subclip(
                btn1_text="FILM STARTEN",
                btn2_text="EXTRAS",
                output_m2ts_path=m2ts_path,
                output_clpi_path=clpi_path,
                duration_sec=10.0,
                lang="eng"
            )
            self.assertTrue(ok)
            self.assertTrue(os.path.exists(m2ts_path))
            self.assertTrue(os.path.exists(clpi_path))
            self.assertEqual(os.path.getsize(m2ts_path) % 192, 0)

    def test_inject_menu_into_bdmv(self):
        with tempfile.TemporaryDirectory() as tmp:
            bdmv_dir = os.path.join(tmp, "BDMV")
            stream_dir = os.path.join(bdmv_dir, "STREAM")
            clip_dir = os.path.join(bdmv_dir, "CLIPINF")
            pl_dir = os.path.join(bdmv_dir, "PLAYLIST")
            os.makedirs(stream_dir, exist_ok=True)
            os.makedirs(clip_dir, exist_ok=True)
            os.makedirs(pl_dir, exist_ok=True)

            # Simuliere tsMuxeR Film-Export: 00000.m2ts, 00000.clpi, 00000.mpls
            movie_m2ts = os.path.join(stream_dir, "00000.m2ts")
            movie_clpi = os.path.join(clip_dir, "00000.clpi")
            movie_mpls = os.path.join(pl_dir, "00000.mpls")
            with open(movie_m2ts, "wb") as f: f.write(b"MOVIE_DATA_M2TS" * 100)
            with open(movie_clpi, "wb") as f: f.write(b"MOVIE_DATA_CLPI" * 10)
            with open(movie_mpls, "wb") as f: f.write(b"MOVIE_DATA_MPLS" * 10)

            ok = inject_menu_into_bdmv(
                bdmv_dir=bdmv_dir,
                bg_image_path=None, # Standard-Hintergrund
                btn1_text="START MOVIE",
                btn2_text="BONUS",
                duration_sec=5.0,
                fps=24.0,
                lang="eng",
                num_titles=2
            )
            self.assertTrue(ok)

            # 1. Hauptfilm 00000.mpls muss zu 00001.mpls geworden sein
            movie_pl_1 = os.path.join(pl_dir, "00001.mpls")
            self.assertTrue(os.path.exists(movie_pl_1))
            with open(movie_pl_1, "rb") as f:
                self.assertEqual(f.read(), b"MOVIE_DATA_MPLS" * 10)

            # 2. Hauptfilm M2TS und CLPI müssen unverändert an 00000 liegen
            self.assertTrue(os.path.exists(movie_m2ts))
            self.assertTrue(os.path.exists(movie_clpi))

            # 3. Menü Playlist muss 00000.mpls sein
            menu_pl_0 = os.path.join(pl_dir, "00000.mpls")
            self.assertTrue(os.path.exists(menu_pl_0))
            with open(menu_pl_0, "rb") as f:
                pl_0_data = f.read()
            self.assertEqual(pl_0_data[:8], b"MPLS0200")
            self.assertIn(b"00001M2TS", pl_0_data) # Hintergrund Video Clip
            self.assertIn(b"00002M2TS", pl_0_data) # IGS SubClip

            # 4. Menü Clips an 00001 (Video) und 00002 (IGS)
            bg_m2ts = os.path.join(stream_dir, "00001.m2ts")
            bg_clpi = os.path.join(clip_dir, "00001.clpi")
            igs_m2ts = os.path.join(stream_dir, "00002.m2ts")
            igs_clpi = os.path.join(clip_dir, "00002.clpi")
            self.assertTrue(os.path.exists(bg_m2ts))
            self.assertTrue(os.path.exists(bg_clpi))
            self.assertTrue(os.path.exists(igs_m2ts))
            self.assertTrue(os.path.exists(igs_clpi))

            # 5. Master-Navigation index.bdmv & MovieObject.bdmv
            index_path = os.path.join(bdmv_dir, "index.bdmv")
            mobj_path = os.path.join(bdmv_dir, "MovieObject.bdmv")
            self.assertTrue(os.path.exists(index_path))
            self.assertTrue(os.path.exists(mobj_path))
            with open(index_path, "rb") as f:
                self.assertEqual(f.read()[:8], b"INDX0200")
            with open(mobj_path, "rb") as f:
                self.assertEqual(f.read()[:8], b"MOBJ0200")

            # 6. Standardkonforme BACKUP-Kopien
            backup_dir = os.path.join(bdmv_dir, "BACKUP")
            self.assertTrue(os.path.exists(os.path.join(backup_dir, "index.bdmv")))
            self.assertTrue(os.path.exists(os.path.join(backup_dir, "MovieObject.bdmv")))
            self.assertTrue(os.path.exists(os.path.join(backup_dir, "PLAYLIST", "00000.mpls")))
            self.assertTrue(os.path.exists(os.path.join(backup_dir, "PLAYLIST", "00001.mpls")))

            # 7. Extras Playlist & Clips bei num_titles = 2
            self.assertTrue(os.path.exists(os.path.join(pl_dir, "00002.mpls")))
            self.assertTrue(os.path.exists(os.path.join(stream_dir, "00003.m2ts")))
            self.assertTrue(os.path.exists(os.path.join(clip_dir, "00003.clpi")))
            self.assertTrue(os.path.exists(os.path.join(backup_dir, "PLAYLIST", "00002.mpls")))
            self.assertTrue(os.path.exists(os.path.join(backup_dir, "CLIPINF", "00003.clpi")))

    def test_assemble_hdmv_disc_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok = assemble_hdmv_disc_structure(
                output_dir=tmp,
                btn1_text="PLAY",
                duration_sec=2.0
            )
            self.assertTrue(ok)
            self.assertTrue(os.path.exists(os.path.join(tmp, "BDMV", "index.bdmv")))
            self.assertTrue(os.path.exists(os.path.join(tmp, "BDMV", "MovieObject.bdmv")))
            self.assertTrue(os.path.exists(os.path.join(tmp, "BDMV", "PLAYLIST", "00000.mpls")))
            self.assertTrue(os.path.exists(os.path.join(tmp, "BDMV", "STREAM", "00001.m2ts")))
            self.assertTrue(os.path.exists(os.path.join(tmp, "BDMV", "STREAM", "00002.m2ts")))
            self.assertTrue(os.path.exists(os.path.join(tmp, "CERTIFICATE", "BACKUP")))

    def test_generate_menu_subclip_with_custom_specs(self):
        from modules.igs.layout import build_main_menu_specs
        specs = build_main_menu_specs(has_extras=True, has_chapters=True, has_audio=True)
        self.assertEqual(len(specs), 4)

        with tempfile.TemporaryDirectory() as tmp:
            m2ts_path = os.path.join(tmp, "00002.m2ts")
            clpi_path = os.path.join(tmp, "00002.clpi")

            ok = generate_menu_subclip(
                output_m2ts_path=m2ts_path,
                output_clpi_path=clpi_path,
                button_specs=specs,
                duration_sec=5.0
            )
            self.assertTrue(ok)
            self.assertTrue(os.path.exists(m2ts_path))
            self.assertEqual(os.path.getsize(m2ts_path) % 192, 0)

    def test_generate_menu_subclip_chapter_and_audio_specs(self):
        from modules.igs.layout import build_chapter_menu_specs, build_audio_menu_specs
        chap_specs = build_chapter_menu_specs(["00:00:00", "00:10:00", "00:20:00", "00:30:00"])
        self.assertEqual(len(chap_specs), 5) # 4 Kapitel + 1 Zurück

        with tempfile.TemporaryDirectory() as tmp:
            m2ts_path = os.path.join(tmp, "chap_00002.m2ts")
            clpi_path = os.path.join(tmp, "chap_00002.clpi")

            ok = generate_menu_subclip(
                output_m2ts_path=m2ts_path,
                output_clpi_path=clpi_path,
                button_specs=chap_specs,
                duration_sec=5.0
            )
            self.assertTrue(ok)
            self.assertEqual(os.path.getsize(m2ts_path) % 192, 0)

        audio_specs = build_audio_menu_specs([{"lang": "deu"}, {"lang": "eng"}], [{"lang": "deu"}])
        with tempfile.TemporaryDirectory() as tmp:
            m2ts_path = os.path.join(tmp, "audio_00002.m2ts")
            clpi_path = os.path.join(tmp, "audio_00002.clpi")

            ok = generate_menu_subclip(
                output_m2ts_path=m2ts_path,
                output_clpi_path=clpi_path,
                button_specs=audio_specs,
                duration_sec=5.0
            )
            self.assertTrue(ok)
            self.assertEqual(os.path.getsize(m2ts_path) % 192, 0)

    def test_extra_meta_builder(self):
        from core.project_state import ProjectState
        from core.meta_builder import MetaBuilder

        proj = ProjectState()
        proj.video_extra = "C:/Videos/bonus.264"
        proj.extra_audio_tracks.append({"path": "C:/Audio/bonus.ac3", "lang": "eng"})

        mb = MetaBuilder(proj)
        meta_txt = mb.generate_extra_meta_content()

        self.assertIn("MUXOPT --blu-ray", meta_txt)
        self.assertIn('V_MPEG4/ISO/AVC, "C:/Videos/bonus.264"', meta_txt)
        self.assertIn('A_AC3, "C:/Audio/bonus.ac3", lang=eng', meta_txt)

    def test_menu_media_and_duration_config(self):
        from core.project_state import ProjectState
        proj = ProjectState()
        self.assertEqual(proj.menu_duration, 30.0)
        self.assertIsNone(proj.menu_bg_video)
        self.assertIsNone(proj.menu_bg_audio)

        proj.menu_duration = 45.0
        proj.menu_bg_video = "C:/Videos/motion.264"
        proj.menu_bg_audio = "C:/Audio/theme.ac3"

        from core.constants import APP_VERSION
        d = proj.to_dict()
        self.assertEqual(d["version"], APP_VERSION)
        self.assertEqual(d["menu_duration"], 45.0)
        self.assertEqual(d["menu_bg_video"], "C:/Videos/motion.264")
        self.assertEqual(d["menu_bg_audio"], "C:/Audio/theme.ac3")

        proj2 = ProjectState()
        proj2.from_dict(d)
        self.assertEqual(proj2.menu_duration, 45.0)
        self.assertEqual(proj2.menu_bg_video, "C:/Videos/motion.264")
        self.assertEqual(proj2.menu_bg_audio, "C:/Audio/theme.ac3")

    def test_probe_media_duration_none(self):
        from modules.menu_author import probe_media_duration
        self.assertIsNone(probe_media_duration(None))
        self.assertIsNone(probe_media_duration("non_existent_file.264"))

    def test_get_clpi_stc_range_and_pts_sync(self):
        from modules.menu_author import get_clpi_stc_range
        from modules.mpls.clpi_generator import write_video_clpi_file
        with tempfile.TemporaryDirectory() as tmp:
            clpi_path = os.path.join(tmp, "00001.clpi")
            write_video_clpi_file(clpi_path, num_packets=100, duration_sec=10.0)
            stc_start, stc_end = get_clpi_stc_range(clpi_path)
            self.assertEqual(stc_start, 27000000)
            self.assertEqual(stc_end, 27000000 + int(10.0 * 45000))


if __name__ == '__main__':
    unittest.main()
