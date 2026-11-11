# tests/test_readme.py
"""Das Versions-Abzeichen oben in beiden READMEs zeigt die Programmversion. Die angezeigte Zahl steht in der
Bild-Adresse (…/badge/Version-1.32.0-orange), nicht im Alternativtext davor – beides muss stimmen."""

import os
import re
import unittest

from core.constants import APP_VERSION

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BADGE = re.compile(r"\[!\[Version ([^\]]+)\]\(https://img\.shields\.io/badge/Version-([^-)]+)-")


class TestReadmeVersion(unittest.TestCase):
    def test_badge_matches_app_version(self):
        for name in ("README.md", "README.de.md"):
            with self.subTest(readme=name):
                with open(os.path.join(ROOT, name), encoding="utf-8") as f:
                    match = BADGE.search(f.read())
                self.assertIsNotNone(match, f"{name}: kein Versions-Abzeichen gefunden")
                alt_text, shown = match.groups()
                self.assertEqual(shown, APP_VERSION, f"{name}: Abzeichen zeigt {shown}")
                self.assertEqual(alt_text, APP_VERSION, f"{name}: Alternativtext nennt {alt_text}")


if __name__ == "__main__":
    unittest.main()
