# gui/prepare/page.py
"""
Arbeitsbereich Vorbereiten (v1.22, Konzept „BD3DEnc in OpenBDAuth integrieren“): macht aus beliebigem Material
Disc-fertige Dateien. Aufbau wie die Disc-Seite: Auftragsliste in der Mitte, Inspektor rechts, Protokoll unten,
dieselben Dock-Fenster. Die Knöpfe Hinzufügen / Abbrechen / Starten zeigt die obere Leiste des Studios.

Sicherheit (Konzept, Grundsatz 2): Diese Seite ändert das Disc-Projekt nie von selbst. Sie liest die Filme
(Vorschlag, Übernehmen-Ziel) und die benutzten Mediendateien (als Ziel gesperrt, Füllstand). Geändert wird es nur auf
ausdrücklichen Klick: „In Film-Knoten übernehmen“ (bestehender Import, ein Schritt mit Undo) und ab v1.24
„Neuer Film-Knoten …“ unter „Für Film“ (ein leerer Film-Knoten als Ziel, ebenfalls mit Undo).

Warteschlange (v1.23): alles hineinziehen, je Datei festlegen (Markierung links: Ring = noch offen, Haken =
festgelegt), „Starten“ arbeitet alle wartenden Aufträge nacheinander ab, in Listenreihenfolge (per Ziehen
änderbar). Ein Fehler oder ein einzeln abgebrochener Auftrag hält die Warteschlange nicht an; „Abbrechen“ in der
oberen Leiste hält sie an. Oben: Ausgabe (neben der Quelle oder ein Ordner für alle), Füllstand der Disc.
Die Aufträge werden getrennt vom Disc-Projekt gespeichert und nach einem Neustart wiederhergestellt.
"""

import os
import shutil
import time
from typing import Dict, List, Optional

from PySide6 import QtGui
from PySide6.QtCore import Qt, QTimer, Signal, QSettings, QStandardPaths, QItemSelectionModel
from PySide6.QtWidgets import (
    QMainWindow, QDockWidget, QTreeWidget, QTreeWidgetItem, QStackedWidget, QLabel, QWidget, QVBoxLayout,
    QHBoxLayout, QTextEdit, QFileDialog, QMessageBox, QAbstractItemView, QHeaderView, QComboBox, QProgressBar,
    QInputDialog,
)

from core.translations import tr, tr_file_filter, ui_language
from gui.app_language import SETTINGS_ORG, SETTINGS_APP
from gui.icons import job_kind_icon, level_icon, settings_mark_icon, LEVEL_ERROR, LEVEL_OK, LEVEL_INFO
from gui.prepare.inspector import PrepareInspector
from gui.studio.widgets import ElidedLabel, fill_combo
from modules.prepare import jobs, tasks
from modules.prepare.background import BackgroundTask
from modules.prepare.runner import run_task

POLL_MS = 200
COL_SOURCE, COL_KIND, COL_OUTPUT, COL_STATUS = range(4)
SOURCE_FILTER = "Video und Ton (*.mp4 *.mov *.mkv *.m4v *.avi *.mxf *.ts *.m2ts *.wav *.flac *.mka *.ac3 *.dts " \
                "*.eac3 *.thd *.aac *.mp3);;Alle Dateien (*.*)"
QUEUE_FILE = "prepare_queue.json"
OUT_BESIDE, OUT_COMMON = "beside", "common"
GAUGE_QSS = "QProgressBar::chunk {{ background-color: {color}; border-radius: 4px; }}"
GB = 1e9                 # dezimal wie BD-25/BD-50 (v1.30.4; vorher 1024³ – eine leere BD-25 hieß „23,3 GB“)


def _size_text(n: float) -> str:
    from gui.studio.export_activity import format_bytes
    return format_bytes(n, ui_language())


def _same_path(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _clock(seconds: float) -> str:
    """Restzeit grob: „< 1 min“, „12 min“, „1:05 h“."""
    if seconds < 60:
        return "< 1 min"
    minutes = int(round(seconds / 60))
    return f"{minutes} min" if minutes < 60 else f"{minutes // 60}:{minutes % 60:02d} h"


def _files(event) -> list:
    mime = event.mimeData()
    return [u.toLocalFile() for u in mime.urls() if u.isLocalFile()] if mime.hasUrls() else []


class _DropArea(QStackedWidget):
    """Mitte ohne Aufträge: Hinweis, auf den Dateien gezogen werden können."""
    files_dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if _files(event):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if _files(event):
            event.acceptProposedAction()

    def dropEvent(self, event):
        files = _files(event)
        if files:
            event.acceptProposedAction()
            self.files_dropped.emit(files)


class _TaskList(QTreeWidget):
    """Auftragsliste: Reihenfolge per Ziehen (= Reihenfolge der Warteschlange), Dateien von außen hineinziehen."""
    files_dropped = Signal(list)
    reordered = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)

    def dragEnterEvent(self, event):
        if _files(event):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if _files(event):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        files = _files(event)
        if files:
            event.acceptProposedAction()
            self.files_dropped.emit(files)
            return
        super().dropEvent(event)
        self.reordered.emit()


class PreparePage(QMainWindow):
    status = Signal(str)                 # Meldung für die Statusleiste des Studios
    running_changed = Signal(bool)
    progress_text = Signal(str)          # Fortschritt für die Statusleiste beider Seiten ("" = nichts läuft)

    def __init__(self, controller, importer, parent=None, persist: bool = True):
        super().__init__(parent)
        self.setWindowFlags(Qt.Widget)   # eingebettet in das Studio-Fenster
        self.setObjectName("PreparePage")
        self.controller = controller
        self.importer = importer
        self.persist = persist           # Warteschlange und Ausgabe-Einstellung speichern (in Tests aus)
        self.tasks: List[tasks.PrepareTask] = []
        self._running: Optional[tuple] = None        # (Auftrag, BackgroundTask, Startzeit)
        self._queue_active = False
        self._queue_run: List[str] = []              # IDs der Aufträge dieses Durchlaufs (Zusammenfassung)
        self._overwrite_ok: set = set()              # beim Start bestätigt: vorhandene Zieldateien ersetzen
        self._rates: Dict[str, float] = {}           # Sekunden Arbeit je Sekunde Laufzeit, je Art (Restzeit)
        self.common_dir: Optional[str] = None        # „ein Ordner für alle“, sonst neben der Quelle
        self.disc_size = "bd25"
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._poll)

        # Mitte: Kopfleiste und Liste
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)
        center_layout.addWidget(self._build_header())
        self.area = _DropArea()
        self.area.files_dropped.connect(self.add_files)
        self.lbl_empty = QLabel()
        self.lbl_empty.setAlignment(Qt.AlignCenter)
        self.lbl_empty.setWordWrap(True)
        self.lbl_empty.setStyleSheet("color: #71717A; font-size: 14px; padding: 40px;")
        self.list = _TaskList()
        self.list.setColumnCount(4)
        self.list.header().setSectionResizeMode(COL_SOURCE, QHeaderView.Stretch)
        for col in (COL_KIND, COL_OUTPUT, COL_STATUS):
            self.list.header().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.list.itemSelectionChanged.connect(self._on_selection)
        self.list.files_dropped.connect(self.add_files)
        self.list.reordered.connect(self._on_reordered)
        self.area.addWidget(self.lbl_empty)
        self.area.addWidget(self.list)
        center_layout.addWidget(self.area, stretch=1)
        self.setCentralWidget(center)

        # Docks: Inspektor rechts, Protokoll unten
        self.inspector = PrepareInspector(controller, self._lang)
        self.inspector.changed.connect(self._on_tasks_changed)
        self.inspector.take_over.connect(self.take_over)
        self.inspector.create_film.connect(self.create_film_for)
        self.inspector.status.connect(self.status)
        self.log_view = QTextEdit()
        self.log_view.setObjectName("log_area")
        self.log_view.setReadOnly(True)
        self.dock_inspector = self._make_dock("prep_dock_inspector", self.inspector)
        self.dock_log = self._make_dock("prep_dock_log", self.log_view)
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock_inspector)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.dock_log)
        self._sized = False

        # Aktionen (die obere Leiste des Studios zeigt Hinzufügen, Abbrechen, Starten)
        self.act_add = QtGui.QAction(self)
        self.act_add.triggered.connect(self.choose_files)
        self.act_cancel = QtGui.QAction(self)
        self.act_cancel.triggered.connect(self.stop_queue)
        self.act_start = QtGui.QAction(self)
        self.act_start.triggered.connect(self.start_queue)
        self.act_cancel_task = QtGui.QAction(self)
        self.act_cancel_task.triggered.connect(self.cancel_selected_task)
        self.act_requeue = QtGui.QAction(self)
        self.act_requeue.triggered.connect(self.requeue_selected)
        self.act_remove = QtGui.QAction(self)
        self.act_remove.setShortcut(QtGui.QKeySequence.Delete)
        self.act_remove.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        self.act_remove.triggered.connect(self.remove_selected)
        for act in (self.act_cancel_task, self.act_requeue, self.act_remove):
            self.list.addAction(act)
        self.list.setContextMenuPolicy(Qt.ActionsContextMenu)

        controller.changed.connect(self._on_project_changed)   # Filmliste, benutzte Dateien, Füllstand
        self._restore()
        self.retranslate()
        self._update_actions()

    def _build_header(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("prep_header")
        bar.setStyleSheet("QWidget#prep_header { background-color: #18181B; border-bottom: 1px solid #27272A; }"
                          " QLabel { background: transparent; }")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)
        self.lbl_open = QLabel()
        layout.addWidget(self.lbl_open)
        layout.addStretch(1)
        self.lbl_out_mode = QLabel()
        self.lbl_out_mode.setStyleSheet("color: #A1A1AA;")
        self.combo_out_mode = QComboBox()
        self.combo_out_mode.activated.connect(self._on_out_mode)
        self.lbl_common_dir = ElidedLabel()
        self.lbl_common_dir.setStyleSheet("color: #A1A1AA;")
        self.lbl_common_dir.setMinimumWidth(60)
        self.lbl_common_dir.setMaximumWidth(260)
        self.lbl_disc = QLabel()
        self.lbl_disc.setStyleSheet("color: #A1A1AA;")
        self.combo_disc = QComboBox()
        self.combo_disc.activated.connect(self._on_disc_size)
        self.gauge = QProgressBar()
        self.gauge.setRange(0, 100)
        self.gauge.setFixedWidth(160)
        self.gauge.setFixedHeight(8)
        # Text neben dem Balken (v1.30.1): helle Schrift auf Amber war kaum lesbar
        self.gauge.setTextVisible(False)
        self.lbl_gauge = QLabel()
        self.lbl_gauge.setStyleSheet("color: #D4D4D8;")
        for w in (self.lbl_out_mode, self.combo_out_mode, self.lbl_common_dir):
            layout.addWidget(w)
        layout.addSpacing(18)
        for w in (self.lbl_disc, self.combo_disc, self.gauge, self.lbl_gauge):
            layout.addWidget(w)
        return bar

    def showEvent(self, event):
        super().showEvent(event)
        if not self._sized:          # erst jetzt hat die eingebettete Seite eine Größe
            self._sized = True
            self.resizeDocks([self.dock_inspector], [460], Qt.Horizontal)
            self.resizeDocks([self.dock_log], [180], Qt.Vertical)

    # --- Grundlagen --------------------------------------------------------------
    def _lang(self) -> str:
        return ui_language()

    def t(self, key: str, **kwargs) -> str:
        text = tr(key, self._lang())
        return text.format(**kwargs) if kwargs else text

    def _make_dock(self, key: str, widget: QWidget) -> QDockWidget:
        dock = QDockWidget(self)
        dock.setObjectName(key)
        dock.setWidget(widget)
        dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        from gui.studio.widgets import DockTitleBar
        dock.setTitleBarWidget(DockTitleBar(dock, lambda: (self.t("studio_dock_undock"), self.t("studio_dock_back"),
                                                           self.t("studio_dock_floating_tip"))))
        return dock

    @property
    def is_running(self) -> bool:
        return self._running is not None

    def selected_tasks(self) -> List[tasks.PrepareTask]:
        """Markierte Aufträge in Listenreihenfolge."""
        ids = {item.data(COL_SOURCE, Qt.UserRole) for item in self.list.selectedItems()}
        return [t for t in self.tasks if t.id in ids]

    def selected_task(self) -> Optional[tasks.PrepareTask]:
        sel = self.selected_tasks()
        return sel[0] if len(sel) == 1 else None

    def _task(self, task_id: str) -> Optional[tasks.PrepareTask]:
        return next((t for t in self.tasks if t.id == task_id), None)

    # --- Speichern (getrennt vom Disc-Projekt) -----------------------------------------
    @staticmethod
    def queue_path() -> str:
        base = QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation)
        return os.path.join(base, "OpenBDAuth", QUEUE_FILE)

    def _restore(self):
        if not self.persist:
            return
        settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        self.common_dir = settings.value("prepare/common_dir", "") or None
        self.disc_size = settings.value("prepare/disc_size", "bd25") or "bd25"
        for task in tasks.load_queue(self.queue_path()):
            self.tasks.append(task)
            self._add_row(task)
        if self.tasks:
            self.area.setCurrentWidget(self.list)

    def _save(self):
        if not self.persist:
            return
        try:
            tasks.save_queue(self.queue_path(), self.tasks)
        except OSError as e:
            self.status.emit(str(e))
        settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        settings.setValue("prepare/common_dir", self.common_dir or "")
        settings.setValue("prepare/disc_size", self.disc_size)

    # --- Aufträge anlegen ----------------------------------------------------------
    def choose_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, self.t("prep_add").rstrip(" …"), "",
                                                tr_file_filter(SOURCE_FILTER))
        if files:
            self.add_files(files)

    def add_files(self, paths: list, target_film_id: Optional[str] = None) -> List[tasks.PrepareTask]:
        """Je Datei ein Auftrag mit Vorbelegung. Ungeeignete Quellen werden mit Begründung abgelehnt."""
        added, rejected = [], []
        for path in paths:
            try:
                task = tasks.create_task(path, self.common_dir)
            except tasks.SourceRejected as e:
                reasons = "\n".join("• " + self.t(f"prep_problem_{code}", **details) for code, details in e.problems)
                rejected.append(self.t("prep_rejected", file=os.path.basename(path)) + "\n" + reasons)
                continue
            except jobs.ProbeError as e:
                rejected.append(self.t("prep_probe_failed", file=os.path.basename(path), error=e.message))
                continue
            except ValueError:
                rejected.append(self.t("prep_unreadable", file=os.path.basename(path)))
                continue
            except OSError as e:
                # ffprobe fehlt, ist nicht ausführbar oder passt nicht zum System
                rejected.append(self.t("prep_probe_not_started", file=os.path.basename(path),
                                       tool=e.filename or "ffprobe", error=e.strerror or str(e)))
                continue
            task.target_film_id = target_film_id
            self.tasks.append(task)
            added.append(task)
            self._add_row(task)
        if added:
            self.area.setCurrentWidget(self.list)
            self.list.clearSelection()
            for task in added:
                item = self._item(task)
                if item is not None:
                    item.setSelected(True)
            self.list.setCurrentItem(self._item(added[-1]), 0, QItemSelectionModel.NoUpdate)
            self._save()
        if rejected:
            QMessageBox.warning(self, self.t("page_prepare"), "\n\n".join(rejected))
        self._refresh_header()
        self._update_actions()
        return added

    def remove_selected(self):
        removable = [t for t in self.selected_tasks() if t.status != tasks.RUNNING]
        for task in removable:
            self.tasks.remove(task)
            item = self._item(task)
            if item is not None:
                self.list.takeTopLevelItem(self.list.indexOfTopLevelItem(item))
        if not self.tasks:
            self.area.setCurrentWidget(self.lbl_empty)
        self._save()
        self._on_selection()
        self._refresh_header()

    def requeue_selected(self):
        """Fertige, fehlgeschlagene oder abgebrochene Aufträge wieder auf „wartet“ setzen."""
        for task in self.selected_tasks():
            if task.status in (tasks.DONE, tasks.FAILED, tasks.CANCELLED):
                task.status, task.progress, task.error, task.outputs = tasks.WAITING, 0.0, "", []
                self._update_row(task)
        self._save()
        self._on_selection()

    # --- Liste ------------------------------------------------------------------------
    def _add_row(self, task: tasks.PrepareTask):
        item = QTreeWidgetItem()
        item.setData(COL_SOURCE, Qt.UserRole, task.id)
        item.setFlags(item.flags() & ~Qt.ItemIsDropEnabled)      # nur zwischen Zeilen ablegen, nie darauf
        self.list.addTopLevelItem(item)
        self._fill_row(item, task)

    def _item(self, task: tasks.PrepareTask) -> Optional[QTreeWidgetItem]:
        for i in range(self.list.topLevelItemCount()):
            item = self.list.topLevelItem(i)
            if item.data(COL_SOURCE, Qt.UserRole) == task.id:
                return item
        return None

    def _update_row(self, task: tasks.PrepareTask):
        item = self._item(task)
        if item is not None:
            self._fill_row(item, task)
        self._update_actions()

    def _fill_row(self, item: QTreeWidgetItem, task: tasks.PrepareTask):
        item.setText(COL_SOURCE, task.name)
        if task.status in (tasks.DONE, tasks.RUNNING):
            item.setIcon(COL_SOURCE, self._blank_icon)
            item.setToolTip(COL_SOURCE, task.source)
        else:
            item.setIcon(COL_SOURCE, settings_mark_icon(task.confirmed))
            mark = self.t("prep_mark_confirmed" if task.confirmed else "prep_mark_open")
            item.setToolTip(COL_SOURCE, f"{task.source}\n{mark}")
        item.setIcon(COL_KIND, job_kind_icon(task.kind))
        item.setText(COL_KIND, self.t(f"prep_kind_{task.kind}"))
        try:
            outputs = task.outputs or tasks.planned_outputs(task)
            item.setText(COL_OUTPUT, ", ".join(os.path.basename(p) for p in outputs))
        except ValueError:
            item.setText(COL_OUTPUT, "–")
        item.setText(COL_STATUS, self._status_text(task))
        item.setToolTip(COL_STATUS, task.error)
        icon = {tasks.DONE: LEVEL_OK, tasks.FAILED: LEVEL_ERROR, tasks.CANCELLED: LEVEL_INFO}.get(task.status)
        item.setIcon(COL_STATUS, level_icon(icon) if icon else QtGui.QIcon())

    @property
    def _blank_icon(self) -> QtGui.QIcon:
        pixmap = QtGui.QPixmap(14, 14)
        pixmap.fill(Qt.transparent)
        return QtGui.QIcon(pixmap)

    def _status_text(self, task: tasks.PrepareTask) -> str:
        if task.status == tasks.RUNNING:
            if self._running and self._running[0] is task and self._running[1].cancelled:
                return self.t("prep_status_cancelling")
            return self.t("prep_status_running", pct=int(task.progress * 100))
        return self.t(f"prep_status_{task.status}")

    def _select(self, task: tasks.PrepareTask):
        item = self._item(task)
        if item is not None:
            self.list.clearSelection()
            self.list.setCurrentItem(item)

    def _on_selection(self):
        sel = self.selected_tasks()
        self.inspector.show_tasks(sel)
        single = sel[0] if len(sel) == 1 else None
        self.log_view.setPlainText("\n".join(single.log) if single else "")
        self.log_view.moveCursor(QtGui.QTextCursor.End)
        self._update_actions()

    def _on_reordered(self):
        order = [self.list.topLevelItem(i).data(COL_SOURCE, Qt.UserRole)
                 for i in range(self.list.topLevelItemCount())]
        self.tasks.sort(key=lambda t: order.index(t.id) if t.id in order else len(order))
        self._save()

    def _on_tasks_changed(self, changed: list):
        for task in changed:
            self._update_row(task)
        self._save()
        self._refresh_header()

    def _on_project_changed(self):
        self.inspector.refresh()
        self._refresh_header()

    def _update_actions(self):
        sel = self.selected_tasks()
        waiting = any(t.status == tasks.WAITING for t in self.tasks)
        self.act_start.setEnabled(waiting and not self._queue_active)
        self.act_cancel.setEnabled(self.is_running or self._queue_active)
        running = self._running[0] if self._running else None
        self.act_cancel_task.setEnabled(running is not None and running in sel)
        self.act_requeue.setEnabled(any(t.status in (tasks.DONE, tasks.FAILED, tasks.CANCELLED) for t in sel))
        self.act_remove.setEnabled(any(t.status != tasks.RUNNING for t in sel))

    # --- Kopfleiste: noch festzulegen, Ausgabe, Füllstand ---------------------------------
    def _refresh_header(self):
        open_tasks = [t for t in self.tasks if t.status == tasks.WAITING and not t.confirmed]
        waiting = [t for t in self.tasks if t.status == tasks.WAITING]
        self.lbl_open.setVisible(bool(waiting))
        if open_tasks:
            self.lbl_open.setText(self.t("prep_open_count", n=len(open_tasks), total=len(waiting)))
            self.lbl_open.setStyleSheet("color: #FBBF24; font-weight: bold;")
        else:
            self.lbl_open.setText(self.t("prep_all_decided"))
            self.lbl_open.setStyleSheet("color: #A1A1AA;")
        fill_combo(self.combo_out_mode, [(OUT_BESIDE, self.t("prep_out_beside")),
                                         (OUT_COMMON, self.t("prep_out_common"))],
                   OUT_COMMON if self.common_dir else OUT_BESIDE)
        self.lbl_common_dir.setVisible(bool(self.common_dir))
        self.lbl_common_dir.setText(self.common_dir or "")
        self.lbl_common_dir.setToolTip(self.common_dir or "")
        fill_combo(self.combo_disc, [("bd25", "BD-25"), ("bd50", "BD-50")], self.disc_size)
        used = self.disc_bytes()
        capacity = tasks.DISC_SIZES[self.disc_size]
        share = used / capacity
        self.gauge.setValue(int(min(1.0, share) * 100))
        number = (lambda x: f"{x:.1f}".replace(".", ",")) if self._lang() == "de" else (lambda x: f"{x:.1f}")
        self.gauge.setFormat(self.t("prep_gauge", used=number(used / GB), cap=number(capacity / GB)))
        self.lbl_gauge.setText(self.gauge.text())
        self.gauge.setToolTip(self.t("prep_gauge_tip"))
        self.lbl_gauge.setToolTip(self.t("prep_gauge_tip"))
        color = "#F87171" if share > 1.0 else "#FDE047" if share > 0.9 else "#FBBF24"
        self.gauge.setStyleSheet(GAUGE_QSS.format(color=color))
        self.lbl_gauge.setStyleSheet(f"color: {'#F87171' if share > 1.0 else '#D4D4D8'};")

    def disc_bytes(self) -> int:
        """Geschätzter Platz auf der Disc: Dateien des offenen Projekts plus alles, was die Aufträge noch liefern
        (fertige Ergebnisse, die schon im Projekt stecken, zählen nur einmal)."""
        from core.media_paths import media_refs
        used_paths = {os.path.normcase(os.path.abspath(r.path)) for r in media_refs(self.controller.project)}
        total = 0
        for path in used_paths:
            try:
                total += os.path.getsize(path)
            except OSError:
                pass
        for task in self.tasks:
            if task.status == tasks.DONE:
                if any(os.path.normcase(os.path.abspath(p)) in used_paths for p in task.outputs):
                    continue
                total += sum(os.path.getsize(p) for p in task.outputs if os.path.isfile(p))
            elif task.status in (tasks.WAITING, tasks.RUNNING):
                total += tasks.estimated_size(task)
        return total

    def _on_out_mode(self, _index: int):
        mode = self.combo_out_mode.currentData()
        if mode == OUT_COMMON:
            folder = QFileDialog.getExistingDirectory(self, self.t("prep_out_choose"), self.common_dir or "")
            if not folder:
                self._refresh_header()
                return
            self.set_common_dir(os.path.normpath(folder))
        else:
            self.set_common_dir(None)

    def set_common_dir(self, folder: Optional[str]):
        """Ausgabe für alle noch nicht gelaufenen Aufträge: ein Ordner (folder) oder neben der Quelle (None)."""
        self.common_dir = folder
        for task in self.tasks:
            if task.status in (tasks.WAITING, tasks.FAILED, tasks.CANCELLED):
                task.out_dir = tasks.default_out_dir(task.source, folder)
                self._update_row(task)
        self.inspector.refresh()
        self._save()
        self._refresh_header()

    def _on_disc_size(self, _index: int):
        self.disc_size = self.combo_disc.currentData()
        self._save()
        self._refresh_header()

    # --- Warteschlange ----------------------------------------------------------------
    def start_queue(self) -> bool:
        """Alle wartenden Aufträge nacheinander. Vorher einmal alle Rückfragen, damit nachts nichts hängt."""
        if self._queue_active:
            self.status.emit(self.t("prep_busy"))
            return False
        waiting = [t for t in self.tasks if t.status == tasks.WAITING]
        if not waiting:
            self.status.emit(self.t("prep_nothing_waiting"))
            return False
        outputs = {}
        for task in waiting:
            try:
                outputs[task.id] = tasks.planned_outputs(task)
            except ValueError as e:
                QMessageBox.warning(self, self.t("page_prepare"), f"{task.name}: {e}")
                return False
        from core.media_paths import media_refs
        used = [ref.path for ref in media_refs(self.controller.project)]
        blocked = [o for paths in outputs.values() for o in paths if any(_same_path(o, u) for u in used)]
        if blocked:
            QMessageBox.warning(self, self.t("page_prepare"),
                                self.t("prep_blocked", file=os.path.basename(blocked[0])))
            return False
        duplicates = tasks.duplicate_outputs(waiting)
        if duplicates:
            QMessageBox.warning(self, self.t("page_prepare"),
                                self.t("prep_duplicates", files="\n".join(os.path.basename(p) for p in duplicates)))
            return False
        unconfirmed = [t for t in waiting if not t.confirmed]
        if unconfirmed and not self.confirm_unconfirmed(unconfirmed):
            return False
        existing = [o for paths in outputs.values() for o in paths if os.path.exists(o)]
        if existing:
            if not self.confirm_overwrite(existing):
                return False
            self._overwrite_ok.update(t.id for t in waiting if any(o in existing for o in outputs[t.id]))
        shortfall = tasks.queue_space_shortfall(waiting)
        if shortfall:
            QMessageBox.warning(self, self.t("page_prepare"),
                                self.t("prep_space", need=_size_text(shortfall[0]), free=_size_text(shortfall[1])))
            return False
        self._queue_active = True
        self._queue_run = []
        self.running_changed.emit(True)
        self._start_next()
        return True

    def confirm_unconfirmed(self, unconfirmed: List[tasks.PrepareTask]) -> bool:
        """Rückfrage vor dem Start, wenn Einstellungen noch offen sind (in Tests ersetzbar)."""
        answer = QMessageBox.question(self, self.t("prep_unconfirmed_title"),
                                      self.t("prep_unconfirmed", files="\n".join(t.name for t in unconfirmed)))
        return answer == QMessageBox.Yes

    def confirm_overwrite(self, existing: List[str]) -> bool:
        """Rückfrage vor dem Start (in Tests ersetzbar)."""
        answer = QMessageBox.question(self, self.t("prep_overwrite_title"),
                                      self.t("prep_overwrite", files="\n".join(os.path.basename(p) for p in existing)))
        return answer == QMessageBox.Yes

    def _silent_problem(self, task: tasks.PrepareTask) -> Optional[str]:
        """Prüfung direkt vor dem Start eines Auftrags, ohne Rückfrage (auch für später hinzugefügte)."""
        try:
            outputs = tasks.planned_outputs(task)
        except ValueError as e:
            return str(e)
        from core.media_paths import media_refs
        used = [ref.path for ref in media_refs(self.controller.project)]
        for out in outputs:
            if any(_same_path(out, u) for u in used):
                return self.t("prep_blocked_failed", file=os.path.basename(out))
            if os.path.exists(out) and task.id not in self._overwrite_ok:
                return self.t("prep_exists_failed", file=os.path.basename(out))
        others = [t for t in self.tasks if t is not task and t.status in (tasks.WAITING, tasks.RUNNING)]
        if tasks.duplicate_outputs([task] + others):
            dup = [p for p in tasks.duplicate_outputs([task] + others) if p in outputs]
            if dup:
                return self.t("prep_duplicates", files=os.path.basename(dup[0]))
        return None

    def _start_next(self):
        if self._running is not None or not self._queue_active:
            return
        for task in self.tasks:
            if task.status != tasks.WAITING:
                continue
            problem = self._silent_problem(task)
            if problem:
                task.status, task.error = tasks.FAILED, problem
                task.log.append("[FEHLER] " + problem)
                self._queue_run.append(task.id)
                self._update_row(task)
                continue
            task.status, task.progress, task.outputs, task.error, task.log = tasks.RUNNING, 0.0, [], "", []
            self._queue_run.append(task.id)
            self._running = (task, BackgroundTask(run_task, task, log=True, cancellable=True), time.time())
            self._timer.start()
            self._update_row(task)
            if task in self.selected_tasks():
                self._on_selection()
            self._refresh_header()
            self._save()
            return
        self._finish_queue()

    def _finish_queue(self):
        self._queue_active = False
        self._timer.stop()
        run = [t for t in self.tasks if t.id in self._queue_run]
        if run:
            count = lambda status: sum(1 for t in run if t.status == status)
            self.status.emit(self.t("prep_queue_done", done=count(tasks.DONE), failed=count(tasks.FAILED),
                                    cancelled=count(tasks.CANCELLED)))
        self._overwrite_ok.clear()
        self.progress_text.emit("")
        self.running_changed.emit(False)
        self._update_actions()
        self._refresh_header()
        self._save()

    def stop_queue(self):
        """Obere Leiste: laufenden Auftrag abbrechen und die Warteschlange anhalten (der Rest wartet weiter)."""
        self._queue_active = False
        if self._running is not None:
            self._running[1].cancel()
            self._update_row(self._running[0])
        else:
            self._finish_queue()
        self._update_actions()

    def cancel_selected_task(self):
        """Nur den laufenden Auftrag abbrechen; die Warteschlange macht mit dem nächsten weiter."""
        if self._running is not None and self._running[0] in self.selected_tasks():
            self._running[1].cancel()
            self._update_row(self._running[0])

    def cancel_running(self):
        self.stop_queue()

    def _poll(self):
        if self._running is None:
            self._timer.stop()
            return
        task, bg, started = self._running
        finished = bg.poll()
        lines = bg.take_log()
        task.log += lines
        task.progress = bg.progress
        if lines and self.selected_task() is task:
            self.log_view.append("\n".join(lines))
        if finished:
            self._running = None
            elapsed = time.time() - started
            if bg.cancelled:
                task.status = tasks.CANCELLED
            elif bg.error:
                task.status, task.error = tasks.FAILED, bg.error
                task.log.append("[FEHLER] " + bg.error)
                if self.selected_task() is task:
                    self.log_view.append("[FEHLER] " + bg.error)
                self.status.emit(self.t("prep_failed", name=task.name))
            else:
                task.status, task.outputs, task.progress = tasks.DONE, list(bg.result or []), 1.0
                if task.duration > 0:
                    self._rates[task.kind] = elapsed / task.duration
                self.status.emit(self.t("prep_finished", name=task.name))
            self._update_row(task)
            self.inspector.refresh()
            self._refresh_header()
            self._save()
            if self._queue_active:
                QTimer.singleShot(0, self._start_next)
            else:
                self._finish_queue()
            return
        self.progress_text.emit(self._progress_text(task, time.time() - started))
        if task in self.inspector.selection:
            self.inspector.update_progress()
        self._update_row(task)

    def _progress_text(self, task: tasks.PrepareTask, elapsed: float) -> str:
        text = self.t("prep_statusbar", name=task.name, pct=int(task.progress * 100))
        rest = tasks.remaining_seconds(elapsed, task.progress)
        if rest is None:
            return text
        text += " · " + self.t("prep_eta", time=_clock(rest))
        waiting = [t for t in self.tasks if t.status == tasks.WAITING] if self._queue_active else []
        if waiting:
            live = elapsed / (task.progress * task.duration) if task.duration > 0 else None
            rates = dict(self._rates)
            if live:
                rates.setdefault(task.kind, live)
            if all(t.kind in rates for t in waiting):
                total = rest + sum(t.duration * rates[t.kind] for t in waiting)
                text += " · " + self.t("prep_eta_total", time=_clock(total))
        return text

    def wait_until_finished(self, seconds: float = 600.0) -> bool:
        """Für Tests und das Beenden: weiter abfragen, bis die Warteschlange fertig oder angehalten ist."""
        end = time.time() + seconds
        while (self._running is not None or self._queue_active) and time.time() < end:
            self._poll()
            if self._running is None and self._queue_active:
                self._start_next()
            time.sleep(0.05)
        return self._running is None and not self._queue_active

    # --- Film-Knoten als Ziel anlegen (v1.24) ----------------------------------------------
    def create_film_for(self, selection: List[tasks.PrepareTask]) -> Optional[str]:
        """Legt auf Klick einen leeren Film-Knoten an und merkt ihn den Aufträgen als Ziel vor. Die Dateien kommen
        erst nach dem Vorbereiten per „Übernehmen“ hinein; bis dahin können die Menüs schon verdrahtet werden."""
        if not selection:
            return None
        first = next((t for t in selection if t.is_video), selection[0])
        name = self.ask_film_name(os.path.splitext(first.name)[0])
        if not name:
            return None
        film_id = self.controller.add_film(name, self.importer.free_position())
        for task in selection:
            task.target_film_id = film_id
            task.confirmed = True
        self._on_tasks_changed(selection)
        self.inspector.refresh()
        self.status.emit(self.t("prep_film_created", film=name))
        return film_id

    def ask_film_name(self, default: str) -> Optional[str]:
        """Name des neuen Film-Knotens (in Tests ersetzbar)."""
        name, ok = QInputDialog.getText(self, self.t("prep_film_name_title"), self.t("prep_film_name"), text=default)
        return name.strip() if ok and name.strip() else None

    # --- Übernehmen ----------------------------------------------------------------------
    def take_over(self, selection, film_id: Optional[str]):
        """Fertige Dateien per bestehendem Import in einen Film-Knoten (film_id None = neuer Film-Knoten),
        als ein Schritt. Höchstens ein Video, denn ein Film-Knoten hat ein Video."""
        if isinstance(selection, tasks.PrepareTask):
            selection = [selection]
        selection = [t for t in selection if t is not None and t.status == tasks.DONE]
        if not selection or sum(1 for t in selection if t.is_video) > 1:
            return
        outputs = [p for t in selection for p in t.outputs]
        missing = [p for p in outputs if not os.path.isfile(p)]
        if missing:
            self.status.emit(self.t("prep_missing_result", file=os.path.basename(missing[0])))
            return
        if film_id is None and not any(t.is_video for t in selection):
            self.status.emit(self.t("prep_take_audio_needs_film"))
            return
        # Video zuerst: ein neuer Film-Knoten entsteht aus dem Video, Ton kommt danach dazu
        outputs.sort(key=lambda p: 0 if p.lower().endswith((".264", ".mvc")) else 1)
        stack = self.controller.undo_stack
        stack.beginMacro(self.t("prep_take"))        # ein Klick = ein Schritt (Film anlegen + Dateien)
        try:
            result = self.importer.import_files(film_id, outputs)
        finally:
            stack.endMacro()
        film = self.controller.project.film(result) if result else None
        if film is not None:
            for task in selection:
                task.target_film_id = film.id
            self.status.emit(self.t("prep_taken", film=film.name))
            self._save()
        self.inspector.refresh()
        self._refresh_header()

    # --- Sprache --------------------------------------------------------------------------
    def retranslate(self):
        self.lbl_empty.setText(self.t("prep_empty"))
        self.list.setHeaderLabels([self.t("prep_col_source"), self.t("prep_col_kind"), self.t("prep_col_output"),
                                   self.t("prep_col_status")])
        self.act_add.setText(self.t("prep_add"))
        self.act_start.setText(self.t("prep_start"))
        self.act_start.setToolTip(self.t("prep_start_tip"))
        self.act_cancel.setText(self.t("prep_cancel"))
        self.act_cancel.setToolTip(self.t("prep_stop_tip"))
        self.act_cancel_task.setText(self.t("prep_cancel_task"))
        self.act_requeue.setText(self.t("prep_requeue"))
        self.act_remove.setText(self.t("prep_remove"))
        self.lbl_out_mode.setText(self.t("prep_out_mode"))
        self.lbl_disc.setText(self.t("prep_disc"))
        self.dock_inspector.setWindowTitle(self.t("prep_dock_inspector"))
        self.dock_log.setWindowTitle(self.t("prep_dock_log"))
        for dock in (self.dock_inspector, self.dock_log):
            dock.titleBarWidget().retranslate()
        self.inspector.retranslate()
        for task in self.tasks:
            self._update_row(task)
        self._refresh_header()
