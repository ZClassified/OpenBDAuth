# gui/studio/importer.py
"""
Import von Dateien in Film-Knoten: Video (inkl. Analyse & Kompatibilitätsprüfung),
MVC, Tonspuren (Vorbereitung im Hintergrund), Untertitel und Kapitel (EDL).
"""

import os
from typing import Callable, List, Optional

from PySide6.QtCore import QObject, QThread, Signal, QPointF

from core.translations import tr
from core.disc_edit import TRACK_AUDIO, TRACK_SUBTITLE
from core.media_import import (
    classify_file, guess_language, prepare_audio_file, needs_preparing,
    KIND_VIDEO, KIND_MVC, KIND_AUDIO, KIND_SUBTITLE, KIND_CHAPTERS,
)
from gui.node_editor.controller import GraphController


class _AudioWorker(QThread):
    done = Signal(str, str, str)  # (film_id, vorbereiteter Pfad, Sprache)

    def __init__(self, film_id: str, path: str, lang: str):
        super().__init__()
        self.film_id, self.path, self.lang = film_id, path, lang

    def run(self):
        prepared = self.path
        try:
            prepared = prepare_audio_file(self.path)
        finally:
            self.done.emit(self.film_id, prepared, self.lang)


class FilmImporter(QObject):
    status = Signal(str)
    busy_changed = Signal(bool)
    compliance_warnings = Signal(str)  # film_id, dessen Video Warnungen hat
    needs_prepare = Signal(object, list)  # (Film-ID oder None, Dateien) – erst vorbereiten (v1.23)

    def __init__(self, controller: GraphController, default_lang: Callable[[], str], parent=None):
        super().__init__(parent)
        self.controller = controller
        self._default_lang = default_lang
        self._workers: List[_AudioWorker] = []
        self.probe = self._probe_video  # in Tests ersetzbar
        self.check_pair = self._check_pair  # in Tests ersetzbar (v1.21: 3D-Paar in eigenem Prozess prüfen)

    # --- Einstieg --------------------------------------------------------------
    def import_files(self, film_id: Optional[str], paths: List[str], pos: Optional[QPointF] = None) -> Optional[str]:
        """
        Importiert Dateien in den Film film_id. Ohne Film wird ein neuer Film angelegt,
        sofern ein Video dabei ist. Gibt die ID des betroffenen Films zurück.
        """
        classified = [(p, classify_file(p)) for p in paths]
        to_prepare = [p for p, k in classified if k is None and needs_preparing(p)]
        unknown = [os.path.basename(p) for p, k in classified if k is None and p not in to_prepare]
        known = [(p, k) for p, k in classified if k is not None]
        if to_prepare:
            # Nicht übernehmen, sondern Vorbereiten anbieten (mit diesem Film als Vorschlag)
            target = film_id if film_id is not None and self.controller.project.film(film_id) is not None else None
            self.needs_prepare.emit(target, to_prepare)

        if film_id is None or self.controller.project.film(film_id) is None:
            video = next((p for p, k in known if k == KIND_VIDEO), None)
            if video is None and to_prepare:
                return None
            if video is None:
                self.status.emit(tr("imp_need_video"))
                return None
            name = os.path.splitext(os.path.basename(video))[0]
            x, y = (pos.x(), pos.y()) if pos is not None else self.free_position()
            film_id = self.controller.add_film(name, (x, y))

        # MVC vor dem Video: Die Videoanalyse braucht den 3D-Hinweis (rohe 3D-Streams melden oft
        # fälschlich 25 fps). Video vor den Kapiteln, weil der EDL-Import die Bildrate braucht.
        order = {KIND_MVC: 0, KIND_VIDEO: 1, KIND_AUDIO: 2, KIND_SUBTITLE: 3, KIND_CHAPTERS: 4}
        for path, kind in sorted(known, key=lambda pk: order[pk[1]]):
            if kind == KIND_VIDEO:
                self.set_video(film_id, path)
            elif kind == KIND_MVC:
                self.set_mvc(film_id, path)
            elif kind == KIND_AUDIO:
                self.add_audio(film_id, path)
            elif kind == KIND_SUBTITLE:
                self.add_subtitle(film_id, path)
            elif kind == KIND_CHAPTERS:
                self.import_chapters(film_id, path)

        if unknown:
            self.status.emit(tr("imp_unsupported", files=", ".join(unknown)))
        return film_id

    # --- Einzelne Dateiarten ------------------------------------------------------
    def set_video(self, film_id: str, path: str):
        film = self.controller.project.film(film_id)
        if film is None:
            return
        details = self.probe(path, bool(film.video_mvc))
        warnings = details.get("warnings", []) if details else []
        warnings = warnings + self._stereo_warnings(details, path, film.video_mvc)
        self.controller.set_film_fields(
            film_id, "Video wählen",
            video_base=path,
            video_details=details,
            fps=details.get("fps", film.fps) if details else film.fps,
            compliance_warnings=warnings,
            warnings_acknowledged=False,
        )
        if warnings:
            self.compliance_warnings.emit(film_id)

    def set_mvc(self, film_id: str, path: Optional[str]):
        film = self.controller.project.film(film_id)
        if film is None:
            return
        fields = {"video_mvc": path}
        if film.video_base:
            # Bildrate mit passendem 3D-Hinweis neu ermitteln (siehe import_files)
            details = self.probe(film.video_base, bool(path))
            if details:
                warnings = details.get("warnings", []) + self._stereo_warnings(details, film.video_base, path)
                fields.update(video_details=details, fps=details.get("fps", film.fps),
                              compliance_warnings=warnings, warnings_acknowledged=False)
        self.controller.set_film_fields(film_id, "3D-Video (MVC) wählen" if path else "3D-Video entfernen",
                                        **fields)
        if fields.get("compliance_warnings"):
            self.compliance_warnings.emit(film_id)

    def clear_video(self, film_id: str):
        self.controller.set_film_fields(film_id, "Video entfernen", video_base=None, video_details=None,
                                        compliance_warnings=[], warnings_acknowledged=False)

    def add_audio(self, film_id: str, path: str):
        lang = guess_language(path, self._default_lang())
        lower = path.lower()
        if lower.endswith(".wav") or lower.endswith(".mp4"):
            worker = _AudioWorker(film_id, path, lang)
            worker.done.connect(self._on_audio_ready)
            worker.finished.connect(lambda w=worker: self._forget(w))
            self._workers.append(worker)
            self.busy_changed.emit(True)
            self.status.emit(f"Bereite Tonspur vor: {os.path.basename(path)} …")
            worker.start()
        else:
            self.controller.add_track(film_id, TRACK_AUDIO, path, lang)

    def add_subtitle(self, film_id: str, path: str):
        self.controller.add_track(film_id, TRACK_SUBTITLE, path, guess_language(path, self._default_lang()))

    def import_chapters(self, film_id: str, path: str):
        from modules.edl_parser import EDLParser
        film = self.controller.project.film(film_id)
        if film is None:
            return
        try:
            times = EDLParser().parse_chapters(path, film.fps)
        except Exception as e:  # EDL-Dateien kommen aus fremden Programmen
            self.status.emit(tr("imp_edl_unreadable", err=e))
            return
        self.controller.set_chapter_times(film_id, times, "Kapitel aus EDL importieren")
        self.status.emit(tr("imp_chapters_imported", n=len(times)))

    # --- Intern -------------------------------------------------------------------
    def _on_audio_ready(self, film_id: str, prepared: str, lang: str):
        if self.controller.project.film(film_id) is not None:
            self.controller.add_track(film_id, TRACK_AUDIO, prepared, lang)
            self.status.emit(tr("imp_audio_added", file=os.path.basename(prepared)))

    def _forget(self, worker: _AudioWorker):
        if worker in self._workers:
            self._workers.remove(worker)
        if not self._workers:
            self.busy_changed.emit(False)

    def wait_for_workers(self):
        for worker in list(self._workers):
            worker.wait()

    def _stereo_warnings(self, details: Optional[dict], base: Optional[str], mvc: Optional[str]) -> list:
        """3D-Hinweise (v1.21): Format des Basis-Videos und ob Basis und MVC Bild für Bild zusammenpassen.
        Läuft, bevor der Film geändert wird – das Ergebnis landet im selben Schritt wie die Datei."""
        if not base or not mvc:
            return []
        from modules.prepare.checks import stereo_format_warnings
        return stereo_format_warnings(details) + self.check_pair(base, mvc)

    def _check_pair(self, base: str, mvc: str) -> list:
        """Prüft das 3D-Paar in einem eigenen Prozess, mit Fortschritt und Abbrechen (modules/prepare)."""
        from PySide6.QtCore import QEventLoop, QTimer, Qt
        from PySide6.QtWidgets import QProgressDialog
        from modules.prepare.background import BackgroundTask
        from modules.prepare.checks import check_pair, unchecked_warning

        task = BackgroundTask(check_pair, base, mvc)
        dialog = QProgressDialog(tr("imp_checking_pair", file=os.path.basename(mvc)), tr("imp_cancel"), 0, 100,
                                 self.parent())
        dialog.setWindowTitle(tr("imp_check_3d"))
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(400)
        dialog.canceled.connect(task.cancel)
        loop = QEventLoop()
        timer = QTimer()

        def tick():
            if task.poll():
                timer.stop()
                loop.quit()
            else:
                dialog.setValue(int(task.progress * 100))

        timer.timeout.connect(tick)
        timer.start(100)
        if not task.finished:
            loop.exec()
        dialog.close()
        if task.cancelled:
            self.status.emit(tr("imp_check_cancelled"))
            return [unchecked_warning(tr("cw_check_cancelled"))]
        if task.error:
            return [unchecked_warning(tr("cw_check_failed", err=task.error))]
        return task.result or []

    def free_position(self):
        positions = self.controller.project.view.node_positions.values()
        if not positions:
            return (720.0, 0.0)
        return (max(p[0] for p in positions), max(p[1] for p in positions) + 200.0)

    @staticmethod
    def _probe_video(path: str, is_3d: bool) -> dict:
        from modules.video_tools import VideoTools
        return VideoTools().probe_video_details(path, is_3d_hint=is_3d)
