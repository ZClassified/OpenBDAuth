# tests/test_selftest.py
"""Selbsttest des Pakets (v1.25.1): aus dem Quellcode derselbe Weg wie im Paket – Kindprozess, kurze 2D- und
3D-Aufträge mit dem mitgelieferten ffmpeg, Ergebnis als JSON."""

import json
import os
import tempfile
import unittest

from modules.prepare import selftest
from tests.prepare_util import needs_ffmpeg


@needs_ffmpeg
class TestSelftest(unittest.TestCase):
    def test_report(self):
        path = os.path.join(tempfile.mkdtemp(prefix="openbdauth_selbsttest_"), "ergebnis.json")
        self.assertEqual(selftest.main(["--selbsttest", path]), 0)
        with open(path, encoding="utf-8") as f:
            report = json.load(f)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["result"]["3d"], ["selbsttest_3d_3D.264", "selbsttest_3d_3D.mvc"])


if __name__ == "__main__":
    unittest.main()
