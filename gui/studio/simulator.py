# gui/studio/simulator.py
"""
Simulator-Fenster (ab v1.8.1): die fertige Disc durchklicken, bevor gebrannt wird.

- Bildschirm im 1920×1080 Raum: Menü mit Standbild aus dem Menü-Video und den echten
  Button-Grafiken der Disc; Filme als Platzhalter-Karte über einem Standbild
- Fernbedienung per Klick oder Tastatur, Umschalter 2D-/3D-Fernseher
- Zustand (Titel, Seite, Spuren, 2D/3D) und Protokoll der ausgeführten Befehle
- Automatische Prüfung (modules/bdsim/explore) als Bericht

Die Navigation stammt vollständig aus modules/bdsim; das Fenster zeigt nur an und leitet Tasten weiter.
"""

from typing import Callable, Dict, Optional

from PySide6 import QtGui
from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QGridLayout, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QPushButton, QLabel, QListWidget, QListWidgetItem, QComboBox, QDialog, QPlainTextEdit, QSizePolicy,
)

from core.translations import tr
from gui.theme import ui_font
from modules.bdsim.disc import Disc
from modules.bdsim.explore import explore, format_report
from modules.bdsim.graphics import ButtonImages, clip_position, extract_frame
from modules.bdsim.player import Player, STATE_MENU, STATE_FILM
from modules.bdmv.movie_object_generator import GPR_AUDIO, GPR_SUBTITLE, GPR_SUBTITLE_MODE, SUB_ON, SUB_OFF

SCREEN_W, SCREEN_H = 1920, 1080
LEVEL_COLOR = {"fehler": "#F87171", "warnung": "#FDE047", "hinweis": "#93C5FD"}
LEVEL_ICON = {"fehler": "⛔", "warnung": "⚠", "hinweis": "ℹ"}


def _qimage(width: int, height: int, rgba: bytes) -> QtGui.QImage:
    # copy(): QImage verweist sonst auf den Python-Puffer
    return QtGui.QImage(rgba, width, height, width * 4, QtGui.QImage.Format_RGBA8888).copy()


class ScreenView(QGraphicsView):
    """Der Fernseher: zeigt Menü, Film-Platzhalter oder Stopp-Bild."""

    button_clicked = Signal(int)
    button_hovered = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(0, 0, SCREEN_W, SCREEN_H, self))
        self.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("background-color: #000000; border: 1px solid #27272A;")
        self.setMinimumSize(480, 270)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.NoFocus)
        self.button_rects: Dict[int, QRectF] = {}

    def clear(self):
        self.scene().clear()
        self.button_rects = {}

    def draw_background(self, image_path: Optional[str], dim: bool = False):
        scene = self.scene()
        pixmap = QtGui.QPixmap(image_path) if image_path else QtGui.QPixmap()
        if not pixmap.isNull():
            item = scene.addPixmap(pixmap.scaled(SCREEN_W, SCREEN_H, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
            item.setZValue(-2)
        else:
            gradient = QtGui.QLinearGradient(0, 0, 0, SCREEN_H)
            gradient.setColorAt(0.0, QtGui.QColor("#1C1C1F"))
            gradient.setColorAt(1.0, QtGui.QColor("#111113"))
            scene.addRect(QRectF(0, 0, SCREEN_W, SCREEN_H), QtGui.QPen(Qt.NoPen),
                          QtGui.QBrush(gradient)).setZValue(-2)
        if dim:
            scene.addRect(QRectF(0, 0, SCREEN_W, SCREEN_H), QtGui.QPen(Qt.NoPen),
                          QtGui.QBrush(QtGui.QColor(0, 0, 0, 150))).setZValue(-1)

    def draw_button(self, button_id: int, x: int, y: int, image: Optional[QtGui.QImage], selected: bool):
        if image is not None and not image.isNull():
            item = QGraphicsPixmapItem(QtGui.QPixmap.fromImage(image))
            item.setPos(x, y)
            self.scene().addItem(item)
            rect = QRectF(x, y, image.width(), image.height())
        else:
            rect = QRectF(x, y, 380, 70)
            color = QtGui.QColor("#FBBF24" if selected else "#71717A")
            self.scene().addRect(rect, QtGui.QPen(color, 3), QtGui.QBrush(Qt.NoBrush))
            text = self.scene().addSimpleText(f"Button {button_id}", ui_font(20))
            text.setBrush(color)
            text.setPos(x + 16, y + 18)
        self.button_rects[button_id] = rect

    def draw_card(self, title: str, lines: list, accent: str):
        scene = self.scene()
        card = QRectF(360, 330, 1200, 420)
        path = QtGui.QPainterPath()
        path.addRoundedRect(card, 24, 24)
        scene.addPath(path, QtGui.QPen(QtGui.QColor(accent), 3), QtGui.QBrush(QtGui.QColor(17, 17, 19, 220)))
        head = scene.addSimpleText(title, ui_font(44, bold=True))
        head.setBrush(QtGui.QColor(accent))
        head.setPos(card.x() + 50, card.y() + 40)
        y = card.y() + 140
        for line in lines:
            item = scene.addSimpleText(line, ui_font(26))
            item.setBrush(QtGui.QColor("#E4E4E7"))
            item.setPos(card.x() + 50, y)
            y += 50

    def fit(self):
        self.fitInView(self.scene().sceneRect(), Qt.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit()

    def _button_at(self, event) -> Optional[int]:
        pos = self.mapToScene(event.position().toPoint())
        for button_id, rect in self.button_rects.items():
            if rect.contains(pos):
                return button_id
        return None

    def mouseMoveEvent(self, event):
        button_id = self._button_at(event)
        if button_id is not None:
            self.button_hovered.emit(button_id)
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        button_id = self._button_at(event)
        if button_id is not None and event.button() == Qt.LeftButton:
            self.button_clicked.emit(button_id)
            return
        super().mousePressEvent(event)


class ReportDialog(QDialog):
    def __init__(self, title: str, text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(900, 640)
        layout = QVBoxLayout(self)
        self.text = QPlainTextEdit(text)
        self.text.setReadOnly(True)
        self.text.setStyleSheet("font-family: Consolas, 'Courier New', monospace; font-size: 12px;")
        layout.addWidget(self.text)


class SimulatorWindow(QWidget):
    """Disc-Simulator als eigenes Fenster."""

    def __init__(self, disc: Disc, lang: str = "de", frames: bool = True, parent=None,
                 on_close: Optional[Callable[[], None]] = None, menu_backgrounds: Optional[Dict[int, str]] = None,
                 title: Optional[str] = None):
        super().__init__(parent, Qt.Window)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.disc = disc
        self._on_close = on_close            # z. B. eingehängte ISO wieder aushängen
        self.lang = lang
        self.frames = frames                 # Standbilder per ffmpeg (in Tests aus)
        # Simulation aus dem Projekt: Bild je Menü-Playlist statt Menü-Clip (v1.13.2: je Menügruppe)
        self.menu_backgrounds = menu_backgrounds or {}
        self.tv_3d = True
        self.player: Optional[Player] = None
        self._images: Dict[int, ButtonImages] = {}
        self._log_len = 0
        self._findings_seen = set()

        self.setWindowTitle(f"{self.t('sim_title')} – {title or disc.bdmv_dir}")
        self.resize(1400, 780)

        self.screen_view = ScreenView()
        self.screen_view.button_clicked.connect(self._on_button_clicked)
        self.screen_view.button_hovered.connect(self._on_button_hovered)

        side = QVBoxLayout()
        side.setSpacing(8)

        self.tv_select = QComboBox()
        self.tv_select.addItem(self.t("sim_tv_3d"), True)
        self.tv_select.addItem(self.t("sim_tv_2d"), False)
        self.tv_select.currentIndexChanged.connect(self._on_tv_changed)
        side.addWidget(self._caption(self.t("sim_tv")))
        side.addWidget(self.tv_select)

        side.addWidget(self._caption(self.t("sim_remote")))
        pad = QGridLayout()
        self.btn_up = self._key("▲", lambda: self.press("up"))
        self.btn_left = self._key("◀", lambda: self.press("left"))
        self.btn_ok = self._key("OK", lambda: self.press("ok"))
        self.btn_right = self._key("▶", lambda: self.press("right"))
        self.btn_down = self._key("▼", lambda: self.press("down"))
        pad.addWidget(self.btn_up, 0, 1)
        pad.addWidget(self.btn_left, 1, 0)
        pad.addWidget(self.btn_ok, 1, 1)
        pad.addWidget(self.btn_right, 1, 2)
        pad.addWidget(self.btn_down, 2, 1)
        side.addLayout(pad)

        self.btn_top_menu = self._key(self.t("sim_top_menu"), lambda: self.press("top_menu"))
        self.btn_end = self._key(self.t("sim_end"), self.playlist_end)
        chapters = QHBoxLayout()
        self.btn_prev = self._key(self.t("sim_prev_chapter"), lambda: self.skip_chapter(-1))
        self.btn_next = self._key(self.t("sim_next_chapter"), lambda: self.skip_chapter(1))
        chapters.addWidget(self.btn_prev)
        chapters.addWidget(self.btn_next)
        streams = QHBoxLayout()
        self.btn_audio = self._key(self.t("sim_key_audio"), lambda: self.press("audio"))
        self.btn_subtitle = self._key(self.t("sim_key_subtitle"), lambda: self.press("subtitle"))
        streams.addWidget(self.btn_audio)
        streams.addWidget(self.btn_subtitle)
        self.btn_reinsert = self._key(self.t("sim_reinsert"), self.insert_disc)
        for w in (self.btn_top_menu, self.btn_end):
            side.addWidget(w)
        side.addLayout(chapters)
        side.addLayout(streams)
        side.addWidget(self.btn_reinsert)

        side.addWidget(self._caption(self.t("sim_status")))
        self.status = QLabel()
        self.status.setTextFormat(Qt.RichText)
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #E4E4E7; font-size: 13px;")
        side.addWidget(self.status)

        side.addWidget(self._caption(self.t("sim_log")))
        self.log = QListWidget()
        self.log.setFocusPolicy(Qt.NoFocus)
        self.log.setStyleSheet("font-family: Consolas, 'Courier New', monospace; font-size: 11px;")
        side.addWidget(self.log, stretch=1)

        self.btn_report = QPushButton(self.t("sim_report"))
        self.btn_report.setFocusPolicy(Qt.NoFocus)
        self.btn_report.clicked.connect(self.show_report)
        side.addWidget(self.btn_report)
        hint = QLabel(self.t("sim_keys_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #71717A; font-size: 11px;")
        side.addWidget(hint)

        panel = QWidget()
        panel.setLayout(side)
        panel.setFixedWidth(340)

        layout = QHBoxLayout(self)
        layout.addWidget(self.screen_view, stretch=1)
        layout.addWidget(panel)
        self.setFocusPolicy(Qt.StrongFocus)

        self.insert_disc()

    # ─── Aufbau ───
    def t(self, key: str, **kwargs) -> str:
        text = tr(key, self.lang)
        return text.format(**kwargs) if kwargs else text

    @staticmethod
    def _caption(text: str) -> QLabel:
        label = QLabel(text.upper())
        label.setStyleSheet("color: #A1A1AA; font-size: 11px; font-weight: bold; margin-top: 6px;")
        return label

    @staticmethod
    def _key(text: str, slot) -> QPushButton:
        btn = QPushButton(text)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn.clicked.connect(slot)
        return btn

    # ─── Bedienung ───
    def insert_disc(self):
        self.player = Player(self.disc, tv_3d=self.tv_3d)
        self._log_len = 0
        self._findings_seen = set()
        self.log.clear()
        self.player.insert_disc()
        self.refresh()

    def press(self, key: str):
        self.player.press(key)
        self.refresh()

    def playlist_end(self):
        self.player.playlist_end()
        self.refresh()

    def skip_chapter(self, step: int):
        self.player.skip_chapter(step)
        self.refresh()

    def _on_button_clicked(self, button_id: int):
        self.player.activate_button(button_id)
        self.refresh()

    def _on_button_hovered(self, button_id: int):
        if self.player.state == STATE_MENU and self.player.selected_button != button_id:
            self.player.select_button(button_id)
            self.refresh()

    def _on_tv_changed(self, _index: int):
        self.tv_3d = bool(self.tv_select.currentData())
        self.insert_disc()

    def keyPressEvent(self, event):
        keys = {Qt.Key_Up: "up", Qt.Key_Down: "down", Qt.Key_Left: "left", Qt.Key_Right: "right",
                Qt.Key_Return: "ok", Qt.Key_Enter: "ok", Qt.Key_T: "top_menu",
                Qt.Key_A: "audio", Qt.Key_U: "subtitle"}
        if event.key() in keys:
            self.press(keys[event.key()])
        elif event.key() == Qt.Key_E:
            self.playlist_end()
        elif event.key() == Qt.Key_PageDown:
            self.skip_chapter(1)
        elif event.key() == Qt.Key_PageUp:
            self.skip_chapter(-1)
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        if self._on_close is not None:
            callback, self._on_close = self._on_close, None
            callback()
        super().closeEvent(event)

    def show_report(self):
        reports = [explore(self.disc, tv_3d=True), explore(self.disc, tv_3d=False)]
        dialog = ReportDialog(self.t("sim_report_title"), format_report(self.disc, reports, detailed=True), self)
        dialog.exec()

    # ─── Anzeige ───
    def refresh(self):
        p = self.player
        self.screen_view.clear()
        if p.state == STATE_MENU:
            self._draw_menu()
        elif p.state == STATE_FILM:
            self._draw_film()
        else:
            self.screen_view.draw_background(None)
            self.screen_view.draw_card(self.t("sim_state_stopped"), [self.t("sim_stopped_hint")], "#F87171")
        self.screen_view.fit()
        self._update_status()
        self._update_log()
        in_menu = p.state == STATE_MENU
        for btn in (self.btn_up, self.btn_down, self.btn_left, self.btn_right, self.btn_ok):
            btn.setEnabled(in_menu)
        in_film = p.state == STATE_FILM
        for btn in (self.btn_prev, self.btn_next, self.btn_audio, self.btn_subtitle):
            btn.setEnabled(in_film)
        self.btn_end.setEnabled(in_menu or in_film)

    def _frame(self, playlist_id: int, mark: Optional[int]) -> Optional[str]:
        if not self.frames or playlist_id not in self.disc.playlists:
            return None
        path, seconds = clip_position(self.disc, self.disc.playlists[playlist_id], mark)
        if path is None:
            return None
        return extract_frame(path, seconds + (1.0 if mark is None else 0.2))

    def _draw_menu(self):
        p = self.player
        self.screen_view.draw_background(self.menu_backgrounds.get(p.playlist_id) or self._frame(p.playlist_id, None))
        page = p.current_page()
        images = self._images.setdefault(p.playlist_id, ButtonImages(p.composition))
        for button in p.valid_buttons():
            selected = button.button_id == p.selected_button
            object_id = (button.selected if selected else button.normal)[0]
            decoded = images.rgba(object_id, page.palette_id)
            image = _qimage(*decoded) if decoded else None
            self.screen_view.draw_button(button.button_id, button.x, button.y, image, selected)

    def _draw_film(self):
        p = self.player
        pl = self.disc.playlists.get(p.playlist_id)
        self.screen_view.draw_background(self._frame(p.playlist_id, p.start_mark), dim=True)
        lines = [self.t("sim_output_3d") if p.output_3d else self.t("sim_output_2d")]
        chapter, total = p.chapter_position()
        if total:
            lines.append(self.t("sim_chapter", n=chapter, total=total))
        if pl is not None and pl.count("audio"):
            lines.append(self.t("sim_audio", n=p.regs.psr[1]))
        pg = p.regs.psr[2]
        if pl is not None and pl.count("pg"):
            lines.append(self.t("sim_subs_on", n=pg & 0xFFF) if pg & 0x80000000 else self.t("sim_subs_off"))
        lines.append(self.t("sim_film_hint"))
        accent = "#A78BFA" if p.output_3d else "#4ADE80"
        self.screen_view.draw_card(self.t("sim_state_film", title=self._title_text(), pl=p.playlist_id), lines, accent)

    def _title_text(self) -> str:
        """Titelnummer; bei Kapitel-Einstiegsobjekten bleibt der Player formal im Menü-Titel (kein Titel)."""
        title = self.player.title
        return str(title) if 1 <= title <= len(self.disc.index.titles) else "–"

    def _update_status(self):
        p = self.player
        if p.state == STATE_MENU:
            head = self.t("sim_state_menu", pl=p.playlist_id, page=p.page_id, button=p.selected_button)
        elif p.state == STATE_FILM:
            head = self.t("sim_state_film", title=self._title_text(), pl=p.playlist_id)
        else:
            head = self.t("sim_state_stopped")
        pg = p.regs.psr[2]
        subs = self.t("sim_subs_on", n=pg & 0xFFF) if pg & 0x80000000 else self.t("sim_subs_off")
        mode = self.t("sim_output_3d") if p.output_3d else self.t("sim_output_2d")
        text = f"<b>{head}</b><br>{mode} · {self.t('sim_audio', n=p.regs.psr[1])} · {subs}"
        # Im Menü gemerkte Wahl (Registerbelegung von OpenBDAuth, modules/bdmv/movie_object_generator.py)
        gpr = p.regs.gpr
        chosen = []
        if gpr[GPR_AUDIO]:
            chosen.append(self.t("sim_audio", n=gpr[GPR_AUDIO]))
        if gpr[GPR_SUBTITLE_MODE] == SUB_ON:
            chosen.append(self.t("sim_subs_on", n=gpr[GPR_SUBTITLE]))
        elif gpr[GPR_SUBTITLE_MODE] == SUB_OFF:
            chosen.append(self.t("sim_subs_off"))
        if chosen:
            text += "<br>" + self.t("sim_remembered", items=", ".join(chosen))
        self.status.setText(text)

    def _update_log(self):
        lines = self.player.machine.log
        for line in lines[self._log_len:]:
            self.log.addItem(line)
        self._log_len = len(lines)
        for finding in self.player.findings:
            key = (finding.code, finding.text)
            if key in self._findings_seen:
                continue
            self._findings_seen.add(key)
            item = QListWidgetItem(f"{LEVEL_ICON[finding.level]} {finding.text}")
            item.setForeground(QtGui.QColor(LEVEL_COLOR[finding.level]))
            self.log.addItem(item)
        self.player.findings = []
        self.log.scrollToBottom()
