# core/release_notes.py
"""
Neuerungen für das Info-Fenster (v1.28.0): je Version eine Überschrift und wenige Stichpunkte aus Sicht der Nutzer,
auf Deutsch und Englisch, neueste zuerst. Gehört zu jedem Release wie der CHANGELOG-Eintrag; der bleibt die
ausführliche, technische Fassung. tests/test_release_notes.py prüft, dass jede Version ab 1.26.0 aus dem CHANGELOG
hier steht, mit demselben Datum und in beiden Sprachen.
"""

from dataclasses import dataclass
from typing import Tuple

# Einzelne Einträge ab dieser Version, alles davor steht im Sammeleintrag
FIRST_SINGLE_VERSION = "1.26.0"


@dataclass(frozen=True)
class Notes:
    title: str
    points: Tuple[str, ...]


@dataclass(frozen=True)
class Release:
    version: str              # "1.27.4", beim Sammeleintrag ein Bereich („0.1 – 1.25“)
    date: str                 # ISO-Datum; beim Sammeleintrag der Beginn des Zeitraums
    de: Notes
    en: Notes
    until: str = ""           # nur beim Sammeleintrag: Ende des Zeitraums

    def notes(self, lang: str) -> Notes:
        return self.de if lang == "de" else self.en


_MONTHS_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def format_date(iso: str, lang: str) -> str:
    """2026-10-30 → „30.10.2026“ bzw. „30 Oct 2026“."""
    year, month, day = iso.split("-")
    if lang == "de":
        return f"{day}.{month}.{year}"
    return f"{int(day)} {_MONTHS_EN[int(month) - 1]} {year}"


def date_text(release: Release, lang: str) -> str:
    text = format_date(release.date, lang)
    return f"{text} – {format_date(release.until, lang)}" if release.until else text


RELEASES: Tuple[Release, ...] = (
    Release("1.32.0", "2026-11-11",
            de=Notes("Brennen jetzt auch unter Windows", (
                "Der Bereich Brennen funktioniert unter Windows mit dem eingebauten Brenndienst, ohne "
                "Zusatzprogramm und ohne Admin-Rechte.",
                "Prüfen nach dem Brennen ist robuster: Ein kurzer Lesefehler bricht nicht mehr ab, die Stelle "
                "wird erneut gelesen.",
            )),
            en=Notes("Burning on Windows too", (
                "The Burn workspace works on Windows with the built-in burning service, without extra software "
                "or admin rights.",
                "Verifying after burning is more robust: a brief read error no longer stops it, the spot is read "
                "again.",
            ))),
    Release("1.31.0", "2026-11-11",
            de=Notes("Brennen jetzt auch unter Linux", (
                "Der Bereich Brennen funktioniert unter Linux mit xorriso. Fehlt es, zeigt OpenBDAuth den passenden "
                "Installationsbefehl.",
                "Neu überall: „Diagnose kopieren“ legt alle Angaben zu Laufwerk und Disc in die Zwischenablage, "
                "zum Weitergeben bei Problemen.",
                "Unter Linux öffnet der Simulator jetzt auch ISO-Dateien.",
            )),
            en=Notes("Burning on Linux too", (
                "The Burn workspace works on Linux with xorriso. If it is missing, OpenBDAuth shows the right "
                "install command.",
                "New everywhere: “Copy diagnostics” puts all drive and disc details on the clipboard, to pass on "
                "when something goes wrong.",
                "On Linux the simulator now opens ISO files too.",
            ))),
    Release("1.30.4", "2026-11-11",
            de=Notes("Größen überall gleich", (
                "Alle Größen rechnen jetzt wie BD-25 und BD-50: Eine ISO hat beim Export und beim Brennen dieselbe "
                "Größe, eine leere BD-25 hat 25,0 GB.",
            )),
            en=Notes("Sizes match everywhere", (
                "All sizes are now counted like BD-25 and BD-50: an ISO has the same size when exporting and "
                "burning, an empty BD-25 holds 25.0 GB.",
            ))),
    Release("1.30.3", "2026-11-11",
            de=Notes("Nach dem Export geht es weiter", (
                "Nach einer ISO ist der Hauptknopf „Zum Brennen“, nach einem BDMV-Ordner „Fertig“. "
                "Erneut exportieren bleibt als normaler Knopf daneben.",
                "Ändert sich das Projekt danach, ist wieder „Export starten“ der Hauptknopf.",
            )),
            en=Notes("Carry on after exporting", (
                "After an ISO the main button is “Go to Burn”, after a BDMV folder “Done”. "
                "Export again stays as a normal button next to it.",
                "If the project changes afterwards, “Start Export” is the main button again.",
            ))),
    Release("1.30.2", "2026-11-11",
            de=Notes("Projekt in der Mitte", (
                "Der Projektname mit dem Menü Neu, Öffnen und Speichern steht jetzt in der Mitte der oberen Leiste. "
                "Links die Bereiche, rechts die Aktionen.",
            )),
            en=Notes("Project in the middle", (
                "The project name with its New, Open and Save menu now sits in the middle of the top bar. "
                "Workspaces on the left, actions on the right.",
            ))),
    Release("1.30.1", "2026-11-11",
            de=Notes("Aufgeräumte Oberfläche auf dem Mac", (
                "Die Schrift in den Knoten ist auf dem Mac so groß wie unter Windows.",
                "Zahlenfelder sehen überall aus wie die übrigen Eingabefelder, mit gut greifbaren Pfeilen.",
                "Beim Export steht die Prozentzahl gut lesbar unter dem Balken, der Füllstand in Vorbereiten neben "
                "dem Balken. Die Lizenzliste im Info-Fenster hat mehr Luft.",
            )),
            en=Notes("Tidier interface on the Mac", (
                "Text in the nodes is as large on the Mac as on Windows.",
                "Number fields look like the other input fields everywhere, with easy-to-hit arrows.",
                "During export the percentage is shown legibly below the bar, the fill level in Prepare next to "
                "the bar. The licence list in the info window has more breathing room.",
            ))),
    Release("1.30.0", "2026-11-11",
            de=Notes("Brennen direkt im Programm (macOS)", (
                "Neuer Bereich Brennen: eine fertige ISO auf Blu-ray brennen, so oft du willst, ohne neu zu packen. "
                "Zuletzt verwendete ISOs stehen gleich bereit.",
                "BD-R und BD-RE: eine BD-RE mit Daten wird nach Rückfrage gelöscht. Auf Wunsch wird die Disc danach "
                "geprüft und nach erfolgreichem Brennen ausgeworfen.",
                "Nach dem Export führt „Zum Brennen“ direkt dorthin. Windows und Linux folgen.",
            )),
            en=Notes("Burn right in the app (macOS)", (
                "New Burn workspace: burn a finished ISO to Blu-ray as often as you like, without rebuilding. "
                "Recently used ISOs are right at hand.",
                "BD-R and BD-RE: a BD-RE with data is erased after asking. Optionally the disc is verified "
                "afterwards and ejected after a successful burn.",
                "After exporting, “Go to Burn” takes you there. Windows and Linux will follow.",
            ))),
    Release("1.29.1", "2026-10-30",
            de=Notes("Hinweis zum Ton in Videos", (
                "Hat ein Video unter Vorbereiten eine Tonspur, weist ein kurzer Hinweis darauf hin, dass sie nicht "
                "übernommen wird. Den Ton bitte als eigene Datei in guter Qualität hinzufügen, zum Beispiel als WAV.",
            )),
            en=Notes("Note on audio in videos", (
                "If a video under Prepare has an audio track, a short note says that it is not used. Please add the "
                "audio as a separate file in good quality, for example as WAV.",
            ))),
    Release("1.29.0", "2026-10-30",
            de=Notes("Neue obere Leiste", (
                "Links stehen Logo, Name und Version. Ein Klick darauf öffnet die Neuerungen, F1 weiterhin das "
                "Info-Fenster.",
                "Vorbereiten und Disc sind Reiter, der aktive Bereich ist unterstrichen.",
                "Neu, Öffnen und Speichern stecken im Menü am Projektnamen. Ein Punkt davor zeigt ungespeicherte "
                "Änderungen; die Tastenkürzel bleiben.",
                "Rückgängig und Wiederholen sind nur noch Symbole, der Tooltip nennt den Schritt.",
                "„Arbeitsbereich“ heißt jetzt „Ansicht“. Bei wenig Platz wird erst der Projektname gekürzt, kein Knopf "
                "verschwindet.",
            )),
            en=Notes("New top bar", (
                "The logo, name and version sit on the left. Clicking them opens What's new; F1 still opens the "
                "About window.",
                "Prepare and Disc are tabs, the active area is underlined.",
                "New, Open and Save live in the menu on the project name. A dot in front of it shows unsaved changes; "
                "the shortcuts stay.",
                "Undo and Redo are icons only, the tooltip names the step.",
                "“Workspace” is now called “View”. When space runs short, the project name is shortened first, no "
                "button disappears.",
            ))),
    Release("1.28.0", "2026-10-30",
            de=Notes("Neuerungen im Info-Fenster", (
                "Neuer Reiter „Neuerungen“ im Info-Fenster (ⓘ oder F1): die wichtigsten Änderungen jeder Version, "
                "in der Sprache der Oberfläche.",
            )),
            en=Notes("What's new in the About window", (
                "New tab “What's new” in the About window (ⓘ or F1): the main changes of every version, in the "
                "interface language.",
            ))),
    Release("1.27.4", "2026-10-30",
            de=Notes("Vorbereiten unter Linux", (
                "Beim Hinzufügen unter Vorbereiten nutzt OpenBDAuth jetzt immer das mitgelieferte ffprobe. Unter Linux "
                "hieß es vorher bei jeder Datei „weder Bild noch Ton gefunden“.",
            )),
            en=Notes("Prepare on Linux", (
                "When adding files under Prepare, OpenBDAuth now always uses the bundled ffprobe. On Linux, every file "
                "was reported as having “neither picture nor audio”.",
            ))),
    Release("1.27.3", "2026-10-30",
            de=Notes("Pakete für Windows, Linux und macOS", (
                "Fertige Pakete für Linux (ab Ubuntu 22.04, Debian 12, Mint 21) und macOS (Apple Silicon, ab macOS 13), "
                "mit ffmpeg und tsMuxeR.",
                "Installer für Windows: ohne Admin-Rechte, mit Eintrag im Startmenü und Deinstallation über „Apps“.",
                "Kann ffprobe eine Datei nicht lesen, nennt Vorbereiten jetzt den Grund statt „weder Bild noch Ton "
                "gefunden“.",
                "Projekte von Windows lassen sich unter Linux und macOS öffnen; ihre Dateien können neu verknüpft "
                "werden.",
                "Text-Buttons sind mindestens 20 Pixel hoch. Flachere ließen Vorschau und Export abbrechen.",
            )),
            en=Notes("Packages for Windows, Linux and macOS", (
                "Ready-made packages for Linux (Ubuntu 22.04, Debian 12, Mint 21 or newer) and macOS (Apple Silicon, "
                "macOS 13 or newer), with ffmpeg and tsMuxeR.",
                "Windows installer: no admin rights needed, Start menu entry, uninstall via “Apps”.",
                "If ffprobe cannot read a file, Prepare now names the reason instead of “neither picture nor audio "
                "found”.",
                "Projects from Windows open on Linux and macOS; their files can be relinked.",
                "Text buttons are at least 20 pixels high. Flatter ones made the preview and the export fail.",
            ))),
    Release("1.27.2", "2026-10-23",
            de=Notes("Meldungen in der Sprache der Oberfläche", (
                "Prüfung vor dem Export, Disc-Simulator, Vorbereiten und die Hinweise zu Videos melden sich jetzt in "
                "der eingestellten Sprache.",
            )),
            en=Notes("Messages in the interface language", (
                "The check before export, the disc simulator, Prepare and the notes on videos now speak the selected "
                "language.",
            ))),
    Release("1.27.1", "2026-10-23",
            de=Notes("Kürzerer Fenstertitel", (
                "Der Fenstertitel zeigt OpenBDAuth, die Version und den Namen der Disc.",
            )),
            en=Notes("Shorter window title", (
                "The window title shows OpenBDAuth, the version and the name of the disc.",
            ))),
    Release("1.27.0", "2026-10-23",
            de=Notes("Sprache der Oberfläche und der Disc getrennt", (
                "Neuer Knopf DE / EN in der oberen Leiste. Die Sprache gilt für das Programm, nicht für ein Projekt; "
                "beim ersten Start folgt sie dem System.",
                "Die „Sprache der Disc“ (Start-Knoten) bestimmt die Beschriftungen auf der Disc, etwa KAPITEL 3 oder "
                "CHAPTER 3. Eine deutsche Disc bleibt deutsch, auch wenn das Programm auf Englisch läuft.",
                "Neue Projekte entstehen in der Sprache der Oberfläche.",
            )),
            en=Notes("Separate languages for the interface and the disc", (
                "New DE / EN button in the top bar. The language applies to the program, not to a project; on the "
                "first start it follows the system.",
                "The “disc language” (start node) sets the labels on the disc, such as CHAPTER 3 or KAPITEL 3. A German "
                "disc stays German even when the program runs in English.",
                "New projects are created in the interface language.",
            ))),
    Release("1.26.1", "2026-10-23",
            de=Notes("Eine Version für alles", (
                "Die separate Designer-Edition gibt es nicht mehr. Menü-Designer und Disc-Simulator sind Teil der "
                "normalen Version.",
                "Bilder und MP4-Dateien gelten auf der Disc-Seite nicht mehr als Platzhalter-Video. Solche Dateien "
                "gehen über Vorbereiten.",
            )),
            en=Notes("One edition for everything", (
                "The separate Designer edition is gone. The menu designer and the disc simulator are part of the "
                "regular version.",
                "Pictures and MP4 files no longer count as placeholder video on the disc page. Such files go through "
                "Prepare.",
            ))),
    Release("1.26.0", "2026-10-23",
            de=Notes("Neuer Name: OpenBDAuth", (
                "Das Programm heißt jetzt OpenBDAuth (vorher BDauthMax). Bestehende Projekte lassen sich weiter öffnen.",
                "Fensteranordnung und Einstellungen von Vorbereiten starten einmal frisch.",
            )),
            en=Notes("New name: OpenBDAuth", (
                "The program is now called OpenBDAuth (formerly BDauthMax). Existing projects still open.",
                "The window layout and the Prepare settings start fresh once.",
            ))),
    Release("0.1 – 1.25", "2026-09-08", until="2026-10-23",
            de=Notes("Die Grundlagen", (
                "Blu-ray-Discs in 2D und 3D (MVC) mit echten HDMV-Menüs, als BDMV-Ordner oder ISO.",
                "Die Disc als Knoten-Graph: Start, Filme und Menüs; jede Verbindung ist ein Sprung auf der Disc.",
                "Menü-Designer im Viewer: Buttons frei platzieren, Formen, Hilfslinien, Ausrichten, eigene "
                "Hintergründe pro Menü (Bild oder Video, mit Musik).",
                "Kapitel-, Ton- und Untertitelmenüs aus Vorlagen und mit dem Generator.",
                "Vorbereiten: beliebiges Material Blu-ray-gerecht umwandeln, auch 3D aus Full-TAB und Full-SBS, mit "
                "Warteschlange.",
                "Prüfung vor dem Export und Disc-Simulator, um die Disc ohne Brennen durchzuklicken.",
            )),
            en=Notes("The foundations", (
                "Blu-ray discs in 2D and 3D (MVC) with real HDMV menus, as a BDMV folder or an ISO.",
                "The disc as a node graph: start, films and menus; every connection is a jump on the disc.",
                "Menu designer in the viewer: place buttons freely, shapes, guide lines, alignment, own backgrounds per "
                "menu (picture or video, with music).",
                "Chapter, audio and subtitle menus from templates and with the generator.",
                "Prepare: turn any material into Blu-ray-ready files, including 3D from full TAB and full SBS, with a "
                "queue.",
                "Check before export and a disc simulator to click through the disc without burning.",
            ))),
)
