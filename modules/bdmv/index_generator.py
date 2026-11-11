# modules/bdmv/index_generator.py
"""
index.bdmv Generator nach BD-ROM Part 3.

Erzeugt die Master-Index-Datei für Blu-ray Discs:
- FirstPlayback: Startet MovieObject 0 (Menü)
- TopMenu: Verweist auf MovieObject 0 (Menü)
- Titles 1..N: Verweisen auf MovieObject 1..N (Hauptfilm, Extras)
"""

import struct

def build_index_bdmv(num_titles: int = 1, has_3d: bool = False) -> bytes:
    """
    Erzeugt den vollständigen Binärinhalt für index.bdmv.
    - num_titles: Anzahl der Titel (Filme/Extras) auf der Disc
    - has_3d: Ob 3D-Stereoscopic (MVC) Inhalte auf der Disc vorhanden sind
    """
    # 1. APP INFO (34 Bytes Payload)
    # Wenn 3D-Inhalte vorhanden sind:
    # Byte 0 = 0x60 (Bit 6: initial_output_mode_preference = 1 [3D HDMI Sync], Bit 5: SS_content_exist_flag = 1)
    # Byte 1 = 0x00 (Exakter Standard nach BD-ROM Profile 5.0 & tsMuxeR)
    app_info_body = bytearray(b"\x00" * 34)
    if has_3d:
        app_info_body[0] = 0x60
        app_info_body[1] = 0x00
    app_info_payload = struct.pack(">I", len(app_info_body)) + bytes(app_info_body)

    # 2. INDEX DATA
    # Ein Playback Object Eintrag hat 12 Bytes:
    # object_type (2b) + reserved (30b) -> 4 Bytes (0x40000000 für HDMV)
    # playback_type (2b) + reserved (14b) + id_ref (16b) -> 4 Bytes
    # reserved -> 4 Bytes
    def make_hdmv_entry(mobj_id: int, is_interactive: bool = False) -> bytes:
        # object_type = 1 (HDMV): Bit 31=0, Bit 30=1 -> 0x40000000
        # access_type = 0 (Permitted): Bits 29..28=0
        obj_type_bytes = struct.pack(">I", 0x40000000)
        # playback_type nach BD-ROM Part 3 / libbluray:
        # 0 = indx_hdmv_playback_type_movie (Linearer Film, VLC zeigt Zeit/Playhead)
        # 1 = indx_hdmv_playback_type_interactive (Menüs mit Loop/IGS)
        # Bit 15=0, Bit 14=playback_type
        pt_flags = 0x4000 if is_interactive else 0x0000
        ref_bytes = struct.pack(">H", pt_flags) + struct.pack(">H", mobj_id)
        reserved_bytes = struct.pack(">I", 0)
        return obj_type_bytes + ref_bytes + reserved_bytes

    index_body = bytearray()
    # FirstPlayback -> MovieObject 0 (Standard nach BD-ROM Part 3 Section 5.2.2: playback_type=0)
    index_body.extend(make_hdmv_entry(0, is_interactive=False))
    # TopMenu -> MovieObject 1 (Interaktives Menü mit IGS-Buttons und Navigation)
    index_body.extend(make_hdmv_entry(1, is_interactive=True))

    # Titles (1..num_titles: Lineare Filme / Hauptfilm & Episoden -> MovieObjects 2..N+1)
    index_body.extend(struct.pack(">H", num_titles))
    for t in range(1, num_titles + 1):
        index_body.extend(make_hdmv_entry(t + 1, is_interactive=False))

    index_payload = struct.pack(">I", len(index_body)) + bytes(index_body)

    # OFFSETS BERECHNEN
    header_len = 40
    indexes_start_address = header_len + len(app_info_payload) # 40 + 38 = 78 (0x4E)
    extension_data_start_address = 0

    # HEADER (40 Bytes nach BD-ROM Part 3)
    # Magic (8B) + Indexes_start (4B) + ExtensionData_start (4B) + Reserved (24B) = 40 Bytes
    header = bytearray()
    header.extend(b"INDX0200")
    header.extend(struct.pack(">II", indexes_start_address, extension_data_start_address))
    header.extend(b"\x00" * 24) # 24 Bytes Reserved

    return bytes(header) + app_info_payload + index_payload

def write_index_bdmv_file(output_path: str, num_titles: int = 1, has_3d: bool = False):
    """Schreibt die index.bdmv Datei auf die Festplatte."""
    data = build_index_bdmv(num_titles=num_titles, has_3d=has_3d)
    with open(output_path, "wb") as f:
        f.write(data)
