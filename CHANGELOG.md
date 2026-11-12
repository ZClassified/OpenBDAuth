# Changelog

Alle nennenswerten Änderungen an diesem Projekt werden in dieser Datei dokumentiert.

Das Format basiert auf [Keep a Changelog](https://keepachangelog.com/de/1.0.0/),
und dieses Projekt folgt [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.32.2] - 2026-11-12

### Geändert

- **Simulator:** Bei der Simulation aus dem Projekt erklärt ein kurzer Hinweis, dass keine Filmbilder gezeigt werden und wo es Standbilder gibt (fertige Disc öffnen).

## [1.32.1] - 2026-11-12

### Behoben

- **Linux-Paket:** Programme vom System (z. B. zum Einhängen von ISOs im Simulator oder zum Brennen) konnten auf manchen Distributionen nicht starten. Sie laufen jetzt wieder mit den Bibliotheken des Systems.

## [1.32.0] - 2026-11-11

### Brennen unter Windows (IMAPI2)

- **Neues Windows-Backend** (`modules/burn/windows.py`) mit IMAPI2, dem Brenndienst von Windows 10/11 (keine Admin-Rechte): Laufwerke über `MsftDiscMaster2`/`MsftDiscRecorder2`, Medium über `MsftDiscFormat2Data` (Typ, Status, freie Sektoren, Geschwindigkeiten), Brennen mit `Write` und der ISO als `IStream` – roh, Sektor für Sektor, Disc abgeschlossen (`ForceMediaToBeClosed`). BD-RE mit Daten wird vorher schnell gelöscht (`MsftDiscFormat2Erase`, 11 s). Auswerfen mit `EjectMedia`.
- **comtypes mit spätem Binden:** Es wird zur Laufzeit kein Code aus der Typbibliothek erzeugt (kein `comtypes.gen`), das fertige Paket funktioniert ohne Zusatzschritte. Die beiden Ereignis-Schnittstellen sind nachgebildet; der Empfänger nimmt Vtable- und `Invoke`-Aufrufe an und protokolliert, welche ankommen. Abbrechen geht auch ohne Ereignisse (Wächter-Thread ruft `CancelWrite`).
- **Prüfen unter Windows:** über den Laufwerksbuchstaben (`\\.\X:`), Größe über `IOCTL_DISK_GET_LENGTH_INFO`. Ohne `FSCTL_ALLOW_EXTENDED_DASD_IO` endet das Lesen am Ende des UDF-Volumes – die letzten 288 Sektoren unserer ISO fehlten, jede Disc hätte als abweichend gegolten.
- **Prüfen auf allen Systemen:** Ein einzelner Lesefehler bricht nicht mehr ab; das Gerät wird neu geöffnet und der Block bis zu dreimal gelesen. Bleibt er, heißt es „Disc nicht lesbar ab Sektor N“ statt einer rohen Fehlermeldung.
- **Erster Brand unter Windows:** BD-RE mit der 7,92-GB-ISO, 894 s bei 2x; die Disc ist Byte für Byte die ISO (`HARDWARE_TESTS.md`).
- **Abhängigkeit:** `comtypes` (MIT, nur Windows) in `requirements.txt`, `THIRD_PARTY_LICENSES.md`, Lizenztext im Paket.
- **Tests:** `tests/test_burn_windows.py` (IMAPI2-Werte aus dem echten Lauf, Ablauf mit nachgebildeten COM-Objekten: Löschen, Geschwindigkeit, Fehler, Abbruch mit und ohne Ereignisse, Prüfen, erneutes Lesen nach Lesefehler).

## [1.31.0] - 2026-11-11

### Brennen unter Linux (Test mit Betatestern)

- **Neues Linux-Backend** (`modules/burn/linux.py`) mit `xorriso` vom System: Laufwerke (`-devices`), Disc nur lesend und ohne exklusiven Zugriff (`-drive_access shared:readonly -indev … -toc -list_speeds`), Brennen mit `xorriso -as cdrecord -v dev=… -nopad blank=as_needed [speed=Nb] <iso>` – ohne Auffüllen, die Disc ist die ISO 1:1; eine BD-RE mit Daten wird überschrieben, eine unformatierte formatiert; ohne `-multi` wird abgeschlossen. Auswerfen mit `-eject all`.
- **Echte Ausgaben statt Vermutungen:** GNU xorriso 1.5.6 wurde zum Entwickeln auf einem Pseudo-Laufwerk (Datei) betrieben – Fortschritt („16 of 381 MB written“), Erfolg, Fehler („FAILURE“), Abbruch; Formatzeilen für echte Laufwerke aus dem Quelltext. Gefunden dabei: `speed=` braucht das Suffix `b` (sonst CD-Einheiten); nach SIGINT bittet xorriso, „die normale Brenndauer“ vor einem kill -9 abzuwarten (Wartezeit 10 min).
- **Eingehängte Disc:** Hängt der Desktop eine BD-RE mit Daten ein, wird sie vor dem Brennen mit `udisksctl` bzw. `umount` ausgehängt.
- **Prüfen** liest die Disc über `/dev/srN` zurück und vergleicht mit der ISO (`modules/burn/verify.py`, nennt den ersten abweichenden Sektor). Meldet das System die neue Größe der Disc nicht, heißt es „gebrannt, aber nicht geprüft“ statt Fehler.
- **Verständliche Hinweise:** Fehlt `xorriso`, nennt der Bereich die Installationsbefehle (apt, dnf, pacman); findet er keinen Brenner, den Hinweis auf die Gruppe `cdrom`/`optical`.
- **„Diagnose kopieren“** (alle Systeme): Version, System, Rohausgaben der Laufwerksabfrage (nur lesend) und das Protokoll in die Zwischenablage – für Rückmeldungen von Testern und Nutzern.
- **Simulator** öffnet ISOs jetzt auch unter Linux (`udisksctl loop-setup` und `mount`, schreibgeschützt, ohne root).
- **Windows** zeigt weiter einen Hinweis; das Backend (IMAPI2) folgt.
- **Tests:** `tests/test_burn_linux.py` (Auswertung mit echten bzw. dem Quelltext entnommenen Ausgaben, Prüfen gegen Gerät, Hinweise und Diagnose; mit installiertem xorriso ein echter Brand auf ein Pseudo-Laufwerk, Byte für Byte verglichen).

## [1.30.4] - 2026-11-11

### Größenangaben überall gleich (dezimal)

- **Eine Rechnung für alle Größen:** `format_bytes` (`gui/studio/export_activity.py`) rechnet jetzt dezimal, 1 GB = 10⁹ Byte – so wie „BD-25“ und „BD-50“ gemeint sind und wie der Finder zählt. Vorher rechnete der Export binär (1024³), der Bereich Brennen dezimal: Dieselbe ISO hieß „7,4 GB“ im Export und „7,9 GB“ unter Brennen.
- **Füllstand in Vorbereiten** ebenfalls dezimal: Eine leere BD-25 heißt „von 25,0 GB“ statt „von 23,3 GB“, eine BD-50 „von 50,0 GB“.
- Export (Lebenszeichen, Ergebnis, „ISO fertig“), Brennen und die Platz-Meldung in Vorbereiten benutzen dieselbe Funktion. Der Grafik-Speicher der Menüs im Generator bleibt in MiB – das ist ein technisches Limit, keine Disc-Größe.
- **Tests:** `tests/test_export_activity.py` (dezimal, die 7,9-GB-ISO aus dem ersten Brand), `tests/test_prepare_page.py` (Füllstand „von 25,0 GB“).

## [1.30.3] - 2026-11-11

### Nach dem Export: der nächste Schritt ist die Hauptaktion

- **Nach einer ISO** ist der gelbe Knopf rechts unten **„Zum Brennen ▸“** (öffnet den Bereich Brennen mit dieser ISO); „Export starten“ wird zum grauen Knopf **„Erneut exportieren“**. Links unten steht, was entstanden ist: „✓ ISO fertig: D4A.iso · 7,4 GB“. Vorher sah der Dialog nach dem Export aus wie davor, und der gelbe Knopf lud zum nochmaligen Exportieren ein.
- **Nach einem BDMV-Ordner** ist **„Fertig“** der gelbe Knopf (schließt den Dialog), daneben „Erneut exportieren“.
- **Ändert sich das Projekt danach**, ist wieder „Export starten“ die Hauptaktion. Verglichen wird der Inhalt des Projekts ohne die Ansicht (`project_fingerprint`): Graph, Format und Zielordner zählen, Knoten verschieben nicht; ein Rückgängig-Schritt zurück zum exportierten Stand macht die ISO wieder aktuell. Der Rückgängig-Verlauf allein taugte dafür nicht – zusammengefasste Schritte ändern ihn nicht, und die Meldung „geändert“ kommt, bevor er weiterzählt.
- Nach einem fehlgeschlagenen Export, oder wenn die ISO nicht gefunden wird, bleibt alles wie bisher.
- **Tests:** `tests/test_export_next_step.py` (vor dem Export, nach ISO und Ordner, Reihenfolge der Knöpfe, Projekt geändert und zurück, zusammengefasste Schritte, Knoten verschieben, Fehler, anderes Projekt).

## [1.30.2] - 2026-11-11

### Projekt in der Mitte der oberen Leiste

- **Der Projektname mit seinem Menü** (Neu, Öffnen, Speichern, Speichern unter) steht jetzt **in der Mitte der Leiste**, wie der Dokumenttitel bei vielen Programmen. Links bleiben Marke, die Bereiche Vorbereiten | Disc | Brennen und Rückgängig/Wiederholen, rechts die Aktionen. Vorher stand er direkt rechts neben den Bereichen und wurde dort leicht übersehen.
- **Gemessen statt geschätzt:** `StudioWindow._center_project` legt die Leiste erst mit kleinstem Abstand aus und verschiebt den Knopf dann um seinen Abstand zur Mitte – höchstens um den freien Platz rechts davon. Bei schmalem Fenster rückt er aus der Mitte, statt Knöpfe zu verdrängen; das Kürzen von Projektname und Marke (v1.29.0) bleibt. Der Abstand wird bei jeder Anpassung zuerst zurückgesetzt, sonst schob ein Wert aus einem breiteren Fenster nach dem Verkleinern Knöpfe aus der Leiste.
- **Test:** `tests/test_top_bar.py` (Projekt mittig auf allen drei Seiten und nach Verkleinern, keine verdeckten Knöpfe).

## [1.30.1] - 2026-11-11

### Oberfläche auf dem Mac (und überall einheitlicher)

Beim ersten Einsatz unter macOS aufgefallen. Alle Änderungen im echten Mac-Stil (Cocoa) mit Bildern vorher/nachher geprüft.

- **Schrift in den Knoten** war auf dem Mac etwa ein Viertel kleiner als unter Windows: Die Größen standen in Punkt, und macOS rechnet mit 72 statt 96 dpi. Neu `ui_font()` / `mono_font()` in `gui/theme.py`: Größen in Pixeln (Punkt × 4/3) und die Systemschrift statt fest „Segoe UI“ (gibt es auf dem Mac nicht). Unter Windows bleibt alles gleich groß. Gilt für Knoten, Hinweise im Viewer, Simulator-Szene und das Export-Protokoll.
- **Zahlenfelder** (Breite, Höhe, Deckkraft, Loop-Dauer …) haben jetzt auf allen Systemen den Stil der übrigen Eingabefelder: dunkler Hintergrund, Rahmen, Amber bei Fokus, eigene Pfeile (beim Start gezeichnet, im Cache-Ordner). Vorher zeichnete sie der native Stil – auf dem Mac mit weißen Rahmen und gequetschten Pfeilen.
- **macOS: Qt-Stil „Fusion“** mit einer Palette in den Farben des Themes statt des nativen Stils, der das dunkle Theme nur teilweise übernimmt (`apply_theme()`, auch für `tools/simulate_disc.py`). Windows und Linux behalten ihren Stil.
- **Prozent beim Export lesbar:** nicht mehr als helle Zahl im gelben Balken, sondern vorn in der Zeile darunter („◐ 92 % · Läuft seit 5:24 · 8,2 GB geschrieben“). Der Balken ist schmaler, wie im Bereich Brennen.
- **Füllstand in Vorbereiten:** „6,8 von 23,3 GB“ steht neben dem Balken statt darin (rot, wenn die Disc zu voll ist).
- **Lizenzen im Info-Fenster:** Zeilenhöhe 40 statt 32 px, die Zeilen standen zu dicht.
- **Häkchen auf Karten** (z. B. „Titel … im Player anzeigen“ beim Export) ohne dunklen Streifen dahinter: Häkchen und Optionsfelder haben keinen eigenen Hintergrund mehr.
- **Tests:** `tests/test_ui_platform.py` (Schriften in Pixeln, Zahlenfeld-Stil und Pfeile, Fusion nur auf dem Mac, Prozent in der Zeile, Zeilenhöhe), `tests/test_prepare_page.py` (Füllstand neben dem Balken).

## [1.30.0] - 2026-11-11

### Neuer Arbeitsbereich Brennen (macOS)

Eine fertige ISO lässt sich jetzt direkt in OpenBDAuth auf Blu-ray brennen, beliebig oft und ohne das Projekt neu zu packen. Plan: `docs/plaene/brennen.md`.

- **Dritter Reiter „Brennen“ / „Burn“** neben Vorbereiten und Disc (`gui/burn/page.py`). Links die ISO (wählen oder hineinziehen; Disc-Titel, Größe, 2D/3D und „passt auf BD-25/BD-50“ direkt aus den UDF-Deskriptoren, ohne Einhängen; zuletzt verwendete ISOs; „Im Simulator öffnen“), rechts der Brenner mit farbigem Punkt und einem Satz zum Zustand der Disc. Fortschritt erscheint erst beim Brennen, das Protokoll ist eingeklappt und öffnet sich bei einem Fehler.
- **1:1 gebrannt:** `hdiutil burn` mit `-forceclose -noaddpmap -nosynthesize -nooptimizeimage -noskipfinalfree`, damit die Disc abgeschlossen wird und das Dateisystem samt 3D-Interleaving aus unserer UDF-Engine unverändert bleibt. BD-RE mit Daten wird nach Rückfrage im selben Aufruf gelöscht (`-erase`).
- **Laufwerk und Disc** über `drutil … -xml`: Typ, leer/löschbar, freier Platz und die Brenngeschwindigkeiten des eingelegten Mediums (Auswahl „Geschwindigkeit“). Abfrage im Hintergrund, nicht während des Brennens.
- **Prüfung vor dem Brennen:** kein Brenner, keine Disc, keine Blu-ray, Disc schon beschrieben, ISO zu groß (Fehler); BD-RE wird gelöscht, kein BDMV in der ISO, Vorbereiten läuft (Rückfrage).
- **Optionen** in den App-Einstellungen: „Disc nach dem Brennen prüfen“ (Vorgabe aus), „Disc nach erfolgreichem Brennen auswerfen“ (Vorgabe an), bis zu 10 Kopien. Bei Fehler, Abweichung oder Abbruch wird nie ausgeworfen; zwischen mehreren Kopien immer.
- **Sicher abbrechen:** Ab dem Schreibstart heißt der Knopf „Abbrechen – Rohling wird unbrauchbar“ (bei BD-RE „… muss neu gelöscht werden“) und fragt nach; beim Prüfen ist Abbrechen harmlos. Beim Beenden während des Brennens fragt das Programm nach. Der Ruhezustand ist gesperrt, solange gebrannt wird.
- **Phasen** (Löschen, Brennen, Prüfen) aus den Meldungen von `hdiutil -puppetstrings`, die in der Sprache des Systems kommen, und zusätzlich am Verlauf der Prozente. Fortschritt auch im Reiter („Brennen 42 %“).
- **Export:** „Zum Brennen“ nach einem ISO-Export; jede exportierte ISO kommt in „Zuletzt verwendet“.
- **Simulator:** öffnet ISOs jetzt auch unter macOS (`hdiutil attach`, schreibgeschützt, ohne Finder).
- **Windows und Linux** zeigen einen Hinweis; die Backends (IMAPI2, xorriso) folgen.
- **Tests:** `tests/test_burn.py` (ISO-Angaben, Auswertung echter `drutil`-Ausgaben, Brennbefehl, Phasen, Prüfungen, Ablauf mit Fake-Backend inkl. Auswerfen und Kopien, Seite, Reiter, Einhängen unter macOS).

## [1.29.1] - 2026-10-30

### Hinweis: Ton im Video wird nicht übernommen

- **Vorbereiten nimmt aus einem Video bewusst nur das Bild.** Der Ton gehört als eigene Datei in guter Qualität dazu, damit nicht versehentlich eine stark komprimierte Spur (z. B. 128 kbps aus einer Handy-MP4) auf der Disc landet. Die frühere Notiz „Ton aus Videoquellen – Stufe 4“ ist damit kein offener Punkt mehr, sondern höchstens eine Idee für später.
- **Neuer Hinweis im Inspektor** (grau, eine Zeile am Ende des Abschnitts Video), nur wenn die Quelle eine Tonspur hat: „Der Ton im Video wird nicht übernommen – bitte als eigene Datei hinzufügen.“ Dafür merkt sich `SourceInfo` jetzt `has_audio`; gespeicherte Warteschlangen laden weiter (ohne Hinweis, bis die Datei neu hinzugefügt wird).
- **README (EN/DE):** Die Formattabelle versprach „Tonspuren aus Videodateien“. Sie nennt jetzt WAV, FLAC und weitere Tondateien, ein Absatz darunter erklärt, warum der Ton aus Videos nicht übernommen wird.
- **Test:** `tests/test_prepare_page.py` (Hinweis nur bei Video mit Ton, kein Ton-Auftrag).

## [1.29.0] - 2026-10-30

### Neue obere Leiste

Flach und nach dem Vorbild von PostFlow: Jede Art von Element hat ihren eigenen Stil, gefüllt ist nur die Hauptaktion.

- **Marke links** (`gui/studio/top_bar.py`, `BrandButton`): Logo, „OpenBDAuth“ in Amber, Version klein daneben. Ein Klick öffnet das Info-Fenster beim Reiter Neuerungen (`open_news`). Der Knopf ⓘ ist weg; F1 öffnet das Info-Fenster weiter beim Überblick.
- **Vorbereiten | Disc als Reiter:** reiner Text, der aktive Bereich in Amber mit Unterstreichung. So sind die beiden Arbeitsbereiche klar von den Aktionen getrennt.
- **Projektname statt Neu / Öffnen / Speichern:** Der Disc-Name steht in der Leiste, ein Klick öffnet das Menü mit Neu, Öffnen, Speichern und Speichern unter. Ein Punkt in Amber davor zeigt ungespeicherte Änderungen, der Tooltip die Datei oder „Noch nicht gespeichert“. Strg+N / O / S und Strg+Umschalt+S gelten weiter im ganzen Fenster.
- **Rückgängig / Wiederholen nur als Symbol** (eigene gezeichnete Pfeile, `history_icon`, ausgegraut ohne Schritt). Der Tooltip nennt den Schritt und das Tastenkürzel, z. B. „Rückgängig: Button verschieben (Strg+Z)“.
- **„Arbeitsbereich“ heißt jetzt „Ansicht“ / „View“** (Anordnung für einen oder zwei Bildschirme, Viewer und Inspektor ein- und ausblenden). Der alte Name ließ sich mit den Arbeitsbereichen Vorbereiten | Disc verwechseln.
- **Flache Knöpfe ohne Rahmen**, beim Überfahren ein dunkler Hintergrund. Gefüllt in Amber bleibt nur „Disc erstellen“ bzw. „Starten“; die Preflight-Plakette bleibt farbig, DE / EN ist grauer Text.
- **Weniger Platzbedarf:** die Disc-Seite braucht etwa 1205 statt 1274 Pixel. Wird es trotzdem eng, kürzt `_fit_toolbar` zuerst den Projektnamen und blendet dann den Schriftzug der Marke aus (Logo und Version bleiben), damit Qt keine Knöpfe hinter dem »-Pfeil der Leiste versteckt. Geprüft nach dem nächsten Layout-Durchgang mit selbst gezählten Breiten.
- **Texte:** neue Schlüssel `studio_view`, `studio_view_tip`, `studio_brand_tip`, `studio_untitled`, `studio_not_saved`, `studio_unsaved_changes`; `studio_undo` / `studio_redo` ohne Pfeilzeichen; `studio_workspace` und `studio_about_tip` entfallen.
- **Tests:** `tests/test_top_bar.py` (Projektmenü und Tastenkürzel, Punkt und Tooltips, Symbole, Ansicht und Reiter, schmales Fenster mit Breiten aus dem gemessenen Bedarf), `tests/test_about_dialog.py` (Marke öffnet Neuerungen, F1 den Überblick).

## [1.28.0] - 2026-10-30

### Neuerungen im Info-Fenster

- **Neuer Reiter „Neuerungen“ / „What's new“** im Info-Fenster (ⓘ oder F1), zwischen Überblick und Tastenkürzeln: je Version Nummer, Datum, Überschrift und wenige Stichpunkte aus Sicht der Nutzer, neueste oben, die laufende Version markiert, in der Sprache der Oberfläche. Einzelne Einträge ab 1.26.0, davor ein Sammeleintrag „0.1 – 1.25“. Das Fenster öffnet sich nach einem Update nicht von selbst.
- **Die Texte stehen in `core/release_notes.py`** (Deutsch und Englisch) und gehören ab jetzt zu jedem Release, neben diesem CHANGELOG, der die ausführliche Fassung bleibt. Als Python-Modul kommen sie ohne Extraschritt ins Paket.
- **Die Seite ist eine Textansicht** (`QTextBrowser`): Labels im Bildlaufbereich bekamen bei umbrochenen Stichpunkten zu wenig Höhe und schnitten Zeilen ab.
- **Plan für später:** `docs/plaene/kapitel-am-filmende.md`, eine zusätzliche Kapitelmarke kurz vor Filmende, damit „Nächstes Kapitel“ ans Ende springt (zurückgestellt, braucht Brenntests).
- **Tests:** `tests/test_release_notes.py` (jede Version ab 1.26.0 aus dem CHANGELOG hat Notizen mit demselben Datum, neueste oben, beide Sprachen gleich aufgebaut, Datumsformat), `tests/test_about_dialog.py` (Reiter in beiden Sprachen, Text wird maskiert).

## [1.27.4] - 2026-10-30

### Vorbereiten nimmt das mitgelieferte ffprobe

- **Fehler behoben:** Beim Hinzufügen einer Datei unter Vorbereiten benutzte OpenBDAuth nicht das mitgelieferte ffprobe aus `tools/<plattform>/`, sondern das aus dem PATH. Nur das eigentliche Umwandeln (im eigenen Prozess) und der Selbsttest stellten die Werkzeuge ein. Unter Windows fiel das nicht auf, wenn ffmpeg im PATH lag. Unter Linux Mint 22.3 (Betatest) scheiterte das System-ffprobe aus `/usr/bin`, und jede Datei hieß „weder Bild noch Ton gefunden“. Ohne ffprobe im PATH passierte beim Hinzufügen gar nichts. `tasks.create_task` stellt die Werkzeuge jetzt wie `run_task` selbst ein.

## [1.27.3] - 2026-10-30

### Verständliche Meldung, wenn ffprobe eine Datei nicht lesen kann

- **Vorbereiten zeigt ffprobes eigene Meldung:** Scheiterte ffprobe beim Hinzufügen (Datei nicht lesbar, keine Rechte, unbekanntes Format), hieß es bisher immer „weder Bild noch Ton gefunden“, weil ffprobe mit `-v quiet` lief und sein Rückgabewert nicht geprüft wurde. Jetzt erscheint zum Beispiel „Film.mkv lässt sich nicht lesen. ffprobe meldet: Permission denied“ (`jobs.ProbeError`, Unterklasse von `ValueError`). Liefert ffprobe trotz Fehler Spuren, bleibt alles wie bisher. Gefunden durch einen Betatest unter Linux.
- **Startet ffprobe gar nicht** (fehlt, nicht ausführbar, falsche Architektur), meldet Vorbereiten das mit dem Pfad des Werkzeugs. Bisher passierte beim Hinzufügen einfach nichts.
- ffprobes Ausgabe wird als UTF-8 gelesen, damit Dateinamen mit Sonderzeichen unter Windows keinen Lesefehler auslösen.

### Pakete für Windows, Linux und macOS auf GitHub

- **Neuer Workflow `.github/workflows/build-linux.yml`** („Linux-Paket“, von Hand gestartet über Actions → „Run workflow“): baut auf Ubuntu 22.04 mit denselben Versionen wie das Windows-Paket (Python 3.12.9, PySide6 6.11.2, Pillow 12.1.0, PyInstaller 6.22.0), führt den Selbsttest aus, öffnet das Fenster einmal unter Xvfb und stellt `OpenBDAuth-<Version>-linux.tar.gz` 14 Tage zum Herunterladen bereit. Danach laufen die Tests unter Linux, nur zur Information.
- **`tools/fetch_tools.py` kennt Linux:** statisches ffmpeg/ffprobe 9.0.2 von BtbN (Monatsbuild, mit x264) und tsMuxeR 2.7.0, mit Prüfsummen; liest jetzt auch `.tar.xz`.
- **`tools/build_release.py`:** Unter Linux entsteht ein `.tar.gz` (Ausführrechte bleiben erhalten), die Python-Lizenz wird auch dort gefunden.
- Läuft auf Systemen mit glibc 2.35 oder neuer (Ubuntu 22.04, Debian 12, Fedora 36, Mint 21 und neuer).
- **Linux-Paket schlanker und verträglicher:** ohne das GTK-Design-Plugin von Qt samt GTK, Pango und Cairo (OpenBDAuth hat ein eigenes Design) und ohne `libstdc++`/`libgcc_s` von Ubuntu 22.04, die auf neueren Systemen mit den Grafiktreibern kollidieren können; die bringt jedes Linux selbst mit. Die Lizenztexte der übrigen Systembibliotheken legt `build_release.py` mit Paketversionen nach `licenses/linux-system/`.
- **Windows-Paket** (`build-windows.yml`): wie bisher von Hand, jetzt auch auf GitHub, mit Selbsttest und Startversuch.
- **Windows-Installer** (`tools/OpenBDAuth.iss`, Inno Setup 6): `OpenBDAuth-Setup-<Version>.exe` neben der ZIP. Installiert ohne Admin-Rechte nach `%LOCALAPPDATA%\Programs\OpenBDAuth` (auf Wunsch für alle Benutzer nach Programme), Startmenü, Desktop-Verknüpfung auf Wunsch, Deinstallation über „Apps“, Deutsch oder Englisch nach Windows-Sprache. Ein Update ersetzt die alte Laufzeit (`_internal`) vollständig. Auf GitHub wird der Installer still ausgeführt und die installierte Version gestartet. `build_release.py` baut ihn, wenn Inno Setup da ist (`--installer`: Pflicht).
- **macOS-Paket** (`build-macos.yml`): `OpenBDAuth-<Version>-macos.dmg` mit `OpenBDAuth.app` (Start per Doppelklick) und den Lizenzen daneben. Nur Apple Silicon ab macOS 13 (tsMuxeR 2.7.0 gibt es für Mac nur als arm64, Qt 6.11 braucht macOS 13). ffmpeg 9.0.2 von Martin Riedl (mit x264). Die App ist nur ad hoc signiert, den ersten Start erlaubt der Nutzer einmal unter Systemeinstellungen → Datenschutz & Sicherheit. Im Disk-Image liegt eine Verknüpfung zu „Programme“ zum Hinüberziehen.
- **Text-Buttons mindestens 20 px hoch** (`TEXT_MIN_HEIGHT`, beim Ändern der Größe über das Feld H oder die Ziehgriffe): Flachere Text-Buttons ließen sich nicht zeichnen, Vorschau und Export brachen ab. Linien und andere Formen dürfen weiter ab 8 px. Der Wechsel Linie → Text setzte schon bisher die Standardhöhe (70 px).
- **README (EN/DE):** Download-Tabelle mit Voraussetzungen je System, Link auf die Releases-Seite, Installation und erster Start unter Windows (SmartScreen), Linux und macOS („Dennoch öffnen“, `xattr`), Badges für alle drei Plattformen.
- **Projekte von Windows unter Linux und macOS:** Gespeicherte Windows-Pfade (`C:/clips/film.264`) gelten dort jetzt als absolut und erscheinen als fehlende Dateien, die sich neu verknüpfen lassen. Bisher wurden sie an den Projektordner gehängt (`/home/…/C:/clips/film.264`). Gefunden von den Tests unter Linux.

## [1.27.2] - 2026-10-23

### Meldungen in der Sprache der Oberfläche

- **Preflight** (Prüfung vor dem Export, Plakette in der Werkzeugleiste): alle Fehler, Warnungen und Hinweise, auch die Prüfung im Export-Adapter.
- **Disc-Simulator:** Befunde, Weg dorthin, Bericht (`tools/simulate_disc.py`, Export, Fenster „Automatische Prüfung“), Meldungen des Players und der HDMV-Befehle, Lesefehler, Einhängen von ISOs.
- **Kompatibilitätshinweise zu Videos** (Auflösung, Seitenverhältnis, Bildraten, 3D-Format, 3D-Paar): Sie speichern jetzt ihre Werte mit (`params`) und erscheinen immer in der aktuellen Sprache (`ComplianceWarning.of`, `warning_text`). Hinweise aus älteren Projekten zeigen weiter den gespeicherten Text. Das Hinweisfenster ist übersetzt.
- **Vorbereiten:** Gründe, warum eine Quelle nicht angenommen wird (dieselben Texte wie in der Oberfläche), Protokoll, Schrittnamen, Fehler. Die Tonformate werden übersetzt angezeigt (z. B. „downmix to 5.1“), gespeichert bleibt der bisherige Wert, damit Warteschlangen weiter passen.
- **Hintergrundprozesse** (Encoding, Prüfung eines 3D-Paars) bekommen die Sprache der Oberfläche mit (`BackgroundTask`).
- **Außerdem:** Statusmeldungen beim Import, Fehler der Menüvorlagen, fehlende Mediendateien, Export-Protokoll, Fehler beim Laden alter Projekte, Dateifilter in Auswahlfenstern (`tr_file_filter`), Sprachliste für Spuren mit englischen Namen (aus Qt, alphabetisch).
- **Bleibt deutsch:** technische Konsolenausgaben einzelner Bausteine (UDF-Schreiber, Transport-Strom, Menügrafik) und die Befunde der MVC-Prüfung (`mvctools`), die als Einzelheiten in einem Hinweis stehen.
- **Tests:** 5 weitere in `tests/test_languages.py` (Preflight, Kompatibilitätshinweis alt und neu, Simulator-Bericht, Vorbereiten, Dateifilter und Sprachliste).

## [1.27.1] - 2026-10-23

### Fenstertitel, Screenshots in der README

- **Fenstertitel ohne „Studio“:** `OpenBDAuth v1.27.1 – <Disc-Name>`.
- **README (EN/DE) mit zwei Screenshots** (Arbeitsbereich Disc, Disc-Simulator) in `docs/screenshots/`, für das Web verkleinert. Die Originale in `design/` bleiben lokal (`.gitignore`).

## [1.27.0] - 2026-10-23

### Sprache der Oberfläche und Sprache der Disc getrennt

- **Die Oberfläche hat eine eigene Sprache**, die für das Programm gilt, nicht für ein Projekt. Beim ersten Start folgt sie Windows (Deutsch auf deutschem Windows, sonst Englisch), danach gilt die zuletzt gewählte. Umschalten: neuer Knopf **DE / EN** in der Werkzeugleiste neben ⓘ (`gui/app_language.py`). Der Wechsel ist kein Schritt im Rückgängig-Verlauf und ändert das Projekt nicht.
- **Die Sprache im Projekt heißt jetzt „Sprache der Disc“** (Inspektor des Start-Knotens). Sie bestimmt die Beschriftungen auf der Disc: automatische Buttons (KAPITEL 3 / CHAPTER 3, TON: JAPANISCH / AUDIO: JAPANESE, UNTERTITEL AUS / SUBTITLES OFF), Vorlagen (ZURÜCK, WEITER, HAUPTMENÜ, FILM STARTEN, KAPITEL, SPRACHE …) und Namen neuer Knoten. So behält eine deutsche Disc ihre Beschriftungen, auch wenn das Programm auf Englisch läuft. Englische Sprachnamen kommen aus Qt.
- **Neue Projekte** entstehen in der Sprache der Oberfläche: „Main menu → PLAY MOVIE → Main movie“ bzw. wie bisher „Hauptmenü → FILM STARTEN → Hauptfilm“. Bestehende Projekte bleiben unverändert.
- **Generator und Vorlagen erkennen Buttons in beiden Sprachen** (WEITER/NEXT, ZURÜCK/BACK, `core/disc_labels.py`), auch in gemischten Projekten.
- **Übersetzt:** Knoten-Graph (Start-, Film- und Menü-Knoten, Zeilen, Tooltips, Kontextmenüs, Eingabefenster, Hinweise beim Ziehen, Rahmenfarben), Verbindungsregeln, Texte im Rückgängig-Verlauf (zentral in `core/translations.py`, `undo_text`), „Aus“ bei Untertitel-Zielen.
- **`tr()` kennt die Sprache der Oberfläche** (`set_ui_language`, `ui_language`) und nimmt Platzhalter direkt an (`tr("graph_n_chapters", n=3)`).
- **Unverändert:** der Ausgabeordner `Disc-fertig` heißt in beiden Sprachen gleich, damit vorbereitete Dateien immer gefunden werden.
- **Noch deutsch:** Meldungen von Preflight, Disc-Simulator, Vorbereiten und Export folgen in v1.27.1.
- **Tests:** `tests/test_languages.py` (11 Tests: Programm-Sprache, Rückgängig-Texte, Startprojekt, automatische Beschriftungen, Vorlagen und Generator auf Englisch, Sprachwechsel im Fenster).

## [1.26.1] - 2026-10-23

### Designer-Edition entfernt

- **Die Designer-Edition ist weg** (`main_designer.py`, `Start_Designer.bat`, `designer.spec`, `tools/build_designer.bat`, `core/designer_mode.py`). Sie war nur für einen Oberflächen-Test gedacht; den Menü-Designer im Viewer und den Disc-Simulator hat die normale Version ohnehin.
- **Damit entfallen auch die Platzhalter-Medien:** Bilder und MP4 werden auf der Disc-Seite nicht mehr als Test-Video angenommen, die Anzeige „Test-Dummy“ in Viewer und Inspektor ist weg. Solche Dateien gehen wie bisher über Vorbereiten.
- **Vorbereiten ist immer da:** Die Abfragen, ob es die Seite gibt, sind entfallen.
- **Tests:** `tests/test_designer_mode.py` entfernt, der Dummy-Fall in `tests/test_mvc_import.py` gestrichen.

## [1.26.0] - 2026-10-23

### Neuer Name: OpenBDAuth

- **Das Programm heißt jetzt OpenBDAuth** (bis v1.25 BDauthMax): Fenstertitel, Info-Fenster, EXE (`OpenBDAuth.exe`, Paket `OpenBDAuth-<Version>-windows.zip`), Startskript `Start_OpenBDAuth.bat`, Icons, Dokumente.
- **Projekte bleiben ladbar:** Die interne Kennung in `.bdproj`-Dateien ist unverändert.
- **Einstellungen und Warteschlange** liegen jetzt unter `OpenBDAuth` (z. B. `%LOCALAPPDATA%\OpenBDAuth\prepare_queue.json`); Fensteranordnung und Vorbereiten-Einstellungen starten deshalb einmal frisch.

## [1.25.2] - 2026-10-23

### Vorbereitung der Veröffentlichung

- **`LICENSE`** (GPL-3.0) im Hauptordner, **`requirements.txt`** (PySide6, Pillow).
- **README neu:** öffentlich verständlich und auf dem Stand von v1.25 (Vorbereiten, Disc, Formate, Installation aus Paket und Quellcode, Prüfen, Tests, Rechtliches); „Entwickelt mit Unterstützung von KI.“
- **Entfernt:** der Plan für die aufgegebene BD-J-Engine, die erledigten Testchecklisten und die Werkzeuge zur Analyse fremder Discs (`tools/inspect_disc.py`, `gui_inspector.py`, `deep_analyze_menu.py`, `measure_menus.py`, `Start_Inspector.bat`). Für eigene Discs bleibt der Disc-Simulator.
- **Dokumente und Kommentare neutral formuliert:** keine persönlichen Pfade, keine Notizen zu Analysen fremder Discs mehr; die technischen Erkenntnisse bleiben.
- **Tests:** zwei Tests umbenannt (`test_matches_reference_commands`, `test_3d_profile_check`), Inhalt unverändert.

## [1.25.1] - 2026-10-23

### Selbsttest des fertigen Pakets

- **`OpenBDAuth.exe --selbsttest [Ergebnisdatei]`** prüft ohne Fenster genau den Weg, den Vorbereiten im Paket nimmt: Kindprozess aus der EXE (multiprocessing, `freeze_support`), mitgeliefertes ffmpeg mit x264, je ein kurzer 2D- und 3D-Auftrag über den normalen Ablauf (Zwischenordner, MVC-Rewriter, Paarprüfung, Verschieben). Ergebnis als JSON (`modules/prepare/selftest.py`).
- **`tools/build_release.py`** ruft ihn nach jedem Build auf; schlägt er fehl, entsteht kein ZIP. Damit ist der bisher offene Punkt geprüft: Der Encoding-Prozess startet auch aus dem fertigen Windows-Paket.
- **Test:** `tests/test_selftest.py`.

## [1.25.0] - 2026-10-23

### Vorbereiten: 30/60 fps werden immer angepasst

- **„Unverändert lassen“ entfällt.** Es erzeugte eine Datei, die nicht Blu-ray-konform ist und deren Ton am Ende um Sekunden versetzt wäre – das wählt niemand bewusst. 30 fps werden immer auf 29,97 fps angepasst, 60 fps auf 59,94 fps (geprüft nach dem Encoding wie bisher).
- **Deutlicher Hinweis aufs Ruckeln** im Inspektor, gelb: „Achtung, kann ruckeln: … dabei fällt etwa alle 33 Sekunden ein Bild weg – sichtbar als kurzes Ruckeln, vor allem bei Kameraschwenks und Bewegung. Ton und Laufzeit bleiben synchron.“ (bei 60 fps etwa alle 17 Sekunden), darunter: „Ohne Ruckeln: im Schnittprogramm direkt in 29,97 fps exportieren.“ Die Bildrate steht als „30 → 29,97 fps (wird angepasst)“.
- **Gespeicherte Warteschlangen** aus v1.24 laden weiter; Felder früherer Versionen werden übergangen.
- **Tests:** `tests/test_prepare_page.py` (Hinweis, Anpassung im Befehl), `tests/test_prepare_tasks.py` (alte Felder).

## [1.24.0] - 2026-10-23

### Vorbereiten: zwei klare Optionen für 25 und 30 fps, Film-Knoten direkt anlegen

Zwei Rückmeldungen zu v1.23.

- **25 fps: zwei Optionen statt Häkchen.** Bisher hieß „Häkchen raus“ stillschweigend echtes 1080p25. Jetzt stehen beide Möglichkeiten nebeneinander wie in BD3DEnc: **25PsF (Standard)** | **Nativ 25p**, darunter, was die gewählte bedeutet – bei Nativ 25p gelb: „Echtes 1080p25 – nicht Teil des Blu-ray-Standards. Viele moderne Player spielen es, ältere womöglich nicht.“
- **30/60 fps ebenso:** **An 29,97 anpassen** | **Unverändert lassen**; bei „unverändert“ der gelbe Hinweis, dass Bild und Ton sonst auseinanderlaufen (ca. 3,6 s pro Stunde). Bei 29,97/30 fps in 1080 zusätzlich: „Wird als 1080i59,94 (PsF) verpackt – so verlangt es die Blu-ray-Spezifikation.“ Bei mehreren markierten Aufträgen mit derselben Bildrate gelten die Optionen für alle.
- **„Für Film“ → „Neuer Film-Knoten …“:** legt sofort einen leeren Film-Knoten an (Name vorgeschlagen aus der Datei, z. B. „Trailer“) und merkt ihn dem Auftrag als Ziel vor. So lassen sich die Menüs schon verdrahten, während das Encoding läuft; nach dem Lauf ist dieser Film beim Übernehmen vorausgewählt. Ein normaler Undo-Schritt; die Datei kommt erst per „Übernehmen“ hinein. Bei mehreren markierten Videos nicht angeboten (ein Film-Knoten hat ein Video).
- **Bildraten auf Deutsch mit Komma** (29,97 / 23,976) im Inspektor von Vorbereiten.
- **Tests:** `tests/test_prepare_page.py` (25p, 30 fps, 24p ohne Optionen; neuer Film-Knoten mit Übernehmen, Undo, abgebrochener Name, nicht bei zwei Videos).

## [1.23.0] - 2026-10-23

### BD3DEnc-Einbau, Stufe 3: Warteschlange

Alles hineinziehen, je Datei festlegen, mit „Starten“ läuft alles nacheinander durch – z. B. über Nacht.

- **Warteschlange:** „Starten“ arbeitet alle wartenden Aufträge nacheinander ab, in der Reihenfolge der Liste (per Ziehen änderbar). Ein Fehler oder ein einzeln abgebrochener Auftrag (Rechtsklick „Diesen Auftrag abbrechen“) hält sie nicht an; „Abbrechen“ in der oberen Leiste bricht den laufenden Auftrag ab und hält sie an, der Rest wartet weiter. „Erneut einreihen“ für fertige, abgebrochene oder fehlgeschlagene Aufträge. Während sie läuft, lassen sich weitere Dateien hinzufügen und wartende Aufträge einstellen.
- **Was schon festgelegt ist, sieht man links in der Liste** (Wunsch): ein gelber Ring, solange die Einstellungen einer Datei noch offen sind, ein Haken, sobald sie festgelegt sind – durch jede Änderung im Inspektor oder den Knopf **„Passt so“** (übernimmt die Voreinstellungen). Oben steht „Noch festzulegen: 2 von 5“; vor dem Start fragt OpenBDAuth einmal nach, wenn noch etwas offen ist, und nennt die Dateien.
- **Mehrere Aufträge auf einmal einstellen:** Bei Mehrfachauswahl zeigt der Inspektor die gemeinsamen Einstellungen (z. B. Bitrate aller Extras, Ausgabeordner, Film-Vorschlag); unterschiedliche Werte stehen als „– unterschiedlich –“, eine Änderung gilt für alle.
- **Ausgabe:** oben „Neben der Quelle (Disc-fertig)“ oder „Ein Ordner für alle …“; die Wahl wird gemerkt und gilt für alle noch nicht gelaufenen Aufträge. Je Auftrag bleibt der Ordner im Inspektor änderbar. Würden zwei Aufträge dieselbe Datei schreiben (z. B. zwei „Trailer.mp4“ aus verschiedenen Ordnern in einem gemeinsamen Ordner), startet die Warteschlange nicht.
- **Rückfragen nur vor dem Start:** offene Einstellungen, vorhandene Dateien, zu wenig Platz (je Laufwerk: alle Ergebnisse plus der größte Zwischenbedarf) und doppelte Zieldateien werden einmal vorher geklärt. Später hinzugefügte Aufträge werden vor ihrem Start ohne Rückfrage geprüft und notfalls als Fehler markiert – über Nacht hängt nichts an einem Dialog.
- **Füllstand der Disc:** oben BD-25/BD-50 und z. B. „18,4 von 23,3 GB“ – geschätzt aus den Aufträgen (Laufzeit × Bitrate) und den Dateien des offenen Projekts (nur gelesen); gelb ab 90 %, rot darüber.
- **Restzeit** in der Statusleiste: für den laufenden Auftrag und, sobald die Geschwindigkeit bekannt ist, für die ganze Warteschlange. Am Ende eine Zusammenfassung („3 fertig, 1 mit Fehler, 0 abgebrochen“).
- **Gespeichert getrennt vom Disc-Projekt** (`%LOCALAPPDATA%/OpenBDAuth/prepare_queue.json`): Nach einem Neustart oder Absturz sind die Aufträge wieder da, unfertige auf „wartet“; ein halbfertiges Encoding wird verworfen, liegengebliebene `_unfertig`-Ordner werden entfernt.
- **Mehrere Ergebnisse übernehmen:** z. B. Hauptfilm und Tonspuren markieren und in einem Schritt in einen (neuen) Film-Knoten übernehmen; höchstens ein Video, denn ein Film-Knoten hat ein Video.
- **Brücke vom Film-Knoten:** Eine Datei, die erst vorbereitet werden muss (z. B. `.mov`, `.mkv`, `.flac`), auf einem Film-Knoten oder der freien Fläche: Rückfrage „Zu Vorbereiten wechseln?“ – dort ist der Auftrag dann angelegt, mit diesem Film als Vorschlag. Gestartet wird bewusst.
- **Tests:** `tests/test_prepare_page.py` (Markierung, Rückfrage, Mehrfachauswahl, Reihenfolge, Anhalten, Einzelabbruch, Erneut einreihen, gemeinsamer Ordner und doppelte Namen, Füllstand, Übernehmen von Video + Ton, Brücke), `tests/test_prepare_tasks.py` (Speichern und Laden, Aufräumen, Schätzungen, Platz).
- **Noch nicht:** Ton aus Videoquellen (Spuren einer MKV/MOV extrahieren oder umwandeln) und `.mlp`/`.mka` im Ton-Import des Film-Knotens – Stufe 4.

## [1.22.0] - 2026-10-23

### BD3DEnc-Einbau, Stufe 2: Arbeitsbereich Vorbereiten

Zweite von vier Stufen (Konzept, „BD3DEnc in OpenBDAuth integrieren“). Vorbereiten macht aus beliebigem Material Disc-fertige Dateien; in die Disc kommen sie nur per Klick.

- **Zwei Seiten:** Links in der oberen Leiste **Vorbereiten | Disc** (wie die Seiten in DaVinci Resolve). Auf Vorbereiten sind die Disc-Docks und die Disc-Knöpfe ausgeblendet – auch ihre Tastenkürzel, Strg+Z ändert dort also nicht unsichtbar den Graphen. Die Designer-Edition hat keine Seite Vorbereiten.
- **Aufbau wie die Disc-Seite**, neu im Studio-Design (nichts von der BD3DEnc-Oberfläche übernommen): Auftragsliste in der Mitte (Quelle, Art, Ausgabe, Status), Inspektor rechts, Protokoll unten, dieselben Dock-Fenster. Oben **Dateien hinzufügen …**, rechts **Abbrechen** und **Starten** an der Stelle von „Disc erstellen“. Dateien lassen sich in die Liste ziehen; Entf entfernt einen Auftrag.
- **Aufträge mit Vorbelegung:** 2D oder 3D aus der Auflösung (Full-TAB 1920 × 2160, Full-SBS 3840 × 1080; „Erkannt: 3D (Full-TAB) – oben = linkes Auge“), 720p/1080 aus der Bildrate, 25p als PsF, Anpassung von 30/60 fps mit Hinweis; Ton: Spur und Format. Ungeeignete Quellen (Bildrate, HDR, Interlaced, 3D-Format) werden mit Begründung abgelehnt und gar nicht erst angelegt.
- **Ein Auftrag zur Zeit, in eigenem Prozess:** ffmpeg wird zeilenweise mitgelesen – Fortschritt in Liste, Inspektor und Statusleiste beider Seiten, Protokoll unten. **Abbrechen** beendet ffmpeg sofort.
- **Keine halben Dateien:** Encodiert wird in `<Ausgabeordner>/_unfertig/<Auftrag>/`, erst nach der Prüfung (3D: Paarprüfung, sonst ffprobe) werden die Dateien in den Ausgabeordner verschoben. Bei Fehler oder Abbruch bleibt nichts liegen. Ausgabeordner: `Disc-fertig` neben der Quelle, änderbar.
- **Vor dem Start:** Dateien, die das offene Projekt benutzt, sind als Ziel gesperrt; vorhandene Dateien nur nach Rückfrage ersetzen; zu wenig Platz wird vorher gemeldet.
- **In Film-Knoten übernehmen:** Unter „Ergebnis“ wählt man einen vorhandenen Film oder „Neuer Film-Knoten“ (ein unter „Ziel“ gemerkter Film ist vorausgewählt). Übernommen wird über den bestehenden Import – mit Analyse und, bei 3D, Paarprüfung – als **ein** rückgängig machbarer Schritt. Von selbst ändert Vorbereiten nichts am Disc-Projekt.
- **Beenden während eines Auftrags:** Rückfrage, dann wird er abgebrochen und aufgeräumt.
- **Lizenzhinweise:** x264 (im mitgelieferten FFmpeg) im Info-Fenster und in `THIRD_PARTY_LICENSES.md`; der Encoder-Code aus BD3DEnc ist Teil von OpenBDAuth.
- **Bausteine:** `Section` und `fill_combo` liegen jetzt in `gui/studio/widgets.py` (beide Inspektoren nutzen sie); Symbole für 2D, 3D und Ton in `gui/icons.py`.
- **Neu im Code:** `modules/prepare/tasks.py` (Aufträge, ohne Qt), `modules/prepare/runner.py` (Ausführung im Prozess), `gui/prepare/` (Seite, Inspektor); `BackgroundTask` mit Protokoll und Abbrechen mit Aufräumfrist.
- **Tests:** `tests/test_prepare_tasks.py` (2D, 3D, Ton, Abbrechen ohne Rückstände, Ablehnung, Panorama auf 2D), `tests/test_prepare_page.py` (Seitenwechsel, Encoding und Übernehmen mit Undo, Ton in vorhandenen Film, Sperre, Rückfrage, Entfernen).
- **Noch nicht:** mehrere Aufträge nacheinander (Warteschlange), Speicherung der Aufträge, Füllstand – Stufe 3. Ton aus Videoquellen – Stufe 4.

## [1.21.0] - 2026-10-23

### BD3DEnc-Einbau, Stufe 1: Encoder-Code ohne Oberfläche, 3D-Paare beim Import prüfen

Erste von vier Stufen (Konzept, „BD3DEnc in OpenBDAuth integrieren“). Noch keine neue Seite, kein Encoding aus der Oberfläche.

- **Übernommen aus BD3DEnc v0.8.1, unverändert:** `mvctools/` (MVC-Rewriter, Prüfung, Analyse; reines Python) samt `docs/mvc/`, der Befehlsaufbau als `modules/prepare/jobs.py` (hardware-geprüfte x264-Parameter). FRIM kommt nicht mit.
- **Tests aus BD3DEnc** (71, darunter der komplette 3D-Weg mit synthetischem Full-TAB-Clip): `tests/test_mvctools.py`, `tests/test_prepare_*.py`. Sie benutzen wie das Programm das mitgelieferte ffmpeg aus `tools/<plattform>/`; die Befehlstests halten weiter die exakten ffmpeg-Aufrufe fest.
- **3D-Paar beim Import prüfen:** Bekommt ein Film Basis-Video und MVC, prüft OpenBDAuth, ob beide Bild für Bild zusammenpassen (Bildanzahl, POC, Bildtypen, IDR/Anchor, PPS-IDs). tsMuxeR würde ein nicht passendes Paar klaglos muxen; der Player zeigte dann kein sauberes 3D.
  - Läuft in einem **eigenen Prozess** mit Fortschrittsfenster und **Abbrechen**, damit die Oberfläche nicht ruckelt und ein Fehler dort das Studio nicht mitreißt (`modules/prepare/background.py`).
  - Läuft, **bevor** der Film geändert wird: Datei und Ergebnis sind ein Schritt (rückgängig machbar), nichts ändert sich nachträglich im Hintergrund.
  - **Passt das Paar nicht, ist das ein Fehler in der Prüfung vor dem Export**, der sich nicht bestätigen lässt. Abgebrochene Prüfung: bestätigbarer Hinweis „3D-Paar nicht geprüft“.
  - **3D-Format großzügig:** 1080p mit 23,976/24 fps und 720p mit 50/59,94 fps ohne Hinweis (auch wenn Vorbereiten nur 1080p erzeugt), sonst ein bestätigbarer Hinweis.
- **Nicht zusammengelegt:** Die Quellprüfung des Encoders (`jobs.source_problems`) und die Prüfung fertiger Streams (`check_compliance`) haben verschiedene Aufgaben (z. B. ist Interlaced für den Encoder ein Ablehnungsgrund, auf der Disc als 1080i richtig). Gemeinsame Grenzen nutzt der Import aus `jobs.py`.
- **`main.py`/`main_designer.py`:** `multiprocessing.freeze_support()`, damit der Prüfprozess auch im fertigen Paket startet.
- **Tests:** `tests/test_mvc_import.py` (Format, echtes Paar und Fehlpaar, eigener Prozess, Abbrechen, Importer mit Fortschrittsfenster, Preflight).

## [1.20.0] - 2026-10-23

### 3D-Filme wahlweise in 2D

Für Zuschauer mit 3D-Player und 3D-Fernseher, die den Film trotzdem in 2D sehen wollen, z. B. mit zwei Buttons „FILM 3D“ und „FILM 2D“.

- **Neu im Inspektor:** Ein Navigations-Button, der direkt einen 3D-Film startet, hat unter „Ziel“ die Auswahl **Wiedergabe: 3D / 2D** (Standard 3D). Bei 2D-Filmen erscheint sie nicht.
- **Kapitel, Film → Film und Top Menu** behalten die zuletzt gewählte Wiedergabe: Wer „FILM 2D“ gestartet hat, sieht auch Kapitel 5 in 2D, bis ein 3D-Button gedrückt wird. Nach dem Einlegen gilt 3D. Eine eigene Wahl für Kapitel-Buttons gibt es bewusst nicht.
- **Auf der Disc:** Der Button merkt die Wahl in GPR 16 (`Move GPR16 = 0/1`, dann `JumpTitle`). Das Titel-Objekt jedes 3D-Films schaltet danach mit `SetOutputMode(1)` auf 3D oder **aktiv** mit `SetOutputMode(0)` auf 2D – aktiv, weil 3D-Discs den Player schon beim Einlegen in 3D starten lassen können (`initial_output_mode_preference`). Beide Zweige mit der 3D-Profilprüfung (PSR 31) wie bisher. Gespielt wird dieselbe 3D-Playlist; der Player zeigt das linke Bild, genau wie heute an einem 2D-Fernseher.
- **Byte-gleich:** Discs ohne 2D-Button ändern sich nicht. Erst mit einem 2D-Button schreiben alle Buttons, die einen 3D-Film starten, ihre Wahl (auch die 3D-Buttons), und alle 3D-Titel werten sie aus.
- **Simulator:** Ein 3D-Film, der auf Wunsch in 2D startet, ist keine Warnung „3D-Film startet ohne SetOutputMode(3D)“ mehr, sondern ein Hinweis zum Prüfen auf dem Player.
- **Tests:** `tests/test_play_2d.py` (Befehle, Profilprüfung, Adapter, Simulations-Disc mit 2D → Kapitel → 3D, Inspektor).
- **Brenntest ausstehend** (3D-Player am 3D-Fernseher): FILM 2D → bleibt 2D; danach Top Menu → Menü in 2D; Kapitel → 2D; FILM 3D → schaltet auf 3D; danach Kapitel → 3D. Gegenprobe am 2D-Fernseher: FILM 3D und FILM 2D laufen beide in 2D.

## [1.19.3] - 2026-10-21

### Eigenes Programm-Icon

- **Icon** aus `design/OpenBDAuth Icon v1.svg` (Affinity-Projekt daneben): in der Fensterleiste, in der Taskleiste (unter Windows mit eigener App-ID, auch beim Start aus dem Quellcode), im Kopf des Info-Fensters und in der EXE (`OpenBDAuth.spec`, `designer.spec`).
- **`assets/icon/`:** PNG in 16–256 px für Qt, 1024 px als Vorlage für macOS, `openbdauth.ico` für Windows.
- **Info-Fenster, Lizenzen:** FFmpeg mit GPL-3.0 (das mitgelieferte Build); Hinweis auf `licenses/` und `THIRD_PARTY_LICENSES.md` im Programmordner.

## [1.19.2] - 2026-10-21

### Fertiges Windows-Paket: entpacken, starten, alles dabei

Entscheidung: Alle Werkzeuge werden mitgeliefert, kein Nachladen per Dialog – eine geprüfte ffmpeg-Version, offline lauffähig, kein fremder Server.

- **`python tools/build_release.py`** baut `dist/OpenBDAuth-<Version>-windows.zip` (115 MB, entpackt 386 MB): `OpenBDAuth.exe`, darunter Python und Qt (`_internal`), die Werkzeuge in `tools/windows/` und alle Lizenztexte.
- **Werkzeuge in festen Versionen** (`tools/fetch_tools.py`, jede Datei mit SHA-256-Prüfsumme): ffmpeg und ffprobe 9.0.2 („essentials“ von gyan.dev, GPL v3, mit x264), tsMuxeR 2.7.0 (Apache-2.0). Dasselbe Skript legt sie beim Entwickeln nach `tools/windows/` – damit benutzt auch der Start aus dem Quellcode genau die ausgelieferte ffmpeg-Version statt der im PATH.
- **`OpenBDAuth.spec`:** Ordner-Paket statt Ein-Datei-EXE (Qt-Bibliotheken bleiben austauschbar, wie die LGPL es verlangt; schnellerer Start). Nur QtCore, QtGui und QtWidgets; Qt-Übersetzungen, Quick/QML/PDF, Software-OpenGL, numpy und yaml bleiben draußen (zuerst 603 MB, jetzt 386 MB).
- **Kein aufblitzendes Konsolenfenster** bei ffmpeg- und tsMuxeR-Aufrufen (14 Stellen, `NO_CONSOLE` in `modules/external_tools.py`), keine Tastatur-Eingabe an die Werkzeuge.
- **Startfehler** erscheinen im Paket als Meldungsfenster statt „Enter drücken“ in einer Konsole, die es dort nicht gibt.
- **Lizenzen:** `THIRD_PARTY_LICENSES.md` (Komponenten, Versionen, Quellen) und `licenses/` mit LGPL-3.0 und GPL-3.0; das Paket bekommt zusätzlich die Lizenztexte von ffmpeg, tsMuxeR, Pillow, Python und den Schriften.

## [1.19.1] - 2026-10-21

### Werkzeuge ohne Installation und ohne PATH finden

Ziel: herunterladen, entpacken, starten – ohne ffmpeg oder tsMuxeR selbst zu installieren oder in den PATH einzutragen (gemeinsamer Plan mit BD3DEnc).

- **Neue Suche `modules/external_tools.py`** für ffmpeg, ffprobe und tsMuxeR: zuerst `tools/windows/` (bzw. `tools/macos/`, `tools/linux/`) neben dem Programm, dann `tools/` (bisheriger Platz von tsMuxeR), zuletzt der PATH. Im fertigen Paket wird neben der EXE und im Paket-Ordner gesucht. Unter macOS und Linux ohne `.exe`.
- **Alle Aufrufe** laufen über den gefundenen Pfad – bisher stand an zehn Stellen nur `"ffmpeg"`/`"ffprobe"`, was nur mit PATH-Eintrag funktionierte.
- **Fehlt ein Werkzeug,** meldet „Disc erstellen“ das als Fehler, bevor der Export startet: „ffmpeg fehlt – in den Ordner tools/windows neben OpenBDAuth legen.“ (Nicht in der Projekt-Prüfung, weil es am Rechner liegt, nicht am Projekt.)
- **Bestehende Installationen laufen weiter:** tsMuxeR in `tools/`, ffmpeg im PATH.
- `.gitignore`: die Werkzeug-Ordner je Plattform werden nicht eingecheckt.
- **Tests:** `tests/test_external_tools.py` (Reihenfolge, PATH, Fehler, Ordner und Dateinamen für Windows, macOS, Linux, Paket-Ordner).

## [1.19.0] - 2026-10-21

### Neues Farbschema, Info-Fenster mit Lizenzen

Wunsch: ein ruhigeres Farbschema und eine Seite mit den Lizenzen der verwendeten Komponenten.

- **Farbschema:** Graphit-Grau statt Nachtblau, **Amber** statt Blau als Akzent – Hauptknopf „Disc erstellen“, Auswahl, Fokus, Häkchen, Fortschrittsbalken, aktive Umschalter. Auf Amber steht dunkle Schrift. Die Auswahl im Node-Editor und im Viewer war schon gelb und ist jetzt dasselbe Amber.
- **Warnungen** sind heller gelb (`#FDE047`), damit sie sich vom Akzent unterscheiden. Grün und Rot, die Filmfarben, die Kennfarben (Menü-Knoten, Hilfslinien, Abstands-Hilfe) und alle Farben, die auf die Disc kommen, bleiben.
- **Farbtabelle** im Kopf von `gui/theme.py`: Alle Oberflächen benutzen nur diese Werte.
- **Info-Fenster** („ⓘ“ rechts in der oberen Leiste oder **F1**) mit drei Reitern:
  - *Überblick:* was OpenBDAuth macht, die fünf Bereiche in je einem Satz.
  - *Tastenkürzel:* erstmals gesammelt – Projekt, Node-Ansicht, Viewer (Gestalten und Fernbedienung), Disc simulieren; gegen den Code geprüft.
  - *Lizenzen:* Qt/PySide6 (LGPL-3.0), Pillow (MIT-CMU), tsMuxeR (Apache-2.0), FFmpeg (LGPL-2.1+ bzw. GPL je nach Build), Liberation Sans und Noto Sans (OFL-1.1), Python (PSF-2.0) mit Verwendung und Rechteinhaber.
- **Eigene, einfarbige Symbole statt Emoji** (`gui/icons.py`): Format-Knöpfe in „Disc erstellen“ (Ordner, Scheibe – in der Farbe der Schrift, auf Amber dunkel), „Export starten“ (Dreieck), die Prüfliste (Fehler, Warnung, Hinweis) und die Plakette oben in der Leiste (Fehler und Warnungen mit Anzahl, sonst Haken und „Bereit“). „Alles bereit“ in der Prüfung ist grün statt mit Emoji.
- **Tests:** `tests/test_about_dialog.py`.

## [1.18.3] - 2026-10-21

### Statuszeile beim Export: Ergebnis statt Summe

Rückmeldung: Nach dem Export stand „17 GB geschrieben“, die ISO war aber nur gut 8 GB groß. Gezählt wurde alles, was unterwegs entstand – erst der BDMV-Ordner, dann die ISO daraus (und Zwischendateien der Extra-Titel).

- **Am Ende steht die Größe des Ergebnisses:** „✅ Fertig nach 12:34 · ISO 8,2 GB“ bzw. „· BDMV-Ordner 8,2 GB“ beim Export als Ordner.
- **Während des Exports** zählt „geschrieben“ weiter alles (es ist das Lebenszeichen und soll wachsen, solange etwas passiert).
- **„letzte Meldung vor …“ entfällt** aus der Statuszeile. Die Warnung, wenn 10 Minuten weder Daten noch Meldungen kommen, bleibt.

## [1.18.2] - 2026-10-21

### ISO: klarer Abbruch statt Ausweg über Windows (Konzept 11.2.6)

Die eigene ISO-Erstellung fasst höchstens 38 Clips pro Ordner (z. B. 3 Filme und 17 Menüs mit eigenem Hintergrund). Darüber brach sie ab, und die ISO entstand still über Windows (IMAPI2FS) – ein Weg, der nie auf einem Player geprüft wurde. Danach wurde der BDMV-Ordner gelöscht. Derselbe Ausweg griff bei jedem anderen Fehler der ISO-Erstellung, auch bei der Prüfung aus v1.17.7, und hatte schon in v1.8.2 einen Fehler verdeckt.

- **Kein Ausweg mehr über Windows:** Scheitert die ISO, bricht der Export mit der Ursache ab. Der BDMV-Ordner bleibt im Zielordner erhalten, eine halbfertige ISO wird gelöscht. Die ISO-Erstellung ist damit auf allen Systemen gleich.
- **Zu viele Clips** werden geprüft, bevor das erste Byte geschrieben wird: „Ordner BDMV/STREAM hat 39 Einträge – die ISO fasst höchstens 38 Clips pro Ordner.“
- **Prüfung vor dem Export** (nur bei ISO): „Die ISO fasst höchstens 38 Clips, diese Disc braucht 39 …“ – je Film einer (3D zwei), je Menü-Hintergrund zwei; Menüs „wie Hauptmenü“ teilen sich ihre Clips. Als Ordner exportiert gibt es die Grenze nicht.
- **Byte-gleich:** Discs bis 38 Clips pro Ordner werden genau wie bisher geschrieben.
- **Tests:** `tests/test_iso_tools.py` (Grenze aus dem Ordner-Aufbau, 38 passen, 39 brechen ab ohne halbfertige ISO, Prüfung vor dem Export).

## [1.18.1] - 2026-10-21

### Film nach Film, Trailer vor dem Menü (Stufe 2.1, Teil 2)

- **Film → Film:** Den Ausgang „Ende“ eines Films mit einem anderen Film verbinden, z. B. Hauptfilm → Making-of oder Folge 1 → Folge 2 („Alle Folgen“). Auf der Disc `JumpTitle(n)` am Filmende. Eine im Film gewählte Ton- oder Untertitelspur wird vorher gesichert und gilt im nächsten Film weiter, wenn er ein Sprachmenü hat.
- **Zwischen zwei 3D-Filmen** schaltet die Disc nicht mehr kurz auf 2D zurück (sonst synchronisiert sich der Fernseher zweimal neu).
- **Start → Film:** Der Start-Knoten kann auf einen beliebigen Film zeigen, z. B. einen Trailer. Das Menü am Ende der Kette (Start → Trailer → Menü) ist das Hauptmenü. Auf der Disc startet First Play den Titel per `JumpTitle`; Top Menu überspringt den Trailer.
- **Prüfung:** Führt die Kette nach dem Start in kein Menü, ist das ein Fehler – außer beim bisherigen Fall „Disc ohne Menü“ (Start → erster Film). Filme, die im Kreis aufeinander zeigen (A → B → A, auch A → A), sind eine Warnung: nur Top Menu führt heraus.
- **Gesperrte Verbindungen gibt es damit keine mehr.** Der Film-Inspektor zeigt „▶ Danach: Making-of“.
- **Byte-gleich:** Discs ohne Film → Film und ohne Start → Film ändern sich nicht.
- **Tests:** `tests/test_film_ends.py` (Befehle, 3D, Start-Kette, Kreise, Simulations-Disc), Ende-zu-Ende mit tsMuxeR `test_trailer_and_film_after_film` (Simulation = Export).
- **Brenntest:** Sony BDP-S4200 mit „D4A“ – Trailer beim Einlegen, danach Hauptmenü; Top Menu überspringt den Trailer. Film → Film noch nicht auf Hardware geprüft.

## [1.18.0] - 2026-10-21

### Filmende in einem beliebigen Menü (Stufe 2.1, Teil 1)

Rückmeldung aus dem großen Test: Nach dem Making-of ging es zurück ins Hauptmenü statt ins Extras-Menü.

- **Neu:** Den Ausgang „Ende“ eines Film-Knotens mit einem beliebigen Menü verbinden – per Ziehen auf das Menü oder ins Leere („Neues Menü“). Unverbunden geht es weiter ins Hauptmenü. Film → Film (z. B. „Alle Folgen“) und Start → Trailer bleiben gesperrt und kommen mit v1.18.1.
- **Ausgewählt ist danach der Button, der den Film gestartet hat** (z. B. „MAKING-OF“), wenn genau ein Navigations-Button im Zielmenü den Film startet; sonst der Standard-Button des Menüs.
- **Auf der Disc:** Der Titel endet mit denselben Befehlen wie ein Button in ein anderes Menü (v1.13): `Move GPR7 = Seite`, `Move GPR8 = Button`, `JumpObject(Menü-Objekt der Gruppe)`; die Startseite der Gruppe zeigt Seite und Button. Eine Gruppe, in der ein Film endet, bekommt deshalb die Startseite auch bei nur einem Menü.
- **Tonspur bleibt erhalten:** Hat der Film ein Sprachmenü, sichert der Titel vor dem Sprung die aktuelle Ton- und Untertitelspur (wie sonst das TopMenu-Objekt beim Menüeintritt). Sonst würde die Spur des Menü-Clips übernommen, wenn man danach erst ins Hauptmenü geht.
- **Menüs, in die nur ein Filmende führt,** landen auf der Disc und gelten in der Prüfung als erreichbar. Ihre Seiten kommen nach allen anderen; bestehende Seiten behalten ihre Nummern.
- **Film-Inspektor:** „Nach dem Film“ zeigt das verbundene Menü („↩ Ins Menü „Extras““).
- **Byte-gleich:** Filme, deren Ende unverbunden ist oder ins Hauptmenü führt, behalten ihre Befehle; eine Disc ohne freie Film-Enden ändert sich nicht.
- **Tests:** `tests/test_film_ends.py` (Befehle, Adapter, Simulations-Disc mit eigenem und gemeinsamem Hintergrund, Tonspur), Ende-zu-Ende mit tsMuxeR `test_film_end_in_extras` (Simulation = Export).
- **Brenntest:** Sony BDP-S4200 mit „D4A“ – nach dem Trailer erscheint das Extras-Menü.

## [1.17.7] - 2026-10-20

### Große Projekte: Menü-Clips fehlten in der ISO

Rückmeldung: Beim ersten großen Projekt (7 Menüs) wechselten in VLC die Menüs nicht, der Sony BDP-S4200 hing beim Einlegen.

- **Behoben:** Der Bereich der ISO, in dem steht, welche Datei wo liegt, war fest 96 Sektoren groß (ein Sektor pro Datei, zwei pro Ordner). Die Disc brauchte 109. Alles dahinter war für Player unsichtbar: 13 Clips – alle Untermenü-Hintergründe und alle Menü-Buttons – erschienen mit 0 Byte, und die UDF-Unique-ID-Tabelle wurde überschrieben.
- **Der Bereich wächst jetzt mit** (in Schritten von 64 KB). Discs, die mit 96 Sektoren auskommen, werden genau so gebaut wie bisher. Passen die Einträge trotzdem nicht, bricht der ISO-Bau ab, statt eine kaputte ISO zu schreiben.
- **Brenntest:** Sony BDP-S4200 – Film, Menüwechsel, Ton- und Untertitelwahl und Kapitel funktionieren.
- **Noch offen (Konzept 11.2.6):** Höchstens 38 Dateien pro Ordner, also z. B. 17 Menüs bei 3 Filmen.

## [1.17.6] - 2026-10-20

### Lebenszeichen beim Export

Rückmeldung: Beim ISO-Export standen 2–3 Minuten nur „0 %“ und „--- Export gestartet ---“ da, auch später hing die Prozentanzeige zeitweise – man fragt sich, ob noch etwas läuft.

- **Neue Statuszeile unter dem Fortschrittsbalken**, jede Sekunde aktualisiert: „◐ Läuft seit 2:14 · 3,4 GB geschrieben · letzte Meldung vor 4 s“.
- **„geschrieben“** misst die Dateigrößen im Zielordner (BDMV, CERTIFICATE, ISO) und in den temporären Ordnern, in denen Extra-Titel gemuxt werden – dort stand der Balken bisher still. Die Export-Pipeline bleibt unverändert.
- **Rot bei Abbruch** („Abgebrochen nach …“, Balken rot), **gelb**, wenn 10 Minuten weder Daten noch Meldungen kommen (nichts wird abgebrochen), **grün** mit Dauer und Datenmenge, wenn fertig.

## [1.17.5] - 2026-10-20

### Video-Import repariert, Hinweis auf exakt 30 fps

Rückmeldung: Im Extras-Menü ließen sich Making Of und Trailer weder per Ziehen noch über die Knöpfe mit Video füllen; zusammen hineingezogener Ton kam auch nicht an.

- **Behoben:** Seit v1.17.1 brach jeder Video-Import ab. Beim Entfernen einer unbenutzten Funktion war deren `@classmethod` stehen geblieben und hing an der Videoanalyse. Damit fiel auch der Ton weg, wenn er zusammen mit dem Video hineingezogen wurde. Ein neuer Test ruft die Videoanalyse jetzt wirklich auf.
- **Neuer Kompatibilitätshinweis „Exakt 30 fps statt 29.97 fps“** (ebenso 60 statt 59.94): Die Blu-ray kennt nur die NTSC-Raten, das Bild läuft auf der Disc 0,1 % langsamer, der Ton nicht – etwa 60 ms Versatz pro Minute. Empfehlung: Timeline mit 30000/1001 und Bild und Ton daraus neu exportieren.

## [1.17.4] - 2026-10-20

### Weniger Erklärtexte

Rückmeldung: Viele dauerhaft sichtbare Erklärtexte liest niemand – der unter dem Viewer war lang und teils veraltet (Kreuzungen-Heften gibt es nicht mehr).

- **Entfallen:** die Bedienungsanleitung unter dem Viewer, der Hinweis unten links in der Node-Ansicht und im Inspektor die Hinweise zu Ziehen auf den Film, „Stufe 2“ nach dem Film, Button anklicken, Button-Größe, Fernbedienung, Raster, Rahmen und zum Hintergrund „wie Hauptmenü“ bzw. eigenem Hintergrund (das ⏸ an der Verbindung zeigt die Ladepause).
- **Gekürzt:** Modus Fernbedienung – „Pfeiltasten und Enter wie auf der Fernbedienung · rot umrandet: nicht erreichbar“; Hintergrund des Hauptmenüs – „Gilt auch für alle Menüs ‚wie Hauptmenü‘“.
- **Verschoben in Tooltips:** die Tastenkürzel des Viewers (Pfeiltasten 1/10 px, Entf, mehrere auswählen, Alt frei) an den Modus-Knopf „Gestalten“; der Hardware-Tipp zu Schleifen ≥ 30 s an das Feld „Loop-Dauer“.
- **Leiste „Form-Buttons ohne Hintergrundbild … Text-Buttons verwenden“** über dem Viewer entfällt (fiel besonders beim ersten Start auf). Den Hinweis gibt es weiter in der Prüfung; umschalten geht im Inspektor.
- **Bleiben:** Hinweise, die nur in ihrer Situation erscheinen (z. B. nach Strg+D, Pipette, Generator-Bereich), „Noch keine Spuren“, der Hinweis, wo das Ziel eines Navigations-Buttons verbunden wird, und die Hinweise im Dialog „Disc erstellen“. Unter dem Viewer steht nur noch etwas, wenn es etwas zu sagen gibt.

## [1.17.3] - 2026-10-20

### Häkchen „Einrasten“

Rückmeldung: Mit ausgeblendeten Hilfslinien rasteten Buttons weiter an den unsichtbaren Linien ein – manchmal gewollt, manchmal nicht. Sichtbarkeit und Einrasten sind jetzt getrennt.

- Neben „Hilfslinien“ im Viewer: **Einrasten**, bei jedem Start gesetzt. Entfernt man das Häkchen, rastet nichts mehr ein – weder an Linien noch an gleichen Abständen, bündigen Kanten, der Bildmitte oder beim Setzen neuer Linien im Lineal. Das entspricht dem Ziehen mit gedrückter **Alt**-Taste, die weiterhin für einzelne Züge gilt.
- Mit ausgeblendeten Linien und gesetztem Häkchen rasten Buttons weiter an den Linien ein.

## [1.17.2] - 2026-10-20

### Dateinamen der Spuren lesbar, abgekoppelte Fenster wie gewohnt

Rückmeldung aus dem großen Test: Die Sprachauswahl der Ton- und Untertitelspuren nahm viel leeren Platz ein, der Dateiname (mit wichtigen Infos wie dem Format) war abgeschnitten. Und ein abgekoppelter Viewer ließ sich nur per Doppelklick auf den Rand wieder andocken – Doppelklick heißt anderswo „Bildschirm füllen“.

- **Spuren:** Die Sprachauswahl ist schmal und fest (150 px); der Dateiname bekommt den Rest der Zeile und wächst mit dem Fenster. Reicht der Platz nicht, wird er in der Mitte gekürzt – Anfang und Endung bleiben sichtbar (`Audio Mas…1 DTS.dts`). Die aufgeklappte Liste zeigt die Sprachen weiter in voller Länge.
- **Eigene Titelleiste für Viewer und Inspektor:** Abgekoppelt sitzt oben rechts **Andocken**; ein **Doppelklick** auf die Titelleiste füllt den Bildschirm (ohne Taskleiste), ein zweiter stellt die vorherige Größe wieder her. Angedockt gibt es **Abkoppeln**; Doppelklick koppelt wie bisher ab. Ziehen an der Leiste verschiebt wie gewohnt.

## [1.17.1] - 2026-10-20

### Aufgeräumt: Code und Tests, die nichts mehr tun

Durchsicht aller Tests: Was nur noch Code prüfte, den das Programm nicht mehr aufruft, ist zusammen mit diesem Code entfernt. Die eingefrorene HDMV-Pipeline (Menü, Disc, ISO) und `core/project_state.py` bleiben unangetastet. Am Verhalten des Studios und an der erzeugten Disc ändert sich nichts.

- **Heften an Hilfslinien** (seit v1.16.4 abgeschafft): Heftungen im Datenmodell (`GuideBinding`, `view.guide_bindings`), Heften, Lösen, Verteilen und Mittig anordnen an einer Linie, Kreuzungen, Mitwandern beim Ändern einer Linie sowie das Umhängen der Enden alter Ankerpunkt-Linien. Ältere Projektdateien mit Heftungen laden weiter (der Eintrag wird ignoriert). Alte Linien an Ankerpunkten werden weiter angezeigt und lassen sich löschen.
- **Button-Reihenfolge verschieben** (`move_button`, seit den freien Buttons in v1.12 ohne Aufruf).
- Einzelne ungenutzte Hilfsfunktionen: `modules/subtitle_ops.py`, `get_framerate`, `number_ranges`, `is_start`, `_items_center`, `has_custom_sizes`, zwei Methoden der Sprachauswahl.
- **Tests:** 9 entfallen (608 statt 617), betroffene Tests auf das heutige Verhalten gekürzt.

## [1.17.0] - 2026-10-20

### Projekte finden ihre Dateien auch auf einem anderen Rechner

Rückmeldung aus dem großen Test: auf Rechner A angefangen, auf Rechner B weitergemacht – alles auf derselben externen SSD, aber die Menü-Hintergründe fehlten. Die SSD hatte auf Rechner A den Buchstaben G:, auf Rechner B F:, und das Projekt speicherte jeden Pfad absolut mit Laufwerksbuchstaben.

- **Relative Pfade:** Video, Ton, Untertitel, Menü-Hintergründe und der Zielordner werden relativ zur `.bdproj` gespeichert, wenn sie auf demselben Laufwerk liegen (z. B. `../../D4A Cover/Bluray Menü V1.jpg`). Projekt und Medien lassen sich so gemeinsam verschieben oder an einem anderen Rechner öffnen. Auf einem anderen Laufwerk bleibt der Pfad absolut.
- **Anderer Laufwerksbuchstabe:** Einen absoluten Pfad, den es nicht gibt, sucht das Studio beim Laden auf dem Laufwerk der Projektdatei. Ältere Projekte (wie das mit `G:`) finden ihre Dateien damit sofort wieder; beim nächsten Speichern werden die Pfade relativ.
- **Medien neu verknüpfen:** Fehlen nach dem Öffnen Dateien, erscheint eine Liste (Datei, wofür sie gebraucht wird, Status). **Ordner durchsuchen …** sucht alle im gewählten Ordner samt Unterordnern nach Namen; bei mehreren Treffern gewinnt der mit der passenden Ordnerstruktur bzw. der, der zur Verschiebung der übrigen Dateien passt – sonst „mehrdeutig“. **Datei wählen …** (oder Doppelklick) setzt eine einzelne von Hand. **Übernehmen** trägt alles als einen Rückgängig-Schritt ein.
- **Fehlende Dateien sichtbar:** Die Prüfung meldet jede fehlende Datei als Fehler (Klick öffnet „Medien neu verknüpfen“), statt dass der Export mittendrin scheitert. Im Inspektor steht der Name rot mit „– fehlt“.
- Im Programm bleiben alle Pfade absolut; nur die Projektdatei rechnet um (`core/media_paths.py`). Der Export ist unverändert. **Tests:** `tests/test_media_paths.py`.

## [1.16.4] - 2026-10-19

### Linien sind reine Einrast-Hilfen

Rückmeldung zu v1.16.3: Buttons blieben an Linien hängen, bis man sie mit X löste – das braucht es nicht mehr. Und wer einen Button greifen wollte, erwischte oft die Linie und verschob sie.

- **Kein Heften mehr:** Beim Ziehen rastet die Mitte eines Buttons (bzw. der Auswahl) an der nächsten waagerechten und der nächsten senkrechten Linie ein, an einer Kreuzung an beiden – danach ist er wieder frei. In der jeweils anderen Richtung wirkt die Abstands-Hilfe wie gewohnt; **Alt** zieht ganz frei. X zum Lösen entfällt.
- **Linien ändern bewegt keine Buttons mehr.** Gespeicherte Heftungen älterer Projekte werden beim Laden verworfen (die Buttons bleiben, wo sie sind).
- **Gesetzte Linien lassen sich nicht mehr ziehen:** Ihre Lage ändert man über die Zahl am Schild, ✕ löscht. Klicks gehen durch eine Linie hindurch auf den Button bzw. die Fläche darunter. Ziehen gibt es nur noch beim Anlegen aus dem Lineal, bevor man loslässt.
- Rechtsklick auf eine Linie bietet nur noch „löschen“ (Verteilen und Mittig anordnen gibt es bei mehreren ausgewählten Buttons).

## [1.16.3] - 2026-10-19

### An zwei Linien zugleich einrasten

Rückmeldung zu v1.16.2: Mit einer waagerechten und einer senkrechten Linie rastete ein Button immer nur an einer ein.

- **Kreuzung:** Kommt ein Button beim Ziehen in die Nähe des Punkts, an dem sich zwei Linien kreuzen, sitzt seine Mitte genau auf der Kreuzung; beide Linien leuchten auf.
- **Folgt beiden:** Er bleibt an beiden Linien geheftet – verschiebt man die waagerechte oder die senkrechte Linie (ziehen oder Zahl am Schild), wandert er mit, in allen Menüs.
- Wird eine der beiden Linien gelöscht, bleibt er an der anderen an derselben Stelle. Ziehen entlang einer Linie weg von der Kreuzung, Pfeiltasten, „Gleichmäßig verteilen“ und „Mittig anordnen“ lösen nur die zweite Linie; **X** löst beide.
- Gespeichert als zweite Linie der Heftung (`guide_bindings[…].cross`). **Tests:** `tests/test_fixed_guides.py`.

## [1.16.2] - 2026-10-19

### Lineal: Klick setzt die Linie genau dort

Rückmeldung zu v1.16.1: Das ＋ im Lineal versprach „hier klicken“, ein Klick tat aber nichts; erst Herausziehen legte eine Linie an – und zwar quer zur erwarteten Richtung. Zum linken Lineal am Fensterrand war der Weg weit.

- **Klick ins Lineal setzt die Linie genau an dieser Stelle:** oberes Lineal (x-Skala) → senkrechte Linie bei diesem x, linkes Lineal (y-Skala) → waagerechte Linie bei diesem y.
- **Vorschau:** Beim Überfahren des Lineals zeigt eine blasse Linie mit Schild („409 px von rechts“), wo sie entsteht – inklusive Einrasten an Mitte, Title Safe, Vierteln, Goldenem Schnitt und Button-Mitten (Alt: frei).
- **Gedrückt halten und ziehen** verschiebt die neue Linie vor dem Loslassen; über das Bild hinaus gezogen entsteht keine.
- **Lineale direkt am Bild** statt am Fensterrand, genau so lang wie das Bild – kurze Wege.
- Das Schild einer senkrechten Linie steht unter dem oberen Bildrand (nicht mehr unter dem Lineal).

## [1.16.1] - 2026-10-19

### Lineale statt Punkte

Rückmeldung zu v1.16.0: Platzieren und Löschen fühlten sich nicht intuitiv an – niemand ahnt einen Rechtsklick mit Menü, die vielen Punkte am Rand sagten nicht, was sie tun, und Linien ließen sich nicht verschieben.

- **Lineale oben und links** am Rand des Viewers (Skala in Bildpunkten, unabhängig vom Platz um das Bild). Beim Überfahren erscheint ein **＋**.
- **Neue Linie:** aus dem oberen Lineal ins Bild ziehen = waagerechte Linie, aus dem linken = senkrechte. Gemessen wird von der näheren Kante; das Schild zeigt den Abstand schon beim Ziehen.
- **Verschieben:** Linie greifen und ziehen. Sie rastet an Bildmitte, Title Safe, Vierteln, Goldenem Schnitt und an den Mitten der Buttons ein; **Alt** = frei. Geheftete Buttons wandern in allen Menüs mit.
- **Genaue Zahl:** Klick auf das Schild („70 px von unten“) – dort die Zahl eintippen, Enter übernimmt, Esc bricht ab.
- **Löschen:** ✕ am Schild, die Linie zurück ins Lineal ziehen, oder anklicken + Entf.
- **Entfallen:** die blauen und gelben Ankerpunkte, schräge Linien, „Linie hier“ im Rechtsklick und die Karte „Eigene Linien“ im Inspektor. Ältere Linien an Ankerpunkten werden weiter angezeigt und lassen sich löschen. Die Lineale zeigt das Häkchen „Hilfslinien“ mit an bzw. aus; im Modus Fernbedienung gibt es keine.

## [1.16.0] - 2026-10-19

### Eigene Linien in allen Menüs

Rückmeldung aus dem großen Test: ZURÜCK steht im Hintergrund jeder Seite an derselben Stelle, die Linien-Buttons ließen sich aber nicht auf genau dieselbe Höhe bringen. Die Hilfslinien an festen Punkten bleiben; dazu kommen eigene Linien mit Abstand in Pixeln.

- **Eigene Linie:** waagerecht oder senkrecht, mit Abstand von einer gewählten Kante – z. B. „70 px von unten“. Sie gilt in **jedem Menü** (violett gestrichelt, mit Beschriftung und Punkten an beiden Rändern).
- **Heften wie gewohnt:** Ein Button rastet beim Ziehen mit seiner Mitte an der Linie ein. Ändert sich der Abstand, wandern alle gehefteten Buttons in allen Menüs mit. „Gleichmäßig verteilen“ und „Mittig anordnen“ gehen auch hier (pro Menü).
- **Anlegen:** Rechtsklick auf freie Fläche im Viewer → „Waagerechte/Senkrechte Linie hier“ (Abstand von der nächsten Kante), oder im Inspektor beim Menü (Karte „Eigene Linien (alle Menüs)“: ＋ Waagerecht / ＋ Senkrecht).
- **Ändern:** im Inspektor Kante („von unten“ / „von oben“ bzw. links/rechts) und Abstand (Zahl, Pfeile oder ziehen). Die Kante zu wechseln lässt die Linie liegen und rechnet den Abstand um. Im Viewer per Rechtsklick auf die Linie: „Abstand ändern …“.
- **Löschen:** ✕ im Inspektor, Rechtsklick → „Eigene Linie löschen (alle Menüs)“ oder Linie anklicken + Entf. Geheftete Buttons bleiben, wo sie sind.
- Gespeichert als `view.fixed_guides`; beim Übernehmen eines Menü-Layouts („wie bei …“) bleiben Heftungen an eigenen Linien erhalten. **Tests:** `tests/test_fixed_guides.py`.

## [1.15.3] - 2026-10-19

### Genauer ausrichten: ruhigeres Einrasten, Zahlen für mehrere Buttons

Rückmeldung aus dem großen Test: Linien-Buttons (8 px) sprangen beim Ziehen zwischen Ober-, Mittel- und Unterkante der Nachbarn hin und her; gleiche Breiten und Höhen waren mühsam (ZURÜCK lag in sechs Menüs bei x 472–487, Kapitel-Linien 527–534 breit).

- **Einrasten nur noch Gleiches an Gleichem:** Oberkante an Oberkante, Mitte an Mitte, Unterkante an Unterkante (waagerecht links, Mitte, rechts). Flache Formen (unter 24 px, also Linien) rasten in dieser Richtung nur mit der Mitte ein – ein Ziel pro Nachbar statt neun.
- **Alt gedrückt halten = frei ziehen**, ganz ohne Einrasten (ein an einer Hilfslinie gehefteter Button löst sich dabei).
- **X / Y / B / H bei Mehrfachauswahl:** Ist ein Wert bei allen gleich, steht er da, sonst bleibt das Feld leer. Eintippen setzt ihn für alle (X/Y: linke bzw. obere Kante; Breite/Höhe: jeder behält seine Mitte), je ein Rückgängig-Schritt.

## [1.15.2] - 2026-10-19

### Ziel-Plaketten verdecken die Buttons nicht mehr

Rückmeldung: Die Plaketten (K1, „→ Hauptfilm“ …) saßen auf der oberen linken Ecke und verdeckten, wie weit ein Button links geht.

- **Unter dem Button, bündig mit seiner linken Kante** (3 Pixel Abstand): Die Form bleibt ganz sichtbar, und die Plakette zeigt zugleich, wo der Button links beginnt.
- **Beim Ziehen und Vergrößern** sind die Plaketten der bewegten Buttons ausgeblendet; die übrigen bleiben als Orientierung.
- **Klicks gehen durch die Plaketten hindurch** auf den Button oder Vorschlag darunter (bisher fing eine Plakette den Klick ab).
- Ganz aus wie bisher mit dem Häkchen **„Ziele“** über dem Viewer (z. B. bei eng gestapelten Beschriftungen in kleiner Ansicht).

## [1.15.1] - 2026-10-19

### Rahmen im Inspektor

Rückmeldung zu v1.15.0: Mit einem ausgewählten Rahmen blieb der Inspektor leer.

- **Ein ausgewählter Rahmen** (Titel anklicken) zeigt im Inspektor seinen **Namen** zum Ändern und das **Farbfeld** wie beim Film (8 Rahmenfarben oder „Eigene Farbe …“), dazu einen kurzen Hinweis zur Bedienung und „Rahmen löschen (Knoten bleiben)“. Der Viewer zeigt weiter, was er vorher gezeigt hat.

## [1.15.0] - 2026-10-19

### Rahmen im Node-Editor (Konzept 3.5, wie Underlays in Fusion)

Rückmeldung aus dem großen Test: Drei Kapitelmenüs gehören zusammen, die Extras sollen in eine Ecke – das soll man auch sehen.

- **Anlegen:** Knoten auswählen und **Strg+G** – der Rahmen legt sich mit etwas Rand um die Auswahl. Oder Rechtsklick auf freie Fläche → „Rahmen hier …“ (bzw. „Rahmen um Auswahl“). Beim Anlegen fragt das Programm nach dem Namen.
- **Aussehen:** halbtransparente farbige Fläche hinter Knoten und Verbindungen, mit Titelleiste. Doppelklick auf den Titel benennt um; Rechtsklick auf den Titel: umbenennen, Farbe (8 Farben), Rahmen löschen.
- **Was drinliegt, gehört dazu:** Knoten mit ihrer Mitte im Rahmen, andere Rahmen, die ganz darin liegen. Knoten zieht man einfach hinein oder heraus.
- **Am Titel ziehen** verschiebt den Rahmen samt Inhalt – ein Rückgängig-Schritt. **Kanten links, rechts, unten** (und die Ecken unten) ändern die Größe. In die Fläche geklickt wirkt wie auf freier Fläche (Auswahlrahmen).
- **Löschen:** Titel anklicken, Entf – nur der Rahmen verschwindet, die Knoten bleiben.
- Reine Ansicht, gespeichert im Projekt (`view.groups`, neues Feld `rect`), kein Einfluss auf die Disc. „Alles anzeigen“ (F) berücksichtigt Rahmen. Zurückgestellt: Zuklappen, automatisches Einrahmen.
- **Neu:** `core/node_frames.py`, `FrameItem` in `gui/node_editor/scene.py`. **Tests:** `tests/test_node_frames.py`.

## [1.14.9] - 2026-10-19

### Deckkraft: Pfeile in 5er-Schritten

Rückmeldung zu v1.14.8: Pfeile mit 1 % pro Klick sind nahezu nutzlos.

- **Pfeile, Mausrad und Pfeiltasten** ändern die Deckkraft in 5er-Schritten und rasten auf glatte Werte ein (37 → ↑ 40, ↓ 35).
- **Jeder Pfeilklick wird sofort übernommen** (Viewer zeigt es gleich, je Klick ein Rückgängig-Schritt). Ziehen bleibt fein (1 % pro 2 Pixel), Eintippen wie bisher.

## [1.14.8] - 2026-10-19

### Deckkraft: nur die Zahl

Rückmeldung zu v1.14.7: Beim Markieren zum Eintippen erwischte man meist nur das %-Zeichen.

- **Kein %-Zeichen mehr im Feld**, nur die Zahl 0–100 (der Tooltip nennt die Einheit).
- **Ein Klick markiert die ganze Zahl** – einfach lostippen ersetzt sie. Ziehen verstellt wie bisher.

## [1.14.7] - 2026-10-19

### Deckkraft: schlichte Zahl, zum Ziehen, Standard 100 %

Rückmeldung zu v1.14.6: „unsichtbar“ statt einer Zahl war unverständlich und auf großen Windows-Schriften abgeschnitten („chtbar“).

- **Nur die Zahl 0–100 %**, kein Text mehr. Das Feld ist so breit wie „100 %“ in der eingestellten Schrift (keine feste Breite mehr).
- **Ziehen zum Verstellen:** in das Feld klicken und mit gedrückter Maustaste nach rechts/oben (mehr) oder links/unten (weniger) ziehen, 1 % pro 2 Pixel; beim Loslassen übernommen, ein Rückgängig-Schritt. Eintippen geht wie bisher.
- **Standard 100 % für alle Zustände:** neue Menüs zeigen die Form auch im Ruhezustand. Bestehende Menüs behalten ihre gespeicherten Werte (wer dort 0 % hat, sieht „Normal“ weiterhin nicht).
- **Neu:** `DragSpinBox` in `gui/studio/widgets.py`. **Tests:** `tests/test_drag_spin.py`.

## [1.14.6] - 2026-10-19

### Start-Button und unsichtbare Farben

Rückmeldung aus dem großen Test (Kapitelmenü mit 6 Kapiteln): Beim Öffnen war ZURÜCK ausgewählt, und die eingestellte Farbe für „Normal“ war nicht zu sehen.

- **Start-Button automatisch:** Ohne festgelegten Standard-Button ist beim Öffnen eines Menüs jetzt der erste Inhalts-Button in Lesereihenfolge ausgewählt (oben links, z. B. Kapitel 1), ohne Inhalts-Buttons der erste Button oben links. Bisher war es der erste Button der Liste – im Kapitelmenü das zuerst angelegte ZURÜCK. Gilt im Viewer („Wie auf dem Player“), im Projektcheck (Pfeiltasten-Erreichbarkeit) und auf der Disc. Der Inspektor zeigt „Automatisch (KAPITEL 1 …)“.
- **Farbe wählen macht sichtbar:** Wer für einen Zustand mit 0 % Deckkraft eine Farbe wählt (Farbfeld, Hex-Code, Pipette), bekommt 100 % dazu – auch bei derselben Farbe noch einmal. Ein Rückgängig-Schritt. 0 % steht im Inspektor jetzt als „unsichtbar“ da.
- **Tests:** `tests/test_start_button.py` (auch auf der Simulations-Disc).

## [1.14.5] - 2026-10-19

### Button-Stil leichter finden: Umschalter Text | Form

Rückmeldung aus dem großen Test (D4A): Im Hauptmenü ließ sich „Form“ nicht finden. Der Stil gilt fürs ganze Menü und stand nur in der Menü-Karte, die ausgeblendet ist, solange ein Button ausgewählt ist – gesucht hat man ihn aber beim Button. Außerdem behielt die Startvorlage „Text“.

- **Aussehen beim Button:** Mit einem oder mehreren ausgewählten Buttons zeigt der Inspektor oben „Aussehen [ Text | Form ]“ mit dem Hinweis „Gilt für alle Buttons in „…““. „Form & Farben …“ hebt die Auswahl auf und springt zur Karte „Button-Stil“ des Menüs.
- **Umschalter statt Auswahlliste:** Auch in der Karte „Button-Stil“ stehen beide Möglichkeiten nebeneinander, darunter ein Satz, was der gewählte Stil bedeutet.
- **Form ist überall Standard,** auch im Hauptmenü der Startvorlage. Solange ein Menü mit Form-Buttons kein Hintergrundbild hat, zeigt der Viewer einen Hinweis: Bild hierher ziehen – oder **„Text-Buttons verwenden“** (ein Klick, rückgängig machbar). Der Projektcheck meldet dasselbe jetzt auch fürs Hauptmenü.
- **Text ↔ Linie behält die Lage:** Die Linie liegt wie eine Unterstreichung an der Unterkante des bisherigen Text-Buttons (waagrecht mittig); eigene Breiten bleiben, nur die Höhe kommt aus dem Stil. Hin und zurück ergibt wieder die alte Lage. Bei Kreis und Dreieck bleibt es wie bisher (mittig, Standardgröße).
- **Tests:** `tests/project_factory.text_starter()` (Startvorlage mit Text wie bis v1.14.4), neue Tests in `tests/test_button_shapes.py`.

## [1.14.4] - 2026-10-15

### Eigene Farben für Form-Buttons

Rückmeldung: Farben aus dem eigenen Hintergrundbild übernehmen bzw. eine Liste mit Hex-Codes eintippen. Die Farben gelten weiter pro Menü für alle Buttons (gut für die Palette des Menüstroms mit 254 Farben).

- **Hex-Feld** neben jedem Farbfeld (normal, ausgewählt, aktiviert): Code eintippen (`#C8A060`, `c8a060` oder kurz `#ca6`), Enter übernimmt. Ungültige Eingaben werden zurückgesetzt, mit Hinweis in der Statuszeile.
- **Pipette ⌖:** danach ins Bild im Viewer klicken – die Farbe kommt aus dem Hintergrundbild in voller Auflösung (bei Menü-Video aus dessen erstem Bild), nicht vom Bildschirm. Esc bricht ab.
- **Farbmenü:** oben „Im Projekt benutzt“ (eigene Farben vor den Voreinstellungen) und „Aus dem Hintergrund“ (die 8 Hauptfarben des Hintergrundbilds, jeweils als echte Pixelfarbe, kein Mittelwert), darunter die bisherigen Vorgaben und „Weitere Farben …“ (Farbdialog).
- **Neu:** `core/color_tools.py`. **Tests:** `tests/test_button_colors.py`.

## [1.14.3] - 2026-10-15

### Höchstens 50 Buttons pro Menüseite

Rückmeldung zu v1.14.2: Das Format erlaubt 255 Buttons pro Seite, sinnvoll bedienbar sind aber viel weniger (übliche Kapitelmenüs zeigen 4–12 Buttons, Serien selten über 20–30).

- **Grenze 50 pro Seite** (Preflight-Fehler darüber, mit Verweis auf den Generator). **Ab 40** ein Hinweis: „mit der Fernbedienung mühsam – lieber auf mehrere Seiten verteilen“.
- **Generator:** höchstens 47 Plätze im Raster (plus ZURÜCK, HAUPTMENÜ, WEITER). Die Ausgangsseite füllt er nur bis zur Grenze – samt WEITER, wenn es weitergeht – der Rest kommt auf Folgeseiten. Der Vorschlag für Spalten und Zeilen bleibt darunter.

## [1.14.2] - 2026-10-15

### Werkzeuge: Generator

Die Disc-Ausgabe ändert sich nicht (es entstehen ganz normale Buttons und Menüs); kein eigener Brenntest.

- **Generator:** Knopf „▦ Generator“ in der Viewer-Leiste, dann den Bereich aufziehen (Esc bricht ab). Im Fenster Typ (Kapitel, Ton, Untertitel), Film, von–bis und Spalten/Zeilen pro Seite wählen; darunter steht in Klartext, was entsteht („30 Buttons: 12 auf dieser Seite, 18 auf 2 neuen Seiten …“). Die Buttons entstehen im Button-Stil des Menüs gleichmäßig im Bereich, mit Ziel-Markern, und sind danach ausgewählt. Ein Rückgängig-Schritt für alles.
- **Ergänzt nur:** Vorhandene Buttons bleiben; Rasterplätze, an denen schon einer liegt, bleiben frei. „Nur Ziele, die noch keinen Button haben“ (Standard) verhindert doppelte Kapitel.
- **Folgeseiten:** Passen nicht alle auf die Seite, entstehen Seiten wie bei der Kapitel-Vorlage („Kapitel 2/3“ …) mit gleichem Stil, gleichem Bereich und zunächst demselben Hintergrund; ZURÜCK, HAUPTMENÜ und WEITER sitzen wie auf der Ausgangsseite (sonst unter dem Bereich). Die Ausgangsseite bekommt WEITER; führte sie schon zu einer anderen Seite, hängen die neuen dazwischen.
- **Aus dem Preflight:** „Kapitel … sind in keinem Menü. Klick: Ergänzen …“ öffnet den Generator auf der letzten Kapitelseite mit genau diesen Kapiteln und dem dort gemerkten Bereich.
- **Grenzen des Menüstroms (Preflight):** mehr als 255 Buttons auf einer Seite ist ein Fehler (Format). Mehr als ca. 16 MB Button-Grafik in einem Menüstrom ist eine Warnung – der Wert ist eine Annahme, nicht gegen die Spezifikation geprüft. Der Generator zeigt beides vorab.
- **Neu:** `core/menu_generator.py`, `gui/studio/generator_dialog.py`. **Tests:** `tests/test_menu_generator.py` (auch Bereich aufziehen mit echten Maus-Ereignissen und das echte Fenster).

## [1.14.1] - 2026-10-15

### Werkzeuge: Als Raster anordnen und verteilen

Die Disc-Ausgabe ändert sich nicht; kein eigener Brenntest. Freies Platzieren und das Einrasten im gleichen Abstand beim Ziehen bleiben unverändert.

- **Verteilen (Inspektor, ab drei Buttons):** waagerecht bzw. senkrecht – der erste und der letzte Button bleiben stehen, dazwischen gleiche Abstände; die andere Richtung bleibt, wie sie ist.
- **Als Raster anordnen (Inspektor, mehrere Buttons):** Spalten und Abstände wählen, „Anordnen“. Die Buttons kommen Zeile für Zeile ins Raster, die obere linke Ecke der Auswahl bleibt; jede Zelle ist so groß wie der größte Button, kleinere sitzen mittig. Vorschlag: Spalten wie die oberste Zeile, Abstände wie die kleinsten vorhandenen (sonst 40/25 wie die Vorlagen). Ragt das Raster aus dem Bild, rückt es hinein. Solange die Maus über dem Bereich ist, zeigt der Viewer die Reihenfolge als Nummern.
- **Tests:** in `tests/test_menu_tools.py`.

## [1.14.0] - 2026-10-15

### Werkzeuge: Strg+D und „Ziele der Reihe nach“

Die Disc-Ausgabe ändert sich nicht; kein eigener Brenntest.

- **Strg+D (Viewer, Modus Gestalten):** kopiert die Auswahl und zählt die Ziele weiter – aus K4 wird K5, aus einer Reihe K1–K4 wird K5–K8, Untertitel zählen bis „Aus“. Die erste Kopie liegt direkt neben der Auswahl (rechts, sonst darunter). Jedes weitere Strg+D wiederholt den Abstand, den man der letzten Kopie gegeben hat. Gibt es kein nächstes Ziel, bleibt die Kopie ohne Ziel (roter Rand). Navigations-Buttons kommen mit ihrer Beschriftung, aber unverbunden. Größe wird mitkopiert, festgelegte Pfeiltasten und Hilfslinien-Heftungen nicht. Ein Rückgängig-Schritt pro Strg+D.
- **Verständlich ohne Vorwissen:** Unter dem Viewer steht nach jedem Strg+D, was als Nächstes kommt („… nächste im gleichen Abstand (K6)“). Strg+C/Strg+V zeigen „Kopieren: Strg+D (zählt Kapitel weiter)“. „Duplizieren (Strg+D)“ gibt es auch als Knopf im Inspektor und im Rechtsklick-Menü.
- **Ziele der Reihe nach (Inspektor, mehrere Buttons):** Typ, Film und „ab“ wählen, dann „Zuweisen“. Die Kapitel-, Ton- und Untertitel-Buttons der Auswahl werden Zeile für Zeile belegt; leicht schiefe Reihen zählen als eine Zeile. Navigations-Buttons bleiben unberührt. Vorher steht in Klartext, wie es ausgeht („8 Buttons → K5–K12 · 2 ohne Ziel“), und solange die Maus über der Zeile ist, zeigt der Viewer die Reihenfolge als Nummern.
- **Neu:** `core/menu_tools.py` (Qt-frei). **Tests:** `tests/test_menu_tools.py`.

## [1.13.2] - 2026-10-15

### Eigene Hintergründe pro Menü: Studio

Die Disc-Ausgabe ändert sich nicht (Pipeline aus v1.13.0/1.13.1, auf dem Sony UBP-X700 bestätigt); kein eigener Brenntest.

- **Hintergrund in jedem Menü (Inspektor):** Unter „Hintergrund“ steht „Wie Hauptmenü“ oder „Eigener Hintergrund“. Wählen geht jetzt in jedem Menü: Ein Menü „wie Hauptmenü“ bekommt dabei einen eigenen Hintergrund, ausgehend von dem des Hauptmenüs (Musik und Loop-Dauer bleiben; ein Bild ersetzt dessen Video, ein Video dessen Bild). „↺ Wie Hauptmenü“ verwirft den eigenen wieder. Die Hinweise aus Stufe 1 („eigene Hintergründe folgen in Stufe 2“) entfallen.
- **Drag & Drop:** Bild, Video oder Musik auf den Viewer oder auf einen Menü-Knoten im Graph ziehen setzt den Hintergrund dieses Menüs – auch wenn gerade ein Button ausgewählt ist. Mehrere Dateien auf einmal sind ein Rückgängig-Schritt.
- **Viewer und Simulator** zeigen den Hintergrund des jeweiligen Menüs, bei einem Menü-Video dessen erstes Bild (mit ffmpeg). Die Simulations-Disc liefert dafür ein Bild je Menü-Playlist (`SimulationDisc.menu_backgrounds`).
- **Graph:** Verbindungen zwischen Menüs mit verschiedenem Hintergrund tragen ein Pausen-Symbol mit Tooltip „Wechsel mit kurzer Ladepause (anderer Hintergrund)“; bei Rücksprung-Marken steht es im Tooltip.
- **Inspektor bei ausgewähltem Button:** Der Rückweg heißt jetzt „← Menü (Hintergrund, Stil …)“; der Viewer-Hilfetext nennt „Klick auf freie Fläche: Auswahl aufheben“.
- **„Form“ ist der Stil neuer Menüs** (Vorschlag C): neue Menüs, Kapitel-, Sprach- und Filmauswahl-Menüs aus den Vorlagen. Die Startvorlage (Hauptmenü mit „FILM STARTEN“) bleibt bei Text, damit eine schnelle Disc ohne eigenes Bild weiter beschriftet ist. Der Preflight-Hinweis zu Form-Buttons gilt nur für Menüs ohne eigenen Hintergrund.
- **Tests:** `tests/test_menu_backgrounds.py` (Modell, ein Rückgängig-Schritt, Drop auf Viewer und Knoten, Inspektor, Pausen-Symbol, Simulator je Gruppe). Die Test-Fabrik und die Designer-Tests behalten für Vorlagen-Menüs den Text-Stil (Lage und Größe in den Tests).

## [1.13.1] - 2026-10-14

### Menü-Schleife behält auch den ausgewählten Button

Hardware-Test v1.13.0 (Sony UBP-X700): Die Seite blieb nach Ablauf der Menü-Schleife stehen, die Auswahl sprang aber alle 20–30 s auf den Standard-Button zurück.

- **Menü-Objekt (`menu_loop_commands`):** merkt sich nach Ablauf Seite *und* Button (`Move GPR7 = PSR11`, `Move GPR8 = PSR10`; ohne ausgewählten Button 0 = Standard-Button).
- **Startseite (`start_page_commands`):** kopiert beide Wünsche nach GPR 9/10, setzt GPR 7/8 zurück und schaltet dann mit `SetButtonPage(Seite = GPR9)` bzw. `SetButtonPage(Button = GPR10, Seite = GPR9)` um.
- **Simulator (`modules/bdsim/hdmv.py`, `scratch_registers`):** Register, die in jeder Befehlsfolge vor dem Lesen ohne Bedingung beschrieben werden (wie GPR 9/10), unterscheiden beim automatischen Durchlauf keine Zustände mehr. Disc A braucht damit 1,9 s statt 10 s, die ganze Testsuite 68 s statt 101 s.
- **Test-Disc** `1_13_1_TEST_A.iso` (wie 1_13_0 A). Simulator: 0 Fehler, 0 Warnungen.
- **Tests:** `tests/test_bdsim_scratch.py`; in `tests/test_menu_groups.py` bleibt ein anderer ausgewählter Button nach der Schleife erhalten.

## [1.13.0] - 2026-10-14

### Eigene Hintergründe pro Menü: Pipeline

Noch ohne Oberfläche zum Einstellen (kommt in v1.13.1); der Export setzt eigene Hintergründe aus dem Projekt aber schon um, und der Viewer zeigt sie.

- **Menügruppen (`core/disc_adapter.py`):** Menüs mit gleichem *wirksamem* Hintergrund (Bild, Video, Musik, Dauer; ohne eigenen = wie Hauptmenü) bilden eine Gruppe mit eigener Menü-Playlist, eigenem Hintergrund-Clip und IG-Strom. Gruppe 0 (mit dem Hauptmenü) bleibt `00000.mpls`; weitere Gruppen bekommen die Playlists hinter den Titeln, freie Clip-Nummern (aus STREAM, CLIPINF und allen Playlist-Verweisen, damit Simulation und Export gleich nummerieren) und ein eigenes Menü-Objekt hinter den Titel-Objekten. Bestehende Projekte bleiben eine Gruppe.
- **Unsichtbare Startseite:** Gruppen mit mehreren Seiten bekommen eine Seite 0 mit einem Button ohne Grafik (`auto_action`, Standard-Button). Er zeigt die in GPR 7 gewünschte Seite, sonst die erste. `SetButtonPage` beendet ein Button-Programm sofort (libbluray „terminate“) – der Wunsch wird deshalb vorher nach GPR 9 kopiert und zurückgesetzt. `SetButtonPage` mit Register-Operanden: Flags im Befehl, Nummer im Register (wie libbluray `_fetch_operand`).
- **Sprung in eine andere Gruppe:** `Move GPR7 = Seite`, `JumpObject(Menü-Objekt der Gruppe)` (Buttons dürfen keine Playlist starten). Innerhalb einer Gruppe weiter `SetButtonPage` ohne Pause.
- **Menü-Schleife ohne Rücksprung (behebt 11.2.4):** Gruppen mit Startseite merken sich nach Ablauf die Seite (`Move GPR7 = PSR11`) und starten per `Goto` neu; First Play springt dann direkt ins TopMenu. Ausgewählt ist danach der Standard-Button der Seite.
- **Standard-Button auf der Disc (Korrektur zu v1.12.1):** Der im Inspektor gewählte Standard-Button kam bisher nicht auf die Disc (nur Seite 0 kannte einen, und auch der war immer Button 1). Jetzt pro Seite (`MenuButtonSpec.is_default`).
- **Test zu 11.2.5:** `DiscSettings.menu_resume` (nur Diagnose, ohne Oberfläche): `False` schreibt die Menü-Objekte ohne `resume_intention`, mit `menu_call_mask` und `title_search_mask`.
- **Byte-gleich:** Disc mit einem einseitigen Menü (z. B. Test-Disc C) ändert sich nicht. Menüs mit mehreren Seiten bekommen die Startseite (gewollt, wegen 11.2.4).
- **Simulator:** `auto_action` beim Anzeigen einer Seite; die Startseite gilt nicht als unerreichbare Seite; der Hinweis zur Menü-Schleife erscheint nur, wenn danach wirklich eine andere Seite zu sehen ist. Durch das Hilfsregister prüft der Durchlauf mehr Zustände (Disc A: etwa dreimal so viele).
- **Viewer:** zeigt den Hintergrund des jeweiligen Menüs (eigener oder wie Hauptmenü). **Preflight:** der Stufe-1-Hinweis „eigener Hintergrund wird ignoriert“ entfällt; der Hinweis zu Form-Buttons gilt nur noch für Menüs ohne eigenen Hintergrund.
- **Test-Discs** `1_13_0_TEST_A.iso` / `_B.iso` (Medien von Disc A, Formen Dreieck und Kreis, zwei Hintergründe, Kapitelmenü mit zwei Seiten) und `TESTCHECKLISTE_1_13_0.md` (5 Punkte). Simulator: 0 Fehler, 0 Warnungen.
- **Tests:** `tests/test_menu_groups.py` (Gruppen, Befehle, MovieObjects, Simulations-Disc mit zwei Hintergründen, Schleife), Ende-zu-Ende mit tsMuxeR `test_two_backgrounds` (Simulation = Export byte-gleich, auch die zweite Menü-Playlist).

## [1.12.2] - 2026-10-14

### Freie Buttons, Teil 3: Palette, Ziel-Plaketten, Preflight

- **Palette in der Viewer-Leiste** (Modus *Gestalten*): `＋ Navigation`, `＋ Kapitel`, `＋ Ton`, `＋ Untertitel`. In den Viewer ziehen legt den Button mit seiner Mitte an der Stelle an, ein Klick am nächsten freien Platz; ein Rückgängig-Schritt, der Button ist danach ausgewählt. Inhalts-Buttons bekommen den Standard-Film und das erste Kapitel bzw. die erste Spur, die im Menü noch fehlt (bei Untertiteln danach „Aus“), sonst kein Ziel; Navigation kommt unverbunden (`disc_edit.add_button_of_kind`).
- **Ziel-Plaketten** (K12, A2, U1, U–, „→ Name“) als Schildchen auf der oberen linken Ecke jedes Buttons, feste Größe bei jedem Zoom, nur im Viewer; Häkchen „Ziele“ blendet sie aus. Buttons ohne Ziel (Inhalt ohne Kapitel/Spur, Navigation unverbunden) haben einen roten Rand und eine rote Plakette.
- **Preflight:** Meldungen nennen den betroffenen Button (`Issue.button_id`); ein Klick in „Disc erstellen“ zeigt das Menü und wählt den Button aus. Neuer Hinweis: Untermenü mit Form-Buttons teilt bis v1.13 das Hintergrundbild des Hauptmenüs.
- **Pfeiltasten im Viewer-Text:** Entf entfernt die Auswahl, Rechtsklick setzt die eigene Größe zurück (statt „auf Vorlage zurücksetzen“).
- **Testcheckliste:** `TESTCHECKLISTE_1_12_2.md` (10 Punkte, nur Studio).
- **Tests:** `tests/test_palette_markers.py`.

## [1.12.1] - 2026-10-14

### Freie Buttons, Teil 2: Inspektor nach Auswahl

- **Gemeinsame Mehrfachauswahl:** Der Controller hält Menü + ausgewählte Buttons (`select_buttons`, Signal `selection_changed`); Viewer, Menü-Knoten und Inspektor zeigen dieselbe Auswahl. Klick auf eine zusammengefasste Inhaltszeile im Knoten wählt alle ihre Buttons; Entf im Viewer entfernt die Auswahl.
- **Inspektor (Menü-Seite):** nichts ausgewählt → Menü (Name, Standard-Film, Standard-Button, Hintergrund, Button-Stil); ein Button → Typ und Name (↺ aus dem Ziel), Ziel (Navigation: Anzeige, verbinden im Graph; Inhalt: Film und Kapitel/Spur/„Aus“, rot ohne Ziel), Form & Position, Fernbedienung (eingeklappt); mehrere Buttons → Film der Inhalts-Buttons, gleiche Breite/Höhe, ausrichten, entfernen. Die Button-Liste im Inspektor entfällt.
- **Qt-frei:** `disc_edit.set_button_kind` (Typwechsel verwirft das Ziel, ein Schritt), `set_button_content`, `set_buttons_film` (Ziel wandert mit seiner Nummer), `menu_design.align_items`, `match_size`, `disc_rules.target_options`, `target_marker`.
- **Tests:** `tests/test_button_edit.py`, `tests/test_inspector_selection.py`.

## [1.12.0] - 2026-10-14

### Freie Buttons, Teil 1: Datenmodell und Speicherformat (Konzept Kap. 10, Plan v1.12)

Jeder Button hat jetzt eine feste Position, eine Art und ein Ziel. Layout-Regeln und die Bindung an Vorlagen entfallen. An der Disc-Kodierung ändert sich nichts (HDMV-Befehle, Menüstrom); geändert hat sich, woher Lage, Größe und Pfeiltasten kommen.

- **Neues Speicherformat (Schema 2, `core/disc_model.py`):** Projekte aus v1.11 und älter sowie aus der früheren Oberfläche öffnen sich nicht mehr; eine Meldung nennt die Version (`ProjectFormatError`). `core/disc_migration.py` entfällt.
- **Button:** `film_id` am Button (bisher `source_film_id` am Menü); `position` setzt jede Anlege-Funktion; `size` leer = Größe aus dem Button-Stil (Text 380 × 70, Form Breite × Höhe des Stils). „Untertitel aus“ ist ein Untertitel-Button mit dem Ziel `off` (Art `subtitle_off` entfällt).
- **Menü:** `default_film_id` (Standard-Film) statt `source_film_id`; `template` und `layout` (Layout-Art, Raster, gemeinsamer Versatz, Pfeiltasten-Modus) entfallen. Ob ein Film ein Kapitel- oder Sprachmenü hat und welches Menü die Filmauswahl ist, ergibt sich aus den Buttons.
- **Lage (`core/menu_layout.py`, neu):** Vorlagen ordnen ihre Buttons einmalig an (Spalte, Raster, zwei Spalten, mit der bisherigen Layout-Engine); danach sind es freie Buttons. Ein neuer einzelner Button (z. B. „＋ Button“, Link zu einem neuen Menü) kommt unter den untersten Button des Menüs, passt er dort nicht mehr hin, rechts daneben.
- **Pfeiltasten:** immer nach der Lage der Buttons, plus Festlegungen pro Button. Liegt in Pfeilrichtung nichts im 45°-Kegel, geht es jetzt erst schräg weiter und erst dann zur gegenüberliegenden Seite (`MenuLayoutEngine.link_spatial`): aus der unteren Reihe eines breiten Kapitelrasters führt „runter“ in die Navigationszeile, wie bisher mit der Raster-Regel.
- **Button-Stil:** Ein Wechsel (Text ↔ Form, Form-Größe) hält die Mitte jedes Buttons (`menu_design.set_style`).
- **Entfallen (Vorschlag B):** Vorschläge „Fehlendes ergänzen“ (`＋ KAPITEL 9–12`, `＋ TON`, `＋ UNTERTITEL`) samt Fenster „Auf dieser Seite / Auf einer neuen Seite“; der Preflight meldet fehlende Kapitel weiter. Außerdem: Kapitelbereich pro Menü, Karte „Anordnung“ mit Layout-Art und Raster, „Auf Vorlage zurücksetzen“ (der Rechtsklick auf Buttons verwirft jetzt die eigene Größe), Heftung des Rasters als Ganzes an Hilfslinien.
- **Preflight:** Inhalts-Button ohne Film oder ohne Ziel ist ein Fehler; die Warnung „mehr Inhalts-Buttons als Plätze im Raster“ entfällt; der Hinweis „kein Weg zum Film“ gilt pro Film der Spur-Buttons.
- **Node-Ansicht:** Inhalts-Buttons werden je Art und Film zu Zeilen zusammengefasst; die Kopfzeile nennt den Film (bei mehreren ihre Anzahl).
- **Tests:** Testprojekte entstehen direkt im Modell (`tests/project_factory.py`) statt über die frühere Oberfläche. Der Byte-Vergleich mit dem Weg der früheren Oberfläche entfällt; der Ende-zu-Ende-Test mit tsMuxeR (Simulator ohne Fehler und Warnungen, Kapitel an ihrer Marke, Spurwahl, Simulation = Export) bleibt. Neu: Speicherformat, Ablehnen älterer Projekte, feste IDs (ein eingefügtes Kapitel verschiebt kein Ziel), Lage und Größe vom Button, Pfeiltasten nach Lage, freier Platz für Link-Buttons.

## [1.11.3] - 2026-10-14

### Alte Oberfläche entfernt

Das Studio ist jetzt die einzige Oberfläche. Keine Paritäts-Checkliste (Entscheidung 2026-10-14): Ihr einziges fehlendes Gegenstück im Studio war der Diagnose-Schalter „Menü ohne Buttons“; das Öffnen alter Projekte entfällt ohnehin mit dem neuen Speicherformat in v1.12. An der Disc ändert sich nichts.

- **Entfernt:** `gui/app.py` und `gui/tabs/` (Reiter Titel, Video, Untertitel, Kapitel, Menü, Export; rund 2.700 Zeilen), `Start_Studio.bat`, die Übergabe „Projekt aus der bisherigen Oberfläche übernehmen“ im Studio (`adopt_legacy_project`) und 45 nur dort benutzte Übersetzungen (je Deutsch und Englisch).
- **Start:** `python main.py` bzw. `Start_OpenBDAuth.bat` öffnet das Studio. `--studio` ist nicht mehr nötig.
- **Bleibt:** `core/project_state.py` als Übergabe an die Export-Pipeline (`modules/disc_export.py`, `modules/menu_author.py`), die Umwandlung alter `.bdproj` beim Öffnen (bis v1.12), Sprachauswahl und Kompatibilitätshinweis (`gui/widgets/`, vom Studio benutzt), Disc-Inspektor.
- **Tests:** `tests/test_gui_qt.py` und die Tests der alten Oberfläche in `test_studio.py` und `test_multititle_export.py` entfernt (11 Tests); der Byte-Vergleich des Exports aus `ProjectState` und aus dem Studio bleibt bis v1.12.

## [1.11.2] - 2026-10-14

### Disc-Titel im Player standardmäßig an

- **Standard „an“ (`DiscSettings.disc_title_meta`):** Brenntest bestanden (Sony BDP-S4200, `HARDWARE_TESTS.md`). Neue Projekte und Projekte ohne gespeicherte Einstellung schreiben den Titel nach `BDMV/META/DL`; das Häkchen in „Disc erstellen“ schaltet ihn weiterhin aus. Projekte, die mit ausgeschaltetem Häkchen gespeichert wurden, bleiben aus. Hinweis „Brenntest ausstehend“ im Häkchen entfällt.
- **Byte-Vergleich alter Weg ↔ Studio (`tests/test_e2e_export.py`):** schaltet den Titel für den Vergleich aus, weil die alte Oberfläche keinen schreibt.
- **Testchecklisten v1.10.1 und v1.11.1** als ausgesetzt markiert; neuer offener Punkt 11.2.5 (Top Menu im Menü setzt den Film fort).

### Behoben

- **Untertitel bei 24,000 fps (`modules/subtitles/srt_to_sup.py`):** `fps_to_pgs_rate_byte` nahm den ersten Eintrag innerhalb von 0,1 fps, sodass 24,000 als 23,976 eingeordnet wurde (PCS-`frame_rate` 0x10 statt 0x20; tsMuxeR meldete die PGS-Spur mit 23,976). Jetzt wird die nächstliegende Bildrate gewählt. Test in `tests/test_srt_to_sup.py`. Aufgefallen beim 3D-Test mit BD3DEnc v0.7.1.

## [1.11.1] - 2026-10-13

### Größe einzelner Buttons (Button-Stil, Stufe 2)

Gilt für Text- und Form-Buttons. Im Export kommt wie bisher nur eine Breite und Höhe pro Button an; ohne eigene Größe bleibt der Menüstrom byte-gleich.

- **Modell (`MenuButton.size`):** `[w, h]` überschreibt die Größe aus Layout bzw. Button-Stil, mindestens 8 px. Ohne feste Position sitzt der Button mittig an seinem Platz (`core/disc_adapter.py`).
- **Griffe im Viewer (`gui/studio/viewer.py`):** acht Griffe am ausgewählten Button, gleich groß bei jedem Zoom und bei dünnen Linien weit genug auseinander. Ziehen ändert die Größe live; die gegenüberliegende Kante bleibt, mit Alt die Mitte, mit Umschalt an einer Ecke das Seitenverhältnis. Bei Mehrfachauswahl bekommen alle Buttons in der gezogenen Richtung dieselbe Breite bzw. Höhe. Ein Rückgängig-Schritt; an Hilfslinien geheftete Buttons bleiben mittig auf der Linie.
- **Inspektor (Karte „Anordnung“):** „Größe des ausgewählten Buttons“ mit Zahlenfeldern (Mitte bleibt) und ↺ zum Zurücksetzen.
- **Zurücksetzen:** „Auf Vorlage zurücksetzen“ und „Alle auf Vorlage zurücksetzen“ verwerfen auch eigene Größen. Ein Wechsel zwischen Text und Form verwirft die eigenen Größen des Menüs (sie passen nur zum alten Stil); Strg+Z holt sie zurück.
- **Tests (`tests/test_button_sizes.py`):** Layout, Bearbeiten, Rechenregel der Griffe, Viewer mit echten Mausereignissen (Live-Vorschau, ein Schritt, Mehrfachauswahl), Inspektor, Stilwechsel, Größe auf der Simulations-Disc.

## [1.11.0] - 2026-10-13

### Form-Buttons (Button-Stil, Stufe 1)

Wie in DVD Studio Pro: Die Beschriftung steht im Hintergrundbild, der Button ist nur eine Form, die beim Auswählen aufleuchtet.

- **Button-Stil pro Menü (`core/disc_model.py`, `ButtonStyle`):** „Text“ (wie bisher, Standard) oder „Form“: Linie, Kreis, Dreieck mit Spitze nach rechts oder links. Breite und Höhe gelten für alle Buttons des Menüs (Linie: Höhe = Strichstärke), mindestens 8 px. Farbe und Deckkraft für normal, ausgewählt und aktiviert einzeln; Standard: normal unsichtbar, ausgewählt gold, aktiviert weiß. Alte Projekte laden unverändert als Text-Buttons.
- **Grafik (`modules/button_shapes.py`, neu):** gewöhnliche RGBA-Bilder wie bei den Text-Buttons; geglättete Kanten mit höchstens vier Farben pro Zustand.
- **Layout (`core/disc_adapter.py`):** Formen sitzen mittig in dem Platz, den das Layout für den Button vorsieht; im Viewer gesetzte Positionen bleiben.
- **Zwei kleine, rein additive Eingriffe in die Pipeline:** `generate_menu_subclip` wählt pro Button Form oder Text (`button_state_image`); `IGSCompiler.compile_pages` hat den optionalen Parameter `priority_images`. Die Farben der Form-Buttons bekommen damit zuerst einen Platz in der gemeinsamen Palette. Ohne Form-Buttons wird er nicht gesetzt, der Menüstrom bleibt byte-gleich. Grund: Text-Buttons brauchen schon bei vier Buttons über 600 Farben; ohne Vorrang wurde z. B. Rot in einem Form-Menü hinter einem Text-Menü zu Graubraun.
- **Inspektor:** neue Karte „Button-Stil“ (Stil, Form, Größe, Farbe und Deckkraft pro Zustand); jede Änderung ist ein Rückgängig-Schritt.
- **Viewer:** zeigt die echten Formen; im aktuellen Zustand unsichtbare Formen erscheinen gepunktet. Dünne Linien sind auf mindestens 24 px Höhe greifbar.
- **Tests (`tests/test_button_shapes.py`):** Grafik, Modell, Layout, Palette (byte-gleich ohne Formen, exakte Formfarbe neben Text-Buttons), Simulations-Disc mit Text-Hauptmenü und rotem Form-Kapitelmenü, Inspektor und Viewer.

## [1.10.1] - 2026-10-12

### Disc-Titel im Player (Konzept Stufe 3.2)

Viele Player zeigen beim Einlegen nur den Medientyp („BD-RE“). Sie lesen den Titel aus `BDMV/META/DL/bdmt_<sprache>.xml`.

- **Generator (`modules/bdmv/meta_generator.py`, neu):** schreibt `bdmt_eng.xml` (Rückfall für alle Player) und `bdmt_deu.xml` im Disc-Library-Format (disclib → di:discinfo mit Datum, Titel, Sprache; UTF-8 ohne BOM).
- **„Titel im Player“ im Disc-Inspektor (Start-Knoten):** freier Text mit Umlauten (`DiscSettings.disc_title`). Der Disc-Name (Label) muss UDF-konform bleiben (A–Z, 0–9, _) und eignet sich deshalb nicht als Anzeige; bleibt das Feld leer, wird der Titel aus ihm abgeleitet („MEINE_DISC“ → „MEINE DISC“).
- **Export:** nach der Menü-Injektion, also im BDMV-Ordner und in der ISO (geprüft: beide Dateien samt Titel in der ISO). Navigation und Ströme bleiben unverändert. Bei einer Disc ohne Menü als ISO schreibt tsMuxeR die ISO direkt – dann entfällt der Titel, das Protokoll sagt es.
- **Vorerst zum Einschalten:** Häkchen „Titel „…“ im Player anzeigen“ in „Disc erstellen“ (nennt den Titel, der geschrieben wird) (`DiscSettings.disc_title_meta`), Standard aus – die Standard-Disc bleibt byte-gleich, bis der Brenntest bestanden ist. Danach wird der Standard „an“.
- **Testcheckliste:** `TESTCHECKLISTE_1_10_1.md` für den Brenntest.
- **Tests:** XML-Aufbau und Titel wie libbluray gelesen, Sonderzeichen, eine Datei je Sprache, abgeleiteter Titel, alte Projekte; Feld im Inspektor (Rückgängig, Label unverändert); Ende-zu-Ende mit tsMuxeR: ohne Häkchen kein META/DL, mit Häkchen beide Dateien mit dem Titel (mit Umlaut), Navigation byte-gleich; Häkchen im Dialog (gespeichert, Rückgängig).

## [1.10.0] - 2026-10-12

### Disc simulieren direkt aus dem Projekt

Bisher musste für den Simulator erst eine Disc erstellt werden (muxen mit tsMuxeR, bei einem echten Film Minuten). Jetzt öffnet „Disc simulieren“ das aktuelle Projekt in Sekunden – ohne tsMuxeR und ffmpeg, also auch in der Designer-Edition. An der Disc ändert sich nichts (Byte-Test des Exports unverändert grün); kein Brenntest nötig.

- **Simulations-Disc (`modules/sim_disc.py`, neu):** Simuliert wird, was der Export erzeugt, kein Nachbau. Menü, `index.bdmv` und `MovieObject.bdmv` entstehen mit `inject_menu_into_bdmv` und denselben Argumenten wie beim Export. Ersetzt wird nur, was tsMuxeR und ffmpeg liefern: Film-Playlists als Platzhalter nach dem Vorbild von tsMuxeR (Start-PTS, Kapitel als Marken, Ton- und Untertitelspuren, 3D-Erweiterung, Nummern und Clip-IDs wie nach dem Muxen) und der Menü-Hintergrund als Platzhalter-Clip mit derselben Start-PTS und der Dauer in ganzen Bildern. Preflight-Fehler und Disc ohne Menü werden verständlich gemeldet.
- **Zwei kleine, rein additive Eingriffe in die Pipeline:** Die Argumente der Menü-Injektion (`menu_injection_args`) und die 3D-Bildratenanpassung (`normalize_3d_fps`) liegen jetzt in `modules/disc_export.py` als gemeinsame Funktionen für Export und Simulation. `inject_menu_into_bdmv` hat den optionalen Parameter `background_renderer`; ohne ihn bleibt alles wie bisher.
- **Knopf „Disc simulieren“:** Klick simuliert das aktuelle Projekt; der Pfeil daneben öffnet wie bisher eine fertige Disc (ISO oder BDMV-Ordner). Das Simulator-Fenster zeigt das Hintergrundbild des Menüs aus dem Projekt und heißt „<Disc-Name> (aus dem Projekt)“; der temporäre Ordner wird beim Schließen gelöscht.
- **Designer-Edition:** „Projekt prüfen“ hängt an den Strukturbericht den Befund des Disc-Simulators an.
- **Gegenprobe mit echtem tsMuxeR:** Dasselbe Projekt exportiert und simuliert – `index.bdmv`, `MovieObject.bdmv`, Menüstrom und Menü-Playlist byte-gleich, Film-Playlists mit denselben Marken und Spuren, derselbe Simulator-Befund.
- **Grenzen:** Was nur der Player beantwortet (Bildraten, Timing, Ströme, Player-Eigenheiten), findet auch diese Simulation nicht. Filme sind Platzhalter-Karten.
- **Tests:** Startprojekt, Disc A (Kapitel über zwei Seiten, Ton & Untertitel: jeder Kapitel-Button an seiner Marke, Spurwahl beim Start), Disc B (3D), mehrere Filme, Disc ohne Menü, Preflight-Fehler, kein externer Prozess, Platzhalter-Playlist und -Hintergrund; Gegenprobe gegen den echten Export; Knopf im Studio (Fenster, Titel, Aufräumen, Fehlermeldungen); Designer-Prüfung mit Simulator-Bericht.

## [1.9.12] - 2026-10-12

### Aufgeräumt: Node-Ansicht beim Start, Designer-Edition, README

- **Node-Ansicht beim Start eingepasst (`gui/node_editor/view.py`):** Beim Programmstart war der Graph winzig und lag knapp außerhalb des Bildes. Ursache: „Alles anzeigen“ lief, bevor das Fenster sichtbar war (bei 1500×920), danach wurde maximiert bzw. das gespeicherte Layout wiederhergestellt. Jetzt wird „Alles anzeigen“ vor dem Anzeigen nur vorgemerkt und ausgeführt, sobald die Ansicht ihre endgültige Größe hat – wie ein Klick auf den Knopf. Bis zum ersten eigenen Zoomen, Klicken oder Tastendruck passt die Ansicht bei Größenänderungen weiter neu ein. Gilt auch für ein Projekt, das vor dem Anzeigen geöffnet wird.
- **Designer-Edition (nachgetragen, Stand 2026-10-02):** Eigene Ausgabe des Studios für UX-Tests ohne tsMuxeR (`main_designer.py`, `Start_Designer.bat`, `core/designer_mode.py`). Als Film-Video lassen sich Bilder oder MP4-Dateien als Platzhalter verwenden; „Disc erstellen“ zeigt statt des Exports einen Prüfbericht über die Projektstruktur. Als eigenständige EXE mit `tools/build_designer.bat` (`designer.spec`). Die normale Ausgabe und die Disc ändern sich dadurch nicht.
- **README** auf den Stand von v1.9.12 gebracht (Bedienung seit v1.9.8, Designer-Edition, Hardware-Stand).
- **Tests:** Graph nach dem ersten Anzeigen vollständig sichtbar; nach eigenem Zoomen ändert eine Größenänderung die Ansicht nicht mehr.

## [1.9.11] - 2026-09-29

### Korrektur: Anlege-Fenster schloss sich sofort

- **Fehler behoben (`gui/node_editor/create_popup.py`):** Klick auf einen gestrichelten Vorschlag (z. B. `＋ SPRACHE`) öffnete das Anlege-Fenster unter Windows nur für einen Augenblick. Ursache: Es war ein natives Popup und öffnete sich, während die Maustaste noch gedrückt war. Jetzt ein rahmenloses Werkzeugfenster mit eigener Ereignisschleife; ein Klick daneben, Escape oder ein Wechsel in ein anderes Programm schließen es, Enter legt an.
- **Öffnen beim Loslassen:** Node-Ansicht und Viewer öffnen das Anlege-Fenster bzw. die Angebotsliste von „＋ Button“ erst beim Loslassen der Maustaste.
- **Zweiter Fehler, beim Testen gefunden:** „Anlegen“ blendete das Fenster aus, das dabei ausgelöste „Fenster inaktiv“ wurde als Abbruch gewertet – es wäre nichts angelegt worden.
- **Aussehen:** keine Rahmen mehr um Texte und Auswahlpunkte (kamen vom allgemeinen Stylesheet).
- **Tests:** Das echte Fenster ohne Abkürzung: bleibt beim Loslassen daneben offen, schließt beim Klick daneben, „Anlegen“ legt an; Klick auf einen Vorschlag im Viewer legt erst beim Loslassen an. Zusätzlich unter echtem Windows geprüft (Fenster offen und aktiv, Menü angelegt).

## [1.9.10] - 2026-09-29

### Einheitliche Bedienung, Teil 3: Ein Button ist ein Button (Konzept 2.1, Regel 4)

Rückmeldung aus dem Brenntest v1.9.7: Automatisch angelegte Kapitel-Buttons wirkten fest, weil sie nur als unsichtbare Gruppe zu ziehen waren (einzeln erst per Doppelklick oder Alt). Jetzt verhalten sich alle Buttons gleich, wie in Keynote.

- **Einzeln ziehen (`gui/studio/viewer.py`):** Klick wählt einen Button aus, Ziehen verschiebt genau ihn – Kapitel, Tonspur oder ZURÜCK. Doppelklick und Alt zum Freistellen entfallen.
- **Mehrfachauswahl:** Umschalt- oder Strg-Klick nimmt Buttons hinzu bzw. heraus, ein Auswahlrahmen auf freier Fläche wählt alle, die er berührt. Ziehen und Pfeiltasten bewegen die ganze Auswahl (ein Rückgängig-Schritt); die Abstands-Hilfe wirkt auf die Auswahl als Block. An Hilfslinien heftet sich weiterhin nur ein einzelner Button.
- **Auf Vorlage zurücksetzen:** Rechtsklick auf Buttons: „Auf Vorlage zurücksetzen“ (Auswahl) und „Alle Buttons auf Vorlage zurücksetzen“ (neu `menu_design.reset_buttons`; die Schaltfläche im Inspektor heißt jetzt „Alle auf Vorlage zurücksetzen“).
- **Title Safe sichtbar:** Die Zone ist in *Gestalten* als feiner gestrichelter Rahmen zu sehen; ein Button, der beim Ziehen darüber hinausragt, bekommt einen orangen Rand (bisher nur ein Preflight-Hinweis in „Disc erstellen“).
- **Ältere Projekte:** Ein Raster-Versatz (`content_offset`) und die Heftung des Rasters gelten weiter; beim Zurücksetzen einzelner Buttons wird der Versatz aufgelöst und die übrigen Buttons behalten ihre Stelle.
- **Außerdem:** Das Feld „Zustand“ im Viewer passt sich an seinen Text an (war nach v1.9.9 abgeschnitten).
- **Testcheckliste:** `TESTCHECKLISTE_1_9_10.md` für die neue Bedienung aus v1.9.8–v1.9.10.
- **Tests:** einzelnes Kapitel ziehen, Umschalt-Klick und Auswahlrahmen, Pfeiltasten mit Auswahl, Title-Safe-Markierung, Zurücksetzen der Auswahl und aller Buttons, Kapitel heftet sich einzeln an eine Linie, Zurücksetzen mit Raster-Versatz (Qt-frei).

## [1.9.9] - 2026-09-29

### Einheitliche Bedienung, Teil 2: Fernbedienung (Konzept 2.1, Regel 5)

Rückmeldung aus dem Brenntest v1.9.7: Das Pfeil-Overlay war schwer zu deuten (bei ZURÜCK zeigten drei Linien auf drei Kapitel – es waren die ↓-Pfeile der Kapitel, nicht die ↑-Richtung von ZURÜCK), und dass man Richtungen im Inspektor festlegen kann, war nicht zu finden. Jetzt probiert man es aus, wie am Fernseher.

- **Umschalter „Gestalten | Fernbedienung“** über der Vorschau (statt des Schalters „Pfeiltasten“). In *Gestalten* bleibt alles wie bisher (Zustand, Hilfslinien, Buttons ziehen und mit den Pfeiltasten verschieben).
- **Fernbedienung (`gui/studio/viewer.py`):** Der ausgewählte Button ist der aktuelle (zu Beginn der Start-Button des Menüs). Die Pfeiltasten der Tastatur springen wie auf dem Player; Enter (oder Leertaste) zeigt kurz den Aktiviert-Zustand und löst aus: Buttons, die in ein Menü führen, wechseln dorthin (Node-Ansicht und Inspektor gehen mit); sonst sagt eine Zeile unter der Vorschau, was passiert („▶ „Hauptfilm“ startet bei Kapitel 3“, „Ton: ENGLISCH gewählt – gilt beim Filmstart“ …).
- **Pfeil-Griffe:** nur am aktuellen Button, je an der Seite, in die die Taste führt, mit gestrichelter Linie zum Ziel; Sprünge über den Rand (Wrap-Around) laufen als Bogen außen herum. Klick auf einen Griff = Taste drücken. **Griff auf einen anderen Button ziehen** legt die Richtung fest (gold), auf den eigenen Button = „bleibt stehen“ (Punkt statt Pfeil). Rechtsklick auf einen Griff: „Automatisch (→ Ziel)“ bzw. „bleibt auf diesem Button“. Jede Änderung ist ein Rückgängig-Schritt und landet wie bisher im Export.
- **Rot umrandet:** Buttons, die vom Start-Button aus mit den Pfeiltasten nicht erreichbar sind (dieselbe Prüfung wie der Preflight, neu `menu_design.reachable_buttons`).
- **Entfallen:** die Karte „Pfeiltasten“ im Menü-Inspektor und das Pfeil-Overlay mit allen Pfeilen aller Buttons.
- **Tests:** Umschalten, Pfeiltasten nach den wirksamen Zielen, Klick auf Griff, Enter wechselt ins Zielmenü bzw. beschreibt Kapitel, Griff ziehen legt fest (ein Schritt, gold, Export), „bleibt stehen“, Rechtsklick setzt zurück, rote Markierung unerreichbarer Buttons.

## [1.9.8] - 2026-09-29

### Einheitliche Bedienung, Teil 1: Anlegen (Konzept 2.1, Regeln 1–3)

Rückmeldung aus dem Brenntest v1.9.7: Menüs für Kapitel, Ton und Untertitel ließen sich auf acht Wegen anlegen, jeder mit anderen Optionen, teils in der Node-Ansicht, teils im Inspektor. Jetzt gilt überall dasselbe: Was es geben kann, steht gestrichelt dort, wo es hingehört; ein Klick legt es an, und wenn es etwas zu entscheiden gibt, fragt ein kleines Fenster direkt an der Stelle. An der Disc ändert sich nichts.

- **Vorschläge in jedem Menü (`core/menu_templates.py`: `suggestions()`):** Ein Menü ohne Inhalts-Buttons, das zu genau einem Film mit Kapiteln bzw. Spuren zur Wahl führt, schlägt dessen Kapitel- und Sprachmenü vor – beim Einzelfilm das Hauptmenü, bei „Film + Bonus“ ebenfalls, bei einer Serie das Menü der Folge (bisher nur das Hauptmenü). Inhalts-Menüs zeigen, was von ihrem Film fehlt: auf der letzten Kapitelseite `＋ KAPITEL 9–12`, in Sprachmenüs `＋ TON: …` bzw. `＋ UNTERTITEL: …`. Dieselbe Liste in der Node-Ansicht, im Viewer (gestrichelte Buttons, jetzt in jedem Menü) und für die Preflight-Hinweise.
- **Ton nachträglich:** `＋ TON` in einem reinen Untertitelmenü macht daraus „Ton & Untertitel“ (zwei Spalten, Ton links); ein Button „UNTERTITEL“, der dorthin führt, heißt danach „SPRACHE“. Umgekehrt genauso.
- **Anlege-Fenster (`gui/node_editor/create_popup.py`, ersetzt den Dialog „Menü aus Vorlage …“):** Sprachmenü: eine Seite, zwei Seiten, nur Untertitel, nur Ton (nur was mit den Spuren geht); Kapitelmenü: Kapitel pro Seite mit Vorschau; bei mehreren Filmen „Wie bei „Folge 1““; fehlende Kapitel: auf dieser Seite (das Raster wächst mit) oder auf einer neuen Seite mit WEITER. Knöpfe „Nicht benötigt“ und „Anlegen“. Ohne Entscheidung (z. B. `＋ TON`, `＋ FILME`) legt der Klick direkt an.
- **Verlinkt, wo der Vorschlag stand:** Das neue Menü bekommt seinen Button in dem Menü, in dem der Vorschlag stand, und sein „ZURÜCK“ führt dorthin (bisher immer Hauptmenü).
- **„＋ Button“** bietet beim Klick „Neuer Button …“ und alle Menüs an, die von hier aus möglich sind (Kapitel- und Sprachmenü je Film, Filmauswahl); ohne Angebote fragt er wie bisher direkt nach der Beschriftung.
- **Umentscheiden = löschen:** Wird ein Menü gelöscht, verschwindet der Button, der zusammen mit ihm entstanden ist (`MenuButton.created_with`), und der Vorschlag erscheint wieder. Selbst angelegte Buttons bleiben unverbunden.
- **Rechtsklick „Nicht benötigt“** auf einen Vorschlag jetzt auch im Viewer; gilt auch für fehlende Kapitel und Spuren (dann ohne Preflight-Warnung).
- **Entfallen (jede Aktion hat nur noch einen Ort):** Chips „＋ Kapitelmenü“ / „＋ Sprachmenü“ am Film-Knoten; „＋ … anlegen“, „Vorlage …“ und „wie bei …“ im Film-Inspektor; „Kapitelseite anhängen“ und „Fehlende ergänzen“ im Menü-Inspektor; „Menü aus Vorlage …“, „Kapitel-/Sprachmenü aus Vorlage …“ und „Filmauswahl anlegen“ in den Kontextmenüs.
- **Tests:** Vorschlagsregel (Einzelfilm, Film + Bonus, mehrere Filme, Folgenmenü, Inhalts-Menüs), Anlegen aus einem Untermenü (Button und ZURÜCK), Ton nachträglich, fehlende Kapitel auf dieser oder neuer Seite, Löschen nimmt den Link-Button mit (Rückgängig), Anlege-Fenster, „＋ Button“, Vorschläge und Rechtsklick im Viewer.

## [1.9.7] - 2026-09-29

### Feinschliff der Bedienung

- **Abstands- und Ausrichtungs-Hilfe beim Ziehen (`core/menu_spacing.py`, neu):** Wie in Keynote rastet ein gezogener Button ein, wenn sein Abstand zum Nachbarn einem vorhandenen Abstand zwischen anderen Buttons entspricht oder er genau mittig zwischen zwei Nachbarn sitzt; ebenso bündig an Kanten und Mitten anderer Buttons. Pinke Markierungen zeigen die gleichen Abstände bzw. die gemeinsame Kante – nur solange die Hilfe beim Ziehen greift. An einer Hilfslinie wirkt die Abstands-Hilfe entlang der Linie; der Button bleibt geheftet. Nichts davon wird gespeichert, auf die Disc kommen nur die Positionen.
- **„Buttons gleichmäßig verteilen“:** Ab drei gehefteten Buttons bleiben der erste und der letzte, wo sie sind, und die übrigen kommen in gleichen Abständen dazwischen (bisher: über die ganze Linie verteilt). Mit einem oder zwei Buttons wie bisher.
- **„Buttons mittig anordnen“** (Rechtsklick auf eine Hilfslinie): rückt alle gehefteten Buttons als Block in die Mitte der Linie; ihre Abstände untereinander bleiben. Zusammen mit „gleichmäßig verteilen“ entsteht so ein Stapel mit gleichen Abständen und gleich viel Rand oben und unten.
- **Obere Leiste neu gestaltet:** höher, mit echten Knöpfen (Rahmen, Hover, deutlich blasse deaktivierte Knöpfe), Gruppen mit Abstand statt Trennstrichen. Rechts der Preflight-Status als farbige Plakette (grün bereit, gelb Warnungen, rot Fehler) und „Disc erstellen“ als blau gefüllter Hauptknopf.
- **„Alles anzeigen“ in der Node-Ansicht:** als Symbol-Knopf (vier Eck-Klammern) oben rechts in der Node-Ansicht statt in der oberen Leiste, dazu die Taste **F**; Tooltip „Alles anzeigen (F)“. Im Rechtsklick-Menü der freien Fläche weiterhin vorhanden.
- **Rücksprünge-Umschalter in der Node-Ansicht:** Symbol-Knopf links neben „Alles anzeigen“ statt Textschalter in der oberen Leiste. Das Symbol zeigt die aktuelle Art (gestrichelter Rückbogen = Linien, Etikett mit Rückpfeil = Sprungmarken, dann blau hinterlegt); der Tooltip nennt Art und was ein Klick bewirkt.
- **Obere Leiste aufgeräumt:** „＋ Film“ und „＋ Menü“ entfallen – Knoten entstehen per Rechtsklick auf die freie Fläche, durch Ziehen von einem Ausgang ins Leere oder durch Hineinziehen eines Videos. Ein dezenter Hinweis unten links in der Node-Ansicht nennt diese drei Wege.
- **Filmfarbe im Inspektor:** Rechts neben dem Namen eines Films zeigt ein Farbfeld seine Farbe; ein Klick bietet die 8 Filmfarben und „Eigene Farbe …“ (Farbdialog). Die Farbe gilt für den Knoten und seine Menüs, ein Rückgängig-Schritt. Neue Filme bekommen ihre Farbe weiterhin automatisch.
- **Ankerpunkte neu verteilt:** 7 pro Kante statt 9 – Title Safe (5 / 95 %), Viertel (25 / 75 %), Goldener Schnitt (38,2 / 61,8 %) und Mitte, gleichmäßig verteilt statt dicht beieinanderliegender Paare. Action Safe (nur für Bildinhalte gedacht) und Drittel (zu dicht am Goldenen Schnitt) entfallen. Die Form zeigt die Art: Mitte großer Punkt, Goldener Schnitt goldene Raute, Title Safe hohler Ring. Linien, die an früheren Punkten hängen, bleiben gültig.
- **Bildmitte beim Ziehen:** Buttons und das Kapitelraster rasten mit ihrer Mitte auch an der waagerechten und senkrechten Bildmitte ein (Markierung: Mittellinie), frei wie entlang einer Hilfslinie.

## [1.9.6] - 2026-09-29

### Mehrere Filme – ohne Einzelfilm-Nutzer zu stören

Bewusst schlank gehalten: Alles erscheint nur, wenn es mehrere Filme gibt. Für ein Projekt mit einem Film ändert sich an der Oberfläche nichts.

- **Filmauswahl (`core/menu_templates.py`):** Ab 3 Filmen schlägt das Hauptmenü `＋ FILME` vor (im Knoten und als gestrichelter Button im Viewer; „Nicht benötigt“ gilt für die ganze Disc). Ein Klick legt ein Menü „Filmauswahl“ mit einem Button pro Film und „ZURÜCK“ an und verlinkt es im Hauptmenü. Ab 2 Filmen auch per Rechtsklick auf die freie Fläche.
- **„wie bei „Folge 1““ (`gui/studio/inspector.py`):** Hat ein anderer Film schon ein Kapitel- bzw. Sprachmenü, bietet der Film-Inspektor neben „＋ Kapitelmenü anlegen“ an, es genauso anzulegen: gleiche Seitenaufteilung bzw. Art (zusammen/getrennt), dazu Anordnung, verschobene Buttons, festgelegte Pfeiltasten und Hilfslinien. Ein Rückgängig-Schritt.
- **Weniger Unordnung bei Serien:** Vorschläge im Hauptmenü, die Verlinkung neuer Kapitel-/Sprachmenüs im Hauptmenü und der Preflight-Hinweis „hat Kapitel, aber kein Kapitelmenü“ gelten nur noch für Filme, zu denen das Hauptmenü direkt führt – bei 10 Folgen stünden sonst 20 Vorschläge im Hauptmenü. Der Dialog „Menü aus Vorlage …“ setzt „Im Hauptmenü verlinken“ nach derselben Regel vor (änderbar).
- **Zurückgestellt:** Gruppen in der Node-Ansicht, ein gemeinsames Sprachmenü für alle Folgen und ein Disc-Assistent – sie würden die Bedienung für alle komplizierter machen.
- **Tests (`tests/test_series.py`):** Einzelfilm unverändert, Filmauswahl (Vorschlag, Buttons, Export, Ablehnen, Mindestanzahl), Verlinkungsregel, „wie bei …“ für Kapitel (Aufteilung, Layout, Positionen, Pfeiltasten, Hilfslinien) und Sprache (Art, Fehler bei fehlenden Spuren), Inspektor-Knopf nur, wo er hilft.

## [1.9.5] - 2026-09-29

### Pfeiltasten im Menü-Designer

- **Pfeil-Overlay (`gui/studio/viewer.py`):** Schalter „Pfeiltasten“ über der Vorschau zeigt, wohin die Pfeiltasten der Fernbedienung führen – beim ausgewählten Button nur dessen vier Pfeile, ohne Auswahl alle. Im Inspektor festgelegte Richtungen sind gold.
- **Überschreiben pro Button:** Im Menü-Inspektor erscheint bei ausgewähltem Button die Karte „Pfeiltasten“ mit ↑ ↓ ← →: „Automatisch (→ Ziel)“ oder ein fester Button (auch „bleibt auf diesem Button“). Datenmodell `MenuButton.dpad`; der Export wendet die Überschreibungen nach der automatischen Berechnung an (Layout-Regel oder Lage), ohne Überschreibung bleibt alles byte-gleich. Wird ein Ziel-Button entfernt, wird die Richtung wieder automatisch.
- **Preflight (`core/preflight.py`), geprüft an denselben Button-Daten wie der Export:**
  - Warnung: zwei Buttons überlappen sich.
  - Hinweis: Buttons außerhalb der Title-Safe-Zone (90 %) können auf manchen Fernsehern angeschnitten sein.
  - Warnung: Buttons, die vom Start-Button aus mit den Pfeiltasten nicht erreichbar sind (vor allem nach Überschreibungen).
- **Tests:** Überschreiben bis in den Export (auch mit Pfeiltasten aus der Lage), zurück auf automatisch byte-gleich, Aufräumen beim Entfernen des Ziels, die drei Preflight-Prüfungen, Inspektor-Karte und Overlay; Ende-zu-Ende mit echtem tsMuxeR: die überschriebene Pfeiltaste steht im IG-Strom.

## [1.9.4] - 2026-09-29

### Hilfslinien im Menü-Designer

Menüs lassen sich an Hilfslinien ausrichten, die zwischen Punkten am Bildrand gezogen werden. An den Linien geheftete Buttons wandern mit, wenn eine Linie umgehängt wird. Für die Disc ändert sich nichts Neues: Auf die Disc kommen nur die daraus entstehenden festen Positionen.

- **Ankerpunkte (`core/menu_guides.py`, neu):** an allen vier Kanten bei Action Safe, Title Safe, Drittel, Goldenem Schnitt und Mitte (36 Punkte).
- **Linien ziehen (`gui/studio/viewer.py`):** von Punkt zu Punkt – waagerecht, senkrecht oder schräg. An einem Punkt mit Linien-Ende hängt Ziehen das Ende um, mit Umschalt beginnt eine neue Linie. Anklicken wählt aus, Entf löscht; Rechtsklick: gleichmäßig verteilen, löschen. Schalter „Hilfslinien“ über der Vorschau.
- **Heften mit der Mitte:** Buttons und das Kapitelraster als Ganzes rasten beim Ziehen an einer nahen Linie ein und bleiben geheftet (Stelle als Anteil entlang der Linie). Geheftete Buttons gleiten beim Ziehen und mit den Pfeiltasten an der Linie entlang; **X** löst – auch bei gehaltener Maus mitten im Ziehen: Der Button folgt dann frei und rastet in diesem Zug nicht wieder an derselben Linie ein (Lösen und Ablegen sind ein Rückgängig-Schritt). Die Linie eines ausgewählten, gehefteten Buttons leuchtet auf.
- **Mitwandern:** Wird ein Ende umgehängt, setzen sich alle gehefteten Buttons an dieselbe Stelle der neuen Linie (im Bild gehalten).
- **Datenmodell:** `Guide`, `GuideBinding`, `ViewState.guides` / `guide_bindings` (pro Menü, rückgängig machbar, mit dem Projekt gespeichert). „Auf Layout zurücksetzen“ löst die Heftungen; beim Löschen eines Menüs werden seine Linien entfernt.
- **Außerdem:** doppelte Methode `_draw_background` im Viewer entfernt (Rest aus v1.9.3).
- **Tests:** Geometrie (Ankerpunkte, Projektion auf schräge Linien), Heften, Mitwandern, Raster als Ganzes, Verteilen, Lösen, Löschen, im Bild halten, Speichern; im Viewer mit echten Maus- und Tastaturereignissen (Linie ziehen, Einrasten, Umhängen, Gleiten, X, Entf, Umschalt für zweite Linie, ungültige Linien).

## [1.9.3] - 2026-09-29

### Viewer als Menü-Designer

Erster Teil des Menü-Designers (Konzept Kap. 5): Menüs direkt im Viewer gestalten. Menüs, in denen nichts verschoben wurde, bleiben byte-gleich zum bisherigen Export.

- **Echte Vorschau (`gui/studio/viewer.py`):** Der Viewer zeichnet die Buttons mit denselben Grafiken, die der Export in den Menüstrom schreibt (Stil-Generator), statt eigener Rechtecke. Umschalter „Zustand“: wie auf dem Player (Standard-Button ausgewählt), Normal, Ausgewählt, Aktiviert.
- **Gemeinsame Button-Auswahl:** Ein Klick auf einen Button im Viewer markiert ihn im Inspektor (Button-Liste) und in der Node-Ansicht (Zeile im Menü-Knoten) – und umgekehrt: Klick auf eine Button-Zeile im Knoten oder in die Button-Liste wählt ihn im Viewer aus (`GraphController.select_button`).
- **Verschieben:** Kapitel-, Ton- und Untertitel-Buttons ziehen das Raster als Ganzes mit (`MenuLayout.content_offset`); ein einzelner Inhalts-Button wird per Doppelklick oder mit Alt freigestellt. Navigations-Buttons ziehen einzeln (`MenuButton.position`). Pfeiltasten verschieben den ausgewählten Button um 1 px, mit Umschalt um 10 px (aufeinanderfolgendes Tippen ist ein Rückgängig-Schritt). Buttons bleiben im Bild. „Auf Layout zurücksetzen“ im Inspektor (Karte „Anordnung“).
- **Pfeiltasten aus der Lage (`modules/igs/layout.py`, `core/disc_adapter.py`):** Sobald in einem Menü etwas verschoben ist (`MenuLayout.dpad = "spatial"`), werden die Pfeiltasten aus der tatsächlichen Lage berechnet: nächster Button im 45°-Kegel der Pfeilrichtung, sonst Wrap-Around zur gegenüberliegenden Seite. Vorher zeigten verschobene Buttons weiter auf ihre alten Nachbarn.
- **Vorschläge im Viewer:** Im Hauptmenü erscheinen `＋ KAPITEL` / `＋ SPRACHE` als gestrichelte Buttons unter den vorhandenen; ein Klick legt Button und Untermenü an.
- **Neu: `core/menu_design.py`** (Verschieben, Zurücksetzen, Qt-frei).
- **Test-Disc:** `1_9_3_DISC_A_MOVED.iso` – Hauptmenü links unten, Kapitelraster oben, „FILM STARTEN“ im Sprachmenü oben rechts. Simulator: 0 Fehler, 0 Warnungen. **Brenntest ausstehend.**
- **Tests:** räumliche Pfeiltasten (Raster, Wrap-Around, Ausrichtung, eine Zeile), Verschieben/Zurücksetzen byte-gleich, Speichern; Viewer mit echten Maus- und Tastaturereignissen (Auswahl überall, Raster ziehen, Alt/Doppelklick einzeln, im Bild halten, Pfeiltasten als ein Schritt, Zurücksetzen, Klick im Knoten, Vorschlag); Ende-zu-Ende mit echtem tsMuxeR: verschobene Buttons, Simulator ohne Warnungen.

## [1.9.2] - 2026-09-29

### Kapitel- und Sprachmenüs leichter finden

Rückmeldung zu v1.9.1: Wo man ein Untertitelmenü „aktiviert“, war nicht offensichtlich – man musste den Film anklicken und den Knopf suchen. Man denkt aber vom Ergebnis her („mein Hauptmenü braucht SPRACHE“). Die Aktionen stehen jetzt dort, wo man sie sucht.

- **Vorschläge im Hauptmenü (`gui/node_editor/rows.py`, `scene.py`):** Der Hauptmenü-Knoten zeigt gedimmte Zeilen `＋ KAPITEL` und `＋ SPRACHE` (bzw. `＋ TON`, `＋ UNTERTITEL`; bei mehreren Filmen mit Filmnamen) mit hohlem, gestricheltem Ausgang – sichtbar, aber noch kein echter Button. Ein Klick legt Button und Untermenü an und wählt das Untermenü aus. Rechtsklick → „Nicht benötigt“ blendet den Vorschlag für diesen Film aus, zusammen mit dem Preflight-Hinweis (`dismissed_hints`, rückgängig machbar).
- **Aktionen bei den Inhalten (`gui/studio/inspector.py`):** Im Film-Inspektor steht „＋ Kapitelmenü anlegen“ direkt unter der Kapitel-Tabelle und „＋ Sprachmenü anlegen“ unter den Untertiteln (ohne Untertitel unter den Tonspuren), jeweils mit „Vorlage …“. Gibt es das Menü schon: „✓ Im Menü „Kapitel 1/3“ – öffnen“. Ohne Hauptmenü nur ein Hinweis. Die eigene Karte „Menüs“ aus v1.9.1 entfällt.
- **Film-Knoten:** Die Schnellaktionen sind als Knöpfe (Pillen) gezeichnet statt als Textzeilen.
- **Fahrplan:** Menü-Designer im Viewer (mit Vorschlags-Buttons direkt in der Vorschau) wird v1.9.3, Serien-Komfort v1.9.4.
- **Unit-Tests:** Vorschläge erscheinen und verschwinden mit dem Menü, „Nicht benötigt“ inklusive Preflight und Rückgängig, Beschriftung bei mehreren Filmen, echter Mausklick auf die Vorschlagszeile, Platz der Aktionen im Inspektor, Hinweis ohne Hauptmenü.

## [1.9.1] - 2026-09-29

### Kapitel- und Sprachmenüs im Studio anlegen

Zweiter Teil von „Inhalts-Menüs im Studio“: die Oberfläche zu den Vorlagen aus v1.9.0. An der Pipeline ändert sich nichts.

- **Schnellaktionen am Film-Knoten (`gui/node_editor/rows.py`, `scene.py`):** „＋ Kapitelmenü“ ab 2 Kapiteln, „＋ Sprachmenü“, sobald es Spuren zur Wahl gibt (nur mit Hauptmenü). Ein Klick legt das Menü mit Standardwerten an und wählt es aus; existiert es, zeigt die Zeile „✓“ und ein Klick wählt es aus.
- **Dialog „Menü aus Vorlage …“ (`gui/node_editor/template_dialog.py`, neu):** Vorlage (Kapitel, Sprachmenü nach Vorschlag, Ton & Untertitel zusammen oder getrennt, nur Ton, nur Untertitel), Quell-Film, Kapitel pro Seite, Verlinkung im Hauptmenü. Zeigt vorab, was entsteht („20 Kapitel, 8 pro Seite → 3 Seite(n)“), und sperrt „Anlegen“, wenn die Vorlage nicht passt. Aufruf über das Kontextmenü der Node-Ansicht und des Film-Knotens sowie im Film-Inspektor.
- **Film-Inspektor:** Karte „Menüs“ mit denselben Aktionen und „Aus Vorlage …“.
- **Menü-Inspektor:** Karte „Inhalt“ für Inhalts-Menüs (Quell-Film, Kapitelbereich von–bis, „Kapitelseite anhängen“, „Fehlende ergänzen (n)“) und Karte „Anordnung“ für alle Menüs (automatisch, Raster mit Spalten × Reihen und Platzanzeige, zwei Spalten).
- **Rückgängig:** Jede Vorlage und jede Inhalts-Aktion ist ein Schritt; passt eine Vorlage nicht (z. B. keine Kapitel), gibt es eine Meldung und keinen Schritt (`GraphController._execute_trial`).
- **Abnahme ohne Brennen:** Disc A und Disc B über die Vorlagen gebaut (Disc A mit 2 Kapiteln pro Seite zum Blättern, Disc B mit reinem Untertitelmenü, da nur eine Tonspur). `index.bdmv`, `MovieObject.bdmv`, alle Playlists und Film-Clips sind byte-gleich mit den v1.8.8-Discs aus dem bisherigen Weg; anders sind nur Menüstrom (neues Layout) und der neu kodierte Menü-Hintergrund. Simulator: 0 Fehler, 0 Warnungen. **Brenntest ausstehend.**
- **Unit-Tests (`tests/test_studio_templates.py`):** ein Undo-Schritt pro Vorlage, Fehler ohne Schritt, Aktionszeilen, Schnellaktion legt an und wählt aus, Inspektor (Bereich, Fehlendes, Anordnung, Seite anhängen), Dialog (Vorschau, Anlegen, Sperre).

## [1.9.0] - 2026-09-29

### Inhalts-Menüs aus Vorlagen (ohne Oberfläche)

Erster Teil von „Inhalts-Menüs im Studio“ (Konzept, Plan v1.9.0/v1.9.1): Datenmodell, Vorlagen, Layouts und Preflight. Die Oberfläche dazu folgt mit v1.9.1. An den Befehlen der Pipeline ändert sich nichts; bestehende und umgewandelte Menüs bleiben byte-gleich.

- **Layout-Arten (`core/disc_model.py`):** `MenuLayout.kind` = `auto` (bisherige Regel, Standard), `grid` (Inhalts-Buttons im festen Raster `grid_cols × grid_rows`, Navigation als Zeile darunter) oder `columns` (Ton links, Untertitel rechts, Navigation darunter). Ältere Projektdateien ohne diese Felder laden als `auto`.
- **Layout-Engine (`modules/igs/layout.py`):** `layout_fixed_grid` und `layout_two_columns` mit vollständiger Pfeiltasten-Verdrahtung (im Raster in alle Richtungen, aus der unteren Reihe in die Navigationszeile und zurück, zwischen den Spalten auf gleicher Höhe). Das Raster reserviert immer alle Plätze: Kapitel und Navigation stehen beim Blättern auf jeder Seite an derselben Stelle. Der Export-Adapter wählt die Anordnung nach `kind`.
- **Vorlagen (`core/menu_templates.py`, neu):**
  - Kapitelmenü: 8 Kapitel pro Seite (4 × 2), Seiten „Kapitel 1/3“ …, verdrahtet mit ZURÜCK · HAUPTMENÜ · WEITER, optional „KAPITEL“ im Hauptmenü.
  - Sprachmenü: „Ton & Untertitel“ auf einer Seite (bis je 4 Spuren) oder getrennte, gegenseitig verlinkte Seiten „Ton“ und „Untertitel“; jeweils mit ZURÜCK und FILM STARTEN, optional „SPRACHE“ im Hauptmenü.
  - Hilfsfunktionen: Kapitelseite anhängen, Kapitelbereich einer Seite setzen, fehlende Kapitel oder Spuren ergänzen.
- **Preflight (`core/preflight.py`):** Warnung „Kapitel 17–20 von … sind in keinem Menü“ (nur bei Filmen mit Kapitelmenü), Warnung bei mehr Inhalts-Buttons als Rasterplätzen, Hinweis bei einem Sprachmenü ohne Weg zum Film.
- **Tests:** Vorlagen (Seiten, Verdrahtung, Bereiche, zusammen/getrennt), Layouts (Positionen, jeder Button per Pfeiltasten erreichbar), Preflight; Ende-zu-Ende mit echtem tsMuxeR: Disc aus Vorlagen im Simulator ohne Fehler und Warnungen, jeder Kapitel-Button startet an seiner Marke, Ton- und Untertitelwahl gilt beim Filmstart.

## [1.8.8] - 2026-09-29

### Menüs auf dem Panasonic DMP-BDT111

Erster Brenntest auf dem Panasonic: Discs mit Menü luden kurz und fielen ins Player-Menü zurück; Discs ohne Menü (reine tsMuxeR-ISO) starteten. Eingegrenzt durch Vergleich mit tsMuxeR sowie Test-ISOs, die sich jeweils nur in einem Punkt unterschieden.

- **Fehler behoben – Spurtabelle der Playlists (`modules/mpls/mpls_generator.py`):** `build_menu_mpls` und `build_movie_mpls` schrieben die STN-Einträge gepackt (`stream_entry` 3 bzw. 5 Bytes, IG-Attribute 4 Bytes). tsMuxeR schreibt immer 9 bzw. 5 Bytes, mit Nullen aufgefüllt. Der Panasonic liest die Tabelle mit diesen festen Größen und verwarf die Menü-Playlist beim Einlegen; Sony und libbluray lesen die Längenfelder und waren nicht betroffen. Auf dem Panasonic mit gepatchter Disc A bestätigt: Das Menü erscheint.
- **Fehler behoben – gelber Schleier über dem Menü (`modules/igs/palette.py`):** Die Button-Palette vergab die Farben 1–255. Eintrag 255 war auf beiden Test-Discs ein fast deckender Gelbton; der Panasonic löscht die Grafikebene mit diesem Eintrag und legte ihn über das ganze Menü außerhalb der Buttons. Farben jetzt nur noch 1–254, Eintrag 255 bleibt transparent. Auf dem Panasonic bestätigt.
- **UDF (`modules/udf250_writer.py`):** Der Eintrag für den Elternordner zählt die Füllbytes zur CRC-Länge (24 statt 22), wie tsMuxeR und ECMA-167. Damit sind die Verzeichniseinträge identisch mit einer tsMuxeR-ISO.
- **Gegenprobe ausstehend:** Brenntest von v1.8.8 (Disc A und B aus dem Code gebaut) auf dem Sony UBP-X700.
- **Offen:** Filme ruckeln bzw. bleiben auf dem Panasonic stehen, auch als reine tsMuxeR-Disc ohne Menü und Untertitel (Disc A 2D, Disc B 3D). Nicht Teil dieser Version.
- **Unit-Tests:** STN-Einträge mit fester Größe (Menü- und Film-Playlist), Eintrag 255 bleibt bei über 254 Farben frei, CRC des Elternordner-Eintrags.

## [1.8.7] - 2026-09-28

### 3D-Umschaltung nur auf 3D-Playern

- **3D-Profilprüfung (`modules/bdmv/movie_object_generator.py`):** Vor jedem `SetOutputMode` prüft das MovieObject das Player-Profil (PSR 31, Maske `0x130240` = Profil 5), wie in libbluray. Player ohne 3D kennen den Befehl nicht; mit der Prüfung überspringen sie die Umschaltung und spielen das linke Bild in 2D, statt womöglich abzubrechen. Drei zusätzliche Befehle, Register GPR 6.
- **Simulator:** meldet `SetOutputMode` ohne vorherige Profilprüfung als Hinweis; PSR 31 je nach Player (3D: Profil 5, sonst Profil 2).
- **Unit-Tests:** Befehle byteweise, Umschaltung wird auf 2D-Playern übersprungen, Hinweis für ungeschützte Umschaltung.

## [1.8.6] - 2026-09-28

### Spurwahl aus dem Film bleibt erhalten

- **Menü übernimmt die Spuren des letzten Films (`modules/bdmv/movie_object_generator.py`):** Bei Discs mit Sprachmenü setzt der Titel beim Start GPR 5 („Film lief“). Kommt der Player danach ins Menü (Filmende oder Top Menu), kopiert das TopMenu-Objekt die aktuelle Ton- und Untertitelspur samt Anzeige in GPR 1–3 und löscht GPR 5. Eine im Film per Fernbedienung gewählte Spur gilt dadurch beim nächsten Start weiter, statt von einer früheren Menüwahl überschrieben zu werden (`Move GPR = PSR1`).
- **Unverändert:** Beim ersten Einlegen gilt die Voreinstellung des Players (nichts wird übernommen), die Menü-Schleife übernimmt nichts erneut, Discs ohne Sprachmenü sind byte-gleich wie bisher.
- **Simulator:** Ton- und Untertitel-Taste der Fernbedienung (Fenster: „Ton ⟳“, „Untertitel ⟳“, Tasten A/U); `And`/`ShiftR` und PSR-Operanden lesbar.
- **Unit-Tests:** Übernahme mit und ohne vorherigen Film, Anzeige an/aus, Fernbedienungs-Wahl übersteht Top Menu und Neustart, TopMenu-Objekt ohne Sprachmenü unverändert.

## [1.8.5] - 2026-09-28

### Spurwechsel mit zwei Operanden

- **Fehler behoben (`modules/bdmv/movie_object_generator.py`, `modules/igs/segments.py`):** `SetStream` wurde mit einem Operanden geschrieben (`0x31 …`). Nach BD-ROM Part 3 hat der Befehl zwei (Ton/Untertitel, IG/Winkel). Der Sony UBP-X700 ignorierte ihn deshalb – Ton- und Untertitelwahl aus dem Menü blieben in v1.8.4 ohne Wirkung, obwohl Register und Kapitelsprung funktionierten. Jetzt `0x51 C0 …` bzw. mit Register `0x51 40 …`.
- **Simulator (`modules/bdsim/hdmv.py`):** prüft die Operandenzahl aller System-Befehle; `SetStream` mit falscher Zahl ist ein Fehler. Die ISO aus v1.8.4 meldet damit genau die drei betroffenen Befehle.
- **Simulator liest auch fremde Discs:** IG-Menüs werden nur am Anfang eines Clips gesucht (das Menü liegt dort oft im Film-Clip); die Struktur-Ausgabe kennzeichnet Pop-up-Menüs und nicht lesbare IG-Ströme.
- **Unit-Tests:** Befehle byteweise, Operandenzahl im Simulator.

## [1.8.4] - 2026-09-28

### Kapitel, Ton und Untertitel aus dem Menü – nach dem Brenntest von Disc A

- **Fehler behoben – Top Menu nach einem Kapitelstart (`modules/bdmv/movie_object_generator.py`, `modules/igs/layout.py`, `modules/menu_author.py`):** Kapitel-Buttons starteten ein Einstiegsobjekt per `JumpObject`. Der Player blieb im Menü-Titel, und die Unterbrechung durch Top Menu wurde nie verworfen: Auf dem Sony UBP-X700 sprang danach jede Top-Menu-Taste in das zuerst gewählte Kapitel, auch im Hauptmenü. Jetzt merkt sich der Kapitel-Button die Marke in GPR 0 und startet den Film per `JumpTitle`; das MovieObject des Titels springt an die Marke und setzt den Wunsch zurück. Die Kapitel-Einstiegsobjekte entfallen.
- **Fehler behoben – Ton- und Untertitelwahl im Menü wirkungslos:** `SetStream` lief, während die Menü-Playlist spielte, die die Spuren nicht hat; der Sony verwarf die Wahl (offener Punkt 11.2.1, jetzt bestätigt). Die Buttons merken sich die Wahl nur noch (GPR 1–3), der Titel schaltet vor dem Abspielen um. „Untertitel aus“ schaltet Spur 1 mit ausgeschalteter Anzeige, damit die Spurnummer gültig ist.
- **Registerbelegung** GPR 0–4 festgelegt, GPR 5–15 reserviert (Konzept 9.1.1). Titel ohne Kapitel- und Sprachmenü behalten die bisherigen Befehle unverändert.
- **Sprachmenü (`core/constants.py`, `core/disc_rules.py`):** Beschriftung „TON: …“ und „UNTERTITEL: …“ statt „AUDIO:“/„SUB:“, damit die Buttons nicht verwechselt werden. Sprachnamen immer in lateinischer Schrift in der Sprache der Menüs („JAPANISCH“ statt „日本語“, das als Kästchen erschien; „ENGLISCH“, „FRANZÖSISCH“).
- **Simulator (`modules/bdsim/`):**
  - Top Menu wie auf dem Sony: Unterbrechung merken, eine bestehende bleibt erhalten, Top Menu im Menü setzt fort, nur `JumpTitle` verwirft. Warnung, wenn ein Film über `JumpObject` startet, während eine Unterbrechung gemerkt ist.
  - Spurwahl im Menü ohne passende Spur in der Menü-Playlist ist jetzt eine Warnung (Ton und Untertitel).
  - Register-Befehle lesbar (`SetStream(Ton = GPR1, …)`); das Fenster zeigt die im Menü gemerkte Wahl.
  - Durchlauf deutlich schneller (Register nur gespeichert, wenn belegt); Grenze 50 000 Zustände.
  - Gegenprobe: Die ISO von Disc A (v1.8.3) meldet jetzt genau die Probleme des Brenntests.
- **Unit-Tests:** Titel-Objekt mit Kapitel- und Spurwahl in der Maschine, Kapitel-Buttons starten den Titel, Top Menu und Fortsetzen, Warnung für den alten Weg, Register-Befehle byteweise; bestehende Tests angepasst. Ende-zu-Ende mit echtem tsMuxeR: jeder Kapitel-Button startet den Titel an seiner Marke.

## [1.8.3] - 2026-09-28

### Simulator im Studio und in „Disc erstellen“

- **Automatische Prüfung beim Export (`modules/disc_export.py`, `gui/studio/export_dialog.py`):** Sobald die BDMV-Struktur fertig ist – vor ISO-Erstellung und Aufräumen –, spielt der Simulator die Disc mit 3D- und 2D-Fernseher durch. Ergebnis und alle Befunde stehen im Protokoll; danach öffnet „🔍 Disc simulieren“ die Disc im Simulator-Fenster, auch wenn der BDMV-Ordner schon aufgeräumt ist (dann ohne Standbilder). Neuer optionaler Parameter `on_disc_ready` von `export_disc`; Fehler darin brechen den Export nicht ab.
- **„Disc simulieren …“ in der Studio-Werkzeugleiste:** öffnet eine fertige ISO oder einen BDMV-Ordner (über `index.bdmv`) im Simulator. Eine ISO wird unter Windows schreibgeschützt eingehängt und beim Schließen des Fensters wieder ausgehängt; offene Simulator-Fenster schließen mit dem Studio.
- **Projekt-Übergabe aus der bisherigen Oberfläche (`gui/app.py`):** Der Knopf „Neue Oberfläche“ übergibt das dort geöffnete Projekt als umgewandelte Kopie ans Studio (bisher startete das Studio leer). „Speichern“ fragt danach nach einem neuen Dateinamen, damit die Alt-Datei nicht im neuen Format überschrieben wird. Ohne geladenen Film bleibt es beim Startprojekt.
- **Fehler behoben (`modules/disc_export.py`):** Scheiterte die ISO-Erstellung, meldete der Export trotzdem Erfolg. Jetzt schlägt er fehl, und der BDMV-Ordner bleibt erhalten.
- **Gemeinsames Öffnen von Discs (`modules/bdsim/source.py`):** ISO, Disc- oder BDMV-Ordner, `index.bdmv`; von Befehlszeile und Studio genutzt.
- **Unit-Tests:** Export-Dialog mit Simulator-Ergebnis und Knopf, Studio-Knopf und Schließen, Projekt-Übergabe, Öffnen aus Ordner/index.bdmv; Ende-zu-Ende: Einhängepunkt wird aufgerufen, gescheiterte ISO lässt den Export fehlschlagen.

## [1.8.2] - 2026-09-28

### ISO-Erstellung bei Filmen über 1 GB

- **Fehler behoben (`modules/udf250_writer.py`):** Die eigene UDF-2.50-Engine beschrieb jede Datei mit einem einzigen Extent. Das Längenfeld eines Extents hat nur 30 Bit (die oberen 2 Bit sind der Typ), also höchstens knapp 1 GiB.
  - Dateien über 4 GB: Abbruch („'I' format requires …“), die ISO entstand dann über den Windows-Fallback (IMAPI2FS). Aufgefallen bei Disc A (Film 6,3 GB).
  - Dateien zwischen 1 und 4 GB: Die Länge lief ohne Meldung in die Typ-Bits über; der Film wäre in der ISO unlesbar gewesen.
  - 3D-Filme über 1 GB: kein Fallback möglich, der Export wäre gescheitert oder defekt gewesen.
- **Lösung:** Große Dateien werden auf mehrere Extents von höchstens 1 GiB − 2 KiB verteilt (zusammenhängend auf der Disc); zu lange Extents werden mit einer Fehlermeldung abgewiesen statt still falsch geschrieben.
- **Gegenprobe:** Disc A (17 Dateien, Film 6,28 GB) mit der eigenen Engine neu erstellt, unter Windows eingehängt: alle Dateien byte-identisch, Simulator ohne Fehler und Warnungen.
- **Unit-Tests (`tests/test_iso_tools.py`):** Aufteilung, File Entry mit mehreren Extents (Inhalt aus der ISO zurückgelesen), Abweisung zu langer Extents.

## [1.8.1] - 2026-09-28

### Simulator-Fenster

- **Disc durchklicken (`gui/studio/simulator.py`):** Eigenes Fenster mit dem Fernseher im 1920×1080 Raum. Menüs zeigen ein Standbild aus dem Menü-Video und die echten Button-Grafiken der Disc (aus dem Menüstrom decodiert, ausgewählter Button hervorgehoben). Filme erscheinen als Karte über einem Standbild an der Startstelle mit Titel, Playlist, 2D/3D, Kapitel, Ton- und Untertitelspur.
- **Fernbedienung:** Pfeile, OK, Top Menu, „Zum Ende“, Kapitel vor/zurück, Disc neu einlegen; per Klick, per Tastatur (Pfeile, Enter, T, E, Bild ↑/↓) oder mit der Maus direkt auf den Buttons. Umschalter 3D-/2D-Fernseher.
- **Zustand und Protokoll:** aktuelle Seite, Button, Spuren und Bildmodus; jeder ausgeführte Befehl und jeder Befund der Navigation erscheint im Protokoll. „Automatische Prüfung …“ zeigt den vollständigen Bericht für beide Fernseher.
- **Aufruf:** `python tools/simulate_disc.py <ISO oder Ordner> --fenster`. Die Einbindung ins Studio und in „Disc erstellen“ folgt mit v1.8.3.
- **Bild-Hilfen (`modules/bdsim/graphics.py`):** Button-Grafiken (RLE + Palette, BT.709) als RGBA; Standbilder per ffmpeg, zwischengespeichert.
- **Kapitel-Tasten im Simulator (`modules/bdsim/player.py`):** vor/zurück innerhalb der Kapitelmarken des laufenden Films.
- **Unit-Tests:** `tests/test_simulator_window.py` (Fenster, Fernbedienung, Maus, Fernseher-Umschaltung, Protokoll, Button-Grafiken).

## [1.8.0] - 2026-09-28

### Disc-Simulator (Prüf-Kern) und Korrekturen an Kapitelsprüngen

- **Disc-Simulator (`modules/bdsim/`):** Liest eine fertige Disc (`index.bdmv`, `MovieObject.bdmv`, Playlists, IG-Menüstrom) und spielt ihre Navigation nach, mit dem Verhalten von BD-ROM Part 3 und libbluray: Register, alle Befehlsgruppen, Titel- und Objektwechsel, Rückkehr nach Playlist-Ende, Seitenwechsel, Button-Auswahl und Pfeiltasten, 3D-Umschaltung mit 2D- oder 3D-Fernseher.
- **Automatischer Durchlauf:** Ab „Disc einlegen“ wird jeder Button auf jeder erreichten Seite gedrückt, jede Playlist läuft zu Ende, die Top-Menu-Taste wird probiert. Der Bericht nennt Fehler, Warnungen und Hinweise mit dem Weg dorthin, u. a. unerreichbare Titel und Seiten, wirkungslose Buttons, Sprünge ins Leere, unzulässige Befehle, ignorierte Operanden, Pfeiltasten-Lücken, 3D-Filme ohne 3D-Umschaltung, Spurwahl ohne passende Spur und die Rückkehr zum Hauptmenü bei Ablauf der Menü-Schleife.
- **Befehlszeile (`tools/simulate_disc.py`):** Prüft einen Disc- oder BDMV-Ordner oder eine ISO (unter Windows automatisch schreibgeschützt eingehängt). `--struktur` listet alle Buttons und MovieObjects mit ihren Befehlen, `--tv 2d|3d|beide` wählt den Fernseher.
- **Gegenprobe mit echten Brenntests:** Die ISO aus v1.7.6 zeigt den Extras-Fehler, die ISO aus v1.7.7 läuft sauber durch, eine ältere 3D-Disc ohne 3D-Umschaltung wird erkannt.
- **Fehler behoben – Kapitelmarke wurde nicht gelesen (`modules/bdmv/movie_object_generator.py`, `modules/igs/segments.py`):** `PlayPLatPM` hatte die Operandenzahl 1. Der Player liest dann nur die Playlist und startet jeden Kapitelsprung bei Kapitel 1. Jetzt Operandenzahl 2 (`0x42 C2 …`).
- **Fehler behoben – Kapitel-Buttons bei 2D-Filmen (`modules/menu_author.py`):** Die Buttons führten `PlayPLatPM` direkt aus. Playlist-Befehle sind in Buttons nicht erlaubt und werden vom Player verworfen. Alle Kapitel-Buttons springen jetzt über ein Kapitel-Einstiegsobjekt, wie bisher schon bei 3D-Filmen; 2D-Einstiegsobjekte enthalten kein `SetOutputMode`.
- **Unit-Tests:** `tests/test_bdsim.py` (Befehle, Maschine, Player, Durchlauf auf Discs aus den Generatoren, Regressionstests mit den Befehlen aus v1.7.6 und v1.7.7). Der Ende-zu-Ende-Export mit echtem tsMuxeR wird zusätzlich im Simulator durchgespielt: keine Fehler oder Warnungen, jeder Kapitel-Button startet an seiner eigenen Marke. Kapitel- und Opcode-Tests an die Korrekturen angepasst.
- **Hinweis:** Kapitel- und Sprachmenüs vor v1.8.0 konnten auf dem Player nicht korrekt funktionieren; Test-Discs A und B mit v1.8.0 bauen (Konzept, Kap. 11.1).

## [1.7.7] - 2026-09-28

### Menüseiten-Wechsel und Sprachauswahl auf dem Player

- **Fehler behoben (`modules/bdmv/movie_object_generator.py`, `modules/igs/segments.py`):** Buttons, die in ein anderes Menü führen (z. B. „Extras“, „Kapitel“, „Sprache“, „Zurück“), reagierten auf dem Player nicht. `SetButtonPage` wurde in der falschen Befehlsgruppe codiert (Register-Arithmetik statt SetSystem, `0x30…` statt `0x51…`), die Seite stand im falschen Operanden, und das Page-Flag fehlte. Der Player führte deshalb eine wirkungslose Rechenoperation aus. Gefunden beim Brenntest `176_4_CLIP_TEST.iso`: Die drei Filme im Hauptmenü starteten, der Button ins Extras-Menü tat nichts.
- **Gleicher Fehler bei `SetStream`:** Die Buttons zur Auswahl von Ton und Untertiteln lagen ebenfalls in der Arithmetik-Gruppe und wirkten nicht. Sie sind jetzt als SetSystem codiert (`0x31…`).
- **Unit-Tests (`tests/test_hdmv_opcodes.py`):** Die bisherigen Tests hatten die falschen Bytes festgeschrieben. Sie prüfen jetzt die Codierung nach BD-ROM Part 3 und libbluray; ein Regressionstest stellt sicher, dass alle SetSystem-Befehle in Gruppe 2 / Untergruppe 1 liegen.
- **Hinweis:** Beim nächsten Brenntest Extras-Menü, „Zurück“ und gegebenenfalls die Sprachauswahl prüfen.

## [1.7.6] - 2026-09-28

### Buttons direkt im Knoten und im Inspektor anlegen

- **„＋ Button“ im Menü-Knoten (`gui/node_editor/rows.py`, `scene.py`):** Jeder Menü-Knoten hat unten eine Zeile „＋ Button“ mit hohlem Ausgang. Klick auf Zeile oder Ausgang legt einen Button an und fragt nach der Beschriftung. Ziehen auf einen Film oder ein Menü legt Button und Verbindung in einem Schritt an; die Beschriftung übernimmt den Namen des Ziels (z. B. „BONUS“). Ziehen ins Leere bietet wie in v1.7.5 einen neuen Film oder ein neues Menü an – ein Zug erzeugt dann Button, Knoten und Verbindung. Bisher ging das nur versteckt per Rechtsklick.
- **Gleiche Regeln (`core/disc_rules.py`):** Der neue Button prüft seine Ziele mit derselben Regel wie bestehende Navigations-Buttons (kein Sprung ins eigene Menü).
- **Button-Liste im Menü-Inspektor (`gui/studio/inspector.py`):** Beschriftung direkt ändern, Reihenfolge mit ↑↓ (Inhalts-Buttons wie Kapitel behalten ihre Plätze), ✕ zum Entfernen, „＋ Button hinzufügen“ mit Fokus auf dem neuen Eingabefeld. Leere Beschriftungen werden verworfen; reine Umbenennungen bauen die Liste nicht neu auf, damit ein direkt folgender Klick nicht verloren geht.
- **Unit-Tests:** Regeln, Button mit Ziel und mit neuem Knoten als ein Undo-Schritt, Verschieben an Inhalts-Buttons vorbei, Klick und Ziehen am „＋“-Ausgang, Inspektor-Liste.

## [1.7.5] - 2026-09-28

### Neuer Knoten direkt aus einer Verbindung

- **Vorschläge beim Loslassen im Leeren (`gui/node_editor/scene.py`):** Wird eine Verbindung von einem Ausgang ins Leere gezogen, erscheinen an dieser Stelle „Neuer Film“ und „Neues Menü“. Ein Klick legt den Knoten an und verbindet ihn in einem einzigen Rückgängig-Schritt; sein Eingang liegt genau an der Stelle des Loslassens, und er ist anschließend ausgewählt. Die gezogene Linie bleibt sichtbar, solange die Vorschläge offen sind.
- **Gleiche Regeln wie beim Verbinden (`core/disc_edit.py`):** Welche Vorschläge erlaubt sind, wird geprüft, indem der Knoten probeweise in einer Kopie des Projekts angelegt wird. Gesperrte Vorschläge erscheinen mit 🔒 und Stufe; gibt es gar keinen erlaubten Vorschlag (z. B. am Film-Ende), erscheint stattdessen der Grund in der Statusleiste.
- **Verbindung lösen:** Bisher löste Loslassen im Leeren eine bestehende Verbindung sofort. Das ist jetzt ein Eintrag in den Vorschlägen; Escape oder ein Klick daneben ändert nichts.
- **Unit-Tests:** Regeln für neue Knoten, Anlegen und Verbinden als ein Undo-Schritt, Position und Auswahl des neuen Knotens, Abbrechen, Verbindung lösen, gesperrte Ausgänge.

## [1.7.4] - 2026-09-28

### 3D-Bildrate beim Import in der neuen Oberfläche

- **Fehler behoben (`gui/studio/importer.py`):** Rohe 3D-Streams melden oft fälschlich 25 fps; die Videoanalyse korrigiert das nur mit 3D-Hinweis. Beim gemeinsamen Hineinziehen von Video und MVC wurde das Video vor der MVC-Datei analysiert, also ohne Hinweis. Für Titel 1 fing der Export das ab, weitere 3D-Titel wären mit 25 fps gemuxt worden; zudem erschien ein falscher „25p“-Hinweis.
- Die MVC-Datei wird jetzt vor dem Video übernommen; beim nachträglichen Hinzufügen oder Entfernen der MVC-Datei wird das Video mit passendem Hinweis neu analysiert.
- **Unit-Tests:** Import in beliebiger Reihenfolge, nachträgliches Hinzufügen/Entfernen der MVC-Datei.

## [1.7.3] - 2026-09-28

### Mitgelieferte Schriften für Menüs und Untertitel

- **Unabhängig von installierten Schriften (`modules/fonts.py`, `assets/fonts/`):** Alles, was auf die Disc gerendert wird, nutzt jetzt mitgelieferte Schriften unter der SIL Open Font License. Eine Disc sieht damit auf jedem Rechner und jedem Betriebssystem identisch aus (Voraussetzung für Linux/macOS).
- **Menü-Buttons: Liberation Sans** statt Arial. Metrisch identisch mit Arial (gleiche Zeichenbreiten, per Test geprüft), dadurch unverändertes Button-Layout; die Glyphen weichen minimal ab, der Text sitzt etwa einen Pixel tiefer.
- **Untertitel aus `.srt`: Noto Sans** statt Segoe UI (sehr ähnlicher Stil, Latein/Griechisch/Kyrillisch). Für Japanisch, Chinesisch und Koreanisch werden weiterhin Systemschriften verwendet – jetzt auch mit Kandidaten für macOS und Linux; ohne passende Schrift wird Noto Sans genommen.
- **Unit-Tests:** `tests/test_fonts.py` (keine Systemschrift für Buttons, Zeichenbreiten identisch mit Arial, Untertitel- und CJK-Auswahl je Betriebssystem).
- **Hinweis:** Die Menügrafiken ändern sich minimal; beim nächsten Brenntest kurz ansehen.

## [1.7.2] - 2026-09-28

### Umschaltung „Rücksprünge: Linien / Sprungmarken“ korrigiert

- **Linien-Ansicht (`gui/node_editor/scene.py`):** Nicht verbundene Film-Enden, die standardmäßig ins Hauptmenü zurückführen, werden jetzt als blasse, gepunktete Linie zum Hauptmenü gezeichnet statt als Sprungmarke. Bisher zeigten beide Ansichten dafür dieselbe Marke, sodass die Umschaltung scheinbar nichts bewirkte.
- **Sprungmarken-Ansicht:** unverändert; alle Rücksprünge erscheinen als „↩ Ziel“.
- **Überfahren einer Linie** hebt jetzt – wie bei Sprungmarken – den Zielknoten hervor.
- **Rechtsklick auf eine Standard-Linie** zeigt „Standard: nach Filmende ins Hauptmenü“ (nichts zu lösen).
- **Tests:** Regressionstest für die Umschaltung; der Windows-Rauchtest schaltet die Ansicht über den Schalter der Werkzeugleiste um und prüft beide Zustände.

## [1.7.1] - 2026-09-28

### Fehlerbehebungen in der neuen Oberfläche (nur unter echtem Windows sichtbar)

- **Absturz im Node-Editor behoben (`gui/node_editor/scene.py`):** Die Sprungmarke „↩ Hauptmenü“ rief `setCursor()` auf, bevor ihre Breite feststand. Unter Windows fragt Qt dabei sofort die Abmessungen ab; die Ausnahme brach den Aufbau des Graphen ab. Folgen: Verbindungen verschwanden nach dem Verschieben eines Knotens, Verbindungen ließen sich nicht ziehen (nur Auswahlrahmen), Endlos-Fehlerausgaben bis zum Absturz. Im Offscreen-Testmodus trat der Fehler nicht auf.
- **Fehlermeldungen beim Beenden behoben (`gui/studio/main_window.py`):** Die Rückgängig-Liste meldete sich nach dem Abbau der Schaltflächen noch einmal.
- **Regressionstests:** `tests/test_windows_behaviour.py` stellt das Windows-Verhalten nach (sofortige Abfrage der Abmessungen) und prüft, dass beim Zeichnen keine versteckten Fehler in Python-Überschreibungen auftreten. `tests/test_gui_smoke_windows.py` spielt echte Mausaktionen auf der Windows-Oberfläche ab (nur mit `OPENBDAUTH_GUI_SMOKE=1`).

## [1.7.0] - 2026-09-28

### „Disc erstellen“ in der neuen Oberfläche: Export über den Node-Graphen

- **Gemeinsamer Export-Ablauf (`modules/disc_export.py`):** Der bisherige Export (tsMuxeR, Multi-Title, 3D/SSIF, HDMV-Menü, UDF 2.50 ISO) wurde unverändert aus dem Export-Bereich in ein eigenes Modul verschoben und wird von beiden Oberflächen genutzt. Einziger Zusatz: optionale `pages_specs` aus dem Node-Graphen.
- **Ende-zu-Ende-Test (`tests/test_e2e_export.py`):** Erzeugt Testclips mit ffmpeg, exportiert mit echtem tsMuxeR über den bisherigen Weg und über den Graphen und vergleicht jede Datei der Disc: byte-identisch (Streams, Playlists, Clip-Infos, index.bdmv, MovieObject.bdmv, Menü).
- **Preflight-Check (`core/preflight.py`):** Fehler (z. B. Film ohne Video, Start nicht verbunden, fehlender Inhalt, Stufe-2-Verbindungen), Warnungen (unverbundene Buttons, Sackgassen, unerreichbare Menüs, unbestätigte Kompatibilitätshinweise) und Hinweise (fehlendes Kapitel-/Sprachmenü).
- **Dialog „Disc erstellen“ (`gui/studio/export_dialog.py`):** Preflight-Liste (Klick wählt den Knoten aus), Zielordner, BDMV-Ordner oder ISO, Aufräumen nach ISO, Protokoll und Fortschritt. Fehler sperren den Export.
- **Werkzeugleiste:** ständige Preflight-Anzeige (⛔ / ⚠ / ✅ Bereit), „Disc erstellen“ aktiv.
- **Menü-Inspektor:** Hintergrund des Hauptmenüs (Standbild, Motion-Video, Musik, Loop-Dauer) per Schaltfläche oder Drag & Drop; übrige Menüs zeigen den gemeinsamen Hintergrund (Stufe 1).
- **Theme:** Gesperrte Primär-Schaltflächen sind jetzt als gesperrt erkennbar.
- **Unit-Tests:** `tests/test_export_dialog.py`.

## [1.6.0] - 2026-09-28

### Neue Arbeitsoberfläche „OpenBDAuth“ (Vorschau)

Start über `Start_Studio.bat`, `python main.py --studio` oder den Knopf „✨ Neue Oberfläche (Vorschau)“ in der bisherigen Oberfläche. Die bisherige Oberfläche bleibt bis zum Export über den Graphen (v1.7.0) unverändert nutzbar.

- **Hauptfenster (`gui/studio/main_window.py`):** Node-Ansicht als zentraler Bereich, **Viewer** und **Inspektor** als andockbare Bereiche, die sich abkoppeln und auf einen zweiten Bildschirm ziehen lassen. Arbeitsbereiche „Ein Bildschirm“ / „Zwei Bildschirme“, die Anordnung wird gespeichert. Die Auswahl eines Knotens steuert Viewer und Inspektor.
- **Film-Inspektor (`gui/studio/inspector.py`):** Video und 3D-Ergänzung mit Analyse und Kompatibilitätsprüfung, Tonspuren und Untertitel mit Sprache und Reihenfolge, Kapitel als Tabelle (Zeit, optionaler Name) mit EDL-Import. Alles per Drag & Drop auf den Film-Knoten oder in den Inspektor, oder per Schaltfläche. Ein Video, das ins Leere der Node-Ansicht gezogen wird, legt einen neuen Film an.
- **Menü- und Start-Inspektor:** Menüname, Hauptmenü festlegen, Button-Übersicht; Disc-Name und Sprache der Oberfläche.
- **Viewer (`gui/studio/viewer.py`):** Menü-Vorschau im 1920×1080-Raum mit exakt dem Button-Layout des Exports; Übersichtskarten für Filme und die Disc.
- **Der Graph ist die einzige Quelle der Wahrheit:** Filme werden direkt im Graphen gepflegt; die Übergangs-Synchronisation und der Bereich „Struktur“ aus v1.5.1 entfallen. Projekte werden als `.bdproj` im neuen Format gespeichert; ältere Projekte lassen sich öffnen.
- **Neue Module:** `core/media_import.py` (Dateityp- und Spracherkennung, Tonspur-Vorbereitung – die WAV-Bereinigung und E-AC-3-Extraktion nutzt jetzt auch die bisherige Oberfläche), `core/disc_edit.py` (Bearbeitungs-Operationen, Startprojekt), `core/chapter_time.py`.
- **Rückgängig/Wiederholen** für alle Änderungen inklusive Importe.
- **Unit-Tests:** `tests/test_studio.py`.

## [1.5.2] - 2026-09-28

### Konzept: neue Arbeitsoberfläche nach dem Vorbild von DaVinci Fusion

- **`KONZEPT_UND_DESIGN_NODE_AUTHORING.md`:** Die bisherige Tab-Oberfläche wird vollständig ersetzt. Node-Ansicht, Viewer und Inspektor als andockbare Bereiche (auch auf zwei Bildschirmen), Auswahl eines Knotens steuert Viewer und Inspektor. Kein Medien-Pool: Video, Ton, Untertitel und Kapitel werden im Film-Knoten importiert. Export über den Dialog „Disc erstellen“.
- **Fahrplan:** v1.6.0 neues Hauptfenster & Film-Inspektor, v1.6.x Viewer als Menü-Designer, v1.7.0 Export über den Graphen mit anschließendem Brenntest und Entfernen der alten Oberfläche.

## [1.5.1] - 2026-09-28

### Neuer Bereich „Struktur“: Node-Editor für den Disc-Ablauf (Stufe 1, Teil 2)

- **Node-Editor (`gui/node_editor/`, `gui/tabs/tab_structure.py`):** Neuer Bereich „🧭 Struktur“ zwischen „Video & Audio“ und „Menü-Designer“.
  - Start-, Film- und Menü-Knoten, Fluss von links nach rechts: Eingang links, Ausgänge rechts (ein Ausgang pro Navigations-Button, „Ende“ pro Film).
  - Verbinden per Ziehen vom Ausgang auf einen Knoten; Ziehen ins Leere löst die Verbindung. Beim Ziehen zeigt jeder Knoten, ob die Verbindung erlaubt (grün), für Stufe 2 gesperrt (🔒, orange) oder ungültig (rot) ist.
  - Inhalts-Buttons (Kapitel, Tonspuren, Untertitel) erscheinen zusammengefasst ohne Draht, z. B. „▸ Kapitel 1–4 → Der Film“; fehlende Inhalte werden markiert.
  - Rücksprünge wahlweise als gestrichelte Linien oder als Sprungmarken „↩ Ziel“ (Hover zeigt die Verbindung, Klick springt zum Ziel). Unverbundene Film-Enden zeigen „↩ Hauptmenü“.
  - Menüs anlegen, umbenennen, löschen, als Hauptmenü festlegen; Navigations-Buttons hinzufügen, umbenennen, entfernen (Rechtsklick).
  - Rückgängig/Wiederholen für alle Änderungen (Strg+Z / Strg+Y), Zoom per Mausrad, Verschieben mit Leertaste oder mittlerer Maustaste, „Alles anzeigen“.
- **Übergangs-Synchronisation (`core/disc_sync.py`):** Filme, Spuren und Kapitel werden weiterhin in „Video & Audio“ gepflegt und beim Öffnen der Struktur übernommen; IDs, Verbindungen und Positionen bleiben erhalten.
- **Projektdatei:** Der Struktur-Graph wird im `.bdproj` unter `disc_graph` mitgespeichert.
- **Hinweis:** Der Export verwendet in dieser Version weiterhin den Menü-Designer; der Graph ist noch eine Vorschau.
- **Unit-Tests:** `tests/test_node_editor.py` (Synchronisation, Knotenzeilen, Controller mit Undo/Redo, Szene inkl. Verbinden per Ziehen und Sprungmarken, Speichern/Öffnen).

## [1.5.0] - 2026-09-28

### Node-basiertes Disc-Modell (Stufe 1, Teil 1): Datenmodell & Export-Adapter

Grundlage für den neuen Node-Editor (siehe `KONZEPT_UND_DESIGN_NODE_AUTHORING.md`). Noch nicht an Oberfläche oder Export angeschlossen; die App verhält sich unverändert.

- **Datenmodell (`core/disc_model.py`):** Qt-freies Modell aus Start-, Film- und Menü-Knoten mit stabilen IDs. Navigations-Buttons (mit Ausgang) und Inhalts-Buttons (Kapitel, Tonspur, Untertitel, Untertitel aus), Layout-Regel pro Menü mit Positions-Überschreibungen, JSON-Speicherung.
- **Verbindungsregeln (`core/disc_rules.py`):** Stufe-1-Regeln für Start, Film-Ende und Buttons; Stufe-2-Verbindungen werden als „gesperrt, folgt später“ gemeldet. Automatische Beschriftung von Inhalts-Buttons aus den Film-Daten.
- **Export-Adapter (`core/disc_adapter.py`):** Übersetzt den Graphen in `ProjectState` und `pages_specs` für die unveränderte HDMV-Pipeline; Hauptmenü = Seite 0, weitere Menüs lückenlos per Breitensuche.
- **Referenz-Umwandlung (`core/disc_migration.py`):** Überführt bisherige Projekte in einen Graphen und dient als Prüfwerkzeug für den Adapter.
- **Unit-Tests (`tests/test_disc_graph.py`):** Abnahmetest mit 13 Projektvarianten (identische Menüseiten wie bisher), Verbindungsregeln, Adapter-Fehler, Serialisierung.

## [1.4.1] - 2026-09-28

### Kapitelsprünge aus dem Kapitelmenü korrigiert (2D & 3D)

- **Kapitelmarken um eins verschoben behoben (`modules/igs/layout.py`, `modules/menu_author.py`):**
  - `PlayPLatPM` erwartet den 0-basierten PlayListMark-Index; bisher sprang „Kapitel 1“ auf Marke 1 (= zweites Kapitel), der letzte Kapitel-Button zeigte ins Leere.
  - Kapitel-Buttons werden beim Export jetzt über ihren Zeitstempel den Marken zugeordnet, die tsMuxeR tatsächlich in die Film-Playlist geschrieben hat (neuer Leser `modules/mpls/mpls_reader.py`). Funktioniert auch bei manuell eingetragenen Kapiteln ohne `00:00:00.000`. Fallback ohne Playlist: Kapitel *n* → Marke *n − 1*.
- **3D-Umschaltung beim Kapitelsprung (`modules/bdmv/movie_object_generator.py`):**
  - Kapitel-Buttons von 3D-Titeln springen per `JumpObject` in ein eigenes Kapitel-Einstiegsobjekt: `SetOutputMode(1)`, `PlayPLatPM`, `SetOutputMode(0)`, `JumpObject(1)`. Bisher startete ein 3D-Film über das Kapitelmenü nur in 2D.
  - Discs ohne 3D-Kapitelmenü bleiben byte-identisch zu 1.4.0.
- **Unit-Tests:** `tests/test_chapter_jumps.py` (Markenindex, MPLS-Leser, Zuordnung, 3D-Einstiegsobjekte).

## [1.4.0] - 2026-09-27

### 🎉 Meilenstein: Volle 3D-Blu-ray-Unterstützung mit interaktivem Menü auf Hardware-Playern!

- **Verifizierter Hardware-Erfolg:**
  - 3D Stereoskopische Blu-rays (MVC Profile 5.0) mit voll interaktiven HDMV-Menüs, Button-Navigation und dynamischer HDMI 3D-Umschaltung wurden erfolgreich auf physischen Standalone-Hardwareplayern und 3D-Fernsehern getestet und verifiziert!
- **Das 1.4.0 Gesamtpaket:**
  - **Native UDF 2.50 Master Engine (`modules/udf250_writer.py`):** Physikalisches Chunk-Interleaving für stereoskopische MVC/AVC Streams und virtuelle `.ssif`-Dateien ohne externe Tools oder Windows-COM/IMAPI-Einschränkungen.
  - **HDMV Virtual Machine `SetOutputMode` (`modules/bdmv/movie_object_generator.py`):** Standardkonforme HDMI-Umschaltung (`0x31 80 00 0A`) zwischen 2D-Menü und 3D Frame-Packing.
  - **Direkte 3D-Stream-Extraktion (`modules/ssif_tools.py`):** Pure Python ISO-Parsing in < 80 ms ohne Laufwerks-Mounts oder Dateisperren.
  - **Automatische Profil 5.0 Konformität:** Sichere Erkennung und Normalisierung von 24p/23.976p Frameraten und `index.bdmv` AppInfo 3D-Flags.

## [1.3.6] - 2026-09-27

### BD-ROM Profile 5.0 HDMV 3D-Umschaltung (`SetOutputMode`) bei Menü-Discs

- **Dynamische HDMI 3D-Modus-Umschaltung (`modules/bdmv/movie_object_generator.py`):**
  - Implementiert den offiziellen BD-ROM Profile 5.0 HDMV Navigationsbefehl `cmd_set_output_mode(mode=1)` (Opcode `0x31 80 00 0A` mit Immediate-Wert `1`).
  - Löst das Hardware-Player-Verhalten beim Wechsel von einem 2D-Menü zu einem stereoskopischen 3D-Hauptfilm: Standalone-Player bleiben bei einem 2D-Menü standardmäßig im 2D-HDMI-Ausgabemodus; durch die Injektion von `SetOutputMode(1)` im MovieObject direkt vor `PlayPL` wird der HDMI-Transmitter aktiv angewiesen, in den 3D Frame-Packing Modus zu schalten.
  - Nach Filmende schaltet `SetOutputMode(0)` die Ausgabe bei der Rückkehr ins 2D-Menü sauber zurück.
- **Automatische 3D-Titel-Erkennung im Menü-Authoring (`modules/menu_author.py`):**
  - Erkennt automatisch alle 3D-Titel (`video_mvc` oder SSIF-Stream vorhanden) und konfiguriert die MovieObjects für die Titel-Buttons entsprechend.
- **Unit-Tests erweitert:**
  - Neue Tests in `tests/test_hdmv_opcodes.py` und `tests/test_bdmv_navigation.py` für `cmd_set_output_mode` und 3D-MovieObject-Generierung (142/142 Tests erfolgreich).

## [1.3.5] - 2026-09-27

### 3D Blu-ray Discs MIT interaktivem Menü & Nativer UDF 2.50 Master Engine

- **Native Python UDF 2.50 Master Engine (`modules/udf250_writer.py`):**
  - Vollständige, plattformunabhängige UDF 2.50 Disc-Mastering-Engine ohne externe Tools oder Windows-COM-Abhängigkeiten.
  - Löst die BD-ROM Part 3 / Profile 5.0 Anforderung für optische 3D-Hardware-Player: Base AVC (`.m2ts`) und Dependent MVC (`.m2ts`) werden in abwechselnden Chunks physikalisch auf der Disc verschachtelt, während der virtuelle `.ssif`-Stream als zusammenhängender Extent ohne Daten-Duplikation abgebildet wird.
  - Ermöglicht zum ersten Mal vollwertige Multi-Title 3D-Blu-rays **mit interaktiven HDMV-Menüs** und Button-Steuerung für Hardware-Player.
  - Ersetzt Windows `IMAPI2FS` (das keine Extent-Verschachtelung beherrscht) als primäre ISO-Engine.
- **Direkte, lock-freie 3D-Stream-Extraktion (`modules/ssif_tools.py`):**
  - Liest ClipInfos, MPLS-Playlists und Extent-Listen direkt aus dem temporären tsMuxeR-3D-ISO mit reinem Python in unter 80 ms.
  - Vollständiger Verzicht auf anfälliges PowerShell `Mount-DiskImage`, wodurch `[WinError 32]`-Dateisperren und Laufwerksbuchstaben-Konflikte endgültig eliminiert sind.
- **Einbindung in den Export (`gui/tabs/tab_export.py` & `modules/iso_tools.py`):**
  - Automatisches Sammeln aller 3D-Stream-Metadaten während des Muxing-Durchlaufs und direkte Übergabe an den UDF 2.50 Master.
  - Bereinigung temporärer Zwischendateien nach erfolgreicher ISO-Erstellung.
- **Umfassende Testabdeckung (`tests/test_3d_compliance.py`):**
  - Unit-Tests für CRC-16 CCITT, UDF 2.50 Tag-Validierung, Prüfsummen und Extent-Interleaving (alle 140 Unit-Tests bestanden).

## [1.3.4] - 2026-09-27

### Direkt-ISO-Export für No-Menu 3D & UDF 2.50 Interleaving

- **Natives tsMuxeR UDF 2.50 ISO-Mastering für Direktstart / No-Menu:**
  - `gui/tabs/tab_export.py` routet den ISO-Export bei abgewähltem Menü (*Menü aktivieren* deaktiviert) und Einzeltitel direkt über tsMuxeR (`cmd = [tsmuxer_bin, meta_path, iso_target]`).
  - Umgeht den Windows `IMAPI2FS`-Flaschenhals, der 3D-Streams bisher linear ohne Sektor-Verschachtelung geschrieben hat.
  - tsMuxeRs interner `iso_writer` schreibt die Blöcke von Base- (`.264`) und MVC-Stream (`.mvc`) physikalisch verschachtelt auf die Disc (`MAIN_INTERLEAVE_BLOCKSIZE` und `SUB_INTERLEAVE_BLOCKSIZE`), wodurch Standalone-Hardwareplayer und 3D-Fernseher den Film sofort im 3D-Modus abspielen.
  - Deutlich schnellerer Exportprozess bei Single-Title Projekten ohne temporäre BDMV-Verzeichnisse.
- **Unit-Test & Testdateien-Bereinigung:**
  - Neuer Unit-Test `test_direct_3d_iso_mode_detection` in `tests/test_3d_compliance.py`.
  - Arbeitsverzeichnis von temporären Inspektions- und Testskripten bereinigt.

## [1.3.3] - 2026-09-27

### 3D SSIF-Interleaving und Stream-Extraktion

- **Standardkonforme `.ssif`-Generierung für optische 3D-Hardware-Player:**
  - `modules/ssif_tools.py` erzeugt den zwingend für Profil 5.0 Hardware-Player vorgeschriebenen stereoskopischen Interleave-Stream (`.ssif`) über tsMuxeR und platziert ihn im Ordner `BDMV/STREAM/SSIF/` (z. B. `00004.ssif`).
  - Verhindert den automatischen 2D-Fallback von Hardware-Playern bei fehlendem SSIF-Stream.
- **Robuste Windows-Extraktion ohne `[WinError 32]` oder Zugriffsfehler:**
  - Temporäres ISO-Muxing erfolgt im Zielverzeichnis zur Umgehung von Windows-Temp-Sicherheitsrestriktionen.
  - Native Windows-Stream-Übertragung (`Copy-Stream`) neutralisiert optische Read-Only-Attribute und verhindert Dateisperren.
  - Atomare Aushänge- und Löschschleife stellt sicher, dass keine System-Locks zurückbleiben.

## [1.3.2] - 2026-09-27

### Volle 3D MVC & SSIF Unterstützung für Standalone Hardware-Player (BD-ROM Profile 5.0)

- **Voraussetzungen für 3D auf Hardware-Playern:**
  - Vier Punkte müssen für optische Hardware-Player erfüllt sein:
    1. Paare von Transport-Streams: Base AVC Clip (z. B. `00000.m2ts`) + Dependent MVC Clip (z. B. `00001.m2ts`).
    2. Der Ordner `BDMV/STREAM/SSIF/` mit korrespondierenden `.ssif`-Dateien (z. B. `00000.ssif`).
    3. `index.bdmv` AppInfo Byte 0 muss auf `0x20` gesetzt sein (`SS_content_exist_flag = 1`), um dem Player die 3D-Fähigkeit der Disc zu signalisieren.
    4. Playlists müssen sowohl den PlayItem-Clip als auch im SubPath Typ 8 (MVC) den korrekten Dependent-Clip referenzieren.
- **Multi-Title 3D MVC Muxing & Playlist-Patching in `tab_export.py`:**
  - Zusätzliche 3D-Titel reservieren nun automatisch zwei aufeinanderfolgende Clip-IDs (z. B. `00004` für AVC-Basis und `00005` für MVC-3D).
  - Sowohl Base- als auch MVC-Streams (`.m2ts`) und ClipInfos (`.clpi`) werden kopiert.
  - In der Playlist (`.mpls`) werden sowohl `00000M2TS` -> `{base_clip}M2TS` als auch `00001M2TS` -> `{mvc_clip}M2TS` im SubPath Typ 8 fehlerfrei gepatcht.
- **Stereoscopic Interleaved Stream (SSIF) Generator (`modules/ssif_tools.py`):**
  - Neues Modul erzeugt über tsMuxeRs UDF-Engine temporär das standardkonforme Interleave-Image und stellt den echten `.ssif`-Stream in `BDMV/STREAM/SSIF/` bereit.
- **Kollisionsschutz für Menüs bei 3D-Hauptfilmen:**
  - `inject_menu_into_bdmv()` erkennt, wenn Titel 1 ein 3D-Film ist, und verschiebt die Menü-Clips dynamisch auf `00002` (Hintergrund) und `00003` (IGS), sodass der MVC-Stream von Titel 1 (`00001.m2ts`) unberührt bleibt.
- **`index.bdmv` 3D-Signalisierung:**
  - `build_index_bdmv()` setzt bei vorhandenen 3D-Titeln automatisch `SS_content_exist_flag = 1` (`0x20`) und Byte 1 auf `0x61`.

## [1.3.1] - 2026-09-27

### Intelligente 25PsF / Fake-Interlaced Erkennung & Nativ-25p Unterstützung

- **Automatische 1080i / 25PsF Bitstream-Erkennung in `VideoTools`:**
  - `probe_video_details()` analysiert bei H.264-Videoströmen (`.264`, `.h264`, `.avc`) nun direkt das SPS (Sequence Parameter Set) und x264 SEI Optionen:
    - Ist `frame_mbs_only_flag == 0` oder `interlaced=fake` vorhanden, wird der Stream automatisch als standardkonformes **1080i / 25PsF** (`is_interlaced = True`, `is_psf = True`) eingestuft.
  - Verhindert den bisherigen Fehlalarm beim Import von 25PsF-Dateien (`UNOFFICIAL_1080P25`), da FFprobes Stream-Ebene bei progressivem Bildinhalt fälschlicherweise `field_order: progressive` meldet.
- **Koexistenz von Nativ 1080p25 und 1080i 25PsF:**
  - `fix_1080i_stream_attributes()` patcht `0x63` nicht mehr pauschal zu `0x43`, sodass moderne native 25p-Streams verlustfrei als Vollbild erhalten bleiben.
  - Das Menü-Playlist-Modul übernimmt das Video-Format nun dynamisch aus der gemuxten `00001.clpi`, sodass CLPI und MPLS immer synchron bleiben.

## [1.3.0] - 2026-09-26

### Durchbruch: Menüs laufen auf Hardware-Playern

- **Erkenntnis:** HDMV-Menüs als **Out-of-Mux SubPaths (Typ 3)** sind zulässig; Hardware-Player lehnen Out-of-Mux keineswegs ab.
- Das Scheitern früherer OpenBDAuth-Menüs auf Hardware lag an **mehreren Parameter-Abweichungen** von der BD-ROM-Spezifikation:

- **Die 6 Behobenen Hardware-Fehler:**
  1. **SubPlayItem Dauer (Buffer Underflow Ursache behoben):**
     - Bisher wurde `out_time` auf die volle Menüdauer (z. B. 30 Sekunden) gesetzt. Da der IGS-SubClip jedoch nur ~18 KB Daten für ein Display-Set enthält, lief der Hardware-Puffer nach ~40 ms leer (*EOF / Buffer Underflow*), was zum Abbruch führte.
     - **Fix:** In `build_menu_mpls()` wird die SubPlayItem-Dauer nun standardkonform auf **exakt 1 Frame** im 45-kHz-Takt begrenzt (`frame_ticks = int(45000.0 / fps)`, z. B. 1876 Ticks bei 23.976 fps).
  2. **`sync_start_pts = 0` (Asynchroner Preload):**
     - Bisher wurde fälschlicherweise `pts_in` (27000000) übergeben. Nach BD-ROM Part 3 muss `sync_start_pts` für asynchrone Preload-Menüs (Typ 3) immer `0` sein.
  3. **`is_repeat = 0` (Kein SubPath Looping):**
     - `is_repeat` im SubPath-Header wurde von `1` auf `0` korrigiert. Die Menü-Grafik wird einmalig in den Decoder geladen; nur das Hintergrundvideo der Playlist loopt.
  4. **CLPI `application_type = 5`:**
     - In `build_igs_clpi()` wurde `application_type` von `6` auf `5` (*SubTS for preloaded stream*) korrigiert.
  5. **CLPI SequenceInfo Dauer synchronisiert:**
     - `presentation_end_45k` in `SequenceInfo` läuft nun passend zum SubPlayItem exakt 1 Frame (`pts_start_45k + frame_ticks`).
  6. **CLPI CPI (EP_map) bereinigt:**
     - Preload-SubClips besitzen nach BD-ROM Spezifikation keine EP_map (`cpi_length = 0`). Die bisherige künstliche EP_map entfällt vollständig.
  7. **🚨 Fataler Hardware-Absturz behoben: `JumpTitle(0)` in FirstPlayback (`MovieObject 0`):**
     - Bei Tests auf modernen UHD-Standalone-Playern wurde der Bildschirm für wenige Sekunden schwarz und der Player sprang ins Home-Menü zurück.
     - **Ursache:** `MovieObject 0` (FirstPlayback) führte `JumpTitle(0)` aus. In der BD-ROM Spezifikation sind Titel in `index.bdmv` jedoch 1-basiert (1 bis N). Titel 0 existiert nicht! VLC toleriert dies tolerant, moderne Hardware-Player (Panasonic/Sony) erkennen den ungültigen Titel-Sprung als fatalen Navigationsfehler und stoppen sofort (`stop_playback()`).
     - **Fix:** In `modules/bdmv/movie_object_generator.py` startet `MovieObject 0` (FirstPlayback) nun direkt die Menü-Playlist mit `PlayPL(0)` und loopt mit `JumpObject(1)`. Auch die Filmtitel springen nach Ablauf mit `JumpObject(1)` direkt in das TopMenu-Objekt zurück.
  8. **CLPI `pcr_pid` Mismatch behoben (`0x1001` vs. `0x1400`):**
     - In `00002.clpi` war `pcr_pid` in `SequenceInfo` auf `0x1001` gesetzt, während der M2TS PMT den PCR auf PID `0x1400` deklarierte.
     - **Fix:** In `modules/mpls/clpi_generator.py` wurde der Standard-PCR-PID auf `0x1400` harmonisiert.
  9. **🚨 Bitgenaue Rekonstruktion von `00002.clpi` (Fehlende 144 Bytes & ClipInfo-Korruption behoben):**
     - Beim Test von `NEUER_TEST.iso` auf dem UHD-Player brach die Wiedergabe weiterhin nach 2–3 Sekunden ab.
     - Ein Byte-Vergleich unserer `00002.clpi` (148 Bytes) mit dem Aufbau nach BD-ROM Part 3 (292 Bytes) zeigte die Ursache im CLPI-Parser des Standalone-Players:
       * **`ClipInfo` war um 128 Bytes zu kurz (48 statt 176 Bytes):** Es fehlten 96 Bytes der von BD-ROM Part 3 Section 5.4.2 vorgeschriebenen 128 Reserved-Bytes sowie der gesamte 32-Byte `ts_type_info_block` (`0x001E`, `0x80`, `"HDMV"`, 25 Bytes Reserved).
       * **`ProgramInfo` Stream-Attribute waren unvollständig (5 statt 21 Bytes):** Es fehlten 12 Bytes ISRC (`b"000000000000"`) und 4 Bytes Padding. Der Hardware-Demuxer las beim Einlesen der Spur über die Daten hinaus und warf einen fatalen Stream-Fehler.
     - **Fix:** `build_igs_clpi()` in `modules/mpls/clpi_generator.py` wurde vollständig aktualisiert und erzeugt nun die vollständige, 292 Bytes lange Struktur nach BD-ROM Part 3.

  10. **🚨 Der 'Rauchende Colt': Fataler `playback_type = 2` (Random) in Menü-Playlist `00000.mpls` behoben:**
      - Beim Test von `TEST3.iso` brach der Standalone-Player nach wie vor nach 2–3 Sekunden ab.
      - Die detaillierte Analyse der BD-ROM Spezifikation (Part 3, Section 5.3.2) deckte die exakte Ursache auf:
        - In `modules/mpls/mpls_generator.py` war seit Meilenstein 3 hartcodiert: `app_info.append(2) # playback_type = 2 (Repeat / Looping für Menüs)`.
        - In der BD-ROM Spezifikation bedeutet `playback_type = 2` jedoch **Random Playback** (Zufallswiedergabe)!
        - Die Spezifikation formuliert hierfür harte Ausschlusskriterien:
          * *"When PlayList_playback_type is 0x02 (Random) or 0x03 (Shuffle), the PlayList shall not contain any SubPath."*
          * *"When PlayList_playback_type is 0x02 or 0x03, the PlayList shall contain two or more PlayItems."*
          * *"If a PlayList violates these constraints, a player shall not execute playback of the PlayList and shall terminate playback."*
        - `00000.mpls` verletzte beide Regeln gleichzeitig (nur 1 PlayItem und ein SubPath Typ 3 vorhanden). Strenge Hardware-Player (UHD-Player) brachen die Wiedergabe daher normgemäß sofort ab!
      - **Fix:** In `modules/mpls/mpls_generator.py` wurde `playback_type` standardkonform auf `1` (Sequential Playback) gesetzt (Looping wird im HDMV-System über `MovieObject 1` / `JumpObject(1)` gesteuert). Zudem wurde `PlayItem_random_access_flag` auf `0` gesetzt und FirstPlayback in `index.bdmv` auf `is_interactive=False` (`playback_type = 0`) angepasst.


## [1.2.5] - 2026-09-17


### Behoben — Standardkonformer SubPath-Typ 3 (Menüs) & Dynamische PTS-Synchronisation

- **Standardkonformer SubPath-Typ 3 für IGS Menüs (`modules/mpls/mpls_generator.py`):**
  - In `00000.mpls` wurde der `subpath_type` auf den offiziellen BD-ROM Part 3 Standardwert `3` (*"Interactive Graphics presentation path for menus"*) gesetzt.
  - Typ 7 bezeichnet laut Spezifikation die nachträgliche Ersetzung einer bereits im Hauptfilm vorhandenen In-Mux IG-Spur; Typ 3 ist der originäre asynchrone Preload-Menü-Pfad für Out-of-Mux Interactive Graphics.
- **Dynamische PTS-Synchronisation zwischen Video, IGS und Playlist (`modules/menu_author.py`, `modules/mpls/clpi_generator.py`, `modules/mpls/mpls_generator.py`):**
  - Bisher war in `00000.mpls` ein statischer Start-PTS von `27.000.000` (600,000 s) hinterlegt, während das von tsMuxeR gemuxte Hintergrundvideo (`00001.clpi`) durch B-Frame-Verzögerung erst bei `27.001.800` (600,040 s) begann. Hardware-Player fanden keinen Frame vor `27.001.800` und brachen ab.
  - `get_clpi_stc_range()` liest nun die tatsächliche `presentation_start_time` und `presentation_end_time` direkt aus `00001.clpi` aus.
  - `00000.mpls` (PlayItem und SubPlayItem `in_time`, Mark 0, `sync_start_pts`), `00002.clpi` (SequenceInfo) sowie der IGS-PES-Stream und TS-PCR in `00002.m2ts` werden auf denselben exakten Mikrosekunden-PTS synchronisiert.

## [1.2.4] - 2026-09-17

### Behoben — Standardkonforme Out-of-Mux Preload SubPaths & HDMV FirstPlayback Weiche

- **Standardkonformer SubPath-Typ 7 für IGS Menü-Preload (`modules/mpls/mpls_generator.py`):**
  - In `00000.mpls` wurde der `subpath_type` von `2` (Diashow-Audio) auf den offiziellen BD-ROM Part 3 Standardwert `7` (Interactive Graphics Presentation / Out-of-Mux Preload) korrigiert.
  - Ermöglicht Hardware-Playern (wie Panasonic DMP-BDT111), den 18-KB SubClip vorab ins Graphics Buffer RAM zu laden, anstatt ihn fälschlicherweise als Slideshow-Audiospur zu interpretieren.
- **Offizielle 14-Byte AppInfoPlayList (`modules/mpls/mpls_generator.py`):**
  - Überflüssige 10 Nullbytes in `AppInfoPlayList` entfernt, sodass sowohl Menü- als auch Film-Playlists exakt die spezifikationskonforme Länge von 14 Bytes (0x0E) aufweisen (identisch zu tsMuxeR).
- **Saubere FirstPlayback -> TopMenu Weiche in HDMV (`modules/bdmv/index_generator.py`, `modules/bdmv/movie_object_generator.py`):**
  - `MovieObject 0` fungiert nun als Bootstrap-Objekt für FirstPlayback und wechselt per `JumpTitle(0)` sauber in das interaktive TopMenu (`MovieObject 1`).
  - `MovieObject 1` betreibt die Menü-Playlist (`PlayPL(0)`).
  - Verhindert, dass der Player im nicht-interaktiven FirstPlayback-Zustand steckenbleibt.

## [1.2.3] - 2026-09-17

### Behoben — BD-ROM Part 3 Menü-Standardkonformität für Hardware-Player (Panasonic & Sony)

- **Standardkonforme 1080i25 / PsF Video-Attribute in Menü-Playlists (`modules/mpls/mpls_generator.py`):**
  - `fps_to_bd_video_attr()` ordnet 25 fps und 50i nun automatisch dem standardkonformen BD-ROM Video-Format `4` (1080i) mit Frame Rate Code `3` (25 fps) zu (`0x43`).
  - Verhindert das unzulässige Byte `0x63` (1080p25 existiert im BD-ROM Standard nicht), welches von strengen Hardware-Playern (Panasonic UniPhier SoC, Sony) sofort als inkompatibel verworfen wurde.
- **Automatisches PsF (`fake-interlaced=1`) für Menü-Hintergrundvideo (`modules/menu_author.py`):**
  - Beim Rendern von Menü-Standbildern bei 25 fps / 50i übergibt FFmpeg an libx264 nun `-x264-params bluray-compat=1:fake-interlaced=1` und passende GOP-Größe (25).
  - Erzeugt einen standardkonformen 1080i25 / PsF Elementary Stream ohne Qualitätsverlust.
- **Resume-Intention Flag (`0x8000`) in MovieObject (`modules/bdmv/movie_object_generator.py`):**
  - Alle generierten MovieObjects erhalten nun das nach BD-ROM Part 3 / tsMuxeR erforderliche Flag `0x8000` (`resume_intention_flag = 1`), wodurch Hardware-Player FirstPlayback und Menü-Rücksprünge korrekt ausführen.
- **Universelles AppInfo in Master-Index (`modules/bdmv/index_generator.py`):**
  - `app_info` in `index.bdmv` wird nun nach tsMuxeR-Standard mit 34 Nullbytes initialisiert, anstatt fest auf 1080p24 gelockt zu sein.
- **Erweiterter Stream-Attribut-Patch (`modules/mux_engine.py`):**
  - `fix_1080i_stream_attributes()` fängt nun auch versehentliche `\x1b\x63` (1080p25) Streams ab und korrigiert sie atomar auf `\x1b\x43` (1080i25).

## [1.2.2] - 2026-09-16

### Behoben — Framerate-Normalisierung für tsMuxeR bei 1080i (Verdopplungs-Bug behoben)

- **Korrektur der tsMuxeR-Framerate bei 1080i / 25PsF (`core/meta_builder.py`):**
  - tsMuxeR erwartet bei H.264 Elementary Streams (`.264`) als `fps=` stets die **Vollbildrate** (Frame Rate, z. B. `fps=25`), nicht die Halbbildrate (`fps=50`).
  - Wenn in v1.2.1 `fps=50` übergeben wurde, interpretierte tsMuxeR dies als Anweisung, das Timing von 25 auf 50 fps zu beschleunigen (`Change H.264 fps from 25 to 50`). Dies führte zu einer 200%igen Wiedergabegeschwindigkeit (Film dauerte 9 statt 18 Minuten) und massiver Audio-Desynchronisation.
  - `_get_tsmuxer_fps_str()` liefert für 1080i nun stets die saubere Vollbildrate (`25` bzw. `29.97`) und normalisiert versehentlich als 50/59.94 übergebene Halbbildraten automatisch.
  - Bild und Ton laufen wieder synchron in normaler Geschwindigkeit.
  - Das Seeking/Springen in der Timeline funktioniert weiterhin (dank Closed-GOP `open-gop=0` im Encoder).
- **BD-ROM Part 3 Stream-Attribut-Patcher (`modules/mux_engine.py`):**
  - Der automatische Patch von Header-Attributen auf offizielle Normwerte (`0x43` für 1080i25) bleibt aktiv und sichert die Kompatibilität auf Standalone-Hardwareplayern.

## [1.2.1] - 2026-09-16

### Behoben — 1080i / 25PsF tsMuxeR Timing & BD-ROM Header Compliance

Diese Version behebt kritische Timing- und Synchronisationsprobleme bei 1080i50 / 25PsF Material:

- **tsMuxeR Halbbildraten-Korrektur bei 1080i (`core/meta_builder.py`):**
  - tsMuxeR interpretiert den Parameter `fps=` bei Interlaced-Streams (`1080i`) als Halbbildrate (Field Rate). Wenn bisher `fps=25` übergeben wurde, skalierte tsMuxeR die Bilddauer auf 25 Halbbilder/s (= 12,5 Vollbilder/s), was zu einer verdoppelten Timeline (z. B. 28:09 statt 14:04 Min), doppelter Zeitzählung, 50% Zeitlupe und einfrierendem Seeking führte.
  - `MetaBuilder` erkennt 1080i-Streams nun zuverlässig und übergibt an tsMuxeR automatisch die Halbbildrate (`fps=50` für 25PsF/50i bzw. `fps=59.94` / `fps=60` für 29.97/30PsF).
  - Progressive Streams (1080p23.976, 1080p24, 720p50 etc.) bleiben unberührt.
- **Automatischer BD-ROM Part 3 Videoattribut-Patch (`modules/mux_engine.py`, `gui/tabs/tab_export.py`):**
  - tsMuxeR schreibt bei `fps=50` das Attribut-Byte `0x46` (1080i @ 50fps) in die Header von `CLPI` und `MPLS`. Laut BD-ROM Part 3 Standard ist 1080i jedoch ausschließlich als `0x43` (1080i @ 25fps) definiert (`0x46` ist nur für 720p50 zulässig).
  - Neue Funktion `fix_1080i_stream_attributes()` durchsucht nach dem Muxen alle `.clpi`- und `.mpls`-Dateien (inkl. `BACKUP/`) und patcht `0x46` auf `0x43` (bzw. `0x47` auf `0x44`).
  - Nötig für strenge Hardware-Player (z. B. ältere Panasonic- oder 4K-UHD-Player).
- **Neue Test-Suite (`tests/test_interlaced_1080i.py`):**
  - Umfassende Tests für die tsMuxeR-Framerate-Generierung bei 1080i/25PsF, 1080i/29.97PsF und progressiven Formaten sowie Verifikation des Header-Patchers.

## [1.2.0] - 2026-09-16

### Hinzugefügt — Sauberes Export-Dateimanagement & ISO-Bereinigung

Diese Version optimiert die Dateiablage und beseitigt die Speicherplatzverdopplung bei ISO-Exports:

- **Automatisches Bereinigen temporärer BDMV- und CERTIFICATE-Ordner nach ISO-Erstellung (`gui/tabs/tab_export.py`):**
  - Bei der Erstellung einer `.iso`-Datei wurden bisher der rohe `BDMV`- und `CERTIFICATE`-Ordner sowie `job.meta` dauerhaft im Zielverzeichnis belassen, was bis zu 50 GB doppelten Speicherplatz verbrauchte.
  - OpenBDAuth bereinigt diese temporären Ordner nun nach erfolgreicher Erstellung des UDF 2.50 ISO-Images automatisch (`shutil.rmtree`).
  - Neue Checkbox im Export-Tab: *„Temporäre BDMV-Dateien nach ISO-Erstellung bereinigen“* (standardmäßig aktiv). Bei reinem Ordner-Export bleibt die BDMV-Struktur selbstverständlich erhalten.
- **Elegante Untertitel-Ablage (`core/meta_builder.py`):**
  - Automatisch aus `.srt` konvertierte `.sup`-Dateien (BD-ROM PGS) werden nicht mehr im Export-/ISO-Verzeichnis abgelegt, sondern direkt im Verzeichnis der originalen `.srt`-Datei (z. B. `mein_film_deu.sup` neben `mein_film.srt`).
  - Dies hält den Exportordner sauber und ermöglicht die direkte Wiederverwendung der generierten `.sup`-Dateien.
- **Bereinigung von `job.meta` (`gui/tabs/tab_export.py`):**
  - Die temporäre tsMuxeR-Steuerdatei `job.meta` wird nach Abschluss des Muxens bzw. der ISO-Erstellung automatisch entfernt, sodass im Ausgabeordner keine Hilfsdatei zurückbleibt.
- **Neue Test-Suite (`tests/test_export_cleanup.py`):**
  - 3 neue Tests zur Verifikation der `.sup`-Ablage im Quellordner, der Namensbildung und der Bereinigungslogik nach ISO-Erstellung. Alle 121 Tests grün.

## [1.1.9] - 2026-09-16

### Hinzugefügt — Video Compliance & Format Pre-Flight Checker (Non-blocking)

Diese Version führt eine intelligente, automatisierte Vorprüfung von importierten Videodateien ein. Sie schützt vor typischen Hardware-Player-Fallstricken (wie vertikal gestreckten Bildern oder Rucklern), bleibt jedoch für den Benutzer **vollständig nicht-blockierend** (die Warnungen können jederzeit mit einem Klick ignoriert werden).

- **Automatischer Pre-Flight Checker (`modules/video_tools.py`):**
  - **Erkennung anamorpher Seitenverhältnisse (`ANAMORPHIC_ASPECT_RATIO`):** Erkennt, wenn eine 1920×1080-Datei im Header als 2.39:1 / 2.35:1 oder mit SAR != 1:1 markiert ist. Erklärt dem Nutzer, dass Standalone-Player solche Flags ignorieren und das Bild vertikal auf 16:9 strecken (Empfehlung: Film mit Hardcoded Letterbox anliefern).
  - **Erkennung inoffizieller Bildraten (`UNOFFICIAL_1080P25`, `UNOFFICIAL_1080P30`):** Erkennt 1080p25 und 1080p30 Progressive-Streams. Weist darauf hin, dass BD-ROM Part 3 bei 1080 nur 24p oder 1080i50 / 1080i60 erlaubt und ältere Player Ruckeln zeigen können (Empfehlung: 1080i50/PsF für alte Hardware; Ignorieren für moderne UHD-Player).
  - **Erkennung unzulässiger Auflösungen (`NON_STANDARD_RESOLUTION`):** Erkennt gecroppte Streams wie 1920×800 oder 2560×1080.
- **Interaktiver Compliance Warning Dialog (`gui/widgets/compliance_dialog.py`):**
  - Elegantes Dialogfenster im Dark-Cinema-Design, das für jede Warnung das Problem, die Auswirkung auf Hardware-Playern und die empfohlene Lösung darstellt.
  - Enthält die Schaltflächen `[Trotzdem verwenden (Ignorieren)]` und `[Schließen]`.
- **Status-Badge in der Titelliste (`gui/tabs/tab_titles.py`):**
  - Zeigt neben der FPS-Anzeige ein klares Status-Badge: Grün (`✅ Blu-ray Standard`) oder Amber (`⚠️ X Kompatibilitätshinweis(e) [Details]`), welches den Dialog jederzeit per Klick öffnet.
- **Export Pre-Flight Check (`gui/tabs/tab_export.py`):**
  - Falls vor dem Muxen noch unbestätigte Warnungen vorliegen, fragt eine kurze Bestätigungsbox: *„Folgende Videodateien weichen von den offiziellen Blu-ray-Spezifikationen ab (...). Möchtest du den Export trotzdem starten? [Trotzdem exportieren] [Abbrechen]“*. Bei Klick auf *Trotzdem exportieren* startet der Vorgang ohne jede Verzögerung.
- **Neue Test-Suite (`tests/test_video_compliance.py`):**
  - 10 umfassende Unit-Tests für alle Erkennungsfälle (25p, 30p, SAR/DAR, Auflösungen und Multi-Title-Aggregation). Alle 118 Projekt-Tests grün.

## [1.1.8] - 2026-09-16

### Behoben — VLC-Crash Fix, MPLS-Header & CLPI SequenceInfo Hardware-Kompatibilität

Diese Version behebt den in 1.1.6 fälschlicherweise eingeführten Offset-Verschub im MPLS-Header (der zum sofortigen Absturz von VLC / `libbluray` sowie Hardware-Player-Ausfällen führte) und korrigiert die tatsächliche Ursache der Hardware-Wiedergabeabbrüche in `SequenceInfo` der `.clpi`-Dateien.

- **VLC-Crash Fix — Wiederherstellung des 40-Byte MPLS-Headers (`modules/mpls/mpls_generator.py`):**
  - **Korrektur:** In v1.1.6 wurde irrtümlich ein `AppInfoPlayList_start_address`-Feld an Byte 8 eingefügt, wodurch alle nachfolgenden Tabellen um 4 Bytes verschoben wurden (`ExtensionData_start_address` zeigte auf Datenmüll in den Chapter-Marks, was VLC mit Segfault abstürzen ließ). Nach BD-ROM Part 3 Section 5.3.2/5.3.3 beginnt `AppInfoPlayList` statisch bei Byte 40. Der Header enthält nur 3 Adressen (`PlayList_start_address`, `PlayListMark_start_address`, `ExtensionData_start_address` gefolgt von 20 Bytes Nullen). Dies wurde in `build_menu_mpls()` und `build_movie_mpls()` wiederhergestellt.
- **Echte Hardware-Ursache behoben — CLPI `SequenceInfo` Struktur (`modules/mpls/clpi_generator.py`):**
  - **1 Byte Reserved:** Nach BD-ROM Part 3 Section 5.4.4 beginnt `SequenceInfo` mit 4B Länge, 1B Reserved (=0) und 1B `num_atc_sequences`. Das fehlende Reserved-Byte führte dazu, dass Hardware-Decoder (Panasonic/Sony) `num_atc_sequences = 0` lasen und die Disc abbrachen.
  - **1 Byte `offset_stc_id`:** Vor `pcr_pid` wurde das 1-Byte-Feld `offset_stc_id` (=0) ergänzt.
  - **45-kHz Zeitbasis:** Zeitstempel in `SequenceInfo` laufen synchron zur Playlist im 45-kHz-Takt (27.000.000 für 10 Min).
  - **PCR-PID Konsistenz:** `pcr_pid` in PMT (`m2ts_writer.py`) und CLPI (`clpi_generator.py`) wieder konsistent auf `0x1400` gesetzt, da der IGS-Stream tatsächlich PCR-Pakete auf 0x1400 sendet.
- **Tests aktualisiert (`tests/test_mpls_clpi_generator.py`):**
  - Prüfung der 3 MPLS-Header-Offsets und der SequenceInfo-Byte-Offsets. Alle 108 Tests grün.

## [1.1.7] - 2026-09-15

### Behoben — Durchgängige Framerate-Konsistenz (MPLS, CLPI, IGS, PGS)

Alle Disc-Komponenten nutzen jetzt die tatsächliche Projekt-Framerate statt hardcodierter 23.976fps-Konstanten. Bei einem 25fps-Film ließ sich bisher im Export-Log erkennen: „Decoding PGS stream: Frame rate: 24" — Menü-Video, MPLS-Stream-Attribute, ICS und PGS-Untertitel waren alle von der Filmrate abweichend. Ein Framerate-Wechsel beim Übergang Menü→Film kann auf strikten Hardware-Playern zu kurzen Schwarzblenden führen.

- **`fps_to_bd_video_attr(fps)` (`modules/mpls/mpls_generator.py`):**
  - Neue Hilfsfunktion konvertiert float-FPS in das kombinierte BD-ROM Video-Attributbyte: High-Nibble = video_format (jetzt korrekt `6` = 1080p statt bisher `4` = 1080i!), Low-Nibble = frame_rate_code (1=23.976, 2=24, 3=25, 4=29.97, 6=50, 7=59.94).
  - Lookup mit ±0.1-Toleranz; Fallback auf 23.976.
  - `build_menu_mpls()`, `write_menu_mpls_file()` und `build_movie_mpls()` haben jetzt alle einen `fps: float = 23.976`-Parameter und nutzen die neue Funktion für das STN-Table Videoattribut-Byte.

- **`fps_to_bd_video_attr` in CLPI (`modules/mpls/clpi_generator.py`):**
  - `build_video_clpi()` und `write_video_clpi_file()` haben jetzt `fps`-Parameter.
  - ProgramInfo-Stream-Attributbyte des Hintergrundvideo-Clips wird ebenfalls dynamisch gesetzt.

- **`fps_to_pgs_rate_byte(fps)` + fps-Parameter (`modules/subtitles/srt_to_sup.py`):**
  - Neue Hilfsfunktion mappt float-FPS auf BD-ROM PGS PCS frame_rate_type-Bytes: `0x10`=23.976, `0x20`=24, `0x30`=25, `0x40`=29.97, `0x60`=50, `0x70`=59.94.
  - `build_sup_cue_bytes()` und `convert_srt_to_sup()` haben `fps`-Parameter; PCS-Byte für Epoch-Start und Clear-Segment wird jetzt korrekt gesetzt.
  - `meta_builder.py` übergab `fps` bereits — dieses Argument wird nun auch tatsächlich genutzt.

- **ICS Frame-Rate-Code (`modules/menu_author.py`):**
  - `fps_to_igs_rate_code(fps)` mappt float-FPS auf den BD-ROM IGS ICS Frame-Rate-Code (`FPS_25 = 3` etc.).
  - `generate_menu_subclip()` hat `fps`-Parameter und instantiiert `IGSCompiler(fps_code=fps_to_igs_rate_code(fps))`.

- **fps-Durchreichung (`modules/menu_author.py`):**
  - `inject_menu_into_bdmv()` reicht `fps` jetzt durch an: `generate_menu_subclip()`, `write_menu_mpls_file()` und `write_video_clpi_file()` (Fallback-Pfad).
  - `tab_export.py` übergibt bereits `fps=self.project.fps` — damit nutzt die ganze Kette die Projekt-Framerate.

- **Test-Suite:** 76 Core-Unit-Tests grün.

## [1.1.6] - 2026-09-15

### Behoben — Hardware-Player Kompatibilität (Sony UB700, Panasonic DMP-BDT111EG)

Diese Version behebt drei kritische Spec-Verstöße, die dazu führten, dass die Menü-Playlist auf allen realen Blu-ray-Playern (Sony, Panasonic) mit schwarzem Screen und sofortigem Rückfall ins Player-Menü abbrach — obwohl VLC die Disc fehlerfrei abspielte, da VLC bei Header-Parsing toleranter ist als Hardware-Decoder.

- **Bug 1 — MPLS-Header: Falscher Offset-Aufbau (`modules/mpls/mpls_generator.py`):**
  - **Ursache:** Der 40-Byte MPLS-Header nach BD-ROM Part 3, Section 5.3.3 enthält 4 Adress-Felder: `AppInfoPlayList_start_address`, `PlayList_start_address`, `PlayListMark_start_address` und `ExtensionData_start_address`. Der Code schrieb bisher nur 3 Felder und ließ `AppInfoPlayList_start_address` (= 40, direkt nach dem Header) komplett weg. Dadurch lasen Hardware-Parser alle folgenden Strukturen um exakt **4 Bytes** falsch verschoben — was einer vollständig korrupten Disc aus Sicht des Decoders entspricht.
  - **Fix:** Header-Ausgabe von `struct.pack(">III", ...)` auf `struct.pack(">IIII", app_info_offset, playlist_offset, mark_offset, 0)` korrigiert. Reserved-Padding von 20 auf 16 Bytes angepasst (Gesamtgröße bleibt exakt 40 Bytes). Fix gilt für sowohl Menü-Playlists (`build_menu_mpls`) als auch Film-Playlists (`build_movie_mpls`).

- **Bug 2 — IGS-SubClip CLPI: Falscher `pcr_pid` im SequenceInfo (`modules/mpls/clpi_generator.py`):**
  - **Ursache:** Ein reiner IGS-SubTS (`application_type = 6`, SubPath Typ 2) enthält per Spezifikation **keine PCR-Pakete**. Der `pcr_pid` im `SequenceInfo` war trotzdem auf `0x1400` (den IGS-PID selbst) gesetzt. Sony- und Panasonic-Hardware-Decoder warten nach diesem Eintrag auf ein PCR-Paket auf PID `0x1400` — das nie kommt — und brechen den Stream-Start nach Timeout ab.
  - **Fix:** `pcr_pid` im IGS-SubClip CLPI auf `0x1FFF` gesetzt (ISO 13818-1 / BD-ROM Part 3: „kein PCR-PID").

- **Bug 3 — IGS-SubClip PMT: Falscher `pcr_pid` im Program Map Table (`modules/m2ts/m2ts_writer.py`):**
  - **Ursache:** Konsistenzproblem zu Bug 2: Auch im PMT-Paket des generierten IGS-M2TS-SubClips war `pcr_pid = 0x1400` eingetragen. Sony UB700 prüft CLPI und PMT gegeneinander; ein Widerspruch (oder ein nicht existierender PCR-Strom) führt ebenfalls zum sofortigen Abbruch.
  - **Fix:** `build_pmt_packet(pcr_pid=0x1FFF, ...)` im IGS-M2TS-Writer gesetzt, konsistent mit der CLPI.

- **Test-Update (`tests/test_mpls_clpi_generator.py`):**
  - `test_mpls_structure` auf das korrekte 4-Feld-Header-Layout aktualisiert: Prüft jetzt explizit `app_info_offset == 40`, `playlist_offset > app_info_offset`, `mark_offset > playlist_offset` und `extension_data_offset == 0`.
  - Alle 44 Core-Unit-Tests grün.

## [1.1.5] - 2026-09-15

### Hinzugefügt & Verbessert
- **Menü-Loop Dauer frei einstellbar (Standard 30 Sekunden statt 10 Sekunden):**
  - Behebt das Ruckeln / kurzzeitige Unresponsiveness der Fernbedienung beim Menü-Loop: Das Menü läuft jetzt standardmäßig **30 Sekunden** (statt bisher 10 Sekunden) und kann in der GUI stufenlos zwischen 5 und 300 Sekunden konfiguriert werden.
  - Playlist (`00000.mpls`), Hintergrundvideo (`00001.m2ts`) und IGS-Grafiksubclip (`00002.m2ts`) werden exakt auf die konfigurierte Dauer synchronisiert.
- **Nativer Motion-Video Support (`.264`):**
  - Direkte Einbindung von rohen H.264 Elementary Streams (`.264` / `.h264` / `.avc`) als Motion-Menühintergrund.
  - **0 % Re-Encoding:** Externe Master-Videoloops werden 1:1 direkt via tsMuxeR gemuxt, ohne jede Qualitätsminderung oder Farbraumverfälschung.
  - Automatische Erkennung der Clip-Dauer via `probe_media_duration`.
- **Hintergrundmusik Support (`.ac3` & `.wav`):**
  - Direkte Einbindung von Menütonspuren als `.ac3` (wird ohne Re-Encoding 1:1 gemuxt) oder `.wav` (wird automatisch standardkonform in Stereo 48 kHz / 192k AC-3 gewandelt).
  - Falls keine Musik hinterlegt ist, wird weiterhin automatisch eine normgerechte lautlose AC-3 Tonspur synthetisiert.
- **Erweitertes Menü-Design-Panel (`gui/tabs/tab_menu.py`):**
  - Neue Steuerelemente im Menü-Tab: Separate Schnellauswahl für Hintergrundbild (`.png`, `.jpg`), Motion-Video (`.264`) und Hintergrundmusik (`.ac3`, `.wav`) inklusive direkter Reset-Buttons (`✕`).
  - Loop-Dauer-SpinBox mit Live-Synchronisation im Projektstatus (`.bdproj`).

## [1.1.4] - 2026-09-15

### Behoben & Verbessert
- **Untertitel Transparenz-Fix (`modules/subtitles/srt_to_sup.py`):**
  - Behebt den soliden schwarzen Kasten/Balken hinter Untertiteln.
  - Palette aus den echten RGBA-Werten: Index 0 ist immer transparent (`Alpha = 0`), damit der Film hinter dem Untertitel sichtbar bleibt.
  - Subpixel-Anti-Aliasing mit bis zu 16 Alpha-Stufen für schwebende, gestochen scharfe weiße Typografie mit edler schwarzer Kontur (Outline).
- **Vollständige CJK- & Japanisch-Unterstützung (`modules/subtitles/srt_to_sup.py`):**
  - Automatischer CJK-Font-Fallback: Erkennt ostasiatische Zeichen (Kanji, Hiragana, Katakana, Hangul, Hanzi) und wechselt automatisch auf vorinstallierte Windows-Schriftarten (`Yu Gothic`, `MS Gothic`, `Meiryo`).
  - Behebt die Anzeige von Platzhalter-Quadraten ("Tofu" `[]`) bei japanischen Untertiteln.
  - Westliche Untertitel nutzen modern proportionierte Typografie (`Segoe UI` / `Arial`).
- **Menü-Hintergrundvideo für Hardware-Player (`modules/menu_author.py`):**
  - FFmpeg-Encoding für Menü-Hintergrundvideo strikt an BD-ROM Broadcast-Norm angepasst: Limited Range (`-color_range tv`), Farbraum `-colorspace bt709 -color_primaries bt709 -color_trc bt709`, `-profile:v high -level:v 4.1` und `-bluray-compat 1`.
  - tsMuxeR-Aufruf für Menüvideo mit `insertSEI, contSPS` aufgerufen; ältere Panasonic- und andere Hardware-Player brauchen die wiederholten SPS/SEI.
- **Test-Suite Erweiterung (`tests/test_srt_to_sup.py`):**
  - Neue Unit-Tests für Transparenz von Paletteneintrag 0 (`Alpha = 0`), CJK-Zeichenerkennung und japanisches Rendering ohne Glyphenverlust (Gesamt-Testsuite: 106 Tests grün).

## [1.1.3] - 2026-09-15

### Behoben
- **VLC Timeline & Playhead Fix (`modules/bdmv/index_generator.py`):**
  - Behebt das Problem, dass VLC während der Filmwiedergabe die Timeline starr auf `00:00 bis 00:00` anzeigt und der Playhead nicht mitwandert.
  - Ursache: Die BD-ROM Spezifikation (`libbluray/bdnav/index_data.h`) unterscheidet zwischen `playback_type_interactive = 1` (`0x4000`) und `playback_type_movie = 0` (`0x0000`). Zuvor wurden alle Titel als interaktiv geflaggt, wodurch VLC `DEMUX_GET_LENGTH`, `DEMUX_GET_TIME` und `DEMUX_GET_POSITION` deaktiviert hatte.
  - Jetzt wird `is_interactive=True` strikt nur für FirstPlayback und TopMenu gesetzt, während Film- und Episodentitel korrekt als `playback_type_movie` (`0x0000`) deklariert werden.
- **Nativer SRT-zu-SUP (BD-ROM PGS) Compiler (`modules/subtitles/srt_to_sup.py`, `core/meta_builder.py`):**
  - Behebt das Problem unsichtbarer Untertitel: Da tsMuxeR 2.7.0 unter Windows ohne integrierte FreeType-Bibliothek kompiliert ist, wurden Untertitel bei `S_TEXT/UTF8` stillschweigend verworfen (0 Pakete in den M2TS-Stream geschrieben).
  - Implementierung einer vollständig nativen Python-Render-Engine:
    - Robustes SRT-Parsing mit automatischer Zeichencodierungs-Erkennung (UTF-8, UTF-8-BOM, CP1252/Latin-1).
    - Hochwertiges Subpixel-Textrendering via Pillow mit 3px starker schwarzer Kontur (Outline) und zentrierter Positionierung am unteren Bildrand (1080p).
    - Farbraum-Quantisierung in BD-ROM konforme 8-Bit Paletten (BT.709 YCbCrA mit Anti-Aliasing Alpha-Stufen).
    - BD-ROM Standard RLE-Kompression (`modules.igs.rle`).
    - Standardkonforme SUP/PGS-Paketierung (Presentation Composition Segment Epoch Start/Clear, Window Definition Segment, Palette Definition Segment, Object Definition Segment, End Segment).
    - Vollautomatische On-the-Fly Konvertierung von `.srt` nach `.sup` im Meta-Builder und Muxing als `S_HDMV/PGS`.
- **Kompatibilität mit Hardware-Playern (Panasonic, Sony u. a.):**
  - **Menü-Audiotrack (`modules/mpls/mpls_generator.py`, `modules/menu_author.py`):** Ältere Standalone-Player (wie der Panasonic DMP-BDT111EG) verwerfen Playlists ohne definierte Tonspur. Das Menü synthetisiert nun automatisch eine leise AC-3 Stereo-Audiospur (`0x1100`), die in der Menü-MPLS STN-Table deklariert und in den M2TS-Stream gemuxt wird.
  - **PMT HDMV Registration Descriptor (`modules/m2ts/ts_packetizer.py`):** Aufnahme des offiziellen 4-Byte HDMV Program Map Table Registration Descriptors (`0x05, 0x04, 'H', 'D', 'M', 'V'`) zur einwandfreien Erkennung standardisierter BD-ROM Streams durch Hardware-Decoder.
  - **Return-to-Menu Navigation (`modules/bdmv/movie_object_generator.py`):** Korrektur des Post-Movie Kommandos von ungültigem `JumpTitle(0)` auf das standardkonforme `JumpObject(0)` (MovieObject 0 = Menü), da Titel 0 nach BD-ROM Spezifikation nicht existiert.

## [1.1.2] - 2026-09-15

### Hinzugefügt
- **Intelligente, durchsuchbare Sprachauswahl (`gui/widgets/language_combo.py`):**
  - Neues wiederverwendbares `LanguageComboBox`-Widget für Audio- und Untertitelspuren.
  - Live-Autovervollständigung mit Substring-Filterung (`MatchContains`): Suche funktioniert sowohl nach Sprachname (z. B. `de`, `ita`, `schwedisch`) als auch direkt nach 3-stelligen ISO-Codes (`jpn`, `swe`, `kor`).
  - Nur gültige Codes für tsMuxeR: verhindert Einfügen von ungültigem Freitext (`NoInsert`) und snappt bei fehlerhaften Eingaben automatisch auf den zuletzt gültigen Wert zurück.
  - ComboBox und Vervollständigungs-Liste im dunklen Programm-Design.
- **Umfassender ISO 639-2 Weltsprachen-Katalog (`core/constants.py`):**
  - Erweiterung des Sprachkatalogs von bisher 6 auf über 100 weltweite Standardsprachen, Dialekte und O-Ton-Formate (`Originalton [qaa]`, `Instrumental [mis]`).
  - Angeheftete Top-Sprachen (Deutsch, English, Français, Español, Italiano, Japanisch) an oberster Stelle des Dropdowns, gefolgt von einer alphabetischen Gesamtliste im Format `Sprachname [iso]`.
  - Robuster Resolver (`resolve_language_code`), der formatierte Strings, direkte ISO-Codes und case-insensitive Namen fehlertolerant auflöst.
- **Test-Suite Erweiterung (`tests/test_language_selector.py`):**
  - 9 neue Unit-Tests für Katalog-Größe, Pinned-Languages, Resolver-Logik, Auto-Snap-Back und ProjectState-Integration (Gesamtzahl Tests: 99, alle grün).

## [1.1.1] - 2026-09-15

### Behoben
- **tsMuxeR SRT-Untertitel Syntax (`core/meta_builder.py`):**
  - Behebt den sofortigen Export-Abbruch mit Fehler `Unsupported codec S_TEXT/SRT (Exit-Code 4294967294)`.
  - Umstellung der Meta-Dateien auf die offizielle tsMuxeR-Syntax `S_TEXT/UTF8` für Textuntertitel.
  - Ergänzung professioneller Rendering-Parameter für Fernseher: Schriftart (`font-name="Arial"`), Schriftgröße (`font-size=65`), Bildschirmabstand (`bottom-offset=40`) und Kontur/Outline (`font-border=2`) für optimale Lesbarkeit auf dunklen und hellen Hintergründen.
- **Robustes Error-Handling für Multi-Title Muxing (`gui/tabs/tab_export.py`):**
  - Fehler beim Muxen von Folgetiteln ($t=2..N$) werden nicht mehr als harmlose Warnung verschluckt, sondern detailliert mit Standard-Error/Output von tsMuxeR geloggt und brechen den Export geordnet ab, um unvollständige oder korrupte Discs zu verhindern.
- **Test-Coverage (`tests/test_multititle_export.py`):**
  - Neue automatisierte Tests für `S_TEXT/UTF8`-Deklaration und Ausschluss veralteter `S_TEXT/SRT`-Kennungen.

## [1.1.0] - 2026-09-10

### Hinzugefügt
- **Dynamische Multi-Title Menü-Generierung (`modules/igs/layout.py`, `modules/menu_author.py`):**
  - Automatische Erstellung separater Menü-Schaltflächen für jeden in `1. Medien & Titel` angelegten Titel ($1..N$).
  - Die Titelnamen (z. B. `FOLGE 1: DER PILOT`, `MAKING-OF`, `EPISODE 3`) fließen vollautomatisch als Standard-Buttontext in das Menü ein.
  - Volle individuelle Editierbarkeit jedes Button-Textes im Menü-Tab (`MediaTitle.menu_btn_text`).
  - Freie Platzierung jedes einzelnen Buttons per Maus-Drag & Drop auf der 16:9 Leinwand mit Speicherung in den Projekt-Metadaten.
  - Automatisches Umschalten zwischen 1-Spalten- und 2-Spalten-Grid-Layouts je nach Buttonanzahl mit vollautomatischer 4-Wege D-Pad Fernbedienungs-Navigation inkl. Wrap-Around.
- **Vollautomatische Multi-Title Muxing- & Authoring-Pipeline (`gui/tabs/tab_export.py`, `core/meta_builder.py`):**
  - Jeder zusätzliche Titel ($t=2..N$) wird automatisch mit tsMuxeR in temporäre BDMV-Strukturen gemuxt (`MetaBuilder.save_title_meta_file`).
  - Zuweisung sequentieller Clip-IDs (`00003`, `00004`, `00005` ...) und Playlists (`00002.mpls`, `00003.mpls` ...).
  - Automatisches Patchen der internen MPLS-Clipreferenzen (`b"00000M2TS"` $\to$ `b"0000XM2TS"`).
  - Standardkonforme `index.bdmv` und `MovieObject.bdmv` Navigation mit $N$ Playback-Objekten und automatischem Rücksprung ins Hauptmenü (`JumpTitle(0)`) nach Wiedergabeende.
  - Automatisches Spiegeln aller Playlists und CLPI-Dateien in den `BDMV/BACKUP/` Ordner.
- **Live-Synchronisation zwischen Titel-Tab und Menü-Designer (`gui/app.py`, `gui/tabs/tab_menu.py`, `gui/tabs/tab_titles.py`):**
  - Qt-Signal `titles_changed`: Sobald im Tab *Medien & Titel* ein Titel hinzugefügt, gelöscht, umbenannt oder mit Video versehen wird, aktualisieren sich der Menü-Tab und die Leinwand in Echtzeit.
  - Aktualisierte Optionsleiste mit dynamischer Titelliste, individuellen Namensfeldern und Status-Badges (⭐ Haupttitel, ✓ Video zugeordnet, ⚠ Kein Video).
- **Umfangreiche Test-Suite (`tests/test_multititle_export.py`):**
  - 7 neue automatisierte Unit-Tests für Multi-Title Button-Generierung, 5-Titel Grid-Layout, Index/MovieObject Navigation für 3 Titel, Title Meta-Generierung, Disc-Assembly und Live-GUI-Synchronisation (insgesamt 89 Tests erfolgreich).

## [1.0.1] - 2026-09-10

### Hinzugefügt
- **Vollständige Projektverwaltung (`.bdproj` / JSON):**
  - Speichern und Laden des gesamten Projektstatus per Mausklick oder Tastaturkürzel (`Strg+S`, `Strg+O`, `Strg+Shift+S`, `Strg+N`).
  - Speichert alle Dateipfade (Videos, Audios, Subs, Kapitel-EDLs, Menühintergrund), Menütexte und die pixelgenauen Drag & Drop Button-Koordinaten.
  - Anzeige der aktuell geöffneten Projektdatei direkt im Fenstertitel.
- **Titel-zentriertes Master-Detail Medien-UI (`gui/tabs/tab_titles.py`):**
  - Ablösung der fragmentierten Einzel-Tabs durch eine aufgeräumte Master-Detail-Architektur: Links die Titelliste aller Medien (Hauptfilm, Making-Of, Episoden), rechts der vollständige Inspector für den ausgewählten Titel.
  - Jeder Titel verfügt über eigene Videodateien (2D Base + optional 3D MVC), Audiospuren (mit BWF-Bereinigung und MP4-Extraktion), Untertitel und Kapitelmarker (EDL-Import & Monospace-Editor).
  - Bereinigung der Hauptnavigation auf 3 logische Kernbereiche: `🎬 1. Medien & Titel`, `🎨 2. Menü-Designer` und `🚀 3. Export`.
- **Modulares Titel-Datenmodell (`MediaTitle` in `core/project_state.py`):**
  - Disc-Titel als eigene Objekte; bestehende Properties und Mux-Aufrufe funktionieren unverändert.
- **Erweiterte Test-Suite (`tests/test_project_io.py`):**
  - 4 neue Unit-Tests für Projekt-IO, MediaTitle-Serialisierung und Titel-Verwaltung (insgesamt 81 Tests erfolgreich).

## [1.0.0] - 2026-09-10

### Hinzugefügt
- **Vollständige Migration auf PySide6 (Qt 6):**
  - Ablösung von CustomTkinter durch modernste Qt 6 Technologie für kompromisslose Desktop-Performance, flüssiges Rendering und native High-DPI-Unterstützung.
  - Ausgereiftes **"Dark Cinema"**-Design-System (`gui/theme.py`) mit harmonischer Farbpalette, transluzenten Karten, Custom-Scrollbars, abgerundeten Steuerelementen und erstklassiger Typografie.
- **Interaktiver Menü-Designer mit `QGraphicsView` & `QGraphicsScene` (`gui/tabs/tab_menu.py`):**
  - Voller $1920 \times 1080$ Blu-ray Koordinatenraum mit automatischer, responsiver 16:9-Viewport-Skalierung.
  - Natives **Drag & Drop** beliebiger Menü-Buttons mit der Maus für pixelgenaue Positionierung.
  - Automatische Begrenzung auf den sichtbaren TV-Bildschirmbereich ($0 \le X \le 1920 - W$, $0 \le Y \le 1080 - H$).
  - Live-Koordinatenanzeige (X, Y) bei Mausbewegung sowie edler Gold-Glow bei Auswahl und Verschieben.
  - Manuell verschobene Button-Koordinaten fließen direkt in den authorierten IGS-Stream der finalen Disc ein.
  - Schnell-Funktion *„Positionen zurücksetzen“* zur Wiederherstellung des automatischen Menü-Layouts.
  - Schnelle Umschaltung zwischen den Seiten *Hauptmenü*, *Kapitelauswahl* und *Sprachauswahl*.
- **Thread-sicherer asynchroner Export (`gui/tabs/tab_export.py`):**
  - Vollständige Kapselung von `tsMuxeR`, Bonusmaterial-Muxing, HDMV-Menü-Injektion und nativer UDF 2.50 ISO-Erstellung in einen separaten `QThread` (`ExportWorker`).
  - Thread-sichere Qt-Signals (`log_signal`, `progress_signal`, `finished_signal`); kein Einfrieren der GUI während rechenintensiver Mux- und Brennprozesse.
- **Moderne Anwendungs-Architektur (`gui/app.py`, `main.py`):**
  - `QStackedWidget` mit vorab geladenen Tabs für verzögerungsfreie Navigation ohne Widget-Churn oder Datenverlust.
  - Automatische UDF-konforme Disc-Label-Bereinigung (Großbuchstaben, Ziffern, Unterstriche, max. 32 Zeichen).
  - Dynamische Laufzeit-Umschaltung aller Oberflächentexte zwischen Deutsch und Englisch.
  - Modaler Spezifikations-Dialog (`InfoDialog`) für Blu-ray Formatstandards.
- **Erweiterte Test-Suite (`tests/test_gui_qt.py`):**
  - 7 neue automatisierte Headless-Tests für alle Qt-Komponenten, Disc-Name-Filterung, Tab-Navigation, Menü Drag & Drop und Sprachwechsel (insgesamt 77 Tests erfolgreich).

## [0.3.3] - 2026-09-10

### Hinzugefügt
- **Vollständige Multi-Page Menü-Architektur (`modules/igs/segments.py`, `modules/igs/compiler.py`):** Unterstützung beliebig vieler Menüseiten (Pages) in einem einzigen Interactive Composition Display Set nach BD-ROM Part 3. Ermöglicht das Umschalten zwischen Menüseiten (`SetButtonPage`) ohne Schwarzbild und ohne Neuladen des Videos.
- **Automatische Projekt-Menü-Generierung (`modules/menu_author.py`):** Automatische Extraktion aller im Projekt vorhandenen Kapitel, Tonspuren und Untertitel für die Menü-Generierung.
  - Automatische Übersetzung von ISO-639-2 Sprachcodes (z. B. `deu`, `eng`) in lesbare Landesnamen (`DEUTSCH`, `ENGLISH`).
  - Automatische Verknüpfung von `SetStream`-Befehlen für Ton- und Untertitel (inkl. `UNTERTITEL AUS`).
  - Automatische `PlayPLatPM`-Kapitelsprung-Befehle für jedes Kapitel.
- **Erweiterter Menü-Tab in der GUI (`gui/tabs/tab_menu.py`):**
  - Schalter für *„Kapitelauswahl-Menü aktivieren“* und *„Sprachauswahl-Menü aktivieren“* mit anpassbaren Button-Namen.
  - Live-Statusabzeichen über erkannte Kapitel und Tonspuren (z. B. *„4 Kapitel hinterlegt“*, *„2 Tonspuren, 1 Untertitel“*).
  - **Vorschau mit Reitern je Seite:** Umschalten zwischen der Vorschau des Hauptmenüs, des Kapitelmenüs und des Sprachmenüs mit exakter maßstabsgetreuer 1:1 Button-Darstellung.
- **Unit Tests (`tests/test_multipage_menu.py`):** 5 neue End-to-End Tests für Multi-Page Menü-Kompilierung, BDMV-Injektion und Projekt-Seiten-Generierung (insgesamt 70 Tests erfolgreich).

## [0.3.2] - 2026-09-10

### Hinzugefügt
- **Modulare Menü-Layout-Engine (`modules/igs/layout.py`):** Dynamische automatische Platzierung von beliebig vielen Buttons (1-Spalten-Layout oder 2D-Grid) mit automatischer 4-Wege D-Pad-Berechnung (`upper_id`, `lower_id`, `left_id`, `right_id`) inkl. intuitivem Fernbedienungs-Wrap-Around.
- **Erweiterte HDMV Virtual Machine Opcodes (`modules/bdmv/movie_object_generator.py`, `modules/igs/segments.py`):** Vollständige Implementierung und Verifikation von `PlayPLatPM` (Kapitelsprünge), `SetStream` (Audio- und Untertitel-Umschaltung im laufenden Betrieb) und `SetButtonPage` (Menü-Unterseiten).
- **Flexibles Menü-Authoring (`modules/menu_author.py`):** `generate_menu_subclip` und `assemble_hdmv_disc_structure` akzeptieren nun frei definierbare Button-Listen (`MenuButtonSpec`) mit responsiver Schriftgrößen-Anpassung und voller Abwärtskompatibilität.
- **Vorgefertigte Menü-Vorlagen:** Fertige Generatoren für Hauptmenüs (`build_main_menu_specs`), Kapitelauswahl (`build_chapter_menu_specs`) und Sprachauswahl (`build_audio_menu_specs`).
- **Erweiterte Test-Suite (`tests/test_hdmv_opcodes.py`, `tests/test_menu_layout.py`):** 20 neue automatisierte Unit-Tests für alle HDMV-Opcodes, Layout-Matrizen und Multi-Button-SubClips (insgesamt 65 Tests fehlerfrei).

## [0.3.1] - 2026-09-10

### Behoben
- **BDMV Navigations-Header (`modules/bdmv/index_generator.py`):** Exakte Einhaltung des 40-Byte Headers für `index.bdmv` nach BD-ROM Spezifikation (`indexes_start = 78`). Behebt den `libbluray`-Abbruch ("app_info length is 0, expected 34") und die VLC-Fehlermeldung *"Start der Blu-Ray-Wiedergabe fehlgeschlagen"* sowie uninitialisierte Video-Grafikfehler.
- **IGS End of Display Set Segment (`modules/igs/segments.py`):** Korrektur des Segment-Typs für `SEGMENT_END` von `0x16` auf standardkonformes `0x80` (`PGS_END_OF_DISPLAY`).
- **IGS UI-Model Always-On (`modules/igs/segments.py`):** Umstellung des UI-Models im Interactive Composition Segment von `0xC0` (`ui_model = 1` / Popup-Menü) auf `0x80` (`ui_model = 0` / Always-On). Verhindert, dass das Hauptmenü fälschlicherweise als ausgeblendetes Popup-Menü behandelt wird, sodass Buttons sofort sichtbar und klickbar gerendert werden.
- **IGS PES-Paketierung (`modules/igs/compiler.py`):** Jedes IGS-Segment (`ICS`, `PDS`, `ODS`, `END`) wird nun in ein eigenes PES-Paket verpackt. Behebt den `libbluray`-Dekoderfehler *"buffer size mismatch"*.
- **MPEG-TS PUSI-Signalierung (`modules/m2ts/ts_packetizer.py`):** Jedes PES-Paket im IGS-Stream beginnt nun zwingend in einem neuen TS-Paket mit gesetztem `PUSI = 1` (Payload Unit Start Indicator), während unvollständige Endpakete sauber mit Adaptation-Field-Stuffing aufgefüllt werden. Verhindert das Verwerfen nachfolgender Segmente durch Demuxer.
- **M2TS Aligned Units Pufferung (`modules/m2ts/m2ts_writer.py`):** M2TS SubClip-Ausgabe (`00002.m2ts`) wird mit Null-Paketen (`PID 0x1FFF`) auf ganzzahlige Vielfache von 6.144 Bytes (32 TS-Pakete = 1 Aligned Unit) gepuffert für unterbrechungsfreies Preloading.
- **CLPI ProgramInfo & EP_map (`modules/mpls/clpi_generator.py`):** Ergänzung des 1-Byte Felds `num_groups = 0` in `ProgramInfo` (beseitigt 1-Byte-Shift beim Stream-Parsing) sowie Erzeugung einer standardkonformen `EP_map` (CPI) mit Coarse- und Fine-Tabellen.
- **MPLS SubPath & PTS-Offset (`modules/mpls/mpls_generator.py`):** Vereinheitlichung des Start-PTS auf das offizielle 10-Minuten-Offset (54.000.000 bei 90 kHz / 27.000.000 bei 45 kHz) und Korrektur des IGS Stream-Entries auf `stream_type = 2` (5 Bytes mit `subclip_id`).
- **Hintergrundvideo-Muxing (`modules/menu_author.py`):** Enkodierung des Hintergrundbilds via FFmpeg zu Raw H.264 (`.264`) und Muxen mittels integriertem `tsMuxeR` zu vollständig standardkonformem `00001.m2ts` und `00001.clpi` mit synchronem Start-PTS.
- **Standalone-Player Kompatibilität (`modules/iso_tools.py`, `modules/menu_author.py`):** Automatische Erstellung aller nach BD-ROM Part 3 vorgeschriebenen Standard-Verzeichnisse (`BDMV/AUXDATA`, `BDMV/BDJO`, `BDMV/JAR`, `BDMV/META`, `CERTIFICATE/BACKUP`), um Firmware-Ablehnungen ("Inkompatible Disc") auf physischen Standalone-Playern (Sony, Panasonic, PS4/PS5) zu verhindern.
- **HDMV Menü-Looping Absicherung (`modules/bdmv/movie_object_generator.py`):** MovieObject 0 führt nun nach `PlayPL(0)` direkt `JumpObject(0)` aus, sodass das Menü auch auf strengen Hardware-Playern nach Ablauf des Videoloops in Schleife weiterläuft.

## [0.3.0] - 2026-09-10

### Hinzugefügt
- **Native UDF 2.50 Blu-ray ISO-Engine (`modules/iso_tools.py`):** Vollautomatische Generierung von standardkonformen UDF 2.50 Blu-ray ISO-Dateien aus fertigen BDMV-Verzeichnissen über die native Windows IMAPI2FS-Schnittstelle. Keine Drittanbieter-Brennsoftware erforderlich.
- **Automatische tsMuxeR-Erkennung (`modules/mux_engine.py`):** Automatisches Auffinden von `tsMuxeR.exe` im Projektordner (`tools/`), im Hauptverzeichnis oder im System-`PATH` inklusive aussagekräftiger GUI-Fehlermeldung.

### Behoben
- **Fehlende ISO-Erstellung bei aktivem Menü & Extras:** Wenn das Exportformat auf "ISO Image" gesetzt war, wurde bisher bei aktivem Menü nur das BDMV-Verzeichnis erzeugt. Nun wird die brennfähige `.iso`-Datei vollautomatisch direkt nach Fertigstellung aller Menüs und Extras erzeugt.
- **Prozessaufruf mit Leerzeichen:** Ausführung von `tsMuxeR` erfolgt nun ohne `shell=True`, wodurch Pfade mit Leerzeichen unter Windows zuverlässig ausgeführt werden.

## [0.2.0] - 2026-09-08

### Hinzugefügt
- **Native Blu-ray HDMV Menü-Engine (Out-of-Mux SubPath Typ 2):** Vollständig native Python-Implementierung zur Erstellung standardkonformer Blu-ray Menüs nach BD-ROM Part 3 Spezifikation:
  - **IGS-Compiler (`modules/igs/`):** Blu-ray RLE Bitmap-Encoder, ITU-R BT.709 Farbraum-Quantisierer (Index 0 Transparenz), Display-Set Segmente (`PDS`, `ODS`, `ICS`, `END`), PES-Paketierer mit 33-Bit PTS bei 90 kHz.
  - **192-Byte M2TS Transport-Stream Packer (`modules/m2ts/`):** Eigene PAT/PMT Generierung mit Stream-Typ `0x91` (IGS) auf PID `0x1400`, 30-Bit Arrival Time Stamp (ATS) `TP_extra_header` und exakte 188-Byte TS Adaptation-Field Auffüllung.
  - **SubPath Playlist & ClipInfo Generatoren (`modules/mpls/`):** Generierung von `00000.mpls` mit Out-of-Mux SubPath Typ 2 für Interactive Graphics und `00001.clpi`/`00002.clpi` mit SequenceInfo, ProgramInfo und EP_map.
  - **BDMV Navigations-Engine (`modules/bdmv/`):** Binäre Generierung von `index.bdmv` (FirstPlayback, TopMenu, Titles) und `MovieObject.bdmv` mit echten HDMV VM Opcodes (`PlayPL`, `JumpTitle`).
  - **High-Level Menü-Orchestrator (`modules/menu_author.py`):** Automatisierte Erstellung von Button-Grafiken (Pillow), Hintergrund-Videorendering via FFmpeg und native TS-Paketierung, SubClip-Erzeugung und Menü-Injektion in bestehende BDMV-Verzeichnisstrukturen.
- **Menü-Designer Tab (`MenuTab` in `gui/tabs/tab_menu.py`):** Interaktiver Tab zur Konfiguration von Menü-Aktivierung, individuellem 1080p Hintergrundbild (JPG/PNG), Button-Texten ("FILM STARTEN", "EXTRAS") und integrierter Live-Vorschau (480x270).
- **Automatisierte Menü-Injektion im Export:** Der Export-Workflow injiziert bei aktivem Menü die SubClips, Playlists und Navigationsdateien automatisch in die vom Muxer erstellte BDMV-Struktur inklusive aller geforderten Backup-Kopien.

## [0.1.0] - 2026-09-08

### Hinzugefügt
- **Versionsanzeige in der Benutzeroberfläche:** Die Versionsnummer (`v0.1.0`) wird nun im Hauptfenstertitel sowie gut sichtbar in der Sidebar unter dem Anwendungslogo angezeigt.
- **Zweiwege-Synchronisation für Kapitel:** Manuelle Eingaben, Ergänzungen oder Zeilenlöschungen in der Kapitel-Textbox (`ChapterTab`) werden live über Event-Bindings in den Projektstatus übernommen und beim Muxen berücksichtigt.
- **Asynchroner Audio-Import:** Das Bereinigen von WAV-Dateien (Metadaten-Stripping) und das Extrahieren von Tonspuren aus MP4-Dateien wird in einem Worker-Thread ausgeführt. Die Benutzeroberfläche bleibt reaktionsfähig und friert bei großen Dateien nicht mehr ein.
- **Drop-Frame Timecode-Support:** Der DaVinci Resolve EDL-Parser unterstützt jetzt sowohl Non-Drop-Frame (`:`) als auch Drop-Frame (`;`) Timecodes.
- **Robuster Encoding-Fallback:** Der EDL-Parser liest Dateien jetzt mit automatischem Encoding-Fallback (`utf-8`, `utf-8-sig`, `cp1252`, `latin-1`), um Abstürze bei NLE-Exporten mit Sonderzeichen zu verhindern.
- **Umfassende Validierung im Export:** Klare Rückmeldungen im Logfenster, falls Video oder Zielordner vor dem Muxen fehlen.
- **Automatisierte Test-Suite:** Unittests für Meta-File-Generierung, WAV/MP4-Caching, EDL-Parsing und Framerate-Heuristik.

### Behoben
- **tsMuxeR Kapitel-Syntax korrigiert:** Umstellung von ungültigem `--chapters=hh:mm:ss.mmm,...` auf die offizielle tsMuxeR-Syntax `--custom-chapters=hh:mm:ss.zzz;...` mit Semikolon.
- **Fehlende Framerate in Meta-Datei:** Die ermittelte Framerate (`fps=...`) wird nun explizit in allen Videostreams (`V_MPEG4/ISO/AVC`), 3D-Erweiterungsstreams (`V_MPEG4/ISO/MVC`) und Textuntertiteln (`S_TEXT/SRT`) deklariert. Verhindert asynchrone Ton- und Untertitelspuren sowie Mux-Abbrüche bei 3D.
- **Falsche Erfolgsmeldung im Export:** Der Exit-Code des Muxer-Prozesses (`tsMuxeR`) wird nun geprüft. Schlägt der Mux-Vorgang fehl, wird die Fehlermeldung mit Exit-Code angezeigt statt eines irreführenden "✅ Fertig.".
- **Race Conditions beim Export:** Der Export-Start-Button wird während des Muxens deaktiviert und nach Abschluss im `finally`-Block reaktiviert.
- **Caching-Logik für Audio bereinigt:** Bei bereits vorhandenen bereinigten WAV- (`_clean.wav`) oder extrahierten MP4-Dateien (`_extracted.eac3`) wird der Pfad nun korrekt zugewiesen; zusätzlich werden Dateizeitstempel verglichen.
- **DTS-Audioerkennung präzisiert:** Substring-Prüfung (`"dts" in path`) durch strikte Dateiendungsprüfung (`.dts`, `.dtshd`, `.dts-hd`) ersetzt, damit Ordnernamen mit "dts" keine falschen Codecs auslösen.
- **Pfadformatierung:** Backslashes in Dateipfaden werden für die `.meta`-Datei einheitlich zu Forward-Slashes (`/`) normalisiert.
- **ffprobe Pfadsuche:** Erkennung von `ffprobe` auch bei absoluten Pfaden zu `ffmpeg`.
- **Framerate-Differenzierung für 720p:** Echte 720p50 und 720p59.94 Streams werden nicht mehr versehentlich durch die Heuristik halbiert.
- **Schutz gegen GUI-TclErrors:** Sichere Widget-Zugriffe beim Muxen verhindern Abstürze, falls der Tab während des Exports gewechselt wird.
