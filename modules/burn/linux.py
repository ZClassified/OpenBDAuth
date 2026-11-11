# modules/burn/linux.py
"""
Brennen unter Linux mit xorriso (v1.31.0, Plan docs/plaene/brennen.md). xorriso kommt vorerst vom System
(`sudo apt install xorriso`); eine mitgelieferte Datei unter tools/linux/ hätte Vorrang (find_tool).

Die Ausgabeformate stammen aus echten Läufen von GNU xorriso 1.5.6 (Pseudo-Laufwerk `stdio:`) und, wo ein echtes
Laufwerk nötig ist, aus dessen Quelltext (drive_mgt.c). Alles, was xorriso über Laufwerk und Medium sagt, kommt auf
stderr; Zeilen mit „FAILURE“ oder „SORRY“ sind Fehler.

- Laufwerke: `xorriso -devices`  →  „0  -dev '/dev/sr0' rwrw-- :  'HL-DT-ST' 'BD-RE BP40NS20'“; ohne Zugriff
  (Gruppe cdrom/optical) erscheint kein Laufwerk: „No drives found“.
- Medium: `xorriso -drive_access shared:readonly -indev <dev> -toc -list_speeds -list_profiles all` – nur lesend und
  ohne exklusiven Zugriff, damit es auch bei eingehängter Disc antwortet. „Media current: BD-RE“,
  „Media status : is blank | is written , is appendable | is written , is closed | is not present“,
  „Media blocks : 2304 readable , 0 writable , 2304 overall“, „Write speed  :  8990k ,  2.0xBD“.
- Brennen: `xorriso -as cdrecord -v dev=<dev> -nopad blank=as_needed [speed=4b] <iso>`.
    -nopad            nichts anhängen: die Disc ist Byte für Byte die ISO (geprüft: identisch bei ganzen Sektoren)
    blank=as_needed   BD-RE wenn nötig formatieren; eine BD-RE mit Daten wird einfach überschrieben
    speed=4b          „b“ = Vielfache der Blu-ray-Geschwindigkeit (ohne Suffix wären es CD-Einheiten)
  Ohne -multi wird die Disc abgeschlossen. Fortschritt: „  16 of  381 MB written (fifo 99%) …“; Erfolg:
  „Writing to '…' completed successfully.“
- Abbrechen: SIGINT. xorriso fährt das Laufwerk geordnet herunter und bittet ausdrücklich, „die normale Brenndauer“
  vor einem kill -9 abzuwarten – deshalb lange Wartezeit (CANCEL_GRACE).
- Eingehängte Disc (Desktop hängt eine BD-RE mit Daten ein): vor dem Brennen mit udisksctl bzw. umount aushängen,
  sonst bekommt xorriso das Laufwerk nicht exklusiv.
- Prüfen: die Disc über /dev/srN zurücklesen und mit der ISO vergleichen (verify.compare_with_device).
- Auswerfen: `xorriso -outdev <dev> -eject all`.
"""

import os
import queue
import re
import shlex
import shutil
import signal
import subprocess
import threading
import time
from typing import List, Optional, Tuple

from modules.burn.model import (
    BurnCancelled, BurnError, BurnOptions, BurnResult, Drive, Media, PHASE_ERASE, PHASE_PREPARE, PHASE_VERIFY,
    PHASE_WRITE,
)

XORRISO = "xorriso"
RUN_TIMEOUT = 60
CANCEL_GRACE = 600.0         # xorriso: „Wait the normal burning time before any kill -9“
ERROR_LINES = 6

DEVICE_LINE = re.compile(r"^\s*(\d+)\s+-dev\s+'([^']+)'\s+(\S+)\s*:\s*'([^']*)'\s*'([^']*)'")
WRITTEN_LINE = re.compile(r"(\d+)\s+of\s+(\d+)\s+MB written")
PERCENT_DONE = re.compile(r"\(\s*([\d.]+)%\s*done")
SPEED_LINE = re.compile(r"^Write speed\s*:\s*\d+k\s*,\s*([\d.]+)x(\w+)", re.M)
PROFILE_LINE = re.compile(r"^Profile\s*:\s*0x([0-9A-Fa-f]{4})\s*\(([^)]*)\)", re.M)
BD_WRITE_PROFILES = {0x41, 0x42, 0x43}          # BD-R sequentiell, BD-R random, BD-RE


def xorriso_path() -> Optional[str]:
    from modules.external_tools import find_tool
    return find_tool(XORRISO)


def _last(text: str, label: str) -> Optional[str]:
    """Wert der letzten Zeile „label: …“ (xorriso gibt die Medium-Zeilen je Befehl einmal aus)."""
    values = re.findall(rf"^{re.escape(label)}\s*:\s*(.*?)\s*$", text, re.M)
    return values[-1] if values else None


def parse_devices(text: str) -> List[Drive]:
    drives = []
    for line in text.splitlines():
        match = DEVICE_LINE.match(line)
        if match:
            _index, device, _perms, vendor, product = match.groups()
            name = " ".join(part for part in (vendor.strip(), product.strip()) if part)
            drives.append(Drive(key=device, name=name or device, device=device))
    return drives


def parse_can_write_bd(text: str) -> Optional[bool]:
    """Aus `-list_profiles all`: Kennt das Laufwerk BD-R oder BD-RE? Ohne Profilliste: unbekannt."""
    profiles = {int(code, 16) for code, _name in PROFILE_LINE.findall(text)}
    if not profiles:
        return None
    return bool(profiles & BD_WRITE_PROFILES)


def _blocks(text: str) -> Tuple[int, int, int]:
    value = _last(text, "Media blocks") or ""
    match = re.match(r"(\d+)\s+readable\s*,\s*(\d+)\s+writable\s*,\s*(\d+)\s+overall", value)
    return tuple(int(x) for x in match.groups()) if match else (0, 0, 0)


def parse_media(text: str) -> Media:
    current = _last(text, "Media current") or ""
    status = _last(text, "Media status") or ""
    if not current or "not recognizable" in current or "not present" in status:
        return Media(present=False, status=status)
    profile = current.split(",")[0].strip()          # „BD-R sequential recording“, „BD-RE“, „DVD+RW“ …
    upper = profile.upper()
    if upper.startswith("BD-RE"):
        kind = "BD-RE"
    elif upper.startswith("BD-ROM"):
        kind = "BD-ROM"
    elif upper.startswith("BD-R"):
        kind = "BD-R"
    else:
        kind = profile.split()[0] if profile else ""
    media_class = "BD" if upper.startswith("BD") else "DVD" if upper.startswith("DVD") else \
        "CD" if upper.startswith("CD") else ""
    readable, writable, overall = _blocks(text)
    rewritable = kind == "BD-RE"
    speeds = []
    for factor, unit in SPEED_LINE.findall(text):
        if unit.upper() == "BD":
            label = f"{float(factor):g}x"
            if label not in speeds:
                speeds.append(label)
    return Media(
        present=True, media_class=media_class, kind=kind,
        blank="is blank" in status,
        appendable="appendable" in status,
        erasable=rewritable, overwritable=rewritable,
        free_blocks=writable, used_blocks=readable, overwritable_blocks=overall if rewritable else 0,
        speeds=speeds, status=status,
    )


def burn_command(xorriso: str, device: str, iso_path: str, options: BurnOptions) -> List[str]:
    cmd = [xorriso, "-as", "cdrecord", "-v", f"dev={device}", "-nopad", "blank=as_needed"]
    if options.speed:
        cmd.append(f"speed={options.speed.lower().rstrip('x')}b")
    cmd.append(iso_path)
    return cmd


class XorrisoTracker:
    """Wertet die Zeilen von `xorriso -as cdrecord -v` aus: Phase, Fortschritt, Erfolg, Fehler."""

    def __init__(self):
        self.phase = PHASE_PREPARE
        self.progress: Optional[float] = None
        self.success = False
        self.errors: List[str] = []

    def feed(self, line: str) -> str:
        """Gibt die Art der Zeile zurück: "progress", "phase", "error", "info"."""
        match = WRITTEN_LINE.search(line)
        if match:
            done, total = int(match.group(1)), int(match.group(2))
            if self.phase != PHASE_WRITE:
                self.phase = PHASE_WRITE
            self.progress = min(1.0, done / total) if total else None
            return "progress"
        if "Blanking" in line or "Formatting" in line:
            self.phase = PHASE_ERASE
            match = PERCENT_DONE.search(line)
            self.progress = float(match.group(1)) / 100 if match else None
            return "phase"
        if "Beginning to write data track" in line:
            self.phase, self.progress = PHASE_WRITE, 0.0
            return "phase"
        if "completed successfully" in line:
            self.success, self.progress = True, 1.0
            return "info"
        if " : FAILURE : " in line or " : SORRY : " in line or " : FATAL : " in line:
            self.errors.append(line.split(" : ", 2)[-1].strip())
            return "error"
        return "info"


def mount_points(device: str, mounts_text: Optional[str] = None) -> List[str]:
    """Wo ist das Laufwerk eingehängt? (/proc/mounts, Gerät auch über Links wie /dev/cdrom)."""
    if mounts_text is None:
        try:
            with open("/proc/mounts", encoding="utf-8", errors="replace") as f:
                mounts_text = f.read()
        except OSError:
            return []
    real = os.path.realpath(device)
    points = []
    for line in mounts_text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith("/dev/") and os.path.realpath(parts[0]) == real:
            points.append(parts[1].replace("\\040", " "))
    return points


def _run(cmd: List[str], timeout: int = RUN_TIMEOUT) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, stdin=subprocess.DEVNULL)


def _output(result: subprocess.CompletedProcess) -> str:
    return (result.stdout or "") + (result.stderr or "")


class LinuxBackend:
    name = "linux-xorriso"
    verifies_itself = True       # burn() prüft selbst (Rücklesen über /dev/srN)
    erase_with_burn = True
    no_drive_hint = "burn_linux_no_drive"

    def __init__(self):
        self._xorriso = xorriso_path()

    def unavailable_reason(self):
        if self._xorriso is None:
            return "burn_linux_no_xorriso", {}
        return None

    def _x(self, *args: str, timeout: int = RUN_TIMEOUT) -> str:
        return _output(_run([self._xorriso, *args], timeout=timeout))

    def list_drives(self) -> List[Drive]:
        drives = parse_devices(self._x("-devices"))
        for drive in drives:
            drive.can_write_bd = parse_can_write_bd(self._x("-drive_access", "shared:readonly", "-indev",
                                                            drive.device, "-list_profiles", "all"))
        return drives

    def media_info(self, drive: Drive) -> Media:
        return parse_media(self._x("-drive_access", "shared:readonly", "-indev", drive.device,
                                   "-toc", "-list_speeds"))

    def eject(self, drive: Drive) -> bool:
        try:
            result = _run([self._xorriso, "-outdev", drive.device, "-eject", "all"])
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0

    def _unmount(self, drive: Drive, report):
        """Eine eingehängte Disc aushängen (der Desktop hängt eine BD-RE mit Daten ein)."""
        for point in mount_points(drive.device):
            report.log(f"umount {point}")
            for cmd in (["udisksctl", "unmount", "-b", drive.device], ["umount", point]):
                if shutil.which(cmd[0]) and _run(cmd).returncode == 0:
                    break
            else:
                raise BurnError(f"Die Disc ist unter {point} eingehängt und lässt sich nicht aushängen.",
                                PHASE_PREPARE)

    def burn(self, drive: Drive, iso_path: str, options: BurnOptions, report) -> BurnResult:
        if self._xorriso is None:
            raise BurnError("xorriso fehlt", PHASE_PREPARE)
        self._unmount(drive, report)
        cmd = burn_command(self._xorriso, drive.device, iso_path, options)
        report.log("$ " + " ".join(shlex.quote(c) for c in cmd))
        tracker = XorrisoTracker()
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    text=True, encoding="utf-8", errors="replace", bufsize=1)
        except OSError as e:
            raise BurnError(str(e), PHASE_PREPARE)
        lines: "queue.Queue[Optional[str]]" = queue.Queue()

        def reader():
            for raw in proc.stdout:
                lines.put(raw.rstrip("\r\n"))
            lines.put(None)

        threading.Thread(target=reader, daemon=True).start()
        tail: List[str] = []
        cancel_deadline = None
        last_logged_mb = -1
        while True:
            if report.cancelled() and cancel_deadline is None:
                report.log("SIGINT → xorriso")
                try:
                    proc.send_signal(signal.SIGINT)
                except OSError:
                    pass
                cancel_deadline = time.monotonic() + CANCEL_GRACE
            if cancel_deadline is not None and time.monotonic() > cancel_deadline and proc.poll() is None:
                proc.kill()
            try:
                line = lines.get(timeout=0.2)
            except queue.Empty:
                continue
            if line is None:
                break
            if not line.strip():
                continue
            before = tracker.phase
            kind = tracker.feed(line)
            if tracker.phase != before:
                report.phase(tracker.phase)
            if tracker.progress is not None or kind == "progress":
                report.progress(tracker.progress)
            if kind == "progress":
                match = WRITTEN_LINE.search(line)
                mb = int(match.group(1))
                if mb // 1024 != last_logged_mb // 1024:      # ins Protokoll nur etwa jedes GB
                    report.log(line.strip())
                    last_logged_mb = mb
                continue
            report.log(line.strip())
            tail.append(line.strip())
        code = proc.wait()
        if cancel_deadline is not None:
            raise BurnCancelled(tracker.phase)
        if code != 0 or not tracker.success:
            detail = "\n".join(tracker.errors[-ERROR_LINES:]) or "\n".join(tail[-ERROR_LINES:]) \
                or f"xorriso: exit {code}"
            raise BurnError(detail, tracker.phase)
        if not options.verify:
            return BurnResult(verified=False)
        from modules.burn.verify import compare_with_device
        report.phase(PHASE_VERIFY)
        verified = compare_with_device(drive.device, iso_path, report)
        return BurnResult(verified=verified)

    def diagnose(self) -> str:
        """Rohausgaben für Rückmeldungen (nur lesende Befehle)."""
        parts = [f"xorriso: {self._xorriso or 'nicht gefunden'}"]
        if self._xorriso:
            parts.append(self._x("-version").strip().splitlines()[0] if self._x("-version").strip() else "")
            devices = self._x("-devices")
            parts += ["$ xorriso -devices", devices.strip()]
            for drive in parse_devices(devices):
                parts += [f"$ xorriso -drive_access shared:readonly -indev {drive.device} -toc -list_speeds "
                          f"-list_profiles all",
                          self._x("-drive_access", "shared:readonly", "-indev", drive.device, "-toc", "-list_speeds",
                                  "-list_profiles", "all").strip()]
                parts.append(f"eingehängt: {', '.join(mount_points(drive.device)) or 'nein'}")
        for cmd in (["id", "-nG"], ["sh", "-c", "ls -l /dev/sr* /dev/cdrom 2>&1"]):
            try:
                parts += ["$ " + " ".join(cmd), _output(_run(cmd)).strip()]
            except (OSError, subprocess.SubprocessError) as e:
                parts.append(f"{cmd[0]}: {e}")
        parts.append("udisksctl: " + (shutil.which("udisksctl") or "fehlt") +
                     " · systemd-inhibit: " + (shutil.which("systemd-inhibit") or "fehlt"))
        return "\n".join(parts)
