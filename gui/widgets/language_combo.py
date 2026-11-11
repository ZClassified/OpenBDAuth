# gui/widgets/language_combo.py
"""
Sprachauswahl mit Vervollständigung per Teilstring (MatchContains).
Ungültige Eingaben springen auf den letzten gültigen ISO-639-2-Code zurück,
damit tsMuxeR nur gültige Codes erhält.
"""

from PySide6 import QtCore, QtWidgets, QtGui
from core.constants import get_language_display_items, resolve_language_code
from core.translations import tr


class LanguageComboBox(QtWidgets.QComboBox):
    def __init__(self, parent=None, default_code: str = "deu"):
        super().__init__(parent)
        self._last_valid_index: int = 0
        self._default_code: str = default_code

        self._init_ui()
        self._populate_items()
        self.set_selected_code(default_code)

    def _init_ui(self):
        self.setEditable(True)
        self.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        self.setMinimumWidth(170)

        # Style für LineEdit im ComboBox
        line_edit = self.lineEdit()
        if line_edit:
            line_edit.setPlaceholderText(tr("lang_search_placeholder"))
            line_edit.editingFinished.connect(self._on_editing_finished)

        # QCompleter konfigurieren (Substring-Suche: MatchContains)
        completer = self.completer()
        if completer:
            completer.setFilterMode(QtCore.Qt.MatchFlag.MatchContains)
            completer.setCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)
            completer.setCompletionMode(QtWidgets.QCompleter.CompletionMode.PopupCompletion)
            popup = completer.popup()
            if popup:
                popup.setStyleSheet("""
                    QListView {
                        background-color: #202024;
                        border: 1px solid #FBBF24;
                        border-radius: 6px;
                        color: #FAFAFA;
                        padding: 4px;
                        selection-background-color: #FBBF24;
                        selection-color: #18181B;
                        font-size: 13px;
                    }
                    QListView::item {
                        padding: 6px 10px;
                        min-height: 24px;
                        border-radius: 4px;
                    }
                    QListView::item:hover {
                        background-color: #27272A;
                        color: #FBBF24;
                    }
                """)

        self.currentIndexChanged.connect(self._on_index_changed)

    def _populate_items(self):
        items = get_language_display_items()
        model = self.model()

        for idx, (label, code) in enumerate(items):
            self.addItem(label, userData=code)
            if code == "sep":
                # Trenner deaktivieren
                if isinstance(model, QtGui.QStandardItemModel):
                    item = model.item(idx)
                    if item:
                        item.setEnabled(False)
                        item.setSelectable(False)

    def _on_index_changed(self, index: int):
        if index >= 0 and self.itemData(index) != "sep":
            self._last_valid_index = index

    def _on_editing_finished(self):
        """Auto-Snap-Back bei fehlerhafter Eingabe oder Fokusverlust."""
        text = self.currentText().strip()
        if not text or "─────" in text:
            self.setCurrentIndex(self._last_valid_index)
            return

        code = resolve_language_code(text)
        if code and code != "und":
            # Suche passenden Eintrag
            for i in range(self.count()):
                if self.itemData(i) == code:
                    self.setCurrentIndex(i)
                    self._last_valid_index = i
                    return

        # Falls keine eindeutige Sprache gematcht werden konnte: Revert
        self.setCurrentIndex(self._last_valid_index)

    def get_selected_lang_code(self) -> str:
        """Gibt den bereinigten 3-Buchstaben-Code nach ISO 639-2 zurück."""
        idx = self.currentIndex()
        if idx >= 0:
            code = self.itemData(idx)
            if code and code != "sep":
                return code
        return resolve_language_code(self.currentText())

    def set_selected_code(self, code: str) -> bool:
        """Wählt einen Eintrag anhand des 3-Buchstaben ISO-Codes aus."""
        target = str(code).strip().lower()
        for i in range(self.count()):
            if self.itemData(i) == target:
                self.setCurrentIndex(i)
                self._last_valid_index = i
                return True
        return False
