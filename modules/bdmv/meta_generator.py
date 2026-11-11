# modules/bdmv/meta_generator.py
"""
Disc-Library-Metadaten (BDMV/META/DL/bdmt_<sprache>.xml) nach BD-ROM Part 3.

Standalone-Player zeigen daraus den Disc-Titel an (statt nur des Medientyps wie „BD-RE“);
libbluray liest dieselben Dateien (meta_parse.c). Aufbau:
disclib → di:discinfo mit Datum, Titel (di:name, numSets, setNumber) und Sprache.
Eine Datei je Sprache; der Player wählt die zu seiner Menüsprache passende.
Zusätzliche Dateien – Navigation und Ströme bleiben unverändert.
"""

import datetime
import os
from typing import Iterable, List, Optional
from xml.sax.saxutils import escape

META_LANGS = ("eng", "deu")       # Englisch als Rückfall für alle Player, Deutsch für deutsche Menüsprache

_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<disclib xmlns="urn:BDA:bdmv;disclib" xmlns:di="urn:BDA:bdmv;discinfo" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="urn:BDA:bdmv;disclib disclib.xsd">
  <di:discinfo>
    <di:date>{date}</di:date>
    <di:title>
      <di:name>{name}</di:name>
      <di:numSets>1</di:numSets>
      <di:setNumber>1</di:setNumber>
    </di:title>
    <di:language>{lang}</di:language>
  </di:discinfo>
</disclib>
"""


def build_bdmt_xml(title: str, lang: str = "eng", date: Optional[datetime.date] = None) -> bytes:
    """Inhalt einer bdmt_<lang>.xml (UTF-8, ohne BOM)."""
    date = date or datetime.date.today()
    return _TEMPLATE.format(date=date.isoformat(), name=escape(title.strip()), lang=lang).encode("utf-8")


def write_disc_title_meta(bdmv_dir: str, title: str, langs: Iterable[str] = META_LANGS,
                          date: Optional[datetime.date] = None) -> List[str]:
    """Schreibt BDMV/META/DL/bdmt_<lang>.xml je Sprache. Gibt die geschriebenen Pfade zurück."""
    dl_dir = os.path.join(bdmv_dir, "META", "DL")
    os.makedirs(dl_dir, exist_ok=True)
    paths = []
    for lang in langs:
        path = os.path.join(dl_dir, f"bdmt_{lang}.xml")
        with open(path, "wb") as f:
            f.write(build_bdmt_xml(title, lang, date))
        paths.append(path)
    return paths
