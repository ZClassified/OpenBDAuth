# core/disc_labels.py
"""
Beschriftungen auf der Disc in der Sprache der Disc (v1.27.0, project.settings.app_lang).
Getrennt von der Sprache der Oberfläche: Eine deutsche Disc behält ZURÜCK und KAPITEL 1, auch wenn das Programm
auf Englisch läuft. Schlüssel ist die deutsche Beschriftung (wie bisher in Projekten gespeichert); Buttons werden
an der Beschriftung in beiden Sprachen wiedererkannt (z. B. WEITER/NEXT im Generator).
"""

DISC_LABELS_EN = {
    "ZURÜCK": "BACK",
    "WEITER": "NEXT",
    "HAUPTMENÜ": "MAIN MENU",
    "FILM STARTEN": "PLAY MOVIE",
    "KAPITEL": "CHAPTERS",
    "SPRACHE": "LANGUAGE",
    "TON": "AUDIO",
    "UNTERTITEL": "SUBTITLES",
    "FILME": "MOVIES",
    "FILM": "MOVIE",
    "NEUER BUTTON": "NEW BUTTON",
    "UNTERTITEL AUS": "SUBTITLES OFF",
    # Namen neuer Knoten (stehen im Graphen und als Vorschlag auf Buttons)
    "Hauptmenü": "Main menu",
    "Hauptfilm": "Main movie",
    "Neuer Film": "New movie",
    "Neues Menü": "New menu",
    "Kapitel": "Chapters",
    "Ton & Untertitel": "Audio & Subtitles",
    "Ton": "Audio",
    "Untertitel": "Subtitles",
}

# Mit Platzhaltern: KAPITEL {n}, TON: {lang}, …
DISC_FORMATS_EN = {
    "KAPITEL {n}": "CHAPTER {n}",
    "TON: {name}": "AUDIO: {name}",
    "UNTERTITEL: {name}": "SUBTITLES: {name}",
    "Kapitel {page}/{count}": "Chapters {page}/{count}",
}


def disc_label(label: str, lang: str) -> str:
    """Deutsche Beschriftung → Beschriftung in der Sprache der Disc."""
    return DISC_LABELS_EN.get(label, label) if lang == "en" else label


def disc_format(pattern: str, lang: str, **kwargs) -> str:
    return (DISC_FORMATS_EN.get(pattern, pattern) if lang == "en" else pattern).format(**kwargs)


def is_label(text: str, label: str) -> bool:
    """Trägt ein Button diese Beschriftung – deutsch oder englisch?"""
    return text in (label, DISC_LABELS_EN.get(label))
