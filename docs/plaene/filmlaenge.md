# Plan: Filmlänge – Kapitel vor dem Ende und Längenprüfung

Stand: 2026-10-30 · Status: **zurückgestellt**, wird in einem Rutsch umgesetzt (verändert die Disc, braucht Simulator- und
Brenntest in 2D und 3D)

Zwei Funktionen, die beide die genaue Länge des Films brauchen:

- **A – Kapitelmarke kurz vor Filmende:** „Nächstes Kapitel“ springt im letzten Kapitel ans Ende des Films.
- **B – Längenprüfung:** Hinweis, wenn Ton, Untertitel oder Kapitel nicht zur Länge des Bildes passen.

Gemeinsame Grundlage ist Teil 0: die Filmlänge einmal beim Import ermitteln und im Projekt speichern.

---

## 0 – Grundlage: Länge des Bildes

**Problem:** Das Projekt kennt die Länge eines Films nicht. Eine rohe `.264` hat keine Längenangabe. ffprobe muss die
Bilder zählen und dafür die ganze Datei lesen, bei einem langen Film eine halbe bis eine Minute.

**Lösung:**

- Beim Zuweisen eines Videos an einen Film-Knoten (`FilmImporter.set_video`) die Bilder **einmal im Hintergrund** zählen
  (`ffprobe -count_packets`, ohne Decodieren). Bei `.m2ts` reicht die Längenangabe der Datei.
- Im Film speichern: Bildanzahl und Bildrate, dazu Pfad, Größe und Änderungszeit der Datei. Ändert sich die Datei,
  wird neu gezählt.
- Ältere Projekte: beim Öffnen im Hintergrund nachholen. Bis die Länge bekannt ist, prüfen die Funktionen aus A und B
  nichts und zeigen nichts an.
- Während des Zählens im Inspektor des Films dezent: „Länge wird ermittelt …“.
- Ton-Längen (WAV, AC-3, DTS, TrueHD …) liest ffprobe schnell aus der Datei. Sie werden beim Hinzufügen einer Spur
  ermittelt und an der Spur gespeichert, bei WAV nach dem Vorbereiten im bestehenden Worker.

---

## A – Kapitelmarke kurz vor Filmende

### Problem

Liegt das letzte Kapitel eines Films einige Minuten vor dem Ende, springt „Nächstes Kapitel“ am Player nicht weiter.
Der Zuschauer kommt nur über die Menü-Taste oder durch Vorspulen zurück ins Menü. Heute hilft nur ein zusätzliches
Kapitel kurz vor Ende ohne Button. Das löst eine Preflight-Warnung aus („Kapitel wird von keinem Button benutzt“).

Manchmal ist das Verhalten aber gewollt, etwa bei einem Hinweisfilm vor dem Hauptfilm, den man nicht überspringen
können soll.

### Lösung

- Pro Film ein Häkchen im Inspektor, vorgegeben **an**: „Mit ‚Nächstes Kapitel‘ ans Filmende springen“ (Arbeitstitel).
  Neues Feld am Film; fehlt es in älteren Projekten, gilt es als an.
- Beim Export bekommt jeder Film mit Häkchen eine zusätzliche Kapitelmarke **1 Sekunde vor dem Ende**, unabhängig davon,
  ob es eigene Kapitel gibt.
- Die Marke existiert **nur auf der Disc**, nicht in der Kapitelliste des Projekts. Darum:
  - keine Preflight-Warnung, kein Eintrag im Kapitelmenü-Generator, keine Änderung an der Kapitelliste im Inspektor
  - Kapitel-Buttons bleiben richtig: `resolve_chapter_jumps` findet ihre Marke über die Zeit, und die neue Marke kommt
    hinter alle bestehenden.

### Technik

- **Mit der Länge aus Teil 0** kommt die Zeit „Ende − 1 s“ einfach als weiterer Eintrag in `--custom-chapters` der
  tsMuxeR-Meta-Datei (`core/meta_builder.py`). Die Playlist muss dann nicht nachträglich verändert werden, das gilt auch
  für 3D.
- Ist die Länge beim Export noch unbekannt, wird sie dort gezählt (mit Fortschritt im Export-Protokoll).
- Rückfall, falls tsMuxeR die Marke nicht wie erwartet setzt: die OUT-Zeit aus der fertigen Playlist (`*.mpls`) lesen
  und die Marke dort anhängen. Bei 3D muss dabei die Startadresse von `ExtensionData` mitverschoben werden. Nur, wenn
  der einfache Weg nicht trägt.
- **Randfälle:**
  - Letztes eigenes Kapitel liegt in den letzten 3 s: keine zusätzliche Marke.
  - Film kürzer als 5 s: keine Marke.

### Prüfen

- Simulator: Die Marke erscheint in den Playlist-Marken. „Nächstes Kapitel“ im letzten Kapitel springt ans Ende,
  danach greift die Endaktion des Films.
- Brenntest auf Hardware (X700 und BDP-S4200), je ein 2D- und ein 3D-Film, mit und ohne Häkchen. Eintrag in
  `HARDWARE_TESTS.md`.
- Hinweis: Am Player zeigt die Disc ein Kapitel mehr an als das Menü (z. B. „7/7“). Das ist gewollt.

---

## B – Längenprüfung: Ton, Untertitel, Kapitel

### Ziel

Auffallen soll vor allem, wenn man beim Hineinziehen die **falsche Datei** erwischt (Ton vom Trailer beim Hauptfilm),
einen **veralteten Export** nach einer Schnittänderung oder **verschobene Zeitstempel**. Ein häufiger Fall: Die Timeline
in Resolve beginnt bei 01:00:00:00, der exportierte Film aber bei 00:00:00:00. Untertitel oder Kapitel, die mit der
Timeline-Zeit exportiert wurden, liegen dann eine Stunde zu spät.

**Grundsätze:**

- **Ton:** Bild und Ton sollen gleich lang sein. Ein Hinweis kommt in **beide Richtungen**, wenn die Spur kürzer oder
  länger als das Bild ist.
- **Untertitel und Kapitel:** Ein Hinweis kommt **nur, wenn etwas nach dem Filmende liegt**. Dass sie vor dem Ende
  aufhören, ist normal (z. B. keine Untertitel im Abspann, Kapitel nur im ersten Teil) und löst nichts aus.

### Prüfungen

| Was | Prüfung | Hinweis ab |
|---|---|---|
| **Tonspur** | Länge der Spur gegen Länge des Bildes, kürzer oder länger | 1 s Unterschied |
| **Untertitel** (`.srt`, `.sup`) | Ende des letzten Untertitels liegt nach dem Filmende | 1 s nach dem Ende |
| **Kapitel** | ein Kapitel liegt nach dem Filmende, egal ob aus der EDL oder von Hand gesetzt | nach dem Ende |

- Die Schwelle steht als eine Konstante im Code (vorgeschlagen 1 s, auch 0,5 s denkbar).
- **Stundenversatz:** Nur wenn etwas nach dem Ende liegt, prüft der Hinweis zusätzlich, ob es mit einer Stunde weniger
  in den Film passen würde (Zeiten ab 01:00:00, alle Zeiten minus 1 h liegen im Film). Dann nennt er die
  wahrscheinliche Ursache: „Die Zeiten beginnen bei 01:00:00 – vermutlich die Startzeit der Timeline. Bitte mit Start
  bei 00:00:00 exportieren.“ Korrigiert wird nicht automatisch. Liegt nichts nach dem Ende, gibt es auch keinen
  Hinweis auf einen Versatz, selbst wenn die Zeiten erst nach einer Stunde beginnen.
- **Zeiten lesen:**
  - `.srt`: Ende des letzten Eintrags (der vorhandene SRT-Leser aus `modules/subtitles`).
  - `.sup` (PGS): Zeitstempel der Segmente (Kopf „PG“ mit PTS in 90 kHz), letzter Wert.
  - Kapitel: die gespeicherten Zeiten des Films.
- Hinweis zum EDL-Import: `modules/edl_parser.py` übernimmt die Timecodes heute unverändert. Eine Timeline mit Start bei
  01:00:00:00 führt also genau zu diesem Fall. Die Prüfung macht ihn sichtbar.

### Wo der Hinweis erscheint

Grundsatz: bemerkbar, aber nicht nervig. Keine Fenster, keine Statusmeldungen.

- **Inspektor des Films**, direkt an der betroffenen Spur: eine kurze Zeile in Gelb, z. B. „4,2 s kürzer als das Bild“
  oder „endet 1:02:13 nach dem Filmende – Startzeit 01:00:00?“. So fällt es auf, sobald man Bild und Ton in den
  Film-Knoten zieht.
- **Film-Knoten im Graphen:** ein kleines Warnsymbol, wenn eine Spur nicht passt (wie bei anderen Hinweisen am Knoten).
- **Preflight:** eine Warnung je Film und Spur, Klick zeigt den Film-Knoten. Keine Fehler: Der Export bleibt möglich.
- Die Prüfung läuft erst, wenn die Länge des Bildes bekannt ist (Teil 0).

### Prüfen (Tests)

- Ton gleich lang, 0,4 s kürzer, 0,4 s länger: kein Hinweis. 3 s kürzer und 3 s länger: Hinweis.
- Ton vom kurzen Trailer beim langen Hauptfilm: Hinweis „… kürzer als das Bild“.
- SRT und SUP mit letztem Eintrag vor dem Ende (kein Hinweis) und nach dem Ende (Hinweis).
- **EDL-Import** (`modules/edl_parser.py`): Kapitel alle im Film (kein Hinweis); ein Kapitel nach dem Ende (Hinweis);
  Resolve-Timeline ab 01:00:00:00 bei einem 20-Minuten-Film (Hinweis mit Startzeit 01:00:00).
- SRT mit Zeiten ab 01:00:00 bei einem 20-Minuten-Film: Hinweis mit Startzeit. Dieselben Zeiten bei einem
  2-Stunden-Film, alle vor dem Ende: kein Hinweis.
- Kapitel von Hand nach dem Ende gesetzt: Hinweis.
- Film ohne bekannte Länge: keine Hinweise.

---

## Reihenfolge beim Umsetzen

1. Teil 0 (Länge ermitteln und speichern, Hintergrund, ältere Projekte).
2. Teil B (Hinweise, rein informativ, ohne Einfluss auf die Disc).
3. Teil A (Marke vor dem Ende, ändert die Disc), danach Simulator und Brenntest.

## Offene Fragen

- Bleibt es fest bei 1 s vor dem Ende, oder soll das einstellbar sein? (Vorschlag: fest)
- Endgültiger Text des Häkchens, Deutsch und Englisch.
- Schwelle für die Längenprüfung: 1 s oder 0,5 s?
