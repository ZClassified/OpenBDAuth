# Plan: Untertitel in der Auflösung des Films

Stand: 2026-11-28 · Status: **geplant**. Anlass: Meldung zu v1.36.0 (Samsung BD-E5300, `HARDWARE_TESTS.md`).

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

- `convert_srt_to_sup(…, width, height)` bzw. `build_sup_cue_bytes(…, width, height)`; Position und PCS aus diesen
  Werten.
- Schriftgröße und Abstand nach unten mit der Bildhöhe skalieren: 48 px und 70 px bei 1080, also 32 px und 47 px
  bei 720, 23 px und 34 px bei 480, 26 px und 37 px bei 576.
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

- **1440×1080 (anamorph):** Muss das PCS 1440×1080 oder 1920×1080 tragen? Eine Referenz-Disc oder tsMuxeR mit einem
  Test-Stream ansehen.
- **SD (720×576, 720×480):** Größe der Schrift für 4:3 und 16:9 (anamorph) festlegen.
- **Ältere Projekte:** Haben sie `.srt`-Untertitel an 720p-Filmen, ist die nächste Disc nach dem Fix richtig. Ein
  Hinweis beim Öffnen ist nicht nötig, denn gewandelt wird erst beim Export.

## Tests

- SRT an Filmen mit 1920×1080, 1280×720, 720×576: PCS-Größe, Position im Bild, Schriftgröße.
- SRT am zweiten Film mit anderer Bildrate als der erste: `frame_rate` im PCS.
- `.sup` mit 1920×1080 an einem 720p-Film: Warnung; passende `.sup`: keine; unlesbare Datei: keine Warnung, kein Absturz.
- Hardware: ein 720p-Film mit SRT auf dem Sony UBP-X700.
