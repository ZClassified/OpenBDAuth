# tests/test_meta_generator.py
"""Disc-Titel für den Player (BDMV/META/DL/bdmt_<sprache>.xml, modules/bdmv/meta_generator.py)."""

import datetime
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET

from modules.bdmv.meta_generator import build_bdmt_xml, write_disc_title_meta, META_LANGS

DI = "{urn:BDA:bdmv;discinfo}"


def disc_name(xml_bytes: bytes) -> str:
    """Liest den Titel wie libbluray (meta_parse.c): disclib → di:discinfo → di:title → di:name."""
    root = ET.fromstring(xml_bytes)
    assert root.tag == "{urn:BDA:bdmv;disclib}disclib"
    return root.find(f"{DI}discinfo/{DI}title/{DI}name").text


class TestMetaGenerator(unittest.TestCase):
    def test_xml_structure(self):
        data = build_bdmt_xml("MEIN FILM", "deu", datetime.date(2026, 10, 12))
        self.assertTrue(data.startswith(b'<?xml version="1.0" encoding="UTF-8"?>'))
        self.assertFalse(data.startswith(b"\xef\xbb\xbf"))           # ohne BOM
        root = ET.fromstring(data)
        info = root.find(f"{DI}discinfo")
        self.assertEqual(info.find(f"{DI}date").text, "2026-10-12")
        self.assertEqual(info.find(f"{DI}language").text, "deu")
        self.assertEqual(info.find(f"{DI}title/{DI}numSets").text, "1")
        self.assertEqual(info.find(f"{DI}title/{DI}setNumber").text, "1")
        self.assertEqual(disc_name(data), "MEIN FILM")

    def test_special_characters(self):
        self.assertEqual(disc_name(build_bdmt_xml("  Tom & Jerry <Teil 2> – Ärger  ")), "Tom & Jerry <Teil 2> – Ärger")

    def test_writes_one_file_per_language(self):
        with tempfile.TemporaryDirectory() as tmp:
            bdmv = os.path.join(tmp, "BDMV")
            paths = write_disc_title_meta(bdmv, "TESTDISC")
            self.assertEqual(sorted(os.listdir(os.path.join(bdmv, "META", "DL"))),
                             sorted(f"bdmt_{lang}.xml" for lang in META_LANGS))
            for path in paths:
                with open(path, "rb") as f:
                    data = f.read()
                self.assertEqual(disc_name(data), "TESTDISC")
                lang = os.path.basename(path)[5:8]
                self.assertEqual(ET.fromstring(data).find(f"{DI}discinfo/{DI}language").text, lang)


class TestPlayerTitle(unittest.TestCase):
    def test_derived_from_disc_name(self):
        from core.disc_model import DiscSettings
        self.assertEqual(DiscSettings(project_name="MEIN__FILM_2026").player_title(), "MEIN FILM 2026")
        self.assertEqual(DiscSettings(project_name="").player_title(), "BD DISC")
        self.assertEqual(DiscSettings(project_name="X", disc_title="  Über uns  ").player_title(), "Über uns")

    def test_old_projects_load(self):
        from core.disc_model import DiscProject
        from core.disc_edit import starter_project
        data = starter_project().to_dict()
        for key in ("disc_title", "disc_title_meta"):
            data["settings"].pop(key)
        settings = DiscProject.from_dict(data).settings
        self.assertEqual((settings.disc_title, settings.disc_title_meta), ("", True))


if __name__ == "__main__":
    unittest.main()
