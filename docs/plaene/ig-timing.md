# Plan: Zeitstempel im Menü-Stream (IG) nach dem Decodermodell

Stand: 2026-11-27 · Status: **Verdacht, ungeprüft**. Wartet auf eine Referenz-Disc mit HDMV-Menü (multiAVCHD) und
Rückmeldung aus einem Hardware-Test.

Verdacht: Einzelne strenge Hardware-Player zeigen das Menü-Video, aber keine Buttons. Software-Player, Sony und
Panasonic zeigen dasselbe Menü korrekt an. Eine mögliche Ursache sind die Zeitstempel im IG-Stream, die das
Decodermodell der Spec nicht einhalten.

---

## Ist-Zustand

- **Ein PTS für alles:** `IGSCompiler.compile_pages` ([compiler.py](../../modules/igs/compiler.py)) verpackt ICS, PDS,
  alle ODS und END mit demselben PTS (`pts_start_45k * 2`).
- **Kein DTS:** `packetize_pes` ([pes.py](../../modules/igs/pes.py)) schreibt nur einen PTS (Flags `0x80`).
- **PCR = PTS:** `build_igs_m2ts` ([m2ts_writer.py](../../modules/m2ts/m2ts_writer.py)) setzt die einzige PCR im ersten
  Paket auf denselben Wert. Nach dem Modell sollen damit alle Daten im selben Moment ankommen, dekodiert und angezeigt
  sein.
- **Display Set:** Alle Seiten mit allen Buttons und je drei Grafiken (normal, ausgewählt, aktiviert) liegen in
  *einem* Display Set (Epoch Start).

## Soll laut Decodermodell

Quelle sind die Patente zum BD-Decodermodell, z. B. US 7366405, US 8126316, CA 2512058. Die Spec selbst liegt nicht vor.

- Jedes ODS hat einen DTS (Beginn des Dekodierens) und einen PTS (Grafik fertig im Object Buffer). Der Abstand
  ergibt sich aus Größe und Dekodierrate.
- Das ICS hat einen DTS am Anfang des Display Sets und einen PTS (Anzeige) **nach** dem Dekodieren aller ODS, plus der
  Zeit zum Löschen und Beschreiben der Grafikebene.
- Folgende Display Sets dürfen sich nicht überlappen: PTS(DSn[ICS]) ≤ DTS(DSn+1[ICS]).
- Die PCR muss vor dem ersten DTS liegen.
- **Offen:** die genauen Dekodier- und Übertragungsraten für die Berechnung (aus den Patenten heraussuchen).

## Warum Software-Player das nicht zeigen

libbluray dekodiert einen vorab geladenen IG-Stream mit STC = −1, also sofort und vollständig, ohne Zeitstempel
(`_init_ig_stream`, `graphics_processor.h`). Ein Menü, das in VLC oder ähnlichen Playern läuft, sagt über das Timing
nichts aus.

## Nebenbefunde (kein konkreter Verdacht)

Abweichungen vom üblichen Aufbau einer BD-m2ts im IG-Clip:

- keine SIT (PID 0x1F)
- PAT, PMT und PCR je nur einmal am Anfang
- kein Copy-Control-Descriptor (0x88) in der PMT

Gegengelesen und unauffällig: ICS-Aufbau (stream_model = vorab geladen, Feldfolge der Buttons, Längenfelder).

## Nächste Schritte

1. **Referenz:** IG-Clip einer Menü-Disc aus multiAVCHD auslesen und vergleichen: DTS/PTS je Segment, PCR, Aufteilung
   in Display Sets, SIT/PMT.
2. **Raten** aus den Patenten heraussuchen und die Berechnung festlegen.
3. **Test-ISOs** jeweils nur in einem Punkt geändert:
   - A: Minimalmenü (1 Seite, 1 Button), wie heute erzeugt
   - B: wie A, mit DTS/PTS pro Segment und PCR vor dem ersten DTS
   - C: ein großes Menü mit dem Timing aus B
   - optional D: zusätzlich SIT/Copy-Control wie bei tsMuxeR
4. **Gegenprobe** auf Sony UBP-X700, Sony BDP-S4200 und Panasonic DMP-BDT111, bevor etwas geändert wird.
5. **Simulator:** Zeitstempel und Puffergrenzen des IG-Streams prüfen und melden.
