# tests/test_burn_mmc.py
"""Leere BD-R selbst schreiben (v1.34.0, modules/burn/mmc.py): Befehle, Auswertung der Antworten und der Ablauf mit
einem nachgebildeten Laufwerk (läuft auf allen Systemen). Die Rohantworten stammen vom HL-DT-ST BP40NS20 (USB) mit der
ImgBurn-Disc und der IMAPI2-Fehlbrand-Disc vom 2026-11-22 (HARDWARE_TESTS.md)."""

import contextlib
import os
import tempfile
import unittest
from unittest import mock

from modules.burn import mmc
from modules.burn.model import BurnCancelled, BurnError, BurnOptions, Drive, PHASE_WRITE

# Echte Antworten (hex) des BP40NS20
TRACK_IMAPI_FAILED = bytes.fromhex("00260101000421030000000000 81e000 0032 9400 00000020 00b47400 0081dfff"
                                   "0000000000000000".replace(" ", ""))
TRACK_IMGBURN = bytes.fromhex("002601010004a1020000000000000000000000000000002000ba7400 0086323f"
                              "0000000000000000".replace(" ", ""))
SPARE_IMAPI_FAILED = bytes.fromhex("000e000000000000 0002c6a0 00030000".replace(" ", ""))
SPARE_IMGBURN = bytes.fromhex("000e0000000000000000000000000000")
CONFIG_BD_R_SRM = bytes.fromhex("0000005000000041")


def fixed_sense(key, asc, ascq):
    data = bytearray(18)
    data[0], data[2], data[7], data[12], data[13] = 0x70, key, 10, asc, ascq
    return bytes(data)


class FakeBdr(mmc.Device):
    """Leere BD-R 25 GB im Laufwerk: beantwortet die Abfragen, schreibt mit und lässt sich Fehler einbauen."""

    max_transfer = 65536

    def __init__(self, profile=mmc.PROFILE_BD_R_SRM, status=0, free=12_219_392):
        self.profile, self.status, self.free = profile, status, free
        self.nwa = 0
        self.data = bytearray()
        self.commands = []                  # Opcode und Kurzangaben in Reihenfolge
        self.streaming = None
        self.busy_writes = 0                # so oft „Long write in progress“ vor dem nächsten Schreiben
        self.fail_at_lba = None             # Schreibfehler 3/0C/00 bei dieser LBA
        self.reject = set()                 # Opcodes, die mit 5/24/00 abgelehnt werden
        self.reject_finalize = False
        self.on_write = None

    def command(self, cdb, data_out=None, data_in=0, timeout=mmc.TIMEOUT_SHORT):
        op = cdb[0]
        if op in self.reject:
            self.commands.append((op, "rejected"))
            return mmc.parse_sense(fixed_sense(5, 0x24, 0)), b""
        if op == 0x46:
            return None, bytes(6) + self.profile.to_bytes(2, "big")
        if op == 0x51:
            info = bytearray(34)
            info[2] = self.status
            return None, bytes(info)
        if op == 0x52:
            info = bytearray(48)
            info[7] = 0x01                                          # NWA gültig
            info[12:16] = self.nwa.to_bytes(4, "big")
            info[16:20] = (self.free - self.nwa).to_bytes(4, "big")
            info[24:28] = self.free.to_bytes(4, "big")
            return None, bytes(info)
        if op == 0xAD:
            return None, SPARE_IMGBURN
        if op == 0xB6:
            self.commands.append((op,))
            self.streaming = data_out
            return None, b""
        if op == 0x2A:
            lba, count = int.from_bytes(cdb[2:6], "big"), int.from_bytes(cdb[7:9], "big")
            if self.busy_writes:
                self.busy_writes -= 1
                return mmc.parse_sense(fixed_sense(2, 0x04, 0x08)), b""
            if self.fail_at_lba is not None and lba >= self.fail_at_lba:
                return mmc.parse_sense(fixed_sense(3, 0x0C, 0x00)), b""
            assert lba == self.nwa and len(data_out) == count * mmc.SECTOR, (lba, self.nwa, count, len(data_out))
            self.commands.append((op, lba, count))
            self.data += data_out
            self.nwa += count
            if self.on_write:
                self.on_write(lba)
            return None, b""
        if op == 0x5B:
            function, track = cdb[2] & 7, int.from_bytes(cdb[4:6], "big")
            if function == mmc.CLOSE_FINALIZE and self.reject_finalize:
                self.commands.append((op, function, "rejected"))
                return mmc.parse_sense(fixed_sense(5, 0x24, 0)), b""
            self.commands.append((op, function, track))
            if function in (mmc.CLOSE_FINALIZE, mmc.CLOSE_SESSION):
                self.status = 2
            return None, b""
        self.commands.append((op,))
        return None, b""

    def ops(self):
        return [c[0] for c in self.commands]


class Report:
    def __init__(self, cancel_after=None):
        self.phases, self.shares, self.lines = [], [], []
        self.cancel_after = cancel_after

    def phase(self, p):
        self.phases.append(p)

    def progress(self, share):
        self.shares.append(share)

    def log(self, text):
        self.lines.append(text)

    def cancelled(self):
        done = [s for s in self.shares if s]
        return self.cancel_after is not None and len(done) >= self.cancel_after


def make_iso(folder, sectors, name="t.iso"):
    path = os.path.join(folder, name)
    with open(path, "wb") as f:
        for i in range(sectors):
            f.write(bytes([i % 251 + 1]) * mmc.SECTOR)
    return path


class TestCommands(unittest.TestCase):
    def test_cdbs(self):
        self.assertEqual(mmc.cdb_write10(0x01020304, 32).hex(), "2a0001020304000020" + "00")
        self.assertEqual(mmc.cdb_close(mmc.CLOSE_TRACK, 1).hex(), "5b0001000001" + "00" * 4)
        self.assertEqual(mmc.cdb_close(mmc.CLOSE_FINALIZE).hex(), "5b0006" + "00" * 7)
        self.assertEqual(mmc.cdb_synchronize_cache(), bytes([0x35]) + bytes(9))
        self.assertEqual(mmc.cdb_set_streaming().hex(), "b6" + "00" * 8 + "001c00")
        self.assertEqual(mmc.cdb_read_track_information(1).hex(), "52010000000100003000")
        self.assertEqual(mmc.cdb_read_spare_area().hex(), "ad010000000000" + "0a" + "0010" + "0000")
        self.assertEqual(len(mmc.cdb_test_unit_ready()), 6)

    def test_streaming_descriptor_4x_like_imgburn(self):
        kbytes = mmc.kbytes_per_second(8780)                       # IMAPI2: 8780 Sektoren/s = 4x
        self.assertEqual(kbytes, 17981)                             # ImgBurn: „Effective: 17.982 KB/s (4x)“
        desc = mmc.streaming_descriptor(12_219_391, kbytes)
        self.assertEqual(len(desc), 28)
        self.assertEqual(int.from_bytes(desc[8:12], "big"), 12_219_391)
        self.assertEqual(int.from_bytes(desc[20:24], "big"), 17981)
        self.assertEqual(int.from_bytes(desc[24:28], "big"), 1000)

    def test_sizes(self):
        self.assertEqual(mmc.padded_sectors(8_794_688), 8_794_688)          # Untitled_Project.iso: volle Cluster
        self.assertEqual(mmc.padded_sectors(33), 64)
        self.assertEqual(mmc.chunk_sectors(65536), 32)                      # BP40NS20 über USB
        self.assertEqual(mmc.chunk_sectors(128 * 1024 + 2048), 64)
        self.assertEqual(mmc.chunk_sectors(8 << 20), 512)                   # höchstens 1 MiB
        self.assertEqual(mmc.chunk_sectors(16384), 8)


class TestAnswers(unittest.TestCase):
    def test_sense(self):
        self.assertIsNone(mmc.parse_sense(bytes(18)))
        self.assertIsNone(mmc.parse_sense(b""))
        # echt: TEST UNIT READY ohne Disc (BP40NS20 über IMAPI2)
        sense = mmc.parse_sense(bytes.fromhex("700002000000000a000000003a0100000000"))
        self.assertEqual(sense, mmc.Sense(2, 0x3A, 0x01))
        self.assertEqual(sense.text(), "Sense 2/3A/01 MEDIUM NOT PRESENT - TRAY CLOSED")
        self.assertFalse(sense.ok or sense.busy)
        self.assertTrue(mmc.parse_sense(fixed_sense(2, 4, 8)).busy)
        self.assertTrue(mmc.parse_sense(fixed_sense(1, 0x17, 0)).ok)
        self.assertEqual(mmc.parse_sense(bytes([0x72, 3, 0x0C, 0]) + bytes(4)), mmc.Sense(3, 0x0C, 0))
        self.assertEqual(mmc.Sense(0xB, 0x99, 0).text(), "Sense B/99/00 ABORTED COMMAND")

    def test_real_track_info(self):
        failed = mmc.track_info(TRACK_IMAPI_FAILED)
        self.assertEqual((failed["nwa_valid"], failed["nwa"], failed["free"], failed["size"]),
                         (True, 8_511_488, 3_314_688, 11_826_176))       # IMAPI2 formatiert: 11 826 176
        imgburn = mmc.track_info(TRACK_IMGBURN)
        self.assertEqual((imgburn["nwa_valid"], imgburn["size"]), (False, 12_219_392))
        self.assertEqual(mmc.track_info(b"short"), {})

    def test_real_spare_profile_status(self):
        self.assertEqual(mmc.spare_area(SPARE_IMAPI_FAILED), (181_920, 196_608))   # 14 688 ausgelagert
        self.assertEqual(mmc.spare_area(SPARE_IMGBURN), (0, 0))
        self.assertEqual(mmc.current_profile(CONFIG_BD_R_SRM), 0x41)
        self.assertEqual(mmc.disc_status(bytes([0, 0x20, 0x0E])), 2)            # ImgBurn-Disc: abgeschlossen
        self.assertEqual(mmc.disc_status(bytes([0, 0x20, 0x05])), 1)            # Fehlbrand: unvollständig

    def test_blank_problem(self):
        ok = mmc.DiscState(profile=0x41, disc_status=0, nwa=0, nwa_valid=True, free_blocks=12_219_392)
        self.assertEqual(ok.blank_problem(8_794_688), "")
        self.assertEqual(ok.blank_problem(12_219_392), "")
        self.assertIn("zu wenig Platz", ok.blank_problem(12_219_393))
        self.assertIn("0x43", mmc.DiscState(profile=0x43, nwa_valid=True).blank_problem(1))
        self.assertIn("nicht leer", mmc.DiscState(profile=0x41, disc_status=1, nwa_valid=True).blank_problem(1))
        self.assertIn("8511488", mmc.DiscState(profile=0x41, nwa=8_511_488, nwa_valid=True,
                                               free_blocks=10 ** 8).blank_problem(1))


class TestWriter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.device = FakeBdr()
        self.report = Report()
        self.drive = mmc.Drive(self.device, sleep=lambda s: None)
        self.writer = mmc.BdrWriter(self.drive, self.report)

    def burn(self, sectors=100, kbytes=17981):
        iso = make_iso(self.tmp.name, sectors)
        state, problem = self.writer.check(sectors)
        self.assertEqual(problem, "")
        self.writer.set_speed(kbytes, state.free_blocks - 1)
        self.writer.write(iso, 32)
        return iso

    def test_writes_iso_pads_and_closes(self):
        iso = self.burn(100)
        with open(iso, "rb") as f:
            expected = f.read()
        self.assertEqual(len(self.device.data), 128 * mmc.SECTOR)              # auf 4 Cluster aufgefüllt
        self.assertEqual(bytes(self.device.data[:len(expected)]), expected)
        self.assertEqual(bytes(self.device.data[len(expected):]), bytes(28 * mmc.SECTOR))
        writes = [c for c in self.device.commands if c[0] == 0x2A]
        self.assertEqual([(c[1], c[2]) for c in writes], [(0, 32), (32, 32), (64, 32), (96, 32)])
        # Reihenfolge wie bei ImgBurn: Geschwindigkeit, Schreiben, Cache, Spur schließen, abschließen
        self.assertEqual(self.device.ops()[0], 0xB6)
        self.assertEqual([c for c in self.device.commands if c[0] in (0x35, 0x5B)],
                         [(0x35,), (0x5B, mmc.CLOSE_TRACK, 1), (0x5B, mmc.CLOSE_FINALIZE, 0)])
        self.assertEqual(int.from_bytes(self.device.streaming[20:24], "big"), 17981)
        self.assertEqual(self.report.shares[-1], 1.0)
        self.assertIn(PHASE_WRITE, self.report.phases)
        log = "\n".join(self.report.lines)
        self.assertIn("MMC: 100 % · LBA 128", log)
        self.assertIn("+28 Nullsektoren", log)
        self.assertIn("kein Reservebereich", log)                              # Beleg im Protokoll
        self.assertIn("Disc-Status 2", log)

    def test_busy_drive_is_retried(self):
        """„Long write in progress“ (2/04/08): Der Puffer des Laufwerks ist voll – derselbe Befehl wird wiederholt."""
        self.device.busy_writes = 5
        iso = self.burn(64)
        self.assertEqual(self.drive.busy_waits, 5)
        with open(iso, "rb") as f:
            self.assertEqual(bytes(self.device.data), f.read())

    def test_busy_forever_fails(self):
        now = [0.0]
        self.device.busy_writes = 10 ** 9

        def sleep(seconds):
            now[0] += 10.0
        self.drive = mmc.Drive(self.device, sleep=sleep, clock=lambda: now[0])
        self.writer = mmc.BdrWriter(self.drive, self.report)
        with self.assertRaises(BurnError) as ctx:
            self.writer.write(make_iso(self.tmp.name, 32), 32)
        self.assertIn("LONG WRITE IN PROGRESS", str(ctx.exception))

    def test_write_error_names_sense_and_lba(self):
        self.device.fail_at_lba = 32
        with self.assertRaises(BurnError) as ctx:
            self.burn(100)
        self.assertEqual(ctx.exception.phase, PHASE_WRITE)
        self.assertEqual(str(ctx.exception), "Sense 3/0C/00 WRITE ERROR bei LBA 32")
        failure = [line for line in self.report.lines if line.startswith("MMC: Fehler")]
        self.assertEqual(len(failure), 1)
        self.assertIn("geschrieben bis LBA 32", failure[0])
        self.assertIn("nächste beschreibbare Adresse 32", failure[0])
        self.assertNotIn(0x5B, self.device.ops())                              # nicht abgeschlossen

    def test_cancel_syncs_cache_and_leaves_disc_open(self):
        self.report = Report(cancel_after=1)
        self.writer = mmc.BdrWriter(self.drive, self.report)
        with self.assertRaises(BurnCancelled) as ctx:
            self.writer.write(make_iso(self.tmp.name, 256), 32)
        self.assertEqual(ctx.exception.phase, PHASE_WRITE)
        self.assertEqual([c[0] for c in self.device.commands if c[0] != 0x2A], [0x35])
        self.assertEqual(len(self.device.data), 32 * mmc.SECTOR)
        self.assertIn("abgebrochen bei LBA 32", "\n".join(self.report.lines))

    def test_finalize_rejected_closes_session(self):
        self.device.reject_finalize = True
        self.burn(32)
        closes = [c for c in self.device.commands if c[0] == 0x5B]
        self.assertEqual(closes, [(0x5B, 1, 1), (0x5B, 6, "rejected"), (0x5B, 2, 0)])
        self.assertIn("Funktion 2", "\n".join(self.report.lines))

    def test_rejected_speed_is_only_logged(self):
        self.device.reject.add(0xB6)
        self.burn(32)
        self.assertIn("SET STREAMING abgelehnt (Sense 5/24/00 INVALID FIELD IN CDB)", "\n".join(self.report.lines))
        self.assertEqual(len(self.device.data), 32 * mmc.SECTOR)

    def test_recovered_errors_are_counted(self):
        original = self.device.command
        calls = [0]

        def command(cdb, data_out=None, data_in=0, timeout=30):
            sense, data = original(cdb, data_out, data_in, timeout)
            if cdb[0] == 0x2A and calls[0] == 0:
                calls[0] += 1
                return mmc.parse_sense(fixed_sense(1, 0x17, 0x01)), data
            return sense, data
        self.device.command = command
        self.burn(64)
        self.assertEqual(self.drive.recovered, 1)
        self.assertIn("1 vom Laufwerk behobene Fehler", "\n".join(self.report.lines))

    def test_unreadable_iso(self):
        with self.assertRaises(BurnError) as ctx:
            self.writer.write(os.path.join(self.tmp.name, "missing.iso"), 32)
        self.assertIn("ISO", str(ctx.exception))


# --- Windows: Anbindung an das Backend --------------------------------------------------------

class TestWindowsBackend(unittest.TestCase):
    """Das Windows-Backend nimmt für eine leere BD-R den eigenen Weg und sonst IMAPI2 (nachgebildete COM-Objekte aus
    test_burn_windows)."""

    def setUp(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from tests import test_burn_windows as tbw
        from modules.burn import windows
        self.tbw, self.windows = tbw, windows
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.iso = make_iso(self.tmp.name, 100)
        self.world = tbw.World(media_type=18, state=windows.STATE_BLANK | windows.STATE_APPENDABLE, blank=True,
                               speeds=(4390, 8780, 13170), profiles=(65,))
        self.device = FakeBdr()
        self.device.close = lambda: None
        identity = lambda handler: handler                           # noqa: E731
        patches = [
            mock.patch.object(windows, "_create", self.world.create),
            mock.patch.object(windows, "_open_stream", lambda path: ("stream", path)),
            mock.patch.object(windows, "_advise", tbw.fake_advise),
            mock.patch.object(windows, "_sink_classes", lambda: (None, identity, None, identity)),
            mock.patch.object(windows, "com_thread", contextlib.nullcontext),
            mock.patch.object(windows, "MmcDevice", lambda recorder: self.device),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.backend = windows.WindowsBackend.__new__(windows.WindowsBackend)
        self.backend._error = None
        self.drive = Drive(key=tbw.UNIQUE_ID, name="HL-DT-ST BD-RE BP40NS20", device="\\\\.\\I:")

    def test_blank_bd_r_is_written_without_imapi2(self):
        report = Report()
        self.backend.burn(self.drive, self.iso, BurnOptions(speed="4x"), report)
        self.assertEqual(self.world.writers, [])                                # IMAPI2 Write nicht benutzt
        self.assertEqual(len(self.device.data), 128 * mmc.SECTOR)
        self.assertEqual(int.from_bytes(self.device.streaming[20:24], "big"), 17981)
        calls = [c[0] for c in self.world.calls]
        self.assertEqual((calls[0], calls[-1]), ("init", "release"))          # exklusiver Zugriff wie bisher
        self.assertIn("acquire", calls)
        self.assertIn("ohne Defektverwaltung", "\n".join(report.lines))

    def test_not_blank_falls_back_to_imapi2(self):
        self.device.status = 1
        report = Report()
        self.backend.burn(self.drive, self.iso, BurnOptions(speed="4x"), report)
        self.assertEqual(len(self.world.writers), 1)
        self.assertEqual(self.device.data, bytearray())
        self.assertIn("Disc nicht leer (Status 1) – brenne über IMAPI2", "\n".join(report.lines))

    def test_no_device_falls_back_to_imapi2(self):
        def broken(recorder):
            raise OSError("kein IDiscRecorder2Ex")
        with mock.patch.object(self.windows, "MmcDevice", broken):
            report = Report()
            self.backend.burn(self.drive, self.iso, BurnOptions(), report)
        self.assertEqual(len(self.world.writers), 1)
        self.assertIn("kein Zugriff auf das Laufwerk", "\n".join(report.lines))

    def test_write_error_is_not_rerouted(self):
        self.device.fail_at_lba = 0
        with self.assertRaises(BurnError):
            self.backend.burn(self.drive, self.iso, BurnOptions(), Report())
        self.assertEqual(self.world.writers, [])
        self.assertEqual(self.world.calls[-1], ("release",))

    def test_media_shows_free_blocks_without_spare_area(self):
        """IMAPI2 meldet für die leere BD-R 11 826 176 Sektoren (nach Formatieren); frei sind 12 219 392."""
        media = self.backend.media_info(self.drive)
        self.assertEqual(media.kind, "BD-R")
        self.assertEqual(media.free_blocks, 12_219_392)

    def test_media_keeps_imapi_value_without_device(self):
        with mock.patch.object(self.windows, "_blank_bd_r_free_blocks", lambda recorder: None):
            self.assertEqual(self.backend.media_info(self.drive).free_blocks, 11_826_176)


if __name__ == "__main__":
    unittest.main()
