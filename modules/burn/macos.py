# modules/burn/macos.py
"""
Brennen unter macOS mit den Werkzeugen des Systems (DiscRecording):

- Laufwerke: `drutil list -xml`, Fähigkeiten: `drutil -drive N info` (Zeile „BD-Write“)
- Medium: `drutil -drive N status -xml` (Typ, leer, löschbar, freie Sektoren, Brenngeschwindigkeiten)
- Brennen: `hdiutil burn <iso>` mit festen Schaltern, damit die ISO 1:1 auf die Disc kommt:
    -forceclose        Disc abschließen (Vorgabe von hdiutil: offen lassen – Player lesen nur abgeschlossene BD-R)
    -noaddpmap         keine Partitionstabelle hinzufügen
    -nosynthesize      kein eigenes Dateisystem erzeugen
    -nooptimizeimage   alle Blöcke unverändert brennen
    -noskipfinalfree   nichts am Ende weglassen
    -noeject           ausgeworfen wird erst nach unserer Entscheidung (Option „Auswerfen“)
    -[no]verifyburn    Prüfen nach dem Brennen (hdiutil prüft sonst immer)
    -erase             BD-RE vorher schnell löschen (drutil erase würfe die Disc danach aus)
  Fortschritt mit -puppetstrings: Zeilen „PERCENT:12.5“ und „MESSAGE:…“. Die Texte sind in der Sprache des Systems,
  darum werden die Phasen auch am Verlauf der Prozente erkannt (jeder Durchgang läuft von 0 bis 100).
- Auswerfen: `drutil -drive N tray eject`
- Prüfen: macht hdiutil selbst (-verifyburn). Rohzugriff auf /dev/rdiskN ginge auch ohne root (das Laufwerk gehört
  dem angemeldeten Nutzer) – Grundlage für ein eigenes „Disc gegen ISO prüfen“.
"""

import queue
import re
import shlex
import shutil
import signal
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from typing import List, Optional

from modules.burn.model import (
    BurnCancelled, BurnError, BurnOptions, BurnResult, Drive, Media, PHASE_ERASE, PHASE_PREPARE, PHASE_VERIFY,
    PHASE_WRITE,
)

RUN_TIMEOUT = 30
CANCEL_GRACE = 30.0          # so lange darf hdiutil nach „Abbrechen“ aufräumen
ERROR_LINES = 6              # so viele letzte Zeilen kommen in die Fehlermeldung

ERASE_WORDS = ("lösch", "eras", "effac", "borr", "cancell")
VERIFY_WORDS = ("prüf", "verif", "vérif", "überprüf", "controll")
WRITE_WORDS = ("brenn", "schreib", "burn", "writ", "grav", "masteriz")


def _strip_doctype(text: str) -> str:
    """drutil gibt eine eingebettete DTD aus (bei list ohne Namen, für ElementTree ungültig)."""
    return re.sub(r"<!DOCTYPE.*?\]>", "", text, count=1, flags=re.S)


def parse_drive_list(xml_text: str) -> List[Drive]:
    root = ET.fromstring(_strip_doctype(xml_text))
    drives = []
    for dev in root.iter("device"):
        index = dev.get("index")
        if not index:
            continue
        interconnect = dev.find("interconnect")
        drives.append(Drive(key=index, name=(dev.get("name") or "").strip(),
                            interconnect=interconnect.get("name", "") if interconnect is not None else ""))
    return drives


def parse_can_write_bd(info_text: str) -> Optional[bool]:
    """Aus `drutil info`: Zeile „BD-Write: -R, -RE“. Ohne Zeile: False; leere Ausgabe: unbekannt."""
    if not info_text.strip():
        return None
    match = re.search(r"^\s*BD-Write:\s*(.*)$", info_text, re.M)
    return bool(match and re.search(r"-R", match.group(1)))


def _blocks(info, tag: str) -> int:
    node = info.find(tag)
    try:
        return int(node.get("blockCount", 0)) if node is not None else 0
    except ValueError:
        return 0


def parse_media_status(xml_text: str) -> Media:
    root = ET.fromstring(_strip_doctype(xml_text))
    status = root.find(".//deviceStatus")
    if status is None:
        return Media()
    present = status.find("mediaIsPresent") is not None
    busy = status.find("mediaIsInTransition") is not None or status.find("mediaIsBusy") is not None
    info = status.find("mediaInfo")
    if info is None:
        return Media(present=present, busy=busy or present)   # eingelegt, aber noch nicht erkannt
    media_type = info.find("mediaType")
    media_class = info.find("mediaClass")
    speeds = []
    for speed in info.findall("burnSpeedList/burnSpeed"):
        factor = next((v for k, v in speed.attrib.items() if k.lower().endswith("xfactor")), "")
        if factor and factor not in speeds:
            speeds.append(factor)
    disc_status = info.find("discInfo/discInfoBlock/discStatus")
    return Media(
        present=True, busy=busy,
        media_class=media_class.get("value", "") if media_class is not None else "",
        kind=media_type.get("value", "") if media_type is not None else "",
        blank=info.find("blank") is not None,
        appendable=info.find("appendable") is not None,
        erasable=info.find("erasable") is not None,
        overwritable=info.find("overwritable") is not None,
        free_blocks=_blocks(info, "freeSpace"),
        used_blocks=_blocks(info, "usedSpace"),
        overwritable_blocks=_blocks(info, "overwritableSpace"),
        speeds=speeds,
        status=disc_status.get("description", "") if disc_status is not None else "",
    )


def parse_burn_devices(list_text: str) -> List[tuple]:
    """`hdiutil burn -list`: je Laufwerk eine Namenszeile, darunter eingerückt der IOService-Pfad."""
    devices, name = [], None
    for line in list_text.splitlines():
        if not line.strip():
            continue
        if line[:1].isspace():
            if name is not None and line.strip().startswith("IOService:"):
                devices.append((name, line.strip()))
                name = None
        else:
            name = line.strip()
    return devices


def burn_command(iso_path: str, options: BurnOptions, device: str = "") -> List[str]:
    cmd = ["hdiutil", "burn", iso_path, "-puppetstrings", "-noeject", "-forceclose", "-noaddpmap",
           "-nosynthesize", "-nooptimizeimage", "-noskipfinalfree",
           "-verifyburn" if options.verify else "-noverifyburn",
           "-speed", options.speed.lower().rstrip("x") if options.speed else "max"]
    if options.erase:
        cmd.append("-erase")
    if device:
        cmd += ["-device", device]
    return cmd


class PuppetTracker:
    """Wertet die Zeilen von `hdiutil burn -puppetstrings` aus: Phase und Fortschritt."""

    def __init__(self, erase: bool, verify: bool):
        self.passes = ([PHASE_ERASE] if erase else []) + [PHASE_WRITE] + ([PHASE_VERIFY] if verify else [])
        self.index = -1
        self.phase = PHASE_PREPARE
        self.progress: Optional[float] = None
        self._last: Optional[float] = None

    def _go(self, index: int):
        if index > self.index:
            self.index = index
            self.phase = self.passes[index]
            self._last = None

    def _phase_from_text(self, text: str) -> Optional[str]:
        low = text.lower()
        for phase, words in ((PHASE_VERIFY, VERIFY_WORDS), (PHASE_ERASE, ERASE_WORDS), (PHASE_WRITE, WRITE_WORDS)):
            if phase in self.passes and any(w in low for w in words):
                return phase
        return None

    def feed(self, line: str) -> tuple:
        """Gibt (Art, Wert) zurück: ("percent", Anteil oder None), ("message", Text) oder ("other", Zeile)."""
        if line.startswith("PERCENT:"):
            try:
                value = float(line[8:])
            except ValueError:
                return "other", line
            if value < 0:
                self.progress = None
                return "percent", None
            if self.index < 0 and value > 0:
                self._go(0)
            elif (self._last is not None and self._last >= 90 and value <= 10
                  and self.index < len(self.passes) - 1):
                self._go(self.index + 1)          # neuer Durchgang: Löschen → Brennen → Prüfen
            self._last = value
            self.progress = max(0.0, min(1.0, value / 100.0))
            return "percent", self.progress
        if line.startswith("MESSAGE:"):
            text = line[8:].strip()
            phase = self._phase_from_text(text)
            if phase is not None:
                self._go(self.passes.index(phase))
            return "message", text
        return "other", line


def _run(cmd: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=RUN_TIMEOUT, stdin=subprocess.DEVNULL)


class MacBackend:
    name = "macos"
    verifies_itself = True
    erase_with_burn = True

    def unavailable_reason(self):
        """(Textschlüssel, Werte) oder None."""
        missing = [t for t in ("drutil", "hdiutil") if not shutil.which(t)]
        return ("burn_tools_missing", {"tools": ", ".join(missing)}) if missing else None

    def diagnose(self) -> str:
        """Rohausgaben für Rückmeldungen (nur lesende Befehle)."""
        parts = []
        for cmd in (["drutil", "list"], ["drutil", "status"], ["drutil", "info"], ["hdiutil", "burn", "-list"]):
            try:
                result = _run(cmd)
                parts += ["$ " + " ".join(cmd), (result.stdout + result.stderr).strip()]
            except (OSError, subprocess.SubprocessError) as e:
                parts.append(f"{' '.join(cmd)}: {e}")
        return "\n".join(parts)

    def list_drives(self) -> List[Drive]:
        result = _run(["drutil", "list", "-xml"])
        if result.returncode != 0 or "<deviceList" not in result.stdout:
            return []
        drives = parse_drive_list(result.stdout)
        burn_devices = []
        if len(drives) > 1:
            burn_list = _run(["hdiutil", "burn", "-list"])
            burn_devices = parse_burn_devices(burn_list.stdout)
        for drive in drives:
            info = _run(["drutil", "-drive", drive.key, "info"])
            drive.can_write_bd = parse_can_write_bd(info.stdout if info.returncode == 0 else "")
            drive.device = next((path for name, path in burn_devices if name.startswith(drive.name)), "")
        return drives

    def media_info(self, drive: Drive) -> Media:
        result = _run(["drutil", "-drive", drive.key, "status", "-xml"])
        if result.returncode != 0 or "<statusdoc" not in result.stdout:
            return Media()
        return parse_media_status(result.stdout)

    def eject(self, drive: Drive) -> bool:
        try:
            return _run(["drutil", "-drive", drive.key, "tray", "eject"]).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def burn(self, drive: Drive, iso_path: str, options: BurnOptions, report) -> BurnResult:
        cmd = burn_command(iso_path, options, drive.device)
        report.log("$ " + " ".join(shlex.quote(c) for c in cmd))
        tracker = PuppetTracker(options.erase, options.verify)
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
        last_message = None
        cancel_deadline = None
        while True:
            if report.cancelled() and cancel_deadline is None:
                report.log("SIGINT → hdiutil")
                try:
                    proc.send_signal(signal.SIGINT)
                except OSError:
                    pass
                cancel_deadline = time.monotonic() + CANCEL_GRACE
            if cancel_deadline is not None:
                if time.monotonic() > cancel_deadline and proc.poll() is None:
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
            kind, value = tracker.feed(line.strip())
            if tracker.phase != before:
                report.phase(tracker.phase)
            if kind == "percent":
                report.progress(value)
            elif kind == "message":
                if value and value != last_message:
                    report.log(value)
                    last_message = value
                    tail.append(value)
            else:
                report.log(value)
                tail.append(value)
        code = proc.wait()
        if cancel_deadline is not None:
            raise BurnCancelled(tracker.phase)
        if code != 0:
            detail = "\n".join(tail[-ERROR_LINES:]) or f"hdiutil: exit {code}"
            raise BurnError(detail, tracker.phase)
        return BurnResult(verified=options.verify)
