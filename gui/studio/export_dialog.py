# gui/studio/export_dialog.py
"""
„Disc erstellen“: Preflight-Check, Ziel & Format, Export-Protokoll.

Der Export läuft über den unveränderten Ablauf in modules/disc_export.py. Die Menüseiten
kommen aus dem Node-Graphen (Export-Adapter), alles andere wie bisher.
Sobald die BDMV-Struktur fertig ist (vor ISO und Aufräumen), spielt der Disc-Simulator sie
durch; die Befunde erscheinen im Protokoll, danach lässt sich die Disc im Simulator öffnen.
"""

import os
import time
from typing import Optional

from PySide6 import QtGui
from PySide6.QtCore import Qt, QThread, QTimer, Signal, QSize
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget, QListWidgetItem, QPlainTextEdit,
    QProgressBar, QFileDialog, QButtonGroup, QCheckBox, QMessageBox,
)

from core.translations import tr, ui_language
from core.preflight import run_preflight, has_errors, ERROR, WARNING, INFO
from core.disc_adapter import build_export_plan, DiscExportError
from gui.node_editor.controller import GraphController
from gui.studio.widgets import DropFrame, hint_label
from gui.studio.export_activity import WriteMeter, format_clock, format_bytes
from gui.icons import level_icon, start_icon, format_icon, LEVEL_ERROR, LEVEL_WARNING, LEVEL_INFO, LEVEL_OK, \
    LEVEL_COLORS

LEVEL_ICON = {ERROR: LEVEL_ERROR, WARNING: LEVEL_WARNING, INFO: LEVEL_INFO}   # gui/icons.py, statt Emoji (v1.19.0)
LEVEL_COLOR = {ERROR: "#F87171", WARNING: "#FDE047", INFO: "#A1A1AA"}

# Lebenszeichen unter dem Fortschrittsbalken (v1.17.6)
SPINNER = "◐◓◑◒"
STALL_SECONDS = 600   # so lange weder neue Daten noch eine Meldung → gelber Hinweis
ACTIVITY_COLOR = {"run": "#A1A1AA", "stall": "#FDE047", "fail": "#F87171", "ok": "#4ADE80"}

# Umschalter-Stil wie im bisherigen Export-Bereich
SEGMENT_STYLE = """
    QPushButton { background-color: #202024; border: 1px solid #3F3F46; border-radius: 6px;
                  padding: 6px 16px; color: #A1A1AA; font-weight: 500; font-size: 13px; }
    QPushButton:hover { background-color: #2E2E33; color: #FAFAFA; }
    QPushButton:checked { background-color: #FBBF24; border: 1px solid #FBBF24; color: #18181B; font-weight: bold; }
"""


def project_fingerprint(project) -> str:
    """Inhalt des Projekts ohne die Ansicht, als Text zum Vergleichen (v1.30.3)."""
    import json
    data = project.to_dict()
    data.pop("view", None)
    return json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)


class _ExportThread(QThread):
    log = Signal(str)
    progress = Signal(float)
    done = Signal(bool, str)

    def __init__(self, project_state, pages_specs, lang: str = "de"):
        super().__init__()
        self.project_state = project_state
        self.pages_specs = pages_specs
        self.lang = lang
        self.disc = None          # geladene Disc für den Simulator (bleibt nach dem Aufräumen nutzbar)

    def t(self, key: str, **kwargs) -> str:
        return tr(key, self.lang).format(**kwargs)

    def run(self):
        from modules.disc_export import export_disc
        try:
            ok, message = export_disc(self.project_state, self.log.emit, self.progress.emit, self.pages_specs,
                                      on_disc_ready=self._simulate)
        except Exception as e:  # export_disc fängt selbst ab; dies ist nur ein Sicherheitsnetz
            ok, message = False, str(e)
        self.done.emit(ok, message)

    def _simulate(self, dest: str):
        """Spielt die fertige Disc im Simulator durch (3D- und 2D-Fernseher) und protokolliert die Befunde."""
        from modules.bdsim.disc import load_disc
        from modules.bdsim.explore import explore, merge_findings
        self.log.emit(self.t("export_sim_running"))
        try:
            disc = load_disc(dest)
            findings = merge_findings([explore(disc, tv_3d=True), explore(disc, tv_3d=False)])
        except Exception as e:
            self.log.emit(self.t("export_sim_failed", err=e))
            return
        self.disc = disc
        for line in simulation_report_lines(findings, self.t):
            self.log.emit(line)


def simulation_report_lines(findings, t) -> list:
    """Protokollzeilen mit den Befunden des Disc-Simulators."""
    count = lambda level: sum(1 for f in findings if f.level == level)
    icons = {"fehler": "⛔", "warnung": "⚠️", "hinweis": "💡"}
    return ([t("export_sim_result", errors=count("fehler"), warnings=count("warnung"), hints=count("hinweis"))]
            + [f"   {icons[f.level]} {f.text}" for f in findings])


class ExportDialog(QDialog):
    select_node = Signal(str)
    select_button = Signal(str, str)   # (Menü-ID, Button-ID): Meldung zu einem Button (v1.12.2)
    open_generator = Signal(str, str)  # (Menü-ID, Film-ID): „Kapitel … sind in keinem Menü“ → Generator (v1.14.2)
    open_relink = Signal()             # „Datei fehlt“ → Medien neu verknüpfen (v1.17.0)
    iso_created = Signal(str)          # fertige ISO (v1.30): kommt in „Zuletzt verwendet“ im Bereich Brennen
    burn_iso = Signal(str)             # „Zum Brennen“ (v1.30)

    def __init__(self, controller: GraphController, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.thread: Optional[_ExportThread] = None
        self.setMinimumSize(760, 640)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        # Preflight
        self.card_check = DropFrame()
        self.card_check.setAcceptDrops(False)
        self.issue_list = QListWidget()
        self.issue_list.setIconSize(QSize(14, 14))
        self.issue_list.setMinimumHeight(140)
        self.issue_list.itemClicked.connect(self._on_issue_clicked)
        self.lbl_summary = QLabel()
        check_row = QHBoxLayout()
        check_row.addWidget(self.lbl_summary, stretch=1)
        self.btn_recheck = QPushButton()
        self.btn_recheck.clicked.connect(self.run_checks)
        check_row.addWidget(self.btn_recheck)
        self.card_check.layout_.addLayout(check_row)
        self.card_check.layout_.addWidget(self.issue_list)
        layout.addWidget(self.card_check)

        # Ziel & Format
        self.card_target = DropFrame()
        self.card_target.setAcceptDrops(False)
        dest_row = QHBoxLayout()
        self.lbl_dest = QLabel()
        self.lbl_dest.setStyleSheet("color: #A1A1AA;")
        self.btn_dest = QPushButton()
        self.btn_dest.clicked.connect(self._choose_destination)
        dest_row.addWidget(self.lbl_dest, stretch=1)
        dest_row.addWidget(self.btn_dest)
        fmt_row = QHBoxLayout()
        self.btn_folder = QPushButton()
        self.btn_iso = QPushButton()
        self.fmt_group = QButtonGroup(self)
        for i, (b, kind) in enumerate(((self.btn_folder, "folder"), (self.btn_iso, "disc"))):
            b.setIcon(format_icon(kind))
            b.setIconSize(QSize(16, 16))
            b.setCheckable(True)
            b.setStyleSheet(SEGMENT_STYLE)
            b.setFixedHeight(34)
            b.setMinimumWidth(160)
            self.fmt_group.addButton(b, i)
            fmt_row.addWidget(b)
        fmt_row.addStretch(1)
        self.fmt_group.idToggled.connect(self._on_format)
        self.chk_clean = QCheckBox()
        self.chk_clean.toggled.connect(lambda on: self.controller.set_settings("Aufräumen ändern", clean_iso_temp=on))
        self.card_target.layout_.addLayout(dest_row)
        self.card_target.layout_.addLayout(fmt_row)
        self.card_target.layout_.addWidget(self.chk_clean)
        self.chk_disc_title = QCheckBox()
        self.chk_disc_title.toggled.connect(
            lambda on: self.controller.set_settings("Disc-Titel ändern", disc_title_meta=on))
        self.card_target.layout_.addWidget(self.chk_disc_title)
        layout.addWidget(self.card_target)

        # Protokoll
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        from gui.theme import mono_font
        self.log_view.setFont(mono_font(10))
        self.log_view.setStyleSheet("QPlainTextEdit { background-color: #111113; border: 1px solid #2E2E33;"
                                    " border-radius: 6px; color: #A1A1AA; padding: 8px; }")
        layout.addWidget(self.log_view, stretch=1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        # Prozent nicht im Balken (v1.30.1): helle Schrift auf Amber war kaum lesbar; sie steht in der Zeile darunter
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        layout.addWidget(self.progress)
        self.lbl_activity = QLabel()
        self.lbl_activity.setVisible(False)
        layout.addWidget(self.lbl_activity)
        self._activity_timer = QTimer(self)
        self._activity_timer.setInterval(1000)
        self._activity_timer.timeout.connect(self._tick_activity)
        self._meter: Optional[WriteMeter] = None

        buttons = QHBoxLayout()
        self.lbl_hint = hint_label()
        buttons.addWidget(self.lbl_hint, stretch=1)
        self.btn_simulate = QPushButton()
        self.btn_simulate.clicked.connect(self.open_simulator)
        self.btn_simulate.setVisible(False)
        buttons.addWidget(self.btn_simulate)
        self._sim_window = None
        self.iso_path: Optional[str] = None          # ISO des letzten erfolgreichen Exports
        # Ergebnis des letzten erfolgreichen Exports (v1.30.3): solange das Projekt danach unverändert ist, ist der
        # nächste Schritt die Hauptaktion – „Zum Brennen ▸“ (ISO) bzw. „Fertig“ (Ordner); Export wird grau.
        self._result: Optional[dict] = None
        self._export_kind = "folder"
        self.btn_close = QPushButton()
        self.btn_close.clicked.connect(self.close)
        self.btn_start = QPushButton()
        self.btn_start.setObjectName("primary_btn")
        self.btn_start.setMinimumHeight(38)
        self.btn_start.setIcon(start_icon())
        self.btn_start.clicked.connect(self.start_export)
        self.btn_burn = QPushButton()
        self.btn_burn.setMinimumHeight(38)
        self.btn_burn.clicked.connect(lambda: self.iso_path and self.burn_iso.emit(self.iso_path))
        self.btn_burn.setVisible(False)
        self.btn_done = QPushButton()
        self.btn_done.setMinimumHeight(38)
        self.btn_done.clicked.connect(self.close)
        self.btn_done.setVisible(False)
        for button in (self.btn_close, self.btn_start, self.btn_burn, self.btn_done):
            buttons.addWidget(button)
        layout.addLayout(buttons)

        self.controller.changed.connect(self._on_model_changed)
        self.retranslate()
        self._load_settings()
        self.run_checks()

    def t(self, key: str, **kwargs) -> str:
        text = tr(key, ui_language())
        return text.format(**kwargs) if kwargs else text

    # --- Anzeige --------------------------------------------------------------
    def retranslate(self):
        self.setWindowTitle(self.t("export_dialog_title"))
        self.btn_start.setText(self.t("btn_start_export"))
        self.card_check.set_title(self.t("export_dialog_preflight"))
        self.btn_recheck.setText(self.t("export_dialog_recheck"))
        self.card_target.set_title(self.t("export_dialog_target"))
        self.btn_dest.setText(self.t("export_dest"))
        self.btn_folder.setText(self.t("export_folder"))
        self.btn_iso.setText(self.t("export_iso") + " (.iso)")
        self.chk_clean.setText(self.t("export_clean_temp"))
        self.chk_disc_title.setText(self.t("export_disc_title", title=self.controller.project.settings.player_title()))
        self.chk_disc_title.setToolTip(self.t("export_disc_title_tip"))
        self.btn_close.setText(self.t("export_dialog_close"))
        self.btn_burn.setText(self.t("export_to_burn"))
        self.btn_burn.setToolTip(self.t("export_to_burn_tip"))
        self.btn_done.setText(self.t("export_done_close"))
        self.btn_simulate.setText(self.t("export_sim_open"))

    def _load_settings(self):
        s = self.controller.project.settings
        self.lbl_dest.setText(s.output_path or self.t("export_dialog_no_dest"))
        self.lbl_dest.setToolTip(s.output_path)
        button = self.btn_iso if s.export_format == "iso" else self.btn_folder
        if not button.isChecked():
            self.fmt_group.blockSignals(True)
            button.setChecked(True)
            self.fmt_group.blockSignals(False)
        self.chk_clean.blockSignals(True)
        self.chk_clean.setChecked(s.clean_iso_temp)
        self.chk_clean.blockSignals(False)
        self.chk_clean.setVisible(s.export_format == "iso")
        self.chk_disc_title.setText(self.t("export_disc_title", title=s.player_title()))
        self.chk_disc_title.blockSignals(True)
        self.chk_disc_title.setChecked(s.disc_title_meta)
        self.chk_disc_title.blockSignals(False)

    def _on_model_changed(self):
        self._load_settings()
        if not self.is_running():
            self.run_checks()

    def run_checks(self):
        issues = self._tool_issues() + run_preflight(self.controller.project)
        self.issue_list.clear()
        for issue in sorted(issues, key=lambda i: (ERROR, WARNING, INFO).index(i.level)):
            item = QListWidgetItem(level_icon(LEVEL_ICON[issue.level]), issue.message)
            item.setForeground(QtGui.QColor(LEVEL_COLOR[issue.level]))
            item.setData(Qt.UserRole, issue.node_id)
            item.setData(Qt.UserRole + 1, issue.button_id)
            item.setData(Qt.UserRole + 2, (issue.action, issue.film_id))
            self.issue_list.addItem(item)
        errors = sum(1 for i in issues if i.level == ERROR)
        warnings = sum(1 for i in issues if i.level == WARNING)
        if not issues:
            self.lbl_summary.setText(self.t("export_dialog_all_ok"))
            self.lbl_summary.setStyleSheet(f"color: {LEVEL_COLORS[LEVEL_OK]};")
            self.issue_list.setVisible(False)
        else:
            self.lbl_summary.setText(self.t("export_dialog_summary", errors=errors, warnings=warnings))
            self.lbl_summary.setStyleSheet("")
            self.issue_list.setVisible(True)
        self._blocked_by_errors = has_errors(issues)
        self._update_start_button()
        return issues

    def _tool_issues(self) -> list:
        """Fehlende Werkzeuge (v1.19.1) – nur hier, nicht im Preflight: Sie gehören zum Rechner, nicht zum Projekt."""
        from core.preflight import Issue
        from modules.external_tools import missing_tools, tools_folder_hint
        names = {"ffmpeg": "ffmpeg", "ffprobe": "ffprobe", "tsmuxer": "tsMuxeR"}
        return [Issue(ERROR, self.t("export_tool_missing", tool=names[t], folder=tools_folder_hint()))
                for t in missing_tools()]

    def result_is_current(self) -> bool:
        """Gibt es ein Ergebnis des letzten Exports, und ist das Projekt seitdem inhaltlich unverändert? Verglichen
        wird der Inhalt ohne die Ansicht (Knotenpositionen, Hilfslinien): Graph, Format und Zielordner zählen,
        Verschieben von Knoten nicht. Der Rückgängig-Verlauf taugt dafür nicht – zusammengefasste Schritte ändern
        ihn nicht, und „geändert“ kommt, bevor er weiterzählt."""
        r = self._result
        return r is not None and not self.is_running() and project_fingerprint(self.controller.project) == r["print"]

    @staticmethod
    def _set_primary(button: QPushButton, primary: bool):
        name = "primary_btn" if primary else ""
        if button.objectName() != name:
            button.setObjectName(name)
            button.style().unpolish(button)
            button.style().polish(button)

    def _update_start_button(self):
        dest = self.controller.project.settings.output_path
        can_start = not self._blocked_by_errors and bool(dest) and not self.is_running()
        self.btn_start.setEnabled(can_start)
        done = self.result_is_current()
        kind = self._result["kind"] if done else None
        self.btn_start.setText(self.t("export_again" if done else "btn_start_export"))
        self.btn_start.setIcon(QtGui.QIcon() if done else start_icon())
        self._set_primary(self.btn_start, not done)
        self.btn_burn.setVisible(kind == "iso")
        self._set_primary(self.btn_burn, kind == "iso")
        self.btn_done.setVisible(kind == "folder")
        self._set_primary(self.btn_done, kind == "folder")
        self.btn_close.setVisible(kind != "folder")       # „Fertig“ schließt; zwei Knöpfe dafür wären doppelt
        self.lbl_hint.setStyleSheet(f"color: {LEVEL_COLORS[LEVEL_OK]}; font-size: 12px;" if done
                                    else "color: #71717A; font-size: 11px;")
        if self.is_running():
            self.lbl_hint.setText("")
        elif done:
            self.lbl_hint.setText(self._result["text"])
        elif self._blocked_by_errors:
            self.lbl_hint.setText(self.t("export_dialog_fix_errors"))
        elif not dest:
            self.lbl_hint.setText(self.t("export_dialog_choose_dest"))
        else:
            self.lbl_hint.setText("")

    def _on_issue_clicked(self, item: QListWidgetItem):
        from core.preflight import ACTION_GENERATOR, ACTION_RELINK
        node_id, button_id = item.data(Qt.UserRole), item.data(Qt.UserRole + 1)
        action, film_id = item.data(Qt.UserRole + 2) or (None, None)
        if action == ACTION_RELINK:
            self.open_relink.emit()
        elif action == ACTION_GENERATOR and node_id:
            self.select_node.emit(node_id)
            self.open_generator.emit(node_id, film_id or "")
        elif node_id and button_id:
            self.select_button.emit(node_id, button_id)
        elif node_id:
            self.select_node.emit(node_id)

    # --- Einstellungen ------------------------------------------------------------
    def _choose_destination(self):
        path = QFileDialog.getExistingDirectory(self, self.t("export_dest"),
                                                self.controller.project.settings.output_path or "")
        if path:
            self.controller.set_settings("Zielordner wählen", output_path=path)

    def _on_format(self, index: int, checked: bool):
        if checked:
            self.controller.set_settings("Exportformat ändern", export_format="iso" if index == 1 else "folder")

    # --- Export ---------------------------------------------------------------------
    def is_running(self) -> bool:
        return self.thread is not None and self.thread.isRunning()

    def start_export(self):
        if self.is_running() or has_errors(self.run_checks()):
            return
        project = self.controller.project
        unconfirmed = [f for f in project.films if f.compliance_warnings and not f.warnings_acknowledged]
        if unconfirmed:
            names = ", ".join(f.name for f in unconfirmed)
            answer = QMessageBox.question(self, self.t("compliance_export_title"),
                                          self.t("export_dialog_confirm_warnings", films=names))
            if answer != QMessageBox.Yes:
                return
            for film in unconfirmed:
                self.controller.set_film_fields(film.id, "Hinweise bestätigen", warnings_acknowledged=True)

        try:
            plan = build_export_plan(self.controller.project)
        except DiscExportError as e:
            self.log_view.appendPlainText("❌ " + str(e))
            return
        os.makedirs(plan.project_state.output_path, exist_ok=True)

        self.log_view.clear()
        self.progress.setValue(0)
        self.btn_simulate.setVisible(False)
        self.btn_burn.setVisible(False)
        self.iso_path = None
        self._result = None
        self._export_kind = "iso" if self.controller.project.settings.export_format == "iso" else "folder"
        self._export_dest = plan.project_state.output_path
        self.thread = _ExportThread(plan.project_state, plan.pages_specs, ui_language())
        self.thread.log.connect(self._log)
        self.thread.log.connect(self._mark_signal)
        self.thread.progress.connect(lambda r: self.progress.setValue(max(0, min(100, int(r * 100)))))
        self.thread.progress.connect(self._mark_signal)
        self.thread.done.connect(self._on_done)
        self._set_controls_enabled(False)
        self._start_activity(plan.project_state.output_path)
        self.thread.start()
        self._update_start_button()

    def _log(self, text: str):
        self.log_view.appendPlainText(text)
        bar = self.log_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    # --- Lebenszeichen ---------------------------------------------------------
    def _start_activity(self, dest: str):
        now = time.monotonic()
        self._meter = WriteMeter(dest)
        self._activity_start = self._last_signal = self._last_growth = now
        self._activity_start_wall = time.time()      # für die neue ISO (Änderungszeit der Datei)
        self._written = 0
        self._spin = 0
        self.progress.setStyleSheet("")
        self.lbl_activity.setVisible(True)
        self._tick_activity()
        self._activity_timer.start()

    def _mark_signal(self, *_):
        self._last_signal = time.monotonic()

    def _measure(self):
        written = self._meter.measure() if self._meter else 0
        if written > self._written:
            self._written = written
            self._last_growth = time.monotonic()

    def _tick_activity(self):
        self._measure()
        now = time.monotonic()
        elapsed = format_clock(now - self._activity_start)
        idle = now - max(self._last_signal, self._last_growth)
        if idle >= STALL_SECONDS:
            self._show_activity("stall", self.t("export_activity_stalled", idle=format_clock(idle), elapsed=elapsed))
            return
        self._spin = (self._spin + 1) % len(SPINNER)
        lang = ui_language()
        self._show_activity("run", self.t("export_activity_running", spin=SPINNER[self._spin], elapsed=elapsed,
                                          percent=self.progress.value(),
                                          written=format_bytes(self._written, lang)))

    def _finish_activity(self, ok: bool):
        self._activity_timer.stop()
        self._measure()
        elapsed = format_clock(time.monotonic() - self._activity_start)
        if ok:
            kind, size = self._meter.result()          # das Ergebnis, nicht alles unterwegs Geschriebene
            result = self.t(f"export_result_{kind}", size=format_bytes(size, ui_language()))
            self._show_activity("ok", self.t("export_activity_done", elapsed=elapsed, result=result))
        else:
            self._show_activity("fail", self.t("export_activity_failed", elapsed=elapsed))
            self.progress.setStyleSheet("QProgressBar::chunk { background-color: #DC2626; }")
        self._meter = None

    def _show_activity(self, state: str, text: str):
        self.lbl_activity.setText(text)
        self.lbl_activity.setStyleSheet(f"color: {ACTIVITY_COLOR[state]};")
        self.lbl_activity.setProperty("state", state)

    def _on_done(self, ok: bool, message: str):
        self._finish_activity(ok)
        self._log(("✨ " + self.t("export_dialog_success")) if ok else f"❌ {message}")
        self._set_controls_enabled(True)
        self.btn_simulate.setVisible(self.thread is not None and self.thread.disc is not None)
        self.iso_path = self._new_iso() if ok and self._export_kind == "iso" else None
        self._result = self._make_result() if ok else None
        self._update_start_button()
        if self.iso_path:
            self.iso_created.emit(self.iso_path)

    def _make_result(self) -> Optional[dict]:
        """Ergebnis für die Knöpfe: ISO (nur wenn die Datei gefunden wurde) oder Ordner, mit kurzem Text."""
        lang = ui_language()
        if self._export_kind == "iso":
            if not self.iso_path:
                return None
            text = self.t("export_done_iso", name=os.path.basename(self.iso_path),
                          size=format_bytes(os.path.getsize(self.iso_path), lang))
        else:
            text = self.t("export_done_folder", path=getattr(self, "_export_dest", "") or "")
        return {"kind": self._export_kind, "text": text, "print": project_fingerprint(self.controller.project)}

    def _new_iso(self) -> Optional[str]:
        """Die ISO dieses Exports: die neueste .iso im Zielordner, geschrieben seit dem Start."""
        dest = getattr(self, "_export_dest", None)
        start = getattr(self, "_activity_start_wall", None)
        if not dest or not os.path.isdir(dest):
            return None
        found = []
        for name in os.listdir(dest):
            path = os.path.join(dest, name)
            if name.lower().endswith(".iso") and os.path.isfile(path):
                mtime = os.path.getmtime(path)
                if start is None or mtime >= start - 2:
                    found.append((mtime, path))
        return max(found)[1] if found else None

    def open_simulator(self):
        if self.thread is None or self.thread.disc is None:
            return
        from gui.studio.simulator import SimulatorWindow
        if self._sim_window is not None:
            self._sim_window.close()
        self._sim_window = SimulatorWindow(self.thread.disc, ui_language(), parent=self)
        self._sim_window.show()
        self._sim_window.raise_()

    def _set_controls_enabled(self, enabled: bool):
        for w in (self.btn_dest, self.btn_folder, self.btn_iso, self.chk_clean, self.chk_disc_title,
                  self.btn_recheck, self.btn_close):
            w.setEnabled(enabled)

    def closeEvent(self, event):
        if self.is_running():
            event.ignore()
            return
        super().closeEvent(event)
