# core/disc_rules.py
"""
Regeln des Node-Systems (Stufe 1):
- Welche Verbindungen sind erlaubt? (Der Editor lässt nur Verbindungen zu, die die bestehende
  HDMV-Pipeline korrekt abbilden kann; Stufe-2-Verbindungen sind sichtbar, aber gesperrt.)
- Automatische Beschriftung von Inhalts-Buttons.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple

from core.disc_model import (
    DiscProject, MenuNode, MenuButton, FilmNode,
    BUTTON_NAV, BUTTON_CHAPTER, BUTTON_AUDIO, BUTTON_SUBTITLE, SUBTITLE_OFF,
)
from core.disc_labels import disc_label, disc_format
from core.translations import tr

CURRENT_STAGE = 1

# Verbindungsquellen
SOURCE_START = "start"
SOURCE_FILM_END = "film_end"
SOURCE_BUTTON = "button"
SOURCE_NEW_BUTTON = "new_button"   # „＋ Button“ eines Menüs: Verbinden legt den Button erst an


@dataclass(frozen=True)
class Source:
    kind: str
    node_id: Optional[str] = None
    button_id: Optional[str] = None

    @staticmethod
    def start() -> "Source":
        return Source(SOURCE_START)

    @staticmethod
    def film_end(film_id: str) -> "Source":
        return Source(SOURCE_FILM_END, film_id)

    @staticmethod
    def button(menu_id: str, button_id: str) -> "Source":
        return Source(SOURCE_BUTTON, menu_id, button_id)

    @staticmethod
    def new_button(menu_id: str) -> "Source":
        return Source(SOURCE_NEW_BUTTON, menu_id)


@dataclass(frozen=True)
class ConnectionCheck:
    allowed: bool
    reason: str = ""
    required_stage: int = CURRENT_STAGE   # > CURRENT_STAGE: gesperrt, kommt in einer späteren Stufe

    @property
    def locked_for_later_stage(self) -> bool:
        return not self.allowed and self.required_stage > CURRENT_STAGE


def check_connection(project: DiscProject, source: Source, target_id: Optional[str]) -> ConnectionCheck:
    """Prüft, ob source mit dem Knoten target_id verbunden werden darf (None = Verbindung lösen)."""
    if source.kind == SOURCE_START:
        if target_id is None:
            return ConnectionCheck(True)
        if project.menu(target_id):
            return ConnectionCheck(True)
        if project.film(target_id):
            return ConnectionCheck(True)       # v1.18.1: z. B. Trailer vor dem Menü (start_chain_problems)
        return ConnectionCheck(False, tr("rule_unknown_target"))

    if source.kind == SOURCE_FILM_END:
        if not project.film(source.node_id):
            return ConnectionCheck(False, tr("rule_unknown_film"))
        if target_id is None:
            return ConnectionCheck(True, tr("rule_end_to_main"))
        main = project.main_menu
        if main is not None and target_id == main.id:
            return ConnectionCheck(True)
        if project.node(target_id) is None:
            return ConnectionCheck(False, tr("rule_unknown_target"))
        return ConnectionCheck(True)       # v1.18: beliebiges Menü, v1.18.1: Film (z. B. „Alle Folgen“)

    if source.kind == SOURCE_BUTTON:
        menu = project.menu(source.node_id)
        button = menu.button(source.button_id) if menu else None
        if button is None:
            return ConnectionCheck(False, tr("rule_unknown_button"))
        if button.kind != BUTTON_NAV:
            return ConnectionCheck(False, tr("rule_content_no_output"))
        if target_id is None:
            return ConnectionCheck(True)
        return _check_nav_target(project, menu, target_id)

    if source.kind == SOURCE_NEW_BUTTON:
        menu = project.menu(source.node_id)
        if menu is None:
            return ConnectionCheck(False, tr("rule_unknown_menu"))
        if target_id is None:
            return ConnectionCheck(False, tr("rule_new_button_target"))
        return _check_nav_target(project, menu, target_id)

    return ConnectionCheck(False, tr("rule_unknown_source"))


def start_chain_problems(project: DiscProject) -> List[str]:
    """
    Start-Kette (ab v1.18.1): Start → Film → … → Menü; das Menü am Ende ist das Hauptmenü. Führt sie in kein Menü,
    ist es eine Disc ohne Menü – die spielt nur den ersten Film, ohne Film danach.
    """
    if project.main_menu is not None:
        return []
    film = project.film(project.start_target)
    if film is None:
        return []
    chain, seen = [film], {film.id}
    while project.film(chain[-1].end_target) is not None:
        nxt = project.film(chain[-1].end_target)
        if nxt.id in seen:
            return [tr("rule_film_loop", films=" → ".join(f.name for f in chain + [nxt]))]
        chain.append(nxt)
        seen.add(nxt.id)
    if len(chain) == 1 and project.films and film.id == project.films[0].id:
        return []                          # Disc ohne Menü: startet direkt den ersten Film
    return [tr("rule_no_menu_after", name=chain[-1].name)]


def film_cycles(project: DiscProject) -> List[List[FilmNode]]:
    """Filme, deren Enden im Kreis aufeinander zeigen (A → B → A, auch A → A); jeder Kreis einmal."""
    cycles, done = [], set()
    for film in project.films:
        path, pos = [], {}
        node = film
        while node is not None and node.id not in done and node.id not in pos:
            pos[node.id] = len(path)
            path.append(node)
            node = project.film(node.end_target)
        if node is not None and node.id in pos:
            cycles.append(path[pos[node.id]:])
        done.update(f.id for f in path)
    return cycles


def _check_nav_target(project: DiscProject, menu: MenuNode, target_id: str) -> ConnectionCheck:
    """Ziel-Regeln für Navigations-Buttons (bestehende und neu anzulegende)."""
    if target_id == menu.id:
        return ConnectionCheck(False, tr("rule_own_menu"))
    if project.film(target_id) or project.menu(target_id):
        return ConnectionCheck(True)
    return ConnectionCheck(False, tr("rule_unknown_target"))


def connect(project: DiscProject, source: Source, target_id: Optional[str]) -> ConnectionCheck:
    """Setzt die Verbindung, falls erlaubt. Gibt das Prüfergebnis zurück."""
    check = check_connection(project, source, target_id)
    if not check.allowed:
        return check
    if source.kind == SOURCE_START:
        project.start_target = target_id
    elif source.kind == SOURCE_FILM_END:
        project.film(source.node_id).end_target = target_id
    elif source.kind == SOURCE_BUTTON:
        project.menu(source.node_id).button(source.button_id).target = target_id
    return check


def connection_target(project: DiscProject, source: Source) -> Optional[str]:
    if source.kind == SOURCE_START:
        return project.start_target
    if source.kind == SOURCE_FILM_END:
        film = project.film(source.node_id)
        return film.end_target if film else None
    if source.kind == SOURCE_BUTTON:
        menu = project.menu(source.node_id)
        button = menu.button(source.button_id) if menu else None
        return button.target if button else None
    return None


# -------------------------------------------------------------------------
# Beschriftungen
# -------------------------------------------------------------------------

def language_display_name(lang_code: str, lang: Optional[str] = None) -> str:
    """ISO 639-2 Code → Anzeigename in Großbuchstaben (z. B. 'deu' → 'DEUTSCH', 'jpn' → 'JAPANISCH').
    lang: Sprache des Namens, ohne Angabe die der Oberfläche (v1.27.0)."""
    from core.constants import language_menu_name
    from core.translations import ui_language
    return language_menu_name(lang_code, lang or ui_language())


def target_options(film: Optional[FilmNode], kind: str) -> list:
    """
    Mögliche Ziele eines Inhalts-Buttons im Film als [(content_ref, Anzeige)]: Kapitel („3 · PROLOG“),
    Tonspuren („2 · ENGLISCH“), Untertitel mit „Aus“ zuerst. Leer ohne Film.
    """
    if film is None:
        return []
    if kind == BUTTON_CHAPTER:
        return [(ch.id, f"{i + 1} · {ch.name}" if ch.name else f"{i + 1} · {ch.time[:8]}")
                for i, ch in enumerate(film.chapters)]
    if kind == BUTTON_AUDIO:
        return [(t.id, f"{i + 1} · {language_display_name(t.lang)}") for i, t in enumerate(film.audio_tracks)]
    if kind == BUTTON_SUBTITLE:
        return [(SUBTITLE_OFF, tr("target_subtitle_off"))] + [(t.id, f"{i + 1} · {language_display_name(t.lang)}")
                                          for i, t in enumerate(film.subtitle_tracks)]
    return []


def target_marker(project: DiscProject, menu: MenuNode, button: MenuButton) -> str:
    """Kurzes Ziel für Plaketten und Listen: K12, A2, U1, U–, bei Navigation „→ Name“; „?“ ohne Ziel."""
    if button.kind == BUTTON_NAV:
        node = project.node(button.target)
        return f"→ {node.name}" if node else "→ ?"
    if is_subtitle_off(button):
        return "U–"
    film, idx = resolve_content(project, menu, button)
    letter = {BUTTON_CHAPTER: "K", BUTTON_AUDIO: "A", BUTTON_SUBTITLE: "U"}.get(button.kind, "?")
    return f"{letter}{idx + 1}" if film is not None and idx is not None else f"{letter}?"


def starts_3d_film(project: DiscProject, button: MenuButton) -> bool:
    """Navigations-Button, der direkt einen 3D-Film startet – nur dort gibt es die Wahl 3D/2D (v1.20)."""
    film = project.film(button.target) if button.kind == BUTTON_NAV else None
    return film is not None and bool(film.video_mvc)


def is_subtitle_off(button: MenuButton) -> bool:
    return button.kind == BUTTON_SUBTITLE and button.content_ref == SUBTITLE_OFF


def has_target(project: DiscProject, menu: MenuNode, button: MenuButton) -> bool:
    """Hat der Inhalts-Button ein gültiges Ziel (Film und Kapitel bzw. Spur oder „Aus“)?"""
    film, idx = resolve_content(project, menu, button)
    return film is not None and (idx is not None or is_subtitle_off(button))


def resolve_content(project: DiscProject, menu: MenuNode, button: MenuButton) -> Tuple[Optional[FilmNode], Optional[int]]:
    """Gibt (Film des Buttons, 0-basierter Index des referenzierten Kapitels / der Spur) zurück."""
    film = project.film(button.film_id)
    if film is None or is_subtitle_off(button):
        return film, None
    if button.kind == BUTTON_CHAPTER:
        return film, film.chapter_index(button.content_ref)
    if button.kind == BUTTON_AUDIO:
        return film, film.audio_index(button.content_ref)
    if button.kind == BUTTON_SUBTITLE:
        return film, film.subtitle_index(button.content_ref)
    return film, None


def auto_label(project: DiscProject, menu: MenuNode, button: MenuButton) -> str:
    """Automatische Beschriftung eines Inhalts-Buttons aus den Daten des Quell-Films, in der Sprache der Disc."""
    lang = project.settings.app_lang
    if is_subtitle_off(button):
        return disc_label("UNTERTITEL AUS", lang)
    film, idx = resolve_content(project, menu, button)
    if film is None or idx is None:
        return "?"
    if button.kind == BUTTON_CHAPTER:
        chapter = film.chapters[idx]
        return chapter.name or disc_format("KAPITEL {n}", lang, n=idx + 1)
    if button.kind == BUTTON_AUDIO:
        return disc_format("TON: {name}", lang, name=language_display_name(film.audio_tracks[idx].lang, lang))
    if button.kind == BUTTON_SUBTITLE:
        return disc_format("UNTERTITEL: {name}", lang,
                           name=language_display_name(film.subtitle_tracks[idx].lang, lang))
    return "?"


def button_label(project: DiscProject, menu: MenuNode, button: MenuButton) -> str:
    """Sichtbare Beschriftung: manuell gesetztes Label oder automatische Beschriftung."""
    if button.label is not None:
        return button.label
    if button.is_content:
        return auto_label(project, menu, button)
    return ""
