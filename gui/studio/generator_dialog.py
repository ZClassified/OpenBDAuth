# gui/studio/generator_dialog.py
"""
Fenster des Generators (v1.14.2): Typ, Film, Bereich von–bis, Spalten und Zeilen pro Seite. Darunter in
Klartext, was entsteht („30 Buttons: 24 auf dieser Seite, 6 auf einer neuen Seite ‚Kapitel 2/2‘“), und ob
die Grenzen des Menüstroms reichen. Angelegt wird erst mit „Anlegen“ (ein Rückgängig-Schritt).
"""

import copy

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox, QSpinBox, QCheckBox, QDialogButtonBox,
)

from core import menu_generator
from core.disc_rules import target_options
from core.menu_generator import GeneratorSettings, GENERATOR_KINDS, MAX_BUTTONS_PER_PAGE, PAGE_NAV
from core.menu_tools import target_sequence
from core.translations import tr, ui_language

MIB = 1024 * 1024


class GeneratorDialog(QDialog):
    def __init__(self, controller, menu_id: str, settings: GeneratorSettings, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.menu_id = menu_id
        self._settings = copy.deepcopy(settings)
        self.setWindowTitle(self.t("gen_title"))
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)

        grid = QGridLayout()
        self.combo_kind = QComboBox()
        for kind in GENERATOR_KINDS:
            self.combo_kind.addItem(self.t(f"studio_kind_{kind}"), kind)
        self.combo_film = QComboBox()
        for film in controller.project.films:
            self.combo_film.addItem(film.name, film.id)
        self.combo_first, self.combo_last = QComboBox(), QComboBox()
        self.chk_missing = QCheckBox(self.t("gen_only_missing"))
        self.spin_cols, self.spin_rows = QSpinBox(), QSpinBox()
        for spin in (self.spin_cols, self.spin_rows):
            spin.setRange(1, MAX_BUTTONS_PER_PAGE - PAGE_NAV)
        self.lbl_film = QLabel(self.t("gen_film"))
        rows = [(QLabel(self.t("gen_kind")), self.combo_kind), (self.lbl_film, self.combo_film),
                (QLabel(self.t("gen_from")), self.combo_first), (QLabel(self.t("gen_to")), self.combo_last)]
        for r, (label, widget) in enumerate(rows):
            grid.addWidget(label, r, 0)
            grid.addWidget(widget, r, 1)
        grid.addWidget(self.chk_missing, len(rows), 1)
        size_row = QHBoxLayout()
        size_row.addWidget(self.spin_cols)
        size_row.addWidget(QLabel(self.t("gen_cols")))
        size_row.addSpacing(16)
        size_row.addWidget(self.spin_rows)
        size_row.addWidget(QLabel(self.t("gen_rows")))
        size_row.addStretch(1)
        grid.addWidget(QLabel(self.t("gen_per_page")), len(rows) + 1, 0)
        grid.addLayout(size_row, len(rows) + 1, 1)
        layout.addLayout(grid)

        self.lbl_summary = QLabel()
        self.lbl_summary.setWordWrap(True)
        self.lbl_summary.setStyleSheet("color: #E4E4E7; font-weight: bold; padding-top: 8px;")
        layout.addWidget(self.lbl_summary)
        self.lbl_notes = QLabel()
        self.lbl_notes.setWordWrap(True)
        self.lbl_notes.setStyleSheet("color: #A1A1AA;")
        layout.addWidget(self.lbl_notes)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText(self.t("gen_create"))
        self.buttons.button(QDialogButtonBox.Cancel).setText(self.t("gen_cancel"))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self._load()
        self.combo_kind.activated.connect(lambda _i: self._changed(kind=self.combo_kind.currentData()))
        self.combo_film.activated.connect(lambda _i: self._changed(film_id=self.combo_film.currentData()))
        self.combo_first.activated.connect(lambda _i: self._changed(first_ref=self.combo_first.currentData()))
        self.combo_last.activated.connect(lambda _i: self._changed(last_ref=self.combo_last.currentData()))
        self.chk_missing.toggled.connect(lambda on: self._changed(only_missing=on))
        self.spin_cols.valueChanged.connect(lambda v: self._changed(cols=v))
        self.spin_rows.valueChanged.connect(lambda v: self._changed(rows=v))

    def t(self, key: str, **kwargs) -> str:
        text = tr(key, ui_language())
        return text.format(**kwargs) if kwargs else text

    def settings(self) -> GeneratorSettings:
        return copy.deepcopy(self._settings)

    # --- Anzeige ----------------------------------------------------------------------
    def _load(self):
        s = self._settings
        project = self.controller.project
        for combo, value in ((self.combo_kind, s.kind), (self.combo_film, s.film_id)):
            combo.blockSignals(True)
            combo.setCurrentIndex(max(0, combo.findData(value)))
            combo.blockSignals(False)
        self.lbl_film.setVisible(len(project.films) > 1)
        self.combo_film.setVisible(len(project.films) > 1)
        film = project.film(s.film_id)
        labels = dict(target_options(film, s.kind))
        sequence = target_sequence(film, s.kind)
        for combo, value in ((self.combo_first, s.first_ref), (self.combo_last, s.last_ref)):
            combo.blockSignals(True)
            combo.clear()
            for ref in sequence:
                combo.addItem(labels.get(ref, ref), ref)
            combo.setCurrentIndex(max(0, combo.findData(value)))
            combo.blockSignals(False)
        for widget, value in ((self.chk_missing, s.only_missing), (self.spin_cols, s.cols), (self.spin_rows, s.rows)):
            widget.blockSignals(True)
            if isinstance(widget, QCheckBox):
                widget.setChecked(value)
            else:
                widget.setValue(value)
            widget.blockSignals(False)
        self._update_summary()

    def _changed(self, **change):
        s = self._settings
        for key, value in change.items():
            setattr(s, key, value)
        if "kind" in change or "film_id" in change:
            sequence = target_sequence(self.controller.project.film(s.film_id), s.kind)
            s.first_ref = sequence[0] if sequence else None
            s.last_ref = sequence[-1] if sequence else None
        self._load()

    def _update_summary(self):
        project = self.controller.project
        menu = project.menu(self.menu_id)
        s = self._settings
        result = menu_generator.plan(project, menu, s)
        ok = self.buttons.button(QDialogButtonBox.Ok)
        notes = []
        if not result.refs:
            self.lbl_summary.setText(self.t("gen_nothing"))
            ok.setEnabled(False)
            self.lbl_notes.setText("")
            return
        here = len(result.chunks[0])
        if result.new_pages == 0:
            text = self.t("gen_summary_one", n=len(result.refs))
        else:
            names = ", ".join(f"„{name}“" for name in result.page_names[1:])
            key = "gen_summary_pages_one" if result.new_pages == 1 else "gen_summary_pages"
            text = self.t(key, n=len(result.refs), here=here, rest=len(result.refs) - here,
                          pages=result.new_pages, names=names)
        self.lbl_summary.setText(text)
        taken = s.capacity - len(menu_generator.free_cells(menu, s))
        if taken:
            notes.append(self.t("gen_note_taken", n=taken))
        if result.new_pages:
            notes.append(self.t("gen_note_pages", name=result.page_names[0]))
        blocked = result.over_page_limit
        if blocked:
            notes.append(self.t("gen_note_page_limit", max=MAX_BUTTONS_PER_PAGE, grid=MAX_BUTTONS_PER_PAGE - PAGE_NAV))
        if result.over_graphics_budget:
            notes.append(self.t("gen_note_graphics", mb=result.graphics_bytes / MIB,
                                budget=menu_generator.GRAPHICS_BUDGET // MIB))
        self.lbl_notes.setText("\n".join(notes))
        ok.setEnabled(not blocked)
