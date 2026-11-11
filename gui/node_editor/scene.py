# gui/node_editor/scene.py
"""
Grafische Darstellung des Disc-Graphen (QGraphicsScene):
- NodeItem: Start-, Film- und Menü-Knoten (Eingang links, Ausgänge rechts)
- PortItem: Ausgangspunkt, von dem aus Verbindungen gezogen werden
- WireItem: Verbindung als Bezier-Kurve (Rücksprünge gestrichelt unterhalb)
- MarkerItem: Sprungmarke „↩ Ziel“ statt einer Rücksprung-Linie

Die Szene liest ausschließlich aus dem GraphController und ändert das Modell nur über ihn.
"""

from typing import Dict, List, Optional

from PySide6 import QtCore, QtGui
from PySide6.QtCore import Qt, QPointF, QRectF, QTimer, Signal
from PySide6.QtWidgets import (
    QGraphicsItem, QGraphicsScene, QGraphicsPathItem, QGraphicsEllipseItem, QMenu, QInputDialog,
)

from core.disc_labels import disc_label
from core.translations import tr, ui_language
from core.disc_model import START_NODE_ID
from core.disc_edit import NODE_FILM, NODE_MENU, background_field
from core.disc_rules import Source, SOURCE_BUTTON, SOURCE_FILM_END, SOURCE_NEW_BUTTON, connection_target
from gui.node_editor.controller import GraphController
from gui.node_editor.rows import (
    NodeRow, ROW_OUTPUT, ROW_CONTENT, ROW_ADD, ROW_SUGGEST, SUGGESTION_TAG,
    start_rows, film_rows, menu_rows, film_subtitle, menu_subtitle, target_display_name, content_films,
)

# --- Maße -----------------------------------------------------------------
NODE_W = 250
START_W = 170
HEADER_H = 46
ROW_H = 26
PORT_R = 6
CORNER = 8
FRAME_TITLE_H = 30      # Titelleiste eines Rahmens (= core.node_frames.TITLE_H)
FRAME_GRIP = 8          # Breite des Griffbands an den Kanten eines Rahmens

# --- Farben (Dark Cinema) ---------------------------------------------------
C_BG = QtGui.QColor("#111113")
C_GRID = QtGui.QColor("#222226")
C_NODE = QtGui.QColor("#202024")
C_HEADER = QtGui.QColor("#27272A")
C_BORDER = QtGui.QColor("#3F3F46")
C_TEXT = QtGui.QColor("#FAFAFA")
C_DIM = QtGui.QColor("#A1A1AA")
C_MUTED = QtGui.QColor("#71717A")
C_GOLD = QtGui.QColor("#FBBF24")
C_MENU = QtGui.QColor("#38BDF8")
C_WIRE = QtGui.QColor("#A1A1AA")
C_OK = QtGui.QColor("#4ADE80")
C_LOCKED = QtGui.QColor("#FDE047")
C_BAD = QtGui.QColor("#EF4444")

HL_NONE, HL_ALLOWED, HL_LOCKED, HL_INVALID, HL_TARGET = range(5)

# Namen der Rahmenfarben (core.node_frames.FRAME_COLORS, gleiche Reihenfolge)
FRAME_COLOR_KEYS = ["slate", "green", "violet", "orange", "pink", "teal", "yellow", "red"]   # graph_color_…

# Vorschläge beim Loslassen einer Verbindung im Leeren: (Knotenart, Eintrag, Name des neuen Knotens)
NEW_NODE_CHOICES = [
    (NODE_FILM, "graph_new_film", "Neuer Film"),     # Eintrag: Schlüssel; Name: in der Sprache der Disc
    (NODE_MENU, "graph_new_menu", "Neues Menü"),
]
CHOICE_DISCONNECT = "disconnect"


def _font(size: int, bold: bool = False, italic: bool = False) -> QtGui.QFont:
    """Schrift der Knoten: Größe in Punkt wie bisher, gezeichnet in Pixeln (v1.30.1) – auf dem Mac sonst ein Viertel
    kleiner als unter Windows; Systemschrift statt fest „Segoe UI“ (gibt es auf dem Mac nicht)."""
    from gui.theme import ui_font
    return ui_font(size, bold=bold, italic=italic)


class PortItem(QGraphicsEllipseItem):
    """Ausgangspunkt einer Verbindung (rechts an Start-, Film- und Menü-Knoten)."""

    def __init__(self, source: Source, parent: "NodeItem"):
        super().__init__(-PORT_R, -PORT_R, 2 * PORT_R, 2 * PORT_R, parent)
        self.source = source
        self._hover = False
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CrossCursor)
        self.setZValue(2)
        self._apply_style()

    @property
    def is_add(self) -> bool:
        return self.source.kind == SOURCE_NEW_BUTTON

    def _apply_style(self):
        color = C_GOLD if self._hover else self.parentItem().accent
        if self.is_add:
            # „＋ Button“: hohler Ausgang, der erst beim Verbinden zu einem Button wird
            self.setPen(QtGui.QPen(color if self._hover else C_MUTED, 1.6))
            self.setBrush(QtGui.QBrush(C_NODE))
        else:
            self.setPen(QtGui.QPen(C_BG, 2))
            self.setBrush(QtGui.QBrush(color))

    def hoverEnterEvent(self, event):
        self._hover = True
        self._apply_style()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._hover = False
        self._apply_style()
        super().hoverLeaveEvent(event)


class NodeItem(QGraphicsItem):
    """Ein Knoten im Graph. Zeichnet Kopfzeile und Zeilen; Ausgänge sind PortItems."""

    def __init__(self, node_id: str, kind: str, title: str, subtitle: str, rows: List[NodeRow],
                 accent: QtGui.QColor, is_main: bool = False, subtitle_color: Optional[QtGui.QColor] = None):
        super().__init__()
        self.node_id = node_id
        self.kind = kind            # "start" | "film" | "menu"
        self.title = title
        self.subtitle = subtitle
        self.rows = rows
        self.accent = accent
        self.is_main = is_main
        self.subtitle_color = subtitle_color or C_DIM
        self.highlight = HL_NONE
        self.highlight_text = ""
        self.selected_button_ids: set = set()   # im Menü-Designer ausgewählte Buttons (Zeilen werden hervorgehoben)
        self.width = START_W if kind == "start" else NODE_W
        self.height = HEADER_H + ROW_H * len(rows) + 8
        self.ports: Dict[Source, PortItem] = {}

        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable |
                      QGraphicsItem.ItemSendsGeometryChanges)
        self.setZValue(1)
        for i, row in enumerate(rows):
            if row.kind in (ROW_OUTPUT, ROW_ADD) and row.source is not None:
                port = PortItem(row.source, self)
                port.setPos(self.width, self.row_center_y(i))
                self.ports[row.source] = port

    # --- Geometrie ------------------------------------------------------------
    @property
    def has_input(self) -> bool:
        return self.kind != "start"

    def row_center_y(self, index: int) -> float:
        return HEADER_H + index * ROW_H + ROW_H / 2 + 4

    def input_point(self) -> QPointF:
        return self.mapToScene(QPointF(0, HEADER_H / 2))

    def output_point(self, source: Source) -> Optional[QPointF]:
        port = self.ports.get(source)
        return port.scenePos() if port else None

    def row_at(self, local_y: float) -> Optional[NodeRow]:
        index = int((local_y - HEADER_H - 4) // ROW_H)
        if 0 <= index < len(self.rows) and local_y >= HEADER_H:
            return self.rows[index]
        return None

    def boundingRect(self) -> QRectF:
        return QRectF(-PORT_R - 2, -24, self.width + 2 * PORT_R + 4, self.height + 26)

    def shape(self) -> QtGui.QPainterPath:
        path = QtGui.QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self.width, self.height), CORNER, CORNER)
        return path

    # --- Zeichnen -------------------------------------------------------------
    def paint(self, painter: QtGui.QPainter, option, widget=None):
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        body = QRectF(0, 0, self.width, self.height)

        border = C_BORDER
        border_w = 1.5
        if self.isSelected():
            border, border_w = C_GOLD, 2.5
        if self.highlight == HL_ALLOWED:
            border, border_w = C_OK, 2.5
        elif self.highlight == HL_LOCKED:
            border, border_w = C_LOCKED, 2.5
        elif self.highlight == HL_INVALID:
            border, border_w = C_BAD, 2.0
        elif self.highlight == HL_TARGET:
            border, border_w = C_GOLD, 2.5

        painter.setPen(QtGui.QPen(border, border_w))
        painter.setBrush(C_NODE)
        painter.drawRoundedRect(body, CORNER, CORNER)

        # Kopfzeile
        header = QtGui.QPainterPath()
        header.addRoundedRect(QRectF(0, 0, self.width, HEADER_H), CORNER, CORNER)
        header.addRect(QRectF(0, HEADER_H - CORNER, self.width, CORNER))
        painter.setPen(Qt.NoPen)
        painter.setBrush(C_HEADER)
        painter.drawPath(header.simplified())
        painter.setBrush(self.accent)
        painter.drawRoundedRect(QRectF(0, 0, 5, HEADER_H), 2, 2)
        painter.setPen(QtGui.QPen(C_BORDER, 1))
        painter.drawLine(QPointF(0, HEADER_H), QPointF(self.width, HEADER_H))

        title = ("⌂ " if self.is_main else "") + self.title
        painter.setPen(C_TEXT)
        painter.setFont(_font(10, bold=True))
        painter.drawText(QRectF(14, 6, self.width - 24, 18), Qt.AlignLeft | Qt.AlignVCenter,
                         painter.fontMetrics().elidedText(title, Qt.ElideRight, int(self.width - 24)))
        painter.setPen(self.subtitle_color)
        painter.setFont(_font(8))
        painter.drawText(QRectF(14, 24, self.width - 24, 16), Qt.AlignLeft | Qt.AlignVCenter,
                         painter.fontMetrics().elidedText(self.subtitle, Qt.ElideRight, int(self.width - 24)))

        # Eingang
        if self.has_input:
            painter.setPen(QtGui.QPen(C_BG, 2))
            painter.setBrush(C_DIM)
            painter.drawEllipse(QPointF(0, HEADER_H / 2), PORT_R, PORT_R)

        # Zeilen
        for i, row in enumerate(self.rows):
            rect = QRectF(14, HEADER_H + 4 + i * ROW_H, self.width - 32, ROW_H)
            if any(row.shows_button(bid) for bid in self.selected_button_ids):
                band = QtGui.QColor(C_GOLD)
                band.setAlpha(45)
                painter.setPen(Qt.NoPen)
                painter.setBrush(band)
                painter.drawRoundedRect(QRectF(6, rect.top() + 1, self.width - 12, ROW_H - 2), 4, 4)
            if row.kind == ROW_OUTPUT:
                painter.setPen(C_TEXT)
                painter.setFont(_font(9))
                align = Qt.AlignRight | Qt.AlignVCenter
            elif row.kind == ROW_ADD:
                painter.setPen(C_MUTED)
                painter.setFont(_font(9))
                align = Qt.AlignRight | Qt.AlignVCenter
            elif row.kind == ROW_SUGGEST:
                self._paint_suggestion(painter, rect, row, i)
                continue
            else:
                painter.setPen(C_LOCKED if row.warning else C_DIM)
                painter.setFont(_font(9, italic=True))
                align = Qt.AlignLeft | Qt.AlignVCenter
            painter.drawText(rect, align, painter.fontMetrics().elidedText(row.text, Qt.ElideRight, int(rect.width())))

        # Hinweis beim Ziehen einer Verbindung
        if self.highlight_text:
            color = {HL_ALLOWED: C_OK, HL_LOCKED: C_LOCKED}.get(self.highlight, C_BAD)
            painter.setFont(_font(8, bold=True))
            text_w = painter.fontMetrics().horizontalAdvance(self.highlight_text) + 16
            badge = QRectF(0, -22, min(text_w, self.width + 80), 18)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QtGui.QColor(24, 24, 27, 235))
            painter.drawRoundedRect(badge, 4, 4)
            painter.setPen(color)
            painter.drawText(badge, Qt.AlignCenter, self.highlight_text)

    def _paint_suggestion(self, painter: QtGui.QPainter, rect: QRectF, row: NodeRow, index: int):
        """Vorschlag (Konzept 2.1, Regel 2): gedimmt, mit hohlem, gestricheltem Ausgang (noch kein echter Button)."""
        painter.setPen(C_MUTED)
        painter.setFont(_font(7))
        painter.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter, SUGGESTION_TAG)
        painter.setPen(C_DIM)
        painter.setFont(_font(9, italic=True))
        painter.drawText(rect, Qt.AlignRight | Qt.AlignVCenter,
                         painter.fontMetrics().elidedText(row.text, Qt.ElideRight, int(rect.width() - 60)))
        pen = QtGui.QPen(C_MUTED, 1.4, Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(C_NODE)
        painter.drawEllipse(QPointF(self.width, self.row_center_y(index)), PORT_R, PORT_R)

    def set_highlight(self, state: int, text: str = ""):
        if (self.highlight, self.highlight_text) != (state, text):
            self.highlight, self.highlight_text = state, text
            self.update()

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged and self.scene() is not None:
            self.scene().node_moved(self)
        return super().itemChange(change, value)


class FrameItem(QGraphicsItem):
    """
    Rahmen (v1.15.0, Konzept 3.5, wie Underlays in Fusion): farbige Fläche hinter den Knoten. Am Titel ziehen
    verschiebt den Rahmen samt Inhalt (Knoten mit der Mitte darin, Rahmen ganz darin), an den Kanten links,
    rechts und unten ändert sich die Größe. Die Fläche selbst nimmt keine Klicks an – dort wirkt der
    Auswahlrahmen wie auf freier Fläche.
    """

    def __init__(self, group):
        super().__init__()
        self.frame_id = group.id
        self.name = group.name
        self.color = QtGui.QColor(group.color)
        x, y, self.w, self.h = group.rect
        self.setPos(x, y)
        self.setZValue(-10)
        self.setFlags(QGraphicsItem.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        self._mode = None            # "move" oder Kanten "l", "r", "b", "lb", "rb"
        self._press = None
        self._start = None
        self._members = ([], [])     # (NodeItems, FrameItems) beim Verschieben
        self._member_start = {}

    def rect(self) -> List[float]:
        return [self.pos().x(), self.pos().y(), self.w, self.h]

    def boundingRect(self) -> QRectF:
        return QRectF(-FRAME_GRIP, -FRAME_GRIP, self.w + 2 * FRAME_GRIP, self.h + 2 * FRAME_GRIP)

    def shape(self) -> QtGui.QPainterPath:
        """Nur Titelleiste und Kantenband; die Fläche dazwischen bleibt frei."""
        g = FRAME_GRIP / 2
        path = QtGui.QPainterPath()
        path.setFillRule(Qt.OddEvenFill)
        path.addRect(QRectF(-g, -g, self.w + 2 * g, self.h + 2 * g))
        path.addRect(QRectF(g, FRAME_TITLE_H, self.w - 2 * g, self.h - FRAME_TITLE_H - g))
        return path

    def paint(self, painter: QtGui.QPainter, option, widget=None):
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        fill, border, title_bg = QtGui.QColor(self.color), QtGui.QColor(self.color), QtGui.QColor(self.color)
        fill.setAlpha(40)
        border.setAlpha(150)
        title_bg.setAlpha(110)
        body = QRectF(0, 0, self.w, self.h)
        painter.setPen(QtGui.QPen(C_GOLD, 2.2) if self.isSelected() else QtGui.QPen(border, 1.2))
        painter.setBrush(fill)
        painter.drawRoundedRect(body, 10, 10)
        title = QtGui.QPainterPath()
        title.addRoundedRect(QRectF(0, 0, self.w, FRAME_TITLE_H), 10, 10)
        title.addRect(QRectF(0, FRAME_TITLE_H - 10, self.w, 10))
        painter.setPen(Qt.NoPen)
        painter.setBrush(title_bg)
        painter.drawPath(title.simplified())
        painter.setPen(C_TEXT)
        painter.setFont(_font(11, bold=True))
        painter.drawText(QRectF(12, 0, self.w - 24, FRAME_TITLE_H), Qt.AlignLeft | Qt.AlignVCenter,
                         painter.fontMetrics().elidedText(self.name, Qt.ElideRight, int(self.w - 24)))
        # Griff unten rechts
        painter.setPen(QtGui.QPen(border, 1.4))
        for d in (6, 11, 16):
            painter.drawLine(QPointF(self.w - d, self.h - 3), QPointF(self.w - 3, self.h - d))

    # --- Maus -----------------------------------------------------------------
    def _edges(self, p: QPointF) -> str:
        edges = ""
        if p.x() <= FRAME_GRIP:
            edges += "l"
        elif p.x() >= self.w - FRAME_GRIP:
            edges += "r"
        if p.y() >= self.h - FRAME_GRIP:
            edges += "b"
        return edges

    def hoverMoveEvent(self, event):
        edges = self._edges(event.pos())
        cursor = {"l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor, "b": Qt.SizeVerCursor,
                  "rb": Qt.SizeFDiagCursor, "lb": Qt.SizeBDiagCursor}.get(edges)
        if cursor is None:
            cursor = Qt.SizeAllCursor if event.pos().y() <= FRAME_TITLE_H else Qt.ArrowCursor
        self.setCursor(cursor)
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return
        self._press = event.scenePos()
        self._start = (self.pos().x(), self.pos().y(), self.w, self.h)
        self._mode = self._edges(event.pos()) or "move"
        if self._mode == "move":
            self._members = self.scene().frame_members(self)
            self._member_start = {item: item.pos() for item in self._members[0] + self._members[1]}
        if not event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier):
            self.scene().clearSelection()
        self.setSelected(True)
        event.accept()

    def mouseMoveEvent(self, event):
        if self._mode is None:
            return
        delta = event.scenePos() - self._press
        x, y, w, h = self._start
        if self._mode == "move":
            self.setPos(x + delta.x(), y + delta.y())
            for item, start in self._member_start.items():
                item.setPos(start + delta)
        else:
            from core.node_frames import MIN_W, MIN_H
            nx, nw, nh = x, w, h
            if "r" in self._mode:
                nw = max(MIN_W, w + delta.x())
            if "l" in self._mode:
                nw = max(MIN_W, w - delta.x())
                nx = x + w - nw
            if "b" in self._mode:
                nh = max(MIN_H, h + delta.y())
            self.prepareGeometryChange()
            self.w, self.h = nw, nh
            self.setPos(nx, y)
        event.accept()

    def mouseReleaseEvent(self, event):
        mode, self._mode = self._mode, None
        if mode is None:
            super().mouseReleaseEvent(event)
            return
        scene = self.scene()
        scene.frame_released = True        # Szene: keine Knoten-Verschiebung extra übernehmen
        if mode == "move":
            dx, dy = self.pos().x() - self._start[0], self.pos().y() - self._start[1]
            nodes, frames = self._members
            scene.controller.move_frame(self.frame_id, dx, dy, [n.node_id for n in nodes],
                                        [f.frame_id for f in frames])
        else:
            scene.controller.set_frame(self.frame_id, "Rahmengröße ändern", rect=self.rect())
        self._members, self._member_start = ([], []), {}
        event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.pos().y() <= FRAME_TITLE_H and not self._edges(event.pos()):
            frame_id, scene = self.frame_id, self.scene()
            QTimer.singleShot(0, lambda: scene.rename_frame(frame_id))   # nach dem Klick (Neuaufbau löscht self)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class WireItem(QGraphicsPathItem):
    """
    Verbindung als Linie. implicit=True: nicht ausdrücklich verbundenes Film-Ende, das standardmäßig
    ins Hauptmenü zurückführt (blasser, gestrichelt).
    """

    def __init__(self, source: Source, target_id: str, implicit: bool = False):
        super().__init__()
        self.source = source
        self.target_id = target_id
        self.implicit = implicit
        self.backward = False
        self._hover = False
        self.pause_badge: Optional[PauseBadge] = None
        self.setZValue(0)
        self.setAcceptHoverEvents(True)
        if implicit:
            self.setToolTip(tr("graph_implicit_return"))
        self._apply_pen()

    def _apply_pen(self):
        if self._hover:
            color, width = C_GOLD, 2.4
        elif self.implicit:
            color, width = C_MUTED, 1.4
        else:
            color, width = C_WIRE, 1.8
        pen = QtGui.QPen(color, width)
        pen.setCapStyle(Qt.RoundCap)
        if self.implicit:
            pen.setStyle(Qt.DotLine)
        elif self.backward:
            pen.setStyle(Qt.DashLine)
        self.setPen(pen)

    def update_path(self, p1: QPointF, p2: QPointF, backward: bool):
        self.backward = backward
        self.setPath(wire_path(p1, p2, backward))
        self._apply_pen()
        if self.pause_badge is not None:
            # vorwärts kurz vor dem Ziel (die Mitte liegt oft auf einem Knoten dazwischen), Rücksprünge auf
            # der langen Strecke unter den Knoten
            self.pause_badge.setPos(self.path().pointAtPercent(0.5 if backward else 0.85))

    def set_pause(self) -> "PauseBadge":
        """Wechsel in ein Menü mit anderem Hintergrund (v1.13.2): Symbol auf der Linie. Es ist ein
        eigenes Element über den Knoten (als Kind der Linie läge es hinter ihnen); die Szene fügt es hinzu."""
        self.pause_badge = PauseBadge()
        self.setToolTip(tr(PAUSE_TOOLTIP))
        return self.pause_badge

    def shape(self) -> QtGui.QPainterPath:
        stroker = QtGui.QPainterPathStroker()
        stroker.setWidth(10)
        return stroker.createStroke(self.path())

    def hoverEnterEvent(self, event):
        self._hover = True
        self._apply_pen()
        if self.scene() is not None:
            self.scene().highlight_target(self.target_id, True)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._hover = False
        self._apply_pen()
        if self.scene() is not None:
            self.scene().highlight_target(self.target_id, False)
        super().hoverLeaveEvent(event)


PAUSE_TOOLTIP = "graph_pause_tip"      # Schlüssel in core/translations.py


class PauseBadge(QGraphicsItem):
    """Kleines Pausen-Symbol auf einer Verbindung zwischen Menüs mit verschiedenem Hintergrund (v1.13.2)."""
    R = 8.0

    def __init__(self):
        super().__init__()
        self.setAcceptHoverEvents(True)
        self.setToolTip(tr(PAUSE_TOOLTIP))
        self.setZValue(2)        # über Linien und Knoten, unter den Sprungmarken

    def boundingRect(self) -> QRectF:
        return QRectF(-self.R - 1, -self.R - 1, 2 * self.R + 2, 2 * self.R + 2)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.setPen(QtGui.QPen(C_MENU, 1.4))
        painter.setBrush(QtGui.QColor(24, 24, 27, 235))
        painter.drawEllipse(QPointF(0, 0), self.R, self.R)
        painter.setPen(Qt.NoPen)
        painter.setBrush(C_MENU)
        for x in (-3.2, 1.0):
            painter.drawRect(QRectF(x, -3.5, 2.2, 7.0))


def wire_path(p1: QPointF, p2: QPointF, backward: bool) -> QtGui.QPainterPath:
    path = QtGui.QPainterPath(p1)
    if not backward:
        dx = max(60.0, abs(p2.x() - p1.x()) * 0.5)
        path.cubicTo(QPointF(p1.x() + dx, p1.y()), QPointF(p2.x() - dx, p2.y()), p2)
    else:
        # Rücksprung: nach rechts heraus, unterhalb der Knoten zurück, von links in den Eingang
        drop = max(p1.y(), p2.y()) + 120.0
        path.cubicTo(QPointF(p1.x() + 140, p1.y()), QPointF(p1.x() + 140, drop), QPointF(p1.x(), drop))
        path.lineTo(QPointF(p2.x(), drop))
        path.cubicTo(QPointF(p2.x() - 140, drop), QPointF(p2.x() - 140, p2.y()), p2)
    return path


class MarkerItem(QGraphicsItem):
    """Sprungmarke „↩ Ziel“ an einem Ausgang (statt einer Rücksprung-Linie)."""

    def __init__(self, source: Source, target_id: Optional[str], text: str, is_default: bool, parent: NodeItem):
        # Wichtig: Maße festlegen, bevor Qt das Element abfragt. Unter Windows lösen setCursor
        # und setParentItem sofort boundingRect() aus (im Offscreen-Test nicht).
        super().__init__()
        self.source = source
        self.target_id = target_id
        self.text = text
        self.is_default = is_default
        self._hover = False
        fm = QtGui.QFontMetrics(_font(8, bold=not is_default, italic=is_default))
        self._w = fm.horizontalAdvance(text) + 14
        self.setParentItem(parent)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setZValue(3)
        if is_default:
            self.setToolTip(tr("graph_implicit_return_marker"))
        else:
            self.setToolTip(tr("graph_return_marker", name=text[2:]))

    def boundingRect(self) -> QRectF:
        return QRectF(0, -9, self._w, 18)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        color = C_GOLD if self._hover else (C_MUTED if self.is_default else C_DIM)
        painter.setPen(QtGui.QPen(color, 1.2, Qt.DashLine if self.is_default else Qt.SolidLine))
        painter.setBrush(QtGui.QColor(24, 24, 27, 220))
        painter.drawRoundedRect(self.boundingRect(), 9, 9)
        painter.setFont(_font(8, bold=not self.is_default, italic=self.is_default))
        painter.setPen(color)
        painter.drawText(self.boundingRect(), Qt.AlignCenter, self.text)

    def hoverEnterEvent(self, event):
        self._hover = True
        self.update()
        if self.scene() is not None:
            self.scene().preview_marker(self, True)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._hover = False
        self.update()
        if self.scene() is not None:
            self.scene().preview_marker(self, False)
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.scene() is not None:
            self.scene().jump_to_node(self.scene().effective_target(self.source))
            event.accept()
            return
        super().mousePressEvent(event)


class NodeScene(QGraphicsScene):
    status_message = Signal(str)
    node_activated = Signal(str)               # Doppelklick auf einen Knoten
    files_dropped = Signal(str, list, QPointF)  # (Film-ID oder "", Dateipfade, Szenenposition)

    def __init__(self, controller: GraphController, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.nodes: Dict[str, NodeItem] = {}
        self.frames: Dict[str, FrameItem] = {}
        self.wires: List[WireItem] = []
        self.frame_released = False   # ein Rahmen hat das Loslassen schon übernommen (v1.15.0)
        self._drag_source: Optional[Source] = None
        self._drag_wire: Optional[QGraphicsPathItem] = None
        self._pending_wire: Optional[QGraphicsPathItem] = None   # bleibt sichtbar, solange die Vorschläge offen sind
        self._preview_wire: Optional[QGraphicsPathItem] = None
        self._select_after_rebuild: Optional[str] = None
        self._empty_drop_hint = ""
        self._rebuild_pending = False
        self._click_action = None   # Klick auf „＋ Button“ bzw. einen Vorschlag: läuft beim Loslassen
        self.setSceneRect(-4000, -4000, 8000, 8000)
        controller.changed.connect(self.schedule_rebuild)
        controller.selection_changed.connect(self._show_selected_buttons)
        self.rebuild()

    def _show_selected_buttons(self, menu_id: str, button_ids: list):
        for node_id, item in self.nodes.items():
            value = set(button_ids) if node_id == menu_id else set()
            if item.selected_button_ids != value:
                item.selected_button_ids = value
                item.update()

    # --- Aufbau ---------------------------------------------------------------
    def schedule_rebuild(self):
        if not self._rebuild_pending:
            self._rebuild_pending = True
            QTimer.singleShot(0, self.rebuild)

    def rebuild(self):
        self._rebuild_pending = False
        selected = {item.node_id for item in self.selectedItems() if isinstance(item, NodeItem)}
        selected_frames = {item.frame_id for item in self.selectedItems() if isinstance(item, FrameItem)}
        if self._select_after_rebuild is not None:
            selected = {self._select_after_rebuild}
            self._select_after_rebuild = None
        self._cancel_drag()
        self._clear_preview()
        self._pending_wire = None   # wird von clear() mit entfernt
        self.clear()
        self.nodes.clear()
        self.frames.clear()
        self.wires.clear()

        project = self.controller.project
        main = project.main_menu
        for group in project.view.groups:
            item = FrameItem(group)
            self.addItem(item)
            self.frames[group.id] = item
            item.setSelected(group.id in selected_frames)
        self._add_node(NodeItem(START_NODE_ID, "start", tr("graph_start_title"), tr("graph_start_subtitle"),
                                start_rows(), C_GOLD))
        for film in project.films:
            self._add_node(NodeItem(film.id, "film", film.name, film_subtitle(film), film_rows(film, project),
                                    QtGui.QColor(film.color)))
        for menu in project.menus:
            films = content_films(project, menu)
            film_color = QtGui.QColor(films[0].color) if len(films) == 1 else None
            self._add_node(NodeItem(menu.id, "menu", menu.name, menu_subtitle(project, menu),
                                    menu_rows(project, menu), C_MENU,
                                    is_main=(main is not None and menu.id == main.id), subtitle_color=film_color))

        for node_id, item in self.nodes.items():
            item.setSelected(node_id in selected)
        self._show_selected_buttons(*self.controller.selected_buttons)
        self._build_connections()

    def _add_node(self, item: NodeItem):
        positions = self.controller.project.view.node_positions
        if item.node_id not in positions:
            # Reine Ansichtsdaten: fehlende Position einmalig festhalten (kein Undo-Schritt)
            positions[item.node_id] = list(self.controller.node_position(item.node_id))
        x, y = self.controller.node_position(item.node_id)
        item.setPos(x, y)
        self.addItem(item)
        self.nodes[item.node_id] = item

    def _build_connections(self):
        from core.disc_adapter import menu_group_index
        project = self.controller.project
        markers_mode = project.view.return_wire_mode == "markers"
        group_of = menu_group_index(project)

        def pause(source: Source, target_id: str) -> bool:
            # Menü → Menü mit anderem Hintergrund: eigene Menü-Playlist, kurze Ladepause
            return (source.kind == SOURCE_BUTTON and source.node_id in group_of and target_id in group_of
                    and group_of[source.node_id] != group_of[target_id])

        for item in list(self.nodes.values()):
            for source in item.ports:
                target_id = connection_target(project, source)
                port = item.ports[source]
                if target_id is None or target_id not in self.nodes:
                    main = project.main_menu
                    if source.kind == SOURCE_FILM_END and main is not None and main.id in self.nodes:
                        # Nicht verbundenes Film-Ende: standardmäßig zurück ins Hauptmenü
                        if markers_mode:
                            self._add_marker(item, port, source, None, "↩ " + tr("graph_main_menu"), True)
                        else:
                            wire = WireItem(source, main.id, implicit=True)
                            self.addItem(wire)
                            self.wires.append(wire)
                    continue
                backward = self.nodes[target_id].pos().x() < item.pos().x()
                if backward and markers_mode:
                    marker = self._add_marker(item, port, source, target_id,
                                              "↩ " + target_display_name(project, target_id), False)
                    if pause(source, target_id):
                        marker.setToolTip(marker.toolTip() + "\n⏸ " + tr(PAUSE_TOOLTIP))
                    continue
                wire = WireItem(source, target_id)
                if pause(source, target_id):
                    self.addItem(wire.set_pause())
                self.addItem(wire)
                self.wires.append(wire)
        self._update_wire_paths()

    def _add_marker(self, item: NodeItem, port: PortItem, source: Source, target_id, text, is_default):
        marker = MarkerItem(source, target_id, text, is_default, item)
        marker.setPos(port.pos().x() + PORT_R + 6, port.pos().y())
        return marker

    def _update_wire_paths(self, node_id: Optional[str] = None):
        for wire in self.wires:
            src_item = self._source_item(wire.source)
            dst_item = self.nodes.get(wire.target_id)
            if src_item is None or dst_item is None:
                continue
            if node_id is not None and node_id not in (src_item.node_id, dst_item.node_id):
                continue
            backward = dst_item.pos().x() < src_item.pos().x()
            wire.update_path(src_item.output_point(wire.source), dst_item.input_point(), backward)

    def _source_item(self, source: Source) -> Optional[NodeItem]:
        return self.nodes.get(START_NODE_ID if source.node_id is None else source.node_id)

    def node_moved(self, item: NodeItem):
        self._update_wire_paths(item.node_id)

    # --- Verbindungen ziehen -----------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            port = self._port_at(event.scenePos())
            if port is not None:
                self._start_drag(port.source, event.scenePos())
                event.accept()
                return
            node = self._node_at(event.scenePos())
            if node is not None and node.kind == "menu":
                row = node.row_at(node.mapFromScene(event.scenePos()).y())
                screen = event.screenPos()
                # Fenster und Listen erst beim Loslassen öffnen (während eines Klicks geöffnet,
                # schloss Windows sie sofort wieder)
                if row is not None and row.kind == ROW_ADD:
                    event.accept()
                    menu_id = node.node_id
                    self._click_action = lambda: self.offer_add(menu_id, screen)
                    return
                if row is not None and row.kind == ROW_SUGGEST:
                    event.accept()
                    self._click_action = lambda: self.activate_suggestion(row.suggestion, screen)
                    return
                if row is not None and row.button_ids:
                    # zusammengefasste Inhaltszeile: alle ihre Buttons auswählen (v1.12.1)
                    self.controller.select_buttons(node.node_id, row.button_ids)
                elif row is not None and row.button_id:
                    # Button-Zeile: Button auswählen (Viewer und Inspektor zeigen ihn), Knoten wie gewohnt
                    self.controller.select_button(node.node_id, row.button_id)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_source is not None:
            self._update_drag(event.scenePos())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._click_action is not None and event.button() == Qt.LeftButton:
            action, self._click_action = self._click_action, None
            QTimer.singleShot(0, action)
            event.accept()
            return
        if self._drag_source is not None and event.button() == Qt.LeftButton:
            self._finish_drag(event.scenePos())
            event.accept()
            return
        super().mouseReleaseEvent(event)
        if self.frame_released:
            self.frame_released = False     # Rahmen samt Inhalt ist schon ein Rückgängig-Schritt
            return
        self._commit_node_positions()

    def mouseDoubleClickEvent(self, event):
        node = self._node_at(event.scenePos())
        if node is not None:
            self.node_activated.emit(node.node_id)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    # --- Dateien hineinziehen -----------------------------------------------------
    @staticmethod
    def _local_files(event) -> list:
        mime = event.mimeData()
        if not mime.hasUrls():
            return []
        return [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]

    def dragEnterEvent(self, event):
        if self._local_files(event):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if not self._local_files(event):
            super().dragMoveEvent(event)
            return
        target = self._node_at(event.scenePos())
        for node in self.nodes.values():
            node.set_highlight(HL_NONE)
        if target is not None and target.kind == "film":
            target.set_highlight(HL_ALLOWED, tr("graph_drop_into_film"))
        elif target is not None and target.kind == "menu" and any(map(background_field, self._local_files(event))):
            target.set_highlight(HL_ALLOWED, tr("graph_drop_background"))
        elif target is not None:
            target.set_highlight(HL_INVALID, tr("graph_drop_needs_film"))
        event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        for node in self.nodes.values():
            node.set_highlight(HL_NONE)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        files = self._local_files(event)
        if not files:
            super().dropEvent(event)
            return
        for node in self.nodes.values():
            node.set_highlight(HL_NONE)
        target = self._node_at(event.scenePos())
        event.acceptProposedAction()
        if target is None:
            self.files_dropped.emit("", files, event.scenePos())
        elif target.kind == "film":
            self.files_dropped.emit(target.node_id, files, event.scenePos())
        elif target.kind == "menu" and any(map(background_field, files)):
            # Bild, Video, Musik auf einem Menü-Knoten: Hintergrund dieses Menüs (v1.13.2)
            from gui.studio.backgrounds import apply_background_files
            rejected = apply_background_files(self.controller, target.node_id, files)
            self.status_message.emit(tr("graph_no_background", files=", ".join(rejected)) if rejected else
                                     tr("graph_background_set", name=target.title))
        else:
            self.status_message.emit(tr("graph_files_need_film"))

    def _port_at(self, pos: QPointF) -> Optional[PortItem]:
        for item in self.items(pos):
            if isinstance(item, PortItem):
                return item
        return None

    def _node_at(self, pos: QPointF) -> Optional[NodeItem]:
        for item in self.items(pos):
            if isinstance(item, NodeItem):
                return item
            if isinstance(item, (PortItem, MarkerItem)) and isinstance(item.parentItem(), NodeItem):
                return item.parentItem()
        return None

    def _start_drag(self, source: Source, pos: QPointF):
        self._drag_source = source
        self._drag_wire = QGraphicsPathItem()
        pen = QtGui.QPen(C_GOLD, 2.2)
        pen.setCapStyle(Qt.RoundCap)
        self._drag_wire.setPen(pen)
        self._drag_wire.setZValue(5)
        self.addItem(self._drag_wire)
        can_create = any(self.controller.check_new_node(source, kind).allowed for kind, _, _ in NEW_NODE_CHOICES)
        connected = connection_target(self.controller.project, source) is not None
        hints = ([tr("graph_hint_new_node")] if can_create else []) + \
            ([tr("graph_hint_disconnect")] if connected else [])
        self._empty_drop_hint = (tr("graph_hint_empty_drop") + tr("graph_or").join(hints)) if hints else ""
        self._update_drag(pos)

    def _update_drag(self, pos: QPointF):
        src_item = self._source_item(self._drag_source)
        start = src_item.output_point(self._drag_source)
        self._drag_wire.setPath(wire_path(start, pos, False))

        target = self._node_at(pos)
        message = self._empty_drop_hint
        for node in self.nodes.values():
            if node is not target:
                node.set_highlight(HL_NONE)
        if target is not None and self._is_own_add_port(target):
            # Noch über dem eigenen Menü: Loslassen hier legt nur einen Button an
            target.set_highlight(HL_NONE)
            message = tr("graph_hint_new_button")
        elif target is not None:
            state, text = self._evaluate_target(target)
            target.set_highlight(state, text)
            message = text
        self.status_message.emit(message)

    def _evaluate_target(self, target: NodeItem):
        if not target.has_input:
            return HL_INVALID, tr("graph_no_input")
        check = self.controller.check(self._drag_source, target.node_id)
        if check.allowed:
            return HL_ALLOWED, tr("graph_connect")
        if check.locked_for_later_stage:
            return HL_LOCKED, f"🔒 {check.reason}"
        return HL_INVALID, check.reason

    def _finish_drag(self, pos: QPointF):
        source = self._drag_source
        target = self._node_at(pos)
        if target is None:
            self._offer_new_node(source, pos)
            return
        own_add_port = self._is_own_add_port(target)
        self._cancel_drag()
        if own_add_port:
            menu_id = source.node_id
            screen = self._screen_point(pos)
            QTimer.singleShot(0, lambda: self.offer_add(menu_id, screen))
            return
        if not target.has_input:
            return
        check = self.controller.connect(source, target.node_id)
        if not check.allowed:
            self.status_message.emit(("🔒 " if check.locked_for_later_stage else "") + check.reason)

    def _is_own_add_port(self, target: NodeItem) -> bool:
        """„＋ Button“ gezogen, aber noch über dem eigenen Menü (entspricht einem Klick)."""
        source = self._drag_source
        return source is not None and source.kind == SOURCE_NEW_BUTTON and target.node_id == source.node_id

    def _cancel_drag(self):
        if self._drag_wire is not None:
            self.removeItem(self._drag_wire)
        self._drag_wire = None
        self._drag_source = None
        for node in self.nodes.values():
            node.set_highlight(HL_NONE)
        self.status_message.emit("")

    # --- Neuer Knoten beim Loslassen im Leeren ----------------------------------
    def _offer_new_node(self, source: Source, pos: QPointF):
        """
        Verbindung im Leeren losgelassen: Vorschläge für einen neuen, direkt verbundenen Knoten
        anbieten (plus „Verbindung lösen“, falls schon verbunden). Die Vorschläge öffnen sich
        erst nach Abschluss des Maus-Ereignisses; bis dahin bleibt die gezogene Linie sichtbar.
        """
        checks = {kind: self.controller.check_new_node(source, kind) for kind, _, _ in NEW_NODE_CHOICES}
        connected = connection_target(self.controller.project, source) is not None
        if not connected and not any(c.allowed for c in checks.values()):
            reason = next(iter(checks.values())).reason
            self._cancel_drag()
            self.status_message.emit("🔒 " + reason)
            return
        self._pending_wire, self._drag_wire = self._drag_wire, None
        self._cancel_drag()
        QTimer.singleShot(0, lambda: self._run_new_node_menu(source, pos, checks, connected))

    def _run_new_node_menu(self, source: Source, pos: QPointF, checks: dict, connected: bool):
        choice = self._choose_new_node(self._screen_point(pos), checks, connected)
        if self._pending_wire is not None:
            self.removeItem(self._pending_wire)
            self._pending_wire = None
        self._apply_new_node_choice(source, pos, choice)

    def _choose_new_node(self, screen_pos: QtCore.QPoint, checks: dict, connected: bool) -> Optional[str]:
        """Zeigt die Vorschläge und gibt die Wahl zurück (Knotenart, CHOICE_DISCONNECT oder None)."""
        menu = QMenu()
        menu.setToolTipsVisible(True)
        for kind, label, _ in NEW_NODE_CHOICES:
            check = checks[kind]
            if check.allowed:
                act = menu.addAction(tr(label))
            else:
                stage = tr("graph_stage", n=check.required_stage) if check.locked_for_later_stage else ""
                act = menu.addAction(f"🔒 {tr(label)}{stage}")
                act.setEnabled(False)
                act.setToolTip(check.reason)
            act.setData(kind)
        if connected:
            menu.addSeparator()
            menu.addAction(tr("graph_disconnect")).setData(CHOICE_DISCONNECT)
        chosen = menu.exec(screen_pos)
        return chosen.data() if chosen is not None else None

    def _apply_new_node_choice(self, source: Source, pos: QPointF, choice: Optional[str]):
        if choice is None:
            return
        if choice == CHOICE_DISCONNECT:
            self.controller.connect(source, None)
            return
        name = disc_label(next(n for kind, _, n in NEW_NODE_CHOICES if kind == choice),
                          self.controller.project.settings.app_lang)
        # Eingang des neuen Knotens genau an die Stelle, an der losgelassen wurde
        node_pos = (pos.x(), pos.y() - HEADER_H / 2)
        node_id = self.controller.add_connected_node(source, choice, name, node_pos)
        if node_id is not None:
            self._select_after_rebuild = node_id

    def _screen_point(self, pos: QPointF) -> QtCore.QPoint:
        for view in self.views():
            return view.viewport().mapToGlobal(view.mapFromScene(pos))
        return QtGui.QCursor.pos()

    def _commit_node_positions(self):
        project = self.controller.project
        moved = {}
        for node_id, item in self.nodes.items():
            pos = [item.pos().x(), item.pos().y()]
            if project.view.node_positions.get(node_id) != pos:
                moved[node_id] = (pos[0], pos[1])
        if moved:
            self.controller.move_nodes(moved)

    # --- Sprungmarken -----------------------------------------------------------
    def effective_target(self, source: Source) -> Optional[str]:
        target = connection_target(self.controller.project, source)
        if target is None and source.kind == SOURCE_FILM_END:
            main = self.controller.project.main_menu
            return main.id if main else None
        return target

    def preview_marker(self, marker: MarkerItem, active: bool):
        self._clear_preview()
        target_id = self.effective_target(marker.source)
        target = self.nodes.get(target_id)
        if not active or target is None:
            return
        src_item = self._source_item(marker.source)
        self._preview_wire = QGraphicsPathItem(wire_path(src_item.output_point(marker.source),
                                                         target.input_point(), True))
        pen = QtGui.QPen(C_GOLD, 1.8, Qt.DashLine)
        self._preview_wire.setPen(pen)
        self._preview_wire.setZValue(4)
        self.addItem(self._preview_wire)
        target.set_highlight(HL_TARGET)

    def highlight_target(self, node_id: Optional[str], active: bool):
        """Zielknoten einer Verbindung beim Überfahren hervorheben (wie bei Sprungmarken)."""
        target = self.nodes.get(node_id)
        if target is None:
            return
        if active:
            target.set_highlight(HL_TARGET)
        elif target.highlight == HL_TARGET:
            target.set_highlight(HL_NONE)

    def _clear_preview(self):
        if self._preview_wire is not None and self._preview_wire.scene() is self:
            self.removeItem(self._preview_wire)
        self._preview_wire = None
        for node in self.nodes.values():
            if node.highlight == HL_TARGET:
                node.set_highlight(HL_NONE)

    def jump_to_node(self, node_id: Optional[str]):
        item = self.nodes.get(node_id)
        if item is None:
            return
        self.clearSelection()
        item.setSelected(True)
        for view in self.views():
            view.centerOn(item)

    # --- Kontextmenüs & Löschen -------------------------------------------------
    def delete_selected(self):
        ids = [i.node_id for i in self.selectedItems() if isinstance(i, NodeItem) and i.kind in ("menu", "film")]
        frame_ids = [i.frame_id for i in self.selectedItems() if isinstance(i, FrameItem)]
        if frame_ids:
            self.controller.remove_frames(frame_ids)     # nur die Rahmen, die Knoten darin bleiben
        if ids:
            self.controller.remove_nodes(ids)
        elif not frame_ids and any(isinstance(i, NodeItem) for i in self.selectedItems()):
            self.status_message.emit(tr("graph_start_not_deletable"))

    # --- Rahmen (v1.15.0) ----------------------------------------------------------
    def node_boxes(self, items=None) -> Dict[str, tuple]:
        return {i.node_id: (i.pos().x(), i.pos().y(), i.width, i.height) for i in (items or self.nodes.values())}

    def frame_members(self, frame: "FrameItem"):
        """(NodeItems, FrameItems), die mit dem Rahmen wandern: Knoten mit der Mitte darin, Rahmen ganz darin."""
        from core.node_frames import members
        node_ids, frame_ids = members(self.controller.project, frame.frame_id, self.node_boxes())
        return ([self.nodes[n] for n in node_ids if n in self.nodes],
                [self.frames[f] for f in frame_ids if f in self.frames])

    def frame_selection(self):
        """Strg+G: Rahmen um die ausgewählten Knoten."""
        from core.node_frames import around
        items = [i for i in self.selectedItems() if isinstance(i, NodeItem)]
        if not items:
            self.status_message.emit(tr("graph_frame_needs_selection"))
            return
        name = self._ask_frame_name()
        if name:
            self.controller.add_frame(around(self.node_boxes(items).values()), name)

    def add_frame_at(self, pos: QPointF):
        name = self._ask_frame_name()
        if name:
            self.controller.add_frame([pos.x(), pos.y(), 520.0, 320.0], name)

    def rename_frame(self, frame_id: str):
        from core.node_frames import frame
        group = frame(self.controller.project, frame_id)
        if group is None:
            return
        name, ok = QInputDialog.getText(None, tr("graph_frame_rename_title"), tr("graph_name_label"),
                                        text=group.name)
        if ok and name.strip():
            self.controller.set_frame(frame_id, "Rahmen umbenennen", name=name.strip())

    @staticmethod
    def _ask_frame_name() -> Optional[str]:
        name, ok = QInputDialog.getText(None, tr("graph_frame_new_title"), tr("graph_frame_new_label"),
                                        text=tr("graph_frame_default"))
        return name.strip() if ok and name.strip() else None

    def _fill_frame_menu(self, menu: QMenu, frame: "FrameItem"):
        from core.node_frames import FRAME_COLORS
        frame_id = frame.frame_id
        act = menu.addAction(tr("graph_frame_rename"))
        act.triggered.connect(lambda: self.rename_frame(frame_id))
        colors = menu.addMenu(tr("graph_color"))
        for color, key in zip(FRAME_COLORS, FRAME_COLOR_KEYS):
            name = tr("graph_color_" + key)
            pix = QtGui.QPixmap(14, 14)
            pix.fill(QtGui.QColor(color))
            act = colors.addAction(QtGui.QIcon(pix), name)
            act.setCheckable(True)
            act.setChecked(frame.color.name().upper() == color.upper())
            act.triggered.connect(lambda _c=False, c=color: self.controller.set_frame(
                frame_id, "Rahmenfarbe ändern", color=c))
        menu.addSeparator()
        act = menu.addAction(tr("graph_frame_delete"))
        act.triggered.connect(lambda: self.controller.remove_frames([frame_id]))

    def selected_frame_id(self) -> Optional[str]:
        """Der allein ausgewählte Rahmen (v1.15.1; keine Knoten dazu ausgewählt)."""
        items = self.selectedItems()
        frames = [i for i in items if isinstance(i, FrameItem)]
        return frames[0].frame_id if len(frames) == 1 and len(items) == 1 else None

    def selected_node_id(self) -> Optional[str]:
        nodes = [i for i in self.selectedItems() if isinstance(i, NodeItem)]
        return nodes[0].node_id if len(nodes) == 1 else None

    def select_node(self, node_id: Optional[str]):
        self.clearSelection()
        item = self.nodes.get(node_id)
        if item is not None:
            item.setSelected(True)

    def contextMenuEvent(self, event):
        pos = event.scenePos()
        wire = next((i for i in self.items(pos) if isinstance(i, WireItem)), None)
        node = self._node_at(pos)
        frame = next((i for i in self.items(pos) if isinstance(i, FrameItem)), None)   # Titel oder Kante
        menu = QMenu()

        if node is None and frame is not None:
            self._fill_frame_menu(menu, frame)
        elif node is None and wire is not None and not wire.implicit:
            act = menu.addAction(tr("graph_disconnect"))
            act.triggered.connect(lambda: self.controller.connect(wire.source, None))
        elif node is None and wire is not None:
            act = menu.addAction(tr("graph_default_return"))
            act.setEnabled(False)
        elif node is None:
            act = menu.addAction(tr("graph_new_film"))
            act.triggered.connect(lambda: self._prompt_new_film(pos))
            act = menu.addAction(tr("graph_new_menu"))
            act.triggered.connect(lambda: self._prompt_new_menu(pos))
            menu.addSeparator()
            act = menu.addAction(tr("graph_frame_here"))
            act.triggered.connect(lambda: self.add_frame_at(pos))
            act = menu.addAction(tr("graph_frame_around"))
            act.setEnabled(any(isinstance(i, NodeItem) for i in self.selectedItems()))
            act.triggered.connect(self.frame_selection)
            act_fit = menu.addAction(tr("graph_show_all"))
            act_fit.triggered.connect(lambda: [v.fit_all() for v in self.views() if hasattr(v, "fit_all")])
        else:
            self._fill_node_menu(menu, node, node.mapFromScene(pos), event.screenPos())

        if not menu.isEmpty():
            menu.exec(event.screenPos())
        event.accept()

    def _fill_node_menu(self, menu: QMenu, node: NodeItem, local: QPointF, screen: QtCore.QPoint):
        row = node.row_at(local.y())
        if row is not None and row.source is not None and \
                connection_target(self.controller.project, row.source) is not None:
            act = menu.addAction(tr("graph_disconnect"))
            act.triggered.connect(lambda: self.controller.connect(row.source, None))

        if node.kind == "film":
            film_id = node.node_id
            act = menu.addAction(tr("graph_film_rename"))
            act.triggered.connect(lambda: self._prompt_rename_node(film_id))
            menu.addSeparator()
            act = menu.addAction(tr("graph_film_delete"))
            act.triggered.connect(lambda: self.controller.remove_nodes([film_id]))
            return
        if node.kind != "menu":
            return
        menu_id = node.node_id
        if row is not None and row.kind == ROW_SUGGEST:
            self.fill_suggestion_menu(menu, row.suggestion, screen)
            menu.addSeparator()
        if row is not None and row.button_id is not None:
            act = menu.addAction(tr("graph_button_rename", name=row.text))
            act.triggered.connect(lambda: self._prompt_rename_button(menu_id, row.button_id, row.text))
            act = menu.addAction(tr("graph_button_remove", name=row.text))
            act.triggered.connect(lambda: self.controller.remove_button(menu_id, row.button_id))
            menu.addSeparator()
        act = menu.addAction(tr("graph_button_add"))
        act.triggered.connect(lambda: self._prompt_add_button(menu_id))
        act = menu.addAction(tr("graph_menu_rename"))
        act.triggered.connect(lambda: self._prompt_rename_node(menu_id))
        if not node.is_main:
            act = menu.addAction(tr("graph_set_main_menu"))
            act.triggered.connect(lambda: self.controller.connect(Source.start(), menu_id))
        menu.addSeparator()
        act = menu.addAction(tr("graph_menu_delete"))
        act.triggered.connect(lambda: self.controller.remove_menus([menu_id]))

    # --- Vorschläge und „＋ Button“ (Konzept 2.1, Regeln 2 und 3) ----------------
    def activate_suggestion(self, suggestion, screen: Optional[QtCore.QPoint] = None, dismissable: bool = True):
        """Vorschlag anlegen – mit Entscheidung über das Fenster an der Mausposition, sonst direkt."""
        from core.menu_templates import TemplateError
        from gui.node_editor.create_popup import activate_suggestion
        parent = self.views()[0] if self.views() else None
        try:
            created, text = activate_suggestion(self.controller, suggestion, screen or QtGui.QCursor.pos(),
                                                parent, dismissable)
        except TemplateError as e:
            self.status_message.emit(str(e))
            return
        if created:
            self._reveal_after_rebuild(created[0])
        self.status_message.emit(text)

    def fill_suggestion_menu(self, menu: QMenu, suggestion, screen: QtCore.QPoint):
        """Rechtsklick auf einen Vorschlag (Node-Ansicht und Viewer): anlegen oder „Nicht benötigt“."""
        from gui.node_editor.create_popup import dismiss_suggestion
        lang = ui_language()
        act = menu.addAction(tr("sugg_create", lang).format(label=suggestion.label))
        act.triggered.connect(lambda: self.activate_suggestion(suggestion, screen))
        act = menu.addAction(tr("sugg_dismiss", lang))
        act.triggered.connect(lambda: dismiss_suggestion(self.controller, suggestion))

    def offer_add(self, menu_id: str, screen: Optional[QtCore.QPoint] = None):
        """
        „＋ Button“: neuer Button und alles, was von diesem Menü aus möglich ist (Kapitel- und Sprachmenü je
        Film, Filmauswahl). Gibt es nichts anzubieten, gleich nach der Beschriftung fragen.
        """
        from core import menu_templates as mt
        menu = self.controller.project.menu(menu_id)
        offers = mt.button_offers(self.controller.project, menu) if menu is not None else []
        if not offers:
            self._prompt_add_button(menu_id)
            return
        choice = self._choose_offer(offers, screen or QtGui.QCursor.pos())
        if choice == "new":
            self._prompt_add_button(menu_id)
        elif choice is not None:
            self.activate_suggestion(choice, screen, dismissable=False)

    def _choose_offer(self, offers: list, screen: QtCore.QPoint):
        """Zeigt die Angebote von „＋ Button“ und gibt "new", den gewählten Vorschlag oder None zurück."""
        from core import menu_templates as mt
        project = self.controller.project
        lang = ui_language()
        menu = QMenu()
        menu.addAction(tr("offer_new_button", lang)).setData("new")
        menu.addSeparator()
        for offer in offers:
            film = project.film(offer.film_id)
            if offer.action == mt.ACTION_TITLES_MENU:
                text = tr("offer_titles", lang)
            elif offer.action == mt.ACTION_CHAPTER_MENU:
                text = tr("offer_chapters", lang).format(film=film.name)
            else:
                text = tr("offer_language", lang).format(film=film.name)
            menu.addAction(text).setData(offer)
        chosen = menu.exec(screen)
        return chosen.data() if chosen is not None else None

    def _reveal_after_rebuild(self, node_id: str):
        """Neu angelegten Knoten nach dem Neuaufbau auswählen und ins Bild holen."""
        self.rebuild()
        self.jump_to_node(node_id)

    def _prompt_new_film(self, pos: QPointF):
        name, ok = QInputDialog.getText(None, tr("graph_new_film"), tr("graph_film_name_label"),
                                        text=disc_label("Neuer Film", self.controller.project.settings.app_lang))
        if ok and name.strip():
            self.controller.add_film(name.strip(), (pos.x(), pos.y()))

    def _prompt_new_menu(self, pos: QPointF):
        name, ok = QInputDialog.getText(None, tr("graph_new_menu"), tr("graph_menu_name_label"),
                                        text=disc_label("Neues Menü", self.controller.project.settings.app_lang))
        if ok and name.strip():
            self.controller.add_menu(name.strip(), (pos.x(), pos.y()))

    def _prompt_add_button(self, menu_id: str):
        label, ok = QInputDialog.getText(None, tr("graph_new_button"), tr("graph_label_label"),
                                         text=disc_label("NEUER BUTTON", self.controller.project.settings.app_lang))
        if ok and label.strip():
            self.controller.add_nav_button(menu_id, label.strip())

    def _prompt_rename_node(self, node_id: str):
        node = self.controller.project.node(node_id)
        name, ok = QInputDialog.getText(None, tr("graph_rename_title"), tr("graph_new_name_label"),
                                        text=node.name if node else "")
        if ok:
            self.controller.rename_node(node_id, name)

    def _prompt_rename_button(self, menu_id: str, button_id: str, current: str):
        label, ok = QInputDialog.getText(None, tr("graph_button_rename_title"), tr("graph_label_label"),
                                         text=current)
        if ok:
            self.controller.rename_button(menu_id, button_id, label)

    # --- Hintergrund ----------------------------------------------------------
    def drawBackground(self, painter: QtGui.QPainter, rect: QRectF):
        painter.fillRect(rect, C_BG)
        step = 32
        left = int(rect.left()) - (int(rect.left()) % step)
        top = int(rect.top()) - (int(rect.top()) % step)
        painter.setPen(QtGui.QPen(C_GRID, 1.6))
        points = []
        x = left
        while x < rect.right():
            y = top
            while y < rect.bottom():
                points.append(QPointF(x, y))
                y += step
            x += step
        if len(points) < 40000:
            painter.drawPoints(points)
