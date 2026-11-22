# modules/burn/windows.py
"""
Brennen unter Windows mit IMAPI2 (in Windows 10/11 eingebaut, keine Admin-Rechte), v1.32.0.

Zugriff über comtypes mit spätem Binden (IDispatch): Es wird zur Laufzeit kein Code erzeugt (kein comtypes.gen),
das fertige Paket braucht also keine Typbibliothek-Module. Nur die beiden Ereignis-Schnittstellen sind hier
nachgebildet; IMAPI2 ruft sie über die Vtable auf (sie haben keine DISPIDs).

Werte aus einem echten Lauf (HL-DT-ST BP40NS20 über USB, BD-RE mit Daten, 2026-11-11):
- MsftDiscMaster2: ein Eintrag „\\\\?\\usbstor#cdrom&ven_hl-dt-st&prod_bd-re_bp40ns20…“. Ohne Laufwerk: Count 0 und
  IsSupportedEnvironment False – das heißt nur „kein Brenner“, nicht „IMAPI2 fehlt“.
- MsftDiscRecorder2: VendorId „HL-DT-ST“, ProductId „BD-RE BP40NS20  “ (mit Leerzeichen), VolumePathNames („I:\\“,),
  SupportedProfiles (64, 65, 66, 67, …), CurrentProfiles (67, 2) – 0x43 = BD-RE.
- MsftDiscFormat2Data: CurrentPhysicalMediaType 19 (IMAPI_MEDIA_TYPE_BDRE; 17 BD-ROM, 18 BD-R, aus der
  Typbibliothek), CurrentMediaStatus 1 (OVERWRITE_ONLY), MediaHeuristicallyBlank False, FreeSectorsOnMedia =
  TotalSectorsOnMedia = 11 826 176 (formatierte BD-RE), SupportedWriteSpeedDescriptors: WriteSpeed 4390 (Sektoren
  pro Sekunde, ≈ 2x).
- Lesen über \\\\.\\I: geht ohne Admin-Rechte. Die Größe liefert nicht seek(END), sondern
  IOCTL_DISK_GET_LENGTH_INFO (verify.device_size): bei der BD-RE die ganze physische Disc (12 219 392 Sektoren).

Fehlbrand (BD-R, 18 GB, ohne gewählte Geschwindigkeit = 6x, 2026-11-21): Write meldete nach CurrentAction 5
(Abschließen) DISP_E_EXCEPTION 0x80020009 mit „Das Laufwerk hat Fehlerinformationen zurückgegeben. Der Fehler ist nicht
behebbar.“ Lesbar waren danach 98,6 % (bis LBA 8 674 911), Status nur NON_EMPTY_SESSION. Der eigentliche Code steht in
EXCEPINFO.scode (comtypes: details[4]); IMAPI2s RemainingTime war ab 30 % nur noch 0 s. Daher: „Automatisch“ höchstens
4x (model.auto_speed), echte Geschwindigkeit, eigene Zeit/Rate und der Zustand nach einem Fehler im Protokoll.

Zweiter Fehlbrand (BD-R, 4x, v1.33.0, 2026-11-22): Das Laufwerk schrieb nur mit 1,0–1,5x, zuletzt 0,7x, und hörte bei
96,8 % auf (lesbar bis LBA 8 511 487, IMAPI2 zuletzt 8 511 871). Diesmal war scode 0; der Text gehört zu 0xC0AA0301
(E_IMAPI_UNEXPECTED_RESPONSE_FROM_DEVICE), daher die Suche in der Meldungstabelle (error_code).

Brennen: die ISO als IStream (SHCreateStreamOnFileEx, nur lesend) an IDiscFormat2Data.Write. Write schreibt den
Datenstrom roh, Sektor für Sektor – anders als IMAPI2FS (Dateisystem-Abbild), das in v1.18.1 entfernt wurde.
ForceMediaToBeClosed schließt die Disc ab. Fortschritt über DDiscFormat2DataEvents.Update; Abbrechen mit
CancelWrite aus diesem Ereignis heraus (so sieht es die Doku vor). Gebrannt wird im Brenn-Thread mit eigener
COM-Initialisierung (MTA, damit die Ereignisse ohne Nachrichtenschleife ankommen).
"""

import ctypes
import os
import sys
import threading
import time
from contextlib import contextmanager
from typing import Dict, List, Optional, Tuple

from modules.burn.model import (
    BurnCancelled, BurnError, BurnOptions, BurnResult, Drive, Media, PHASE_ERASE, PHASE_PREPARE, PHASE_VERIFY,
    PHASE_WRITE,
)

CLIENT_NAME = "OpenBDAuth"

# IMAPI_MEDIA_PHYSICAL_TYPE (aus der Typbibliothek imapi2.dll gelesen)
MEDIA_TYPES = {
    0: ("", ""), 1: ("CD", "CD-ROM"), 2: ("CD", "CD-R"), 3: ("CD", "CD-RW"), 4: ("DVD", "DVD-ROM"),
    5: ("DVD", "DVD-RAM"), 6: ("DVD", "DVD+R"), 7: ("DVD", "DVD+RW"), 8: ("DVD", "DVD+R DL"), 9: ("DVD", "DVD-R"),
    10: ("DVD", "DVD-RW"), 11: ("DVD", "DVD-R DL"), 12: ("", "Disk"), 13: ("DVD", "DVD+RW DL"),
    14: ("HD DVD", "HD DVD-ROM"), 15: ("HD DVD", "HD DVD-R"), 16: ("HD DVD", "HD DVD-RAM"),
    17: ("BD", "BD-ROM"), 18: ("BD", "BD-R"), 19: ("BD", "BD-RE"),
}
MEDIA_BD_RE = 19

# IMAPI_FORMAT2_DATA_MEDIA_STATE (Bitmaske)
STATE_OVERWRITE_ONLY, STATE_BLANK, STATE_APPENDABLE, STATE_FINAL_SESSION = 0x1, 0x2, 0x4, 0x8
STATE_DAMAGED, STATE_ERASE_REQUIRED, STATE_NON_EMPTY_SESSION = 0x400, 0x800, 0x1000
STATE_WRITE_PROTECTED, STATE_FINALIZED, STATE_UNSUPPORTED_MEDIA = 0x2000, 0x4000, 0x8000
STATE_NAMES = [(STATE_OVERWRITE_ONLY, "overwrite only"), (STATE_BLANK, "blank"), (STATE_APPENDABLE, "appendable"),
               (STATE_FINAL_SESSION, "final session"), (STATE_DAMAGED, "damaged"),
               (STATE_ERASE_REQUIRED, "erase required"), (STATE_NON_EMPTY_SESSION, "non-empty session"),
               (STATE_WRITE_PROTECTED, "write protected"), (STATE_FINALIZED, "finalized"),
               (STATE_UNSUPPORTED_MEDIA, "unsupported media")]

# IMAPI_FORMAT2_DATA_WRITE_ACTION
ACTION_VALIDATING, ACTION_FORMATTING, ACTION_INIT_HW, ACTION_CALIBRATING = 0, 1, 2, 3
ACTION_WRITING, ACTION_FINALIZATION, ACTION_COMPLETED, ACTION_VERIFYING = 4, 5, 6, 7
ACTION_NAMES = {ACTION_VALIDATING: "Prüfen der Disc", ACTION_FORMATTING: "Formatieren",
                ACTION_INIT_HW: "Laufwerk vorbereiten", ACTION_CALIBRATING: "Laser kalibrieren",
                ACTION_WRITING: "Schreiben", ACTION_FINALIZATION: "Abschließen", ACTION_COMPLETED: "Fertig",
                ACTION_VERIFYING: "Stichprobe"}

BD_WRITE_PROFILES = {0x41, 0x42, 0x43}          # BD-R sequentiell, BD-R random, BD-RE
BD_1X_SECTORS = 4_500_000 / 2048                # 1x Blu-ray = 36 Mbit/s ≈ 2197 Sektoren/s

COINIT_MULTITHREADED = 0x0
RPC_E_CHANGED_MODE = -2147417850                # Thread hat COM schon anders initialisiert (z. B. GUI-Thread, STA)
E_IMAPI_REQUEST_CANCELLED = 0xC0AA0002
DISP_E_EXCEPTION = 0x80020009
STGM_READ, STGM_SHARE_DENY_WRITE = 0x0, 0x20
FILE_ATTRIBUTE_NORMAL = 0x80

# IIDs der Ereignis-Schnittstellen (imapi2.dll)
IID_DATA_EVENTS = "{2735413C-7F64-5B0F-8F00-5D77AFBE261E}"
IID_ERASE_EVENTS = "{2735413A-7F64-5B0F-8F00-5D77AFBE261E}"


# --- Auswertung (rein, ohne COM; auf allen Systemen testbar) ---------------------------------

def speed_label(sectors_per_second: int) -> str:
    """IMAPI2 nennt Geschwindigkeiten in Sektoren pro Sekunde; 4390 → „2x“."""
    factor = round(sectors_per_second / BD_1X_SECTORS * 2) / 2      # auf halbe Stufen
    return f"{factor:g}x"


def can_write_bd(profiles) -> Optional[bool]:
    profiles = set(profiles or ())
    if not profiles:
        return None
    return bool(profiles & BD_WRITE_PROFILES)


def device_path(volume_paths) -> str:
    """(„I:\\“,) → „\\\\.\\I:“ (Rohzugriff für das Prüfen). Ohne Laufwerksbuchstabe: leer."""
    for path in volume_paths or ():
        path = str(path)
        if len(path) >= 2 and path[1] == ":":
            return "\\\\.\\" + path[:2].upper()
    return ""


def status_text(state: int) -> str:
    return ", ".join(name for bit, name in STATE_NAMES if state & bit) or "unknown"


def media_from_values(media_type: int, state: int, blank: bool, free: int, total: int,
                      speeds: List[int]) -> Media:
    media_class, kind = MEDIA_TYPES.get(media_type, ("", f"type {media_type}"))
    rewritable = media_type == MEDIA_BD_RE
    labels = []
    for sectors in sorted(set(speeds)):
        label = speed_label(sectors)
        if label not in labels:
            labels.append(label)
    blank = bool(blank or state & STATE_BLANK)
    return Media(
        present=True, media_class=media_class, kind=kind, blank=blank,
        appendable=bool(state & STATE_APPENDABLE),
        erasable=rewritable, overwritable=rewritable,
        free_blocks=0 if (state & STATE_FINALIZED and not rewritable) else free,
        used_blocks=0 if rewritable or blank else max(0, total - free),
        overwritable_blocks=total if rewritable else 0,
        speeds=labels, status=status_text(state),
    )


def hresult(code: int) -> int:
    return code & 0xFFFFFFFF


def _details(error) -> tuple:
    details = getattr(error, "details", None)
    return details if isinstance(details, tuple) else ()


def _normalized(text) -> str:
    return " ".join(str(text or "").split())


def code_from_messages(text, messages: Dict[int, str]) -> Optional[int]:
    """Der Fehlercode zu einem Meldungstext aus der Meldungstabelle von IMAPI2 (Code → Text)."""
    wanted = _normalized(text)
    if not wanted:
        return None
    for code, message in messages.items():
        if _normalized(message) == wanted:
            return code
    return None


_MESSAGES: Optional[Dict[int, str]] = None
IMAPI_MESSAGE_RANGES = (0xC0AA0000, 0x80AA0000, 0x40AA0000, 0x00AA0000)      # IMAPI2-Codes: Facility 0xAA


def imapi_messages() -> Dict[int, str]:
    """Die Meldungstabelle von imapi2.dll (Code → Text in der Sprache von Windows), einmal je Prozess gelesen. Ohne
    Windows oder ohne imapi2.dll leer."""
    global _MESSAGES
    if _MESSAGES is None:
        _MESSAGES = {}
        try:
            from ctypes import wintypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.LoadLibraryExW.restype = wintypes.HMODULE
            kernel32.FormatMessageW.argtypes = [wintypes.DWORD, wintypes.HMODULE, wintypes.DWORD, wintypes.DWORD,
                                                wintypes.LPWSTR, wintypes.DWORD, ctypes.c_void_p]
            module = kernel32.LoadLibraryExW("imapi2.dll", None, 0x2)      # LOAD_LIBRARY_AS_DATAFILE
            if module:
                buffer = ctypes.create_unicode_buffer(2048)
                for base in IMAPI_MESSAGE_RANGES:
                    for index in range(0x400):
                        if kernel32.FormatMessageW(0x800 | 0x200, module, base | index, 0, buffer, 2048, None):
                            _MESSAGES[base | index] = buffer.value
        except Exception:
            pass
    return _MESSAGES


def error_code(error) -> Optional[int]:
    """Der eigentliche Fehlercode. Über IDispatch kommt jeder IMAPI2-Fehler als DISP_E_EXCEPTION (0x80020009); den
    Code von IMAPI2 legt comtypes aus EXCEPINFO.scode in details[4]. Lässt IMAPI2 scode leer (so beim Fehlbrand
    2026-11-22), wird der Code über den Text in der Meldungstabelle von imapi2.dll gesucht."""
    details = _details(error)
    if len(details) >= 5 and isinstance(details[4], int) and details[4]:
        return hresult(details[4])
    code = getattr(error, "hresult", None)
    if code is not None and hresult(code) == DISP_E_EXCEPTION and details:
        found = code_from_messages(details[0], imapi_messages())
        if found is not None:
            return found
    return hresult(code) if code is not None else None


def com_error_text(error) -> str:
    """Text eines COMError (IMAPI2 legt die eigentliche Meldung in details[0]) mit dem eigentlichen Fehlercode."""
    details = _details(error)
    text = str(details[0]).strip() if details and details[0] else (getattr(error, "text", "") or str(error))
    code = error_code(error)
    return f"{text} (0x{code:08X})" if code is not None else text


def duration_text(seconds: float) -> str:
    """125 → „2:05“, 3725 → „1:02:05“."""
    seconds = max(0, int(round(seconds)))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def factor_text(sectors_per_second: float) -> str:
    return f"{sectors_per_second / BD_1X_SECTORS:.1f}x"


class WriteClock:
    """Zeit und Schreibrate fürs Protokoll. IMAPI2s RemainingTime taugt nicht (im echten Lauf ab 30 % nur 0 s);
    die Rate wird je Abschnitt zwischen zwei Protokollzeilen gemessen, so sieht man auch, wenn das Laufwerk bremst."""

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


def failure_text(elapsed: float, start_lba: Optional[int], count: int, last_lba: Optional[int], state: str) -> str:
    """Eine Zeile nach einem Schreibfehler: wann, wie weit IMAPI2 gekommen ist, wie die Disc jetzt dasteht."""
    parts = [f"IMAPI2: Fehler nach {duration_text(elapsed)}"]
    if last_lba is not None and count > 0:
        start = start_lba or 0
        parts.append(f"zuletzt gemeldet LBA {last_lba} von {start + count} "
                     f"({(last_lba - start) / count * 100:.1f} %)")
    else:
        parts.append("Schreiben hatte noch nicht begonnen")
    parts.append(f"Disc danach: {state}")
    return " · ".join(parts)


class WriteTracker:
    """Wertet die Update-Ereignisse von Write aus: Phase und Fortschritt."""

    def __init__(self):
        self.phase = PHASE_PREPARE
        self.progress: Optional[float] = None
        self.action: Optional[int] = None

    def feed(self, action: int, start_lba: int, sector_count: int, last_written_lba: int) -> bool:
        """True, wenn sich die Phase geändert hat."""
        self.action = action
        before = self.phase
        if action == ACTION_FORMATTING:
            self.phase, self.progress = PHASE_ERASE, None
        elif action == ACTION_WRITING:
            self.phase = PHASE_WRITE
            if sector_count > 0:
                self.progress = max(0.0, min(1.0, (last_written_lba - start_lba) / sector_count))
        elif action in (ACTION_FINALIZATION, ACTION_COMPLETED):
            self.phase, self.progress = PHASE_WRITE, 1.0
        elif action == ACTION_VERIFYING:
            self.phase, self.progress = PHASE_WRITE, None      # IMAPI2 prüft kurz selbst (Stichprobe)
        else:
            self.progress = None
        return self.phase != before


# --- COM ------------------------------------------------------------------------------------

@contextmanager
def com_thread():
    """COM für diesen Thread (MTA). Ist der Thread schon anders initialisiert (GUI-Thread: STA), wird das genutzt."""
    ole32 = ctypes.windll.ole32
    hr = ole32.CoInitializeEx(None, COINIT_MULTITHREADED)
    try:
        yield
    finally:
        if hr >= 0:                     # S_OK oder S_FALSE: wieder freigeben
            ole32.CoUninitialize()


def _comtypes():
    import comtypes                     # noqa: F401  (initialisiert COM im importierenden Thread)
    import comtypes.client
    return comtypes


def _create(progid: str):
    return _comtypes().client.CreateObject(progid, dynamic=True)


def _open_stream(path: str):
    from comtypes import IUnknown
    stream = ctypes.POINTER(IUnknown)()
    ctypes.OleDLL("shlwapi").SHCreateStreamOnFileEx(
        ctypes.c_wchar_p(path), STGM_READ | STGM_SHARE_DENY_WRITE, FILE_ATTRIBUTE_NORMAL, False, None,
        ctypes.byref(stream))
    return stream


_SINKS = None


def _sink_classes():
    """Ereignis-Schnittstellen und Empfänger (einmal je Prozess angelegt)."""
    global _SINKS
    if _SINKS is None:
        import comtypes
        from comtypes import COMMETHOD, GUID, HRESULT
        from comtypes.automation import IDispatch

        class DDiscFormat2DataEvents(IDispatch):
            _iid_ = GUID(IID_DATA_EVENTS)
            _methods_ = [COMMETHOD([], HRESULT, "Update", (["in"], ctypes.POINTER(IDispatch), "object"),
                                   (["in"], ctypes.POINTER(IDispatch), "progress"))]

        class DDiscFormat2EraseEvents(IDispatch):
            _iid_ = GUID(IID_ERASE_EVENTS)
            _methods_ = [COMMETHOD([], HRESULT, "Update", (["in"], ctypes.POINTER(IDispatch), "object"),
                                   (["in"], ctypes.c_int, "elapsedSeconds"),
                                   (["in"], ctypes.c_int, "estimatedTotalSeconds"))]

        class _Sink(comtypes.COMObject):
            """Empfänger für beide Aufrufwege: Vtable (Update) und IDispatch::Invoke (DISPID 0x200). Welchen IMAPI2
            nimmt, steht nicht in der Doku; eine Ausnahme im Handler wird gemerkt statt verschluckt."""

            def __init__(self, handler):
                super().__init__()
                self.handler = handler
                self.calls = {"vtable": 0, "invoke": 0}
                self.error: Optional[str] = None

            def _deliver(self, way, values):
                self.calls[way] += 1
                try:
                    self.handler(*self._convert(values))
                except Exception as e:
                    if self.error is None:
                        self.error = f"{type(e).__name__}: {e}"

            def IDispatch_GetTypeInfoCount(self, this, pctinfo):
                if pctinfo:
                    pctinfo[0] = 0
                return 0

            def IDispatch_Invoke(self, this, dispid, riid, lcid, flags, params, result, excepinfo, argerr):
                args = []
                if params:
                    p = params[0]
                    args = [p.rgvarg[i].value for i in range(p.cArgs)][::-1]    # rgvarg steht rückwärts
                self._deliver("invoke", args)
                return 0

        class DataSink(_Sink):
            _com_interfaces_ = [DDiscFormat2DataEvents]

            def _convert(self, values):
                from comtypes.client.dynamic import Dispatch
                return (Dispatch(values[1]),)

            def Update(self, this, obj, progress):
                self._deliver("vtable", (obj, progress))
                return 0

        class EraseSink(_Sink):
            _com_interfaces_ = [DDiscFormat2EraseEvents]

            def _convert(self, values):
                return int(values[1]), int(values[2])

            def Update(self, this, obj, elapsed, total):
                self._deliver("vtable", (obj, elapsed, total))
                return 0

        _SINKS = (DDiscFormat2DataEvents, DataSink, DDiscFormat2EraseEvents, EraseSink)
    return _SINKS


def _sink_summary(sink) -> str:
    """Für das Protokoll: wie viele Ereignisse ankamen und auf welchem Weg, dazu ein Fehler im Handler."""
    calls = getattr(sink, "calls", None)
    if calls is None:
        return ""
    text = f" · events vtable {calls['vtable']}, invoke {calls['invoke']}"
    error = getattr(sink, "error", None)
    return text + (f" · handler error {error}" if error else "")


@contextmanager
def _advise(com_object, interface, sink):
    from comtypes.connectionpoints import IConnectionPointContainer
    container = com_object._comobj.QueryInterface(IConnectionPointContainer)
    point = container.FindConnectionPoint(ctypes.byref(interface._iid_))
    cookie = point.Advise(sink)
    try:
        yield
    finally:
        try:
            point.Unadvise(cookie)
        except Exception:
            pass


def _recorders() -> List[Tuple[str, object]]:
    master = _create("IMAPI2.MsftDiscMaster2")
    result = []
    for index in range(int(master.Count)):
        unique_id = str(master.Item(index))
        recorder = _create("IMAPI2.MsftDiscRecorder2")
        recorder.InitializeDiscRecorder(unique_id)
        result.append((unique_id, recorder))
    return result


def _recorder(drive: Drive):
    recorder = _create("IMAPI2.MsftDiscRecorder2")
    recorder.InitializeDiscRecorder(drive.key)
    return recorder


def _drive_from(unique_id: str, recorder) -> Drive:
    name = " ".join(part for part in (str(recorder.VendorId or "").strip(), str(recorder.ProductId or "").strip())
                    if part)
    return Drive(key=unique_id, name=name or unique_id, can_write_bd=can_write_bd(recorder.SupportedProfiles),
                 device=device_path(recorder.VolumePathNames),
                 interconnect="USB" if "usbstor" in unique_id.lower() else "")


def _read_media(recorder) -> Tuple[Media, Dict[str, int]]:
    """Medium und die Geschwindigkeiten (Etikett → Sektoren/s)."""
    if not tuple(recorder.CurrentProfiles or ()):
        return Media(present=False), {}
    data = _create("IMAPI2.MsftDiscFormat2Data")
    if not data.IsRecorderSupported(recorder):
        return Media(present=True, status="recorder not supported"), {}
    data.Recorder = recorder
    media_type = int(data.CurrentPhysicalMediaType)
    if not data.IsCurrentMediaSupported(recorder):
        media_class, kind = MEDIA_TYPES.get(media_type, ("", ""))
        return Media(present=True, media_class=media_class, kind=kind, status="media not supported"), {}
    sectors = []
    for descriptor in tuple(data.SupportedWriteSpeedDescriptors or ()):
        try:
            sectors.append(int(descriptor.WriteSpeed))
        except Exception:
            pass
    media = media_from_values(media_type, int(data.CurrentMediaStatus), bool(data.MediaHeuristicallyBlank),
                              int(data.FreeSectorsOnMedia), int(data.TotalSectorsOnMedia), sectors)
    speeds = {}
    for value in sorted(set(sectors)):
        speeds.setdefault(speed_label(value), value)
    return media, speeds


def _media_state(recorder) -> str:
    """Zustand der Disc nach einem Fehler (z. B. „non-empty session“: offen geblieben, nicht abgeschlossen)."""
    try:
        data = _create("IMAPI2.MsftDiscFormat2Data")
        data.Recorder = recorder
        return status_text(int(data.CurrentMediaStatus))
    except Exception as e:
        return f"unbekannt ({com_error_text(e)})"


class WindowsBackend:
    name = "windows-imapi2"
    verifies_itself = True       # burn() prüft selbst (Rücklesen über \\.\X:)
    erase_with_burn = True

    def __init__(self):
        self._error: Optional[str] = None
        try:
            _comtypes()
        except Exception as e:
            self._error = f"{type(e).__name__}: {e}"

    def unavailable_reason(self):
        if self._error is not None:
            return "burn_windows_no_imapi", {"error": self._error}
        return None

    def list_drives(self) -> List[Drive]:
        with com_thread():
            try:
                return [_drive_from(uid, recorder) for uid, recorder in _recorders()]
            except Exception:
                return []

    def media_info(self, drive: Drive) -> Media:
        with com_thread():
            try:
                media, _speeds = _read_media(_recorder(drive))
                return media
            except Exception as e:
                return Media(present=True, busy=True, status=com_error_text(e))

    def eject(self, drive: Drive) -> bool:
        with com_thread():
            try:
                _recorder(drive).EjectMedia()
                return True
            except Exception:
                return False

    def _erase(self, recorder, report):
        """BD-RE schnell löschen (MsftDiscFormat2Erase, FullErase False)."""
        _data_events, _data_sink, erase_events, erase_sink = _sink_classes()
        eraser = _create("IMAPI2.MsftDiscFormat2Erase")
        eraser.Recorder = recorder
        eraser.FullErase = False
        eraser.ClientName = CLIENT_NAME

        def on_update(elapsed: int, total: int):
            report.progress(min(1.0, elapsed / total) if total > 0 else None)

        report.phase(PHASE_ERASE)
        sink = erase_sink(on_update)
        with _advise(eraser, erase_events, sink):
            try:
                eraser.EraseMedia()
            except Exception as e:
                raise BurnError(com_error_text(e), PHASE_ERASE)
        report.log("IMAPI2: EraseMedia done" + _sink_summary(sink))

    def burn(self, drive: Drive, iso_path: str, options: BurnOptions, report) -> BurnResult:
        with com_thread():
            self._burn(drive, iso_path, options, report)
        if not options.verify:
            return BurnResult(verified=False)
        from modules.burn.verify import compare_with_device
        device = drive.device or self._device_after(drive)
        if not device:
            raise BurnError("Kein Laufwerksbuchstabe für das Prüfen", PHASE_VERIFY)
        report.phase(PHASE_VERIFY)
        return BurnResult(verified=compare_with_device(device, iso_path, report))

    def _device_after(self, drive: Drive) -> str:
        with com_thread():
            try:
                return device_path(_recorder(drive).VolumePathNames)
            except Exception:
                return ""

    def _burn(self, drive: Drive, iso_path: str, options: BurnOptions, report):
        data_events, data_sink, _erase_events, _erase_sink = _sink_classes()
        try:
            recorder = _recorder(drive)
            media, speeds = _read_media(recorder)
        except Exception as e:
            raise BurnError(com_error_text(e), PHASE_PREPARE)
        if not media.present:
            raise BurnError("Kein Medium im Laufwerk", PHASE_PREPARE)
        report.log(f"IMAPI2: {drive.name} · {media.kind} · {media.status} · {media.free_blocks} Sektoren frei · "
                   f"Stufen {', '.join(speeds) or '–'}")
        if report.cancelled():
            raise BurnCancelled(PHASE_PREPARE)
        try:
            recorder.AcquireExclusiveAccess(True, CLIENT_NAME)
        except Exception as e:
            raise BurnError(com_error_text(e), PHASE_PREPARE)
        mcn_disabled = False
        try:
            try:
                recorder.DisableMcn()
                mcn_disabled = True
            except Exception:
                pass
            if options.erase and media.is_rewritable:
                self._erase(recorder, report)
                if report.cancelled():
                    raise BurnCancelled(PHASE_ERASE)
            writer = _create("IMAPI2.MsftDiscFormat2Data")
            writer.Recorder = recorder
            writer.ClientName = CLIENT_NAME
            writer.ForceMediaToBeClosed = True
            if media.is_rewritable:
                writer.ForceOverwrite = True
            if options.speed and options.speed in speeds:
                writer.SetWriteSpeed(speeds[options.speed], False)
                report.log(f"IMAPI2: SetWriteSpeed({speeds[options.speed]}) = {options.speed}")
            elif options.speed:
                report.log(f"IMAPI2: {options.speed} wird für dieses Medium nicht angeboten – das Laufwerk wählt")
            else:
                report.log("IMAPI2: keine Geschwindigkeit gesetzt – das Laufwerk wählt (meist die höchste)")
            stream = _open_stream(iso_path)
            tracker = WriteTracker()
            cancel_sent = threading.Event()
            logged = {"action": None, "tenth": -1, "speed": False}
            last = {"start": None, "count": 0, "lba": None}
            clock = WriteClock(time.monotonic())

            cancel_lock = threading.Lock()

            def cancel_if_wanted():
                """CancelWrite einmal senden – aus dem Ereignis heraus (so die Doku) oder vom Wächter-Thread, falls
                keine Ereignisse kommen."""
                with cancel_lock:
                    if report.cancelled() and not cancel_sent.is_set():
                        cancel_sent.set()
                        report.log("IMAPI2: CancelWrite")
                        try:
                            writer.CancelWrite()
                        except Exception as e:
                            report.log(f"IMAPI2: CancelWrite: {com_error_text(e)}")

            def on_update(args):
                cancel_if_wanted()
                action = int(args.CurrentAction)
                lba = int(args.LastWrittenLba) if action == ACTION_WRITING else 0
                start, count = int(args.StartLba), int(args.SectorCount)
                if action == ACTION_WRITING:
                    last.update(start=start, count=count, lba=lba)
                if tracker.feed(action, start, count, lba):
                    report.phase(tracker.phase)
                if action != logged["action"]:
                    logged["action"] = action
                    report.log(f"IMAPI2: CurrentAction {action} ({ACTION_NAMES.get(action, '?')}) · "
                               f"{duration_text(time.monotonic() - clock.started)}")
                if action == ACTION_WRITING and not logged["speed"]:
                    logged["speed"] = True
                    try:
                        current = int(writer.CurrentWriteSpeed)
                        report.log(f"IMAPI2: Schreibgeschwindigkeit {current} Sektoren/s ≈ {speed_label(current)}")
                    except Exception as e:
                        report.log(f"IMAPI2: Schreibgeschwindigkeit unbekannt ({com_error_text(e)})")
                report.progress(tracker.progress)
                if action == ACTION_WRITING and tracker.progress is not None:
                    tenth = int(tracker.progress * 10)
                    if tenth != logged["tenth"]:                # ins Protokoll etwa alle 10 %
                        logged["tenth"] = tenth
                        report.log(f"IMAPI2: {tracker.progress * 100:.0f} % · LBA {lba} · "
                                   + clock.text(time.monotonic(), start + count, lba))

            report.phase(PHASE_WRITE)
            report.progress(None)
            tracker.phase = PHASE_WRITE
            started = time.monotonic()
            sink = data_sink(on_update)
            done = threading.Event()

            def watch_cancel():
                with com_thread():
                    while not done.wait(0.5):
                        cancel_if_wanted()

            watcher = threading.Thread(target=watch_cancel, daemon=True)
            with _advise(writer, data_events, sink):
                watcher.start()
                try:
                    writer.Write(stream)
                except Exception as e:
                    if cancel_sent.is_set() or error_code(e) == E_IMAPI_REQUEST_CANCELLED:
                        raise BurnCancelled(tracker.phase if tracker.phase != PHASE_PREPARE else PHASE_WRITE)
                    report.log(failure_text(time.monotonic() - started, last["start"], last["count"], last["lba"],
                                            _media_state(recorder)) + _sink_summary(sink))
                    raise BurnError(com_error_text(e), PHASE_WRITE)
                finally:
                    done.set()
                    watcher.join(2.0)
            if cancel_sent.is_set():
                raise BurnCancelled(PHASE_WRITE)
            report.progress(1.0)
            report.log(f"IMAPI2: Write done ({time.monotonic() - started:.0f} s)" + _sink_summary(sink))
        finally:
            if mcn_disabled:
                try:
                    recorder.EnableMcn()
                except Exception:
                    pass
            try:
                recorder.ReleaseExclusiveAccess()
            except Exception:
                pass

    def diagnose(self) -> str:
        """Rohwerte von IMAPI2 für Rückmeldungen (nur lesend)."""
        parts = [f"comtypes: {self._error or 'ok'}", f"Windows: {sys.getwindowsversion()}"
                 if hasattr(sys, "getwindowsversion") else ""]
        with com_thread():
            try:
                master = _create("IMAPI2.MsftDiscMaster2")
                parts.append(f"MsftDiscMaster2: Count {master.Count}, IsSupportedEnvironment "
                             f"{master.IsSupportedEnvironment}")
                for uid, recorder in _recorders():
                    parts += [f"--- {uid}",
                              f"VendorId {recorder.VendorId!r} ProductId {recorder.ProductId!r} "
                              f"ProductRevision {recorder.ProductRevision!r}",
                              f"VolumePathNames {tuple(recorder.VolumePathNames or ())}",
                              f"SupportedProfiles {tuple(recorder.SupportedProfiles or ())}",
                              f"CurrentProfiles {tuple(recorder.CurrentProfiles or ())}",
                              f"ExclusiveAccessOwner {recorder.ExclusiveAccessOwner!r}"]
                    try:
                        data = _create("IMAPI2.MsftDiscFormat2Data")
                        parts.append(f"IsRecorderSupported {data.IsRecorderSupported(recorder)} "
                                     f"IsCurrentMediaSupported {data.IsCurrentMediaSupported(recorder)}")
                        data.Recorder = recorder
                        parts.append(f"CurrentPhysicalMediaType {data.CurrentPhysicalMediaType} "
                                     f"CurrentMediaStatus {data.CurrentMediaStatus} "
                                     f"({status_text(int(data.CurrentMediaStatus))}) "
                                     f"MediaHeuristicallyBlank {data.MediaHeuristicallyBlank}")
                        parts.append(f"FreeSectorsOnMedia {data.FreeSectorsOnMedia} "
                                     f"TotalSectorsOnMedia {data.TotalSectorsOnMedia} "
                                     f"NextWritableAddress {data.NextWritableAddress}")
                        parts.append("SupportedWriteSpeedDescriptors " + ", ".join(
                            f"{d.WriteSpeed} ({speed_label(int(d.WriteSpeed))})"
                            for d in tuple(data.SupportedWriteSpeedDescriptors or ())))
                    except Exception as e:
                        parts.append(f"Medium: {com_error_text(e)}")
                    device = device_path(recorder.VolumePathNames)
                    if device:
                        from modules.burn.verify import device_size
                        parts.append(f"{device}: {device_size(device)} Byte, lesbar: {_readable(device)}")
            except Exception as e:
                parts.append(f"IMAPI2: {com_error_text(e)}")
        return "\n".join(p for p in parts if p)


def _readable(device: str) -> str:
    try:
        with open(device, "rb", buffering=0) as f:
            return "ja" if len(f.read(2048)) == 2048 else "kurz"
    except OSError as e:
        return f"nein ({e})"
