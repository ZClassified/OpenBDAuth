# gui/studio/widgets.py
"""Kleine, wiederverwendbare Bausteine für Inspektor und Viewer."""

from PySide6.QtCore import Qt, Signal, QEvent, QTimer
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox, QSizePolicy, QPushButton, QToolButton, QMenu, QWidget, QGridLayout, QWidgetAction,
    QComboBox,
)


class ElidedLabel(QLabel):
    """Einzeilige Beschriftung, die bei Platzmangel in der Mitte kürzt – Anfang und Dateiendung bleiben sichtbar."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setText(text)

    def setText(self, text: str):
        self._full = text or ""
        self._elide()

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def _elide(self):
        super().setText(self.fontMetrics().elidedText(self._full, Qt.ElideMiddle, max(0, self.width())))


class DockTitleBar(QWidget):
    """
    Titelleiste eines andockbaren Bereichs (v1.17.2). Angedockt: Knopf „Abkoppeln“, Doppelklick koppelt ab.
    Abgekoppelt: Knopf „Andocken“ oben rechts; Doppelklick füllt den Bildschirm bzw. stellt die Größe wieder her
    (wie bei Fenstern im Explorer). Ziehen an der Leiste verschiebt wie gewohnt (Qt).
    """

    def __init__(self, dock, texts, parent=None):
        super().__init__(parent or dock)
        self.dock = dock
        self._texts = texts                 # Funktion → (Abkoppeln, Andocken, Tooltip abgekoppelt)
        self._normal_geometry = None        # Größe vor „Bildschirm füllen“
        self.setStyleSheet("QWidget { background-color: #1C1C1F; }"
                           "QLabel { color: #A1A1AA; font-size: 11px; font-weight: bold; letter-spacing: 1px; }"
                           "QToolButton { color: #D4D4D8; background-color: #27272A; border: 1px solid #3F3F46;"
                           " border-radius: 4px; padding: 1px 8px; font-size: 11px; }"
                           "QToolButton:hover { background-color: #34343A; border-color: #FBBF24; }")
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 3, 4, 3)
        self.title = QLabel(dock.windowTitle())
        self.button = QToolButton()
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.clicked.connect(self.toggle_docked)
        row.addWidget(self.title, stretch=1)
        row.addWidget(self.button)
        dock.windowTitleChanged.connect(self.title.setText)
        dock.topLevelChanged.connect(self._on_top_level_changed)
        self.retranslate()

    def _on_top_level_changed(self, _floating: bool):
        self._normal_geometry = None
        self.retranslate()

    def retranslate(self):
        undock, dock_back, tip = self._texts()
        floating = self.dock.isFloating()
        self.button.setText(("⇲ " + dock_back) if floating else ("⧉ " + undock))
        self.setToolTip(tip if floating else "")

    def toggle_docked(self):
        self.dock.setFloating(not self.dock.isFloating())

    def is_filling_screen(self) -> bool:
        return self._normal_geometry is not None

    def toggle_fill_screen(self):
        """Abgekoppelt: Bildschirm (ohne Taskleiste) füllen bzw. vorherige Größe wiederherstellen."""
        if self._normal_geometry is not None:
            self.dock.setGeometry(self._normal_geometry)
            self._normal_geometry = None
            return
        screen = self.dock.screen()
        if screen is None:
            return
        self._normal_geometry = self.dock.geometry()
        self.dock.setGeometry(screen.availableGeometry())

    def mouseDoubleClickEvent(self, event):
        if event.button() != Qt.LeftButton:
            return super().mouseDoubleClickEvent(event)
        if self.dock.isFloating():
            self.toggle_fill_screen()
        else:
            self.toggle_docked()
        event.accept()


class DropFrame(QFrame):
    """Karte, auf die Dateien aus dem Explorer gezogen werden können."""
    files_dropped = Signal(list)

    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setAcceptDrops(True)
        # Beschriftungen ohne eigenen Hintergrund (sonst erben sie die Fensterfarbe)
        self._normal_style = "QLabel { background: transparent; }"
        self.setStyleSheet(self._normal_style)
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(14, 12, 14, 12)
        self.layout_.setSpacing(8)
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #A1A1AA; "
                                       "text-transform: uppercase; letter-spacing: 1px;")
        self.layout_.addWidget(self.title_label)

    def set_title(self, title: str):
        self.title_label.setText(title)

    @staticmethod
    def _files(event) -> list:
        mime = event.mimeData()
        return [u.toLocalFile() for u in mime.urls() if u.isLocalFile()] if mime.hasUrls() else []

    def dragEnterEvent(self, event):
        if self._files(event):
            self.setStyleSheet(self._normal_style + " QFrame#card { border: 1px solid #4ADE80; }")
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.setStyleSheet(self._normal_style)

    def dropEvent(self, event):
        self.setStyleSheet(self._normal_style)
        files = self._files(event)
        if files:
            event.acceptProposedAction()
            self.files_dropped.emit(files)


class ColorSwatchButton(QToolButton):
    """
    Farbfeld mit Auswahl: ein Klick zeigt die vorgegebenen Farben als Felder, darunter „Eigene Farbe …“
    (Farbdialog). color_chosen meldet die gewählte Farbe als „#RRGGBB“.
    Mit set_extra_provider kommen beim Öffnen weitere Abschnitte dazu (v1.14.4: „Zuletzt benutzt“,
    „Aus dem Hintergrund“), jeweils als [(Überschrift, Farben)].
    """
    color_chosen = Signal(str)

    def __init__(self, palette: list, custom_text: str = "Eigene Farbe …", parent=None):
        super().__init__(parent)
        self._color = palette[0] if palette else "#FFFFFF"
        self._palette = list(palette)
        self._extra_provider = None
        self.setFixedSize(34, 28)
        self.setPopupMode(QToolButton.InstantPopup)
        self.setCursor(Qt.PointingHandCursor)
        menu = QMenu(self)
        self.act_custom = menu.addAction(custom_text)     # Text setzt der Aufrufer ggf. später (Sprache)
        self.act_custom.triggered.connect(self._custom)
        self.setMenu(menu)
        self.swatches = []
        self._build_menu()
        menu.aboutToShow.connect(self._build_menu)
        self._update_style()

    def set_extra_provider(self, provider):
        """provider() → [(Überschrift, [„#RRGGBB“, …])]; leere Abschnitte werden ausgelassen."""
        self._extra_provider = provider

    def _swatch_grid(self, colors) -> QWidget:
        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(8, 4, 8, 4)
        grid.setSpacing(6)
        for i, color in enumerate(colors):
            swatch = QToolButton()
            swatch.setFixedSize(26, 26)
            swatch.setToolTip(color)
            swatch.setStyleSheet(f"QToolButton {{ background-color: {color}; border: 2px solid #18181B; border-radius: 5px; }}"
                                 f"QToolButton:hover {{ border: 2px solid #FAFAFA; }}")
            swatch.clicked.connect(lambda _c=False, col=color: self._choose(col))
            grid.addWidget(swatch, i // 4, i % 4)
            self.swatches.append(swatch)
        return grid_widget

    def _build_menu(self):
        menu = self.menu()
        for action in list(menu.actions()):
            if action is not self.act_custom:
                menu.removeAction(action)
                if isinstance(action, QWidgetAction):
                    action.deleteLater()
        self.swatches = []
        sections = [(title, colors) for title, colors in (self._extra_provider() if self._extra_provider else [])
                    if colors]
        sections.append(("", self._palette))
        for title, colors in sections:
            if title:
                label = QLabel(title)
                label.setStyleSheet("color: #A1A1AA; font-size: 11px; padding: 6px 10px 0 10px;")
                caption = QWidgetAction(menu)
                caption.setDefaultWidget(label)
                menu.insertAction(self.act_custom, caption)
            action = QWidgetAction(menu)
            action.setDefaultWidget(self._swatch_grid(colors))
            menu.insertAction(self.act_custom, action)
        menu.insertSeparator(self.act_custom)

    def set_color(self, color: str):
        if color and color != self._color:
            self._color = color
            self._update_style()

    def color(self) -> str:
        return self._color

    def _update_style(self):
        self.setStyleSheet(f"QToolButton {{ background-color: {self._color}; border: 2px solid #3F3F46;"
                           f" border-radius: 6px; }} QToolButton::menu-indicator {{ image: none; }}")

    def _choose(self, color: str):
        self.menu().hide()
        self.set_color(color)
        self.color_chosen.emit(color)

    def _custom(self):
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QColorDialog
        chosen = QColorDialog.getColor(QColor(self._color), self, self.act_custom.text().rstrip(" …"))
        if chosen.isValid():
            self._choose(chosen.name().upper())


SEGMENT_QSS = """
QPushButton {{ color: #D4D4D8; background-color: #202024; border: 1px solid #3F3F46; padding: 4px 14px;
               font-weight: 600; border-top-left-radius: {left}; border-bottom-left-radius: {left};
               border-top-right-radius: {right}; border-bottom-right-radius: {right}; }}
QPushButton:hover {{ background-color: #34343A; }}
QPushButton:checked {{ color: #FFFFFF; background-color: #3D3218; border-color: #FBBF24; }}
"""


class SegmentedSwitch(QWidget):
    """
    Zwei oder mehr nebeneinanderliegende Schaltflächen, genau eine ist aktiv (v1.14.5, z. B. Text | Form).
    Anders als eine Auswahlliste sieht man alle Möglichkeiten auf einen Blick. chosen meldet nur Klicks.
    """
    chosen = Signal(str)

    def __init__(self, values, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.buttons = {}
        last = len(values) - 1
        for i, value in enumerate(values):
            btn = QPushButton()
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.setStyleSheet(SEGMENT_QSS.format(left="8px" if i == 0 else "0px", right="8px" if i == last else "0px"))
            btn.clicked.connect(lambda _c=False, v=value: self.chosen.emit(v))
            layout.addWidget(btn)
            self.buttons[value] = btn

    def set_value(self, value):
        btn = self.buttons.get(value)
        if btn is not None and not btn.isChecked():
            btn.setChecked(True)

    def value(self):
        return next((v for v, b in self.buttons.items() if b.isChecked()), None)

    def clear(self):
        """Keine Schaltfläche aktiv (z. B. unterschiedliche Werte bei Mehrfachauswahl)."""
        for btn in self.buttons.values():
            btn.setAutoExclusive(False)
            btn.setChecked(False)
            btn.setAutoExclusive(True)

    def set_texts(self, texts: dict, tooltips: dict = None):
        for value, btn in self.buttons.items():
            btn.setText(texts.get(value, ""))
            btn.setToolTip((tooltips or {}).get(value, ""))


class DragSpinBox(QSpinBox):
    """
    Zahlenfeld (v1.14.7): eintippen wie gewohnt oder mit gedrückter Maustaste ziehen – nach rechts bzw. oben
    größer, nach links bzw. unten kleiner (1 pro 2 px). committed meldet den Wert nach Enter, Fokuswechsel oder
    dem Loslassen nach dem Ziehen; ein einfacher Klick markiert die ganze Zahl (Tippen ersetzt sie).
    """
    committed = Signal(int)
    DRAG_START = 4          # px, bevor aus einem Klick ein Ziehen wird
    PX_PER_STEP = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self._press = None
        self._start_value = 0
        self._dragging = False
        self.lineEdit().installEventFilter(self)
        self.lineEdit().setCursor(Qt.SizeHorCursor)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)   # Breite aus der Schrift, nie abgeschnitten
        self.editingFinished.connect(lambda: self.committed.emit(self.value()))

    def stepBy(self, steps: int):
        """
        Pfeile, Mausrad, Pfeiltasten (v1.14.9): in Schritten von singleStep auf glatte Werte (37 → 40 bzw. 35),
        sofort übernommen.
        """
        step = max(1, self.singleStep())
        value = self.value()
        base = value // step if steps > 0 else -(-value // step)
        self.setValue((base + steps) * step)
        self.committed.emit(self.value())

    def eventFilter(self, obj, event):
        if obj is self.lineEdit() and self.isEnabled():
            kind = event.type()
            if kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._press = event.globalPosition()
                self._start_value = self.value()
                self._dragging = False
            elif kind == QEvent.MouseMove and self._press is not None and event.buttons() & Qt.LeftButton:
                moved = event.globalPosition() - self._press
                delta = moved.x() - moved.y()
                if not self._dragging and abs(delta) >= self.DRAG_START:
                    self._dragging = True
                if self._dragging:
                    self.setValue(self._start_value + int(delta / self.PX_PER_STEP))
                    return True
            elif kind == QEvent.MouseButtonRelease and self._press is not None:
                self._press = None
                if self._dragging:
                    self._dragging = False
                    self.committed.emit(self.value())
                    return True
                # einfacher Klick (v1.14.8): ganze Zahl markieren, damit Tippen sie ersetzt
                QTimer.singleShot(0, self.selectAll)
        return super().eventFilter(obj, event)


def small_button(text: str, tooltip: str = "", danger: bool = False) -> QPushButton:
    btn = QPushButton(text)
    btn.setFixedSize(28, 26)
    btn.setToolTip(tooltip)
    if danger:
        btn.setStyleSheet("QPushButton { background-color: #7F1D1D; color: #FCA5A5; border: 1px solid #991B1B;"
                          " border-radius: 4px; padding: 0px; }"
                          "QPushButton:hover { background-color: #991B1B; color: #FFFFFF; }")
    else:
        btn.setStyleSheet("QPushButton { padding: 0px; }")
    return btn


def hint_label(text: str = "") -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet("color: #71717A; font-size: 11px;")
    return lbl


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget() is not None:
            item.widget().deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())


# Inspektor-Bausteine (bis v1.21 in gui/studio/inspector.py; ab v1.22 auch im Arbeitsbereich Vorbereiten)

class Section(QFrame):
    """Einklappbarer Abschnitt mit Kopfzeile (▾ Titel); der Zustand gilt pro Abschnitt für die ganze Sitzung."""

    collapsed_state: dict = {}

    def __init__(self, key: str, collapsed: bool = False):
        super().__init__()
        self.key = key
        self.setObjectName("inspector_section")
        self.setStyleSheet("QFrame#inspector_section { background-color: #202024; border: 1px solid #34343A; "
                           "border-radius: 8px; } QWidget#section_body, QWidget#section_row, "
                           "QFrame#inspector_section QLabel { background: transparent; }")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 6, 10, 8)
        outer.setSpacing(6)
        self.header = QPushButton()
        self.header.setFlat(True)
        self.header.setCursor(Qt.PointingHandCursor)
        self.header.setStyleSheet("QPushButton { text-align: left; color: #E4E4E7; font-weight: bold; border: none; "
                                  "padding: 2px 0; background: transparent; }")
        self.header.clicked.connect(self.toggle)
        outer.addWidget(self.header)
        self.body = QWidget()
        self.body.setObjectName("section_body")
        self.layout_ = QVBoxLayout(self.body)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.layout_.setSpacing(6)
        outer.addWidget(self.body)
        self._title = ""
        Section.collapsed_state.setdefault(key, collapsed)
        self._apply()

    @property
    def collapsed(self) -> bool:
        return Section.collapsed_state[self.key]

    def set_title(self, title: str):
        self._title = title
        self._apply()

    def toggle(self):
        Section.collapsed_state[self.key] = not self.collapsed
        self._apply()
        self.updateGeometry()

    def _apply(self):
        self.body.setVisible(not self.collapsed)
        self.header.setText(("▸ " if self.collapsed else "▾ ") + self._title.replace("&", "&&"))


def fill_combo(combo: QComboBox, entries, current):
    """Einträge [(Daten, Text)] setzen, ohne Signale auszulösen; current auswählen (sonst den ersten)."""
    combo.blockSignals(True)
    if [(combo.itemData(i), combo.itemText(i)) for i in range(combo.count())] != list(entries):
        combo.clear()
        for data, text in entries:
            combo.addItem(text, data)
    index = combo.findData(current if current is not None else "")
    combo.setCurrentIndex(index if index >= 0 else 0)
    combo.blockSignals(False)
