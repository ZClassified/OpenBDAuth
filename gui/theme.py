# gui/theme.py
"""
Design-System für OpenBDAuth (PySide6 / Qt 6), ab v1.19.0:
Graphit-Grau, Amber als Akzent, Weiß. Auf Amber steht dunkle Schrift.

Farbtabelle (alle Oberflächen benutzen nur diese Werte; Ampelfarben und Disc-Farben ausgenommen):
  #111113 Leinwand, Protokoll, obere Leiste    #18181B Grund        #1C1C1F gedrückt/gesperrt
  #202024 Flächen, Karten, Knöpfe               #27272A Felder       #2E2E33 feine Rahmen
  #34343A Hover                                 #3F3F46 Rahmen       #52525B gesperrte Schrift
  #71717A schwache Schrift   #A1A1AA gedämpfte Schrift   #D4D4D8 / #E4E4E7 Schrift   #FAFAFA hell
  #FBBF24 Akzent (Auswahl, Fokus, Hauptknopf)   #FCD34D Akzent hell  #F59E0B / #D97706 Akzent gedrückt
  #3D3218 Akzent dunkel (eingerastete Umschalter)                    #FDE047 Warnung (heller als der Akzent)
"""

DARK_THEME_QSS = """
/* Globale Stile */
QWidget {
    background-color: #18181B;
    color: #E4E4E7;
    font-family: "Segoe UI", -apple-system, Roboto, Helvetica, Arial, sans-serif;
    font-size: 13px;
    selection-background-color: #FBBF24;
    selection-color: #18181B;
}

/* Hauptfenster & Frames */
QMainWindow {
    background-color: #18181B;
}

QFrame#sidebar {
    background-color: #202024;
    border-right: 1px solid #2E2E33;
}

QFrame#card {
    background-color: #202024;
    border: 1px solid #2E2E33;
    border-radius: 8px;
}

QScrollArea {
    background-color: transparent;
    border: none;
}

QScrollArea > QWidget > QWidget {
    background-color: transparent;
}

/* Überschriften & Labels */
QLabel#h1 {
    font-size: 20px;
    font-weight: bold;
    color: #FAFAFA;
}

QLabel#h2 {
    font-size: 16px;
    font-weight: bold;
    color: #FAFAFA;
}

QLabel#subtitle {
    font-size: 12px;
    color: #A1A1AA;
}

QLabel#badge_success {
    color: #4ADE80;
    font-weight: bold;
    font-size: 11px;
}

QLabel#badge_gray {
    color: #71717A;
    font-size: 11px;
}

/* Eingabefelder */
QLineEdit {
    background-color: #27272A;
    border: 1px solid #3F3F46;
    border-radius: 6px;
    padding: 6px 10px;
    color: #FAFAFA;
    font-size: 13px;
}

QLineEdit:focus {
    border: 1px solid #FBBF24;
    background-color: #27272A;
}

QLineEdit:disabled {
    background-color: #1C1C1F;
    color: #52525B;
    border: 1px solid #2E2E33;
}

/* Dropdown / ComboBox */
QComboBox {
    background-color: #27272A;
    border: 1px solid #3F3F46;
    border-radius: 6px;
    padding: 5px 10px;
    color: #FAFAFA;
    min-width: 100px;
}

QComboBox:hover {
    border: 1px solid #FBBF24;
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 25px;
    border-left-width: 0px;
    border-top-right-radius: 6px;
    border-bottom-right-radius: 6px;
}

QComboBox QAbstractItemView {
    background-color: #27272A;
    border: 1px solid #3F3F46;
    border-radius: 6px;
    selection-background-color: #FBBF24;
    selection-color: #18181B;
    padding: 4px;
    color: #E4E4E7;
}

/* Buttons */
QPushButton {
    background-color: #27272A;
    border: 1px solid #3F3F46;
    border-radius: 6px;
    padding: 7px 16px;
    color: #FAFAFA;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #34343A;
    border-color: #52525B;
}

QPushButton:pressed {
    background-color: #1C1C1F;
}

QPushButton:disabled {
    background-color: #1C1C1F;
    border-color: #2E2E33;
    color: #52525B;
}

/* Primärer Action-Button (Amber) */
QPushButton#primary_btn {
    background-color: #FBBF24;
    border: 1px solid #FBBF24;
    color: #18181B;
    font-weight: bold;
    padding: 8px 20px;
}

QPushButton#primary_btn:hover {
    background-color: #FCD34D;
    border-color: #FCD34D;
}

QPushButton#primary_btn:pressed {
    background-color: #D97706;
}

QPushButton#primary_btn:disabled {
    background-color: #27272A;
    border-color: #3F3F46;
    color: #71717A;
}

/* Gefahr-Button (Löschen) */
QPushButton#danger_btn {
    background-color: #3F1D24;
    border: 1px solid #7F1D1D;
    color: #FCA5A5;
    padding: 4px 10px;
    font-size: 11px;
}

QPushButton#danger_btn:hover {
    background-color: #991B1B;
    color: #FFFFFF;
}

/* Sidebar Navigations-Buttons */
QPushButton#nav_btn {
    background-color: transparent;
    border: none;
    border-radius: 6px;
    padding: 10px 14px;
    text-align: left;
    color: #A1A1AA;
    font-size: 13px;
    font-weight: 600;
}

QPushButton#nav_btn:hover {
    background-color: #2E2E33;
    color: #FAFAFA;
}

QPushButton#nav_btn[active="true"] {
    background-color: #FBBF24;
    color: #18181B;
    font-weight: bold;
}

/* Checkboxen */
QCheckBox {
    spacing: 8px;
    background: transparent;   /* v1.30.1: kein dunkler Streifen auf Karten */
    color: #E4E4E7;
    font-size: 13px;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 1px solid #3F3F46;
    border-radius: 4px;
    background-color: #27272A;
}

QCheckBox::indicator:hover {
    border-color: #FBBF24;
}

QCheckBox::indicator:checked {
    background-color: #FBBF24;
    border-color: #FBBF24;
    image: none;
}

/* Radio Buttons */
QRadioButton {
    spacing: 8px;
    background: transparent;   /* v1.30.1: kein dunkler Streifen auf Karten */
    color: #E4E4E7;
    font-size: 13px;
}

QRadioButton::indicator {
    width: 18px;
    height: 18px;
    border: 2px solid #52525B;
    border-radius: 9px;
    background-color: #27272A;
}

QRadioButton::indicator:hover {
    border-color: #FBBF24;
}

QRadioButton::indicator:checked {
    border: 5px solid #FBBF24;
    background-color: #FAFAFA;
}

/* Tabellen */
QTableWidget {
    background-color: #202024;
    border: 1px solid #2E2E33;
    border-radius: 6px;
    gridline-color: #2E2E33;
    color: #E4E4E7;
}

QHeaderView::section {
    background-color: #27272A;
    color: #A1A1AA;
    padding: 6px 10px;
    border: none;
    border-bottom: 1px solid #3F3F46;
    font-weight: bold;
    font-size: 11px;
}

/* Fortschrittsbalken */
QProgressBar {
    background-color: #202024;
    border: 1px solid #2E2E33;
    border-radius: 5px;
    height: 10px;
    text-align: center;
    color: #E4E4E7;
    font-size: 10px;
}

QProgressBar::chunk {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FBBF24, stop:1 #FCD34D);
    border-radius: 4px;
}

/* Log-Textfeld */
QTextEdit#log_area {
    background-color: #111113;
    border: 1px solid #2E2E33;
    border-radius: 6px;
    padding: 8px;
    color: #D4D4D8;
    font-family: "Consolas", "Courier New", monospace;
    font-size: 12px;
}

/* Scrollbars */
QScrollBar:vertical {
    background: #18181B;
    width: 8px;
    margin: 0px;
}

QScrollBar::handle:vertical {
    background: #3F3F46;
    min-height: 20px;
    border-radius: 4px;
}

QScrollBar::handle:vertical:hover {
    background: #FBBF24;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

/* QGraphicsView (Menü-Canvas) */
QGraphicsView#menu_canvas {
    background-color: #111113;
    border: 1px solid #2E2E33;
    border-radius: 8px;
}
"""

# ----------------------------------------------------------------------------------------------------------------
# Plattformgleiche Darstellung (v1.30.1)
#
# - Schriften im Code in Pixeln statt Punkten: macOS rechnet mit 72 dpi, Windows mit 96 – dieselbe Punktgröße war auf
#   dem Mac ein Viertel kleiner. ui_font(9) ist unter Windows genau so groß wie bisher QFont(…, 9).
# - Zahlenfelder (QSpinBox, QDoubleSpinBox) im Stil der übrigen Eingabefelder, mit eigenen Pfeilen; sonst zeichnete
#   sie der native Stil (auf dem Mac weiße Rahmen, gequetschte Pfeile).
# - macOS: Qt-Stil „Fusion“ statt des nativen Stils, der das dunkle Theme nur teilweise übernimmt.
# ----------------------------------------------------------------------------------------------------------------

PT_TO_PX = 4 / 3          # 1 pt bei 96 dpi
ARROW_COLOR, ARROW_COLOR_DISABLED = "#A1A1AA", "#52525B"
ARROW_FILES = "spin_{kind}_{state}_v1.png"

SPINBOX_QSS = """
QAbstractSpinBox {{
    background-color: #27272A;
    border: 1px solid #3F3F46;
    border-radius: 6px;
    padding: 4px 22px 4px 8px;
    color: #FAFAFA;
    font-size: 13px;
    selection-background-color: #FBBF24;
    selection-color: #18181B;
}}
QAbstractSpinBox:hover {{ border-color: #52525B; }}
QAbstractSpinBox:focus {{ border-color: #FBBF24; }}
QAbstractSpinBox:disabled {{ background-color: #1C1C1F; color: #52525B; border-color: #2E2E33; }}
QAbstractSpinBox QLineEdit {{
    background: transparent; border: none; padding: 0; margin: 0; color: #FAFAFA;
    selection-background-color: #FBBF24; selection-color: #18181B;
}}
QAbstractSpinBox QLineEdit:disabled {{ color: #52525B; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
    subcontrol-origin: border;
    width: 18px;
    border: none;
    border-left: 1px solid #3F3F46;
    background: transparent;
}}
QAbstractSpinBox::up-button {{ subcontrol-position: top right; border-top-right-radius: 6px; }}
QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; border-bottom-right-radius: 6px; }}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background-color: #34343A; }}
QAbstractSpinBox::up-button:pressed, QAbstractSpinBox::down-button:pressed {{ background-color: #1C1C1F; }}
QAbstractSpinBox::up-button:disabled, QAbstractSpinBox::down-button:disabled {{ border-left-color: #2E2E33; }}
QAbstractSpinBox::up-arrow {{ image: url("{up}"); width: 8px; height: 5px; }}
QAbstractSpinBox::down-arrow {{ image: url("{down}"); width: 8px; height: 5px; }}
QAbstractSpinBox::up-arrow:disabled, QAbstractSpinBox::up-arrow:off {{ image: url("{up_off}"); }}
QAbstractSpinBox::down-arrow:disabled, QAbstractSpinBox::down-arrow:off {{ image: url("{down_off}"); }}
"""


def ui_font(points: float, bold: bool = False, italic: bool = False):
    """Schrift der Oberfläche in Pixeln (points × 4/3): auf allen Systemen gleich groß wie unter Windows."""
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication
    font = QFont(QApplication.font())
    font.setPixelSize(max(1, round(points * PT_TO_PX)))
    font.setBold(bold)
    font.setItalic(italic)
    return font


def mono_font(points: float):
    """Feste Breite (Protokolle) in Pixeln; Consolas gibt es nur unter Windows."""
    from PySide6.QtGui import QFontDatabase
    font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
    font.setPixelSize(max(1, round(points * PT_TO_PX)))
    return font


def _arrow_pixmap(up: bool, color: str):
    """Pfeil 8 × 5 px, doppelt so groß gezeichnet (scharf auf Retina-/HiDPI-Bildschirmen)."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap
    pixmap = QPixmap(16, 10)
    pixmap.fill(Qt.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    path = QPainterPath()
    if up:
        path.moveTo(QPointF(8, 1)); path.lineTo(QPointF(15, 9)); path.lineTo(QPointF(1, 9))
    else:
        path.moveTo(QPointF(1, 1)); path.lineTo(QPointF(15, 1)); path.lineTo(QPointF(8, 9))
    path.closeSubpath()
    p.drawPath(path)
    p.end()
    return pixmap


def _arrow_files(folder: str) -> dict:
    """Pfeil-Grafiken für das Stylesheet (Qt lädt Bilder im Stylesheet nur aus Dateien oder Ressourcen)."""
    import os
    os.makedirs(folder, exist_ok=True)
    files = {}
    for kind, up in (("up", True), ("down", False)):
        for state, color in (("on", ARROW_COLOR), ("off", ARROW_COLOR_DISABLED)):
            path = os.path.join(folder, ARROW_FILES.format(kind=kind, state=state))
            if not os.path.isfile(path):
                _arrow_pixmap(up, color).save(path, "PNG")
            key = kind if state == "on" else f"{kind}_off"
            files[key] = path.replace("\\", "/")
    return files


def app_stylesheet(cache_dir: str = "") -> str:
    """Komplettes Stylesheet: Theme plus Zahlenfelder (Pfeile im Cache-Ordner, braucht eine QApplication)."""
    import os
    import tempfile
    if not cache_dir:
        from PySide6.QtCore import QStandardPaths
        base = QStandardPaths.writableLocation(QStandardPaths.CacheLocation) or tempfile.gettempdir()
        cache_dir = os.path.join(base, "OpenBDAuth", "ui")
    try:
        files = _arrow_files(cache_dir)
    except OSError:
        files = _arrow_files(os.path.join(tempfile.gettempdir(), "openbdauth_ui"))
    return DARK_THEME_QSS + SPINBOX_QSS.format(**files)


PALETTE = (("Window", "#18181B"), ("Base", "#27272A"), ("AlternateBase", "#202024"), ("Button", "#202024"),
           ("Text", "#FAFAFA"), ("WindowText", "#E4E4E7"), ("ButtonText", "#E4E4E7"), ("BrightText", "#FAFAFA"),
           ("Highlight", "#FBBF24"), ("HighlightedText", "#18181B"), ("ToolTipBase", "#27272A"),
           ("ToolTipText", "#E4E4E7"), ("PlaceholderText", "#71717A"), ("Light", "#3F3F46"),
           ("Midlight", "#34343A"), ("Mid", "#2E2E33"), ("Dark", "#111113"), ("Shadow", "#000000"))


def dark_palette():
    """Palette in den Farben des Themes – für alles, was der Stil (Fusion) ohne Stylesheet-Regel zeichnet."""
    from PySide6.QtGui import QColor, QPalette
    palette = QPalette()
    for role, color in PALETTE:
        palette.setColor(getattr(QPalette.ColorRole, role), QColor(color))
    for role in ("Text", "WindowText", "ButtonText"):
        palette.setColor(QPalette.Disabled, getattr(QPalette.ColorRole, role), QColor("#52525B"))
    return palette


def apply_theme(app):
    """Stil und Stylesheet für das Programm (main.py, Werkzeuge mit Oberfläche)."""
    import sys
    if sys.platform == "darwin":
        app.setStyle("Fusion")       # der native macOS-Stil übernimmt das dunkle Theme nur teilweise
        app.setPalette(dark_palette())
    app.setStyleSheet(app_stylesheet())
