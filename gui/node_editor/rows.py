# gui/node_editor/rows.py
"""
Qt-freie Beschreibung dessen, was ein Knoten im Graph anzeigt: Kopfzeile, Unterzeile
und Zeilen (Navigations-Buttons mit Ausgang, zusammengefasste Inhalts-Buttons ohne Ausgang).
"""

from dataclasses import dataclass
from typing import List, Optional

from core.disc_model import (
    DiscProject, MenuNode, FilmNode,
    BUTTON_NAV, BUTTON_CHAPTER, BUTTON_AUDIO,
)
from core.disc_rules import Source, button_label, resolve_content, language_display_name, is_subtitle_off, has_target
from core.translations import tr
from core.menu_templates import (   # noqa: F401 – Aktionen der Vorschläge (auch für Aufrufer dieses Moduls)
    Suggestion, suggestions, ACTION_CHAPTER_MENU, ACTION_LANGUAGE_MENU, ACTION_TITLES_MENU,
)

ROW_OUTPUT = "output"     # Zeile mit Ausgang (Navigations-Button, Film-Ende, Start)
ROW_CONTENT = "content"   # zusammengefasste Inhalts-Buttons (kein Ausgang)
ROW_EMPTY = "empty"       # Platzhalter
ROW_ADD = "add"           # „＋ Button“: Klick bietet an, was von hier aus möglich ist; Ziehen legt einen Button mit Ziel an
ROW_SUGGEST = "suggest"   # Vorschlag (gestrichelt, Konzept 2.1 Regel 2): „＋ KAPITEL“, „＋ TON: ENGLISCH“ …
ADD_BUTTON_TEXT = "＋ Button"
SUGGESTION_TAG = "Vorschlag"


@dataclass
class NodeRow:
    kind: str
    text: str
    source: Optional[Source] = None
    button_id: Optional[str] = None
    warning: bool = False
    action: Optional[str] = None          # ROW_SUGGEST: Art des Vorschlags
    target_id: Optional[str] = None
    film_id: Optional[str] = None         # ROW_SUGGEST: Film, um dessen Inhalte es geht
    button_ids: Optional[List[str]] = None  # ROW_CONTENT: die zusammengefassten Inhalts-Buttons
    suggestion: Optional[Suggestion] = None  # ROW_SUGGEST

    def shows_button(self, button_id: str) -> bool:
        return bool(button_id) and (self.button_id == button_id or button_id in (self.button_ids or []))


def start_rows() -> List[NodeRow]:
    return [NodeRow(ROW_OUTPUT, tr("graph_disc_inserted"), Source.start())]


def film_subtitle(film: FilmNode) -> str:
    parts = ["3D" if film.is_3d else ("2D" if film.video_base else tr("graph_no_video"))]
    if film.chapters:
        parts.append(tr("graph_n_chapters", n=len(film.chapters)))
    if film.audio_tracks:
        parts.append(tr("graph_n_audio", n=len(film.audio_tracks)))
    if film.subtitle_tracks:
        parts.append(tr("graph_n_subs", n=len(film.subtitle_tracks)))
    return " · ".join(parts)


def film_rows(film: FilmNode, project: Optional[DiscProject] = None) -> List[NodeRow]:
    """Nur der Ausgang „Ende“. Menüs zu einem Film schlägt das Menü vor, das zum Film führt (Konzept 2.1)."""
    return [NodeRow(ROW_OUTPUT, tr("graph_end"), Source.film_end(film.id))]


def content_films(project: DiscProject, menu: MenuNode) -> List[FilmNode]:
    """Filme, deren Inhalte (Kapitel, Spuren) das Menü zeigt, in Button-Reihenfolge."""
    films: List[FilmNode] = []
    for b in menu.buttons:
        film = project.film(b.film_id) if b.is_content else None
        if film is not None and film not in films:
            films.append(film)
    return films


def menu_subtitle(project: DiscProject, menu: MenuNode) -> str:
    """Film nur anzeigen, wenn das Menü tatsächlich Inhalte zeigt (bei mehreren Filmen ihre Anzahl)."""
    films = content_films(project, menu)
    if len(films) == 1:
        return f"▣ {films[0].name}"
    if films:
        return "▣ " + tr("graph_n_films", n=len(films))
    return tr("graph_menu")


def _names(names: List[str], limit: int = 3) -> str:
    if len(names) <= limit:
        return ", ".join(names)
    return ", ".join(names[:limit]) + f" +{len(names) - limit}"


def _content_group_text(project: DiscProject, menu: MenuNode, group: list) -> (str, bool):
    kind = group[0].kind
    film = project.film(group[0].film_id)
    resolved = [resolve_content(project, menu, b)[1] for b in group]
    missing = not all(has_target(project, menu, b) for b in group)

    if kind == BUTTON_CHAPTER:
        numbers = [i + 1 for i in resolved if i is not None]
        if numbers and numbers == list(range(numbers[0], numbers[0] + len(numbers))):
            text = tr("graph_chapter", n=numbers[0]) if len(numbers) == 1 else \
                tr("graph_chapter_range", first=numbers[0], last=numbers[-1])
        else:
            text = tr("graph_n_chapters", n=len(group))
        if film:
            text += f" → {film.name}"
    elif kind == BUTTON_AUDIO:
        names = [language_display_name(film.audio_tracks[i].lang) for i in resolved if i is not None] if film else []
        text = tr("graph_audio_names", names=_names(names)) if names else tr("graph_n_audio_tracks", n=len(group))
    else:
        names = []
        for b, i in zip(group, resolved):
            if is_subtitle_off(b):
                names.append(tr("target_subtitle_off"))
            elif film and i is not None:
                names.append(language_display_name(film.subtitle_tracks[i].lang))
        text = tr("graph_sub_names", names=_names(names)) if names else tr("graph_n_sub_tracks", n=len(group))

    if missing:
        text = "⚠ " + text + tr("graph_content_missing")
    return "▸ " + text if not missing else text, missing


def menu_rows(project: DiscProject, menu: MenuNode) -> List[NodeRow]:
    rows: List[NodeRow] = []
    group: list = []

    def flush():
        if group:
            text, missing = _content_group_text(project, menu, group)
            rows.append(NodeRow(ROW_CONTENT, text, warning=missing, button_ids=[b.id for b in group]))
            group.clear()

    for button in menu.buttons:
        if button.kind == BUTTON_NAV:
            flush()
            label = button_label(project, menu, button) or "(ohne Text)"
            rows.append(NodeRow(ROW_OUTPUT, label, Source.button(menu.id, button.id), button.id))
        else:
            if group and (group[0].kind, group[0].film_id) != (button.kind, button.film_id):
                flush()
            group.append(button)
    flush()

    rows += suggestion_rows(project, menu)
    rows.append(NodeRow(ROW_ADD, ADD_BUTTON_TEXT, Source.new_button(menu.id)))
    return rows


def suggestion_rows(project: DiscProject, menu: MenuNode) -> List[NodeRow]:
    """Vorschläge des Menüs als gestrichelte Zeilen (Regel in core.menu_templates.suggestions)."""
    return [NodeRow(ROW_SUGGEST, s.text, action=s.action, film_id=s.film_id, suggestion=s)
            for s in suggestions(project, menu)]


def target_display_name(project: DiscProject, target_id: Optional[str]) -> str:
    node = project.node(target_id)
    return node.name if node else "?"

