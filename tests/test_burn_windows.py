# tests/test_burn_windows.py
"""Brennen unter Windows (v1.32.0): Auswertung der IMAPI2-Werte und Ablauf von burn() mit nachgebildeten
COM-Objekten (läuft auf allen Systemen). Die Werte stammen aus einem echten Lauf mit dem HL-DT-ST BP40NS20 und einer
BD-RE mit Daten (2026-11-11, siehe modules/burn/windows.py)."""

import contextlib
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from modules.burn import windows
from modules.burn.model import (
    BurnCancelled, BurnError, BurnOptions, Drive, PHASE_ERASE, PHASE_PREPARE, PHASE_VERIFY, PHASE_WRITE,
)

app_instance = QApplication.instance() or QApplication(sys.argv)

UNIQUE_ID = "\\\\?\\usbstor#cdrom&ven_hl-dt-st&prod_bd-re_bp40ns20&rev_ml01#0000000000000000&0#{53f56308}"
PROFILES = (64, 65, 66, 67, 18, 17, 21, 22, 20, 19, 26, 27, 43, 16, 9, 10, 8, 2)


class TestValues(unittest.TestCase):
    def test_speed_label(self):
        self.assertEqual(windows.speed_label(4390), "2x")
        self.assertEqual(windows.speed_label(8780), "4x")
        self.assertEqual(windows.speed_label(13170), "6x")

    def test_can_write_bd(self):
        self.assertTrue(windows.can_write_bd(PROFILES))
        self.assertFalse(windows.can_write_bd((16, 9, 10, 8, 2)))       # nur DVD/CD
        self.assertIsNone(windows.can_write_bd(()))

    def test_device_path(self):
        self.assertEqual(windows.device_path(("I:\\",)), "\\\\.\\I:")
        self.assertEqual(windows.device_path(("e:\\",)), "\\\\.\\E:")
        self.assertEqual(windows.device_path(()), "")
        self.assertEqual(windows.device_path(None), "")

    def test_used_bd_re_from_real_run(self):
        media = windows.media_from_values(19, 1, False, 11826176, 11826176, [4390])
        self.assertEqual((media.media_class, media.kind), ("BD", "BD-RE"))
        self.assertTrue(media.needs_erase)
        self.assertTrue(media.writable)
        self.assertEqual(media.capacity_bytes, 11826176 * 2048)
        self.assertEqual(media.speeds, ["2x"])
        self.assertEqual(media.status, "overwrite only")

    def test_blank_bd_r(self):
        media = windows.media_from_values(18, windows.STATE_BLANK | windows.STATE_APPENDABLE, True, 12219392,
                                          12219392, [8780, 4390, 13170, 4390])
        self.assertEqual(media.kind, "BD-R")
        self.assertTrue(media.blank and media.writable)
        self.assertFalse(media.needs_erase)
        self.assertEqual(media.capacity_bytes, 12219392 * 2048)
        self.assertEqual(media.speeds, ["2x", "4x", "6x"])

    def test_finalized_bd_r_is_not_writable(self):
        media = windows.media_from_values(18, windows.STATE_FINALIZED, False, 0, 12219392, [])
        self.assertFalse(media.writable)
        self.assertEqual(media.capacity_bytes, 0)

    def test_bd_rom_and_dvd(self):
        self.assertEqual(windows.media_from_values(17, 0, False, 0, 0, []).kind, "BD-ROM")
        dvd = windows.media_from_values(7, 1, False, 2295104, 2295104, [])
        self.assertEqual((dvd.media_class, dvd.kind), ("DVD", "DVD+RW"))
        self.assertFalse(dvd.is_bd)

    def test_com_error_text_uses_details(self):
        class FakeComError(Exception):
            hresult = -2147352567
            text = "Ausnahmefehler aufgetreten."
            details = ("Für die Anforderung muss ein aktueller CD-Rekorder ausgewählt sein.\r\n", None)
        with mock.patch.object(windows, "imapi_messages", dict):          # ohne Meldungstabelle: die Hülle
            text = windows.com_error_text(FakeComError())
        self.assertIn("CD-Rekorder", text)
        self.assertIn("0x80020009", text)

    def test_com_error_text_uses_scode_from_excepinfo(self):
        """comtypes legt EXCEPINFO in details: (Text, Quelle, Hilfedatei, Hilfekontext, scode). Der scode ist der
        eigentliche IMAPI2-Fehler, 0x80020009 nur die IDispatch-Hülle."""
        class FakeComError(Exception):
            hresult = -2147352567
            text = "Ausnahmefehler aufgetreten."
            details = ("Fehler beim Schreiben. Das Laufwerk hat Fehlerinformationen zurückgegeben.", "IMAPI2", None, 0,
                       0xC0AA0301 - (1 << 32))
        error = FakeComError()
        self.assertEqual(windows.error_code(error), 0xC0AA0301)
        text = windows.com_error_text(error)
        self.assertIn("Fehler beim Schreiben", text)
        self.assertIn("0xC0AA0301", text)
        self.assertNotIn("0x80020009", text)

    def test_code_from_message_table_when_scode_is_empty(self):
        """Fehlbrand 2026-11-22: IMAPI2 ließ scode leer (0). Der Code wird dann über den Text in der Meldungstabelle
        von imapi2.dll gesucht (Leerraum und Zeilenumbrüche zählen nicht)."""
        table = {0xC0AA0300: "Fehler beim Schreiben. Das Laufwerk hat die Daten nicht schnell genug empfangen.",
                 0xC0AA0301: "Fehler beim Schreiben. Das Laufwerk hat Fehlerinformationen zurückgegeben. Der "
                             "Fehler ist nicht behebbar.\r\n"}

        class FakeComError(Exception):
            hresult = -2147352567
            text = "Ausnahmefehler aufgetreten."
            details = ("Fehler beim Schreiben. Das Laufwerk hat Fehlerinformationen zurückgegeben. Der Fehler ist "
                       "nicht behebbar.", "IMAPI2", None, 0, 0)
        with mock.patch.object(windows, "imapi_messages", lambda: table):
            text = windows.com_error_text(FakeComError())
            self.assertTrue(text.endswith("(0xC0AA0301)"))
            FakeComError.details = ("Etwas anderes.", "IMAPI2", None, 0, 0)
            self.assertIn("(0x80020009)", windows.com_error_text(FakeComError()))     # nicht gefunden: Hülle

    @unittest.skipUnless(sys.platform == "win32", "nur unter Windows")
    def test_real_message_table_has_imapi_codes(self):
        messages = windows.imapi_messages()
        self.assertIn(0xC0AA0301, messages)
        self.assertIn(windows.E_IMAPI_REQUEST_CANCELLED, messages)

    def test_com_error_text_with_odd_details(self):
        class FakeComError(Exception):
            hresult = -2147352567
            text = "Typ passt nicht"
            details = 3                                    # DISP_E_PARAMNOTFOUND: comtypes gibt argerr als int
        self.assertEqual(windows.com_error_text(FakeComError()), "Typ passt nicht (0x80020009)")

    def test_duration_and_factor(self):
        self.assertEqual(windows.duration_text(0), "0:00")
        self.assertEqual(windows.duration_text(125), "2:05")
        self.assertEqual(windows.duration_text(3725), "1:02:05")
        self.assertEqual(windows.factor_text(13170), "6.0x")

    def test_write_clock_measures_each_section(self):
        clock = windows.WriteClock(started=100.0)
        self.assertEqual(clock.text(160.0, 1_000_000, 0), "1:00")             # erste Zeile: nur Zeit
        text = clock.text(260.0, 1_000_000, 439_000)                           # 100 s, 4390 Sektoren/s
        self.assertIn("2:40", text)
        self.assertIn("2.0x (4390 Sektoren/s)", text)
        self.assertIn("noch ca. 2:08", text)                                   # 561 000 / 4390 s
        self.assertEqual(clock.text(260.0, 1_000_000, 439_000), "2:40")       # keine Zeit vergangen: keine Rate

    def test_failure_text(self):
        text = windows.failure_text(2520, 0, 8_794_688, 8_674_911, "non-empty session")
        self.assertIn("nach 42:00", text)
        self.assertIn("LBA 8674911 von 8794688 (98.6 %)", text)
        self.assertIn("Disc danach: non-empty session", text)
        self.assertIn("noch nicht begonnen", windows.failure_text(3, None, 0, None, "blank"))

    def test_tracker(self):
        tracker = windows.WriteTracker()
        tracker.phase = PHASE_WRITE
        self.assertFalse(tracker.feed(windows.ACTION_VALIDATING, 0, 0, 0))
        self.assertIsNone(tracker.progress)
        self.assertTrue(tracker.feed(windows.ACTION_FORMATTING, 0, 0, 0))
        self.assertEqual(tracker.phase, PHASE_ERASE)
        self.assertTrue(tracker.feed(windows.ACTION_WRITING, 0, 1000, 250))
        self.assertEqual((tracker.phase, tracker.progress), (PHASE_WRITE, 0.25))
        tracker.feed(windows.ACTION_FINALIZATION, 0, 0, 0)
        self.assertEqual(tracker.progress, 1.0)


# --- nachgebildete COM-Objekte ---------------------------------------------------------------

class Args:
    def __init__(self, action, start=0, count=0, last=0):
        self.CurrentAction, self.StartLba, self.SectorCount, self.LastWrittenLba = action, start, count, last
        self.RemainingTime = 0


class FakeComError(Exception):
    def __init__(self, text, hresult=-2147352567):
        super().__init__(text)
        self.hresult, self.text, self.details = hresult, "Ausnahmefehler aufgetreten.", (text, None)


class FakeRecorder:
    VendorId, ProductId, ProductRevision = "HL-DT-ST", "BD-RE BP40NS20  ", "ML01"
    VolumePathNames = ("I:\\",)
    SupportedProfiles = PROFILES
    ExclusiveAccessOwner = None

    def __init__(self, world):
        self.world = world
        self.CurrentProfiles = world.profiles

    def InitializeDiscRecorder(self, uid):
        self.world.calls.append(("init", uid))

    def AcquireExclusiveAccess(self, force, name):
        self.world.calls.append(("acquire", force, name))

    def ReleaseExclusiveAccess(self):
        self.world.calls.append(("release",))

    def DisableMcn(self):
        self.world.calls.append(("mcn_off",))

    def EnableMcn(self):
        self.world.calls.append(("mcn_on",))

    def EjectMedia(self):
        self.world.calls.append(("eject",))


class Descriptor:
    def __init__(self, speed):
        self.WriteSpeed = speed


class FakeData:
    def __init__(self, world):
        self.world = world
        self.handler = None
        self.cancelled = False
        self.Recorder = None
        self.ClientName = None
        self.ForceMediaToBeClosed = False
        self.ForceOverwrite = False
        self.CurrentPhysicalMediaType = world.media_type
        self.CurrentMediaStatus = world.state
        self.MediaHeuristicallyBlank = world.blank
        self.FreeSectorsOnMedia = self.TotalSectorsOnMedia = 11826176
        self.NextWritableAddress = 0
        self.SupportedWriteSpeedDescriptors = tuple(Descriptor(s) for s in world.speeds)
        self.CurrentWriteSpeed = world.current_speed

    def IsRecorderSupported(self, recorder):
        return True

    def IsCurrentMediaSupported(self, recorder):
        return True

    def SetWriteSpeed(self, speed, pure_cav):
        self.world.calls.append(("speed", speed))

    def CancelWrite(self):
        self.cancelled = True

    def Write(self, stream):
        self.world.writers.append(self)
        for args in self.world.events:
            self.handler(args)
            if self.cancelled:
                raise FakeComError("Abgebrochen", hresult=windows.E_IMAPI_REQUEST_CANCELLED - (1 << 32))
        if self.world.block_until_cancel:                  # IMAPI2 schreibt, ohne Ereignisse zu melden
            for _ in range(100):
                if self.cancelled:
                    raise FakeComError("Abgebrochen", hresult=windows.E_IMAPI_REQUEST_CANCELLED - (1 << 32))
                time.sleep(0.05)
        if self.world.write_error:
            raise FakeComError(self.world.write_error)


class FakeEraser:
    def __init__(self, world):
        self.world = world
        self.handler = None

    def EraseMedia(self):
        self.world.calls.append(("erase", self.FullErase))
        self.handler(5, 10)


class World:
    def __init__(self, media_type=19, state=1, blank=False, speeds=(4390, 8780), profiles=(67, 2)):
        self.media_type, self.state, self.blank, self.speeds, self.profiles = media_type, state, blank, speeds, profiles
        self.calls, self.writers = [], []
        self.events = [Args(windows.ACTION_VALIDATING), Args(windows.ACTION_WRITING, 0, 100, 50),
                       Args(windows.ACTION_WRITING, 0, 100, 100), Args(windows.ACTION_FINALIZATION),
                       Args(windows.ACTION_COMPLETED)]
        self.write_error = None
        self.block_until_cancel = False
        self.current_speed = 8780

    def create(self, progid):
        return {"IMAPI2.MsftDiscRecorder2": FakeRecorder, "IMAPI2.MsftDiscFormat2Data": FakeData,
                "IMAPI2.MsftDiscFormat2Erase": FakeEraser}[progid](self)


@contextlib.contextmanager
def fake_advise(obj, interface, sink):
    obj.handler = sink
    yield


class Report:
    def __init__(self, cancel_at_progress=None):
        self.phases, self.shares, self.lines = [], [], []
        self.cancel_at_progress = cancel_at_progress

    def phase(self, p):
        self.phases.append(p)

    def progress(self, share):
        self.shares.append(share)

    def log(self, text):
        self.lines.append(text)

    def cancelled(self):
        return self.cancel_at_progress is not None and any(
            s is not None and s >= self.cancel_at_progress for s in self.shares)


class TestBurnFlow(unittest.TestCase):
    def setUp(self):
        self.world = World()
        identity = lambda handler: handler                           # noqa: E731
        patches = [
            mock.patch.object(windows, "_create", self.world.create),
            mock.patch.object(windows, "_open_stream", lambda path: ("stream", path)),
            mock.patch.object(windows, "_advise", fake_advise),
            mock.patch.object(windows, "_sink_classes", lambda: (None, identity, None, identity)),
            mock.patch.object(windows, "com_thread", contextlib.nullcontext),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.backend = windows.WindowsBackend.__new__(windows.WindowsBackend)
        self.backend._error = None
        self.drive = Drive(key=UNIQUE_ID, name="HL-DT-ST BD-RE BP40NS20", device="\\\\.\\I:")

    def test_burn_erases_writes_and_closes(self):
        report = Report()
        result = self.backend.burn(self.drive, "a.iso", BurnOptions(speed="4x", erase=True), report)
        self.assertFalse(result.verified)
        writer = self.world.writers[0]
        self.assertTrue(writer.ForceMediaToBeClosed)
        self.assertTrue(writer.ForceOverwrite)
        self.assertEqual(writer.ClientName, "OpenBDAuth")
        names = [c[0] for c in self.world.calls]
        self.assertLess(names.index("acquire"), names.index("erase"))
        self.assertIn(("erase", False), self.world.calls)            # schnell löschen
        self.assertIn(("speed", 8780), self.world.calls)
        self.assertEqual(names[-2:], ["mcn_on", "release"])
        self.assertEqual(report.phases[:2], [PHASE_ERASE, PHASE_WRITE])
        self.assertIn(0.5, report.shares)
        self.assertEqual(report.shares[-1], 1.0)

    def test_auto_speed_and_no_erase_for_blank_media(self):
        self.world = World(media_type=18, state=windows.STATE_BLANK, blank=True)
        with mock.patch.object(windows, "_create", self.world.create):
            self.backend.burn(self.drive, "a.iso", BurnOptions(), Report())
        names = [c[0] for c in self.world.calls]
        self.assertNotIn("erase", names)
        self.assertNotIn("speed", names)
        self.assertFalse(self.world.writers[0].ForceOverwrite)

    def test_no_media(self):
        self.world.profiles = ()
        with self.assertRaises(BurnError) as ctx:
            self.backend.burn(self.drive, "a.iso", BurnOptions(), Report())
        self.assertEqual(ctx.exception.phase, PHASE_PREPARE)
        self.assertNotIn("acquire", [c[0] for c in self.world.calls])

    def test_write_error_keeps_imapi_text_and_releases(self):
        self.world.write_error = "Das Medium ist schreibgeschützt."
        with self.assertRaises(BurnError) as ctx:
            self.backend.burn(self.drive, "a.iso", BurnOptions(), Report())
        self.assertEqual(ctx.exception.phase, PHASE_WRITE)
        self.assertIn("schreibgeschützt", str(ctx.exception))
        self.assertEqual(self.world.calls[-1], ("release",))

    def test_write_error_logs_how_far_and_disc_state(self):
        """Wie beim Fehlbrand 2026-11-21: Fehler erst beim Abschließen – das Protokoll sagt, wie weit IMAPI2 kam und
        wie die Disc danach dasteht."""
        self.world = World(media_type=18, state=windows.STATE_BLANK | windows.STATE_APPENDABLE, blank=True,
                           speeds=(4390, 8780, 13170))
        self.world.events = self.world.events[:3] + [Args(windows.ACTION_FINALIZATION)]
        self.world.write_error = "Fehler beim Schreiben. Der Fehler ist nicht behebbar."
        report = Report()
        with mock.patch.object(windows, "_create", self.world.create):
            self.world.state = windows.STATE_NON_EMPTY_SESSION      # so liest _media_state die Disc danach
            with self.assertRaises(BurnError):
                self.backend.burn(self.drive, "a.iso", BurnOptions(), report)
        failure = [line for line in report.lines if line.startswith("IMAPI2: Fehler nach")]
        self.assertEqual(len(failure), 1)
        self.assertIn("LBA 100 von 100 (100.0 %)", failure[0])
        self.assertIn("Disc danach: non-empty session", failure[0])
        self.assertIn("IMAPI2: CurrentAction 5 (Abschließen)", " ".join(report.lines))

    def test_cancel_recognised_by_scode(self):
        """Über IDispatch kommt auch der Abbruch als 0x80020009; erkannt wird er am scode."""
        self.world.write_error = "Abgebrochen"
        cancelled = windows.E_IMAPI_REQUEST_CANCELLED - (1 << 32)

        def raise_wrapped(stream):
            error = FakeComError("Abgebrochen")
            error.details = ("Abgebrochen", "IMAPI2", None, 0, cancelled)
            raise error
        with mock.patch.object(FakeData, "Write", lambda self, stream: raise_wrapped(stream)):
            with self.assertRaises(BurnCancelled):
                self.backend.burn(self.drive, "a.iso", BurnOptions(), Report())

    def test_log_names_speed_and_time(self):
        report = Report()
        self.backend.burn(self.drive, "a.iso", BurnOptions(), report)
        log = "\n".join(report.lines)
        self.assertIn("keine Geschwindigkeit gesetzt", log)
        self.assertIn("Schreibgeschwindigkeit 8780 Sektoren/s ≈ 4x", log)
        self.assertIn("Stufen 2x, 4x", log)
        progress = [line for line in report.lines if line.startswith("IMAPI2: 50 %")]
        self.assertEqual(len(progress), 1)
        self.assertRegex(progress[0], r"LBA 50 · \d+:\d\d")
        self.assertFalse(progress[0].endswith(" 0 s"))                    # nicht mehr IMAPI2s RemainingTime

    def test_unknown_speed_choice_is_logged(self):
        report = Report()
        self.backend.burn(self.drive, "a.iso", BurnOptions(speed="8x"), report)
        self.assertNotIn("speed", [c[0] for c in self.world.calls])
        self.assertIn("8x wird für dieses Medium nicht angeboten", "\n".join(report.lines))

    def test_cancel_during_write_calls_cancel_write(self):
        report = Report(cancel_at_progress=0.5)
        with self.assertRaises(BurnCancelled) as ctx:
            self.backend.burn(self.drive, "a.iso", BurnOptions(), report)
        self.assertEqual(ctx.exception.phase, PHASE_WRITE)
        self.assertTrue(self.world.writers[0].cancelled)
        self.assertIn("IMAPI2: CancelWrite", report.lines)
        self.assertEqual(self.world.calls[-1], ("release",))

    def test_cancel_without_events_uses_watcher(self):
        self.world.events = []
        self.world.block_until_cancel = True
        report = Report()
        report.cancelled = lambda: bool(self.world.writers)        # Abbruch erst, wenn Write läuft
        with self.assertRaises(BurnCancelled):
            self.backend.burn(self.drive, "a.iso", BurnOptions(), report)
        self.assertTrue(self.world.writers[0].cancelled)

    def test_verify_reads_back_through_device(self):
        with mock.patch("modules.burn.verify.compare_with_device", return_value=True) as compare:
            report = Report()
            result = self.backend.burn(self.drive, "a.iso", BurnOptions(verify=True), report)
        self.assertTrue(result.verified)
        compare.assert_called_once()
        self.assertEqual(compare.call_args[0][:2], ("\\\\.\\I:", "a.iso"))
        self.assertEqual(report.phases[-1], PHASE_VERIFY)

    def test_list_drives_and_media(self):
        with mock.patch.object(windows, "_recorders", lambda: [(UNIQUE_ID, self.world.create(
                "IMAPI2.MsftDiscRecorder2"))]):
            drives = self.backend.list_drives()
        self.assertEqual(len(drives), 1)
        self.assertEqual(drives[0].name, "HL-DT-ST BD-RE BP40NS20")
        self.assertEqual((drives[0].device, drives[0].interconnect), ("\\\\.\\I:", "USB"))
        self.assertTrue(drives[0].can_write_bd)
        media = self.backend.media_info(drives[0])
        self.assertEqual((media.kind, media.speeds), ("BD-RE", ["2x", "4x"]))

    def test_eject(self):
        self.assertTrue(self.backend.eject(self.drive))
        self.assertIn(("eject",), self.world.calls)


class TestWindowsInApp(unittest.TestCase):
    def test_backend_selected_on_windows(self):
        from modules.burn import get_backend
        with mock.patch.object(sys, "platform", "win32"), \
                mock.patch.object(windows, "_comtypes", lambda: None):
            backend = get_backend()
        self.assertIsInstance(backend, windows.WindowsBackend)
        self.assertIsNone(backend.unavailable_reason())

    def test_missing_comtypes_is_explained(self):
        from gui.burn.page import BurnPage

        def broken():
            raise ImportError("No module named 'comtypes'")
        with mock.patch.object(windows, "_comtypes", broken):
            page = BurnPage(backend=windows.WindowsBackend(), persist=False)
        self.assertFalse(page.usable)
        self.assertIn("IMAPI2", page.lbl_unavailable.text())


class FlakyFile:
    """Dateiobjekt, das beim n-ten Lesen OSError wirft (wie unter Windows beim ersten Brand)."""

    def __init__(self, path, fail_reads):
        self.f = open(path, "rb")
        self.fail_reads = fail_reads
        self.reads = 0

    def seek(self, pos):
        self.f.seek(pos)

    def read(self, n):
        self.reads += 1
        if self.reads in self.fail_reads:
            raise OSError(22, "Invalid argument")
        return self.f.read(n)

    def close(self):
        self.f.close()


class BadFromFile(FlakyFile):
    """Ab einer Position dauerhaft unlesbar (wie ein beschädigter Bereich der Disc)."""

    def __init__(self, path, bad_from):
        super().__init__(path, set())
        self.bad_from = bad_from

    def read(self, n):
        if self.f.tell() >= self.bad_from:
            raise OSError(22, "Invalid argument")
        return self.f.read(n)


class TestVerifyRetry(unittest.TestCase):
    def setUp(self):
        from modules.burn import verify
        self.verify = verify
        self.tmp = tempfile.mkdtemp(prefix="verify_")
        self.iso = os.path.join(self.tmp, "a.iso")
        with open(self.iso, "wb") as f:
            f.write(os.urandom(verify.BLOCK * 2 + 2048 * 3))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, True))
        self.opened = []

    def reader(self, fail_reads):
        """DeviceReader, dessen Gerät die ISO-Datei ist; jedes (Neu-)Öffnen zählt seine eigenen Lesevorgänge."""
        reader = self.verify.DeviceReader(self.iso, retry_wait=0, log=lambda text: self.opened.append(text))

        def fake_open():
            reader._file = FlakyFile(self.iso, fail_reads if not any(isinstance(o, FlakyFile) for o in self.opened)
                                     else set())
            self.opened.append(reader._file)
        reader._open = fake_open
        return reader

    def test_single_read_error_is_retried(self):
        reader = self.reader({2})
        with open(self.iso, "rb") as iso:
            self.verify.compare_streams(reader, iso, os.path.getsize(self.iso), Report())
        reader.close()
        self.assertEqual(sum(isinstance(o, FlakyFile) for o in self.opened), 2)       # einmal neu geöffnet
        self.assertTrue(any("Lesefehler bei Sektor 2048" in str(o) for o in self.opened))

    def test_lasting_read_error_names_sector(self):
        reader = self.verify.DeviceReader(self.iso, retry_wait=0)
        reader._open = lambda: setattr(reader, "_file", BadFromFile(self.iso, self.verify.BLOCK))
        with open(self.iso, "rb") as iso, self.assertRaises(BurnError) as ctx:
            self.verify.compare_streams(reader, iso, os.path.getsize(self.iso), Report())
        self.assertEqual(ctx.exception.phase, PHASE_VERIFY)
        self.assertIn("2048", str(ctx.exception))
        self.assertIn("Invalid argument", str(ctx.exception))


@unittest.skipUnless(os.name == "nt", "nur unter Windows")
class TestWindowsDeviceSize(unittest.TestCase):
    def test_plain_file_falls_back_to_seek(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"\0" * 4096)
        self.addCleanup(os.unlink, f.name)
        from modules.burn import verify
        self.assertIsNone(verify._windows_device_size(f.name))     # Dateien haben keine Disk-Länge …
        self.assertEqual(verify.device_size(f.name), 4096)          # … dann gilt seek(END)


if __name__ == "__main__":
    unittest.main()
