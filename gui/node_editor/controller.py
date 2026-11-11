# gui/node_editor/controller.py
"""
GraphController: hält den DiscProject-Graphen und führt alle Änderungen als
rückgängig machbare Schritte über einen QUndoStack aus.

Jeder Schritt speichert einen Schnappschuss des Projekts vor und nach der Änderung.
Das ist bei Disc-Projekten (wenige Dutzend Knoten) schnell genug und schließt
Fehler in handgeschriebenen Undo-Logiken aus.
"""

import copy
from dataclasses import fields as dataclass_fields
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoCommand, QUndoStack

from core.translations import tr, ui_language, undo_text
from core.disc_model import DiscProject, FilmNode, new_id, START_NODE_ID, BUTTON_NAV
from core.disc_rules import Source, check_connection, ConnectionCheck, SOURCE_NEW_BUTTON
from core import disc_edit, media_paths, menu_templates, menu_tools


class _SnapshotCommand(QUndoCommand):
    def __init__(self, controller: "GraphController", text: str, mutate: Callable[[DiscProject], None],
                 merge_key: Optional[tuple] = None):
        super().__init__(text)
        self._controller = controller
        self._mutate = mutate
        self._merge_key = merge_key   # aufeinanderfolgende Schritte mit gleichem Schlüssel werden einer
        self._before: Optional[DiscProject] = None
        self._after: Optional[DiscProject] = None

    def id(self) -> int:
        return 1 if self._merge_key is not None else -1

    def mergeWith(self, other: QUndoCommand) -> bool:
        if not isinstance(other, _SnapshotCommand) or other._merge_key != self._merge_key:
            return False
        self._after = other._after
        return True

    def redo(self):
        if self._after is None:
            self._before = copy.deepcopy(self._controller.project)
            self._mutate(self._controller.project)
            self._after = copy.deepcopy(self._controller.project)
            self._controller.changed.emit()
        else:
            self._controller._restore(self._after)

    def undo(self):
        self._controller._restore(self._before)


class GraphController(QObject):
    changed = Signal()
    button_selected = Signal(str, str)   # (Menü-ID, Button-ID) bzw. ("", "") – Auswahl im Menü-Designer
    selection_changed = Signal(str, list)   # (Menü-ID, alle ausgewählten Button-IDs) – Mehrfachauswahl (v1.12.1)
    tool_hint = Signal(str)                 # Hinweis für den Viewer (Strg+D, v1.14); "" = keiner
    order_preview = Signal(str, list)       # (Menü-ID, Button-IDs in Reihenfolge) – Nummern im Viewer; [] = aus
    color_pick = Signal(str, str)           # (Menü-ID, Stil-Feld „color_…“): Pipette im Viewer (v1.14.4)

    def __init__(self, project: Optional[DiscProject] = None, parent=None):
        super().__init__(parent)
        self.project = project or DiscProject()
        self.undo_stack = QUndoStack(self)
        self.selected_button: Tuple[str, str] = ("", "")          # der zuerst gezeigte Button der Auswahl
        self.selected_buttons: Tuple[str, Tuple[str, ...]] = ("", ())   # alle ausgewählten Buttons (ein Menü)
        self._dup_chain: Optional[Tuple[str, tuple, tuple]] = None   # (Menü, Originale, Kopien) des letzten Strg+D

    # --- Infrastruktur ------------------------------------------------------
    def set_project(self, project: DiscProject):
        """Neues Projekt übernehmen (z. B. nach Laden); Undo-Verlauf wird geleert."""
        self.project = project
        self.undo_stack.clear()
        self.changed.emit()

    def _restore(self, snapshot: DiscProject):
        self.project = copy.deepcopy(snapshot)
        self.changed.emit()

    def execute(self, text: str, mutate: Callable[[DiscProject], None], merge_key: Optional[tuple] = None):
        self.undo_stack.push(_SnapshotCommand(self, undo_text(text), mutate, merge_key))

    # --- Verbindungen ---------------------------------------------------------
    def check(self, source: Source, target_id: Optional[str]) -> ConnectionCheck:
        return check_connection(self.project, source, target_id)

    def connect(self, source: Source, target_id: Optional[str]) -> ConnectionCheck:
        check = self.check(source, target_id)
        if not check.allowed:
            return check

        if source.kind == SOURCE_NEW_BUTTON:
            text = f"Button „{disc_edit.button_label_for(self.project, target_id)}“ anlegen und verbinden"
        else:
            text = "Verbindung lösen" if target_id is None else "Verbinden"
        self.execute(text, lambda p: disc_edit.connect_to(p, source, target_id))
        return check

    # --- Knoten ---------------------------------------------------------------
    def add_menu(self, name: str, pos: Tuple[float, float]) -> str:
        menu_id = new_id("menu")
        self.execute(f"Menü „{name}“ anlegen", lambda p: disc_edit.add_menu(p, name, pos, menu_id))
        return menu_id

    def check_new_node(self, source: Source, kind: str) -> ConnectionCheck:
        return disc_edit.check_new_node_connection(self.project, source, kind)

    def add_connected_node(self, source: Source, kind: str, name: str, pos: Tuple[float, float]) -> Optional[str]:
        """Legt einen Film oder ein Menü an und verbindet source damit (ein Undo-Schritt)."""
        if not self.check_new_node(source, kind).allowed:
            return None
        node_id = new_id(kind)

        def mutate(p: DiscProject):
            disc_edit.add_node(p, kind, name, pos, node_id)
            disc_edit.connect_to(p, source, node_id)

        what = "Film" if kind == disc_edit.NODE_FILM else "Menü"
        self.execute(f"{what} „{name}“ anlegen und verbinden", mutate)
        return node_id

    def remove_menus(self, menu_ids: Iterable[str]):
        ids = {m for m in menu_ids if self.project.menu(m) is not None}
        if ids:
            self.execute("Menü löschen" if len(ids) == 1 else f"{len(ids)} Menüs löschen",
                         lambda p: disc_edit.remove_nodes(p, ids))

    def remove_nodes(self, node_ids: Iterable[str]):
        """Filme und Menüs löschen (der Start-Knoten bleibt immer erhalten)."""
        ids = {n for n in node_ids if self.project.node(n) is not None}
        if ids:
            text = "Knoten löschen" if len(ids) == 1 else f"{len(ids)} Knoten löschen"
            self.execute(text, lambda p: disc_edit.remove_nodes(p, ids))

    # --- Filme ----------------------------------------------------------------
    def add_film(self, name: str, pos: Tuple[float, float]) -> str:
        film_id = new_id("film")
        self.execute(f"Film „{name}“ anlegen", lambda p: disc_edit.add_film(p, name, pos, film_id))
        return film_id

    def edit_film(self, film_id: str, text: str, mutate: Callable[[FilmNode], None]):
        """Beliebige Änderung an einem Film als ein rückgängig machbarer Schritt."""
        if self.project.film(film_id) is None:
            return
        self.execute(text, lambda p: mutate(p.film(film_id)))

    def set_film_fields(self, film_id: str, text: str, **fields):
        film = self.project.film(film_id)
        if film is None or all(getattr(film, k) == v for k, v in fields.items()):
            return

        def mutate(f: FilmNode):
            for k, v in fields.items():
                setattr(f, k, v)

        self.edit_film(film_id, text, mutate)

    def add_track(self, film_id: str, kind: str, path: str, lang: str) -> Optional[str]:
        if self.project.film(film_id) is None:
            return None
        track_id = new_id("trk")
        text = "Tonspur hinzufügen" if kind == disc_edit.TRACK_AUDIO else "Untertitel hinzufügen"
        self.edit_film(film_id, text, lambda f: disc_edit.add_track(f, kind, path, lang, track_id))
        return track_id

    def remove_track(self, film_id: str, kind: str, track_id: str):
        self.edit_film(film_id, "Spur entfernen", lambda f: disc_edit.remove_track(f, kind, track_id))

    def move_track(self, film_id: str, kind: str, track_id: str, delta: int):
        self.edit_film(film_id, "Spur verschieben", lambda f: disc_edit.move_track(f, kind, track_id, delta))

    def set_track_lang(self, film_id: str, kind: str, track_id: str, lang: str):
        film = self.project.film(film_id)
        track = next((t for t in disc_edit.tracks(film, kind) if t.id == track_id), None) if film else None
        if track is None or track.lang == lang:
            return
        self.edit_film(film_id, "Sprache ändern", lambda f: disc_edit.set_track_lang(f, kind, track_id, lang))

    def set_chapter_times(self, film_id: str, times: list, text: str = "Kapitel ändern"):
        film = self.project.film(film_id)
        if film is None or [c.time for c in film.chapters] == list(times):
            return
        self.edit_film(film_id, text, lambda f: disc_edit.set_chapter_times(f, times))

    def remove_chapters(self, film_id: str, chapter_ids: Iterable[str]):
        """Entfernt einzelne Kapitel; die übrigen behalten ihre IDs (Kapitel-Buttons bleiben gültig)."""
        ids = set(chapter_ids)
        film = self.project.film(film_id)
        if film is None or not any(c.id in ids for c in film.chapters):
            return

        def mutate(f: FilmNode):
            f.chapters = [c for c in f.chapters if c.id not in ids]

        self.edit_film(film_id, "Kapitel entfernen", mutate)

    def add_chapter(self, film_id: str, time: str) -> Optional[str]:
        if self.project.film(film_id) is None:
            return None
        chapter_id = new_id("ch")

        def mutate(f: FilmNode):
            from core.disc_model import Chapter
            f.chapters.append(Chapter(id=chapter_id, time=time))

        self.edit_film(film_id, "Kapitel hinzufügen", mutate)
        return chapter_id

    def set_chapter_time(self, film_id: str, chapter_id: str, time: str):
        film = self.project.film(film_id)
        idx = film.chapter_index(chapter_id) if film else None
        if idx is None or film.chapters[idx].time == time:
            return

        def mutate(f: FilmNode):
            f.chapters[f.chapter_index(chapter_id)].time = time

        self.edit_film(film_id, "Kapitelzeit ändern", mutate)

    def set_chapter_name(self, film_id: str, chapter_id: str, name: Optional[str]):
        film = self.project.film(film_id)
        idx = film.chapter_index(chapter_id) if film else None
        if idx is None or film.chapters[idx].name == name:
            return

        def mutate(f: FilmNode):
            f.chapters[f.chapter_index(chapter_id)].name = name

        self.edit_film(film_id, "Kapitel umbenennen", mutate)

    # --- Menü-Hintergrund -------------------------------------------------------
    def set_menu_background(self, menu_id: str, text: str, **fields):
        menu = self.project.menu(menu_id)
        if menu is None or all(getattr(menu.background, k) == v for k, v in fields.items()):
            return

        def mutate(p: DiscProject):
            for k, v in fields.items():
                setattr(p.menu(menu_id).background, k, v)

        self.execute(text, mutate)

    def set_background_file(self, menu_id: str, field: str, path: str, duration: Optional[float] = None):
        """Bild, Video oder Musik als Hintergrund; ein Menü „wie Hauptmenü“ bekommt einen eigenen (v1.13.2)."""
        menu = self.project.menu(menu_id)
        if menu is None or (getattr(menu.background, field, None) == path and not duration):
            return
        self.execute("Hintergrund wählen",
                     lambda p: disc_edit.set_background_file(p, menu_id, field, path, duration))

    def clear_background(self, menu_id: str):
        """Eigener Hintergrund → „wie Hauptmenü“."""
        menu = self.project.menu(menu_id)
        if menu is None or not menu.background.is_set:
            return
        self.execute("Hintergrund wie Hauptmenü", lambda p: disc_edit.clear_background(p, menu_id))

    def relink_media(self, paths: dict):
        """Neue Pfade für fehlende Mediendateien ({MediaRef.key: Pfad}) als ein Schritt (v1.17.0)."""
        if paths:
            self.execute("Medien neu verknüpfen", lambda p: media_paths.apply_relink(p, paths))

    # --- Disc-Einstellungen -----------------------------------------------------
    def set_settings(self, text: str, **fields):
        s = self.project.settings
        if all(getattr(s, k) == v for k, v in fields.items()):
            return

        def mutate(p: DiscProject):
            for k, v in fields.items():
                setattr(p.settings, k, v)

        self.execute(text, mutate)

    def rename_node(self, node_id: str, name: str):
        name = name.strip()
        node = self.project.node(node_id)
        if node is None or not name or node.name == name:
            return
        self.execute(f"Umbenennen in „{name}“", lambda p: setattr(p.node(node_id), "name", name))

    def move_nodes(self, positions: Dict[str, Tuple[float, float]]):
        current = self.project.view.node_positions
        moved = {k: [float(v[0]), float(v[1])] for k, v in positions.items() if current.get(k) != [float(v[0]), float(v[1])]}
        if not moved:
            return

        def mutate(p: DiscProject):
            p.view.node_positions.update(moved)

        self.execute("Verschieben", mutate)

    # --- Rahmen (v1.15.0, Konzept 3.5): reine Ansicht, aber rückgängig machbar -------------
    def add_frame(self, rect, name: str) -> str:
        from core import node_frames
        frame_id = new_id("frame")
        self.execute(f"Rahmen „{name}“ anlegen", lambda p: node_frames.add_frame(p, rect, name, frame_id=frame_id))
        return frame_id

    def set_frame(self, frame_id: str, text: str, **fields):
        from core import node_frames
        group = node_frames.frame(self.project, frame_id)
        if group is None or all(getattr(group, k) == (node_frames.normalized(v) if k == "rect" else v)
                                for k, v in fields.items()):
            return
        self.execute(text, lambda p: node_frames.set_frame(p, frame_id, **fields))

    def remove_frames(self, frame_ids):
        from core import node_frames
        ids = [fid for fid in frame_ids if node_frames.frame(self.project, fid) is not None]
        if ids:
            self.execute("Rahmen löschen", lambda p: node_frames.remove_frames(p, ids))

    def move_frame(self, frame_id: str, dx: float, dy: float, node_ids=(), frame_ids=()):
        """Rahmen samt Inhalt verschieben (ein Rückgängig-Schritt)."""
        from core import node_frames
        if (dx, dy) == (0, 0) or node_frames.frame(self.project, frame_id) is None:
            return
        node_ids, frame_ids = list(node_ids), list(frame_ids)
        self.execute("Rahmen verschieben",
                     lambda p: node_frames.move_frame(p, frame_id, dx, dy, node_ids, frame_ids))

    # --- Buttons --------------------------------------------------------------
    def add_nav_button(self, menu_id: str, label: str) -> Optional[str]:
        if self.project.menu(menu_id) is None:
            return None
        button_id = new_id("btn")
        self.execute(f"Button „{label}“ hinzufügen",
                     lambda p: disc_edit.add_nav_button(p, menu_id, label, button_id=button_id))
        return button_id

    def remove_button(self, menu_id: str, button_id: str):
        menu = self.project.menu(menu_id)
        if menu is None or menu.button(button_id) is None:
            return

        self.execute("Button entfernen", lambda p: disc_edit.remove_buttons(p, p.menu(menu_id), {button_id}))

    def add_button(self, menu_id: str, kind: str, center=None, label: str = "BUTTON") -> Optional[str]:
        """Button einer Art aus der Palette anlegen (ein Schritt) und auswählen (v1.12.2)."""
        if self.project.menu(menu_id) is None:
            return None
        button_id = new_id("btn")
        self.execute("Button hinzufügen", lambda p: disc_edit.add_button_of_kind(
            p, menu_id, kind, center, label=label, button_id=button_id))
        self.select_button(menu_id, button_id)
        return button_id

    def remove_buttons(self, menu_id: str, button_ids):
        """Mehrere Buttons entfernen (ein Schritt)."""
        menu = self.project.menu(menu_id)
        ids = {b.id for b in menu.buttons if b.id in set(button_ids)} if menu else set()
        if not ids:
            return
        text = "Button entfernen" if len(ids) == 1 else f"{len(ids)} Buttons entfernen"
        self.execute(text, lambda p: disc_edit.remove_buttons(p, p.menu(menu_id), ids))

    def reset_button_label(self, menu_id: str, button_id: str):
        """Eigene Beschriftung verwerfen: der Name entsteht wieder aus dem Ziel."""
        menu = self.project.menu(menu_id)
        button = menu.button(button_id) if menu else None
        if button is None or button.label is None:
            return
        if button.kind == BUTTON_NAV:
            label = disc_edit.button_label_for(self.project, button.target)
            if button.label == label:
                return
            self.execute("Name aus dem Ziel", lambda p: setattr(p.menu(menu_id).button(button_id), "label", label))
        else:
            self.execute("Name aus dem Ziel", lambda p: setattr(p.menu(menu_id).button(button_id), "label", None))

    def set_button_kind(self, menu_id: str, button_id: str, kind: str):
        menu = self.project.menu(menu_id)
        button = menu.button(button_id) if menu else None
        if button is None or button.kind == kind:
            return
        self.execute("Button-Typ ändern", lambda p: disc_edit.set_button_kind(p, menu_id, button_id, kind))

    def set_button_content(self, menu_id: str, button_id: str, film_id: Optional[str], content_ref: Optional[str]):
        menu = self.project.menu(menu_id)
        button = menu.button(button_id) if menu else None
        if button is None or (button.film_id, button.content_ref) == (film_id, content_ref):
            return
        self.execute("Ziel ändern",
                     lambda p: disc_edit.set_button_content(p, menu_id, button_id, film_id, content_ref))

    def set_buttons_film(self, menu_id: str, button_ids, film_id: str):
        menu = self.project.menu(menu_id)
        ids = {b.id for b in menu.buttons if b.id in set(button_ids) and b.is_content and b.film_id != film_id} \
            if menu else set()
        if not ids or self.project.film(film_id) is None:
            return
        self.execute("Film ändern", lambda p: disc_edit.set_buttons_film(p, menu_id, ids, film_id))

    def set_menu_fields(self, menu_id: str, text: str, **fields):
        """Felder des Menü-Knotens (z. B. Standard-Film, Standard-Button) als ein Schritt."""
        menu = self.project.menu(menu_id)
        if menu is None or all(getattr(menu, k) == v for k, v in fields.items()):
            return

        def mutate(p: DiscProject):
            for k, v in fields.items():
                setattr(p.menu(menu_id), k, v)

        self.execute(text, mutate)

    def align_buttons(self, menu_id: str, button_ids, how: str):
        from core import menu_design
        trial = copy.deepcopy(self.project)
        menu_design.align_items(trial, menu_id, button_ids, how)
        if trial.menu(menu_id) == self.project.menu(menu_id):
            return
        self.execute("Buttons ausrichten", lambda p: menu_design.align_items(p, menu_id, button_ids, how))

    def match_button_sizes(self, menu_id: str, button_ids, reference_id: str, width: bool = True, height: bool = True):
        from core import menu_design
        trial = copy.deepcopy(self.project)
        menu_design.match_size(trial, menu_id, button_ids, reference_id, width, height)
        if trial.menu(menu_id) == self.project.menu(menu_id):
            return
        self.execute("Gleiche Größe",
                     lambda p: menu_design.match_size(p, menu_id, button_ids, reference_id, width, height))

    def set_button_play_2d(self, menu_id: str, button_id: str, play_2d: bool):
        """Button, der einen 3D-Film startet: in 3D oder 2D (v1.20)."""
        menu = self.project.menu(menu_id)
        button = menu.button(button_id) if menu else None
        if button is None or button.play_2d == play_2d:
            return
        self.execute("Wiedergabe in 2D" if play_2d else "Wiedergabe in 3D",
                     lambda p: setattr(p.menu(menu_id).button(button_id), "play_2d", play_2d))

    def rename_button(self, menu_id: str, button_id: str, label: str):
        label = label.strip()
        menu = self.project.menu(menu_id)
        button = menu.button(button_id) if menu else None
        if button is None or not label or button.label == label:
            return
        self.execute(f"Button umbenennen in „{label}“",
                     lambda p: setattr(p.menu(menu_id).button(button_id), "label", label))

    # --- Inhalts-Menüs aus Vorlagen (v1.9.1) -----------------------------------
    def _execute_trial(self, text: str, action: Callable[[DiscProject], object]):
        """
        Führt action zuerst an einer Kopie aus (Fehler wie TemplateError kommen so vor dem Schritt)
        und übernimmt das Ergebnis dann als einen rückgängig machbaren Schritt. Gibt das Ergebnis
        von action zurück (z. B. die angelegten Menüs, deren IDs damit feststehen).
        """
        trial = copy.deepcopy(self.project)
        result = action(trial)

        def mutate(p: DiscProject):
            for f in dataclass_fields(DiscProject):
                setattr(p, f.name, copy.deepcopy(getattr(trial, f.name)))

        self.execute(text, mutate)
        return result

    def create_chapter_menus(self, film_id: str, per_page: int = menu_templates.CHAPTERS_PER_PAGE,
                             link_from_main: Optional[bool] = None, parent_id: Optional[str] = None) -> List[str]:
        """Kapitelmenü aus der Vorlage (ein Schritt). Wirft TemplateError, z. B. ohne Kapitel.
        Verlinkt im Ausgangsmenü parent_id; ohne parent_id im Hauptmenü, wenn es direkt zum Film führt."""
        pages = self._execute_trial("Kapitelmenü anlegen", lambda p: menu_templates.create_chapter_menus(
            p, film_id, per_page, link_from_main, parent_id))
        return [m.id for m in pages]

    def create_language_menus(self, film_id: str, mode: Optional[str] = None,
                              link_from_main: Optional[bool] = None, parent_id: Optional[str] = None) -> List[str]:
        menus = self._execute_trial("Sprachmenü anlegen", lambda p: menu_templates.create_language_menus(
            p, film_id, mode, link_from_main, parent_id))
        return [m.id for m in menus]

    # --- Menü-Designer (v1.9.3) -------------------------------------------------
    def select_button(self, menu_id: Optional[str], button_id: Optional[str]):
        """
        Gemeinsame Button-Auswahl für Viewer, Inspektor und Node-Ansicht (Ansicht, kein Undo-Schritt). Gehört der
        Button schon zur Mehrfachauswahl, bleibt sie; sonst ist er allein ausgewählt.
        """
        value = (menu_id or "", button_id or "")
        menu_ids = self.selected_buttons
        if not value[1]:
            self._set_selection("", ())
        elif menu_ids[0] != value[0] or value[1] not in menu_ids[1]:
            self._set_selection(value[0], (value[1],))
        if value != self.selected_button:
            self.selected_button = value
            self.button_selected.emit(*value)

    def select_buttons(self, menu_id: Optional[str], button_ids, primary: Optional[str] = None):
        """Mehrere Buttons eines Menüs auswählen; primary (sonst der erste) zeigt sich in Inspektor und Node-Ansicht."""
        ids = tuple(button_ids)
        if not menu_id or not ids:
            self.select_button(None, None)
            return
        self._set_selection(menu_id, ids)
        first = primary if primary in ids else ids[0]
        if (menu_id, first) != self.selected_button:
            self.selected_button = (menu_id, first)
            self.button_selected.emit(menu_id, first)

    def _set_selection(self, menu_id: str, ids: tuple):
        chain = self._dup_chain
        if chain is not None and (chain[0] != menu_id or set(chain[2]) != set(ids)):
            # andere Auswahl: die Strg+D-Folge ist zu Ende
            self._dup_chain = None
            self.tool_hint.emit("")
        if (menu_id, ids) != self.selected_buttons:
            self.selected_buttons = (menu_id, ids)
            self.selection_changed.emit(menu_id, list(ids))

    # --- Werkzeuge (v1.14) ----------------------------------------------------------
    def duplicate_selection(self, menu_id: str) -> List[str]:
        """
        Strg+D: kopiert die Auswahl, zählt die Ziele weiter und wählt die Kopien aus (ein Schritt). Sind genau
        die letzten Kopien ausgewählt, wiederholt es den Versatz, den man ihnen gegeben hat; sonst landet die
        Kopie direkt daneben (menu_tools.first_offset) und man zieht sie bei Bedarf an ihren Platz.
        """
        menu = self.project.menu(menu_id)
        ids = self.selection_in(menu_id)
        if menu is None or not ids:
            return []
        chain = self._dup_chain
        offset, repeat = menu_tools.first_offset(menu, ids), False
        if chain is not None and chain[0] == menu_id and set(chain[2]) == set(ids):
            moved = menu_tools.repeat_offset(menu, chain[1], chain[2])
            if moved is not None and moved != (0, 0):
                offset, repeat = moved, True
        new = [new_id("btn") for _ in ids]
        self.execute("Duplizieren", lambda p: menu_tools.duplicate_buttons(p, menu_id, ids, offset, new))
        self._dup_chain = None
        self.select_buttons(menu_id, new)
        self._dup_chain = (menu_id, tuple(ids), tuple(new))
        self.tool_hint.emit(self._duplicate_hint(menu_id, new, repeat))
        return new

    def _duplicate_hint(self, menu_id: str, copies: List[str], repeat: bool) -> str:
        from core.disc_model import MenuButton
        from core.disc_rules import target_marker
        lang = ui_language()
        menu = self.project.menu(menu_id)
        content = [b for b in menu.buttons if b.id in set(copies) and b.is_content]
        if content:
            first = content[0]
            ref = menu_tools.next_target(self.project, first, len(content))
            following = MenuButton(id="", kind=first.kind, film_id=first.film_id, content_ref=ref)
            nxt = target_marker(self.project, menu, following) if ref else tr("studio_dup_no_more", lang)
        else:
            nxt = tr("studio_dup_unconnected", lang)
        key = "studio_dup_hint_next" if repeat else "studio_dup_hint_first"
        return tr(key, lang).format(next=nxt)

    def arrange_grid(self, menu_id: str, button_ids, cols: int, gap_x: int, gap_y: int):
        """Als Raster anordnen (v1.14.1, ein Schritt)."""
        menu = self.project.menu(menu_id)
        if menu is None or not menu_tools.grid_positions(menu, list(button_ids), cols, gap_x, gap_y):
            return
        self.execute("Als Raster anordnen", lambda p: menu_tools.arrange_grid(
            p, menu_id, list(button_ids), cols, gap_x, gap_y))

    def distribute_buttons(self, menu_id: str, button_ids, horizontal: bool):
        """Gleiche Abstände zwischen dem ersten und dem letzten Button (v1.14.1, ein Schritt)."""
        menu = self.project.menu(menu_id)
        if menu is None or not menu_tools.distribute_positions(menu, list(button_ids), horizontal):
            return
        self.execute("Verteilen", lambda p: menu_tools.distribute(p, menu_id, list(button_ids), horizontal))

    def run_generator(self, menu_id: str, settings) -> List[str]:
        """Generator (v1.14.2): Buttons im Bereich anlegen, wenn nötig mit Folgeseiten (ein Schritt). Die neuen
        Buttons der Ausgangsseite werden ausgewählt; gibt die IDs der neuen Seiten zurück."""
        from core import menu_generator
        menu = self.project.menu(menu_id)
        if menu is None:
            return []
        before = {b.id for b in menu.buttons}
        pages: List[str] = []
        self.execute("Generator", lambda p: pages.extend(menu_generator.generate(p, menu_id, settings)))
        new = [b.id for b in self.project.menu(menu_id).buttons if b.id not in before and b.is_content]
        if new:
            self.select_buttons(menu_id, new)
        return pages

    def assign_sequence(self, menu_id: str, button_ids, kind: str, film_id: Optional[str],
                        start_ref: Optional[str]):
        """Fortlaufend zuweisen: Inhalts-Buttons der Auswahl der Reihe nach belegen (ein Schritt)."""
        if self.project.menu(menu_id) is None or not button_ids:
            return
        self.execute("Ziele der Reihe nach", lambda p: menu_tools.assign_sequence(
            p, menu_id, list(button_ids), kind, film_id, start_ref))

    def selection_in(self, menu_id: str) -> List[str]:
        """Ausgewählte Buttons, die es im Menü (noch) gibt, in Button-Reihenfolge."""
        menu = self.project.menu(menu_id)
        if menu is None or self.selected_buttons[0] != menu_id:
            return []
        chosen = set(self.selected_buttons[1])
        return [b.id for b in menu.buttons if b.id in chosen]

    def move_menu_items(self, menu_id: str, positions=None, merge_key: Optional[tuple] = None):
        """Button-Positionen setzen (ein Schritt; Tippen mit den Pfeiltasten wird über merge_key zu einem
        Schritt zusammengefasst)."""
        from core import menu_design
        menu = self.project.menu(menu_id)
        if menu is None or not positions:
            return
        self.execute("Button verschieben", lambda p: menu_design.move_items(p, menu_id, positions), merge_key)

    def set_button_dpad(self, menu_id: str, button_id: str, direction: str, target_id: Optional[str]):
        """Pfeiltaste überschreiben (target_id) oder wieder automatisch (None)."""
        from core import menu_design
        menu = self.project.menu(menu_id)
        button = menu.button(button_id) if menu else None
        if button is None or button.dpad.get(direction) == target_id:
            return
        text = "Pfeiltaste automatisch" if target_id is None else "Pfeiltaste festlegen"
        self.execute(text, lambda p: menu_design.set_dpad(p, menu_id, button_id, direction, target_id))

    def resize_menu_items(self, menu_id: str, sizes: dict, positions: Optional[dict] = None,
                          merge_key: Optional[tuple] = None):
        """Eigene Größe von Buttons (v1.11.1, ein Schritt)."""
        from core import menu_design
        menu = self.project.menu(menu_id)
        if menu is None or not sizes:
            return
        if positions is None and all((b := menu.button(bid)) is not None and b.size == [int(w), int(h)]
                                     for bid, (w, h) in sizes.items()):
            return
        self.execute("Button-Größe ändern", lambda p: menu_design.resize_items(p, menu_id, sizes, positions),
                     merge_key)

    def clear_button_sizes(self, menu_id: str, button_ids):
        """Eigene Größe verwerfen (ein Schritt)."""
        from core import menu_design
        menu = self.project.menu(menu_id)
        ids = {b.id for b in menu.buttons if b.id in set(button_ids) and b.size is not None} if menu else set()
        if not ids:
            return
        self.execute("Button-Größe zurücksetzen", lambda p: menu_design.clear_sizes(p, menu_id, ids))

    # --- Hilfslinien (v1.9.4) -----------------------------------------------------
    def remove_guide(self, menu_id: str, guide_id: str):
        from core import menu_guides
        self._execute_trial("Hilfslinie löschen", lambda p: menu_guides.remove_guide(p, menu_id, guide_id))

    # --- Eigene Linien in allen Menüs (v1.16.0) -----------------------------------------------
    def add_fixed_guide(self, edge: str, distance) -> str:
        from core import menu_guides
        guide_id = new_id("line")
        self._execute_trial("Eigene Linie anlegen",
                            lambda p: menu_guides.add_fixed_guide(p, edge, distance, guide_id=guide_id))
        return guide_id

    def set_fixed_guide(self, guide_id: str, edge: Optional[str] = None, distance=None):
        from core import menu_guides
        fixed = menu_guides.fixed_guide(self.project, guide_id)
        if fixed is None or ((edge is None or edge == fixed.edge) and
                             (distance is None or menu_guides.clamp_distance(fixed.edge, distance) == fixed.distance)):
            return
        self._execute_trial("Eigene Linie ändern",
                            lambda p: menu_guides.set_fixed_guide(p, guide_id, edge=edge, distance=distance))

    def create_titles_menu(self, parent_id: Optional[str] = None) -> str:
        """Filmauswahl mit einem Button pro Film (v1.9.6), verlinkt im Ausgangsmenü (sonst Hauptmenü)."""
        menu = self._execute_trial("Filmauswahl anlegen",
                                   lambda p: menu_templates.create_titles_menu(p, parent_id=parent_id))
        return menu.id

    def create_menus_like(self, source_film_id: str, target_film_id: str, kind: str,
                          parent_id: Optional[str] = None) -> List[str]:
        """Kapitel- bzw. Sprachmenü wie bei einem anderen Film anlegen (Design übernehmen)."""
        text = "Kapitelmenü wie bei Vorlage" if kind == menu_templates.KIND_CHAPTERS else "Sprachmenü wie bei Vorlage"
        menus = self._execute_trial(text, lambda p: menu_templates.create_menus_like(
            p, source_film_id, target_film_id, kind, parent_id))
        return [m.id for m in menus]

    def dismiss_hint(self, film_id: Optional[str], hint: str):
        """Vorschlag ablehnen („Nicht benötigt“) – für einen Film oder (film_id None) für die ganze Disc;
        gilt auch für den Preflight-Hinweis."""
        if film_id is None:
            if hint not in self.project.settings.dismissed_hints:
                self.execute("Vorschlag ausblenden", lambda p: p.settings.dismissed_hints.append(hint))
            return
        film = self.project.film(film_id)
        if film is None or hint in film.dismissed_hints:
            return
        self.edit_film(film_id, "Vorschlag ausblenden", lambda f: f.dismissed_hints.append(hint))

    def set_button_style(self, menu_id: str, **fields):
        from core import menu_design
        menu = self.project.menu(menu_id)
        if menu is None:
            return
        fields = menu_design.style_changes(menu.button_style, fields)
        if all(getattr(menu.button_style, k) == v for k, v in fields.items()):
            return
        self.execute("Button-Stil ändern", lambda p: menu_design.set_style(p, menu_id, **fields))

    # --- Ansicht (nicht rückgängig machbar, beeinflusst die Disc nicht) ---------
    def set_return_wire_mode(self, mode: str):
        if self.project.view.return_wire_mode != mode:
            self.project.view.return_wire_mode = mode
            self.changed.emit()

    def node_position(self, node_id: str) -> Tuple[float, float]:
        pos = self.project.view.node_positions.get(node_id)
        if pos is None:
            return (0.0, 0.0) if node_id == START_NODE_ID else (400.0, 0.0)
        return (pos[0], pos[1])
