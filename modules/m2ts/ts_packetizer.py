# modules/m2ts/ts_packetizer.py
"""
MPEG-2 Transport Stream (188 Bytes) Paketierung für Blu-ray HDMV IGS SubClips
nach ISO/IEC 13818-1 und BD-ROM Part 3.

- Erzeugt 188-Byte TS-Pakete mit Sync-Byte 0x47
- Program Association Table (PAT, PID 0x0000)
- Program Map Table (PMT, PID 0x0100) mit Stream-Typ 0x91 für HDMV IGS (PID 0x1400)
- PES-Stream Zerlegung in TS-Pakete mit Adaptation Field Padding
"""

import struct
from typing import List, Optional, Tuple

TS_PACKET_SIZE = 188
SYNC_BYTE = 0x47

PID_PAT = 0x0000
PID_PMT = 0x0100
PID_IGS = 0x1400 # Standard-PID für ersten HDMV IG Stream auf Blu-ray

STREAM_TYPE_IGS = 0x91 # Offizieller BD-ROM Stream-Typ für Interactive Graphics

def mpeg2_crc32(data: bytes) -> int:
    """Berechnet die MPEG-2 standardkonforme 32-Bit CRC (Poly 0x04C11DB7)."""
    crc = 0xFFFFFFFF
    for b in data:
        crc ^= (b << 24)
        for _ in range(8):
            if crc & 0x80000000:
                crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF
            else:
                crc = (crc << 1) & 0xFFFFFFFF
    return crc

def make_ts_packet(
    pid: int,
    pusi: bool,
    cc: int,
    payload: bytes,
    adaptation_field: Optional[bytes] = None
) -> bytes:
    """
    Erzeugt ein einzelnes, standardkonformes 188-Byte MPEG-2 Transport Stream Paket.
    Füllt den verbleibenden Platz automatisch mit Adaptation Field Stuffing auf.
    """
    if len(payload) > 184:
        raise ValueError(f"Payload ({len(payload)} Bytes) zu groß für ein einzelnes TS-Paket.")

    # Header Bytes 1 & 2
    b1 = ((1 if pusi else 0) << 6) | ((pid >> 8) & 0x1F)
    b2 = pid & 0xFF

    payload_len = len(payload)
    if payload_len == 184 and adaptation_field is None:
        # Reines Payload-Paket
        af_ctrl = 0x01
        b3 = (af_ctrl << 4) | (cc & 0x0F)
        pkt = bytes([SYNC_BYTE, b1, b2, b3]) + payload
    else:
        # Paket mit Adaptation Field (für Stuffing oder PCR)
        af_ctrl = 0x03
        b3 = (af_ctrl << 4) | (cc & 0x0F)
        
        # Das gesamte Adaptation Field (ohne Längenbyte) muss N Bytes lang sein:
        # 1 (af_length_byte) + N + payload_len == 184  ==> N = 183 - payload_len
        n = 183 - payload_len
        if n < 0:
            raise ValueError(f"Payload ({payload_len}) zu groß für TS-Paket mit Adaptation Field.")

        af_body = bytearray()
        if adaptation_field is not None:
            if len(adaptation_field) > n:
                raise ValueError(f"Adaptation Field Daten ({len(adaptation_field)}) passen nicht in {n} verfügbare Bytes.")
            af_body.extend(adaptation_field)
            # Rest mit 0xFF auffüllen
            af_body.extend(b"\xFF" * (n - len(adaptation_field)))
        else:
            # Reines Stuffing: wenn N >= 1, erstes Byte ist Flags (0x00), Rest 0xFF
            if n >= 1:
                af_body.append(0x00) # Flags: keine PCR, etc.
                af_body.extend(b"\xFF" * (n - 1))

        header = bytes([SYNC_BYTE, b1, b2, b3, n & 0xFF])
        pkt = header + bytes(af_body) + payload

    if len(pkt) != TS_PACKET_SIZE:
        raise RuntimeError(f"TS Paketgröße ist {len(pkt)}, erwartet werden exakt {TS_PACKET_SIZE} Bytes.")
    return pkt

def build_pat_packet(pmt_pid: int = PID_PMT, program_number: int = 1, ts_id: int = 1, cc: int = 0) -> bytes:
    """Erzeugt ein Program Association Table (PAT) TS-Paket auf PID 0x0000."""
    section = bytearray()
    table_id = 0x00
    section_syntax_indicator = 1
    zero_bit = 0
    reserved = 3

    # Program entry: program_number (2B) + reserved (3bit) + pmt_pid (13bit)
    prog_entry = struct.pack(">HH", program_number, 0xE000 | (pmt_pid & 0x1FFF))

    # Header: table_id (1B) + syntax/len (2B) + ts_id (2B) + ver/cni (1B) + sec_num (1B) + last_sec_num (1B)
    # Payload vor CRC: 5 Bytes + len(prog_entry) = 9 Bytes. Plus 4 Bytes CRC = 13 Bytes section_length.
    section_length = 5 + len(prog_entry) + 4
    b1_b2 = struct.pack(">H", 0xB000 | (section_length & 0x0FFF)) # 1011 0000 ...

    sec_hdr = bytes([table_id]) + b1_b2 + struct.pack(">HBBB", ts_id, 0xC1, 0, 0) # Version 0, current=1
    crc_data = sec_hdr + prog_entry
    crc = mpeg2_crc32(crc_data)
    full_section = crc_data + struct.pack(">I", crc)

    # In PSI-Tabellen steht vor der Section 1 Byte pointer_field (hier 0x00)
    payload = b"\x00" + full_section
    return make_ts_packet(pid=PID_PAT, pusi=True, cc=cc, payload=payload)

def build_pmt_packet(
    pcr_pid: int = PID_IGS,
    igs_pid: int = PID_IGS,
    program_number: int = 1,
    cc: int = 0
) -> bytes:
    """
    Erzeugt ein Program Map Table (PMT) TS-Paket auf PID 0x0100.
    Deklariert Stream-Typ 0x91 (Blu-ray HDMV IGS) auf PID 0x1400.
    """
    table_id = 0x02
    
    # HDMV Registration Descriptor (Tag 0x05, Length 4, "HDMV") nach BD-ROM Spezifikation
    hdmv_desc = bytes([0x05, 0x04]) + b"HDMV"
    prog_info_len = len(hdmv_desc)

    # Elementary Stream Info für IGS:
    # stream_type (1B): 0x91
    # reserved (3bit) + elementary_PID (13bit): 0xE000 | igs_pid
    # reserved (4bit) + ES_info_length (12bit): 0xF000 (keine zusätzlichen Descriptoren nötig)
    es_info = struct.pack(">BHH", STREAM_TYPE_IGS, 0xE000 | (igs_pid & 0x1FFF), 0xF000)

    # Section-Länge: 9 Bytes Header + len(hdmv_desc) + len(es_info) + 4 Bytes CRC
    # 9 Bytes = ts_id/prog_num(2B) + ver/cni(1B) + sec_num(1B) + last_sec_num(1B) + pcr_pid(2B) + prog_info_len(2B)
    section_length = 9 + prog_info_len + len(es_info) + 4
    b1_b2 = struct.pack(">H", 0xB000 | (section_length & 0x0FFF))

    sec_hdr = bytes([table_id]) + b1_b2 + struct.pack(
        ">HBBBHH", 
        program_number, 0xC1, 0, 0, 
        0xE000 | (pcr_pid & 0x1FFF), 
        0xF000 | (prog_info_len & 0x0FFF)
    ) + hdmv_desc

    crc_data = sec_hdr + es_info
    crc = mpeg2_crc32(crc_data)
    full_section = crc_data + struct.pack(">I", crc)

    payload = b"\x00" + full_section
    return make_ts_packet(pid=PID_PMT, pusi=True, cc=cc, payload=payload)

def encode_pcr(pcr_90khz: int) -> bytes:
    """
    Encodiert einen 6-Byte Program Clock Reference (PCR) Wert
    nach MPEG-2 (33-Bit Base bei 90 kHz + 6-Bit reserviert + 9-Bit Extension bei 27 MHz).
    """
    base = pcr_90khz & 0x1FFFFFFFF
    ext = 0
    b0 = (base >> 25) & 0xFF
    b1 = (base >> 17) & 0xFF
    b2 = (base >> 9) & 0xFF
    b3 = (base >> 1) & 0xFF
    b4 = ((base & 1) << 7) | 0x7E | ((ext >> 8) & 1)
    b5 = ext & 0xFF
    return bytes([b0, b1, b2, b3, b4, b5])

def packetize_pes_to_ts(
    pes_data: bytes,
    pid: int = PID_IGS,
    start_cc: int = 0,
    pcr_90khz: Optional[int] = None
) -> Tuple[List[bytes], int]:
    """
    Zerlegt einen oder mehrere PES-Pakete in 188-Byte TS-Pakete auf der angegebenen PID.
    Jedes PES-Paket beginnt zwingend in einem neuen TS-Paket mit PUSI=True (Payload Unit Start Indicator).
    Nicht vollständig gefüllte Endpakete eines PES-Pakets werden per Adaptation Field Stuffing aufgefüllt.
    Das allererste TS-Paket erhält optional die PCR.
    Gibt die Liste der TS-Pakete und den nächsten Continuity Counter zurück.
    """
    # 1. Zerlege pes_data in einzelne PES-Pakete anhand des PES-Headers (0x000001)
    pes_packets: List[bytes] = []
    idx = 0
    total_pes_bytes = len(pes_data)
    while idx < total_pes_bytes:
        if idx + 6 > total_pes_bytes:
            pes_packets.append(pes_data[idx:])
            break
        # Prüfe PES Start Code 0x000001
        if pes_data[idx:idx+3] == b"\x00\x00\x01":
            pes_len = struct.unpack(">H", pes_data[idx+4:idx+6])[0]
            if pes_len > 0:
                pkt_total = 6 + pes_len
                pes_packets.append(pes_data[idx:idx+pkt_total])
                idx += pkt_total
                continue
        # Fallback falls kein PES Start Code erkannt wird
        pes_packets.append(pes_data[idx:])
        break

    if not pes_packets:
        return [], start_cc

    all_ts_packets: List[bytes] = []
    cc = start_cc & 0x0F
    is_disc_first = True

    for single_pes in pes_packets:
        offset = 0
        pes_len = len(single_pes)
        is_pes_first = True

        while offset < pes_len:
            pusi = is_pes_first
            af = None

            if is_disc_first and pcr_90khz is not None:
                # Adaptation Field mit PCR im allerersten Paket des gesamten Streams
                af = bytes([0x10]) + encode_pcr(pcr_90khz)
                is_disc_first = False

            af_overhead = (len(af) + 1) if af is not None else 0
            max_chunk = 184 - af_overhead

            chunk = single_pes[offset:offset + max_chunk]
            offset += len(chunk)

            pkt = make_ts_packet(
                pid=pid,
                pusi=pusi,
                cc=cc,
                payload=chunk,
                adaptation_field=af
            )
            all_ts_packets.append(pkt)
            cc = (cc + 1) & 0x0F
            is_pes_first = False

    return all_ts_packets, cc
