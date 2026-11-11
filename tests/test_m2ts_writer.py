# tests/test_m2ts_writer.py
import unittest
import struct
from modules.m2ts.ts_packetizer import (
    TS_PACKET_SIZE, SYNC_BYTE, PID_PAT, PID_PMT, PID_IGS,
    STREAM_TYPE_IGS, mpeg2_crc32, make_ts_packet,
    build_pat_packet, build_pmt_packet
)
from modules.m2ts.m2ts_writer import (
    M2TS_PACKET_SIZE, add_tp_extra_header, build_igs_m2ts
)

class TestM2TSWriter(unittest.TestCase):
    def test_crc32_mpeg2(self):
        # Einfacher Testvektor: ASCII "123456789" hat bekannten MPEG-2 CRC 0x0376EEC7
        data = b"123456789"
        crc = mpeg2_crc32(data)
        self.assertEqual(crc, 0x0376E6E7)

    def test_make_ts_packet_structure(self):
        payload = b"test payload 123"
        pkt = make_ts_packet(pid=PID_IGS, pusi=True, cc=5, payload=payload)
        self.assertEqual(len(pkt), TS_PACKET_SIZE)
        self.assertEqual(pkt[0], SYNC_BYTE)

        # PID prüfen
        pid_parsed = ((pkt[1] & 0x1F) << 8) | pkt[2]
        self.assertEqual(pid_parsed, PID_IGS)

        # PUSI prüfen (Bit 6 in Byte 1)
        self.assertEqual((pkt[1] >> 6) & 1, 1)

        # Continuity Counter prüfen (untere 4 Bits in Byte 3)
        self.assertEqual(pkt[3] & 0x0F, 5)

    def test_pat_packet(self):
        pkt = build_pat_packet(pmt_pid=PID_PMT, program_number=1, cc=0)
        self.assertEqual(len(pkt), TS_PACKET_SIZE)
        self.assertEqual(pkt[0], SYNC_BYTE)

        # PID 0x0000
        pid = ((pkt[1] & 0x1F) << 8) | pkt[2]
        self.assertEqual(pid, PID_PAT)

    def test_pmt_packet(self):
        pkt = build_pmt_packet(pcr_pid=PID_IGS, igs_pid=PID_IGS, program_number=1, cc=0)
        self.assertEqual(len(pkt), TS_PACKET_SIZE)
        self.assertEqual(pkt[0], SYNC_BYTE)

        # PID 0x0100
        pid = ((pkt[1] & 0x1F) << 8) | pkt[2]
        self.assertEqual(pid, PID_PMT)

        # Stream Typ 0x91 muss im PMT Payload enthalten sein
        self.assertIn(bytes([STREAM_TYPE_IGS]), pkt)

    def test_tp_extra_header(self):
        ts_dummy = bytes([SYNC_BYTE] + [0] * 187)
        ats = 0x12345678
        m2ts_pkt = add_tp_extra_header(ts_dummy, ats=ats, copy_permission=0)
        self.assertEqual(len(m2ts_pkt), M2TS_PACKET_SIZE)

        # Extra Header prüfen (obere 4 Bytes)
        hdr = struct.unpack(">I", m2ts_pkt[:4])[0]
        self.assertEqual(hdr & 0x3FFFFFFF, ats)
        # Sync-Byte an Offset 4
        self.assertEqual(m2ts_pkt[4], SYNC_BYTE)

    def test_build_igs_m2ts_stream(self):
        fake_pes = b"FAKE_IGS_PES_DATA_" * 20
        m2ts = build_igs_m2ts(fake_pes, igs_pid=PID_IGS)

        # Gesamtlänge muss ein Vielfaches von 6144 Bytes (32 M2TS-Pakete / Aligned Unit) sein
        self.assertGreater(len(m2ts), 0)
        self.assertEqual(len(m2ts) % M2TS_PACKET_SIZE, 0)
        self.assertEqual(len(m2ts) % 6144, 0)

        # Prüfe jedes einzelne Paket: Sync-Byte an Offset 4, 196, 388...
        num_pkts = len(m2ts) // M2TS_PACKET_SIZE
        self.assertGreaterEqual(num_pkts, 3) # Mindestens PAT + PMT + 1 IGS Paket

        for i in range(num_pkts):
            pkt_start = i * M2TS_PACKET_SIZE
            sync = m2ts[pkt_start + 4]
            self.assertEqual(sync, SYNC_BYTE, f"Paket {i} hat ungültiges Sync-Byte: {hex(sync)}")

if __name__ == '__main__':
    unittest.main()
