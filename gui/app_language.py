# gui/app_language.py
"""
Sprache der Oberfläche (v1.27.0): eine Programm-Einstellung, nicht mehr Teil des Projekts.
Beim ersten Start gilt die Sprache von Windows (Deutsch → „de“, sonst „en“), danach die zuletzt gewählte.
Das Projekt trägt die Sprache weiter in settings.app_lang, damit alle Stellen sie wie bisher dort lesen;
beim Laden wird sie mit der Programm-Sprache überschrieben.
"""

from PySide6.QtCore import QLocale, QSettings

SETTINGS_ORG = "OpenBDAuth"
SETTINGS_APP = "Studio"
LANGUAGES = ("de", "en")


def system_language() -> str:
    return "de" if QLocale.system().language() == QLocale.German else "en"


def load_app_language() -> str:
    lang = QSettings(SETTINGS_ORG, SETTINGS_APP).value("language")
    return lang if lang in LANGUAGES else system_language()


def save_app_language(lang: str):
    if lang in LANGUAGES:
        QSettings(SETTINGS_ORG, SETTINGS_APP).setValue("language", lang)
