# gui/node_editor/view.py
"""Zoom- und verschiebbare Ansicht für den Node-Graph."""

from PySide6 import QtGui
from PySide6.QtCore import Qt, QRectF, QPointF, QSize, QTimer
from PySide6.QtWidgets import QGraphicsView, QToolButton

from gui.node_editor.scene import NodeScene, NodeItem, FrameItem

MIN_ZOOM = 0.25
MAX_ZOOM = 2.5
FIT_BUTTON = 34


def fit_icon(size: int = 20, color: str = "#D4D4D8") -> QtGui.QIcon:
    """Symbol „alles einpassen“: vier Ecken, die einen Rahmen bilden."""
    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    p = QtGui.QPainter(pixmap)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    pen = QtGui.QPen(QtGui.QColor(color), 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    m, arm = 2.5, size * 0.24          # kurze Ecken: klar als Eck-Klammern erkennbar, nicht als Quadrat
    lo, hi = m, size - m
    for (x, y, dx, dy) in ((lo, lo, 1, 1), (hi, lo, -1, 1), (lo, hi, 1, -1), (hi, hi, -1, -1)):
        p.drawLine(QPointF(x, y), QPointF(x + dx * arm, y))
        p.drawLine(QPointF(x, y), QPointF(x, y + dy * arm))
    p.end()
    return QtGui.QIcon(pixmap)


def returns_icon(markers: bool, size: int = 20, color: str = "#D4D4D8") -> QtGui.QIcon:
    """
    Symbol für die Darstellung der Rücksprünge – zeigt die aktuelle Art:
    Linien: gestrichelter Bogen, der nach links zurückläuft; Sprungmarken: Etikett mit Rückpfeil.
    """
    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    p = QtGui.QPainter(pixmap)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    c = QtGui.QColor(color)
    if not markers:
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawEllipse(QPointF(18, 5.5), 1.7, 1.7)          # Anschluss, von dem der Rücksprung ausgeht
        p.setBrush(Qt.NoBrush)
        pen = QtGui.QPen(c, 1.9, Qt.CustomDashLine, Qt.FlatCap, Qt.RoundJoin)
        pen.setDashPattern([1.6, 1.3])
        p.setPen(pen)
        path = QtGui.QPainterPath(QPointF(18, 7.5))
        path.cubicTo(QPointF(18, 20), QPointF(2.5, 20), QPointF(2.5, 7.5))
        p.drawPath(path)
        p.setPen(QtGui.QPen(c, 1.9, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawLine(QPointF(2.5, 3.5), QPointF(0.4, 6.8))      # Pfeilspitze nach oben
        p.drawLine(QPointF(2.5, 3.5), QPointF(4.6, 6.8))
        p.drawLine(QPointF(2.5, 3.5), QPointF(2.5, 7.5))
    else:
        tag = QtGui.QPainterPath()
        tag.moveTo(1.5, 10)
        tag.lineTo(6, 5)
        tag.lineTo(18.5, 5)
        tag.lineTo(18.5, 15)
        tag.lineTo(6, 15)
        tag.closeSubpath()
        p.setPen(QtGui.QPen(c, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(tag)
        hook = QtGui.QPainterPath(QPointF(15, 8))
        hook.lineTo(15, 11.5)
        hook.lineTo(9, 11.5)
        p.drawPath(hook)
        p.drawLine(QPointF(9, 11.5), QPointF(11, 9.8))
        p.drawLine(QPointF(9, 11.5), QPointF(11, 13.2))
    p.end()
    return QtGui.QIcon(pixmap)


class NodeView(QGraphicsView):
    def __init__(self, scene: NodeScene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.TextAntialiasing)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("border: 1px solid #27272A; border-radius: 8px;")
        self.setAcceptDrops(True)
        self._panning = False
        self._pan_start = None
        self._space_down = False
        # „Alles anzeigen“ vor dem Anzeigen: erst ausführen, wenn die Ansicht ihre endgültige Größe hat
        # (Fenster maximiert, Docks wiederhergestellt) – bis der Nutzer selbst zoomt oder klickt.
        self._fit_pending = False

        # Symbol-Knopf oben rechts: alles anzeigen (auch Taste F)
        self.fit_button = QToolButton(self)
        self.fit_button.setIcon(fit_icon())
        self.fit_button.setIconSize(QSize(18, 18))
        self.fit_button.setFixedSize(FIT_BUTTON, FIT_BUTTON)
        self.fit_button.setCursor(Qt.PointingHandCursor)
        self.fit_button.setStyleSheet(
            "QToolButton { background-color: rgba(22, 29, 42, 225); border: 1px solid #3F3F46; border-radius: 8px; }"
            "QToolButton:hover { background-color: #34343A; border-color: #FBBF24; }"
            "QToolButton:pressed { background-color: #1C1C1F; }")
        self.fit_button.clicked.connect(self.fit_all)

        # Umschalter links daneben: Rücksprünge als Linien oder Sprungmarken (Aktion setzt das Hauptfenster)
        self.returns_button = QToolButton(self)
        self.returns_button.setIconSize(QSize(18, 18))
        self.returns_button.setFixedSize(FIT_BUTTON, FIT_BUTTON)
        self.returns_button.setCursor(Qt.PointingHandCursor)
        self.returns_button.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.returns_button.setStyleSheet(self.fit_button.styleSheet() +
                                          "QToolButton:checked { background-color: #3D3218; border-color: #FBBF24; }")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_button.move(self.width() - FIT_BUTTON - 12, 12)
        self.returns_button.move(self.width() - 2 * FIT_BUTTON - 20, 12)
        if self._fit_pending and self.isVisible():
            self._fit_now()

    def showEvent(self, event):
        super().showEvent(event)
        if self._fit_pending:
            QTimer.singleShot(0, self._fit_now)

    # --- Zoom -----------------------------------------------------------------
    def zoom(self) -> float:
        return self.transform().m11()

    def wheelEvent(self, event):
        self._fit_pending = False
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        new_zoom = self.zoom() * factor
        if MIN_ZOOM <= new_zoom <= MAX_ZOOM:
            self.scale(factor, factor)
        event.accept()

    def fit_all(self):
        if not self.isVisible():
            self._fit_pending = True
            return
        self._fit_now()

    def _fit_now(self):
        items = [i for i in self.scene().items() if isinstance(i, (NodeItem, FrameItem))]
        if not items:
            return
        rect = QRectF()
        for item in items:
            rect = rect.united(item.sceneBoundingRect())
        rect.adjust(-80, -80, 80, 200)
        self.fitInView(rect, Qt.KeepAspectRatio)
        if self.zoom() > 1.0:
            self.resetTransform()
            self.centerOn(rect.center())
        elif self.zoom() < MIN_ZOOM:
            self.resetTransform()
            self.scale(MIN_ZOOM, MIN_ZOOM)
            self.centerOn(rect.center())

    # --- Verschieben (mittlere Maustaste oder Leertaste + Ziehen) ------------------
    def mousePressEvent(self, event):
        self._fit_pending = False
        if event.button() == Qt.MiddleButton or (event.button() == Qt.LeftButton and self._space_down):
            self._panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(delta.y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._panning and event.button() in (Qt.MiddleButton, Qt.LeftButton):
            self._panning = False
            self.setCursor(Qt.OpenHandCursor if self._space_down else Qt.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        self._fit_pending = False
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._space_down = True
            self.setCursor(Qt.OpenHandCursor)
            event.accept()
            return
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.scene().delete_selected()
            event.accept()
            return
        if event.key() == Qt.Key_G and event.modifiers() == Qt.ControlModifier:
            self.scene().frame_selection()      # Rahmen um die Auswahl (v1.15.0)
            event.accept()
            return
        if event.key() == Qt.Key_F and not event.modifiers():
            self.fit_all()
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._space_down = False
            self.setCursor(Qt.ArrowCursor)
            event.accept()
            return
        super().keyReleaseEvent(event)
