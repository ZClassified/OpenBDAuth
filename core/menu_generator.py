# core/menu_generator.py
"""
Generator: legt in einem aufgezogenen Bereich eines Menüs Kapitel-, Ton- oder
Untertitel-Buttons im Raster an. Passen nicht alle auf die Seite, entstehen Folgeseiten mit ZURÜCK, HAUPTMENÜ
und WEITER. Danach sind es ganz normale, freie Buttons; Qt-frei.

Grenzen des Menüstroms (MenuLimits):
- Höchstens 50 Buttons pro Seite (MAX_BUTTONS_PER_PAGE, v1.14.3): bewusst enger als das Format (255, die
  Anzahl steht im ICS in einem Byte, modules/igs/segments.py) – mehr ist mit der Fernbedienung nicht
  bedienbar. Ab 40 gibt der Preflight einen Hinweis (MANY_BUTTONS).
- Grafikspeicher: Jeder Button bringt drei Bilder (normal, ausgewählt, aktiviert) mit 1 Byte pro Pixel in den
  Menüstrom seiner Gruppe (modules/igs/compiler.py). GRAPHICS_BUDGET ist eine *Annahme* (16 MiB für den
  Objektpuffer des IG-Decoders), nicht gegen die BD-Spezifikation geprüft; deshalb nur Warnung, kein Fehler.
"""

import copy
import re
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Sequence, Tuple

from core.disc_model import (
    DiscProject, MenuNode, MenuButton, new_id, BUTTON_NAV, BUTTON_CHAPTER, BUTTON_AUDIO, BUTTON_SUBTITLE,
    SUBTITLE_OFF,
)
from core import menu_layout
from core.disc_labels import disc_label, is_label
from core.menu_tools import target_sequence

FORMAT_MAX_BUTTONS = 255                # Format: eine Byte-Zahl im ICS
MAX_BUTTONS_PER_PAGE = 50               # OpenBDAuth: Grenze pro Seite (mehr ist mit Fernbedienung unpraktisch)
MANY_BUTTONS = 40                       # ab hier Hinweis: mit der Fernbedienung mühsam
PAGE_NAV = 3                            # ZURÜCK, HAUPTMENÜ, WEITER auf Folgeseiten
GRAPHICS_BUDGET = 16 * 1024 * 1024      # Annahme, siehe oben
STATES_PER_BUTTON = 3
GENERATOR_KINDS = (BUTTON_CHAPTER, BUTTON_AUDIO, BUTTON_SUBTITLE)
MIN_GAP = (40, 25)                      # Mindestabstände für den Vorschlag (wie die Raster der Vorlagen)
NAV_GAP = 40


@dataclass
class GeneratorSettings:
    area: Tuple[int, int, int, int]     # x, y, w, h im 1920×1080 Raum
    kind: str = BUTTON_CHAPTER
    film_id: Optional[str] = None
    first_ref: Optional[str] = None     # erstes Ziel (Kapitel-/Spur-ID bzw. SUBTITLE_OFF)
    last_ref: Optional[str] = None      # letztes Ziel (einschließlich)
    cols: int = 4
    rows: int = 3
    only_missing: bool = True           # nur Ziele, die noch keinen Button haben (keine Doppel)

    @property
    def capacity(self) -> int:
        return max(1, self.cols) * max(1, self.rows)


def settings_to_dict(settings: GeneratorSettings) -> dict:
    data = asdict(settings)
    data["area"] = list(settings.area)
    return data


def settings_from_dict(data: dict) -> GeneratorSettings:
    data = dict(data)
    data["area"] = tuple(int(v) for v in data.get("area", (0, 0, 1920, 1080)))
    return GeneratorSettings(**data)


# -------------------------------------------------------------------------
# Vorschläge
# -------------------------------------------------------------------------

def suggest_grid(menu: MenuNode, area: Tuple[int, int, int, int]) -> Tuple[int, int]:
    """Spalten und Zeilen, die mit der Button-Größe des Stils und den Mindestabständen in den Bereich passen."""
    bw, bh = menu_layout.default_size(menu)
    _x, _y, w, h = area
    cols = max(1, (w + MIN_GAP[0]) // (bw + MIN_GAP[0]))
    rows = max(1, (h + MIN_GAP[1]) // (bh + MIN_GAP[1]))
    room = MAX_BUTTONS_PER_PAGE - PAGE_NAV         # Folgeseiten brauchen Platz für die Navigation
    cols = min(cols, room)
    rows = max(1, min(rows, room // cols))
    return int(cols), int(rows)


def used_refs(project: DiscProject, kind: str, film_id: Optional[str], menu: Optional[MenuNode] = None) -> set:
    """Ziele dieses Typs, die schon einen Button haben – bei Kapiteln in allen Menüs, bei Spuren im Menü."""
    menus = project.menus if kind == BUTTON_CHAPTER or menu is None else [menu]
    return {b.content_ref for m in menus for b in m.buttons if b.kind == kind and b.film_id == film_id}


def default_settings(project: DiscProject, menu: MenuNode, area: Tuple[int, int, int, int],
                     kind: Optional[str] = None, film_id: Optional[str] = None) -> GeneratorSettings:
    """
    Vorschlag: Kapitel (sonst Ton), Standard-Film, alle Ziele ohne Button (bei Kapiteln in der ganzen Disc,
    bei Spuren in diesem Menü) – gibt es keine, alle; Spalten und Zeilen aus der Größe des Bereichs.
    """
    from core.disc_edit import default_film
    film = project.film(film_id) or default_film(project, menu) or (project.films[0] if project.films else None)
    if kind is None:
        kind = BUTTON_CHAPTER if film is None or film.chapters or not film.audio_tracks else BUTTON_AUDIO
    sequence = target_sequence(film, kind)
    used = used_refs(project, kind, film.id if film else None, menu)
    missing = [r for r in sequence if r not in used] or sequence
    cols, rows = suggest_grid(menu, area)
    if missing:
        # nicht mehr Zeilen als nötig, damit die Buttons den Bereich gleichmäßig füllen
        cols = min(cols, len(missing))
        rows = max(1, min(rows, -(-len(missing) // cols)))
    return GeneratorSettings(area=tuple(int(v) for v in area), kind=kind, film_id=film.id if film else None,
                             first_ref=missing[0] if missing else None, last_ref=missing[-1] if missing else None,
                             cols=cols, rows=rows)


def target_range(project: DiscProject, settings: GeneratorSettings, menu: Optional[MenuNode] = None) -> List[str]:
    """Die Ziele von first_ref bis last_ref in Zählreihenfolge (vertauschte Grenzen werden umgedreht); mit
    only_missing ohne die, die schon einen Button haben."""
    sequence = target_sequence(project.film(settings.film_id), settings.kind)
    if not sequence:
        return []
    a = sequence.index(settings.first_ref) if settings.first_ref in sequence else 0
    b = sequence.index(settings.last_ref) if settings.last_ref in sequence else len(sequence) - 1
    if a > b:
        a, b = b, a
    refs = sequence[a:b + 1]
    if settings.only_missing:
        used = used_refs(project, settings.kind, settings.film_id, menu)
        refs = [r for r in refs if r not in used]
    return refs


# -------------------------------------------------------------------------
# Plan: was entsteht
# -------------------------------------------------------------------------

@dataclass
class GeneratorPlan:
    refs: List[str]
    chunks: List[List[str]]             # chunks[0] auf der Ausgangsseite, die übrigen auf Folgeseiten
    page_names: List[str]               # Namen aller Seiten (Ausgangsseite zuerst), nach dem Anlegen
    graphics_bytes: int                 # Button-Grafik im Menüstrom der Gruppe danach (geschätzt)
    over_page_limit: bool               # mehr als 255 Buttons auf einer Seite

    @property
    def new_pages(self) -> int:
        return max(0, len(self.chunks) - 1)

    @property
    def over_graphics_budget(self) -> bool:
        return self.graphics_bytes > GRAPHICS_BUDGET


_PAGE_SUFFIX = re.compile(r"\s+\d+\s*/\s*\d+$")


def base_name(menu: MenuNode) -> str:
    """Name ohne „ 1/2“."""
    return _PAGE_SUFFIX.sub("", menu.name).strip() or menu.name


def button_graphics_bytes(menu: MenuNode, button: Optional[MenuButton] = None) -> int:
    w, h = menu_layout.button_size(menu, button) if button is not None else menu_layout.default_size(menu)
    return STATES_PER_BUTTON * w * h


def group_graphics_bytes(project: DiscProject, menu: MenuNode) -> int:
    """Button-Grafik im Menüstrom der Gruppe des Menüs (alle Menüs mit demselben wirksamen Hintergrund)."""
    from core.disc_adapter import background_key
    key = background_key(project, menu)
    return sum(button_graphics_bytes(m, b) for m in project.menus if background_key(project, m) == key
               for b in m.buttons)


def plan(project: DiscProject, menu: MenuNode, settings: GeneratorSettings) -> GeneratorPlan:
    refs = target_range(project, settings, menu)
    capacity = settings.capacity
    # Ausgangsseite: nur freie Plätze und nie über die Grenze pro Seite (WEITER kommt dazu, wenn es weitergeht)
    first = min(len(free_cells(menu, settings)), max(0, MAX_BUTTONS_PER_PAGE - len(menu.buttons)))
    from core.menu_templates import LABEL_NEXT
    has_next = any(b.kind == BUTTON_NAV and is_label(b.label, LABEL_NEXT) for b in menu.buttons)
    if len(refs) > first and not has_next:
        first = max(0, min(first, MAX_BUTTONS_PER_PAGE - len(menu.buttons) - 1))
    chunks = [refs[:first]] + [refs[i:i + capacity] for i in range(first, len(refs), capacity)]
    total = len(chunks)
    base = base_name(menu)
    names = [menu.name] if total == 1 else [f"{base} {i}/{total}" for i in range(1, total + 1)]
    extra = len(refs) * button_graphics_bytes(menu) + (total - 1) * PAGE_NAV * button_graphics_bytes(menu)
    over_page = capacity + PAGE_NAV > MAX_BUTTONS_PER_PAGE      # Folgeseiten würden zu voll
    return GeneratorPlan(refs, chunks, names, group_graphics_bytes(project, menu) + extra, over_page)


# -------------------------------------------------------------------------
# Anlegen
# -------------------------------------------------------------------------

def cell_positions(menu: MenuNode, settings: GeneratorSettings) -> List[Tuple[int, int]]:
    """Obere linke Ecken aller Rasterplätze: Mitten auf einem gleichmäßigen Raster im Bereich, Zeile für Zeile."""
    x, y, w, h = settings.area
    cols, rows = max(1, settings.cols), max(1, settings.rows)
    bw, bh = menu_layout.default_size(menu)
    positions = []
    for i in range(cols * rows):
        cx = x + (i % cols + 0.5) * w / cols
        cy = y + (i // cols + 0.5) * h / rows
        positions.append((max(0, min(menu_layout.CANVAS_W - bw, int(round(cx - bw / 2)))),
                          max(0, min(menu_layout.CANVAS_H - bh, int(round(cy - bh / 2))))))
    return positions


def free_cells(menu: MenuNode, settings: GeneratorSettings) -> List[Tuple[int, int]]:
    """Rasterplätze, an denen noch kein Button liegt (ergänzen statt überdecken)."""
    bw, bh = menu_layout.default_size(menu)
    taken = [menu_layout.button_box(menu, b) for b in menu.buttons]

    def free(pos):
        x, y = pos
        return not any(x < tx + tw and tx < x + bw and y < ty + th and ty < y + bh for tx, ty, tw, th in taken)

    return [pos for pos in cell_positions(menu, settings) if free(pos)]


def _content_buttons(cells: Sequence[Tuple[int, int]], settings: GeneratorSettings,
                     refs: Sequence[str]) -> List[MenuButton]:
    return [MenuButton(id=new_id("btn"), kind=settings.kind, film_id=settings.film_id, content_ref=ref,
                       position=list(pos))
            for ref, pos in zip(refs, cells)]


def _nav_place(source: MenuNode, page: MenuNode, settings: GeneratorSettings, label: str, index: int):
    """Lage eines Navigations-Buttons auf einer Folgeseite: wie der gleichnamige auf der Ausgangsseite, sonst
    in einer Reihe unter dem Bereich."""
    twin = next((b for b in source.buttons if b.kind == BUTTON_NAV and is_label(b.label, label)), None)
    if twin is not None and twin.position is not None:
        return list(twin.position), (list(twin.size) if twin.size is not None else None)
    bw, bh = menu_layout.default_size(page)
    x, y, _w, h = settings.area
    nx = max(0, min(menu_layout.CANVAS_W - bw, x + index * (bw + NAV_GAP)))
    ny = max(0, min(menu_layout.SAFE_BOTTOM - bh, y + h + NAV_GAP))
    return [nx, ny], None


def _nav(source: MenuNode, page: MenuNode, settings: GeneratorSettings, label: str, target: Optional[str],
         index: int, lang: str) -> MenuButton:
    """label: deutsche Beschriftung (LABEL_…); auf die Disc kommt sie in der Sprache der Disc (v1.27.0)."""
    position, size = _nav_place(source, page, settings, label, index)
    return MenuButton(id=new_id("btn"), kind=BUTTON_NAV, label=disc_label(label, lang), target=target,
                      position=position, size=size)


def generate(project: DiscProject, menu_id: str, settings: GeneratorSettings) -> List[str]:
    """
    Legt die Buttons an (Ausgangsseite ergänzt, vorhandene Buttons bleiben) und, wenn nötig, Folgeseiten mit
    gleichem Stil, gleichem Bereich und einer Kopie des Hintergrunds. Verdrahtung wie bei der Kapitel-Vorlage:
    ZURÜCK zur vorigen Seite, HAUPTMENÜ, WEITER zur nächsten. Hatte die Ausgangsseite schon ein WEITER zu einer
    anderen Seite, hängen die Folgeseiten dazwischen. Merkt sich die Einstellungen pro Seite (Preflight
    „Ergänzen …“). Gibt die IDs der neuen Seiten zurück.
    """
    from core.menu_templates import LABEL_BACK, LABEL_MAIN, LABEL_NEXT, NODE_SPACING_Y, _free_y

    source = project.menu(menu_id)
    if source is None:
        return []
    result = plan(project, source, settings)
    source.buttons.extend(_content_buttons(free_cells(source, settings), settings, result.chunks[0]))
    _remember(project, source.id, settings)
    if result.new_pages == 0:
        return []

    main = project.main_menu
    lang = project.settings.app_lang
    nxt = next((b for b in source.buttons if b.kind == BUTTON_NAV and is_label(b.label, LABEL_NEXT)), None)
    old_next = nxt.target if nxt is not None else None
    pages: List[MenuNode] = []
    for chunk, name in zip(result.chunks[1:], result.page_names[1:]):
        page = MenuNode(id=new_id("menu"), name=name, default_film_id=source.default_film_id,
                        background=copy.deepcopy(source.background),
                        button_style=copy.deepcopy(source.button_style))
        page.buttons = _content_buttons(cell_positions(page, settings), settings, chunk)
        pages.append(page)
    source.name = result.page_names[0]

    for i, page in enumerate(pages):
        previous = source if i == 0 else pages[i - 1]
        following = pages[i + 1].id if i + 1 < len(pages) else old_next
        page.buttons.append(_nav(source, page, settings, LABEL_BACK, previous.id, 0, lang))
        if main is not None:
            page.buttons.append(_nav(source, page, settings, LABEL_MAIN, main.id, 1, lang))
        if following is not None:
            page.buttons.append(_nav(source, page, settings, LABEL_NEXT, following, 2, lang))
        _remember(project, page.id, settings)

    if nxt is None:
        source.buttons.append(_nav(source, source, settings, LABEL_NEXT, pages[0].id, 2, lang))
    else:
        nxt.target = pages[0].id
    if old_next is not None:
        # die frühere nächste Seite führt jetzt zur letzten neuen zurück
        later = project.menu(old_next)
        for b in later.buttons if later else []:
            if b.kind == BUTTON_NAV and is_label(b.label, LABEL_BACK) and b.target == source.id:
                b.target = pages[-1].id

    positions = project.view.node_positions
    x, y = positions.get(source.id, [720.0, 0.0])
    for page in pages:
        project.menus.append(page)
        y = _free_y(project, x, y + NODE_SPACING_Y)
        positions[page.id] = [float(x), float(y)]
    return [p.id for p in pages]


def _remember(project: DiscProject, menu_id: str, settings: GeneratorSettings):
    project.view.generator[menu_id] = settings_to_dict(settings)


def remembered(project: DiscProject, menu_id: str) -> Optional[GeneratorSettings]:
    data = project.view.generator.get(menu_id)
    return settings_from_dict(data) if data else None


def default_area(menu: MenuNode) -> Tuple[int, int, int, int]:
    """Bereich ohne Aufziehen (Preflight „Ergänzen …“ ohne gemerkten Bereich): um die Inhalts-Buttons, sonst
    die Title-Safe-Fläche ohne den unteren Streifen für die Navigation."""
    boxes = [menu_layout.button_box(menu, b) for b in menu.buttons if b.is_content]
    if boxes:
        left = min(b[0] for b in boxes)
        top = min(b[1] for b in boxes)
        right = max(b[0] + b[2] for b in boxes)
        bottom = max(b[1] + b[3] for b in boxes)
        return left, top, right - left, bottom - top
    return 192, 108, 1536, 700


def preset_for_missing(project: DiscProject, menu: MenuNode, film_id: str, refs: Sequence[str]) -> GeneratorSettings:
    """Einstellungen für „Ergänzen …“: gemerkter Bereich der Seite (sonst default_area), genau diese Kapitel."""
    known = remembered(project, menu.id)
    area = known.area if known else default_area(menu)
    settings = default_settings(project, menu, area, kind=BUTTON_CHAPTER, film_id=film_id)
    if known is not None:
        settings.cols, settings.rows = known.cols, known.rows
    if refs:
        settings.first_ref, settings.last_ref = refs[0], refs[-1]
    return settings
