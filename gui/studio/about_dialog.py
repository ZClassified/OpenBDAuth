# gui/studio/about_dialog.py
"""
Info-Fenster (v1.19.0): Überblick, Neuerungen (v1.28.0), Tastenkürzel und die Lizenzen der
Komponenten, die OpenBDAuth benutzt oder aufruft. Geöffnet über F1 (Überblick) oder die Marke links in der oberen
Leiste (Neuerungen, seit v1.29.0; bis dahin über „ⓘ“).
Die Texte stehen hier in beiden Sprachen statt in core/translations.py: Sie gehören nur zu diesem Fenster.
Die Neuerungen kommen aus core/release_notes.py.
"""

import html
from typing import List, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QWidget, QScrollArea, QFrame, QButtonGroup, QTextBrowser,
)

from core.constants import APP_NAME, APP_VERSION
from core.release_notes import RELEASES, date_text
from gui.icons import app_icon

TAB_OVERVIEW, TAB_NEWS, TAB_SHORTCUTS, TAB_LICENSES = range(4)

ABOUT_QSS = """
QDialog#about { background-color: #18181B; }
QFrame#about_header { background-color: #202024; border-bottom: 1px solid #2E2E33; }
QFrame#about_tabs { background-color: #1C1C1F; border-bottom: 1px solid #2E2E33; }
QFrame#about_footer { background-color: #1C1C1F; border-top: 1px solid #2E2E33; }
QLabel#about_title { font-size: 17px; font-weight: 600; color: #FAFAFA; background: transparent; }
QLabel#about_version, QLabel#about_subtitle { color: #A1A1AA; background: transparent; }
QLabel#about_section { color: #A1A1AA; font-size: 11px; font-weight: 600; letter-spacing: 1px; }
QPushButton#about_tab {
    background: transparent; border: none; border-bottom: 2px solid transparent; border-radius: 0;
    color: #A1A1AA; padding: 10px 12px; font-weight: 500;
}
QPushButton#about_tab:hover { color: #FAFAFA; background: transparent; }
QPushButton#about_tab:checked { color: #FAFAFA; border-bottom: 2px solid #FBBF24; }
QTextBrowser#news { background: transparent; color: #D4D4D8; border: none; }
QTableWidget#about_table {
    background: transparent; border: none; gridline-color: transparent; color: #D4D4D8;
}
QTableWidget#about_table::item { border-bottom: 1px solid #27272A; padding: 6px 8px 6px 0; }
QTableWidget#about_table QHeaderView::section {
    background: transparent; color: #A1A1AA; border: none; border-bottom: 1px solid #2E2E33;
    padding: 4px 8px 6px 0; font-size: 11px; font-weight: 600;
}
"""


def overview_text(de: bool) -> str:
    return ("OpenBDAuth erstellt Blu-ray-Discs mit Menüs, in 2D und 3D. Filme und Menüs sind Knoten, die Verbindungen "
            "zwischen ihnen sind die Sprünge auf der Disc. Der Export schreibt eine fertige Disc als ISO oder als "
            "BDMV-Ordner."
            if de else
            "OpenBDAuth creates Blu-ray discs with menus, in 2D and 3D. Films and menus are nodes, the connections "
            "between them are the jumps on the disc. The export writes a finished disc as an ISO or a BDMV folder.")


def areas(de: bool) -> List[Tuple[str, str]]:
    if de:
        return [
            ("Node-Ansicht", "Aufbau der Disc: Start, Filme, Menüs und wohin jeder Button und jedes Filmende führt."),
            ("Viewer", "Gestalten: Buttons auf das Hintergrundbild legen. Fernbedienung: Menü wie auf dem Player "
                       "durchgehen."),
            ("Inspektor", "Einstellungen des ausgewählten Films, Menüs oder Buttons."),
            ("Disc simulieren", "Spielt die Disc ohne Brennen durch und prüft jeden Button und jedes Filmende."),
            ("Disc erstellen", "Prüfung, dann Export als ISO oder BDMV-Ordner."),
        ]
    return [
        ("Node view", "Structure of the disc: start, films, menus and where each button and each film end leads."),
        ("Viewer", "Design: place buttons on the background picture. Remote: step through the menu as on the player."),
        ("Inspector", "Settings of the selected film, menu or button."),
        ("Simulate disc", "Plays the disc without burning and checks every button and every film end."),
        ("Create disc", "Checks, then exports as an ISO or a BDMV folder."),
    ]


def shortcut_groups(de: bool) -> List[Tuple[str, List[Tuple[str, str]]]]:
    """Gegen die Tasten- und Maus-Handler geprüft (main_window, node_editor/view, studio/viewer, simulator)."""
    ctrl, shift = ("Strg", "Umschalt") if de else ("Ctrl", "Shift")
    if de:
        return [
            ("Projekt", [
                (f"{ctrl} + N / O / S", "Neu, Öffnen, Speichern"),
                (f"{ctrl} + {shift} + S", "Speichern unter"),
                (f"{ctrl} + Z  ·  {ctrl} + Y", "Rückgängig, Wiederholen"),
                ("F1", "Dieses Fenster"),
            ]),
            ("Node-Ansicht", [
                ("Mausrad", "Zoomen"),
                ("Mittlere Maustaste  ·  Leertaste + Ziehen", "Ansicht verschieben"),
                ("F", "Alles anzeigen"),
                (f"{ctrl} + G", "Rahmen um die Auswahl"),
                ("Entf", "Auswahl löschen"),
                (f"{ctrl} / {shift} + Klick", "Mehrere auswählen"),
            ]),
            ("Viewer – Gestalten", [
                ("Pfeiltasten", "Auswahl um 1 Pixel verschieben"),
                (f"{shift} + Pfeiltasten", "Auswahl um 10 Pixel verschieben"),
                (f"{ctrl} + D", "Nächster Button im gleichen Abstand, Ziel zählt weiter"),
                ("Entf", "Ausgewählte Buttons entfernen"),
                ("Esc", "Auswahl aufheben, Werkzeug abbrechen"),
                (f"{ctrl} / {shift} + Klick", "Mehrere auswählen"),
                ("Alt beim Ziehen", "Ohne Einrasten"),
                ("Alt / " + shift + " an einer Ecke", "Größe symmetrisch / im gleichen Seitenverhältnis"),
            ]),
            ("Viewer – Fernbedienung", [
                ("Pfeiltasten", "Auswahl wie auf der Fernbedienung"),
                ("Enter  ·  Leertaste", "Button drücken"),
            ]),
            ("Disc simulieren", [
                ("Pfeiltasten  ·  Enter", "Auswahl, Button drücken"),
                ("T", "Top Menu"),
                ("A  ·  U", "Nächste Tonspur, nächster Untertitel"),
                ("Bild ↑  ·  Bild ↓", "Voriges, nächstes Kapitel"),
                ("E", "Zum Filmende"),
            ]),
        ]
    return [
        ("Project", [
            (f"{ctrl} + N / O / S", "New, open, save"),
            (f"{ctrl} + {shift} + S", "Save as"),
            (f"{ctrl} + Z  ·  {ctrl} + Y", "Undo, redo"),
            ("F1", "This window"),
        ]),
        ("Node view", [
            ("Mouse wheel", "Zoom"),
            ("Middle mouse  ·  Space + drag", "Pan the view"),
            ("F", "Show everything"),
            (f"{ctrl} + G", "Frame around the selection"),
            ("Del", "Delete the selection"),
            (f"{ctrl} / {shift} + click", "Select several"),
        ]),
        ("Viewer – Design", [
            ("Arrow keys", "Move the selection by 1 pixel"),
            (f"{shift} + arrow keys", "Move the selection by 10 pixels"),
            (f"{ctrl} + D", "Next button at the same distance, target counts up"),
            ("Del", "Remove the selected buttons"),
            ("Esc", "Clear the selection, cancel a tool"),
            (f"{ctrl} / {shift} + click", "Select several"),
            ("Alt while dragging", "No snapping"),
            ("Alt / " + shift + " on a corner", "Resize symmetrically / keep the aspect ratio"),
        ]),
        ("Viewer – Remote", [
            ("Arrow keys", "Selection as on the remote"),
            ("Enter  ·  Space", "Press the button"),
        ]),
        ("Simulate disc", [
            ("Arrow keys  ·  Enter", "Selection, press the button"),
            ("T", "Top Menu"),
            ("A  ·  U", "Next audio track, next subtitle"),
            ("Page ↑  ·  Page ↓", "Previous, next chapter"),
            ("E", "Jump to the end of the film"),
        ]),
    ]


def components(de: bool) -> List[Tuple[str, str, str, str]]:
    """(Komponente, Verwendung, Lizenz, Rechteinhaber) – alles, was OpenBDAuth einbindet oder aufruft."""
    return [
        ("Qt / PySide6", "Oberfläche" if de else "User interface", "LGPL-3.0-only", "© The Qt Company Ltd."),
        ("Pillow", "Bilder, Button-Grafiken" if de else "Images, button graphics", "MIT-CMU",
         "© Secret Labs AB, Fredrik Lundh, Jeffrey A. Clark"),
        ("tsMuxeR", "Muxen der Filme" if de else "Muxing the films", "Apache-2.0",
         "© Roman Vasilenko, tsMuxeR contributors"),
        ("FFmpeg", "Menü-Hintergründe, Analyse, Vorbereiten" if de else "Menu backgrounds, analysis, Prepare",
         "GPL-3.0", "© the FFmpeg developers"),
        ("x264 (in FFmpeg)", "Video-Encoding in Vorbereiten" if de else "Video encoding in Prepare",
         "GPL-2.0-or-later", "© x264 project"),
        ("Liberation Sans", "Schrift auf der Disc (Menüs)" if de else "Font on the disc (menus)", "OFL-1.1",
         "© Red Hat, Inc.; © Google Corporation"),
        ("Noto Sans", "Schrift auf der Disc (Untertitel)" if de else "Font on the disc (subtitles)", "OFL-1.1",
         "© The Noto Project Authors"),
        ("Python", "Laufzeit" if de else "Runtime", "PSF-2.0", "© Python Software Foundation"),
    ]


def licenses_text(de: bool) -> str:
    return ("OpenBDAuth verwendet die folgenden Open-Source-Komponenten. FFmpeg und tsMuxeR liegen dem Programm bei "
            "und werden als eigene Programme aufgerufen. Die vollständigen Lizenztexte liegen im Programmordner "
            "unter licenses/, Versionen und Quellen in THIRD_PARTY_LICENSES.md."
            if de else
            "OpenBDAuth uses the following open source components. FFmpeg and tsMuxeR are shipped with the program "
            "and run as separate programs. The full license texts are in the program folder under licenses/, "
            "versions and sources in THIRD_PARTY_LICENSES.md.")


def news_html(lang: str) -> str:
    """Neuerungen als HTML (Qt-Rich-Text): je Version Nummer, Datum, Überschrift und Stichpunkte, neueste oben,
    die laufende Version markiert, Trennlinie dazwischen."""
    parts = []
    for i, release in enumerate(RELEASES):
        notes = release.notes(lang)
        if i:
            parts.append('<table width="100%" cellspacing="0" cellpadding="0" style="margin-top: 14px; '
                         'margin-bottom: 14px;"><tr><td height="1" bgcolor="#2E2E33" style="font-size: 1px;"></td>'
                         '</tr></table>')     # font-size: sonst ist die leere Zelle eine Textzeile hoch
        badge = ""
        if release.version == APP_VERSION:
            label = "Diese Version" if lang == "de" else "This version"
            badge = (f'&nbsp;&nbsp;<span style="background-color: #FBBF24; color: #18181B; font-size: 11px; '
                     f'font-weight: 600;">&nbsp;{label}&nbsp;</span>')
        parts.append(
            '<table width="100%" cellspacing="0" cellpadding="0"><tr>'
            f'<td><span style="color: #FBBF24; font-size: 15px; font-weight: 600;">{html.escape(release.version)}'
            f'</span>{badge}</td>'
            f'<td align="right" style="color: #71717A;">{html.escape(date_text(release, lang))}</td>'
            '</tr></table>')
        parts.append(f'<p style="margin-top: 4px; margin-bottom: 0px; color: #FAFAFA; font-weight: 600;">'
                     f'{html.escape(notes.title)}</p>')
        items = "".join(f'<li style="margin-bottom: 4px;">{html.escape(text)}</li>' for text in notes.points)
        parts.append(f'<ul style="margin-top: 6px; margin-bottom: 0px; margin-left: 0px; -qt-list-indent: 1;">'
                     f'{items}</ul>')
    return "".join(parts)


ROW_HEIGHT = 40          # v1.30.1: vorher 32, auf dem Mac zu dicht
HEADER_HEIGHT = 28


class AboutDialog(QDialog):
    def __init__(self, lang: str = "de", tab: int = TAB_OVERVIEW, parent=None):
        super().__init__(parent)
        self.setObjectName("about")
        self.setStyleSheet(ABOUT_QSS)
        de = lang == "de"
        self.setWindowTitle(f"Info – {APP_NAME}" if de else f"About {APP_NAME}")
        self.resize(820, 660)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("about_header")
        outer = QHBoxLayout(header)
        outer.setContentsMargins(24, 16, 24, 14)
        outer.setSpacing(14)
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(44, 44))
        logo.setStyleSheet("background: transparent;")
        outer.addWidget(logo, 0, Qt.AlignVCenter)
        head = QVBoxLayout()
        head.setSpacing(2)
        outer.addLayout(head, 1)
        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title = QLabel(APP_NAME)
        title.setObjectName("about_title")
        version = QLabel(f"Version {APP_VERSION}")
        version.setObjectName("about_version")
        title_row.addWidget(title)
        title_row.addWidget(version, 0, Qt.AlignBottom)
        title_row.addStretch(1)
        head.addLayout(title_row)
        subtitle = QLabel("Blu-ray-Authoring mit Menüs" if de else "Blu-ray authoring with menus")
        subtitle.setObjectName("about_subtitle")
        head.addWidget(subtitle)
        layout.addWidget(header)

        tabs = QFrame()
        tabs.setObjectName("about_tabs")
        tab_row = QHBoxLayout(tabs)
        tab_row.setContentsMargins(20, 0, 20, 0)
        tab_row.setSpacing(4)
        self.tab_group = QButtonGroup(self)
        self.stack = QStackedWidget()
        labels = (["Überblick", "Neuerungen", "Tastenkürzel", "Lizenzen"] if de
                  else ["Overview", "What's new", "Shortcuts", "Licenses"])
        pages = [self._overview(de), self._news(lang), self._shortcuts(de), self._licenses(de)]
        for i, (label, page) in enumerate(zip(labels, pages)):
            button = QPushButton(label)
            button.setObjectName("about_tab")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            self.tab_group.addButton(button, i)
            tab_row.addWidget(button)
            self.stack.addWidget(page if isinstance(page, QTextBrowser) else self._scroll(page))
        tab_row.addStretch(1)
        self.tab_group.idClicked.connect(self.stack.setCurrentIndex)
        layout.addWidget(tabs)
        layout.addWidget(self.stack, 1)

        footer = QFrame()
        footer.setObjectName("about_footer")
        foot = QHBoxLayout(footer)
        foot.setContentsMargins(24, 10, 24, 10)
        foot.addStretch(1)
        close = QPushButton("Schließen" if de else "Close")
        close.clicked.connect(self.accept)
        foot.addWidget(close)
        layout.addWidget(footer)

        self.show_tab(tab)

    def show_tab(self, tab: int):
        self.tab_group.button(tab).setChecked(True)
        self.stack.setCurrentIndex(tab)

    # --- Seiten --------------------------------------------------------------------------
    @staticmethod
    def _scroll(page: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setWidget(page)
        return area

    @staticmethod
    def _page() -> Tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(24, 20, 24, 20)
        box.setSpacing(10)
        return page, box

    @staticmethod
    def _text(text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        return label

    @staticmethod
    def _section(text: str) -> QLabel:
        label = QLabel(text.upper())
        label.setObjectName("about_section")
        return label

    def _table(self, rows, headers=None, first_width: int = 0) -> QTableWidget:
        columns = len(rows[0])
        table = QTableWidget(len(rows), columns)
        table.setObjectName("about_table")
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        table.setWordWrap(False)              # jede Zeile einzeilig: feste Höhe, keine Bildlaufleiste
        table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        table.setFocusPolicy(Qt.NoFocus)
        table.setSelectionMode(QAbstractItemView.NoSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        if headers:
            table.setHorizontalHeaderLabels(headers)
            table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        else:
            table.horizontalHeader().setVisible(False)
        for r, row in enumerate(rows):
            for c, text in enumerate(row):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                if c == 0:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                    item.setForeground(Qt.white)
                table.setItem(r, c, item)
        header = table.horizontalHeader()
        for c in range(columns - 1):
            header.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        if first_width:                        # gleiche Spalte in allen Gruppen
            header.setSectionResizeMode(0, QHeaderView.Fixed)
            header.resizeSection(0, first_width)
        header.setSectionResizeMode(columns - 1, QHeaderView.Stretch)
        header.setFixedHeight(HEADER_HEIGHT)
        table.setFixedHeight(len(rows) * ROW_HEIGHT + (HEADER_HEIGHT if headers else 0) + 2)
        return table

    def _overview(self, de: bool) -> QWidget:
        page, box = self._page()
        box.addWidget(self._text(overview_text(de)))
        box.addSpacing(8)
        box.addWidget(self._section("Bereiche" if de else "Areas"))
        box.addWidget(self._table(areas(de)))
        box.addStretch(1)
        return page

    @staticmethod
    def _news(lang: str) -> QTextBrowser:
        """Eine Textansicht statt Labels im Bildlaufbereich: Die berechnete die Höhe umbrochener Stichpunkte zu knapp
        und schnitt sie ab. Scrollt selbst, Text lässt sich markieren, Links gibt es keine."""
        view = QTextBrowser()
        view.setObjectName("news")
        view.setOpenLinks(False)
        view.setFrameShape(QFrame.NoFrame)
        view.document().setDocumentMargin(22)
        view.setHtml(news_html(lang))
        return view

    def _shortcuts(self, de: bool) -> QWidget:
        page, box = self._page()
        for title, items in shortcut_groups(de):
            box.addWidget(self._section(title))
            box.addWidget(self._table(items, first_width=300))
            box.addSpacing(6)
        note = self._text("Unter macOS gilt ⌘ anstelle von Strg." if de else "On macOS, use ⌘ instead of Ctrl.")
        note.setStyleSheet("color: #71717A;")
        box.addWidget(note)
        box.addStretch(1)
        return page

    def _licenses(self, de: bool) -> QWidget:
        page, box = self._page()
        box.addWidget(self._text(licenses_text(de)))
        box.addSpacing(6)
        headers = (["Komponente", "Verwendung", "Lizenz", "Rechteinhaber"] if de
                   else ["Component", "Used for", "License", "Copyright"])
        box.addWidget(self._table(components(de), headers))
        box.addStretch(1)
        return page
