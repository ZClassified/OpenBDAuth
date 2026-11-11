# core/disc_model.py
"""
Node-basiertes Disc-Datenmodell für OpenBDAuth (Stufe 1).

Die Disc besteht aus drei Knotentypen:
- Start: der Moment, in dem die Disc eingelegt wird (genau einer, ein Ausgang)
- FilmNode: ein Titel (Film, Episode, Trailer, Extra) mit Eingang "Start" und Ausgang "Ende"
- MenuNode: eine Menüseite mit einem Ausgang pro Navigations-Button

Alle Verweise laufen über stabile IDs. Laufende Nummern (Titel-, Seiten-, Button-, Spurnummern)
entstehen erst im Export-Adapter (core/disc_adapter.py).

Ab v1.12 (Schema 2) sind Buttons frei: Jeder Button hat seine eigene Position, eine Art und ein Ziel
(Navigation: Knoten; Inhalt: Film + Kapitel bzw. Spur). Es gibt keine Layout-Regeln und keine Bindung
an Vorlagen mehr; Vorlagen legen nur einmalig Buttons an (core/menu_templates.py).
Das Modell ist bewusst Qt-frei und damit ohne Oberfläche testbar.
"""

import json
import uuid
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Union

from core.translations import tr

SCHEMA_VERSION = 2
FORMAT_ID = "bdauthmax-disc-graph"   # interne Kennung, bleibt (Projekte aus der Zeit als BDauthMax öffnen weiter)

START_NODE_ID = "start"

# Button-Arten
BUTTON_NAV = "nav"                    # Navigations-Button mit Ausgang (Draht)
BUTTON_CHAPTER = "chapter"            # Inhalts-Button: Kapitel des Quell-Films abspielen
BUTTON_AUDIO = "audio"                # Inhalts-Button: Tonspur wählen
BUTTON_SUBTITLE = "subtitle"          # Inhalts-Button: Untertitel wählen bzw. ausschalten (SUBTITLE_OFF)
CONTENT_BUTTON_KINDS = (BUTTON_CHAPTER, BUTTON_AUDIO, BUTTON_SUBTITLE)
SUBTITLE_OFF = "off"                  # content_ref eines Untertitel-Buttons, der die Untertitel ausschaltet

# Pfeiltasten: automatisch nach der Lage der Buttons; Richtungen und die zugehörigen Felder von
# MenuButtonSpec (Überschreiben pro Button, v1.9.5)
DPAD_DIRECTIONS = {"up": "upper_id", "down": "lower_id", "left": "left_id", "right": "right_id"}

# Button-Stil eines Menüs (v1.11.0)
STYLE_TEXT = "text"         # Beschriftung im Button (Stil-Generator), wie bisher – Standard
STYLE_SHAPE = "shape"       # nur eine Form (Linie, Kreis, Dreieck); die Beschriftung steht im Hintergrundbild

# Filmfarben meiden Gold (Start-Knoten) und Hellblau (Menüs)
FILM_COLORS = ["#A78BFA", "#34D399", "#F472B6", "#FB923C", "#2DD4BF", "#F87171", "#A3E635", "#E879F9"]


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# -------------------------------------------------------------------------
# Film
# -------------------------------------------------------------------------

@dataclass
class Chapter:
    id: str
    time: str                   # "HH:MM:SS.mmm"
    name: Optional[str] = None  # None = automatische Beschriftung ("KAPITEL n")


@dataclass
class Track:
    id: str
    path: str
    lang: str
    extra: Dict[str, object] = field(default_factory=dict)  # weitere Felder aus Alt-Projekten unverändert mitführen


@dataclass
class FilmNode:
    id: str
    name: str = "Neuer Film"
    color: str = FILM_COLORS[0]
    is_main: bool = False
    video_base: Optional[str] = None
    video_mvc: Optional[str] = None
    fps: float = 23.976
    audio_tracks: List[Track] = field(default_factory=list)
    subtitle_tracks: List[Track] = field(default_factory=list)
    chapters: List[Chapter] = field(default_factory=list)
    end_target: Optional[str] = None      # None = zurück ins Hauptmenü
    video_details: Optional[dict] = None
    compliance_warnings: List[dict] = field(default_factory=list)
    warnings_acknowledged: bool = False
    dismissed_hints: List[str] = field(default_factory=list)

    @property
    def is_3d(self) -> bool:
        return bool(self.video_mvc)

    def chapter_index(self, chapter_id: str) -> Optional[int]:
        for i, ch in enumerate(self.chapters):
            if ch.id == chapter_id:
                return i
        return None

    def audio_index(self, track_id: str) -> Optional[int]:
        return _index_of(self.audio_tracks, track_id)

    def subtitle_index(self, track_id: str) -> Optional[int]:
        return _index_of(self.subtitle_tracks, track_id)


def _index_of(items: list, item_id: str) -> Optional[int]:
    for i, it in enumerate(items):
        if it.id == item_id:
            return i
    return None


# -------------------------------------------------------------------------
# Menü
# -------------------------------------------------------------------------

@dataclass
class Background:
    """Hintergrund eines Menüs. Bild, Video und Musik alle None = wie Hauptmenü (v1.13)."""
    image: Optional[str] = None
    video: Optional[str] = None
    audio: Optional[str] = None
    duration: float = 30.0

    @property
    def is_set(self) -> bool:
        """Eigener Hintergrund (mindestens Bild, Video oder Musik); sonst gilt der des Hauptmenüs."""
        return bool(self.image or self.video or self.audio)


@dataclass
class ButtonStyle:
    """
    Aussehen aller Buttons eines Menüs. Buttons ohne eigene Größe haben bei Formen die Größe
    width × height (bei der Linie ist die Höhe die Strichstärke), bei Text TEXT_BUTTON_SIZE.
    Farben als '#RRGGBB', Deckkraft in Prozent (0 = unsichtbar).
    """
    kind: str = STYLE_TEXT
    shape: str = "line"               # modules.button_shapes.SHAPES
    width: int = 300
    height: int = 8
    color_normal: str = "#FFFFFF"
    opacity_normal: int = 100           # ab v1.14.7 sichtbar (bis v1.14.6: 0 = im Ruhezustand unsichtbar)
    color_selected: str = "#FFD700"
    opacity_selected: int = 100
    color_activated: str = "#FFFFFF"
    opacity_activated: int = 100


TEXT_BUTTON_SIZE = (380, 70)          # Größe von Text-Buttons ohne eigene Größe (wie die Spalte bis v1.11)
TEXT_MIN_HEIGHT = 20                  # kleinste eigene Höhe eines Text-Buttons: Platz für die kleinste Schrift
                                      # (14 px); darunter lässt sich der Button nicht zeichnen


@dataclass
class MenuButton:
    id: str
    kind: str = BUTTON_NAV
    label: Optional[str] = None               # None = automatische Beschriftung (nur Inhalts-Buttons)
    target: Optional[str] = None              # Ziel-Knoten (nur Navigations-Buttons)
    film_id: Optional[str] = None             # Film des Inhalts (nur Inhalts-Buttons)
    content_ref: Optional[str] = None         # Kapitel-/Spur-ID im Film bzw. SUBTITLE_OFF (nur Inhalts-Buttons)
    position: Optional[List[int]] = None      # [x, y] obere linke Ecke; jede Anlege-Funktion setzt sie (v1.12)
    size: Optional[List[int]] = None          # [w, h]; None = Größe aus dem Button-Stil (v1.11.1)
    dpad: Dict[str, str] = field(default_factory=dict)   # Richtung ("up"|"down"|"left"|"right") → Button-ID; fehlt = automatisch
    created_with: Optional[str] = None        # Menü, das zusammen mit diesem Link-Button entstand (geht beim Löschen mit)
    play_2d: bool = False                     # v1.20: startet einen 3D-Film in 2D (gilt nur, solange das Ziel 3D ist)

    @property
    def is_content(self) -> bool:
        return self.kind in CONTENT_BUTTON_KINDS


@dataclass
class MenuNode:
    id: str
    name: str = "Neues Menü"
    default_film_id: Optional[str] = None     # Standard-Film: neue Inhalts-Buttons übernehmen ihn
    background: Background = field(default_factory=Background)
    buttons: List[MenuButton] = field(default_factory=list)
    default_button_id: Optional[str] = None   # None = erster Button
    button_style: ButtonStyle = field(default_factory=ButtonStyle)

    def button(self, button_id: str) -> Optional[MenuButton]:
        for b in self.buttons:
            if b.id == button_id:
                return b
        return None


# -------------------------------------------------------------------------
# Projekt
# -------------------------------------------------------------------------

@dataclass
class DiscSettings:
    app_lang: str = "de"
    project_name: str = "Untitled_Project"
    output_path: str = ""
    export_format: str = "folder"   # "folder" oder "iso"
    clean_iso_temp: bool = True
    disc_title_meta: bool = True        # Titel im Player (BDMV/META/DL) schreiben; Brenntest bestanden (v1.11.2)
    disc_title: str = ""                # Titel im Player, freier Text; leer = aus dem Disc-Namen
    menu_no_buttons_test: bool = False  # Hardware-Diagnose: Menü ohne Buttons
    menu_resume: bool = True            # Hardware-Diagnose (11.2.5): False = Menü-Objekte ohne resume_intention
    dismissed_hints: List[str] = field(default_factory=list)   # abgelehnte Vorschläge für die ganze Disc (z. B. Filmauswahl)

    def player_title(self) -> str:
        """Titel, den der Player anzeigt: eigener Titel oder der Disc-Name mit Leerzeichen statt „_“."""
        return self.disc_title.strip() or " ".join(self.project_name.replace("_", " ").split()) or "BD DISC"


@dataclass
class NodeGroup:
    """
    Rahmen im Node-Editor (v1.15.0, wie die Underlays in Fusion): farbige Fläche [x, y, w, h] hinter den Knoten.
    Dazu gehört, was darin liegt (core/node_frames.py); node_ids und collapsed sind ältere, ungenutzte Felder.
    """
    id: str
    name: str
    color: str
    node_ids: List[str] = field(default_factory=list)
    collapsed: bool = False
    rect: List[float] = field(default_factory=lambda: [0.0, 0.0, 400.0, 300.0])


@dataclass
class Guide:
    """
    Hilfslinie im Menü-Designer (v1.9.4) zwischen zwei Ankerpunkten am Bildrand.
    Ein Ankerpunkt ist [Kante, Anteil]: Kante "top" | "bottom" | "left" | "right", Anteil 0..1 entlang der Kante.
    """
    id: str
    a: List[Union[str, float]]
    b: List[Union[str, float]]


@dataclass
class FixedGuide:
    """
    Eigene Linie (v1.16.0) in allen Menüs: waagerecht (edge "top"/"bottom") oder senkrecht ("left"/"right"),
    distance Bildpunkte von dieser Kante. Intern eine Hilfslinie von Rand zu Rand mit derselben ID in jedem Menü.
    """
    id: str
    edge: str
    distance: int


@dataclass
class ViewState:
    """Reine Darstellung im Node-Editor; beeinflusst die Disc nicht."""
    node_positions: Dict[str, List[float]] = field(default_factory=dict)
    groups: List[NodeGroup] = field(default_factory=list)
    return_wire_mode: str = "lines"   # "lines" oder "markers"
    guides: Dict[str, List[Guide]] = field(default_factory=dict)                     # Menü-ID → Hilfslinien
    generator: Dict[str, dict] = field(default_factory=dict)   # Menü-ID → letzte Generator-Einstellungen (v1.14.2)
    fixed_guides: List[FixedGuide] = field(default_factory=list)   # eigene Linien in allen Menüs (v1.16.0)


Node = Union[FilmNode, MenuNode]


@dataclass
class DiscProject:
    films: List[FilmNode] = field(default_factory=list)
    menus: List[MenuNode] = field(default_factory=list)
    start_target: Optional[str] = None
    settings: DiscSettings = field(default_factory=DiscSettings)
    view: ViewState = field(default_factory=ViewState)

    # --- Abfragen ---------------------------------------------------------
    def film(self, node_id: Optional[str]) -> Optional[FilmNode]:
        for f in self.films:
            if f.id == node_id:
                return f
        return None

    def menu(self, node_id: Optional[str]) -> Optional[MenuNode]:
        for m in self.menus:
            if m.id == node_id:
                return m
        return None

    def node(self, node_id: Optional[str]) -> Optional[Node]:
        return self.film(node_id) or self.menu(node_id)

    @property
    def main_menu(self) -> Optional[MenuNode]:
        """Das Hauptmenü ist das Menü, auf das der Start-Knoten führt – direkt oder über Filme mit verbundenem Ende
        (ab v1.18.1, z. B. Start → Trailer → Hauptmenü)."""
        node_id, seen = self.start_target, set()
        while node_id not in seen:
            seen.add(node_id)
            film = self.film(node_id)
            if film is None:
                return self.menu(node_id)
            node_id = film.end_target
        return None

    def next_film_color(self) -> str:
        return FILM_COLORS[len(self.films) % len(FILM_COLORS)]

    # --- Serialisierung ---------------------------------------------------
    def to_dict(self) -> dict:
        from core.constants import APP_VERSION
        data = asdict(self)
        data["format"] = FORMAT_ID
        data["schema"] = SCHEMA_VERSION
        data["version"] = APP_VERSION
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "DiscProject":
        schema = data.get("schema")
        if schema != SCHEMA_VERSION:
            raise ProjectFormatError(
                tr("model_old_project", version=data.get("version") or tr("model_before_112")))
        return cls(
            films=[_film_from_dict(f) for f in data.get("films", [])],
            menus=[_menu_from_dict(m) for m in data.get("menus", [])],
            start_target=data.get("start_target"),
            settings=DiscSettings(**data.get("settings", {})),
            view=_view_from_dict(data.get("view", {})),
        )

    def save_to_file(self, filepath: str):
        """Schreibt das Projekt; Mediendateien relativ zum Projektordner, wo möglich (core/media_paths.py, v1.17)."""
        from core.media_paths import project_for_file
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(project_for_file(self, filepath).to_dict(), f, indent=2, ensure_ascii=False)


class ProjectFormatError(ValueError):
    """Die Datei ist kein Projekt im aktuellen Format (frühere Oberfläche oder vor v1.12)."""


def is_disc_graph_data(data: dict) -> bool:
    return data.get("format") == FORMAT_ID


def load_disc_project(filepath: str) -> DiscProject:
    """
    Lädt ein .bdproj im aktuellen Format; ältere Projekte werden mit ProjectFormatError abgelehnt.
    Gespeicherte Pfade werden absolut, auch auf einem anderen Laufwerksbuchstaben gesucht (core/media_paths.py).
    """
    from core.media_paths import resolve_project_paths
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not is_disc_graph_data(data):
        raise ProjectFormatError(tr("model_legacy_project"))
    project = DiscProject.from_dict(data)
    resolve_project_paths(project, filepath)
    return project


def _film_from_dict(d: dict) -> FilmNode:
    d = dict(d)
    d["audio_tracks"] = [Track(**t) for t in d.get("audio_tracks", [])]
    d["subtitle_tracks"] = [Track(**t) for t in d.get("subtitle_tracks", [])]
    d["chapters"] = [Chapter(**c) for c in d.get("chapters", [])]
    return FilmNode(**d)


def _menu_from_dict(d: dict) -> MenuNode:
    d = dict(d)
    d["background"] = Background(**d.get("background", {}))
    d["button_style"] = ButtonStyle(**d.get("button_style", {}))
    d["buttons"] = [MenuButton(**b) for b in d.get("buttons", [])]
    return MenuNode(**d)


def _view_from_dict(d: dict) -> ViewState:
    return ViewState(
        node_positions={k: list(v) for k, v in d.get("node_positions", {}).items()},
        groups=[NodeGroup(**g) for g in d.get("groups", [])],
        return_wire_mode=d.get("return_wire_mode", "lines"),
        guides={m: [Guide(**g) for g in gs] for m, gs in d.get("guides", {}).items()},
        generator={m: dict(g) for m, g in d.get("generator", {}).items()},
        fixed_guides=[FixedGuide(**g) for g in d.get("fixed_guides", [])],
    )
