# modules/m2ts/m2ts_writer.py
"""
M2TS Writer für Blu-ray HDMV SubClips nach BD-ROM Part 3.

- Fügt 4-Byte TP_extra_header (30-Bit Arrival Time Stamp / ATS) hinzu
- 192-Byte Paketierung
- Schreibt vollständige, standardkonforme IGS SubClips (.m2ts)
"""

import struct
from typing import List, Union
from modules.m2ts.ts_packetizer import (
    TS_PACKET_SIZE, build_pat_packet, build_pmt_packet,
    packetize_pes_to_ts, PID_IGS
)

M2TS_PACKET_SIZE = 192

# ATS-Berechnung nach BD-ROM Spezifikation:
# ATS-Takt läuft bei 27 MHz (27_000_000 Hz).
# Bei maximaler Blu-ray Transport-Bitrate von 48 Mbps:
# Ticks pro 192-Byte Paket = (192 Bytes * 8 Bits * 27_000_000 Hz) / 48_000_000 bps = 864 Ticks.
DEFAULT_ATS_STEP = 864

def add_tp_extra_header(ts_packet: bytes, ats: int, copy_permission: int = 0) -> bytes:
    """
    Fügt einem 188-Byte TS-Paket den 4-Byte TP_extra_header hinzu
    (2-Bit Copy Permission Indicator + 30-Bit Arrival Time Stamp).
    Ergebnis: Exakt 192 Bytes.
    """
    if len(ts_packet) != TS_PACKET_SIZE:
        raise ValueError(f"TS-Paketgröße muss {TS_PACKET_SIZE} sein, ist aber {len(ts_packet)}.")

    header_32 = ((copy_permission & 0x03) << 30) | (ats & 0x3FFFFFFF)
    extra_header = struct.pack(">I", header_32)
    return extra_header + ts_packet

def build_igs_m2ts(
    pes_stream: bytes,
    igs_pid: int = PID_IGS,
    pts_90khz: int = 54000000,
    ats_step: int = DEFAULT_ATS_STEP
) -> bytes:
    """
    Erzeugt einen kompletten, binären 192-Byte M2TS-SubClip aus einem IGS-PES-Stream.
    - PAT Paket (PID 0x0000)
    - PMT Paket (PID 0x0100 mit Stream Type 0x91 für IGS)
    - IGS TS-Pakete (PID 0x1400)
    - Alle Pakete mit fortlaufendem Arrival Time Stamp (ATS)
    - Aufgefüllt auf Aligned Units (Vielfaches von 6.144 Bytes / 32 Pakete)
    """
    ts_packets: List[bytes] = []

    # 1. PAT Paket (PID 0x0000)
    pat_pkt = build_pat_packet(cc=0)
    ts_packets.append(pat_pkt)

    # 2. PMT Paket (PID 0x0100)
    pmt_pkt = build_pmt_packet(pcr_pid=igs_pid, igs_pid=igs_pid, cc=0)
    ts_packets.append(pmt_pkt)

    # 3. IGS PES Daten in TS-Pakete verpacken
    # Mit PCR im ersten Paket synchron zum PTS
    igs_ts_pkts, _ = packetize_pes_to_ts(
        pes_stream, 
        pid=igs_pid, 
        start_cc=0, 
        pcr_90khz=pts_90khz
    )
    ts_packets.extend(igs_ts_pkts)

    # 4. In 192-Byte M2TS Pakete konvertieren
    m2ts_data = bytearray()
    ats = 0

    for pkt in ts_packets:
        m2ts_pkt = add_tp_extra_header(pkt, ats=ats)
        m2ts_data.extend(m2ts_pkt)
        ats = (ats + ats_step) & 0x3FFFFFFF

    # 5. Auf Aligned Units (Vielfaches von 6.144 Bytes = 32 Pakete) auffüllen
    null_ts = b'\x47\x1f\xff\x10' + (b'\xff' * 184)
    while len(m2ts_data) % 6144 != 0:
        m2ts_pkt = add_tp_extra_header(null_ts, ats=ats)
        m2ts_data.extend(m2ts_pkt)
        ats = (ats + ats_step) & 0x3FFFFFFF

    return bytes(m2ts_data)

def write_igs_m2ts_file(
    output_path: str,
    pes_stream: bytes,
    igs_pid: int = PID_IGS,
    pts_90khz: int = 54000000
):
    """Schreibt den erzeugten M2TS-SubClip direkt in eine Datei."""
    m2ts_bytes = build_igs_m2ts(pes_stream, igs_pid=igs_pid, pts_90khz=pts_90khz)
    with open(output_path, "wb") as f:
        f.write(m2ts_bytes)
