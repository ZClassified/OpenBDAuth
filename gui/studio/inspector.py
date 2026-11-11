# gui/studio/inspector.py
"""
Inspektor: zeigt die Eigenschaften des ausgewählten Knotens.
- Start: Disc-Einstellungen
- Film: Video, Tonspuren, Untertitel, Kapitel (Import per Drag & Drop oder Schaltfläche)
- Menü: nach Auswahl das Menü, ein Button (Typ, Ziel, Form & Position, Fernbedienung) oder mehrere Buttons
"""

import os
import re
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QWidget, QScrollArea, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QFileDialog, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QComboBox, QFrame, QSpinBox,
)

from core import menu_design, menu_templates, disc_edit, node_frames
from core.translations import tr, tr_file_filter, ui_language
from core.disc_model import START_NODE_ID
from core.disc_edit import TRACK_AUDIO, TRACK_SUBTITLE, tracks
from core.disc_rules import button_label, starts_3d_film
from core.disc_model import (
    BUTTON_NAV, BUTTON_CHAPTER, BUTTON_AUDIO, BUTTON_SUBTITLE,
    FILM_COLORS, STYLE_TEXT, STYLE_SHAPE,
)
from modules.button_shapes import SHAPES, MIN_SIZE
from core.chapter_time import is_valid_chapter_time, next_chapter_time
from core.media_paths import is_missing
from gui.node_editor.controller import GraphController
from gui.studio.importer import FilmImporter
from gui.studio.widgets import (
    DropFrame, ColorSwatchButton, SegmentedSwitch, DragSpinBox, ElidedLabel, small_button, hint_label, clear_layout,
    Section as _Section, fill_combo as _fill_combo,
)
from gui.widgets.language_combo import LanguageComboBox

VIDEO_FILTER = "AVC Video (*.264 *.h264 *.avc *.m2ts);;Alle Dateien (*.*)"
MVC_FILTER = "MVC Video (*.mvc);;Alle Dateien (*.*)"
AUDIO_FILTER = "Audio (*.ac3 *.eac3 *.ec3 *.dts *.dtshd *.truehd *.thd *.wav *.mp4);;Alle Dateien (*.*)"
SUB_FILTER = "Untertitel (*.srt *.sup);;Alle Dateien (*.*)"
EDL_FILTER = "EDL (*.edl);;Alle Dateien (*.*)"
BG_IMAGE_FILTER = "Bilder (*.png *.jpg *.jpeg *.bmp);;Alle Dateien (*.*)"
BG_VIDEO_FILTER = "H.264 Video (*.264 *.h264 *.avc);;Alle Dateien (*.*)"
BG_AUDIO_FILTER = "Audio (*.ac3 *.wav);;Alle Dateien (*.*)"


MAX_PLAYER_TITLE = 64
MISSING_STYLE = "color: #F87171;"
TRACK_LANG_WIDTH = 150      # Sprachauswahl einer Spur (v1.17.2: vorher mind. 170 und mitwachsend)
SHAPE_COLORS = ["#FFFFFF", "#FFD700", "#F97316", "#EF4444", "#22D3EE", "#3B82F6", "#94A3B8", "#000000"]
SHAPE_STATES = ("normal", "selected", "activated")
STYLE_KINDS = (STYLE_TEXT, STYLE_SHAPE)
MULTI_GEO_FIELDS = ("x", "y", "w", "h")   # Reihenfolge wie menu_layout.button_box


def show_file(label: QLabel, path: Optional[str], t: Callable, style: str = ""):
    """Dateiname mit Pfad als Tooltip; eine fehlende Datei rot mit „– fehlt“ (v1.17.0)."""
    missing = is_missing(path)
    if not path:
        label.setText(t("studio_none"))
    else:
        name = os.path.basename(path)
        label.setText(t("studio_file_missing", name=name) if missing else name)
    label.setToolTip(path or "")
    label.setStyleSheet(MISSING_STYLE if missing else style)


def sanitize_disc_name(raw: str) -> str:
    """UDF-konformer Disc-Name (wie bisher: nur A–Z, 0–9, _, max. 32 Zeichen)."""
    return re.sub(r'[^A-Za-z0-9_]', '_', raw).upper()[:32]


class _Page(QWidget):
    def __init__(self, inspector: "InspectorPanel"):
        super().__init__()
        self.inspector = inspector
        self.node_id: Optional[str] = None

    @property
    def controller(self) -> GraphController:
        return self.inspector.controller

    def t(self, key: str, **kwargs) -> str:
        text = tr(key, ui_language())
        return text.format(**kwargs) if kwargs else text

    def load(self, node_id: str):
        self.node_id = node_id
        self.refresh()

    def refresh(self):
        pass

    def retranslate(self):
        pass


def _set_text_if_idle(edit: QLineEdit, text: str):
    if not edit.hasFocus() and edit.text() != text:
        edit.setText(text)


# -------------------------------------------------------------------------
# Start
# -------------------------------------------------------------------------

class StartPage(_Page):
    def __init__(self, inspector):
        super().__init__(inspector)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.card = DropFrame()
        self.lbl_name = QLabel()
        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("BD_DISC")
        self.edit_name.textEdited.connect(self._on_name_typed)
        self.edit_name.editingFinished.connect(self._commit_name)
        # Titel im Player (BDMV/META, v1.10.1): freier Text mit Umlauten, leer = aus dem Disc-Namen
        self.lbl_title = QLabel()
        self.edit_title = QLineEdit()
        self.edit_title.setMaxLength(MAX_PLAYER_TITLE)
        self.edit_title.editingFinished.connect(self._commit_title)
        self.lbl_lang = QLabel()
        self.combo_lang = QComboBox()
        self.combo_lang.addItem("Deutsch", "de")
        self.combo_lang.addItem("English", "en")
        self.combo_lang.currentIndexChanged.connect(self._on_lang)
        self.lbl_target = hint_label()
        for w in (self.lbl_name, self.edit_name, self.lbl_title, self.edit_title, self.lbl_lang, self.combo_lang,
                  self.lbl_target):
            self.card.layout_.addWidget(w)
        layout.addWidget(self.card)
        layout.addStretch(1)

    def _on_name_typed(self, raw: str):
        clean = sanitize_disc_name(raw)
        if clean != raw:
            pos = self.edit_name.cursorPosition()
            self.edit_name.setText(clean)
            self.edit_name.setCursorPosition(min(pos, len(clean)))

    def _commit_name(self):
        self.controller.set_settings("Disc-Namen ändern", project_name=sanitize_disc_name(self.edit_name.text()))

    def _commit_title(self):
        self.controller.set_settings("Titel im Player ändern", disc_title=self.edit_title.text().strip())

    def _on_lang(self, index: int):
        lang = self.combo_lang.itemData(index)
        if lang and lang != self.controller.project.settings.app_lang:
            self.controller.set_settings("Sprache der Disc ändern", app_lang=lang)

    def refresh(self):
        s = self.controller.project.settings
        _set_text_if_idle(self.edit_name, s.project_name)
        _set_text_if_idle(self.edit_title, s.disc_title)
        self.edit_title.setPlaceholderText(s.player_title())
        idx = self.combo_lang.findData(s.app_lang)
        if idx >= 0 and idx != self.combo_lang.currentIndex():
            self.combo_lang.blockSignals(True)
            self.combo_lang.setCurrentIndex(idx)
            self.combo_lang.blockSignals(False)
        target = self.controller.project.node(self.controller.project.start_target)
        self.lbl_target.setText(self.t("studio_start_target", name=target.name) if target
                                else self.t("studio_start_none"))
        self.retranslate()

    def retranslate(self):
        self.card.set_title(self.t("studio_start_title"))
        self.lbl_name.setText(self.t("studio_disc_name"))
        self.lbl_title.setText(self.t("studio_disc_title"))
        self.edit_title.setToolTip(self.t("studio_disc_title_tip"))
        self.lbl_lang.setText(self.t("studio_ui_lang"))


# -------------------------------------------------------------------------
# Film
# -------------------------------------------------------------------------

class _TrackList(QWidget):
    """Liste von Ton- oder Untertitelspuren mit Sprache, Reihenfolge und Entfernen."""

    def __init__(self, page: "FilmPage", kind: str):
        super().__init__()
        self.page = page
        self.kind = kind
        self._signature = None
        self.rows = QVBoxLayout(self)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(4)

    def refresh(self, film):
        items = tracks(film, self.kind)
        signature = (film.id, tuple((t.id, t.path, t.lang) for t in items))
        if signature == self._signature:
            return
        self._signature = signature
        clear_layout(self.rows)
        if not items:
            self.rows.addWidget(hint_label(self.page.t("studio_no_tracks")))
            return
        for i, track in enumerate(items):
            self.rows.addWidget(self._row(film.id, i, track, len(items)))

    def _row(self, film_id, index, track, count) -> QWidget:
        row = QFrame()
        row.setStyleSheet("QFrame { background-color: #27272A; border: 1px solid #3F3F46; border-radius: 6px; }"
                          "QLabel { border: none; background: transparent; }")
        h = QHBoxLayout(row)
        h.setContentsMargins(8, 4, 6, 4)
        h.setSpacing(6)
        num = QLabel(str(index + 1))
        num.setStyleSheet("color: #71717A; font-weight: bold;")
        name = ElidedLabel()          # kürzt in der Mitte: Dateiendung bleibt sichtbar
        show_file(name, track.path, self.page.t)
        name.setMinimumWidth(60)
        combo = LanguageComboBox(default_code=track.lang)
        combo.setFixedWidth(TRACK_LANG_WIDTH)   # „English [eng]“ passt; der Rest der Zeile gehört dem Dateinamen
        combo.view().setMinimumWidth(combo.view().sizeHintForColumn(0) + 24)   # Liste zeigt volle Namen
        combo.currentIndexChanged.connect(
            lambda _i, c=combo, tid=track.id: self.page.controller.set_track_lang(
                film_id, self.kind, tid, c.get_selected_lang_code()))
        up = small_button("↑", self.page.t("studio_move_up"))
        up.setEnabled(index > 0)
        up.clicked.connect(lambda: self.page.controller.move_track(film_id, self.kind, track.id, -1))
        down = small_button("↓", self.page.t("studio_move_down"))
        down.setEnabled(index < count - 1)
        down.clicked.connect(lambda: self.page.controller.move_track(film_id, self.kind, track.id, 1))
        remove = small_button("✕", self.page.t("studio_remove"), danger=True)
        remove.clicked.connect(lambda: self.page.controller.remove_track(film_id, self.kind, track.id))
        h.addWidget(num)
        h.addWidget(name, stretch=1)
        h.addWidget(combo)
        h.addWidget(up)
        h.addWidget(down)
        h.addWidget(remove)
        return row


class FilmPage(_Page):
    def __init__(self, inspector):
        super().__init__(inspector)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        importer = inspector.importer

        # Name
        self.card_name = DropFrame()
        self.edit_name = QLineEdit()
        self.edit_name.editingFinished.connect(
            lambda: self.controller.rename_node(self.node_id, self.edit_name.text()))
        # Farbe des Films (Knoten und seine Menüs); neue Filme bekommen sie weiterhin automatisch
        self.btn_color = ColorSwatchButton(list(FILM_COLORS))
        self.btn_color.color_chosen.connect(
            lambda color: self.controller.set_film_fields(self.node_id, "Farbe ändern", color=color))
        name_row = QHBoxLayout()
        name_row.addWidget(self.edit_name, stretch=1)
        name_row.addWidget(self.btn_color)
        self.card_name.layout_.addLayout(name_row)
        layout.addWidget(self.card_name)

        # Video
        self.card_video = DropFrame()
        self.lbl_base_caption = QLabel()
        self.lbl_base = QLabel()
        self.btn_base = QPushButton()
        self.btn_base.clicked.connect(lambda: self._pick(VIDEO_FILTER, lambda p: importer.set_video(self.node_id, p)))
        self.btn_base_clear = small_button("✕", "", danger=True)
        self.btn_base_clear.clicked.connect(lambda: importer.clear_video(self.node_id))
        self.lbl_mvc_caption = QLabel()
        self.lbl_mvc = QLabel()
        self.btn_mvc = QPushButton()
        self.btn_mvc.clicked.connect(lambda: self._pick(MVC_FILTER, lambda p: importer.set_mvc(self.node_id, p)))
        self.btn_mvc_clear = small_button("✕", "", danger=True)
        self.btn_mvc_clear.clicked.connect(lambda: importer.set_mvc(self.node_id, None))
        self.lbl_info = QLabel()
        self.lbl_info.setStyleSheet("color: #4ADE80; font-weight: bold;")
        self.btn_compliance = QPushButton()
        self.btn_compliance.clicked.connect(lambda: self.inspector.show_compliance(self.node_id))
        for caption, label, pick, clear in ((self.lbl_base_caption, self.lbl_base, self.btn_base, self.btn_base_clear),
                                            (self.lbl_mvc_caption, self.lbl_mvc, self.btn_mvc, self.btn_mvc_clear)):
            caption.setStyleSheet("color: #D4D4D8;")
            self.card_video.layout_.addWidget(caption)
            row = QHBoxLayout()
            label.setStyleSheet("color: #A1A1AA;")
            label.setMinimumWidth(40)
            row.addWidget(label, stretch=1)
            row.addWidget(pick)
            row.addWidget(clear)
            self.card_video.layout_.addLayout(row)
        self.card_video.layout_.addWidget(self.lbl_info)
        self.card_video.layout_.addWidget(self.btn_compliance, alignment=Qt.AlignLeft)
        layout.addWidget(self.card_video)

        # Tonspuren
        self.card_audio = DropFrame()
        self.audio_list = _TrackList(self, TRACK_AUDIO)
        self.btn_audio = QPushButton()
        self.btn_audio.clicked.connect(lambda: self._pick(AUDIO_FILTER, lambda p: importer.add_audio(self.node_id, p),
                                                          multiple=True))
        self.card_audio.layout_.addWidget(self.audio_list)
        self.card_audio.layout_.addWidget(self.btn_audio, alignment=Qt.AlignLeft)
        layout.addWidget(self.card_audio)

        # Untertitel
        self.card_subs = DropFrame()
        self.sub_list = _TrackList(self, TRACK_SUBTITLE)
        self.btn_sub = QPushButton()
        self.btn_sub.clicked.connect(lambda: self._pick(SUB_FILTER, lambda p: importer.add_subtitle(self.node_id, p),
                                                        multiple=True))
        self.card_subs.layout_.addWidget(self.sub_list)
        self.card_subs.layout_.addWidget(self.btn_sub, alignment=Qt.AlignLeft)
        layout.addWidget(self.card_subs)

        # Kapitel
        self.card_chapters = DropFrame()
        self.table = QTableWidget(0, 2)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setMinimumHeight(140)
        self.table.cellChanged.connect(self._on_chapter_edited)
        self._chapter_signature = None
        self._loading_table = False
        chapter_buttons = QHBoxLayout()
        edl_row = QHBoxLayout()
        self.btn_edl = QPushButton()
        self.btn_edl.clicked.connect(lambda: self._pick(EDL_FILTER, lambda p: importer.import_chapters(self.node_id, p)))
        self.btn_add_chapter = QPushButton()
        self.btn_add_chapter.clicked.connect(self._add_chapter)
        self.btn_remove_chapter = QPushButton()
        self.btn_remove_chapter.clicked.connect(self._remove_selected_chapters)
        edl_row.addWidget(self.btn_edl)
        edl_row.addStretch(1)
        for b in (self.btn_add_chapter, self.btn_remove_chapter):
            chapter_buttons.addWidget(b)
        chapter_buttons.addStretch(1)
        self.card_chapters.layout_.addWidget(self.table)
        self.card_chapters.layout_.addLayout(chapter_buttons)
        self.card_chapters.layout_.addLayout(edl_row)
        layout.addWidget(self.card_chapters)

        # Nach dem Film
        self.card_end = DropFrame()
        self.lbl_end = QLabel()
        self.card_end.layout_.addWidget(self.lbl_end)
        layout.addWidget(self.card_end)
        layout.addStretch(1)

        for card in (self.card_name, self.card_video, self.card_audio, self.card_subs, self.card_chapters, self.card_end):
            card.files_dropped.connect(lambda files: importer.import_files(self.node_id, files))

    # --- Aktionen -------------------------------------------------------------
    def _pick(self, file_filter: str, apply: Callable[[str], None], multiple: bool = False):
        if multiple:
            paths, _ = QFileDialog.getOpenFileNames(self, "", "", tr_file_filter(file_filter))
        else:
            path, _ = QFileDialog.getOpenFileName(self, "", "", tr_file_filter(file_filter))
            paths = [path] if path else []
        for p in paths:
            apply(p)

    def _add_chapter(self):
        film = self.controller.project.film(self.node_id)
        if film is None:
            return
        self.controller.add_chapter(self.node_id, next_chapter_time([c.time for c in film.chapters]))

    def _remove_selected_chapters(self):
        film = self.controller.project.film(self.node_id)
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        ids = [film.chapters[r].id for r in rows if film and r < len(film.chapters)]
        self.controller.remove_chapters(self.node_id, ids)

    def _on_chapter_edited(self, row: int, col: int):
        if self._loading_table:
            return
        film = self.controller.project.film(self.node_id)
        if film is None or row >= len(film.chapters):
            return
        chapter = film.chapters[row]
        text = self.table.item(row, col).text().strip()
        if col == 0:
            if is_valid_chapter_time(text):
                self.controller.set_chapter_time(self.node_id, chapter.id, text)
            else:
                self.inspector.status(self.t("studio_invalid_time"))
                self._chapter_signature = None
                self.refresh()
        else:
            self.controller.set_chapter_name(self.node_id, chapter.id, text or None)

    # --- Anzeige --------------------------------------------------------------
    def refresh(self):
        film = self.controller.project.film(self.node_id)
        if film is None:
            return
        self.retranslate()
        _set_text_if_idle(self.edit_name, film.name)
        self.card_name.title_label.setStyleSheet(
            f"font-size: 12px; font-weight: bold; color: {film.color}; letter-spacing: 1px;")
        self.btn_color.set_color(film.color)

        show_file(self.lbl_base, film.video_base, self.t)
        self.btn_base_clear.setEnabled(bool(film.video_base))
        show_file(self.lbl_mvc, film.video_mvc, self.t)
        self.btn_mvc_clear.setEnabled(bool(film.video_mvc))

        details = film.video_details or {}
        if film.video_base:
            mode = "3D" if film.is_3d else "2D"
            w, h = details.get("width", 0), details.get("height", 0)
            size = f"{w}×{h} · " if w and h else ""
            self.lbl_info.setText(f"{size}{film.fps:.3f} fps · {mode}")
            warn = len(film.compliance_warnings)
            self.btn_compliance.setVisible(True)
            self.btn_compliance.setText(tr("compliance_badge_warn", ui_language())
                                        .format(count=warn) if warn else
                                        tr("compliance_badge_ok", ui_language()))
            self.btn_compliance.setEnabled(bool(warn))
        else:
            self.lbl_info.setText("")
            self.btn_compliance.setVisible(False)

        self.audio_list.refresh(film)
        self.sub_list.refresh(film)
        self._refresh_chapters(film)
        project = self.controller.project
        end, next_film = project.menu(film.end_target), project.film(film.end_target)
        if next_film is not None:
            self.lbl_end.setText(self.t("studio_end_film", name=next_film.name))
        elif end is not None and end is not project.main_menu:
            self.lbl_end.setText(self.t("studio_end_menu", name=end.name))
        else:
            self.lbl_end.setText(self.t("studio_end_main"))

    def _refresh_chapters(self, film):
        signature = (film.id, tuple((c.id, c.time, c.name) for c in film.chapters))
        if signature == self._chapter_signature:
            return
        self._chapter_signature = signature
        self._loading_table = True
        self.table.setRowCount(len(film.chapters))
        for i, ch in enumerate(film.chapters):
            self.table.setItem(i, 0, QTableWidgetItem(ch.time))
            item = QTableWidgetItem(ch.name or "")
            item.setToolTip(self.t("studio_chapter_name_hint", n=i + 1))
            self.table.setItem(i, 1, item)
        self._loading_table = False
        self.btn_remove_chapter.setEnabled(bool(film.chapters))

    def retranslate(self):
        self.card_name.set_title(self.t("studio_film"))
        self.btn_color.setToolTip(self.t("studio_film_color_tip"))
        self.btn_color.act_custom.setText(self.t("studio_film_color_custom"))
        self.card_video.set_title(self.t("studio_section_video"))
        self.lbl_base_caption.setText(self.t("studio_video_base"))
        self.lbl_mvc_caption.setText(self.t("studio_video_mvc"))
        self.btn_base.setText(self.t("studio_choose"))
        self.btn_mvc.setText(self.t("studio_choose"))
        self.btn_base_clear.setToolTip(self.t("studio_remove"))
        self.btn_mvc_clear.setToolTip(self.t("studio_remove"))
        self.card_audio.set_title(self.t("studio_section_audio"))
        self.btn_audio.setText(self.t("studio_add_audio"))
        self.card_subs.set_title(self.t("studio_section_subs"))
        self.btn_sub.setText(self.t("studio_add_sub"))
        self.card_chapters.set_title(self.t("studio_section_chapters"))
        self.table.setHorizontalHeaderLabels([self.t("studio_col_time"), self.t("studio_col_name")])
        self.btn_edl.setText(self.t("studio_import_edl"))
        self.btn_add_chapter.setText(self.t("studio_add_chapter"))
        self.btn_remove_chapter.setText(self.t("studio_remove_chapter"))
        self.card_end.set_title(self.t("studio_section_end"))


# -------------------------------------------------------------------------
# Menü
# -------------------------------------------------------------------------

def _set_spin(spin: QSpinBox, value: int):
    if not spin.hasFocus() and spin.value() != value:
        spin.blockSignals(True)
        spin.setValue(int(value))
        spin.blockSignals(False)


BUTTON_KIND_ORDER = (BUTTON_NAV, BUTTON_CHAPTER, BUTTON_AUDIO, BUTTON_SUBTITLE)
DIRECTIONS = ("up", "down", "left", "right")
ALIGN_GLYPHS = (("left", "⇤"), ("hcenter", "↔"), ("right", "⇥"), ("top", "⤒"), ("vcenter", "↕"), ("bottom", "⤓"))

MODE_MENU, MODE_BUTTON, MODE_MULTI = "menu", "button", "multi"


class _HoverBox(QWidget):
    """Bereich, der meldet, ob die Maus darüber ist (Nummern-Vorschau „Ziele der Reihe nach“, v1.14)."""
    hovered = Signal(bool)

    def enterEvent(self, event):
        self.hovered.emit(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hovered.emit(False)
        super().leaveEvent(event)


SEQ_KINDS = (BUTTON_CHAPTER, BUTTON_AUDIO, BUTTON_SUBTITLE)


class MenuPage(_Page):
    """
    Menü-Inspektor nach Auswahl:
    - nichts ausgewählt: das Menü (Name, Standard-Film, Standard-Button, Hintergrund, Button-Stil)
    - ein Button: Typ und Name · Ziel · Form & Position · Fernbedienung (eingeklappt)
    - mehrere Buttons: Film für alle Inhalts-Buttons, gleiche Größe, ausrichten, entfernen
    - bei einem oder mehreren Buttons oben „Aussehen [ Text | Form ]“: der Stil des ganzen Menüs (v1.14.5)
    Buttons wählt man im Viewer oder in den Zeilen des Menü-Knotens; die Auswahl teilen sich alle Bereiche.
    """

    def __init__(self, inspector):
        super().__init__(inspector)
        self.mode = MODE_MENU
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # --- Kopf für Button-Ansichten: wo bin ich, zurück zum Menü -------------
        self.selection_bar = QWidget()
        bar = QHBoxLayout(self.selection_bar)
        bar.setContentsMargins(0, 0, 0, 0)
        self.lbl_selection = QLabel()
        self.lbl_selection.setStyleSheet("color: #FBBF24; font-weight: bold;")
        self.lbl_selection.setWordWrap(True)
        self.btn_back = QPushButton()
        self.btn_back.clicked.connect(lambda: self.controller.select_button(None, None))
        bar.addWidget(self.lbl_selection, stretch=1)
        bar.addWidget(self.btn_back)
        layout.addWidget(self.selection_bar)

        # Aussehen bei ausgewählten Buttons (v1.14.5): man sucht den Stil beim Button; er gilt aber fürs Menü
        self.style_bar = QFrame()
        self.style_bar.setObjectName("style_bar")
        self.style_bar.setStyleSheet("QFrame#style_bar { background-color: #1C1C1F; border: 1px solid #27272A;"
                                     " border-radius: 6px; }")
        sb = QVBoxLayout(self.style_bar)
        sb.setContentsMargins(10, 8, 10, 8)
        sb.setSpacing(4)
        sb_row = QHBoxLayout()
        self.lbl_look = QLabel()
        self.lbl_look.setStyleSheet("color: #D4D4D8; border: none;")
        self.switch_look = SegmentedSwitch(STYLE_KINDS)
        self.switch_look.chosen.connect(lambda kind: self.controller.set_button_style(self.node_id, kind=kind))
        self.btn_look_more = QPushButton()
        self.btn_look_more.setFlat(True)
        self.btn_look_more.setCursor(Qt.PointingHandCursor)
        self.btn_look_more.setStyleSheet("QPushButton { color: #FCD34D; border: none; padding: 2px 4px; }"
                                         "QPushButton:hover { text-decoration: underline; }")
        self.btn_look_more.clicked.connect(self._show_style_card)
        sb_row.addWidget(self.lbl_look)
        sb_row.addWidget(self.switch_look)
        sb_row.addStretch(1)
        sb_row.addWidget(self.btn_look_more)
        sb.addLayout(sb_row)
        self.lbl_look_hint = hint_label()
        self.lbl_look_hint.setStyleSheet(self.lbl_look_hint.styleSheet() + " border: none;")
        sb.addWidget(self.lbl_look_hint)
        layout.addWidget(self.style_bar)

        # =====================================================================
        # Menü
        # =====================================================================
        self.card = DropFrame()
        self.edit_name = QLineEdit()
        self.edit_name.editingFinished.connect(
            lambda: self.controller.rename_node(self.node_id, self.edit_name.text()))
        self.lbl_main = QLabel()
        self.btn_make_main = QPushButton()
        self.btn_make_main.clicked.connect(self._make_main)
        self.card.layout_.addWidget(self.edit_name)
        self.card.layout_.addWidget(self.lbl_main)
        self.card.layout_.addWidget(self.btn_make_main, alignment=Qt.AlignLeft)
        self.film_row = QWidget()
        film_layout = QHBoxLayout(self.film_row)
        film_layout.setContentsMargins(0, 0, 0, 0)
        self.lbl_default_film = QLabel()
        self.lbl_default_film.setStyleSheet("color: #D4D4D8;")
        self.combo_default_film = QComboBox()
        self.combo_default_film.activated.connect(
            lambda _i: self.controller.set_menu_fields(self.node_id, "Standard-Film ändern",
                                                       default_film_id=self.combo_default_film.currentData() or None))
        film_layout.addWidget(self.lbl_default_film, stretch=1)
        film_layout.addWidget(self.combo_default_film, stretch=2)
        self.card.layout_.addWidget(self.film_row)
        default_row = QHBoxLayout()
        self.lbl_default_button = QLabel()
        self.lbl_default_button.setStyleSheet("color: #D4D4D8;")
        self.combo_default_button = QComboBox()
        self.combo_default_button.activated.connect(
            lambda _i: self.controller.set_menu_fields(self.node_id, "Standard-Button ändern",
                                                       default_button_id=self.combo_default_button.currentData() or None))
        default_row.addWidget(self.lbl_default_button, stretch=1)
        default_row.addWidget(self.combo_default_button, stretch=2)
        self.card.layout_.addLayout(default_row)
        layout.addWidget(self.card)

        # Inhalt: die Filme, deren Kapitel bzw. Spuren die Buttons zeigen
        self.card_content = DropFrame()
        self.lbl_source = QLabel()
        self.card_content.layout_.addWidget(self.lbl_source)
        layout.addWidget(self.card_content)

        # Hintergrund (v1.13.2): jedes Menü „wie Hauptmenü“ oder mit eigenem Bild, Video, Musik
        self.card_bg = DropFrame()
        mode_row = QHBoxLayout()
        self.lbl_bg_mode = QLabel()
        self.lbl_bg_mode.setWordWrap(True)
        self.btn_bg_follow = QPushButton()
        self.btn_bg_follow.clicked.connect(lambda: self.controller.clear_background(self.node_id))
        mode_row.addWidget(self.lbl_bg_mode, stretch=1)
        mode_row.addWidget(self.btn_bg_follow)
        self.card_bg.layout_.addLayout(mode_row)
        self.bg_rows = {}
        for field, file_filter in (("image", BG_IMAGE_FILTER), ("video", BG_VIDEO_FILTER), ("audio", BG_AUDIO_FILTER)):
            caption = QLabel()
            caption.setStyleSheet("color: #D4D4D8;")
            value = QLabel()
            value.setStyleSheet("color: #A1A1AA;")
            value.setMinimumWidth(40)
            pick = QPushButton()
            pick.clicked.connect(lambda _c=False, f=field, flt=file_filter: self._pick_background(f, flt))
            clear = small_button("✕", "", danger=True)
            clear.clicked.connect(lambda _c=False, f=field: self.controller.set_menu_background(
                self.node_id, "Hintergrund entfernen", **{f: None}))
            row = QHBoxLayout()
            row.addWidget(value, stretch=1)
            row.addWidget(pick)
            row.addWidget(clear)
            self.card_bg.layout_.addWidget(caption)
            self.card_bg.layout_.addLayout(row)
            self.bg_rows[field] = (caption, value, pick, clear)
        duration_row = QHBoxLayout()
        self.lbl_duration = QLabel()
        self.lbl_duration.setStyleSheet("color: #D4D4D8;")
        self.spin_duration = QSpinBox()
        self.spin_duration.setRange(5, 300)
        self.spin_duration.setFixedWidth(110)
        self.spin_duration.editingFinished.connect(self._commit_duration)
        duration_row.addWidget(self.lbl_duration, stretch=1)
        duration_row.addWidget(self.spin_duration)
        self.card_bg.layout_.addLayout(duration_row)
        self.lbl_bg_hint = hint_label()
        self.card_bg.layout_.addWidget(self.lbl_bg_hint)
        self.card_bg.files_dropped.connect(self._drop_background)
        layout.addWidget(self.card_bg)

        # Button-Stil (v1.11.0): Text wie bisher oder eine Form; die Beschriftung steht dann im Hintergrundbild.
        # Ab v1.14.5 ein Umschalter statt einer Auswahlliste, damit beide Möglichkeiten zu sehen sind.
        self.card_style = DropFrame()
        self.switch_style = SegmentedSwitch(STYLE_KINDS)
        self.switch_style.chosen.connect(lambda kind: self.controller.set_button_style(self.node_id, kind=kind))
        self.card_style.layout_.addWidget(self.switch_style, alignment=Qt.AlignLeft)
        self.lbl_style_desc = hint_label()
        self.card_style.layout_.addWidget(self.lbl_style_desc)
        self.shape_box = QWidget()
        shape_layout = QVBoxLayout(self.shape_box)
        shape_layout.setContentsMargins(0, 0, 0, 0)
        self.combo_shape = QComboBox()
        for shape in SHAPES:
            self.combo_shape.addItem("", shape)
        self.combo_shape.activated.connect(
            lambda _i: self.controller.set_button_style(self.node_id, shape=self.combo_shape.currentData()))
        shape_layout.addWidget(self.combo_shape)
        size_row = QHBoxLayout()
        self.lbl_shape_w = QLabel()
        self.spin_shape_w = QSpinBox()
        self.spin_shape_w.setRange(MIN_SIZE, 1920)
        self.spin_shape_w.editingFinished.connect(
            lambda: self.controller.set_button_style(self.node_id, width=self.spin_shape_w.value()))
        self.lbl_shape_h = QLabel()
        self.spin_shape_h = QSpinBox()
        self.spin_shape_h.setRange(MIN_SIZE, 1080)
        self.spin_shape_h.editingFinished.connect(
            lambda: self.controller.set_button_style(self.node_id, height=self.spin_shape_h.value()))
        for w in (self.lbl_shape_w, self.spin_shape_w, self.lbl_shape_h, self.spin_shape_h):
            size_row.addWidget(w)
        size_row.addStretch(1)
        shape_layout.addLayout(size_row)
        self.state_rows = {}
        self.color_tools = {}
        for state in SHAPE_STATES:
            caption = QLabel()
            caption.setStyleSheet("color: #D4D4D8;")
            swatch = ColorSwatchButton(list(SHAPE_COLORS))
            swatch.color_chosen.connect(
                lambda color, st=state: self.controller.set_button_style(self.node_id, **{f"color_{st}": color}))
            swatch.set_extra_provider(self._color_sections)
            # eigene Farbe als Hex-Code und Pipette im Viewer (v1.14.4)
            hex_edit = QLineEdit()
            hex_edit.setFixedWidth(82)
            hex_edit.setMaxLength(7)
            hex_edit.setPlaceholderText("#RRGGBB")
            hex_edit.editingFinished.connect(lambda st=state, ed=hex_edit: self._commit_hex(st, ed))
            pipette = small_button("⌖", "")
            pipette.clicked.connect(lambda _c=False, st=state: self.controller.color_pick.emit(self.node_id, f"color_{st}"))
            opacity = DragSpinBox()          # eintippen oder ziehen (v1.14.7), nur die Zahl (v1.14.8)
            opacity.setRange(0, 100)
            opacity.setSingleStep(5)         # Pfeile in 5er-Schritten (v1.14.9)
            opacity.committed.connect(
                lambda value, st=state: self.controller.set_button_style(self.node_id, **{f"opacity_{st}": value}))
            row = QHBoxLayout()
            row.addWidget(caption, stretch=1)
            row.addWidget(swatch)
            row.addWidget(hex_edit)
            row.addWidget(pipette)
            row.addWidget(opacity)
            shape_layout.addLayout(row)
            self.state_rows[state] = (caption, swatch, opacity)
            self.color_tools[state] = (hex_edit, pipette)
        self.card_style.layout_.addWidget(self.shape_box)
        layout.addWidget(self.card_style)

        # =====================================================================
        # Ein Button
        # =====================================================================
        self.sec_head = _Section("button")
        kind_row = QHBoxLayout()
        self.lbl_kind = QLabel()
        self.lbl_kind.setStyleSheet("color: #D4D4D8;")
        self.combo_kind = QComboBox()
        for kind in BUTTON_KIND_ORDER:
            self.combo_kind.addItem("", kind)
        self.combo_kind.activated.connect(
            lambda _i: self._with_button(lambda m, b: self.controller.set_button_kind(
                m.id, b.id, self.combo_kind.currentData())))
        kind_row.addWidget(self.lbl_kind, stretch=1)
        kind_row.addWidget(self.combo_kind, stretch=2)
        self.sec_head.layout_.addLayout(kind_row)
        name_row = QHBoxLayout()
        self.lbl_button_name = QLabel()
        self.lbl_button_name.setStyleSheet("color: #D4D4D8;")
        self.edit_button_name = QLineEdit()
        self.edit_button_name.editingFinished.connect(self._commit_button_name)
        self.btn_name_auto = small_button("↺", "")
        self.btn_name_auto.clicked.connect(
            lambda: self._with_button(lambda m, b: self.controller.reset_button_label(m.id, b.id)))
        name_row.addWidget(self.lbl_button_name, stretch=1)
        name_row.addWidget(self.edit_button_name, stretch=2)
        name_row.addWidget(self.btn_name_auto)
        self.sec_head.layout_.addLayout(name_row)
        self.btn_duplicate = QPushButton()
        self.btn_duplicate.clicked.connect(lambda: self.controller.duplicate_selection(self.node_id))
        self.btn_remove_button = QPushButton()
        self.btn_remove_button.clicked.connect(
            lambda: self._with_button(lambda m, b: self.controller.remove_buttons(m.id, [b.id])))
        head_buttons = QHBoxLayout()
        head_buttons.addWidget(self.btn_duplicate)
        head_buttons.addWidget(self.btn_remove_button)
        head_buttons.addStretch(1)
        self.sec_head.layout_.addLayout(head_buttons)
        layout.addWidget(self.sec_head)

        self.sec_target = _Section("target")
        self.lbl_nav_target = QLabel()
        self.lbl_nav_target.setWordWrap(True)
        self.sec_target.layout_.addWidget(self.lbl_nav_target)
        self.lbl_nav_hint = hint_label()
        self.sec_target.layout_.addWidget(self.lbl_nav_hint)
        # v1.20: Button, der einen 3D-Film startet – in 3D oder 2D
        self.play_mode_row = QWidget()
        self.play_mode_row.setObjectName("section_row")
        pm = QHBoxLayout(self.play_mode_row)
        pm.setContentsMargins(0, 0, 0, 0)
        self.lbl_play_mode = QLabel()
        self.lbl_play_mode.setStyleSheet("color: #D4D4D8;")
        self.combo_play_mode = QComboBox()
        self.combo_play_mode.activated.connect(lambda _i: self._with_button(
            lambda m, b: self.controller.set_button_play_2d(m.id, b.id, self.combo_play_mode.currentData() == "2d")))
        pm.addWidget(self.lbl_play_mode, stretch=1)
        pm.addWidget(self.combo_play_mode, stretch=2)
        self.sec_target.layout_.addWidget(self.play_mode_row)
        self.target_film_row = QWidget()
        self.target_film_row.setObjectName("section_row")
        tf = QHBoxLayout(self.target_film_row)
        tf.setContentsMargins(0, 0, 0, 0)
        self.lbl_target_film = QLabel()
        self.lbl_target_film.setStyleSheet("color: #D4D4D8;")
        self.combo_target_film = QComboBox()
        self.combo_target_film.activated.connect(lambda _i: self._commit_target(film_changed=True))
        tf.addWidget(self.lbl_target_film, stretch=1)
        tf.addWidget(self.combo_target_film, stretch=2)
        self.sec_target.layout_.addWidget(self.target_film_row)
        self.target_item_row = QWidget()
        self.target_item_row.setObjectName("section_row")
        ti = QHBoxLayout(self.target_item_row)
        ti.setContentsMargins(0, 0, 0, 0)
        self.lbl_target_item = QLabel()
        self.lbl_target_item.setStyleSheet("color: #D4D4D8;")
        self.combo_target_item = QComboBox()
        self.combo_target_item.activated.connect(lambda _i: self._commit_target())
        ti.addWidget(self.lbl_target_item, stretch=1)
        ti.addWidget(self.combo_target_item, stretch=2)
        self.sec_target.layout_.addWidget(self.target_item_row)
        self.lbl_target_missing = QLabel()
        self.lbl_target_missing.setWordWrap(True)
        self.lbl_target_missing.setStyleSheet("color: #F87171;")
        self.sec_target.layout_.addWidget(self.lbl_target_missing)
        layout.addWidget(self.sec_target)

        self.sec_geometry = _Section("geometry")
        pos_row = QHBoxLayout()
        self.spin_x, self.spin_y = QSpinBox(), QSpinBox()
        self.spin_x.setRange(0, 1920)
        self.spin_y.setRange(0, 1080)
        self.lbl_pos = QLabel()
        self.lbl_pos.setStyleSheet("color: #D4D4D8;")
        pos_row.addWidget(self.lbl_pos, stretch=1)
        for prefix, spin in (("X", self.spin_x), ("Y", self.spin_y)):
            spin.setPrefix(f"{prefix} ")
            spin.setSuffix(" px")
            spin.editingFinished.connect(self._commit_position)
            pos_row.addWidget(spin)
        self.sec_geometry.layout_.addLayout(pos_row)
        # Größe des ausgewählten Buttons (v1.11.1); im Viewer auch mit den Griffen
        self.size_row = QWidget()
        self.size_row.setObjectName("section_row")
        size_layout = QHBoxLayout(self.size_row)
        size_layout.setContentsMargins(0, 0, 0, 0)
        self.lbl_btn_size = QLabel()
        self.lbl_btn_size.setStyleSheet("color: #D4D4D8;")
        self.spin_btn_w = QSpinBox()
        self.spin_btn_w.setRange(MIN_SIZE, 1920)
        self.lbl_btn_x = QLabel("×")
        self.spin_btn_h = QSpinBox()
        self.spin_btn_h.setRange(MIN_SIZE, 1080)
        for spin in (self.spin_btn_w, self.spin_btn_h):
            spin.setSuffix(" px")
            spin.editingFinished.connect(self._commit_button_size)
        self.btn_size_reset = small_button("↺", "")
        self.btn_size_reset.clicked.connect(self._reset_button_size)
        size_layout.addWidget(self.lbl_btn_size, stretch=1)
        for w in (self.spin_btn_w, self.lbl_btn_x, self.spin_btn_h, self.btn_size_reset):
            size_layout.addWidget(w)
        self.sec_geometry.layout_.addWidget(self.size_row)
        layout.addWidget(self.sec_geometry)

        self.sec_remote = _Section("remote", collapsed=True)
        self.dpad_rows = {}
        for direction in DIRECTIONS:
            row = QHBoxLayout()
            caption = QLabel()
            caption.setStyleSheet("color: #D4D4D8;")
            combo = QComboBox()
            combo.activated.connect(lambda _i, d=direction, c=combo: self._with_button(
                lambda m, b: self.controller.set_button_dpad(m.id, b.id, d, c.currentData() or None)))
            row.addWidget(caption, stretch=1)
            row.addWidget(combo, stretch=3)
            self.sec_remote.layout_.addLayout(row)
            self.dpad_rows[direction] = (caption, combo)
        layout.addWidget(self.sec_remote)

        # =====================================================================
        # Mehrere Buttons
        # =====================================================================
        self.card_multi = DropFrame()
        self.multi_film_row = QWidget()
        mf = QHBoxLayout(self.multi_film_row)
        mf.setContentsMargins(0, 0, 0, 0)
        self.lbl_multi_film = QLabel()
        self.lbl_multi_film.setStyleSheet("color: #D4D4D8;")
        self.combo_multi_film = QComboBox()
        self.combo_multi_film.activated.connect(self._commit_multi_film)
        mf.addWidget(self.lbl_multi_film, stretch=1)
        mf.addWidget(self.combo_multi_film, stretch=2)
        self.card_multi.layout_.addWidget(self.multi_film_row)
        # Lage und Größe für alle (v1.15.3): gleicher Wert steht da, unterschiedliche bleiben leer; Eintippen
        # setzt ihn für alle (X/Y: linke bzw. obere Kante, Breite/Höhe: jeder behält seine Mitte)
        geo_row = QHBoxLayout()
        self.multi_geo = {}
        for field in MULTI_GEO_FIELDS:
            caption = QLabel(field.upper() if field in ("x", "y") else "")
            caption.setStyleSheet("color: #D4D4D8;")
            edit = QLineEdit()
            edit.setValidator(QIntValidator(0, 1920, edit))
            edit.setPlaceholderText("–")
            edit.setAlignment(Qt.AlignRight)
            edit.setMinimumWidth(edit.fontMetrics().horizontalAdvance("00000") + 12)
            edit.editingFinished.connect(lambda f=field, e=edit: self._commit_multi_geo(f, e))
            geo_row.addWidget(caption)
            geo_row.addWidget(edit, stretch=1)
            self.multi_geo[field] = (caption, edit)
        self.card_multi.layout_.addLayout(geo_row)
        same_row = QHBoxLayout()
        self.btn_same_width = QPushButton()
        self.btn_same_width.clicked.connect(lambda: self._match_size(width=True, height=False))
        self.btn_same_height = QPushButton()
        self.btn_same_height.clicked.connect(lambda: self._match_size(width=False, height=True))
        same_row.addWidget(self.btn_same_width)
        same_row.addWidget(self.btn_same_height)
        same_row.addStretch(1)
        self.card_multi.layout_.addLayout(same_row)
        self.lbl_same_hint = hint_label()
        self.card_multi.layout_.addWidget(self.lbl_same_hint)
        align_row = QHBoxLayout()
        self.lbl_align = QLabel()
        self.lbl_align.setStyleSheet("color: #D4D4D8;")
        align_row.addWidget(self.lbl_align)
        self.align_buttons = {}
        for how, glyph in ALIGN_GLYPHS:
            btn = small_button(glyph, "")
            btn.clicked.connect(lambda _c=False, h=how: self._align(h))
            align_row.addWidget(btn)
            self.align_buttons[how] = btn
        align_row.addStretch(1)
        self.card_multi.layout_.addLayout(align_row)
        # Verteilen und als Raster anordnen (v1.14.1)
        dist_row = QHBoxLayout()
        self.lbl_distribute = QLabel()
        self.lbl_distribute.setStyleSheet("color: #D4D4D8;")
        self.btn_dist_h = QPushButton()
        self.btn_dist_h.clicked.connect(lambda: self._distribute(True))
        self.btn_dist_v = QPushButton()
        self.btn_dist_v.clicked.connect(lambda: self._distribute(False))
        for w in (self.lbl_distribute, self.btn_dist_h, self.btn_dist_v):
            dist_row.addWidget(w)
        dist_row.addStretch(1)
        self.card_multi.layout_.addLayout(dist_row)
        self.grid_box = _HoverBox()
        self.grid_box.hovered.connect(lambda on: self._preview_order(on, content_only=False))
        grid = QVBoxLayout(self.grid_box)
        grid.setContentsMargins(0, 6, 0, 0)
        self.lbl_grid = QLabel()
        self.lbl_grid.setStyleSheet("color: #D4D4D8; font-weight: bold;")
        grid.addWidget(self.lbl_grid)
        grid_row = QHBoxLayout()
        self.lbl_grid_cols = QLabel()
        self.lbl_grid_cols.setStyleSheet("color: #D4D4D8;")
        self.spin_grid_cols = QSpinBox()
        self.spin_grid_cols.setRange(1, 99)
        self.lbl_grid_gap = QLabel()
        self.lbl_grid_gap.setStyleSheet("color: #D4D4D8;")
        self.spin_gap_x, self.spin_gap_y = QSpinBox(), QSpinBox()
        for prefix, spin in (("↔ ", self.spin_gap_x), ("↕ ", self.spin_gap_y)):
            spin.setRange(0, 1000)
            spin.setPrefix(prefix)
            spin.setSuffix(" px")
        self.btn_grid = QPushButton()
        self.btn_grid.clicked.connect(self._arrange_grid)
        for w in (self.lbl_grid_cols, self.spin_grid_cols, self.lbl_grid_gap, self.spin_gap_x, self.spin_gap_y):
            grid_row.addWidget(w)
        grid_row.addStretch(1)
        grid.addLayout(grid_row)
        grid_button_row = QHBoxLayout()
        grid_button_row.addWidget(self.btn_grid)
        grid_button_row.addStretch(1)
        grid.addLayout(grid_button_row)
        self.card_multi.layout_.addWidget(self.grid_box)
        self._grid_key = None
        # Ziele der Reihe nach (v1.14): Inhalts-Buttons in Lesereihenfolge ab einem Ziel belegen
        self.seq_box = _HoverBox()
        self.seq_box.hovered.connect(self._preview_order)
        seq = QVBoxLayout(self.seq_box)
        seq.setContentsMargins(0, 6, 0, 0)
        self.lbl_seq = QLabel()
        self.lbl_seq.setStyleSheet("color: #D4D4D8; font-weight: bold;")
        seq.addWidget(self.lbl_seq)
        seq_row = QHBoxLayout()
        self.combo_seq_kind = QComboBox()
        self.combo_seq_kind.activated.connect(lambda _i: self._on_seq_changed(kind=self.combo_seq_kind.currentData()))
        self.combo_seq_film = QComboBox()
        self.combo_seq_film.activated.connect(lambda _i: self._on_seq_changed(film=self.combo_seq_film.currentData()))
        self.lbl_seq_from = QLabel()
        self.lbl_seq_from.setStyleSheet("color: #D4D4D8;")
        self.combo_seq_start = QComboBox()
        self.combo_seq_start.activated.connect(
            lambda _i: self._on_seq_changed(start=self.combo_seq_start.currentData()))
        for w in (self.combo_seq_kind, self.combo_seq_film, self.lbl_seq_from, self.combo_seq_start):
            seq_row.addWidget(w)
        seq_row.addStretch(1)
        seq.addLayout(seq_row)
        self.btn_seq_assign = QPushButton()
        self.btn_seq_assign.clicked.connect(self._assign_sequence)
        assign_row = QHBoxLayout()
        assign_row.addWidget(self.btn_seq_assign)
        self.lbl_seq_preview = hint_label()
        assign_row.addWidget(self.lbl_seq_preview, stretch=1)
        seq.addLayout(assign_row)
        self.card_multi.layout_.addWidget(self.seq_box)
        self._seq_key = None
        self._seq = {}
        self.btn_duplicate_many = QPushButton()
        self.btn_duplicate_many.clicked.connect(lambda: self.controller.duplicate_selection(self.node_id))
        self.btn_remove_many = QPushButton()
        self.btn_remove_many.clicked.connect(self._remove_selection)
        many_buttons = QHBoxLayout()
        many_buttons.addWidget(self.btn_duplicate_many)
        many_buttons.addWidget(self.btn_remove_many)
        many_buttons.addStretch(1)
        self.card_multi.layout_.addLayout(many_buttons)
        layout.addWidget(self.card_multi)

        layout.addStretch(1)
        # lange Einträge (Buttons mit Ziel, „Automatisch (→ …)“) dürfen den Inspektor nicht verbreitern
        for combo in self.findChildren(QComboBox):
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(6)
        self.menu_widgets = (self.card, self.card_content, self.card_bg, self.card_style)
        self.button_widgets = (self.sec_head, self.sec_target, self.sec_geometry, self.sec_remote)
        inspector.controller.selection_changed.connect(lambda *_a: self._on_selection())
        inspector.controller.button_selected.connect(lambda *_a: self._on_selection())

    # --- Auswahl ------------------------------------------------------------------
    def _menu(self):
        return self.controller.project.menu(self.node_id)

    def _selection(self):
        """(Menü, ausgewählte Buttons dieses Menüs in Button-Reihenfolge)."""
        menu = self._menu()
        if menu is None:
            return None, []
        ids = set(self.controller.selection_in(menu.id))
        return menu, [b for b in menu.buttons if b.id in ids]

    def _selected_button(self):
        """Der einzeln ausgewählte Button dieses Menüs oder (Menü, None)."""
        menu, buttons = self._selection()
        return menu, (buttons[0] if len(buttons) == 1 else None)

    def _with_button(self, action):
        menu, button = self._selected_button()
        if button is not None:
            action(menu, button)

    def _on_selection(self):
        if self.node_id is None or self.inspector.stack.currentWidget() is not self:
            return
        self.refresh()
        self.inspector._fit_height()

    # --- Menü ---------------------------------------------------------------------
    def _refresh_menu(self, project, menu):
        _set_text_if_idle(self.edit_name, menu.name)
        is_main = project.main_menu is not None and project.main_menu.id == menu.id
        self.lbl_main.setText(self.t("studio_menu_is_main") if is_main else "")
        self.lbl_main.setVisible(is_main)
        self.btn_make_main.setVisible(not is_main)
        self.film_row.setVisible(len(project.films) > 1)
        _fill_combo(self.combo_default_film, [("", self.t("studio_default_film_none"))] +
                    [(f.id, f.name) for f in project.films], menu.default_film_id)
        auto = menu.button(menu_design.auto_start_button_id(menu) or "")
        auto_text = self.t("studio_default_button_auto", name=self._button_title(project, menu, auto)) \
            if auto is not None else self.t("studio_default_button_first")
        _fill_combo(self.combo_default_button, [("", auto_text)] +
                    [(b.id, self._button_title(project, menu, b)) for b in menu.buttons], menu.default_button_id)

        from gui.node_editor.rows import content_films
        films = content_films(project, menu)
        self.card_content.setVisible(bool(films))
        if films:
            self.lbl_source.setText(self.t("studio_content_source", film=", ".join(f.name for f in films)))
            color = films[0].color if len(films) == 1 else "#D4D4D8"
            self.lbl_source.setStyleSheet(f"color: {color}; font-weight: bold;")

        from core.disc_adapter import effective_background
        follows = disc_edit.follows_main_background(project, menu)
        bg = effective_background(project, menu)
        for field, (_caption, value, pick, clear) in self.bg_rows.items():
            path = getattr(bg, field)
            show_file(value, path, self.t, "color: #71717A; font-style: italic;" if follows else "color: #A1A1AA;")
            clear.setVisible(not follows)
            clear.setEnabled(bool(path))
        if not self.spin_duration.hasFocus():
            self.spin_duration.setValue(int(round(bg.duration)))
        self.spin_duration.setEnabled(not follows)
        if is_main or project.main_menu is None:
            mode, hint = "", self.t("studio_bg_hint_main")
        elif follows:
            mode, hint = self.t("studio_bg_follows_main"), ""
        else:
            mode, hint = self.t("studio_bg_own"), ""
        self.lbl_bg_mode.setText(mode)
        self.lbl_bg_mode.setStyleSheet("color: #A1A1AA;" if follows else "color: #FCD34D; font-weight: bold;")
        self.lbl_bg_mode.setVisible(bool(mode))
        self.btn_bg_follow.setVisible(bool(mode) and not follows)
        self.lbl_bg_hint.setText(hint)
        self.lbl_bg_hint.setVisible(bool(hint))
        self._refresh_style(menu)

    @staticmethod
    def _button_title(project, menu, button) -> str:
        """„FILM STARTEN (→ Hauptfilm)“, „KAPITEL 3 (K3)“ – Beschriftung und Ziel in einer Zeile."""
        from core.disc_rules import target_marker
        label = button_label(project, menu, button)
        marker = target_marker(project, menu, button)
        return f"{label} ({marker})" if label else marker

    # --- Ein Button -----------------------------------------------------------------
    def _refresh_button(self, project, menu, button):
        from core.disc_rules import target_options, has_target
        from core import menu_layout
        self.lbl_selection.setText(self.t("studio_button_in_menu", name=self._button_title(project, menu, button),
                                          menu=menu.name))
        _fill_combo(self.combo_kind, [(k, self.t(f"studio_kind_{k}")) for k in BUTTON_KIND_ORDER], button.kind)
        _set_text_if_idle(self.edit_button_name, button_label(project, menu, button))
        auto = button.label is None if button.is_content else \
            button.label == disc_edit.button_label_for(project, button.target)
        self.btn_name_auto.setEnabled(not auto)

        nav = button.kind == BUTTON_NAV
        self.lbl_nav_target.setVisible(nav)
        self.lbl_nav_hint.setVisible(nav)
        self.target_film_row.setVisible(not nav and len(project.films) > 1)
        self.target_item_row.setVisible(not nav)
        play_mode = starts_3d_film(project, button)
        self.play_mode_row.setVisible(play_mode)
        if play_mode:
            _fill_combo(self.combo_play_mode, [("3d", "3D"), ("2d", "2D")], "2d" if button.play_2d else "3d")
        if nav:
            node = project.node(button.target)
            if node is not None:
                self.lbl_nav_target.setText(self.t("studio_target_nav", target=node.name))
                self.lbl_nav_target.setStyleSheet("color: #E4E4E7; font-weight: bold;")
            else:
                self.lbl_nav_target.setText(self.t("studio_target_nav", target=self.t("studio_unconnected")))
                self.lbl_nav_target.setStyleSheet("color: #FDE047; font-weight: bold;")
            self.lbl_target_missing.setVisible(False)
        else:
            film = project.film(button.film_id)
            _fill_combo(self.combo_target_film, [("", self.t("studio_target_none"))] +
                        [(f.id, f.name) for f in project.films], button.film_id)
            self.lbl_target_item.setText(self.t(f"studio_target_item_{button.kind}"))
            _fill_combo(self.combo_target_item, [("", self.t("studio_target_none"))] +
                        target_options(film, button.kind), button.content_ref)
            missing = not has_target(project, menu, button)
            self.lbl_target_missing.setVisible(missing)
            self.lbl_target_missing.setText(self.t("studio_target_missing"))

        x, y, w, h = menu_layout.button_box(menu, button)
        _set_spin(self.spin_x, x)
        _set_spin(self.spin_y, y)
        _set_spin(self.spin_btn_w, w)
        _set_spin(self.spin_btn_h, h)
        self.btn_size_reset.setEnabled(button.size is not None)

        targets = menu_design.dpad_targets(project, menu).get(button.id, {})
        others = [(b.id, self._button_title(project, menu, b)) for b in menu.buttons if b.id != button.id]
        for direction, (_caption, combo) in self.dpad_rows.items():
            auto_target = menu_design.auto_dpad_target(project, menu, button.id, direction)
            auto_name = self.t("studio_dpad_stay") if auto_target in (None, button.id) else \
                self._button_title(project, menu, menu.button(auto_target))
            entries = [("", self.t("studio_dpad_auto", target=auto_name)),
                       (button.id, self.t("studio_dpad_stay"))] + others
            _fill_combo(combo, entries, button.dpad.get(direction, ""))
            combo.setToolTip(self._button_title(project, menu, menu.button(targets[direction]))
                             if targets.get(direction) in [b.id for b in menu.buttons] else "")

    def _commit_button_name(self):
        menu, button = self._selected_button()
        if button is None:
            return
        text = self.edit_button_name.text().strip()
        if not text:
            self.edit_button_name.setText(button_label(self.controller.project, menu, button))
            return
        if text != button_label(self.controller.project, menu, button):
            self.controller.rename_button(menu.id, button.id, text)

    def _commit_target(self, film_changed: bool = False):
        menu, button = self._selected_button()
        if button is None or not button.is_content:
            return
        film_id = (self.combo_target_film.currentData() or None) if len(self.controller.project.films) > 1 else button.film_id
        if film_id is None and len(self.controller.project.films) == 1:
            film_id = self.controller.project.films[0].id
        if film_changed:
            # neuer Film: das Ziel wandert mit seiner Nummer (Kapitel 3 → Kapitel 3 des anderen Films)
            if film_id is not None:
                self.controller.set_buttons_film(menu.id, [button.id], film_id)
            else:
                self.controller.set_button_content(menu.id, button.id, None, None)
            return
        self.controller.set_button_content(menu.id, button.id, film_id, self.combo_target_item.currentData() or None)

    def _commit_position(self):
        menu, button = self._selected_button()
        if button is not None and [self.spin_x.value(), self.spin_y.value()] != button.position:
            self.controller.move_menu_items(menu.id, positions={button.id: (self.spin_x.value(), self.spin_y.value())})

    def _commit_button_size(self):
        menu, button = self._selected_button()
        if button is not None:
            self.controller.resize_menu_items(menu.id, {button.id: (self.spin_btn_w.value(), self.spin_btn_h.value())})

    def _reset_button_size(self):
        menu, button = self._selected_button()
        if button is not None:
            self.controller.clear_button_sizes(menu.id, [button.id])

    # --- Mehrere Buttons ------------------------------------------------------------
    def _refresh_multi(self, project, menu, buttons):
        self.lbl_selection.setText(self.t("studio_buttons_selected", n=len(buttons), menu=menu.name))
        content = [b for b in buttons if b.is_content]
        self.multi_film_row.setVisible(bool(content) and len(project.films) > 1)
        films = {b.film_id for b in content}
        current = next(iter(films)) if len(films) == 1 else None
        _fill_combo(self.combo_multi_film, [("", self.t("studio_multi_film_mixed"))] +
                    [(f.id, f.name) for f in project.films], current)
        from core import menu_layout
        boxes = [menu_layout.button_box(menu, b) for b in buttons]
        for i, field in enumerate(MULTI_GEO_FIELDS):
            values = {box[i] for box in boxes}
            _set_text_if_idle(self.multi_geo[field][1], str(next(iter(values))) if len(values) == 1 else "")
        primary = menu.button(self.controller.selected_button[1]) or buttons[0]
        self.lbl_same_hint.setText(self.t("studio_same_size_hint", name=self._button_title(project, menu, primary)))
        self.btn_remove_many.setText(self.t("studio_remove_buttons", n=len(buttons)))
        self._refresh_sequence(project, menu, buttons)
        self.btn_dist_h.setEnabled(len(buttons) >= 3)
        self.btn_dist_v.setEnabled(len(buttons) >= 3)
        key = (menu.id, tuple(b.id for b in buttons))
        if key != self._grid_key:
            # Vorschlag nur bei neuer Auswahl, damit eigene Eingaben stehen bleiben
            from core import menu_tools
            self._grid_key = key
            cols, gap_x, gap_y = menu_tools.grid_defaults(menu, [b.id for b in buttons])
            for spin, value in ((self.spin_grid_cols, cols), (self.spin_gap_x, gap_x), (self.spin_gap_y, gap_y)):
                spin.setValue(value)

    def _commit_multi_geo(self, field: str, edit: QLineEdit):
        """Wert für alle ausgewählten Buttons setzen (ein Rückgängig-Schritt); leer = nichts ändern."""
        from core import menu_layout
        menu, buttons = self._selection()
        text = edit.text().strip()
        if menu is None or len(buttons) < 2 or not text.isdigit():
            return
        value = int(text)
        boxes = {b.id: menu_layout.button_box(menu, b) for b in buttons}
        if field in ("x", "y"):
            positions = {bid: (value, y) if field == "x" else (x, value) for bid, (x, y, _w, _h) in boxes.items()}
            if any((x, y) != positions[bid] for bid, (x, y, _w, _h) in boxes.items()):
                self.controller.move_menu_items(menu.id, positions=positions)
        else:
            value = max(MIN_SIZE, value)
            sizes = {bid: (value, h) if field == "w" else (w, value) for bid, (_x, _y, w, h) in boxes.items()}
            self.controller.resize_menu_items(menu.id, sizes)

    # --- Verteilen, Raster (v1.14.1) -----------------------------------------------------
    def _distribute(self, horizontal: bool):
        menu, buttons = self._selection()
        if menu is not None and len(buttons) >= 3:
            self.controller.distribute_buttons(menu.id, [b.id for b in buttons], horizontal)

    def _arrange_grid(self):
        menu, buttons = self._selection()
        if menu is not None and len(buttons) >= 2:
            self.controller.arrange_grid(menu.id, [b.id for b in buttons], self.spin_grid_cols.value(),
                                         self.spin_gap_x.value(), self.spin_gap_y.value())

    # --- Ziele der Reihe nach (v1.14) ---------------------------------------------------
    def _seq_defaults(self, project, menu, buttons) -> dict:
        """Vorschlag: häufigster Inhaltstyp der Auswahl, ihr Film (sonst Standard-Film), Ziel des ersten
        Buttons in Lesereihenfolge (sonst das erste)."""
        from core import menu_tools
        content = [b for b in buttons if b.is_content]
        kinds = [b.kind for b in content]
        kind = max(SEQ_KINDS, key=kinds.count) if kinds else BUTTON_CHAPTER
        films = {b.film_id for b in content if project.film(b.film_id)}
        film = next(iter(films)) if len(films) == 1 else None
        if film is None:
            default = disc_edit.default_film(project, menu)
            film = default.id if default else (project.films[0].id if project.films else None)
        ordered = menu_tools.reading_order(menu, content)
        sequence = menu_tools.target_sequence(project.film(film), kind)
        start = ordered[0].content_ref if ordered and ordered[0].kind == kind else None
        return {"kind": kind, "film": film, "start": start if start in sequence else (sequence or [None])[0]}

    def _refresh_sequence(self, project, menu, buttons):
        from core import menu_tools
        from core.disc_rules import target_options
        key = (menu.id, tuple(b.id for b in buttons))
        if key != self._seq_key:
            self._seq_key, self._seq = key, self._seq_defaults(project, menu, buttons)
        state = self._seq
        if project.film(state["film"]) is None and project.films:
            state["film"] = project.films[0].id
        sequence = menu_tools.target_sequence(project.film(state["film"]), state["kind"])
        if state["start"] not in sequence:
            state["start"] = sequence[0] if sequence else None
        _fill_combo(self.combo_seq_kind, [(k, self.t(f"studio_kind_{k}")) for k in SEQ_KINDS], state["kind"])
        _fill_combo(self.combo_seq_film, [(f.id, f.name) for f in project.films], state["film"])
        self.combo_seq_film.setVisible(len(project.films) > 1)
        options = dict(target_options(project.film(state["film"]), state["kind"]))
        _fill_combo(self.combo_seq_start, [(ref, options.get(ref, ref)) for ref in sequence], state["start"])

        plan = menu_tools.sequence_plan(project, menu, [b.id for b in buttons], state["kind"], state["film"],
                                        state["start"])
        self.btn_seq_assign.setEnabled(bool(plan) and bool(sequence))
        self.lbl_seq_preview.setText(self._sequence_text(project, menu, buttons, plan))

    def _sequence_text(self, project, menu, buttons, plan) -> str:
        """„8 Buttons → K5–K12 · 2 bleiben ohne Ziel · 1 Navigations-Button bleibt“."""
        from core.disc_model import MenuButton
        from core.disc_rules import target_marker
        if not plan:
            return self.t("studio_seq_no_content")
        state = self._seq

        def marker(ref):
            return target_marker(project, menu, MenuButton(id="", kind=state["kind"], film_id=state["film"],
                                                           content_ref=ref))

        refs = [ref for _b, ref in plan if ref is not None]
        parts = []
        if refs:
            span = marker(refs[0]) if len(refs) == 1 else f"{marker(refs[0])}–{marker(refs[-1])}"
            parts.append(self.t("studio_seq_preview", n=len(plan), span=span))
        rest = len(plan) - len(refs)
        if rest:
            parts.append(self.t("studio_seq_rest", n=rest))
        nav = sum(1 for b in buttons if not b.is_content)
        if nav:
            parts.append(self.t("studio_seq_nav", n=nav))
        return " · ".join(parts)

    def _on_seq_changed(self, **change):
        self._seq.update(change)
        if "kind" in change or "film" in change:
            self._seq["start"] = None          # neuer Typ/Film: ab dem ersten Ziel
        menu, buttons = self._selection()
        if menu is not None and buttons:
            self._refresh_sequence(self.controller.project, menu, buttons)

    def _preview_order(self, on: bool, content_only: bool = True):
        """Reihenfolge als Nummern im Viewer, solange die Maus über „Ziele der Reihe nach“ (nur Inhalts-Buttons)
        bzw. „Als Raster“ (alle) ist."""
        from core import menu_tools
        menu, buttons = self._selection()
        if menu is None:
            return
        chosen = [b for b in buttons if b.is_content or not content_only]
        ordered = menu_tools.reading_order(menu, chosen) if on else []
        self.controller.order_preview.emit(menu.id, [b.id for b in ordered])

    def _assign_sequence(self):
        menu, buttons = self._selection()
        if menu is None or not buttons:
            return
        state = dict(self._seq)
        self.controller.assign_sequence(menu.id, [b.id for b in buttons], state["kind"], state["film"],
                                        state["start"])

    def _commit_multi_film(self, _index=None):
        menu, buttons = self._selection()
        film_id = self.combo_multi_film.currentData()
        if menu is not None and film_id:
            self.controller.set_buttons_film(menu.id, [b.id for b in buttons], film_id)

    def _match_size(self, width: bool, height: bool):
        menu, buttons = self._selection()
        if menu is None or len(buttons) < 2:
            return
        primary = self.controller.selected_button[1]
        reference = primary if menu.button(primary) in buttons else buttons[0].id
        self.controller.match_button_sizes(menu.id, [b.id for b in buttons], reference, width, height)

    def _align(self, how: str):
        menu, buttons = self._selection()
        if menu is not None and len(buttons) > 1:
            self.controller.align_buttons(menu.id, [b.id for b in buttons], how)

    def _remove_selection(self):
        menu, buttons = self._selection()
        if menu is not None and buttons:
            self.controller.remove_buttons(menu.id, [b.id for b in buttons])

    # --- Stil, Hintergrund ------------------------------------------------------------
    def _refresh_style(self, menu):
        style = menu.button_style
        self.switch_style.set_value(style.kind)
        self.lbl_style_desc.setText(self.t(f"studio_style_{style.kind}_desc"))
        index = self.combo_shape.findData(style.shape)
        if index >= 0 and self.combo_shape.currentIndex() != index:
            self.combo_shape.setCurrentIndex(index)
        self.shape_box.setVisible(style.kind == STYLE_SHAPE)
        for spin, value in ((self.spin_shape_w, style.width), (self.spin_shape_h, style.height)):
            if not spin.hasFocus():
                spin.setValue(value)
        for state, (_caption, swatch, opacity) in self.state_rows.items():
            swatch.set_color(getattr(style, f"color_{state}"))
            if not opacity.hasFocus():
                opacity.setValue(getattr(style, f"opacity_{state}"))
            hex_edit = self.color_tools[state][0]
            if not hex_edit.hasFocus():
                hex_edit.setText(getattr(style, f"color_{state}").upper())

    # --- Eigene Farben (v1.14.4) -------------------------------------------------------
    def _show_style_card(self):
        """„Form & Farben …“ (v1.14.5): Button-Auswahl aufheben und zur Karte Button-Stil des Menüs springen."""
        self.controller.select_button(None, None)
        QTimer.singleShot(0, lambda: self.inspector.ensureWidgetVisible(self.card_style, 0, 0))

    def _color_sections(self):
        """Zusätzliche Abschnitte im Farbmenü: im Projekt benutzte Farben, Hauptfarben des Hintergrunds."""
        from core import color_tools
        from core.disc_adapter import effective_background
        from modules.sim_disc import menu_still
        project = self.controller.project
        menu = self._menu()
        if menu is None:
            return []
        bg = effective_background(project, menu)
        return [(self.t("studio_colors_recent"), color_tools.project_colors(project)),
                (self.t("studio_colors_background"), color_tools.dominant_colors(menu_still(bg.image, bg.video)))]

    def _commit_hex(self, state: str, edit: QLineEdit):
        from core.color_tools import parse_hex
        menu = self._menu()
        if menu is None:
            return
        current = getattr(menu.button_style, f"color_{state}").upper()
        color = parse_hex(edit.text())
        if color is None:
            if edit.text().strip() and edit.text().strip().upper() != current:
                self.inspector.status(self.t("studio_color_hex_invalid", text=edit.text().strip()))
            edit.setText(current)
            return
        edit.setText(color)
        if color != current:
            self.controller.set_button_style(self.node_id, **{f"color_{state}": color})

    def _make_main(self):
        from core.disc_rules import Source
        self.controller.connect(Source.start(), self.node_id)

    def _pick_background(self, field: str, file_filter: str):
        path, _ = QFileDialog.getOpenFileName(self, "", "", tr_file_filter(file_filter))
        if path:
            self.set_background_file(field, path)

    def _drop_background(self, files: list):
        from gui.studio.backgrounds import apply_background_files
        for name in apply_background_files(self.controller, self.node_id, files):
            self.inspector.status(self.t("studio_bg_unsupported", name=name))

    def set_background_file(self, field: str, path: str):
        """Setzt Bild, Video oder Musik; bei Video/Musik wird die Loop-Dauer wie bisher übernommen."""
        from gui.studio.backgrounds import set_background_file
        set_background_file(self.controller, self.node_id, field, path)

    def _commit_duration(self):
        self.controller.set_menu_background(self.node_id, "Loop-Dauer ändern",
                                            duration=float(self.spin_duration.value()))

    # --- Aufbau nach Auswahl -----------------------------------------------------------
    def refresh(self):
        project = self.controller.project
        menu, buttons = self._selection()
        if menu is None:
            return
        self.retranslate()
        self.mode = MODE_MENU if not buttons else (MODE_BUTTON if len(buttons) == 1 else MODE_MULTI)
        for w in self.menu_widgets:
            w.setVisible(self.mode == MODE_MENU)
        for w in self.button_widgets:
            w.setVisible(self.mode == MODE_BUTTON)
        self.card_multi.setVisible(self.mode == MODE_MULTI)
        self.selection_bar.setVisible(self.mode != MODE_MENU)
        self.style_bar.setVisible(self.mode != MODE_MENU)
        if self.mode == MODE_MENU:
            self._refresh_menu(project, menu)
            return
        self.switch_look.set_value(menu.button_style.kind)
        self.lbl_look_hint.setText(self.t("studio_look_hint", menu=menu.name))
        if self.mode == MODE_BUTTON:
            self._refresh_button(project, menu, buttons[0])
        else:
            self._refresh_multi(project, menu, buttons)

    def retranslate(self):
        self.btn_back.setText(self.t("studio_back_to_menu"))
        self.card.set_title(self.t("studio_menu"))
        self.btn_make_main.setText(self.t("studio_menu_make_main"))
        self.lbl_default_film.setText(self.t("studio_menu_default_film"))
        self.lbl_default_button.setText(self.t("studio_default_button"))
        self.card_content.set_title(self.t("studio_section_content"))
        self.card_bg.set_title(self.t("studio_section_background"))
        self.btn_bg_follow.setText(self.t("studio_bg_follow_main"))
        self.btn_bg_follow.setToolTip(self.t("studio_bg_follow_main_tip"))
        for field, (caption, _value, pick, clear) in self.bg_rows.items():
            caption.setText(self.t(f"studio_bg_{field}"))
            pick.setText(self.t("studio_choose"))
            clear.setToolTip(self.t("studio_remove"))
        self.lbl_duration.setText(self.t("studio_bg_duration"))
        self.spin_duration.setToolTip(self.t("studio_bg_duration_tip"))
        self.spin_duration.setSuffix(" s")
        self.card_style.set_title(self.t("studio_section_style"))
        texts = {k: self.t(f"studio_style_{k}_short") for k in STYLE_KINDS}
        tips = {k: self.t(f"studio_style_{k}") for k in STYLE_KINDS}
        for switch in (self.switch_style, self.switch_look):
            switch.set_texts(texts, tips)
        self.lbl_look.setText(self.t("studio_look"))
        self.btn_look_more.setText(self.t("studio_look_more").replace("&", "&&"))   # kein Tastenkürzel
        self.btn_look_more.setToolTip(self.t("studio_look_more_tip"))
        for i, shape in enumerate(SHAPES):
            self.combo_shape.setItemText(i, self.t(f"studio_shape_{shape}"))
        self.lbl_shape_w.setText(self.t("studio_shape_width"))
        self.lbl_shape_h.setText(self.t("studio_shape_height"))
        self.spin_shape_w.setSuffix(" px")
        self.spin_shape_h.setSuffix(" px")
        for state, (caption, swatch, opacity) in self.state_rows.items():
            caption.setText(self.t(f"studio_state_{state}"))
            swatch.act_custom.setText(self.t("studio_color_more"))
            opacity.setToolTip(self.t("studio_shape_opacity_tip"))
            hex_edit, pipette = self.color_tools[state]
            hex_edit.setToolTip(self.t("studio_color_hex_tip"))
            pipette.setToolTip(self.t("studio_color_pipette_tip"))
        # ein Button
        self.sec_head.set_title(self.t("studio_section_button"))
        self.lbl_kind.setText(self.t("studio_button_kind"))
        self.lbl_button_name.setText(self.t("studio_button_label"))
        self.btn_name_auto.setToolTip(self.t("studio_button_name_auto"))
        self.btn_remove_button.setText(self.t("studio_remove_button"))
        self.btn_duplicate.setText(self.t("studio_duplicate"))
        self.btn_duplicate_many.setText(self.t("studio_duplicate"))
        self.lbl_seq.setText(self.t("studio_seq_title"))
        self.lbl_distribute.setText(self.t("studio_distribute"))
        self.btn_dist_h.setText(self.t("studio_distribute_h"))
        self.btn_dist_v.setText(self.t("studio_distribute_v"))
        for btn in (self.btn_dist_h, self.btn_dist_v):
            btn.setToolTip(self.t("studio_distribute_tip"))
        self.lbl_grid.setText(self.t("studio_grid_title"))
        self.lbl_grid_cols.setText(self.t("studio_grid_cols"))
        self.lbl_grid_gap.setText(self.t("studio_grid_gap"))
        self.btn_grid.setText(self.t("studio_grid_apply"))
        self.lbl_seq_from.setText(self.t("studio_seq_from"))
        self.btn_seq_assign.setText(self.t("studio_seq_assign"))
        self.sec_target.set_title(self.t("studio_section_target"))
        self.lbl_nav_hint.setText(self.t("studio_target_nav_hint"))
        self.lbl_target_film.setText(self.t("studio_target_film"))
        self.lbl_play_mode.setText(self.t("studio_play_mode"))
        self.play_mode_row.setToolTip(self.t("studio_play_mode_hint"))
        self.sec_geometry.set_title(self.t("studio_section_geometry"))
        self.lbl_pos.setText(self.t("studio_position"))
        self.lbl_btn_size.setText(self.t("studio_button_size"))
        self.btn_size_reset.setToolTip(self.t("studio_button_size_reset"))
        self.sec_remote.set_title(self.t("studio_section_remote"))
        for direction, (caption, _combo) in self.dpad_rows.items():
            caption.setText(self.t(f"studio_dir_{direction}"))
        # mehrere Buttons
        self.card_multi.set_title(self.t("studio_section_selection"))
        self.lbl_multi_film.setText(self.t("studio_multi_film"))
        self.btn_same_width.setText(self.t("studio_same_width"))
        self.btn_same_height.setText(self.t("studio_same_height"))
        self.lbl_align.setText(self.t("studio_align"))
        for field, (caption, edit) in self.multi_geo.items():
            caption.setText(self.t(f"studio_geo_{field}"))
            edit.setToolTip(self.t(f"studio_geo_{field}_tip"))
        for how, btn in self.align_buttons.items():
            btn.setToolTip(self.t(f"studio_align_{how}"))


# -------------------------------------------------------------------------
# Rahmen (v1.15.1)
# -------------------------------------------------------------------------

class FramePage(_Page):
    """Ausgewählter Rahmen im Node-Editor: Name, Farbe, löschen (die Knoten bleiben)."""

    def __init__(self, inspector):
        from core.node_frames import FRAME_COLORS
        super().__init__(inspector)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.card = DropFrame()
        self.edit_name = QLineEdit()
        self.edit_name.editingFinished.connect(self._commit_name)
        self.btn_color = ColorSwatchButton(list(FRAME_COLORS))
        self.btn_color.color_chosen.connect(
            lambda color: self.controller.set_frame(self.node_id, "Rahmenfarbe ändern", color=color))
        name_row = QHBoxLayout()
        name_row.addWidget(self.edit_name, stretch=1)
        name_row.addWidget(self.btn_color)
        self.card.layout_.addLayout(name_row)
        self.btn_delete = QPushButton()
        self.btn_delete.clicked.connect(lambda: self.controller.remove_frames([self.node_id]))
        self.card.layout_.addWidget(self.btn_delete, alignment=Qt.AlignLeft)
        layout.addWidget(self.card)
        layout.addStretch(1)

    def _group(self):
        from core.node_frames import frame
        return frame(self.controller.project, self.node_id)

    def _commit_name(self):
        group = self._group()
        name = self.edit_name.text().strip()
        if group is None:
            return
        if not name:
            self.edit_name.setText(group.name)
        elif name != group.name:
            self.controller.set_frame(self.node_id, "Rahmen umbenennen", name=name)

    def refresh(self):
        group = self._group()
        if group is None:
            return
        self.retranslate()
        _set_text_if_idle(self.edit_name, group.name)
        self.btn_color.set_color(group.color)
        self.card.title_label.setStyleSheet(
            f"font-size: 12px; font-weight: bold; color: {group.color}; letter-spacing: 1px;")

    def retranslate(self):
        self.card.set_title(self.t("studio_frame"))
        self.btn_color.setToolTip(self.t("studio_frame_color_tip"))
        self.btn_color.act_custom.setText(self.t("studio_film_color_custom"))
        self.btn_delete.setText(self.t("studio_frame_delete"))


# -------------------------------------------------------------------------
# Panel
# -------------------------------------------------------------------------

class _PageSwitcher(QWidget):
    """
    Zeigt genau eine Seite. Anders als QStackedWidget zählt für die Höhe nur die sichtbare
    Seite, damit der Scrollbereich den Inhalt nicht staucht.
    """

    def __init__(self):
        super().__init__()
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._pages = []
        self._current = None

    def addWidget(self, page: QWidget):
        page.hide()
        self._pages.append(page)
        self._layout.addWidget(page)

    def setCurrentWidget(self, page: QWidget):
        for p in self._pages:
            p.setVisible(p is page)
        self._current = page

    def currentWidget(self) -> Optional[QWidget]:
        return self._current


class InspectorPanel(QScrollArea):
    node_requested = Signal(str)   # Knoten auswählen (z. B. ein gerade angelegtes Menü)

    def __init__(self, controller: GraphController, importer: FilmImporter, status: Callable[[str], None], parent=None):
        super().__init__(parent)
        self.controller = controller
        self.importer = importer
        self.status = status
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMinimumWidth(380)

        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(14, 14, 14, 14)
        self.stack = _PageSwitcher()
        outer.addWidget(self.stack)
        outer.addStretch(1)
        self.setWidget(container)

        self.empty = QWidget()
        empty_layout = QVBoxLayout(self.empty)
        self.lbl_empty = hint_label()
        self.lbl_empty.setAlignment(Qt.AlignCenter)
        empty_layout.addStretch(1)
        empty_layout.addWidget(self.lbl_empty)
        empty_layout.addStretch(2)
        self.start_page = StartPage(self)
        self.film_page = FilmPage(self)
        self.menu_page = MenuPage(self)
        self.frame_page = FramePage(self)
        for page in (self.empty, self.start_page, self.film_page, self.menu_page, self.frame_page):
            self.stack.addWidget(page)

        self.current_id: Optional[str] = None
        controller.changed.connect(self.refresh)
        self.show_node(None)

    def show_node(self, node_id: Optional[str]):
        self.current_id = node_id
        project = self.controller.project
        if node_id == START_NODE_ID:
            page = self.start_page
        elif project.film(node_id):
            page = self.film_page
        elif project.menu(node_id):
            page = self.menu_page
        elif node_id and node_frames.frame(project, node_id) is not None:
            page = self.frame_page                  # Rahmen im Node-Editor (v1.15.1)
        else:
            self.current_id = None
            self.lbl_empty.setText(tr("studio_inspector_empty", ui_language()))
            self.stack.setCurrentWidget(self.empty)
            return
        page.load(node_id)
        self.stack.setCurrentWidget(page)
        self._fit_height()

    def _fit_height(self):
        """Mindesthöhe = natürliche Höhe der sichtbaren Seite; der Rest wird gescrollt."""
        page = self.stack.currentWidget()
        if page is not None:
            page.adjustSize()
            self.widget().setMinimumHeight(page.sizeHint().height() + 28)

    def refresh(self):
        # Knoten kann durch Löschen oder Rückgängig verschwunden sein
        self.show_node(self.current_id)

    def show_compliance(self, film_id: str):
        film = self.controller.project.film(film_id)
        if film is None or not film.compliance_warnings:
            return
        from gui.widgets.compliance_dialog import ComplianceWarningDialog
        dlg = ComplianceWarningDialog(
            title_name=film.name,
            video_filename=os.path.basename(film.video_base) if film.video_base else "Video",
            warnings=film.compliance_warnings,
            lang=ui_language(),
            parent=self,
        )
        if dlg.exec():
            self.controller.set_film_fields(film_id, "Hinweise bestätigen", warnings_acknowledged=True)
