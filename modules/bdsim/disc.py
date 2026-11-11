# modules/bdsim/disc.py
"""
Leser für eine fertige BDMV-Struktur (BD-ROM Part 3):
- index.bdmv       -> FirstPlayback, TopMenu, Titel
- MovieObject.bdmv -> MovieObjects mit HDMV-Befehlen
- PLAYLIST/*.mpls  -> PlayItems, Spuren (STN), SubPaths, Kapitelmarken, 3D-Erweiterung
- IG-Menüstrom     -> Seiten, Buttons, Befehle, Paletten, Grafiken (ICS/PDS/ODS)

Die Leser sind unabhängig von den Generatoren in modules/bdmv, modules/mpls und modules/igs,
damit der Simulator prüft, was tatsächlich auf der Disc steht.
"""

import os
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from core.translations import tr
from modules.bdsim.hdmv import Command, decode_command

TICKS_PER_SECOND = 45000

OBJECT_TYPE_HDMV = 1
OBJECT_TYPE_BDJ = 2

# IGS Segmenttypen
SEG_PDS = 0x14
SEG_ODS = 0x15
SEG_ICS = 0x18
SEG_END = 0x80

NO_BUTTON = 0xFFFF


class DiscReadError(Exception):
    """Eine Datei der Disc fehlt oder ist nicht lesbar."""


# ─────────────────────────────── index.bdmv ───────────────────────────────

@dataclass
class IndexEntry:
    object_type: int                  # 1 = HDMV, 2 = BD-J, 0 = leer
    mobj_id: Optional[int] = None     # nur HDMV
    interactive: bool = False         # playback_type 1 (Menü)
    bdj_name: str = ""

    @property
    def is_hdmv(self) -> bool:
        return self.object_type == OBJECT_TYPE_HDMV


@dataclass
class DiscIndex:
    first_play: IndexEntry
    top_menu: IndexEntry
    titles: List[IndexEntry]          # titles[0] = Titel 1
    has_3d_content: bool = False


def _read_index_entry(data: bytes, pos: int) -> IndexEntry:
    object_type = data[pos] >> 6
    if object_type == OBJECT_TYPE_HDMV:
        playback_type = data[pos + 4] >> 6
        mobj_id = struct.unpack(">H", data[pos + 6:pos + 8])[0]
        return IndexEntry(object_type, mobj_id=mobj_id, interactive=playback_type == 1)
    if object_type == OBJECT_TYPE_BDJ:
        return IndexEntry(object_type, bdj_name=data[pos + 6:pos + 11].decode("ascii", "replace"))
    return IndexEntry(object_type)


def read_index(path: str) -> DiscIndex:
    data = _read_file(path)
    if data[0:4] != b"INDX":
        raise DiscReadError(tr("sim_not_index", file=os.path.basename(path), magic=repr(data[0:4])))
    indexes_start = struct.unpack(">I", data[8:12])[0]
    # AppInfoBDMV beginnt bei 40: length(4), dann Flags; Bit 5 von Byte 0 = SS_content_exist_flag
    has_3d = bool(data[44] & 0x20) if len(data) > 44 else False
    pos = indexes_start + 4
    first_play = _read_index_entry(data, pos)
    top_menu = _read_index_entry(data, pos + 12)
    num_titles = struct.unpack(">H", data[pos + 24:pos + 26])[0]
    titles = [_read_index_entry(data, pos + 26 + 12 * i) for i in range(num_titles)]
    return DiscIndex(first_play, top_menu, titles, has_3d)


# ─────────────────────────────── MovieObject.bdmv ───────────────────────────────

@dataclass
class MovieObject:
    object_id: int
    commands: List[Command]
    resume_intention: bool = False
    menu_call_mask: bool = False
    title_search_mask: bool = False


def read_movie_objects(path: str) -> List[MovieObject]:
    data = _read_file(path)
    if data[0:4] != b"MOBJ":
        raise DiscReadError(tr("sim_not_mobj", file=os.path.basename(path), magic=repr(data[0:4])))
    pos = 40 + 8
    count = struct.unpack(">H", data[pos:pos + 2])[0]
    pos += 2
    objects = []
    for i in range(count):
        flags, num_cmds = struct.unpack(">HH", data[pos:pos + 4])
        pos += 4
        cmds = [decode_command(data[pos + 12 * k:pos + 12 * k + 12]) for k in range(num_cmds)]
        pos += 12 * num_cmds
        objects.append(MovieObject(i, cmds, bool(flags & 0x8000), bool(flags & 0x4000), bool(flags & 0x2000)))
    return objects


# ─────────────────────────────── MPLS ───────────────────────────────

@dataclass
class StreamRef:
    kind: str                    # "video", "audio", "pg", "ig"
    entry_type: int              # 1 = im PlayItem-Clip, 2/3/4 = über SubPath
    pid: int
    subpath_id: Optional[int] = None
    subclip_id: int = 0
    coding_type: int = 0
    lang: str = ""


@dataclass
class PlayItem:
    clip: str
    in_time: int
    out_time: int
    streams: List[StreamRef] = field(default_factory=list)

    def count(self, kind: str) -> int:
        return sum(1 for s in self.streams if s.kind == kind)


@dataclass
class SubPath:
    subpath_type: int
    clips: List[str]


@dataclass
class PlaylistMark:
    mark_type: int               # 1 = Entry Mark (Kapitel), 2 = Link Point
    item_ref: int
    time: int


@dataclass
class Playlist:
    playlist_id: int
    items: List[PlayItem]
    subpaths: List[SubPath]
    marks: List[PlaylistMark]
    is_3d: bool = False

    @property
    def duration_sec(self) -> float:
        return sum(max(0, i.out_time - i.in_time) for i in self.items) / TICKS_PER_SECOND

    @property
    def chapter_marks(self) -> List[int]:
        return [i for i, m in enumerate(self.marks) if m.mark_type == 1]

    def count(self, kind: str) -> int:
        return self.items[0].count(kind) if self.items else 0

    def ig_streams(self) -> List[StreamRef]:
        return [s for s in (self.items[0].streams if self.items else []) if s.kind == "ig"]


def _read_stream_entry(data: bytes, pos: int, kind: str) -> Tuple[StreamRef, int]:
    entry_len = data[pos]
    entry_type = data[pos + 1]
    if entry_type == 1:
        ref = StreamRef(kind, 1, struct.unpack(">H", data[pos + 2:pos + 4])[0])
    elif entry_type in (2, 4):
        ref = StreamRef(kind, entry_type, struct.unpack(">H", data[pos + 4:pos + 6])[0],
                        subpath_id=data[pos + 2], subclip_id=data[pos + 3])
    elif entry_type == 3:
        ref = StreamRef(kind, 3, struct.unpack(">H", data[pos + 3:pos + 5])[0], subpath_id=data[pos + 2])
    else:
        ref = StreamRef(kind, entry_type, 0)
    pos += 1 + entry_len

    attr_len = data[pos]
    attr = data[pos + 1:pos + 1 + attr_len]
    if attr:
        ref.coding_type = attr[0]
        lang = b""
        if kind == "audio" and len(attr) >= 5:
            lang = attr[2:5]
        elif kind in ("pg", "ig") and ref.coding_type in (0x90, 0x91) and len(attr) >= 4:
            lang = attr[1:4]
        elif kind == "pg" and ref.coding_type == 0x92 and len(attr) >= 5:
            lang = attr[2:5]
        ref.lang = lang.decode("ascii", "replace")
    return ref, pos + 1 + attr_len


def _read_stn(data: bytes, pos: int) -> List[StreamRef]:
    counts = data[pos + 4:pos + 8]     # video, audio, pg, ig
    pos += 16
    streams = []
    for kind, n in zip(("video", "audio", "pg", "ig"), counts):
        for _ in range(n):
            ref, pos = _read_stream_entry(data, pos, kind)
            streams.append(ref)
    return streams


def read_playlist(path: str, playlist_id: int) -> Playlist:
    data = _read_file(path)
    if data[0:4] != b"MPLS":
        raise DiscReadError(tr("sim_not_playlist", file=os.path.basename(path), magic=repr(data[0:4])))
    playlist_start, mark_start, ext_start = struct.unpack(">III", data[8:20])

    num_items, num_subpaths = struct.unpack(">HH", data[playlist_start + 6:playlist_start + 10])
    pos = playlist_start + 10
    items = []
    for _ in range(num_items):
        item_len = struct.unpack(">H", data[pos:pos + 2])[0]
        body = pos + 2
        clip = data[body:body + 5].decode("ascii", "replace")
        multi_angle = (struct.unpack(">H", data[body + 9:body + 11])[0] >> 4) & 1
        in_time, out_time = struct.unpack(">II", data[body + 12:body + 20])
        stn = body + 32
        if multi_angle:
            num_angles = data[stn]
            stn += 2 + 10 * max(0, num_angles - 1)
        items.append(PlayItem(clip, in_time, out_time, _read_stn(data, stn)))
        pos = body + item_len

    subpaths = []
    for _ in range(num_subpaths):
        sp_len = struct.unpack(">I", data[pos:pos + 4])[0]
        body = pos + 4
        sp_type = data[body + 1]
        num_sub_items = data[body + 5]
        spos = body + 6
        clips = []
        for _ in range(num_sub_items):
            si_len = struct.unpack(">H", data[spos:spos + 2])[0]
            clips.append(data[spos + 2:spos + 7].decode("ascii", "replace"))
            spos += 2 + si_len
        subpaths.append(SubPath(sp_type, clips))
        pos = body + sp_len

    marks = []
    num_marks = struct.unpack(">H", data[mark_start + 4:mark_start + 6])[0]
    mpos = mark_start + 6
    for _ in range(num_marks):
        mark_type = data[mpos + 1]
        item_ref, stamp = struct.unpack(">HI", data[mpos + 2:mpos + 8])
        marks.append(PlaylistMark(mark_type, item_ref, stamp))
        mpos += 14

    # ExtensionData: ID1 = 2 kennzeichnet die 3D-Erweiterungen (STN_table_SS, SubPath-Erweiterung für MVC)
    is_3d = False
    if ext_start and ext_start + 12 <= len(data):
        num_entries = data[ext_start + 11]
        epos = ext_start + 12
        for _ in range(num_entries):
            id1 = struct.unpack(">H", data[epos:epos + 2])[0]
            if id1 == 2:
                is_3d = True
            epos += 12

    return Playlist(playlist_id, items, subpaths, marks, is_3d)


# ─────────────────────────────── IG-Menüstrom ───────────────────────────────

@dataclass
class Button:
    button_id: int
    numeric_select_value: int
    auto_action: bool
    x: int
    y: int
    upper: int
    lower: int
    left: int
    right: int
    normal: Tuple[int, int]            # (start_object_id, end_object_id)
    selected: Tuple[int, int]
    activated: Tuple[int, int]
    commands: List[Command]


@dataclass
class ButtonGroup:
    """Button Overlap Group (BOG): höchstens ein Button der Gruppe ist gleichzeitig gültig."""
    default_valid_button: int
    buttons: List[Button]


@dataclass
class Page:
    page_id: int
    default_selected_button: int
    default_activated_button: int
    palette_id: int
    groups: List[ButtonGroup]

    def buttons(self) -> List[Button]:
        return [b for g in self.groups for b in g.buttons]

    def button(self, button_id: int) -> Optional[Button]:
        for b in self.buttons():
            if b.button_id == button_id:
                return b
        return None


@dataclass
class GraphicObject:
    object_id: int
    width: int
    height: int
    rle: bytes


@dataclass
class Composition:
    """Interactive Composition eines IG-Stroms (erste Epoche)."""
    width: int
    height: int
    stream_model: int                  # 0 = Multiplexed, 1 = Out-of-Mux
    ui_model: int                      # 0 = Always-On, 1 = Pop-up
    pages: List[Page]
    palettes: Dict[int, List[Tuple[int, int, int, int, int]]]   # palette_id -> [(entry, Y, Cr, Cb, T)]
    objects: Dict[int, GraphicObject]
    display_sets: int = 1

    def page(self, page_id: int) -> Optional[Page]:
        for p in self.pages:
            if p.page_id == page_id:
                return p
        return None


def _skip_effect_sequence(d: bytes, q: int) -> int:
    num_windows = d[q]
    q += 1 + 9 * num_windows
    num_effects = d[q]
    q += 1
    for _ in range(num_effects):
        q += 4                          # effect_duration(3) + palette_id_ref(1)
        num_objects = d[q]
        q += 1
        for _ in range(num_objects):
            cropped = d[q + 3] & 0x80
            q += 8 + (8 if cropped else 0)
    return q


def parse_interactive_composition(d: bytes) -> Tuple[int, int, List[Page]]:
    """Parst interactive_composition() (ohne Längenfeld). Gibt (stream_model, ui_model, pages) zurück."""
    stream_model = d[0] >> 7
    ui_model = (d[0] >> 6) & 1
    q = 1
    if stream_model == 0:
        q += 10                         # composition_time_out_pts + selection_time_out_pts
    q += 3                              # user_time_out_duration
    num_pages = d[q]
    q += 1
    pages = []
    for _ in range(num_pages):
        page_id = d[q]
        q += 2 + 8                      # page_id, page_version, UO_mask_table
        q = _skip_effect_sequence(d, q)
        q = _skip_effect_sequence(d, q)
        q += 1                          # animation_frame_rate_code
        def_sel, def_act = struct.unpack(">HH", d[q:q + 4])
        palette_id = d[q + 4]
        num_bogs = d[q + 5]
        q += 6
        groups = []
        for _ in range(num_bogs):
            def_valid = struct.unpack(">H", d[q:q + 2])[0]
            num_buttons = d[q + 2]
            q += 3
            buttons = []
            for _ in range(num_buttons):
                bid, nsv = struct.unpack(">HH", d[q:q + 4])
                auto = bool(d[q + 4] & 0x80)
                x, y, up, down, left, right = struct.unpack(">HHHHHH", d[q + 5:q + 17])
                q += 17
                n_start, n_end = struct.unpack(">HH", d[q:q + 4])
                q += 5
                s_start, s_end = struct.unpack(">HH", d[q + 1:q + 5])
                q += 6
                a_start, a_end = struct.unpack(">HH", d[q + 1:q + 5])
                q += 5
                num_cmds = struct.unpack(">H", d[q:q + 2])[0]
                q += 2
                cmds = [decode_command(d[q + 12 * k:q + 12 * k + 12]) for k in range(num_cmds)]
                q += 12 * num_cmds
                buttons.append(Button(bid, nsv, auto, x, y, up, down, left, right,
                                      (n_start, n_end), (s_start, s_end), (a_start, a_end), cmds))
            groups.append(ButtonGroup(def_valid, buttons))
        pages.append(Page(page_id, def_sel, def_act, palette_id, groups))
    return stream_model, ui_model, pages


IG_SCAN_BYTES = 128 * 1024 * 1024   # IG-Menüs liegen am Anfang des Clips; Filme mit Menü im Clip nicht ganz lesen


def demux_pes_payloads(m2ts_path: str, pid: int, max_bytes: int = IG_SCAN_BYTES) -> List[bytes]:
    """Liest die PES-Pakete einer PID aus einem M2TS (192-Byte-Pakete) und gibt ihre Nutzdaten zurück.
    Gelesen werden höchstens max_bytes vom Anfang (bei manchen Discs liegt das Menü im Film-Clip)."""
    pes_list: List[bytearray] = []
    current: Optional[bytearray] = None
    try:
        f = open(m2ts_path, "rb")
    except OSError as ex:
        raise DiscReadError(tr("sim_unreadable", file=os.path.basename(m2ts_path), err=ex)) from ex
    with f:
        remaining = max_bytes
        while remaining > 0:
            raw = f.read(min(remaining, 192 * 8192))
            if len(raw) < 192:
                break
            remaining -= len(raw)
            for off in range(0, len(raw) - 191, 192):
                pkt = raw[off + 4:off + 192]
                if pkt[0] != 0x47:
                    continue
                if (((pkt[1] & 0x1F) << 8) | pkt[2]) != pid:
                    continue
                afc = (pkt[3] >> 4) & 3
                start = 4
                if afc in (2, 3):
                    start = 5 + pkt[4]
                if afc not in (1, 3) or start >= 188:
                    continue
                if pkt[1] & 0x40:
                    current = bytearray()
                    pes_list.append(current)
                if current is not None:
                    current.extend(pkt[start:])

    payloads = []
    for pes in pes_list:
        if len(pes) < 9 or pes[0:3] != b"\x00\x00\x01":
            continue
        pes_len = struct.unpack(">H", pes[4:6])[0]
        header_len = pes[8]
        end = 6 + pes_len if pes_len else len(pes)
        payloads.append(bytes(pes[9 + header_len:end]))
    return payloads


def read_composition(m2ts_path: str, pid: int) -> Composition:
    """Liest den IG-Strom einer PID und gibt die erste Interactive Composition samt Paletten und Grafiken zurück."""
    segments: List[Tuple[int, bytes]] = []
    for payload in demux_pes_payloads(m2ts_path, pid):
        pos = 0
        while pos + 3 <= len(payload):
            seg_type = payload[pos]
            seg_len = struct.unpack(">H", payload[pos + 1:pos + 3])[0]
            segments.append((seg_type, payload[pos + 3:pos + 3 + seg_len]))
            pos += 3 + seg_len

    ics_data = bytearray()
    ics_header: Optional[bytes] = None
    ics_complete = False
    display_sets = 0
    palettes: Dict[int, List[Tuple[int, int, int, int, int]]] = {}
    objects: Dict[int, GraphicObject] = {}
    pending_ods: Dict[int, List] = {}

    for seg_type, s in segments:
        if seg_type == SEG_ICS:
            display_sets += 1
            if ics_complete:
                continue
            seq = s[8]
            if seq & 0x80:
                ics_header = s[:8]
                ics_data = bytearray(s[12:])
            else:
                ics_data.extend(s[9:])
            if seq & 0x40:
                ics_complete = True
        elif seg_type == SEG_PDS and display_sets <= 1:
            entries = [tuple(s[i:i + 5]) for i in range(2, len(s) - 4, 5)]
            palettes[s[0]] = entries
        elif seg_type == SEG_ODS and display_sets <= 1:
            obj_id = struct.unpack(">H", s[0:2])[0]
            seq = s[3]
            if seq & 0x80:
                width, height = struct.unpack(">HH", s[7:11])
                pending_ods[obj_id] = [width, height, bytearray(s[11:])]
            elif obj_id in pending_ods:
                pending_ods[obj_id][2].extend(s[4:])
            if seq & 0x40 and obj_id in pending_ods:
                w, h, rle = pending_ods.pop(obj_id)
                objects[obj_id] = GraphicObject(obj_id, w, h, bytes(rle))

    if ics_header is None or not ics_complete:
        raise DiscReadError(tr("sim_no_ics", file=os.path.basename(m2ts_path), pid=f"0x{pid:04X}"))
    width, height = struct.unpack(">HH", ics_header[0:4])
    stream_model, ui_model, pages = parse_interactive_composition(bytes(ics_data))
    return Composition(width, height, stream_model, ui_model, pages, palettes, objects, display_sets)


# ─────────────────────────────── Disc ───────────────────────────────

@dataclass
class Disc:
    bdmv_dir: str
    index: DiscIndex
    movie_objects: List[MovieObject]
    playlists: Dict[int, Playlist]
    compositions: Dict[int, Composition]           # playlist_id -> Menü
    read_problems: List[str] = field(default_factory=list)

    @property
    def scratch_registers(self) -> frozenset:
        """Hilfsregister, die der automatische Durchlauf nicht als Zustand unterscheidet (hdmv.scratch_registers)."""
        cached = self.__dict__.get("_scratch")
        if cached is None:
            from modules.bdsim.hdmv import scratch_registers
            lists = [o.commands for o in self.movie_objects]
            lists += [b.commands for comp in self.compositions.values() for page in comp.pages for b in page.buttons()]
            cached = self.__dict__["_scratch"] = scratch_registers(lists)
        return cached

    def title_object(self, title: int) -> Optional[int]:
        if 1 <= title <= len(self.index.titles) and self.index.titles[title - 1].is_hdmv:
            return self.index.titles[title - 1].mobj_id
        return None


def find_bdmv_dir(path: str) -> Optional[str]:
    """Akzeptiert Disc-Wurzel oder BDMV-Ordner."""
    path = os.path.normpath(path)
    if os.path.basename(path).upper() == "BDMV" and os.path.isdir(path):
        return path
    for name in ("BDMV", "bdmv"):
        candidate = os.path.join(path, name)
        if os.path.isdir(candidate):
            return candidate
    return None


def _ig_clip_path(bdmv_dir: str, playlist: Playlist, ref: StreamRef) -> Optional[str]:
    if ref.entry_type == 1:
        clip = playlist.items[0].clip
    else:
        if ref.subpath_id is None or ref.subpath_id >= len(playlist.subpaths):
            return None
        clips = playlist.subpaths[ref.subpath_id].clips
        if ref.subclip_id >= len(clips):
            return None
        clip = clips[ref.subclip_id]
    return os.path.join(bdmv_dir, "STREAM", f"{clip}.m2ts")


def load_disc(path: str) -> Disc:
    bdmv_dir = find_bdmv_dir(path)
    if not bdmv_dir:
        raise DiscReadError(tr("sim_no_bdmv", path=path))

    index = read_index(os.path.join(bdmv_dir, "index.bdmv"))
    movie_objects = read_movie_objects(os.path.join(bdmv_dir, "MovieObject.bdmv"))
    problems: List[str] = []

    playlists: Dict[int, Playlist] = {}
    playlist_dir = os.path.join(bdmv_dir, "PLAYLIST")
    for name in sorted(os.listdir(playlist_dir)) if os.path.isdir(playlist_dir) else []:
        stem, ext = os.path.splitext(name)
        if ext.lower() != ".mpls" or not stem.isdigit():
            continue
        try:
            playlists[int(stem)] = read_playlist(os.path.join(playlist_dir, name), int(stem))
        except (DiscReadError, struct.error, IndexError) as ex:
            problems.append(tr("sim_playlist_unreadable", name=name, err=ex))

    compositions: Dict[int, Composition] = {}
    for pl_id, pl in playlists.items():
        for ref in pl.ig_streams()[:1]:
            clip_path = _ig_clip_path(bdmv_dir, pl, ref)
            if not clip_path or not os.path.exists(clip_path):
                problems.append(tr("sim_menu_clip_missing", pl=f"{pl_id:05d}", pid=f"0x{ref.pid:04X}"))
                continue
            try:
                compositions[pl_id] = read_composition(clip_path, ref.pid)
            except (DiscReadError, struct.error, IndexError) as ex:
                problems.append(tr("sim_menu_unreadable", pl=f"{pl_id:05d}", err=ex))

    return Disc(bdmv_dir, index, movie_objects, playlists, compositions, problems)


def _read_file(path: str) -> bytes:
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError as ex:
        raise DiscReadError(tr("sim_unreadable", file=os.path.basename(path), err=ex)) from ex
