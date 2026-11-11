# modules/burn/job.py
"""
Ein Brennvorgang (eine Disc) in einem eigenen Thread. Die Oberfläche fragt den Zustand regelmäßig ab (wie bei
Vorbereiten); die eigentliche Arbeit macht das Brennprogramm des Systems in einem eigenen Prozess.

Ablauf: Ruhezustand sperren → brennen (mit Löschen und Prüfen, wenn gewählt) → bei Erfolg auswerfen, wenn gewünscht.
Bei Fehler, Abweichung oder Abbruch wird nie ausgeworfen: Eine offene Lade heißt „fertig und in Ordnung“.
"""

import threading
from dataclasses import dataclass
from typing import List, Optional

from core.translations import tr
from modules.burn.model import (
    BurnCancelled, BurnError, BurnOptions, Drive, PHASE_EJECT, PHASE_ERASE, PHASE_PREPARE, PHASE_VERIFY, PHASE_WRITE,
)
from modules.burn.power import SleepInhibitor

MAX_COPIES = 10


def should_eject(copy_number: int, copies: int, eject_after_success: bool) -> bool:
    """Zwischen mehreren Kopien wird immer ausgeworfen (sonst kein neuer Rohling); die letzte richtet sich nach der
    Einstellung. Gilt nur nach Erfolg."""
    return copy_number < copies or eject_after_success


@dataclass
class BurnOutcome:
    ok: bool = False
    verified: bool = False
    cancelled: bool = False
    error: Optional[str] = None
    phase: str = PHASE_PREPARE       # in welcher Phase es endete (bei Fehler oder Abbruch)
    ejected: Optional[bool] = None   # None: nicht versucht

    @property
    def disc_damaged(self) -> bool:
        """Abbruch oder Fehler, nachdem das Schreiben begonnen hat."""
        return not self.ok and self.phase in (PHASE_ERASE, PHASE_WRITE)


class BurnRun:
    def __init__(self, backend, drive: Drive, iso_path: str, options: BurnOptions, eject_on_success: bool,
                 lang: str = "de", start: bool = True):
        self.backend = backend
        self.drive = drive
        self.iso_path = iso_path
        self.options = options
        self.eject_on_success = eject_on_success
        self.lang = lang
        self.current_phase = PHASE_PREPARE
        self.current_progress: Optional[float] = None
        self.writing_started = False
        self.outcome: Optional[BurnOutcome] = None
        self._log: List[str] = []
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        if start:
            self._thread.start()

    # --- Abfrage durch die Oberfläche ---------------------------------------------------
    @property
    def finished(self) -> bool:
        return self.outcome is not None

    def take_log(self) -> List[str]:
        with self._lock:
            lines, self._log = self._log, []
        return lines

    def cancel(self):
        self._cancel.set()

    def join(self, timeout: Optional[float] = None):
        self._thread.join(timeout)

    # --- Rückmeldungen des Backends ------------------------------------------------------
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def phase(self, phase: str):
        self.current_phase = phase
        self.current_progress = None
        if phase in (PHASE_ERASE, PHASE_WRITE):
            self.writing_started = True
        self.log(tr(f"burn_phase_{phase}", self.lang))

    def progress(self, share: Optional[float]):
        self.current_progress = share

    def log(self, text: str):
        with self._lock:
            self._log.append(text)

    # --- Ablauf ---------------------------------------------------------------------------
    def _run(self):
        outcome = BurnOutcome()
        inhibitor = SleepInhibitor(tr("burn_inhibit_reason", self.lang))
        if not inhibitor.start():
            self.log(tr("burn_log_no_inhibit", self.lang))
        try:
            result = self.backend.burn(self.drive, self.iso_path, self.options, self)
            outcome.ok, outcome.verified, outcome.phase = True, result.verified, self.current_phase
        except BurnCancelled as e:
            outcome.cancelled, outcome.phase = True, e.phase
        except BurnError as e:
            outcome.error, outcome.phase = str(e), e.phase
        except Exception as e:       # Sicherheitsnetz: nie einen hängenden Zustand hinterlassen
            outcome.error, outcome.phase = f"{type(e).__name__}: {e}", self.current_phase
        finally:
            inhibitor.stop()
        if outcome.ok and self.eject_on_success:
            self.current_phase = PHASE_EJECT
            outcome.ejected = bool(self.backend.eject(self.drive))
            if not outcome.ejected:
                self.log(tr("burn_log_eject_failed", self.lang))
        self.outcome = outcome
