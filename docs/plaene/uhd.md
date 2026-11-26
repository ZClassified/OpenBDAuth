# Plan: Ultra HD Blu-ray (UHD) – 2160p, SDR und HDR10, mit HDMV-Menüs

Stand: 2026-11-24 · Status: **Planung**, noch nichts umgesetzt. Zuerst kommt ein Machbarkeitstest (Phase 0). Erst
danach fällt die Entscheidung, ob UHD gebaut wird.

## Ziel und Grundsätze

OpenBDAuth erstellt **vollwertige UHD-Blu-rays**: 2160p HEVC in SDR und HDR10, mit HDMV-Menüs (Hauptmenü, Seiten,
Kapitel-, Ton- und Untertitelmenü). Das ist derselbe Funktionsumfang wie heute bei 2D.

- **Ganz oder gar nicht.** UHD erscheint erst in einem Release, wenn alles aus „Umfang“ fertig und auf Hardware
  geprüft ist. Bis dahin wird auf einem eigenen Branch entwickelt (`feature/uhd`), ohne halbe Zwischenstände in `main`.
- **Professioneller Workflow.** OpenBDAuth legt fest, welches Material angeliefert wird, und prüft es streng.
  Handymaterial, HLG, Dolby Vision Profil 8 und automatische Umwandlungen von Dynamikbereich oder Farbraum gibt es
  nicht. Was nicht passt, wird mit klarer Begründung abgelehnt.
- **Umfang = alles, was die Spezifikation für jeden UHD-Player zur Pflicht macht.** Optionale Formate (Dolby Vision,
  HDR10+) und BD-J gehören nicht dazu (siehe „Nicht im Umfang“).
- **Grundlage:** Die BD-ROM-Spezifikation Version 3 ist nicht frei verfügbar. Quellen sind die Quelltexte von
  **libbluray** (liest UHD-Discs, u. a. die UHD-Zusatzdaten in `index.bdmv`) und **tsMuxeR** (schreibt UHD-Discs,
  `--blu-ray-v3`). Dazu kommt der Vergleich mit dem, was tsMuxeR selbst erzeugt. Jede Angabe, die nicht belegt ist,
  steht in diesem Plan als **„zu prüfen“** und wird vor der Umsetzung geklärt.
- **3D und UHD schließen sich aus.** UHD-Blu-ray kennt kein 3D. Der Disc-Typ ist eine Projekteinstellung: Blu-ray
  (2D/3D) oder Ultra HD Blu-ray. Er gilt für die ganze Disc: Eine UHD-Disc spielt nur auf UHD-Playern, auch ihre
  HD-Filme; eine Blu-ray kann keine UHD-Filme enthalten.
- **Entscheiden, wo es hingehört.** Was für eine Disc es wird, steht an einer Stelle (Start-Knoten); was aus einem
  Film wird, entscheidet der Auftrag in Vorbereiten, im Rahmen des Disc-Typs. Kein zweiter Schalter, nichts wird
  still umgestellt (siehe „Bedienung“).

## Umfang

| Bereich | Inhalt |
|---|---|
| Video | 2160p HEVC Main10, 10 Bit 4:2:0. SDR in BT.709 und BT.2020, HDR10 (BT.2020, PQ, statische Metadaten). Dazu HD-Filme (1080p) auf derselben UHD-Disc, z. B. für Extras: als HEVC oder, falls erlaubt, als H.264 (Phase 0.8) |
| Bildraten | 23.976, 24, 25, 50, 59.94 progressiv (zu prüfen: vollständige Liste für 2160p und 1080p HEVC) |
| Anlieferung | Mezzanine (ProRes, DNxHR) oder fertig kodierter HEVC-Strom, siehe Phase 2 |
| Ton | wie heute (AC-3, DTS, LPCM, TrueHD und DTS-HD durchgereicht, Atmos und DTS:X im Kern-Strom enthalten) |
| Untertitel | PG in 1080, auf HDR-Filmen in korrekter Helligkeit |
| Menüs | HDMV/IGS wie heute; Hintergrund als HEVC im Dynamikbereich des Films |
| Disc-Struktur | `index.bdmv`, `MovieObject.bdmv`, `.mpls`, `.clpi` in Version 3 (`0300`) mit UHD-Zusatzdaten |
| Kapazität | BD-50, BD-66, BD-100 mit den jeweiligen Bitraten-Grenzen; BD-25 zu prüfen |
| Simulator | liest UHD-Discs, Vorschau von HDR auf SDR heruntergerechnet |
| Brennen | BD-R/BD-RE wie heute, dazu **BDXL** (BD-R XL TL/QL, BD-RE XL) auf allen drei Systemen |

### Bedienung

**Start-Knoten (Inspektor „Disc“): was für eine Disc es wird.** Dort stehen schon Disc-Name, Titel im Player und
Sprache der Disc; dazu kommen:

```
Disc-Typ      [ Blu-ray | Ultra HD Blu-ray ]
Disc-Größe    [ BD-25 | BD-50 ]            bei UHD: [ BD-50 | BD-66 | BD-100 ]
```

- Neue Projekte und ältere Projektdateien sind „Blu-ray“; für bestehende Nutzer ändert sich nichts.
- Bei UHD zeigt der Start-Knoten im Graph ein kleines „UHD“.
- Die **Disc-Größe steht schon hier** (v1.36.0, `DiscSettings.disc_size`); Vorbereiten zeigt sie nur an. Für UHD
  kommen die Größen BD-66 und BD-100 dazu, und die Auswahl hängt vom Disc-Typ ab.

**Vorbereiten (Auftrag): was aus einem Film wird, im Rahmen des Disc-Typs.**

- Blu-ray-Disc: wie heute (2D | 3D, 1080 | 720).
- UHD-Disc: Auflösung 2160 | 1080; der Dynamikbereich (HDR10, SDR BT.709/BT.2020) wird aus der Datei gelesen und
  angezeigt, nicht gewählt; kein 3D.
- Oben in Vorbereiten nur eine Anzeige „Disc: Ultra HD · BD-66 · ändern“; „ändern“ springt zum Start-Knoten.
- 4K-Quelle in einem Blu-ray-Projekt: Hinweis am Auftrag „Für 2160 den Disc-Typ auf Ultra HD stellen“.

**Was nicht passt, wird gemeldet, nicht umgestellt.** 3D-Film in einem UHD-Projekt, fertiger 2160p-Strom in einem
Blu-ray-Projekt, Film zu groß für die Disc: Film-Knoten rot markiert, die Vorprüfung nennt den Grund. Wird der
Disc-Typ umgestellt, während schon unpassende Filme im Projekt sind, sagt ein Hinweis vorher, welche das sind.

**Export und Brennen:** Hinweis „Diese Disc spielt nur auf UHD-Playern“, bevor gebrannt wird.

### Datenrate

Gebrannt wird voraussichtlich auf BD-25 oder BD-50, also mit deutlich weniger Platz als bei gepressten UHD-Discs
(BD-66/100). Deshalb wählt der User die Datenrate **bewusst aus festen Stufen**; es gibt **keine Automatik**, die
die Rate so weit senkt, bis der Film passt (ein 2-Stunden-Film auf BD-25 ergäbe sonst unbemerkt eine viel zu
niedrige Rate).

**Stufen je Auftrag (mittlere Datenrate des Videos; Annahmen, geprüft in Phase 0.10 und 0.11):**

| Auflösung | Stufen (Ø Mbit/s) | Vorgabe |
|---|---|---|
| 2160p | 60 · 45 · 35 · 25 | 45 |
| 1080p HEVC (z. B. Extras auf einer UHD-Disc) | 20 · 15 · 10 | 15 |

- Angeboten werden **nur Stufen, die auf BD-25 und BD-50 sicher gehen**: Mittlere Rate plus Ton bleibt mit Abstand
  unter der Spitzenrate, die der Player von einem gebrannten Rohling liest. Zeigt Phase 0.10 eine niedrigere Grenze,
  werden die Stufen gesenkt. Unter 25 Mbit/s gibt es für 2160p keine Stufe; dafür ist 1080p der bessere Weg.
- **Jede Stufe zeigt, wie viel Film damit auf die gewählte Disc passt**, gerechnet aus Disc-Größe minus Ton, Menüs
  und Reserve:

  ```
  Datenrate   [ 45 Mbit/s – passt bis ca. 2 h 15 min auf BD-50 ▾ ]
                60 Mbit/s – passt bis ca. 1 h 40 min
                45 Mbit/s – passt bis ca. 2 h 15 min
                35 Mbit/s – passt bis ca. 2 h 55 min
                25 Mbit/s – passt bis ca. 4 h 00 min
  ```

- Passt der Film mit der gewählten Stufe nicht, steht darunter der Ausweg („Passt nicht auf BD-25. Mit 25 Mbit/s
  oder auf BD-50 passt es.“). Gewählt wird nichts automatisch; Füllanzeige und Vorprüfung blockieren wie heute.
- **Die Spitzenrate** (HRD/VBV: `vbv-maxrate`, `vbv-bufsize`) legt das Programm je Disc-Größe fest, nicht der User.
  Annahme: 80 Mbit/s für den ganzen Transportstrom (zu prüfen, Phase 0.10).

**Kodierung: zwei Wege, der User wählt je Auftrag.**

| Weg | Ablauf | Größe | Wofür |
|---|---|---|---|
| Genau (Vorgabe) | zwei Durchläufe mit Ziel-Datenrate | trifft die Stufe | Spielfilm, Disc wird voll |
| Schnell | ein Durchlauf mit Ziel-Datenrate | ungefähr (Annahme ±10 %) | Kurzfilm, Platz reicht sicher |

Beide halten die Spitzenrate ein. Bei „Schnell“ rechnet die Füllanzeige mit Aufschlag und zeigt die Größe als
geschätzt; nach der Kodierung gilt die echte Größe.

### Nicht im Umfang

- **Dolby Vision:** lizenzpflichtig, braucht Profil 7 (zwei Ebenen) und proprietäre Werkzeuge.
- **HDR10+:** technisch möglich (x265 und tsMuxeR können es), in der Spezifikation aber optional. Später als eigene
  Erweiterung denkbar, nicht Teil von „ganz“.
- **BD-J (Java-Menüs):** eigenes Projekt in der Größe von OpenBDAuth. HDMV ist auf UHD-Discs ein übliches,
  vollwertiges Menüsystem.
- **AACS 2.0:** Kopierschutz für gepresste Discs. Selbst gebrannte Discs bleiben unverschlüsselt (siehe Phase 0).
- **Pop-up-Menüs:** gibt es heute auch bei 2D nicht (OpenBDAuth schreibt nur Always-On-Menüs). Später als eigene
  Funktion für 2D, 3D und UHD denkbar; die Helligkeit über HDR-Video wäre dann mit zu prüfen.

---

## Phase 0 – Machbarkeitstest (Entscheidung: bauen oder nicht)

Ziel ist, die großen Unbekannten auf Hardware zu klären, **bevor** Code in OpenBDAuth entsteht. Werkzeuge und Discs
werden von Hand erzeugt. Alle Ergebnisse kommen in `HARDWARE_TESTS.md`.

**Hardware:** Sony UBP-X700 an 4K-HDR-Fernseher. Brenner HL-DT-ST BP40NS20; ob er BDXL kann, klärt 0.1. Wenn nicht,
wird ein BDXL-fähiges Laufwerk besorgt.

**Material:** eigenes Filmmaterial des Entwicklers in 2160p: HDR10 mit Metadaten aus dem Grading sowie SDR in
BT.709 und BT.2020. Es wird nicht ins Repository aufgenommen und nicht veröffentlicht. In `HARDWARE_TESTS.md` stehen
nur die technischen Angaben (Codec, Auflösung, Bildrate, Dynamikbereich, Metadaten, Bitrate).

| Schritt | Frage | Vorgehen |
|---|---|---|
| 0.1 | Kann der BP40NS20 BDXL? | `GET CONFIGURATION` über `modules/burn/mmc.py`: unterstützte Profile und Schreibklassen. Ergebnis gilt für Phase 6 |
| 0.2 | Spielt der X700 eine **unverschlüsselte, selbst gebrannte** UHD-Disc ab? | Ausschnitt aus dem Testmaterial mit `x265 --uhd-bd` kodieren, tsMuxeR mit `--blu-ray-v3` ohne Menü, ISO auf BD-RE (BD-50 bzw. BD-25). Nacheinander: SDR BT.709, SDR BT.2020, HDR10. Prüfen: startet, Fernseher meldet HDR, Info-Anzeige des Players zeigt 2160p/HDR10 |
| 0.3 | Welche Medien nimmt der Player? | dieselbe Disc auf BD-25, BD-50 und (falls Laufwerk vorhanden) BD-R XL |
| 0.4 | Wie sieht eine UHD-Disc von tsMuxeR genau aus? | `index.bdmv`, `MovieObject.bdmv`, `.mpls`, `.clpi` aus 0.2 zerlegen und mit libbluray (`index_parse.c`, `mpls_parse.c`, `clpi_parse.c`) gegenlesen. Ergebnis: Feldliste in Anhang A |
| 0.5 | Funktioniert **unser HDMV-Menü** auf einer UHD-Disc? | Disc aus 0.2, von Hand ergänzt: IGS-Menü aus OpenBDAuth, Playlist und Clip-Infos auf `0300` gesetzt, Hintergrund als HEVC. Zwei Varianten: Hintergrund 2160p und 1080p |
| 0.6 | Ist H.264 als Menü-Hintergrund auf einer UHD-Disc erlaubt? | Variante von 0.5 mit dem heutigen H.264-Hintergrund. Klappt das nicht oder ist es laut libbluray/tsMuxeR nicht vorgesehen, wird der Hintergrund immer HEVC |
| 0.7 | Wie verhalten sich Menüs auf HDR? | (a) SDR-Menü, dann HDR-Film: schaltet der Fernseher um, wie lange ist er schwarz? (b) HDR10-Menü mit Grafik in verschiedenen Helligkeiten der Palette. (c) PG-Untertitel über HDR-Film. Ergebnis: Helligkeit, die für Weiß in der Grafik gilt (zu prüfen: wie der Player SDR-Grafik auf PQ abbildet, ob die Palette BT.2020 sein kann) |
| 0.8 | Dürfen HD-Filme auf einer UHD-Disc liegen, und in welchem Format? | Disc aus 0.2 um einen 1080p-Film ergänzen, einmal als H.264, einmal als HEVC. Spielt der X700 beide, auch per Menü-Sprung? Gegenlesen mit libbluray/tsMuxeR, ob H.264 auf `0300`-Discs vorgesehen ist. Ergebnis bestimmt, ob fertige HD-Extras unverändert übernommen werden können oder nach HEVC kodiert werden müssen |
| 0.9 | HDR- und SDR-Filme auf einer Disc? | HDR10-Film und SDR-Film auf derselben Disc mit Menü. Wie lange ist der Fernseher beim Wechsel schwarz? In welchem Dynamikbereich wirkt das Menü bei beiden Filmen gut? Ergebnis: ob Mischen angeboten wird und welchem Film das Menü folgt |
| 0.10 | Welche Spitzenrate liest der X700 ruckelfrei von gebrannten Rohlingen? | Testclips mit viel Bewegung und Korn, Spitzen 50 / 70 / 82 Mbit/s (gesamter Strom), je auf BD-R 25 und BD-R 50. Prüfen: läuft ohne Ruckeln und Aussetzer, auch beim Springen zwischen Kapiteln. Ergebnis: Spitzenrate des Programms (mit Abstand zur Grenze) und welche Stufen angeboten werden |
| 0.11 | Welche Datenrate reicht wofür? | Eigenes Material in 18 / 25 / 35 / 45 / 60 Mbit/s (2160p) und 10 / 15 / 20 Mbit/s (1080p HEVC), am 4K-Fernseher verglichen, ruhige Szenen und Szenen mit Korn/Rauschen. Ergebnis: Stufen und Vorgabe bestätigen oder anpassen; jeweils „Genau“ und „Schnell“ (Abweichung der Größe) |

**Entscheidung nach Phase 0:**

- **Weiter**, wenn 0.2 (HDR10), 0.5 und 0.7 auf dem X700 sauber laufen und 0.4 alle Felder erklärt. 0.8 und 0.9
  entscheiden nicht über das Ob, sondern über den Umfang: Fallen sie negativ aus, gibt es auf UHD-Discs nur
  2160p-Filme bzw. nur einen Dynamikbereich je Disc.
- **Abbruch**, wenn der X700 unverschlüsselte UHD-Discs verweigert oder sich das Verhalten der Menüs auf HDR nicht
  belegen lässt. Dann wird das Ergebnis hier und in `HARDWARE_TESTS.md` festgehalten, und UHD wird nicht gebaut.
- Ein zweiter UHD-Player (andere Marke) wäre für die Abnahme in Phase 8 sehr wertvoll, weil die Spezifikation Raum für
  Auslegung lässt.

---

## Phase 1 – Disc-Modell und Projekt

- Projektmodell (`core/disc_model.py`, `DiscSettings`): Disc-Typ `bluray` | `uhd`. Ältere Projekte sind `bluray`. Bedienung im Start-Knoten (siehe
  „Bedienung“). Bei `uhd` ist 3D gesperrt (Vorbereiten, Film-Knoten, Export).
- Disc-Größe: schon im Start-Knoten (v1.36.0); BD-66/BD-100 und die Abhängigkeit vom Disc-Typ ergänzen.
- Dynamikbereich je Film (`sdr709` | `sdr2020` | `hdr10`), aus der Datei gelesen. Ob Filme mit verschiedenem
  Dynamikbereich auf einer Disc liegen dürfen und welchem Film die Menüs folgen, entscheidet Phase 0.9; bis dahin
  lehnt die Vorprüfung Mischungen ab.
- Kapazität: BD-50, BD-66, BD-100 (BD-25 nach Ergebnis von 0.3), mit Füllanzeige und Bitraten-Grenzen je Größe
  (zu prüfen: maximale Rate des Transportstroms je Disc-Größe).
- `core/disc_rules.py`, `core/preflight.py`: Regeln für UHD (Disc-Typ passt zu jedem Film, Dynamikbereich, Bitrate,
  Bildraten, keine 3D-Inhalte, HD-Filme nur im Format, das Phase 0.8 belegt). Unpassende Filme: Knoten rot,
  Meldung mit Grund.

**Stand (2026-11-24, `feature/uhd`): Disc-Typ umgesetzt** – `DiscSettings.disc_type`, Auswahl im Start-Knoten mit
Rückfrage (nur UHD-Player, unpassende Filme genannt), Untertitel „Ultra HD Blu-ray“ am Start-Knoten, Anzeige in
Vorbereiten, Vorprüfung (3D auf UHD und HEVC auf Blu-ray: Fehler; H.264 auf UHD: Hinweis bis Phase 0.8). Solange
Phase 4 fehlt, sperrt die Vorprüfung den Export einer UHD-Disc. Disc-Größen bei UHD vorerst BD-25 und BD-50;
BD-66/BD-100 kommen mit BDXL (Phase 6). Tests: `tests/test_disc_type.py`.

**Stand (2026-11-24, `feature/uhd`): Disc ohne Menü exportierbar** (Zwischenschritt vor Phase 4). Ist der Disc-Typ
UHD, führt der Start-Knoten direkt auf den einzigen Film und gibt es kein Hauptmenü, schreibt tsMuxeR die ganze Disc
selbst (`MUXOPT --blu-ray-v3`, Spur `V_MPEGH/ISO/HEVC`): `index.bdmv`, `MovieObject.bdmv`, Playlist und Clip-Info in
Version 3 (`INDX0300`, `MOBJ0300`, `MPLS0300`, `HDMV0300`), als Ordner oder direkt als ISO. Ausgelassen bei UHD: der
1080i-Patch (nur H.264) und der Disc-Simulator (liest Version 3 noch nicht, Phase 7). Mit Menü oder mehreren Filmen
sperrt die Vorprüfung weiter. Damit lässt sich Phase 0.2/0.3 über den normalen Ablauf der App testen, und die
Dateien von tsMuxeR sind die Vorlage für die Feldliste (0.4). Tests: `tests/test_uhd_export.py`.

## Phase 2 – Anlieferung und Prüfung des Materials

Zwei Wege, beide fest beschrieben (Spezifikation für User in README und in der Oberfläche):

**A – Mezzanine:** ProRes 422 HQ/4444/4444 XQ oder DNxHR HQX/444, 3840×2160, 10 oder 12 Bit, progressiv. Bei HDR10:
BT.2020, PQ (SMPTE ST 2084) und die Metadaten aus dem Grading: Mastering Display (Primärfarben, Weißpunkt, min./max.
Helligkeit), MaxCLL, MaxFALL. Die Metadaten werden aus der Datei gelesen, sonst im Inspektor eingegeben (Pflicht).
Fehlende oder widersprüchliche Kennzeichnung (z. B. PQ ohne BT.2020) führt zur Ablehnung.

**B – Fertiger HEVC-Strom** (`.hevc`/`.h265` als Elementarstrom): wird nicht neu kodiert, sondern geprüft:

- Profil Main10, Level und Tier passend zur Auflösung (zu prüfen: Level 5.1 High Tier für 2160p), 4:2:0, 10 Bit.
- Auflösung, Bildrate, progressiv.
- GOP-Struktur (Abstand der Einstiegspunkte, zu prüfen: Grenze je Bildrate), Access Unit Delimiter, Wiederholung von
  VPS/SPS/PPS.
- HRD/VBV-Parameter und Einhaltung der Puffer über den ganzen Strom.
- VUI: Farbraum, Übertragungsfunktion und Matrix passend zum Dynamikbereich der Disc.
- HDR10: SEI Mastering Display und Content Light Level vorhanden, Werte plausibel.
- Kein Dolby-Vision-RPU, keine HDR10+-SEI (sonst Ablehnung oder ausdrücklich entfernen, zu entscheiden).

Umsetzung als eigenes Paket `hevctools/`, genauso aufgebaut wie `mvctools/` (NAL-Einheiten, VPS/SPS/PPS, SEI, VUI,
Prüfbericht). Dieselbe Prüfung läuft auch nach jeder eigenen Kodierung aus Weg A.

**Stand (2026-11-24, `feature/uhd`): `hevctools/` ist umgesetzt** – `python -m hevctools.check FILM.hevc [--range
hdr10]` und `python -m hevctools.analyze` (ausführlicher Bericht). Geprüft wird alles aus der Liste oben; die
Puffer-Prüfung ist eine Näherung mit gleichem Bildabstand. Dolby Vision und HDR10+ werden abgelehnt (nicht entfernt).
Tests mit selbst erzeugten x265-Clips (`tests/test_hevctools.py`).

Die Regeln stammen aus dem, was **x265 4.3 mit `--uhd-bd` erzwingt** (ausprobiert): Level 5.1 High Tier, Main 10,
4:2:0, 10 Bit, progressiv, 1920×1080 oder 3840×2160, Primärfarben BT.709/BT.2020, Übertragung BT.709/BT.2020-10/PQ
(kein HLG), Matrix BT.709/BT.2020, geschlossene GOPs, Keyframe-Abstand höchstens die Bildrate (eine Sekunde),
höchstens 6 Referenzen, AUD, HRD, Parameter-Sets an jedem Einstiegspunkt. Noch zu belegen (tsMuxeR/libbluray,
Phase 0.4): Bildraten-Liste, ob HDR-SEI an jedem Einstiegspunkt stehen müssen.

**Wichtig für Phase 3:** Passt eine Bedingung nicht (z. B. 1280×720 oder fehlende Farbkennzeichnung), meldet x265
nur „uhd-bd: Disabled“ und **kodiert trotzdem weiter**. Jede eigene Kodierung muss deshalb mit `hevctools` geprüft
werden, und die Farbkennzeichnung muss immer ausdrücklich übergeben werden.

## Phase 3 – Kodierung (Prepare)

- Auftrag auf einer UHD-Disc: Auflösung 2160 | 1080 (Bedienung siehe oben); 1080 ergibt einen HD-Film im Format aus
  Phase 0.8.

- Neues x265-Profil in `modules/prepare/jobs.py`: `--uhd-bd` als Grundlage, Main10, HRD, AUD, wiederholte Header,
  GOP nach Bildrate, Farbkennzeichnung, bei HDR10 `--master-display` und `--max-cll` aus dem Projekt.
  Nur Software-x265, keine Hardware-Encoder (halten die Regeln nicht verlässlich ein).
- Datenrate als feste Stufe des Auftrags, Kodierung „Genau“ (zwei Durchläufe) oder „Schnell“ (ein Durchlauf),
  beide mit der Spitzenrate der Disc-Größe (siehe „Datenrate“). Die Füllanzeige rechnet mit.
- Prüfen, ob die mitgelieferte ffmpeg-Version (`tools/fetch_tools.py`) auf allen drei Systemen `libx265` mit 10 Bit
  enthält. Sonst x265 als eigenes Werkzeug mitliefern. Windows: ja (ffmpeg 9.0.2 essentials, x265 4.3, 8/10/12 Bit).
  Linux und macOS: offen, zeigt ein CI-Lauf von `feature/uhd` (die x265-Tests werden sonst übersprungen).
- Selbsttest (`modules/prepare/selftest.py`): kurzer UHD-Clip, den ffmpeg selbst erzeugt (Testbild, kein fremdes
  Material), danach Prüfung mit `hevctools`. Automatische Tests verwenden ebenfalls nur selbst erzeugte Clips.
- Dauer ehrlich anzeigen: 4K-HEVC ist um ein Vielfaches langsamer als 1080p-H.264. Die Warteschlange über Nacht ist
  hier der Normalfall.
- **MaxCLL und MaxFALL messen** (Idee aus dem ersten Resolve-Test): HDR10 braucht neben dem Mastering-Display zwei
  Angaben über den Inhalt – MaxCLL (hellstes einzelnes Pixel des Films, in Nits) und MaxFALL (durchschnittliche
  Helligkeit des hellsten Bildes). Der Fernseher richtet danach sein Tone Mapping aus. Resolve schreibt sie in
  ProRes meist nicht mit; heute trägt man sie ein oder setzt 0/0 („unbekannt“, erlaubt, der Fernseher nimmt dann
  den ungünstigsten Fall an). Vorbereiten soll sie selbst messen können: jedes Bild dekodieren, PQ-Werte in Nits
  umrechnen (je Pixel das Maximum von R, G, B), daraus das hellste Pixel und den hellsten Bilddurchschnitt. Ablauf:
  eigener Schritt vor der Kodierung, wenn die Datei keine Werte mitbringt (oder auf Wunsch), Ergebnis im
  Inspektor und in der Kodierung. Zu prüfen: Weg der Messung (ffmpeg-Filter oder eigene Auswertung der Bilder,
  ohne zusätzliche Bibliotheken) und Dauer bei einem Spielfilm in 4K; ob die Messung im ersten Durchlauf von
  „Genau“ mitlaufen kann.

**Stand (2026-11-24, `feature/uhd`): Backend umgesetzt** in `modules/prepare/uhd.py` (noch ohne Oberfläche, die
folgt nach dem Disc-Typ aus Phase 1): Quellprüfung, x265-Befehle für „Genau“ und „Schnell“, HDR10-Metadaten aus der
Datei (erstes Bild) oder angegeben, Prüfung jedes Ergebnisses mit `hevctools`, Platzbedarf inklusive x265-Statistik
(„Genau“ bei 2160p ca. 36 KB je Bild, also rund 6 GB bei 2 Stunden). Preset `medium`. Tests:
`tests/test_prepare_uhd.py` (auch echte Kodierungen aus ProRes- und HDR10-Testquellen). Erkenntnisse:

- Die x265-Statistik wird relativ zum Zielordner benannt: `-x265-params` trennt an „:“, ein Windows-Pfad würde dort
  zerbrechen.
- ffmpeg schreibt die Farbkennzeichnung bei ProRes nicht vollständig aus den Ausgabeoptionen; für x265 ist das egal,
  weil die Kennzeichnung direkt in `-x265-params` steht.
- Ein roher `.hevc`-Strom als Quelle hat keine verlässliche Bildrate (ffprobe rät); das ist Weg B (nur prüfen).

**Stand (2026-11-24, `feature/uhd`): Oberfläche umgesetzt.** Auf einer UHD-Disc wird jedes Video ein UHD-Auftrag
(2160p bei 4K-Quellen, sonst 1080p). Inspektor: Auflösung, Datenrate mit „passt bis ca. … auf BD-xx“ (Platz abzüglich
Reserve 4 % und allem anderen auf der Disc) und Ausweg, wenn es nicht passt; Genau/Schnell; Dynamik mit den
HDR10-Werten; Eingabe der Grading-Werte (Mastering-Display DCI-P3 D65 oder BT.2020, Helligkeit, MaxCLL/MaxFALL),
wenn die Datei keine mitbringt – ohne sie startet der Auftrag nicht. Wurde der Disc-Typ nach dem Hinzufügen
umgestellt: Hinweis und „An den Disc-Typ anpassen“. Auf einer Blu-ray nennt die Ablehnung einer 4K-HDR-Quelle den
Weg über den Disc-Typ. `.hevc` lässt sich in Film-Knoten übernehmen, Kenndaten und Bildrate aus dem SPS
(`hevctools.stream.quick_info`). Tests: `tests/test_prepare_uhd_page.py`.

**Stand (2026-11-24, `feature/uhd`): Weg B umgesetzt.** Ein `.hevc` im Film-Knoten wird mit `hevctools` in einem
eigenen Prozess geprüft (Fortschritt, Abbrechen; `modules/prepare/checks.check_hevc`). Fehler werden ein
Hinweis mit severity „error“ (Vorprüfung blockiert, Bestätigen hilft nicht), Warnungen ein bestätigbarer Hinweis,
ein Abbruch der Hinweis „nicht geprüft“. Dauer und Dynamikbereich gehen in die Kenndaten des Films. Ergebnisse aus
Vorbereiten (dort schon geprüft) werden beim Übernehmen nicht noch einmal geprüft (Größe und Änderungszeit
gleich). Vorprüfung: verschiedene Dynamikbereiche auf einer UHD-Disc vorerst ein Fehler (bis Phase 0.9). Tests:
`tests/test_hevc_import.py`.

## Phase 4 – Disc-Struktur Version 3

Alle selbst geschriebenen Dateien bekommen eine UHD-Variante. Die Bluray-Variante bleibt unverändert (Tests sichern
das ab). Die Feldliste aus Anhang A (Phase 0.4) ist die Vorlage.

- `modules/bdmv/index_generator.py`: `INDX0300`, UHD-Zusatzdaten (Disc-Typ/Größe, 4K-Kennung, HDR-Kennungen; zu
  prüfen: genauer Aufbau laut libbluray).
- `modules/bdmv/movie_object_generator.py`: `MOBJ0300` (zu prüfen: ob sich außer der Version etwas ändert).
- `modules/mpls/mpls_generator.py`: `MPLS0300`, Videotyp `0x24` (HEVC), Videoformat 2160p, in der STN-Tabelle
  Dynamikbereich und Farbraum (zu prüfen: Lage der Felder), UHD-Zusatzdaten der Playlist, falls vorhanden.
- `modules/mpls/clpi_generator.py`: `HDMV0300`, ProgramInfo mit HEVC-Attributen, EP-Map für HEVC, Zusatzdaten.
- `core/meta_builder.py`: `--blu-ray-v3` und HEVC-Spuren für tsMuxeR; Abgleich, dass die Dateien von tsMuxeR und
  unsere eigenen zusammenpassen (gleiche Version, gleiche Kennungen).
- `modules/udf250_writer.py`, `modules/iso_tools.py`: Größen über 50 GB (BD-66/100) testen, Volume-Größe und
  Lage der Anker bei mehr Sektoren. Zu prüfen: ob UHD-Discs am UDF etwas anders erwarten als Blu-ray.
- Tests: Bytevergleich mit Referenzdateien aus Phase 0.4, Gegenlesen mit dem Simulator.

## Phase 5 – Menüs und Untertitel auf UHD

- Grafik bleibt 1920×1080; `modules/igs` ändert sich im Kern nicht.
- **Menü-Hintergrund** (`modules/menu_author.py`): wird mit x265 statt x264 kodiert, in Auflösung (nach Phase 0.5)
  und Dynamikbereich der Disc. Bei HDR10 wird das Hintergrundbild aus SDR nach PQ umgerechnet, mit einem festen
  Weißwert für Grafik (Ausgangspunkt 203 Nits nach ITU-R BT.2408; endgültiger Wert nach Phase 0.7). Das Ergebnis
  bekommt eigene HDR10-Metadaten.
- **Palette der Buttons** (`modules/igs/palette.py`): Umrechnung so, dass Buttons auf HDR-Hintergrund und über dem
  HDR-Film in der gewünschten Helligkeit erscheinen. Abhängig davon, was Phase 0.7 zur Abbildung von Grafik belegt.
- **PG-Untertitel** (`modules/subtitles/srt_to_sup.py`): dieselbe Regel für die Helligkeit wie bei den Buttons. Für
  User einstellbar: Helligkeit der Untertitel in Nits (mit Vorgabe).
- **Vorschau im Viewer** (`gui/studio/viewer.py`): Der Bildschirm der Oberfläche ist SDR. HDR-Hintergründe und
  Filmbilder werden für die Anzeige heruntergerechnet (ffmpeg `zscale` + `tonemap`). Der Hinweis „Vorschau, auf dem
  Fernseher heller“ wird angezeigt. Die Grafik wird so gezeigt, wie sie relativ zum Bild wirkt.

## Phase 6 – Brennen und BDXL

- `modules/burn/checks.py`, `model.py`: Medien BD-R XL (TL 100 GB, QL 128 GB) und BD-RE XL erkennen, Kapazität aus
  dem Laufwerk lesen, Laufwerk ohne BDXL-Unterstützung mit klarer Meldung ablehnen.
- Windows: zu prüfen, ob IMAPI2 BDXL schreibt; der eigene MMC-Weg aus v1.34.0 (`modules/burn/mmc.py`) gilt für eine
  leere BD-R XL ebenfalls (zu prüfen: Profil 0x41 auch bei BDXL, Verhalten von `CLOSE SESSION`).
- macOS (`hdiutil`/`drutil`) und Linux (xorriso): BDXL-Unterstützung prüfen und testen.
- Prüfen der Disc gegen die ISO (`modules/burn/verify.py`) bei 66–128 GB: Dauer anzeigen.

## Phase 7 – Simulator

- `modules/bdsim/disc.py`: Dateien in Version 3 und UHD-Zusatzdaten lesen.
- `modules/bdsim/hdmv.py`: Player-Register für einen UHD-Player (zu prüfen: welche PSR die 4K- und HDR-Fähigkeit
  melden und was Discs dort abfragen).
- `modules/bdsim/source.py`: HEVC-Hintergrund dekodieren, HDR für die Anzeige herunterrechnen.
- Prüfbericht des Simulators: Version aller Dateien einheitlich, Dynamikbereich einheitlich, Kennungen in `index.bdmv`
  passen zum Inhalt.

## Phase 8 – Abnahme auf Hardware (Bedingung für das Release)

Auf dem X700 am HDR-Fernseher, mit dem eigenen Testmaterial aus Phase 0, eingetragen in `HARDWARE_TESTS.md`:

- je eine Disc in SDR BT.709, SDR BT.2020 und HDR10, jeweils mit Menü (Seiten, Kapitel, Ton, Untertitel)
- Weg A (Mezzanine) und Weg B (fertiger HEVC-Strom)
- BD-50 und BD-66 oder BD-100 (gebrannt mit OpenBDAuth)
- mehrere Filme auf einer Disc, Wechsel Menü ↔ Film ohne Umschalten des Fernsehers
- Untertitel über HDR in angenehmer Helligkeit
- Disc gegen ISO geprüft
- nach Möglichkeit ein zweiter UHD-Player einer anderen Marke

Erst wenn alles besteht, wird `feature/uhd` in `main` übernommen und als eine Version veröffentlicht.

---

## Offene Fragen (Sammlung, wird in Phase 0 abgearbeitet)

1. Aufbau der UHD-Zusatzdaten in `index.bdmv`, `.mpls`, `.clpi` (Anhang A).
2. Erlaubte Video-Kombinationen auf einer UHD-Disc: HD-Filme als 1080p HEVC oder H.264 (0.8), H.264 als
   Menü-Hintergrund (0.6).
3. Bildraten für 2160p und 1080p HEVC.
4. Bitraten-Grenzen je Disc-Größe (Video und Transportstrom), BD-25 überhaupt zulässig.
5. Grenzen für GOP, Level und Tier. Teilweise belegt durch x265 `--uhd-bd` (Level 5.1 High Tier, geschlossene
   GOPs, höchstens eine Sekunde, höchstens 6 Referenzen); Gegenprobe mit tsMuxeR/libbluray offen.
6. Wie der Player SDR-Grafik (IG, PG) auf HDR abbildet; ob die Palette BT.2020 sein darf.
7. Player-Register für UHD im Simulator.
8. BDXL unter IMAPI2, macOS und Linux; Profil und Abschluss bei BD-R XL.
9. Enthält die mitgelieferte ffmpeg-Version auf allen Systemen `libx265` mit 10 Bit? Windows: ja; Linux/macOS: CI-Lauf.
10. HDR- und SDR-Filme auf einer Disc: Umschalten des Fernsehers, Dynamikbereich der Menüs (0.9).
11. Spitzenrate von gebrannten BD-R 25/50 im Player und Stufen der Datenrate (0.10, 0.11).
12. MaxCLL/MaxFALL selbst messen: Verfahren und Dauer (Phase 3).

## Anhang A – Feldliste Version 3

Wird in Phase 0.4 aus den Dateien von tsMuxeR und den Quelltexten von libbluray erstellt.
