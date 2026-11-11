# gui/studio/main_window.py
"""
OpenBDAuth: neue Arbeitsoberfläche (ab v1.6.0) nach dem Vorbild von DaVinci Fusion.

- Node-Ansicht als zentraler Bereich
- Viewer und Inspektor als andockbare Bereiche, abkoppelbar auf einen zweiten Bildschirm
- Die Auswahl eines Knotens steuert Viewer und Inspektor
- Der Graph (DiscProject) ist die einzige Quelle der Wahrheit
"""

import os
from typing import Optional

import shiboken6

from PySide6 import QtGui
from PySide6.QtCore import Qt, QSettings, QPointF, QTimer, QSize
from PySide6.QtWidgets import (
    QMainWindow, QDockWidget, QToolBar, QToolButton, QMenu, QWidget, QSizePolicy, QFileDialog,
    QMessageBox, QStatusBar, QStackedWidget, QLabel, QStyle,
)

from core.constants import APP_NAME, APP_VERSION
from core.translations import tr, set_ui_language, tr_file_filter, ui_language
from core.disc_model import DiscProject, load_disc_project
from core.disc_edit import starter_project
from gui.node_editor.controller import GraphController
from gui.node_editor.scene import NodeScene
from gui.node_editor.view import NodeView
from gui.icons import counts_pixmap, dot_icon, history_icon, level_icon, LEVEL_ERROR, LEVEL_WARNING, LEVEL_OK
from gui.studio.importer import FilmImporter
from gui.studio.inspector import InspectorPanel
from gui.studio.top_bar import TOOLBAR_QSS, BrandButton
from gui.studio.viewer import ViewerPanel

PAGE_PREPARE, PAGE_DISC, PAGE_BURN = "prepare", "disc", "burn"
PROJECT_FILTER = "OpenBDAuth Projekt (*.bdproj);;Alle Dateien (*.*)"
from gui.app_language import SETTINGS_ORG, SETTINGS_APP, load_app_language, save_app_language
LAYOUT_VERSION = 1
CENTER_MIN_GAP = 16       # px: kleinster Abstand vor dem Projekt-Knopf, wenn die Mitte nicht frei ist


class StudioWindow(QMainWindow):
    def __init__(self, project: Optional[DiscProject] = None, persist_layout: bool = True):
        super().__init__()
        self.setObjectName("StudioWindow")
        self.current_file: Optional[str] = None
        self._persist_layout = persist_layout  # Fensteranordnung lesen/speichern (in Tests aus)
        # Sprache der Oberfläche (v1.27.0): Programm-Einstellung; in Tests (persist_layout aus) die des Projekts
        set_ui_language(load_app_language() if persist_layout else (project.settings.app_lang if project else "de"))
        self.controller = GraphController(project or starter_project(ui_language()), self)
        self.importer = FilmImporter(self.controller, self._default_track_lang, self)

        # Zentral: Node-Ansicht; ab v1.22 daneben die Seite Vorbereiten
        self.scene = NodeScene(self.controller, self)
        self.view = NodeView(self.scene)
        self.pages = QStackedWidget()
        self.pages.addWidget(self.view)
        self.setCentralWidget(self.pages)
        from gui.prepare.page import PreparePage
        self.prepare_page = PreparePage(self.controller, self.importer, self, persist=persist_layout)
        self.pages.addWidget(self.prepare_page)
        # ab v1.30: Brennen – eine fertige ISO 1:1 auf Blu-ray (docs/plaene/brennen.md)
        from gui.burn.page import BurnPage
        self.burn_page = BurnPage(self, persist=persist_layout)
        self.burn_page.prepare_running = lambda: self.prepare_page.is_running
        self.pages.addWidget(self.burn_page)
        self.page = PAGE_DISC
        self._disc_docks_visible = {}

        # Andockbare Bereiche
        self.viewer = ViewerPanel(self.controller)
        self.inspector = InspectorPanel(self.controller, self.importer, self._status)
        self.dock_viewer = self._make_dock("dock_viewer", self.viewer)
        self.dock_inspector = self._make_dock("dock_inspector", self.inspector)
        self.setDockNestingEnabled(True)
        self.setCorner(Qt.TopRightCorner, Qt.RightDockWidgetArea)
        self.setCorner(Qt.BottomRightCorner, Qt.RightDockWidgetArea)

        self._build_toolbar()
        self.setStatusBar(QStatusBar())
        self.lbl_prepare_progress = QLabel()
        self.lbl_prepare_progress.setStyleSheet("color: #FBBF24; padding: 0 8px;")
        self.statusBar().addPermanentWidget(self.lbl_prepare_progress)
        self.importer.needs_prepare.connect(self._offer_prepare)
        self.prepare_page.status.connect(self._status)
        self.prepare_page.progress_text.connect(self.lbl_prepare_progress.setText)
        self.burn_page.status.connect(self._status)
        self.burn_page.progress_text.connect(self._on_burn_progress)
        self.burn_page.simulate_requested.connect(self.open_simulator)

        # Signale
        self.scene.selectionChanged.connect(self._on_selection_changed)
        self.scene.status_message.connect(self._status)
        self.scene.node_activated.connect(self._on_node_activated)
        self.scene.files_dropped.connect(self._on_files_dropped)
        self.importer.status.connect(self._status)
        self.importer.compliance_warnings.connect(self.inspector.show_compliance)
        self.inspector.node_requested.connect(self._reveal_new_node)
        self.viewer.menu_preview.suggestion_activated.connect(self.scene.activate_suggestion)
        self.viewer.menu_preview.suggestion_menu.connect(self._suggestion_menu)
        self.viewer.menu_preview.node_requested.connect(self._reveal_node)   # Fernbedienung: Enter wechselt das Menü
        self.viewer.menu_preview.generator_area.connect(self._on_generator_area)
        self.controller.changed.connect(self._on_model_changed)
        # Gebundene Methoden statt lambda: Qt trennt sie automatisch, wenn das Fenster abgebaut wird
        self.controller.undo_stack.cleanChanged.connect(self._on_clean_changed)

        self.resize(1500, 920)
        self._apply_single_screen_layout()
        if persist_layout:
            self._restore_layout()
        self._last_lang = None
        self._on_model_changed()
        self.view.fit_all()

    # --- Aufbau ---------------------------------------------------------------
    def _make_dock(self, name: str, widget: QWidget) -> QDockWidget:
        dock = QDockWidget(self)
        dock.setObjectName(name)
        dock.setWidget(widget)
        dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        # eigene Titelleiste: Knopf „Andocken“ im abgekoppelten Fenster, Doppelklick füllt den Bildschirm (v1.17.2)
        from gui.studio.widgets import DockTitleBar
        dock.setTitleBarWidget(DockTitleBar(dock, lambda: (self.t("studio_dock_undock"), self.t("studio_dock_back"),
                                                           self.t("studio_dock_floating_tip"))))
        return dock

    @staticmethod
    def _gap(bar: QToolBar, width: int = 18):
        """Abstand zwischen Gruppen (statt Trennstrichen); gibt die Aktion zurück (ein- und ausblendbar)."""
        gap = QWidget()
        gap.setFixedWidth(width)
        gap.setStyleSheet("background: transparent;")
        return bar.addWidget(gap)

    def _build_toolbar(self):
        self._fit_pending = False
        bar = QToolBar(self)
        bar.setObjectName("main_toolbar")
        bar.setMovable(False)
        bar.setToolButtonStyle(Qt.ToolButtonTextOnly)
        bar.setStyleSheet(TOOLBAR_QSS)
        self.addToolBar(Qt.TopToolBarArea, bar)
        self.toolbar = bar

        # Marke (v1.29.0): Logo, Name, Version – öffnet das Info-Fenster bei den Neuerungen
        self.brand = BrandButton()
        self.brand.clicked.connect(self.open_news)
        bar.addWidget(self.brand)
        self._gap(bar, 14)

        # Arbeitsbereiche Vorbereiten | Disc (v1.22) als Reiter (v1.29.0), Brennen ab v1.30
        self.page_actions = {}
        group = QtGui.QActionGroup(self)
        group.setExclusive(True)
        for page in (PAGE_PREPARE, PAGE_DISC, PAGE_BURN):
            act = bar.addAction("", lambda p=page: self.show_page(p))
            act.setCheckable(True)
            group.addAction(act)
            bar.widgetForAction(act).setObjectName("page_tab")
            self.page_actions[page] = act
        self.page_actions[PAGE_DISC].setChecked(True)
        self._gap(bar, 14)

        # Projekt (v1.29.0): Name mit Menü statt der Knöpfe Neu / Öffnen / Speichern; die Tastenkürzel gelten
        # über das Fenster
        self.act_new = QtGui.QAction(self)
        self.act_new.setShortcut(QtGui.QKeySequence.New)
        self.act_new.triggered.connect(self.new_project)
        self.act_open = QtGui.QAction(self)
        self.act_open.setShortcut(QtGui.QKeySequence.Open)
        self.act_open.triggered.connect(self.open_project)
        self.act_save = QtGui.QAction(self)
        self.act_save.setShortcut(QtGui.QKeySequence.Save)
        self.act_save.triggered.connect(self.save_project)
        self.act_save_as = QtGui.QAction(self)
        self.act_save_as.setShortcut(QtGui.QKeySequence.SaveAs)
        self.act_save_as.triggered.connect(self.save_project_as)
        self.menu_project = QMenu(self)
        self.menu_project.addActions([self.act_new, self.act_open])
        self.menu_project.addSeparator()
        self.menu_project.addActions([self.act_save, self.act_save_as])
        self.addActions([self.act_new, self.act_open, self.act_save, self.act_save_as])
        self.btn_project = QToolButton()
        self.btn_project.setObjectName("project_button")
        self.btn_project.setPopupMode(QToolButton.InstantPopup)
        self.btn_project.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn_project.setIconSize(QSize(9, 9))
        self.btn_project.setMenu(self.menu_project)
        self._project_text_width = None          # gekürzt durch _fit_toolbar, None = ganzer Name

        stack = self.controller.undo_stack
        self.act_undo = bar.addAction(history_icon(), "", stack.undo)
        bar.widgetForAction(self.act_undo).setObjectName("icon_action")
        bar.widgetForAction(self.act_undo).setToolButtonStyle(Qt.ToolButtonIconOnly)
        self._disc_actions = [self.act_undo]
        self.act_undo.setShortcut(QtGui.QKeySequence.Undo)
        self.act_undo.setEnabled(False)
        stack.canUndoChanged.connect(self.act_undo.setEnabled)
        stack.undoTextChanged.connect(self._on_undo_text)
        self.act_redo = bar.addAction(history_icon(redo=True), "", stack.redo)
        bar.widgetForAction(self.act_redo).setObjectName("icon_action")
        bar.widgetForAction(self.act_redo).setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.act_redo.setShortcut(QtGui.QKeySequence.Redo)
        self.act_redo.setEnabled(False)
        stack.canRedoChanged.connect(self.act_redo.setEnabled)
        stack.redoTextChanged.connect(self._on_redo_text)
        self._disc_actions.append(self.act_redo)
        self._prepare_actions = []
        bar.addAction(self.prepare_page.act_add)
        self._prepare_actions.append(self.prepare_page.act_add)

        # Rücksprünge als Linien/Sprungmarken: Symbol-Knopf in der Node-Ansicht (nicht in dieser Leiste)
        self.act_returns = QtGui.QAction(self)
        self.act_returns.setCheckable(True)
        self.act_returns.toggled.connect(
            lambda on: self.controller.set_return_wire_mode("markers" if on else "lines"))
        self.view.returns_button.setDefaultAction(self.act_returns)

        # Projekt mittig (v1.30.2): links ein Abstand, den _center_project so setzt, dass der Knopf in der Mitte der
        # Leiste steht; rechts der dehnbare Abstand vor den Aktionen
        self._center_gap = QWidget()
        self._center_gap.setFixedWidth(CENTER_MIN_GAP)
        self._center_gap.setStyleSheet("background: transparent;")
        self._center_gap_action = bar.addWidget(self._center_gap)
        self._project_action = bar.addWidget(self.btn_project)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        spacer.setStyleSheet("background: transparent;")
        self._spacer_action = bar.addWidget(spacer)

        # Ansicht (bis v1.28 „Arbeitsbereich“, verwechselbar mit Vorbereiten | Disc): Anordnung, Viewer, Inspektor
        self.btn_workspace = QToolButton()
        self.btn_workspace.setPopupMode(QToolButton.InstantPopup)
        self.menu_workspace = QMenu(self.btn_workspace)
        self.act_ws_single = self.menu_workspace.addAction("", self._apply_single_screen_layout)
        self.act_ws_dual = self.menu_workspace.addAction("", self._apply_dual_screen_layout)
        self.menu_workspace.addSeparator()
        self.act_ws_viewer = self.dock_viewer.toggleViewAction()
        self.act_ws_inspector = self.dock_inspector.toggleViewAction()
        self.menu_workspace.addAction(self.act_ws_viewer)
        self.menu_workspace.addAction(self.act_ws_inspector)
        self.btn_workspace.setMenu(self.menu_workspace)
        self._disc_actions.append(bar.addWidget(self.btn_workspace))
        self._disc_gap = self._gap(bar, 14)

        self.act_issues = bar.addAction("", self.open_export_dialog)
        bar.widgetForAction(self.act_issues).setObjectName("status_badge")
        bar.widgetForAction(self.act_issues).setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        # Klick: aktuelles Projekt simulieren; Pfeil: fertige Disc (ISO, BDMV-Ordner) öffnen
        self.act_simulate = bar.addAction("", self.simulate_project)
        self.menu_simulate = QMenu(self)
        self.act_simulate_open = self.menu_simulate.addAction("", self.open_simulator)
        sim_button = bar.widgetForAction(self.act_simulate)
        sim_button.setObjectName("simulate_action")
        sim_button.setMenu(self.menu_simulate)
        sim_button.setPopupMode(QToolButton.MenuButtonPopup)
        self._disc_actions += [self.act_issues, self.act_simulate, self._gap(bar, 4)]
        self.act_build = bar.addAction("", self.open_export_dialog)
        bar.widgetForAction(self.act_build).setObjectName("primary_action")   # Hauptaktion des Programms
        self._disc_actions += [self.act_build, self._disc_gap]
        # Vorbereiten: Abbrechen und Starten an derselben Stelle wie „Disc erstellen“
        bar.addAction(self.prepare_page.act_cancel)
        self._prepare_actions.append(self.prepare_page.act_cancel)
        self._prepare_actions.append(self._gap(bar, 4))
        bar.addAction(self.prepare_page.act_start)
        bar.widgetForAction(self.prepare_page.act_start).setObjectName("primary_action")
        self._prepare_actions.append(self.prepare_page.act_start)
        # Brennen: Abbrechen und Brennen an derselben Stelle
        self._burn_actions = [self.burn_page.act_cancel]
        bar.addAction(self.burn_page.act_cancel)
        self._burn_actions.append(self._gap(bar, 4))
        bar.addAction(self.burn_page.act_burn)
        bar.widgetForAction(self.burn_page.act_burn).setObjectName("primary_action")
        self._burn_actions.append(self.burn_page.act_burn)
        for act in self._prepare_actions + self._burn_actions:
            act.setVisible(False)
        self._gap(bar, 8)
        # Sprache der Oberfläche (v1.27.0): DE / EN, gilt für das Programm, nicht für die Disc
        self.btn_ui_lang = QToolButton()
        self.btn_ui_lang.setPopupMode(QToolButton.InstantPopup)
        self.btn_ui_lang.setObjectName("lang_button")
        menu_lang = QMenu(self.btn_ui_lang)
        self.ui_lang_actions = {}
        for lang, name in (("de", "Deutsch"), ("en", "English")):
            act = menu_lang.addAction(name, lambda l=lang: self.set_ui_lang(l))
            act.setCheckable(True)
            self.ui_lang_actions[lang] = act
        self.btn_ui_lang.setMenu(menu_lang)
        bar.addWidget(self.btn_ui_lang)
        # Info, Tastenkürzel und Lizenzen (v1.19.0): seit v1.29.0 über die Marke, F1 bleibt
        self.act_about = QtGui.QAction(self)
        self.act_about.setShortcut(QtGui.QKeySequence.HelpContents)
        self.act_about.triggered.connect(lambda: self.open_about())     # ohne das checked-Argument von triggered
        self.addAction(self.act_about)
        self._export_dialog = None
        self._sim_windows = []

    def t(self, key: str, **kwargs) -> str:
        text = tr(key, ui_language())
        return text.format(**kwargs) if kwargs else text

    def retranslate(self):
        self.act_new.setText(self.t("studio_new"))
        self.act_open.setText(self.t("studio_open"))
        self.act_save.setText(self.t("studio_save"))
        self.act_save_as.setText(self.t("studio_save_as"))
        self.act_undo.setText(self.t("studio_undo"))
        self.act_redo.setText(self.t("studio_redo"))
        self._on_undo_text(self.controller.undo_stack.undoText())
        self._on_redo_text(self.controller.undo_stack.redoText())
        self.brand.setToolTip(self.t("studio_brand_tip"))
        self.view.fit_button.setToolTip(self.t("structure_btn_fit") + " (F)")
        self.btn_workspace.setText(self.t("studio_view") + " ▾")
        self.btn_workspace.setToolTip(self.t("studio_view_tip"))
        self.btn_ui_lang.setText(ui_language().upper())
        self.btn_ui_lang.setToolTip(self.t("studio_ui_lang_tip"))
        for lang, act in self.ui_lang_actions.items():
            act.setChecked(lang == ui_language())
        self.act_ws_single.setText(self.t("studio_ws_single"))
        self.act_ws_dual.setText(self.t("studio_ws_dual"))
        self.act_build.setText(self.t("studio_build_disc"))
        self.act_build.setToolTip(self.t("studio_build_disc_tip"))
        self.act_issues.setToolTip(self.t("studio_issues_tip"))
        self.act_simulate.setText(self.t("studio_simulate"))
        self.act_simulate.setToolTip(self.t("studio_simulate_tip"))
        self.act_simulate_open.setText(self.t("studio_simulate_open"))
        for page, act in self.page_actions.items():
            act.setText(self.t(f"page_{page}"))
            act.setToolTip(self.t(f"page_{page}_tip"))
        self._burn_progress = getattr(self, "_burn_progress", "")
        self._on_burn_progress(self._burn_progress)
        self.prepare_page.retranslate()
        self.burn_page.retranslate()
        self.dock_viewer.setWindowTitle(self.t("studio_dock_viewer"))
        for dock in (self.dock_viewer, self.dock_inspector):
            dock.titleBarWidget().retranslate()
        self.dock_inspector.setWindowTitle(self.t("studio_dock_inspector"))
        self._update_returns_text()
        self._update_project_button()

    # --- Seiten Vorbereiten | Disc (v1.22) ------------------------------------------
    def show_page(self, page: str):
        """Auf der Seite Vorbereiten sind Disc-Docks und Disc-Aktionen ausgeblendet – ausgeblendete Aktionen
        reagieren auch nicht auf ihre Tastenkürzel (z. B. Strg+Z ändert dort nicht unsichtbar den Graphen)."""
        if page == self.page:
            return
        docks = (self.dock_viewer, self.dock_inspector)
        if self.page == PAGE_DISC:
            self._disc_docks_visible = {dock: dock.isVisible() for dock in docks}
            for dock in docks:
                dock.hide()
        if page == PAGE_DISC:
            self.pages.setCurrentWidget(self.view)
            for dock in docks:
                dock.setVisible(self._disc_docks_visible.get(dock, True))
        else:
            self.pages.setCurrentWidget(self.prepare_page if page == PAGE_PREPARE else self.burn_page)
        self.page = page
        for act in self._disc_actions:
            act.setVisible(page == PAGE_DISC)
        for act in self._prepare_actions:
            act.setVisible(page == PAGE_PREPARE)
        for act in self._burn_actions:
            act.setVisible(page == PAGE_BURN)
        self.page_actions[page].setChecked(True)
        self._schedule_fit()

    def _on_burn_progress(self, text: str):
        """Fortschritt im Reiter („Brennen 42 %“), damit er auch von den anderen Bereichen aus sichtbar ist."""
        self._burn_progress = text
        label = self.t(f"page_{PAGE_BURN}")
        self.page_actions[PAGE_BURN].setText(f"{label} {text}" if text else label)
        self._schedule_fit()

    def show_burn(self, iso_path: Optional[str] = None):
        """Bereich Brennen öffnen, optional mit dieser ISO (aus „Disc erstellen“: „Zum Brennen“)."""
        if iso_path:
            self.burn_page.set_iso(iso_path)
        self.show_page(PAGE_BURN)
        self.raise_()
        self.activateWindow()

    def _offer_prepare(self, film_id, paths: list):
        """Datei, die erst vorbereitet werden muss, auf einem Film-Knoten oder der Fläche (v1.23): Zu Vorbereiten
        wechseln, der Auftrag ist dann angelegt, dieser Film als Vorschlag. Gestartet wird bewusst."""
        names = "\n".join(os.path.basename(p) for p in paths)
        if self.confirm_prepare(names):
            self.show_page(PAGE_PREPARE)
            self.prepare_page.add_files(paths, target_film_id=film_id)

    def confirm_prepare(self, names: str) -> bool:
        """Rückfrage „Zu Vorbereiten wechseln?“ (in Tests ersetzbar)."""
        answer = QMessageBox.question(self, self.t("prep_needs_prepare_title"), self.t("prep_needs_prepare", files=names))
        return answer == QMessageBox.Yes

    def open_about(self, tab: Optional[int] = None):
        from gui.studio.about_dialog import TAB_OVERVIEW
        self.about_dialog(TAB_OVERVIEW if tab is None else tab).exec()

    def open_news(self):
        """Klick auf die Marke (v1.29.0): Info-Fenster bei den Neuerungen."""
        from gui.studio.about_dialog import TAB_NEWS
        self.open_about(TAB_NEWS)

    def about_dialog(self, tab: int):
        """Das Info-Fenster (in Tests ersetzbar, exec blockiert)."""
        from gui.studio.about_dialog import AboutDialog
        return AboutDialog(ui_language(), tab, parent=self)

    # --- Arbeitsbereiche --------------------------------------------------------
    def _apply_single_screen_layout(self):
        for dock in (self.dock_viewer, self.dock_inspector):
            dock.setFloating(False)
            dock.show()
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock_inspector)
        self.addDockWidget(Qt.TopDockWidgetArea, self.dock_viewer)
        self.resizeDocks([self.dock_viewer], [int(self.height() * 0.45)], Qt.Vertical)
        self.resizeDocks([self.dock_inspector], [460], Qt.Horizontal)

    def _apply_dual_screen_layout(self):
        screens = QtGui.QGuiApplication.screens()
        if len(screens) < 2:
            self._status(self.t("studio_dual_needs_two"))
            return
        own = self.screen() or screens[0]
        other = next(s for s in screens if s is not own)
        geo = other.availableGeometry()
        viewer_w = int(geo.width() * 0.62)
        for dock in (self.dock_viewer, self.dock_inspector):
            dock.show()
            dock.setFloating(True)
        self.dock_viewer.setGeometry(geo.x(), geo.y(), viewer_w, geo.height())
        self.dock_inspector.setGeometry(geo.x() + viewer_w, geo.y(), geo.width() - viewer_w, geo.height())
        self.showMaximized()

    def _restore_layout(self):
        settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        geometry = settings.value("geometry")
        state = settings.value("state")
        if geometry is not None:
            self.restoreGeometry(geometry)
        if state is not None:
            self.restoreState(state, LAYOUT_VERSION)

    def _save_layout(self):
        settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("state", self.saveState(LAYOUT_VERSION))

    # --- Auswahl & Modell ---------------------------------------------------------
    def _on_selection_changed(self):
        node_id = self.scene.selected_node_id()
        frame_id = self.scene.selected_frame_id()
        if frame_id is not None:
            self.inspector.show_node(frame_id)   # Rahmen: Name und Farbe im Inspektor, Viewer bleibt (v1.15.1)
            return
        if node_id is None and self.scene.selectedItems():
            return  # Mehrfachauswahl: Anzeige unverändert lassen
        self.viewer.show_node(node_id)
        self.inspector.show_node(node_id)

    def _suggestion_menu(self, suggestion, screen):
        """Rechtsklick auf einen Vorschlag im Viewer: dieselben Einträge wie im Menü-Knoten."""
        menu = QMenu(self)
        self.scene.fill_suggestion_menu(menu, suggestion, screen)
        menu.exec(screen)

    def _on_node_activated(self, node_id: str):
        for dock in (self.dock_viewer, self.dock_inspector):
            dock.show()
            dock.raise_()

    def _on_files_dropped(self, film_id: str, files: list, pos: QPointF):
        film = self.importer.import_files(film_id or None, files, pos)
        if film:
            self.scene.rebuild()
            self.scene.select_node(film)

    def set_ui_lang(self, lang: str):
        """Sprache der Oberfläche wechseln (v1.27.0): kein Schritt im Projekt, gespeichert für den nächsten Start."""
        if lang == ui_language():
            return
        set_ui_language(lang)
        if self._persist_layout:
            save_app_language(lang)
        self.controller.changed.emit()      # Graph, Viewer und Inspektor neu aufbauen

    def _on_model_changed(self):
        lang = ui_language()
        if lang != self._last_lang:
            self._last_lang = lang
            self.retranslate()
        markers = self.controller.project.view.return_wire_mode == "markers"
        if self.act_returns.isChecked() != markers:
            self.act_returns.blockSignals(True)
            self.act_returns.setChecked(markers)
            self.act_returns.blockSignals(False)
        self._update_returns_text()
        self._update_title()
        self._update_issue_badge()

    def _update_issue_badge(self):
        from core.preflight import run_preflight, ERROR, WARNING
        issues = run_preflight(self.controller.project)
        errors = sum(1 for i in issues if i.level == ERROR)
        warnings = sum(1 for i in issues if i.level == WARNING)
        # Eigene Symbole statt Emoji (v1.19.0): Fehler und Warnungen je mit Anzahl, sonst Haken und „Bereit“
        badge = self.toolbar.widgetForAction(self.act_issues)
        if errors or warnings:
            counts = ([(LEVEL_ERROR, errors)] if errors else []) + ([(LEVEL_WARNING, warnings)] if warnings else [])
            font = QtGui.QFont(badge.font() if badge is not None else self.font())
            font.setPixelSize(13)          # wie die Schrift der Leiste (TOOLBAR_QSS)
            font.setBold(True)
            pixmap = counts_pixmap(counts, font)
            self.act_issues.setIcon(QtGui.QIcon(pixmap))
            self.act_issues.setText("")
            if badge is not None:
                badge.setIconSize(pixmap.deviceIndependentSize().toSize())
        else:
            self.act_issues.setIcon(level_icon(LEVEL_OK))
            self.act_issues.setText(self.t("studio_ready"))
            if badge is not None:
                badge.setIconSize(QSize(14, 14))
        # Farbe der Plakette: grün bereit, gelb Warnungen, rot Fehler
        state = "error" if errors else "warn" if warnings else "ok"
        if badge is not None and badge.property("state") != state:
            badge.setProperty("state", state)
            badge.style().unpolish(badge)
            badge.style().polish(badge)

    # --- Disc erstellen ---------------------------------------------------------------
    def open_export_dialog(self):
        from gui.studio.export_dialog import ExportDialog
        if self._export_dialog is None:
            self._export_dialog = ExportDialog(self.controller, self)
            self._export_dialog.select_node.connect(self._reveal_node)
            self._export_dialog.select_button.connect(self._reveal_button)
            self._export_dialog.open_generator.connect(self._on_preflight_generator)
            self._export_dialog.open_relink.connect(self.open_relink_dialog)
            self._export_dialog.burn_iso.connect(self._on_export_burn)
            self._export_dialog.iso_created.connect(self.burn_page.add_recent)
        else:
            self._export_dialog.run_checks()
        self._export_dialog.show()
        self._export_dialog.raise_()
        self._export_dialog.activateWindow()

    def _on_export_burn(self, iso_path: str):
        if self._export_dialog is not None:
            self._export_dialog.close()
        self.show_burn(iso_path)

    # --- Disc simulieren ----------------------------------------------------------------
    def simulate_project(self):
        """Öffnet das aktuelle Projekt im Simulator – ohne Disc zu erstellen (modules/sim_disc.py).
        Die Simulations-Disc liegt in einem temporären Ordner, der beim Schließen gelöscht wird."""
        import tempfile
        from PySide6.QtWidgets import QApplication
        from core.disc_adapter import DiscExportError
        from modules.sim_disc import build_simulation_disc, NoMenuError
        from modules.bdsim.disc import load_disc

        project = self.controller.project
        dest = tempfile.mkdtemp(prefix="openbdauth_sim_")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            sim = build_simulation_disc(project, dest)
            disc = load_disc(dest)
        except NoMenuError:
            sim = disc = None
            message = self.t("studio_simulate_no_menu")
        except DiscExportError as e:
            sim = disc = None
            message = self.t("studio_simulate_errors", items="\n".join(f"• {p}" for p in e.problems))
        except Exception as e:
            sim = disc = None
            message = self.t("studio_simulate_build_failed", err=e)
        finally:
            QApplication.restoreOverrideCursor()
        if disc is None:
            import shutil
            shutil.rmtree(dest, ignore_errors=True)
            QMessageBox.information(self, self.t("studio_simulate"), message)
            return None
        name = (project.settings.project_name or "").strip() or "BD_DISC"   # wie der Export
        # Keine Clips auf der Simulations-Disc: Standbilder nicht per ffmpeg suchen, Menü zeigt das Projektbild
        return self._show_simulator(disc, sim.cleanup, menu_backgrounds=sim.menu_backgrounds, frames=False,
                                    title=self.t("studio_simulate_window", name=name))

    def open_simulator(self, path: Optional[str] = None):
        """Öffnet eine fertige Disc (ISO, BDMV-Ordner oder index.bdmv) im Simulator-Fenster."""
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, self.t("studio_simulate_pick"), self.controller.project.settings.output_path or "",
                "Blu-ray (*.iso index.bdmv);;ISO (*.iso);;index.bdmv (index.bdmv)")
            if not path:
                return None
        from modules.bdsim.source import open_disc
        try:
            disc, close = open_disc(path)
        except Exception as e:
            QMessageBox.critical(self, self.t("studio_simulate"), self.t("studio_simulate_failed", err=e))
            return None
        return self._show_simulator(disc, close)

    def _show_simulator(self, disc, on_close, menu_backgrounds: Optional[dict] = None, frames: bool = True,
                        title: Optional[str] = None):
        from gui.studio.simulator import SimulatorWindow
        window = SimulatorWindow(disc, ui_language(), frames=frames, on_close=on_close,
                                 menu_backgrounds=menu_backgrounds, title=title)
        window.destroyed.connect(lambda *_: self._sim_windows.remove(window) if window in self._sim_windows else None)
        self._sim_windows.append(window)
        window.show()
        window.raise_()
        return window

    # --- Generator (v1.14.2) -----------------------------------------------------------
    def open_generator(self, menu_id: str, area=None, film_id: Optional[str] = None, settings=None):
        """Generator-Fenster für ein Menü: aus einem aufgezogenen Bereich (area) oder aus dem Preflight
        („Kapitel … sind in keinem Menü“: settings vorbelegt). Anlegen ist ein Rückgängig-Schritt."""
        from core import menu_generator
        from gui.studio.generator_dialog import GeneratorDialog
        project = self.controller.project
        menu = project.menu(menu_id)
        if menu is None:
            return None
        if settings is None:
            if area is None:
                known = menu_generator.remembered(project, menu_id)
                area = known.area if known else menu_generator.default_area(menu)
            settings = menu_generator.default_settings(project, menu, area, film_id=film_id)
        dialog = GeneratorDialog(self.controller, menu_id, settings, self)
        self._generator_dialog = dialog          # für Tests erreichbar
        accepted = dialog.exec() == GeneratorDialog.Accepted
        self._generator_dialog = None
        if accepted:
            self._reveal_node(menu_id)
            return self.controller.run_generator(menu_id, dialog.settings())
        return None

    def _on_generator_area(self, menu_id: str, area):
        self.open_generator(menu_id, area=area)

    def _on_preflight_generator(self, menu_id: str, film_id: str):
        # erst nach dem Klick in der Liste öffnen (eigene Ereignisschleife)
        QTimer.singleShot(0, lambda: self._generator_from_preflight(menu_id, film_id))

    def _generator_from_preflight(self, menu_id: str, film_id: str):
        from core import menu_generator
        from core.menu_templates import missing_chapters
        project = self.controller.project
        menu = project.menu(menu_id)
        if menu is None:
            return None
        refs = [ch.id for ch in missing_chapters(project, film_id)]
        settings = menu_generator.preset_for_missing(project, menu, film_id, refs)
        return self.open_generator(menu_id, settings=settings)

    def _reveal_button(self, menu_id: str, button_id: str):
        """Preflight-Meldung zu einem Button: Menü zeigen und den Button auswählen (Viewer, Inspektor)."""
        self._reveal_node(menu_id)
        self.controller.select_button(menu_id, button_id)

    def _reveal_node(self, node_id: str):
        self.scene.select_node(node_id)
        item = self.scene.nodes.get(node_id)
        if item is not None:
            self.view.centerOn(item)

    def _reveal_new_node(self, node_id: str):
        """Wie _reveal_node, baut die Szene aber vorher neu auf (der Knoten kann gerade erst entstanden sein)."""
        self.scene.rebuild()
        self._reveal_node(node_id)

    def _update_returns_text(self):
        from gui.node_editor.view import returns_icon
        markers = self.act_returns.isChecked()
        key = "structure_returns_markers" if markers else "structure_returns_lines"
        self.act_returns.setText(self.t(key))
        self.act_returns.setToolTip(self.t(key + "_tip"))
        self.act_returns.setIcon(returns_icon(markers))

    def _update_title(self):
        name = self.controller.project.settings.project_name
        file_part = f" – {os.path.basename(self.current_file)}" if self.current_file else ""
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION} – {name}{file_part}[*]")
        self._update_project_button()

    def _on_clean_changed(self, clean: bool):
        self.setWindowModified(not clean)
        self._update_project_button()

    def _update_project_button(self, fit: bool = True):
        """Projektname in der Leiste (v1.29.0), ● bei ungespeicherten Änderungen, Datei im Tooltip."""
        button = getattr(self, "btn_project", None)
        if button is None or not shiboken6.isValid(button):
            return
        name = self.controller.project.settings.project_name or self.t("studio_untitled")
        if self._project_text_width is not None:
            name = self.btn_project.fontMetrics().elidedText(name, Qt.ElideRight, self._project_text_width)
        self.btn_project.setText(f"{name}  ▾")
        modified = not self.controller.undo_stack.isClean()
        self.btn_project.setIcon(dot_icon() if modified else QtGui.QIcon())
        lines = [self.controller.project.settings.project_name,
                 self.current_file or self.t("studio_not_saved")]
        if modified:
            lines.append(self.t("studio_unsaved_changes"))
        self.btn_project.setToolTip("\n".join(line for line in lines if line))
        if fit:
            self._schedule_fit()

    def _schedule_fit(self):
        """_fit_toolbar nach dem nächsten Layout-Durchgang: vorher hat die Leiste noch ihre alte Breite."""
        if not self._fit_pending:
            self._fit_pending = True
            QTimer.singleShot(0, self._fit_toolbar)

    def _fit_toolbar(self):
        """Passt die Leiste nicht in die Fensterbreite (v1.29.0), wird erst der Projektname gekürzt, dann der
        Schriftzug der Marke ausgeblendet – sonst versteckt Qt die Knöpfe ganz rechts hinter einem »-Pfeil."""
        self._fit_pending = False
        if not shiboken6.isValid(self.toolbar):
            return
        self.layout().activate()             # Leiste auf die aktuelle Fensterbreite bringen
        available = self.toolbar.width()
        for width, compact in ((None, False), (160, False), (160, True), (90, True)):
            self._project_text_width = width
            self.brand.set_compact(compact)
            self._update_project_button(fit=False)
            if self._toolbar_needed_width() <= available:
                break
        self._center_project()

    def _center_project(self):
        """Projekt-Knopf in die Mitte der Leiste (v1.30.2). Gemessen an den echten Positionen: erst mit kleinstem
        Abstand auslegen, dann den Knopf um seinen Abstand zur Mitte verschieben – höchstens um den freien Platz im
        dehnbaren Abstand rechts davon. Ist es eng, rückt er aus der Mitte, nie über andere Knöpfe."""
        bar = self.toolbar
        spacer = bar.widgetForAction(self._spacer_action)
        self._set_center_gap(CENTER_MIN_GAP)        # immer zuerst: ein Abstand aus einem breiteren Fenster schöbe sonst
        if spacer is None or not self.btn_project.isVisible():      # Knöpfe aus der Leiste
            return
        free = spacer.width()
        offset = bar.width() / 2 - self.btn_project.geometry().center().x()
        self._set_center_gap(CENTER_MIN_GAP + int(max(0, min(offset, free))))

    def _set_center_gap(self, width: int):
        if self._center_gap.width() != width or self._center_gap.minimumWidth() != width:
            self._center_gap.setFixedWidth(width)
        layout = self.toolbar.layout()
        layout.invalidate()
        layout.activate()

    def _toolbar_needed_width(self) -> int:
        """Breite aller sichtbaren Elemente ohne den dehnbaren Abstand. Selbst gezählt: sizeHint der Leiste ist
        direkt nach einer Änderung noch der alte Wert."""
        bar = self.toolbar
        widths = []
        for act in bar.actions():
            widget = bar.widgetForAction(act)
            if act.isVisible() and widget is not None and act is not self._spacer_action:
                width = widget.sizeHint().expandedTo(widget.minimumSize()).width()
                widths.append(CENTER_MIN_GAP if act is self._center_gap_action else width)
        spacing = bar.style().pixelMetric(QStyle.PM_ToolBarItemSpacing, None, bar)
        margins = bar.contentsMargins()
        inner = bar.layout().contentsMargins()
        return (sum(widths) + spacing * len(widths) + margins.left() + margins.right() + inner.left() + inner.right()
                + 16)          # Reserve für Rundungen und den Rahmen der Leiste

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule_fit()

    # Die Rückgängig-Liste meldet sich beim Beenden noch einmal, wenn die Schaltflächen
    # bereits abgebaut sind; daher vorher prüfen.
    def _on_undo_text(self, text: str):
        if shiboken6.isValid(self.act_undo):
            self.act_undo.setToolTip(self._history_tip("studio_undo", text, QtGui.QKeySequence.Undo))

    def _on_redo_text(self, text: str):
        if shiboken6.isValid(self.act_redo):
            self.act_redo.setToolTip(self._history_tip("studio_redo", text, QtGui.QKeySequence.Redo))

    def _history_tip(self, key: str, text: str, keys) -> str:
        """„Rückgängig: Button verschieben (Strg+Z)“ – die Knöpfe zeigen seit v1.29.0 nur noch ein Symbol."""
        shortcut = QtGui.QKeySequence(keys).toString(QtGui.QKeySequence.NativeText)
        if ui_language() == "de":
            shortcut = shortcut.replace("Ctrl", "Strg").replace("Shift", "Umschalt")
        return f"{self.t(key)}: {text} ({shortcut})" if text else f"{self.t(key)} ({shortcut})"

    def _status(self, text: str):
        if text:
            self.statusBar().showMessage(text, 8000)
        else:
            self.statusBar().clearMessage()

    def _default_track_lang(self) -> str:
        return "deu" if self.controller.project.settings.app_lang == "de" else "eng"

    # --- Projektdateien -------------------------------------------------------------
    def _confirm_discard(self) -> bool:
        if self.controller.undo_stack.isClean():
            return True
        answer = QMessageBox.question(
            self, self.t("studio_unsaved_title"), self.t("studio_unsaved_text"),
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if answer == QMessageBox.Save:
            return self.save_project()
        return answer == QMessageBox.Discard

    def set_project(self, project: DiscProject, filepath: Optional[str] = None):
        self.current_file = filepath
        self.controller.set_project(project)
        self.controller.undo_stack.setClean()
        self.scene.rebuild()
        self.viewer.show_node(None)
        self.inspector.show_node(None)
        self._on_model_changed()
        self.view.fit_all()

    def new_project(self):
        if self._confirm_discard():
            self.set_project(starter_project(ui_language()))

    def open_project(self):
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, self.t("studio_open"), "",
                                              tr_file_filter(PROJECT_FILTER))
        if path:
            try:
                self.set_project(load_disc_project(path), path)
            except Exception as e:
                QMessageBox.critical(self, self.t("studio_open"), self.t("studio_open_failed", err=e))
                return
            from core.media_paths import missing_media
            if missing_media(self.controller.project):
                QTimer.singleShot(0, self.open_relink_dialog)

    def open_relink_dialog(self):
        """Fehlende Mediendateien suchen und neu verknüpfen (v1.17.0)."""
        from gui.studio.relink_dialog import RelinkDialog
        RelinkDialog(self.controller, self).exec()

    def save_project(self) -> bool:
        if not self.current_file:
            return self.save_project_as()
        return self._write(self.current_file)

    def save_project_as(self) -> bool:
        default = f"{self.controller.project.settings.project_name}.bdproj"
        path, _ = QFileDialog.getSaveFileName(self, self.t("studio_save_as"), default,
                                              tr_file_filter(PROJECT_FILTER))
        if not path:
            return False
        if not path.lower().endswith(".bdproj"):
            path += ".bdproj"
        return self._write(path)

    def _write(self, path: str) -> bool:
        try:
            self.controller.project.save_to_file(path)
        except Exception as e:
            QMessageBox.critical(self, self.t("studio_save"), str(e))
            return False
        self.current_file = path
        self.controller.undo_stack.setClean()
        self._update_title()
        return True

    def closeEvent(self, event):
        if self.burn_page.is_running:
            answer = QMessageBox.question(self, self.t("page_burn"), self.t("burn_running_close"))
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self.burn_page.cancel_running()
            self.burn_page.wait_until_finished(40)
        if self.prepare_page.is_running:
            answer = QMessageBox.question(self, self.t("page_prepare"), self.t("prep_running_close"))
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self.prepare_page.cancel_running()
            self.prepare_page.wait_until_finished(30)
        if not self._confirm_discard():
            event.ignore()
            return
        self.show_page(PAGE_DISC)          # Fensteranordnung mit den Disc-Docks speichern
        self.importer.wait_for_workers()
        for window in list(self._sim_windows):
            window.close()
        if self._persist_layout:
            self._save_layout()
        super().closeEvent(event)
