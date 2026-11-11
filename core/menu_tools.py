# core/menu_tools.py
"""
Werkzeuge gegen Handarbeit im Menü-Designer, Qt-frei.

- Duplizieren (Strg+D): Kopien versetzt anlegen, Ziele weiterzählen (Kapitel 4 → 5).
- Fortlaufend zuweisen: markierte Inhalts-Buttons der Reihe nach mit Zielen ab X belegen.

Alle Werkzeuge legen ganz normale, freie Buttons an bzw. ändern sie; der GraphController ruft sie innerhalb
eines Rückgängig-Schritts auf.
"""

from typing import Dict, List, Optional, Sequence, Tuple

from core.disc_model import (
    DiscProject, MenuNode, MenuButton, FilmNode, new_id,
    BUTTON_NAV, BUTTON_CHAPTER, BUTTON_AUDIO, BUTTON_SUBTITLE, SUBTITLE_OFF, CONTENT_BUTTON_KINDS,
)
from core import menu_layout

DUPLICATE_GAP = 40              # Abstand der ersten Kopie neben dem Original (wie das Raster der Vorlagen)
DUPLICATE_OFFSET = (24, 24)     # erste Kopie, wenn daneben und darunter kein Platz ist: leicht versetzt


# -------------------------------------------------------------------------
# Ziele zählen
# -------------------------------------------------------------------------

def target_sequence(film: Optional[FilmNode], kind: str) -> List[str]:
    """Ziele eines Films in Zählreihenfolge: Kapitel, Tonspuren bzw. Untertitel und danach „Aus“."""
    if film is None:
        return []
    if kind == BUTTON_CHAPTER:
        return [ch.id for ch in film.chapters]
    if kind == BUTTON_AUDIO:
        return [t.id for t in film.audio_tracks]
    if kind == BUTTON_SUBTITLE:
        return [t.id for t in film.subtitle_tracks] + [SUBTITLE_OFF]
    return []


def next_target(project: DiscProject, button: MenuButton, steps: int = 1) -> Optional[str]:
    """Ziel `steps` Schritte weiter (Kapitel 4 → 5); None, wenn es keins gibt oder der Button keins hat."""
    sequence = target_sequence(project.film(button.film_id), button.kind)
    if button.content_ref not in sequence:
        return None
    index = sequence.index(button.content_ref) + steps
    return sequence[index] if 0 <= index < len(sequence) else None


# -------------------------------------------------------------------------
# Lesereihenfolge
# -------------------------------------------------------------------------

def reading_rows(menu: MenuNode, buttons: Sequence[MenuButton]) -> List[List[MenuButton]]:
    """
    Zeilen von oben nach unten, jede links nach rechts. Buttons, deren Oberkanten höchstens eine halbe
    Button-Höhe auseinanderliegen, gelten als eine Zeile (hält schief gezogene Reihen zusammen).
    """
    boxes = {b.id: menu_layout.button_box(menu, b) for b in buttons}
    rows: List[List[MenuButton]] = []
    for button in sorted(buttons, key=lambda b: (boxes[b.id][1], boxes[b.id][0])):
        _x, y, _w, h = boxes[button.id]
        row = rows[-1] if rows else None
        if row is not None:
            top = boxes[row[0].id][1]
            tolerance = max(boxes[row[0].id][3], h) / 2
            if y - top <= tolerance:
                row.append(button)
                continue
        rows.append([button])
    return [sorted(row, key=lambda b: boxes[b.id][0]) for row in rows]


def reading_order(menu: MenuNode, buttons: Sequence[MenuButton]) -> List[MenuButton]:
    """Zeile für Zeile, links nach rechts (reading_rows)."""
    return [b for row in reading_rows(menu, buttons) for b in row]


# -------------------------------------------------------------------------
# Duplizieren (Strg+D)
# -------------------------------------------------------------------------

def duplicate_buttons(project: DiscProject, menu_id: str, button_ids: Sequence[str],
                      offset: Tuple[int, int] = DUPLICATE_OFFSET,
                      new_ids: Optional[Sequence[str]] = None) -> List[str]:
    """
    Kopiert die Buttons (in Button-Reihenfolge) um offset versetzt und gibt die neuen IDs zurück.
    Inhalts-Buttons zählen ihr Ziel um die Anzahl der kopierten Inhalts-Buttons weiter (eine Reihe K1–K4 wird
    K5–K8); gibt es kein Ziel mehr, bleibt die Kopie ohne Ziel. Navigations-Buttons kommen unverbunden mit
    ihrer Beschriftung. Mit kopiert werden Typ, Film und Größe; Pfeiltasten und Heftungen nicht.
    Die Kopien bleiben ganz im Bild.
    """
    menu = project.menu(menu_id)
    if menu is None:
        return []
    chosen = set(button_ids)
    sources = [b for b in menu.buttons if b.id in chosen]
    steps = sum(1 for b in sources if b.is_content)
    created = []
    for i, source in enumerate(sources):
        copy = MenuButton(id=new_ids[i] if new_ids else new_id("btn"), kind=source.kind,
                          size=list(source.size) if source.size is not None else None)
        if source.kind == BUTTON_NAV:
            copy.label = source.label
        else:
            copy.film_id = source.film_id
            copy.content_ref = next_target(project, source, steps)
        x, y, w, h = menu_layout.button_box(menu, source)
        copy.position = [max(0, min(menu_layout.CANVAS_W - w, x + int(offset[0]))),
                         max(0, min(menu_layout.CANVAS_H - h, y + int(offset[1])))]
        menu.buttons.append(copy)
        created.append(copy.id)
    return created


def first_offset(menu: MenuNode, button_ids: Sequence[str]) -> Tuple[int, int]:
    """
    Versatz der ersten Kopie: direkt neben die Auswahl (rechts mit Abstand), passt sie dort nicht ins Bild,
    darunter; sonst leicht versetzt. So sieht man die Kopie und hat oft schon den richtigen Platz.
    """
    chosen = set(button_ids)
    boxes = [menu_layout.button_box(menu, b) for b in menu.buttons if b.id in chosen]
    if not boxes:
        return DUPLICATE_OFFSET
    left = min(x for x, _y, _w, _h in boxes)
    top = min(y for _x, y, _w, _h in boxes)
    right = max(x + w for x, _y, w, _h in boxes)
    bottom = max(y + h for _x, y, _w, h in boxes)
    gap = DUPLICATE_GAP
    if right + gap + (right - left) <= menu_layout.SAFE_RIGHT:
        return right - left + gap, 0
    if bottom + gap + (bottom - top) <= menu_layout.SAFE_BOTTOM:
        return 0, bottom - top + gap
    return DUPLICATE_OFFSET


def repeat_offset(menu: MenuNode, sources: Sequence[str], copies: Sequence[str]) -> Optional[Tuple[int, int]]:
    """Versatz, den man der letzten Kopie gegeben hat (erstes Paar Original/Kopie); None, wenn eins fehlt."""
    for source_id, copy_id in zip(sources, copies):
        source, copy = menu.button(source_id), menu.button(copy_id)
        if source is not None and copy is not None:
            sx, sy, _w, _h = menu_layout.button_box(menu, source)
            cx, cy, _w, _h = menu_layout.button_box(menu, copy)
            return cx - sx, cy - sy
    return None


# -------------------------------------------------------------------------
# Fortlaufend zuweisen
# -------------------------------------------------------------------------

def sequence_plan(project: DiscProject, menu: MenuNode, button_ids: Sequence[str], kind: str,
                  film_id: Optional[str], start_ref: Optional[str]) -> List[Tuple[MenuButton, Optional[str]]]:
    """
    (Button, Ziel) für die Inhalts-Buttons der Auswahl in Lesereihenfolge, Ziele ab start_ref.
    Mehr Buttons als Ziele: der Rest bekommt None. Navigations-Buttons sind nicht dabei.
    """
    chosen = set(button_ids)
    buttons = reading_order(menu, [b for b in menu.buttons if b.id in chosen and b.is_content])
    sequence = target_sequence(project.film(film_id), kind)
    start = sequence.index(start_ref) if start_ref in sequence else 0
    targets = sequence[start:]
    return [(b, targets[i] if i < len(targets) else None) for i, b in enumerate(buttons)]


def assign_sequence(project: DiscProject, menu_id: str, button_ids: Sequence[str], kind: str,
                    film_id: Optional[str], start_ref: Optional[str]) -> Dict[str, Optional[str]]:
    """Belegt die Inhalts-Buttons der Auswahl der Reihe nach (Typ, Film, Ziel, automatische Beschriftung).
    Gibt {Button-ID: Ziel} zurück."""
    menu = project.menu(menu_id)
    if menu is None or kind not in CONTENT_BUTTON_KINDS:
        return {}
    result = {}
    for button, ref in sequence_plan(project, menu, button_ids, kind, film_id, start_ref):
        if button.kind != kind:
            button.created_with = None      # wie beim Typwechsel im Inspektor (disc_edit.set_button_kind)
        button.kind = kind
        button.film_id = film_id
        button.content_ref = ref
        button.label = None
        result[button.id] = ref
    return result


# -------------------------------------------------------------------------
# Als Raster anordnen, verteilen (v1.14.1)
# -------------------------------------------------------------------------

GRID_GAP = (40, 25)             # Abstände ohne Vorbild (wie die Raster der Vorlagen)


def grid_defaults(menu: MenuNode, button_ids: Sequence[str]) -> Tuple[int, int, int]:
    """
    Vorschlag für „Als Raster“: Spalten = Buttons der obersten Zeile, Abstände = die kleinsten vorhandenen
    (zwischen Nachbarn einer Zeile bzw. zwischen Zeilen), sonst GRID_GAP.
    """
    chosen = set(button_ids)
    buttons = [b for b in menu.buttons if b.id in chosen]
    if not buttons:
        return 1, GRID_GAP[0], GRID_GAP[1]
    rows = [[menu_layout.button_box(menu, b) for b in row] for row in reading_rows(menu, buttons)]
    gaps_x = [b[0] - (a[0] + a[2]) for row in rows for a, b in zip(row, row[1:])]
    gaps_y = [min(y for _x, y, _w, _h in lower) - max(y + h for _x, y, _w, h in upper)
              for upper, lower in zip(rows, rows[1:])]
    gap_x = min((g for g in gaps_x if g > 0), default=GRID_GAP[0])
    gap_y = min((g for g in gaps_y if g > 0), default=GRID_GAP[1])
    cols = len(rows[0]) if len(rows) > 1 else len(buttons)
    return max(1, cols), int(gap_x), int(gap_y)


def grid_positions(menu: MenuNode, button_ids: Sequence[str], cols: int, gap_x: int,
                   gap_y: int) -> Dict[str, Tuple[int, int]]:
    """
    Positionen für „Als Raster“: Buttons in Lesereihenfolge, cols Spalten; jede Zelle so groß wie der größte
    Button (kleinere mittig); die obere linke Ecke bleibt, wo die Auswahl beginnt. Ragt das Raster aus dem
    Bild, rückt es als Ganzes hinein.
    """
    chosen = set(button_ids)
    buttons = reading_order(menu, [b for b in menu.buttons if b.id in chosen])
    if not buttons:
        return {}
    cols = max(1, min(int(cols), len(buttons)))
    boxes = {b.id: menu_layout.button_box(menu, b) for b in buttons}
    cell_w = max(w for _x, _y, w, _h in boxes.values())
    cell_h = max(h for _x, _y, _w, h in boxes.values())
    rows = -(-len(buttons) // cols)
    width = cols * cell_w + (cols - 1) * gap_x
    height = rows * cell_h + (rows - 1) * gap_y
    left = min(x for x, _y, _w, _h in boxes.values())
    top = min(y for _x, y, _w, _h in boxes.values())
    left = max(0, min(menu_layout.CANVAS_W - width, left))
    top = max(0, min(menu_layout.CANVAS_H - height, top))
    positions = {}
    for i, button in enumerate(buttons):
        _x, _y, w, h = boxes[button.id]
        cx = left + (i % cols) * (cell_w + gap_x) + (cell_w - w) // 2
        cy = top + (i // cols) * (cell_h + gap_y) + (cell_h - h) // 2
        positions[button.id] = (max(0, min(menu_layout.CANVAS_W - w, cx)),
                                max(0, min(menu_layout.CANVAS_H - h, cy)))
    return positions


def arrange_grid(project: DiscProject, menu_id: str, button_ids: Sequence[str], cols: int, gap_x: int, gap_y: int):
    menu = project.menu(menu_id)
    if menu is None:
        return
    for button_id, (x, y) in grid_positions(menu, button_ids, cols, gap_x, gap_y).items():
        menu.button(button_id).position = [int(x), int(y)]


def distribute_positions(menu: MenuNode, button_ids: Sequence[str], horizontal: bool) -> Dict[str, Tuple[int, int]]:
    """
    Verteilen (ab drei Buttons): der erste und der letzte bleiben stehen, die übrigen bekommen gleiche Abstände
    dazwischen (wie in Grafikprogrammen); die andere Achse bleibt unverändert.
    """
    chosen = set(button_ids)
    boxes = {b.id: menu_layout.button_box(menu, b) for b in menu.buttons if b.id in chosen}
    if len(boxes) < 3:
        return {}
    axis, size = (0, 2) if horizontal else (1, 3)
    order = sorted(boxes, key=lambda bid: (boxes[bid][axis], boxes[bid][1 - axis]))
    first, last = boxes[order[0]], boxes[order[-1]]
    span = last[axis] + last[size] - first[axis]
    gap = (span - sum(boxes[bid][size] for bid in order)) / (len(order) - 1)
    positions = {}
    pos = float(first[axis])
    for bid in order:
        x, y, w, h = boxes[bid]
        value = int(round(pos))
        positions[bid] = (value, y) if horizontal else (x, value)
        pos += boxes[bid][size] + gap
    positions[order[-1]] = (last[0], last[1])      # Rundung: der letzte bleibt genau stehen
    return positions


def distribute(project: DiscProject, menu_id: str, button_ids: Sequence[str], horizontal: bool):
    menu = project.menu(menu_id)
    if menu is None:
        return
    for button_id, (x, y) in distribute_positions(menu, button_ids, horizontal).items():
        menu.button(button_id).position = [int(x), int(y)]
