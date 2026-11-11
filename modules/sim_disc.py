# modules/sim_disc.py
"""
Simulations-Disc: baut aus einem Projekt in Sekunden eine BDMV-Struktur für den Disc-Simulator –
ohne Muxen, ohne tsMuxeR und ohne ffmpeg.

Simuliert wird, was der Export erzeugt, kein Nachbau: Menü, index.bdmv und MovieObject.bdmv entstehen
mit inject_menu_into_bdmv und denselben Argumenten wie in export_disc (menu_injection_args). Ersetzt
wird nur, was tsMuxeR und ffmpeg liefern:
- Film-Playlists: Platzhalter nach dem Vorbild von tsMuxeR (Start-PTS 27000000, Kapitel als Marken
  0..n−1 bzw. eine Marke am Anfang, Spuren in der Spurtabelle, 3D-Erweiterung bei MVC). Nummern und
  Clip-IDs wie nach dem Muxen in export_disc. Die Clip-Dateien selbst gibt es nicht.
- Menü-Hintergrund: Platzhalter-Clip mit derselben Start-PTS und der Dauer in ganzen Bildern.
"""

import math
import os
import shutil
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from core.disc_adapter import build_export_plan, DiscExportError
from modules.disc_export import menu_injection_args, normalize_3d_fps
from modules.external_tools import find_tool, FFMPEG
from modules.mpls.clpi_generator import write_video_clpi_file
from modules.mpls.mpls_generator import _stream_entry, _stream_attributes, fps_to_bd_video_attr

PTS_START_45K = 27000000          # tsMuxeR beginnt jeden Clip bei 10 Minuten (45-kHz-Takt)
TICKS_PER_SECOND = 45000
VIDEO_PID = 0x1011
AUDIO_PID = 0x1100
PG_PID = 0x1200
DEFAULT_FILM_SECONDS = 600.0      # Filmdauer, wenn das Projekt sie nicht kennt

# coding_type der Tonspur nach Dateiendung (BD-ROM Part 3); unbekannt -> AC-3
_AUDIO_CODING = {".ac3": 0x81, ".dts": 0x82, ".thd": 0x83, ".truehd": 0x83, ".eac3": 0x84, ".ec3": 0x84,
                 ".dtshd": 0x86, ".wav": 0x80, ".pcm": 0x80}
_EXACT_FPS = {23.976: 24000 / 1001, 29.97: 30000 / 1001, 59.94: 60000 / 1001}


class NoMenuError(Exception):
    """Disc ohne Menü: Sie startet direkt den Film, im Simulator gibt es nichts durchzuklicken."""


@dataclass
class SimulationDisc:
    root: str                                # Disc-Wurzel (enthält BDMV)
    # Standbild des Menü-Hintergrunds je Menü-Playlist für das Simulator-Fenster (v1.13.2: je Menügruppe)
    menu_backgrounds: Dict[int, str] = field(default_factory=dict)

    @property
    def menu_background(self) -> Optional[str]:
        """Hintergrund des Hauptmenüs (Menü-Playlist 0)."""
        return self.menu_backgrounds.get(0)

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


def build_simulation_disc(project, dest: str) -> SimulationDisc:
    """Erzeugt die Simulations-Disc für ein DiscProject in dest (wird angelegt).
    DiscExportError mit den Preflight-Fehlern bzw. den Problemen des Export-Adapters (wie „Disc erstellen“),
    NoMenuError bei einer Disc ohne Menü."""
    from core.preflight import run_preflight, ERROR
    from modules.menu_author import inject_menu_into_bdmv
    from modules.mux_engine import fix_1080i_stream_attributes

    # fehlende Mediendateien stören hier nicht: Clips und Hintergründe sind Platzhalter (v1.17.0)
    errors = [issue.message for issue in run_preflight(project, check_files=False) if issue.level == ERROR]
    if errors:
        raise DiscExportError(errors)
    plan = build_export_plan(project)
    if plan.pages_specs is None:
        raise NoMenuError()
    state = plan.project_state
    normalize_3d_fps(state)

    bdmv = os.path.join(dest, "BDMV")
    for sub in ("PLAYLIST", "STREAM", "CLIPINF"):
        os.makedirs(os.path.join(bdmv, sub), exist_ok=True)
    films = {i: film for i, film in enumerate(project.films, start=1)}
    _write_film_playlists(state, films, os.path.join(bdmv, "PLAYLIST"))

    inject_menu_into_bdmv(bdmv_dir=bdmv, background_renderer=placeholder_background,
                          **menu_injection_args(state, plan.pages_specs))
    fix_1080i_stream_attributes(bdmv)
    return SimulationDisc(dest, _menu_backgrounds(plan, len(project.films)))


# ─────────────────────────────── Film-Playlists ───────────────────────────────

def _write_film_playlists(state, films: dict, playlist_dir: str):
    """Playlists und Clip-IDs wie nach dem Muxen in export_disc (mit Menü): Titel 1 als 00000.mpls
    (inject_menu_into_bdmv benennt sie in 00001.mpls um), Titel 2..N als 0000N.mpls."""
    titles = state.titles
    t1_is_3d = bool(titles and titles[0].video_mvc)
    if titles and titles[0].video_base:
        _write(os.path.join(playlist_dir, "00000.mpls"), _film_mpls(titles[0], films.get(1), "00000"))

    next_clip_id = 4 if t1_is_3d else 3
    for idx, title in enumerate(titles[1:], start=2):
        if not title.video_base:
            continue
        clip = f"{next_clip_id:05d}"
        next_clip_id += 2 if title.video_mvc else 1
        _write(os.path.join(playlist_dir, f"{idx:05d}.mpls"), _film_mpls(title, films.get(idx), clip))


def _film_mpls(title, film, clip_id: str) -> bytes:
    from modules.mpls.mpls_reader import parse_chapter_time
    details = (film.video_details if film is not None else None) or {}
    chapters = [s for s in (parse_chapter_time(c) for c in title.chapters) if s is not None]
    duration = float(details.get("duration_s") or 0.0) or max(DEFAULT_FILM_SECONDS, max(chapters, default=0.0) + 60.0)
    audio = [(_audio_coding(t.get("path", "")), t.get("lang", "und")) for t in title.audio_tracks]
    subtitles = [t.get("lang", "und") for t in title.subtitle_tracks]
    return build_film_mpls(clip_id, duration, title.fps, audio, subtitles, chapters or [0.0], bool(title.video_mvc))


def _audio_coding(path: str) -> int:
    return _AUDIO_CODING.get(os.path.splitext(path)[1].lower(), 0x81)


def _lang(code: str) -> bytes:
    return (code or "und").encode("ascii", "replace")[:3].ljust(3, b"\x00")


def build_film_mpls(clip_id: str, duration_sec: float, fps: float, audio: List[tuple], subtitles: List[str],
                    chapters_sec: List[float], is_3d: bool = False) -> bytes:
    """Film-Playlist wie von tsMuxeR: ein PlayItem, Spurtabelle mit festen Eintragsgrößen
    (Video 0x1011, Ton ab 0x1100, Untertitel ab 0x1200), Kapitel als Entry Marks, bei 3D eine
    ExtensionData mit ID1 = 2 (STN_table_SS)."""
    pts_in = PTS_START_45K
    pts_out = pts_in + int(duration_sec * TICKS_PER_SECOND)

    app_info = bytes([0, 1]) + struct.pack(">H", 0) + b"\x00" * 8 + struct.pack(">H", 0)
    app_info_payload = struct.pack(">I", len(app_info)) + app_info

    stn = bytearray(struct.pack(">H", 0))
    stn += bytes([1, len(audio), len(subtitles), 0, 0, 0, 0, 0]) + b"\x00" * 4
    stn += _stream_entry(bytes([1]) + struct.pack(">H", VIDEO_PID))
    stn += _stream_attributes(bytes([0x1B, fps_to_bd_video_attr(fps)]))
    for n, (coding, lang) in enumerate(audio):
        stn += _stream_entry(bytes([1]) + struct.pack(">H", AUDIO_PID + n))
        stn += _stream_attributes(bytes([coding, 0x31]) + _lang(lang))
    for n, lang in enumerate(subtitles):
        stn += _stream_entry(bytes([1]) + struct.pack(">H", PG_PID + n))
        stn += _stream_attributes(bytes([0x90]) + _lang(lang))
    stn_payload = struct.pack(">H", len(stn)) + bytes(stn)

    item = bytearray(clip_id.encode("ascii")[:5].ljust(5, b"0") + b"M2TS")
    item += struct.pack(">H", 0x0001) + bytes([0]) + struct.pack(">II", pts_in, pts_out)
    item += b"\x00" * 8 + bytes([0, 0]) + struct.pack(">H", 0) + stn_payload
    playlist = struct.pack(">H", 0) + struct.pack(">HH", 1, 0) + struct.pack(">H", len(item)) + bytes(item)
    playlist_payload = struct.pack(">I", len(playlist)) + playlist

    marks = bytearray(struct.pack(">H", len(chapters_sec)))
    for seconds in chapters_sec:
        marks += bytes([0, 1]) + struct.pack(">HI", 0, pts_in + int(round(seconds * TICKS_PER_SECOND)))
        marks += struct.pack(">HI", 0xFFFF, 0)
    mark_payload = struct.pack(">I", len(marks)) + bytes(marks)

    app_info_offset = 40
    playlist_offset = app_info_offset + len(app_info_payload)
    mark_offset = playlist_offset + len(playlist_payload)
    ext_offset = mark_offset + len(mark_payload) if is_3d else 0
    header = b"MPLS0200" + struct.pack(">III", playlist_offset, mark_offset, ext_offset) + b"\x00" * 20
    data = header + app_info_payload + playlist_payload + mark_payload
    if is_3d:
        data += _extension_data_3d()
    return data


def _extension_data_3d() -> bytes:
    """ExtensionData mit einem Eintrag ID1 = 2 / ID2 = 1 (STN_table_SS, hier ohne Inhalt).
    Kennzeichnet die Playlist als 3D, wie die MVC-Playlists von tsMuxeR."""
    block = struct.pack(">H", 0)                     # leere STN_table_SS
    block_start = 24                                 # ab Beginn der ExtensionData: Kopf 12 + 1 Eintrag 12
    body = struct.pack(">I", block_start) + b"\x00" * 3 + bytes([1])
    body += struct.pack(">HHII", 2, 1, block_start, len(block)) + block
    return struct.pack(">I", len(body)) + body


# ─────────────────────────────── Menü-Hintergrund ───────────────────────────────

def placeholder_background(bg_image_path, output_m2ts_path, output_clpi_path, duration_sec=30.0, fps=23.976,
                           bg_video_path=None, bg_audio_path=None) -> bool:
    """Ersatz für render_background_video: leerer Clip, Clip-Info mit Start-PTS 27000000 und der Dauer
    in ganzen Bildern (ffmpeg rundet die Menü-Dauer auf ganze Bilder auf)."""
    exact = _EXACT_FPS.get(round(fps, 3), fps)
    frames = max(1, math.ceil(duration_sec * fps - 1e-6))
    with open(output_m2ts_path, "wb") as f:
        f.write(b"\x00" * (192 * 32))
    write_video_clpi_file(output_clpi_path, num_packets=32, duration_sec=frames / exact, fps=fps)
    return True


def _menu_backgrounds(plan, num_titles: int) -> Dict[int, str]:
    """Standbilder für das Simulator-Fenster je Menü-Playlist (Gruppe 0 = 00000.mpls, weitere Gruppen
    wie im Export hinter den Titeln)."""
    from modules.bdmv.movie_object_generator import menu_group_playlist
    found = {}
    for group, info in enumerate(plan.menu_groups or []):
        image = menu_still(info.get("bg_image"), info.get("bg_video"))
        if image:
            found[menu_group_playlist(num_titles, group)] = image
    return found


def menu_still(image: Optional[str], video: Optional[str]) -> Optional[str]:
    """Hintergrundbild des Menüs, bei einem Menü-Video dessen erstes Bild (nur mit ffmpeg), sonst None."""
    if image and os.path.exists(image):
        return image
    if video and os.path.exists(video) and find_tool(FFMPEG):
        from modules.bdsim.graphics import extract_frame
        return extract_frame(video, 0.5)
    return None


def _write(path: str, data: bytes):
    with open(path, "wb") as f:
        f.write(data)
