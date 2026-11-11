# gui/studio/backgrounds.py
"""
Hintergrund-Dateien für ein Menü übernehmen (v1.13.2): aus dem Inspektor (Wählen, Hineinziehen), per Drag & Drop
auf den Viewer oder auf den Menü-Knoten. Es gilt immer das Menü, auch wenn gerade ein Button ausgewählt ist.
"""

import os
from typing import List, Optional, Tuple

from core import disc_edit


def background_files(files: List[str]) -> List[Tuple[str, str]]:
    """(Feld, Pfad) für alle Dateien, die als Hintergrund taugen (Bild, Video, Musik)."""
    found = []
    for path in files:
        field = disc_edit.background_field(path)
        if field is not None:
            found.append((field, path))
    return found


def _loop_duration(controller, menu_id: str, field: str, path: str) -> Optional[float]:
    """Loop-Dauer wie bisher: aus dem Video bzw. aus der Musik, wenn das Menü dann kein Video zeigt."""
    from core.disc_adapter import effective_background
    project = controller.project
    menu = project.menu(menu_id)
    if field == disc_edit.BG_AUDIO and menu is not None and effective_background(project, menu).video:
        return None
    if field not in (disc_edit.BG_VIDEO, disc_edit.BG_AUDIO):
        return None
    from modules.menu_author import probe_media_duration
    films = project.films
    fps = films[0].fps if films else 23.976
    duration = probe_media_duration(path, fps=fps) if field == disc_edit.BG_VIDEO else probe_media_duration(path)
    return float(duration) if duration and duration >= 2.0 else None


def set_background_file(controller, menu_id: str, field: str, path: str):
    controller.set_background_file(menu_id, field, path, _loop_duration(controller, menu_id, field, path))


def apply_background_files(controller, menu_id: str, files: List[str]) -> List[str]:
    """Übernimmt Bild, Video und Musik aus files als Hintergrund des Menüs (ein Rückgängig-Schritt).
    Gibt die Namen der Dateien zurück, die sich nicht als Hintergrund eignen."""
    usable = background_files(files)
    rejected = [os.path.basename(p) for p in files if p not in {path for _f, path in usable}]
    if usable and controller.project.menu(menu_id) is not None:
        controller.undo_stack.beginMacro("Hintergrund wählen")
        for field, path in usable:
            set_background_file(controller, menu_id, field, path)
        controller.undo_stack.endMacro()
    return rejected
