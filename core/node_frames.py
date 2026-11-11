# core/node_frames.py
"""
Rahmen im Node-Editor (v1.15.0, Konzept 3.5), Qt-frei.

Ein Rahmen ist eine beschriftete, farbige Fläche hinter den Knoten (ViewState.groups, NodeGroup.rect). Dazu
gehört, was darin liegt: Knoten mit ihrer Mitte, andere Rahmen ganz. Eine Mitgliederliste gibt es nicht –
Knoten zieht man einfach hinein oder heraus. Reine Ansicht, kein Einfluss auf die Disc.
"""

from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from core.disc_model import DiscProject, NodeGroup, new_id

FRAME_COLORS = ["#64748B", "#22C55E", "#A855F7", "#F97316", "#EC4899", "#14B8A6", "#EAB308", "#EF4444"]
MIN_W, MIN_H = 160.0, 80.0
PADDING = 30.0          # Rand um die Knoten beim Einrahmen einer Auswahl
TITLE_H = 30.0          # Höhe der Titelleiste (Platz über den Knoten)

Rect = Tuple[float, float, float, float]


def frame(project: DiscProject, frame_id: str) -> Optional[NodeGroup]:
    return next((g for g in project.view.groups if g.id == frame_id), None)


def next_color(project: DiscProject) -> str:
    """Erste Farbe, die noch kein Rahmen hat (sonst reihum)."""
    used = [g.color for g in project.view.groups]
    free = [c for c in FRAME_COLORS if c not in used]
    return free[0] if free else FRAME_COLORS[len(used) % len(FRAME_COLORS)]


def normalized(rect: Sequence[float]) -> List[float]:
    x, y, w, h = (float(v) for v in rect)
    return [round(x, 1), round(y, 1), round(max(MIN_W, w), 1), round(max(MIN_H, h), 1)]


def around(boxes: Iterable[Rect]) -> Optional[List[float]]:
    """Rahmen um Knoten-Rechtecke (x, y, w, h) mit Rand und Platz für die Titelleiste."""
    boxes = list(boxes)
    if not boxes:
        return None
    left = min(x for x, _y, _w, _h in boxes) - PADDING
    top = min(y for _x, y, _w, _h in boxes) - PADDING - TITLE_H
    right = max(x + w for x, _y, w, _h in boxes) + PADDING
    bottom = max(y + h for _x, y, _w, h in boxes) + PADDING
    return normalized([left, top, right - left, bottom - top])


def add_frame(project: DiscProject, rect: Sequence[float], name: str, color: Optional[str] = None,
              frame_id: Optional[str] = None) -> NodeGroup:
    group = NodeGroup(id=frame_id or new_id("frame"), name=name, color=color or next_color(project),
                      rect=normalized(rect))
    project.view.groups.append(group)
    return group


def set_frame(project: DiscProject, frame_id: str, **fields):
    """Name, Farbe oder rect eines Rahmens ändern."""
    group = frame(project, frame_id)
    if group is None:
        return
    for key, value in fields.items():
        setattr(group, key, normalized(value) if key == "rect" else value)


def remove_frames(project: DiscProject, frame_ids: Iterable[str]):
    """Nur die Rahmen; die Knoten darin bleiben, wo sie sind."""
    ids = set(frame_ids)
    project.view.groups = [g for g in project.view.groups if g.id not in ids]


def contains_point(rect: Sequence[float], x: float, y: float) -> bool:
    fx, fy, fw, fh = rect
    return fx <= x <= fx + fw and fy <= y <= fy + fh


def contains_rect(outer: Sequence[float], inner: Sequence[float]) -> bool:
    ox, oy, ow, oh = outer
    ix, iy, iw, ih = inner
    return ox <= ix and oy <= iy and ix + iw <= ox + ow and iy + ih <= oy + oh


def members(project: DiscProject, frame_id: str, node_boxes: Dict[str, Rect]) -> Tuple[List[str], List[str]]:
    """
    (Knoten-IDs, Rahmen-IDs), die zum Rahmen gehören: Knoten mit ihrer Mitte darin, Rahmen ganz darin.
    node_boxes: Knoten-ID → (x, y, w, h) in Szenen-Koordinaten (die Größe kennt nur die Oberfläche).
    """
    group = frame(project, frame_id)
    if group is None:
        return [], []
    nodes = [nid for nid, (x, y, w, h) in node_boxes.items() if contains_point(group.rect, x + w / 2, y + h / 2)]
    frames = [g.id for g in project.view.groups if g.id != frame_id and contains_rect(group.rect, g.rect)]
    return nodes, frames


def move_frame(project: DiscProject, frame_id: str, dx: float, dy: float, node_ids: Iterable[str] = (),
               frame_ids: Iterable[str] = ()):
    """Rahmen samt Inhalt verschieben (Inhalt vorher mit members() bestimmen)."""
    for fid in [frame_id, *frame_ids]:
        group = frame(project, fid)
        if group is not None:
            x, y, w, h = group.rect
            group.rect = normalized([x + dx, y + dy, w, h])
    positions = project.view.node_positions
    for node_id in node_ids:
        if node_id in positions:
            x, y = positions[node_id]
            positions[node_id] = [x + dx, y + dy]
