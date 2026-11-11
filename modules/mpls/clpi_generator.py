# modules/mpls/clpi_generator.py
"""
Generator für Blu-ray Clip Information (.clpi) Dateien nach BD-ROM Part 3.

Erzeugt standardkonforme .clpi Dateien für:
- IGS-SubClips (00002.clpi)
- Hintergrund-Videos (00001.clpi)
- SequenceInfo, ProgramInfo und EP_map
"""

import struct
from modules.mpls.mpls_generator import fps_to_bd_video_attr

def build_ep_map(pid: int, ep_stream_type: int = 1, pts_start: int = 54000000) -> bytes:
    """
    Erzeugt Characteristic Point Information (CPI) / EP_map nach BD-ROM Part 3.
    """
    num_coarse = 1
    num_fine = 1
    start_addr = 14 # 2B Header + 12B Stream Entry = 14

    # 48-bit Block: reserved (10b) + ep_stream_type (4b) + num_ep_coarse (16b) + num_ep_fine (18b)
    mid = ((ep_stream_type & 0x0F) << 34) | ((num_coarse & 0xFFFF) << 18) | (num_fine & 0x3FFFF)
    stream_entry = struct.pack(">H", pid) + struct.pack(">Q", mid)[2:] + struct.pack(">I", start_addr)

    # An start_addr:
    fine_start = 12 # 4B Header + 1 * 8B Coarse = 12
    # Coarse Entry (8B): ref_ep_fine_id (18b), pts_ep_coarse (14b), spn_ep_coarse (32b)
    pts_coarse = (pts_start >> 19) & 0x3FFF
    coarse_mid = (0 << 14) | pts_coarse
    coarse_entry = struct.pack(">II", coarse_mid, 0)

    # Fine Entry (4B): is_angle_change (1b), i_end_position_offset (3b), pts_ep_fine (11b), spn_ep_fine (17b)
    pts_fine = (pts_start >> 8) & 0x7FF
    fine_val = pts_fine << 17
    fine_entry = struct.pack(">I", fine_val)

    ep_data = bytearray()
    ep_data.append(0) # reserved
    ep_data.append(1) # num_stream_pid = 1
    ep_data.extend(stream_entry)
    ep_data.extend(struct.pack(">I", fine_start))
    ep_data.extend(coarse_entry)
    ep_data.extend(fine_entry)
    return bytes(ep_data)

def build_igs_clpi(
    num_source_packets: int,
    duration_sec: float = 10.0,
    fps: float = 23.976,
    igs_pid: int = 0x1400,
    lang: str = "deu",
    pts_start_45k: int = 27000000,
    pcr_pid: int = 0x1400
) -> bytes:
    """
    Erzeugt eine standardkonforme .clpi Datei für einen preloaded IGS SubClip nach BD-ROM Part 3.
    - num_source_packets: Anzahl der 192-Byte M2TS-Pakete im SubClip
    - duration_sec: Dauer des Menü-Loops in Sekunden
    - fps: Framerate des Menü-Hintergrundvideos
    - igs_pid: PID der Interactive Graphics Spur (Standard: 0x1400)
    - lang: ISO 639-2 Sprachcode (z.B. "deu")
    - pts_start_45k: Start-PTS im 45-kHz-Takt (Standard: 27000000 = 10 Min; dynamisch aus 00001.clpi)
    - pcr_pid: PCR PID (Standard: 0x1400, exakt passend zur PMT des IGS M2TS-Streams)
    """
    # 1. CLIP INFO (176 Bytes Data nach BD-ROM Part 3, Section 5.4.2)
    clip_info_data = bytearray()
    clip_info_data.extend(struct.pack(">H", 0)) # 2 Bytes Reserved
    clip_info_data.append(1) # clip_stream_type = 1 (TS)
    clip_info_data.append(5) # application_type = 5 (SubTS for preloaded stream nach BD-ROM Part 3)
    clip_info_data.append(0) # is_atc_delta = 0
    clip_info_data.extend(b"\x00\x00\x00") # 24 bits Reserved
    clip_info_data.extend(struct.pack(">II", 6000000, num_source_packets)) # ts_recording_rate (6 Mbps Standard), num_source_packets
    clip_info_data.extend(b"\x00" * 128) # 128 Bytes Reserved nach Spezifikation!
    # ts_type_info_block (32 Bytes): length (2B=30), validity (1B=0x80), format_id (4B=b"HDMV"), reserved (25B)
    ts_type_info = struct.pack(">HB", 30, 0x80) + b"HDMV" + (b"\x00" * 25)
    clip_info_data.extend(ts_type_info)
    clip_info_payload = struct.pack(">I", len(clip_info_data)) + bytes(clip_info_data)

    # 2. SEQUENCE INFO nach BD-ROM Part 3, Section 5.4.4
    # Für Preloaded IGS SubClips läuft SequenceInfo synchron zum 1-Frame SubPlayItem (45-kHz-Takt):
    frame_ticks = int(45000.0 / fps) if fps > 0 else 1876
    pts_end_45k = pts_start_45k + frame_ticks

    seq_data = bytearray()
    seq_data.append(0) # 1 Byte Reserved (BD-ROM Part 3)
    seq_data.append(1) # num_atc_sequences = 1
    seq_data.extend(struct.pack(">I", 0)) # spn_atc_start = 0
    seq_data.append(1) # num_stc_sequences = 1
    seq_data.append(0) # offset_stc_id = 0
    seq_data.extend(struct.pack(">H", pcr_pid)) # pcr_pid (exakt passend zur PMT des IGS M2TS-Streams)
    seq_data.extend(struct.pack(">I", 0)) # spn_stc_start = 0
    seq_data.extend(struct.pack(">II", pts_start_45k, pts_end_45k)) # presentation_start, end (45 kHz: exakt 1 Frame!)
    seq_payload = struct.pack(">I", len(seq_data)) + bytes(seq_data)

    # 3. PROGRAM INFO (34 Bytes Data nach BD-ROM Part 3)
    prog_data = bytearray()
    prog_data.append(0) # 1 Byte Reserved
    prog_data.append(1) # num_program_sequences = 1
    prog_data.extend(struct.pack(">IH", 0, 0x0100)) # spn_start = 0, pmt_pid = 0x0100
    prog_data.append(1) # num_streams = 1
    prog_data.append(0) # num_groups = 0 (wichtig für BD-ROM Parsing!)

    # Stream 0: IGS auf PID 0x1400 (attr_len = 21, coding_type 0x91, 3B Sprache, 1B Reserved, 12B ISRC, 4B Padding)
    lang_bytes = lang.encode("ascii")[:3].ljust(3, b"\x00")
    isrc_bytes = b"000000000000"
    stream_attr = struct.pack(">B", 0x91) + lang_bytes + b"\x00" + isrc_bytes + (b"\x00" * 4)
    stream_entry = struct.pack(">HB", igs_pid, len(stream_attr)) + stream_attr
    prog_data.extend(stream_entry)
    prog_payload = struct.pack(">I", len(prog_data)) + bytes(prog_data)

    # 4. CPI (Characteristic Point Information / EP_map)
    # Preloaded Asynchronous SubClips haben keine EP_map (cpi_length = 0 nach BD-ROM Part 3)
    cpi_payload = struct.pack(">I", 0)

    # 5. CLIP MARK
    clip_mark_payload = struct.pack(">I", 0)

    # OFFSETS BERECHNEN
    header_len = 40
    clip_info_offset = header_len
    seq_offset = clip_info_offset + len(clip_info_payload)
    prog_offset = seq_offset + len(seq_payload)
    cpi_offset = prog_offset + len(prog_payload)
    mark_offset = cpi_offset + len(cpi_payload)

    # HEADER (40 Bytes)
    header = bytearray()
    header.extend(b"HDMV0200")
    header.extend(struct.pack(">IIIII", seq_offset, prog_offset, cpi_offset, mark_offset, 0))
    header.extend(b"\x00" * 12)

    return bytes(header) + clip_info_payload + seq_payload + prog_payload + cpi_payload + clip_mark_payload

def write_clpi_file(
    output_path: str,
    num_packets: int,
    duration_sec: float = 10.0,
    fps: float = 23.976,
    lang: str = "deu",
    pts_start_45k: int = 27000000,
    pcr_pid: int = 0x1400
):
    """Schreibt eine .clpi Datei für IGS auf die Festplatte."""
    clpi_bytes = build_igs_clpi(
        num_packets,
        duration_sec=duration_sec,
        fps=fps,
        lang=lang,
        pts_start_45k=pts_start_45k,
        pcr_pid=pcr_pid
    )
    with open(output_path, "wb") as f:
        f.write(clpi_bytes)

def build_video_clpi(
    num_source_packets: int,
    duration_sec: float = 10.0,
    fps: float = 23.976,
    video_pid: int = 0x1011
) -> bytes:
    """
    Erzeugt eine vollständige, gültige .clpi Datei für einen H.264 Hintergrund-Video Clip.
    - num_source_packets: Anzahl der 192-Byte M2TS-Pakete
    - duration_sec: Dauer des Menü-Loops in Sekunden
    - video_pid: PID der Videospur (Standard: 0x1011)
    """
    pts_start = 54000000 # 10 Minuten bei 90 kHz
    pts_duration = int(duration_sec * 90000)
    pts_end = pts_start + pts_duration

    # 1. CLIP INFO
    clip_info_data = bytearray()
    clip_info_data.extend(struct.pack(">H", 0))
    clip_info_data.append(1) # clip_stream_type = 1 (TS)
    clip_info_data.append(1) # application_type = 1 (Main TS)
    clip_info_data.append(0) # is_atc_delta = 0
    clip_info_data.extend(b"\x00\x00\x00")
    clip_info_data.extend(struct.pack(">II", 48000000, num_source_packets))
    clip_info_data.extend(b"\x00" * 32)
    clip_info_payload = struct.pack(">I", len(clip_info_data)) + bytes(clip_info_data)

    # 2. SEQUENCE INFO nach BD-ROM Part 3, Section 5.4.4
    pts_start_45k = 27000000 # 10 Minuten bei 45 kHz
    pts_end_45k = pts_start_45k + int(duration_sec * 45000)

    seq_data = bytearray()
    seq_data.append(0) # 1 Byte Reserved
    seq_data.append(1) # num_atc_sequences = 1
    seq_data.extend(struct.pack(">I", 0)) # spn_atc_start = 0
    seq_data.append(1) # num_stc_sequences = 1
    seq_data.append(0) # offset_stc_id = 0
    seq_data.extend(struct.pack(">H", video_pid)) # pcr_pid
    seq_data.extend(struct.pack(">I", 0)) # spn_stc_start = 0
    seq_data.extend(struct.pack(">II", pts_start_45k, pts_end_45k)) # presentation_start, end (45 kHz)
    seq_payload = struct.pack(">I", len(seq_data)) + bytes(seq_data)

    # 3. PROGRAM INFO
    prog_data = bytearray()
    prog_data.append(0)
    prog_data.append(1)
    prog_data.extend(struct.pack(">IH", 0, 0x0100))
    prog_data.append(1)
    prog_data.append(0) # num_groups = 0

    # Stream 0: H.264 Video auf PID 0x1011, Attributbyte dynamisch nach fps
    stream_entry = struct.pack(">HB", video_pid, 5) + struct.pack(">BB", 0x1B, fps_to_bd_video_attr(fps)) + b"\x00\x00\x00"
    prog_data.extend(stream_entry)
    prog_payload = struct.pack(">I", len(prog_data)) + bytes(prog_data)

    # 4. CPI (Characteristic Point Information / EP_map)
    cpi_data = bytearray()
    cpi_data.extend(struct.pack(">H", 0x0001))
    cpi_data.extend(build_ep_map(video_pid, ep_stream_type=1, pts_start=pts_start))
    cpi_payload = struct.pack(">I", len(cpi_data)) + bytes(cpi_data)

    # 5. CLIP MARK
    clip_mark_payload = struct.pack(">I", 0)

    # OFFSETS BERECHNEN
    header_len = 40
    clip_info_offset = header_len
    seq_offset = clip_info_offset + len(clip_info_payload)
    prog_offset = seq_offset + len(seq_payload)
    cpi_offset = prog_offset + len(prog_payload)
    mark_offset = cpi_offset + len(cpi_payload)

    # HEADER (40 Bytes)
    header = bytearray()
    header.extend(b"HDMV0200")
    header.extend(struct.pack(">IIIII", seq_offset, prog_offset, cpi_offset, mark_offset, 0))
    header.extend(b"\x00" * 12)

    return bytes(header) + clip_info_payload + seq_payload + prog_payload + cpi_payload + clip_mark_payload

def write_video_clpi_file(output_path: str, num_packets: int, duration_sec: float = 10.0, fps: float = 23.976, video_pid: int = 0x1011):
    """Schreibt eine .clpi Datei für Video auf die Festplatte."""
    clpi_bytes = build_video_clpi(num_packets, duration_sec=duration_sec, fps=fps, video_pid=video_pid)
    with open(output_path, "wb") as f:
        f.write(clpi_bytes)
