# core/constants.py
"""
Globale Konstanten und standardkonforme ISO 639-2 Sprachdefinitionen für OpenBDAuth.
"""

import re
from typing import Dict, List, Tuple

APP_NAME = "OpenBDAuth"
APP_VERSION = "1.32.0"

# ----------------------------------------------------------------------
# 1. PINNED LANGUAGES (Häufigste Sprachen an oberster Stelle)
# ----------------------------------------------------------------------
PINNED_LANGUAGES: List[Tuple[str, str]] = [
    ("Deutsch [deu]", "deu"),
    ("English [eng]", "eng"),
    ("Français [fra]", "fra"),
    ("Español [spa]", "spa"),
    ("Italiano [ita]", "ita"),
    ("日本語 (Japanese) [jpn]", "jpn"),
]

# ----------------------------------------------------------------------
# 2. VOLLSTÄNDIGER ISO 639-2 WELTSPRACHEN-KATALOG (Alphabetisch)
# ----------------------------------------------------------------------
ISO_639_2_CATALOG: List[Tuple[str, str]] = [
    ("Afrikaans [afr]", "afr"),
    ("Albanisch [sqi]", "sqi"),
    ("Amharisch [amh]", "amh"),
    ("Arabisch [ara]", "ara"),
    ("Armenisch [hye]", "hye"),
    ("Aserbaidschanisch [aze]", "aze"),
    ("Baskisch [eus]", "eus"),
    ("Bengalisch [ben]", "ben"),
    ("Birmanisch [mya]", "mya"),
    ("Bosnisch [bos]", "bos"),
    ("Bulgarisch [bul]", "bul"),
    ("Chinesisch (Kantonesisch) [yue]", "yue"),
    ("Chinesisch (Mandarin) [zho]", "zho"),
    ("Dänisch [dan]", "dan"),
    ("Deutsch [deu]", "deu"),
    ("English [eng]", "eng"),
    ("Esperanto [epo]", "epo"),
    ("Estnisch [est]", "est"),
    ("Färöisch [fao]", "fao"),
    ("Finnisch [fin]", "fin"),
    ("Französisch [fra]", "fra"),
    ("Galicisch [glg]", "glg"),
    ("Georgisch [kat]", "kat"),
    ("Griechisch (Alt) [grc]", "grc"),
    ("Griechisch (Neu) [ell]", "ell"),
    ("Hebräisch [heb]", "heb"),
    ("Hindi [hin]", "hin"),
    ("Indonesisch [ind]", "ind"),
    ("Irisch [gle]", "gle"),
    ("Isländisch [isl]", "isl"),
    ("Italienisch [ita]", "ita"),
    ("Japanisch [jpn]", "jpn"),
    ("Jiddisch [yid]", "yid"),
    ("Katalanisch [cat]", "cat"),
    ("Kasachisch [kaz]", "kaz"),
    ("Khmer [khm]", "khm"),
    ("Koreanisch [kor]", "kor"),
    ("Kroatisch [hrv]", "hrv"),
    ("Kurdisch [kur]", "kur"),
    ("Laotisch [lao]", "lao"),
    ("Latein [lat]", "lat"),
    ("Lettisch [lav]", "lav"),
    ("Litauisch [lit]", "lit"),
    ("Luxemburgisch [ltz]", "ltz"),
    ("Malagassi [mlg]", "mlg"),
    ("Malaiisch [msa]", "msa"),
    ("Maltesisch [mlt]", "mlt"),
    ("Mazedonisch [mkd]", "mkd"),
    ("Mongolisch [mon]", "mon"),
    ("Nepalesisch [nep]", "nep"),
    ("Niederländisch [nld]", "nld"),
    ("Norwegisch (Bokmål) [nob]", "nob"),
    ("Norwegisch (Nynorsk) [nno]", "nno"),
    ("Norwegisch [nor]", "nor"),
    ("Originalton (O-Ton) [qaa]", "qaa"),
    ("Paschtu [pus]", "pus"),
    ("Persisch (Farsi) [fas]", "fas"),
    ("Polnisch [pol]", "pol"),
    ("Portugiesisch (Brasilien) [por]", "por"),
    ("Portugiesisch (Portugal) [por]", "por"),
    ("Panjabi [pan]", "pan"),
    ("Rätoromanisch [roh]", "roh"),
    ("Rumänisch [ron]", "ron"),
    ("Russisch [rus]", "rus"),
    ("Sanskrit [san]", "san"),
    ("Schottisch-Gälisch [gla]", "gla"),
    ("Schwedisch [swe]", "swe"),
    ("Schweizerdeutsch [gsw]", "gsw"),
    ("Serbisch [srp]", "srp"),
    ("Serbokroatisch [hbs]", "hbs"),
    ("Slowakisch [slk]", "slk"),
    ("Slowenisch [slv]", "slv"),
    ("Somali [som]", "som"),
    ("Spanisch [spa]", "spa"),
    ("Suaheli [swa]", "swa"),
    ("Tagalog / Filipino [tgl]", "tgl"),
    ("Tamil [tam]", "tam"),
    ("Telugu [tel]", "tel"),
    ("Thailändisch [tha]", "tha"),
    ("Tibetisch [bod]", "bod"),
    ("Tschechisch [ces]", "ces"),
    ("Türkisch [tur]", "tur"),
    ("Ukrainisch [ukr]", "ukr"),
    ("Ungarisch [hun]", "hun"),
    ("Urdu [urd]", "urd"),
    ("Usbekisch [uzb]", "uzb"),
    ("Vietnamesisch [vie]", "vie"),
    ("Walisisch [cym]", "cym"),
    ("Weißrussisch [bel]", "bel"),
    ("Zulu [zul]", "zul"),
    ("Ohne Sprache / Instrumental [mis]", "mis"),
    ("Unbekannt / Undetermined [und]", "und"),
]

# ----------------------------------------------------------------------
# 3. KOMPATIBILITÄTS-DICTIONARY FÜR BESTEHENDE MODULE
# ----------------------------------------------------------------------
LANGUAGES: Dict[str, str] = {
    # Historische Basis-Keys
    "Deutsch": "deu",
    "English": "eng",
    "Français": "fra",
    "Español": "spa",
    "Italiano": "ita",
    "日本語 (Japanese)": "jpn",
}

# Ergänze alle Katalog-Einträge in LANGUAGES (sowohl reiner Name als auch mit [iso])
for display_name, code in ISO_639_2_CATALOG:
    # 1. Formatierter Name: z. B. "Schwedisch [swe]" -> "swe"
    LANGUAGES[display_name] = code
    # 2. Reiner Name vor der Klammer: z. B. "Schwedisch" -> "swe"
    base_name = display_name.split("[")[0].strip()
    if base_name and base_name not in LANGUAGES:
        LANGUAGES[base_name] = code

# Alternative deutsche Schreibweise für English
LANGUAGES["Englisch"] = "eng"

def language_menu_name(lang_code: str, lang: str = "de") -> str:
    """Sprachname für Disc-Menüs in Großbuchstaben, immer in lateinischer Schrift ('jpn' -> 'JAPANISCH').
    Die Menü-Schrift enthält keine CJK-Zeichen; Originalnamen wie '日本語' erschienen als Kästchen.
    lang „en“ (v1.27.0): englischer Name aus Qt ('jpn' -> 'JAPANESE')."""
    code = (lang_code or "und").lower()
    if lang == "en":
        from PySide6.QtCore import QLocale
        language = QLocale.codeToLanguage(code, QLocale.ISO639Part2)
        return QLocale.languageToString(language).upper() if language != QLocale.AnyLanguage else code.upper()
    if code == "eng":
        return "ENGLISCH"
    for display_name, catalog_code in ISO_639_2_CATALOG:
        if catalog_code == code:
            return display_name.split("[")[0].strip().upper()
    return code.upper()


# Kanonische Namen für Rückwärts-Auflösung (code -> Name) sichern
for _code, _canon_name in [
    ("deu", "Deutsch"),
    ("eng", "English"),
    ("fra", "Français"),
    ("spa", "Español"),
    ("ita", "Italiano"),
    ("jpn", "日本語 (Japanese)"),
]:
    if _canon_name in LANGUAGES:
        del LANGUAGES[_canon_name]
    LANGUAGES[_canon_name] = _code


# Englische Namen, wo Qt keinen oder einen zu allgemeinen kennt
ENGLISH_NAME_OVERRIDES = {"zho": "Chinese (Mandarin)", "yue": "Chinese (Cantonese)"}


def get_language_display_items() -> List[Tuple[str, str]]:
    """
    Liefert die Auswahlliste für ComboBoxen:
    Zuerst die wichtigsten 6 Pinned Languages, gefolgt von der alphabetischen Gesamtliste.
    """
    seen_codes = set()
    items: List[Tuple[str, str]] = []

    # 1. Pinned
    for label, code in PINNED_LANGUAGES:
        items.append((label, code))

    # 2. Trenner optisch andeuten
    items.append(("────────────────────────────", "sep"))

    # 3. Alphabetisch, bei englischer Oberfläche mit englischen Namen aus Qt (v1.27.2)
    from core.translations import ui_language
    if ui_language() == "en":
        from PySide6.QtCore import QLocale
        catalog = []
        for label, code in ISO_639_2_CATALOG:
            language = QLocale.codeToLanguage(code, QLocale.ISO639Part2)
            name = ENGLISH_NAME_OVERRIDES.get(code) or (QLocale.languageToString(language)
                                                         if language != QLocale.AnyLanguage else label.split(" [")[0])
            catalog.append((f"{name} [{code}]", code))
        catalog.sort(key=lambda item: item[0].lower())
    else:
        catalog = list(ISO_639_2_CATALOG)
    items.extend(catalog)

    return items


def resolve_language_code(input_str: str) -> str:
    """
    Löst beliebige Benutzereingaben sicher und fehlertolerant in einen
    exakt 3-stelligen ISO 639-2 Code für tsMuxeR auf.

    Unterstützt:
    - Formatierte Strings: "Deutsch [deu]" -> "deu"
    - Direkte 3-Buchstaben-Codes: "deu", "SWE", "jpn" -> "deu", "swe", "jpn"
    - Exakte oder case-insensitive Namen: "Schwedisch", "koreanisch" -> "swe", "kor"
    - Fallback: "und"
    """
    if not input_str:
        return "und"

    clean = str(input_str).strip()
    if not clean or clean == "sep" or "─────" in clean:
        return "und"

    # 1. Code in eckigen Klammern extrahieren: "Schwedisch [swe]" -> "swe"
    bracket_match = re.search(r'\[([a-zA-Z]{3})\]', clean)
    if bracket_match:
        return bracket_match.group(1).lower()

    # 2. Direkte Eingabe eines 3-stelligen ASCII-Codes: "swe" -> "swe"
    if len(clean) == 3 and clean.isalpha():
        return clean.lower()

    # 3. Exakter Treffer im LANGUAGES Dictionary
    if clean in LANGUAGES:
        return LANGUAGES[clean]

    # 4. Case-Insensitive Treffer
    clean_lower = clean.lower()
    for name, code in LANGUAGES.items():
        if name.lower() == clean_lower:
            return code
        # Teilstring vor eckigen Klammern vergleichen
        base_name = name.split("[")[0].strip().lower()
        if base_name == clean_lower:
            return code

    return "und"


VIDEO_RESOLUTIONS = ["1080p", "1080i", "720p", "2160p (UHD)"]
FRAME_RATES = ["23.976", "24", "25", "29.97", "50", "59.94"]
