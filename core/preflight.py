# core/preflight.py
"""
Preflight-Check (Konzept Kap. 8): prüft den Disc-Graphen vor dem Export.

- Fehler blockieren den Export (die Disc würde falsch oder gar nicht funktionieren).
- Warnungen weisen auf wahrscheinliche Versehen hin.
- Hinweise sind Vorschläge.
Jede Meldung nennt den betroffenen Knoten, damit die Oberfläche ihn auswählen kann.
"""

import os
from dataclasses import dataclass
from typing import List, Optional

from core.disc_model import DiscProject, START_NODE_ID, BUTTON_NAV, BUTTON_CHAPTER, BUTTON_AUDIO, BUTTON_SUBTITLE, \
    STYLE_SHAPE
from core.disc_rules import Source, check_connection, button_label, resolve_content, is_subtitle_off, \
    start_chain_problems, film_cycles
from core.media_paths import missing_media, media_label
from core.menu_templates import chapter_menus, missing_chapters, suggestion_film, HINT_MISSING_CHAPTERS
from core.translations import tr
from modules.video_tools import warning_text

LANGUAGE_KINDS = (BUTTON_AUDIO, BUTTON_SUBTITLE)

ERROR = "error"
WARNING = "warning"
INFO = "info"


@dataclass
class Issue:
    level: str
    message: str
    node_id: Optional[str] = None
    button_id: Optional[str] = None    # betroffener Button (die Oberfläche wählt ihn mit aus)
    film_id: Optional[str] = None      # mit ACTION_GENERATOR: Film der fehlenden Kapitel (v1.14.2)
    action: Optional[str] = None       # ACTION_GENERATOR: ein Klick öffnet den Generator auf node_id


ACTION_GENERATOR = "generator"
ACTION_RELINK = "relink"           # ein Klick öffnet „Medien neu verknüpfen“ (v1.17.0)


def run_preflight(project: DiscProject, check_files: bool = True) -> List[Issue]:
    """check_files=False: ohne fehlende Mediendateien – der Simulator braucht sie nicht (Platzhalter-Clips)."""
    issues: List[Issue] = []
    add = lambda level, msg, node=None, button=None: issues.append(Issue(level, msg, node, button))

    # --- Start ---------------------------------------------------------------
    if not project.films:
        add(ERROR, tr("pf_no_film"))
    if project.start_target is None:
        add(ERROR, tr("pf_start_unconnected"), START_NODE_ID)
    else:
        check = check_connection(project, Source.start(), project.start_target)
        if not check.allowed:
            add(ERROR, tr("pf_start_reason", reason=check.reason), START_NODE_ID)
        for problem in start_chain_problems(project):
            add(ERROR, problem, START_NODE_ID)

    # --- Filme ---------------------------------------------------------------
    for film in project.films:
        if not film.video_base:
            add(ERROR, tr("pf_film_no_video", film=film.name), film.id)
        check = check_connection(project, Source.film_end(film.id), film.end_target)
        if not check.allowed:
            add(ERROR, tr("pf_film_end_reason", film=film.name, reason=check.reason), film.id)
        # v1.21: Fehler (z. B. 3D-Paar passt nicht zusammen) lassen sich nicht bestätigen
        for w in film.compliance_warnings:
            if w.get("severity") == "error":
                add(ERROR, tr("pf_film_compliance_error", film=film.name, title=warning_text(w, "title"),
                              message=warning_text(w, "message")), film.id)
        hints = [w for w in film.compliance_warnings if w.get("severity") != "error"]
        if hints and not film.warnings_acknowledged:
            add(WARNING, tr("pf_film_hints_unconfirmed", film=film.name, n=len(hints)), film.id)

    if project.main_menu is not None:
        for cycle in film_cycles(project):
            names = " → ".join(f.name for f in cycle + cycle[:1])
            add(WARNING, tr("pf_film_cycle", names=names), cycle[0].id)

    # --- Mediendateien (v1.17.0) ------------------------------------------------
    for ref in (missing_media(project) if check_files else []):
        issues.append(Issue(ERROR, tr("pf_file_missing", file=os.path.basename(ref.path),
                                      what=media_label(project, ref)), ref.owner_id, action=ACTION_RELINK))

    # --- Menüs ---------------------------------------------------------------
    main = project.main_menu
    reachable = _reachable_menus(project)
    used_chapter_films, used_language_films = set(), set()
    for menu in project.menus:
        if main is not None and menu.id not in reachable:
            add(WARNING, tr("pf_menu_unreachable", menu=menu.name), menu.id)
        nav_buttons = [b for b in menu.buttons if b.kind == BUTTON_NAV]
        if not menu.buttons:
            add(WARNING, tr("pf_menu_no_buttons", menu=menu.name), menu.id)
        elif nav_buttons and all(b.target is None for b in nav_buttons):
            add(WARNING, tr("pf_menu_dead_end", menu=menu.name), menu.id)
        for button in menu.buttons:
            label = button_label(project, menu, button) or tr("pf_no_text")
            if button.kind == BUTTON_NAV:
                if button.target is None:
                    add(WARNING, tr("pf_button_unconnected", menu=menu.name, label=label), menu.id, button.id)
                else:
                    check = check_connection(project, Source.button(menu.id, button.id), button.target)
                    if not check.allowed:
                        add(ERROR, tr("pf_button_reason", menu=menu.name, label=label, reason=check.reason),
                            menu.id, button.id)
                continue
            film, idx = resolve_content(project, menu, button)
            if film is None:
                add(ERROR, tr("pf_button_no_film", menu=menu.name, label=label), menu.id, button.id)
            elif button.content_ref is None:
                add(ERROR, tr("pf_button_no_target", menu=menu.name, label=label), menu.id, button.id)
            elif idx is None and not is_subtitle_off(button):
                add(ERROR, tr("pf_button_content_gone", menu=menu.name, label=label, film=film.name),
                    menu.id, button.id)
            if film is not None and button.kind == BUTTON_CHAPTER:
                used_chapter_films.add(film.id)
            if film is not None and button.kind in LANGUAGE_KINDS:
                used_language_films.add(film.id)
        language_films = []
        for b in menu.buttons:
            film = project.film(b.film_id) if b.kind in LANGUAGE_KINDS else None
            if film is not None and film not in language_films:
                language_films.append(film)
        for film in language_films:
            if not _leads_to_film(project, menu, film.id):
                add(INFO, tr("pf_no_way_to_film", menu=menu.name, film=film.name), menu.id)
        if menu.buttons and (main is None or menu.id in reachable):
            _check_geometry(project, menu, add)
        if menu.buttons and menu.button_style.kind == STYLE_SHAPE and not _has_picture(project, menu):
            # v1.14.5: auch das Hauptmenü (Startvorlage mit Form-Buttons, noch ohne Bild)
            add(INFO, tr("pf_shapes_no_picture", menu=menu.name), menu.id)
        elif main is not None and menu.id != main.id and menu.buttons and menu.button_style.kind == STYLE_SHAPE \
                and not _has_own_background(menu):
            add(INFO, tr("pf_shapes_main_background", menu=menu.name), menu.id)

    # --- Kapitel ohne Menü -------------------------------------------------------
    for film in (f for f in project.films if f.id in used_chapter_films):
        missing = [film.chapter_index(ch.id) + 1 for ch in missing_chapters(project, film.id)]
        if missing and HINT_MISSING_CHAPTERS not in film.dismissed_hints:
            pages = chapter_menus(project, film.id)
            text = tr("pf_chapters_missing_one" if len(missing) == 1 else "pf_chapters_missing_many",
                      chapters=_number_ranges(tr("pf_chapter_word"), missing), film=film.name)
            if pages:
                # ein Klick öffnet den Generator auf der letzten Kapitelseite mit genau diesen Kapiteln
                issues.append(Issue(WARNING, text + tr("pf_click_complete"), pages[-1].id, None, film.id,
                                    ACTION_GENERATOR))
            else:
                add(WARNING, text, film.id)

    # --- Grenzen des Menüstroms (v1.14.2) -------------------------------------------
    _check_stream_limits(project, add)
    _check_iso_directory(project, add)

    # --- Vorschläge ------------------------------------------------------------
    if main is not None:
        # nur für Filme, deren Menüs ein Menü vorschlägt (Konzept 2.1, Regel 2)
        offered = {f.id for f in (suggestion_film(project, m) for m in project.menus) if f is not None}
        for film in (f for f in project.films if f.id in offered):
            if len(film.chapters) > 1 and film.id not in used_chapter_films \
                    and "chapter_menu" not in film.dismissed_hints:
                add(INFO, tr("pf_no_chapter_menu", film=film.name, n=len(film.chapters)), film.id)
            tracks = len(film.audio_tracks) + len(film.subtitle_tracks)
            if (len(film.audio_tracks) > 1 or film.subtitle_tracks) and film.id not in used_language_films \
                    and "language_menu" not in film.dismissed_hints and tracks > 1:
                add(INFO, tr("pf_no_language_menu", film=film.name), film.id)

    return issues


def has_errors(issues: List[Issue]) -> bool:
    return any(i.level == ERROR for i in issues)


def _reachable_menus(project: DiscProject) -> set:
    """Wie im Export: über Buttons und Film-Enden (v1.18) vom Hauptmenü aus erreichbar."""
    from core.disc_adapter import reachable_menus
    return reachable_menus(project)


TITLE_SAFE = (96, 54, 1824, 1026)   # 90 % von 1920 × 1080


def _check_stream_limits(project: DiscProject, add):
    """Höchstens 50 Buttons pro Seite (v1.14.3, enger als das Format), ab 40 ein Hinweis; Button-Grafik je
    Menüstrom unter der angenommenen Grenze (core/menu_generator.py: GRAPHICS_BUDGET, nicht gegen die
    Spezifikation geprüft – daher nur Warnung)."""
    from core.menu_generator import MAX_BUTTONS_PER_PAGE, MANY_BUTTONS, GRAPHICS_BUDGET, group_graphics_bytes
    from core.disc_adapter import background_key
    for menu in project.menus:
        count = len(menu.buttons)
        if count > MAX_BUTTONS_PER_PAGE:
            add(ERROR, tr("pf_too_many_buttons", menu=menu.name, n=count, max=MAX_BUTTONS_PER_PAGE), menu.id)
        elif count > MANY_BUTTONS:
            add(INFO, tr("pf_many_buttons", menu=menu.name, n=count), menu.id)
    seen = set()
    for menu in project.menus:
        key = background_key(project, menu)
        if key in seen:
            continue
        seen.add(key)
        size = group_graphics_bytes(project, menu)
        if size > GRAPHICS_BUDGET:
            add(WARNING, tr("pf_graphics_budget", menu=menu.name, mb=f"{size / (1024 * 1024):.0f}",
                            budget=GRAPHICS_BUDGET // (1024 * 1024)), menu.id)


def stream_clip_count(project: DiscProject) -> int:
    """Clips in BDMV/STREAM: je Film einer (3D: Basis und zweites Auge), je Menügruppe zwei (Hintergrund und
    Menüstrom; Menüs „wie Hauptmenü“ teilen sich ihre Gruppe)."""
    from core.disc_adapter import menu_group_index
    films = sum(2 if film.is_3d else 1 for film in project.films)
    return films + 2 * len(set(menu_group_index(project).values()))


def _check_iso_directory(project: DiscProject, add):
    """Konzept 11.2.6: Die ISO fasst höchstens 38 Clips pro Ordner (modules/udf250_writer.py). Nur für ISO; als
    Ordner exportiert gibt es die Grenze nicht."""
    from modules.udf250_writer import MAX_DIR_ENTRIES
    if project.settings.export_format != "iso":
        return
    clips = stream_clip_count(project)
    # Mit 3D liegt in STREAM zusätzlich der Unterordner SSIF
    if clips + any(film.is_3d for film in project.films) > MAX_DIR_ENTRIES:
        add(ERROR, tr("pf_iso_clips", max=MAX_DIR_ENTRIES, n=clips))


def _check_geometry(project: DiscProject, menu, add):
    """Lage und Pfeiltasten der fertigen Menüseite (wie im Export): Überlappung, Title-Safe, Erreichbarkeit."""
    from core.disc_adapter import preview_menu_specs
    specs = preview_menu_specs(project, menu)
    labels = [button_label(project, menu, b) or tr("pf_no_text") for b in menu.buttons]

    for i, a in enumerate(specs):
        for j in range(i + 1, len(specs)):
            b = specs[j]
            if a.x < b.x + b.width and b.x < a.x + a.width and a.y < b.y + b.height and b.y < a.y + a.height:
                add(WARNING, tr("pf_overlap", menu=menu.name, a=labels[i], b=labels[j]), menu.id)

    left, top, right, bottom = TITLE_SAFE
    outside = [labels[i] for i, s in enumerate(specs)
               if s.x < left or s.y < top or s.x + s.width > right or s.y + s.height > bottom]
    if outside:
        add(INFO, tr("pf_title_safe_one" if len(outside) == 1 else "pf_title_safe_many", menu=menu.name,
                     labels=_quoted(outside)), menu.id)

    # Pfeiltasten: alle Buttons vom Start-Button aus erreichbar? (wie die Prüfung im Simulator)
    by_number = {s.button_id: s for s in specs}
    from core.menu_design import start_button_id
    start = start_button_id(menu)
    start_index = next((n for n, b in enumerate(menu.buttons) if b.id == start), 0)
    seen, todo = set(), [specs[start_index].button_id]
    while todo:
        n = todo.pop()
        if n in seen or n not in by_number:
            continue
        seen.add(n)
        s = by_number[n]
        todo += [s.upper_id, s.lower_id, s.left_id, s.right_id]
    missing = [labels[i] for i, s in enumerate(specs) if s.button_id not in seen]
    if missing:
        add(WARNING, tr("pf_unreachable_one" if len(missing) == 1 else "pf_unreachable_many", menu=menu.name,
                        labels=_quoted(missing)), menu.id)


def _leads_to_film(project: DiscProject, menu, film_id: str) -> bool:
    """Führt von diesem Menü aus (auch über weitere Menüs) ein Button zum Film?"""
    seen, stack = set(), [menu]
    while stack:
        m = stack.pop()
        if m.id in seen:
            continue
        seen.add(m.id)
        for b in m.buttons:
            if b.kind != BUTTON_NAV:
                continue
            if b.target == film_id:
                return True
            target = project.menu(b.target)
            if target is not None:
                stack.append(target)
    return False


def _quoted(labels: List[str]) -> str:
    return ", ".join(tr("pf_quoted", text=t) for t in labels)


def _number_ranges(word: str, numbers: List[int]) -> str:
    """[3, 17, 18, 19, 20] → „Kapitel 3, 17–20“."""
    parts, start = [], None
    for i, n in enumerate(numbers):
        if start is None:
            start = n
        if i + 1 == len(numbers) or numbers[i + 1] != n + 1:
            parts.append(str(start) if start == n else f"{start}–{n}")
            start = None
    return f"{word} {', '.join(parts)}"


def _has_own_background(menu) -> bool:
    bg = menu.background
    return bool(bg.image or bg.video or bg.audio)


def _has_picture(project: DiscProject, menu) -> bool:
    """Zeigt das Menü auf der Disc ein Bild oder Video (eigenes oder wie Hauptmenü)? Nur Musik zählt nicht."""
    from core.disc_adapter import effective_background
    bg = effective_background(project, menu)
    return bool(bg.image or bg.video)
