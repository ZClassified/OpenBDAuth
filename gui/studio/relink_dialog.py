# gui/studio/relink_dialog.py
"""
„Medien neu verknüpfen“ (v1.17.0): Liste der fehlenden Mediendateien. „Ordner durchsuchen …“ sucht sie im
gewählten Ordner samt Unterordnern (core/media_paths.py), „Datei wählen …“ setzt eine einzelne von Hand.
Eingetragen wird erst mit „Übernehmen“ – als ein Rückgängig-Schritt.
"""

import os
from typing import Dict, List, Optional, Tuple

from PySide6 import QtGui
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem, QHeaderView,
    QDialogButtonBox, QFileDialog, QApplication,
)

from core.media_paths import MediaRef, missing_media, media_label, index_folder, plan_relink
from core.translations import tr, ui_language

COLOR_MISSING = "#F87171"
COLOR_FOUND = "#4ADE80"
COLOR_AMBIGUOUS = "#FDE047"

Key = Tuple[str, str, Optional[str]]


class RelinkDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.refs: List[MediaRef] = missing_media(controller.project)
        self.paths: Dict[Key, str] = {}          # neu gefundene Pfade
        self.ambiguous: Dict[Key, List[str]] = {}
        self._start_dir = ""
        self.setWindowTitle(self.t("relink_title"))
        self.setMinimumSize(760, 360)
        layout = QVBoxLayout(self)

        self.lbl_info = QLabel()
        self.lbl_info.setWordWrap(True)
        layout.addWidget(self.lbl_info)

        self.tree = QTreeWidget()
        self.tree.setRootIsDecorated(False)
        self.tree.setHeaderLabels([self.t("relink_col_file"), self.t("relink_col_use"), self.t("relink_col_state")])
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)
        self.tree.itemDoubleClicked.connect(lambda _item, _col: self.pick_file())
        self.tree.itemSelectionChanged.connect(self._update_buttons)
        layout.addWidget(self.tree, stretch=1)

        row = QHBoxLayout()
        self.btn_folder = QPushButton(self.t("relink_search_folder"))
        self.btn_folder.clicked.connect(self.search_folder)
        self.btn_file = QPushButton(self.t("relink_pick_file"))
        self.btn_file.clicked.connect(self.pick_file)
        row.addWidget(self.btn_folder)
        row.addWidget(self.btn_file)
        row.addStretch(1)
        layout.addLayout(row)

        self.buttons = QDialogButtonBox()
        self.btn_apply = self.buttons.addButton(self.t("relink_apply"), QDialogButtonBox.AcceptRole)
        self.buttons.addButton(self.t("relink_later"), QDialogButtonBox.RejectRole)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        if self.refs:
            self._start_dir = os.path.dirname(self.refs[0].path)
        self._fill()

    def t(self, key: str, **kwargs) -> str:
        text = tr(key, ui_language())
        return text.format(**kwargs) if kwargs else text

    # --- Anzeige ------------------------------------------------------------------
    def _fill(self):
        self.tree.clear()
        project = self.controller.project
        for ref in self.refs:
            item = QTreeWidgetItem([os.path.basename(ref.path), media_label(project, ref), ""])
            item.setToolTip(0, ref.path)
            item.setData(0, Qt.UserRole, ref.key)
            self.tree.addTopLevelItem(item)
            self._show_state(item)
        self._update_buttons()

    def _show_state(self, item: QTreeWidgetItem):
        key = item.data(0, Qt.UserRole)
        if key in self.paths:
            text, color, tip = self.t("relink_found", path=self.paths[key]), COLOR_FOUND, self.paths[key]
        elif key in self.ambiguous:
            text, color = self.t("relink_ambiguous", n=len(self.ambiguous[key])), COLOR_AMBIGUOUS
            tip = "\n".join(self.ambiguous[key])
        else:
            text, color, tip = self.t("relink_missing"), COLOR_MISSING, ""
        item.setText(2, text)
        item.setToolTip(2, tip)
        item.setForeground(2, QtGui.QColor(color))

    def _update_buttons(self):
        open_count = sum(1 for r in self.refs if r.key not in self.paths)
        self.lbl_info.setText(self.t("relink_info", n=len(self.refs)) if open_count
                              else self.t("relink_all_found"))
        self.btn_apply.setEnabled(bool(self.paths))
        self.btn_file.setEnabled(bool(self.tree.selectedItems()))

    # --- Suchen -------------------------------------------------------------------
    def search_folder(self):
        folder = QFileDialog.getExistingDirectory(self, self.t("relink_search_folder"), self._start_dir)
        if folder:
            self.search_in(folder)

    def search_in(self, folder: str):
        """Sucht alle noch offenen Dateien in folder; schon gefundene bleiben, wie sie sind."""
        self._start_dir = folder
        pending = [r for r in self.refs if r.key not in self.paths]
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            index = index_folder(folder, progress=QApplication.processEvents)
        finally:
            QApplication.restoreOverrideCursor()
        result = plan_relink(pending, index)
        self.paths.update(result.found)
        for key in result.found:
            self.ambiguous.pop(key, None)
        self.ambiguous.update(result.ambiguous)
        self._refresh_states()

    def pick_file(self):
        items = self.tree.selectedItems()
        if not items:
            return
        key = items[0].data(0, Qt.UserRole)
        ref = next(r for r in self.refs if r.key == key)
        start = self.paths.get(key) or (self.ambiguous.get(key) or [""])[0] or self._start_dir
        name = os.path.basename(ref.path)
        path, _ = QFileDialog.getOpenFileName(self, self.t("relink_pick_title", name=name),
                                              os.path.dirname(start) if os.path.isfile(start) else start,
                                              f"{name} ({name});;{self.t('relink_all_files')} (*.*)")
        if path:
            self.set_path(key, path)

    def set_path(self, key: Key, path: str):
        self.paths[key] = path.replace("\\", "/")
        self.ambiguous.pop(key, None)
        self._start_dir = os.path.dirname(path)
        self._refresh_states()

    def _refresh_states(self):
        for i in range(self.tree.topLevelItemCount()):
            self._show_state(self.tree.topLevelItem(i))
        self._update_buttons()

    # --- Übernehmen ---------------------------------------------------------------
    def accept(self):
        self.controller.relink_media(dict(self.paths))
        super().accept()
