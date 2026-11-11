# modules/igs/segments.py
"""
HDMV Interactive Graphics Stream (IGS) Segmente nach BD-ROM Part 3.

Enthält die Segment-Definitionen und Builder für:
- PDS (Palette Definition Segment, 0x14)
- ODS (Object Definition Segment, 0x15)
- ICS (Interactive Composition Segment, 0x18)
- END (End of Display Set Segment, 0x16)
"""

import struct
from typing import List, Optional
from dataclasses import dataclass, field

# Segment Typen
SEGMENT_PDS = 0x14
SEGMENT_ODS = 0x15
SEGMENT_ICS = 0x18
SEGMENT_END = 0x80

# Composition States
STATE_NORMAL = 0x00
STATE_ACQUISITION_POINT = 0x01
STATE_EPOCH_START = 0x02

# Framerate Codes
FPS_23_976 = 1
FPS_24 = 2
FPS_25 = 3
FPS_29_97 = 4
FPS_50 = 6
FPS_59_94 = 7

def make_segment(segment_type: int, payload: bytes) -> bytes:
    """Packt einen 3-Byte Segment-Header (Typ + 16-Bit Big Endian Länge) vor den Payload."""
    header = struct.pack(">BH", segment_type, len(payload))
    return header + payload

def build_end_segment() -> bytes:
    """Erzeugt ein End of Display Set (END) Segment (3 Bytes)."""
    return make_segment(SEGMENT_END, b"")

def build_pds_segment(palette_payload: bytes) -> bytes:
    """Erzeugt ein Palette Definition Segment (PDS, 0x14)."""
    return make_segment(SEGMENT_PDS, palette_payload)

def build_ods_segment(
    object_id: int, 
    width: int, 
    height: int, 
    rle_data: bytes, 
    version: int = 0
) -> bytes:
    """
    Erzeugt ein Object Definition Segment (ODS, 0x15).
    - object_id: uint16
    - version: uint8
    - sequence_descriptor: 0xC0 (first_in_seq=1, last_in_seq=1)
    - object_data_length: 3 Bytes (4 + len(rle_data))
    - width: uint16
    - height: uint16
    - rle_data: bytes
    """
    seq_desc = 0xC0
    obj_data_len = 4 + len(rle_data)
    
    # Packe object_id (2B), version (1B), seq_desc (1B)
    hdr1 = struct.pack(">HBB", object_id, version, seq_desc)
    # Packe object_data_length als 3 Bytes (uint24)
    data_len_bytes = struct.pack(">I", obj_data_len)[1:] # Nimm die unteren 3 Bytes
    # Packe width (2B), height (2B)
    dim_bytes = struct.pack(">HH", width, height)
    
    payload = hdr1 + data_len_bytes + dim_bytes + rle_data
    return make_segment(SEGMENT_ODS, payload)

@dataclass
class ButtonDef:
    """Definition eines interaktiven Buttons im Menü."""
    button_id: int
    numeric_select_value: int
    x: int
    y: int
    width: int
    height: int
    # Navigations-Verknüpfungen (Pfeiltasten auf der Fernbedienung)
    upper_button_id: int
    lower_button_id: int
    left_button_id: int
    right_button_id: int
    # Referenzen auf ODS Objekt-IDs
    normal_object_id: int
    selected_object_id: int
    activated_object_id: int
    # Navigations-Kommandos (12 Bytes HDMV Bytecode pro Kommando)
    nav_commands: List[bytes] = field(default_factory=list)
    auto_action: bool = False

def build_play_playlist_cmd(playlist_id: int) -> bytes:
    """
    Erzeugt ein standardisiertes 12-Byte HDMV Command: PlayPL(playlist_id).
    Opcode für PlayPL(imm): 0x22 0x80 0x00 0x00
    - Byte 0 (0x22): Opcode Count 1 (001b << 5) | Group Branch (00b << 3) | Sub-Instruction Play (010b = 2)
    - Byte 1 (0x80): Imm Flag Op1 (1 << 7) | Branch Option PlayPL (0x00)
    - Bytes 4..7: Playlist ID (dst)
    - Bytes 8..11: 0 (src)
    """
    return bytes([0x22, 0x80, 0x00, 0x00]) + struct.pack(">II", playlist_id, 0)

def build_play_playlist_at_mark_cmd(playlist_id: int, mark_id: int) -> bytes:
    """
    Erzeugt ein standardisiertes 12-Byte HDMV Command: PlayPLatPM(playlist_id, mark_id).
    Opcode für PlayPLatPM(imm, imm): 0x42 0xC2 0x00 0x00
    - Byte 0 (0x42): Opcode Count 2 | Group Branch | Sub-Instruction Play
    - Byte 1 (0xC2): Imm Flag Op1 (1 << 7) | Imm Flag Op2 (1 << 6) | Branch Option PlayPLatPM (0x02)
    - Bytes 4..7: Playlist ID (dst)
    - Bytes 8..11: PlayMark ID (src, 0-basierter PlayListMark-Index)
    """
    return bytes([0x42, 0xC2, 0x00, 0x00]) + struct.pack(">II", playlist_id, mark_id)

def build_jump_title_cmd(title_id: int) -> bytes:
    """
    Erzeugt ein standardisiertes 12-Byte HDMV Command: JumpTitle(title_id).
    Opcode für JumpTitle(imm): 0x21 0x81 0x00 0x00
    - Byte 0 (0x21): Opcode Count 1 (001b << 5) | Group Branch (00b << 3) | Sub-Instruction Jump (001b = 1)
    - Byte 1 (0x81): Imm Flag Op1 (1 << 7) | Branch Option JumpTitle (0x01)
    - Bytes 4..7: Title ID (dst)
    - Bytes 8..11: 0 (src)
    In BD-ROM IGS Interactive Buttons MUSS JumpTitle verwendet werden, da direkte
    Playlist-Wechsel (PlayPL) innerhalb einer aktiven Interactive Composition
    von standardkonformen Playern (libbluray / Hardware) blockiert werden.
    """
    return bytes([0x21, 0x81, 0x00, 0x00]) + struct.pack(">II", title_id, 0)

def build_set_stream_cmd(
    audio_id: Optional[int] = None,
    subtitle_id: Optional[int] = None,
    subtitle_on: Optional[bool] = None
) -> bytes:
    """
    Erzeugt ein standardisiertes 12-Byte HDMV Command: SetStream(audio_id, subtitle_id, subtitle_on).
    Opcode für SetStream: 0x51 0xC0 0x00 0x01
    - Byte 0 (0x51): Opcode Count 2 | Group Set (2 << 3) | Sub-Group SetSystem (1)
      (Sub-Group 0 wäre die Register-Arithmetik: 0x30 .. 0x01 = Move!)
      Zwei Operanden; mit einem ignorierte der Sony UBP-X700 den Befehl.
    - Byte 1 (0xC0): Imm Flag Op1 (1 << 7) | Imm Flag Op2 (1 << 6); Operand 2 (IG/Winkel) = 0
    - Byte 3 (0x01): Set Option SetStream
    - Bytes 4..7: Bitmaske für Audio & PG Streams
    """
    dst = 0
    if audio_id is not None:
        dst |= 0x80000000 | ((audio_id & 0x0FFF) << 16)
    if subtitle_id is not None or subtitle_on is not None:
        dst |= 0x00008000
        if subtitle_on is True or (subtitle_on is None and subtitle_id is not None):
            dst |= 0x00004000
        if subtitle_id is not None:
            dst |= (subtitle_id & 0x0FFF)
    return bytes([0x51, 0xC0, 0x00, 0x01]) + struct.pack(">II", dst, 0)

def build_set_button_page_cmd(page_id: int) -> bytes:
    """
    Erzeugt ein standardisiertes 12-Byte HDMV Command: SetButtonPage(page_id).
    Opcode für SetButtonPage: 0x51 0xC0 0x00 0x03
    - Byte 0 (0x51): Opcode Count 2 | Group Set (2 << 3) | Sub-Group SetSystem (1)
    - Byte 1 (0xC0): Imm Flag Op1 (1 << 7) | Imm Flag Op2 (1 << 6)
    - Byte 3 (0x03): Set Option SetButtonPage
    - Bytes 4..7 (dst): button_flag (Bit 31) + Button ID; 0 = Standard-Button der Seite
    - Bytes 8..11 (src): page_flag (Bit 31) + Page ID (Bits 7..0)
    """
    return bytes([0x51, 0xC0, 0x00, 0x03]) + struct.pack(">II", 0, 0x80000000 | (page_id & 0xFF))


@dataclass
class PageDef:
    """Definition einer Menüseite (Page) im Interactive Composition Segment."""
    page_id: int
    buttons: List[ButtonDef] = field(default_factory=list)
    default_selected_button_id: int = 1

def build_ics_segment(
    video_width: int = 1920,
    video_height: int = 1080,
    frame_rate_code: int = FPS_23_976,
    composition_number: int = 0,
    composition_state: int = STATE_EPOCH_START,
    buttons: Optional[List[ButtonDef]] = None,
    default_selected_button_id: int = 1,
    pages: Optional[List[PageDef]] = None
) -> bytes:
    """
    Erzeugt ein Interactive Composition Segment (ICS, 0x18).
    Standardmäßig als Out-of-Mux / SubPath Stream deklariert.
    Unterstützt sowohl einzelne Button-Listen (Single Page 0) als auch
    mehrere Seiten (Pages) zum Umschalten per SetButtonPage.
    """
    if pages is None:
        pages = [PageDef(
            page_id=0,
            buttons=buttons or [],
            default_selected_button_id=default_selected_button_id
        )]

    # 1. Video Descriptor (5 Bytes): width (2B), height (2B), frame_rate (4bit) + reserved (4bit)
    video_desc = struct.pack(">HHB", video_width, video_height, (frame_rate_code << 4) & 0xF0)

    # 2. Composition Descriptor (3 Bytes): number (2B), state (2bit) + reserved (6bit)
    state_byte = (composition_state << 6) & 0xC0
    comp_desc = struct.pack(">HB", composition_number, state_byte)

    # 3. Sequence Descriptor (1 Byte): first_in_seq=1, last_in_seq=1 -> 0xC0
    seq_desc = struct.pack(">B", 0xC0)

    # 4. Interactive Composition Data:
    ic_data = bytearray()

    # stream_model = 1 (Out-of-Mux / SubPath), ui_model = 0 (Always-On / Normal Menu), reserved = 0
    # Bit 7: stream_model (1), Bit 6: ui_model (0) -> 0x80
    ic_data.append(0x80)

    # user_timeout_duration: 3 Bytes (uint24) -> 0 für unbegrenzt
    ic_data.extend(b"\x00\x00\x00")

    # num_pages: 1 Byte
    ic_data.append(len(pages))

    # Pages serialisieren
    for page in pages:
        page_data = bytearray()
        page_data.append(page.page_id & 0xFF)
        page_data.append(0) # page_version = 0

        # uo_mask_table (8 Bytes, keine Operationen gesperrt)
        page_data.extend(b"\x00" * 8)

        # in_effects: num_windows = 0, num_effects = 0
        page_data.extend(b"\x00\x00")
        # out_effects: num_windows = 0, num_effects = 0
        page_data.extend(b"\x00\x00")

        page_data.append(1) # animation_frame_rate_code = 1
        page_data.extend(struct.pack(">HH", page.default_selected_button_id, 0xFFFF))
        page_data.append(0) # palette_id_ref = 0

        num_bogs = len(page.buttons) if page.buttons else 1
        page_data.append(num_bogs)

        if page.buttons:
            for b in page.buttons:
                bog_data = bytearray()
                bog_data.extend(struct.pack(">H", b.button_id)) # default_valid_button_id_ref
                bog_data.append(1) # num_buttons in dieser BOG = 1

                btn_data = bytearray()
                btn_data.extend(struct.pack(">H", b.button_id))
                btn_data.extend(struct.pack(">H", b.numeric_select_value))
                
                # auto_action_flag (1 bit) + reserved (7 bit)
                auto_byte = 0x80 if b.auto_action else 0x00
                btn_data.append(auto_byte)

                # x, y
                btn_data.extend(struct.pack(">HH", b.x, b.y))

                # 4-Wege Navigation (D-Pad)
                btn_data.extend(struct.pack(">HHHH", b.upper_button_id, b.lower_button_id, b.left_button_id, b.right_button_id))

                # Normal State: start_obj, end_obj, repeat_flag (1 bit) + reserved (7 bit)
                btn_data.extend(struct.pack(">HHB", b.normal_object_id, b.normal_object_id, 0x00))

                # Selected State: sound_ref (0xFF = none), start_obj, end_obj, repeat_flag
                btn_data.extend(struct.pack(">BHHB", 0xFF, b.selected_object_id, b.selected_object_id, 0x00))

                # Activated State: sound_ref (0xFF = none), start_obj, end_obj
                btn_data.extend(struct.pack(">BHH", 0xFF, b.activated_object_id, b.activated_object_id))

                # Navigations-Kommandos
                btn_data.extend(struct.pack(">H", len(b.nav_commands)))
                for cmd in b.nav_commands:
                    if len(cmd) != 12:
                        raise ValueError(f"HDMV Nav Command muss 12 Bytes lang sein, ist aber {len(cmd)}.")
                    btn_data.extend(cmd)

                bog_data.extend(btn_data)
                page_data.extend(bog_data)
        else:
            page_data.extend(struct.pack(">HB", 0xFFFF, 0))

        ic_data.extend(page_data)

    # Länge von interactive_composition als uint24 voranstellen
    ic_len = len(ic_data)
    ic_len_bytes = struct.pack(">I", ic_len)[1:] # untere 3 Bytes

    payload = video_desc + comp_desc + seq_desc + ic_len_bytes + bytes(ic_data)
    return make_segment(SEGMENT_ICS, payload)
