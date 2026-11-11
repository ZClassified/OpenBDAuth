# modules/burn/power.py
"""
Ruhezustand verhindern, solange gebrannt wird. Gelingt das nicht, wird trotzdem gebrannt (nur ein Hinweis im
Protokoll).

- macOS: caffeinate -i -w <eigene PID> (endet spätestens mit dem Programm)
- Windows: SetThreadExecutionState – gilt für den aufrufenden Thread, darum start() und stop() im Brenn-Thread
- Linux: systemd-inhibit mit einem wartenden sleep
"""

import os
import shutil
import subprocess
import sys
from typing import Optional

ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001


class SleepInhibitor:
    def __init__(self, reason: str = "OpenBDAuth"):
        self.reason = reason
        self._proc: Optional[subprocess.Popen] = None
        self._windows = False

    def start(self) -> bool:
        try:
            if sys.platform == "darwin" and shutil.which("caffeinate"):
                self._proc = subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())],
                                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            if os.name == "nt":
                import ctypes
                self._windows = bool(ctypes.windll.kernel32.SetThreadExecutionState(
                    ES_CONTINUOUS | ES_SYSTEM_REQUIRED))
                return self._windows
            if shutil.which("systemd-inhibit"):
                self._proc = subprocess.Popen(
                    ["systemd-inhibit", "--what=sleep:idle", "--who=OpenBDAuth", f"--why={self.reason}",
                     "sleep", "infinity"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
        except Exception:
            self._proc = None
        return False

    def stop(self):
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                pass
            self._proc = None
        if self._windows:
            try:
                import ctypes
                ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
            except Exception:
                pass
            self._windows = False
