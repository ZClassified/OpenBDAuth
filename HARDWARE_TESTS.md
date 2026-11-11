# Hardware-Tests

Protokoll aller Brenntests auf echten Playern: was mit welcher Version auf welchem Gerät lief und was nicht.
**Legende:** ✅ läuft · ❌ läuft nicht · ⚠ läuft mit Einschränkung · – nicht getestet

---

## Stand je Player

Letzte Version, mit der eine Funktion auf dem Gerät bestätigt wurde.

| Player | Baujahr | Zuletzt getestet | Filme 2D | Filme 3D | Menü | Menüseiten wechseln | Kapitelsprung | Ton-/Untertitelwahl im Menü |
|---|---|---|---|---|---|---|---|---|
| Sony UBP-X700 | 2018 | v1.32.0 | ✅ v1.13.0 | ✅ v1.8.5 | ✅ v1.32.0 (7 Menüs; Form-Buttons Dreieck und Kreis ab v1.13.0) | ✅ v1.13.1 (auch zwischen Menü-Playlists; Seite und Button überstehen die Menü-Schleife) | ✅ v1.32.0 (Taste „Nächstes Kapitel“ im Film; 2D und 3D ab v1.8.5) | ✅ v1.13.0 (Ton und Untertitel) |
| Sony BDP-S4200 | 2014 | v1.18.1 | ✅ v1.17.7 | ✅ v1.4.0 | ✅ v1.18.1 (7 Menüs; Filmende im Extras-Menü, Trailer vor dem Menü) | ✅ v1.17.7 (zwischen 7 Menü-Playlists) | ✅ v1.17.7 | ✅ v1.17.7 (Ton und Untertitel) |
| Sony PlayStation 3 | – | v1.9.7 | ⚠ v1.9.7 (kein Ton) | – | ✅ v1.9.7 | ✅ v1.9.7 | ✅ v1.9.7 | ✅ v1.9.7 (Untertitel an/aus; Ton nicht prüfbar) |
| Panasonic DMP-BDT111EG | – | v1.17.7 | ❌ v1.17.7 (ruckelt, wie schon immer) | ❌ bleibt stehen | ✅ v1.17.7 (7 Menüs) | ✅ v1.17.7 | ✅ v1.17.7 | – |

Der Panasonic hat sich in früheren Versionen als besonders strenger Player erwiesen (siehe Changelog); eine Disc, die dort läuft, gilt als robust. Vorrang haben aber aktuelle Player: Korrekturen für den Panasonic nur, wenn sie die Disc näher an Norm und tsMuxeR bringen, und immer mit Gegenprobe auf dem Sony.

## Geräte

| Gerät | Typ | Hinweis |
|---|---|---|
| Sony UBP-X700 (2018) | Player | 4K-UHD-Player, Blu-ray 3D |
| Sony BDP-S4200 (2014) | Player | Blu-ray 3D |
| Panasonic DMP-BDT111EG | Player | Blu-ray 3D, strenge Prüfung |
| Sony PlayStation 3 | Spielkonsole als Player | Modell und Firmware nicht erfasst |
| LG OLED55C27LA | Fernseher | 2D |
| LG OLED55E6V | Fernseher | 3D |
| HL-DT-ST BP40NS20 | Brenner (USB, extern) | BD-R/BD-RE; Brenntests aus OpenBDAuth unter macOS (ab v1.30.0) |
| VLC (macOS) | Software-Player | libbluray; HDMV-Menüs, 3D nur als 2D – kein Ersatz für einen Player |

---

## Testläufe (neueste zuerst)

### 2026-11-11 · v1.32.0-dev · Projekt „D4A“ · `D4A.iso` · erster Brand unter Windows (IMAPI2)

- **Inhalt:** dieselbe ISO wie beim Brand unter macOS (7 923 499 008 Bytes, 3 868 896 Sektoren).
- **Laufwerk:** HL-DT-ST BP40NS20 über USB, Windows 11 (Build 26200), Medium: dieselbe BD-RE. IMAPI2 meldet Typ 19 (BD-RE), Status „nur überschreiben“, 11 826 176 freie Sektoren, eine Geschwindigkeit (4390 Sektoren/s = 2x).
- **Vorher, nur lesend:** Die BD-RE vom macOS-Brand über `\\.\I:` (ohne Admin-Rechte) zurückgelesen: bis auf die letzten 288 Sektoren gleich. Grund: Über den Laufwerksbuchstaben endet das Lesen am Ende des UDF-Volumes (3 868 608 Sektoren). Mit `FSCTL_ALLOW_EXTENDED_DASD_IO` sind auch diese Sektoren lesbar und **identisch** – das Prüfen nutzt das seitdem.
- **Löschen:** `MsftDiscFormat2Erase` (schnell) in 11 s; danach meldet IMAPI2 die BD-RE als leer, Sektor 16 enthält nur Nullen.
- **Brennen:** `MsftDiscFormat2Data.Write` mit der ISO als `IStream`, `ForceMediaToBeClosed`, 894 s bei 9,1 MB/s (2x), ohne Fehler. Die Fortschrittsereignisse kamen dabei nicht an (Empfänger danach umgebaut, noch nicht bestätigt).
- **Prüfen:** brach nach 45 % mit „[Errno 22] Invalid argument“ ab; dieselben Sektoren ließen sich danach fehlerfrei lesen. Zusammen mit einem zweiten Lauf (45–100 %) ist die ganze Disc **Byte für Byte die ISO**. Seitdem liest das Prüfen nach einem Lesefehler bis zu dreimal erneut. Während des Prüfens öffnete Windows die Disc per Autoplay in VLC; beide lasen gleichzeitig, das Prüfen wurde langsamer.

| Player | Fernseher | Ergebnis | Bemerkung |
|---|---|---|---|
| VLC 3.0.24 (Windows) | – | ⚠ | Mit Videoausgabe **Direct3D9** (war eingestellt) bleibt nach „Kapitel“ die Grafik des Hauptmenüs stehen, nach einem Kapitel laufen Film und Untertitel unter der Menügrafik – bei jeder ISO (auch v1.29.0 und Mac-Export). Mit **Direct3D11** läuft das Menü richtig; mit OpenGL ignoriert VLC das Menü. „Nächstes Kapitel“ in VLC springt ins Menü – in Kodi richtig, auf den Playern ging der Kapitelsprung immer; also VLC. Simulator: 0 Fehler (wie v1.17.7). |
| Kodi (Windows) | – | ✅ | Menüs, Wechsel ins Kapitelmenü und Film laufen richtig (Blu-ray-Menü-Modus, libbluray wie VLC). „Nächstes Kapitel“ springt richtig; die Zeitleiste zeigt dabei kurz den Filmanfang bzw. „-2:32“, dann die richtige Stelle – vermutlich nur Anzeige; auf dem Sony UBP-X700 nicht aufgetreten, also Kodi. |
| Sony UBP-X700 | nicht erfasst | ✅ | Diese unter Windows gebrannte Disc (bitgleich zum macOS-Export), getestet mit v1.32.0: Menüs laufen; „Nächstes Kapitel“ per Taste im Film springt richtig zum nächsten Kapitel, ohne auffällige Zeitanzeige oder Sprünge. Bestätigt: Das Springen ins Menü in VLC und die kurze falsche Zeit in Kodi sind Fehler der Software-Player, nicht der Disc. |

### 2026-11-11 · v1.30.0 · Projekt „D4A“ · `D4A.iso` · erster Brand aus OpenBDAuth (macOS)

- **Inhalt:** wie beim Test mit v1.17.7 (Hauptfilm mit 6 Tonspuren und 5 Untertiteln, Trailer, Making-of, 7 Menüs), mit v1.30.0 unter macOS als ISO exportiert (7,92 GB).
- **Brennen:** im neuen Arbeitsbereich Brennen auf eine **BD-RE mit Daten** (HL-DT-ST BP40NS20 über USB, macOS 26.2, App aus dem GitHub-Build). Die Disc wurde gelöscht und gebrannt (`hdiutil burn -erase … -forceclose -noaddpmap -nosynthesize -nooptimizeimage -noskipfinalfree`).
- **1:1-Kontrolle:** Die Disc roh gelesen (`/dev/rdisk4`, ohne root) und mit der ISO verglichen: **identisch**, 7 923 499 008 Bytes (3 868 896 Sektoren), 544 s bei 12–15 MB/s.
- **Simulator auf der gebrannten Disc:** wie bei v1.17.7: 0 Fehler, 10 Warnungen, 2 Hinweise. Die Warnungen („Tonspur 2–6 gewählt, der Film hat nur 1“ bei Trailer und Making-of) sind eine Übermeldung des Simulators: Trailer und Making-of setzen die Tonwahl nicht (MovieObject 3 und 4 ohne `SetStream`, ohne `GPR5`); das Register der aktuellen Tonspur steht nach dem Hauptfilm nur noch auf der alten Nummer, und ein Player wählt beim Start eine gültige Spur. Die gemerkte Wahl bleibt für den Hauptfilm erhalten. Offen: den Simulator so ändern, dass er ungültige Spurnummern beim Filmstart wie ein Player behandelt.

| Player | Fernseher | Ergebnis | Bemerkung |
|---|---|---|---|
| VLC (macOS) | – | ✅ | Gebrannte Disc läuft. Kein Hardware-Player verfügbar; Test auf einem Player steht aus. |

### 2026-10-21 · v1.18.1 · Projekt „D4A“

- **Inhalt:** wie bei v1.18.0; neu: Start → Trailer → Hauptmenü (Film vor dem Menü per `JumpTitle` in First Play).

| Player | Fernseher | Ergebnis | Bemerkung |
|---|---|---|---|
| Sony BDP-S4200 | nicht erfasst | ✅ | Disc eingelegt: Trailer startet, danach erscheint das Hauptmenü. Top Menu während des Trailers: sofort im Hauptmenü. Film → Film (Hauptfilm → Making-of) nicht getestet. |

### 2026-10-21 · v1.18.0 · Projekt „D4A“

- **Inhalt:** wie beim Test mit v1.17.7; neu: Filmende in einem anderen Menü als dem Hauptmenü (Trailer → Extras-Menü).

| Player | Fernseher | Ergebnis | Bemerkung |
|---|---|---|---|
| Sony BDP-S4200 | nicht erfasst | ✅ | Trailer angesehen, danach erscheint das Extras-Menü statt des Hauptmenüs. Nachgetragen am 2026-10-21: Danach ist „TRAILER“ ausgewählt (zweiter Button im Menü, nicht der Standard-Button) – der Button, der den Film startet, wird nach dem Film gewählt. Tonspur nach einem Filmende im Extras-Menü nicht gemeldet. |

### 2026-10-20 · v1.17.7 · Projekt „D4A“ · `D4A.iso`

- **Inhalt:** Erstes großes Projekt: Hauptfilm (18 min, 6 Tonspuren, 5 Untertitel, 15 Kapitel), Trailer und Making-of als eigene Titel, 7 Menüs (17 Clips). Mit v1.17.6 exportiert.
- **Vorher (v1.17.6):** In VLC wechselten die Menüs nicht, der Sony BDP-S4200 hing beim Einlegen. Ursache: Der UDF-Metadatenbereich war fest 96 Sektoren groß, die Disc brauchte 109. Die Einträge von 13 Clips (alle Untermenü-Hintergründe und alle IG-Ströme) lagen dahinter, waren für Player 0 Byte groß und überschrieben die Unique-ID-Tabelle. Behoben in v1.17.7.
- **Neue ISO:** Die 77 Dateien wurden aus der alten ISO gelesen und mit dem v1.17.7-Schreiber neu verpackt (kein neuer Export); unter Windows eingehängt alle Byte für Byte gleich.
- **Simulator:** 0 Fehler; 10 Warnungen (im Menü gewählte Tonspur 2–6 gilt auch für Trailer und Making-of, die nur eine haben); 2 Hinweise (Test 13, Durchlauf nach 50 000 Zuständen abgebrochen).

| Player | Fernseher | Ergebnis | Bemerkung |
|---|---|---|---|
| Sony BDP-S4200 | nicht erfasst | ✅ | Film läuft, Menüs wechseln, Ton- und Untertitelwahl im Menü wirken, Kapitel starten. Trailer und Making-of nicht gemeldet. |
| Panasonic DMP-BDT111EG | nicht erfasst | ⚠ | Nachgetragen am 2026-10-21. Menüs laufen, Kapitel wählbar. Film ruckelt – bekannt seit der Eingrenzung vom 2026-09-29 (liegt an den Film-Clips, nicht an Menü oder Disc-Aufbau). Ton-/Untertitelwahl, Trailer und Making-of nicht gemeldet. |

### 2026-10-14 · v1.13.1 · Test-Disc A · `1_13_1_TEST_A.iso`

- **Inhalt:** wie `1_13_0_TEST_A.iso`; die Menü-Schleife merkt sich jetzt Seite und ausgewählten Button.
- **Simulator:** 0 Fehler, 0 Warnungen, 1 Hinweis (Test 13, bekannt).

| Player | Fernseher | Ergebnis | Bemerkung |
|---|---|---|---|
| Sony UBP-X700 | nicht erfasst | ✅ | Hauptmenü: Auswahl auf „KAPITEL“, nach Ablauf der Schleife (30 s) bleibt „KAPITEL“ ausgewählt. Kapitelmenü (eigener Hintergrund, Schleife 20 s): nach 20 s und nach 40 s bleiben Seite und ausgewählter Button. **Offener Punkt 11.2.4 vollständig behoben** (Seite und Button). |

### 2026-10-14 · v1.13.0 · Test-Disc A · `1_13_0_TEST_A.iso`

- **Inhalt:** Per Skript aus den Medien von Disc A gebaut (2D test, 25p, 3 Kapitel, Ton EN/DE, UT EN/DE). Bild 1: Hauptmenü (Form-Buttons Dreieck) und Sprachmenü (Kreise) in einer Menügruppe; Bild 2: Kapitelmenü mit zwei Seiten als zweite Menü-Playlist. Checkliste `TESTCHECKLISTE_1_13_0.md`.
- **Simulator:** 0 Fehler, 0 Warnungen, 1 Hinweis (Test 13, bekannt).

| Player | Fernseher | Ergebnis | Bemerkung |
|---|---|---|---|
| Sony UBP-X700 | nicht erfasst | ✅ | Disc läuft. Ton und Untertitel im Menü wählbar und beim Start wirksam. **Beide Menüs mit unterschiedlichen Hintergründen laufen** – der Sprung zwischen zwei Menü-Playlists über Register und Startseite trägt. Nachtest Punkt 3: Die Seite bleibt nach Ablauf der Schleife stehen (Kapitelmenü bleibt Kapitelmenü, 60 s geprüft; 11.2.4 behoben), aber die Auswahl springt nach jeder Schleife (30 s Hauptmenü, 20 s Kapitelmenü) auf den ersten Button – behoben in v1.13.1. Top Menu im Menü (Punkt 5) nicht gemeldet. Disc B (Menüs ohne `resume_intention`, 11.2.5) nicht getestet. |

### 2026-10-13 · 1.11.0-dev (Branch `feature/button-shapes`) · Sony BDP-S4200

- **Inhalt:** Testprojekt mit einem Film mit mehreren Ton- und Untertitelspuren; Hauptmenü mit einem neuen Form-Button (Linie, Stufe 1). Disc-Titel im Player eingeschaltet.
- **Sony BDP-S4200:** ✅ Form-Button (Linie) funktioniert. ✅ Disc-Titel wird angezeigt (Funktion aus v1.10.1).
- **Nicht getestet:** Kreis und Dreiecke, mehrere Form-Buttons, gemischte Text- und Form-Menüs, andere Player.

### 2026-09-29 · v1.9.7 · Disc A (2D) · `1_9_7_DISC_A.iso`

- **Inhalt:** Im Studio mit neuem Projekt gebaut (`1_9_7_DISC_A.bdproj`, Teil 1 von `TESTCHECKLISTE_1_9_7.md`): 2D-Film 54 s, 3 Kapitel, 2 Tonspuren (EN, DE; AC3), 2 Untertitel. Hauptmenü mit Kapitelmenü und kombiniertem Ton-/Untertitelmenü (eine Menü-Playlist, 3 Seiten).
- **Simulator:** 0 Fehler, 0 Warnungen, 3 Hinweise (2D- und 3D-Fernseher).
- **Medium:** BD-RE.

| Player | Fernseher | Ergebnis | Bemerkung |
|---|---|---|---|
| Sony PlayStation 3 | nicht erfasst | ⚠ | **Erster erfolgreicher Lauf auf der PS3** (frühere Versionen liefen dort nicht; nicht protokolliert). Ausführlich durchgeklickt: Menüs und Seitenwechsel, alle Untertitel ein und aus, Kapitelstarts – alles wie erwartet. **Kein Ton.** Ursache offen: möglicherweise Fernseher bzw. Tonausgabe der PS3 (HDMI-Einstellungen), nicht zwingend die Disc. Tonwahl im Menü deshalb nicht prüfbar. |
| Sony UBP-X700 | nicht erfasst | ✅ | Kurztest: Disc startet, Menü und Film laufen. Nicht mehr alles einzeln durchprobiert (lief schon mit v1.8.6 vollständig). |
| Sony BDP-S4200 | nicht erfasst | ✅ | Kurztest wie beim UBP-X700; erster Test dieses Players mit Menüs aus dem Studio. |

**Folgerung:** Dass die PS3 jetzt läuft, geht vermutlich auf v1.8.8 zurück (Spurtabelle der Playlists mit festen Eintragsgrößen wie tsMuxeR, Palette-Eintrag 255 transparent) – dieselben Korrekturen, die den Panasonic zum Laufen brachten. Die in v1.8.8 offene Gegenprobe auf dem Sony UBP-X700 ist damit erledigt. **Offen:** Ton auf der PS3 mit anderem Fernseher bzw. geprüfter Tonausgabe gegentesten (zum Vergleich eine andere Blu-ray mit AC3-Ton auf derselben PS3). *Zurückgestellt am 2026-10-12: zurzeit keine PS3 verfügbar.* Disc B (3D) auf der PS3 an einem 3D-Fernseher testen, sobald einer verfügbar ist – die PS3 wählt die 3D-Ausgabe anders als die Sony-Player, die Umschaltung 3D-Film ↔ 2D-Menü ist dort noch ungeprüft.

### 2026-09-29 · Panasonic-Eingrenzung · Disc A und B (v1.8.6/v1.8.7, Test-ISOs)

- **Medium:** BD-RE (auch die frühere, laufende Disc ohne Menü war BD-RE).
- **Test-ISOs:** jeweils nur in einem Punkt gegenüber der vorherigen geändert. `_STN9`: Menü-Playlist mit festen STN-Längen (9/5). `_PAL255`: zusätzlich Palette-Eintrag 255 transparent. `_OHNE_MENU`: reine tsMuxeR-ISO des Films. `_OHNE_MENU_OHNE_UT`: zusätzlich ohne Untertitel.

| ISO | Player | Ergebnis | Bemerkung |
|---|---|---|---|
| `1_8_6_DISC_A.iso`, `1_8_7_DISC_B_3D.iso` | Panasonic DMP-BDT111EG | ❌ | Disc wird erkannt (B als 3D), lädt kurz, zurück ins Player-Menü. |
| `1_8_6_DISC_A_STN9.iso` | Panasonic DMP-BDT111EG | ⚠ | Menü erscheint, Buttons wählbar. Gelber Schleier über dem ganzen Menü außer auf den Buttons. Film ruckelt (etwa 1 Bild alle 2 s). |
| `1_8_7_DISC_B_3D_STN9.iso` | Panasonic DMP-BDT111EG | ⚠ | Menü mit demselben Schleier; Film startet in 3D, bleibt auf dem ersten Bild stehen. |
| `1_8_7_DISC_A_OHNE_MENU.iso` | Panasonic DMP-BDT111EG | ⚠ | Startet, ruckelt wie mit Menü. |
| `1_8_7_DISC_A_OHNE_MENU_OHNE_UT.iso` | Panasonic DMP-BDT111EG | ⚠ | Ruckelt weiterhin – Untertitel sind nicht die Ursache. |
| `1_8_7_DISC_B_OHNE_MENU_OHNE_UT.iso` | Panasonic DMP-BDT111EG | ⚠ | Bleibt weiterhin stehen. |
| `1_8_6_DISC_A_STN9_PAL255.iso` | Panasonic DMP-BDT111EG | ✅ Menü | Menü ohne Schleier, wie gewünscht. Film ruckelt weiterhin. |

**Folgerung:** Menü-Fehler behoben in v1.8.8 (feste STN-Längen, Palette-Eintrag 255 transparent). Die Film-Wiedergabe auf dem Panasonic hängt nicht an Menü, Untertiteln oder unserem UDF-Writer, sondern an den Film-Clips selbst (Kodierung oder tsMuxeR); offen.

### 2026-09-28 · v1.8.7 · Disc B (3D) · `1_8_7_DISC_B_3D.iso`

- **Inhalt:** wie v1.8.5 (Projekt `DISC_B_3D.bdproj`); neu: 3D-Profilprüfung (PSR 31) vor jedem `SetOutputMode`.
- **Simulator:** 0 Fehler, 0 Warnungen; Kapitelstart mit 3D-Player + 3D-TV in 3D, mit 3D-Player + 2D-TV und mit Player ohne 3D-Profil in 2D.

| Player | Fernseher | Ergebnis | Bemerkung |
|---|---|---|---|
| Sony UBP-X700 | LG OLED55E6V (3D) | ✅ | Alles wie mit v1.8.5: Kapitel in 3D, Menü danach in 2D. |
| Sony UBP-X700 | LG OLED55C27LA (2D) | ✅ | Läuft normal in 2D. |

### 2026-09-28 · v1.8.6 · Disc A (neu) · `1_8_6_DISC_A.iso`

- **Inhalt:** wie v1.8.5 (Projekt `1_8_4_DISC_A.bdproj`); neu: TopMenu übernimmt die Spuren des zuletzt gelaufenen Films.
- **Simulator:** 0 Fehler, 0 Warnungen, 3 Hinweise.

| Player | Fernseher | Ergebnis | Bemerkung |
|---|---|---|---|
| Sony UBP-X700 | nicht erfasst | ✅ | Untertitel DE im Menü, Film; im Film per Fernbedienung Ton + Untertitel EN; Top Menu, Film erneut: bleibt EN ✅. „Untertitel aus“ im Menü gewinnt danach ✅. Nach Auswerfen und Neueinlegen direkt „Film starten“: Voreinstellung des Players (DE, ohne Untertitel) ✅. |

### 2026-09-28 · v1.8.5 · Disc B (3D) · `1_8_5_DISC_B_3D.iso`

- **Inhalt:** Projekt `DISC_B_3D.bdproj`, neu gebaut mit v1.8.5: 3D-Film 154 s, 5 Kapitel, 1 Tonspur (DE), 2 Untertitel (DE, EN); Kapitel über Register + `JumpTitle`.
- **Simulator:** 0 Fehler, 0 Warnungen, 3 Hinweise (3D- und 2D-Fernseher). Dateisatz gleich der auf Hardware bestätigten v1.8.0-Disc, geändert nur MovieObject und Menü.

| Player | Fernseher | Ergebnis | Bemerkung |
|---|---|---|---|
| Sony UBP-X700 | LG OLED55E6V (3D) | ✅ | Untertitel im Menü ein- und ausschalten, Start über „Film starten“ und über Kapitel: immer wie erwartet. Tonwahl nicht prüfbar (nur 1 Tonspur); gleicher Befehl wie auf Disc A (2D, bestanden). |

### 2026-09-28 · v1.8.5 · Disc A (neu) · `1_8_5_DISC_A.iso`

- **Inhalt:** wie v1.8.4 (Projekt `1_8_4_DISC_A.bdproj`, neu gebaut mit v1.8.5): 2D-Film 54 s, 3 Kapitel, 2 Tonspuren (DE, EN), 2 Untertitel (DE, EN).
- **Simulator:** 0 Fehler, 0 Warnungen, 3 Hinweise; `SetStream` mit zwei Operanden (`51 40 00 01 …`).

| Player | Fernseher | Ergebnis | Bemerkung |
|---|---|---|---|
| Sony UBP-X700 | nicht erfasst | ✅ | **Test 5 ✅:** Ton ENG im Menü → Film startet auf Englisch. **Test 6 ✅:** Ton DE + Untertitel DE → beides aktiv. Ton + Untertitel ENG, Start über Kapitel → beides aktiv. Ton DE + Untertitel aus, Start über Kapitel → Untertitel aus. Test 13 durch den Aufbau abgedeckt (der Titel setzt erst Ton, dann Untertitel). |

### 2026-09-28 · v1.8.4 · Disc A (neu) · `1_8_4_DISC_A.iso`

- **Inhalt:** Neue 2D-Disc (54 s, ruckelfrei), Kapitelmenü (3 Kapitel, Positionen bekannt), Sprachmenü; 2 Tonspuren (DE, EN), 2 Untertitel (DE, EN).
- **Simulator:** 0 Fehler, 0 Warnungen, 3 Hinweise.

| Player | Fernseher | Ergebnis | Bemerkung |
|---|---|---|---|
| Sony UBP-X700 | nicht erfasst | ⚠ | **Test 1 ✅:** Kapitel 1, 3, 2 jeweils mit Top Menu dazwischen – jedes Mal zurück ins Menü (Kapitel per Register + `JumpTitle`). **Test 5 ❌:** Ton Englisch im Menü, dann Film starten: bleibt Deutsch. **Test 6 ❌:** Untertitel Deutsch im Menü → Film ohne Untertitel; „Aus“ wirkt nicht; im Film per Fernbedienung gewählte ENG-Untertitel bleiben trotz „Aus“ im Menü beim nächsten Start an. Wahl im Menü gilt auch beim Kapitelstart nicht. Test 13 nicht durchgeführt. **Folgerung:** Register, Vergleiche und `PlayPLatPM` mit Register funktionieren; `SetStream` im MovieObject vor `PlayPL` (keine Playlist läuft) ignoriert der Sony – in beiden Formen (Register und fester Wert). |

### 2026-09-28 · v1.8.3 · Disc A · `DISC_A_2D.iso`

- **Inhalt:** In der alten Oberfläche gebaut. Hauptmenü mit Menü-Musik, Kapitelmenü (6 Kapitel) und Sprachmenü. 1 2D-Film (1105 s, 6,3 GB; versehentlich mit Top-Field-First kodiert, ruckelt – bekannt, nicht Teil des Tests), 4 Tonspuren (DE, DE, EN, EN), 3 Untertitel (DE, JA, FR).
- **Simulator:** 0 Fehler, 0 Warnungen, 9 Hinweise (u. a. Tonspur-Wahl im Menü, offener Punkt 11.2.1).

| Player | Fernseher | Ergebnis | Bemerkung |
|---|---|---|---|
| Sony UBP-X700 | nicht erfasst | ❌ | Menü-Musik läuft. Kapitelsprung aus dem Menü landet vermutlich richtig (Test 1). **Top Menu nach einem Kapitelstart:** Nach dem ersten Kapitel springt jede weitere Top-Menu-Taste – auch im Hauptmenü – zuerst in das zuerst gewählte Kapitel statt ins Menü; nach Neueinlegen dasselbe Muster. **Tonspur im Menü** (Test 5): ohne Wirkung, Film bleibt Deutsch; Wechsel per Fernbedienung klappt. **Untertitel im Menü** (Test 6): ohne Wirkung, „Aus“ wirkt nicht, es erscheinen immer deutsche Untertitel. Test 13 daher nicht durchführbar. Japanischer Button im Sprachmenü zeigt Kästchen statt Schrift. |

### 2026-09-28 · v1.8.0 · Disc B · `DISC_B_3D.iso`

- **Inhalt:** In der alten Oberfläche gebaut. Hauptmenü mit Kapitelmenü (5 Kapitel) und Sprachmenü. 1 3D-Film (154 s), 1 Tonspur (WAV Stereo), 2 Untertitel (DE, ENG), Kapitel aus EDL.
- **Simulator:** 0 Fehler, 0 Warnungen, 3 Hinweise (Menü-Schleife zeigt wieder das Hauptmenü, Test 12; Ton-Button schaltet laut libbluray die Untertitel aus).

| Player | Fernseher | Ergebnis | Bemerkung |
|---|---|---|---|
| Sony UBP-X700 | LG OLED55E6V (3D) | ✅ | Film läuft in 3D mit Ton, startet ohne Untertitel. Untertitel- und Kapitel-Tasten der Fernbedienung funktionieren. Kapitel aus dem Menü: Sprung an die richtige Stelle, in 3D (Test 2 ✅). Untertitel ENG im Menü gewählt, danach Film gestartet: läuft mit ENG-Untertiteln (Test 6 teilweise ✅). Nach Kapitelstart und Filmende: Menü wieder in 2D (Test 3 ✅). Top-Menu während Kapitel-Wiedergabe: Menü wieder in 2D (Test 4 ✅). Nach 30 s im Kapitel- oder Sprachmenü springt die Anzeige zurück ins Hauptmenü (Test 12, wie vom Simulator vorhergesagt; offener Punkt 11.2.4). |

### 2026-09-28 · v1.7.7 · Disc C · `177_4_CLIP_TEST.iso`

- **Inhalt:** Im Studio gebaut. Hauptmenü mit 3 Filmen und „Extras“ → Extras-Menü mit 1 Film und „Zurück“. Clips: 1. 25PsF, 2. 25p, 3. 3D 24p, 4. (Extras) 25PsF.
- **Simulator** (nachträglich mit v1.8.0): 0 Fehler, 0 Warnungen, 1 Hinweis (Menü-Schleife zeigt wieder das Hauptmenü, Test 12).

| Player | Fernseher | Ergebnis | Bemerkung |
|---|---|---|---|
| Sony UBP-X700 | LG OLED55C27LA (2D) | ✅ | Alle Menüs und Filme laufen, der 3D-Film in 2D. Tests 7–10. |
| Sony UBP-X700 | LG OLED55E6V (3D) | ✅ | 3D-Film schaltet auf 3D, danach Menü wieder in 2D. Tests 7–11. |

### 2026-09-28 · v1.7.6 · Disc C · `176_4_CLIP_TEST.iso`

- **Inhalt:** wie oben.
- **Simulator** (nachträglich mit v1.8.0): 1 Fehler, 3 Warnungen – Extras-Button als Rechenbefehl statt Seitenwechsel.

| Player | Fernseher | Ergebnis | Bemerkung |
|---|---|---|---|
| Sony UBP-X700 | nicht erfasst | ⚠ | Die 3 Filme im Hauptmenü laufen; der Button ins Extras-Menü bewirkt nichts (Tests 8, 10 ❌). `SetButtonPage` falsch codiert, behoben in v1.7.7. |

### 2026-09-27 · v1.4.0 · 3 Clips

- **Inhalt:** 3 Filme mit Menü. Clips: 1. 25PsF, 2. 25p, 3. 3D 24p.
- **Simulator:** – (vor v1.8.0).

| Player | Fernseher | Ergebnis | Bemerkung |
|---|---|---|---|
| Sony UBP-X700 | nicht erfasst | ✅ | 2D und 3D laufen. |
| Sony BDP-S4200 | nicht erfasst | ✅ | 2D und 3D laufen. |

---

## Vorlage für neue Einträge

```markdown
### JJJJ-MM-TT · vX.Y.Z · Disc A/B/C · `NAME.iso`

- **Inhalt:** Wie gebaut (Studio / alte Oberfläche), Menüs, Clips mit Format (z. B. 25PsF, 24p, 3D 24p), Kapitel, Spuren.
- **Simulator:** Ergebnis von `python tools/simulate_disc.py NAME.iso` (Fehler / Warnungen / Hinweise).

| Player | Fernseher | Ergebnis | Bemerkung |
|---|---|---|---|
| Sony UBP-X700 | LG OLED55E6V (3D) | ✅ | Tests …; was lief, was nicht. |
```

Danach die Tabelle „Stand je Player“ oben nachziehen.
