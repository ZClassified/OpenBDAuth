# core/menu_templates.py
"""
Menü-Vorlagen für Inhalts-Menüs (Kapitel, Ton, Untertitel), Qt-frei.

Vorlagen sind nur eine Starthilfe (Konzept Kap. 4): Sie legen einmalig normale Menü-Knoten mit freien
Buttons an (Lage einmal ausgerechnet, core.menu_layout), füllen die Inhalts-Buttons aus einem Film und
verdrahten die Navigation. Danach gehört alles dem Nutzer; es gibt keine Bindung an die Vorlage, und nichts
wird später heimlich ergänzt. Die Oberfläche fasst jeden Aufruf zu einem Rückgängig-Schritt zusammen.

Was möglich ist, zeigt die Oberfläche als Vorschlag (Konzept 2.1, Regel 2): suggestions() liefert dieselbe
Liste für Node-Ansicht, Viewer und Preflight.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple

from core.disc_model import (
    DiscProject, FilmNode, MenuNode, MenuButton, Chapter, new_id,
    BUTTON_NAV, BUTTON_CHAPTER, BUTTON_AUDIO, BUTTON_SUBTITLE, SUBTITLE_OFF,
)
from core.disc_edit import new_menu_style
from core.disc_labels import disc_label, disc_format
from core.translations import tr
from core.menu_layout import arrange, place_new, ARRANGE_LIST, ARRANGE_GRID, ARRANGE_COLUMNS

KIND_CHAPTERS = "chapters"
KIND_LANGUAGE = "language"

CHAPTERS_PER_PAGE = 8
CHAPTER_GRID_COLS = 4          # 4 × 2 = 8 Kapitel pro Seite; die Plätze passen später zu 16:9-Vorschaubildern
MAX_TRACKS_COMBINED = 4        # bis zu 4 Ton- und 4 Untertitelspuren passen auf eine gemeinsame Seite

LANG_COMBINED = "combined"     # eine Seite „Ton & Untertitel“ (zwei Spalten)
LANG_SEPARATE = "separate"     # zwei Seiten „Ton“ und „Untertitel“
LANG_AUDIO = "audio"           # nur „Ton“
LANG_SUBTITLES = "subtitles"   # nur „Untertitel“

LABEL_BACK = "ZURÜCK"
LABEL_NEXT = "WEITER"
LABEL_MAIN = "HAUPTMENÜ"
LABEL_PLAY = "FILM STARTEN"
LABEL_CHAPTERS = "KAPITEL"
LABEL_LANGUAGE = "SPRACHE"
LABEL_AUDIO = "TON"
LABEL_SUBTITLES = "UNTERTITEL"
LABEL_FILMS = "FILME"
MIN_FILMS_FOR_TITLES = 3       # ab 3 Filmen wird eine Filmauswahl vorgeschlagen (Serien, Kurzfilm-Sammlungen)
HINT_TITLES_MENU = "titles_menu"

# Vorschläge (Konzept 2.1, Regel 2); die Namen sind zugleich die Schlüssel für „Nicht benötigt“.
# „Fehlendes ergänzen“ (Kapitel 9–12, fehlende Spuren) entfällt ab v1.12: ohne Raster gibt es keinen Platz
# dafür; der Preflight meldet fehlende Kapitel, ergänzt wird von Hand (ab v1.14 mit dem Generator).
ACTION_CHAPTER_MENU = "chapter_menu"        # Kapitelmenü anlegen und verlinken
ACTION_LANGUAGE_MENU = "language_menu"      # Sprachmenü anlegen und verlinken
ACTION_TITLES_MENU = HINT_TITLES_MENU       # Filmauswahl (für die ganze Disc)
HINT_MISSING_CHAPTERS = "more_chapters"     # Preflight-Hinweis „Kapitel … sind in keinem Menü“ abgelehnt

LANGUAGE_BUTTON_KINDS = (BUTTON_AUDIO, BUTTON_SUBTITLE)


@dataclass
class Suggestion:
    """Etwas, das es noch nicht gibt, aber geben kann – gestrichelt im Menü-Knoten und im Viewer."""
    action: str
    label: str                     # Beschriftung, z. B. „KAPITEL“, „TON: ENGLISCH“, „KAPITEL 9–12“
    menu_id: str                   # Menü, in dem der Vorschlag steht (von dort verlinkt bzw. dort ergänzt)
    film_id: Optional[str] = None
    needs_choice: bool = False     # beim Anlegen gibt es etwas zu entscheiden (Fenster statt direkt)

    @property
    def text(self) -> str:
        return f"＋ {self.label}"

NODE_SPACING_X = 400.0
NODE_SPACING_Y = 200.0


class TemplateError(ValueError):
    """Die Vorlage passt nicht zum Film (z. B. keine Kapitel)."""


# -------------------------------------------------------------------------
# Abfragen
# -------------------------------------------------------------------------

def chapter_menus(project: DiscProject, film_id: str) -> List[MenuNode]:
    """Kapitelseiten eines Films, sortiert nach ihrem ersten Kapitel (Seiten ohne Kapitel zuletzt)."""
    film = project.film(film_id)
    pages = [m for m in project.menus if any(b.kind == BUTTON_CHAPTER and b.film_id == film_id for b in m.buttons)]
    if film is None:
        return pages

    def first_chapter(menu: MenuNode) -> int:
        indices = _chapter_indices(film, menu)
        return min(indices) if indices else len(film.chapters) + project.menus.index(menu)
    return sorted(pages, key=first_chapter)


def missing_chapters(project: DiscProject, film_id: str) -> List[Chapter]:
    """Kapitel des Films, für die es in keinem Menü einen Kapitel-Button gibt."""
    film = project.film(film_id)
    if film is None:
        return []
    shown = {b.content_ref for m in project.menus for b in m.buttons
             if b.kind == BUTTON_CHAPTER and b.film_id == film_id}
    return [ch for ch in film.chapters if ch.id not in shown]


def main_links_to(project: DiscProject, film_id: str) -> bool:
    """Führt ein Button des Hauptmenüs direkt zum Film? Nur dann gehören seine Menüs ins Hauptmenü
    (bei einer Serie mit Filmauswahl bekäme das Hauptmenü sonst Buttons für jede Folge)."""
    main = project.main_menu
    return main is not None and any(b.kind == BUTTON_NAV and b.target == film_id for b in main.buttons)


def titles_menu(project: DiscProject) -> Optional[MenuNode]:
    """Filmauswahl: ein Menü außer dem Hauptmenü ohne Inhalts-Buttons, dessen Buttons zu mindestens zwei Filmen führen."""
    main = project.main_menu
    return next((m for m in project.menus if (main is None or m.id != main.id)
                 and not any(b.is_content for b in m.buttons) and len(linked_films(project, m)) >= 2), None)


def suggest_titles_menu(project: DiscProject) -> bool:
    """Filmauswahl vorschlagen: ab 3 Filmen, mit Hauptmenü, noch keine Filmauswahl, nicht abgelehnt."""
    return (len(project.films) >= MIN_FILMS_FOR_TITLES and project.main_menu is not None
            and titles_menu(project) is None and HINT_TITLES_MENU not in project.settings.dismissed_hints)


def film_chapter_menu(project: DiscProject, film_id: str) -> Optional[MenuNode]:
    """Erste Kapitelseite des Films, None ohne Kapitelmenü."""
    pages = chapter_menus(project, film_id)
    return pages[0] if pages else None


def film_language_menu(project: DiscProject, film_id: str) -> Optional[MenuNode]:
    """Erstes Menü mit Ton- oder Untertitel-Buttons des Films, None ohne Sprachmenü."""
    return next((m for m in project.menus
                 if any(b.kind in LANGUAGE_BUTTON_KINDS and b.film_id == film_id for b in m.buttons)), None)


def suggest_language_mode(film: FilmNode) -> Optional[str]:
    """
    Vorschlag für ein Sprachmenü: zusammen bis je 4 Spuren, sonst getrennt; nur Untertitel, wenn es
    nur eine Tonspur gibt; nur Ton ohne Untertitel. None, wenn es nichts zu wählen gibt.
    """
    audio, subs = len(film.audio_tracks), len(film.subtitle_tracks)
    if subs and audio >= 2:
        return LANG_COMBINED if audio <= MAX_TRACKS_COMBINED and subs <= MAX_TRACKS_COMBINED else LANG_SEPARATE
    if subs:
        return LANG_SUBTITLES
    if audio >= 2:
        return LANG_AUDIO
    return None


def language_modes(film: FilmNode) -> List[str]:
    """Arten des Sprachmenüs, die mit den Spuren des Films sinnvoll sind (Vorschlag zuerst)."""
    audio, subs = len(film.audio_tracks) >= 2, bool(film.subtitle_tracks)
    if audio and subs:
        modes = [LANG_COMBINED, LANG_SEPARATE, LANG_SUBTITLES, LANG_AUDIO]
    elif subs:
        modes = [LANG_SUBTITLES]
    elif audio:
        modes = [LANG_AUDIO]
    else:
        return []
    first = suggest_language_mode(film)
    return [first] + [m for m in modes if m != first]


def language_link_label(mode: str) -> str:
    """Beschriftung des Buttons, der ins neue Sprachmenü führt."""
    return {LANG_AUDIO: LABEL_AUDIO, LANG_SUBTITLES: LABEL_SUBTITLES}.get(mode, LABEL_LANGUAGE)


def like_source(project: DiscProject, film_id: str, kind: str) -> Optional[FilmNode]:
    """Erster andere Film mit einem Kapitel- bzw. Sprachmenü (Vorlage für „wie bei …“)."""
    lookup = film_chapter_menu if kind == KIND_CHAPTERS else film_language_menu
    return next((f for f in project.films if f.id != film_id and lookup(project, f.id) is not None), None)


# -------------------------------------------------------------------------
# Vorschläge (Konzept 2.1, Regel 2)
# -------------------------------------------------------------------------

def offers_content(film: FilmNode) -> bool:
    """Hat der Film etwas, wofür es ein Kapitel- oder Sprachmenü geben kann?"""
    return len(film.chapters) >= 2 or suggest_language_mode(film) is not None


def linked_films(project: DiscProject, menu: MenuNode) -> List[FilmNode]:
    """Filme, zu denen Buttons dieses Menüs direkt führen (in Button-Reihenfolge, ohne Doppelte)."""
    films, seen = [], set()
    for button in menu.buttons:
        film = project.film(button.target) if button.kind == BUTTON_NAV else None
        if film is not None and film.id not in seen:
            seen.add(film.id)
            films.append(film)
    return films


def suggestion_film(project: DiscProject, menu: MenuNode) -> Optional[FilmNode]:
    """
    Film, dessen Kapitel- und Sprachmenü dieses Menü vorschlägt: Das Menü zeigt selbst keine Inhalte
    und führt zu genau einem Film mit Kapiteln bzw. Spuren zur Wahl (Einzelfilm, Film + Bonus, Menü
    einer Folge). Menüs, die zu mehreren solchen Filmen führen (Filmauswahl), schlagen nichts vor.
    """
    if any(b.is_content for b in menu.buttons):
        return None
    films = [f for f in linked_films(project, menu) if offers_content(f)]
    return films[0] if len(films) == 1 else None


def suggestions(project: DiscProject, menu: MenuNode) -> List[Suggestion]:
    """Alle Vorschläge eines Menüs: Filmauswahl, Kapitel- und Sprachmenü."""
    result: List[Suggestion] = []
    main = project.main_menu
    if main is not None and menu.id == main.id and suggest_titles_menu(project):
        result.append(Suggestion(ACTION_TITLES_MENU, _L(project, LABEL_FILMS), menu.id))
    film = suggestion_film(project, menu)
    if film is not None:
        if len(film.chapters) >= 2 and ACTION_CHAPTER_MENU not in film.dismissed_hints \
                and film_chapter_menu(project, film.id) is None:
            result.append(Suggestion(ACTION_CHAPTER_MENU, _L(project, LABEL_CHAPTERS), menu.id, film.id,
                                     needs_choice=True))
        mode = suggest_language_mode(film)
        if mode is not None and ACTION_LANGUAGE_MENU not in film.dismissed_hints \
                and film_language_menu(project, film.id) is None:
            choice = len(language_modes(film)) > 1 or like_source(project, film.id, KIND_LANGUAGE) is not None
            result.append(Suggestion(ACTION_LANGUAGE_MENU, _L(project, language_link_label(mode)), menu.id, film.id,
                                     needs_choice=choice))
    return result


def button_offers(project: DiscProject, menu: MenuNode) -> List[Suggestion]:
    """
    Was „＋ Button“ in diesem Menü anbietet (Regel 3): Kapitel- und Sprachmenü für jeden Film, der
    noch keines hat, und eine Filmauswahl ab 2 Filmen. Abgelehnte Vorschläge zählen hier nicht –
    wer über „＋ Button“ geht, fragt ausdrücklich danach.
    """
    offers: List[Suggestion] = []
    if len(project.films) >= 2 and titles_menu(project) is None:
        offers.append(Suggestion(ACTION_TITLES_MENU, _L(project, LABEL_FILMS), menu.id))
    for film in project.films:
        if len(film.chapters) >= 2 and film_chapter_menu(project, film.id) is None:
            offers.append(Suggestion(ACTION_CHAPTER_MENU, _L(project, LABEL_CHAPTERS), menu.id, film.id,
                                     needs_choice=True))
        mode = suggest_language_mode(film)
        if mode is not None and film_language_menu(project, film.id) is None:
            offers.append(Suggestion(ACTION_LANGUAGE_MENU, _L(project, language_link_label(mode)), menu.id, film.id,
                                     needs_choice=True))
    return offers


def _names(names: List[str], limit: int = 3) -> str:
    return ", ".join(names) if len(names) <= limit else ", ".join(names[:limit]) + f" +{len(names) - limit}"


# -------------------------------------------------------------------------
# Kapitel
# -------------------------------------------------------------------------

def create_chapter_menus(project: DiscProject, film_id: str, per_page: int = CHAPTERS_PER_PAGE,
                         link_from_main: Optional[bool] = True, parent_id: Optional[str] = None) -> List[MenuNode]:
    """
    Legt ⌈Kapitel / per_page⌉ Kapitelseiten an (Raster mit 4 Spalten, einmal angeordnet) und verdrahtet sie:
    „ZURÜCK“ (vorige Seite, auf Seite 1 das Ausgangsmenü), „HAUPTMENÜ“ (ab Seite 2) und „WEITER“
    (nächste Seite, nicht auf der letzten). „KAPITEL“ zur ersten Seite entsteht im Ausgangsmenü
    parent_id; ohne parent_id optional im Hauptmenü (link_from_main None: nur, wenn das Hauptmenü
    direkt zum Film führt).
    """
    film = _film_or_error(project, film_id)
    if not film.chapters:
        raise TemplateError(tr("tpl_no_chapters", film=film.name))
    per_page = max(1, per_page)
    chunks = [film.chapters[i:i + per_page] for i in range(0, len(film.chapters), per_page)]
    main = project.main_menu
    parent = project.menu(parent_id)
    home = parent or main

    pages = [_new_chapter_page(film, chunk) for chunk in chunks]
    for i, page in enumerate(pages):
        page.name = _chapter_page_name(i, len(pages), project.settings.app_lang)
        back = pages[i - 1].id if i > 0 else (home.id if home else None)
        page.buttons.append(_nav(_L(project, LABEL_BACK), back))
        if i > 0 and main is not None:
            page.buttons.append(_nav(_L(project, LABEL_MAIN), main.id))
        if i + 1 < len(pages):
            page.buttons.append(_nav(_L(project, LABEL_NEXT), pages[i + 1].id))
        # Raster so breit wie nötig (wenige Kapitel) und auf allen Seiten gleich hoch (Navigation bleibt stehen)
        cols = min(CHAPTER_GRID_COLS, len(film.chapters))
        arrange(page, page.buttons, ARRANGE_GRID, cols=cols, rows=-(-min(per_page, len(film.chapters)) // cols))

    _add_menus_next_to(project, film, pages)
    if parent is not None:
        _link_from(parent, pages[0], _L(project, LABEL_CHAPTERS))
    elif _should_link(project, film_id, link_from_main):
        _link_from_main(project, pages[0], _L(project, LABEL_CHAPTERS))
    return pages


# -------------------------------------------------------------------------
# Ton & Untertitel
# -------------------------------------------------------------------------

def create_language_menus(project: DiscProject, film_id: str, mode: Optional[str] = None,
                          link_from_main: Optional[bool] = True, parent_id: Optional[str] = None) -> List[MenuNode]:
    """
    Legt ein Sprachmenü an (mode None = Vorschlag, siehe suggest_language_mode):
    - combined: „Ton & Untertitel“, Ton links, Untertitel und „UNTERTITEL AUS“ rechts
    - separate: „Ton“ und „Untertitel“, gegenseitig verlinkt
    - audio / subtitles: nur eine der beiden Seiten
    Jede Seite hat „ZURÜCK“ (ins Ausgangsmenü parent_id, sonst Hauptmenü) und „FILM STARTEN“.
    Der Button zum neuen Menü entsteht im Ausgangsmenü, ohne parent_id optional im Hauptmenü.
    """
    film = _film_or_error(project, film_id)
    mode = mode or suggest_language_mode(film)
    if mode is None:
        raise TemplateError(tr("tpl_no_tracks", film=film.name))
    if mode in (LANG_COMBINED, LANG_SEPARATE, LANG_AUDIO) and not film.audio_tracks:
        raise TemplateError(tr("tpl_no_audio", film=film.name))
    if mode in (LANG_SEPARATE, LANG_SUBTITLES) and not film.subtitle_tracks:
        raise TemplateError(tr("tpl_no_subs", film=film.name))
    parent = project.menu(parent_id)
    home = parent or project.main_menu
    back = home.id if home else None

    audio_buttons = [_content(BUTTON_AUDIO, film, t.id) for t in film.audio_tracks]
    sub_buttons = [_content(BUTTON_SUBTITLE, film, t.id) for t in film.subtitle_tracks]
    if film.subtitle_tracks:
        sub_buttons.append(_content(BUTTON_SUBTITLE, film, SUBTITLE_OFF))

    if mode == LANG_COMBINED:
        menu = _new_menu(_L(project, "Ton & Untertitel"), film)
        back_btn, play_btn = _nav(_L(project, LABEL_BACK), back), _nav(_L(project, LABEL_PLAY), film.id)
        menu.buttons = audio_buttons + sub_buttons + [back_btn, play_btn]
        arrange(menu, menu.buttons, ARRANGE_COLUMNS)
        menus, link_label = [menu], LABEL_LANGUAGE
    elif mode == LANG_SEPARATE:
        audio = _new_menu(_L(project, "Ton"), film)
        subs = _new_menu(_L(project, "Untertitel"), film)
        audio.buttons = audio_buttons + [_nav(_L(project, LABEL_BACK), back),
                                         _nav(_L(project, LABEL_SUBTITLES), subs.id),
                                         _nav(_L(project, LABEL_PLAY), film.id)]
        subs.buttons = sub_buttons + [_nav(_L(project, LABEL_BACK), back), _nav(_L(project, LABEL_AUDIO), audio.id),
                                      _nav(_L(project, LABEL_PLAY), film.id)]
        _arrange_list(audio, len(audio_buttons))
        _arrange_list(subs, len(sub_buttons))
        menus, link_label = [audio, subs], LABEL_LANGUAGE
    elif mode == LANG_AUDIO:
        menu = _new_menu(_L(project, "Ton"), film)
        menu.buttons = audio_buttons + [_nav(_L(project, LABEL_BACK), back), _nav(_L(project, LABEL_PLAY), film.id)]
        _arrange_list(menu, len(audio_buttons))
        menus, link_label = [menu], LABEL_AUDIO
    elif mode == LANG_SUBTITLES:
        menu = _new_menu(_L(project, "Untertitel"), film)
        menu.buttons = sub_buttons + [_nav(_L(project, LABEL_BACK), back), _nav(_L(project, LABEL_PLAY), film.id)]
        _arrange_list(menu, len(sub_buttons))
        menus, link_label = [menu], LABEL_SUBTITLES
    else:
        raise TemplateError(tr("tpl_unknown_mode", mode=mode))

    _add_menus_next_to(project, film, menus)
    if parent is not None:
        _link_from(parent, menus[0], _L(project, link_label))
    elif _should_link(project, film_id, link_from_main):
        _link_from_main(project, menus[0], _L(project, link_label))
    return menus


# -------------------------------------------------------------------------
# Mehrere Filme (v1.9.6)
# -------------------------------------------------------------------------

def create_titles_menu(project: DiscProject, film_ids: Optional[List[str]] = None,
                       link_from_main: bool = True, parent_id: Optional[str] = None) -> MenuNode:
    """
    Filmauswahl: ein Button pro Film (Beschriftung = Filmname) und „ZURÜCK“ ins Ausgangsmenü
    (ohne parent_id ins Hauptmenü); „FILME“ im Ausgangsmenü bzw. optional im Hauptmenü.
    Standard: alle Filme in Projektreihenfolge.
    """
    films = [project.film(f) for f in film_ids] if film_ids else list(project.films)
    films = [f for f in films if f is not None]
    if len(films) < 2:
        raise TemplateError("Eine Filmauswahl braucht mindestens zwei Filme.")
    home = project.menu(parent_id) or project.main_menu
    menu = MenuNode(id=new_id("menu"), name="Filmauswahl", button_style=new_menu_style())
    menu.buttons = [_nav(f.name.strip().upper() or _L(project, "FILM"), f.id) for f in films]
    menu.buttons.append(_nav(_L(project, LABEL_BACK), home.id if home else None))
    arrange(menu, menu.buttons, ARRANGE_LIST)
    pos = project.view.node_positions
    mx, my = pos.get(home.id, [320.0, 0.0]) if home else [320.0, 0.0]
    project.menus.append(menu)
    x = mx + NODE_SPACING_X
    pos[menu.id] = [float(x), float(_free_y(project, x, my))]
    if parent_id is not None and home is not None:
        _link_from(home, menu, _L(project, LABEL_FILMS))
    elif link_from_main and home is not None:
        _link_from_main(project, menu, _L(project, LABEL_FILMS))
    return menu


def create_menus_like(project: DiscProject, source_film_id: str, target_film_id: str, kind: str,
                      parent_id: Optional[str] = None) -> List[MenuNode]:
    """
    Kapitel- bzw. Sprachmenü für target wie bei source anlegen: gleiche Seitenaufteilung bzw. Art
    (zusammen/getrennt) aus den Inhalten von target, dazu das Design der Vorlage – Lage und Größe der
    Buttons, Button-Stil, festgelegte Pfeiltasten und Hilfslinien. Verlinkt im Ausgangsmenü parent_id,
    ohne parent_id im Hauptmenü nur, wenn es direkt zum Film führt.
    """
    if kind == KIND_CHAPTERS:
        sources = chapter_menus(project, source_film_id)
        if not sources:
            raise TemplateError(tr("tpl_source_no_chapter_menu"))
        per_page = max(1, len([b for b in sources[0].buttons if b.kind == BUTTON_CHAPTER]))
        created = create_chapter_menus(project, target_film_id, per_page, link_from_main=None, parent_id=parent_id)
        pairs = [(sources[min(i, len(sources) - 1)], page) for i, page in enumerate(created)]
    else:
        sources = [m for m in project.menus
                   if any(b.kind in LANGUAGE_BUTTON_KINDS and b.film_id == source_film_id for b in m.buttons)]
        if not sources:
            raise TemplateError(tr("tpl_source_no_language_menu"))
        families = [_language_family(m) for m in sources]
        if (BUTTON_AUDIO, BUTTON_SUBTITLE) in families:
            mode = LANG_COMBINED
        elif (BUTTON_AUDIO,) in families and (BUTTON_SUBTITLE,) in families:
            mode = LANG_SEPARATE
        elif (BUTTON_AUDIO,) in families:
            mode = LANG_AUDIO
        else:
            mode = LANG_SUBTITLES
        created = create_language_menus(project, target_film_id, mode, link_from_main=None, parent_id=parent_id)
        pairs = [(next((s for s in sources if _language_family(s) == _language_family(m)), sources[0]), m)
                 for m in created]
    for source, target in pairs:
        _copy_design(project, source, target)
    return created


def _copy_design(project: DiscProject, source: MenuNode, target: MenuNode):
    """Button-Stil, Lage und Größe der Buttons, Pfeiltasten und Hilfslinien einer Seite auf eine gleich
    aufgebaute übertragen. Buttons werden über ihre Reihenfolge zugeordnet (Inhalte untereinander,
    Navigation untereinander); Buttons ohne Gegenstück behalten ihre eigene Lage."""
    import copy as _copy
    from core import menu_guides

    target.button_style = _copy.deepcopy(source.button_style)
    id_map = {}
    for is_content in (True, False):
        src = [b for b in source.buttons if b.is_content == is_content]
        dst = [b for b in target.buttons if b.is_content == is_content]
        id_map.update({s.id: d.id for s, d in zip(src, dst)})
    by_id = {b.id: b for b in target.buttons}
    for button in source.buttons:
        twin = by_id.get(id_map.get(button.id))
        if twin is None:
            continue
        twin.position = list(button.position) if button.position is not None else twin.position
        twin.size = list(button.size) if button.size is not None else None
        twin.dpad = {d: id_map[t] for d, t in button.dpad.items() if t in id_map}

    # eigene Linien (v1.16.0) gibt es schon in jedem Menü; die Linien des Menüs selbst werden übernommen
    for g in project.view.guides.get(source.id, []):
        menu_guides.add_guide(project, target.id, g.a, g.b)


# -------------------------------------------------------------------------
# Hilfsfunktionen
# -------------------------------------------------------------------------

def _should_link(project: DiscProject, film_id: str, link_from_main: Optional[bool]) -> bool:
    return main_links_to(project, film_id) if link_from_main is None else bool(link_from_main)


def _film_or_error(project: DiscProject, film_id: str) -> FilmNode:
    film = project.film(film_id)
    if film is None:
        raise TemplateError(tr("tpl_unknown_film"))
    return film


def _chapter_indices(film: FilmNode, menu: MenuNode) -> List[int]:
    indices = [film.chapter_index(b.content_ref) for b in menu.buttons
               if b.kind == BUTTON_CHAPTER and b.film_id == film.id]
    return [i for i in indices if i is not None]


def _chapter_page_name(index: int, count: int, lang: str) -> str:
    if count == 1:
        return disc_label("Kapitel", lang)
    return disc_format("Kapitel {page}/{count}", lang, page=index + 1, count=count)


def _language_family(menu: MenuNode) -> tuple:
    """(BUTTON_AUDIO,), (BUTTON_SUBTITLE,) oder beide: welche Spurarten das Menü zeigt."""
    kinds = {b.kind for b in menu.buttons}
    return tuple(k for k in (BUTTON_AUDIO, BUTTON_SUBTITLE) if k in kinds)


def _L(project: DiscProject, label: str) -> str:
    """Beschriftung in der Sprache der Disc (v1.27.0, core/disc_labels.py)."""
    return disc_label(label, project.settings.app_lang)


def _nav(label: str, target: Optional[str]) -> MenuButton:
    return MenuButton(id=new_id("btn"), kind=BUTTON_NAV, label=label, target=target)


def _content(kind: str, film: FilmNode, ref: str) -> MenuButton:
    return MenuButton(id=new_id("btn"), kind=kind, film_id=film.id, content_ref=ref)


def _new_menu(name: str, film: FilmNode) -> MenuNode:
    return MenuNode(id=new_id("menu"), name=name, default_film_id=film.id, button_style=new_menu_style())


def _new_chapter_page(film: FilmNode, chapters: List[Chapter]) -> MenuNode:
    page = _new_menu("Kapitel", film)       # Name setzt danach _chapter_page_name
    page.buttons = [_content(BUTTON_CHAPTER, film, ch.id) for ch in chapters]
    return page


def _arrange_list(menu: MenuNode, count: int):
    """Ton- oder Untertitelliste: bis 4 Buttons untereinander, darüber in zwei Spalten; Navigation darunter."""
    cols = 1 if count <= MAX_TRACKS_COMBINED else 2
    arrange(menu, menu.buttons, ARRANGE_GRID, cols=cols, rows=max(1, -(-count // cols)))


def _link_from_main(project: DiscProject, first_page: MenuNode, label: str):
    main = project.main_menu
    if main is not None:
        _link_from(main, first_page, label)


def _link_from(parent: MenuNode, first_page: MenuNode, label: str):
    """Button im Ausgangsmenü zum neuen Menü; er entsteht mit dem Menü und geht beim Löschen mit ihm."""
    if parent.id == first_page.id:
        return
    if any(b.kind == BUTTON_NAV and b.target == first_page.id for b in parent.buttons):
        return
    button = _nav(label, first_page.id)
    button.created_with = first_page.id
    place_new(parent, button)
    parent.buttons.append(button)


def _add_menus_next_to(project: DiscProject, film: FilmNode, menus: List[MenuNode],
                       below: Optional[MenuNode] = None):
    """Hängt die Menüs an und platziert sie rechts neben dem Film (bzw. unter below) auf freien Plätzen."""
    pos = project.view.node_positions
    if below is not None and below.id in pos:
        x, y = pos[below.id][0], pos[below.id][1] + NODE_SPACING_Y
    else:
        fx, fy = pos.get(film.id, [720.0, 0.0])
        x, y = fx + NODE_SPACING_X, fy
    for menu in menus:
        project.menus.append(menu)
        y = _free_y(project, x, y)
        pos[menu.id] = [float(x), float(y)]
        y += NODE_SPACING_Y


def _free_y(project: DiscProject, x: float, y: float) -> float:
    """Nächste Höhe ab y, an der in dieser Spalte kein anderer Knoten liegt."""
    taken = [p for p in project.view.node_positions.values() if abs(p[0] - x) < NODE_SPACING_X * 0.6]
    while any(abs(p[1] - y) < NODE_SPACING_Y * 0.75 for p in taken):
        y += NODE_SPACING_Y
    return y
