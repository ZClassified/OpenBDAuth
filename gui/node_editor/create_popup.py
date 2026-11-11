# gui/node_editor/create_popup.py
"""
Anlegen aus einem Vorschlag (Konzept 2.1, Regel 3). Gibt es etwas zu entscheiden, fragt ein kleines
Fenster direkt an der Stelle – Art des Sprachmenüs, Kapitel pro Seite, „wie bei …“, diese oder eine
neue Seite –, sonst wird direkt angelegt. Node-Ansicht und Viewer nutzen dieselben Funktionen.
Ersetzt den Dialog „Menü aus Vorlage …“ (v1.9.1).
"""

from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, QPoint, QEvent, QEventLoop
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QRadioButton, QButtonGroup, QSpinBox, QPushButton, QWidget,
    QApplication,
)

from core import menu_templates as mt
from core.translations import tr, ui_language
from gui.node_editor.controller import GraphController

POPUP_QSS = """
QDialog#create_popup { background-color: #202024; border: 1px solid #3F3F46; border-radius: 10px; }
QDialog#create_popup QLabel { color: #D4D4D8; background: transparent; border: none; }
QDialog#create_popup QRadioButton { background: transparent; border: none; }
QDialog#create_popup QLabel#popup_title { color: #FAFAFA; font-size: 14px; font-weight: bold; }
QDialog#create_popup QLabel#popup_info { color: #A1A1AA; }
QDialog#create_popup QRadioButton { color: #E4E4E7; padding: 3px 0; }
QDialog#create_popup QPushButton { color: #E4E4E7; background-color: #27272A; border: 1px solid #3F3F46;
                                   border-radius: 7px; padding: 6px 14px; }
QDialog#create_popup QPushButton:hover { background-color: #34343A; }
QDialog#create_popup QPushButton#popup_create { color: #18181B; background-color: #FBBF24; border-color: #FBBF24;
                                                font-weight: bold; }
QDialog#create_popup QPushButton#popup_create:hover { background-color: #FCD34D; }
QDialog#create_popup QPushButton#popup_dismiss { background: transparent; border-color: transparent; color: #A1A1AA; }
QDialog#create_popup QPushButton#popup_dismiss:hover { color: #E4E4E7; }
"""

CHOICE_LIKE = "like"


class CreatePopup(QDialog):
    """
    Kleines Fenster für einen Vorschlag mit Entscheidung. Nach exec_at(): True → options() anwenden;
    dismissed True → der Nutzer hat „Nicht benötigt“ gewählt.

    Bewusst kein natives Popup (Qt.Popup): Unter Windows schloss es sich sofort wieder, wenn es während
    eines Mausklicks aufging (v1.9.10). Stattdessen ein rahmenloses Werkzeugfenster mit eigener
    Ereignisschleife; ein Klick daneben, Escape oder ein Wechsel in ein anderes Programm schließen es.
    """

    def __init__(self, controller: GraphController, suggestion: mt.Suggestion, dismissable: bool = True,
                 parent: Optional[QWidget] = None):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint)
        self._activated = False
        self._done = False
        self.setObjectName("create_popup")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(POPUP_QSS)
        self.controller = controller
        self.suggestion = suggestion
        self.dismissed = False
        project = controller.project
        self.film = project.film(suggestion.film_id)
        self.menu = project.menu(suggestion.menu_id)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        self.lbl_title = QLabel()
        self.lbl_title.setObjectName("popup_title")
        self.lbl_info = QLabel()
        self.lbl_info.setObjectName("popup_info")
        layout.addWidget(self.lbl_title)
        layout.addWidget(self.lbl_info)

        self.group = QButtonGroup(self)
        self.radios = {}
        self.spin_per_page: Optional[QSpinBox] = None
        self.lbl_preview: Optional[QLabel] = None
        self.options_box = QVBoxLayout()
        self.options_box.setSpacing(2)
        layout.addLayout(self.options_box)
        {mt.ACTION_CHAPTER_MENU: self._build_chapters,
         mt.ACTION_LANGUAGE_MENU: self._build_language}.get(suggestion.action, lambda: None)()

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 8, 0, 0)
        self.btn_dismiss = QPushButton(self.t("pop_dismiss"))
        self.btn_dismiss.setObjectName("popup_dismiss")
        self.btn_dismiss.setToolTip(self.t("pop_dismiss_tip"))
        self.btn_dismiss.setVisible(dismissable)
        self.btn_dismiss.clicked.connect(self._dismiss)
        self.btn_create = QPushButton(self.t("pop_create"))
        self.btn_create.setObjectName("popup_create")
        self.btn_create.setDefault(True)
        self.btn_create.clicked.connect(self.accept)
        buttons.addWidget(self.btn_dismiss)
        buttons.addStretch(1)
        buttons.addWidget(self.btn_create)
        layout.addLayout(buttons)
        self._update_preview()

    def t(self, key: str, **kwargs) -> str:
        text = tr(key, ui_language())
        return text.format(**kwargs) if kwargs else text

    # --- Aufbau je Vorschlag -------------------------------------------------
    def _radio(self, key: str, text: str, checked: bool = False) -> QRadioButton:
        radio = QRadioButton(text)
        radio.setChecked(checked)
        radio.toggled.connect(lambda _on: self._update_preview())
        self.group.addButton(radio)
        self.radios[key] = radio
        self.options_box.addWidget(radio)
        return radio

    def _build_chapters(self):
        film = self.film
        self.lbl_title.setText(self.t("pop_chapters_title", film=film.name))
        like = mt.like_source(self.controller.project, film.id, mt.KIND_CHAPTERS)
        if like is not None:
            self._radio("new", self.t("pop_new"), checked=True)
        row = QHBoxLayout()
        row.setContentsMargins(22 if like is not None else 0, 0, 0, 0)
        row.addWidget(QLabel(self.t("pop_per_page")))
        self.spin_per_page = QSpinBox()
        self.spin_per_page.setRange(1, 24)
        self.spin_per_page.setValue(mt.CHAPTERS_PER_PAGE)
        self.spin_per_page.valueChanged.connect(lambda _v: self._update_preview())
        row.addWidget(self.spin_per_page)
        row.addStretch(1)
        self.options_box.addLayout(row)
        self.lbl_preview = QLabel()
        self.lbl_preview.setObjectName("popup_info")
        self.lbl_preview.setContentsMargins(22 if like is not None else 0, 0, 0, 0)
        self.options_box.addWidget(self.lbl_preview)
        if like is not None:
            self._radio(CHOICE_LIKE, self.t("pop_like", film=like.name))
            self._like_id = like.id

    def _build_language(self):
        film = self.film
        self.lbl_title.setText(self.t("pop_language_title", film=film.name))
        self.lbl_info.setText(self.t("pop_tracks_info", audio=len(film.audio_tracks), subs=len(film.subtitle_tracks)))
        for i, mode in enumerate(mt.language_modes(film)):
            self._radio(mode, self.t(f"pop_mode_{mode}"), checked=(i == 0))
        like = mt.like_source(self.controller.project, film.id, mt.KIND_LANGUAGE)
        if like is not None:
            self._radio(CHOICE_LIKE, self.t("pop_like", film=like.name))
            self._like_id = like.id

    def _update_preview(self):
        self.lbl_info.setVisible(bool(self.lbl_info.text()))
        if self.spin_per_page is None or self.lbl_preview is None:
            return
        n, per_page = len(self.film.chapters), self.spin_per_page.value()
        self.lbl_preview.setText(self.t("pop_preview_chapters", n=n, per_page=per_page, pages=-(-n // per_page)))
        new = self.radios.get("new")
        enabled = new is None or new.isChecked()
        self.spin_per_page.setEnabled(enabled)
        self.lbl_preview.setEnabled(enabled)

    # --- Ergebnis ------------------------------------------------------------
    def choice(self) -> Optional[str]:
        return next((key for key, radio in self.radios.items() if radio.isChecked()), None)

    def options(self) -> dict:
        """Gewählte Optionen für apply_suggestion()."""
        chosen = self.choice()
        opts = {}
        if chosen == CHOICE_LIKE:
            opts["like"] = self._like_id
        if self.suggestion.action == mt.ACTION_CHAPTER_MENU and self.spin_per_page is not None:
            opts["per_page"] = self.spin_per_page.value()
        elif self.suggestion.action == mt.ACTION_LANGUAGE_MENU and chosen != CHOICE_LIKE:
            opts["mode"] = chosen
        return opts

    def _dismiss(self):
        self.dismissed = True
        self.reject()

    def show_at(self, screen_pos: QPoint):
        """Neben der Maus öffnen, ganz auf dem Bildschirm."""
        self.adjustSize()
        screen = QApplication.screenAt(screen_pos) or QApplication.primaryScreen()
        area = screen.availableGeometry() if screen is not None else None
        x, y = screen_pos.x() + 8, screen_pos.y() + 8
        if area is not None:
            x = max(area.left(), min(x, area.right() - self.width()))
            y = max(area.top(), min(y, area.bottom() - self.height()))
        self.move(x, y)

    def exec_at(self, screen_pos: QPoint) -> bool:
        """Neben der Maus zeigen und warten, bis angelegt, abgelehnt oder geschlossen wurde."""
        self.show_at(screen_pos)
        loop = QEventLoop()
        self.finished.connect(loop.quit)
        app = QApplication.instance()
        app.installEventFilter(self)
        try:
            self.show()
            self.raise_()
            self.activateWindow()
            self.btn_create.setFocus()
            if self.isVisible():
                loop.exec()
        finally:
            app.removeEventFilter(self)
        return self.result() == QDialog.Accepted

    def eventFilter(self, obj, event) -> bool:
        """Ein Mausklick außerhalb schließt das Fenster (und wirkt nicht zusätzlich dahinter)."""
        if event.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick) and self.isVisible() \
                and isinstance(obj, QWidget) and obj.window() is not self:
            if not self.frameGeometry().contains(event.globalPosition().toPoint()):
                self.reject()
                return True
        return False

    def event(self, event) -> bool:
        # In ein anderes Programm gewechselt: schließen (erst, nachdem das Fenster einmal aktiv war,
        # und nicht, wenn es gerade durch „Anlegen“ oder „Nicht benötigt“ zugeht)
        if event.type() == QEvent.WindowActivate:
            self._activated = True
        elif event.type() == QEvent.WindowDeactivate and self._activated and self.isVisible() and not self._done:
            self.reject()
        return super().event(event)

    def done(self, result: int):
        self._done = True
        super().done(result)


def apply_suggestion(controller: GraphController, suggestion: mt.Suggestion,
                     options: Optional[dict] = None) -> Tuple[List[str], str]:
    """
    Legt an, was der Vorschlag verspricht (ein Rückgängig-Schritt), verlinkt vom Menü des Vorschlags.
    Gibt (IDs der angelegten bzw. geänderten Menüs, Meldung für die Statusleiste) zurück.
    Wirft menu_templates.TemplateError.
    """
    opts = options or {}
    t = lambda key, **kw: tr(key, ui_language()).format(**kw)
    action, film_id, menu_id = suggestion.action, suggestion.film_id, suggestion.menu_id
    if action == mt.ACTION_TITLES_MENU:
        return [controller.create_titles_menu(parent_id=menu_id)], t("sugg_done_titles")
    if action in (mt.ACTION_CHAPTER_MENU, mt.ACTION_LANGUAGE_MENU):
        kind = mt.KIND_CHAPTERS if action == mt.ACTION_CHAPTER_MENU else mt.KIND_LANGUAGE
        if opts.get("like"):
            created = controller.create_menus_like(opts["like"], film_id, kind, parent_id=menu_id)
        elif kind == mt.KIND_CHAPTERS:
            created = controller.create_chapter_menus(film_id, opts.get("per_page", mt.CHAPTERS_PER_PAGE),
                                                      parent_id=menu_id)
        else:
            created = controller.create_language_menus(film_id, opts.get("mode"), parent_id=menu_id)
        if kind == mt.KIND_LANGUAGE:
            return created, t("sugg_done_language")
        return created, t("sugg_done_chapters") if len(created) == 1 else t("sugg_done_chapter_pages", n=len(created))
    return [], ""


def dismiss_suggestion(controller: GraphController, suggestion: mt.Suggestion):
    """„Nicht benötigt“: für den Film bzw. (Filmauswahl) für die ganze Disc; Strg+Z holt es zurück."""
    controller.dismiss_hint(suggestion.film_id, suggestion.action)


def activate_suggestion(controller: GraphController, suggestion: mt.Suggestion, screen_pos: QPoint,
                        parent: Optional[QWidget] = None, dismissable: bool = True) -> Tuple[List[str], str]:
    """
    Klick auf einen Vorschlag: mit Entscheidung über das Fenster, sonst direkt. Gibt wie
    apply_suggestion (IDs, Meldung) zurück; ([], "") wenn abgebrochen oder abgelehnt.
    """
    options = None
    if suggestion.needs_choice:
        popup = CreatePopup(controller, suggestion, dismissable, parent)
        accepted = popup.exec_at(screen_pos)
        if popup.dismissed:
            dismiss_suggestion(controller, suggestion)
            return [], ""
        if not accepted:
            return [], ""
        options = popup.options()
    return apply_suggestion(controller, suggestion, options)
