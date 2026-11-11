# core/disc_adapter.py
"""
Export-Adapter: übersetzt einen DiscProject-Graphen in die Eingaben der bestehenden,
auf Hardware verifizierten HDMV-Pipeline:
- ProjectState (Titel, Menü-Hintergrund, Export-Einstellungen)
- pages_specs für inject_menu_into_bdmv(pages_specs=...)

Die Pipeline selbst wird nicht verändert. Der Adapter bildet nur Stufe-1-Verbindungen ab
(siehe core/disc_rules.py); alles andere wird als Fehler gemeldet.
"""

from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from core.translations import tr
from core.disc_model import (
    DiscProject, FilmNode, MenuNode, MenuButton,
    BUTTON_NAV, BUTTON_CHAPTER, BUTTON_AUDIO, BUTTON_SUBTITLE,
    DPAD_DIRECTIONS, STYLE_SHAPE, ButtonStyle,
)
from core.disc_rules import Source, check_connection, button_label, resolve_content, is_subtitle_off, has_target, \
    start_chain_problems, starts_3d_film
from core.menu_design import start_button_id


class DiscExportError(Exception):
    """Das Projekt lässt sich mit der aktuellen Stufe nicht exportieren."""
    def __init__(self, problems: List[str]):
        super().__init__("\n".join(problems))
        self.problems = problems


@dataclass
class ExportPlan:
    project_state: object                                   # core.project_state.ProjectState
    pages_specs: Optional[List[Tuple[int, list]]]           # None = Disc ohne Menü
    title_ids: Dict[str, int] = field(default_factory=dict)  # film_id -> Titelnummer (1..N)
    page_ids: Dict[str, int] = field(default_factory=dict)   # menu_id -> IGS-Seitennummer (in seiner Gruppe)
    unreachable_menus: List[str] = field(default_factory=list)
    group_of: Dict[str, int] = field(default_factory=dict)   # menu_id -> Menügruppe (v1.13; 0 = mit Hauptmenü)
    menu_groups: Optional[List[dict]] = None                 # alle Gruppen wie für inject_menu_into_bdmv


def build_export_plan(project: DiscProject) -> ExportPlan:
    problems = _check_stage1(project)
    if problems:
        raise DiscExportError(problems)

    title_ids = {film.id: i for i, film in enumerate(project.films, start=1)}
    main = project.main_menu
    state = _build_project_state(project, main)

    if main is None:
        # Start → erster Film: Disc ohne Menü (bisheriger Export mit enable_menu = False)
        return ExportPlan(project_state=state, pages_specs=None, title_ids=title_ids)

    page_order = _menu_page_order(project, main)
    groups = _menu_groups(project, page_order)
    group_of = {m.id: g for g, menus in enumerate(groups) for m in menus}
    ends = {f: m for f, m in _free_film_ends(project, main).items() if m.id in group_of}
    # Gruppen mit mehreren Seiten bekommen eine unsichtbare Startseite 0 (v1.13); die Menüs folgen ab Seite 1.
    # Ab v1.18 auch Gruppen, in denen ein Film endet: die Startseite wählt Seite und Button aus GPR 7/8.
    with_start = [len(menus) > 1 or any(group_of[menu.id] == g for menu in ends.values())
                  for g, menus in enumerate(groups)]
    page_ids = {}
    for g, menus in enumerate(groups):
        first = 1 if with_start[g] else 0
        page_ids.update({m.id: first + i for i, m in enumerate(menus)})
    num_titles = len(project.films)
    title_ends = _title_end_commands(project, ends, title_ids, page_ids, group_of, num_titles)
    for film in project.films:                     # v1.18.1: Film → Film (nächster Titel)
        if project.film(film.end_target) is not None:
            title_ends[title_ids[film.id]] = title_ids[film.end_target]
    state.title_ends = title_ends or None
    if project.film(project.start_target) is not None:      # v1.18.1: Start → Film (z. B. Trailer vor dem Menü)
        state.first_play_title = title_ids[project.start_target]

    # v1.20: Startet ein Button einen 3D-Film in 2D, merken alle Buttons zu 3D-Filmen ihre Wahl, und die 3D-Titel
    # schalten danach um. Sonst byte-gleich wie bisher.
    with_2d_choice = any(button.play_2d and starts_3d_film(project, button)
                         for menus in groups for menu in menus for button in menu.buttons)
    state.with_2d_choice = with_2d_choice

    menu_groups = []
    for g, menus in enumerate(groups):
        pages = [_start_page()] if with_start[g] else []
        for menu in menus:
            specs = [
                _button_spec(project, menu, button, n, title_ids, page_ids, group_of, num_titles)
                for n, button in enumerate(menu.buttons, start=1)
            ]
            _apply_layout(menu, specs)
            start = start_button_id(menu)          # Standard-Button oder automatisch (v1.14.6)
            for button, spec in zip(menu.buttons, specs):
                spec.is_default = button.id == start
                if with_2d_choice and starts_3d_film(project, button):
                    spec.play_2d = button.play_2d
            pages.append((page_ids[menu.id], specs))
        bg = effective_background(project, menus[0])
        menu_groups.append({"pages_specs": pages, "bg_image": bg.image, "bg_video": bg.video,
                            "bg_audio": bg.audio, "duration": bg.duration, "keep_page": with_start[g]})

    # Nur eine Gruppe mit einer Seite: wie bisher, ohne Gruppenangaben (Menüstrom und Navigation byte-gleich)
    if len(menu_groups) > 1 or menu_groups[0]["keep_page"]:
        state.menu_groups = menu_groups
    unreachable = [m.id for m in project.menus if m.id not in page_ids]
    return ExportPlan(state, menu_groups[0]["pages_specs"], title_ids, page_ids, unreachable, group_of,
                      menu_groups)


def preview_menu_specs(project: DiscProject, menu: MenuNode) -> list:
    """
    Buttons einer einzelnen Menüseite für die Vorschau im Viewer, wie im Export, aber ohne Abbruch bei
    unfertigen Projekten (Buttons ohne Ziel erscheinen mit ihrer Beschriftung bzw. „?“).
    """
    from modules.igs.layout import MenuButtonSpec

    title_ids = {film.id: i for i, film in enumerate(project.films, start=1)}
    main = project.main_menu
    order = _menu_page_order(project, main) if main is not None else []
    page_ids = {m.id: i for i, m in enumerate(order)}
    page_ids.setdefault(menu.id, len(page_ids))

    specs = []
    for n, button in enumerate(menu.buttons, start=1):
        if button.is_content and not has_target(project, menu, button):
            specs.append(MenuButtonSpec(button_id=n, text=button_label(project, menu, button),
                                        action_type="set_page", target_page_id=page_ids[menu.id]))
        else:
            specs.append(_button_spec(project, menu, button, n, title_ids, page_ids))
    _apply_layout(menu, specs)
    return specs


# -------------------------------------------------------------------------
# Prüfung
# -------------------------------------------------------------------------

def _check_stage1(project: DiscProject) -> List[str]:
    problems = []
    if not project.films:
        problems.append(tr("pf_no_film"))
    if project.start_target is None:
        problems.append(tr("pf_start_unconnected"))
    else:
        check = check_connection(project, Source.start(), project.start_target)
        if not check.allowed:
            problems.append(f"Start: {check.reason}")
        problems += start_chain_problems(project)

    for film in project.films:
        check = check_connection(project, Source.film_end(film.id), film.end_target)
        if not check.allowed:
            problems.append(tr("pf_film_end_reason", film=film.name, reason=check.reason))

    for menu in project.menus:
        for button in menu.buttons:
            label = button_label(project, menu, button)
            if button.kind == BUTTON_NAV:
                check = check_connection(project, Source.button(menu.id, button.id), button.target)
                if not check.allowed:
                    problems.append(tr("pf_button_reason", menu=menu.name, label=label, reason=check.reason))
            else:
                film, idx = resolve_content(project, menu, button)
                if film is None:
                    problems.append(tr("pf_button_no_film", menu=menu.name, label=label))
                elif idx is None and not is_subtitle_off(button):
                    problems.append(tr("pf_button_content_gone", menu=menu.name, label=label, film=film.name))
    return problems


# -------------------------------------------------------------------------
# Seiten
# -------------------------------------------------------------------------

def _menu_page_order(project: DiscProject, main: MenuNode) -> List[MenuNode]:
    """Hauptmenü = Seite 0, danach alle erreichbaren Menüs in Breitensuche (Button-Reihenfolge). Menüs, die nur
    ein Filmende erreicht (v1.18), kommen danach, in der Reihenfolge der Filme – bestehende Seiten behalten ihre
    Nummern."""
    order: List[MenuNode] = []
    seen, films_seen = set(), set()
    queue = deque([main])
    films = deque()
    while queue or films:
        if not queue:
            end = films.popleft().end_target
            target = project.menu(end)
            if target is not None and target.id not in seen:
                queue.append(target)
            nxt = project.film(end)                # v1.18.1: Film → Film, dessen Ende zählt auch
            if nxt is not None and nxt.id not in films_seen:
                films_seen.add(nxt.id)
                films.append(nxt)
            continue
        menu = queue.popleft()
        if menu.id in seen:
            continue
        seen.add(menu.id)
        order.append(menu)
        for button in menu.buttons:
            target = project.menu(button.target) if button.kind == BUTTON_NAV else None
            if target is not None and target.id not in seen:
                queue.append(target)
            film = _started_film(project, menu, button)
            if film is not None and film.id not in films_seen:
                films_seen.add(film.id)
                films.append(film)
    return order


def reachable_menus(project: DiscProject) -> set:
    """IDs aller Menüs, die auf der Disc landen (vom Hauptmenü über Buttons und Film-Enden erreichbar, auch über
    Filme nach Filmen)."""
    main = project.main_menu
    return {m.id for m in _menu_page_order(project, main)} if main is not None else set()


def _started_film(project: DiscProject, menu: MenuNode, button: MenuButton) -> Optional[FilmNode]:
    """Film, den der Button startet (Navigations-Button auf einen Film oder Kapitel-Button), sonst None."""
    if button.kind == BUTTON_NAV:
        return project.film(button.target)
    if button.kind == BUTTON_CHAPTER:
        return resolve_content(project, menu, button)[0]
    return None


# -------------------------------------------------------------------------
# Freie Film-Enden (v1.18, Stufe 2.1)
# -------------------------------------------------------------------------

def _free_film_ends(project: DiscProject, main: MenuNode) -> Dict[str, MenuNode]:
    """film_id → Menü, in dem der Film endet, für alle Filme, die nicht ins Hauptmenü zurückkehren."""
    ends = {}
    for film in project.films:
        target = project.menu(film.end_target)
        if target is not None and target.id != main.id:
            ends[film.id] = target
    return ends


def return_button(project: DiscProject, menu: MenuNode, film: FilmNode) -> Optional[MenuButton]:
    """Button, der nach dem Film im Zielmenü ausgewählt wird: der einzige Navigations-Button dort, der den Film
    startet. Gibt es keinen oder mehrere, bleibt es beim Standard-Button (None)."""
    starters = [b for b in menu.buttons if b.kind == BUTTON_NAV and b.target == film.id]
    return starters[0] if len(starters) == 1 else None


def _title_end_commands(project: DiscProject, ends: Dict[str, MenuNode], title_ids: Dict[str, int],
                        page_ids: Dict[str, int], group_of: Dict[str, int], num_titles: int) -> Dict[int, list]:
    """{Titel: Befehle am Filmende} für Filme, die in einem anderen Menü als dem Hauptmenü enden (Film → Film
    ergänzt build_export_plan als Nummer des nächsten Titels)."""
    from modules.bdmv.movie_object_generator import film_end_commands, menu_group_object
    commands = {}
    for film_id, menu in ends.items():
        button = return_button(project, menu, project.film(film_id))
        button_no = menu.buttons.index(button) + 1 if button is not None else 0
        commands[title_ids[film_id]] = film_end_commands(menu_group_object(num_titles, group_of[menu.id]),
                                                         page_ids[menu.id], button_no)
    return commands


def _button_spec(project: DiscProject, menu: MenuNode, button: MenuButton, button_no: int,
                 title_ids: Dict[str, int], page_ids: Dict[str, int],
                 group_of: Optional[Dict[str, int]] = None, num_titles: int = 0):
    from modules.igs.layout import MenuButtonSpec

    text = button_label(project, menu, button)

    if button.kind == BUTTON_NAV:
        if project.film(button.target):
            return MenuButtonSpec(button_id=button_no, text=text, action_type="jump_title",
                                  target_title_id=title_ids[button.target])
        # Menü-Ziel; ein unverbundener Button bleibt auf seiner Seite (Preflight warnt)
        target_page = page_ids.get(button.target, page_ids[menu.id])
        spec = MenuButtonSpec(button_id=button_no, text=text, action_type="set_page", target_page_id=target_page)
        if group_of and button.target in group_of and group_of[button.target] != group_of.get(menu.id):
            # anderer Hintergrund (v1.13): Seite merken, Menü-Objekt der Zielgruppe starten
            from modules.bdmv.movie_object_generator import jump_menu_commands, menu_group_object
            spec.nav_commands = jump_menu_commands(menu_group_object(num_titles, group_of[button.target]),
                                                   target_page)
        return spec

    film, idx = resolve_content(project, menu, button)
    if button.kind == BUTTON_CHAPTER:
        return MenuButtonSpec(button_id=button_no, text=text, action_type="play_chapter",
                              target_title_id=title_ids[film.id], target_chapter_id=idx + 1,
                              chapter_time=film.chapters[idx].time)
    film_title = title_ids.get(film.id, 1) if film is not None else 1
    if button.kind == BUTTON_AUDIO:
        return MenuButtonSpec(button_id=button_no, text=text, action_type="set_stream",
                              target_title_id=film_title, target_audio_id=idx + 1)
    if button.kind == BUTTON_SUBTITLE and not is_subtitle_off(button):
        return MenuButtonSpec(button_id=button_no, text=text, action_type="set_stream",
                              target_title_id=film_title, target_subtitle_id=idx + 1, target_subtitle_on=True)
    return MenuButtonSpec(button_id=button_no, text=text, action_type="set_stream",
                          target_title_id=film_title, target_subtitle_on=False)


def _apply_layout(menu: MenuNode, specs: list):
    """Lage und Größe jedes Buttons (v1.12: immer fest), Form des Button-Stils, Pfeiltasten nach der Lage
    und die pro Button festgelegten Pfeiltasten."""
    from modules.igs.layout import MenuLayoutEngine
    from core.menu_layout import button_box

    shape = shape_style(menu.button_style) if menu.button_style.kind == STYLE_SHAPE else None
    for button, spec in zip(menu.buttons, specs):
        spec.x, spec.y, spec.width, spec.height = button_box(menu, button)
        spec.shape = shape
    MenuLayoutEngine.link_spatial(specs)
    # Pfeiltasten pro Button überschrieben (Inspektor); Ziele, die es nicht mehr gibt, bleiben automatisch
    number = {b.id: n for n, b in enumerate(menu.buttons, start=1)}
    for button, spec in zip(menu.buttons, specs):
        for direction, target in (button.dpad or {}).items():
            if target in number and direction in DPAD_DIRECTIONS:
                setattr(spec, DPAD_DIRECTIONS[direction], number[target])


# -------------------------------------------------------------------------
# Menügruppen (v1.13): eigener Hintergrund pro Menü
# -------------------------------------------------------------------------

def _has_own_background(menu: MenuNode) -> bool:
    return menu.background.is_set


def effective_background(project: DiscProject, menu: MenuNode):
    """Hintergrund, mit dem das Menü auf der Disc erscheint: der eigene oder („wie Hauptmenü“) der des Hauptmenüs."""
    main = project.main_menu
    if _has_own_background(menu) or main is None:
        return menu.background
    return main.background


def background_key(project: DiscProject, menu: MenuNode) -> tuple:
    bg = effective_background(project, menu)
    return (bg.image, bg.video, bg.audio, float(bg.duration))


def _menu_groups(project: DiscProject, page_order: List[MenuNode]) -> List[List[MenuNode]]:
    """Menüs mit gleichem wirksamen Hintergrund bilden eine Gruppe (eine Menü-Playlist, Wechsel ohne Pause).
    Gruppe 0 enthält das Hauptmenü; Reihenfolge wie die Seiten (erreichbar vom Hauptmenü aus)."""
    groups: Dict[tuple, List[MenuNode]] = {}
    for menu in page_order:
        groups.setdefault(background_key(project, menu), []).append(menu)
    return list(groups.values())


def menu_group_index(project: DiscProject) -> Dict[str, int]:
    """menu_id → Menügruppe der erreichbaren Menüs (für Graph und Vorschau; ohne Hauptmenü leer)."""
    main = project.main_menu
    if main is None:
        return {}
    groups = _menu_groups(project, _menu_page_order(project, main))
    return {m.id: g for g, menus in enumerate(groups) for m in menus}


def _start_page():
    """Unsichtbare Startseite 0 einer Gruppe mit mehreren Seiten: ein Button mit auto_action zeigt die gewünschte
    Seite (GPR 7/8) bzw. die erste Seite der Gruppe (modules.bdmv.movie_object_generator.start_page_commands)."""
    from modules.igs.layout import MenuButtonSpec
    from modules.bdmv.movie_object_generator import start_page_commands
    spec = MenuButtonSpec(button_id=1, text="", action_type="set_page", target_page_id=1,
                          nav_commands=start_page_commands(1), x=0, y=0, width=8, height=8,
                          upper_id=1, lower_id=1, left_id=1, right_id=1)
    spec.invisible = spec.auto_action = spec.is_default = True
    return (0, [spec])


def shape_style(style: ButtonStyle):
    """Form-Stil des Menüs für den Grafik-Generator (modules.button_shapes)."""
    from modules.button_shapes import ShapeStyle
    return ShapeStyle(shape=style.shape,
                      color_normal=style.color_normal, opacity_normal=style.opacity_normal,
                      color_selected=style.color_selected, opacity_selected=style.opacity_selected,
                      color_activated=style.color_activated, opacity_activated=style.opacity_activated)


# -------------------------------------------------------------------------
# ProjectState
# -------------------------------------------------------------------------

def _track_to_legacy(track) -> dict:
    data = {"path": track.path, "lang": track.lang}
    data.update(track.extra)
    return data


def _film_to_title(film: FilmNode):
    from core.project_state import MediaTitle
    title = MediaTitle(name=film.name, is_main=film.is_main)
    title.video_base = film.video_base
    title.video_mvc = film.video_mvc
    title.fps = film.fps
    title.audio_tracks = [_track_to_legacy(t) for t in film.audio_tracks]
    title.subtitle_tracks = [_track_to_legacy(t) for t in film.subtitle_tracks]
    title.chapters = [c.time for c in film.chapters]
    title.video_details = film.video_details
    title.compliance_warnings = list(film.compliance_warnings)
    title.warnings_acknowledged = film.warnings_acknowledged
    return title


def _build_project_state(project: DiscProject, main: Optional[MenuNode]):
    from core.project_state import ProjectState
    s = project.settings
    state = ProjectState()
    state.app_lang = s.app_lang
    state.project_name = s.project_name
    state.output_path = s.output_path
    state.export_format = s.export_format
    state.clean_iso_temp = s.clean_iso_temp
    state.disc_title_meta = s.disc_title_meta
    state.disc_title = s.player_title()
    state.menu_no_buttons_test = s.menu_no_buttons_test
    state.menu_resume = s.menu_resume
    state.enable_menu = main is not None
    if main is not None:
        # Stufe 1: alle Menüs teilen den Hintergrund des Hauptmenüs
        state.menu_bg_image = main.background.image
        state.menu_bg_video = main.background.video
        state.menu_bg_audio = main.background.audio
        state.menu_duration = main.background.duration
    state.custom_button_positions = {}  # Positionen stecken bereits in den pages_specs
    state.titles = [_film_to_title(f) for f in project.films]
    state.current_title_index = 0
    return state
