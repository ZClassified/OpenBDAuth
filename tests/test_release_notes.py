# tests/test_release_notes.py
"""
Neuerungen im Info-Fenster (v1.28.0): Jede Version ab FIRST_SINGLE_VERSION, die im CHANGELOG steht, hat einen Eintrag
mit demselben Datum, in beiden Sprachen gleich aufgebaut; die laufende Version steht oben. So fällt ein Release ohne
Notizen beim Testen auf.
"""

import os
import re
import unittest

from core.constants import APP_VERSION
from core.release_notes import FIRST_SINGLE_VERSION, RELEASES, date_text, format_date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def version_key(version):
    return tuple(int(part) for part in version.split("."))


def changelog_versions():
    """{Version: Datum} aller Einträge im CHANGELOG."""
    with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as f:
        return dict(re.findall(r"^## \[(\d+\.\d+\.\d+)\] - (\d{4}-\d{2}-\d{2})", f.read(), re.MULTILINE))


class TestReleaseNotes(unittest.TestCase):
    def test_current_version_on_top(self):
        self.assertEqual(RELEASES[0].version, APP_VERSION)

    def test_every_changelog_version_has_notes(self):
        logged = {v: d for v, d in changelog_versions().items()
                  if version_key(v) >= version_key(FIRST_SINGLE_VERSION)}
        noted = {r.version: r.date for r in RELEASES[:-1]}
        self.assertEqual(noted, logged)

    def test_newest_first(self):
        keys = [version_key(r.version) for r in RELEASES[:-1]]
        self.assertEqual(keys, sorted(keys, reverse=True))
        self.assertEqual(len(set(keys)), len(keys))

    def test_summary_covers_everything_before(self):
        summary = RELEASES[-1]
        self.assertTrue(summary.until)
        older = [v for v in changelog_versions() if version_key(v) < version_key(FIRST_SINGLE_VERSION)]
        self.assertTrue(summary.version.endswith(max(older, key=version_key).rsplit(".", 1)[0]))

    def test_both_languages_alike(self):
        for release in RELEASES:
            for notes in (release.de, release.en):
                self.assertTrue(notes.title.strip(), release.version)
                self.assertTrue(notes.points and all(p.strip() for p in notes.points), release.version)
            self.assertEqual(len(release.de.points), len(release.en.points), release.version)

    def test_dates(self):
        self.assertEqual(format_date("2026-10-30", "de"), "30.10.2026")
        self.assertEqual(format_date("2026-09-08", "en"), "8 Sep 2026")
        self.assertEqual(date_text(RELEASES[-1], "de"), "08.09.2026 – 23.10.2026")


if __name__ == "__main__":
    unittest.main()
