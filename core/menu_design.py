# core/menu_design.py
"""
Gestalten von Menüseiten im Viewer (v1.9.3, ab v1.12 mit freien Buttons), Qt-frei.

- Jeder Button hat eine feste Position (MenuButton.position, obere linke Ecke im 1920×1080 Raum) und
  optional eine eigene Größe (MenuButton.size, sonst aus dem Button-Stil, core.menu_layout).
- Die Pfeiltasten folgen der Lage der Buttons; einzelne Richtungen lassen sich pro Button festlegen.
"""

from typing import Dict, Optional, Tuple

from core.disc_model import DiscProject, MenuNode, DPAD_DIRECTIONS, STYLE_TEXT, TEXT_MIN_HEIGHT
from core import menu_layout

CANVAS_W, CANVAS_H = menu_layout.CANVAS_W, menu_layout.CANVAS_H
STYLE_STATES = ("normal", "selected", "activated")


def resize_items(project: DiscProject, menu_id: str, sizes: Dict[str, Tuple[int, int]],
                 positions: Optional[Dict[str, Tuple[int, int]]] = None):
    """
    Eigene Größe einzelner Buttons (button_id → (w, h), mindestens 8 px, Text-Buttons mindestens
    TEXT_MIN_HEIGHT hoch). Mit positions (Ziehgriffe im Viewer) bekommen die Buttons zugleich ihre neue obere
    linke Ecke; sonst bleibt ihre Mitte.
    """
    from modules.button_shapes import clamp_size
    menu = project.menu(menu_id)
    if menu is None:
        return
    before = menu_layout.boxes(menu)
    min_h = TEXT_MIN_HEIGHT if menu.button_style.kind == STYLE_TEXT else 0
    for button_id, (w, h) in sizes.items():
        button = menu.button(button_id)
        if button is not None:
            button.size = list(clamp_size(min(int(w), CANVAS_W), max(min_h, min(int(h), CANVAS_H))))
    if positions:
        move_items(project, menu_id, positions=positions)
    else:
        menu_layout.keep_centers(menu, before, set(sizes))


def clear_sizes(project: DiscProject, menu_id: str, button_ids):
    """Eigene Größe verwerfen (Größe aus dem Button-Stil); die Buttons behalten ihre Mitte."""
    menu = project.menu(menu_id)
    if menu is None:
        return
    before = menu_layout.boxes(menu)
    ids = {b.id for b in menu.buttons if b.id in set(button_ids) and b.size is not None}
    for button_id in ids:
        menu.button(button_id).size = None
    menu_layout.keep_centers(menu, before, ids)


ALIGN_MODES = ("left", "hcenter", "right", "top", "vcenter", "bottom")


def align_items(project: DiscProject, menu_id: str, button_ids, how: str):
    """Mehrere Buttons an der gemeinsamen Kante bzw. Mitte ihres umgebenden Rechtecks ausrichten."""
    menu = project.menu(menu_id)
    if menu is None or how not in ALIGN_MODES:
        return
    boxes = {bid: box for bid, box in menu_layout.boxes(menu).items() if bid in set(button_ids)}
    if len(boxes) < 2:
        return
    left = min(x for x, _y, _w, _h in boxes.values())
    top = min(y for _x, y, _w, _h in boxes.values())
    right = max(x + w for x, _y, w, _h in boxes.values())
    bottom = max(y + h for _x, y, _w, h in boxes.values())
    positions = {}
    for bid, (x, y, w, h) in boxes.items():
        positions[bid] = {
            "left": (left, y), "hcenter": ((left + right - w) // 2, y), "right": (right - w, y),
            "top": (x, top), "vcenter": (x, (top + bottom - h) // 2), "bottom": (x, bottom - h),
        }[how]
    move_items(project, menu_id, positions)


def match_size(project: DiscProject, menu_id: str, button_ids, reference_id: str, width: bool = True,
               height: bool = True):
    """Breite und/oder Höhe mehrerer Buttons an einen Referenz-Button angleichen; jeder behält seine Mitte."""
    menu = project.menu(menu_id)
    reference = menu.button(reference_id) if menu else None
    if reference is None:
        return
    rw, rh = menu_layout.button_size(menu, reference)
    sizes = {}
    for button in menu.buttons:
        if button.id in set(button_ids) and button.id != reference_id:
            w, h = menu_layout.button_size(menu, button)
            sizes[button.id] = (rw if width else w, rh if height else h)
    if sizes:
        resize_items(project, menu_id, sizes)


def style_changes(style, fields: dict) -> dict:
    """
    Felder, die set_style wirklich setzt. Wer für einen unsichtbaren Zustand (Deckkraft 0 %) eine Farbe wählt,
    will sie sehen (v1.14.6): die Deckkraft geht dann mit auf 100 % – auch bei derselben Farbe noch einmal.
    """
    fields = dict(fields)
    for state in STYLE_STATES:
        if f"color_{state}" in fields and f"opacity_{state}" not in fields \
                and getattr(style, f"opacity_{state}") == 0:
            fields[f"opacity_{state}"] = 100
    return fields


def set_style(project: DiscProject, menu_id: str, **fields):
    """
    Button-Stil ändern (Felder von ButtonStyle). Jeder Button behält seine Mitte, auch wenn sich seine Größe
    ändert (Form-Größe, Wechsel Text ↔ Kreis/Dreieck). Ein Wechsel der Art verwirft eigene Größen: sie passen
    nur zum alten Stil (Text 380 × 70, Linie 300 × 8).
    Ausnahme Text ↔ Linie (v1.14.5): die Linie liegt wie eine Unterstreichung an der Unterkante des
    Text-Buttons. Eigene Breiten bleiben (nur die Höhe kommt aus dem neuen Stil), waagrechte Mitte und
    Unterkante bleiben; hin und zurück ergibt wieder die alte Lage.
    """
    menu = project.menu(menu_id)
    if menu is None:
        return
    before = menu_layout.boxes(menu)
    restyle = "kind" in fields and fields["kind"] != menu.button_style.kind
    was_line = menu_layout.is_line_style(menu.button_style)
    fields = style_changes(menu.button_style, fields)
    for k, v in fields.items():
        setattr(menu.button_style, k, v)
    underline = restyle and (was_line or menu_layout.is_line_style(menu.button_style))
    if restyle:
        height = menu_layout.default_size(menu)[1]
        for b in menu.buttons:
            b.size = [b.size[0], height] if underline and b.size is not None else None
    if underline:
        menu_layout.keep_bottoms(menu, before)
    else:
        menu_layout.keep_centers(menu, before)


def move_items(project: DiscProject, menu_id: str, positions: Optional[Dict[str, Tuple[int, int]]] = None):
    """Setzt die Positionen einzelner Buttons (button_id → (x, y), obere linke Ecke im 1920×1080 Raum)."""
    menu = project.menu(menu_id)
    if menu is None:
        return
    for button_id, (x, y) in (positions or {}).items():
        button = menu.button(button_id)
        if button is not None:
            button.position = [int(x), int(y)]


def set_dpad(project: DiscProject, menu_id: str, button_id: str, direction: str, target_id: Optional[str]):
    """Pfeiltaste eines Buttons überschreiben (target_id) oder wieder automatisch machen (None)."""
    menu = project.menu(menu_id)
    button = menu.button(button_id) if menu else None
    if button is None or direction not in DPAD_DIRECTIONS:
        return
    if target_id is None:
        button.dpad.pop(direction, None)
    elif menu.button(target_id) is not None:
        button.dpad[direction] = target_id


def dpad_targets(project: DiscProject, menu: MenuNode) -> Dict[str, Dict[str, str]]:
    """Wirksame Pfeiltasten-Ziele wie auf der Disc: {Button-ID: {Richtung: Ziel-Button-ID}}."""
    from core.disc_adapter import preview_menu_specs
    specs = preview_menu_specs(project, menu)
    by_number = {n: b.id for n, b in enumerate(menu.buttons, start=1)}
    return {b.id: {d: by_number.get(getattr(s, attr)) for d, attr in DPAD_DIRECTIONS.items()}
            for b, s in zip(menu.buttons, specs)}


def start_button_id(menu: MenuNode) -> Optional[str]:
    """
    Button, der beim Öffnen des Menüs ausgewählt ist: der Standard-Button, sonst automatisch (v1.14.6) der erste
    Inhalts-Button in Lesereihenfolge (Kapitel 1 statt des zuerst angelegten ZURÜCK), ohne Inhalts-Buttons der
    erste oben links. Bis v1.14.5 war es der erste Button der Liste.
    """
    if menu.default_button_id and menu.button(menu.default_button_id) is not None:
        return menu.default_button_id
    return auto_start_button_id(menu)


def auto_start_button_id(menu: MenuNode) -> Optional[str]:
    """Automatischer Start-Button (ohne festgelegten Standard-Button), siehe start_button_id."""
    if not menu.buttons:
        return None
    from core.menu_tools import reading_order
    content = [b for b in menu.buttons if b.is_content]
    return reading_order(menu, content or menu.buttons)[0].id


def reachable_buttons(project: DiscProject, menu: MenuNode) -> set:
    """Buttons, die vom Start-Button aus mit den Pfeiltasten erreichbar sind (wie im Preflight)."""
    targets = dpad_targets(project, menu)
    start = start_button_id(menu)
    seen, todo = set(), [start] if start else []
    while todo:
        button_id = todo.pop()
        if button_id in seen or button_id not in targets:
            continue
        seen.add(button_id)
        todo.extend(t for t in targets[button_id].values() if t)
    return seen


def auto_dpad_target(project: DiscProject, menu: MenuNode, button_id: str, direction: str) -> Optional[str]:
    """Ziel, das die Pfeiltaste ohne Überschreiben hätte (für „Automatisch (→ …)“ im Inspektor)."""
    import copy
    trial = copy.deepcopy(project)
    trial_menu = trial.menu(menu.id)
    trial_menu.button(button_id).dpad.pop(direction, None)
    return dpad_targets(trial, trial_menu).get(button_id, {}).get(direction)
