# core/menu_spacing.py
"""
Abstands-Hilfe beim Ziehen im Menü-Designer (Feinschliff nach v1.9.6), Qt-frei.

Wie in Keynote: Kommt der Abstand eines gezogenen Buttons zu seinem Nachbarn in die Nähe eines
Abstands, den es zwischen anderen Buttons schon gibt, rastet er dort ein; ebenso genau mittig zwischen
zwei Nachbarn. Solange die Hilfe greift, zeigt der Viewer die gleichen Abstände als Markierungen.
Nichts davon wird gespeichert – auf die Disc kommen nur die fertigen Positionen.
"""

from typing import List, Optional, Sequence, Tuple

Rect = Tuple[float, float, float, float]          # x, y, Breite, Höhe
Segment = Tuple[float, float, float, float]       # x1, y1, x2, y2 einer Abstands-Markierung
SPACING_TOLERANCE = 12                            # Bildpunkte im 1920×1080 Raum
_SAME = 1.0                                       # Abstände, die sich um höchstens so viel unterscheiden, gelten als gleich
THIN = 24                                         # flacher als das (Linien): rastet nur mit der Mitte ein (v1.15.3)


def _axis(rect: Rect, axis: str) -> Tuple[float, float, float, float]:
    """(Anfang, Länge, Queranfang, Querlänge) entlang der Achse „y“ (untereinander) oder „x“ (nebeneinander)."""
    x, y, w, h = rect
    return (y, h, x, w) if axis == "y" else (x, w, y, h)


def _overlaps_across(a: Rect, b: Rect, axis: str) -> bool:
    _, _, a0, al = _axis(a, axis)
    _, _, b0, bl = _axis(b, axis)
    return a0 < b0 + bl and b0 < a0 + al


def _marker(a: Rect, b: Rect, axis: str) -> Segment:
    """Markierung für den Abstand zwischen a (davor) und b (danach), mittig im gemeinsamen Querbereich."""
    a0, al, ac0, acl = _axis(a, axis)
    b0, _, bc0, bcl = _axis(b, axis)
    lo, hi = max(ac0, bc0), min(ac0 + acl, bc0 + bcl)
    c = (lo + hi) / 2 if hi > lo else ac0 + acl / 2
    return (c, a0 + al, c, b0) if axis == "y" else (a0 + al, c, b0, c)


def existing_gaps(others: Sequence[Rect], axis: str) -> List[Tuple[float, Segment]]:
    """Abstände zwischen direkt aufeinanderfolgenden Buttons (quer überlappend), mit ihrer Markierung."""
    gaps = []
    for a in others:
        a0, al, _, _ = _axis(a, axis)
        after = [b for b in others if b is not a and _overlaps_across(a, b, axis) and _axis(b, axis)[0] >= a0 + al]
        if after:
            b = min(after, key=lambda r: _axis(r, axis)[0])
            gaps.append((_axis(b, axis)[0] - (a0 + al), _marker(a, b, axis)))
    return gaps


def snap_alignment(moving: Rect, others: Sequence[Rect], axis: str,
                   tolerance: float = SPACING_TOLERANCE) -> Optional[Tuple[float, List[Segment]]]:
    """
    Ausrichtung entlang der Achse: Anfang an Anfang, Mitte an Mitte, Ende an Ende eines anderen Buttons
    (Achse „x“: linke Kante, Mitte, rechte Kante). Ab v1.15.3 nur noch Gleiches an Gleichem, und bei flachen
    Formen (Linien, unter THIN Bildpunkten) nur die Mitte – sonst lagen bei einer 8 px hohen Linie neun
    Einrastpunkte innerhalb von 8 px, und sie sprang hin und her. Markierung: eine Linie durch beide Buttons.
    """
    m0, ml, mc0, mcl = _axis(moving, axis)
    best = None
    for o in others:
        o0, ol, oc0, ocl = _axis(o, axis)
        pairs = [(m0 + ml / 2, o0 + ol / 2)]
        if ml >= THIN and ol >= THIN:
            pairs += [(m0, o0), (m0 + ml, o0 + ol)]
        for mv, ov in pairs:
            shift = ov - mv
            if abs(shift) <= tolerance and (best is None or abs(shift) < abs(best[0])):
                lo, hi = min(mc0, oc0), max(mc0 + mcl, oc0 + ocl)
                seg = (ov, lo, ov, hi) if axis == "x" else (lo, ov, hi, ov)
                best = (shift, [seg])
    return best


def snap_center(moving: Rect, axis: str, canvas: Tuple[float, float] = (1920, 1080),
                tolerance: float = SPACING_TOLERANCE) -> Optional[Tuple[float, List[Segment]]]:
    """Mitte des gezogenen Buttons (bzw. Rasters) auf die Bildmitte; Markierung: Mittellinie durchs Bild."""
    m0, ml, _, _ = _axis(moving, axis)
    mid = (canvas[0] if axis == "x" else canvas[1]) / 2
    shift = mid - (m0 + ml / 2)
    if abs(shift) > tolerance:
        return None
    seg = (mid, 0, mid, canvas[1]) if axis == "x" else (0, mid, canvas[0], mid)
    return shift, [seg]


def snap_spacing(moving: Rect, others: Sequence[Rect], axis: str,
                 tolerance: float = SPACING_TOLERANCE) -> Optional[Tuple[float, List[Segment]]]:
    """
    Verschiebung entlang der Achse, mit der der gezogene Button einen vorhandenen Abstand trifft
    (oder genau mittig zwischen seinen Nachbarn sitzt), und die Markierungen der gleichen Abstände.
    None, wenn nichts in der Nähe liegt.
    """
    m0, ml, _, _ = _axis(moving, axis)
    column = [o for o in others if _overlaps_across(o, moving, axis)]
    center = m0 + ml / 2
    before = [o for o in column if _axis(o, axis)[0] + _axis(o, axis)[1] / 2 < center]
    after = [o for o in column if _axis(o, axis)[0] + _axis(o, axis)[1] / 2 >= center]
    prev = max(before, key=lambda r: sum(_axis(r, axis)[:2])) if before else None
    nxt = min(after, key=lambda r: _axis(r, axis)[0]) if after else None
    gaps = [g for g in existing_gaps(others, axis) if g[0] > 0]

    candidates = []   # (neue Position, Abstand, Nachbarn)
    for gap, _seg in gaps:
        if prev is not None:
            candidates.append((sum(_axis(prev, axis)[:2]) + gap, gap, (prev, None)))
        if nxt is not None:
            candidates.append((_axis(nxt, axis)[0] - gap - ml, gap, (None, nxt)))
    if prev is not None and nxt is not None:
        start, end = sum(_axis(prev, axis)[:2]), _axis(nxt, axis)[0]
        if end - start > ml:
            candidates.append((start + (end - start - ml) / 2, (end - start - ml) / 2, (prev, nxt)))
    candidates = [c for c in candidates if abs(c[0] - m0) <= tolerance]
    if not candidates:
        return None
    pos, gap, (p, n) = min(candidates, key=lambda c: abs(c[0] - m0))

    delta = pos - m0
    x, y, w, h = moving
    placed = (x, y + delta, w, h) if axis == "y" else (x + delta, y, w, h)
    markers = [seg for g, seg in gaps if abs(g - gap) <= _SAME]
    if p is not None:
        markers.append(_marker(p, placed, axis))
    if n is not None:
        markers.append(_marker(placed, n, axis))
    return delta, markers
