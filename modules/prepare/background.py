# modules/prepare/background.py
"""
Rechenarbeit in einem eigenen Prozess (v1.21), z. B. die Prüfung eines 3D-Paars über Gigabytes, ab v1.22 auch
das Encoding im Arbeitsbereich Vorbereiten.

Gründe (Konzept, „Sicherheit der Dateien“): mvctools ist reines Python und würde in einem Thread neben Qt die
Oberfläche ruckeln lassen (GIL); ein Absturz dort reißt das Studio nicht mit; Abbrechen beendet den Prozess.
Ohne Qt: Die Oberfläche fragt poll() regelmäßig ab.

Im fertigen Paket startet multiprocessing dieselbe EXE noch einmal; dafür ruft main.py freeze_support() auf.
"""

import multiprocessing
import queue as queue_module
import time
from typing import Any, Callable, List, Optional

from core.translations import set_ui_language, ui_language

DONE, PROGRESS, ERROR, LOG, STATUS = "done", "progress", "error", "log", "status"
CANCEL_GRACE_SECONDS = 15.0      # so lange darf ein Auftrag nach „Abbrechen“ aufräumen, dann wird er beendet


def _run(func: Callable, args: tuple, results, cancel_event, with_log: bool, lang: str = "de") -> None:
    set_ui_language(lang)      # der Prozess startet neu: Meldungen in der Sprache der Oberfläche (v1.27.2)
    kwargs = {"progress": lambda share: results.put((PROGRESS, share))}
    if with_log:
        kwargs["log"] = lambda text, is_progress=False: results.put((STATUS if is_progress else LOG, text))
    if cancel_event is not None:
        kwargs["cancelled"] = cancel_event.is_set
    try:
        results.put((DONE, func(*args, **kwargs)))
    except Exception as e:     # Fehler kommen als Meldung zurück, nicht als abgestürzter Prozess
        results.put((ERROR, str(e) if with_log else f"{type(e).__name__}: {e}"))


class BackgroundTask:
    """
    Führt func(*args, progress=…) in einem eigenen Prozess aus. func muss eine Funktion auf Modulebene sein
    (wird an den Prozess übergeben). progress(Anteil 0..1) darf func beliebig oft aufrufen.
    log=True: func bekommt zusätzlich log(text, is_progress=False); Zeilen landen in take_log(), die letzte
    Fortschrittszeile in status. cancellable=True: func bekommt cancelled() und räumt nach cancel() selbst auf
    (spätestens nach CANCEL_GRACE_SECONDS wird der Prozess beendet); sonst beendet cancel() ihn sofort.
    """

    def __init__(self, func: Callable, *args, log: bool = False, cancellable: bool = False):
        ctx = multiprocessing.get_context("spawn")      # überall gleich: Windows kennt nur spawn
        self._results = ctx.Queue()
        self._cancel_event = ctx.Event() if cancellable else None
        self._process = ctx.Process(target=_run, args=(func, args, self._results, self._cancel_event, log,
                                                       ui_language()), daemon=True)
        self.progress = 0.0
        self.status = ""
        self.result: Any = None
        self.error: Optional[str] = None
        self.finished = False
        self.cancelled = False
        self._log: List[str] = []
        self._cancel_deadline: Optional[float] = None
        self._process.start()

    def poll(self) -> bool:
        """Neue Meldungen übernehmen; True, sobald die Arbeit beendet ist (result oder error)."""
        while not self.finished:
            try:
                kind, value = self._results.get_nowait()
            except queue_module.Empty:
                if self._process.is_alive():
                    if self._cancel_deadline is not None and time.time() > self._cancel_deadline:
                        self._process.terminate()
                        self._finish()
                    break
                try:        # beendet: letzte Meldung kann noch unterwegs sein
                    kind, value = self._results.get(timeout=1.0)
                except queue_module.Empty:
                    if self.cancelled:
                        self._finish()
                    else:
                        self._finish(error=f"Der Prozess wurde unerwartet beendet "
                                           f"(Code {self._process.exitcode}).")
                    break
            if kind == PROGRESS:
                self.progress = float(value)
            elif kind == LOG:
                self._log.append(value)
            elif kind == STATUS:
                self.status = value
            elif kind == DONE:
                self._finish(result=value)
            else:
                self._finish(error=None if self.cancelled else value)
        return self.finished

    def take_log(self) -> List[str]:
        """Protokollzeilen seit dem letzten Aufruf."""
        lines, self._log = self._log, []
        return lines

    def cancel(self):
        if self.finished or self.cancelled:
            return
        self.cancelled = True
        if self._cancel_event is not None and self._process.is_alive():
            self._cancel_event.set()
            self._cancel_deadline = time.time() + CANCEL_GRACE_SECONDS
            return
        if self._process.is_alive():
            self._process.terminate()
        self._finish()

    def _finish(self, result: Any = None, error: Optional[str] = None):
        self.result, self.error, self.finished = result, error, True
        self._process.join(timeout=5)
