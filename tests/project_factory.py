# tests/project_factory.py
"""
Testprojekte direkt im Datenmodell (ab v1.12; bis v1.11 entstanden sie über die frühere Oberfläche und
core/disc_migration.py). Startprojekt Start → Hauptmenü („FILM STARTEN“) → Hauptfilm, dazu auf Wunsch
Kapitel, Spuren, weitere Filme sowie Kapitel- und Sprachmenü aus den Vorlagen.
Hauptmenü und Vorlagen-Menüs bekommen hier den Text-Stil wie bis v1.13.1 (Lage und Größe der Buttons in den
Tests); neue Menüs im Programm haben ab v1.13.2 den Stil „Form“, die Startvorlage ab v1.14.5.
"""

from core.disc_edit import starter_project, add_film, add_nav_button
from core.disc_model import Chapter, Track, DiscProject, STYLE_TEXT
from core import menu_templates, menu_layout

LANGS = ["deu", "eng", "fra", "spa"]


def temp_media(testcase, name: str) -> str:
    """Leere Mediendatei name in einem temporären Ordner (wird mit dem Test entfernt) – für Prüfungen, die
    vorhandene Dateien erwarten (ab v1.17.0 sind fehlende Dateien ein Fehler und im Inspektor markiert)."""
    import os
    import tempfile
    tmp = tempfile.TemporaryDirectory()
    testcase.addCleanup(tmp.cleanup)
    path = os.path.join(tmp.name, name).replace("\\", "/")
    open(path, "wb").close()
    return path


def text_starter() -> DiscProject:
    """Startvorlage wie bis v1.14.4: Hauptmenü mit Text-Buttons (Lage und Größe 380 × 70 in den Tests)."""
    project = starter_project()
    main = project.main_menu
    main.button_style.kind = STYLE_TEXT
    menu_layout.arrange(main, main.buttons)
    return project


def make_project(chapters: int = 0, audio: int = 0, subs: int = 0, extra_films: int = 0,
                 chapter_menu: bool = False, language_menu: bool = False, language_mode: str = None,
                 video: bool = True) -> DiscProject:
    project = text_starter()
    film = project.films[0]
    film.name = "Hauptfilm"
    if video:
        film.video_base = "C:/clips/main.264"
    film.chapters = [Chapter(id=f"ch{i + 1}", time=f"00:{i * 5:02d}:00.000") for i in range(chapters)]
    film.audio_tracks = [Track(id=f"a{i + 1}", path=f"C:/a{i}.ac3", lang=LANGS[i % 4]) for i in range(audio)]
    film.subtitle_tracks = [Track(id=f"s{i + 1}", path=f"C:/s{i}.sup", lang=LANGS[(i + 1) % 4]) for i in range(subs)]
    main = project.main_menu
    for i in range(extra_films):
        extra = add_film(project, f"Bonus {i + 1}", (720.0, 200.0 * (i + 1)))
        if video:
            extra.video_base = f"C:/clips/bonus{i}.264"
        add_nav_button(project, main.id, extra.name.upper(), extra.id)
    created = []
    if chapter_menu:
        created += menu_templates.create_chapter_menus(project, film.id, parent_id=main.id)
    if language_menu:
        created += menu_templates.create_language_menus(project, film.id, language_mode, parent_id=main.id)
    for menu in created:
        menu.button_style.kind = STYLE_TEXT
    return project
