# modules/external_tools.py
"""
Externe Werkzeuge (v1.19.1): ffmpeg, ffprobe und tsMuxeR finden, ohne dass der Nutzer etwas installieren oder
in den PATH eintragen muss (gemeinsamer Plan mit BD3DEnc).

Suchreihenfolge:
  1. tools/<plattform>/ neben dem Programm (windows, macos, linux) – so liegen sie im fertigen Paket
  2. tools/ neben dem Programm (bisheriges Muster für tsMuxeR)
  3. PATH
„Neben dem Programm“ ist der Projektordner beim Start aus dem Quellcode, im PyInstaller-Paket der Ordner der
EXE und der Bundle-Ordner (sys._MEIPASS).
"""

import os
import shutil
import subprocess
import sys
from typing import Dict, List, Optional, Sequence

FFMPEG, FFPROBE, TSMUXER = "ffmpeg", "ffprobe", "tsmuxer"

# Dateinamen je Werkzeug (ohne Endung; unter Windows wird .exe angehängt)
TOOL_NAMES: Dict[str, List[str]] = {
    FFMPEG: ["ffmpeg"],
    FFPROBE: ["ffprobe"],
    TSMUXER: ["tsMuxeR", "tsmuxer"],
}
REQUIRED = (FFMPEG, FFPROBE, TSMUXER)

# Für subprocess-Aufrufe der Werkzeuge (v1.19.2): im Paket ohne Konsole kein aufblitzendes Fenster und keine
# Tastatur-Eingabe, auf die ffmpeg sonst warten könnte.
NO_CONSOLE = {"stdin": subprocess.DEVNULL,
              "creationflags": subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0}


class ToolMissingError(FileNotFoundError):
    """Ein Werkzeug fehlt. Unterklasse von FileNotFoundError, damit bestehende Fehlerbehandlung greift."""

    def __init__(self, tool: str):
        super().__init__(f"{tool} wurde nicht gefunden (erwartet in {tools_folder_hint()} oder im PATH).")
        self.tool = tool


def platform_dir() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def app_roots() -> List[str]:
    """Ordner, neben denen tools/ gesucht wird."""
    roots = []
    if getattr(sys, "frozen", False):
        roots.append(os.path.dirname(sys.executable))
        bundle = getattr(sys, "_MEIPASS", None)
        if bundle:
            roots.append(bundle)
    roots.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # Projektordner
    return list(dict.fromkeys(roots))


def tools_folder_hint() -> str:
    return os.path.join("tools", platform_dir())


def _file_names(tool: str) -> List[str]:
    names = TOOL_NAMES.get(tool, [tool])
    if os.name == "nt":
        return [n + ".exe" for n in names]
    return names


def find_tool(tool: str, roots: Optional[Sequence[str]] = None, use_path: bool = True) -> Optional[str]:
    """Absoluter Pfad des Werkzeugs oder None."""
    roots = app_roots() if roots is None else roots
    for folder in [os.path.join(r, "tools", platform_dir()) for r in roots] + [os.path.join(r, "tools") for r in roots]:
        for name in _file_names(tool):
            candidate = os.path.join(folder, name)
            if os.path.isfile(candidate):
                return candidate
    if use_path:
        for name in TOOL_NAMES.get(tool, [tool]):
            found = shutil.which(name)
            if found:
                return found
    return None


def tool_path(tool: str) -> str:
    """Wie find_tool, aber mit verständlichem Fehler, wenn das Werkzeug fehlt."""
    path = find_tool(tool)
    if path is None:
        raise ToolMissingError(tool)
    return path


def missing_tools(tools: Sequence[str] = REQUIRED) -> List[str]:
    return [t for t in tools if find_tool(t) is None]
