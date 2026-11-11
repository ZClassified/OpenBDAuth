# core/menu_layout.py
"""
Lage und Größe von Buttons (v1.12), Qt-frei.

Seit v1.12 hat jeder Button eine feste Position (MenuButton.position, obere linke Ecke im 1920×1080 Raum).
Es gibt keine Layout-Regeln mehr, die beim Export gelten. Dieses Modul rechnet die Lage nur einmal aus,
wenn Buttons entstehen:
- arrange(): ganze Vorlagen (Spalte, Raster, zwei Spalten) mit der bewährten MenuLayoutEngine; danach sind
  es ganz normale, freie Buttons.
- place_new(): ein einzelner neuer Button unter dem untersten Button des Menüs (bzw. rechts daneben, wenn
  unten kein Platz mehr ist).
"""

from typing import List, Optional, Sequence, Tuple

from core.disc_model import MenuNode, MenuButton, STYLE_SHAPE, TEXT_BUTTON_SIZE, BUTTON_AUDIO, BUTTON_SUBTITLE

CANVAS_W, CANVAS_H = 1920, 1080
SAFE_BOTTOM = 1026          # Title Safe (90 %)
SAFE_RIGHT = 1824

# Anordnungen der Vorlagen (wie die Layout-Regeln bis v1.11)
ARRANGE_LIST = "list"       # bis 4 Buttons untereinander, darüber Raster mit 2 Spalten
ARRANGE_GRID = "grid"       # Inhalts-Buttons im Raster (cols × rows), Navigation als Zeile darunter
ARRANGE_COLUMNS = "columns"  # Ton links, Untertitel rechts, Navigation darunter

SLOT = TEXT_BUTTON_SIZE     # Platz eines Buttons in allen Anordnungen (Text-Buttons haben genau diese Größe)
COLUMN_SPACING = 24
GRID_SPACING = (40, 25)
MAX_COLUMN_ITEMS = 4


def default_size(menu: MenuNode) -> Tuple[int, int]:
    """Größe eines Buttons ohne eigene Größe: Form-Größe des Button-Stils bzw. Standardgröße für Text."""
    from modules.button_shapes import clamp_size
    style = menu.button_style
    if style.kind == STYLE_SHAPE:
        return clamp_size(style.width, style.height)
    return TEXT_BUTTON_SIZE


def button_size(menu: MenuNode, button: MenuButton) -> Tuple[int, int]:
    from modules.button_shapes import clamp_size
    if button.size is not None:
        return clamp_size(*button.size)
    return default_size(menu)


def button_box(menu: MenuNode, button: MenuButton) -> Tuple[int, int, int, int]:
    """(x, y, w, h) wie auf der Disc; ein Button ohne Position (sollte nicht vorkommen) liegt oben links."""
    w, h = button_size(menu, button)
    x, y = button.position if button.position is not None else (96, 54)
    return int(x), int(y), w, h


def arrange(menu: MenuNode, buttons: Sequence[MenuButton], how: str = ARRANGE_LIST,
            cols: int = 2, rows: int = 0):
    """
    Ordnet die Buttons einmalig an (Vorlagen) und schreibt die Position in die Buttons; eigene Größen werden
    verworfen. Jeder Platz ist so groß wie ein Text-Button; Form-Buttons sitzen mittig in ihrem Platz.
    """
    from modules.igs.layout import MenuButtonSpec, MenuLayoutEngine

    buttons = list(buttons)
    if not buttons:
        return
    specs = [MenuButtonSpec(button_id=n, text="") for n in range(1, len(buttons) + 1)]
    pairs = list(zip(buttons, specs))
    content = [s for b, s in pairs if b.is_content]
    nav = [s for b, s in pairs if not b.is_content]
    if how == ARRANGE_GRID:
        MenuLayoutEngine.layout_fixed_grid(content, nav, cols=cols, btn_w=SLOT[0], btn_h=SLOT[1],
                                           spacing_x=GRID_SPACING[0], spacing_y=GRID_SPACING[1], min_rows=rows)
    elif how == ARRANGE_COLUMNS:
        left = [s for b, s in pairs if b.kind == BUTTON_AUDIO]
        right = [s for b, s in pairs if b.kind == BUTTON_SUBTITLE]
        left += [s for b, s in pairs if b.is_content and b.kind not in (BUTTON_AUDIO, BUTTON_SUBTITLE)]
        MenuLayoutEngine.layout_two_columns(left, right, nav, btn_w=SLOT[0], btn_h=SLOT[1],
                                            spacing_x=GRID_SPACING[0], spacing_y=GRID_SPACING[1])
    elif len(specs) <= MAX_COLUMN_ITEMS:
        MenuLayoutEngine.layout_column(specs, btn_w=SLOT[0], btn_h=SLOT[1], spacing=COLUMN_SPACING)
    else:
        MenuLayoutEngine.layout_grid(specs, cols=2, btn_w=SLOT[0], btn_h=SLOT[1],
                                     spacing_x=GRID_SPACING[0], spacing_y=GRID_SPACING[1])
    w, h = default_size(menu)
    for button, spec in pairs:
        button.size = None
        button.position = [int(spec.x + (spec.width - w) // 2), int(spec.y + (spec.height - h) // 2)]


def place_new(menu: MenuNode, button: MenuButton, others: Optional[List[MenuButton]] = None):
    """
    Platz für einen neuen Button: unter dem untersten Button (gleiche linke Kante und Größe wie dieser);
    reicht der Platz bis zum unteren Title-Safe-Rand nicht, rechts neben den bisherigen Buttons auf Höhe
    des obersten. In einem leeren Menü wie bisher eine Spalte mit einem Button.
    """
    placed = [b for b in (others if others is not None else menu.buttons)
              if b is not button and b.position is not None]
    if not placed:
        arrange(menu, [button])
        return
    boxes = [button_box(menu, b) for b in placed]
    lowest = max(range(len(placed)), key=lambda i: (boxes[i][1] + boxes[i][3], boxes[i][0]))
    ref, (x, y, w, h) = placed[lowest], boxes[lowest]
    if ref.size is not None and button.size is None:
        button.size = list(ref.size)
    bw, bh = button_size(menu, button)
    spacing = COLUMN_SPACING
    ny = y + h + spacing
    if ny + bh <= SAFE_BOTTOM:
        button.position = [int(x), int(ny)]
        return
    right = max(bx + bw_ for bx, _by, bw_, _bh in boxes)
    top = min(by for _bx, by, _bw, _bh in boxes)
    nx = min(right + GRID_SPACING[0], CANVAS_W - bw)
    button.position = [int(nx), int(max(0, min(top, CANVAS_H - bh)))]


def keep_centers(menu: MenuNode, before: dict, button_ids=None):
    """Nach einer Größenänderung (Stil, eigene Größe) bleibt die Mitte jedes Buttons, wo sie war (im Bild gehalten)."""
    for button in menu.buttons:
        if (button_ids is not None and button.id not in button_ids) or button.id not in before:
            continue
        x, y, w, h = before[button.id]
        nw, nh = button_size(menu, button)
        button.position = [max(0, min(CANVAS_W - nw, int(x + (w - nw) // 2))),
                           max(0, min(CANVAS_H - nh, int(y + (h - nh) // 2)))]


def keep_bottoms(menu: MenuNode, before: dict):
    """Wechsel Text ↔ Linie (v1.14.5): waagrechte Mitte und Unterkante jedes Buttons bleiben (Unterstreichung)."""
    for button in menu.buttons:
        if button.id not in before:
            continue
        x, y, w, h = before[button.id]
        nw, nh = button_size(menu, button)
        button.position = [max(0, min(CANVAS_W - nw, int(x + (w - nw) // 2))),
                           max(0, min(CANVAS_H - nh, int(y + h - nh)))]


def is_line_style(style) -> bool:
    from modules.button_shapes import SHAPE_LINE
    return style.kind == STYLE_SHAPE and style.shape == SHAPE_LINE


def boxes(menu: MenuNode) -> dict:
    return {b.id: button_box(menu, b) for b in menu.buttons}
