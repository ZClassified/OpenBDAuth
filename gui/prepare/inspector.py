# gui/prepare/inspector.py
"""
Inspektor des Arbeitsbereichs Vorbereiten (v1.22): Einstellungen der markierten Aufträge in denselben
aufklappbaren Abschnitten wie Film- und Menü-Inspektor (Konzept, „Oberfläche neu im Studio-Design“).

- Kopf: Quelle, Kenndaten, erkanntes 3D-Format, Fortschritt; „Passt so“ (v1.23)
- Video: Art 2D/3D, Bitrate, Auflösung, PsF, Bildraten-Anpassung
- Ton: Spur und Format
- Ziel: Ausgabeordner, Dateien, Film als Vorschlag
- Ergebnis: fertige Dateien, „In Film-Knoten übernehmen“ (bewusster Klick, bestehender Import)

Mehrere markierte Aufträge (v1.23): nur die gemeinsamen Einstellungen, eine Änderung gilt für alle – wie bei
mehreren Buttons im Menü-Inspektor. Jede Änderung und „Passt so“ legen die Einstellungen fest (Markierung links
in der Liste). Einstellungen gelten direkt am Auftrag (kein Undo: Aufträge sind kein Teil des Disc-Projekts).
"""

import os
from typing import Callable, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QScrollArea, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton, QFrame,
    QProgressBar, QFileDialog, QSpinBox, QDoubleSpinBox,
)

from core.translations import tr
from modules.prepare import jobs, tasks, uhd
from gui.studio.widgets import Section, SegmentedSwitch, ElidedLabel, hint_label, fill_combo

INFO_STYLE = "color: #A1A1AA;"
DETECTED_STYLE = "color: #FBBF24; font-weight: bold;"
OPEN_STYLE = "color: #FBBF24;"
ERROR_STYLE = "color: #F87171;"
CAPTION_STYLE = "color: #D4D4D8;"
HINT_STYLE = "color: #71717A; font-size: 11px;"
NONSTANDARD_STYLE = "color: #FDE047; font-size: 11px;"   # Wahl außerhalb des Blu-ray-Standards
MIXED = "__mixed__"
NEW_FILM = "__new_film__"


def _format_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def _row(caption: QLabel, field: QWidget) -> QWidget:
    row = QWidget()
    row.setObjectName("section_row")
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    caption.setStyleSheet(CAPTION_STYLE)
    layout.addWidget(caption, stretch=1)
    layout.addWidget(field, stretch=2)
    return row


def _common(values: list):
    """Der gemeinsame Wert oder MIXED."""
    return values[0] if values and all(v == values[0] for v in values) else MIXED


# Primärfarben des Mastering-Displays (Einheiten wie x265: CIE xy × 50 000), Weißpunkt D65
HDR_PRIMARIES = {
    "p3d65": {"green": (13250, 34500), "blue": (7500, 3000), "red": (34000, 16000), "white": (15635, 16450)},
    "bt2020": {"green": (8500, 39850), "blue": (6550, 2300), "red": (35400, 14600), "white": (15635, 16450)},
}
# Eingabefelder: (kleinster Wert, größter Wert, Nachkommastellen, Schritt)
HDR_SPINS = {"max_luminance": (100, 10000, 0, 100), "min_luminance": (0.0001, 1.0, 4, 0.0001),
             "max_cll": (0, 10000, 0, 50), "max_fall": (0, 10000, 0, 50)}


def _format_hours(seconds: float) -> str:
    minutes = int(seconds // 60)
    return f"{minutes // 60} h {minutes % 60:02d} min" if minutes >= 60 else f"{minutes} min"


def _lum(value: int, lang: str) -> str:
    """Helligkeit aus 0,0001 cd/m² lesbar: 1000 bzw. 0,0001 (Komma auf Deutsch)."""
    number = value / 10000
    text = f"{number:g}" if number >= 1 else f"{number:.4f}".rstrip("0")
    return text.replace(".", ",") if lang == "de" else text


def audio_option_label(option: str) -> str:
    """Anzeige eines Tonformats in der Sprache der Oberfläche (v1.27.2); der Wert selbst bleibt unverändert."""
    return option.replace("Downmix auf 5.1", tr("prep_downmix_51")).replace(
        "übernehmen (unverändert / unchanged)", tr("prep_copy_unchanged"))


class PrepareInspector(QScrollArea):
    changed = Signal(list)                   # Einstellungen dieser Aufträge geändert (Liste zeigt sie neu)
    create_film = Signal(list)               # „Neuer Film-Knoten …“ als Ziel dieser Aufträge (v1.24)
    take_over = Signal(list, object)         # (Aufträge, Film-ID oder None = neuer Film-Knoten)
    status = Signal(str)

    def __init__(self, controller, lang: Callable[[], str], parent=None):
        super().__init__(parent)
        self.controller = controller
        self._lang = lang
        self.selection: List[tasks.PrepareTask] = []
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMinimumWidth(380)                # wie der Inspektor der Disc-Seite
        self.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        self.setWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignTop)        # jeder Abschnitt nur so hoch wie nötig

        self.lbl_empty = QLabel()
        self.lbl_empty.setAlignment(Qt.AlignCenter)
        self.lbl_empty.setStyleSheet("color: #71717A;")
        layout.addWidget(self.lbl_empty)

        # Kopf
        self.card = QFrame()
        self.card.setObjectName("card")
        self.card.setStyleSheet("QLabel { background: transparent; }")
        card = QVBoxLayout(self.card)
        card.setContentsMargins(14, 12, 14, 12)
        card.setSpacing(6)
        self.lbl_name = ElidedLabel()
        self.lbl_name.setStyleSheet("font-size: 14px; font-weight: bold; color: #FAFAFA;")
        self.lbl_info = QLabel()
        self.lbl_info.setStyleSheet(INFO_STYLE)
        self.lbl_detected = QLabel()
        self.lbl_detected.setStyleSheet(DETECTED_STYLE)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.lbl_confirm = QLabel()
        self.btn_confirm = QPushButton()
        self.btn_confirm.clicked.connect(self._confirm)
        confirm_row = QHBoxLayout()
        confirm_row.addWidget(self.lbl_confirm, stretch=1)
        confirm_row.addWidget(self.btn_confirm)
        for w in (self.lbl_name, self.lbl_info, self.lbl_detected, self.progress):
            card.addWidget(w)
        card.addLayout(confirm_row)
        layout.addWidget(self.card)

        # Video
        self.sec_video = Section("prep_video")
        self.lbl_kind = QLabel()
        self.switch_kind = SegmentedSwitch([tasks.KIND_2D, tasks.KIND_3D])
        self.switch_kind.chosen.connect(self._on_kind)
        self.row_kind = _row(self.lbl_kind, self.switch_kind)
        self.lbl_bitrate = QLabel()
        self.combo_bitrate = QComboBox()
        self.combo_bitrate.activated.connect(self._on_bitrate)
        self.lbl_resolution = QLabel()
        self.switch_resolution = SegmentedSwitch(["1080", "720"])
        self.switch_resolution.chosen.connect(lambda value: self._set("target_720p", value == "720"))
        self.lbl_resolution_fixed = QLabel()
        self.lbl_resolution_fixed.setStyleSheet(INFO_STYLE)
        res_box = QWidget()
        res_layout = QHBoxLayout(res_box)
        res_layout.setContentsMargins(0, 0, 0, 0)
        res_layout.addWidget(self.switch_resolution)
        res_layout.addWidget(self.lbl_resolution_fixed)
        self.row_resolution = _row(self.lbl_resolution, res_box)
        # 25 fps und 30/60 fps: je zwei sichtbare Optionen mit Hinweis (wie in BD3DEnc, v1.24 statt Häkchen)
        self.lbl_25p = QLabel()
        self.switch_25p = SegmentedSwitch(["psf", "p"])
        self.switch_25p.chosen.connect(lambda value: self._set("psf_25", value == "psf"))
        self.row_25p = _row(self.lbl_25p, self.switch_25p)
        self.lbl_25p_hint = hint_label()
        # 30/60 fps: immer angepasst (v1.25), mit deutlichem Hinweis aufs Ruckeln
        self.lbl_conform = QLabel()
        self.lbl_conform_value = QLabel()
        self.lbl_conform_value.setStyleSheet("color: #FDE047;")
        self.row_conform = _row(self.lbl_conform, self.lbl_conform_value)
        self.lbl_conform_hint = hint_label()
        self.lbl_conform_hint.setStyleSheet("color: #FDE047; font-size: 11px;")
        self.lbl_conform_tip = hint_label()
        self.lbl_ntsc_hint = hint_label()
        # Ton im Video wird bewusst nicht übernommen (v1.29.1): Ton gehört als eigene Datei in guter Qualität dazu
        self.lbl_no_audio = hint_label()
        # Ultra HD Blu-ray (UHD-Plan): Auflösung, Datenrate mit „passt bis …“, Genau/Schnell, Dynamikbereich, HDR10
        self.lbl_uhd_res = QLabel()
        self.switch_uhd_res = SegmentedSwitch([uhd.RES_2160, uhd.RES_1080])
        self.switch_uhd_res.chosen.connect(self._on_uhd_resolution)
        self.row_uhd_res = _row(self.lbl_uhd_res, self.switch_uhd_res)
        self.lbl_fit = hint_label()
        self.lbl_uhd_mode = QLabel()
        self.switch_uhd_mode = SegmentedSwitch([uhd.MODE_EXACT, uhd.MODE_FAST])
        self.switch_uhd_mode.chosen.connect(lambda value: self._set("uhd_mode", value))
        self.row_uhd_mode = _row(self.lbl_uhd_mode, self.switch_uhd_mode)
        self.lbl_uhd_mode_hint = hint_label()
        self.lbl_range_caption = QLabel()
        self.lbl_range = QLabel()
        self.lbl_range.setWordWrap(True)
        self.lbl_range.setStyleSheet(INFO_STYLE)
        self.row_range = _row(self.lbl_range_caption, self.lbl_range)
        self.box_hdr = self._build_hdr_box()
        self.lbl_disc_mismatch = hint_label()
        self.lbl_disc_mismatch.setStyleSheet(NONSTANDARD_STYLE)
        self.btn_fit_disc = QPushButton()
        self.btn_fit_disc.clicked.connect(self._fit_disc)
        self.row_bitrate = _row(self.lbl_bitrate, self.combo_bitrate)
        for w in (self.lbl_disc_mismatch, self.btn_fit_disc, self.row_kind, self.row_uhd_res, self.row_bitrate,
                  self.lbl_fit, self.row_uhd_mode, self.lbl_uhd_mode_hint, self.row_range, self.box_hdr,
                  self.row_resolution, self.row_25p, self.lbl_25p_hint, self.row_conform, self.lbl_conform_hint,
                  self.lbl_conform_tip, self.lbl_ntsc_hint, self.lbl_no_audio):
            self.sec_video.layout_.addWidget(w)
        layout.addWidget(self.sec_video)

        # Ton
        self.sec_audio = Section("prep_audio")
        self.lbl_track = QLabel()
        self.combo_track = QComboBox()
        self.combo_track.activated.connect(self._on_track)
        self.row_track = _row(self.lbl_track, self.combo_track)
        self.lbl_format = QLabel()
        self.combo_format = QComboBox()
        self.combo_format.activated.connect(self._on_format)
        self.lbl_offset = hint_label()
        self.lbl_offset.setStyleSheet("color: #FDE047; font-size: 11px;")
        for w in (self.row_track, _row(self.lbl_format, self.combo_format), self.lbl_offset):
            self.sec_audio.layout_.addWidget(w)
        layout.addWidget(self.sec_audio)

        # Ziel
        self.sec_target = Section("prep_target")
        self.lbl_out_caption = QLabel()
        self.lbl_out_dir = ElidedLabel()
        self.lbl_out_dir.setStyleSheet(INFO_STYLE)
        self.btn_out_dir = QPushButton()
        self.btn_out_dir.clicked.connect(self._choose_out_dir)
        out_box = QWidget()
        out_layout = QHBoxLayout(out_box)
        out_layout.setContentsMargins(0, 0, 0, 0)
        out_layout.addWidget(self.lbl_out_dir, stretch=1)
        out_layout.addWidget(self.btn_out_dir)
        self.lbl_files_caption = QLabel()
        self.lbl_files = QLabel()
        self.lbl_files.setStyleSheet(INFO_STYLE)
        self.lbl_files.setWordWrap(True)
        self.row_files = _row(self.lbl_files_caption, self.lbl_files)
        self.lbl_suggest = QLabel()
        self.combo_suggest = QComboBox()
        self.combo_suggest.activated.connect(self._on_suggest)
        for w in (_row(self.lbl_out_caption, out_box), self.row_files, _row(self.lbl_suggest, self.combo_suggest)):
            self.sec_target.layout_.addWidget(w)
        layout.addWidget(self.sec_target)

        # Ergebnis
        self.sec_result = Section("prep_result")
        self.lbl_result = QLabel()
        self.lbl_result.setWordWrap(True)
        self.lbl_result.setStyleSheet(INFO_STYLE)
        self.lbl_take_into = QLabel()
        self.combo_take = QComboBox()
        self.row_take = _row(self.lbl_take_into, self.combo_take)
        self.lbl_take_hint = hint_label()
        self.btn_take = QPushButton()
        self.btn_take.setObjectName("primary_btn")
        self.btn_take.clicked.connect(
            lambda: self.take_over.emit(list(self.selection), self.combo_take.currentData() or None))
        for w in (self.lbl_result, self.row_take, self.lbl_take_hint):
            self.sec_result.layout_.addWidget(w)
        self.sec_result.layout_.addWidget(self.btn_take, alignment=Qt.AlignLeft)
        layout.addWidget(self.sec_result)

        # „passt bis …“: freier Platz der Disc für diesen Auftrag in Bytes (setzt die Seite Vorbereiten)
        self.free_bytes_for: Callable[[tasks.PrepareTask], Optional[int]] = lambda task: None
        self.disc_size_name: Callable[[], str] = lambda: ""
        self.retranslate()
        self.show_tasks([])

    def _build_hdr_box(self) -> QWidget:
        """Eingabe der HDR10-Angaben aus dem Grading, wenn die Datei keine mitbringt (Pflicht)."""
        box = QWidget()
        form = QVBoxLayout(box)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(6)
        self.lbl_hdr_needed = hint_label()
        self.lbl_hdr_needed.setStyleSheet(NONSTANDARD_STYLE)
        form.addWidget(self.lbl_hdr_needed)
        self.lbl_hdr_primaries = QLabel()
        self.combo_hdr_primaries = QComboBox()
        for key in HDR_PRIMARIES:
            self.combo_hdr_primaries.addItem("", key)
        self.combo_hdr_primaries.activated.connect(lambda _i: self._commit_hdr())
        form.addWidget(_row(self.lbl_hdr_primaries, self.combo_hdr_primaries))
        self.spin_hdr = {}
        for key, (low, high, decimals, step) in HDR_SPINS.items():
            label = QLabel()
            spin = QDoubleSpinBox() if decimals else QSpinBox()
            if decimals:
                spin.setDecimals(decimals)
            spin.setRange(low, high)
            spin.setSingleStep(step)
            spin.editingFinished.connect(self._commit_hdr)
            self.spin_hdr[key] = (label, spin)
            form.addWidget(_row(label, spin))
        return box

    def t(self, key: str, **kwargs) -> str:
        text = tr(key, self._lang())
        return text.format(**kwargs) if kwargs else text

    def fps(self, value: str) -> str:
        """Bildrate wie in der Sprache üblich: 29,97 auf Deutsch, 29.97 auf Englisch."""
        return value.replace(".", ",") if self._lang() == "de" else value

    @property
    def task(self) -> Optional[tasks.PrepareTask]:
        """Der Auftrag bei Einzelauswahl, sonst None."""
        return self.selection[0] if len(self.selection) == 1 else None

    # --- Anzeige ---------------------------------------------------------------
    def show_tasks(self, selection: List[tasks.PrepareTask]):
        self.selection = list(selection)
        self.refresh()

    def show_task(self, task: Optional[tasks.PrepareTask]):
        self.show_tasks([task] if task is not None else [])

    def refresh(self):
        sel = self.selection
        self.lbl_empty.setVisible(not sel)
        for w in (self.card, self.sec_video, self.sec_audio, self.sec_target, self.sec_result):
            w.setVisible(bool(sel))
        if not sel:
            return
        kinds = {t.kind for t in sel}
        self._refresh_head(sel)
        self.sec_video.setVisible(len(kinds) == 1 and sel[0].is_video)
        self.sec_audio.setVisible(kinds == {tasks.KIND_AUDIO})
        if self.sec_video.isVisibleTo(self):
            self._refresh_video(sel)
        if self.sec_audio.isVisibleTo(self):
            self._refresh_audio(sel)
        self._refresh_target(sel)
        self._refresh_result(sel)
        editable = all(t.editable for t in sel)
        for w in (self.sec_video, self.sec_audio, self.sec_target):
            w.setEnabled(editable)

    def update_progress(self):
        task = self.task
        if task is not None:
            self.progress.setVisible(task.status == tasks.RUNNING)
            self.progress.setValue(int(task.progress * 100))

    def _refresh_head(self, sel):
        task = self.task
        if task is not None:
            self.lbl_name.setText(task.name)
            if task.video is not None:
                v = task.video
                self.lbl_info.setText(f"{v.width}×{v.height} · {self.fps(v.fps_str)} fps · {_format_duration(v.duration)}"
                                      + (f" · {v.codec}" if v.codec else ""))
            else:
                self.lbl_info.setText(_format_duration(task.duration))
            self.lbl_detected.setVisible(bool(task.layout) and task.kind == tasks.KIND_3D)
            if task.layout:
                self.lbl_detected.setText(self.t(f"prep_detected_{task.layout}"))
        else:
            self.lbl_name.setText(self.t("prep_multi", n=len(sel)))
            self.lbl_info.setText(", ".join(sorted({self.t(f"prep_kind_{t.kind}") for t in sel})))
            self.lbl_detected.setVisible(False)
        open_tasks = [t for t in sel if t.editable and t.status != tasks.DONE and not t.confirmed]
        relevant = [t for t in sel if t.status != tasks.DONE]
        self.lbl_confirm.setVisible(bool(relevant))
        self.btn_confirm.setVisible(bool(open_tasks))
        self.lbl_confirm.setText(self.t("prep_open") if open_tasks else self.t("prep_confirmed"))
        self.lbl_confirm.setStyleSheet(OPEN_STYLE if open_tasks else INFO_STYLE)
        self.progress.setVisible(False)
        self.update_progress()

    def _refresh_video(self, sel):
        single = self.task
        kind = sel[0].kind
        self._refresh_disc_match(sel)
        is_uhd = kind == tasks.KIND_UHD
        for w in (self.row_uhd_res, self.lbl_fit, self.row_uhd_mode, self.lbl_uhd_mode_hint, self.row_range):
            w.setVisible(is_uhd)
        self.box_hdr.setVisible(False)
        if is_uhd:
            self.row_kind.setVisible(False)
            for w in (self.row_resolution, self.row_25p, self.lbl_25p_hint, self.row_conform, self.lbl_conform_hint,
                      self.lbl_conform_tip, self.lbl_ntsc_hint):
                w.setVisible(False)
            self._refresh_uhd(sel)
            self.lbl_no_audio.setVisible(any(t.video.has_audio for t in sel))
            self.lbl_no_audio.setText(self.t("prep_hint_no_audio"))
            return
        self.row_kind.setVisible(single is not None)
        if single is not None:
            self.switch_kind.set_value(kind)
            self.switch_kind.buttons[tasks.KIND_3D].setEnabled(bool(single.layout))
        mixed = [(MIXED, self.t("prep_mixed"))]
        if kind == tasks.KIND_3D:
            value = _common([t.total_kbps for t in sel])
            entries = [(k, self.t("prep_bitrate_3d", n=k // 1000)) for k in tasks.BUDGETS_3D]
        else:
            value = _common([t.bitrate_2d for t in sel])
            entries = [(b, self.t("prep_bitrate_2d", n=b)) for b in tasks.BITRATES_2D]
        fill_combo(self.combo_bitrate, (mixed if value == MIXED else []) + entries, value)

        is_2d = kind == tasks.KIND_2D
        choices = {tasks.resolution_choice(t) for t in sel}
        self.row_resolution.setVisible(is_2d and len(choices) == 1)
        choice = next(iter(choices))
        self.switch_resolution.setVisible(choice is None)
        self.lbl_resolution_fixed.setVisible(choice is not None)
        resolution = _common([t.target_720p for t in sel])
        if resolution == MIXED:
            self.switch_resolution.clear()
        else:
            self.switch_resolution.set_value("720" if resolution else "1080")
        if choice is not None and single is not None:
            self.lbl_resolution_fixed.setText(self.t("prep_resolution_fixed", res="720p" if choice else "1080",
                                                     fps=self.fps(single.video.fps_str)))
        elif choice is not None:
            self.lbl_resolution_fixed.setText("720p" if choice else "1080")

        # 25 fps: PsF oder nativ; 30/60 fps: Hinweis auf die Anpassung – bei allen markierten mit derselben Bildrate
        fps_values = {t.video.fps_str for t in sel}
        fps = next(iter(fps_values)) if len(fps_values) == 1 else None
        in_1080 = not any(t.target_720p for t in sel)
        show_25p = is_2d and fps == "25" and in_1080
        self.row_25p.setVisible(show_25p)
        self.lbl_25p_hint.setVisible(show_25p)
        if show_25p:
            psf = _common([t.psf_25 for t in sel])
            if psf == MIXED:
                self.switch_25p.clear()
                self.lbl_25p_hint.setText("")
            else:
                self.switch_25p.set_value("psf" if psf else "p")
                self.lbl_25p_hint.setText(self.t("prep_hint_25p_i" if psf else "prep_hint_25p_p"))
                self.lbl_25p_hint.setStyleSheet(HINT_STYLE if psf else NONSTANDARD_STYLE)
        conform = jobs.NON_BD_FPS.get(fps) if is_2d and fps else None
        self.row_conform.setVisible(conform is not None)
        self.lbl_conform_hint.setVisible(conform is not None)
        self.lbl_conform_tip.setVisible(conform is not None)
        if conform is not None:
            seconds = round(1001 / float(fps))          # ein Bild von 1001 fällt weg
            self.lbl_conform_value.setText(self.t("prep_conform_value", fps=self.fps(fps), bd=self.fps(conform[2])))
            self.lbl_conform_hint.setText(self.t("prep_conform_warning", fps=self.fps(fps), bd=self.fps(conform[2]),
                                                 seconds=seconds))
            self.lbl_conform_tip.setText(self.t("prep_conform_tip", bd=self.fps(conform[2])))
        ntsc = is_2d and fps in ("29.97", "30") and in_1080
        self.lbl_ntsc_hint.setVisible(ntsc)
        self.lbl_ntsc_hint.setText(self.t("prep_hint_ntsc_psf"))
        self.lbl_no_audio.setVisible(any(t.video.has_audio for t in sel))
        self.lbl_no_audio.setText(self.t("prep_hint_no_audio"))

    def _refresh_disc_match(self, sel):
        """Hinweis, wenn Auftrag und Disc-Typ nicht zusammenpassen (Disc-Typ nach dem Hinzufügen umgestellt)."""
        disc_uhd = self.controller.project.settings.is_uhd
        task_uhd = sel[0].kind == tasks.KIND_UHD
        mismatch = disc_uhd != task_uhd
        self.lbl_disc_mismatch.setVisible(mismatch)
        self.btn_fit_disc.setVisible(mismatch)
        if mismatch:
            self.lbl_disc_mismatch.setText(self.t("prep_uhd_task_on_bluray" if task_uhd else "prep_bluray_task_on_uhd"))
            self.btn_fit_disc.setText(self.t("prep_fit_disc"))

    def _fit_text(self, task, bitrate: int) -> str:
        free = self.free_bytes_for(task)
        if free is None:
            return ""
        seconds = free / (uhd.estimated_size(1, bitrate, task.uhd_mode) or 1)
        if seconds < 60:
            return self.t("prep_fits_none", disc=self.disc_size_name())
        return self.t("prep_fits_until", time=_format_hours(seconds), disc=self.disc_size_name())

    def _refresh_uhd(self, sel):
        single = self.task
        resolutions = {t.uhd_resolution for t in sel}
        resolution = next(iter(resolutions)) if len(resolutions) == 1 else None
        self.row_uhd_res.setVisible(resolution is not None)
        if resolution is not None:
            self.switch_uhd_res.set_value(resolution)
            only_1080 = any((t.video.width, t.video.height) != uhd.SIZES[uhd.RES_2160] for t in sel)
            self.switch_uhd_res.buttons[uhd.RES_2160].setEnabled(not only_1080)
        # Datenrate: Stufen der Auflösung, jede mit „passt bis …“ (bei Einzelauswahl)
        rates = uhd.BITRATES.get(resolution, ())
        value = _common([t.uhd_bitrate for t in sel])
        entries = []
        for rate in rates:
            fit = self._fit_text(single, rate) if single is not None else ""
            entries.append((rate, self.t("prep_bitrate_2d", n=rate) + (f" – {fit}" if fit else "")))
        self.row_bitrate.setVisible(bool(rates))
        fill_combo(self.combo_bitrate, ([(MIXED, self.t("prep_mixed"))] if value == MIXED else []) + entries, value)
        # passt der Film mit dieser Stufe nicht: der Ausweg (kleinere Stufe oder größere Disc)
        self.lbl_fit.setVisible(False)
        if single is not None and single.duration > 0:
            free = self.free_bytes_for(single)
            if free is not None and uhd.estimated_size(single.duration, single.uhd_bitrate, single.uhd_mode) > free:
                fitting = [r for r in rates if uhd.estimated_size(single.duration, r, single.uhd_mode) <= free]
                text = self.t("prep_fit_too_big", disc=self.disc_size_name())
                if fitting:
                    text += " " + self.t("prep_fit_with", n=max(fitting))
                self.lbl_fit.setText(text)
                self.lbl_fit.setStyleSheet(NONSTANDARD_STYLE)
                self.lbl_fit.setVisible(True)
        mode = _common([t.uhd_mode for t in sel])
        if mode == MIXED:
            self.switch_uhd_mode.clear()
            self.lbl_uhd_mode_hint.setText("")
        else:
            self.switch_uhd_mode.set_value(mode)
            self.lbl_uhd_mode_hint.setText(self.t(f"prep_uhd_mode_{mode}_hint"))
        # Dynamikbereich der Quelle und HDR10-Angaben
        ranges = {t.dynamic_range for t in sel}
        dyn = next(iter(ranges)) if len(ranges) == 1 else None
        if dyn is None:
            self.lbl_range.setText(self.t("prep_mixed"))
            return
        text = self.t(f"uhd_range_{dyn}")
        if dyn == uhd.HDR10 and single is not None:
            meta = single.hdr_meta()
            if meta is not None and meta.plausible():
                text += "\n" + self.t("prep_hdr_values", min=_lum(meta.min_luminance, self._lang()),
                                      max=_lum(meta.max_luminance, self._lang()),
                                      cll=meta.max_cll, fall=meta.max_fall)
                text += " " + self.t("prep_hdr_from_file" if single.uhd_hdr_from_file else "prep_hdr_entered")
            self.box_hdr.setVisible(not single.uhd_hdr_from_file)
            self._fill_hdr_box(single)
        self.lbl_range.setText(text)

    def _fill_hdr_box(self, task):
        meta = task.hdr_meta()
        self.lbl_hdr_needed.setVisible(task.needs_hdr_meta())
        self.lbl_hdr_needed.setText(self.t("prep_hdr_needed"))
        primaries = next((k for k, v in HDR_PRIMARIES.items() if meta is not None and
                          (v["green"], v["blue"], v["red"], v["white"]) ==
                          (meta.green, meta.blue, meta.red, meta.white)), "p3d65")
        index = self.combo_hdr_primaries.findData(primaries)
        if index >= 0:
            self.combo_hdr_primaries.setCurrentIndex(index)
        values = {"max_luminance": meta.max_luminance / 10000 if meta else 1000,
                  "min_luminance": meta.min_luminance / 10000 if meta else 0.0001,
                  "max_cll": meta.max_cll if meta else 0, "max_fall": meta.max_fall if meta else 0}
        for key, (_label, spin) in self.spin_hdr.items():
            if not spin.hasFocus():
                spin.setValue(values[key])

    def _commit_hdr(self):
        task = self.task
        if task is None or not task.editable:
            return
        prim = HDR_PRIMARIES[self.combo_hdr_primaries.currentData()]
        spins = {key: spin.value() for key, (_label, spin) in self.spin_hdr.items()}
        meta = uhd.HdrMeta(green=prim["green"], blue=prim["blue"], red=prim["red"], white=prim["white"],
                           max_luminance=int(round(spins["max_luminance"] * 10000)),
                           min_luminance=int(round(spins["min_luminance"] * 10000)),
                           max_cll=int(spins["max_cll"]), max_fall=int(spins["max_fall"]))
        self._apply(lambda t: (setattr(t, "uhd_hdr", tasks.hdr_to_dict(meta)), setattr(t, "uhd_hdr_from_file", False)))

    def _on_uhd_resolution(self, resolution: str):
        problems = []
        for task in self._editable():
            problems += tasks.set_uhd_resolution(task, resolution)
        if problems:
            self.status.emit(" ".join(self.t(f"prep_problem_{code}", **details) for code, details in problems))
        self._apply(lambda t: None)

    def _fit_disc(self):
        """Aufträge an den Disc-Typ anpassen (Blu-ray ↔ Ultra HD), soweit die Quelle es erlaubt."""
        kind = tasks.KIND_UHD if self.controller.project.settings.is_uhd else None
        problems = []
        for task in self._editable():
            target = kind or (tasks.KIND_3D if jobs.stereo_layout(task.video.width, task.video.height)
                              else tasks.KIND_2D)
            problems += tasks.set_kind(task, target)
        if problems:
            self.status.emit(" ".join(self.t(f"prep_problem_{code}", **details) for code, details in problems))
        self._apply(lambda t: None)

    def _refresh_audio(self, sel):
        single = self.task
        self.row_track.setVisible(single is not None and len(single.audio.tracks) > 1)
        if single is not None:
            lang_suffix = lambda tr_: f", {tr_.language}" if tr_.language else ""
            fill_combo(self.combo_track,
                       [(t.index, self.t("prep_track_entry", n=t.index + 1, codec=t.codec.upper(),
                                         channels=t.channels, rate=t.sample_rate, lang=lang_suffix(t)))
                        for t in single.audio.tracks], single.audio_track)
        option_lists = [jobs.audio_track_options(t.track()) for t in sel]
        same_options = all(o == option_lists[0] for o in option_lists)
        value = _common([t.audio_format for t in sel])
        entries = [(o, audio_option_label(o)) for o in option_lists[0]] if same_options else []
        fill_combo(self.combo_format, ([(MIXED, self.t("prep_mixed"))] if value == MIXED else []) + entries, value)
        self.combo_format.setEnabled(same_options)
        offset = single.track().offset if single is not None and single.audio.has_video else 0.0
        self.lbl_offset.setVisible(abs(offset) >= jobs.OFFSET_WARN)
        self.lbl_offset.setText(self.t("prep_offset", ms=round(abs(offset) * 1000)))

    def _refresh_target(self, sel):
        out_dir = _common([t.out_dir for t in sel])
        text = self.t("prep_mixed") if out_dir == MIXED else out_dir
        self.lbl_out_dir.setText(text)
        self.lbl_out_dir.setToolTip(text)
        single = self.task
        self.row_files.setVisible(single is not None)
        if single is not None:
            try:
                names = [os.path.basename(p) for p in tasks.planned_outputs(single)]
            except ValueError as e:
                names = [str(e)]
            self.lbl_files.setText("\n".join(names))
        films = self.controller.project.films
        known = {f.id for f in films}
        suggest = _common([t.target_film_id if t.target_film_id in known else "" for t in sel])
        entries = [("", self.t("prep_suggest_none"))] + [(f.id, f.name) for f in films]
        if sum(1 for t in sel if t.is_video) <= 1:          # ein Film-Knoten hat ein Video
            entries.append((NEW_FILM, self.t("prep_new_film_create")))
        fill_combo(self.combo_suggest, ([(MIXED, self.t("prep_mixed"))] if suggest == MIXED else []) + entries,
                   suggest)

    def _refresh_result(self, sel):
        done = all(t.status == tasks.DONE for t in sel)
        failed = self.task is not None and self.task.status == tasks.FAILED
        self.sec_result.setVisible(done or failed)
        self.row_take.setVisible(done)
        self.btn_take.setVisible(done)
        self.lbl_take_hint.setVisible(False)
        if failed:
            self.lbl_result.setStyleSheet(ERROR_STYLE)
            self.lbl_result.setText(self.task.error)
            return
        if not done:
            return
        self.lbl_result.setStyleSheet(INFO_STYLE)
        self.lbl_result.setText("\n".join(os.path.basename(p) for t in sel for p in t.outputs))
        videos = [t for t in sel if t.is_video]
        films = self.controller.project.films
        entries = [(f.id, f.name) for f in films]
        if videos:
            entries.append(("", self.t("prep_new_film")))
        known = {f.id for f in films}
        suggestions = [t.target_film_id for t in sel if t.target_film_id in known]
        current = suggestions[0] if suggestions else ("" if videos else None)
        fill_combo(self.combo_take, entries, current)
        # ein Film-Knoten hat ein Video: mehrere Videos auf einmal gingen ineinander über
        one_video = len(videos) <= 1
        self.lbl_take_hint.setVisible(not one_video)
        self.lbl_take_hint.setText(self.t("prep_take_one_video"))
        self.btn_take.setEnabled(bool(entries) and one_video)

    # --- Eingaben ---------------------------------------------------------------
    def _editable(self) -> List[tasks.PrepareTask]:
        return [t for t in self.selection if t.editable]

    def _apply(self, change: Callable[[tasks.PrepareTask], None]):
        """Änderung an allen markierten (nicht laufenden) Aufträgen; legt deren Einstellungen fest."""
        changed = self._editable()
        for task in changed:
            change(task)
            task.confirmed = True
        self.refresh()
        if changed:
            self.changed.emit(changed)

    def _set(self, field: str, value):
        if value == MIXED:
            return
        self._apply(lambda task: setattr(task, field, value))

    def _confirm(self):
        self._apply(lambda task: None)

    def _on_kind(self, kind: str):
        task = self.task
        if task is None or not task.editable:
            return
        problems = tasks.set_kind(task, kind)
        if problems:
            self.status.emit(" ".join(self.t(f"prep_problem_{code}", **details) for code, details in problems))
        self._apply(lambda t: None)

    def _on_bitrate(self, _index: int):
        value = self.combo_bitrate.currentData()
        if value == MIXED:
            return
        kind = self.selection[0].kind if self.selection else None
        field = {tasks.KIND_3D: "total_kbps", tasks.KIND_UHD: "uhd_bitrate"}.get(kind, "bitrate_2d")
        self._set(field, value)

    def _on_track(self, _index: int):
        task = self.task
        if task is None:
            return

        def change(t):
            t.audio_track = self.combo_track.currentData()
            options = jobs.audio_track_options(t.track())
            if t.audio_format not in options:
                t.audio_format = options[0]
        self._apply(change)

    def _on_format(self, _index: int):
        self._set("audio_format", self.combo_format.currentData())

    def _on_suggest(self, _index: int):
        value = self.combo_suggest.currentData()
        if value == NEW_FILM:
            editable = self._editable()
            self.refresh()                       # Auswahl zurück, bis der Film-Knoten wirklich angelegt ist
            if editable:
                self.create_film.emit(editable)
        elif value != MIXED:
            self._set("target_film_id", value or None)

    def _choose_out_dir(self):
        if not self.selection:
            return
        first = self.selection[0]
        start = first.out_dir if os.path.isdir(first.out_dir) else os.path.dirname(first.source)
        folder = QFileDialog.getExistingDirectory(self, self.t("prep_out_choose"), start)
        if folder:
            self._set("out_dir", os.path.normpath(folder))

    def retranslate(self):
        self.lbl_empty.setText(self.t("prep_inspector_empty"))
        self.sec_video.set_title(self.t("prep_section_video"))
        self.sec_audio.set_title(self.t("prep_section_audio"))
        self.sec_target.set_title(self.t("prep_section_target"))
        self.sec_result.set_title(self.t("prep_section_result"))
        self.lbl_kind.setText(self.t("prep_kind"))
        self.switch_kind.set_texts({tasks.KIND_2D: "2D", tasks.KIND_3D: "3D"})
        self.lbl_bitrate.setText(self.t("prep_bitrate"))
        self.lbl_resolution.setText(self.t("prep_resolution"))
        self.switch_resolution.set_texts({"1080": "1080", "720": "720p"})
        self.lbl_25p.setText(self.t("prep_25p"))
        self.lbl_conform.setText(self.t("prep_frame_rate"))
        self.switch_25p.set_texts({"psf": self.t("prep_25p_i"), "p": self.t("prep_25p_p")})
        self.lbl_uhd_res.setText(self.t("prep_resolution"))
        self.switch_uhd_res.set_texts({uhd.RES_2160: "2160p", uhd.RES_1080: "1080p"})
        self.lbl_uhd_mode.setText(self.t("prep_uhd_mode"))
        self.switch_uhd_mode.set_texts({uhd.MODE_EXACT: self.t("prep_uhd_mode_exact"),
                                        uhd.MODE_FAST: self.t("prep_uhd_mode_fast")})
        self.lbl_range_caption.setText(self.t("prep_range"))
        self.lbl_hdr_primaries.setText(self.t("prep_hdr_primaries"))
        for i in range(self.combo_hdr_primaries.count()):
            self.combo_hdr_primaries.setItemText(i, self.t(f"prep_hdr_primaries_{self.combo_hdr_primaries.itemData(i)}"))
        for key, (label, spin) in self.spin_hdr.items():
            label.setText(self.t(f"prep_hdr_{key}"))
            spin.setSuffix(" cd/m²")
        self.lbl_track.setText(self.t("prep_track"))
        self.lbl_format.setText(self.t("prep_format"))
        self.lbl_out_caption.setText(self.t("prep_out_dir"))
        self.btn_out_dir.setText(self.t("prep_out_change"))
        self.lbl_files_caption.setText(self.t("prep_files"))
        self.lbl_suggest.setText(self.t("prep_suggest"))
        self.lbl_take_into.setText(self.t("prep_take_into"))
        self.btn_take.setText(self.t("prep_take"))
        self.btn_confirm.setText(self.t("prep_confirm"))
        self.btn_confirm.setToolTip(self.t("prep_confirm_tip"))
        self.refresh()
