# MVC / Blu-ray 3D – Wissenssammlung

Lebendes Dokument. Status-Markierungen:
- **(Referenz)** – so im Output des Referenz-Encoders gefunden, der nachweislich auf Hardware-Playern läuft
  → zeigt, was *akzeptiert* wird, nicht zwingend, was *vorgeschrieben* ist
- **(Praxis)** – übliche Werte auf Blu-ray-3D-Discs
- **(unbestätigt)** – Vermutung, noch durch Analyse/Test abzusichern

Analyse-Werkzeug: `python -m mvctools.analyze BASE.264 --mvc DEP.mvc [--frames N] [--json out.json]`

## Quellen

- ITU-T H.264, Annex H (Multiview Video Coding) – frei bei der ITU erhältlich
- ITU/JVT-Konformitätsbitstreams für MVC
- tsMuxeR (Open Source) – MVC-Parsing und Muxing
- edge264 (Open Source, C) – MVC-fähiger Decoder
- JMVC – Referenz-Encoder/-Decoder
- Eigene Analysen: Output des Referenz-Encoders und eigene Test-Discs

## NAL-Typen (H.264)

| Typ | Bedeutung | Wo |
|---|---|---|
| 1 / 5 | Slice Non-IDR / IDR | Base View |
| 6 | SEI | beide |
| 7 / 8 | SPS / PPS | Base View (PPS auch Dependent) |
| 9 | Access Unit Delimiter | Base View, jede AU **(Referenz)** |
| 10 | End of Sequence | Dependent View, am Ende jedes GOP außer dem letzten **(Referenz)** |
| 14 | Prefix-NAL | **nicht** vorhanden – Base View ist reines AVC **(Referenz)** |
| 15 | Subset-SPS | Dependent View, an jedem IDR **(Referenz)** |
| 20 | Coded Slice Extension (MVC-Slice) | Dependent View |
| 24 | Dependent-View-Delimiter (BD-spezifisch, gleiche Syntax wie AUD) | Dependent View, jede AU **(Referenz)** |

## MVC-NAL-Header-Erweiterung (NAL 14/20, 3 Byte nach dem NAL-Header)

`svc_extension_flag(1)=0, non_idr_flag(1), priority_id(6), view_id(10), temporal_id(3),
anchor_pic_flag(1), inter_view_flag(1), reserved_one_bit(1)=1`

Referenz-Encoder: `view_id = 1`, `priority_id = 0`, `temporal_id = 0`, `inter_view_flag = 0` (rechtes Auge wird
von niemandem referenziert), `anchor_pic_flag = 1` genau an den IDR-Bildern.

## Blu-ray-3D-Rahmenbedingungen

| Punkt | Wert | Status |
|---|---|---|
| Profil Base View | High (100), Level 4.1, constraint_flags 0 | **(Referenz)**, **(Praxis)** |
| Profil Dependent View | Stereo High (128), Level 4.1 | **(Referenz)**, **(Praxis)** |
| Max. Bitrate Base View | 40 Mbit/s (CPB 30 Mbit) | **(Praxis)** |
| Max. Bitrate gesamt (beide Views) | 60 Mbit/s (CPB 60 Mbit) | **(Praxis)**: MVC-VUI-HRD |
| Auflösungen/Frameraten 3D | 1920x1080p23.976/24, 1280x720p50/59.94 | **(unbestätigt)**; 1080p24 (exakt 24,000) **(Referenz)** |
| GOP | Closed GOP mit IDR an jedem I genügt; Open GOP mit Non-IDR-I ist aber auch zulässig. Anchor an jedem I | **(Referenz)**, **(Praxis)**: GOP ≤ 24, adaptiv |
| Slices pro Bild | 6 in beiden Views | **(Referenz)**, **(Praxis)** (BD verlangt vermutl. ≥ 4 bei 1080) |
| Entropie-Codierung | CABAC, 8x8-Transformation | **(Referenz)** |
| PIDs im Transportstrom | Base 0x1011, Dependent 0x1012 (eigenes `.m2ts` mit eigener PAT/PMT 0x100, PCR 0x1001, SIT 0x1F) | **(Praxis)** |

## Analyse-Ergebnisse

### Referenz-Encoder (`samples/referenz/Winter 3D Long.*`, 153 s, 1080p24, eigene 3D-Kamera)

Datei läuft auf den meisten 3D-Playern (Ausnahme: sehr alter Panasonic, der auch mit selbst
gebrannten 2D-Discs Probleme hat).

**Gemeinsam (beide Views identisch):**
- 1920x1088 codiert, Cropping unten 8 Zeilen → 1920x1080
- `pic_order_cnt_type 0`, `log2_max_pic_order_cnt_lsb 5`, `log2_max_frame_num 8`, `max_num_ref_frames 3`
- VUI: `aspect_ratio_idc 1`, Timing `num_units_in_tick 1 / time_scale 48` (24,000 fps), `fixed_frame_rate 1`,
  NAL-HRD (VBR), `pic_struct_present 1`, keine Farbangaben, keine bitstream_restriction
- GOP: 24 Bilder (1 s), jedes GOP mit **IDR**, 3 B-Bilder ohne Pyramide (B = Nicht-Referenz)
  - Decodier-Reihenfolge `I P b b b P b b b …`, Anzeige `I b b b P b b b P …`
- POC, `frame_num`, `nal_ref_idc`, IDR-Positionen sind pro AU in beiden Views **identisch**
- Delimiter `primary_pic_type`: I → 0, P → 1, B → 2 (Dependent-Anchor-P → 1)
- Pic-Timing: `pic_struct 0`, `dpb_output_delay 2`

**Base View (`.264`):**
- AU-Aufbau: IDR `9 7 8 6 5×6`, sonst `9 6 1×6`
- SPS id 0, PPS id 0, an jedem IDR wiederholt
- Eine SEI-NAL pro AU: an IDR `buffering_period + pic_timing`, sonst nur `pic_timing`
- HRD: 21,82 Mbit/s, CPB 16,36 Mbit

**Dependent View (`.mvc`):**
- AU-Aufbau: IDR `24 15 8 6 6 20×6`, sonst `24 6 20×6`, letzte AU eines GOP zusätzlich `… 10` (End of Sequence)
- Subset-SPS id **1**, PPS id **1** (PPS-ID-Raum wird mit dem Base View geteilt → muss abweichen)
- Subset-SPS: SPS-Teil identisch zum Base-SPS (bis auf Profil 128, ID und HRD-Werte), eigene VUI mit HRD
  18,18 Mbit/s, CPB 13,64 Mbit; **keine** MVC-VUI-Extension
  - Summe Base + Dependent: 40,0 Mbit/s und 30,0 Mbit CPB → der Referenz-Encoder teilt ein Gesamtbudget auf (≈ 55:45)
- MVC-Extension: 2 Views (view_id 0, 1); View 1 darf View 0 referenzieren, sowohl Anchor (L0: [0]) als auch
  Non-Anchor (L0: [0]); ein Level-Wert 41 mit Operationspunkt temporal_id 0, Ziel-Views [0, 1]
- SEIs: **jede** HRD-SEI einzeln in `mvc_scalable_nesting` verpackt, `operation_point_flag 1`,
  `sei_op_view_id [1]`, `sei_op_temporal_id 0`; an IDR zwei SEI-NALs (Buffering Period, Pic Timing), sonst eine
  - `initial_cpb_removal_delay` identisch zum Base View
- **Keine** User-Data-SEIs → keine 3D-Offset-Metadaten im Elementary Stream; für die Videowiedergabe nicht nötig
- Keine Ref-Listen-Modifikationen, keine MMCOs

**Inter-View-Prädiktion beim Referenz-Encoder:**
- Anchor-Bilder sind **P-Bilder mit genau 1 Referenz** (= Base-View-Bild) → nur 4 % kleiner als das Base-I-Bild
- Non-Anchor-P/B: L0 hat genau eine Referenz mehr als im Base View (Inter-View-Referenz am Listenende)
- Größe Dependent/Base: gesamt **80 %**, bei P 82 %, bei B 68 % – bei im Schnitt ~1 QP höherer Quantisierung
  im Dependent View → der echte Gewinn durch Inter-View-Prädiktion ist beim Referenz-Encoder **gering**

### tsMuxeR 2.7.0 (Muxing mit `insertSEI, contSPS`)

- BD3D-ISO entsteht nur bei Ausgabe direkt als `.iso` (bei Ordnerausgabe keine SSIF-Dateien!)
- Struktur: `00000.m2ts` (Base, PID 4113), `00001.m2ts` (Dependent, PID 4114), `SSIF/00000.ssif`
- Meldet beim Referenz-Encoder **und** den generierten Streams „insert pict timing and buffering period SEI units“ und
  normalisiert dabei (festgestellt durch Demux + Analyse):
  - `fixed_frame_rate_flag` → 1, zusätzlich VCL-HRD (Kopie des NAL-HRD) in SPS und Subset-SPS
  - Buffering-Period-SEIs neu berechnet (NAL+VCL), im Dependent View weiterhin in MVC Scalable Nesting
  - Reihenfolge der SEIs im Base View angepasst (BP vor PT)
  - **End-of-Sequence-NALs (10) im Dependent View werden entfernt** → für die Disc irrelevant
- Der Rewriter-Output übersteht Mux → Demux strukturell unverändert (POC, Bildtypen, Slices, NAL-20-Header)
- Disc-Struktur (geprüft mit `bdmeta.py` an einem 5-s-Test-ISO aus x264 + Rewriter) entspricht dem üblichen
  Aufbau von Blu-ray-3D-Discs: SSIF vorhanden, Dependent-Clip `application_type 8` mit eigener EP-Map (CPI_SS) und identischen PTS,
  STN_table_SS mit 1 Offset-Sequenz, SubPath Typ 8. Abweichung: TS_recording_rate des Dependent View 35 statt
  32 Mbit/s. Wie erwartet bei Simulcast: Anchor so groß wie das Base-I-Bild, Dependent/Base ≈ 0,99

## Folgerungen für Phase 1

1. **Größennachteil wohl klein:** Der Referenz-Encoder spart durch Inter-View-Prädiktion nur wenig. x264 ist in der Regel
   effizienter als der Referenz-Encoder – Phase 1 könnte in der Gesamtgröße nahe am Referenz-Encoder liegen.
2. **Vorlage für den Rewriter** ist vollständig bekannt: Delimiter 24, Subset-SPS-Aufbau, PPS-ID 1,
   SEI-Verschachtelung, NAL-20-Header-Werte, End-of-Sequence am GOP-Ende.
3. **Entscheidung Subset-SPS-Referenzen:** zwei Varianten, beide auf Playern zu testen
   - (a) keine Inter-View-Referenzen deklarieren (`num_anchor_refs = num_non_anchor_refs = 0`) – „sauberes“ Simulcast,
     Anchor-Bilder sind dann I-Bilder
   - (b) wie beim Referenz-Encoder deklarieren, aber nie benutzen: Die Inter-View-Referenz landet am **Ende** der Ref-Liste;
     solange `num_ref_idx_active` nur die zeitlichen Referenzen abdeckt, wird sie nie angesprochen.
     Anchor-Bilder müssen dann trotzdem I-Slices haben. Vorteil: Subset-SPS strukturell identisch zum Referenz-Encoder.
4. x264-Parameter am Output des Referenz-Encoders orientieren: Closed GOP 24, jedes GOP IDR, 3 B-Bilder ohne Pyramide,
   max. 3 Referenzen, 6 Slices, CABAC, 8x8, NAL-HRD VBR, AUD, `pic_struct`.
   Ergänzt 2026-10-14: IDR an Szenenwechseln (GOP ≤ 24, adaptiv) und
   VBV 28 Mbit/s / 30 Mbit pro Auge, siehe `phase-1-simulcast.md`, Testlauf 2.

## Offene Fragen

1. ~~NAL-Reihenfolge im Dependent View~~ → beantwortet (Referenz)
2. ~~Prefix-NALs im Base View~~ → keine (Referenz)
3. ~~SPS-/PPS-IDs~~ → SPS 0 / Subset-SPS 1 / PPS 0 und 1 (Referenz)
4. ~~SEIs im Dependent View~~ → HRD-SEIs einzeln in MVC Scalable Nesting, keine Offset-Metadaten (Referenz)
5. ~~Subset-SPS-Felder~~ → siehe oben (Referenz)
6. ~~Wie viel spart Inter-View-Prädiktion in der Praxis?~~ → typisch Dependent ≈ 50–64 % des Base View,
   Anchors als P-Bilder.
7. Was prüft tsMuxeR beim Einlesen eines `.mvc` (Fehlerverhalten bei Abweichungen)?
8. Ist End of Sequence (NAL 10) im Dependent View nötig oder ein Artefakt des Referenz-Encoders? (zur Sicherheit nachbilden)
9. ~~Übliche GOP-Struktur: GOP-Länge, IDR vs. Non-IDR-I, B-Pyramide, Slice-Anzahl?~~ → GOP ≤ 24 adaptiv,
   closed **oder** open mit Non-IDR-I, 1–2 B ohne Pyramide, 6 Slices
10. ~~Akzeptieren Player Anchor-Bilder mit I-Slices?~~ → ja, Testlauf 1 Variante A (ohne deklarierte Inter-View-
    Referenzen) läuft auf 3D-Player + Beamer, siehe `phase-1-simulcast.md`
