# gui/studio/viewer.py
"""
Viewer: zeigt, wie der ausgewählte Knoten aussieht.
- Menü: Vorschau im 1920×1080 Raum mit exakt dem Button-Layout des Exports
- Film: Übersichtskarte (Format, Dateien, Spuren, Kapitel)
- Start: Überblick über die Disc
"""

import os
from functools import lru_cache
from typing import Dict, List, Optional

from PySide6 import QtGui
from PySide6.QtCore import Qt, QRectF, QPointF, QTimer, Signal, QMimeData
from PySide6.QtWidgets import (
    QWidget, QStackedWidget, QVBoxLayout, QHBoxLayout, QLabel, QGraphicsView, QGraphicsScene,
    QGraphicsItem, QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsEllipseItem, QGraphicsPathItem, QGraphicsLineItem, QComboBox, QCheckBox, QMenu,
    QPushButton, QButtonGroup, QApplication, QSizePolicy, QLineEdit,
)

from core import menu_design, menu_guides, menu_spacing
from core.disc_labels import disc_label
from core.translations import tr, ui_language
from core.disc_model import START_NODE_ID
from core.disc_adapter import preview_menu_specs
from core.disc_rules import button_label, target_marker, has_target
from core.disc_model import BUTTON_NAV, BUTTON_CHAPTER, BUTTON_AUDIO, BUTTON_SUBTITLE
from gui.node_editor.controller import GraphController
from gui.studio.widgets import hint_label

CANVAS_W, CANVAS_H = 1920, 1080


MODE_BUTTON_QSS = """
QPushButton {{ color: #D4D4D8; background-color: #202024; border: 1px solid #3F3F46; padding: 5px 14px;
               font-weight: 600; border-top-left-radius: {left}; border-bottom-left-radius: {left};
               border-top-right-radius: {right}; border-bottom-right-radius: {right}; }}
QPushButton:hover {{ background-color: #34343A; }}
QPushButton:checked {{ color: #FFFFFF; background-color: #3D3218; border-color: #FBBF24; }}
"""

STATE_PLAYER = "player"   # wie auf dem Player: Standard-Button ausgewählt, die übrigen normal
BUTTON_STATES = (STATE_PLAYER, "normal", "selected", "activated")
C_SELECT = QtGui.QColor("#FBBF24")
C_GHOST = QtGui.QColor(161, 161, 170, 170)
C_OUTSIDE_SAFE = QtGui.QColor("#FB923C")        # Button ragt über die Title-Safe-Zone hinaus
C_SAFE_FRAME = QtGui.QColor(161, 161, 170, 110)
C_MISSING = QtGui.QColor("#F87171")             # Button ohne Ziel (v1.12.2)
PALETTE_MIME = "application/x-openbdauth-button-kind"
PALETTE_KINDS = (BUTTON_NAV, BUTTON_CHAPTER, BUTTON_AUDIO, BUTTON_SUBTITLE)
MARKER_MAX = 16                                 # Zeichen einer Ziel-Plakette (lange Namen gekürzt)
MARKER_GAP = 3                                  # Bildschirm-Pixel zwischen Button-Unterkante und Plakette
TITLE_SAFE = QRectF(96, 54, 1728, 972)          # 90 % von 1920 × 1080 (wie core/preflight.py)
MIN_GRAB = 24                                   # kleinste Greiffläche eines Buttons im 1920 × 1080 Raum
MIN_BUTTON = 8                                  # kleinste Button-Größe (wie modules.button_shapes.MIN_SIZE)
HANDLE_SPREAD = 32                              # Griffe dünner Buttons mindestens so weit auseinander (Bildschirm-Pixel)
SIZE_HANDLES = ("tl", "t", "tr", "r", "br", "b", "bl", "l")
SIZE_CURSORS = {"tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor, "tr": Qt.SizeBDiagCursor,
                "bl": Qt.SizeBDiagCursor, "t": Qt.SizeVerCursor, "b": Qt.SizeVerCursor,
                "l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor}


@lru_cache(maxsize=512)
def button_pixmap(text: str, width: int, height: int, state: str, shape=None) -> QtGui.QPixmap:
    """Dieselbe Button-Grafik, die der Export in den Menüstrom schreibt (Stil-Generator oder Form)."""
    if shape is not None:
        from modules.button_shapes import create_shape_image
        img = create_shape_image(shape, width, height, state)
    else:
        from modules.menu_author import create_button_image
        img = create_button_image(text, width, height, state)
    data = img.tobytes("raw", "RGBA")
    qimage = QtGui.QImage(data, img.width, img.height, 4 * img.width, QtGui.QImage.Format_RGBA8888).copy()
    return QtGui.QPixmap.fromImage(qimage)


class _ButtonItem(QGraphicsPixmapItem):
    """
    Ein Button der Menüseite; die Auswahl im Designer wird als goldener Rahmen darüber gezeichnet,
    ein oranger Rahmen warnt beim Ziehen außerhalb der Title-Safe-Zone.
    """

    def __init__(self, spec, button_id: str, is_content: bool, pixmap: QtGui.QPixmap):
        super().__init__(pixmap)
        self.spec = spec
        self.button_id = button_id
        self.is_content = is_content
        self.chosen = False
        self.outside_safe = False
        self.show_outline = False   # Form, die im aktuellen Zustand unsichtbar ist: gepunkteter Umriss
        self.missing = False        # ohne Ziel (Inhalt ohne Kapitel/Spur, Navigation unverbunden): roter Rand
        self.state_name = "normal"  # gezeichneter Zustand (für die Live-Vorschau beim Größe-Ändern)
        self.setShapeMode(QGraphicsPixmapItem.BoundingRectShape)
        self.setTransformationMode(Qt.SmoothTransformation)   # verkleinerte Vorschau: Schrift bleibt lesbar
        self.setPos(spec.x or 0, spec.y or 0)
        self.setCursor(Qt.OpenHandCursor)
        self.setZValue(1)

    def hit_rect(self) -> QRectF:
        """Greiffläche: mindestens MIN_GRAB × MIN_GRAB, damit auch dünne Linien zu fassen sind."""
        rect = QRectF(self.pixmap().rect())
        pad_x = max(0.0, (MIN_GRAB - rect.width()) / 2)
        pad_y = max(0.0, (MIN_GRAB - rect.height()) / 2)
        return rect.adjusted(-pad_x, -pad_y, pad_x, pad_y)

    def boundingRect(self) -> QRectF:
        return self.hit_rect().adjusted(-6, -6, 6, 6)   # Platz für den Auswahlrahmen

    def shape(self) -> QtGui.QPainterPath:
        path = QtGui.QPainterPath()
        path.addRect(self.hit_rect())
        return path

    def paint(self, painter, option, widget=None):
        super().paint(painter, option, widget)
        if self.show_outline and not self.chosen:
            painter.setPen(QtGui.QPen(C_GHOST, 2, Qt.DotLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRectF(self.pixmap().rect()))
        if self.missing and not self.chosen:
            painter.setPen(QtGui.QPen(C_MISSING, 3))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(self.boundingRect().adjusted(3, 3, -3, -3), 10, 10)
        if self.outside_safe:
            painter.setPen(QtGui.QPen(C_OUTSIDE_SAFE, 5))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(self.boundingRect().adjusted(3, 3, -3, -3), 12, 12)
        if self.chosen:
            painter.setPen(QtGui.QPen(C_SELECT, 3, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(self.boundingRect().adjusted(2, 2, -2, -2), 12, 12)

    def set_outside_safe(self, outside: bool):
        if outside != self.outside_safe:
            self.outside_safe = outside
            self.update()


class _MarkerItem(QGraphicsItem):
    """
    Ziel-Plakette eines Buttons (v1.12.2): K12, A2, U1, U–, „→ Name“. Feste Größe bei jedem Zoom – auch an dünnen
    Linien lesbar. Ab v1.15.2 knapp unter dem Button, bündig mit seiner linken Kante: sie verdeckt die Form
    nicht mehr und zeigt zugleich, wo der Button links beginnt. Beim Ziehen und Vergrößern ausgeblendet.
    Nur im Viewer, nicht auf der Disc; rot, wenn der Button kein Ziel hat.
    """

    def __init__(self, text: str, missing: bool, button_id: str = ""):
        super().__init__()
        self.button_id = button_id
        self.text = text if len(text) <= MARKER_MAX else text[:MARKER_MAX - 1] + "…"
        self.missing = missing
        self.font = QtGui.QFont()
        self.font.setPixelSize(11)
        self.font.setBold(True)
        metrics = QtGui.QFontMetrics(self.font)
        w, h = metrics.horizontalAdvance(self.text) + 10, metrics.height() + 4
        self._box = QRectF(0, MARKER_GAP, w, h)        # Ursprung: untere linke Ecke des Buttons
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setZValue(3)

    def boundingRect(self) -> QRectF:
        return self._box

    def paint(self, painter, option, widget=None):
        painter.setPen(Qt.NoPen)
        painter.setBrush(QtGui.QColor("#B91C1C") if self.missing else QtGui.QColor(24, 24, 27, 225))
        painter.drawRoundedRect(self._box, 4, 4)
        painter.setFont(self.font)
        painter.setPen(QtGui.QColor("#FFFFFF") if self.missing else QtGui.QColor("#FBBF24"))
        painter.drawText(self._box, Qt.AlignCenter, self.text)


class _OrderItem(QGraphicsItem):
    """Nummer in der Reihenfolge „Ziele der Reihe nach“ (v1.14), solange der Inspektor sie zeigt."""
    R = 12

    def __init__(self, number: int):
        super().__init__()
        self.text = str(number)
        self.font = QtGui.QFont()
        self.font.setPixelSize(12)
        self.font.setBold(True)
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setZValue(3.5)

    def boundingRect(self) -> QRectF:
        return QRectF(-self.R, -self.R, 2 * self.R, 2 * self.R)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.setPen(QtGui.QPen(QtGui.QColor("#18181B"), 1.5))
        painter.setBrush(QtGui.QColor("#FB923C"))
        painter.drawEllipse(self.boundingRect().adjusted(1, 1, -1, -1))
        painter.setFont(self.font)
        painter.setPen(QtGui.QColor("#18181B"))
        painter.drawText(self.boundingRect(), Qt.AlignCenter, self.text)


class _PaletteButton(QPushButton):
    """Palette (v1.12.2): in den Viewer ziehen legt einen Button dieser Art an der Stelle an, Klick am nächsten
    freien Platz."""

    def __init__(self, kind: str, on_click):
        super().__init__()
        self.kind = kind
        self._press = None
        self.clicked.connect(lambda: on_click(kind))
        self.setCursor(Qt.OpenHandCursor)

    def mousePressEvent(self, event):
        self._press = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press is not None and (event.position().toPoint() - self._press).manhattanLength() \
                >= QApplication.startDragDistance():
            self._press = None
            self.setDown(False)
            from PySide6.QtGui import QDrag
            drag = QDrag(self)
            mime = QMimeData()
            mime.setData(PALETTE_MIME, self.kind.encode("ascii"))
            drag.setMimeData(mime)
            drag.exec(Qt.CopyAction)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._press = None
        super().mouseReleaseEvent(event)


class _SizeHandleItem(QGraphicsRectItem):
    """Ziehgriff zum Ändern der Button-Größe (v1.11.1); bleibt unabhängig vom Zoom gleich groß."""

    def __init__(self, code: str, center: QPointF):
        super().__init__(-5, -5, 10, 10)
        self.code = code
        self.setPos(center)
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self.setPen(QtGui.QPen(QtGui.QColor("#18181B"), 1))
        self.setBrush(QtGui.QBrush(C_SELECT))
        self.setCursor(SIZE_CURSORS[code])
        self.setZValue(5)


def handle_points(rect: QRectF, spread: float = HANDLE_SPREAD) -> Dict[str, QPointF]:
    """Lage der acht Griffe; bei dünnen Buttons (Linie) mindestens spread auseinander."""
    c = rect.center()
    w, h = max(rect.width(), spread) / 2, max(rect.height(), spread) / 2
    xs = {"l": c.x() - w, "r": c.x() + w}
    ys = {"t": c.y() - h, "b": c.y() + h}
    return {code: QPointF(xs.get(code[-1], c.x()), ys.get(code[0], c.y())) for code in SIZE_HANDLES}


def resized_rects(rects: Dict[str, tuple], primary: str, code: str, dx: float, dy: float,
                  symmetric: bool = False, keep_ratio: bool = False) -> Dict[str, tuple]:
    """
    Neue Rechtecke (x, y, w, h) beim Ziehen eines Griffs. Der gezogene Button folgt der Maus; alle
    ausgewählten bekommen in der gezogenen Richtung dieselbe Breite bzw. Höhe und behalten die
    gegenüberliegende Kante (symmetric: die Mitte). keep_ratio (Umschalt an einer Ecke): Seitenverhältnis bleibt.
    """
    x, y, w, h = rects[primary]
    horizontal, vertical = "l" in code or "r" in code, "t" in code or "b" in code
    grow_x = (-dx if "l" in code else dx) * (2 if symmetric else 1)
    grow_y = (-dy if "t" in code else dy) * (2 if symmetric else 1)
    nw = max(MIN_BUTTON, min(CANVAS_W, w + grow_x)) if horizontal else w
    nh = max(MIN_BUTTON, min(CANVAS_H, h + grow_y)) if vertical else h
    if keep_ratio and horizontal and vertical and w and h:
        scale = max(nw / w, nh / h)
        nw = max(MIN_BUTTON, min(CANVAS_W, w * scale))
        nh = max(MIN_BUTTON, min(CANVAS_H, h * scale))
    nw, nh = int(round(nw)), int(round(nh))
    fx = 0.5 if symmetric else (1.0 if "l" in code else 0.0)
    fy = 0.5 if symmetric else (1.0 if "t" in code else 0.0)
    result = {}
    for bid, (ox, oy, ow, oh) in rects.items():
        w2 = nw if horizontal else ow
        h2 = nh if vertical else oh
        x2 = max(0, min(CANVAS_W - w2, ox + (ow - w2) * fx))
        y2 = max(0, min(CANVAS_H - h2, oy + (oh - h2) * fy))
        result[bid] = (int(round(x2)), int(round(y2)), w2, h2)
    return result


class _GhostItem(QGraphicsRectItem):
    """Vorschlag (Konzept 2.1, Regel 2) wie im Menü-Knoten: Klick legt an, Rechtsklick „Nicht benötigt“."""

    def __init__(self, rect: QRectF, suggestion):
        super().__init__(rect)
        self.suggestion = suggestion
        self.text, self.film_id, self.action = suggestion.text, suggestion.film_id, suggestion.action
        self.setPen(QtGui.QPen(C_GHOST, 2, Qt.DashLine))
        self.setBrush(QtGui.QBrush(QtGui.QColor(24, 24, 27, 90)))
        self.setCursor(Qt.PointingHandCursor)
        self.setZValue(1)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.setPen(self.pen())
        painter.setBrush(self.brush())
        painter.drawRoundedRect(self.rect(), 12, 12)
        painter.setPen(C_GHOST)
        from gui.theme import ui_font
        font = ui_font(max(10, int(self.rect().height() * 0.3)), italic=True)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignCenter, self.text)


C_GUIDE = QtGui.QColor(34, 211, 238, 210)
C_FIXED_GUIDE = QtGui.QColor(192, 132, 252, 225)   # eigene Linien in allen Menüs (v1.16.0)


class _LineLabelItem(QGraphicsItem):
    """
    Schild einer eigenen Linie („70 px von unten  ✕“, v1.16.1): feste Größe bei jedem Zoom. Klick auf die Zahl
    öffnet die Eingabe, Klick auf ✕ löscht die Linie (beides im MenuPreview, das die Klicks auswertet).
    """

    def __init__(self, guide_id: str, text: str, below: bool = False):
        super().__init__()
        self.guide_id = guide_id
        self.text = text
        self.font = QtGui.QFont()
        self.font.setPixelSize(11)
        self.font.setBold(True)
        metrics = QtGui.QFontMetrics(self.font)
        h = metrics.height() + 6
        # waagerechte Linie: über der Linie; senkrechte: rechts daneben, unter dem oberen Bildrand
        self.text_rect = QRectF(4, 6 if below else -h - 4, metrics.horizontalAdvance(text) + 12, h)
        self.close_rect = QRectF(self.text_rect.right() + 2, self.text_rect.top(), h, h)
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("")
        self.setZValue(3.2)

    def boundingRect(self) -> QRectF:
        return self.text_rect.united(self.close_rect)

    def paint(self, painter, option, widget=None):
        painter.setPen(Qt.NoPen)
        painter.setBrush(QtGui.QColor(24, 24, 27, 225))
        painter.drawRoundedRect(self.text_rect, 4, 4)
        painter.setBrush(QtGui.QColor(127, 29, 29, 225))
        painter.drawRoundedRect(self.close_rect, 4, 4)
        painter.setFont(self.font)
        painter.setPen(C_FIXED_GUIDE)
        painter.drawText(self.text_rect, Qt.AlignCenter, self.text)
        painter.setPen(QtGui.QColor("#FCA5A5"))
        painter.drawText(self.close_rect, Qt.AlignCenter, "✕")


RULER = 22                                       # Breite der Lineale oben und links (Bildschirm-Pixel)
LINE_SNAP_PX = 8                                 # Einrasten beim Ziehen einer Linie (Bildschirm-Pixel)


class _Ruler(QWidget):
    """
    Lineal direkt über bzw. links neben dem Bild (v1.16.1, ab v1.16.2 am Bild statt am Fensterrand): Skala in
    Bildpunkten des 1920×1080 Raums, violette Marken an den eigenen Linien. Beim Überfahren erscheinen ein ＋ und
    eine blasse Vorschau-Linie; ein Klick setzt die Linie genau dort – oben eine senkrechte bei x, links eine
    waagerechte bei y. Gedrückt halten und ziehen verschiebt sie vor dem Loslassen.
    """

    def __init__(self, view: "MenuPreview", side: str):
        super().__init__(view)
        self.view = view
        self.side = side                      # "top" oder "left"
        self.hover: Optional[float] = None    # Mausposition entlang des Lineals (Widget-Koordinate)
        self.setMouseTracking(True)
        self.setCursor(Qt.SplitVCursor if side == "top" else Qt.SplitHCursor)

    @property
    def horizontal_lines(self) -> bool:
        """Linkes Lineal (y-Skala) → waagerechte Linien, oberes (x-Skala) → senkrechte (v1.16.2)."""
        return self.side == "left"

    def _to_widget(self, scene_value: float) -> float:
        """Stelle im Bild → Koordinate im Lineal (das Lineal ist ein Kind der Ansicht, nicht des Viewports)."""
        p = self.view.mapFromScene(QPointF(scene_value, 0) if self.side == "top" else QPointF(0, scene_value))
        vp = self.view.viewport().geometry()
        return float(p.x() + vp.left() - self.x()) if self.side == "top" else float(p.y() + vp.top() - self.y())

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor("#18181B"))
        painter.setPen(QtGui.QColor("#27272A"))
        if self.side == "top":
            painter.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        else:
            painter.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
        size = CANVAS_W if self.side == "top" else CANVAS_H
        scale = self.view.transform().m11() or 1.0
        major = 100 if scale >= 0.35 else 200
        font = QtGui.QFont()
        font.setPixelSize(9)
        painter.setFont(font)
        for value in range(0, size + 1, major // 2):
            w = self._to_widget(value)
            is_major = value % major == 0
            length = 9 if is_major else 5
            painter.setPen(QtGui.QColor("#52525B") if is_major else QtGui.QColor("#3F3F46"))
            if self.side == "top":
                painter.drawLine(QPointF(w, RULER - length), QPointF(w, RULER))
                if is_major:
                    painter.setPen(QtGui.QColor("#71717A"))
                    painter.drawText(QPointF(w + 2, 10), str(value))
            else:
                painter.drawLine(QPointF(RULER - length, w), QPointF(RULER, w))
                if is_major:
                    painter.save()
                    painter.setPen(QtGui.QColor("#71717A"))
                    painter.translate(10, w - 2)
                    painter.rotate(-90)
                    painter.drawText(QPointF(0, 0), str(value))
                    painter.restore()
        # Marken der eigenen Linien: das obere Lineal (x) zeigt die senkrechten, das linke (y) die waagerechten
        controller = self.view.controller
        if controller is not None:
            painter.setPen(Qt.NoPen)
            painter.setBrush(C_FIXED_GUIDE)
            for fixed in controller.project.view.fixed_guides:
                if menu_guides.is_horizontal(fixed.edge) == (self.side == "top"):
                    continue
                w = self._to_widget(menu_guides.fixed_coordinate(fixed))
                if self.side == "top":
                    painter.drawPolygon(QtGui.QPolygonF([QPointF(w - 5, RULER - 7), QPointF(w + 5, RULER - 7),
                                                         QPointF(w, RULER)]))
                else:
                    painter.drawPolygon(QtGui.QPolygonF([QPointF(RULER - 7, w - 5), QPointF(RULER - 7, w + 5),
                                                         QPointF(RULER, w)]))
        # ＋ unter der Maus: hier beginnt eine neue Linie
        if self.hover is not None:
            painter.setBrush(QtGui.QColor(192, 132, 252, 235))
            painter.setPen(Qt.NoPen)
            center = QPointF(self.hover, RULER / 2) if self.side == "top" else QPointF(RULER / 2, self.hover)
            painter.drawEllipse(center, 8, 8)
            painter.setPen(QtGui.QPen(QtGui.QColor("#18181B"), 2))
            painter.drawLine(center + QPointF(-4, 0), center + QPointF(4, 0))
            painter.drawLine(center + QPointF(0, -4), center + QPointF(0, 4))
        painter.end()

    def mouseMoveEvent(self, event):
        pos = event.position()
        if event.buttons() & Qt.LeftButton:
            self.view.update_line_drag(event.globalPosition().toPoint(), event.modifiers())
            return
        self.hover = pos.x() if self.side == "top" else pos.y()
        self.update()
        self.view.preview_ruler_line(self.horizontal_lines, event.globalPosition().toPoint(), event.modifiers())

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.view.start_line_from_ruler(self.horizontal_lines, event.globalPosition().toPoint(), event.modifiers())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.view.finish_line_drag(event.globalPosition().toPoint())

    def leaveEvent(self, event):
        self.hover = None
        self.update()
        self.view.clear_ruler_preview()
        super().leaveEvent(event)


class _LineEditor(QLineEdit):
    """Eingabe am Schild einer eigenen Linie: Zahl tippen, Enter übernimmt, Esc bricht ab (v1.16.1)."""
    cancelled = Signal()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.cancelled.emit()
            return
        super().keyPressEvent(event)


class _GuideItem(QGraphicsLineItem):
    """Hilfslinie; lässt sich anklicken (Entf löscht, Rechtsklick: verteilen/löschen). Eigene Linien aller Menüs
    (v1.16.0) sind violett."""

    def __init__(self, guide_id: str, p1: QPointF, p2: QPointF, active: bool, fixed: bool = False):
        super().__init__(p1.x(), p1.y(), p2.x(), p2.y())
        self.guide_id = guide_id
        self.fixed = fixed
        self.set_active(active)
        self.setZValue(0.5)
        self.setAcceptedMouseButtons(Qt.NoButton)   # v1.16.4: Klicks gehen hindurch (Buttons greifen, nicht Linien)

    def set_active(self, active: bool):
        color = C_SELECT if active else (C_FIXED_GUIDE if self.fixed else C_GUIDE)
        self.setPen(QtGui.QPen(color, 4 if active else 2, Qt.DashLine))

    def shape(self) -> QtGui.QPainterPath:
        stroker = QtGui.QPainterPathStroker()
        stroker.setWidth(18)   # leichter zu treffen
        path = QtGui.QPainterPath(self.line().p1())
        path.lineTo(self.line().p2())
        return stroker.createStroke(path)


C_ARROW = QtGui.QColor(228, 228, 231, 220)
C_SPACING = QtGui.QColor(244, 114, 182, 235)   # Abstands-Hilfe (pink, hebt sich von Linien und Pfeilen ab)
DIRECTION_GLYPHS = {"up": "↑", "down": "↓", "left": "←", "right": "→"}


def _edge_point(rect: QRectF, toward: QPointF) -> QPointF:
    """Punkt, an dem die Strecke von der Rechteckmitte zu toward das Rechteck verlässt."""
    c = rect.center()
    dx, dy = toward.x() - c.x(), toward.y() - c.y()
    if dx == 0 and dy == 0:
        return c
    tx = (rect.width() / 2) / abs(dx) if dx else float("inf")
    ty = (rect.height() / 2) / abs(dy) if dy else float("inf")
    t = min(tx, ty, 1.0)
    return QPointF(c.x() + dx * t, c.y() + dy * t)


def arrow_path(p1: QPointF, p2: QPointF, head: float = 18) -> QtGui.QPainterPath:
    import math
    path = QtGui.QPainterPath(p1)
    path.lineTo(p2)
    angle = math.atan2(p2.y() - p1.y(), p2.x() - p1.x())
    for side in (-1, 1):
        a = angle + math.pi + side * 0.45
        path.moveTo(p2)
        path.lineTo(p2.x() + head * math.cos(a), p2.y() + head * math.sin(a))
    return path


MODE_DESIGN = "design"    # Buttons anordnen (Ziehen, Hilfslinien, Pfeiltasten verschieben)
MODE_REMOTE = "remote"    # wie am Fernseher: Pfeiltasten springen, Enter löst aus, Pfeil-Griffe legen fest
DIRECTIONS = ("up", "down", "left", "right")
HANDLE_R = 26
HANDLE_GAP = 8          # Griff-Mitte knapp außerhalb der Button-Kante (passt in enge Raster)
C_UNREACHABLE = QtGui.QColor("#EF4444")
C_HANDLE_BG = QtGui.QColor(24, 24, 27, 235)


class _HandleItem(QGraphicsEllipseItem):
    """
    Pfeil-Griff am aktuellen Button (Modus Fernbedienung), an der Seite, in die die Taste führt.
    Klick = Taste drücken; Ziehen auf einen Button = Richtung festlegen (gold); Rechtsklick = automatisch.
    """

    def __init__(self, direction: str, center: QPointF, target: Optional[str], overridden: bool, stays: bool):
        super().__init__(center.x() - HANDLE_R, center.y() - HANDLE_R, 2 * HANDLE_R, 2 * HANDLE_R)
        self.direction = direction
        self.center = center
        self.target = target
        self.overridden = overridden
        self.stays = stays            # führt nirgendwohin (bleibt auf dem Button)
        self.color = C_SELECT if overridden else (C_GHOST if stays else C_ARROW)
        self.setPen(QtGui.QPen(self.color, 4))
        self.setBrush(QtGui.QBrush(C_HANDLE_BG))
        self.setCursor(Qt.PointingHandCursor)
        self.setZValue(3)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        super().paint(painter, option, widget)
        painter.setPen(self.color)
        from gui.theme import ui_font
        font = ui_font(26, bold=True)
        painter.setFont(font)
        glyph = "•" if self.stays else DIRECTION_GLYPHS[self.direction]
        painter.drawText(self.rect(), Qt.AlignCenter, glyph)


class MenuPreview(QGraphicsView):
    """
    Menü-Designer (v1.9.3): zeigt die Menüseite mit den echten Button-Grafiken im 1920×1080 Raum.
    - Klick wählt einen Button aus (gemeinsam mit Inspektor und Node-Ansicht), Umschalt/Strg-Klick oder Rahmen
      mehrere. Ziehen verschiebt die Auswahl; Pfeiltasten: 1 px, mit Umschalt 10 px; Entf entfernt.
    - Ziel-Plaketten an jedem Button, roter Rand ohne Ziel; aus der Palette gezogene Buttons entstehen an der
      Stelle, an der sie losgelassen werden (v1.12.2).
    - Im Hauptmenü erscheinen Vorschläge als gestrichelte Buttons.
    - Hilfslinien (v1.9.4): von Ankerpunkt zu Ankerpunkt ziehen; Enden umhängen (mit Umschalt an einem
      belegten Punkt: neue Linie); Buttons und das Raster rasten mit ihrer Mitte ein und bleiben geheftet –
      sie gleiten beim Ziehen an der Linie und wandern mit, wenn die Linie umgehängt wird. X löst,
      Entf löscht die ausgewählte Linie.
    - Modus Fernbedienung (v1.9.9, Konzept 2.1 Regel 5): der ausgewählte Button ist der aktuelle; Pfeiltasten
      springen wie auf dem Player, Enter löst aus. Pfeil-Griffe am aktuellen Button: Klick = Taste, Ziehen auf
      einen Button = Richtung festlegen, Rechtsklick = automatisch. Unerreichbare Buttons sind rot umrandet.
    """
    suggestion_activated = Signal(object, object)   # (Suggestion, Bildschirmposition)
    suggestion_menu = Signal(object, object)        # Rechtsklick auf einen Vorschlag: (Suggestion, Bildschirmposition)
    node_requested = Signal(str)                    # Fernbedienung: Enter auf einem Button, der in ein Menü führt
    remote_message = Signal(str)                    # Fernbedienung: was der ausgelöste Button bewirkt
    generator_area = Signal(str, object)            # (Menü-ID, (x, y, w, h)): Bereich für den Generator (v1.14.2)

    def __init__(self, controller: Optional[GraphController] = None, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setScene(QGraphicsScene(0, 0, CANVAS_W, CANVAS_H, self))
        self.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform |
                            QtGui.QPainter.TextAntialiasing)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("background-color: #111113; border: 1px solid #27272A; border-radius: 8px;")
        self.setMinimumSize(320, 180)
        self.setFocusPolicy(Qt.StrongFocus)
        self.state = STATE_PLAYER
        self.show_guides = True
        self.snap_enabled = True                    # Häkchen „Einrasten“ (v1.17.3); aus = immer frei wie mit Alt
        self.show_markers = True
        self.marker_items: list = []
        self.order_items: list = []                 # Nummern „Ziele der Reihe nach“ (v1.14)
        self._area_pick: Optional[dict] = None      # Generator: Bereich aufziehen (v1.14.2)
        self._color_pick: Optional[str] = None      # Pipette: Stil-Feld „color_…“, das die Farbe bekommt (v1.14.4)
        self.setAcceptDrops(True)
        self.mode = MODE_DESIGN
        self.handle_items: Dict[str, _HandleItem] = {}
        self.unreachable_items: list = []
        self._remote_current: Optional[str] = None   # im Modus Fernbedienung gezeichneter aktueller Button
        self._remote_flash = False                   # Aktiviert-Zustand kurz nach Enter
        self._handle_drag: Optional[dict] = None
        self.menu_id: Optional[str] = None
        self.items: Dict[str, _ButtonItem] = {}
        self.guide_items: Dict[str, _GuideItem] = {}
        self.selected_guide: Optional[str] = None
        self.selection: set = set()                 # ausgewählte Buttons (Umschalt-/Strg-Klick, Auswahlrahmen)
        self._band: Optional[dict] = None           # Auswahlrahmen auf freier Fläche
        self._ghost_click = None                    # Klick auf einen Vorschlag: läuft beim Loslassen
        self._drag: Optional[dict] = None
        self._resize: Optional[dict] = None        # Ziehen an einem Größen-Griff
        self.size_handles: List[_SizeHandleItem] = []
        # Lineale (v1.16.1): eigene Linien aus dem Lineal ziehen, verschieben, am Schild Zahl eingeben
        self._line_drag: Optional[dict] = None
        self._line_editor: Optional[_LineEditor] = None
        self._ruler_preview: Optional[tuple] = None    # (Linie, Schild) beim Überfahren eines Lineals
        self.ruler_top = _Ruler(self, "top")
        self.ruler_left = _Ruler(self, "left")
        self._set_rulers_visible(False)
        if controller is not None:
            controller.button_selected.connect(self._on_button_selected)
            controller.selection_changed.connect(self._on_selection_changed)
            controller.order_preview.connect(self._show_order)
            controller.color_pick.connect(self.start_color_pick)

    # --- Aufbau ---------------------------------------------------------------
    def show_menu(self, project, menu):
        scene = self.scene()
        scene.clear()
        self.items = {}
        self.handle_items = {}   # mit clear() gelöscht
        self.size_handles = []
        self._resize = None
        self.unreachable_items = []
        self.spacing_items = []
        self.guide_items = {}
        self.marker_items = []
        self.order_items = []
        self._ruler_preview = None                     # mit clear() gelöscht
        if menu.id != self.menu_id:
            self.selection = set()
        self.selection &= {b.id for b in menu.buttons}
        self._band = None
        self.menu_id = menu.id
        from core.disc_adapter import effective_background
        background = effective_background(project, menu)   # eigener Hintergrund oder wie Hauptmenü (v1.13)
        from modules.sim_disc import menu_still           # bei Menü-Video das erste Bild (mit ffmpeg)
        self._draw_background(scene, menu_still(background.image, background.video))

        remote = self.mode == MODE_REMOTE
        current = self._current_button(menu) if remote else None
        self._remote_current = current
        specs = preview_menu_specs(project, menu)
        default_id = menu_design.start_button_id(menu)
        for button, spec in zip(menu.buttons, specs):
            state = self.state
            if remote:   # wie am Fernseher: der aktuelle Button ist ausgewählt (nach Enter kurz aktiviert)
                state = ("activated" if self._remote_flash else "selected") if button.id == current else "normal"
            elif state == STATE_PLAYER:
                state = "selected" if button.id == default_id else "normal"
            pixmap = button_pixmap(spec.text, int(spec.width or 380), int(spec.height or 70), state, spec.shape)
            item = _ButtonItem(spec, button.id, button.is_content, pixmap)
            item.show_outline = not remote and spec.shape is not None and spec.shape.state_color(state)[3] == 0
            item.state_name = state
            item.missing = not remote and (button.target is None if button.kind == BUTTON_NAV
                                           else not has_target(project, menu, button))
            scene.addItem(item)
            self.items[button.id] = item
        if remote:
            self._draw_remote(project, menu, current)
            if self.controller is not None and current and self.controller.selected_button != (menu.id, current):
                self.controller.select_button(menu.id, current)   # Inspektor und Node-Ansicht zeigen ihn mit
        else:
            frame = scene.addRect(TITLE_SAFE, QtGui.QPen(C_SAFE_FRAME, 2, Qt.DashLine))
            frame.setZValue(0.4)
            frame.setAcceptedMouseButtons(Qt.NoButton)
            self._draw_suggestions(project, menu, specs)
            self._draw_guides(project, menu.id)
            if self.show_markers:
                self._draw_markers(project, menu, specs)
            self._on_button_selected(*(self.controller.selected_button if self.controller else ("", "")))
        self._set_rulers_visible(not remote and self.show_guides and self.controller is not None)
        self.fitInView(scene.sceneRect(), Qt.KeepAspectRatio)
        self._place_rulers()                           # erst nach dem Einpassen liegt das Bild fest
        self._update_rulers()

    def _draw_markers(self, project, menu, specs):
        for button, spec in zip(menu.buttons, specs):
            item = self.items[button.id]
            marker = _MarkerItem(target_marker(project, menu, button), item.missing, button.id)
            marker.setPos(spec.x, spec.y + spec.height)
            self.scene().addItem(marker)
            self.marker_items.append(marker)

    def _hide_markers(self, button_ids=()):
        """Plaketten der gerade gezogenen bzw. vergrößerten Buttons ausblenden, die übrigen zeigen (v1.15.2)."""
        hidden = set(button_ids)
        for marker in self.marker_items:
            marker.setVisible(marker.button_id not in hidden)

    # --- Pipette: Farbe aus dem Hintergrund (v1.14.4) ----------------------------------
    def start_color_pick(self, menu_id: str, field: str):
        """Der nächste Klick ins Bild liest die Farbe des Hintergrunds an dieser Stelle (aus dem Original)."""
        if self.controller is None or menu_id != self.menu_id or self.mode != MODE_DESIGN:
            return
        self.cancel_area_pick()
        self._color_pick = field
        self.viewport().setCursor(Qt.CrossCursor)
        self.setFocus()
        self.controller.tool_hint.emit(self._t("studio_color_pick_hint"))

    def cancel_color_pick(self):
        if self._color_pick is None:
            return
        self._color_pick = None
        self.viewport().unsetCursor()
        if self.controller is not None:
            self.controller.tool_hint.emit("")

    def _finish_color_pick(self, pos: QPointF):
        from core import color_tools
        from core.disc_adapter import effective_background
        from modules.sim_disc import menu_still
        field = self._color_pick
        self.cancel_color_pick()
        project = self.controller.project
        menu = project.menu(self.menu_id)
        if menu is None:
            return
        bg = effective_background(project, menu)
        color = color_tools.color_at(menu_still(bg.image, bg.video), pos.x(), pos.y())
        if color is None:
            self.controller.tool_hint.emit(self._t("studio_color_pick_no_image"))
            return
        self.controller.set_button_style(self.menu_id, **{field: color})

    # --- Generator: Bereich aufziehen (v1.14.2) ------------------------------------------
    def start_area_pick(self):
        """Fadenkreuz: der nächste aufgezogene Rahmen ist der Bereich für den Generator (Esc bricht ab)."""
        if self.controller is None or self.menu_id is None:
            return
        self._area_pick = {"start": None, "item": None}
        self.viewport().setCursor(Qt.CrossCursor)
        self.setFocus()
        self.controller.tool_hint.emit(self._t("gen_pick_hint"))

    def cancel_area_pick(self):
        pick, self._area_pick = self._area_pick, None
        if pick and pick.get("item") is not None and pick["item"].scene() is self.scene():
            self.scene().removeItem(pick["item"])
        self.viewport().unsetCursor()
        if pick is not None and self.controller is not None:
            self.controller.tool_hint.emit("")

    def _area_rect(self, pos: QPointF) -> QRectF:
        end = QPointF(max(0.0, min(CANVAS_W, pos.x())), max(0.0, min(CANVAS_H, pos.y())))
        return QRectF(self._area_pick["start"], end).normalized()

    def _show_order(self, menu_id: str, button_ids: list):
        """Nummern 1, 2, 3 … auf den Buttons in der Reihenfolge, in der „Ziele der Reihe nach“ sie belegt."""
        for item in self.order_items:
            if item.scene() is self.scene():
                self.scene().removeItem(item)
        self.order_items = []
        if menu_id != self.menu_id:
            return
        for n, button_id in enumerate(button_ids, start=1):
            item = self.items.get(button_id)
            if item is None:
                continue
            number = _OrderItem(n)
            number.setPos(item.sceneBoundingRect().center())
            self.scene().addItem(number)
            self.order_items.append(number)

    # --- Palette: Buttons hineinziehen (v1.12.2) ------------------------------------
    def _palette_kind(self, event) -> Optional[str]:
        if self.mode != MODE_DESIGN or self.controller is None or self.menu_id is None:
            return None
        if not event.mimeData().hasFormat(PALETTE_MIME):
            return None
        return bytes(event.mimeData().data(PALETTE_MIME)).decode("ascii")

    def _background_files(self, event) -> list:
        """Bild, Video oder Musik aus dem Explorer: wird Hintergrund des gezeigten Menüs (v1.13.2)."""
        from gui.studio.backgrounds import background_files
        mime = event.mimeData()
        if self.controller is None or self.menu_id is None or not mime.hasUrls():
            return []
        files = [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]
        return files if background_files(files) else []

    def dragEnterEvent(self, event):
        if self._palette_kind(event) or self._background_files(event):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if self._palette_kind(event) or self._background_files(event):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        files = self._background_files(event)
        if files:
            # wirkt immer aufs Menü, auch wenn ein Button ausgewählt ist
            from gui.studio.backgrounds import apply_background_files
            apply_background_files(self.controller, self.menu_id, files)
            event.acceptProposedAction()
            return
        kind = self._palette_kind(event)
        if not kind:
            return super().dropEvent(event)
        pos = self.mapToScene(event.position().toPoint())
        self.add_from_palette(kind, (pos.x(), pos.y()))
        event.acceptProposedAction()

    def add_from_palette(self, kind: str, center=None):
        """Neuer Button aus der Palette (Mitte bei center, sonst nächster freier Platz); wird ausgewählt."""
        if self.controller is None or self.menu_id is None:
            return None
        label = disc_label("NEUER BUTTON", self.controller.project.settings.app_lang)
        return self.controller.add_button(self.menu_id, kind, center, label=label)

    def _current_button(self, menu) -> Optional[str]:
        """Aktueller Button im Modus Fernbedienung: der ausgewählte, sonst der Start-Button des Menüs."""
        sel_menu, sel_button = self.controller.selected_button if self.controller else ("", "")
        if sel_menu == menu.id and menu.button(sel_button) is not None:
            return sel_button
        return menu_design.start_button_id(menu)

    def _draw_guides(self, project, menu_id: str, snap_guide: Optional[str] = None):
        self.guide_items = {}
        if not self.show_guides:
            return
        scene = self.scene()
        if self.selected_guide not in {g.id for g in menu_guides.guides(project, menu_id)}:
            self.selected_guide = None
        for g in menu_guides.guides(project, menu_id):
            (x1, y1), (x2, y2) = menu_guides.endpoints(g)
            fixed = menu_guides.fixed_guide(project, g.id)
            item = _GuideItem(g.id, QPointF(x1, y1), QPointF(x2, y2), g.id in (self.selected_guide, snap_guide),
                              fixed is not None)
            scene.addItem(item)
            self.guide_items[g.id] = item
            if fixed is not None:
                self._add_line_label(fixed)

    def _add_line_label(self, fixed):
        """Schild am Anfang der Linie (links über der waagerechten, oben neben der senkrechten)."""
        horizontal = menu_guides.is_horizontal(fixed.edge)
        label = _LineLabelItem(fixed.id, self._t(f"studio_line_label_{fixed.edge}", px=fixed.distance),
                               below=not horizontal)
        pos = menu_guides.fixed_coordinate(fixed)
        label.setPos(QPointF(0, pos) if horizontal else QPointF(pos, 0))
        self.scene().addItem(label)
        return label

    # --- Modus Fernbedienung (v1.9.9) ------------------------------------------------
    def _draw_remote(self, project, menu, current: Optional[str]):
        """Pfeil-Griffe am aktuellen Button, gestrichelte Linien zu den Zielen, rote Rahmen um Unerreichbares."""
        scene = self.scene()
        item = self.items.get(current)
        if item is not None:
            button = menu.button(current)
            targets = menu_design.dpad_targets(project, menu).get(current, {})
            rect = item.sceneBoundingRect().adjusted(6, 6, -6, -6)
            c = rect.center()
            spots = {"up": QPointF(c.x(), rect.top() - HANDLE_GAP), "down": QPointF(c.x(), rect.bottom() + HANDLE_GAP),
                     "left": QPointF(rect.left() - HANDLE_GAP, c.y()), "right": QPointF(rect.right() + HANDLE_GAP, c.y())}
            margin = HANDLE_R + 4
            for direction in DIRECTIONS:
                spot = spots[direction]
                spot = QPointF(max(margin, min(CANVAS_W - margin, spot.x())),
                               max(margin, min(CANVAS_H - margin, spot.y())))
                target = targets.get(direction)
                stays = target is None or target == current or target not in self.items
                handle = _HandleItem(direction, spot, target, direction in button.dpad, stays)
                scene.addItem(handle)
                self.handle_items[direction] = handle
                if not stays:
                    other = self.items[target].sceneBoundingRect().adjusted(6, 6, -6, -6)
                    path = self._remote_path(direction, spot, rect, other)
                    line = scene.addPath(path, QtGui.QPen(handle.color, 4, Qt.DashLine), QtGui.QBrush(Qt.NoBrush))
                    line.setZValue(2.2)
                    line.setAcceptedMouseButtons(Qt.NoButton)
        reachable = menu_design.reachable_buttons(project, menu)
        for button_id, it in self.items.items():
            if button_id not in reachable:
                frame = scene.addRect(it.sceneBoundingRect().adjusted(-4, -4, 4, 4), QtGui.QPen(C_UNREACHABLE, 5))
                frame.setZValue(2.1)
                frame.setAcceptedMouseButtons(Qt.NoButton)
                frame.setToolTip(self._t("remote_unreachable"))
                self.unreachable_items.append(frame)

    def _remote_path(self, direction: str, spot: QPointF, rect: QRectF, other: QRectF) -> QtGui.QPainterPath:
        """
        Linie vom Griff zum Ziel. Liegt das Ziel in Pfeilrichtung, gerade; sonst (Wrap-Around, z. B. ↓ in
        der unteren Reihe führt nach oben) als Bogen außen herum, der am Ziel aus Pfeilrichtung ankommt.
        """
        import math
        dx, dy = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}[direction]
        ahead = (other.center().x() - spot.x()) * dx + (other.center().y() - spot.y()) * dy
        if ahead > 0:
            end = _edge_point(other, spot)
            return arrow_path(self._circle_edge(spot, end), end, head=22)
        # Bogen: in Pfeilrichtung hinaus, seitlich an allem vorbei, von der Gegenseite ins Ziel
        entry = {"up": QPointF(other.center().x(), other.bottom()), "down": QPointF(other.center().x(), other.top()),
                 "left": QPointF(other.right(), other.center().y()), "right": QPointF(other.left(), other.center().y())}
        end = entry[direction]
        start = QPointF(spot.x() + dx * HANDLE_R, spot.y() + dy * HANDLE_R)
        side = QPointF(-dy, dx) if direction in ("left", "right") else QPointF(1, 0)
        reach = max(rect.width(), rect.height(), other.width(), other.height()) * 0.9 + 120
        c1 = QPointF(start.x() + dx * 260 + side.x() * reach, start.y() + dy * 260 + side.y() * reach)
        c2 = QPointF(end.x() - dx * 260 + side.x() * reach, end.y() - dy * 260 + side.y() * reach)
        path = QtGui.QPainterPath(start)
        path.cubicTo(c1, c2, end)
        angle = math.atan2(end.y() - c2.y(), end.x() - c2.x())
        for s in (-1, 1):
            a = angle + math.pi + s * 0.45
            path.moveTo(end)
            path.lineTo(end.x() + 22 * math.cos(a), end.y() + 22 * math.sin(a))
        return path

    @staticmethod
    def _circle_edge(center: QPointF, toward: QPointF) -> QPointF:
        import math
        dx, dy = toward.x() - center.x(), toward.y() - center.y()
        length = math.hypot(dx, dy) or 1.0
        return QPointF(center.x() + dx / length * HANDLE_R, center.y() + dy / length * HANDLE_R)

    def _t(self, key: str, **kwargs) -> str:
        lang = ui_language()
        text = tr(key, lang)
        return text.format(**kwargs) if kwargs else text

    def set_mode(self, mode: str):
        self.mode = mode
        self._handle_drag = None
        self._remote_flash = False
        if mode == MODE_REMOTE:
            self.setFocus()

    def remote_press(self, direction: str):
        """Pfeiltaste wie auf der Fernbedienung: zum Ziel springen (festgelegt oder automatisch)."""
        project = self.controller.project if self.controller else None
        menu = project.menu(self.menu_id) if project else None
        if menu is None or self._remote_current is None:
            return
        target = menu_design.dpad_targets(project, menu).get(self._remote_current, {}).get(direction)
        if target and target != self._remote_current:
            self.controller.select_button(menu.id, target)

    def remote_activate(self):
        """Enter: Button kurz im Aktiviert-Zustand zeigen, dann ausführen bzw. beschreiben, was passiert."""
        project = self.controller.project if self.controller else None
        menu = project.menu(self.menu_id) if project else None
        button = menu.button(self._remote_current) if menu and self._remote_current else None
        if button is None:
            return
        self._remote_flash = True
        self.show_menu(project, menu)
        QTimer.singleShot(220, lambda: self._finish_activation(menu.id, button.id))

    def _finish_activation(self, menu_id: str, button_id: str):
        self._remote_flash = False
        project = self.controller.project
        menu = project.menu(menu_id)
        button = menu.button(button_id) if menu else None
        if button is None:
            return
        from core.disc_model import BUTTON_NAV, BUTTON_CHAPTER, BUTTON_AUDIO, BUTTON_SUBTITLE
        from core.disc_rules import resolve_content, language_display_name
        if button.kind == BUTTON_NAV:
            target_menu, target_film = project.menu(button.target), project.film(button.target)
            if target_menu is not None:
                self.controller.select_button(target_menu.id, menu_design.start_button_id(target_menu))
                self.node_requested.emit(target_menu.id)   # erst wechseln (setzt die Meldung zurück), dann melden
                self.remote_message.emit(self._t("remote_to_menu", name=target_menu.name))
                return
            message = self._t("remote_to_film", name=target_film.name) if target_film else self._t("remote_unconnected")
        else:
            film, idx = resolve_content(project, menu, button)
            name = film.name if film else "?"
            if button.kind == BUTTON_CHAPTER:
                message = self._t("remote_chapter", film=name, n=(idx + 1) if idx is not None else "?")
            elif button.kind == BUTTON_AUDIO:
                lang = language_display_name(film.audio_tracks[idx].lang) if film and idx is not None else "?"
                message = self._t("remote_audio", lang=lang)
            elif button.kind == BUTTON_SUBTITLE:
                lang = language_display_name(film.subtitle_tracks[idx].lang) if film and idx is not None else "?"
                message = self._t("remote_subtitle", lang=lang)
            else:
                message = self._t("remote_subtitle_off")
        self.show_menu(project, menu)
        self.remote_message.emit(message)

    def fill_handle_menu(self, qmenu: QMenu, direction: str):
        """Rechtsklick auf einen Griff: automatisch (mit Ziel) oder „bleibt auf diesem Button“."""
        project = self.controller.project
        menu = project.menu(self.menu_id)
        current = self._remote_current
        button = menu.button(current)
        label = lambda b: button_label(project, menu, b) or "(ohne Text)"
        auto = menu_design.auto_dpad_target(project, menu, current, direction)
        auto_name = self._t("studio_dpad_stay") if auto in (None, current) else label(menu.button(auto))
        act = qmenu.addAction(self._t("studio_dpad_auto", target=auto_name))
        act.setCheckable(True)
        act.setChecked(direction not in button.dpad)
        act.triggered.connect(lambda: self.controller.set_button_dpad(menu.id, current, direction, None))
        act = qmenu.addAction(self._t("studio_dpad_stay"))
        act.setCheckable(True)
        act.setChecked(button.dpad.get(direction) == current)
        act.triggered.connect(lambda: self.controller.set_button_dpad(menu.id, current, direction, current))

    def _hit(self, pos: QPointF, cls):
        """Oberstes Element dieser Art an der Stelle (Linien und Rahmen darüber zählen nicht)."""
        return next((i for i in self.scene().items(pos) if isinstance(i, cls)), None)

    def _remote_mouse_press(self, event, pos: QPointF):
        handle = self._hit(pos, _HandleItem)
        if handle is not None:
            self._handle_drag = {"handle": handle, "start": event.position(), "line": None}
            return
        item = self._hit(pos, _ButtonItem)
        if item is not None:
            self._select(item.button_id)

    def _remote_mouse_move(self, event, pos: QPointF):
        drag = self._handle_drag
        delta = event.position() - drag["start"]
        if drag["line"] is None and abs(delta.x()) + abs(delta.y()) < 8:
            return
        if drag["line"] is None:
            drag["line"] = QGraphicsLineItem()
            drag["line"].setPen(QtGui.QPen(C_SELECT, 4, Qt.DashLine))
            drag["line"].setZValue(4)
            self.scene().addItem(drag["line"])
        center = drag["handle"].center
        drag["line"].setLine(center.x(), center.y(), pos.x(), pos.y())

    def _remote_mouse_release(self, pos: QPointF):
        drag, self._handle_drag = self._handle_drag, None
        direction = drag["handle"].direction
        if drag["line"] is None:
            self.remote_press(direction)       # Klick auf den Griff = Taste drücken
            return
        self.scene().removeItem(drag["line"])
        item = self._hit(pos, _ButtonItem)
        if item is not None and self.controller is not None:
            # auf den eigenen Button gezogen = „bleibt stehen“
            self.controller.set_button_dpad(self.menu_id, self._remote_current, direction, item.button_id)

    def _highlight_guide(self, guide_id: Optional[str], cross: Optional[str] = None):
        for gid, item in self.guide_items.items():
            item.set_active(gid in (guide_id, cross, self.selected_guide))

    def _draw_suggestions(self, project, menu, specs):
        """Vorschläge des Menüs als gestrichelte Buttons unter den vorhandenen (wie die Zeilen im Knoten)."""
        from core.menu_templates import suggestions
        found = suggestions(project, menu)
        if not found:
            return
        ref = specs[-1] if specs else None
        w = int(ref.width) if ref else 380
        h = int(ref.height) if ref else 70
        x = int(ref.x) if ref else (CANVAS_W - w) // 2
        y = int(max(s.y + s.height for s in specs)) + 24 if specs else 660
        for suggestion in found:
            if y + h > CANVAS_H - 30:        # unten kein Platz mehr: daneben weiter
                x, y = x + w + 40, int(ref.y) if ref else 660
            if x + w > CANVAS_W:             # auch rechts kein Platz: oben links weiter
                x, y = 40, 40
            self.scene().addItem(_GhostItem(QRectF(x, y, w, h), suggestion))
            y += h + 24

    @staticmethod
    def _draw_background(scene: QGraphicsScene, image_path: Optional[str]):
        if image_path and os.path.exists(image_path):
            pixmap = QtGui.QPixmap(image_path)
            if not pixmap.isNull():
                item = scene.addPixmap(pixmap.scaled(CANVAS_W, CANVAS_H, Qt.IgnoreAspectRatio,
                                                     Qt.SmoothTransformation))
                item.setZValue(-1)
                return
        gradient = QtGui.QLinearGradient(0, 0, 0, CANVAS_H)
        gradient.setColorAt(0.0, QtGui.QColor("#1C1C1F"))
        gradient.setColorAt(1.0, QtGui.QColor("#111113"))
        scene.addRect(QRectF(0, 0, CANVAS_W, CANVAS_H), QtGui.QPen(Qt.NoPen), QtGui.QBrush(gradient)).setZValue(-1)

    # --- Auswahl --------------------------------------------------------------
    def _on_button_selected(self, menu_id: str, button_id: str):
        if self.mode == MODE_REMOTE:
            # Fernbedienung: die Auswahl ist der aktuelle Button – neu zeichnen, wenn er sich geändert hat
            if menu_id == self.menu_id and button_id and button_id != self._remote_current and self.controller:
                menu = self.controller.project.menu(self.menu_id)
                if menu is not None:
                    self.show_menu(self.controller.project, menu)
            return
        # Auswahl von außen (Node-Ansicht, Inspektor): die gemeinsame Auswahl des Controllers (v1.12.1)
        self._adopt_selection(menu_id)

    def _on_selection_changed(self, menu_id: str, _ids: list):
        if self.mode != MODE_REMOTE:
            self._adopt_selection(menu_id)

    def _adopt_selection(self, menu_id: str):
        if self.controller is None or menu_id != self.menu_id:
            self.selection = set()
        else:
            self.selection = set(self.controller.selection_in(self.menu_id)) & set(self.items)
        self._apply_selection()

    def _apply_selection(self):
        for bid, item in self.items.items():
            chosen = bid in self.selection
            if item.chosen != chosen:
                item.chosen = chosen
                item.update()
        self._draw_size_handles()

    # --- Größe ändern (v1.11.1) ------------------------------------------------------
    def _primary_item(self) -> Optional[_ButtonItem]:
        """Button mit den Griffen: der in Inspektor und Node-Ansicht gezeigte, sonst der erste ausgewählte."""
        ordered = self._ordered(self.selection)
        if not ordered:
            return None
        shown = self.controller.selected_button[1] if self.controller else None
        return self.items[shown if shown in ordered else ordered[0]]

    def _draw_size_handles(self, rect: Optional[QRectF] = None):
        for handle in self.size_handles:
            if handle.scene() is self.scene():
                self.scene().removeItem(handle)
        self.size_handles = []
        item = self._primary_item()
        if item is None or self.mode == MODE_REMOTE or self.controller is None:
            return
        if rect is None:
            rect = QRectF(item.pos().x(), item.pos().y(), item.pixmap().width(), item.pixmap().height())
        scale = self.transform().m11() or 1.0
        for code, point in handle_points(rect, HANDLE_SPREAD / scale).items():
            handle = _SizeHandleItem(code, point)
            self.scene().addItem(handle)
            self.size_handles.append(handle)

    def _start_resize(self, handle: _SizeHandleItem, pos: QPointF, event):
        primary = self._primary_item()
        items = [self.items[b] for b in self._ordered(self.selection)]
        self._resize = {"start": pos, "code": handle.code, "items": items, "primary": primary.button_id,
                        "rects": {i.button_id: (int(i.spec.x), int(i.spec.y), int(i.spec.width), int(i.spec.height))
                                  for i in items},
                        "result": None}
        self._hide_markers(i.button_id for i in items)

    def _update_resize(self, pos: QPointF, modifiers):
        r = self._resize
        delta = pos - r["start"]
        result = resized_rects(r["rects"], r["primary"], r["code"], delta.x(), delta.y(),
                               symmetric=bool(modifiers & Qt.AltModifier),
                               keep_ratio=bool(modifiers & Qt.ShiftModifier))
        r["result"] = result
        for item in r["items"]:
            x, y, w, h = result[item.button_id]
            item.setPixmap(button_pixmap(item.spec.text, w, h, item.state_name, item.spec.shape))
            item.setPos(x, y)
        x, y, w, h = result[r["primary"]]
        self._draw_size_handles(QRectF(x, y, w, h))

    def _finish_resize(self):
        r, self._resize = self._resize, None
        self._hide_markers()
        result = r["result"]
        if not result or result == r["rects"] or self.controller is None:
            self._draw_size_handles()
            return
        sizes = {bid: (w, h) for bid, (_x, _y, w, h) in result.items()}
        positions = {bid: (x, y) for bid, (x, y, _w, _h) in result.items()}
        self.controller.resize_menu_items(self.menu_id, sizes, positions)

    def _select(self, button_id: Optional[str]):
        if self.controller is not None:
            self.controller.select_button(self.menu_id if button_id else None, button_id)

    def _select_many(self, button_ids, primary: Optional[str] = None):
        """Mehrere Buttons auswählen (gemeinsame Auswahl im Controller); der erste (in Button-Reihenfolge) bzw.
        primary zeigt sich in Inspektor und Node-Ansicht."""
        ordered = self._ordered(button_ids)
        self.selection = set(ordered)
        if self.controller is not None:
            self.controller.select_buttons(self.menu_id if ordered else None, ordered, primary)
        self._apply_selection()

    def _toggle(self, button_id: str):
        """Umschalt-/Strg-Klick: Button zur Auswahl hinzufügen bzw. herausnehmen."""
        selection = set(self.selection) ^ {button_id}
        self._select_many(selection, button_id if button_id in selection else None)

    def _ordered(self, button_ids) -> List[str]:
        return [bid for bid in self.items if bid in button_ids]

    # --- Verschieben ------------------------------------------------------------
    def _clamped_delta(self, items: List[_ButtonItem], dx: float, dy: float) -> QPointF:
        """Verschiebung so begrenzen, dass alle bewegten Buttons im Bild bleiben."""
        left = min(i.spec.x for i in items)
        top = min(i.spec.y for i in items)
        right = max(i.spec.x + i.spec.width for i in items)
        bottom = max(i.spec.y + i.spec.height for i in items)
        dx = max(-left, min(CANVAS_W - right, dx))
        dy = max(-top, min(CANVAS_H - bottom, dy))
        return QPointF(round(dx), round(dy))

    def _commit(self, items: List[_ButtonItem], delta: QPointF, merge_key=None):
        """Jeder bewegte Button bekommt seine neue Stelle als eigene Position (ein Rückgängig-Schritt)."""
        if self.controller is None or (delta.x() == 0 and delta.y() == 0):
            return
        d = (int(delta.x()), int(delta.y()))
        positions = {i.button_id: (int(i.spec.x) + d[0], int(i.spec.y) + d[1]) for i in items}
        self.controller.move_menu_items(self.menu_id, positions=positions, merge_key=merge_key)

    @staticmethod
    def _mark_outside_safe(items: List[_ButtonItem], delta: Optional[QPointF]):
        """Beim Ziehen: oranger Rand, solange ein Button über die Title-Safe-Zone hinausragt."""
        for item in items:
            if delta is None:
                item.set_outside_safe(False)
                continue
            rect = QRectF(item.spec.x + delta.x(), item.spec.y + delta.y(), item.spec.width, item.spec.height)
            item.set_outside_safe(not TITLE_SAFE.contains(rect))

    # --- Maus ------------------------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        pos = self.mapToScene(event.position().toPoint())
        # Ziel-Plaketten und Linien sind reine Anzeige: der Klick gilt dem, was darunter liegt (v1.15.2, v1.16.4)
        hit = next((i for i in self.scene().items(pos, Qt.IntersectsItemShape, Qt.DescendingOrder, self.transform())
                    if not isinstance(i, (_MarkerItem, _GuideItem))), None)
        self.setFocus()
        if self.mode == MODE_REMOTE:
            self._remote_mouse_press(event, pos)
            return
        if self._color_pick is not None:
            self._finish_color_pick(pos)
            return
        if self._area_pick is not None:
            start = QPointF(max(0.0, min(CANVAS_W, pos.x())), max(0.0, min(CANVAS_H, pos.y())))
            self._area_pick["start"] = start
            self._area_pick["item"] = self.scene().addRect(QRectF(start, start), QtGui.QPen(C_SELECT, 3, Qt.DashLine),
                                                           QtGui.QBrush(QtGui.QColor(251, 191, 36, 30)))
            self._area_pick["item"].setZValue(5)
            return
        if isinstance(hit, _SizeHandleItem):
            self._start_resize(hit, pos, event)
            return
        if isinstance(hit, _GhostItem):
            # erst beim Loslassen: das Anlege-Fenster hat eine eigene Ereignisschleife, und während eines
            # Klicks geöffnet schloss Windows es sofort wieder
            suggestion, screen = hit.suggestion, event.globalPosition().toPoint()
            self._ghost_click = lambda: self.suggestion_activated.emit(suggestion, screen)
            return
        if isinstance(hit, _LineLabelItem):
            local = hit.deviceTransform(self.viewportTransform()).inverted()[0].map(event.position())
            if hit.close_rect.contains(local):
                self.controller.remove_guide(self.menu_id, hit.guide_id)
            else:
                self._edit_line(hit)
            return
        additive = bool(event.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier))
        if isinstance(hit, _ButtonItem):
            if additive:
                self._toggle(hit.button_id)
                return
            if hit.button_id not in self.selection:
                self.selection = {hit.button_id}
            self._select(hit.button_id)
            self._apply_selection()
            items = [self.items[b] for b in self._ordered(self.selection)]
            self._drag = {"start": pos, "items": items, "delta": QPointF(0, 0)}
            self._hide_markers(i.button_id for i in items)
            self.viewport().setCursor(Qt.ClosedHandCursor)
            return
        # freie Fläche: Auswahl aufheben und einen Auswahlrahmen beginnen
        self.selected_guide = None
        self._highlight_guide(None)
        if not additive:
            self._select(None)
        self._band = {"start": pos, "item": None, "additive": additive, "before": set(self.selection)}

    def mouseMoveEvent(self, event):
        pos = self.mapToScene(event.position().toPoint())
        if self._area_pick is not None and self._area_pick.get("item") is not None:
            self._area_pick["item"].setRect(self._area_rect(pos))
            return
        if self._handle_drag is not None:
            self._remote_mouse_move(event, pos)
            return
        if self._resize is not None:
            self._update_resize(pos, event.modifiers())
            return
        if self._band is not None:
            self._update_band(pos)
            return
        if self._line_drag is not None:
            self.update_line_drag(event.globalPosition().toPoint(), event.modifiers())
            return
        if self._drag is None:
            return super().mouseMoveEvent(event)
        drag = self._drag
        items = drag["items"]
        raw = pos - drag["start"]
        if abs(raw.x()) + abs(raw.y()) > 4:
            drag["dragged"] = True        # echtes Ziehen (kein bloßer Klick) – auch wenn es wieder auf der Stelle einrastet
        delta = self._clamped_delta(items, raw.x(), raw.y())
        if self._free(event.modifiers()):
            # Alt gedrückt oder „Einrasten“ aus: frei ziehen, ohne jedes Einrasten (v1.15.3, v1.17.3)
            self._show_spacing([])
            self._highlight_guide(None)
        elif self.controller is not None:
            # Linien sind reine Einrast-Hilfen (v1.16.4): die Mitte rastet an waagerechten bzw. senkrechten Linien
            # ein (an einer Kreuzung an beiden), in den übrigen Richtungen die Abstands-Hilfe; nichts bleibt geheftet
            delta, snapped, lit = self._snap_to_lines(items, delta)
            delta = self._spacing_free(items, delta, axes=[a for a in ("y", "x") if a not in snapped])
            self._highlight_guide(*lit)
        drag["delta"] = delta
        for item in items:
            item.setPos(item.spec.x + delta.x(), item.spec.y + delta.y())
        self._mark_outside_safe(items, delta)

    def _update_band(self, pos: QPointF):
        band = self._band
        rect = QRectF(band["start"], pos).normalized()
        if band["item"] is None:
            if rect.width() + rect.height() < 12:
                return
            band["item"] = self.scene().addRect(rect, QtGui.QPen(C_SELECT, 2, Qt.DashLine),
                                                QtGui.QBrush(QtGui.QColor(251, 191, 36, 25)))
            band["item"].setZValue(4)
        band["item"].setRect(rect)
        hits = {bid for bid, it in self.items.items() if it.sceneBoundingRect().intersects(rect)}
        self.selection = (band["before"] | hits) if band["additive"] else hits
        self._apply_selection()

    # --- Abstands-Hilfe ------------------------------------------------------------------
    def _moving_rect(self, items: List[_ButtonItem], delta: QPointF):
        left = min(i.spec.x for i in items) + delta.x()
        top = min(i.spec.y for i in items) + delta.y()
        right = max(i.spec.x + i.spec.width for i in items) + delta.x()
        bottom = max(i.spec.y + i.spec.height for i in items) + delta.y()
        return (left, top, right - left, bottom - top)

    def _other_rects(self, items: List[_ButtonItem]):
        moving = {id(i) for i in items}
        return [(i.spec.x, i.spec.y, i.spec.width, i.spec.height) for i in self.items.values() if id(i) not in moving]

    def _free(self, modifiers) -> bool:
        """Ohne jedes Einrasten: Alt gedrückt oder Häkchen „Einrasten“ entfernt (v1.17.3)."""
        return bool(modifiers & Qt.AltModifier) or not self.snap_enabled

    def _snap_to_lines(self, items: List[_ButtonItem], delta: QPointF):
        """
        Mitte des gezogenen Buttons (bzw. der Auswahl) an der nächsten waagerechten und der nächsten senkrechten
        Linie einrasten (v1.16.4). Ergebnis: (Verschiebung, eingerastete Richtungen, (Linie y, Linie x)).
        """
        x, y, w, h = self._moving_rect(items, delta)
        cx, cy = x + w / 2, y + h / 2
        best = {"x": None, "y": None}          # Richtung → (Abstand, Stelle, Linien-ID)
        for g in menu_guides.guides(self.controller.project, self.menu_id):
            (x1, y1), (x2, y2) = menu_guides.endpoints(g)
            if abs(y1 - y2) < 1e-6:
                axis, value, dist = "y", y1, abs(cy - y1)
            elif abs(x1 - x2) < 1e-6:
                axis, value, dist = "x", x1, abs(cx - x1)
            else:
                continue                          # schräge Linien älterer Projekte: kein Einrasten
            if dist <= menu_guides.SNAP_DISTANCE and (best[axis] is None or dist < best[axis][0]):
                best[axis] = (dist, value, g.id)
        dx = best["x"][1] - cx if best["x"] else 0.0
        dy = best["y"][1] - cy if best["y"] else 0.0
        if dx or dy:
            delta = self._clamped_delta(items, delta.x() + dx, delta.y() + dy)
        snapped = [a for a in ("x", "y") if best[a]]
        return delta, snapped, (best["y"][2] if best["y"] else None, best["x"][2] if best["x"] else None)

    def _spacing_free(self, items: List[_ButtonItem], delta: QPointF, axes=("y", "x")) -> QPointF:
        """Frei gezogen: senkrecht und waagerecht unabhängig auf vorhandene Abstände oder bündig zu anderen
        Buttons einrasten (pro Richtung die nähere der beiden Hilfen); axes: nur diese Richtungen."""
        others = self._other_rects(items)
        markers = []
        for axis in axes:
            rect = self._moving_rect(items, delta)
            hits = [h for h in (menu_spacing.snap_spacing(rect, others, axis),
                                menu_spacing.snap_alignment(rect, others, axis),
                                menu_spacing.snap_center(rect, axis)) if h is not None]
            hit = min(hits, key=lambda h: abs(h[0])) if hits else None
            if hit is not None:
                shift, segs = hit
                delta = self._clamped_delta(items, delta.x() + (shift if axis == "x" else 0),
                                            delta.y() + (shift if axis == "y" else 0))
                markers += segs
        self._show_spacing(markers)
        return delta

    def _show_spacing(self, segments):
        """Markierungen gleicher Abstände (nur während des Ziehens)."""
        for item in getattr(self, "spacing_items", []):
            if item.scene() is self.scene():
                self.scene().removeItem(item)
        self.spacing_items = []
        pen = QtGui.QPen(C_SPACING, 6)   # kräftig genug für die verkleinerte Vorschau
        for x1, y1, x2, y2 in segments:
            line = self.scene().addLine(x1, y1, x2, y2, pen)
            vertical = abs(x2 - x1) < abs(y2 - y1)
            for (px, py) in ((x1, y1), (x2, y2)):   # Endstriche
                cap = self.scene().addLine(px - 18, py, px + 18, py, pen) if vertical else \
                    self.scene().addLine(px, py - 18, px, py + 18, pen)
                self.spacing_items.append(cap)
            self.spacing_items.append(line)
        for item in self.spacing_items:
            item.setZValue(2.4)
            item.setAcceptedMouseButtons(Qt.NoButton)

    def mouseReleaseEvent(self, event):
        if self._area_pick is not None and self._area_pick.get("item") is not None:
            rect = self._area_rect(self.mapToScene(event.position().toPoint()))
            self.cancel_area_pick()
            if rect.width() >= 40 and rect.height() >= 8 and self.menu_id:
                area = tuple(int(round(v)) for v in (rect.x(), rect.y(), rect.width(), rect.height()))
                menu_id = self.menu_id
                # das Fenster erst nach dem Loslassen öffnen (eigene Ereignisschleife, vgl. v1.12.2)
                QTimer.singleShot(0, lambda: self.generator_area.emit(menu_id, area))
            return
        if self._ghost_click is not None:
            action, self._ghost_click = self._ghost_click, None
            QTimer.singleShot(0, action)
            return
        if self._handle_drag is not None:
            self._remote_mouse_release(self.mapToScene(event.position().toPoint()))
            return
        if self._resize is not None:
            self._finish_resize()
            return
        if self._band is not None:
            band, self._band = self._band, None
            if band["item"] is not None:
                self.scene().removeItem(band["item"])
                self._select_many(self.selection)
            return
        if self._line_drag is not None:
            self.finish_line_drag(event.globalPosition().toPoint())
            return
        if self._drag is None:
            return super().mouseReleaseEvent(event)
        drag, self._drag = self._drag, None
        self.viewport().unsetCursor()
        self._hide_markers()
        self._show_spacing([])
        self._mark_outside_safe(drag["items"], None)
        self._highlight_guide(None)
        self._commit(drag["items"], drag["delta"])

    def mouseDoubleClickEvent(self, event):
        # Buttons sind immer einzeln verschiebbar (v1.9.10) – ein Doppelklick wirkt wie ein Klick
        self.mousePressEvent(event)

    # --- Eigene Linien: Lineal, verschieben, Zahl (v1.16.1) ------------------------------
    def _set_rulers_visible(self, visible: bool):
        self.setViewportMargins(RULER if visible else 0, RULER if visible else 0, 0, 0)
        self.ruler_top.setVisible(visible)
        self.ruler_left.setVisible(visible)
        self._place_rulers()

    def _place_rulers(self):
        """Lineale direkt am Bild (v1.16.2): so lang wie das Bild, im freien Rand daneben, sonst am Fensterrand."""
        f = self.frameWidth()
        vp = self.viewport().geometry()
        image = self.mapFromScene(self.scene().sceneRect()).boundingRect()
        left, top = vp.left() + image.left(), vp.top() + image.top()
        width = min(image.width(), vp.right() - left + 1)
        height = min(image.height(), vp.bottom() - top + 1)
        self.ruler_top.setGeometry(left, max(f, top - RULER), max(0, width), RULER)
        self.ruler_left.setGeometry(max(f, left - RULER), top, RULER, max(0, height))

    def _update_rulers(self):
        self.ruler_top.update()
        self.ruler_left.update()

    def _line_value(self, global_pos, horizontal: bool):
        """(Stelle im 1920×1080 Raum, liegt sie im Bild?) für eine waagerechte bzw. senkrechte Linie aus dem Lineal
        – die Maus darf dabei auch über dem Lineal selbst sein."""
        scene = self.mapToScene(self.viewport().mapFromGlobal(global_pos))
        value = scene.y() if horizontal else scene.x()
        size = CANVAS_H if horizontal else CANVAS_W
        return max(0.0, min(float(size), value)), 0 <= value <= size

    def preview_ruler_line(self, horizontal: bool, global_pos, modifiers=Qt.NoModifier):
        """Maus über dem Lineal: blasse Linie mit Abstand, wo ein Klick sie setzen würde."""
        if self._line_drag is not None or self.controller is None:
            return
        self.clear_ruler_preview()
        value, inside = self._line_value(global_pos, horizontal)
        if not inside:
            return
        if not self._free(modifiers):
            value = self._snap_line(value, horizontal)
        item = _GuideItem("", QPointF(0, 0), QPointF(0, 0), False, fixed=True)
        item.setLine(0, value, CANVAS_W, value) if horizontal else item.setLine(value, 0, value, CANVAS_H)
        item.setOpacity(0.55)
        item.setAcceptedMouseButtons(Qt.NoButton)
        self.scene().addItem(item)
        edge, distance = self._edge_and_distance(value, horizontal)
        from core.disc_model import FixedGuide
        label = self._add_line_label(FixedGuide(id="", edge=edge, distance=distance))
        label.setOpacity(0.75)
        label.setAcceptedMouseButtons(Qt.NoButton)
        self._ruler_preview = (item, label)

    def clear_ruler_preview(self):
        preview, self._ruler_preview = self._ruler_preview, None
        for item in preview or ():
            if item.scene() is self.scene():
                self.scene().removeItem(item)

    def _snap_line(self, value: float, horizontal: bool) -> float:
        """Einrasten an Bildmitte, Title Safe, Vierteln, Goldenem Schnitt und an den Mitten der Buttons."""
        size = CANVAS_H if horizontal else CANVAS_W
        targets = [ratio * size for ratio, _name in menu_guides.ANCHOR_RATIOS]
        targets += [(i.spec.y + i.spec.height / 2) if horizontal else (i.spec.x + i.spec.width / 2)
                    for i in self.items.values()]
        tolerance = LINE_SNAP_PX / (self.transform().m11() or 1.0)
        best = min(targets, key=lambda t: abs(t - value), default=None)
        return best if best is not None and abs(best - value) <= tolerance else value

    @staticmethod
    def _edge_and_distance(value: float, horizontal: bool):
        """Von der näheren Kante gemessen: (Kante, Abstand in ganzen Bildpunkten)."""
        size = CANVAS_H if horizontal else CANVAS_W
        value = int(round(value))
        if value <= size / 2:
            return ("top" if horizontal else "left"), value
        return ("bottom" if horizontal else "right"), size - value

    def start_line_from_ruler(self, horizontal: bool, global_pos, modifiers=Qt.NoModifier):
        """Klick ins Lineal: neue Linie genau dort; mit gedrückter Maus verschiebbar, bis sie losgelassen wird."""
        if self.controller is None or self.menu_id is None:
            return
        self._cancel_line_editor()
        self.clear_ruler_preview()
        item = _GuideItem("", QPointF(0, 0), QPointF(0, 0), True, fixed=True)
        self.scene().addItem(item)
        self._line_drag = {"horizontal": horizontal, "item": item, "label": None, "value": 0.0, "inside": False}
        self.update_line_drag(global_pos, modifiers)

    def update_line_drag(self, global_pos, modifiers):
        drag = self._line_drag
        if drag is None:
            return
        value, inside = self._line_value(global_pos, drag["horizontal"])
        if not self._free(modifiers):
            value = self._snap_line(value, drag["horizontal"])
        drag["value"], drag["inside"] = value, inside
        item = drag["item"]
        if drag["horizontal"]:
            item.setLine(0, value, CANVAS_W, value)
        else:
            item.setLine(value, 0, value, CANVAS_H)
        item.setVisible(inside)
        if drag["label"] is not None:
            self.scene().removeItem(drag["label"])
        edge, distance = self._edge_and_distance(value, drag["horizontal"])
        from core.disc_model import FixedGuide
        drag["label"] = self._add_line_label(FixedGuide(id="", edge=edge, distance=distance)) if inside else None

    def finish_line_drag(self, global_pos):
        """Loslassen: neue Linie anlegen, wenn sie im Bild liegt (gesetzte Linien ändert nur die Zahl, v1.16.4)."""
        drag, self._line_drag = self._line_drag, None
        if drag is None or self.controller is None:
            return
        if drag["label"] is not None and drag["label"].scene() is self.scene():
            self.scene().removeItem(drag["label"])
        self.scene().removeItem(drag["item"])
        if drag["inside"]:
            self.controller.add_fixed_guide(*self._edge_and_distance(drag["value"], drag["horizontal"]))
        self._update_rulers()

    def _edit_line(self, label: "_LineLabelItem"):
        """Klick auf das Schild: Zahl direkt dort eintippen (Enter übernimmt, Esc bricht ab)."""
        fixed = menu_guides.fixed_guide(self.controller.project, label.guide_id) if self.controller else None
        if fixed is None:
            return
        self._cancel_line_editor()
        rect = label.deviceTransform(self.viewportTransform()).mapRect(label.text_rect).toRect()
        editor = _LineEditor(self.viewport())
        editor.setValidator(QtGui.QIntValidator(0, CANVAS_H if menu_guides.is_horizontal(fixed.edge) else CANVAS_W,
                                                editor))
        editor.setText(str(fixed.distance))
        editor.setAlignment(Qt.AlignCenter)
        editor.setStyleSheet("QLineEdit { background-color: #18181B; color: #E9D5FF; border: 2px solid #C084FC;"
                             " border-radius: 4px; font-weight: bold; padding: 0px; }")
        editor.setGeometry(rect.adjusted(0, -2, 0, 2))
        guide_id = fixed.id
        editor.editingFinished.connect(lambda: self._apply_line_editor(guide_id))
        editor.cancelled.connect(self._cancel_line_editor)
        editor.show()
        editor.setFocus()
        editor.selectAll()
        self._line_editor = editor

    def _apply_line_editor(self, guide_id: str):
        editor, self._line_editor = self._line_editor, None
        if editor is None:
            return
        text = editor.text().strip()
        editor.hide()
        editor.deleteLater()
        if text.isdigit() and self.controller is not None:
            self.controller.set_fixed_guide(guide_id, distance=int(text))
        self.setFocus()

    def _cancel_line_editor(self):
        editor, self._line_editor = self._line_editor, None
        if editor is not None:
            editor.hide()
            editor.deleteLater()
            self.setFocus()

    def contextMenuEvent(self, event):
        pos = self.mapToScene(event.pos())
        hit = self.scene().itemAt(pos, self.transform())
        if self.mode == MODE_REMOTE:
            handle = self._hit(pos, _HandleItem)
            if handle is not None and self.controller is not None:
                menu = QMenu(self)
                self.fill_handle_menu(menu, handle.direction)
                menu.exec(event.globalPos())
            return
        if isinstance(hit, _GhostItem):
            self.suggestion_menu.emit(hit.suggestion, event.globalPos())
            return
        button = self._hit(pos, _ButtonItem)
        if button is not None and self.controller is not None:
            if button.button_id not in self.selection:
                self._select_many({button.button_id})
            menu = QMenu(self)
            self.fill_button_menu(menu)
            menu.exec(event.globalPos())
            return
        if self.controller is None:
            return super().contextMenuEvent(event)
        guide = self._hit(pos, _GuideItem)
        if guide is None:
            return super().contextMenuEvent(event)
        guide_id = guide.guide_id
        menu = QMenu(self)
        lang = ui_language()
        if guide.fixed:
            act = menu.addAction(tr("studio_line_delete", lang))
        else:
            act = menu.addAction(tr("studio_guide_delete", lang))
        act.triggered.connect(lambda: self.controller.remove_guide(self.menu_id, guide_id))
        menu.exec(event.globalPos())

    def fill_button_menu(self, qmenu: QMenu):
        """Rechtsklick auf Buttons (Gestalten): duplizieren (v1.14), eigene Größe der Auswahl verwerfen."""
        selected = self._ordered(self.selection)
        menu_id = self.menu_id
        menu = self.controller.project.menu(menu_id)
        act = qmenu.addAction(self._t("studio_duplicate"))
        act.triggered.connect(lambda: self.controller.duplicate_selection(menu_id))
        qmenu.addSeparator()
        text = self._t("studio_reset_selection", n=len(selected)) if len(selected) > 1 else self._t("studio_reset_button")
        act = qmenu.addAction(text)
        act.setEnabled(menu is not None and any(b.size is not None for b in menu.buttons if b.id in selected))
        act.triggered.connect(lambda: self.controller.clear_button_sizes(menu_id, selected))

    # --- Tastatur ------------------------------------------------------------------------
    def keyPressEvent(self, event):
        if self.mode == MODE_REMOTE:
            keys = {Qt.Key_Up: "up", Qt.Key_Down: "down", Qt.Key_Left: "left", Qt.Key_Right: "right"}
            if event.key() in keys:
                self.remote_press(keys[event.key()])
            elif event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
                self.remote_activate()
            else:
                super().keyPressEvent(event)
            return
        ctrl = bool(event.modifiers() & Qt.ControlModifier)
        if ctrl and event.key() == Qt.Key_D and self.controller and self.menu_id:
            self.controller.duplicate_selection(self.menu_id)        # v1.14
            return
        if ctrl and event.key() in (Qt.Key_C, Qt.Key_V) and self.controller:
            self.controller.tool_hint.emit(self._t("studio_dup_copy_hint"))
            return
        steps = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0), Qt.Key_Up: (0, -1), Qt.Key_Down: (0, 1)}
        items = [self.items[b] for b in self._ordered(self.selection)]
        single = items[0] if len(items) == 1 else None
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace) and items and self.controller:
            self.controller.remove_buttons(self.menu_id, [i.button_id for i in items])   # v1.12.1
            return
        if event.key() in steps and items:
            step = 10 if event.modifiers() & Qt.ShiftModifier else 1
            dx, dy = steps[event.key()]
            delta = self._clamped_delta(items, dx * step, dy * step)
            self._commit(items, delta, merge_key=("nudge", self.menu_id, tuple(sorted(self.selection))))
            return
        if event.key() == Qt.Key_Escape and self._area_pick is not None:
            self.cancel_area_pick()
            return
        if event.key() == Qt.Key_Escape and self._color_pick is not None:
            self.cancel_color_pick()
            return
        if event.key() == Qt.Key_Escape:
            self._select(None)
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fitInView(self.scene().sceneRect(), Qt.KeepAspectRatio)
        self._place_rulers()
        self._update_rulers()


class _InfoCard(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(6)
        self.title = QLabel()
        self.title.setStyleSheet("font-size: 26px; font-weight: 800; color: #FAFAFA;")
        self.subtitle = QLabel()
        self.subtitle.setStyleSheet("font-size: 14px; font-weight: bold; color: #4ADE80;")
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.RichText)
        self.body.setStyleSheet("font-size: 13px; color: #D4D4D8;")
        self.body.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)
        layout.addSpacing(10)
        layout.addWidget(self.body, stretch=1)

    def set_content(self, title: str, subtitle: str, lines: list, accent: str = "#4ADE80"):
        self.title.setText(title)
        self.subtitle.setText(subtitle)
        self.subtitle.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {accent};")
        self.body.setText("<br>".join(lines))


class ViewerPanel(QWidget):
    def __init__(self, controller: GraphController, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.current_id: Optional[str] = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        # Zustand der Buttons (nur bei Menüs sichtbar)
        self.state_bar = QWidget()
        state_layout = QHBoxLayout(self.state_bar)
        state_layout.setContentsMargins(0, 0, 0, 4)
        # Modus (v1.9.9): Gestalten | Fernbedienung
        self.mode_group = QButtonGroup(self)
        self.mode_buttons = {}
        for i, mode in enumerate((MODE_DESIGN, MODE_REMOTE)):
            btn = QPushButton()
            btn.setCheckable(True)
            btn.setChecked(mode == MODE_DESIGN)
            btn.setStyleSheet(MODE_BUTTON_QSS.format(left="8px" if i == 0 else "0px", right="0px" if i == 0 else "8px"))
            btn.clicked.connect(lambda _c=False, m=mode: self.set_mode(m))
            self.mode_group.addButton(btn)
            self.mode_buttons[mode] = btn
            state_layout.addWidget(btn)
        state_layout.addSpacing(18)
        self.lbl_state = QLabel()
        self.lbl_state.setStyleSheet("color: #A1A1AA;")
        self.combo_state = QComboBox()
        for state in BUTTON_STATES:
            self.combo_state.addItem("", state)
        self.combo_state.setSizeAdjustPolicy(QComboBox.AdjustToContents)   # Texte kommen erst mit der Sprache
        self.combo_state.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)   # bei enger Leiste nicht abschneiden
        self.combo_state.currentIndexChanged.connect(self._on_state_changed)
        state_layout.addWidget(self.lbl_state)
        state_layout.addWidget(self.combo_state)
        self.chk_guides = QCheckBox()
        self.chk_guides.setChecked(True)
        self.chk_guides.toggled.connect(self._on_guides_toggled)
        state_layout.addSpacing(16)
        state_layout.addWidget(self.chk_guides)
        self.chk_snap = QCheckBox()            # v1.17.3: bei jedem Start an; aus = frei ziehen wie mit Alt
        self.chk_snap.setChecked(True)
        self.chk_snap.toggled.connect(self._on_snap_toggled)
        state_layout.addSpacing(10)
        state_layout.addWidget(self.chk_snap)
        self.chk_markers = QCheckBox()
        self.chk_markers.setChecked(True)
        self.chk_markers.toggled.connect(self._on_markers_toggled)
        state_layout.addSpacing(10)
        state_layout.addWidget(self.chk_markers)
        state_layout.addStretch(1)
        # Palette (v1.12.2): Navigation, Kapitel, Ton, Untertitel
        self.palette_buttons = {}
        for kind in PALETTE_KINDS:
            btn = _PaletteButton(kind, self._palette_click)
            state_layout.addWidget(btn)
            self.palette_buttons[kind] = btn
        self.btn_generator = QPushButton()
        self.btn_generator.clicked.connect(lambda: self.menu_preview.start_area_pick())
        state_layout.addWidget(self.btn_generator)
        layout.addWidget(self.state_bar)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)
        self.caption = hint_label()
        layout.addWidget(self.caption)

        self.empty = QLabel()
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet("color: #52525B; font-size: 14px;")
        self.card = _InfoCard()
        self.menu_preview = MenuPreview(controller)
        self.menu_preview.remote_message.connect(self._on_remote_message)
        self._remote_message = ""
        self._tool_hint = ""                         # Strg+D-Hinweis im Modus Gestalten (v1.14)
        controller.tool_hint.connect(self._on_tool_hint)
        for w in (self.empty, self.card, self.menu_preview):
            self.stack.addWidget(w)
        controller.changed.connect(self.refresh)
        self.show_node(None)

    @property
    def mode(self) -> str:
        return self.menu_preview.mode

    def set_mode(self, mode: str):
        """Gestalten (Buttons anordnen) oder Fernbedienung (bedienen wie am Fernseher, Pfeiltasten festlegen)."""
        self.mode_buttons[mode].setChecked(True)
        self._remote_message = ""
        self.menu_preview.set_mode(mode)
        self.refresh()

    def _on_remote_message(self, text: str):
        self._remote_message = text
        self._update_caption()

    def _on_tool_hint(self, text: str):
        self._tool_hint = text
        if self.current_id is not None and self.controller.project.menu(self.current_id) is not None:
            self._update_caption()

    def _update_caption(self):
        """Unter dem Viewer: im Modus Fernbedienung eine kurze Zeile, sonst nur Hinweise zur laufenden Aktion
        (v1.17.4: die lange Bedienungsanleitung entfällt; Tastenkürzel im Tooltip von „Gestalten“)."""
        if self.mode == MODE_REMOTE:
            hint = self.t("remote_hint")
            self.caption.setText(f"<b style='color:#E4E4E7'>{self._remote_message}</b><br>{hint}"
                                 if self._remote_message else hint)
        else:
            self.caption.setText(f"<b style='color:#FB923C'>{self._tool_hint}</b>" if self._tool_hint else "")
        self.caption.setVisible(bool(self.caption.text()))

    def t(self, key: str, **kwargs) -> str:
        text = tr(key, ui_language())
        return text.format(**kwargs) if kwargs else text

    def _on_state_changed(self, _index: int):
        self.menu_preview.state = self.combo_state.currentData()
        self.refresh()

    def _on_markers_toggled(self, on: bool):
        self.menu_preview.show_markers = on
        self.refresh()

    def _palette_click(self, kind: str):
        self.menu_preview.add_from_palette(kind)

    def _on_guides_toggled(self, on: bool):
        self.menu_preview.show_guides = on
        self.refresh()

    def _on_snap_toggled(self, on: bool):
        self.menu_preview.snap_enabled = on

    def show_node(self, node_id: Optional[str]):
        if node_id != self.current_id:
            self._remote_message = ""
        self.current_id = node_id
        project = self.controller.project
        film = project.film(node_id)
        menu = project.menu(node_id)
        self.caption.setText("")
        self.state_bar.setVisible(menu is not None)
        if menu is not None:
            design = self.mode == MODE_DESIGN
            for mode, btn in self.mode_buttons.items():
                btn.setText(self.t(f"studio_mode_{mode}"))
                btn.setToolTip(self.t(f"studio_mode_{mode}_tip"))
            for w in (self.lbl_state, self.combo_state, self.chk_guides, self.chk_snap, self.chk_markers,
                      *self.palette_buttons.values(), self.btn_generator):
                w.setVisible(design)
            self.btn_generator.setText(self.t("gen_button"))
            self.btn_generator.setToolTip(self.t("gen_button_tip"))
            self.chk_markers.setText(self.t("studio_markers"))
            self.chk_markers.setToolTip(self.t("studio_markers_tip"))
            for kind, btn in self.palette_buttons.items():
                btn.setText("＋ " + self.t(f"studio_kind_{kind}"))
                btn.setToolTip(self.t("studio_palette_tip"))
            self.lbl_state.setText(self.t("studio_state"))
            self.chk_guides.setText(self.t("studio_guides"))
            self.chk_guides.setToolTip(self.t("studio_guides_tip"))
            self.chk_snap.setText(self.t("studio_snap"))
            self.chk_snap.setToolTip(self.t("studio_snap_tip"))
            for i, state in enumerate(BUTTON_STATES):
                self.combo_state.setItemText(i, self.t(f"studio_state_{state}"))
            self.menu_preview.show_menu(project, menu)
            self.stack.setCurrentWidget(self.menu_preview)
            self._update_caption()
        elif film is not None:
            self._show_film(film)
        elif node_id == START_NODE_ID:
            self._show_start()
        else:
            self.current_id = None
            self.empty.setText(self.t("studio_viewer_empty"))
            self.stack.setCurrentWidget(self.empty)

    def refresh(self):
        self.show_node(self.current_id)

    def _show_film(self, film):
        if film.video_base:
            details = film.video_details or {}
            w, h = details.get("width", 0), details.get("height", 0)
            size = f"{w}×{h} · " if w and h else ""
            subtitle = f"{'3D (MVC)' if film.is_3d else '2D'} · {size}{film.fps:.3f} fps"
            accent = "#4ADE80"
        else:
            subtitle = self.t("studio_viewer_no_video")
            accent = "#FDE047"
        lines = []
        if film.video_base:
            lines.append(f"🎞 {os.path.basename(film.video_base)}")
        if film.video_mvc:
            lines.append(f"👓 {os.path.basename(film.video_mvc)}")
        lines.append("")
        lines.append(self.t("studio_viewer_tracks", audio=len(film.audio_tracks), subs=len(film.subtitle_tracks),
                            chapters=len(film.chapters)))
        if film.compliance_warnings:
            lines.append(f"<span style='color:#FDE047'>⚠ {self.t('studio_viewer_warnings', n=len(film.compliance_warnings))}</span>")
        self.card.set_content(film.name, subtitle, lines, accent)
        self.stack.setCurrentWidget(self.card)

    def _show_start(self):
        project = self.controller.project
        target = project.node(project.start_target)
        lines = [
            self.t("studio_viewer_counts", films=len(project.films), menus=len(project.menus)),
            self.t("studio_start_target", name=target.name) if target else self.t("studio_start_none"),
        ]
        self.card.set_content(project.settings.project_name, self.t("studio_viewer_disc"), lines, "#FBBF24")
        self.stack.setCurrentWidget(self.card)
