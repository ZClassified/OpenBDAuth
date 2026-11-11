# tests/test_burn.py
"""Tests für den Arbeitsbereich Brennen (v1.30, docs/plaene/brennen.md) – ohne Brenner, mit dem Fake-Backend."""

import os
import shutil
import sys
import tempfile
import time
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from modules.burn import checks
from modules.burn.fake import FakeBackend, blank_bd_r, used_bd_re
from modules.burn.iso_info import IsoInfo, decode_dstring, read_iso_info, BD25_BYTES
from modules.burn.job import BurnRun, should_eject
from modules.burn.macos import (
    PuppetTracker, burn_command, parse_burn_devices, parse_can_write_bd, parse_drive_list, parse_media_status,
)
from modules.burn.model import (
    BurnOptions, Drive, Media, PHASE_ERASE, PHASE_PREPARE, PHASE_VERIFY, PHASE_WRITE,
)

app_instance = QApplication.instance() or QApplication(sys.argv)

# Echte Ausgaben (HL-DT-ST BP40NS20 über USB, BD-RE mit Daten), DTD gekürzt
DOCTYPE = "<!DOCTYPE  [\n    <!ELEMENT deviceList (device)*>\n]>\n"
LIST_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
""" + DOCTYPE + """
<deviceList>
    <device name="HL-DT-ST BD-RE BP40NS20" index="1">
        <vendor name="HL-DT-ST"/>
        <product name="BD-RE BP40NS20"/>
        <firmware revision="ML01"/>
        <interconnect name="USB"/>
        <support level="unSupported"/>
    </device>
</deviceList>
"""
INFO_TEXT = """ Vendor   Product           Rev
 HL-DT-ST BD-RE BP40NS20    ML01

   Interconnect: USB
   SupportLevel: Unsupported
       CD-Write: -R, -RW, BUFE, CDText, Test, IndexPts, ISRC
      DVD-Write: -R, -R DL, -RAM, -RW, +R, +R DL, +RW, BUFE, Test
       BD-Write: -R, -RE
     Strategies: CD-TAO, CD-SAO, CD-Raw, DVD-DAO
"""
STATUS_BD_RE_USED = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<!DOCTYPE statusdoc [
    <!ELEMENT statusdoc (statusfordevice)*>
]>
<statusdoc>
    <statusfordevice>
        <device name="HL-DT-ST BD-RE BP40NS20"/>
        <deviceStatus>
            <writeSpeed maxSpeed="8992" currentSpeed="8992"/>
            <mediaInfo>
                <usedSpace blockCount="12219392" msf="2715:25:17"/>
                <freeSpace blockCount="0" msf="0:00:00"/>
                <overwritableSpace blockCount="12219392" msf="2715:25:17"/>
                <overwritable/>
                <erasable/>
                <mediaClass value="BD"/>
                <mediaType value="BD-RE"/>
                <trackCount value="0"/>
                <sessionCount value="0"/>
                <burnSpeedList>
                    <burnSpeed value="8992" dvdXFactor="2x"/>
                </burnSpeedList>
                <discInfo>
                    <discInfoBlock>
                        <erasable/>
                        <discStatus value="2" description="Finalized Disc"/>
                    </discInfoBlock>
                </discInfo>
            </mediaInfo>
            <mediaIsPresent/>
            <trayState value="closed"/>
        </deviceStatus>
    </statusfordevice>
</statusdoc>
"""
STATUS_EMPTY = """<?xml version="1.0"?>
<!DOCTYPE statusdoc [ <!ELEMENT statusdoc (statusfordevice)*> ]>
<statusdoc><statusfordevice><deviceStatus><writeSpeed currentSpeed="0"/><trayState value="closed"/>
</deviceStatus></statusfordevice></statusdoc>
"""
BURN_LIST = """HL-DT-ST BD-RE BP40NS20 via USB (DRDeviceSupportLevelUnsupported)
\tIOService:/AppleARMPE/arm-io/IOBDServices
PIONEER BD-RW BDR-XD08 via USB (DRDeviceSupportLevelUnsupported)
\tIOService:/AppleARMPE/other/IOBDServices
"""


def make_iso(folder: str, label: str = "TEST_DISC", bdmv: bool = True, ssif: bool = False) -> str:
    """Kleine ISO aus unserer UDF-Engine. bdmv=False: der Ordner BDMV heißt in der fertigen ISO „DATA“ (die Engine
    selbst schreibt nur Blu-ray-Strukturen)."""
    from modules.iso_tools import create_udf_iso
    src = os.path.join(folder, "src_" + label)
    os.makedirs(os.path.join(src, "BDMV", "STREAM", "SSIF") if ssif else os.path.join(src, "BDMV", "STREAM"))
    with open(os.path.join(src, "BDMV", "STREAM", "00000.m2ts"), "wb") as f:
        f.write(os.urandom(200_000))
    if ssif:
        with open(os.path.join(src, "BDMV", "STREAM", "SSIF", "00000.ssif"), "wb") as f:
            f.write(b"\0" * 6144)
    iso = os.path.join(folder, f"{label}.iso")
    assert create_udf_iso(src, iso, label, log_callback=lambda *_: None)
    if not bdmv:
        with open(iso, "rb") as f:
            data = f.read()
        with open(iso, "wb") as f:
            f.write(data.replace(b"\x08BDMV", b"\x08DATA"))
    return iso


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="burn_test_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestIsoInfo(TempDirCase):
    def test_reads_label_and_bdmv_from_our_udf_iso(self):
        info = read_iso_info(make_iso(self.tmp, "MY_FILM"))
        self.assertEqual(info.label, "MY_FILM")
        self.assertTrue(info.has_bdmv)
        self.assertFalse(info.is_3d)
        self.assertEqual(info.fits, "bd25")

    def test_detects_3d_by_ssif_folder(self):
        self.assertTrue(read_iso_info(make_iso(self.tmp, "FILM_3D", ssif=True)).is_3d)

    def test_iso_without_bdmv(self):
        info = read_iso_info(make_iso(self.tmp, "DATA_DISC", bdmv=False))
        self.assertEqual(info.label, "DATA_DISC")
        self.assertFalse(info.has_bdmv)

    def test_not_an_udf_image(self):
        path = os.path.join(self.tmp, "x.iso")
        with open(path, "wb") as f:
            f.write(b"\0" * 1024 * 1024)
        info = read_iso_info(path)
        self.assertIsNone(info.label)
        self.assertFalse(info.has_bdmv)

    def test_dstring(self):
        self.assertEqual(decode_dstring(bytes([8]) + b"ABC" + b"\0" * 27 + bytes([4])), "ABC")
        self.assertEqual(decode_dstring(bytes([16]) + "Ä".encode("utf-16-be") + b"\0" * 28 + bytes([3])), "Ä")
        self.assertEqual(decode_dstring(b"\0" * 32), "")

    def test_fits(self):
        self.assertEqual(IsoInfo("a", BD25_BYTES).fits, "bd25")
        self.assertEqual(IsoInfo("a", BD25_BYTES + 1).fits, "bd50")
        self.assertEqual(IsoInfo("a", 60 * 10 ** 9).fits, "too_large")


class TestMacParsers(unittest.TestCase):
    def test_drive_list(self):
        drives = parse_drive_list(LIST_XML)
        self.assertEqual([(d.key, d.name, d.interconnect) for d in drives],
                         [("1", "HL-DT-ST BD-RE BP40NS20", "USB")])

    def test_can_write_bd(self):
        self.assertTrue(parse_can_write_bd(INFO_TEXT))
        self.assertFalse(parse_can_write_bd(INFO_TEXT.replace("       BD-Write: -R, -RE\n", "")))
        self.assertIsNone(parse_can_write_bd(""))

    def test_used_bd_re(self):
        media = parse_media_status(STATUS_BD_RE_USED)
        self.assertTrue(media.present)
        self.assertTrue(media.is_bd)
        self.assertEqual(media.kind, "BD-RE")
        self.assertFalse(media.blank)
        self.assertTrue(media.erasable)
        self.assertTrue(media.needs_erase)
        self.assertTrue(media.writable)
        self.assertEqual(media.capacity_bytes, 12_219_392 * 2048)
        self.assertEqual(media.speeds, ["2x"])
        self.assertEqual(media.status, "Finalized Disc")

    def test_no_media(self):
        media = parse_media_status(STATUS_EMPTY)
        self.assertFalse(media.present)

    def test_media_present_but_not_yet_read_is_busy(self):
        media = parse_media_status(STATUS_EMPTY.replace("<trayState", "<mediaIsPresent/><trayState"))
        self.assertTrue(media.present)
        self.assertTrue(media.busy)

    def test_burn_devices(self):
        devices = parse_burn_devices(BURN_LIST)
        self.assertEqual(len(devices), 2)
        self.assertTrue(devices[0][0].startswith("HL-DT-ST BD-RE BP40NS20"))
        self.assertEqual(devices[1][1], "IOService:/AppleARMPE/other/IOBDServices")

    def test_burn_command_writes_iso_unchanged(self):
        cmd = burn_command("/x/film.iso", BurnOptions())
        for flag in ("-forceclose", "-noaddpmap", "-nosynthesize", "-nooptimizeimage", "-noeject",
                     "-noverifyburn", "-puppetstrings"):
            self.assertIn(flag, cmd)
        self.assertEqual(cmd[:3], ["hdiutil", "burn", "/x/film.iso"])
        self.assertEqual(cmd[cmd.index("-speed") + 1], "max")
        self.assertNotIn("-erase", cmd)
        self.assertNotIn("-device", cmd)

    def test_burn_command_options(self):
        cmd = burn_command("/x/film.iso", BurnOptions(speed="4x", verify=True, erase=True), device="IOService:/a")
        self.assertIn("-verifyburn", cmd)
        self.assertNotIn("-noverifyburn", cmd)
        self.assertIn("-erase", cmd)
        self.assertEqual(cmd[cmd.index("-speed") + 1], "4")
        self.assertEqual(cmd[cmd.index("-device") + 1], "IOService:/a")


class TestPuppetTracker(unittest.TestCase):
    def feed(self, tracker, values):
        for v in values:
            tracker.feed(f"PERCENT:{v:.6f}")

    def test_write_then_verify_by_percent_passes(self):
        t = PuppetTracker(erase=False, verify=True)
        t.feed("PERCENT:0.000000")
        self.assertEqual(t.phase, PHASE_PREPARE)
        self.feed(t, [1, 50, 99.5, 100])
        self.assertEqual(t.phase, PHASE_WRITE)
        self.feed(t, [0, 3])
        self.assertEqual(t.phase, PHASE_VERIFY)
        self.assertAlmostEqual(t.progress, 0.03)

    def test_erase_write_verify(self):
        t = PuppetTracker(erase=True, verify=True)
        self.feed(t, [5, 100, 0, 40, 100, 1])
        self.assertEqual(t.phase, PHASE_VERIFY)

    def test_german_messages(self):
        t = PuppetTracker(erase=True, verify=True)
        self.assertEqual(t.feed("MESSAGE:Medium wird gelöscht …"), ("message", "Medium wird gelöscht …"))
        self.assertEqual(t.phase, PHASE_ERASE)
        t.feed("MESSAGE:Brennen …")
        self.assertEqual(t.phase, PHASE_WRITE)
        t.feed("MESSAGE:Überprüfen …")
        self.assertEqual(t.phase, PHASE_VERIFY)
        t.feed("MESSAGE:Brennen …")           # nie zurück
        self.assertEqual(t.phase, PHASE_VERIFY)

    def test_without_verify_no_verify_phase(self):
        t = PuppetTracker(erase=False, verify=False)
        self.feed(t, [10, 100, 0, 50])
        t.feed("MESSAGE:Verifying")
        self.assertEqual(t.phase, PHASE_WRITE)

    def test_indeterminate_and_other_lines(self):
        t = PuppetTracker(erase=False, verify=False)
        self.assertEqual(t.feed("PERCENT:-1.000000"), ("percent", None))
        self.assertEqual(t.feed("hdiutil: burn failed - x"), ("other", "hdiutil: burn failed - x"))


class TestChecks(unittest.TestCase):
    drive = Drive(key="1", name="BD", can_write_bd=True)
    iso = IsoInfo("a.iso", 20 * 10 ** 9, label="A", has_bdmv=True)

    def keys(self, *args, **kwargs):
        return [(i.level, i.key) for i in checks.check_burn(*args, **kwargs)]

    def test_ready(self):
        self.assertEqual(self.keys(self.iso, self.drive, blank_bd_r()), [])

    def test_errors(self):
        self.assertIn((checks.ERROR, "burn_err_no_iso"), self.keys(None, self.drive, blank_bd_r()))
        self.assertIn((checks.ERROR, "burn_err_iso_unreadable"),
                      self.keys(None, self.drive, blank_bd_r(), iso_error="nope"))
        self.assertIn((checks.ERROR, "burn_err_no_drive"), self.keys(self.iso, None, None))
        self.assertIn((checks.ERROR, "burn_err_drive_no_bd"),
                      self.keys(self.iso, Drive(key="1", name="DVD", can_write_bd=False), blank_bd_r()))
        self.assertIn((checks.ERROR, "burn_err_no_media"), self.keys(self.iso, self.drive, Media()))
        self.assertIn((checks.ERROR, "burn_err_media_busy"),
                      self.keys(self.iso, self.drive, Media(present=True, busy=True)))
        dvd = Media(present=True, media_class="DVD", kind="DVD+R", blank=True, free_blocks=10 ** 6)
        self.assertIn((checks.ERROR, "burn_err_not_bd"), self.keys(self.iso, self.drive, dvd))
        closed = Media(present=True, media_class="BD", kind="BD-R", used_blocks=10 ** 6)
        self.assertIn((checks.ERROR, "burn_err_not_writable"), self.keys(self.iso, self.drive, closed))

    def test_too_large_by_one_sector(self):
        media = blank_bd_r()
        fits = IsoInfo("a", media.capacity_bytes, has_bdmv=True)
        too_big = IsoInfo("a", media.capacity_bytes + 2048, has_bdmv=True)
        self.assertEqual(self.keys(fits, self.drive, media), [])
        self.assertIn((checks.ERROR, "burn_err_too_large"), self.keys(too_big, self.drive, media))

    def test_warnings(self):
        self.assertEqual(self.keys(self.iso, self.drive, used_bd_re()), [(checks.WARNING, "burn_warn_erase")])
        no_bdmv = IsoInfo("a", 10 ** 6, label="", has_bdmv=False)
        self.assertEqual(self.keys(no_bdmv, self.drive, blank_bd_r()), [(checks.WARNING, "burn_warn_no_bdmv")])

    def test_unknown_drive_capability_is_no_error(self):
        self.assertEqual(self.keys(self.iso, Drive(key="1", name="?"), blank_bd_r()), [])


class TestBurnRun(unittest.TestCase):
    drive = Drive(key="1", name="FAKE", can_write_bd=True)

    def run_burn(self, backend, eject=True, options=None, cancel=False):
        run = BurnRun(backend, self.drive, "/x/a.iso", options or BurnOptions(), eject, start=not cancel)
        if cancel:
            run.cancel()
            run._thread.start()
        run.join(10)
        self.assertTrue(run.finished)
        return run

    def test_success_ejects(self):
        backend = FakeBackend()
        run = self.run_burn(backend)
        self.assertTrue(run.outcome.ok)
        self.assertTrue(run.outcome.ejected)
        self.assertEqual(backend.ejects, 1)

    def test_success_without_eject_option(self):
        backend = FakeBackend()
        run = self.run_burn(backend, eject=False)
        self.assertTrue(run.outcome.ok)
        self.assertIsNone(run.outcome.ejected)
        self.assertEqual(backend.ejects, 0)

    def test_failure_never_ejects(self):
        backend = FakeBackend(fail_phase=PHASE_WRITE)
        run = self.run_burn(backend)
        self.assertFalse(run.outcome.ok)
        self.assertEqual(run.outcome.phase, PHASE_WRITE)
        self.assertTrue(run.outcome.disc_damaged)
        self.assertEqual(backend.ejects, 0)

    def test_verify_failure_never_ejects(self):
        backend = FakeBackend(fail_phase=PHASE_VERIFY)
        run = self.run_burn(backend, options=BurnOptions(verify=True))
        self.assertEqual(run.outcome.phase, PHASE_VERIFY)
        self.assertFalse(run.outcome.disc_damaged)
        self.assertEqual(backend.ejects, 0)

    def test_verified(self):
        run = self.run_burn(FakeBackend(), options=BurnOptions(verify=True))
        self.assertTrue(run.outcome.verified)

    def test_cancel_before_start_never_ejects(self):
        backend = FakeBackend()
        run = self.run_burn(backend, cancel=True)
        self.assertTrue(run.outcome.cancelled)
        self.assertFalse(run.outcome.disc_damaged)
        self.assertEqual(backend.ejects, 0)

    def test_cancel_while_writing(self):
        backend = FakeBackend(steps=200, step_seconds=0.01)
        run = BurnRun(backend, self.drive, "/x/a.iso", BurnOptions(), True)
        deadline = time.time() + 5
        while not run.writing_started and time.time() < deadline:
            time.sleep(0.01)
        run.cancel()
        run.join(10)
        self.assertTrue(run.outcome.cancelled)
        self.assertTrue(run.outcome.disc_damaged)
        self.assertEqual(backend.ejects, 0)

    def test_eject_failure_is_not_a_burn_failure(self):
        run = self.run_burn(FakeBackend(eject_ok=False))
        self.assertTrue(run.outcome.ok)
        self.assertFalse(run.outcome.ejected)

    def test_should_eject(self):
        self.assertTrue(should_eject(1, 3, False))      # zwischen Kopien immer
        self.assertTrue(should_eject(2, 3, False))
        self.assertFalse(should_eject(3, 3, False))     # letzte: Einstellung
        self.assertTrue(should_eject(3, 3, True))
        self.assertFalse(should_eject(1, 1, False))


class TestBurnPage(TempDirCase):
    def make_page(self, backend="fake", media=None):
        from gui.burn.page import BurnPage
        if backend == "fake":
            backend = FakeBackend(media=media or blank_bd_r())
        page = BurnPage(backend=backend, persist=False)
        page.confirm = lambda title, text: self.confirms.append(text) or True
        page.ask_next_disc = lambda text: self.asked.append(text) or True
        self.confirms, self.asked = [], []
        return page

    def wait(self, page, timeout=10):
        deadline = time.time() + timeout
        while page.is_running and time.time() < deadline:
            page._poll()
            QApplication.processEvents()
            time.sleep(0.01)
        self.assertFalse(page.is_running)

    def test_defaults(self):
        page = self.make_page()
        self.assertFalse(page.chk_verify.isChecked())    # Prüfen: Vorgabe aus
        self.assertTrue(page.chk_eject.isChecked())      # Auswerfen: Vorgabe an
        self.assertEqual(page.spin_copies.maximum(), 10)
        self.assertFalse(page.act_burn.isEnabled())      # ohne ISO

    def test_ready_after_iso_and_probe(self):
        page = self.make_page()
        page.set_iso(make_iso(self.tmp))
        page.refresh_devices(sync=True)
        self.assertTrue(page.act_burn.isEnabled())
        self.assertEqual(page.state_level(), "ready")
        self.assertIn("TEST_DISC", page.lbl_iso_title.text())

    def test_burn_one_disc_ejects(self):
        page = self.make_page()
        page.set_iso(make_iso(self.tmp))
        page.start_burn()
        self.wait(page)
        self.assertEqual(len(page.backend.burns), 1)
        self.assertEqual(page.backend.ejects, 1)
        self.assertFalse(page.backend.burns[0][2].verify)
        self.assertIn("✅", page.log_view.toPlainText())

    def test_burn_without_eject(self):
        page = self.make_page()
        page.chk_eject.setChecked(False)
        page.set_iso(make_iso(self.tmp))
        page.start_burn()
        self.wait(page)
        self.assertEqual(page.backend.ejects, 0)

    def test_used_bd_re_asks_and_erases(self):
        page = self.make_page(media=used_bd_re())
        page.set_iso(make_iso(self.tmp))
        page.start_burn()
        self.wait(page)
        self.assertEqual(len(self.confirms), 1)
        self.assertTrue(page.backend.burns[0][2].erase)

    def test_declined_warning_does_not_burn(self):
        page = self.make_page(media=used_bd_re())
        page.confirm = lambda title, text: False
        page.set_iso(make_iso(self.tmp))
        page.start_burn()
        self.assertFalse(page.is_running)
        self.assertEqual(page.backend.burns, [])

    def test_copies_eject_between_and_follow_setting_at_the_end(self):
        page = self.make_page()
        page.chk_eject.setChecked(False)
        page.spin_copies.setValue(3)
        page.set_iso(make_iso(self.tmp))
        page.start_burn()
        self.wait(page, 20)
        self.assertEqual(len(page.backend.burns), 3)
        self.assertEqual(len(self.asked), 2)
        self.assertEqual(page.backend.ejects, 2)         # nach Kopie 1 und 2, nicht nach der letzten

    def test_copies_stop_when_user_finishes(self):
        page = self.make_page()
        page.ask_next_disc = lambda text: False
        page.spin_copies.setValue(3)
        page.set_iso(make_iso(self.tmp))
        page.start_burn()
        self.wait(page)
        self.assertEqual(len(page.backend.burns), 1)

    def test_failure_shows_log_and_keeps_disc(self):
        page = self.make_page()
        page.backend.fail_phase = PHASE_WRITE
        page.set_iso(make_iso(self.tmp))
        page.start_burn()
        self.wait(page)
        self.assertEqual(page.backend.ejects, 0)
        self.assertTrue(page.log_view.isVisibleTo(page))

    def test_recent_list(self):
        page = self.make_page()
        paths = [os.path.join(self.tmp, f"{i}.iso") for i in range(12)]
        for p in paths:
            page.add_recent(p)
        page.add_recent(paths[5])
        self.assertEqual(len(page.recent), 10)
        self.assertEqual(page.recent[0], paths[5])
        self.assertEqual(page.recent.count(paths[5]), 1)

    def test_no_backend(self):
        page = self.make_page(backend=None)
        page.set_iso(make_iso(self.tmp))
        self.assertFalse(page.act_burn.isEnabled())
        self.assertFalse(page.lbl_unavailable.isHidden())

    def test_unreadable_iso(self):
        page = self.make_page()
        page.set_iso(os.path.join(self.tmp, "missing.iso"))
        self.assertIsNotNone(page.iso_error)
        self.assertFalse(page.act_burn.isEnabled())


class TestStudioBurnTab(TempDirCase):
    def test_three_workspaces_and_go_to_burn(self):
        from gui.studio.main_window import StudioWindow, PAGE_BURN
        w = StudioWindow(persist_layout=False)
        try:
            self.assertEqual(set(w.page_actions), {"prepare", "disc", "burn"})
            iso = make_iso(self.tmp)
            w.show_burn(iso)
            self.assertEqual(w.page, PAGE_BURN)
            self.assertIs(w.pages.currentWidget(), w.burn_page)
            self.assertEqual(w.burn_page.iso_path, iso)
            self.assertTrue(w.burn_page.act_burn.isVisible() or not w.isVisible())
            self.assertFalse(w.act_build.isVisible())
            w._on_burn_progress("42 %")
            self.assertTrue(w.page_actions[PAGE_BURN].text().endswith("42 %"))
            w._on_burn_progress("")
            w.show_page("disc")
            self.assertIs(w.pages.currentWidget(), w.view)
        finally:
            w.controller.undo_stack.setClean()
            w.close()


@unittest.skipUnless(sys.platform == "darwin", "Einhängen per hdiutil nur unter macOS")
class TestMacMount(TempDirCase):
    def test_simulator_mounts_iso(self):
        from modules.bdsim.source import mount_iso
        mount, unmount = mount_iso(make_iso(self.tmp, "MOUNT_TEST"))
        try:
            self.assertIn("BDMV", os.listdir(mount))
        finally:
            unmount()
        self.assertFalse(os.path.exists(mount))


if __name__ == "__main__":
    unittest.main()
