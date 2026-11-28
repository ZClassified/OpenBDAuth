# Plan: Untertitel in der Auflösung des Films

Stand: 2026-11-28 · Status: **umgesetzt in v1.40.1**, auf dem Sony UBP-X700 bestätigt (`HARDWARE_TESTS.md`). Anlass: Meldung zu v1.36.0 (Samsung BD-E5300, `HARDWARE_TESTS.md`).

Ein Trailer in 720p hatte fertige PGS-Untertitel (`.sup`) in 1920×1080. OpenBDAuth hat das nicht bemerkt. Beim
Nachsehen zeigte sich: Der eigene SRT-Wandler erzeugt denselben Fehler, denn er rendert immer in 1920×1080.

---

## Ist-Zustand

- **Fertige `.sup`** gehen unverändert an tsMuxeR (`MetaBuilder._ensure_sup_path`, [meta_builder.py](../../core/meta_builder.py)).
  Ihre Auflösung wird nirgends gelesen, weder beim Import noch im Preflight.
- **`.srt` → `.sup`** ([srt_to_sup.py](../../modules/subtitles/srt_to_sup.py)): fest 1920×1080. Das betrifft die
  Bildposition (`x = (1920 - w) // 2`, `y = 1080 - h - 70`), die Video-Größe im PCS (`video_width/height`, in jeder
  Anzeige- und Lösch-PCS) und die Schriftgröße 48 px sowie den Abstand 70 px nach unten, beide für 1080 gewählt.
  Bei einem 720p-Film liegen die Untertitel damit außerhalb des Bildes oder werden vom Player verworfen.
- **Bildrate beim Wandeln:** `_ensure_sup_path` nimmt `self.state.fps`, das ist immer die Rate des **ersten** Films
  (`ProjectState.fps` → `titles[0].fps`). Eine SRT für einen Trailer bekommt also die Bildrate des Hauptfilms
  (`frame_rate` im PCS, Raster der Zeitstempel).

## Soll

Die Untertitel haben dieselbe Auflösung wie das Video (BD-ROM Part 3: `video_descriptor` im PCS gleich dem Video).

### 1. SRT in der Auflösung des Films rendern

- **Größe der Untertitel** wie bei tsMuxeR (`TextToPGSConverter::enlargeCrop` in
  [textSubtitles.cpp](https://github.com/justdan96/tsMuxer/blob/master/tsMuxer/textSubtitles.cpp), gelesen am
  2026-11-28), aber bei SD nach der Höhe:

  | Video | PCS `video_width × video_height` |
  |---|---|
  | 1920×1080, 1440×1080 | 1920×1080 |
  | 1280×720 | 1280×720 |
  | 720×576 | 720×576 |
  | 720×480 | 720×480 |

  tsMuxeR prüft nur die Breite (> 1280 → 1920×1080, > 720 → 1280×720) und unterscheidet SD über die Bildrate (25/50 →
  576). Die Bildrate liest es dabei, bevor sie gesetzt ist; SD wird dort vermutlich immer 720×480. Anamorphes Video
  behandelt tsMuxeR nicht besonders.
- `convert_srt_to_sup(…, width, height)` bzw. `build_sup_cue_bytes(…, width, height)`; Position und PCS aus diesen
  Werten.
- Schriftgröße und Abstand nach unten mit der Bildhöhe skalieren: 48 px und 70 px bei 1080, also 32 px und 47 px
  bei 720, 26 px und 37 px bei 576, 21 px und 31 px bei 480.
- **1440×1080:** Die Untertitel-Fläche ist 1920×1080 und wird nicht gestaucht, der Text wird normal gerendert.
- **SD 16:9 (anamorph):** Der Player zieht die 720 Pixel breite Fläche auf 16:9. Der Text wird deshalb um das
  Pixel-Seitenverhältnis waagerecht gestaucht gerendert (SAR aus `video_details`, z. B. 64:45 bei 576, 32:27 bei 480),
  damit er auf dem Fernseher nicht breitgezogen aussieht. Bei SD 4:3 genauso, nur mit kleinem Faktor (SAR 16:15 →
  15/16), denn der Player skaliert auch dort.
- `_ensure_sup_path` bekommt den Titel und nimmt dessen Auflösung (aus `video_details`) und dessen Bildrate statt
  `self.state`.
- Ohne bekannte Auflösung (alte Projekte ohne `video_details`) bleibt es bei 1920×1080.

### 2. Fertige `.sup` prüfen

- Beim Import und im Preflight aus der ersten PCS (Segment `0x16`) `video_width` und `video_height` lesen. Das sind
  wenige Bytes am Anfang der Datei: `PG`, PTS, DTS, Typ, Länge, dann die Video-Größe.
- Weicht die Größe vom Video ab: Warnung am Film, z. B. „Untertitel ‚POR‘ sind für 1920×1080 erstellt, das Video ist
  1280×720. Auf vielen Playern erscheinen sie an falscher Stelle oder gar nicht.“ Mit dem Rat, eine `.sup` in der
  Größe des Videos zu verwenden oder die Untertitel als `.srt` zu importieren.
- Warnung, kein Fehler: Manche Player skalieren selbst.
- Neu prüfen, wenn sich das Video des Films ändert.

### Nicht geplant

- Fertige `.sup` umrechnen (Bilder skalieren und neu packen). Das wäre verlustbehaftet und aufwendig; die Warnung
  reicht.

## Offen

- **Auf dem Player bestätigen:** 1440×1080 mit Fläche 1920×1080 und das Stauchen bei SD 16:9 sind aus tsMuxeR und
  Foren abgeleitet, nicht aus der Spec. Vor dem Release eine Test-ISO mit vier kurzen Filmen (720p, 1440×1080, SD 4:3,
  SD 16:9), jeweils mit SRT, auf dem Sony UBP-X700 prüfen: Lage, Größe, Seitenverhältnis der Schrift.
- **Ältere Projekte:** Haben sie `.srt`-Untertitel an 720p-Filmen, ist die nächste Disc nach dem Fix richtig. Ein
  Hinweis beim Öffnen ist nicht nötig, denn gewandelt wird erst beim Export.

## Tests

- SRT an Filmen mit 1920×1080, 1440×1080, 1280×720, 720×576, 720×480 (4:3 und 16:9): PCS-Größe, Position im Bild,
  Schriftgröße, Stauchen nur bei SD 16:9.
- SRT am zweiten Film mit anderer Bildrate als der erste: `frame_rate` im PCS.
- `.sup` mit 1920×1080 an einem 720p-Film: Warnung; passende `.sup`: keine; unlesbare Datei: keine Warnung, kein Absturz.
- Hardware: ein 720p-Film mit SRT auf dem Sony UBP-X700.
