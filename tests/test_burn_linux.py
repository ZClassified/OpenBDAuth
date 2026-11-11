# tests/test_burn_linux.py
"""Brennen unter Linux (v1.31.0): Auswertung der xorriso-Ausgaben, Prüfen gegen das Gerät, Diagnose.

Die Beispielausgaben stammen aus echten Läufen von GNU xorriso 1.5.6 (Pseudo-Laufwerk stdio:) bzw. – für Laufwerk und
Blu-ray-Medium – aus den Formatzeilen im Quelltext (drive_mgt.c). Ist xorriso installiert (oder über
OPENBDAUTH_TEST_XORRISO angegeben), brennt ein Test wirklich: auf ein Pseudo-Laufwerk (Datei) und vergleicht."""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from modules.burn import linux, verify
from modules.burn.model import BurnCancelled, BurnError, BurnOptions, Drive, PHASE_VERIFY, PHASE_WRITE

app_instance = QApplication.instance() or QApplication(sys.argv)

DEVICES = """GNU xorriso 1.5.6.pl02 : RockRidge filesystem manipulator, libburnia project.

Beginning to scan for devices ...
Full drive scan done
-----------------------------------------------------------------------------
0  -dev '/dev/sr0' rwrw-- :  'HL-DT-ST' 'BD-RE BP40NS20'
1  -dev '/dev/sr1' rwrw-- :  'HL-DT-ST' 'DVDRAM GH24NSD1'
-----------------------------------------------------------------------------
"""
NO_DRIVES = """Beginning to scan for devices ...
libburn : WARNING : No MMC transport adapter is present. Running on sg-dummy.c.
xorriso : SORRY : No drives found
"""
TOC_BD_RE_USED = """Drive current: -indev '/dev/sr0'
Drive access : shared:readonly
Media current: BD-RE
Media status : is written , is appendable
Media summary: 1 session, 3868896 data blocks, 7556m data, 15.8g free
Drive current: -indev '/dev/sr0'
Drive access : shared:readonly
Drive type   : vendor 'HL-DT-ST' product 'BD-RE BP40NS20' revision 'ML01'
Media current: BD-RE
Media status : is written , is appendable
Media blocks : 3868896 readable , 8350496 writable , 12219392 overall
Write speed  :   8990k ,  2.0xBD
Write speed  :  17980k ,  4.0xBD
Write speed L:   8990k ,  2.0xBD
Write speed H:  17980k ,  4.0xBD
"""
TOC_BD_R_BLANK = """Media current: BD-R sequential recording
Media status : is blank
Media blocks : 0 readable , 12219392 writable , 12219392 overall
Write speed  :  26970k ,  6.0xBD
"""
TOC_NO_DISC = """Drive current: -indev '/dev/sr0'
Media current: is not recognizable
Media status : is not present
"""
TOC_STDIO_WRITTEN = """Drive current: -indev 'stdio:/tmp/test.iso'
Drive access : shared:readonly
Media current: stdio file, overwriteable
Media status : is written , is closed
Media summary: 1 session, 2304 data blocks, 4608k data,     0 free
Drive type   : vendor 'YOYODYNE' product 'WARP DRIVE' revision 'FX01'
Media current: stdio file, overwriteable
Media status : is written , is closed
Media blocks : 2304 readable , 0 writable , 2304 overall
"""
PROFILES = """Profile      : 0x0008 (CD-ROM)
Profile      : 0x0010 (DVD-ROM)
Profile      : 0x0040 (BD-ROM)
Profile      : 0x0041 (BD-R sequential recording)
Profile      : 0x0043 (BD-RE) (current)
"""
BURN_LINES = [
    "xorriso : NOTE : -blank as_needed: no need for action detected",
    "Beginning to write data track.",
    "xorriso : UPDATE :    6 of  292 MB written (fifo  0%) [buf  50%]",
    "xorriso : UPDATE :  146 of  292 MB written (fifo 99%) [buf  50%]  54.9x.",
    "Writing to '/dev/sr0' completed successfully.",
]


class FakeReport:
    def __init__(self, cancel_after=None):
        self.lines, self.phases, self.shares = [], [], []
        self.cancel_after = cancel_after

    def cancelled(self):
        return self.cancel_after is not None and len(self.shares) >= self.cancel_after

    def phase(self, phase):
        self.phases.append(phase)

    def progress(self, share):
        self.shares.append(share)

    def log(self, text):
        self.lines.append(text)


class TestParsers(unittest.TestCase):
    def test_devices(self):
        drives = linux.parse_devices(DEVICES)
        self.assertEqual([(d.key, d.device, d.name) for d in drives],
                         [("/dev/sr0", "/dev/sr0", "HL-DT-ST BD-RE BP40NS20"),
                          ("/dev/sr1", "/dev/sr1", "HL-DT-ST DVDRAM GH24NSD1")])
        self.assertEqual(linux.parse_devices(NO_DRIVES), [])

    def test_profiles(self):
        self.assertTrue(linux.parse_can_write_bd(PROFILES))
        self.assertFalse(linux.parse_can_write_bd("Profile      : 0x0010 (DVD-ROM)\n"))
        self.assertIsNone(linux.parse_can_write_bd(""))

    def test_bd_re_with_data(self):
        media = linux.parse_media(TOC_BD_RE_USED)
        self.assertTrue(media.present)
        self.assertEqual((media.kind, media.media_class), ("BD-RE", "BD"))
        self.assertFalse(media.blank)
        self.assertTrue(media.needs_erase)
        self.assertEqual(media.capacity_bytes, 12_219_392 * 2048)
        self.assertEqual(media.speeds, ["2x", "4x"])

    def test_blank_bd_r(self):
        media = linux.parse_media(TOC_BD_R_BLANK)
        self.assertEqual(media.kind, "BD-R")
        self.assertTrue(media.blank)
        self.assertFalse(media.is_rewritable)
        self.assertEqual(media.capacity_bytes, 12_219_392 * 2048)
        self.assertEqual(media.speeds, ["6x"])

    def test_no_disc(self):
        self.assertFalse(linux.parse_media(TOC_NO_DISC).present)

    def test_stdio_real_output(self):
        media = linux.parse_media(TOC_STDIO_WRITTEN)
        self.assertTrue(media.present)
        self.assertFalse(media.is_bd)
        self.assertEqual(media.used_blocks, 2304)

    def test_burn_command(self):
        cmd = linux.burn_command("/usr/bin/xorriso", "/dev/sr0", "/x/a.iso", BurnOptions())
        self.assertEqual(cmd, ["/usr/bin/xorriso", "-as", "cdrecord", "-v", "dev=/dev/sr0", "-nopad",
                               "blank=as_needed", "/x/a.iso"])
        cmd = linux.burn_command("xorriso", "/dev/sr0", "/x/a.iso", BurnOptions(speed="4x"))
        self.assertIn("speed=4b", cmd)              # b = Blu-ray-Einheiten, nicht CD

    def test_tracker(self):
        t = linux.XorrisoTracker()
        kinds = [t.feed(line) for line in BURN_LINES]
        self.assertEqual(kinds[1], "phase")
        self.assertEqual(t.phase, PHASE_WRITE)
        self.assertEqual(kinds[3], "progress")
        self.assertTrue(t.success)
        self.assertEqual(t.progress, 1.0)
        t2 = linux.XorrisoTracker()
        t2.feed("xorriso : UPDATE :  146 of  292 MB written (fifo 99%) [buf  50%]  54.9x.")
        self.assertAlmostEqual(t2.progress, 0.5)
        self.assertEqual(t2.feed("xorriso : FAILURE : Could not open data source '/x.iso' : No such file"), "error")
        self.assertIn("Could not open data source", t2.errors[0])
        self.assertFalse(t2.success)

    def test_formatting_counts_as_erase(self):
        t = linux.XorrisoTracker()
        t.feed("xorriso : UPDATE : Formatting  ( 12.5% done in 15 seconds )")
        self.assertEqual(t.phase, "erase")
        self.assertAlmostEqual(t.progress, 0.125)

    def test_mount_points(self):
        mounts = ("/dev/sda1 / ext4 rw 0 0\n"
                  "/dev/sr0 /media/anna/D4A\\040DISC udf ro,nosuid 0 0\n")
        self.assertEqual(linux.mount_points("/dev/sr0", mounts), ["/media/anna/D4A DISC"])
        self.assertEqual(linux.mount_points("/dev/sr1", mounts), [])


class TestVerify(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="verify_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.iso = os.path.join(self.tmp, "a.iso")
        with open(self.iso, "wb") as f:
            f.write(os.urandom(2048 * 3000))

    def copy(self, change_at=None, extra=0) -> str:
        disc = os.path.join(self.tmp, "disc.img")
        with open(self.iso, "rb") as f:
            data = bytearray(f.read())
        if change_at is not None:
            data[change_at] ^= 0xFF
        with open(disc, "wb") as f:
            f.write(data + b"\0" * extra)
        return disc

    def test_identical_even_with_more_on_disc(self):
        report = FakeReport()
        self.assertTrue(verify.compare_with_device(self.copy(extra=2048 * 10), self.iso, report, size_wait=0))
        self.assertEqual(report.shares[-1], 1.0)

    def test_mismatch_names_sector(self):
        with self.assertRaises(BurnError) as ctx:
            verify.compare_with_device(self.copy(change_at=2048 * 2500 + 7), self.iso, FakeReport(), size_wait=0)
        self.assertEqual(ctx.exception.phase, PHASE_VERIFY)
        self.assertIn("2500", str(ctx.exception))

    def test_short_device_is_not_verifiable(self):
        disc = os.path.join(self.tmp, "short.img")
        with open(disc, "wb") as f:
            f.write(b"\0" * 2048)
        report = FakeReport()
        self.assertFalse(verify.compare_with_device(disc, self.iso, report, size_wait=0))
        self.assertTrue(report.lines)

    def test_cancel(self):
        with self.assertRaises(BurnCancelled):
            verify.compare_with_device(self.copy(), self.iso, FakeReport(cancel_after=0), size_wait=0)


def _xorriso_for_tests():
    return os.environ.get("OPENBDAUTH_TEST_XORRISO") or shutil.which("xorriso")


@unittest.skipUnless(_xorriso_for_tests(), "xorriso nicht installiert")
class TestRealXorriso(unittest.TestCase):
    """Echter Brennvorgang auf ein Pseudo-Laufwerk (Datei): Befehl, Fortschritt, 1:1-Ergebnis, Abbruch, Fehler."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="xorriso_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.backend = linux.LinuxBackend()
        self.backend._xorriso = _xorriso_for_tests()
        self.iso = os.path.join(self.tmp, "a.iso")
        with open(self.iso, "wb") as f:
            f.write(os.urandom(2048 * 40000))       # 80 MB, ganze Sektoren wie jede ISO
        self.out = os.path.join(self.tmp, "disc.img")
        self.drive = Drive(key="stdio", name="Pseudo", device=f"stdio:{self.out}")

    def test_burn_is_byte_identical_and_verified_against_file(self):
        report = FakeReport()
        result = self.backend.burn(self.drive, self.iso, BurnOptions(), report)
        self.assertFalse(result.verified)
        self.assertIn(PHASE_WRITE, report.phases)
        self.assertEqual(report.shares[-1], 1.0)
        with open(self.iso, "rb") as a, open(self.out, "rb") as b:
            self.assertEqual(a.read(), b.read())
        self.assertTrue(verify.compare_with_device(self.out, self.iso, FakeReport(), size_wait=0))

    def test_media_info_of_written_pseudo_disc(self):
        self.backend.burn(self.drive, self.iso, BurnOptions(), FakeReport())
        media = self.backend.media_info(self.drive)
        self.assertTrue(media.present)
        self.assertEqual(media.used_blocks, 40000)

    def test_missing_iso_is_a_burn_error(self):
        with self.assertRaises(BurnError) as ctx:
            self.backend.burn(self.drive, os.path.join(self.tmp, "fehlt.iso"), BurnOptions(), FakeReport())
        self.assertIn("Could not open data source", str(ctx.exception))

    def test_no_drives_here(self):
        self.assertEqual(linux.parse_devices(self.backend._x("-devices")), [])


class TestLinuxInApp(unittest.TestCase):
    def test_backend_selected_on_linux(self):
        from modules.burn import get_backend
        with mock.patch.object(sys, "platform", "linux"), \
                mock.patch.object(linux, "xorriso_path", return_value="/usr/bin/xorriso"):
            backend = get_backend()
        self.assertIsInstance(backend, linux.LinuxBackend)
        self.assertIsNone(backend.unavailable_reason())

    def test_missing_xorriso_explains_install(self):
        from gui.burn.page import BurnPage
        from core.translations import tr
        with mock.patch.object(linux, "xorriso_path", return_value=None):
            page = BurnPage(backend=linux.LinuxBackend(), persist=False)
        self.assertFalse(page.usable)
        self.assertFalse(page.lbl_unavailable.isHidden())
        self.assertIn("apt install xorriso", page.lbl_unavailable.text())
        self.assertFalse(page.act_burn.isEnabled())
        self.assertIn(tr("burn_linux_no_xorriso", "de")[:20], page.diagnosis_text())

    def test_no_drive_hint_and_diagnosis(self):
        from gui.burn.page import BurnPage
        backend = linux.LinuxBackend()
        backend._xorriso = "/usr/bin/xorriso"
        backend.list_drives = lambda: []
        backend.diagnose = lambda: "$ xorriso -devices\nxorriso : SORRY : No drives found"
        page = BurnPage(backend=backend, persist=False)
        page.refresh_devices(sync=True)
        self.assertIn("cdrom", page.lbl_media.text())
        page._log("Testzeile")
        text = page.diagnosis_text()
        for part in ("linux-xorriso", "No drives found", "Testzeile", "System:"):
            self.assertIn(part, text)
        page.copy_diagnosis()
        self.assertIn("No drives found", QApplication.clipboard().text())

    def test_wanted_but_impossible_verify_is_reported(self):
        from gui.burn.page import BurnPage
        from modules.burn.job import BurnOutcome
        page = BurnPage(backend=None, persist=False)
        state, text = page._outcome_text(BurnOutcome(ok=True, verified=False), wanted_verify=True)
        self.assertEqual(state, "ok")
        self.assertIn("nicht geprüft", text)


if __name__ == "__main__":
    unittest.main()
