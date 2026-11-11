# modules/bdsim/source.py
"""
Öffnet eine Disc für den Simulator: Disc-Ordner, BDMV-Ordner, index.bdmv oder ISO.
Eine ISO wird unter Windows schreibgeschützt eingehängt und beim Schließen wieder ausgehängt.
"""

import contextlib
import os
import subprocess
from typing import Callable, Tuple

from core.translations import tr
from modules.bdsim.disc import Disc, DiscReadError, load_disc


def _powershell(command: str) -> subprocess.CompletedProcess:
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                          capture_output=True, text=True, creationflags=flags)


def _mount_iso_macos(iso_path: str) -> Tuple[str, Callable[[], None]]:
    """macOS (ab v1.30): hdiutil hängt die ISO schreibgeschützt ein, ohne sie im Finder zu zeigen."""
    import plistlib
    result = subprocess.run(["hdiutil", "attach", "-readonly", "-nobrowse", "-noautoopen", "-plist",
                             os.path.abspath(iso_path)], capture_output=True)
    if result.returncode != 0:
        raise DiscReadError(tr("sim_iso_mount_failed", err=result.stderr.decode("utf-8", "replace").strip()))
    try:
        entities = plistlib.loads(result.stdout).get("system-entities", [])
    except Exception as e:
        raise DiscReadError(tr("sim_iso_mount_failed", err=e))
    mount = next((e["mount-point"] for e in entities if e.get("mount-point")), None)
    devices = [e["dev-entry"] for e in entities if e.get("dev-entry")]
    device = min(devices, key=len) if devices else None      # /dev/diskN vor /dev/diskNsM

    def unmount():
        if device:
            subprocess.run(["hdiutil", "detach", device, "-quiet"], capture_output=True)

    if mount is None:
        unmount()
        raise DiscReadError(tr("sim_iso_mount_failed", err="no mount point"))
    return mount, unmount


def _mount_iso_linux(iso_path: str) -> Tuple[str, Callable[[], None]]:
    """Linux (ab v1.31): udisksctl hängt die ISO als Loop-Gerät schreibgeschützt ein – ohne root auf Desktops."""
    import re
    import shutil
    if not shutil.which("udisksctl"):
        raise DiscReadError(tr("sim_iso_windows_only"))

    def run(*args):
        return subprocess.run(["udisksctl", *args], capture_output=True, text=True)

    setup = run("loop-setup", "-r", "-f", os.path.abspath(iso_path))
    match = re.search(r"(/dev/loop\d+)", setup.stdout + setup.stderr)
    if setup.returncode != 0 or not match:
        raise DiscReadError(tr("sim_iso_mount_failed", err=(setup.stderr or setup.stdout).strip()))
    loop = match.group(1).rstrip(".")

    def unmount():
        run("unmount", "-b", loop)
        run("loop-delete", "-b", loop)

    mounted = run("mount", "-b", loop)          # der Desktop hängt manchmal schon selbst ein
    from modules.burn.linux import mount_points
    point = mount_points(loop)
    found = re.search(r" at (.+?)\.?$", mounted.stdout.strip())
    mount = point[0] if point else (found.group(1) if found else None)
    if not mount:
        unmount()
        raise DiscReadError(tr("sim_iso_mount_failed", err=(mounted.stderr or mounted.stdout).strip()))
    return mount, unmount


def mount_iso(iso_path: str) -> Tuple[str, Callable[[], None]]:
    """Hängt eine ISO schreibgeschützt ein. Gibt (Laufwerkspfad, Aushängen) zurück."""
    import sys
    if sys.platform == "darwin":
        return _mount_iso_macos(iso_path)
    if sys.platform.startswith("linux"):
        return _mount_iso_linux(iso_path)
    if os.name != "nt":
        raise DiscReadError(tr("sim_iso_windows_only"))
    iso = os.path.abspath(iso_path).replace("'", "''")
    result = _powershell(f"$i = Mount-DiskImage -ImagePath '{iso}' -Access ReadOnly -PassThru; "
                         f"($i | Get-Volume).DriveLetter")
    letter = result.stdout.strip()
    if result.returncode != 0 or len(letter) != 1:
        raise DiscReadError(tr("sim_iso_mount_failed", err=result.stderr.strip() or letter))

    def unmount():
        _powershell(f"Dismount-DiskImage -ImagePath '{iso}' | Out-Null")

    return f"{letter}:\\", unmount


@contextlib.contextmanager
def mounted_iso(iso_path: str):
    """Kontext: ISO eingehängt, liefert den Laufwerkspfad."""
    drive, unmount = mount_iso(iso_path)
    try:
        yield drive
    finally:
        unmount()


def open_disc(path: str) -> Tuple[Disc, Callable[[], None]]:
    """Lädt eine Disc aus ISO, Ordner oder index.bdmv. Gibt (Disc, Schließen) zurück;
    Schließen hängt eine ISO wieder aus (sonst ohne Wirkung)."""
    if os.path.basename(path).lower() == "index.bdmv":
        path = os.path.dirname(path)
    if path.lower().endswith(".iso"):
        drive, unmount = mount_iso(path)
        try:
            return load_disc(drive), unmount
        except Exception:
            unmount()
            raise
    return load_disc(path), lambda: None
