#!/usr/bin/env python3
# tools/ig_test_disc.py
"""
Test-Disc für die Meldung „Menü ohne Buttons“ (Samsung BD-E5300), Plan docs/plaene/ig-timing.md.

Baut über den normalen Export eine Disc mit sechs Menügruppen („Variante 1“ … „Variante 6“, je zwei Seiten, also mit
unsichtbarer Startseite 0) und ändert danach die Menü-Clips so, dass jede Variante genau einen Punkt anders macht:

  1  wie OpenBDAuth heute (Gegenprobe)
  2  Startseite mit default_activated_button (Register-Operanden bleiben)
  3  Startseite mit SetButtonPage mit festen Werten (wie multiAVCHD)
  4  Zeitstempel nach dem Decodermodell (DTS/PTS je Segment, PCR 218 ms vor dem ersten DTS)
  5  Transport wie multiAVCHD (PCR auf eigener PID 0x1001, SIT, Copy-Control in der PMT)
  6  2, 4 und 5 zusammen

Die Disc schaltet die Varianten selbst durch: Jede Menü-Playlist läuft 20 s, danach springt das MovieObject zur
nächsten Variante, nach der letzten wieder zur ersten. Der Tester notiert nur, bei welchen Nummern Buttons erscheinen.

Nur für diesen Test (Branch test/ig-varianten); der Programmcode bleibt unverändert.

Aufruf:
    python tools/ig_test_disc.py <Ausgabeordner>
"""

import math
import os
import shutil
import struct
import subprocess
import sys
from typing import List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw

from core.disc_adapter import build_export_plan
from core.disc_edit import starter_project, add_film, add_menu, add_nav_button
from core.disc_model import ButtonStyle, Track, STYLE_TEXT
from modules.disc_export import export_disc
from modules.external_tools import find_tool, FFMPEG
from modules.fonts import load_subtitle_font
from modules.iso_tools import create_udf_iso
from modules.igs.pes import encode_pts
from modules.igs.segments import build_set_button_page_cmd
from modules.m2ts.m2ts_writer import add_tp_extra_header, DEFAULT_ATS_STEP
from modules.m2ts.ts_packetizer import build_pat_packet, build_pmt_packet, encode_pcr, mpeg2_crc32

VARIANTS = {
    1: "as today (control)",
    2: "start page: default_activated_button",
    3: "start page: SetButtonPage with fixed values",
    4: "time stamps per decoder model",
    5: "transport as in multiAVCHD (PCR PID, SIT, copy control)",
    6: "2 + 4 + 5 combined",
}
MENU_SECONDS = 20.0
IG_PID = 0x1400
PCR_PID_OWN = 0x1001
SIT_PID = 0x1F

# Raten aus der multiAVCHD-Referenz (docs/plaene/ig-timing.md)
ODS_PIXELS_PER_SECOND = 8_000_000           # 64 Mbit/s bei 8 bit pro Pixel
PLANE_TICKS = math.ceil(90000 * 8 * 1920 * 1080 / 128_000_000)   # 11 664: eine Grafikebene bei 128 Mbit/s
PCR_LEAD = 19_620                           # 218 ms (Referenz: PCR 9, erster DTS 19 628)

SEG_PDS, SEG_ODS, SEG_ICS, SEG_END = 0x14, 0x15, 0x18, 0x80


# ---------------------------------------------------------------------------------------------------------------
# 1. Projekt über den normalen Export bauen
# ---------------------------------------------------------------------------------------------------------------

def ff(*args):
    subprocess.run([find_tool(FFMPEG) or "ffmpeg", "-loglevel", "error", "-y", *args], check=True)


def background(path: str, number: int):
    img = Image.new("RGB", (1920, 1080), (24, 28, 40))
    draw = ImageDraw.Draw(img)
    # Nur Nummer und Hinweis: Die ISO geht an Tester und liegt danach öffentlich im Netz; was eine Variante ändert,
    # steht nur hier im Skript
    big = load_subtitle_font(150)
    text = f"Variant {number}"
    w = draw.textbbox((0, 0), text, font=big)[2]
    draw.text(((1920 - w) // 2, 140), text, font=big, fill=(240, 240, 240))
    draw.text((120, 960), "Buttons visible? Please note the number. The next variant follows after 20 seconds.",
              font=load_subtitle_font(36), fill=(170, 170, 170))
    img.save(path)


def build_project(media: str, disc: str):
    film_video = os.path.join(media, "film.264")
    ff("-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=24000/1001", "-t", "5", "-c:v", "libx264",
       "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p", "-x264-params", "keyint=24:min-keyint=1:bframes=0",
       "-bsf:v", "h264_mp4toannexb", "-f", "h264", film_video)
    film_audio = os.path.join(media, "film.ac3")
    ff("-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "5", "-ac", "2", "-c:a", "ac3",
       "-b:a", "192k", film_audio)

    graph = starter_project("de")
    graph.settings.project_name = "TEST_DISC"
    graph.settings.export_format = "folder"
    graph.settings.output_path = disc
    film = graph.films[0]
    film.name, film.video_base, film.fps = "Movie", film_video, 23.976
    film.audio_tracks = [Track(id="a1", path=film_audio, lang="deu")]

    menus = []
    for n in VARIANTS:
        image = os.path.join(media, f"variante{n}.png")
        background(image, n)
        if n == 1:
            menu = graph.main_menu
            menu.buttons = []
        else:
            menu = add_menu(graph, f"Variante {n}", (300.0, 200.0 * n))
            menu.buttons = []
        menu.name = f"Variante {n}"
        menu.button_style = ButtonStyle(kind=STYLE_TEXT)   # Buttons mit Text (Form-Buttons zeigen nur Striche)
        menu.background.image, menu.background.duration = image, MENU_SECONDS
        sub = add_menu(graph, f"Variante {n} Unterseite", (600.0, 200.0 * n))
        sub.buttons = []
        sub.button_style = ButtonStyle(kind=STYLE_TEXT)
        sub.background.image, sub.background.duration = image, MENU_SECONDS
        menus.append((menu, sub))

    for i, (menu, sub) in enumerate(menus):
        add_nav_button(graph, menu.id, "SUBPAGE", sub.id)
        add_nav_button(graph, menu.id, "MOVIE", film.id)
        if i + 1 < len(menus):
            add_nav_button(graph, menu.id, "NEXT", menus[i + 1][0].id)
        add_nav_button(graph, sub.id, "BACK", menu.id)
    film.end_target = menus[0][0].id

    plan = build_export_plan(graph)
    log: List[str] = []
    ok, msg = export_disc(plan.project_state, log.append, lambda p: None, plan.pages_specs)
    if not ok:
        print("\n".join(log[-30:]))
        raise SystemExit(f"Export fehlgeschlagen: {msg}")


# ---------------------------------------------------------------------------------------------------------------
# 2. IG-Clip lesen und neu schreiben
# ---------------------------------------------------------------------------------------------------------------

def _ts(b: bytes) -> int:
    return ((b[0] >> 1) & 7) << 30 | b[1] << 22 | (b[2] >> 1) << 15 | b[3] << 7 | b[4] >> 1


def read_ig_segments(m2ts: str) -> Tuple[List[Tuple[int, bytes]], int]:
    """Segmente (Typ, Nutzdaten) des IG-Stroms und der PTS des ersten PES."""
    data = open(m2ts, "rb").read()
    pes, cur = [], None
    for i in range(len(data) // 192):
        p = data[i * 192 + 4:(i + 1) * 192]
        if ((p[1] & 0x1F) << 8 | p[2]) != IG_PID:
            continue
        afc = (p[3] >> 4) & 3
        pos = 4 + (1 + p[4] if afc & 2 else 0)
        if (p[1] >> 6) & 1:
            if cur is not None:
                pes.append(cur)
            cur = bytearray(p[pos:])
        elif cur is not None:
            cur += p[pos:]
    if cur is not None:
        pes.append(cur)
    segments, first_pts = [], None
    for b in pes:
        length = struct.unpack(">H", b[4:6])[0]
        hl = b[8]
        if first_pts is None:
            first_pts = _ts(b[9:14])
        body = bytes(b[9 + hl:6 + length])
        q = 0
        while q + 3 <= len(body):
            seg_type, seg_len = body[q], struct.unpack(">H", body[q + 1:q + 3])[0]
            segments.append((seg_type, body[q + 3:q + 3 + seg_len]))
            q += 3 + seg_len
    return segments, first_pts


def pes_packet(segment: bytes, pts: int, dts: Optional[int] = None) -> bytes:
    """Ein PES (private_stream_1) mit einem Segment; mit dts zusätzlich DTS (Flags 0xC0)."""
    if dts is None:
        header = bytes([0x80, 0x80, 5]) + encode_pts(pts)
    else:
        p = bytearray(encode_pts(pts))
        d = bytearray(encode_pts(dts))
        p[0] = (p[0] & 0x0F) | 0x30          # Präfix 0011 vor dem PTS, wenn ein DTS folgt
        d[0] = (d[0] & 0x0F) | 0x10          # Präfix 0001 vor dem DTS
        header = bytes([0x80, 0xC0, 10]) + bytes(p) + bytes(d)
    return b"\x00\x00\x01\xBD" + struct.pack(">H", len(header) + len(segment)) + header + segment


def segment_bytes(seg_type: int, payload: bytes) -> bytes:
    return bytes([seg_type]) + struct.pack(">H", len(payload)) + payload


def _section_packet(pid: int, section_wo_crc: bytes) -> bytes:
    from modules.m2ts.ts_packetizer import make_ts_packet
    section = section_wo_crc + struct.pack(">I", mpeg2_crc32(section_wo_crc))
    return make_ts_packet(pid=pid, pusi=True, cc=0, payload=b"\x00" + section)


def transport_packets_multiavchd() -> List[bytes]:
    """PAT (Programm 0 → SIT, Programm 1 → PMT), PMT mit eigener PCR-PID und Copy-Control, SIT wie multiAVCHD."""
    progs = struct.pack(">HH", 0, 0xE000 | SIT_PID) + struct.pack(">HH", 1, 0xE000 | 0x0100)
    pat = bytes([0x00]) + struct.pack(">H", 0xB000 | (5 + len(progs) + 4)) + struct.pack(">HBBB", 1, 0xC1, 0, 0) + progs
    prog_info = bytes([0x05, 0x04]) + b"HDMV" + bytes([0x88, 0x04, 0x0F, 0xFF, 0xFC, 0xFC])
    es = struct.pack(">BHH", 0x91, 0xE000 | IG_PID, 0xF000)
    body = struct.pack(">HBBBHH", 1, 0xC1, 0, 0, 0xE000 | PCR_PID_OWN, 0xF000 | len(prog_info)) + prog_info + es
    pmt = bytes([0x02]) + struct.pack(">H", 0xB000 | (len(body) + 4)) + body
    # SIT aus der Referenz ohne CRC: partial_transport_stream_descriptor, Service 1
    sit_body = bytes.fromhex("ffffc10000f00a6308c1a49fffffffffff0001800069ec20c7")[:-4]
    sit = bytes([0x7F]) + struct.pack(">H", 0xF000 | (len(sit_body) + 4)) + sit_body
    return [_section_packet(0x0000, pat), _section_packet(0x0100, pmt), _section_packet(SIT_PID, sit)]


def pcr_only_packet(pid: int, pcr: int) -> bytes:
    """TS-Paket nur mit Adaptation Field und PCR (wie die Referenz auf PID 0x1001)."""
    af = bytes([0x10]) + encode_pcr(pcr) + b"\xFF" * (183 - 7)
    return bytes([0x47, (pid >> 8) & 0x1F, pid & 0xFF, 0x20, 183]) + af


def write_ig_m2ts(path: str, pes_list: List[bytes], pcr: int, multiavchd_transport: bool):
    from modules.m2ts.ts_packetizer import packetize_pes_to_ts
    packets: List[bytes] = []
    if multiavchd_transport:
        packets += transport_packets_multiavchd()
        packets.append(pcr_only_packet(PCR_PID_OWN, pcr))
        ig, _ = packetize_pes_to_ts(b"".join(pes_list), pid=IG_PID, start_cc=0, pcr_90khz=None)
    else:
        packets += [build_pat_packet(cc=0), build_pmt_packet(pcr_pid=IG_PID, igs_pid=IG_PID, cc=0)]
        ig, _ = packetize_pes_to_ts(b"".join(pes_list), pid=IG_PID, start_cc=0, pcr_90khz=pcr)
    packets += ig
    out, ats = bytearray(), 0
    for pkt in packets:
        out += add_tp_extra_header(pkt, ats=ats)
        ats = (ats + DEFAULT_ATS_STEP) & 0x3FFFFFFF
    null_ts = b"\x47\x1f\xff\x10" + b"\xff" * 184
    while len(out) % 6144:
        out += add_tp_extra_header(null_ts, ats=ats)
        ats = (ats + DEFAULT_ATS_STEP) & 0x3FFFFFFF
    with open(path, "wb") as f:
        f.write(out)


def patch_clpi(path: str, num_packets: int, pcr_pid: int):
    d = bytearray(open(path, "rb").read())
    seq = struct.unpack(">I", d[8:12])[0]
    struct.pack_into(">I", d, 56, num_packets)          # ClipInfo: number_of_source_packets
    struct.pack_into(">H", d, seq + 12, pcr_pid)        # SequenceInfo: PCR_PID
    with open(path, "wb") as f:
        f.write(d)


# ---------------------------------------------------------------------------------------------------------------
# 3. Varianten
# ---------------------------------------------------------------------------------------------------------------

def page0_offsets(ics_payload: bytes) -> Tuple[int, List[int]]:
    """Offsets im ICS-Segment: default_selected_button der Seite 0 und Beginn jedes Befehls ihres ersten Buttons."""
    from modules.bdsim.disc import _skip_effect_sequence
    base = 12                                         # video(5) + composition(3) + sequence(1) + data_length(3)
    d = ics_payload[base:]
    stream_model = d[0] >> 7
    q = 1 + (10 if stream_model == 0 else 0) + 3
    num_pages = d[q]
    q += 1
    assert num_pages >= 2 and d[q] == 0, "Startseite 0 erwartet"
    q += 2 + 8
    q = _skip_effect_sequence(d, q)
    q = _skip_effect_sequence(d, q)
    q += 1
    def_sel_at = base + q
    q += 4 + 1                                        # def_sel, def_act, palette
    q += 1 + 3                                        # num_bogs, erste BOG: default_valid(2) + num_buttons(1)
    q += 17 + 5 + 6 + 5                               # Button-Kopf, normal, selected, activated
    num_cmds = struct.unpack(">H", d[q:q + 2])[0]
    q += 2
    return def_sel_at, [base + q + 12 * k for k in range(num_cmds)]


def timed_pes(segments: List[Tuple[int, bytes]], ics_pts: int) -> Tuple[List[bytes], int]:
    """Zeitstempel wie multiAVCHD. ICS: PTS bleibt, DTS = Beginn; ODS hintereinander mit 8 Mpx/s;
    PTS(ICS) = DTS(ICS) + max(Ebene löschen, alle ODS dekodieren) + Ebene beschreiben. Gibt (PES, PCR) zurück."""
    durations = []
    for seg_type, payload in segments:
        if seg_type == SEG_ODS:
            assert payload[3] & 0xC0 == 0xC0, "ODS in mehreren Teilen wird hier nicht unterstützt"
            w, h = struct.unpack(">HH", payload[7:11])
            durations.append(math.ceil(90000 * w * h / ODS_PIXELS_PER_SECOND))
    decode = sum(durations)
    start = ics_pts - (max(PLANE_TICKS, decode) + PLANE_TICKS)
    out, t, k = [], start, 0
    for seg_type, payload in segments:
        seg = segment_bytes(seg_type, payload)
        if seg_type == SEG_ICS:
            out.append(pes_packet(seg, ics_pts, start))
        elif seg_type == SEG_ODS:
            out.append(pes_packet(seg, t + durations[k], t))
            t += durations[k]
            k += 1
        elif seg_type == SEG_END:
            out.append(pes_packet(seg, t))
        else:                                         # PDS: nur PTS = Beginn
            out.append(pes_packet(seg, start))
    return out, start - PCR_LEAD


def build_variant(m2ts: str, clpi: str, variant: int):
    segments, pts = read_ig_segments(m2ts)
    segs = [(t, bytearray(p)) for t, p in segments]
    ics = next(p for t, p in segs if t == SEG_ICS)
    def_sel_at, cmd_at = page0_offsets(bytes(ics))
    if variant in (2, 6):
        ics[def_sel_at + 2:def_sel_at + 4] = ics[def_sel_at:def_sel_at + 2]   # default_activated = default_selected
    if variant == 3:
        fixed = build_set_button_page_cmd(1)
        for at in cmd_at[-2:]:                    # beide SetButtonPage der Startseite (mit und ohne Button-Wunsch)
            assert ics[at] == 0x51, "SetButtonPage erwartet"
            ics[at:at + 12] = fixed
    segs = [(t, bytes(p)) for t, p in segs]
    if variant in (4, 6):
        pes_list, pcr = timed_pes(segs, pts)
    else:
        pes_list, pcr = [pes_packet(segment_bytes(t, p), pts) for t, p in segs], pts
    transport = variant in (5, 6)
    write_ig_m2ts(m2ts, pes_list, pcr, transport)
    patch_clpi(clpi, os.path.getsize(m2ts) // 192, PCR_PID_OWN if transport else IG_PID)


# ---------------------------------------------------------------------------------------------------------------
# 4. MovieObjects: Varianten nacheinander
# ---------------------------------------------------------------------------------------------------------------

def cycle_movie_objects(path: str, group_objects: List[int]):
    """Jede Menügruppe spielt ihre Playlist einmal und springt dann zur nächsten (Startseite, Standard-Button)."""
    from modules.bdmv.movie_object_generator import cmd_jump_object, cmd_move_gpr
    d = bytearray(open(path, "rb").read())
    pos = 40 + 8
    count = struct.unpack(">H", d[pos:pos + 2])[0]
    pos += 2
    objects = []
    for _ in range(count):
        flags, n = struct.unpack(">HH", d[pos:pos + 4])
        objects.append([flags, [bytes(d[pos + 4 + 12 * k:pos + 16 + 12 * k]) for k in range(n)]])
        pos += 4 + 12 * n
    for i, obj in enumerate(group_objects):
        nxt = group_objects[(i + 1) % len(group_objects)]
        play = objects[obj][1][0]
        assert play[0] == 0x22, "PlayPL am Anfang erwartet"
        objects[obj][1] = [play, cmd_move_gpr(7, 0), cmd_move_gpr(8, 0), cmd_jump_object(nxt)]
    body = bytearray(d[44:48]) + struct.pack(">H", count)
    for flags, cmds in objects:
        body += struct.pack(">HH", flags, len(cmds)) + b"".join(cmds)
    out = bytes(d[:40]) + struct.pack(">I", len(body)) + bytes(body)
    with open(path, "wb") as f:
        f.write(out)


def main(out: str):
    from modules.bdsim.disc import read_playlist, read_movie_objects
    shutil.rmtree(out, ignore_errors=True)
    media, disc = os.path.join(out, "media"), os.path.join(out, "disc")
    os.makedirs(media)
    os.makedirs(disc)
    build_project(media, disc)
    bdmv = os.path.join(disc, "BDMV")

    # Menü-Playlists in Reihenfolge der Varianten und die MovieObjects, die sie spielen
    groups = []
    for obj in read_movie_objects(os.path.join(bdmv, "MovieObject.bdmv")):
        first = obj.commands[0] if obj.commands else None
        if first is not None and first.raw[0] == 0x22:
            pl = read_playlist(os.path.join(bdmv, "PLAYLIST", f"{first.dst:05d}.mpls"), first.dst)
            if pl.subpaths:
                groups.append((obj.object_id, pl.subpaths[0].clips[0]))
    assert len(groups) == len(VARIANTS), groups

    # Selbstprüfung: Der eigene Writer erzeugt ohne Änderung denselben Clip wie OpenBDAuth
    m2ts0 = os.path.join(bdmv, "STREAM", f"{groups[0][1]}.m2ts")
    segments, pts = read_ig_segments(m2ts0)
    probe = os.path.join(out, "probe.m2ts")
    write_ig_m2ts(probe, [pes_packet(segment_bytes(t, p), pts) for t, p in segments], pts, False)
    assert open(probe, "rb").read() == open(m2ts0, "rb").read(), "eigener Writer weicht von OpenBDAuth ab"
    os.remove(probe)
    print("Selbstprüfung: eigener Writer bytegleich zu OpenBDAuth")

    for variant, (obj, clip) in zip(VARIANTS, groups):
        m2ts = os.path.join(bdmv, "STREAM", f"{clip}.m2ts")
        clpi = os.path.join(bdmv, "CLIPINF", f"{clip}.clpi")
        if variant != 1:
            build_variant(m2ts, clpi, variant)
        shutil.copy(clpi, os.path.join(bdmv, "BACKUP", "CLIPINF", f"{clip}.clpi"))
        print(f"Variante {variant}: Clip {clip}, MovieObject {obj} – {VARIANTS[variant]}")

    cycle_movie_objects(os.path.join(bdmv, "MovieObject.bdmv"), [obj for obj, _ in groups])
    shutil.copy(os.path.join(bdmv, "MovieObject.bdmv"), os.path.join(bdmv, "BACKUP", "MovieObject.bdmv"))

    iso = os.path.join(out, "TEST_DISC.iso")
    create_udf_iso(disc, iso, volume_label="TEST_DISC", log_callback=lambda m: None)
    print("ISO:", iso)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
