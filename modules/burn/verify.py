# modules/burn/verify.py
"""
Disc gegen ISO prüfen (v1.31.0): die Disc über ihr Gerät (Linux /dev/srN, macOS /dev/rdiskN – dort ohne root
lesbar, siehe HARDWARE_TESTS.md 2026-11-11; Windows über den Laufwerksbuchstaben mit
FSCTL_ALLOW_EXTENDED_DASD_IO) blockweise zurücklesen und mit der ISO vergleichen. Jeder Block wird nur einmal
gelesen; der erste abweichende Sektor wird genannt.

Direkt nach dem Brennen kennt das System die neue Größe der Disc manchmal noch nicht (das Gerät ist dann kürzer als
die ISO). Dann wird kurz gewartet; bleibt es dabei, ist die Disc „gebrannt, aber nicht geprüft“ – kein Fehler.
"""

import os
import time
from typing import Optional

from core.translations import tr
from modules.burn.model import BurnCancelled, BurnError, PHASE_VERIFY, SECTOR

BLOCK = 4 * 1024 * 1024
SIZE_WAIT = 60.0             # so lange auf die neue Größe der Disc warten


IOCTL_DISK_GET_LENGTH_INFO = 0x7405C
FSCTL_ALLOW_EXTENDED_DASD_IO = 0x90083


def _windows_device_size(path: str) -> Optional[int]:
    """Windows: seek(END) geht auf dem Laufwerksbuchstaben nicht, die Größe kommt über DeviceIoControl."""
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                     wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                                         wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                         wintypes.LPVOID]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    generic_read, share_rw, open_existing = 0x80000000, 0x3, 3
    handle = kernel32.CreateFileW(path, generic_read, share_rw, None, open_existing, 0, None)
    if handle in (None, wintypes.HANDLE(-1).value):
        return None
    try:
        length, returned = ctypes.c_longlong(0), wintypes.DWORD(0)
        if not kernel32.DeviceIoControl(handle, IOCTL_DISK_GET_LENGTH_INFO, None, 0, ctypes.byref(length),
                                        ctypes.sizeof(length), ctypes.byref(returned), None):
            return None
        return length.value
    finally:
        kernel32.CloseHandle(handle)


def device_size(path: str) -> Optional[int]:
    if os.name == "nt":
        size = _windows_device_size(path)
        if size is not None:
            return size
    try:                                    # Linux, macOS; unter Windows für gewöhnliche Dateien
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return None
    try:
        return os.lseek(fd, 0, os.SEEK_END)
    except OSError:
        return None
    finally:
        os.close(fd)


def allow_reading_past_filesystem(disc) -> bool:
    """Windows: Über den Laufwerksbuchstaben (z. B. I:) endet das Lesen sonst am Ende des Dateisystems, das das
    UDF-Volume meldet. Unsere ISO reicht 288 Sektoren weiter (D4A.iso: Volume 3 868 608, ISO 3 868 896 Sektoren); ohne diese Freigabe
    kämen dort 0 Byte zurück und jede Disc gälte als abweichend (gemessen 2026-11-11)."""
    if os.name != "nt":
        return False
    import ctypes
    import msvcrt
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                                         wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                         wintypes.LPVOID]
    returned = wintypes.DWORD(0)
    try:
        handle = msvcrt.get_osfhandle(disc.fileno())
    except OSError:
        return False
    return bool(kernel32.DeviceIoControl(handle, FSCTL_ALLOW_EXTENDED_DASD_IO, None, 0, None, 0,
                                         ctypes.byref(returned), None))


READ_ATTEMPTS = 3
READ_RETRY_WAIT = 2.0


class DeviceReader:
    """Liest die Disc an festen Stellen. Nach einem Lesefehler wird das Gerät neu geöffnet und derselbe Block erneut
    gelesen. Unter Windows kam beim ersten Brand (2026-11-11) mitten im Prüfen einmal „[Errno 22] Invalid argument“;
    dieselben Sektoren ließen sich danach fehlerfrei lesen und waren identisch."""

    def __init__(self, device: str, attempts: int = READ_ATTEMPTS, retry_wait: float = READ_RETRY_WAIT, log=None):
        self.device = device
        self.attempts = attempts
        self.retry_wait = retry_wait
        self.log = log
        self._file = None

    def _open(self):
        self._file = open(self.device, "rb", buffering=0)
        allow_reading_past_filesystem(self._file)

    def close(self):
        if self._file is not None:
            try:
                self._file.close()
            except OSError:
                pass
            self._file = None

    def read_at(self, pos: int, n: int) -> bytes:
        """n Bytes ab pos (gelesen in ganzen Sektoren). OSError erst nach allen Versuchen."""
        for attempt in range(1, self.attempts + 1):
            try:
                if self._file is None:
                    self._open()
                self._file.seek(pos)
                return self._file.read(-(-n // SECTOR) * SECTOR)[:n]       # Geräte lesen nur ganze Sektoren
            except OSError as e:
                self.close()
                if attempt == self.attempts:
                    raise
                if self.log is not None:
                    self.log(f"Lesefehler bei Sektor {pos // SECTOR} ({e}), Versuch {attempt + 1} von "
                             f"{self.attempts}")
                time.sleep(self.retry_wait)
        raise AssertionError("unreachable")


def compare_streams(disc, iso, size: int, report) -> None:
    """Vergleicht size Bytes; BurnError mit Sektor bei Abweichung oder bleibendem Lesefehler, BurnCancelled bei
    Abbruch. disc: DeviceReader oder ein Dateiobjekt."""
    read_at = disc.read_at if hasattr(disc, "read_at") else (lambda pos, n: disc.read(-(-n // SECTOR) * SECTOR)[:n])
    pos = 0
    while pos < size:
        if report.cancelled():
            raise BurnCancelled(PHASE_VERIFY)
        n = min(BLOCK, size - pos)
        want = iso.read(n)
        try:
            got = read_at(pos, n)
        except OSError as e:
            raise BurnError(tr("burn_verify_read_error", sector=pos // SECTOR, gb=f"{pos / 1e9:.2f}", err=e),
                            PHASE_VERIFY)
        if got != want:
            first = next((i for i in range(min(len(got), len(want))) if got[i] != want[i]), min(len(got), len(want)))
            sector = (pos + first) // SECTOR
            raise BurnError(tr("burn_verify_mismatch", sector=sector, gb=f"{(pos + first) / 1e9:.2f}"), PHASE_VERIFY)
        pos += n
        report.progress(pos / size)


def compare_with_device(device: str, iso_path: str, report, size_wait: float = SIZE_WAIT,
                        retry_wait: float = READ_RETRY_WAIT) -> bool:
    """True: geprüft und identisch. False: nicht prüfbar (Grund im Protokoll). Fehler bei Abweichung."""
    size = os.path.getsize(iso_path)
    deadline = time.monotonic() + size_wait
    while True:
        available = device_size(device)
        if available is not None and available >= size:
            break
        if report.cancelled():
            raise BurnCancelled(PHASE_VERIFY)
        if time.monotonic() > deadline:
            report.log(tr("burn_verify_unavailable", size=available if available is not None else "?"))
            return False
        time.sleep(1.0)
    disc = DeviceReader(device, retry_wait=retry_wait, log=report.log)
    try:
        with open(iso_path, "rb") as iso:
            compare_streams(disc, iso, size, report)
    finally:
        disc.close()
    return True
