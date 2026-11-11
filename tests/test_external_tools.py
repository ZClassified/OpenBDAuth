# tests/test_external_tools.py
"""Externe Werkzeuge finden (v1.19.1): tools/<plattform>/ vor tools/ vor PATH, auf allen drei Systemen."""

import os
import sys
import tempfile
import unittest
from unittest import mock

from modules import external_tools as et


def touch(path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").close()


class TestFindTool(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name

    def _exe(self, name: str) -> str:
        return name + ".exe" if os.name == "nt" else name

    def test_platform_folder_wins_over_tools_and_path(self):
        touch(os.path.join(self.root, "tools", self._exe("ffmpeg")))
        own = os.path.join(self.root, "tools", et.platform_dir(), self._exe("ffmpeg"))
        touch(own)
        self.assertEqual(et.find_tool(et.FFMPEG, [self.root]), own)

    def test_tools_folder_as_before(self):
        old = os.path.join(self.root, "tools", self._exe("tsMuxeR"))
        touch(old)
        self.assertEqual(et.find_tool(et.TSMUXER, [self.root], use_path=False), old)

    def test_missing_without_path(self):
        self.assertIsNone(et.find_tool(et.FFPROBE, [self.root], use_path=False))

    def test_falls_back_to_path(self):
        with mock.patch.object(et.shutil, "which", return_value="/usr/bin/ffprobe") as which:
            self.assertEqual(et.find_tool(et.FFPROBE, [self.root]), "/usr/bin/ffprobe")
            which.assert_called_with("ffprobe")

    def test_tool_path_raises_a_file_not_found_error(self):
        with mock.patch.object(et, "find_tool", return_value=None):
            with self.assertRaises(FileNotFoundError) as ctx:
                et.tool_path(et.FFMPEG)
        self.assertIn(et.tools_folder_hint(), str(ctx.exception))


class TestPlatforms(unittest.TestCase):
    """Linux und macOS: eigene Unterordner, Dateinamen ohne .exe."""

    def test_platform_folders(self):
        for platform, folder in (("win32", "windows"), ("darwin", "macos"), ("linux", "linux")):
            with mock.patch.object(et.sys, "platform", platform):
                self.assertEqual(et.platform_dir(), folder)

    def test_names_without_exe_outside_windows(self):
        with mock.patch.object(et.os, "name", "posix"):
            self.assertEqual(et._file_names(et.TSMUXER), ["tsMuxeR", "tsmuxer"])
        with mock.patch.object(et.os, "name", "nt"):
            self.assertEqual(et._file_names(et.FFMPEG), ["ffmpeg.exe"])

    def test_packaged_app_looks_next_to_the_executable(self):
        with mock.patch.object(et.sys, "frozen", True, create=True), \
                mock.patch.object(et.sys, "executable", os.path.join("C:", os.sep, "Apps", "OpenBDAuth", "OpenBDAuth.exe")), \
                mock.patch.object(et.sys, "_MEIPASS", os.path.join("C:", os.sep, "Apps", "OpenBDAuth", "_internal"),
                                  create=True):
            roots = et.app_roots()
        self.assertEqual(roots[0], os.path.join("C:", os.sep, "Apps", "OpenBDAuth"))
        self.assertIn(os.path.join("C:", os.sep, "Apps", "OpenBDAuth", "_internal"), roots)


if __name__ == "__main__":
    unittest.main()
