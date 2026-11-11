# modules/mpls/mpls_generator.py
"""
Generator für Blu-ray Playlist (.mpls) Dateien nach BD-ROM Part 3.

Erzeugt standardkonforme Playlists mit Out-of-Mux SubPath-Verknüpfung:
- MainPath: Hintergrund-Video (Clip 00000)
- SubPath (Typ 2): Interactive Graphics Presentation (Clip 00001)
- STN_table mit IGS-Zuordnung
"""

import struct
from typing import Optional

# BD-ROM Part 3: Video Attribute Byte = (video_format << 4) | frame_rate_code
# video_format: 4=1080i, 5=720p, 6=1080p, 7=576p
# frame_rate_code: 1=23.976, 2=24, 3=25, 4=29.97, 6=50, 7=59.94
_FPS_TO_RATE_CODE = {
    23.976: 1,
    24.0:   2,
    25.0:   3,
    29.97:  4,
    50.0:   6,
    59.94:  7,
}

def fps_to_bd_video_attr(fps: float, video_format: Optional[int] = None) -> int:
    """
    Gibt das kombinierte BD-ROM Video-Attribut-Byte zurück:
    - High-Nibble (bits 7-4): video_format  (6 = 1080p, 5 = 720p, 4 = 1080i)
    - Low-Nibble  (bits 3-0): frame_rate_code (1=23.976, 2=24, 3=25, 4=29.97, 6=50, 7=59.94)
    Unbekannte FPS-Werte fallen auf 23.976 zurück.

    BD-ROM Part 3 Standardregeln:
    - 25 fps ist bei 1080 Zeilen IMMER 1080i (video_format = 4, Code 0x43). 1080p25 existiert nicht!
    - 29.97 fps ist bei 1080 Zeilen 1080i (video_format = 4, Code 0x44).
    - 23.976 / 24.0 fps ist standardmäßig 1080p (video_format = 6, Code 0x61 / 0x62).
    - 50.0 / 59.94 fps: Wenn format nicht 720p (5), dann 1080i25/29.97 (Code 0x43/0x44).
    """
    # Nächsten bekannten FPS-Wert suchen (Toleranz 0.01)
    rate_code = 1  # Fallback: 23.976
    for known_fps, code in _FPS_TO_RATE_CODE.items():
        if abs(fps - known_fps) < 0.01:
            rate_code = code
            break

    if video_format is None:
        if abs(fps - 25.0) < 0.1:
            video_format = 4  # 1080i25 (50i / 25fps) -> 0x43
        elif abs(fps - 29.97) < 0.1:
            video_format = 4  # 1080i29.97 (60i / 29.97fps) -> 0x44
        elif abs(fps - 50.0) < 0.1:
            video_format = 4  # 1080i50
            rate_code = 3     # 25 fps nach BD-ROM Part 3
        elif abs(fps - 59.94) < 0.1:
            video_format = 4  # 1080i59.94
            rate_code = 4     # 29.97 fps nach BD-ROM Part 3
        else:
            video_format = 6  # 1080p (23.976 / 24.0)

    return ((video_format & 0x0F) << 4) | (rate_code & 0x0F)

# Feste Längen der STN-Einträge (wie tsMuxeR): stream_entry immer 9 Bytes,
# stream_attributes immer 5 Bytes, jeweils mit Nullen aufgefüllt. Ältere Player (Panasonic DMP-BDT111)
# lesen die Tabelle mit diesen festen Größen; mit kürzeren Einträgen brachen sie beim Einlegen ab.
STREAM_ENTRY_LEN = 9
STREAM_ATTR_LEN = 5

def _stream_entry(body: bytes) -> bytes:
    """stream_entry(): Länge + stream_type/Verweise/PID, aufgefüllt auf 9 Bytes."""
    return bytes([STREAM_ENTRY_LEN]) + body.ljust(STREAM_ENTRY_LEN, b"\x00")

def _stream_attributes(body: bytes) -> bytes:
    """stream_attributes(): Länge + coding_type/Format/Sprache, aufgefüllt auf 5 Bytes."""
    return bytes([STREAM_ATTR_LEN]) + body.ljust(STREAM_ATTR_LEN, b"\x00")

def build_menu_mpls(
    bg_clip_id: str = "00000",
    igs_clip_id: str = "00001",
    duration_sec: float = 10.0,
    fps: float = 23.976,
    video_pid: int = 0x1011,
    igs_pid: int = 0x1400,
    audio_pid: Optional[int] = 0x1100,
    lang: str = "deu",
    pts_in: int = 27000000,
    subpath_type: int = 3,
    video_format: Optional[int] = None
) -> bytes:
    """
    Erzeugt eine standardkonforme 00000.mpls Menü-Playlist mit Out-of-Mux SubPath.
    - bg_clip_id: 5-stellige Clip-ID des Hintergrundvideos (z.B. "00000")
    - igs_clip_id: 5-stellige Clip-ID des IGS-SubClips (z.B. "00001")
    - duration_sec: Menü-Dauer in Sekunden
    - audio_pid: PID der Menü-Audiospur (z.B. 0x1100 für lautlosen AC3/Stereo-Ton)
    - pts_in: Start-PTS im 45-kHz-Takt (Standard: 27000000 = 10 Min; dynamisch aus 00001.clpi)
    - subpath_type: BD-ROM SubPath-Typ (Standard: 3 = Interactive Graphics Menu)
    """
    pts_out = pts_in + int(duration_sec * 45000)

    # 1. APP INFO PLAYLIST (14 Bytes nach BD-ROM Part 3 Section 5.3.2)
    app_info = bytearray()
    app_info.append(0) # reserved
    app_info.append(1) # playback_type = 1 (Sequential Playback nach BD-ROM Part 3; Typ 2 ist Random und verbietet SubPaths!)
    app_info.extend(struct.pack(">H", 0)) # playback_count = 0 (nur für Random/Shuffle)
    app_info.extend(b"\x00" * 8) # uo_mask = 0 (keine Einschränkungen)
    app_info.extend(struct.pack(">H", 0)) # flags
    app_info_payload = struct.pack(">I", len(app_info)) + bytes(app_info)

    # 2. PLAYLIST
    # --- STN Table ---
    stn_data = bytearray()
    stn_data.extend(struct.pack(">H", 0)) # reserved
    stn_data.append(1) # num_video = 1
    stn_data.append(1 if audio_pid else 0) # num_audio (1 für Hardware-Kompatibilität!)
    stn_data.append(0) # num_pg = 0
    stn_data.append(1) # num_ig = 1 (Out-of-Mux SubPath!)
    stn_data.append(0) # num_secondary_audio = 0
    stn_data.append(0) # num_secondary_video = 0
    stn_data.append(0) # num_pip_pg = 0
    stn_data.append(0) # num_dv = 0
    stn_data.extend(b"\x00" * 4) # reserved

    # Video Stream Entry (PID 0x1011)
    # Stream-Type 1 = In-Mux PlayItem
    stn_data.extend(_stream_entry(bytes([1]) + struct.pack(">H", video_pid)))
    # Stream Attributes: 0x1B (H.264), video format 1080p (6), frame rate dynamisch
    stn_data.extend(_stream_attributes(bytes([0x1B, fps_to_bd_video_attr(fps, video_format=video_format)])))

    # Audio Stream Entry (PID 0x1100 falls vorhanden)
    if audio_pid:
        stn_data.extend(_stream_entry(bytes([1]) + struct.pack(">H", audio_pid)))
        # Stream Attributes: 0x81 (AC-3), stereo (0x30) + 48kHz (0x01) = 0x31
        lang_bytes = lang.encode("ascii")[:3].ljust(3, b"\x00")
        stn_data.extend(_stream_attributes(bytes([0x81, 0x31]) + lang_bytes))

    # Interactive Graphics Stream Entry (PID 0x1400)
    # Stream-Type 2 = Out-of-Mux SubPath Stream (ref_to_sub_path_id = 0, ref_to_sub_clip_entry_id = 0)
    stn_data.extend(_stream_entry(bytes([2, 0, 0]) + struct.pack(">H", igs_pid)))
    # Stream Attributes: coding_type 0x91 (Interactive Graphics) + Sprache
    lang_bytes = lang.encode("ascii")[:3].ljust(3, b"\x00")
    stn_data.extend(_stream_attributes(bytes([0x91]) + lang_bytes))

    stn_payload = struct.pack(">H", len(stn_data)) + bytes(stn_data)

    # --- PlayItem 0 (Hintergrund-Video) ---
    pi_data = bytearray()
    pi_data.extend(bg_clip_id.encode("ascii")[:5].ljust(5, b"0"))
    pi_data.extend(b"M2TS")
    # reserved (11b) + is_multi_angle (1b) + connection_condition (4b) = 0x0001
    pi_data.extend(struct.pack(">H", 0x0001))
    pi_data.append(0) # stc_id = 0
    pi_data.extend(struct.pack(">II", pts_in, pts_out))
    pi_data.extend(b"\x00" * 8) # uo_mask
    pi_data.append(0) # random_access_flag = 0 (Standard nach tsMuxeR)
    pi_data.append(0) # still_mode = 0
    pi_data.extend(struct.pack(">H", 0)) # still_time = 0
    pi_data.extend(stn_payload)
    pi_payload = struct.pack(">H", len(pi_data)) + bytes(pi_data)

    # --- SubPath 0 (Interactive Graphics Presentation) ---
    # SubPlayItem 0 (Preloaded IGS Stream nach BD-ROM Part 3)
    spi_data = bytearray()
    spi_data.extend(igs_clip_id.encode("ascii")[:5].ljust(5, b"0"))
    spi_data.extend(b"M2TS")
    # reserved (27b) + connection_condition (4b=1) + is_multi_clip (1b=0)
    spi_data.extend(struct.pack(">I", 0x00000002))
    spi_data.append(0) # stc_id = 0
    # Preloaded SubPlayItem Dauer: Exakt 1 Frame im 45-kHz-Takt (z.B. 1876 Ticks für 23.976/24fps)
    frame_ticks = int(45000.0 / fps) if fps > 0 else 1876
    sub_pts_out = pts_in + frame_ticks
    spi_data.extend(struct.pack(">II", pts_in, sub_pts_out))
    # sync_play_item_id = 0, sync_start_pts = 0 (Preload vor PlayItem 0 Start nach BD-ROM Part 3!)
    spi_data.extend(struct.pack(">HI", 0, 0))
    spi_payload = struct.pack(">H", len(spi_data)) + bytes(spi_data)

    # SubPath Header
    sub_data = bytearray()
    sub_data.append(0) # reserved
    sub_data.append(subpath_type) # subpath_type = 3 (Interactive Graphics presentation path for menus nach BD-ROM Part 3!)
    # reserved (15b) + is_repeat (1b=0 für Preload! Nicht loopen, da Grafik im Decoder-Puffer verbleibt)
    sub_data.extend(struct.pack(">H", 0x0000))
    sub_data.append(0) # reserved
    sub_data.append(1) # num_sub_play_items = 1
    sub_data.extend(spi_payload)
    sub_payload = struct.pack(">I", len(sub_data)) + bytes(sub_data)

    # Gesamt-Playlist-Block
    pl_data = bytearray()
    pl_data.extend(struct.pack(">H", 0)) # reserved
    pl_data.extend(struct.pack(">HH", 1, 1)) # num_play_items = 1, num_sub_paths = 1
    pl_data.extend(pi_payload)
    pl_data.extend(sub_payload)
    playlist_payload = struct.pack(">I", len(pl_data)) + bytes(pl_data)

    # 3. PLAYLIST MARK
    mark_data = bytearray()
    mark_data.extend(struct.pack(">H", 1)) # num_marks = 1
    # Mark 0: Chapter / Entry Point
    mark_data.append(0) # reserved
    mark_data.append(1) # mark_type = 1 (Entry mark)
    mark_data.extend(struct.pack(">H", 0)) # play_item_ref = 0
    mark_data.extend(struct.pack(">I", pts_in)) # mark_time_stamp
    mark_data.extend(struct.pack(">HI", 0xFFFF, 0)) # entry_es_pid, duration
    mark_payload = struct.pack(">I", len(mark_data)) + bytes(mark_data)

    # OFFSETS BERECHNEN
    # BD-ROM Part 3, Section 5.3.2 / 5.3.3 - MPLS Header Layout (40 Bytes):
    # Byte  0.. 7: Type Indicator (MPLS0200)
    # Byte  8..11: PlayList_start_address
    # Byte 12..15: PlayListMark_start_address
    # Byte 16..19: ExtensionData_start_address (0 = nicht vorhanden)
    # Byte 20..39: Reserved (20 Bytes)
    # Byte 40..  : AppInfoPlayList (feste Startadresse 40)
    header_len = 40
    app_info_offset = header_len                              # = 40
    playlist_offset = app_info_offset + len(app_info_payload)
    mark_offset = playlist_offset + len(playlist_payload)
    extension_data_offset = 0  # nicht vorhanden

    # HEADER (40 Bytes)
    header = bytearray()
    header.extend(b"MPLS0200")
    header.extend(struct.pack(">III", playlist_offset, mark_offset, extension_data_offset))
    header.extend(b"\x00" * 20) # 20 Bytes Reserved (= 8 Magic + 3*4 Offsets + 20 Reserved = 40 Bytes)

    return bytes(header) + app_info_payload + playlist_payload + mark_payload

def write_menu_mpls_file(
    output_path: str,
    bg_clip_id: str = "00000",
    igs_clip_id: str = "00001",
    duration_sec: float = 10.0,
    fps: float = 23.976,
    video_pid: int = 0x1011,
    audio_pid: Optional[int] = 0x1100,
    igs_pid: int = 0x1400,
    lang: str = "deu",
    pts_in: int = 27000000,
    subpath_type: int = 3,
    video_format: Optional[int] = None
):
    """Schreibt eine .mpls Menü-Playlist auf die Festplatte."""
    mpls_bytes = build_menu_mpls(
        bg_clip_id=bg_clip_id,
        igs_clip_id=igs_clip_id,
        duration_sec=duration_sec,
        fps=fps,
        video_pid=video_pid,
        audio_pid=audio_pid,
        igs_pid=igs_pid,
        lang=lang,
        pts_in=pts_in,
        subpath_type=subpath_type,
        video_format=video_format
    )
    with open(output_path, "wb") as f:
        f.write(mpls_bytes)

def build_movie_mpls(
    clip_id: str = "00000",
    duration_sec: float = 10.0,
    fps: float = 23.976,
    video_pid: int = 0x1011,
    audio_pid: Optional[int] = None,
    lang: str = "deu",
    pts_in: int = 27000000,
    video_format: Optional[int] = None
) -> bytes:
    """
    Erzeugt eine einfache Movie-Playlist (.mpls) ohne SubPath für Hauptfilm oder Extras.
    Unterstützt optional eine Audiospur (z. B. für Intro-/Menü-Hintergrundton).
    """
    pts_out = pts_in + int(duration_sec * 45000)

    # 1. APP INFO PLAYLIST (14 Bytes nach BD-ROM Part 3 Section 5.3.2)
    app_info = bytearray()
    app_info.append(0) # reserved
    app_info.append(1) # playback_type = 1 (Sequential)
    app_info.extend(struct.pack(">H", 0)) # reserved
    app_info.extend(b"\x00" * 8) # uo_mask
    app_info.extend(struct.pack(">H", 0)) # flags
    app_info_payload = struct.pack(">I", len(app_info)) + bytes(app_info)

    # 2. PLAYLIST
    stn_data = bytearray()
    stn_data.extend(struct.pack(">H", 0)) # reserved
    stn_data.append(1) # num_video = 1
    stn_data.append(1 if audio_pid else 0) # num_audio
    stn_data.append(0) # num_pg = 0
    stn_data.append(0) # num_ig = 0
    stn_data.append(0) # num_secondary_audio = 0
    stn_data.append(0) # num_secondary_video = 0
    stn_data.append(0) # num_pip_pg = 0
    stn_data.append(0) # num_dv = 0
    stn_data.extend(b"\x00" * 4) # reserved

    # Video Stream Entry (PID 0x1011)
    stn_data.extend(_stream_entry(bytes([1]) + struct.pack(">H", video_pid)))
    # format 6 (1080p) + rate aus Projekt-FPS
    stn_data.extend(_stream_attributes(bytes([0x1B, fps_to_bd_video_attr(fps, video_format=video_format)])))

    # Audio Stream Entry (PID audio_pid falls vorhanden)
    if audio_pid:
        stn_data.extend(_stream_entry(bytes([1]) + struct.pack(">H", audio_pid)))
        lang_bytes = lang.encode("ascii")[:3].ljust(3, b"\x00")
        # coding_type = AC-3, format: stereo + 48kHz
        stn_data.extend(_stream_attributes(bytes([0x81, 0x31]) + lang_bytes))

    stn_payload = struct.pack(">H", len(stn_data)) + bytes(stn_data)

    # PlayItem 0
    pi_data = bytearray()
    pi_data.extend(clip_id.encode("ascii")[:5].ljust(5, b"0"))
    pi_data.extend(b"M2TS")
    pi_data.extend(struct.pack(">H", 0x0001))
    pi_data.append(0) # stc_id = 0
    pi_data.extend(struct.pack(">II", pts_in, pts_out))
    pi_data.extend(b"\x00" * 8)
    pi_data.append(0) # random_access_flag = 0
    pi_data.append(0)
    pi_data.extend(struct.pack(">H", 0))
    pi_data.extend(stn_payload)
    pi_payload = struct.pack(">H", len(pi_data)) + bytes(pi_data)

    # Gesamt-Playlist (1 PlayItem, 0 SubPaths)
    pl_data = bytearray()
    pl_data.extend(struct.pack(">H", 0))
    pl_data.extend(struct.pack(">HH", 1, 0)) # num_play_items = 1, num_sub_paths = 0
    pl_data.extend(pi_payload)
    playlist_payload = struct.pack(">I", len(pl_data)) + bytes(pl_data)

    # 3. PLAYLIST MARK
    mark_data = bytearray()
    mark_data.extend(struct.pack(">H", 1)) # num_marks = 1
    mark_data.append(0)
    mark_data.append(1)
    mark_data.extend(struct.pack(">H", 0))
    mark_data.extend(struct.pack(">I", pts_in))
    mark_data.extend(struct.pack(">HI", 0xFFFF, 0))
    mark_payload = struct.pack(">I", len(mark_data)) + bytes(mark_data)

    # OFFSETS
    header_len = 40
    app_info_offset = header_len
    playlist_offset = app_info_offset + len(app_info_payload)
    mark_offset = playlist_offset + len(playlist_payload)
    extension_data_offset = 0

    # HEADER (40 Bytes)
    header = bytearray()
    header.extend(b"MPLS0200")
    header.extend(struct.pack(">III", playlist_offset, mark_offset, extension_data_offset))
    header.extend(b"\x00" * 20)

    return bytes(header) + app_info_payload + playlist_payload + mark_payload
