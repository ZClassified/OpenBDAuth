# core/menu_guides.py
"""
Hilfslinien im Menü-Designer (v1.9.4), Qt-frei.

- Eigene Linien (v1.16.0) gelten in allen Menüs: waagerecht oder senkrecht, mit Abstand in Bildpunkten von einer
  Kante. Angelegt werden sie aus den Linealen im Viewer.
- Ältere Linien eines Menüs verbinden zwei Ankerpunkte an verschiedenen Kanten ([Kante, Anteil]); sie werden
  weiter angezeigt und lassen sich löschen, neu anlegen lassen sie sich seit v1.16.1 nicht mehr.
- Linien sind reine Einrast-Hilfen beim Ziehen (viewer.py, _snap_to_lines, ab v1.16.4); nichts wird an ihnen
  festgehalten.

Hilfslinien sind Ansichtsdaten (DiscProject.view); auf der Disc landen nur die Positionen der Buttons.
"""

from typing import List, Optional, Sequence, Tuple

from core.disc_model import DiscProject, Guide, FixedGuide, new_id
from core import menu_design

CANVAS_W, CANVAS_H = menu_design.CANVAS_W, menu_design.CANVAS_H
EDGES = ("top", "bottom", "left", "right")
SNAP_DISTANCE = 16                # Bildpunkte im 1920×1080 Raum

# Anteile, an denen eine neue Linie im Lineal einrastet (Feinschliff v1.9.7): Title Safe, Viertel, Goldener
# Schnitt, Mitte. Ältere Linien können noch an früheren Punkten hängen: Ankerpunkte stehen als [Kante, Anteil].
ANCHOR_TITLE_SAFE = "Title Safe"
ANCHOR_QUARTER = "Viertel"
ANCHOR_GOLDEN = "Goldener Schnitt"
ANCHOR_CENTER = "Mitte"
ANCHOR_RATIOS = [
    (0.05, ANCHOR_TITLE_SAFE), (0.25, ANCHOR_QUARTER), (0.382, ANCHOR_GOLDEN), (0.5, ANCHOR_CENTER),
    (0.618, ANCHOR_GOLDEN), (0.75, ANCHOR_QUARTER), (0.95, ANCHOR_TITLE_SAFE),
]


class GuideError(ValueError):
    pass


# -------------------------------------------------------------------------
# Geometrie
# -------------------------------------------------------------------------

def anchor_xy(anchor: Sequence) -> Tuple[float, float]:
    edge, ratio = anchor[0], float(anchor[1])
    if edge == "top":
        return ratio * CANVAS_W, 0.0
    if edge == "bottom":
        return ratio * CANVAS_W, float(CANVAS_H)
    if edge == "left":
        return 0.0, ratio * CANVAS_H
    if edge == "right":
        return float(CANVAS_W), ratio * CANVAS_H
    raise GuideError(f"Unbekannte Kante: {edge}")


def endpoints(guide: Guide) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    return anchor_xy(guide.a), anchor_xy(guide.b)


# -------------------------------------------------------------------------
# Abfragen
# -------------------------------------------------------------------------

def guides(project_: DiscProject, menu_id: str) -> List[Guide]:
    """Linien eines Menüs: seine eigenen und die eigenen Linien aller Menüs (v1.16.0)."""
    return project_.view.guides.get(menu_id, []) + [as_guide(f) for f in project_.view.fixed_guides]


def guide(project_: DiscProject, menu_id: str, guide_id: str) -> Optional[Guide]:
    return next((g for g in guides(project_, menu_id) if g.id == guide_id), None)


# -------------------------------------------------------------------------
# Eigene Linien in allen Menüs (v1.16.0)
# -------------------------------------------------------------------------

HORIZONTAL_EDGES = ("top", "bottom")
VERTICAL_EDGES = ("left", "right")


def is_horizontal(edge: str) -> bool:
    return edge in HORIZONTAL_EDGES


def fixed_coordinate(fixed: FixedGuide) -> float:
    """y einer waagerechten bzw. x einer senkrechten Linie im 1920×1080 Raum."""
    size = CANVAS_H if is_horizontal(fixed.edge) else CANVAS_W
    return float(fixed.distance) if fixed.edge in ("top", "left") else float(size - fixed.distance)


def as_guide(fixed: FixedGuide) -> Guide:
    """Als Hilfslinie von Rand zu Rand (links → rechts bzw. oben → unten); ID wie die eigene Linie."""
    pos = fixed_coordinate(fixed)
    if is_horizontal(fixed.edge):
        return Guide(id=fixed.id, a=["left", pos / CANVAS_H], b=["right", pos / CANVAS_H])
    return Guide(id=fixed.id, a=["top", pos / CANVAS_W], b=["bottom", pos / CANVAS_W])


def fixed_guide(project_: DiscProject, guide_id: str) -> Optional[FixedGuide]:
    return next((f for f in project_.view.fixed_guides if f.id == guide_id), None)


def clamp_distance(edge: str, distance) -> int:
    return max(0, min(CANVAS_H if is_horizontal(edge) else CANVAS_W, int(round(float(distance)))))


def add_fixed_guide(project_: DiscProject, edge: str, distance, guide_id: Optional[str] = None) -> FixedGuide:
    if edge not in EDGES:
        raise GuideError(f"Unbekannte Kante: {edge}")
    fixed = FixedGuide(id=guide_id or new_id("line"), edge=edge, distance=clamp_distance(edge, distance))
    project_.view.fixed_guides.append(fixed)
    return fixed


def set_fixed_guide(project_: DiscProject, guide_id: str, edge: Optional[str] = None, distance=None):
    """
    Abstand und/oder Bezugskante ändern. Nur die Kante zu wechseln (z. B. von unten → von oben) lässt die Linie
    liegen und rechnet den Abstand um.
    """
    fixed = fixed_guide(project_, guide_id)
    if fixed is None:
        raise GuideError("Unbekannte Linie.")
    if edge is not None and edge != fixed.edge:
        if edge not in (HORIZONTAL_EDGES if is_horizontal(fixed.edge) else VERTICAL_EDGES):
            raise GuideError("Eine waagerechte Linie misst von oben oder unten, eine senkrechte von links oder rechts.")
        size = CANVAS_H if is_horizontal(fixed.edge) else CANVAS_W
        fixed.edge, fixed.distance = edge, clamp_distance(edge, size - fixed.distance)
    if distance is not None:
        fixed.distance = clamp_distance(fixed.edge, distance)


# -------------------------------------------------------------------------
# Bearbeiten
# -------------------------------------------------------------------------

def add_guide(project_: DiscProject, menu_id: str, a: Sequence, b: Sequence,
              guide_id: Optional[str] = None) -> Guide:
    """Linie eines Menüs zwischen zwei Ankerpunkten (nur noch beim Übernehmen in „wie bei …“)."""
    if a[0] == b[0]:
        raise GuideError("Eine Hilfslinie verbindet zwei verschiedene Kanten.")
    g = Guide(id=guide_id or new_id("guide"), a=[a[0], float(a[1])], b=[b[0], float(b[1])])
    project_.view.guides.setdefault(menu_id, []).append(g)
    return g


def remove_guide(project_: DiscProject, menu_id: str, guide_id: str):
    """Linie löschen; eine eigene Linie verschwindet aus allen Menüs (v1.16.0)."""
    if fixed_guide(project_, guide_id) is not None:
        project_.view.fixed_guides = [f for f in project_.view.fixed_guides if f.id != guide_id]
    else:
        project_.view.guides[menu_id] = [g for g in project_.view.guides.get(menu_id, []) if g.id != guide_id]
