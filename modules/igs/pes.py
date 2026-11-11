# modules/igs/pes.py
"""
PES (Packetized Elementary Stream) Packetizer für Blu-ray IGS / PGS.

- Stream ID: 0xBD (Private Stream 1)
- MPEG-2 PES Header mit 33-Bit PTS (90 kHz Zeittakt)
- Unterstützt das Verpacken von IGS Display Sets in standardkonforme PES-Pakete.
"""

import struct
from typing import List

STREAM_ID_PRIVATE_1 = 0xBD

def encode_pts(pts_90khz: int) -> bytes:
    """
    Encodiert einen 33-Bit Presentation Time Stamp (PTS)
    im MPEG-2 5-Byte Format (mit '0010' Präfix für PTS-only).
    """
    pts = pts_90khz & 0x1FFFFFFFF # 33 bits

    pts_32_30 = (pts >> 30) & 0x07
    pts_29_15 = (pts >> 15) & 0x7FFF
    pts_14_00 = pts & 0x7FFF

    b0 = 0x20 | (pts_32_30 << 1) | 0x01
    b1 = (pts_29_15 >> 7) & 0xFF
    b2 = ((pts_29_15 & 0x7F) << 1) | 0x01
    b3 = (pts_14_00 >> 7) & 0xFF
    b4 = ((pts_14_00 & 0x7F) << 1) | 0x01

    return bytes([b0, b1, b2, b3, b4])

def decode_pts(pts_bytes: bytes) -> int:
    """Dekodiert 5 MPEG-2 PTS Bytes zurück in einen Integer (90 kHz)."""
    if len(pts_bytes) < 5:
        raise ValueError("PTS-Bytes müssen mindestens 5 Bytes lang sein.")

    b0, b1, b2, b3, b4 = pts_bytes[:5]
    pts_32_30 = (b0 >> 1) & 0x07
    pts_29_15 = ((b1 & 0xFF) << 7) | ((b2 >> 1) & 0x7F)
    pts_14_00 = ((b3 & 0xFF) << 7) | ((b4 >> 1) & 0x7F)

    pts = (pts_32_30 << 30) | (pts_29_15 << 15) | pts_14_00
    return pts

def packetize_pes(payload: bytes, pts_90khz: int = 0, stream_id: int = STREAM_ID_PRIVATE_1) -> List[bytes]:
    """
    Packt einen Bytestream (z. B. ein oder mehrere IGS-Segmente) in ein oder
    mehrere PES-Pakete (max 65520 Bytes Payload pro Paket).
    """
    max_payload = 65520 # Bleibt sicher unter der 65535 Byte Grenze für uint16
    packets = []
    offset = 0
    total_len = len(payload)

    first_packet = True
    while offset < total_len or first_packet:
        chunk = payload[offset:offset + max_payload]
        offset += len(chunk)

        # PES Header zusammenbauen
        # Start Code Prefix: 0x000001 + stream_id
        start_code = struct.pack(">IB", 0x000001, stream_id)[1:] # 4 Bytes

        if first_packet:
            # Erstes Paket trägt den PTS-Zeitstempel
            pts_bytes = encode_pts(pts_90khz)
            # Flags: 0x80 (MPEG-2), 0x80 (PTS present), Header-Länge = 5
            header_flags = bytes([0x80, 0x80, 5]) + pts_bytes
        else:
            # Folgepakete ohne PTS
            # Flags: 0x80 (MPEG-2), 0x00 (Kein PTS/DTS), Header-Länge = 0
            header_flags = bytes([0x80, 0x00, 0])

        # PES_packet_length: Länge von header_flags + chunk
        pes_packet_len = len(header_flags) + len(chunk)
        if pes_packet_len > 0xFFFF:
            raise ValueError(f"PES Paketlänge {pes_packet_len} überschreitet 16-Bit Maximum.")

        len_field = struct.pack(">H", pes_packet_len)
        packet = start_code + len_field + header_flags + chunk
        packets.append(packet)

        first_packet = False
        if offset >= total_len:
            break

    return packets
