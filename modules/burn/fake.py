# modules/burn/fake.py
"""
Fake-Backend für Tests und für die Entwicklung ohne Brenner: simuliert Laufwerke, Medium, Fortschritt und Fehler.
Mit OPENBDAUTH_FAKE_BURNER=1 benutzt auch das Programm dieses Backend (modules/burn/__init__.py).
"""

import time
from typing import List, Optional

from modules.burn.model import (
    BurnCancelled, BurnError, BurnOptions, BurnResult, Drive, Media, PHASE_ERASE, PHASE_PREPARE, PHASE_VERIFY,
    PHASE_WRITE,
)


def blank_bd_r(gb: int = 25) -> Media:
    blocks = 12_219_392 if gb == 25 else 24_438_784
    return Media(present=True, media_class="BD", kind="BD-R", blank=True, appendable=True, free_blocks=blocks,
                 speeds=["2x", "4x", "6x"])


def used_bd_re() -> Media:
    return Media(present=True, media_class="BD", kind="BD-RE", erasable=True, overwritable=True,
                 used_blocks=12_219_392, overwritable_blocks=12_219_392, speeds=["2x"], status="Finalized Disc")


class FakeBackend:
    name = "fake"
    verifies_itself = True
    erase_with_burn = True

    def __init__(self, drives: Optional[List[Drive]] = None, media: Optional[Media] = None,
                 fail_phase: Optional[str] = None, steps: int = 4, step_seconds: float = 0.0,
                 eject_ok: bool = True):
        self.drives = drives if drives is not None else [Drive(key="1", name="FAKE BD-RE", can_write_bd=True)]
        self.media = media if media is not None else blank_bd_r()
        self.fail_phase = fail_phase
        self.steps = steps
        self.step_seconds = step_seconds
        self.eject_ok = eject_ok
        self.burns: List[tuple] = []          # (Laufwerk, ISO, Optionen)
        self.ejects = 0

    def unavailable_reason(self):
        return None

    def diagnose(self) -> str:
        return "fake backend"

    def list_drives(self) -> List[Drive]:
        return list(self.drives)

    def media_info(self, drive: Drive) -> Media:
        return self.media

    def eject(self, drive: Drive) -> bool:
        self.ejects += 1
        return self.eject_ok

    def _pass(self, phase: str, report):
        report.phase(phase)
        for i in range(self.steps + 1):
            if report.cancelled():
                raise BurnCancelled(phase)
            if self.fail_phase == phase and i == self.steps // 2:
                raise BurnError(f"fake failure in {phase}", phase)
            report.progress(i / self.steps)
            if self.step_seconds:
                time.sleep(self.step_seconds)

    def burn(self, drive: Drive, iso_path: str, options: BurnOptions, report) -> BurnResult:
        self.burns.append((drive, iso_path, options))
        report.log(f"fake burn {iso_path}")
        if report.cancelled():
            raise BurnCancelled(PHASE_PREPARE)
        if self.fail_phase == PHASE_PREPARE:
            raise BurnError("fake failure in prepare", PHASE_PREPARE)
        if options.erase:
            self._pass(PHASE_ERASE, report)
        self._pass(PHASE_WRITE, report)
        if options.verify:
            self._pass(PHASE_VERIFY, report)
        return BurnResult(verified=options.verify)
