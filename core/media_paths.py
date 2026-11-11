# core/media_paths.py
"""
Mediendateien eines Projekts (v1.17.0): Pfade relativ speichern, beim Laden wiederfinden, neu verknüpfen.

Im Speicher sind alle Pfade absolut – Oberfläche und Export sehen nichts von dieser Umrechnung.
- Speichern: Pfade auf demselben Laufwerk wie die .bdproj werden relativ zu ihrem Ordner geschrieben
  („../../D4A Cover/Menü.jpg“); auf einem anderen Laufwerk bleiben sie absolut.
- Laden: relativer Pfad → absoluter Pfad → derselbe Pfad auf dem Laufwerk der Projektdatei. So findet ein
  Projekt seine Dateien auch dann, wenn die externe SSD an einem anderen Rechner einen anderen Buchstaben hat.
- Neu verknüpfen: fehlende Dateien in einem Ordner (samt Unterordnern) nach Dateinamen suchen.
Qt-frei und damit ohne Oberfläche testbar.
"""

import copy
import ntpath
import os
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from core.translations import tr
from core.disc_model import DiscProject

# Arten von Mediendateien
MEDIA_VIDEO = "video_base"
MEDIA_VIDEO_MVC = "video_mvc"
MEDIA_AUDIO = "audio"
MEDIA_SUBTITLE = "subtitle"
MEDIA_BG_IMAGE = "image"
MEDIA_BG_VIDEO = "video"
MEDIA_BG_AUDIO = "audio_bg"

_BG_FIELDS = {MEDIA_BG_IMAGE: "image", MEDIA_BG_VIDEO: "video", MEDIA_BG_AUDIO: "audio"}

# Ordner, die bei der Suche übersprungen werden (Papierkorb, Systemordner)
_SKIP_DIRS = {"$recycle.bin", "system volume information", "found.000", "__pycache__"}


@dataclass(frozen=True)
class MediaRef:
    """Eine Mediendatei im Projekt: Art, Film bzw. Menü, Spur (nur bei Ton/Untertiteln) und Pfad."""
    kind: str
    owner_id: str
    track_id: Optional[str]
    path: str

    @property
    def key(self) -> Tuple[str, str, Optional[str]]:
        return self.kind, self.owner_id, self.track_id


# -------------------------------------------------------------------------
# Mediendateien im Projekt
# -------------------------------------------------------------------------

def media_refs(project: DiscProject) -> List[MediaRef]:
    """Alle eingetragenen Mediendateien (ohne Zielordner) in der Reihenfolge Filme, dann Menüs."""
    refs = []
    for film in project.films:
        for kind in (MEDIA_VIDEO, MEDIA_VIDEO_MVC):
            path = getattr(film, kind)
            if path:
                refs.append(MediaRef(kind, film.id, None, path))
        for kind, tracks in ((MEDIA_AUDIO, film.audio_tracks), (MEDIA_SUBTITLE, film.subtitle_tracks)):
            refs.extend(MediaRef(kind, film.id, t.id, t.path) for t in tracks if t.path)
    for menu in project.menus:
        for kind, field in _BG_FIELDS.items():
            path = getattr(menu.background, field)
            if path:
                refs.append(MediaRef(kind, menu.id, None, path))
    return refs


def set_media_path(project: DiscProject, key: Tuple[str, str, Optional[str]], path: str) -> bool:
    """Trägt einen neuen Pfad für die Mediendatei key (MediaRef.key) ein; False, wenn es sie nicht mehr gibt."""
    kind, owner_id, track_id = key
    if kind in _BG_FIELDS:
        menu = project.menu(owner_id)
        if menu is None:
            return False
        setattr(menu.background, _BG_FIELDS[kind], path)
        return True
    film = project.film(owner_id)
    if film is None:
        return False
    if kind in (MEDIA_VIDEO, MEDIA_VIDEO_MVC):
        setattr(film, kind, path)
        return True
    tracks = film.audio_tracks if kind == MEDIA_AUDIO else film.subtitle_tracks
    for track in tracks:
        if track.id == track_id:
            track.path = path
            return True
    return False


def media_label(project: DiscProject, ref: MediaRef) -> str:
    """Wofür die Datei gebraucht wird, z. B. „Hauptfilm – Tonspur 2“ oder „Menü Audio – Hintergrundbild“."""
    if ref.kind in _BG_FIELDS:
        menu = project.menu(ref.owner_id)
        what = tr({MEDIA_BG_IMAGE: "media_bg_image", MEDIA_BG_VIDEO: "media_bg_video",
                   MEDIA_BG_AUDIO: "media_bg_audio"}[ref.kind])
        return f"{menu.name if menu else '?'} – {what}"
    film = project.film(ref.owner_id)
    name = film.name if film else "?"
    if ref.kind == MEDIA_VIDEO:
        return tr("media_video", name=name)
    if ref.kind == MEDIA_VIDEO_MVC:
        return tr("media_video_mvc", name=name)
    if ref.kind == MEDIA_AUDIO:
        index = film.audio_index(ref.track_id) if film else None
        return tr("media_audio", name=name, n=index + 1 if index is not None else "?")
    index = film.subtitle_index(ref.track_id) if film else None
    return tr("media_subtitle", name=name, n=index + 1 if index is not None else "?")


def is_missing(path: Optional[str]) -> bool:
    """Eingetragen, aber nicht (mehr) vorhanden."""
    return bool(path) and not os.path.isfile(path)


def missing_media(project: DiscProject) -> List[MediaRef]:
    return [ref for ref in media_refs(project) if is_missing(ref.path)]


def _map_paths(project: DiscProject, fn: Callable[[str], str]):
    """Wendet fn auf jede Mediendatei und den Zielordner an (in place)."""
    for ref in media_refs(project):
        set_media_path(project, ref.key, fn(ref.path))
    if project.settings.output_path:
        project.settings.output_path = fn(project.settings.output_path)


# -------------------------------------------------------------------------
# Speichern und Laden
# -------------------------------------------------------------------------

def _clean(path: str) -> str:
    """Normalisiert und schreibt wie die Dateidialoge von Qt mit „/“."""
    path = os.path.normpath(path)
    return path.replace(os.sep, "/") if os.sep != "/" else path


def to_stored(path: str, project_dir: str) -> str:
    """Pfad für die Projektdatei: relativ zum Projektordner, wenn möglich (gleiches Laufwerk), sonst absolut."""
    if not path or not os.path.isabs(path):
        return path
    try:
        return _clean(os.path.relpath(path, project_dir))
    except ValueError:   # anderes Laufwerk (Windows)
        return _clean(path)


def resolve_stored(stored: str, project_dir: str) -> str:
    """
    Absoluter Pfad zu einem gespeicherten Pfad: relativ zum Projektordner; ein absoluter Pfad, den es nicht gibt,
    wird auf dem Laufwerk der Projektdatei gesucht. Wird nichts gefunden, bleibt der erste Kandidat.
    """
    if not stored:
        return stored
    # Windows-Pfade (C:/…) aus einem Projekt von Windows sind auch unter Linux und macOS absolut: Sie bleiben
    # stehen und erscheinen als fehlend, statt an den Projektordner gehängt zu werden
    if not os.path.isabs(stored) and not ntpath.isabs(stored):
        return _clean(os.path.join(project_dir, stored))
    if os.path.isfile(stored) or os.path.isdir(stored):
        return _clean(stored)
    drive, rest = os.path.splitdrive(stored)
    own_drive = os.path.splitdrive(os.path.abspath(project_dir))[0]
    if drive and own_drive and drive.lower() != own_drive.lower():
        moved = own_drive + rest
        if os.path.isfile(moved) or os.path.isdir(moved):
            return _clean(moved)
    return _clean(stored)


def project_for_file(project: DiscProject, filepath: str) -> DiscProject:
    """Kopie des Projekts mit Pfaden, wie sie in die Datei filepath geschrieben werden."""
    stored = copy.deepcopy(project)
    project_dir = os.path.dirname(os.path.abspath(filepath))
    _map_paths(stored, lambda p: to_stored(p, project_dir))
    return stored


def resolve_project_paths(project: DiscProject, filepath: str):
    """Macht nach dem Laden aus filepath alle gespeicherten Pfade absolut (in place)."""
    project_dir = os.path.dirname(os.path.abspath(filepath))
    _map_paths(project, lambda p: resolve_stored(p, project_dir))


# -------------------------------------------------------------------------
# Neu verknüpfen
# -------------------------------------------------------------------------

@dataclass
class RelinkResult:
    found: Dict[Tuple[str, str, Optional[str]], str]           # MediaRef.key → neuer Pfad
    ambiguous: Dict[Tuple[str, str, Optional[str]], List[str]]  # mehrere gleich gute Treffer
    not_found: List[Tuple[str, str, Optional[str]]]


def index_folder(folder: str, progress: Optional[Callable[[], None]] = None) -> Dict[str, List[str]]:
    """Dateiname (klein) → alle Pfade im Ordner und seinen Unterordnern; Papierkorb und Systemordner fehlen."""
    index: Dict[str, List[str]] = {}
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d.lower() not in _SKIP_DIRS and not d.startswith(".")]
        for name in files:
            index.setdefault(name.lower(), []).append(_clean(os.path.join(root, name)))
        if progress is not None:
            progress()
    return index


def _parts(path: str) -> List[str]:
    """Bestandteile eines Pfads ohne Laufwerk, klein geschrieben."""
    rest = os.path.splitdrive(path.replace("\\", "/"))[1]
    return [p.lower() for p in rest.split("/") if p]


def _common_tail(a: List[str], b: List[str]) -> int:
    n = 0
    while n < min(len(a), len(b)) and a[-1 - n] == b[-1 - n]:
        n += 1
    return n


def _lower(path: str) -> str:
    return path.replace("\\", "/").rstrip("/").lower()


def _prefix(path: str, tail: int) -> str:
    """Der Teil von path vor den letzten tail Bestandteilen (klein, mit „/“)."""
    parts = _lower(path).split("/")
    return "/".join(parts[:len(parts) - tail])


def plan_relink(refs: List[MediaRef], index: Dict[str, List[str]]) -> RelinkResult:
    """
    Sucht zu jeder fehlenden Datei einen Ersatz gleichen Namens. Bei mehreren Treffern gewinnt der, dessen
    Ordnerstruktur am längsten mit dem alten Pfad übereinstimmt; bei Gleichstand der, der zur Verschiebung
    passt, die die eindeutigen Treffer zeigen (alter Ordner → neuer Ordner). Sonst bleibt die Wahl offen.
    """
    found, ties = {}, {}
    moves = set()   # (alter Ordner, neuer Ordner) aus eindeutigen Treffern
    not_found = []
    for ref in refs:
        old = _parts(ref.path)
        candidates = index.get(old[-1], []) if old else []
        if not candidates:
            not_found.append(ref.key)
            continue
        scored = sorted(((_common_tail(old, _parts(c)), c) for c in candidates), key=lambda s: -s[0])
        best = [c for score, c in scored if score == scored[0][0]]
        if len(best) == 1:
            found[ref.key] = best[0]
            tail = scored[0][0]
            moves.add((_prefix(ref.path, tail), _prefix(best[0], tail)))
        else:
            ties[ref.key] = (ref, best)
    ambiguous = {}
    for key, (ref, best) in ties.items():
        moved = {new + _lower(ref.path)[len(old):] for old, new in moves if _lower(ref.path).startswith(old + "/")}
        fits = [c for c in best if _lower(c) in moved]
        if len(fits) == 1:
            found[key] = fits[0]
        else:
            ambiguous[key] = best
    return RelinkResult(found, ambiguous, not_found)


def apply_relink(project: DiscProject, paths: Dict[Tuple[str, str, Optional[str]], str]):
    """Trägt die neuen Pfade ein (in place)."""
    for key, path in paths.items():
        set_media_path(project, key, path)
