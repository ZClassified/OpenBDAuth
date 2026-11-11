# modules/burn/__init__.py
"""
Arbeitsbereich Brennen (Plan docs/plaene/brennen.md): eine fertige ISO 1:1 auf Blu-ray schreiben, mit dem Brenner
des Systems. Ein Backend je System: macOS (hdiutil/drutil, v1.30), Linux (xorriso, v1.31),
Windows (IMAPI2, v1.32).
"""

import os
import sys


def get_backend():
    """Backend für dieses System, None, wenn es hier noch keins gibt."""
    if os.environ.get("OPENBDAUTH_FAKE_BURNER") == "1":
        from modules.burn.fake import FakeBackend
        return FakeBackend(step_seconds=0.3, steps=30)
    if sys.platform == "darwin":
        from modules.burn.macos import MacBackend
        return MacBackend()
    if sys.platform.startswith("linux"):
        from modules.burn.linux import LinuxBackend
        return LinuxBackend()
    if sys.platform == "win32":
        from modules.burn.windows import WindowsBackend
        return WindowsBackend()
    return None
