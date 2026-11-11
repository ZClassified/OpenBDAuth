# Plan: Bereich Brennen – ISO direkt auf Blu-ray schreiben

Stand: 2026-11-11 · Status: **macOS und Windows mit einem echten Brand bestätigt** (v1.30.0, v1.32.0); Linux im
Test mit Betatestern (v1.31.0)

### Stand macOS (2026-11-11)

- Umgesetzt: `modules/burn` (Modell, Prüfungen, ISO-Angaben, Ruhezustand, macOS-Backend, Fake-Backend, Ablauf),
  `gui/burn/page.py`, dritter Reiter, „Zum Brennen“ im Export-Dialog, ISO im Simulator auch unter macOS
  (`hdiutil attach`), Tests in `tests/test_burn.py`.
- Gegen den echten Brenner geprüft (nur lesend, HL-DT-ST BP40NS20 über USB): `drutil list -xml` und
  `drutil -drive N status -xml` liefern Typ, leer/löschbar, freie Sektoren und die **Brenngeschwindigkeiten des
  eingelegten Mediums** – die Auswahl „Geschwindigkeit“ zeigt genau diese.
- `hdiutil burn` braucht für einen 1:1-Brand `-forceclose -noaddpmap -nosynthesize -nooptimizeimage -noskipfinalfree`
  (sonst bleibt die Disc offen oder hdiutil baut ein eigenes Dateisystem). BD-RE wird mit `-erase` im selben Aufruf
  gelöscht, weil `drutil erase` die Disc danach auswirft.
- Die Meldungen von `hdiutil -puppetstrings` sind in der Sprache des Systems (z. B. Deutsch). Die Phasen (Löschen,
  Brennen, Prüfen) werden deshalb an Stichwörtern **und** am Verlauf der Prozente erkannt.
- **Erster Brand (2026-11-11, `HARDWARE_TESTS.md`):** BD-RE mit Daten, 7,92-GB-ISO. `-erase` löscht die BD-RE im
  selben Aufruf. Die Disc ist **Byte für Byte die ISO** (roh zurückgelesen und verglichen) und läuft in VLC. Ein Test
  auf einem Hardware-Player steht noch aus (zurzeit keiner verfügbar).
- **Korrektur:** Rohzugriff auf die Disc braucht unter macOS **kein root**. `/dev/rdiskN` des optischen Laufwerks
  gehört dem angemeldeten Nutzer (`brw-r----- <nutzer> operator`). Damit kann OpenBDAuth die Disc später auch selbst
  gegen die ISO prüfen (wie unter Windows und Linux geplant), etwa für „Disc gegen ISO prüfen“; bisher prüft unter
  macOS `hdiutil`.
- Noch offen: Phasenanzeige mit „Prüfen“ an und mehrere Kopien auf echter Hardware; BD-R (bisher nur BD-RE).

Heute endet OpenBDAuth bei einer ISO oder einem BDMV-Ordner. Zum Brennen braucht man ein anderes Programm (z. B.
ImgBurn unter Windows). Ziel: ein dritter Arbeitsbereich **Brennen** neben Vorbereiten und Disc. Eine einmal erstellte
ISO lässt sich dort beliebig oft brennen, ohne das Projekt neu zu packen.

---

### Stand Linux (2026-11-11, v1.31.0)

- Umgesetzt: `modules/burn/linux.py` (xorriso vom System), `modules/burn/verify.py` (Disc gegen ISO über das Gerät),
  „Diagnose kopieren“, Simulator mit `udisksctl`. Kein Linux-Rechner mit Brenner verfügbar: Die Ausgaben stammen aus
  echten xorriso-Läufen auf ein Pseudo-Laufwerk (Datei) und, für Laufwerk und Medium, aus dem Quelltext.
- **Test über zwei Betatester:** erst „Diagnose kopieren“ ohne zu brennen, dann ein Brand auf BD-RE mit „Prüfen“.
- Offen, klärt der Test: echte `-devices`- und `-toc`-Ausgabe mit Blu-ray-Laufwerk, Aushängen einer eingehängten
  BD-RE, ob das System nach dem Brennen die neue Größe meldet (sonst „nicht geprüft“), Formatieren einer neuen BD-RE
  (`blank=as_needed` formatiert mit Reservebereich, etwas weniger Platz).

### Stand Windows (2026-11-11, v1.32.0, Branch `feature/brennen-windows`)

- Umgesetzt: `modules/burn/windows.py` (IMAPI2 über comtypes, spätes Binden, kein `comtypes.gen`), Prüfen über
  `\\.\X:` mit `IOCTL_DISK_GET_LENGTH_INFO` und `FSCTL_ALLOW_EXTENDED_DASD_IO`, erneutes Lesen nach Lesefehlern.
- Erster Brand (BD-RE, 7,92 GB): Löschen 11 s, Schreiben 894 s bei 2x, Disc Byte für Byte die ISO.
- **Offen:** Kommen die Fortschrittsereignisse jetzt an (Protokollzeile „events vtable …, invoke …“ nach Write und
  EraseMedia)? Brand über die Oberfläche, Abbrechen, Auswerfen, BD-R. Autoplay öffnet die frisch gebrannte Disc
  während des Prüfens (z. B. in VLC) – ggf. `DisableMcn` bis nach dem Prüfen. Kurz ansehen: die Zahlenfelder aus
  v1.30.1 unter Windows.

## Grundsätze

- **Nur die fertige ISO wird gebrannt, Sektor für Sektor, 1:1.** Das Dateisystem kommt immer aus unserer
  UDF-2.50-Engine (`modules/udf250_writer.py`), auch das 3D-SSIF-Interleaving. Das Brennprogramm des Systems schreibt nur
  die Bytes. Wir geben ihm nie einen Ordner, der dann ein eigenes Dateisystem bekäme. Das ist dieselbe Lehre wie beim
  Ausbau von IMAPI2FS in v1.18.1: Es hat Fehler verdeckt (siehe `modules/iso_tools.py`).
- **Keine eigene Laufwerksansteuerung** (SCSI/MMC). Wir nutzen den Brenner, den das System mitbringt. Er kennt die
  Laufwerke, braucht keine Admin-Rechte und ist erprobt.
- **Brennen verbraucht Rohlinge.** Darum wird vorher alles geprüft, was sich prüfen lässt. Der Abbruch wird ehrlich
  beschrieben, und hinterher wird die Disc geprüft.
- Die Disc wird immer **abgeschlossen** (finalisiert). Multisession gibt es nicht; Player lesen nur abgeschlossene
  BD-R.

---

## Brenner je System

| System | Brennen | Laufwerk/Medium abfragen | Auswerfen |
|---|---|---|---|
| **Windows 10/11** | IMAPI2 `IDiscFormat2Data.Write` mit der ISO als `IStream` | `IDiscMaster2`, `IDiscRecorder2`, `CurrentPhysicalMediaType`, `FreeSectorsOnMedia`, `MediaHeuristicallyBlank` | `IDiscRecorder2.EjectMedia` |
| **macOS 13+** | `hdiutil burn <iso> -noeject` (DiscRecording) | `drutil list`, `drutil -drive N status` | `drutil -drive N eject` |
| **Linux** | `xorriso -as cdrecord dev=/dev/srN -v <iso>` | `xorriso -devices`, `xorriso -outdev /dev/srN -toc` | `xorriso -outdev /dev/srN -eject all` |

- **Windows:** Zugriff aus Python über `comtypes` (MIT-Lizenz, eine neue Abhängigkeit, Eintrag in
  `THIRD_PARTY_LICENSES.md`). Den Fortschritt liefert das COM-Event `DDiscFormat2DataEvents.Update`. Das Brennen läuft in
  einem eigenen Thread mit eigener COM-Initialisierung (MTA).
- **macOS:** `hdiutil` gibt mit `-puppetstrings` maschinenlesbaren Fortschritt aus. Auswerfen übernimmt `hdiutil`
  selbst nicht (`-noeject`), damit die Einstellung „Auswerfen“ an einer Stelle entschieden wird (siehe unten).
- **Linux:** `xorriso` wird zunächst **nicht mitgeliefert**. Fehlt es, nennt der Bereich den Installationsbefehl
  (`sudo apt install xorriso` bzw. dnf/pacman). Fehlt die Berechtigung am Laufwerk: Hinweis auf die Gruppe
  `cdrom`/`optical`. Mitliefern über `tools/fetch_tools.py` ist später möglich (GPL, passt zur Lizenz).

### Aufbau im Code

- `modules/burn/__init__.py`: gemeinsame Schnittstelle und Datenklassen
  - `list_drives() -> [Drive]` (Name, Hersteller, Pfad/Kennung, kann BD schreiben)
  - `media_info(drive) -> Media` (Typ BD-R/BD-RE/BD-R DL/kein Medium, leer, freie Sektoren)
  - `burn(drive, iso_path, speed, progress, cancel) -> Ergebnis`
  - `verify(drive, iso_path, progress, cancel) -> Ergebnis`
  - `erase(drive, quick=True)` (nur BD-RE)
  - `eject(drive)`
- `modules/burn/windows.py`, `macos.py`, `linux.py`: ein Backend pro System
- `modules/burn/fake.py`: Fake-Backend für Tests und für die Entwicklung ohne Brenner (simuliert Laufwerk, Medium,
  Fortschritt und Fehler)
- `modules/burn/power.py`: Ruhezustand verhindern, solange gebrannt wird (Windows `SetThreadExecutionState`, macOS
  `caffeinate -i -w <pid>`, Linux `systemd-inhibit`)
- `gui/burn/page.py`: der Arbeitsbereich

---

## Der Arbeitsbereich Brennen

Neuer Reiter in der oberen Leiste: **Vorbereiten | Disc | Brennen** (`PAGE_BURN` neben `PAGE_PREPARE` und `PAGE_DISC`
in `gui/studio/main_window.py`). Wie bei Vorbereiten sind die Disc-Docks und Disc-Aktionen dort ausgeblendet.

### Links: Image

- **ISO wählen:** Datei-Dialog oder per Drag & Drop. Darunter die **zuletzt verwendeten ISOs** (exportiert oder
  gebrannt). Die Liste steht in den App-Einstellungen (`QSettings`, nicht im Projekt); fehlende Dateien werden
  ausgegraut.
- **Angaben zur ISO:** Dateiname, Disc-Titel (Volume-Label aus der ISO), Größe, „passt auf BD-25 / braucht BD-50“, 2D
  oder 3D. Gelesen wird mit dem vorhandenen ISO-Leser des Simulators (`modules/bdsim`).
- Ist die Datei keine Blu-ray (kein `BDMV` darin): **Warnung**, Brennen bleibt möglich.
- Knopf **„Im Simulator öffnen“**: die ISO vor dem Brennen noch einmal durchklicken.

### Rechts: Brenner

- **Laufwerk** (Auswahl, falls mehrere vorhanden) mit Status: kein Medium / BD-R leer, 25 GB / BD-RE mit Daten /
  …; „Aktualisieren“ und automatische Abfrage alle paar Sekunden, solange der Bereich offen ist.
- **Geschwindigkeit:** „Automatisch“ (Vorgabe) oder die Stufen, die das Laufwerk für das eingelegte Medium meldet.
- **Häkchen „Disc nach dem Brennen prüfen“** (englisch: „Verify disc after burning“), vorgegeben **aus**. Prüfen
  kostet zusätzlich Zeit, weil die ganze Disc einmal gelesen wird. Gespeichert in den App-Einstellungen
  (`burn/verify_after_burn`); fehlt der Wert, gilt **aus**.
- **Häkchen „Disc nach erfolgreichem Brennen auswerfen“**, vorgegeben **an** (siehe unten).
- **Kopien:** 1 (Vorgabe) bis 10.
- Hauptaktion **„Brennen“**, gefüllt, an derselben Stelle wie „Disc erstellen“ bzw. „Starten“.
- Darunter Fortschritt (Phase, Prozent, Restzeit) und ein Protokoll wie beim Export (`export_activity.py`).

### Vom Export zum Brennen

- Nach einem erfolgreichen ISO-Export bietet der Export-Dialog **„Zum Brennen“** an. Der Knopf öffnet den Bereich mit
  dieser ISO.
- Jede exportierte ISO kommt automatisch in die Liste der zuletzt verwendeten.
- Ein BDMV-Ordner als Ziel wird **nicht** direkt gebrannt. Wer einen Ordner brennen will, exportiert als ISO. So gibt es
  nur einen Weg, und das Dateisystem kommt immer von uns.

---

## Ablauf eines Brennvorgangs

1. **Prüfen vor dem Brennen** (Ergebnisse wie im Preflight: Fehler blockieren, Warnungen fragen nach):
   - Fehler: kein Laufwerk, kein Medium, Medium nicht beschreibbar (BD-ROM, DVD, abgeschlossene BD-R), ISO größer als
     der freie Platz (freie Sektoren × 2048 Byte vom Laufwerk, keine festen Werte), ISO nicht lesbar.
   - Warnungen: BD-RE mit Daten („wird gelöscht – fortfahren?“), ISO ist keine Blu-ray, in Vorbereiten läuft gerade die
     Warteschlange (Laufwerk und Platte teilen sich die Last; die Laufwerke schützen sich zwar vor Pufferunterlauf, ein
     Hinweis schadet aber nicht).
2. Bei BD-RE mit Daten: **schnell löschen**.
3. **Ruhezustand verhindern** (`power.py`), bis der ganze Ablauf beendet ist.
4. **Brennen**, Fortschritt im Bereich und als Prozent im Reiter („Brennen 42 %“), damit er auch von Disc aus sichtbar
   ist.
5. **Prüfen** (wenn eingeschaltet), siehe unten.
6. **Auswerfen** (wenn eingeschaltet und alles erfolgreich), siehe unten.
7. Bei mehreren Kopien: auswerfen, „Nächsten Rohling einlegen“, neues Medium erkennen, ab Schritt 1 für dieses Medium.
   Abbrechen ist zwischen zwei Kopien jederzeit möglich.

### Abbrechen

- **Vor dem Schreibstart** (Prüfen, Löschen, Vorlauf): normal abbrechbar, der Rohling bleibt unbenutzt.
- **Während des Schreibens:** Der Knopf heißt dann „Abbrechen – Rohling wird unbrauchbar“ und fragt einmal nach. Bei
  BD-RE: „Disc muss neu gelöscht werden“.
- **Während des Prüfens:** abbrechbar, ohne Schaden. Die Disc gilt dann als „nicht geprüft“.
- **Programm schließen** während eines Brennvorgangs: Rückfrage (wie bei laufender Warteschlange in Vorbereiten).

### Prüfen nach dem Brennen

- **Windows und Linux:** Die Disc wird Sektor für Sektor über die Länge der ISO zurückgelesen (Windows `\\.\X:`, Linux
  `/dev/srN`) und gegen die ISO verglichen. Die Prüfsumme der ISO entsteht dabei nebenbei: Gelesen wird blockweise aus
  beiden, verglichen wird sofort. So wird jeder Block nur einmal gelesen, und der erste abweichende Sektor lässt sich
  benennen.
- **macOS:** `hdiutil burn` prüft selbst. (Rohzugriff auf `/dev/rdiskN` geht ohne root, siehe Stand macOS – ein
  eigenes Prüfen wäre also auch möglich.) Von sich aus
  prüft `hdiutil` immer; wir geben deshalb ausdrücklich `-verifyburn` oder `-noverifyburn` mit, je nach Häkchen.
- Ergebnis im Protokoll: „Disc geprüft: identisch mit der ISO“ oder „Abweichung ab Sektor N (≈ X GB) – Disc nicht
  verwenden“.

---

## Option: Disc nach erfolgreichem Brennen auswerfen

- Häkchen **„Disc nach erfolgreichem Brennen auswerfen“** (englisch: „Eject disc after successful burn“), vorgegeben
  **an**.
- Gespeichert in den **App-Einstellungen** (`QSettings`, Schlüssel `burn/eject_after_success`), nicht im Projekt: Es ist
  eine Vorliebe des Nutzers, kein Merkmal der Disc. Fehlt der Wert, gilt **an**.
- **„Erfolgreich“** heißt: gebrannt **und**, falls das Prüfen eingeschaltet ist, geprüft und identisch. Ausgeworfen
  wird erst nach dem Prüfen, nie davor (bei macOS deshalb `-noeject` an `hdiutil`).
- **Bei Fehler, Abweichung oder Abbruch wird nicht ausgeworfen.** Eine offene Lade heißt dann immer „fertig und in
  Ordnung“. Wer neben dem Laufwerk steht, nimmt so keine fehlerhafte Disc in dem Glauben heraus, sie sei gut. Die
  Meldung im Bereich sagt, was schiefging.
- **Mehrere Kopien:** Zwischen den Kopien wird immer ausgeworfen, sonst lässt sich kein neuer Rohling einlegen. Das
  Häkchen entscheidet nur über die **letzte** Kopie. Schlägt eine Kopie fehl, wird sie nicht ausgeworfen; der Ablauf
  hält an und fragt „Rohling wechseln und fortfahren / Beenden“.
- Klappt das Auswerfen nicht (z. B. Laufwerk ohne Motor, Disc vom System belegt), ist das kein Fehler des Brennens. Im
  Protokoll steht dann nur „Disc konnte nicht ausgeworfen werden“.
- Zusätzlich gibt es im Bereich jederzeit einen kleinen Knopf **„Auswerfen“** am Laufwerk (außer während eines
  Brennvorgangs).

---

## Prüfen (Tests)

Alles mit dem Fake-Backend, damit es auf allen drei CI-Systemen läuft:

- Prüfen vor dem Brennen: kein Laufwerk, kein Medium, BD-ROM, abgeschlossene BD-R, ISO zu groß (ein Sektor zu viel) und
  genau passend; BD-RE mit Daten fragt nach; ISO ohne `BDMV` warnt.
- Ablauf: Brennen + Prüfen ok → ausgeworfen. Prüfen meldet Abweichung → nicht ausgeworfen, Meldung mit Sektor. Fehler
  beim Brennen → nicht ausgeworfen. Abbruch → nicht ausgeworfen.
- Auswerfen-Häkchen aus → nach Erfolg nicht ausgeworfen. Wert fehlt in den Einstellungen → gilt als an. Der Wert bleibt
  nach einem Neustart erhalten.
- Prüfen-Häkchen: Wert fehlt → gilt als aus, es wird nicht geprüft, Auswerfen gleich nach dem Brennen. Häkchen an →
  geprüft, ausgeworfen erst danach. macOS bekommt je nach Häkchen `-verifyburn` bzw. `-noverifyburn`.
- Mehrere Kopien: Zwischen den Kopien wird immer ausgeworfen; die letzte Kopie richtet sich nach dem Häkchen. Eine
  Kopie schlägt fehl → Ablauf hält an.
- Abbrechen in jeder Phase; der Text des Knopfs wechselt mit dem Schreibstart.
- Ruhezustand: wird zum Start gesperrt und am Ende freigegeben, auch nach Fehler und Abbruch.
- Liste der zuletzt verwendeten ISOs: Export trägt ein, Duplikate werden zusammengefasst, fehlende Dateien ausgegraut,
  höchstens 10 Einträge.
- Vergleich beim Prüfen (`verify`): identische Daten, Abweichung im ersten, mittleren und letzten Block, Disc kürzer
  als die ISO.
- GUI-Smoke-Test: Bereich öffnen, ISO hineinziehen, Angaben erscheinen, ohne Laufwerk ist „Brennen“ gesperrt.

### Auf echter Hardware

Pro System mindestens ein Brenner, jeweils mit Eintrag in `HARDWARE_TESTS.md`:

- BD-R 25 GB mit einer 2D-ISO und einer 3D-ISO, danach auf den Test-Playern (X700, BDP-S4200) abspielen.
- BD-R DL 50 GB mit einer ISO über 25 GB (Wechsel der Schicht).
- BD-RE: mit Daten (löschen + brennen) und leer.
- Prüfen deckt einen Fehler auf (Disc nach dem Brennen zerkratzen oder eine andere Disc zum Vergleich einlegen).
- Abbruch während des Schreibens: Programm bleibt bedienbar, das Laufwerk ist danach wieder nutzbar.
- Auswerfen an/aus, zwei Kopien hintereinander.
- Kontrolle der 1:1-Kopie: die gebrannte Disc auslesen (Windows/Linux über das Prüfen, macOS z. B. mit
  `hdiutil makehybrid`/`dd` als root) und die Prüfsumme mit der ISO vergleichen.

---

## Reihenfolge beim Umsetzen

1. **Probebrand pro System**, noch ohne Oberfläche: ein kleines Skript in `tools/` brennt eine 3D-ISO mit dem jeweiligen
   Backend. Danach wird bestätigt, dass die Disc **Byte für Byte** der ISO entspricht und auf den Playern in 3D läuft.
   Besonders wichtig bei `hdiutil burn`: Es muss die ISO roh schreiben und darf nichts umwandeln. Erst wenn das auf
   einem System sicher ist, geht es dort weiter.
2. Schnittstelle, Fake-Backend und Tests (`modules/burn`).
3. Backend **macOS** (am einfachsten, direkt testbar).
4. Arbeitsbereich Brennen mit Auswahl der ISO, Laufwerk, Ablauf, Prüfen, Auswerfen.
5. Backend **Windows** (IMAPI2 über `comtypes`, Abhängigkeit in Build und Lizenzen).
6. Backend **Linux** (`xorriso` vom System, Hinweise bei fehlendem Programm oder fehlender Berechtigung).
7. „Zum Brennen“ im Export-Dialog, Liste der zuletzt verwendeten ISOs.
8. Mehrere Kopien.
9. README (Funktionen, Plattformen), CHANGELOG, Übersetzungen DE/EN, Hardware-Tests.

## Risiken

- **`hdiutil burn` und ISO:** Ob es eine `.iso` wirklich roh schreibt, muss Schritt 1 belegen. Wenn nicht, braucht
  macOS einen anderen Weg (z. B. DiscRecording direkt über PyObjC). Das wäre deutlich mehr Aufwand.
- **BD-RE löschen unter macOS:** `man hdiutil` (`-erase`) und `drutil help` (`erase`) nennen nur CD-RW/DVD-RW. Ob
  BD-RE damit gelöscht wird, gehört in den Probebrand. Wenn nicht, gibt es BD-RE unter macOS zunächst nur leer.
- **Zurücklesen direkt nach dem Brennen:** Manche Laufwerke erkennen die frisch geschriebene Disc erst nach einem
  Neuladen. Wenn das Lesen fehlschlägt: einmal neu einlesen lassen bzw. kurz warten und erneut versuchen, bevor
  „Prüfen fehlgeschlagen“ gemeldet wird.
- **Lesezugriff `\\.\X:` unter Windows ohne Admin-Rechte:** für optische Laufwerke normalerweise erlaubt, muss aber
  bestätigt werden.
- **Hardware-Vielfalt:** Wir können nur wenige Brenner testen. Die Fehlermeldungen des Systems werden deshalb
  vollständig ins Protokoll übernommen, damit Rückmeldungen von Nutzern auswertbar sind.

## Entschieden (2026-11-11)

- Name des Reiters: **Brennen** / **Burn**.
- Linux: `xorriso` **vom System**. Mitliefern über `tools/fetch_tools.py` kann später dazukommen; die Backends rufen
  das Programm über `find_tool` auf (`modules/external_tools.py`), sodass eine mitgelieferte Datei ohne Änderung am
  Backend Vorrang bekäme.
- Prüfen nach dem Brennen: **Option, vorgegeben aus**.
- Kopien: **höchstens 10**.

## Später

- „Disc gegen ISO prüfen“ einzeln für eine bereits gebrannte Disc anbieten. `verify` gibt es dafür ohnehin.
- `xorriso` für Linux mitliefern.
