# Plan: Menü-Stream (IG) wie bei multiAVCHD – Zeitstempel, Transport, Startseite

Stand: 2026-11-28 · Status: **Test-Disc gebaut (`tools/ig_test_disc.py`, Branch `test/ig-varianten`), auf dem Sony UBP-X700 laufen alle sechs Varianten; Rückmeldung vom Samsung ausstehend**.

Anlass: Auf einem Samsung BD-E5300 zeigt eine Disc aus v1.36.0 nur den Menü-Hintergrund, keine Buttons
(`HARDWARE_TESTS.md`, 2026-11-28). Dieselbe Disc läuft auf dem Sony UBP-X700 mit Menü. Software-Player, Sony und
Panasonic zeigen unsere Menüs korrekt an.

---

## Ist-Zustand

- **Ein PTS für alles:** `IGSCompiler.compile_pages` ([compiler.py](../../modules/igs/compiler.py)) verpackt ICS, PDS,
  alle ODS und END mit demselben PTS (`pts_start_45k * 2`).
- **Kein DTS:** `packetize_pes` ([pes.py](../../modules/igs/pes.py)) schreibt nur einen PTS (Flags `0x80`).
- **PCR = PTS:** `build_igs_m2ts` ([m2ts_writer.py](../../modules/m2ts/m2ts_writer.py)) setzt die einzige PCR im ersten
  Paket der IG-PID auf denselben Wert. Nach dem Modell sollen damit alle Daten im selben Moment ankommen, dekodiert und
  angezeigt sein.
- **Transport:** PAT, PMT (PCR_PID = IG-PID `0x1400`, nur der HDMV-Registrierungs-Deskriptor) und PCR je einmal am
  Anfang, keine SIT.
- **Display Set:** Alle Seiten mit allen Buttons und je drei Grafiken (normal, ausgewählt, aktiviert) liegen in
  *einem* Display Set (Epoch Start).
- **Startseite** (Menügruppen mit mehreren Seiten, seit v1.13): Seite 0 mit einem unsichtbaren Button (8×8),
  `auto_action`, Standard-Button 1, **kein** `default_activated_button` (`0xFFFF`). Die Befehle kopieren die gewünschte
  Seite aus GPR 7 und zeigen sie mit `SetButtonPage` **mit Register-Operanden** (`0x80000009`/`0x8000000A`, Flags im
  Befehl, Nummer im Register wie libbluray `_fetch_operand`).

## Referenz: multiAVCHD (gelesen am 2026-11-28)

Eine mit multiAVCHD erstellte BD-R (2017) mit 20 Menü-Clips (`90010`–`90069`, je 73 728 Byte). Gleicher Aufbau wie bei
uns: IG vorab geladen in einer SubPath vom Typ 3, eigener Hintergrund-Clip. Alle 20 Clips folgen denselben Regeln:

| | multiAVCHD | OpenBDAuth |
|---|---|---|
| ICS | DTS = Beginn des Display Sets, PTS = DTS + 23 328 | nur PTS |
| PDS | nur PTS = DTS des ICS | gleicher PTS |
| ODS | DTS = PTS des vorigen ODS (erstes: DTS des ICS), PTS = DTS + Dekodierdauer | gleicher PTS, kein DTS |
| END | nur PTS = PTS des letzten ODS | gleicher PTS |
| PCR | eigene PID `0x1001` (nur Adaptation Field), Wert 9, also 218 ms vor dem ersten DTS (19 628) | auf der IG-PID, gleich dem PTS |
| PMT | PCR_PID `0x1001`, HDMV-Registrierung **und Copy-Control `88 04 0f ff fc fc`** | nur HDMV-Registrierung |
| SIT | vorhanden (PID `0x1F`, PAT mit Programm 0 → `0x1F`) | fehlt |
| Display Sets | 1 (Epoch Start, 4 Seiten, 80 ODS) | 1 |
| Seite 0 | 2 unsichtbare Buttons mit `auto_action`, Standard-Button 0 **und `default_activated_button` 0**; Befehl `SetButtonPage` mit **festen Werten** (Button 0, Seite 2) | 1 Button, nur `auto_action`, Register-Operanden |

Gemessene Raten:

- **Dekodierdauer eines ODS** = `ceil(90000 · Breite · Höhe / 8 000 000)` Ticks (90 kHz), also 8 Mpx/s bzw. 64 Mbit/s
  bei 8 bit pro Pixel. Exakt bei allen ODS: 48×48 → 26, 40×48 → 22, 40×40 → 18, 8×8 → 1.
- **ICS: PTS − DTS = 23 328 = 2 × 11 664.** 11 664 = `ceil(90000 · 8 · 1920 · 1080 / 128 000 000)`, eine volle
  Grafikebene bei 128 Mbit/s. Naheliegend: einmal Ebene löschen, einmal beschreiben.
- **Lücke der Referenz:** Hier dauert das Dekodieren aller ODS (5 957) kürzer als das Löschen der Ebene (11 664). Was
  bei längerem Dekodieren gilt, zeigt die Disc nicht. Vorschlag für unsere Berechnung, der beide Fälle abdeckt:
  `PTS(ICS) = DTS(ICS) + max(Ebene löschen, Dekodieren aller ODS) + Ebene beschreiben`. Bei unseren Menüs (z. B. 36 ODS
  mit 380×70) liegt das Dekodieren ebenfalls darunter (≈ 10 800).

## Warum Software-Player das nicht zeigen

libbluray dekodiert einen vorab geladenen IG-Stream mit STC = −1, also sofort und vollständig, ohne Zeitstempel
(`_init_ig_stream`, `graphics_processor.h`). Ein Menü, das in VLC oder ähnlichen Playern läuft, sagt über das Timing
nichts aus. Leawo verhält sich offenbar genauso (Meldung des Nutzers).

## Verdachtsmomente für den Samsung

1. **Zeitstempel:** Mit PTS = PCR und ohne DTS wäre nach dem Modell alles im selben Moment dekodiert und angezeigt.
   Ein strenger Player kann das Display Set verwerfen.
2. **Startseite:** Ohne `default_activated_button` hängt das Weiterschalten allein an `auto_action` beim Auswählen des
   Standard-Buttons. Führt ein Player das beim ersten Anzeigen nicht aus, bleibt er auf der leeren Seite 0 stehen,
   genau wie beschrieben. multiAVCHD setzt beides.
3. **Register-Operanden** in `SetButtonPage`: Liest ein Player Bit 31 als „PSR“ statt als Flag, zeigt er Seite 0
   (PSR 9 = 0). multiAVCHD nimmt feste Werte. Für die Menü-Schleife (Seite und Button bleiben erhalten) brauchen wir
   aber Register.
4. **Transport:** PCR auf eigener PID, SIT, Copy-Control. Kein konkreter Verdacht, aber bei multiAVCHD und tsMuxeR so.

## Nächste Schritte

1. **Eine Test-Disc für den Nutzer, die die Varianten selbst durchschaltet.** Jede Variante ist eine eigene
   Menü-Playlist mit Hintergrund „Variante N“ und läuft 20 s, danach springt das MovieObject zur nächsten; nach der
   letzten wieder von vorn. Der Nutzer notiert nur, bei welchen Nummern Buttons erscheinen, und probiert dort einmal
   die Pfeiltasten. Jede Variante ist eine Menügruppe mit zwei Seiten (damit es eine Startseite gibt) und ändert genau
   einen Punkt gegenüber Variante 1:
   1. wie heute (Gegenprobe)
   2. Startseite mit `default_activated_button` (Register-Operanden bleiben)
   3. Startseite mit `SetButtonPage` mit festen Werten (wie multiAVCHD)
   4. Zeitstempel nach dem Decodermodell (Raten oben) und PCR 218 ms vor dem ersten DTS
   5. Transport wie multiAVCHD: PCR auf eigener PID, SIT, Copy-Control
   6. alles aus 2, 4 und 5 zusammen
2. **Gegenprobe** derselben Disc auf Sony UBP-X700, Sony BDP-S4200 und Panasonic DMP-BDT111 (alle Varianten müssen dort
   laufen), bevor etwas am Programm geändert wird.
3. **Umsetzen**, was auf dem Samsung den Unterschied macht. Wenn es die Register-Operanden sind: Menü-Schleife ohne
   Register auf der Startseite lösen (z. B. eine Startseite pro Zielseite).
4. **Simulator:** Zeitstempel und Puffergrenzen des IG-Streams prüfen und melden.
