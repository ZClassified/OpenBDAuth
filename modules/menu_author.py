# modules/menu_author.py
"""
High-Level Menü-Orchestrator für OpenBDAuth.

Verbindet:
1. Grafische Button-Generierung (Pillow)
2. Hintergrund-Videoerstellung (FFmpeg & nativer Transport-Stream)
3. IGS-Compiler (RLE, BT.709 Palette, ICS/ODS/PDS/END, PES)
4. M2TS-Packer (192-Byte SubClips mit ATS)
5. Playlist- & CLPI-Generator (SubPath Typ 2 Verknüpfung)
6. BDMV-Navigations-Generator (index.bdmv und MovieObject.bdmv)
"""

import os
import shutil
import struct
import subprocess
import tempfile
from typing import Callable, List, Optional, Dict, Tuple, Any
from PIL import Image, ImageDraw, ImageFont

from modules.igs.compiler import IGSCompiler, MenuButton, MenuPage
from modules.igs.layout import (
    MenuButtonSpec, MenuLayoutEngine,
    build_main_menu_specs, build_chapter_menu_specs, build_audio_menu_specs
)
from modules.igs.segments import FPS_23_976, FPS_24, FPS_25, FPS_29_97, FPS_50, FPS_59_94
from modules.m2ts.m2ts_writer import write_igs_m2ts_file, add_tp_extra_header, TS_PACKET_SIZE, DEFAULT_ATS_STEP
from modules.mpls.clpi_generator import write_clpi_file, write_video_clpi_file
from modules.mpls.mpls_generator import write_menu_mpls_file
from modules.mpls.mpls_reader import read_mpls_marks, parse_chapter_time, find_mark_for_time
from modules.bdmv.index_generator import write_index_bdmv_file
from modules.bdmv.movie_object_generator import write_movie_object_file
from modules.mux_engine import find_tsmuxer
from modules.external_tools import tool_path, FFMPEG, FFPROBE, NO_CONSOLE
from modules.fonts import load_menu_font

_FPS_TO_IGS_CODE = {
    23.976: FPS_23_976,
    24.0:   FPS_24,
    25.0:   FPS_25,
    29.97:  FPS_29_97,
    50.0:   FPS_50,
    59.94:  FPS_59_94,
}

def fps_to_igs_rate_code(fps: float) -> int:
    """Konvertiert float-FPS in den BD-ROM ICS Frame-Rate-Code für den Interactive Composition Segment."""
    for known_fps, code in _FPS_TO_IGS_CODE.items():
        if abs(fps - known_fps) < 0.1:
            return code
    return FPS_23_976  # Fallback

def create_button_image(
    text: str,
    width: int = 380,
    height: int = 70,
    state: str = "normal"
) -> Image.Image:
    """
    Erzeugt ein einzelnes Button-Grafikobjekt (RGBA) mit edlem Heimkino-Design.
    state: 'normal', 'selected' oder 'activated'
    """
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Schriftgröße dynamisch an Button-Höhe anpassen
    font_size = max(14, min(26, int(height * 0.42)))
    font = load_menu_font(font_size)  # Liberation Sans, metrisch identisch mit Arial (modules/fonts.py)

    # Bounding Box für Text-Zentrierung & Überlaufschutz
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    # Falls Text zu lang ist, Schriftgröße schrittweise verkleinern
    while font_size > 12 and text_w > width - 24:
        font_size -= 2
        font = load_menu_font(font_size)
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

    tx = (width - text_w) // 2
    ty = (height - text_h) // 2

    radius = 12

    if state == "normal":
        # Ruhezustand: Halbtransparenter anthrazitfarbener Balken mit dezentem Rahmen
        draw.rounded_rectangle(
            [4, 4, width - 5, height - 5],
            radius=radius,
            fill=(25, 28, 35, 180),
            outline=(160, 170, 190, 200),
            width=2
        )
        draw.text((tx, ty), text, fill=(230, 235, 245, 255), font=font)

    elif state == "selected":
        # Ausgewählter Zustand: Kräftiger Gold-Glow Rahmen und leuchtender Text
        draw.rounded_rectangle(
            [2, 2, width - 3, height - 3],
            radius=radius,
            fill=(65, 50, 15, 230),
            outline=(255, 215, 0, 255),
            width=3
        )
        draw.text((tx, ty), text, fill=(255, 235, 130, 255), font=font)

    elif state == "activated":
        # Klick / Bestätigung: Weißer Blitz mit schwarzem Text
        draw.rounded_rectangle(
            [2, 2, width - 3, height - 3],
            radius=radius,
            fill=(255, 255, 255, 250),
            outline=(255, 255, 255, 255),
            width=3
        )
        draw.text((tx, ty), text, fill=(10, 10, 10, 255), font=font)

    return img

def button_state_image(spec: MenuButtonSpec, width: int, height: int, state: str) -> Image.Image:
    """Grafik eines Buttons für einen Zustand: Form-Button (spec.shape) oder Text-Button."""
    if spec.shape is not None:
        from modules.button_shapes import create_shape_image
        return create_shape_image(spec.shape, width, height, state)
    return create_button_image(spec.text, width, height, state)


def create_default_background(width: int = 1920, height: int = 1080) -> Image.Image:
    """Erzeugt ein dunkles Verlaufs-Hintergrundbild als Standard-Menühintergrund."""
    img = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(img)

    # Vertikaler Verlauf: Dunkelblau (#0B0E14) nach Tiefschwarz (#030406)
    for y in range(height):
        ratio = y / height
        r = int(11 * (1 - ratio) + 3 * ratio)
        g = int(14 * (1 - ratio) + 4 * ratio)
        b = int(20 * (1 - ratio) + 6 * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b, 255))

    # Dezente Vignettierung an den Rändern
    draw.rectangle([0, 0, width, 6], fill=(0, 0, 0, 200))
    draw.rectangle([0, height - 6, width, height], fill=(0, 0, 0, 200))
    return img
def probe_media_duration(file_path: str, fps: float = 23.976) -> Optional[float]:
    """Ermittelt die exakte Dauer einer Mediendatei (.264, .ac3, .wav) via ffprobe."""
    if not file_path or not os.path.exists(file_path):
        return None
    ext = os.path.splitext(file_path)[1].lower()
    try:
        if ext in [".264", ".h264", ".avc"]:
            cmd = [
                tool_path(FFPROBE), "-v", "error", "-count_frames",
                "-select_streams", "v:0",
                "-show_entries", "stream=nb_read_frames",
                "-of", "default=noprint_wrappers=1:nokey=1",
                file_path
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True, **NO_CONSOLE)
            txt = res.stdout.strip()
            if txt.isdigit():
                return int(txt) / (fps if fps > 0 else 23.976)
        else:
            cmd = [
                tool_path(FFPROBE), "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                file_path
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True, **NO_CONSOLE)
            txt = res.stdout.strip()
            if txt:
                return float(txt)
    except Exception:
        pass
    return None


def render_background_video(
    bg_image_path: Optional[str],
    output_m2ts_path: str,
    output_clpi_path: str,
    duration_sec: float = 30.0,
    fps: float = 23.976,
    bg_video_path: Optional[str] = None,
    bg_audio_path: Optional[str] = None
) -> bool:
    """
    Rendert das Menü-Hintergrundvideo mit H.264 Video und AC-3 Audio und muxt
    diesen per tsMuxeR zu standardkonformem .m2ts und .clpi (mit Start-PTS 54000000 / 10 Min).
    Unterstützt:
    - bg_video_path: Rohes .264 Elementary Stream (0 % Re-Encoding!)
    - bg_image_path: PNG/JPG Standbild (wird für duration_sec kodiert)
    - bg_audio_path: .ac3 (0 % Re-Encoding!) oder .wav (wird zu Stereo AC3 konvertiert)
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # 1. VIDEO SOURCE: .264 Elementary Stream oder Standbild
        is_raw_264 = (
            bg_video_path
            and os.path.exists(bg_video_path)
            and os.path.getsize(bg_video_path) > 0
            and bg_video_path.lower().endswith((".264", ".h264", ".avc"))
        )

        if is_raw_264:
            # Reiner Elementary Stream: 1:1 direkt übernehmen (0% Re-Encoding!)
            h264_src = bg_video_path
        else:
            # Standbild als Video rendern (oder Default-Hintergrund falls leer)
            if not bg_image_path or not os.path.exists(bg_image_path):
                tmp_img = os.path.join(tmpdir, "default_bg.png")
                create_default_background().save(tmp_img)
                img_source = tmp_img
            else:
                img_source = bg_image_path

            h264_tmp = os.path.join(tmpdir, "menu_bg.264")
            # BD-ROM Part 3 x264 Parameter:
            # Bei 25 fps / 50 fps oder 29.97 / 59.94 fps muss 1080i (fake-interlaced / PsF) verwendet werden,
            # da 1080p25 und 1080p29.97 im Blu-ray Standard nicht existieren.
            x264_params = ["bluray-compat=1"]
            if abs(fps - 25.0) < 0.1 or abs(fps - 50.0) < 0.1 or abs(fps - 29.97) < 0.1 or abs(fps - 59.94) < 0.1:
                x264_params.append("fake-interlaced=1")

            gop_size = 25 if (abs(fps - 25.0) < 0.1 or abs(fps - 50.0) < 0.1) else 24

            ffmpeg_cmd = [
                tool_path(FFMPEG), "-y", "-loop", "1", "-i", img_source,
                "-t", str(duration_sec),
                "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
                "-c:v", "libx264", "-preset", "fast", "-tune", "stillimage",
                "-profile:v", "high", "-level:v", "4.1",
                "-x264-params", ":".join(x264_params),
                "-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                "-b:v", "15M", "-maxrate", "20M", "-bufsize", "20M",
                "-g", str(gop_size), "-keyint_min", str(gop_size), "-sc_threshold", "0",
                "-r", str(fps),
                h264_tmp
            ]
            try:
                subprocess.run(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, **NO_CONSOLE)
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                print(f"[MenuAuthor] FFmpeg Hinweis: {e}")
            h264_src = h264_tmp

        # 2. AUDIO SOURCE: .ac3 direkt, .wav konvertieren oder lautloses Stereo AC-3
        has_custom_audio = (
            bg_audio_path
            and os.path.exists(bg_audio_path)
            and os.path.getsize(bg_audio_path) > 0
        )

        ac3_src = None
        if has_custom_audio and bg_audio_path.lower().endswith(".ac3"):
            # Echter AC3 Elementary Stream: 1:1 direkt übernehmen (0% Re-Encoding!)
            ac3_src = bg_audio_path
        elif has_custom_audio:
            # WAV oder anderes Audio-Format: Zu 48kHz Stereo AC-3 wandeln
            ac3_tmp = os.path.join(tmpdir, "menu_audio.ac3")
            ffmpeg_aud_cmd = [
                tool_path(FFMPEG), "-y", "-i", bg_audio_path,
                "-t", str(duration_sec),
                "-c:a", "ac3", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                ac3_tmp
            ]
            try:
                subprocess.run(ffmpeg_aud_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, **NO_CONSOLE)
                ac3_src = ac3_tmp
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                print(f"[MenuAuthor] Audio-Transcoding Hinweis: {e}")
                ac3_src = None

        if not ac3_src or not os.path.exists(ac3_src):
            # Stumme Stereo-Tonspur erzeugen; manche Hardware-Player verwerfen Menü-Playlists ohne Ton
            ac3_tmp = os.path.join(tmpdir, "silence.ac3")
            ffmpeg_aud_cmd = [
                tool_path(FFMPEG), "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                "-t", str(duration_sec),
                "-c:a", "ac3", "-b:a", "192k",
                ac3_tmp
            ]
            try:
                subprocess.run(ffmpeg_aud_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, **NO_CONSOLE)
                ac3_src = ac3_tmp
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                print(f"[MenuAuthor] Audio-Synthese Hinweis: {e}")
                ac3_src = None

        # 3. Falls tsMuxeR vorhanden ist, echten Blu-ray Stream inkl. CLPI erzeugen
        tsmuxer_bin = find_tsmuxer()
        if tsmuxer_bin and os.path.exists(h264_src) and os.path.getsize(h264_src) > 0:
            norm_h264 = h264_src.replace("\\", "/")
            meta_lines = [
                "MUXOPT --no-pcr-on-video-pid --new-audio-pes --demux --vbr --disc-cdb --blu-ray",
                f'V_MPEG4/ISO/AVC, "{norm_h264}", fps={fps}, insertSEI, contSPS'
            ]
            if ac3_src and os.path.exists(ac3_src) and os.path.getsize(ac3_src) > 0:
                norm_ac3 = ac3_src.replace("\\", "/")
                meta_lines.append(f'A_AC3, "{norm_ac3}", lang=deu')

            meta_file = os.path.join(tmpdir, "bg.meta")
            with open(meta_file, "w", encoding="utf-8") as f:
                f.write("\n".join(meta_lines) + "\n")

            mux_out = os.path.join(tmpdir, "mux_out")
            try:
                subprocess.run([tsmuxer_bin, meta_file, mux_out], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, **NO_CONSOLE)
                stream_dir = os.path.join(mux_out, "BDMV", "STREAM")
                clipinf_dir = os.path.join(mux_out, "BDMV", "CLIPINF")
                if os.path.exists(stream_dir) and os.listdir(stream_dir):
                    src_m2ts = os.path.join(stream_dir, os.listdir(stream_dir)[0])
                    src_clpi = os.path.join(clipinf_dir, os.listdir(clipinf_dir)[0])
                    shutil.copy2(src_m2ts, output_m2ts_path)
                    shutil.copy2(src_clpi, output_clpi_path)
                    return True
            except Exception as e:
                print(f"[MenuAuthor] tsMuxeR Warnung: {e}, versuche Fallback...")

        # 4. Fallback (falls tsMuxeR nicht installiert oder fehlgeschlagen):
        ts_tmp = os.path.join(tmpdir, "menu_bg.ts")
        if is_raw_264:
            ffmpeg_ts_cmd = [tool_path(FFMPEG), "-y", "-i", h264_src]
        else:
            ffmpeg_ts_cmd = [tool_path(FFMPEG), "-y", "-loop", "1", "-i", img_source]

        if ac3_src and os.path.exists(ac3_src):
            ffmpeg_ts_cmd.extend(["-i", ac3_src])

        ffmpeg_ts_cmd.extend([
            "-t", str(duration_sec),
            "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
            "-c:v", "libx264", "-preset", "fast", "-tune", "stillimage",
            "-profile:v", "high", "-level:v", "4.1",
            "-x264-params", ":".join(x264_params),
            "-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
            "-b:v", "15M", "-maxrate", "20M", "-bufsize", "20M",
            "-g", str(gop_size), "-keyint_min", str(gop_size), "-sc_threshold", "0",
            "-r", str(fps),
            "-streamid", "0:4113"
        ])
        if ac3_src and os.path.exists(ac3_src):
            ffmpeg_ts_cmd.extend(["-c:a", "copy", "-streamid", "1:4352"])
        ffmpeg_ts_cmd.extend([
            "-f", "mpegts",
            ts_tmp
        ])
        try:
            subprocess.run(ffmpeg_ts_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, **NO_CONSOLE)
            if os.path.exists(ts_tmp) and os.path.getsize(ts_tmp) > 0:
                num_packets = 0
                ats = 0
                ats_step = DEFAULT_ATS_STEP
                with open(ts_tmp, "rb") as fin, open(output_m2ts_path, "wb") as fout:
                    while True:
                        pkt = fin.read(TS_PACKET_SIZE)
                        if not pkt or len(pkt) < TS_PACKET_SIZE:
                            break
                        m2ts_pkt = add_tp_extra_header(pkt, ats=ats)
                        fout.write(m2ts_pkt)
                        ats = (ats + ats_step) & 0x3FFFFFFF
                        num_packets += 1

                write_video_clpi_file(output_clpi_path, num_packets=num_packets, duration_sec=duration_sec, fps=fps, video_pid=0x1011)
                return True
        except Exception:
            pass

        # 4. Fallback falls kein FFmpeg/tsMuxeR vorhanden ist: Dummy 192-Byte M2TS für Tests
        with open(output_m2ts_path, "wb") as f:
            f.write(b"\x00" * (192 * 32))
        write_video_clpi_file(output_clpi_path, num_packets=32, duration_sec=duration_sec, video_pid=0x1011)
        return True

def build_project_menu_pages(project) -> List[Tuple[int, List[MenuButtonSpec]]]:
    """
    Erzeugt alle benötigten Menüseiten (Pages) für das Projekt:
    - Page 0: Hauptmenü (Film starten, Kapitel, Sprache, Extras)
    - Page 1: Kapitelauswahl (falls aktiviert & Kapitel vorhanden)
    - Page 2: Sprachauswahl (falls aktiviert & Audios/Subs vorhanden)
    """
    has_chapters = bool(getattr(project, "menu_show_chapters", False) and getattr(project, "chapters", None))
    has_audio = bool(getattr(project, "menu_show_audio", False) and (getattr(project, "audio_tracks", None) or getattr(project, "subtitle_tracks", None)))
    titles = getattr(project, "titles", [])
    has_extra_titles = len(titles) > 1 and any(t.video_base for t in titles[1:])
    has_extras = bool(has_extra_titles or getattr(project, "video_extra", None) or getattr(project, "menu_show_btn2", False))

    # Text für Titel 1 / Hauptfilm
    title1_name = getattr(titles[0], "name", "Hauptfilm") if titles else "Hauptfilm"
    custom_title1_btn = getattr(titles[0], "menu_btn_text", None) if titles else None
    proj_btn1_txt = getattr(project, "menu_btn1_text", None)

    if custom_title1_btn:
        play_text = custom_title1_btn
    elif title1_name and title1_name != "Hauptfilm":
        play_text = title1_name.upper()
    elif proj_btn1_txt:
        play_text = proj_btn1_txt
    else:
        play_text = "FILM STARTEN"

    # 1. Page 0: Hauptmenü
    page0_buttons = build_main_menu_specs(
        has_extras=has_extras,
        has_chapters=has_chapters,
        has_audio=has_audio,
        play_text=play_text,
        extras_text=getattr(project, "menu_btn2_text", "EXTRAS") or "EXTRAS",
        chapters_text=getattr(project, "menu_btn_chapters_text", "KAPITEL") or "KAPITEL",
        audio_text=getattr(project, "menu_btn_audio_text", "SPRACHE") or "SPRACHE",
        main_title_id=1,
        extra_title_id=2,
        chapter_page_id=1,
        audio_page_id=2,
        titles=titles if len(titles) > 1 else None
    )
    pages: List[Tuple[int, List[MenuButtonSpec]]] = [(0, page0_buttons)]

    # 2. Page 1: Kapitelauswahl (falls aktiv)
    if has_chapters:
        chapter_buttons = build_chapter_menu_specs(
            chapters=project.chapters,
            main_playlist_id=1,
            return_page_id=0,
            back_text="ZURÜCK"
        )
        pages.append((1, chapter_buttons))

    # 3. Page 2: Sprachauswahl (falls aktiv)
    if has_audio:
        audio_buttons = build_audio_menu_specs(
            audio_tracks=getattr(project, "audio_tracks", []),
            subtitle_tracks=getattr(project, "subtitle_tracks", []),
            return_page_id=0,
            back_text="ZURÜCK"
        )
        pages.append((2, audio_buttons))

    # Benutzerdefinierte Koordinaten aus interaktivem GUI-Designer anwenden
    custom_pos = getattr(project, "custom_button_positions", {})
    if custom_pos:
        for page_id, specs in pages:
            for spec in specs:
                key = (page_id, spec.button_id)
                if key in custom_pos:
                    x, y = custom_pos[key]
                    spec.x = int(x)
                    spec.y = int(y)

    return pages

def get_clpi_stc_range(clpi_path: str) -> Tuple[int, int]:
    """
    Liest presentation_start_time und presentation_end_time (im 45-kHz-Takt)
    aus der SequenceInfo einer .clpi Datei.
    """
    try:
        if os.path.exists(clpi_path):
            with open(clpi_path, "rb") as f:
                data = f.read()
            if len(data) >= 40 and data[:8] in (b"HDMV0100", b"HDMV0200"):
                seq_off = struct.unpack(">I", data[8:12])[0]
                if len(data) >= seq_off + 26:
                    pts_start = struct.unpack(">I", data[seq_off+4+14:seq_off+4+18])[0]
                    pts_end = struct.unpack(">I", data[seq_off+4+18:seq_off+4+22])[0]
                    if pts_start > 0 and pts_end > pts_start:
                        return pts_start, pts_end
    except Exception as e:
        print(f"[MenuAuthor] Hinweis beim Lesen von {clpi_path}: {e}")
    return 27000000, 27000000 + int(10.0 * 45000)

def get_clpi_video_format_code(clpi_path: str) -> Optional[int]:
    """
    Liest den video_format-Code (z.B. 6 für 1080p, 4 für 1080i)
    aus der ProgramInfo einer .clpi Datei.
    """
    try:
        if os.path.exists(clpi_path):
            with open(clpi_path, "rb") as f:
                data = f.read()
            if len(data) >= 40 and data[:8] in (b"HDMV0100", b"HDMV0200"):
                prog_off = struct.unpack(">I", data[12:16])[0]
                pos = data.find(b"\x1b", prog_off)
                if pos != -1 and pos + 1 < len(data):
                    attr_byte = data[pos + 1]
                    return (attr_byte >> 4) & 0x0F
    except Exception as e:
        print(f"[MenuAuthor] Hinweis beim Lesen des Video-Formats aus {clpi_path}: {e}")
    return None

def generate_menu_subclip(
    btn1_text: str = "FILM STARTEN",
    btn2_text: Optional[str] = None,
    output_m2ts_path: str = "",
    output_clpi_path: str = "",
    duration_sec: float = 10.0,
    fps: float = 23.976,
    lang: str = "deu",
    button_specs: Optional[List[MenuButtonSpec]] = None,
    pages_specs: Optional[List[Tuple[int, List[MenuButtonSpec]]]] = None,
    default_selected_id: int = 1,
    pts_start_45k: int = 27000000
) -> bool:
    """
    Erzeugt den IGS-SubClip (00002.m2ts und 00002.clpi) mit interaktiven Pfeiltasten-Buttons.
    Unterstützt sowohl Einzelseiten-Buttons als auch Multi-Page Menüs (Hauptmenü, Kapitel, Sprache).
    """
    # 1. Fallunterscheidung: Multi-Page oder Einzelseite
    if pages_specs is None:
        if button_specs is None:
            button_specs = [
                MenuButtonSpec(button_id=1, text=btn1_text, action_type="jump_title", target_title_id=1)
            ]
            if btn2_text:
                button_specs.append(
                    MenuButtonSpec(button_id=2, text=btn2_text, action_type="jump_title", target_title_id=2)
                )
            MenuLayoutEngine.layout_column(button_specs)
        pages_specs = [(0, button_specs)]

    # 2. Seiten und Buttons aufbereiten
    menu_pages: List[MenuPage] = []
    shape_images: List[Image.Image] = []   # Farben der Form-Buttons zuerst in die Palette
    for page_id, specs in pages_specs:
        needs_layout = any(
            b.x is None or b.y is None or b.upper_id is None
            for b in specs
        )
        if needs_layout:
            MenuLayoutEngine.auto_layout(specs)

        page_buttons: List[MenuButton] = []
        for spec in specs:
            w = spec.width if spec.width else 380
            h = spec.height if spec.height else 70

            if spec.invisible:   # Startseite einer Menügruppe (v1.13): Button ohne sichtbare Grafik
                b_norm = b_sel = b_act = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            else:
                b_norm, b_sel, b_act = (button_state_image(spec, w, h, state)
                                        for state in ("normal", "selected", "activated"))
            if spec.shape is not None:
                shape_images.extend((b_norm, b_sel, b_act))

            btn = MenuButton(
                button_id=spec.button_id,
                x=spec.x,
                y=spec.y,
                normal_image=b_norm,
                selected_image=b_sel,
                activated_image=b_act,
                upper_id=spec.upper_id if spec.upper_id is not None else spec.button_id,
                lower_id=spec.lower_id if spec.lower_id is not None else spec.button_id,
                left_id=spec.left_id if spec.left_id is not None else spec.button_id,
                right_id=spec.right_id if spec.right_id is not None else spec.button_id,
                target_playlist_id=spec.target_title_id,
                nav_commands=spec.get_nav_commands(),
                auto_action=spec.auto_action
            )
            page_buttons.append(btn)

        # Standard-Button: der markierte Button der Seite (v1.13), sonst wie bisher
        marked = next((s.button_id for s in specs if s.is_default), None)
        menu_pages.append(MenuPage(
            page_id=page_id,
            buttons=page_buttons,
            default_selected_id=marked if marked is not None else (default_selected_id if page_id == 0 else 1)
        ))

    # 3. IGS Kompilierung (Multi-Page Display Set mit synchronem 90-kHz PTS)
    pts_90khz = pts_start_45k * 2
    compiler = IGSCompiler(width=1920, height=1080, fps_code=fps_to_igs_rate_code(fps))
    pes_stream = compiler.compile_pages(menu_pages, pts_90khz=pts_90khz, priority_images=shape_images or None)

    # 4. 192-Byte M2TS schreiben
    write_igs_m2ts_file(output_m2ts_path, pes_stream, igs_pid=0x1400, pts_90khz=pts_90khz)

    # 5. CLPI für SubClip schreiben
    num_packets = os.path.getsize(output_m2ts_path) // 192
    write_clpi_file(output_clpi_path, num_packets=num_packets, duration_sec=duration_sec, fps=fps, lang=lang, pts_start_45k=pts_start_45k)

    return True

def resolve_chapter_jumps(
    pages_specs: List[Tuple[int, List[MenuButtonSpec]]],
    playlist_dir: str
) -> List[int]:
    """
    Ordnet jedem Kapitel-Button (action_type "play_chapter") den PlayListMark-Index zu, den tsMuxeR
    für seinen Zeitstempel tatsächlich in die Film-Playlist geschrieben hat (Fallback: Kapitelnummer - 1).
    Der Button merkt sich die Marke in einem Register und startet den Film per JumpTitle (siehe
    MenuButtonSpec.get_nav_commands); das MovieObject des Titels springt an die Marke.

    Gibt die Titel zurück, die Kapitel-Buttons haben (ihre MovieObjects werten den Kapitelwunsch aus).
    """
    marks_cache: Dict[int, Optional[List[dict]]] = {}
    chapter_titles = set()

    for _page_id, specs in pages_specs:
        for spec in specs:
            if spec.action_type != "play_chapter" or spec.nav_commands is not None:
                continue

            playlist_id = spec.target_title_id
            if playlist_id not in marks_cache:
                marks_cache[playlist_id] = read_mpls_marks(os.path.join(playlist_dir, f"{playlist_id:05d}.mpls"))
            marks = marks_cache[playlist_id]

            mark_id = None
            ch_seconds = parse_chapter_time(spec.chapter_time) if spec.chapter_time else None
            if marks and ch_seconds is not None:
                mark_id = find_mark_for_time(marks, ch_seconds)
            if mark_id is None:
                mark_id = max(0, spec.target_chapter_id - 1)
                if marks:
                    print(f"Warnung: Keine Kapitelmarke für '{spec.chapter_time}' in {playlist_id:05d}.mpls gefunden, "
                          f"verwende Marke {mark_id}.")
            spec.target_mark_id = mark_id
            chapter_titles.add(playlist_id)

    return sorted(chapter_titles)


def stream_choice_titles(pages_specs: List[Tuple[int, List[MenuButtonSpec]]]) -> List[int]:
    """Titel, für die ein Ton-/Untertitel-Menü Spuren wählt (ihre MovieObjects setzen die Wahl beim Start)."""
    return sorted({spec.target_title_id for _page_id, specs in pages_specs for spec in specs
                   if spec.action_type == "set_stream" and spec.nav_commands is None})


def inject_menu_into_bdmv(
    bdmv_dir: str,
    bg_image_path: Optional[str] = None,
    btn1_text: str = "FILM STARTEN",
    btn2_text: Optional[str] = None,
    duration_sec: float = 30.0,
    fps: float = 23.976,
    lang: str = "deu",
    num_titles: int = 1,
    button_specs: Optional[List[MenuButtonSpec]] = None,
    pages_specs: Optional[List[Tuple[int, List[MenuButtonSpec]]]] = None,
    project: Optional[object] = None,
    default_selected_id: int = 1,
    bg_video_path: Optional[str] = None,
    bg_audio_path: Optional[str] = None,
    background_renderer: Optional[Callable[..., bool]] = None,
    menu_groups: Optional[List[dict]] = None,
    menu_resume: bool = True,
    title_ends: Optional[Dict[int, object]] = None,
    first_play_title: Optional[int] = None,
    with_2d_choice: bool = False
) -> bool:
    """
    menu_groups (v1.13, eigene Hintergründe pro Menü): eine Liste von Menügruppen
    {"pages_specs", "bg_image", "bg_video", "bg_audio", "duration", "keep_page"}. Gruppe 0 ist das bisherige Menü
    (Hintergrund aus den übrigen Argumenten, ihre pages_specs ersetzen pages_specs); jede weitere Gruppe bekommt
    einen eigenen Hintergrund-Clip, einen IG-Strom und eine Menü-Playlist hinter den Titeln
    (menu_group_playlist) sowie ein eigenes Menü-Objekt. keep_page: Gruppe mit Startseite (Seite merken).
    menu_resume=False: Menü-Objekte ohne resume_intention (Test zu 11.2.5).
    title_ends (v1.18): {Titel: Befehle am Filmende} für Filme, die nicht im Hauptmenü enden, ab v1.18.1 auch die
    Nummer des nächsten Titels; first_play_title (v1.18.1): Film vor dem Menü (beides vom Export-Adapter).
    with_2d_choice (v1.20): Disc mit 2D-Wahl, die 3D-Titel schalten nach GPR 16 (Buttons mit play_2d).
    Ohne diese Angaben byte-gleich.

    Injiziert das HDMV-Menü in eine bestehende BDMV-Verzeichnisstruktur (z. B. nach tsMuxeR-Export):
    1. BDMV/PLAYLIST/00000.mpls (Hauptfilm) wird zu 00001.mpls umbenannt.
    2. Menü-Hintergrundvideo wird als 00001.m2ts & 00001.clpi abgelegt.
    3. Menü-IGS-SubClip wird als 00002.m2ts & 00002.clpi abgelegt.
    4. Menü-Playlist wird als 00000.mpls mit SubPath Typ 2 erzeugt.
    5. index.bdmv und MovieObject.bdmv werden mit HDMV-Opcodes geschrieben.
    6. Backup-Dateien in BDMV/BACKUP/ werden aktualisiert.

    background_renderer ersetzt render_background_video (gleiche Parameter). Nur für die Simulation
    aus dem Projekt (modules/sim_disc.py), die ohne ffmpeg und tsMuxeR einen Platzhalter-Clip schreibt.
    """
    if background_renderer is None:
        background_renderer = render_background_video
    if menu_groups:
        pages_specs = menu_groups[0]["pages_specs"]
    # Projekt-Parameter synchronisieren
    if project is not None:
        if bg_video_path is None:
            bg_video_path = getattr(project, "menu_bg_video", None)
        if bg_audio_path is None:
            bg_audio_path = getattr(project, "menu_bg_audio", None)
        if bg_image_path is None:
            bg_image_path = getattr(project, "menu_bg_image", None)
        if duration_sec == 30.0 or duration_sec == 10.0:
            duration_sec = float(getattr(project, "menu_duration", 30.0))

    # Falls ein Video (.264) übergeben wurde, dessen tatsächliche Dauer ermitteln
    if bg_video_path and os.path.exists(bg_video_path):
        probed_dur = probe_media_duration(bg_video_path, fps=fps)
        if probed_dur and probed_dur >= 2.0:
            duration_sec = probed_dur
    elif bg_audio_path and os.path.exists(bg_audio_path) and not bg_image_path:
        probed_dur = probe_media_duration(bg_audio_path, fps=fps)
        if probed_dur and probed_dur >= 2.0:
            duration_sec = probed_dur

    stream_dir = os.path.join(bdmv_dir, "STREAM")
    clipinf_dir = os.path.join(bdmv_dir, "CLIPINF")
    playlist_dir = os.path.join(bdmv_dir, "PLAYLIST")
    backup_dir = os.path.join(bdmv_dir, "BACKUP")
    backup_pl_dir = os.path.join(backup_dir, "PLAYLIST")
    backup_clip_dir = os.path.join(backup_dir, "CLIPINF")
    auxdata_dir = os.path.join(bdmv_dir, "AUXDATA")
    bdjo_dir = os.path.join(bdmv_dir, "BDJO")
    jar_dir = os.path.join(bdmv_dir, "JAR")
    meta_dir = os.path.join(bdmv_dir, "META")

    disc_root = os.path.dirname(os.path.abspath(bdmv_dir))
    cert_dir = os.path.join(disc_root, "CERTIFICATE", "BACKUP")

    for d in [stream_dir, clipinf_dir, playlist_dir, backup_dir, backup_pl_dir, backup_clip_dir,
              auxdata_dir, bdjo_dir, jar_dir, meta_dir, cert_dir]:
        os.makedirs(d, exist_ok=True)

    # 3D-Erkennung für Disc Master-Index (SS_content_exist_flag)
    has_3d = False
    if project is not None:
        has_3d = any(bool(getattr(t, "video_mvc", None)) for t in getattr(project, "titles", [])) or bool(getattr(project, "video_mvc", None))
    if not has_3d:
        ssif_dir = os.path.join(stream_dir, "SSIF")
        if os.path.exists(ssif_dir) and any(f.lower().endswith(".ssif") for f in os.listdir(ssif_dir)):
            has_3d = True

    # Clip-IDs für Menü bestimmen:
    # Falls 00001.m2ts bereits existiert (z. B. MVC-Stream von Titel 1), darf es NICHT überschrieben werden!
    t1_is_3d = False
    if project is not None:
        t0 = getattr(project, "titles", [None])[0] if getattr(project, "titles", []) else project
        t1_is_3d = bool(getattr(t0, "video_mvc", None))
    if not t1_is_3d and os.path.exists(os.path.join(stream_dir, "00001.m2ts")):
        t1_is_3d = True

    if t1_is_3d:
        bg_clip_id = "00002"
        igs_clip_id = "00003"
    else:
        bg_clip_id = "00001"
        igs_clip_id = "00002"

    # 1. Hauptfilm-Playlist 00000.mpls -> 00001.mpls verschieben (falls vorhanden)
    orig_pl_0 = os.path.join(playlist_dir, "00000.mpls")
    target_pl_1 = os.path.join(playlist_dir, "00001.mpls")
    if os.path.exists(orig_pl_0):
        if os.path.exists(target_pl_1):
            os.remove(target_pl_1)
        os.rename(orig_pl_0, target_pl_1)

    # 2. Menü-Hintergrundvideo (bg_clip_id.m2ts & bg_clip_id.clpi)
    m2ts_bg = os.path.join(stream_dir, f"{bg_clip_id}.m2ts")
    clpi_bg = os.path.join(clipinf_dir, f"{bg_clip_id}.clpi")
    background_renderer(
        bg_image_path=bg_image_path,
        output_m2ts_path=m2ts_bg,
        output_clpi_path=clpi_bg,
        duration_sec=duration_sec,
        fps=fps,
        bg_video_path=bg_video_path,
        bg_audio_path=bg_audio_path
    )

    # Exakten Start-PTS und Dauer aus dem tatsächlich gemuxten clpi ermitteln
    pts_start_45k, pts_end_45k = get_clpi_stc_range(clpi_bg)
    if pts_end_45k > pts_start_45k:
        duration_sec = (pts_end_45k - pts_start_45k) / 45000.0

    no_buttons = bool(getattr(project, "menu_no_buttons_test", False)) if project is not None else False

    # 3. Menü-IGS-SubClip (igs_clip_id.m2ts & igs_clip_id.clpi)
    # Falls ein project übergeben wurde, automatisch alle Seiten bauen und num_titles ermitteln
    if project is not None:
        if pages_specs is None:
            pages_specs = build_project_menu_pages(project)
        if num_titles == 1:
            valid_titles = [t for t in getattr(project, "titles", []) if getattr(t, "video_base", None)]
            if len(valid_titles) > 1:
                num_titles = len(valid_titles)

    # 3D-Titel bestimmen (wird für Kapitel-Einstiegsobjekte und MovieObject.bdmv benötigt)
    titles_3d = []
    if project is not None:
        titles_list = getattr(project, "titles", [])
        if titles_list:
            for idx, t in enumerate(titles_list, start=1):
                if bool(getattr(t, "video_mvc", None)):
                    titles_3d.append(idx)
        elif bool(getattr(project, "video_mvc", None)):
            titles_3d.append(1)
    if not titles_3d and has_3d:
        titles_3d.append(1)

    # Kapitel-Buttons auf die tatsächlich geschriebenen PlayListMarks abbilden
    chapter_titles: List[int] = []
    stream_titles: List[int] = []
    all_pages = list(pages_specs or []) + [p for g in (menu_groups or [])[1:] for p in g["pages_specs"]]
    if all_pages and not no_buttons:
        chapter_titles = resolve_chapter_jumps(all_pages, playlist_dir=playlist_dir)
        stream_titles = stream_choice_titles(all_pages)

    if not no_buttons:
        m2ts_igs = os.path.join(stream_dir, f"{igs_clip_id}.m2ts")
        clpi_igs = os.path.join(clipinf_dir, f"{igs_clip_id}.clpi")
        generate_menu_subclip(
            btn1_text=btn1_text,
            btn2_text=btn2_text,
            output_m2ts_path=m2ts_igs,
            output_clpi_path=clpi_igs,
            duration_sec=duration_sec,
            fps=fps,
            lang=lang,
            button_specs=button_specs,
            pages_specs=pages_specs,
            default_selected_id=default_selected_id,
            pts_start_45k=pts_start_45k
        )

    # 4. Menü-Playlist (00000.mpls)
    menu_mpls = os.path.join(playlist_dir, "00000.mpls")
    clpi_video_format = get_clpi_video_format_code(clpi_bg)
    if no_buttons:
        from modules.mpls.mpls_generator import build_movie_mpls
        menu_mpls_bytes = build_movie_mpls(
            clip_id=bg_clip_id,
            duration_sec=duration_sec,
            fps=fps,
            audio_pid=0x1100,
            lang=lang,
            pts_in=pts_start_45k,
            video_format=clpi_video_format
        )
        with open(menu_mpls, "wb") as f:
            f.write(menu_mpls_bytes)
    else:
        write_menu_mpls_file(
            menu_mpls,
            bg_clip_id=bg_clip_id,
            igs_clip_id=igs_clip_id,
            duration_sec=duration_sec,
            fps=fps,
            lang=lang,
            pts_in=pts_start_45k,
            subpath_type=3,
            video_format=clpi_video_format
        )

    # 5. Falls num_titles >= 2 und Ziel-Playlists noch nicht existieren (z. B. Test-Clips):
    for t in range(2, num_titles + 1):
        target_pl_t = os.path.join(playlist_dir, f"{t:05d}.mpls")
        if not os.path.exists(target_pl_t):
            from modules.mpls.mpls_generator import build_movie_mpls
            clip_id_str = f"{t+1:05d}"
            extra_m2ts = os.path.join(stream_dir, f"{clip_id_str}.m2ts")
            extra_clpi = os.path.join(clipinf_dir, f"{clip_id_str}.clpi")
            background_renderer(None, extra_m2ts, extra_clpi, duration_sec=5.0, fps=fps)
            extra_mpls_bytes = build_movie_mpls(clip_id=clip_id_str, duration_sec=5.0)
            with open(target_pl_t, "wb") as f:
                f.write(extra_mpls_bytes)

    # 5b. Weitere Menügruppen mit eigenem Hintergrund (v1.13)
    group_info = [(0, bool(menu_groups[0].get("keep_page")))] if menu_groups else None
    if menu_groups and not no_buttons:
        from modules.bdmv.movie_object_generator import menu_group_playlist
        for k, group in enumerate(menu_groups[1:], start=1):
            playlist_id = menu_group_playlist(num_titles, k)
            g_bg, g_igs = (f"{n:05d}" for n in _free_clip_ids(bdmv_dir, 2))
            g_video, g_audio, g_image = group.get("bg_video"), group.get("bg_audio"), group.get("bg_image")
            g_duration = float(group.get("duration") or 30.0)
            if g_video and os.path.exists(g_video):
                probed = probe_media_duration(g_video, fps=fps)
                if probed and probed >= 2.0:
                    g_duration = probed
            elif g_audio and os.path.exists(g_audio) and not g_image:
                probed = probe_media_duration(g_audio, fps=fps)
                if probed and probed >= 2.0:
                    g_duration = probed
            g_m2ts_bg = os.path.join(stream_dir, f"{g_bg}.m2ts")
            g_clpi_bg = os.path.join(clipinf_dir, f"{g_bg}.clpi")
            background_renderer(
                bg_image_path=g_image,
                output_m2ts_path=g_m2ts_bg,
                output_clpi_path=g_clpi_bg,
                duration_sec=g_duration,
                fps=fps,
                bg_video_path=g_video,
                bg_audio_path=g_audio
            )
            g_start, g_end = get_clpi_stc_range(g_clpi_bg)
            if g_end > g_start:
                g_duration = (g_end - g_start) / 45000.0
            generate_menu_subclip(
                output_m2ts_path=os.path.join(stream_dir, f"{g_igs}.m2ts"),
                output_clpi_path=os.path.join(clipinf_dir, f"{g_igs}.clpi"),
                duration_sec=g_duration,
                fps=fps,
                lang=lang,
                pages_specs=group["pages_specs"],
                pts_start_45k=g_start
            )
            write_menu_mpls_file(
                os.path.join(playlist_dir, f"{playlist_id:05d}.mpls"),
                bg_clip_id=g_bg,
                igs_clip_id=g_igs,
                duration_sec=g_duration,
                fps=fps,
                lang=lang,
                pts_in=g_start,
                subpath_type=3,
                video_format=get_clpi_video_format_code(g_clpi_bg)
            )
            group_info.append((playlist_id, bool(group.get("keep_page"))))

    # 6. Master-Navigation (index.bdmv & MovieObject.bdmv)
    index_file = os.path.join(bdmv_dir, "index.bdmv")
    mobj_file = os.path.join(bdmv_dir, "MovieObject.bdmv")

    write_index_bdmv_file(index_file, num_titles=num_titles, has_3d=has_3d)
    write_movie_object_file(
        mobj_file,
        num_titles=num_titles,
        auto_play_movie_after_menu=no_buttons,
        titles_3d=titles_3d,
        has_3d=has_3d,
        chapter_titles=chapter_titles,
        stream_titles=stream_titles,
        menu_groups=group_info,
        menu_resume=menu_resume,
        title_ends=None if no_buttons else title_ends,
        first_play_title=None if no_buttons else first_play_title,
        with_2d_choice=with_2d_choice and not no_buttons
    )

    # 7. Stream-Attribute nach BD-ROM Part 3 korrigieren (1080i / 25 fps)
    from modules.mux_engine import fix_1080i_stream_attributes
    fix_1080i_stream_attributes(bdmv_dir)

    # 8. Standard-konforme BACKUP-Kopien anlegen
    shutil.copy2(index_file, os.path.join(backup_dir, "index.bdmv"))
    shutil.copy2(mobj_file, os.path.join(backup_dir, "MovieObject.bdmv"))
    for pl_file in os.listdir(playlist_dir):
        if pl_file.lower().endswith(".mpls"):
            shutil.copy2(os.path.join(playlist_dir, pl_file), os.path.join(backup_pl_dir, pl_file))
    for clpi_file in os.listdir(clipinf_dir):
        if clpi_file.lower().endswith(".clpi"):
            shutil.copy2(os.path.join(clipinf_dir, clpi_file), os.path.join(backup_clip_dir, clpi_file))

    return True

def _free_clip_ids(bdmv_dir: str, count: int) -> List[int]:
    """
    Freie Clip-Nummern hinter allen vergebenen: in STREAM/CLIPINF vorhandene Clips und alle Clips, auf die eine
    Playlist verweist (auch die MVC-Clips von 3D-Filmen). So vergeben Export und Simulations-Disc (deren
    Film-Clips nur in den Playlists stehen) dieselben Nummern.
    """
    import re
    used = set()
    for sub, ext in (("STREAM", ".m2ts"), ("CLIPINF", ".clpi")):
        folder = os.path.join(bdmv_dir, sub)
        for name in os.listdir(folder) if os.path.isdir(folder) else []:
            if name.lower().endswith(ext) and name[:5].isdigit():
                used.add(int(name[:5]))
    playlist_dir = os.path.join(bdmv_dir, "PLAYLIST")
    for name in os.listdir(playlist_dir) if os.path.isdir(playlist_dir) else []:
        if name.lower().endswith(".mpls"):
            with open(os.path.join(playlist_dir, name), "rb") as f:
                used.update(int(m) for m in re.findall(rb"(\d{5})M2TS", f.read()))
    start = max(used) + 1 if used else 0
    return list(range(start, start + count))


def assemble_hdmv_disc_structure(
    output_dir: str,
    bg_image_path: Optional[str] = None,
    btn1_text: str = "FILM STARTEN",
    btn2_text: Optional[str] = None,
    duration_sec: float = 10.0,
    fps: float = 23.976,
    lang: str = "deu",
    num_titles: int = 1,
    button_specs: Optional[List[MenuButtonSpec]] = None,
    pages_specs: Optional[List[Tuple[int, List[MenuButtonSpec]]]] = None,
    project: Optional[object] = None,
    default_selected_id: int = 1
) -> bool:
    """
    Erstellt oder aktualisiert die komplette standardkonforme BDMV-Verzeichnisstruktur
    mit HDMV-Menü:
    - BDMV/index.bdmv & MovieObject.bdmv
    - BDMV/PLAYLIST/00000.mpls (Menü mit SubPath Typ 2)
    - BDMV/CLIPINF/00001.clpi (Hintergrund Video Info)
    - BDMV/CLIPINF/00002.clpi (Buttons IGS Info)
    - BDMV/STREAM/00001.m2ts (Hintergrund Video)
    - BDMV/STREAM/00002.m2ts (Buttons IGS SubClip)
    """
    bdmv_dir = os.path.join(output_dir, "BDMV")
    cert_dir = os.path.join(output_dir, "CERTIFICATE", "BACKUP")
    os.makedirs(bdmv_dir, exist_ok=True)
    os.makedirs(cert_dir, exist_ok=True)

    return inject_menu_into_bdmv(
        bdmv_dir=bdmv_dir,
        bg_image_path=bg_image_path,
        btn1_text=btn1_text,
        btn2_text=btn2_text,
        duration_sec=duration_sec,
        fps=fps,
        lang=lang,
        num_titles=num_titles,
        button_specs=button_specs,
        pages_specs=pages_specs,
        project=project,
        default_selected_id=default_selected_id
    )
