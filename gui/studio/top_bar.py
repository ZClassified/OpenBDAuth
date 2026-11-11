# gui/studio/top_bar.py
"""
Obere Leiste (v1.29.0, nach dem Vorbild von PostFlow): flach, jede Art von Element mit eigenem Stil.

- Links die Marke: Logo, Name, Version. Ein Klick öffnet das Info-Fenster bei den Neuerungen.
- Arbeitsbereiche Vorbereiten | Disc | Brennen (ab v1.30) als Reiter mit Unterstreichung: Bereiche, keine Aktionen.
- Der Projektname mit Menü (Neu, Öffnen, Speichern …) statt drei Knöpfen; ● zeigt ungespeicherte Änderungen. Ab v1.30.2
  steht er in der Mitte der Leiste (StudioWindow._center_project): links die Bereiche, rechts die Aktionen.
- Werkzeuge ohne Rahmen; gefüllt ist nur die Hauptaktion (Disc erstellen bzw. Starten).

Wird es eng (z. B. 1920 Pixel bei 150 % Skalierung), kürzt StudioWindow._fit_toolbar zuerst den Projektnamen und
blendet dann den Schriftzug „OpenBDAuth“ aus; das Logo mit der Version bleibt.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel

from core.constants import APP_NAME, APP_VERSION
from gui.icons import app_icon

TOOLBAR_QSS = """
QToolBar#main_toolbar {
    background-color: #111113;
    border: none;
    border-bottom: 1px solid #27272A;
    padding: 6px 14px;
    spacing: 4px;
}
QToolBar#main_toolbar QToolButton {
    color: #D4D4D8;
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 7px 12px;
    font-size: 13px;
    font-weight: 500;
}
QToolBar#main_toolbar QToolButton:hover { background-color: #232327; color: #FAFAFA; }
QToolBar#main_toolbar QToolButton:pressed { background-color: #1B1B1E; }
QToolBar#main_toolbar QToolButton:disabled { color: #52525B; background: transparent; }
QToolBar#main_toolbar QToolButton::menu-indicator { image: none; }

QToolBar#main_toolbar QToolButton#page_tab {
    color: #A1A1AA; font-size: 14px; font-weight: 600; border-radius: 0;
    padding: 8px 6px 7px 6px; margin: 0 6px; border-bottom: 2px solid transparent;
}
QToolBar#main_toolbar QToolButton#page_tab:hover { background: transparent; color: #FAFAFA; }
QToolBar#main_toolbar QToolButton#page_tab:checked { color: #FBBF24; border-bottom: 2px solid #FBBF24; }

QToolBar#main_toolbar QToolButton#project_button { color: #FAFAFA; font-weight: 600; }
QToolBar#main_toolbar QToolButton#icon_action { padding: 6px 7px; }

QToolBar#main_toolbar QToolButton#primary_action {
    color: #18181B; background-color: #FBBF24; font-weight: 700; padding: 7px 20px;
}
QToolBar#main_toolbar QToolButton#primary_action:hover { background-color: #FCD34D; color: #18181B; }
QToolBar#main_toolbar QToolButton#primary_action:pressed { background-color: #F59E0B; }
QToolBar#main_toolbar QToolButton#primary_action:disabled { color: #71717A; background-color: #27272A; }

QToolBar#main_toolbar QToolButton#simulate_action { padding-right: 32px; }
QToolBar#main_toolbar QToolButton#simulate_action::menu-button {
    width: 22px; border: none; border-left: 1px solid #2E2E33;
    border-top-right-radius: 6px; border-bottom-right-radius: 6px;
}
QToolBar#main_toolbar QToolButton#simulate_action::menu-button:hover { background-color: #2E2E33; }
QToolBar#main_toolbar QToolButton#simulate_action::menu-arrow { width: 8px; height: 8px; }

QToolBar#main_toolbar QToolButton#status_badge {
    border: 1px solid transparent; border-radius: 13px; padding: 4px 12px; font-weight: 700;
}
QToolBar#main_toolbar QToolButton#status_badge[state="ok"] { color: #4ADE80; background-color: #0F2A1C; border-color: #166534; }
QToolBar#main_toolbar QToolButton#status_badge[state="warn"] { color: #FDE047; background-color: #2A230B; border-color: #854D0E; }
QToolBar#main_toolbar QToolButton#status_badge[state="error"] { color: #F87171; background-color: #2A1111; border-color: #991B1B; }

QToolBar#main_toolbar QToolButton#lang_button { color: #A1A1AA; font-weight: 600; padding: 7px 9px; }

QFrame#brand { background: transparent; border: none; border-radius: 6px; }
QFrame#brand:hover { background-color: #1B1B1E; }
QLabel#brand_name { color: #FBBF24; font-size: 16px; font-weight: 700; background: transparent; border: none; }
QLabel#brand_version {
    color: #71717A; font-size: 12px; background: transparent; border: none; padding-top: 3px;
}
QFrame#brand:hover QLabel#brand_version { color: #D4D4D8; }
"""


class BrandButton(QFrame):
    """Logo, Name und Version; ein Klick öffnet das Info-Fenster (Neuerungen)."""
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("brand")
        self.setCursor(Qt.PointingHandCursor)
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 2, 10, 2)
        row.setSpacing(8)
        self.logo = QLabel()
        self.logo.setPixmap(app_icon().pixmap(26, 26))
        self.logo.setStyleSheet("background: transparent;")
        self.name = QLabel(APP_NAME)
        self.name.setObjectName("brand_name")
        self.version = QLabel(f"v{APP_VERSION}")
        self.version.setObjectName("brand_version")
        row.addWidget(self.logo)
        row.addWidget(self.name)
        row.addWidget(self.version, 0, Qt.AlignVCenter)

    def set_compact(self, compact: bool):
        """Bei wenig Platz nur Logo und Version."""
        self.name.setVisible(not compact)

    @property
    def compact(self) -> bool:
        return self.name.isHidden()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)
