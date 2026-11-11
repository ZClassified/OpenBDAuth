# gui/icons.py
"""
Eigene, einfarbige Symbole (v1.19.0) statt Emoji: Emoji sehen je nach System anders aus, sind bunt und gehen auf
farbigen Knöpfen unter. Alle Symbole werden in doppelter Auflösung gezeichnet (scharf auf hochauflösenden
Bildschirmen) und haben die Farbe ihrer Rolle: Prüfung rot / gelb / grau / grün, auf Amber dunkel.
"""

import os
import sys
from typing import List, Tuple

from PySide6 import QtGui
from PySide6.QtCore import Qt, QPointF, QRectF

SCALE = 2
LEVEL_ERROR, LEVEL_WARNING, LEVEL_INFO, LEVEL_OK = "error", "warning", "info", "ok"
LEVEL_COLORS = {LEVEL_ERROR: "#F87171", LEVEL_WARNING: "#FDE047", LEVEL_INFO: "#A1A1AA", LEVEL_OK: "#4ADE80"}
ON_COLOR = "#18181B"          # Schrift und Symbole auf Amber


def _canvas(width: float, height: float) -> Tuple[QtGui.QPixmap, QtGui.QPainter]:
    pixmap = QtGui.QPixmap(int(width * SCALE), int(height * SCALE))
    pixmap.setDevicePixelRatio(SCALE)
    pixmap.fill(Qt.transparent)
    p = QtGui.QPainter(pixmap)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    return pixmap, p


def _draw_level(p: QtGui.QPainter, level: str, x: float, y: float, s: float):
    """Symbol einer Prüf-Stufe im Quadrat (x, y, s): Fehler = Kreis mit Balken, Warnung = Dreieck mit
    Ausrufezeichen, Hinweis = Kreis mit „i“, bereit = Haken."""
    color = QtGui.QColor(LEVEL_COLORS[level])
    hole = QtGui.QColor(ON_COLOR)
    c = QPointF(x + s / 2, y + s / 2)
    p.setPen(Qt.NoPen)
    if level == LEVEL_ERROR:
        p.setBrush(color)
        p.drawEllipse(c, s / 2, s / 2)
        p.setBrush(hole)
        p.drawRoundedRect(QRectF(x + s * 0.24, y + s * 0.42, s * 0.52, s * 0.16), s * 0.05, s * 0.05)
    elif level == LEVEL_WARNING:
        tri = QtGui.QPainterPath()
        tri.moveTo(x + s / 2, y + s * 0.04)
        tri.lineTo(x + s * 0.98, y + s * 0.92)
        tri.lineTo(x + s * 0.02, y + s * 0.92)
        tri.closeSubpath()
        p.setBrush(color)
        p.setPen(QtGui.QPen(color, s * 0.08, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(tri)
        p.setPen(Qt.NoPen)
        p.setBrush(hole)
        p.drawRoundedRect(QRectF(x + s * 0.44, y + s * 0.32, s * 0.12, s * 0.34), s * 0.05, s * 0.05)
        p.drawEllipse(QPointF(x + s / 2, y + s * 0.77), s * 0.07, s * 0.07)
    elif level == LEVEL_INFO:
        p.setBrush(color)
        p.drawEllipse(c, s / 2, s / 2)
        p.setBrush(hole)
        p.drawEllipse(QPointF(x + s / 2, y + s * 0.28), s * 0.075, s * 0.075)
        p.drawRoundedRect(QRectF(x + s * 0.44, y + s * 0.42, s * 0.12, s * 0.34), s * 0.05, s * 0.05)
    else:
        p.setBrush(Qt.NoBrush)
        p.setPen(QtGui.QPen(color, s * 0.16, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        check = QtGui.QPainterPath(QPointF(x + s * 0.12, y + s * 0.54))
        check.lineTo(x + s * 0.40, y + s * 0.80)
        check.lineTo(x + s * 0.88, y + s * 0.22)
        p.drawPath(check)


def level_icon(level: str, size: int = 14) -> QtGui.QIcon:
    pixmap, p = _canvas(size, size)
    _draw_level(p, level, 0, 0, size)
    p.end()
    return QtGui.QIcon(pixmap)


def counts_pixmap(counts: List[Tuple[str, int]], font: QtGui.QFont, size: int = 14) -> QtGui.QPixmap:
    """Plakette der oberen Leiste: Symbol und Anzahl je Stufe, z. B. Fehler 2 · Warnung 3 (Zahl in der Farbe
    der Stufe)."""
    metrics = QtGui.QFontMetricsF(font)
    gap, between = 5, 12
    widths = [size + gap + metrics.horizontalAdvance(str(n)) for _, n in counts]
    width = sum(widths) + between * (len(counts) - 1)
    height = max(size, metrics.height())
    pixmap, p = _canvas(width + 1, height)
    p.setFont(font)
    x = 0.0
    for (level, n), w in zip(counts, widths):
        _draw_level(p, level, x, (height - size) / 2, size)
        p.setPen(QtGui.QColor(LEVEL_COLORS[level]))
        p.drawText(QRectF(x + size + gap, 0, w - size - gap + 1, height), Qt.AlignLeft | Qt.AlignVCenter, str(n))
        x += w + between
    p.end()
    return pixmap


def start_icon(size: int = 14) -> QtGui.QIcon:
    """Dreieck „Start“ für den Hauptknopf: dunkel auf Amber, grau, solange er gesperrt ist."""
    icon = QtGui.QIcon()
    for color, mode in ((ON_COLOR, QtGui.QIcon.Normal), ("#71717A", QtGui.QIcon.Disabled)):
        pixmap, p = _canvas(size, size)
        p.setPen(QtGui.QPen(QtGui.QColor(color), size * 0.1, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(QtGui.QColor(color))
        tri = QtGui.QPolygonF([QPointF(size * 0.22, size * 0.12), QPointF(size * 0.88, size * 0.5),
                               QPointF(size * 0.22, size * 0.88)])
        p.drawPolygon(tri)
        p.end()
        icon.addPixmap(pixmap, mode)
    return icon


def format_icon(kind: str, size: int = 16) -> QtGui.QIcon:
    """Format-Knöpfe in „Disc erstellen“: „folder“ oder „disc“. Farbe wie die Schrift des Knopfs: gedämpft, beim
    Überfahren hell, angewählt dunkel auf Amber."""
    icon = QtGui.QIcon()
    for color, mode, state in (("#A1A1AA", QtGui.QIcon.Normal, QtGui.QIcon.Off),
                               ("#FAFAFA", QtGui.QIcon.Active, QtGui.QIcon.Off),
                               (ON_COLOR, QtGui.QIcon.Normal, QtGui.QIcon.On),
                               (ON_COLOR, QtGui.QIcon.Active, QtGui.QIcon.On)):
        icon.addPixmap(_format_pixmap(kind, color, size), mode, state)
    return icon


def _format_pixmap(kind: str, color: str, size: int) -> QtGui.QPixmap:
    pixmap, p = _canvas(size, size)
    k = size / 16
    p.setPen(Qt.NoPen)
    p.setBrush(QtGui.QColor(color))
    path = QtGui.QPainterPath()
    if kind == "folder":
        # Ordner mit Reiter oben links
        path.addRoundedRect(QRectF(1 * k, 4.5 * k, 14 * k, 9.5 * k), 1.5 * k, 1.5 * k)
        path.addRoundedRect(QRectF(1 * k, 2.5 * k, 6 * k, 4 * k), 1.2 * k, 1.2 * k)
        p.drawPath(path.simplified())
    else:
        # Scheibe mit Loch in der Mitte
        path.setFillRule(Qt.OddEvenFill)
        path.addEllipse(QPointF(8 * k, 8 * k), 7 * k, 7 * k)
        path.addEllipse(QPointF(8 * k, 8 * k), 2 * k, 2 * k)
        p.drawPath(path)
    p.end()
    return pixmap


KIND_COLOR = "#D4D4D8"


def job_kind_icon(kind: str, size: int = 16) -> QtGui.QIcon:
    """Art eines Auftrags in Vorbereiten (v1.22): „2d“ = ein Bild, „3d“ = zwei versetzte Bilder (zwei Augen),
    „audio“ = Pegelbalken. In der markierten (amberfarbenen) Zeile dunkel statt von Qt eingefärbt."""
    icon = QtGui.QIcon()
    icon.addPixmap(_job_kind_pixmap(kind, KIND_COLOR, size), QtGui.QIcon.Normal)
    icon.addPixmap(_job_kind_pixmap(kind, ON_COLOR, size), QtGui.QIcon.Selected)
    return icon


def _job_kind_pixmap(kind: str, color_name: str, size: int) -> QtGui.QPixmap:
    pixmap, p = _canvas(size, size)
    k = size / 16
    color = QtGui.QColor(color_name)
    pen = QtGui.QPen(color, 1.4 * k, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    if kind == "audio":
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        for i, h in enumerate((5, 10, 14, 8, 4)):
            p.drawRoundedRect(QRectF((1.5 + i * 2.8) * k, (8 - h / 2) * k, 1.8 * k, h * k), 0.9 * k, 0.9 * k)
    elif kind == "3d":
        p.setBrush(Qt.NoBrush)
        p.setPen(pen)
        p.drawRoundedRect(QRectF(1.2 * k, 2.2 * k, 10 * k, 7.5 * k), 1.5 * k, 1.5 * k)
        p.setBrush(color)
        p.drawRoundedRect(QRectF(4.8 * k, 6.3 * k, 10 * k, 7.5 * k), 1.5 * k, 1.5 * k)
    else:
        p.setBrush(Qt.NoBrush)
        p.setPen(pen)
        p.drawRoundedRect(QRectF(1.2 * k, 3.2 * k, 13.6 * k, 9.6 * k), 1.5 * k, 1.5 * k)
    p.end()
    return pixmap


OPEN_COLOR = "#FBBF24"


def settings_mark_icon(confirmed: bool, size: int = 14) -> QtGui.QIcon:
    """Vorbereiten (v1.23), links in der Auftragsliste: Ring = Einstellungen noch nicht festgelegt (Amber),
    Haken = festgelegt (hell). In der markierten Zeile dunkel."""
    icon = QtGui.QIcon()
    for color, mode in (((KIND_COLOR if confirmed else OPEN_COLOR), QtGui.QIcon.Normal), (ON_COLOR, QtGui.QIcon.Selected)):
        pixmap, p = _canvas(size, size)
        s = size
        p.setBrush(Qt.NoBrush)
        if confirmed:
            p.setPen(QtGui.QPen(QtGui.QColor(color), s * 0.14, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            check = QtGui.QPainterPath(QPointF(s * 0.16, s * 0.54))
            check.lineTo(s * 0.42, s * 0.78)
            check.lineTo(s * 0.86, s * 0.24)
            p.drawPath(check)
        else:
            p.setPen(QtGui.QPen(QtGui.QColor(color), s * 0.14))
            p.drawEllipse(QPointF(s / 2, s / 2), s * 0.32, s * 0.32)
        p.end()
        icon.addPixmap(pixmap, mode)
    return icon


def _history_pixmap(redo: bool, color: str, size: int) -> QtGui.QPixmap:
    """Gebogener Pfeil nach links (Rückgängig) bzw. rechts (Wiederholen)."""
    pixmap, p = _canvas(size, size)
    pen = QtGui.QPen(QtGui.QColor(color), size * 0.11, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    s = size
    if redo:                                    # gespiegelt zeichnen
        p.translate(s, 0)
        p.scale(-1, 1)
    path = QtGui.QPainterPath(QPointF(s * 0.28, s * 0.38))
    path.lineTo(s * 0.62, s * 0.38)
    path.arcTo(QRectF(s * 0.42, s * 0.38, s * 0.40, s * 0.40), 90, -180)
    path.lineTo(s * 0.40, s * 0.78)
    p.drawPath(path)
    head = QtGui.QPainterPath(QPointF(s * 0.42, s * 0.20))
    head.lineTo(s * 0.24, s * 0.38)
    head.lineTo(s * 0.42, s * 0.56)
    p.drawPath(head)
    p.end()
    return pixmap


def history_icon(redo: bool = False, size: int = 18) -> QtGui.QIcon:
    """Rückgängig/Wiederholen für die obere Leiste (v1.29.0), ausgegraut, wenn es nichts zu tun gibt."""
    icon = QtGui.QIcon()
    icon.addPixmap(_history_pixmap(redo, "#D4D4D8", size), QtGui.QIcon.Normal)
    icon.addPixmap(_history_pixmap(redo, "#FAFAFA", size), QtGui.QIcon.Active)
    icon.addPixmap(_history_pixmap(redo, "#52525B", size), QtGui.QIcon.Disabled)
    return icon


def dot_icon(color: str = "#FBBF24", size: int = 10) -> QtGui.QIcon:
    """Punkt für ungespeicherte Änderungen neben dem Projektnamen (v1.29.0)."""
    pixmap, p = _canvas(size, size)
    p.setPen(Qt.NoPen)
    p.setBrush(QtGui.QColor(color))
    p.drawEllipse(QRectF(size * 0.15, size * 0.15, size * 0.7, size * 0.7))
    p.end()
    return QtGui.QIcon(pixmap)


ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "icon")
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def app_icon() -> QtGui.QIcon:
    """Programm-Icon (v1.19.3, Vorlage: design/OpenBDAuth Icon v1.svg) in allen Größen für Fenster und Taskleiste."""
    icon = QtGui.QIcon()
    for size in ICON_SIZES:
        icon.addFile(os.path.join(ICON_DIR, f"openbdauth_{size}.png"))
    return icon


def use_app_icon(app):
    """Icon für alle Fenster setzen. Unter Windows zusätzlich eine eigene App-ID, damit die Taskleiste das Icon
    zeigt statt des Python-Symbols (beim Start aus dem Quellcode)."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("OpenBDAuth.App")
        except (AttributeError, OSError):
            pass
    app.setWindowIcon(app_icon())
