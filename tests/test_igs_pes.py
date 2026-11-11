# tests/test_igs_pes.py
import unittest
import struct
from modules.igs.pes import encode_pts, decode_pts, packetize_pes, STREAM_ID_PRIVATE_1

class TestIGSPES(unittest.TestCase):
    def test_pts_roundtrip(self):
        test_values = [0, 1, 45000, 90000, 90000 * 60, 0x1FFFFFFFF]
        for pts in test_values:
            encoded = encode_pts(pts)
            self.assertEqual(len(encoded), 5)
            # Prüfe '0010' Marker
            self.assertEqual((encoded[0] >> 4) & 0x0F, 0x02)
            # Prüfe Marker-Bits an Bit 0 von Bytes 0, 2, 4
            self.assertEqual(encoded[0] & 1, 1)
            self.assertEqual(encoded[2] & 1, 1)
            self.assertEqual(encoded[4] & 1, 1)

            decoded = decode_pts(encoded)
            self.assertEqual(decoded, pts)

    def test_single_pes_packet(self):
        dummy_payload = b"Hello OpenBDAuth IGS"
        pts = 90000 # 1 Sekunde bei 90 kHz
        packets = packetize_pes(dummy_payload, pts_90khz=pts)
        self.assertEqual(len(packets), 1)

        pkt = packets[0]
        # Startcode Prefix (3B) + Stream-ID (1B)
        self.assertEqual(pkt[:3], bytes([0, 0, 1]))
        self.assertEqual(pkt[3], STREAM_ID_PRIVATE_1)

        # PES Paketlänge
        pkt_len = struct.unpack(">H", pkt[4:6])[0]
        self.assertEqual(pkt_len, len(pkt) - 6)

        # Flags: 0x80, 0x80, 5 + 5 Bytes PTS
        self.assertEqual(pkt[6:9], bytes([0x80, 0x80, 5]))
        pts_decoded = decode_pts(pkt[9:14])
        self.assertEqual(pts_decoded, pts)

        # Payload
        self.assertEqual(pkt[14:], dummy_payload)

    def test_large_payload_splitting(self):
        # 100 KB Payload erfordert mindestens 2 PES Pakete
        large_payload = b"X" * 100000
        packets = packetize_pes(large_payload)
        self.assertGreater(len(packets), 1)

        # Zusammenfügen der Payloads aus den Paketen
        reassembled = bytearray()
        for i, pkt in enumerate(packets):
            # Prüfe Startcode
            self.assertEqual(pkt[:4], bytes([0, 0, 1, STREAM_ID_PRIVATE_1]))
            header_len = 9 + pkt[8] # 6B Start+Len + 3B Flags/HdrLen + HdrDataLen
            reassembled.extend(pkt[header_len:])

        self.assertEqual(bytes(reassembled), large_payload)

if __name__ == '__main__':
    unittest.main()
