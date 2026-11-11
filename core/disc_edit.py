# core/disc_edit.py
"""
Bearbeitungs-Operationen am DiscProject (Qt-frei). Der GraphController ruft sie
innerhalb rückgängig machbarer Schritte auf.
"""

import copy
from typing import Iterable, List, Optional, Tuple, Union

from core.disc_model import (
    DiscProject, FilmNode, MenuNode, MenuButton, Track, Chapter, ButtonStyle, new_id,
    BUTTON_NAV, BUTTON_CHAPTER, BUTTON_AUDIO, BUTTON_SUBTITLE, SUBTITLE_OFF, STYLE_SHAPE,
)
from core.disc_labels import disc_label
from core.menu_layout import place_new
from core.disc_rules import Source, ConnectionCheck, check_connection, connect, SOURCE_NEW_BUTTON

TRACK_AUDIO = "audio"
TRACK_SUBTITLE = "subtitle"

# Knotenarten, die neu angelegt werden können
NODE_FILM = "film"
NODE_MENU = "menu"


def drop_node_references(project: DiscProject, node_ids: set):
    """Verbindungen und Film-Verweise auf die angegebenen Knoten lösen (Inhalts-Buttons bleiben ohne Ziel)."""
    if project.start_target in node_ids:
        project.start_target = None
    for film in project.films:
        if film.end_target in node_ids:
            film.end_target = None
    for menu in project.menus:
        if menu.default_film_id in node_ids:
            menu.default_film_id = None
        for button in menu.buttons:
            if button.target in node_ids:
                button.target = None
            if button.film_id in node_ids:
                button.film_id = None


def remove_nodes(project: DiscProject, node_ids: Iterable[str]) -> set:
    """
    Entfernt Film- und Menü-Knoten samt aller Verweise. Buttons, die zusammen mit einem der Menüs
    entstanden sind (created_with, z. B. „KAPITEL“ im Hauptmenü), gehen mit; alle anderen Buttons
    bleiben unverbunden. Gibt die entfernten IDs zurück.
    """
    ids = {n for n in node_ids if project.node(n) is not None}
    if not ids:
        return ids
    project.films = [f for f in project.films if f.id not in ids]
    project.menus = [m for m in project.menus if m.id not in ids]
    for menu in project.menus:
        gone = {b.id for b in menu.buttons if b.created_with in ids}
        if gone:
            remove_buttons(project, menu, gone)
    drop_node_references(project, ids)
    for node_id in ids:
        project.view.node_positions.pop(node_id, None)
        project.view.guides.pop(node_id, None)
        project.view.generator.pop(node_id, None)
    return ids


def add_film(project: DiscProject, name: str, pos: Tuple[float, float], film_id: Optional[str] = None) -> FilmNode:
    film = FilmNode(id=film_id or new_id("film"), name=name, color=project.next_film_color(),
                    is_main=not project.films)
    project.films.append(film)
    project.view.node_positions[film.id] = [float(pos[0]), float(pos[1])]
    return film


def new_menu_style() -> ButtonStyle:
    """Button-Stil neuer Menüs: Form – die
    Beschriftung steht im eigenen Hintergrundbild. Text bleibt im Inspektor wählbar (Umschalter Text | Form)."""
    return ButtonStyle(kind=STYLE_SHAPE)


def add_menu(project: DiscProject, name: str, pos: Tuple[float, float], menu_id: Optional[str] = None) -> MenuNode:
    """Leeres Menü mit „ZURÜCK“-Button im Stil „Form“ (v1.13.2). Das erste Menü einer Disc wird zum Hauptmenü."""
    menu = MenuNode(id=menu_id or new_id("menu"), name=name, button_style=new_menu_style())
    back = disc_label("ZURÜCK", project.settings.app_lang)
    add_button(menu, MenuButton(id=new_id("btn"), kind=BUTTON_NAV, label=back))
    project.menus.append(menu)
    project.view.node_positions[menu.id] = [float(pos[0]), float(pos[1])]
    if project.start_target is None:
        project.start_target = menu.id
    return menu


def add_button(menu: MenuNode, button: MenuButton) -> MenuButton:
    """Button ans Ende des Menüs anhängen; ohne Position bekommt er einen freien Platz (core.menu_layout)."""
    if button.position is None:
        place_new(menu, button)
    menu.buttons.append(button)
    return button


def add_nav_button(project: DiscProject, menu_id: str, label: str, target: Optional[str] = None,
                   button_id: Optional[str] = None) -> MenuButton:
    button = MenuButton(id=button_id or new_id("btn"), kind=BUTTON_NAV, label=label, target=target)
    return add_button(project.menu(menu_id), button)


def remove_buttons(project: DiscProject, menu: MenuNode, button_ids: set):
    """Buttons entfernen; Standard-Button und festgelegte Pfeiltasten, die auf sie zeigen, aufräumen."""
    menu.buttons = [b for b in menu.buttons if b.id not in button_ids]
    if menu.default_button_id in button_ids:
        menu.default_button_id = None
    for b in menu.buttons:   # festgelegte Pfeiltasten auf entfernte Buttons werden wieder automatisch
        for direction in [d for d, target in b.dpad.items() if target in button_ids]:
            del b.dpad[direction]


BUTTON_KINDS = (BUTTON_NAV, BUTTON_CHAPTER, BUTTON_AUDIO, BUTTON_SUBTITLE)


def default_film(project: DiscProject, menu: MenuNode) -> Optional[FilmNode]:
    """Standard-Film des Menüs; gibt es nur einen Film, ist er es auch ohne Einstellung."""
    film = project.film(menu.default_film_id)
    if film is None and len(project.films) == 1:
        film = project.films[0]
    return film


def set_button_kind(project: DiscProject, menu_id: str, button_id: str, kind: str):
    """
    Typ wechseln (Navigation, Kapitel, Ton, Untertitel). Das Ziel wird verworfen, eine Navigations-Verbindung
    gelöst. Inhalts-Buttons behalten ihren Film bzw. bekommen den Standard-Film des Menüs. Der Button hängt
    danach an keinem Menü mehr, mit dem er entstanden ist (created_with).
    """
    menu = project.menu(menu_id)
    button = menu.button(button_id) if menu else None
    if button is None or kind not in BUTTON_KINDS or button.kind == kind:
        return
    button.kind = kind
    button.target = None
    button.content_ref = None
    button.created_with = None
    if kind == BUTTON_NAV:
        button.film_id = None
    elif project.film(button.film_id) is None:
        film = default_film(project, menu)
        button.film_id = film.id if film else None


def set_button_content(project: DiscProject, menu_id: str, button_id: str, film_id: Optional[str],
                       content_ref: Optional[str]):
    """Film und Ziel (Kapitel-/Spur-ID bzw. SUBTITLE_OFF) eines Inhalts-Buttons setzen."""
    menu = project.menu(menu_id)
    button = menu.button(button_id) if menu else None
    if button is None or not button.is_content:
        return
    button.film_id = film_id
    button.content_ref = content_ref


def _items_of(film: FilmNode, kind: str) -> list:
    return {BUTTON_CHAPTER: film.chapters, BUTTON_AUDIO: film.audio_tracks,
            BUTTON_SUBTITLE: film.subtitle_tracks}.get(kind, [])


def set_buttons_film(project: DiscProject, menu_id: str, button_ids, film_id: str):
    """
    Film mehrerer Inhalts-Buttons wechseln. Das Ziel wandert mit seiner Nummer: Kapitel 3 zeigt danach auf
    Kapitel 3 des neuen Films (bei Serien das Übliche); gibt es die Nummer dort nicht, bleibt der Button ohne
    Ziel. „Untertitel aus“ bleibt „Aus“.
    """
    menu = project.menu(menu_id)
    new = project.film(film_id)
    if menu is None or new is None:
        return
    for button in menu.buttons:
        if button.id not in button_ids or not button.is_content or button.film_id == film_id:
            continue
        old = project.film(button.film_id)
        if button.content_ref != SUBTITLE_OFF:
            ids = [item.id for item in _items_of(old, button.kind)] if old else []
            index = ids.index(button.content_ref) if button.content_ref in ids else None
            targets = _items_of(new, button.kind)
            button.content_ref = targets[index].id if index is not None and index < len(targets) else None
        button.film_id = film_id


def next_free_target(menu: MenuNode, kind: str, film: Optional[FilmNode]) -> Optional[str]:
    """Erstes Kapitel bzw. erste Spur des Films, die in diesem Menü noch keinen Button hat (bei Untertiteln
    danach „Aus“); None, wenn alles schon da ist."""
    if film is None:
        return None
    used = {b.content_ref for b in menu.buttons if b.kind == kind and b.film_id == film.id}
    for item in _items_of(film, kind):
        if item.id not in used:
            return item.id
    if kind == BUTTON_SUBTITLE and SUBTITLE_OFF not in used:
        return SUBTITLE_OFF
    return None


def add_button_of_kind(project: DiscProject, menu_id: str, kind: str, center: Optional[Tuple[float, float]] = None,
                       label: str = "BUTTON", button_id: Optional[str] = None) -> Optional[MenuButton]:
    """
    Neuer Button aus der Palette (v1.12.2): Navigation unverbunden (verbunden wird im Graph), Inhalts-Buttons mit
    dem Standard-Film und dem ersten Ziel, das im Menü noch fehlt (sonst ohne Ziel). Mit center sitzt die Mitte
    dort (im Bild gehalten), sonst kommt der Button an den nächsten freien Platz.
    """
    from core import menu_layout
    menu = project.menu(menu_id)
    if menu is None or kind not in BUTTON_KINDS:
        return None
    button = MenuButton(id=button_id or new_id("btn"), kind=kind)
    if kind == BUTTON_NAV:
        button.label = label
    else:
        film = default_film(project, menu)
        button.film_id = film.id if film else None
        button.content_ref = next_free_target(menu, kind, film)
    if center is not None:
        w, h = menu_layout.button_size(menu, button)
        x = max(0, min(menu_layout.CANVAS_W - w, int(round(center[0] - w / 2))))
        y = max(0, min(menu_layout.CANVAS_H - h, int(round(center[1] - h / 2))))
        button.position = [x, y]
    return add_button(menu, button)


def button_label_for(project: DiscProject, target_id: Optional[str]) -> str:
    """Vorschlag für die Beschriftung eines neuen Buttons: Name des Ziels in Großbuchstaben."""
    node = project.node(target_id)
    name = node.name.strip() if node else ""
    return name.upper() if name else "BUTTON"


def add_node(project: DiscProject, kind: str, name: str, pos: Tuple[float, float],
             node_id: Optional[str] = None) -> Union[FilmNode, MenuNode]:
    if kind == NODE_FILM:
        return add_film(project, name, pos, node_id)
    return add_menu(project, name, pos, node_id)


def check_new_node_connection(project: DiscProject, source: Source, kind: str) -> ConnectionCheck:
    """
    Prüft, ob source mit einem neu angelegten Knoten dieser Art verbunden werden dürfte.
    Der Knoten wird dafür probeweise in einer Kopie des Projekts angelegt, damit exakt
    dieselben Regeln gelten wie beim Verbinden bestehender Knoten.
    """
    trial = copy.deepcopy(project)
    node = add_node(trial, kind, "", (0.0, 0.0))
    return check_connection(trial, source, node.id)


def connect_to(project: DiscProject, source: Source, target_id: Optional[str]) -> ConnectionCheck:
    """Wie disc_rules.connect; bei „＋ Button“ wird der Button mit dem Ziel angelegt."""
    check = check_connection(project, source, target_id)
    if check.allowed and source.kind == SOURCE_NEW_BUTTON:
        add_nav_button(project, source.node_id, button_label_for(project, target_id), target_id)
        return check
    return connect(project, source, target_id)


def tracks(film: FilmNode, kind: str) -> List[Track]:
    return film.audio_tracks if kind == TRACK_AUDIO else film.subtitle_tracks


def add_track(film: FilmNode, kind: str, path: str, lang: str, track_id: Optional[str] = None) -> Track:
    track = Track(id=track_id or new_id("trk"), path=path, lang=lang)
    tracks(film, kind).append(track)
    return track


def remove_track(film: FilmNode, kind: str, track_id: str):
    items = tracks(film, kind)
    items[:] = [t for t in items if t.id != track_id]


def move_track(film: FilmNode, kind: str, track_id: str, delta: int):
    items = tracks(film, kind)
    idx = next((i for i, t in enumerate(items) if t.id == track_id), None)
    if idx is None:
        return
    new_idx = max(0, min(len(items) - 1, idx + delta))
    if new_idx != idx:
        items.insert(new_idx, items.pop(idx))


def set_track_lang(film: FilmNode, kind: str, track_id: str, lang: str):
    for t in tracks(film, kind):
        if t.id == track_id:
            t.lang = lang


def set_chapter_times(film: FilmNode, times: List[str]):
    """
    Setzt die Kapitelliste. Bestehende Kapitel behalten Position für Position ihre ID
    und ihren Namen, damit Kapitel-Buttons in Menüs gültig bleiben.
    """
    result = []
    for i, time in enumerate(times):
        if i < len(film.chapters):
            old = film.chapters[i]
            result.append(Chapter(id=old.id, time=str(time), name=old.name))
        else:
            result.append(Chapter(id=new_id("ch"), time=str(time)))
    film.chapters = result


# -------------------------------------------------------------------------
# Hintergrund eines Menüs (v1.13.2)
# -------------------------------------------------------------------------

BG_IMAGE = "image"
BG_VIDEO = "video"
BG_AUDIO = "audio"
BG_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp")
BG_AUDIO_EXTS = (".ac3", ".wav")


def background_field(path: str) -> Optional[str]:
    """Wofür eine Datei als Menü-Hintergrund taugt: BG_IMAGE, BG_VIDEO, BG_AUDIO oder None."""
    import os
    from core.media_import import classify_file, KIND_VIDEO
    ext = os.path.splitext(path)[1].lower()
    if ext in BG_IMAGE_EXTS:
        return BG_IMAGE
    if ext in BG_AUDIO_EXTS:
        return BG_AUDIO
    if classify_file(path) == KIND_VIDEO:
        return BG_VIDEO
    return None


def follows_main_background(project: DiscProject, menu: MenuNode) -> bool:
    """Das Menü nutzt den Hintergrund des Hauptmenüs („wie Hauptmenü“)."""
    main = project.main_menu
    return main is not None and menu.id != main.id and not menu.background.is_set


def set_background_file(project: DiscProject, menu_id: str, field: str, path: str,
                        duration: Optional[float] = None):
    """
    Bild, Video oder Musik als Hintergrund eines Menüs. Ein Menü „wie Hauptmenü“ bekommt dabei einen eigenen
    Hintergrund; Ausgangspunkt ist der des Hauptmenüs (die Musik bleibt also), nur ersetzt ein Bild dessen
    Video und ein Video dessen Bild – sonst wäre das Gewählte nicht zu sehen.
    """
    menu = project.menu(menu_id)
    if menu is None or field not in (BG_IMAGE, BG_VIDEO, BG_AUDIO):
        return
    if follows_main_background(project, menu):
        menu.background = copy.deepcopy(project.main_menu.background)
        if field == BG_IMAGE:
            menu.background.video = None
        elif field == BG_VIDEO:
            menu.background.image = None
    setattr(menu.background, field, path)
    if duration:
        menu.background.duration = float(duration)


def clear_background(project: DiscProject, menu_id: str):
    """Zurück auf „wie Hauptmenü“ (beim Hauptmenü: kein Hintergrund)."""
    from core.disc_model import Background
    menu = project.menu(menu_id)
    if menu is not None:
        menu.background = Background()


def starter_project(lang: str = "de") -> DiscProject:
    """
    Ausgangspunkt für ein neues Projekt: Start → Hauptmenü („FILM STARTEN“) → Hauptfilm.
    Der Film ist noch leer; ein Video wird per Drag & Drop hinzugefügt. lang: Sprache der Disc (v1.27.0,
    beim neuen Projekt die der Oberfläche) – Namen und Beschriftungen entstehen in ihr.
    """
    from core.disc_model import START_NODE_ID

    project = DiscProject()
    project.settings.app_lang = lang
    film = add_film(project, disc_label("Hauptfilm", lang), (720.0, 0.0))
    menu = MenuNode(id=new_id("menu"), name=disc_label("Hauptmenü", lang), default_film_id=film.id,
                    button_style=new_menu_style())
    add_button(menu, MenuButton(id=new_id("btn"), kind=BUTTON_NAV, label=disc_label("FILM STARTEN", lang),
                                target=film.id))
    project.menus.append(menu)
    project.start_target = menu.id
    project.view.node_positions[START_NODE_ID] = [0.0, 0.0]
    project.view.node_positions[menu.id] = [320.0, 0.0]
    return project
