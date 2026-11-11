# gui/burn/page.py
"""
Arbeitsbereich Brennen (v1.30, Plan docs/plaene/brennen.md): eine fertige ISO 1:1 auf Blu-ray brennen, beliebig oft,
ohne das Projekt neu zu packen.

- Links das Image: ISO wählen oder hineinziehen, zuletzt verwendete ISOs, Angaben (Titel, Größe, 2D/3D),
  „Im Simulator öffnen“.
- Rechts der Brenner: Laufwerk und Medium (im Hintergrund abgefragt), Geschwindigkeit, Kopien (höchstens 10),
  „Disc nach dem Brennen prüfen“ (Vorgabe aus), „Disc nach erfolgreichem Brennen auswerfen“ (Vorgabe an).
- Unten Fortschritt, Ergebnis und Protokoll. „Abbrechen“ und „Brennen“ zeigt die obere Leiste des Studios.

Die Einstellungen sind Vorlieben des Nutzers und stehen in den App-Einstellungen, nicht im Projekt.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional

from PySide6 import QtGui
from PySide6.QtCore import Qt, QTimer, Signal, QSettings
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QComboBox, QSpinBox, QCheckBox,
    QListWidget, QListWidgetItem, QPlainTextEdit, QProgressBar, QFileDialog, QMessageBox, QFrame, QApplication,
)

from core.translations import tr, tr_file_filter, ui_language
from gui.app_language import SETTINGS_ORG, SETTINGS_APP
from gui.studio.widgets import DropFrame, ElidedLabel, fill_combo, hint_label
from modules.burn import checks
from modules.burn.iso_info import IsoInfo, read_iso_info
from modules.burn.job import BurnRun, MAX_COPIES, should_eject
from modules.burn.model import BurnOptions, Drive, Media, PHASE_VERIFY, SPEED_AUTO

POLL_MS = 200
PROBE_MS = 3000
MAX_RECENT = 10
ISO_FILTER = "ISO (*.iso);;Alle Dateien (*.*)"
KEY_RECENT, KEY_EJECT, KEY_VERIFY, KEY_SPEED = ("burn/recent_isos", "burn/eject_after_success",
                                                "burn/verify_after_burn", "burn/speed")
LEVEL_COLOR = {checks.ERROR: "#F87171", checks.WARNING: "#FDE047"}
DOT_COLOR = {"ready": "#4ADE80", checks.WARNING: "#FDE047", checks.ERROR: "#F87171", "idle": "#52525B"}
# Schon anderswo gesagt: kein Medium/Laufwerk (Satz zum Medium), ISO fehlt oder unlesbar (linke Karte),
# BD-RE wird gelöscht (Satz zum Medium), ISO ohne BDMV (Hinweis auf der linken Karte)
HIDDEN_KEYS = {"burn_err_no_iso", "burn_err_iso_unreadable", "burn_err_no_drive", "burn_err_no_media",
               "burn_err_media_busy", "burn_warn_erase", "burn_warn_no_bdmv", "burn_err_not_bd"}
ISO_KEYS = {"burn_err_no_iso", "burn_err_iso_unreadable", "burn_warn_no_bdmv"}
IDLE_KEYS = {"burn_err_no_drive", "burn_err_no_media", "burn_err_media_busy"}
RESULT_COLOR = {"ok": "#4ADE80", "fail": "#F87171", "info": "#A1A1AA"}


def _gb(n: int, lang: str) -> str:
    from gui.studio.export_activity import format_bytes
    return format_bytes(n, lang)


def _same_path(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _bool(value, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.lower() in ("1", "true", "yes")
    return bool(value)


class BurnPage(QWidget):
    status = Signal(str)                 # Meldung für die Statusleiste des Studios
    running_changed = Signal(bool)
    progress_text = Signal(str)          # z. B. „42 %“ für den Reiter ("" = nichts läuft)
    simulate_requested = Signal(str)     # ISO im Simulator öffnen

    def __init__(self, parent=None, backend="auto", persist: bool = True):
        super().__init__(parent)
        self.setObjectName("BurnPage")
        if backend == "auto":
            from modules.burn import get_backend
            backend = get_backend()
        self.backend = backend
        # (Textschlüssel, Werte), wenn hier nicht gebrannt werden kann: kein Backend für dieses System (Windows) oder
        # ein Werkzeug fehlt (Linux: xorriso) – v1.31.0
        self.unavailable = self._unavailable()
        self.persist = persist           # Einstellungen und Liste speichern (in Tests aus)
        self.iso: Optional[IsoInfo] = None
        self.iso_path: Optional[str] = None
        self.iso_error: Optional[str] = None
        self.drives: List[Drive] = []
        self.media: Optional[Media] = None
        self.recent: List[str] = []
        self.eject_after = True
        self.verify_after = False
        self.speed = SPEED_AUTO
        self.prepare_running = lambda: False     # setzt das Studio: läuft die Warteschlange in Vorbereiten?
        self.run: Optional[BurnRun] = None
        self._copy = 0
        self._copies = 1
        self._results: List[str] = []
        self._probe_pool = ThreadPoolExecutor(max_workers=1)
        self._probe_future = None
        self._probe_drive_key: Optional[str] = None
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._poll)
        self._probe_timer = QTimer(self)
        self._probe_timer.setInterval(PROBE_MS)
        self._probe_timer.timeout.connect(self.refresh_devices)

        self.act_burn = QtGui.QAction(self)
        self.act_burn.triggered.connect(self.start_burn)
        self.act_cancel = QtGui.QAction(self)
        self.act_cancel.triggered.connect(self.cancel_burn)
        self.act_cancel.setEnabled(False)

        self._build()
        self._restore()
        self.retranslate()
        self._update_all()

    # --- Aufbau -----------------------------------------------------------------------
    # Ruhig und übersichtlich: zwei Karten (Image, Brenner), je eine klare Aussage oben; Fortschritt erst beim
    # Brennen, Protokoll eingeklappt (öffnet sich bei einem Fehler von selbst).
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(14)
        self.lbl_unavailable = QLabel()
        self.lbl_unavailable.setWordWrap(True)
        self.lbl_unavailable.setStyleSheet("color: #FDE047; padding: 4px 2px;")
        self.lbl_unavailable.setVisible(self.unavailable is not None)
        root.addWidget(self.lbl_unavailable)

        cards = QHBoxLayout()
        cards.setSpacing(14)
        cards.addWidget(self._build_image_card(), stretch=1)
        cards.addWidget(self._build_burner_card(), stretch=1)
        root.addLayout(cards)

        # Fortschritt: nur während und nach einem Brennvorgang sichtbar
        self.activity = QFrame()
        self.activity.setObjectName("card")
        self.activity.setStyleSheet("QLabel { background: transparent; }")
        act = QVBoxLayout(self.activity)
        act.setContentsMargins(16, 12, 16, 12)
        act.setSpacing(8)
        head = QHBoxLayout()
        self.lbl_phase = QLabel()
        self.lbl_phase.setStyleSheet("color: #FAFAFA; font-size: 14px; font-weight: 600;")
        self.lbl_percent = QLabel()
        self.lbl_percent.setStyleSheet("color: #A1A1AA; font-size: 14px;")
        head.addWidget(self.lbl_phase, stretch=1)
        head.addWidget(self.lbl_percent)
        act.addLayout(head)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        act.addWidget(self.progress)
        self.lbl_result = QLabel()
        self.lbl_result.setWordWrap(True)
        self.lbl_result.setTextInteractionFlags(Qt.TextSelectableByMouse)
        act.addWidget(self.lbl_result)
        self.activity.setVisible(False)
        root.addWidget(self.activity)
        root.addStretch(1)

        self.btn_log = QPushButton()
        self.btn_log.setFlat(True)
        self.btn_log.setCursor(Qt.PointingHandCursor)
        self.btn_log.setStyleSheet("QPushButton { color: #71717A; border: none; background: transparent; "
                                   "text-align: left; padding: 2px 0; } QPushButton:hover { color: #D4D4D8; }")
        self.btn_log.clicked.connect(lambda: self.set_log_visible(not self.log_view.isVisible()))
        # Diagnose (v1.31.0): Rohausgaben der Laufwerksabfrage und Protokoll in die Zwischenablage – für Rückmeldungen
        self.btn_diagnose = QPushButton()
        self.btn_diagnose.setFlat(True)
        self.btn_diagnose.setCursor(Qt.PointingHandCursor)
        self.btn_diagnose.setStyleSheet(self.btn_log.styleSheet())
        self.btn_diagnose.clicked.connect(self.copy_diagnosis)
        footer = QHBoxLayout()
        footer.addWidget(self.btn_log)
        footer.addStretch(1)
        footer.addWidget(self.btn_diagnose)
        root.addLayout(footer)
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("log_area")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        self.log_view.setMinimumHeight(120)
        self.log_view.setVisible(False)
        root.addWidget(self.log_view, stretch=3)

    @staticmethod
    def _title_label(text: str = "") -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("font-size: 12px; font-weight: bold; color: #A1A1AA; "
                            "text-transform: uppercase; letter-spacing: 1px;")
        return label

    def _build_image_card(self) -> QWidget:
        card = DropFrame()
        card.files_dropped.connect(self._on_files_dropped)
        card.layout_.setContentsMargins(20, 16, 20, 16)
        card.layout_.setSpacing(6)
        self.card_image = card
        lay = card.layout_
        lay.addSpacing(6)
        self.lbl_disc_icon = QLabel()
        self.lbl_disc_icon.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.lbl_disc_icon)
        lay.addSpacing(4)
        self.lbl_iso_title = QLabel()
        self.lbl_iso_title.setAlignment(Qt.AlignCenter)
        self.lbl_iso_title.setWordWrap(True)
        self.lbl_iso_title.setStyleSheet("color: #FAFAFA; font-size: 18px; font-weight: 600;")
        self.lbl_iso_facts = QLabel()
        self.lbl_iso_facts.setAlignment(Qt.AlignCenter)
        self.lbl_iso_facts.setWordWrap(True)
        self.lbl_iso_facts.setStyleSheet("color: #D4D4D8;")
        self.lbl_iso_file = ElidedLabel()
        self.lbl_iso_file.setAlignment(Qt.AlignCenter)
        self.lbl_iso_file.setStyleSheet("color: #71717A; font-size: 12px;")
        self.lbl_iso_note = QLabel()
        self.lbl_iso_note.setAlignment(Qt.AlignCenter)
        self.lbl_iso_note.setWordWrap(True)
        self.lbl_iso_note.setStyleSheet("color: #FDE047; font-size: 12px;")
        for w in (self.lbl_iso_title, self.lbl_iso_facts, self.lbl_iso_file, self.lbl_iso_note):
            lay.addWidget(w)
        lay.addSpacing(8)
        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_choose = QPushButton()
        self.btn_choose.clicked.connect(self.choose_iso)
        self.btn_simulate = QPushButton()
        self.btn_simulate.clicked.connect(self._on_simulate)
        row.addWidget(self.btn_choose)
        row.addWidget(self.btn_simulate)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addSpacing(10)
        self.lbl_recent = self._title_label()
        lay.addWidget(self.lbl_recent)
        self.list_recent = QListWidget()
        self.list_recent.setStyleSheet("QListWidget { background: transparent; border: none; }"
                                       " QListWidget::item { padding: 4px 2px; }")
        self.list_recent.setMaximumHeight(170)
        self.list_recent.itemClicked.connect(self._on_recent)
        self.list_recent.itemActivated.connect(self._on_recent)
        lay.addWidget(self.list_recent)
        return card

    def _build_burner_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        card.setStyleSheet("QLabel, QCheckBox { background: transparent; }")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(8)
        self.lbl_burner_title = self._title_label()
        lay.addWidget(self.lbl_burner_title)
        lay.addSpacing(4)

        # Zustand: farbiger Punkt, Laufwerk, ein Satz zum Medium
        state = QHBoxLayout()
        state.setSpacing(10)
        self.lbl_dot = QLabel()
        self.lbl_dot.setFixedWidth(14)
        self.lbl_dot.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        state.addWidget(self.lbl_dot, alignment=Qt.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.lbl_drive_name = ElidedLabel()
        self.lbl_drive_name.setStyleSheet("color: #FAFAFA; font-size: 15px; font-weight: 600;")
        self.combo_drive = QComboBox()          # nur bei mehr als einem Laufwerk sichtbar
        self.combo_drive.activated.connect(lambda *_: self._on_drive_changed())
        self.combo_drive.setVisible(False)
        self.lbl_media = QLabel()
        self.lbl_media.setWordWrap(True)
        self.lbl_media.setStyleSheet("color: #D4D4D8;")
        self.lbl_issues = QLabel()
        self.lbl_issues.setWordWrap(True)
        self.lbl_issues.setTextFormat(Qt.RichText)
        for w in (self.lbl_drive_name, self.combo_drive, self.lbl_media, self.lbl_issues):
            text.addWidget(w)
        state.addLayout(text, stretch=1)
        self.btn_eject = QPushButton()
        self.btn_eject.clicked.connect(self.eject_now)
        state.addWidget(self.btn_eject, alignment=Qt.AlignTop)
        lay.addLayout(state)

        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet("background-color: #2E2E33;")
        lay.addSpacing(8)
        lay.addWidget(line)
        lay.addSpacing(8)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        self.lbl_copies = QLabel()
        self.spin_copies = QSpinBox()
        self.spin_copies.setRange(1, MAX_COPIES)
        self.spin_copies.setValue(1)
        self.spin_copies.setFixedWidth(80)
        self.lbl_speed = QLabel()
        self.combo_speed = QComboBox()
        self.combo_speed.activated.connect(lambda *_: self._on_speed())
        self.combo_speed.setMinimumWidth(140)
        for row_index, (label, widget) in enumerate(((self.lbl_copies, self.spin_copies),
                                                     (self.lbl_speed, self.combo_speed))):
            label.setStyleSheet("color: #A1A1AA;")
            grid.addWidget(label, row_index, 0)
            grid.addWidget(widget, row_index, 1, Qt.AlignLeft)
        grid.setColumnStretch(2, 1)
        lay.addLayout(grid)
        lay.addSpacing(6)
        self.chk_verify = QCheckBox()
        self.chk_verify.toggled.connect(self._on_verify)
        self.chk_eject = QCheckBox()
        self.chk_eject.toggled.connect(self._on_eject_option)
        lay.addWidget(self.chk_verify)
        lay.addWidget(self.chk_eject)
        lay.addStretch(1)
        return card

    def set_log_visible(self, visible: bool):
        self.log_view.setVisible(visible)
        self.btn_log.setText(self.t("burn_log_hide" if visible else "burn_log_show"))

    # --- Grundlagen ---------------------------------------------------------------------
    def t(self, key: str, **kwargs) -> str:
        text = tr(key, ui_language())
        return text.format(**kwargs) if kwargs else text

    def retranslate(self):
        self.act_burn.setText(self.t("burn_start"))
        self.act_burn.setToolTip(self.t("burn_start_tip"))
        self._update_cancel_text()
        if self.unavailable is not None:
            key, args = self.unavailable
            self.lbl_unavailable.setText(self.t(key, **args))
        self.btn_diagnose.setText(self.t("burn_diagnose"))
        self.btn_diagnose.setToolTip(self.t("burn_diagnose_tip"))
        self.card_image.set_title(self.t("burn_image"))
        self.btn_simulate.setText(self.t("burn_simulate"))
        self.lbl_recent.setText(self.t("burn_recent"))
        self.lbl_burner_title.setText(self.t("burn_burner"))
        self.btn_eject.setText(self.t("burn_eject"))
        self.lbl_speed.setText(self.t("burn_speed"))
        self.lbl_copies.setText(self.t("burn_copies"))
        self.chk_verify.setText(self.t("burn_verify"))
        self.chk_verify.setToolTip(self.t("burn_verify_tip"))
        self.chk_eject.setText(self.t("burn_eject_after"))
        self.chk_eject.setToolTip(self.t("burn_eject_after_tip"))
        self.set_log_visible(self.log_view.isVisible())
        self._update_all()

    def _unavailable(self):
        if self.backend is None:
            return "burn_unavailable", {}
        try:
            return self.backend.unavailable_reason()
        except Exception as e:                  # nie am Start scheitern: dann eben nicht brennbar
            return "burn_probe_failed", {"err": e}

    @property
    def usable(self) -> bool:
        return self.backend is not None and self.unavailable is None

    @property
    def is_running(self) -> bool:
        return self.run is not None

    def showEvent(self, event):
        super().showEvent(event)
        if self.usable:
            self.refresh_devices()
            self._probe_timer.start()
        self._timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._probe_timer.stop()
        if not self.is_running:
            self._timer.stop()

    # --- Einstellungen ---------------------------------------------------------------------
    def _settings(self) -> Optional[QSettings]:
        return QSettings(SETTINGS_ORG, SETTINGS_APP) if self.persist else None

    def _restore(self):
        settings = self._settings()
        if settings is not None:
            self.eject_after = _bool(settings.value(KEY_EJECT), True)
            self.verify_after = _bool(settings.value(KEY_VERIFY), False)
            self.speed = settings.value(KEY_SPEED, SPEED_AUTO) or SPEED_AUTO
            recent = settings.value(KEY_RECENT, []) or []
            self.recent = [recent] if isinstance(recent, str) else [p for p in recent if p]
        for chk, value in ((self.chk_verify, self.verify_after), (self.chk_eject, self.eject_after)):
            chk.blockSignals(True)
            chk.setChecked(value)
            chk.blockSignals(False)

    def _save(self):
        settings = self._settings()
        if settings is None:
            return
        settings.setValue(KEY_EJECT, self.eject_after)
        settings.setValue(KEY_VERIFY, self.verify_after)
        settings.setValue(KEY_SPEED, self.speed)
        settings.setValue(KEY_RECENT, self.recent)

    def _on_verify(self, on: bool):
        self.verify_after = on
        self._save()

    def _on_eject_option(self, on: bool):
        self.eject_after = on
        self._save()

    def _on_speed(self):
        self.speed = self.combo_speed.currentData() or SPEED_AUTO
        self._save()

    # --- Image --------------------------------------------------------------------------------
    def choose_iso(self):
        start = os.path.dirname(self.iso_path) if self.iso_path else ""
        path, _ = QFileDialog.getOpenFileName(self, self.t("burn_choose_iso").rstrip(" …"), start,
                                              tr_file_filter(ISO_FILTER))
        if path:
            self.set_iso(path)

    def _on_files_dropped(self, files: list):
        isos = [f for f in files if f.lower().endswith(".iso")]
        if isos:
            self.set_iso(isos[0])
        else:
            self.status.emit(self.t("burn_drop_only_iso"))

    def _on_recent(self, item: QListWidgetItem):
        path = item.data(Qt.UserRole)
        if path and not self.is_running:
            if os.path.isfile(path):
                self.set_iso(path)
            else:
                self.status.emit(self.t("burn_recent_missing", path=path))

    def set_iso(self, path: str):
        """ISO wählen (auch aus dem Export: „Zum Brennen“)."""
        if self.is_running:
            return
        self.iso_path = path
        try:
            self.iso, self.iso_error = read_iso_info(path), None
        except OSError as e:
            self.iso, self.iso_error = None, str(e)
        if self.iso is not None:
            self.add_recent(path)
        self._update_all()

    def add_recent(self, path: str):
        """Vorne einreihen, Doppelte zusammenfassen, höchstens MAX_RECENT."""
        self.recent = [path] + [p for p in self.recent if not _same_path(p, path)]
        del self.recent[MAX_RECENT:]
        self._save()
        self._update_recent()

    def _on_simulate(self):
        if self.iso_path and self.iso is not None:
            self.simulate_requested.emit(self.iso_path)

    # --- Laufwerk und Medium -------------------------------------------------------------------
    def selected_drive(self) -> Optional[Drive]:
        key = self.combo_drive.currentData()
        return next((d for d in self.drives if d.key == key), self.drives[0] if self.drives else None)

    def _probe(self, drive_key: Optional[str]):
        """Im Hintergrund: Laufwerke und Medium des gewählten Laufwerks."""
        drives = self.backend.list_drives()
        drive = next((d for d in drives if d.key == drive_key), drives[0] if drives else None)
        media = self.backend.media_info(drive) if drive is not None else None
        return drives, media

    def refresh_devices(self, sync: bool = False):
        """Laufwerke und Medium abfragen (nicht während eines Brennvorgangs: drutil würde dazwischenfunken)."""
        if not self.usable or self.is_running:
            return
        drive = self.selected_drive()
        key = drive.key if drive else None
        if sync:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                self._apply_probe(*self._probe(key))
            except Exception as e:
                self._probe_failed(e)
            finally:
                QApplication.restoreOverrideCursor()
            return
        if self._probe_future is None:
            self._probe_future = self._probe_pool.submit(self._probe, key)
            self._timer.start()

    def _collect_probe(self):
        future = self._probe_future
        if future is None or not future.done():
            return
        self._probe_future = None
        try:
            self._apply_probe(*future.result())
        except Exception as e:
            self._probe_failed(e)

    def _probe_failed(self, error: Exception):
        self.drives, self.media = [], None
        self.status.emit(self.t("burn_probe_failed", err=error))
        self._update_all()

    def _apply_probe(self, drives: List[Drive], media: Optional[Media]):
        if self.is_running:
            return
        self.drives, self.media = drives, media
        self._update_all()

    def _on_drive_changed(self):
        self.media = None
        self._update_all()
        self.refresh_devices(sync=True)

    def eject_now(self):
        drive = self.selected_drive()
        if drive is None or self.is_running:
            return
        if not self.backend.eject(drive):
            self.status.emit(self.t("burn_log_eject_failed"))
        self.refresh_devices(sync=True)

    # --- Anzeige ------------------------------------------------------------------------------------
    def issues(self) -> List[checks.BurnIssue]:
        drive = self.selected_drive()
        result = checks.check_burn(self.iso, drive, self.media if drive else None, self.iso_error)
        if self.prepare_running():
            result.append(checks.BurnIssue(checks.WARNING, "burn_warn_prepare_running"))
        return result

    def _update_all(self):
        lang = ui_language()
        self._update_iso_info(lang)
        self._update_drive_combo()
        self._update_media(lang)
        self._update_speed_combo()
        self._update_recent()
        self._update_issues()
        self._update_actions()

    def _update_iso_info(self, lang: str):
        from gui.icons import _format_pixmap
        has_iso = self.iso is not None
        self.lbl_disc_icon.setPixmap(_format_pixmap("disc", "#FBBF24" if has_iso else "#3F3F46", 56))
        self.btn_choose.setText(self.t("burn_choose_other" if self.iso_path else "burn_choose_iso"))
        self.btn_simulate.setVisible(has_iso)
        self.lbl_iso_file.setVisible(self.iso_path is not None)
        note = ""
        if self.iso_path is None:
            self.lbl_iso_title.setText(self.t("burn_no_iso"))
            self.lbl_iso_facts.setText(self.t("burn_drop_hint"))
        elif not has_iso:
            self.lbl_iso_title.setText(os.path.basename(self.iso_path))
            self.lbl_iso_facts.setText("")
            note = self.t("burn_err_iso_unreadable", err=self.iso_error)
        else:
            iso = self.iso
            self.lbl_iso_title.setText(iso.label or os.path.splitext(os.path.basename(iso.path))[0])
            content = self.t("burn_content_3d" if iso.is_3d else "burn_content_2d") if iso.has_bdmv else None
            facts = [content, _gb(iso.size, lang), self.t("burn_fits_" + iso.fits)]
            self.lbl_iso_facts.setText(" · ".join(f for f in facts if f))
            if not iso.has_bdmv:
                note = self.t("burn_content_unknown")
        if self.iso_path:
            self.lbl_iso_file.setText(os.path.basename(self.iso_path))
            self.lbl_iso_file.setToolTip(self.iso_path)
        self.lbl_iso_note.setText(note)
        self.lbl_iso_note.setVisible(bool(note))

    def _update_drive_combo(self):
        current = self.combo_drive.currentData()
        entries = [(d.key, d.name + (f" ({d.interconnect})" if d.interconnect else "")) for d in self.drives]
        fill_combo(self.combo_drive, entries or [("", "")], current)
        several = len(self.drives) > 1
        self.combo_drive.setVisible(several)
        self.combo_drive.setEnabled(several and not self.is_running)
        drive = self.selected_drive()
        self.lbl_drive_name.setVisible(not several)
        self.lbl_drive_name.setText(drive.name if drive else self.t("burn_no_drive"))

    def media_text(self, lang: Optional[str] = None) -> str:
        lang = lang or ui_language()
        media = self.media
        if self.selected_drive() is None:
            hint = getattr(self.backend, "no_drive_hint", None) if self.usable else None
            return self.t(hint) if hint else "–"
        if media is None:
            return self.t("burn_media_unknown")
        if not media.present:
            return self.t("burn_media_none")
        if media.busy:
            return self.t("burn_media_busy")
        kind = media.kind or media.media_class or "?"
        if not media.is_bd:
            return self.t("burn_media_not_bd", kind=kind)
        size = _gb(media.capacity_bytes, lang)
        if media.blank:
            return self.t("burn_media_blank", kind=kind, size=size)
        if media.needs_erase:
            return self.t("burn_media_rewritable_used", kind=kind, size=size)
        return self.t("burn_media_used", kind=kind)

    def _update_media(self, lang: str):
        self.lbl_media.setText(self.media_text(lang))
        self.lbl_media.setVisible(self.selected_drive() is not None or (self.usable and bool(
            getattr(self.backend, "no_drive_hint", None))))

    def _update_speed_combo(self):
        speeds = self.media.speeds if self.media is not None and self.media.present else []
        entries = [(SPEED_AUTO, self.t("burn_speed_auto"))] + [(s, s.replace("x", "×")) for s in speeds]
        if self.speed and self.speed not in speeds:
            entries.append((self.speed, self.speed.replace("x", "×")))   # gemerkte Wahl bleibt sichtbar
        fill_combo(self.combo_speed, entries, self.speed)

    def _update_recent(self):
        self.lbl_recent.setVisible(bool(self.recent))
        self.list_recent.setVisible(bool(self.recent))
        self.list_recent.clear()
        for path in self.recent:
            item = QListWidgetItem(os.path.basename(path))
            item.setData(Qt.UserRole, path)
            exists = os.path.isfile(path)
            item.setToolTip(path if exists else self.t("burn_recent_missing", path=path))
            if not exists:
                item.setForeground(QtGui.QColor("#52525B"))
            self.list_recent.addItem(item)

    def state_level(self) -> str:
        """Farbe des Punkts – beschreibt nur den Brenner: ready (grün), warning (gelb), error (rot), idle (grau: kein
        Laufwerk oder keine Disc). Was die ISO betrifft, zeigt die linke Karte."""
        issues = [i for i in self.issues() if i.key not in ISO_KEYS]
        if any(i.key in IDLE_KEYS for i in issues):
            return "idle"
        if checks.has_errors(issues):
            return checks.ERROR
        return checks.WARNING if issues else "ready"

    def _update_issues(self):
        if self.is_running:
            self.lbl_issues.setVisible(False)
            return
        level = self.state_level()
        self.lbl_dot.setText(f'<span style="color:{DOT_COLOR[level]}; font-size: 15px;">●</span>')
        lines = []
        for issue in self.issues():
            if issue.key in HIDDEN_KEYS:
                continue                     # steht schon im Satz zum Medium oder auf der linken Karte
            color = LEVEL_COLOR[issue.level]
            lines.append(f'<span style="color:{color}">{self.t(issue.key, **issue.args)}</span>')
        if not lines and level == "ready" and self.iso is not None:
            lines.append(f'<span style="color:{DOT_COLOR["ready"]}">{self.t("burn_ready")}</span>')
        self.lbl_issues.setText("<br>".join(lines))
        self.lbl_issues.setVisible(bool(lines))

    def _update_actions(self):
        running = self.is_running
        ready = self.usable and not checks.has_errors(self.issues())
        self.act_burn.setEnabled(ready and not running)
        self.act_cancel.setEnabled(running)
        for w in (self.btn_choose, self.list_recent, self.combo_speed, self.spin_copies,
                  self.chk_verify, self.chk_eject):
            w.setEnabled(not running and (self.usable or w in (self.btn_choose, self.list_recent)))
        self.btn_diagnose.setEnabled(not running)
        self.btn_eject.setEnabled(not running and self.selected_drive() is not None)
        self.btn_simulate.setEnabled(not running and self.iso is not None)
        self.card_image.setAcceptDrops(not running)
        self._update_cancel_text()

    def _update_cancel_text(self):
        run = self.run
        if run is None or not run.writing_started:
            key = "burn_cancel"
        elif run.current_phase == PHASE_VERIFY:
            key = "burn_cancel_verify"
        elif run.options.erase:
            key = "burn_cancel_rewritable"
        else:
            key = "burn_cancel_damage"
        self.act_cancel.setText(self.t(key))

    def _log(self, text: str):
        self.log_view.appendPlainText(text)

    def _show_result(self, state: str, text: str):
        self.lbl_result.setText(text)
        self.lbl_result.setVisible(bool(text))
        self.lbl_result.setStyleSheet(f"color: {RESULT_COLOR[state]}; font-weight: 600;")

    # --- Diagnose (v1.31.0) ----------------------------------------------------------------------
    def diagnosis_text(self) -> str:
        """Alles, was für eine Rückmeldung nötig ist: Version, System, Rohausgaben der Laufwerksabfrage (nur lesend)
        und das Protokoll. Keine Pfade außer denen im Protokoll und der gewählten ISO."""
        import platform
        from core.constants import APP_NAME, APP_VERSION
        lines = [f"{APP_NAME} {APP_VERSION} – {self.t('burn_diagnose')}",
                 f"System: {platform.platform()} ({platform.machine()})",
                 f"Backend: {getattr(self.backend, 'name', '–')}"]
        if self.unavailable is not None:
            key, args = self.unavailable
            lines.append(f"Nicht verfügbar: {self.t(key, **args)}")
        if self.iso is not None:
            lines.append(f"ISO: {os.path.basename(self.iso.path)} · {self.iso.size} Bytes · Titel {self.iso.label!r} · "
                         f"BDMV {self.iso.has_bdmv} · 3D {self.iso.is_3d}")
        diagnose = getattr(self.backend, "diagnose", None)
        if diagnose is not None:
            try:
                lines += ["", diagnose()]
            except Exception as e:
                lines.append(f"Diagnose fehlgeschlagen: {type(e).__name__}: {e}")
        log = self.log_view.toPlainText().strip()
        if log:
            lines += ["", "--- Protokoll ---", log]
        return "\n".join(lines)

    def copy_diagnosis(self):
        if self.is_running:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            text = self.diagnosis_text()
        finally:
            QApplication.restoreOverrideCursor()
        QApplication.clipboard().setText(text)
        self.status.emit(self.t("burn_diagnose_copied"))

    # --- Brennen ----------------------------------------------------------------------------------
    def confirm(self, title: str, text: str) -> bool:
        """Rückfrage Ja/Nein (in Tests ersetzbar)."""
        return QMessageBox.question(self, title, text) == QMessageBox.Yes

    def ask_next_disc(self, text: str) -> bool:
        """„Nächsten Rohling einlegen“: Weiter oder Beenden (in Tests ersetzbar)."""
        box = QMessageBox(QMessageBox.Question, self.t("page_burn"), text, parent=self)
        go = box.addButton(self.t("burn_next_continue"), QMessageBox.AcceptRole)
        box.addButton(self.t("burn_next_stop"), QMessageBox.RejectRole)
        box.exec()
        return box.clickedButton() is go

    def _confirm_issues(self) -> bool:
        """Frische Prüfung direkt vor dem Brennen: Fehler melden, Warnungen bestätigen lassen."""
        self.refresh_devices(sync=True)
        issues = self.issues()
        errors = [i for i in issues if i.level == checks.ERROR]
        if errors:
            QMessageBox.warning(self, self.t("page_burn"),
                                "\n".join(self.t(i.key, **i.args) for i in errors))
            return False
        warnings = [i for i in issues if i.level == checks.WARNING]
        if warnings:
            text = "\n\n".join(self.t(i.key, **i.args) for i in warnings) + "\n\n" + self.t("burn_confirm_go")
            return self.confirm(self.t("page_burn"), text)
        return True

    def start_burn(self):
        if self.is_running or not self.usable or not self._confirm_issues():
            return
        self._copies = self.spin_copies.value()
        self._copy = 1
        self._results = []
        self.log_view.clear()
        self._start_copy()

    def _start_copy(self):
        drive = self.selected_drive()
        options = BurnOptions(speed=self.speed, verify=self.verify_after,
                              erase=bool(self.media is not None and self.media.needs_erase))
        eject = should_eject(self._copy, self._copies, self.eject_after)
        if self._copies > 1:
            self._log(self.t("burn_log_copy", n=self._copy, total=self._copies))
        self._log(self.t("burn_log_start", iso=self.iso_path, drive=drive.name))
        self._show_result("info", "")
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.activity.setVisible(True)
        self.run = BurnRun(self.backend, drive, self.iso_path, options, eject, ui_language())
        self._timer.start()
        self.running_changed.emit(True)
        self._update_actions()
        self._update_drive_combo()

    def cancel_burn(self):
        run = self.run
        if run is None or run.finished:
            return
        if run.writing_started and run.current_phase != PHASE_VERIFY:
            key = "burn_cancel_confirm_rewritable" if run.options.erase else "burn_cancel_confirm_damage"
            if not self.confirm(self.t("page_burn"), self.t(key)):
                return
        run.cancel()
        self._log(self.t("burn_log_cancelling"))

    def cancel_running(self):
        """Beim Schließen des Programms: ohne Rückfrage abbrechen."""
        if self.run is not None:
            self.run.cancel()

    def wait_until_finished(self, timeout: float):
        if self.run is not None:
            self.run.join(timeout)
            self._poll()

    def _poll(self):
        self._collect_probe()
        run = self.run
        if run is None:
            if self._probe_future is None and not self.isVisible():
                self._timer.stop()
            return
        for line in run.take_log():
            self._log(line)
        share = run.current_progress
        if share is None:
            self.progress.setRange(0, 0)           # unbestimmt (Vorbereiten, Abschließen)
        else:
            self.progress.setRange(0, 1000)
            self.progress.setValue(int(share * 1000))
        phase = self.t(f"burn_phase_{run.current_phase}")
        copy = self.t("burn_copy_of", n=self._copy, total=self._copies) + " · " if self._copies > 1 else ""
        self.lbl_phase.setText(f"{copy}{phase}")
        self.lbl_percent.setText(f"{int(share * 100)} %" if share is not None else "")
        self.progress_text.emit(f"{int(share * 100)} %" if share is not None else "…")
        self._update_cancel_text()
        if run.finished:
            self._on_copy_done(run)

    def _outcome_text(self, outcome, wanted_verify: bool = False) -> tuple:
        if outcome.ok:
            if outcome.verified:
                return "ok", self.t("burn_result_ok_verified")
            return "ok", self.t("burn_result_ok_unverified" if wanted_verify else "burn_result_ok")
        if outcome.cancelled:
            if outcome.phase == PHASE_VERIFY:
                return "fail", self.t("burn_result_verify_cancelled")
            return "fail", self.t("burn_result_cancelled_damaged" if outcome.disc_damaged
                                  else "burn_result_cancelled")
        if outcome.phase == PHASE_VERIFY:
            return "fail", self.t("burn_result_verify_failed", err=outcome.error)
        return "fail", self.t("burn_result_failed", err=outcome.error)

    def _on_copy_done(self, run: BurnRun):
        outcome = run.outcome
        for line in run.take_log():
            self._log(line)
        self.run = None
        self.progress.setRange(0, 1000)
        self.progress.setValue(1000 if outcome.ok else 0)
        state, text = self._outcome_text(outcome, run.options.verify)
        if self._copies > 1:
            text = self.t("burn_copy_of", n=self._copy, total=self._copies) + ": " + text
        self._results.append(text)
        self._log(("✅ " if outcome.ok else "❌ ") + text)
        self._show_result(state, text)
        self.lbl_phase.setText(self.t("burn_done_title" if outcome.ok else "burn_failed_title"))
        self.lbl_percent.setText("")
        self.progress.setVisible(False)
        if not outcome.ok and not outcome.cancelled:
            self.set_log_visible(True)          # Fehler: Einzelheiten gleich zeigen
        if self.iso_path:
            self.add_recent(self.iso_path)
        if self._copy < self._copies and not outcome.cancelled:
            key = "burn_next_disc" if outcome.ok else "burn_next_after_failure"
            while self.ask_next_disc(self.t(key, n=self._copy, total=self._copies)):
                if self._confirm_issues():
                    self._copy += 1
                    self._start_copy()
                    return
                key = "burn_next_disc_again"
        self._finish()

    def _finish(self):
        self.progress_text.emit("")
        self.running_changed.emit(False)
        if len(self._results) > 1:
            self._log("\n".join(self._results))
        self.status.emit(self._results[-1] if self._results else "")
        if not self.isVisible():
            self._timer.stop()
        self.refresh_devices()
        self._update_all()
