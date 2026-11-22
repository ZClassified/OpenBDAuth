# modules/burn/mmc.py
"""
Leere BD-R selbst schreiben, mit MMC-Befehlen (v1.34.0). Rein und auf allen Systemen testbar: Das Gerät kommt von
außen (unter Windows IMAPI2 IDiscRecorder2Ex, siehe windows.py), Tests nehmen ein nachgebildetes Laufwerk.

Warum: IMAPI2 (IDiscFormat2Data.Write) formatiert eine leere BD-R mit Defektverwaltung. Das Laufwerk prüft dann
jeden Block nach (halbe Geschwindigkeit) und lagert schwache Blöcke aus. Auf CMC-Rohlingen (CMCMAG-BA5-000) brach
das zweimal kurz vor dem Ende ab; die Fehlbrand-Disc hatte 196 608 Blöcke Reservebereich, 14 688 davon belegt.
ImgBurn schrieb dieselbe ISO ohne Defektverwaltung fehlerfrei mit 3,1x (HARDWARE_TESTS.md, 2026-11-22).

Ohne FORMAT UNIT bleibt die BD-R unformatiert: kein Reservebereich, kein Nachprüfen. Ablauf wie im ImgBurn-Log:
SET STREAMING (Geschwindigkeit), WRITE(10) ab LBA 0, SYNCHRONIZE CACHE, CLOSE TRACK, Disc abschließen.

Am echten Laufwerk (BP40NS20 über USB, IMAPI2): Ein SCSI-Fehler kommt nicht als Ausnahme, sondern nur im
Sense-Puffer (TEST UNIT READY ohne Disc: „ok“, Sense 2/3A/01). Jeder Befehl wird deshalb am Sense-Puffer geprüft.
Größte Übertragung 64 KiB = 32 Sektoren = ein BD-Cluster.
"""

import os
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from modules.burn.model import BurnCancelled, BurnError, PHASE_WRITE, SECTOR

BD_1X_SECTORS = 4_500_000 / 2048                # 1x Blu-ray = 36 Mbit/s ≈ 2197 Sektoren/s
CLUSTER = 32                                    # Sektoren je BD-Cluster (64 KiB)
PROFILE_BD_R_SRM = 0x41
READ_AHEAD_BYTES = 64 * 1024 * 1024             # Vorrat aus der ISO (Quelle und Brenner teilen sich oft den USB)

TIMEOUT_SHORT = 30                              # Sekunden je Befehl
TIMEOUT_WRITE = 60
TIMEOUT_LONG = 900                              # Cache leeren, Spur schließen, abschließen
BUSY_PAUSE = 0.02                               # Pause, wenn das Laufwerk „beschäftigt“ meldet
BUSY_LIMIT = 300.0                              # so lange ohne Fortschritt, dann Fehler
UNIT_ATTENTION_RETRIES = 3

CLOSE_TRACK, CLOSE_SESSION, CLOSE_FINALIZE = 1, 2, 6

SENSE_KEYS = {0x0: "NO SENSE", 0x1: "RECOVERED ERROR", 0x2: "NOT READY", 0x3: "MEDIUM ERROR",
              0x4: "HARDWARE ERROR", 0x5: "ILLEGAL REQUEST", 0x6: "UNIT ATTENTION", 0x7: "DATA PROTECT",
              0x8: "BLANK CHECK", 0xB: "ABORTED COMMAND"}

# Klartexte der Norm (SPC/MMC) für die Fehler, die beim Schreiben vorkommen
ASC_TEXTS = {
    (0x04, 0x00): "LOGICAL UNIT NOT READY", (0x04, 0x01): "LOGICAL UNIT IS IN PROCESS OF BECOMING READY",
    (0x04, 0x04): "FORMAT IN PROGRESS", (0x04, 0x07): "OPERATION IN PROGRESS",
    (0x04, 0x08): "LONG WRITE IN PROGRESS",
    (0x0C, 0x00): "WRITE ERROR", (0x0C, 0x07): "WRITE ERROR - RECOVERY NEEDED",
    (0x0C, 0x08): "WRITE ERROR - RECOVERY FAILED", (0x0C, 0x09): "WRITE ERROR - LOSS OF STREAMING",
    (0x0C, 0x0A): "WRITE ERROR - PADDING BLOCKS ADDED", (0x11, 0x00): "UNRECOVERED READ ERROR",
    (0x21, 0x00): "LOGICAL BLOCK ADDRESS OUT OF RANGE", (0x21, 0x02): "INVALID ADDRESS FOR WRITE",
    (0x24, 0x00): "INVALID FIELD IN CDB", (0x26, 0x00): "INVALID FIELD IN PARAMETER LIST",
    (0x28, 0x00): "NOT READY TO READY CHANGE, MEDIUM MAY HAVE CHANGED",
    (0x29, 0x00): "POWER ON, RESET, OR BUS DEVICE RESET OCCURRED", (0x2C, 0x00): "COMMAND SEQUENCE ERROR",
    (0x30, 0x00): "INCOMPATIBLE MEDIUM INSTALLED", (0x30, 0x05): "CANNOT WRITE MEDIUM - INCOMPATIBLE FORMAT",
    (0x3A, 0x00): "MEDIUM NOT PRESENT", (0x3A, 0x01): "MEDIUM NOT PRESENT - TRAY CLOSED",
    (0x3A, 0x02): "MEDIUM NOT PRESENT - TRAY OPEN", (0x44, 0x00): "INTERNAL TARGET FAILURE",
    (0x5D, 0x00): "FAILURE PREDICTION THRESHOLD EXCEEDED", (0x64, 0x00): "ILLEGAL MODE FOR THIS TRACK",
    (0x72, 0x00): "SESSION FIXATION ERROR", (0x72, 0x01): "SESSION FIXATION ERROR WRITING LEAD-IN",
    (0x72, 0x02): "SESSION FIXATION ERROR WRITING LEAD-OUT",
    (0x72, 0x03): "SESSION FIXATION ERROR - INCOMPLETE TRACK IN SESSION",
    (0x73, 0x00): "CD CONTROL ERROR", (0x73, 0x01): "POWER CALIBRATION AREA ALMOST FULL",
    (0x73, 0x02): "POWER CALIBRATION AREA IS FULL", (0x73, 0x03): "POWER CALIBRATION AREA ERROR",
    (0x73, 0x04): "PROGRAM MEMORY AREA UPDATE FAILURE", (0x73, 0x05): "PROGRAM MEMORY AREA IS FULL",
}


# --- Zeit und Rate fürs Protokoll (auch vom IMAPI2-Weg genutzt) -------------------------------

def duration_text(seconds: float) -> str:
    """125 → „2:05“, 3725 → „1:02:05“."""
    seconds = max(0, int(round(seconds)))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def factor_text(sectors_per_second: float) -> str:
    return f"{sectors_per_second / BD_1X_SECTORS:.1f}x"


class WriteClock:
    """Zeit und Schreibrate fürs Protokoll, je Abschnitt zwischen zwei Protokollzeilen gemessen – so sieht man auch,
    wenn das Laufwerk bremst."""

    def __init__(self, started: float):
        self.started = started
        self.mark: Optional[Tuple[float, int]] = None      # (Zeit, LBA) der letzten Zeile

    def text(self, now: float, end_lba: int, last_lba: int) -> str:
        parts = [duration_text(now - self.started)]
        if self.mark is not None and now > self.mark[0] and last_lba > self.mark[1]:
            rate = (last_lba - self.mark[1]) / (now - self.mark[0])
            parts.append(f"{factor_text(rate)} ({rate:.0f} Sektoren/s)")
            parts.append(f"noch ca. {duration_text(max(0, end_lba - last_lba) / rate)}")
        self.mark = (now, last_lba)
        return " · ".join(parts)


# --- Sense und Antworten ---------------------------------------------------------------------

@dataclass(frozen=True)
class Sense:
    key: int
    asc: int
    ascq: int

    @property
    def ok(self) -> bool:
        """Kein Fehler: NO SENSE oder RECOVERED ERROR (das Laufwerk hat es selbst behoben)."""
        return self.key in (0x0, 0x1)

    @property
    def busy(self) -> bool:
        """Das Laufwerk ist beschäftigt (Puffer voll, Kalibrieren …): denselben Befehl später wiederholen."""
        return self.key == 0x2 and self.asc == 0x04 and self.ascq in (0x01, 0x04, 0x07, 0x08)

    def text(self) -> str:
        name = ASC_TEXTS.get((self.asc, self.ascq)) or SENSE_KEYS.get(self.key, "")
        code = f"Sense {self.key:X}/{self.asc:02X}/{self.ascq:02X}"
        return f"{code} {name}".strip()


def parse_sense(data: bytes) -> Optional[Sense]:
    """Sense-Daten (fest oder als Deskriptoren). None: keine Sense-Daten, also kein Fehler."""
    if not data:
        return None
    code = data[0] & 0x7F
    if code in (0x70, 0x71) and len(data) >= 14:
        sense = Sense(data[2] & 0x0F, data[12], data[13])
    elif code in (0x72, 0x73) and len(data) >= 4:
        sense = Sense(data[1] & 0x0F, data[2], data[3])
    else:
        return None
    return None if sense == Sense(0, 0, 0) else sense


class MmcError(Exception):
    """Das Laufwerk hat einen Befehl mit Fehler beendet."""

    def __init__(self, sense: Sense, what: str):
        super().__init__(f"{what}: {sense.text()}")
        self.sense = sense
        self.what = what


@dataclass
class DiscState:
    profile: int = 0
    disc_status: int = 0             # 0 leer, 1 unvollständig, 2 abgeschlossen, 3 anderes
    nwa: int = 0                     # nächste beschreibbare Adresse von Spur 1
    nwa_valid: bool = False
    free_blocks: int = 0
    track_size: int = 0

    def blank_problem(self, sectors: int) -> str:
        """Warum diese Disc nicht selbst beschrieben wird (leer = passt)."""
        if self.profile != PROFILE_BD_R_SRM:
            return f"Profil 0x{self.profile:02X} statt 0x41 (BD-R SRM)"
        if self.disc_status != 0:
            return f"Disc nicht leer (Status {self.disc_status})"
        if not self.nwa_valid or self.nwa != 0:
            return f"nächste beschreibbare Adresse {self.nwa if self.nwa_valid else 'unbekannt'} statt 0"
        if self.free_blocks < sectors:
            return f"zu wenig Platz ({self.free_blocks} Sektoren frei, {sectors} nötig)"
        return ""


def current_profile(data: bytes) -> int:
    """Antwort von GET CONFIGURATION: aktuelles Profil in Byte 6–7."""
    return int.from_bytes(data[6:8], "big") if len(data) >= 8 else 0


def disc_status(data: bytes) -> int:
    """Antwort von READ DISC INFORMATION: Status der Disc in Byte 2, Bit 0–1."""
    return data[2] & 0x03 if len(data) >= 3 else 3


def track_info(data: bytes) -> dict:
    """Antwort von READ TRACK INFORMATION."""
    if len(data) < 28:
        return {}
    return {"nwa_valid": bool(data[7] & 0x01), "start": int.from_bytes(data[8:12], "big"),
            "nwa": int.from_bytes(data[12:16], "big"), "free": int.from_bytes(data[16:20], "big"),
            "size": int.from_bytes(data[24:28], "big")}


# --- Befehle (CDB) ---------------------------------------------------------------------------

def cdb_test_unit_ready() -> bytes:
    return bytes(6)


def cdb_get_configuration(length: int = 8) -> bytes:
    return bytes([0x46, 0x02, 0, 0, 0, 0, 0]) + length.to_bytes(2, "big") + bytes(1)


def cdb_read_disc_information(length: int = 34) -> bytes:
    return bytes([0x51, 0, 0, 0, 0, 0, 0]) + length.to_bytes(2, "big") + bytes(1)


def cdb_read_track_information(track: int = 1, length: int = 48) -> bytes:
    return bytes([0x52, 0x01]) + track.to_bytes(4, "big") + bytes(1) + length.to_bytes(2, "big") + bytes(1)


def cdb_read_spare_area(length: int = 16) -> bytes:
    """READ DISC STRUCTURE, BD (Medientyp 1), Format 0Ah: Reservebereich."""
    return bytes([0xAD, 0x01, 0, 0, 0, 0, 0, 0x0A]) + length.to_bytes(2, "big") + bytes(2)


def spare_area(data: bytes) -> Tuple[int, int]:
    """Antwort auf cdb_read_spare_area: (freie, angelegte) Reserveblöcke."""
    if len(data) < 16:
        return 0, 0
    return int.from_bytes(data[8:12], "big"), int.from_bytes(data[12:16], "big")


def cdb_set_streaming(length: int = 28) -> bytes:
    return bytes([0xB6, 0, 0, 0, 0, 0, 0, 0, 0]) + length.to_bytes(2, "big") + bytes(1)


def streaming_descriptor(end_lba: int, kbytes_per_second: int) -> bytes:
    """Leistungs-Deskriptor für SET STREAMING: Lesen und Schreiben mit kbytes_per_second je 1000 ms, von LBA 0 bis
    end_lba."""
    rate = kbytes_per_second.to_bytes(4, "big")
    second = (1000).to_bytes(4, "big")
    return bytes(4) + bytes(4) + end_lba.to_bytes(4, "big") + rate + second + rate + second


def cdb_write10(lba: int, sectors: int) -> bytes:
    return bytes([0x2A, 0]) + lba.to_bytes(4, "big") + bytes(1) + sectors.to_bytes(2, "big") + bytes(1)


def cdb_synchronize_cache() -> bytes:
    return bytes([0x35]) + bytes(9)


def cdb_close(function: int, track: int = 0) -> bytes:
    return bytes([0x5B, 0, function & 0x07, 0]) + track.to_bytes(2, "big") + bytes(4)


def kbytes_per_second(sectors_per_second: int) -> int:
    """IMAPI2 nennt Geschwindigkeiten in Sektoren/s, SET STREAMING will kB/s (1000 Byte): 8780 → 17 981 (4x)."""
    return sectors_per_second * SECTOR // 1000


def padded_sectors(sectors: int) -> int:
    """Auf volle BD-Cluster aufgefüllt: Das Laufwerk schreibt immer ganze Cluster."""
    return -(-sectors // CLUSTER) * CLUSTER


def chunk_sectors(max_transfer: int) -> int:
    """Sektoren je Schreibbefehl: so viele wie das Gerät auf einmal nimmt (höchstens 1 MiB), in ganzen Clustern."""
    sectors = max(1, min(max_transfer, 1 << 20) // SECTOR)
    return sectors // CLUSTER * CLUSTER if sectors >= CLUSTER else sectors


# --- Gerät und Ablauf ------------------------------------------------------------------------

class Device:
    """Was der Writer vom Laufwerk braucht. command schickt einen Befehl und gibt (Sense oder None, gelesene Daten)
    zurück; data_out wird geschrieben, data_in Bytes werden gelesen. max_transfer: größte Übertragung in Byte."""

    max_transfer = CLUSTER * SECTOR

    def command(self, cdb: bytes, data_out: Optional[bytes] = None, data_in: int = 0,
                timeout: int = TIMEOUT_SHORT) -> Tuple[Optional[Sense], bytes]:
        raise NotImplementedError


class Drive:
    """Befehle mit Wiederholen: beschäftigt → kurz warten, UNIT ATTENTION → bis zu dreimal erneut."""

    def __init__(self, device: Device, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        self.device = device
        self.sleep = sleep
        self.clock = clock
        self.recovered = 0                      # vom Laufwerk selbst behobene Fehler (Sense-Key 1)
        self.busy_waits = 0

    def run(self, what: str, cdb: bytes, data_out: Optional[bytes] = None, data_in: int = 0,
            timeout: int = TIMEOUT_SHORT) -> bytes:
        deadline = None
        attention = 0
        while True:
            sense, data = self.device.command(cdb, data_out, data_in, timeout)
            if sense is None or sense.ok:
                if sense is not None:
                    self.recovered += 1
                return data
            if sense.busy:
                now = self.clock()
                if deadline is None:
                    deadline = now + BUSY_LIMIT
                elif now > deadline:
                    raise MmcError(sense, what)
                self.busy_waits += 1
                self.sleep(BUSY_PAUSE)
                continue
            if sense.key == 0x6 and attention < UNIT_ATTENTION_RETRIES:
                attention += 1
                continue
            raise MmcError(sense, what)

    def state(self) -> DiscState:
        profile = current_profile(self.run("GET CONFIGURATION", cdb_get_configuration(), data_in=8))
        status = disc_status(self.run("READ DISC INFORMATION", cdb_read_disc_information(), data_in=34))
        info = self.track()
        return DiscState(profile=profile, disc_status=status, nwa=info.get("nwa", 0),
                         nwa_valid=info.get("nwa_valid", False), free_blocks=info.get("free", 0),
                         track_size=info.get("size", 0))

    def track(self) -> dict:
        return track_info(self.run("READ TRACK INFORMATION", cdb_read_track_information(), data_in=48))

    def spare(self) -> Tuple[int, int]:
        """(freie, angelegte) Reserveblöcke; (0, 0) = ohne Defektverwaltung."""
        return spare_area(self.run("READ DISC STRUCTURE", cdb_read_spare_area(), data_in=16))

    def summary(self) -> str:
        """Für Protokoll und Diagnose: Profil, Disc, Spur 1 und Reservebereich."""
        state = self.state()
        parts = [f"Profil 0x{state.profile:02X}", f"Disc-Status {state.disc_status}",
                 f"Spurgröße {state.track_size}", f"frei {state.free_blocks}"]
        if state.nwa_valid:
            parts.append(f"nächste Adresse {state.nwa}")
        try:
            free, allocated = self.spare()
            parts.append(f"Reservebereich {allocated} (frei {free})" if allocated else "kein Reservebereich")
        except MmcError as e:
            parts.append(f"Reservebereich unbekannt ({e.sense.text()})")
        return " · ".join(parts)


def _read_iso(path: str, sectors_per_chunk: int, out: "queue.Queue", stop: threading.Event):
    """Lese-Thread: (LBA, Daten) in den Vorrat, der letzte Block auf volle Cluster aufgefüllt; am Ende None, bei einem
    Fehler die Ausnahme."""
    try:
        size = os.path.getsize(path)
        sectors = -(-size // SECTOR)
        total = padded_sectors(sectors)
        lba = 0
        with open(path, "rb") as f:
            while lba < total and not stop.is_set():
                count = min(sectors_per_chunk, total - lba)
                data = f.read(count * SECTOR) if lba < sectors else b""
                if len(data) < count * SECTOR:
                    data = data + bytes(count * SECTOR - len(data))
                while not stop.is_set():
                    try:
                        out.put((lba, data), timeout=0.2)
                        break
                    except queue.Full:
                        pass
                lba += count
        out.put(None)
    except Exception as e:                      # noqa: BLE001 – an den Schreib-Thread weitergeben
        out.put(e)


class BdrWriter:
    """Schreibt eine ISO auf eine leere BD-R (ohne Defektverwaltung) und schließt die Disc ab. report: log, phase,
    progress, cancelled (wie bei den Backends)."""

    def __init__(self, drive: Drive, report, clock: Callable[[], float] = time.monotonic):
        self.drive = drive
        self.report = report
        self.clock = clock
        self.lba = 0                            # nächster zu schreibender Sektor

    def check(self, sectors: int) -> Tuple[DiscState, str]:
        """Zustand der Disc und, falls sie nicht passt, warum (leer = passt)."""
        state = self.drive.state()
        return state, state.blank_problem(padded_sectors(sectors))

    def set_speed(self, kbytes: int, end_lba: int):
        try:
            self.drive.run("SET STREAMING", cdb_set_streaming(), data_out=streaming_descriptor(end_lba, kbytes))
            self.report.log(f"MMC: SET STREAMING {kbytes} kB/s ≈ {factor_text(kbytes * 1000 / SECTOR)}")
        except MmcError as e:
            self.report.log(f"MMC: SET STREAMING abgelehnt ({e.sense.text()}) – das Laufwerk wählt")

    def write(self, iso_path: str, sectors_per_chunk: int):
        try:
            size = os.path.getsize(iso_path)
        except OSError as e:
            raise BurnError(f"ISO nicht lesbar: {e}", PHASE_WRITE)
        sectors = -(-size // SECTOR)
        total = padded_sectors(sectors)
        report = self.report
        report.phase(PHASE_WRITE)
        report.progress(0.0)
        report.log(f"MMC: schreibe {sectors} Sektoren"
                   + (f" (+{total - sectors} Nullsektoren bis zum vollen Cluster)" if total > sectors else "")
                   + f" in Blöcken zu {sectors_per_chunk} Sektoren")
        depth = max(4, READ_AHEAD_BYTES // (sectors_per_chunk * SECTOR))
        chunks: "queue.Queue" = queue.Queue(maxsize=depth)
        stop = threading.Event()
        reader = threading.Thread(target=_read_iso, args=(iso_path, sectors_per_chunk, chunks, stop), daemon=True)
        clock = WriteClock(self.clock())
        tenth = -1
        reader.start()
        try:
            while True:
                if report.cancelled():
                    self._stop_after_cancel()
                    raise BurnCancelled(PHASE_WRITE)
                item = chunks.get()
                if item is None:
                    break
                if isinstance(item, Exception):
                    raise BurnError(f"ISO nicht lesbar: {item}", PHASE_WRITE)
                lba, data = item
                count = len(data) // SECTOR
                try:
                    self.drive.run(f"WRITE bei LBA {lba}", cdb_write10(lba, count), data_out=data,
                                   timeout=TIMEOUT_WRITE)
                except MmcError as e:
                    self._log_failure(e)
                    raise BurnError(f"{e.sense.text()} bei LBA {lba}", PHASE_WRITE)
                self.lba = lba + count
                share = min(1.0, self.lba / total)
                report.progress(share)
                if int(share * 10) != tenth:
                    tenth = int(share * 10)
                    report.log(f"MMC: {share * 100:.0f} % · LBA {self.lba} · "
                               + clock.text(self.clock(), total, self.lba))
        finally:
            stop.set()
            reader.join(2.0)
        self._finish(clock)

    def _finish(self, clock: WriteClock):
        report = self.report
        report.progress(None)
        steps = [("SYNCHRONIZE CACHE", cdb_synchronize_cache()),
                 ("CLOSE TRACK", cdb_close(CLOSE_TRACK, 1)),
                 ("Disc abschließen", cdb_close(CLOSE_FINALIZE))]
        for what, cdb in steps:
            report.log(f"MMC: {what} · {duration_text(self.clock() - clock.started)}")
            try:
                self.drive.run(what, cdb, timeout=TIMEOUT_LONG)
            except MmcError as e:
                if what == "Disc abschließen" and e.sense.key == 0x5:
                    # Abschließen (Funktion 6) nicht angenommen: Sitzung schließen (Funktion 2)
                    report.log(f"MMC: {e.sense.text()} – schließe die Sitzung (Funktion 2)")
                    try:
                        self.drive.run("CLOSE SESSION", cdb_close(CLOSE_SESSION), timeout=TIMEOUT_LONG)
                        continue
                    except MmcError as e2:
                        e = e2
                self._log_failure(e)
                raise BurnError(f"{e.what}: {e.sense.text()}", PHASE_WRITE)
        report.progress(1.0)
        extra = []
        if self.drive.recovered:
            extra.append(f"{self.drive.recovered} vom Laufwerk behobene Fehler")
        report.log(f"MMC: fertig nach {duration_text(self.clock() - clock.started)}"
                   + (" · " + ", ".join(extra) if extra else ""))
        try:
            report.log("MMC: Disc danach: " + self.drive.summary())
        except MmcError as e:
            report.log(f"MMC: Disc danach nicht lesbar ({e.sense.text()})")

    def _stop_after_cancel(self):
        self.report.log(f"MMC: abgebrochen bei LBA {self.lba} – SYNCHRONIZE CACHE, die Disc bleibt offen")
        try:
            self.drive.run("SYNCHRONIZE CACHE", cdb_synchronize_cache(), timeout=TIMEOUT_LONG)
        except MmcError as e:
            self.report.log(f"MMC: SYNCHRONIZE CACHE: {e.sense.text()}")

    def _log_failure(self, error: MmcError):
        """Fehlerzeile: was, wie weit, und wo das Laufwerk jetzt weiterschreiben würde."""
        parts = [f"MMC: Fehler bei {error.what}: {error.sense.text()}", f"geschrieben bis LBA {self.lba}"]
        try:
            info = self.drive.track()
            if info.get("nwa_valid"):
                parts.append(f"nächste beschreibbare Adresse {info['nwa']}")
        except MmcError:
            pass
        self.report.log(" · ".join(parts))
