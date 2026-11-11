# Phase 1 – MVC ohne Inter-View-Prädiktion („Simulcast in MVC-Syntax“)

Ziel: Funktionierende, Blu-ray-3D-konforme `.264` + `.mvc` auf allen Plattformen – ohne den Referenz-Encoder.
Beide Augen werden unabhängig mit x264 codiert; ein eigener **MVC-Rewriter** verpackt den
Stream des rechten Auges in MVC-Syntax.

Voraussetzung: Phase 0 (Analyzer `mvctools.analyze` und Vorlage aus Referenzstreams, Ergebnisse in [mvc-wissen.md](mvc-wissen.md)).

## Warum das legal ist

H.264 Annex H erlaubt `num_anchor_refs = 0` und `num_non_anchor_refs = 0` für den
Dependent View. Anchor Pictures sind dann intra-codiert (I-Slices), alle anderen Bilder
referenzieren nur den eigenen View. Jeder konforme MVC-Decoder muss das abspielen.
Ob die (nicht öffentliche) BD-Spezifikation zusätzliche Anforderungen stellt, wird über
Referenzvergleich und Player-Tests abgesichert.

## Pipeline

```
TaB-Quelle ──ffmpeg crop oben──▶ x264 (links)  ──▶ left.264  ─────────────────────▶ Final_3D.264
           └─ffmpeg crop unten─▶ x264 (rechts) ──▶ right.264 ──▶ MVC-Rewriter ──▶ Final_3D.mvc
                                                                                      │
                                                         tsMuxeR (SSIF / BD-Ordner) ◀─┘
```

Beide Encodes können parallel laufen (Pipes: Windows Named Pipes bzw. `os.mkfifo` unter
Linux/macOS, alternativ ffmpeg → stdout → x264 stdin).

## Schritt 1: Synchrone x264-Encodes

Beide Views **müssen** pro Access Unit identische Bildtypen, Decodier-Reihenfolge und POCs haben.

- **1a (einfach, deterministisch):** feste GOP-Struktur für beide Encodes
  `--b-adapt 0 --no-scenecut --keyint N --min-keyint N --bframes 3 --b-pyramid strict --open-gop none`
  plus Blu-ray-Parameter (`--bluray-compat`, Level 4.1, VBV, `--slices 4`, `--aud`, `--nal-hrd vbr`, …
  genaue Werte aus Phase 0 bzw. vorhandener 2D-Pipeline übernehmen).
- **1b (bessere Qualität):** linkes Auge adaptiv codieren, Bildtyp-Entscheidungen aus dem
  Log/Stream extrahieren und dem rechten Auge per `--qpfile` vorgeben.
- Analyzer prüft nach jedem Encode das Alignment (Bildtyp + POC pro AU identisch).
- Bitrate pro View so wählen, dass die Gesamt-Grenzen für BD3D eingehalten werden (Werte → mvc-wissen.md).

## Schritt 2: MVC-Rewriter (`mvctools/rewrite.py`)

Eingabe: `right.264` (normales AVC). Ausgabe: `.mvc` (Dependent View). Pro NAL:

| Eingang | Ausgang |
|---|---|
| AUD (9) | Dependent-Delimiter (24), falls Phase 0 das bestätigt |
| SPS (7) | Subset-SPS (15): `profile_idc = 128` (Stereo High), `seq_parameter_set_mvc_extension` mit view_id 0/1, keine Inter-View-Referenzen, Level-/Operationspunkt-Werte; optional `mvc_vui_parameters_extension` (HRD) |
| PPS (8) | PPS mit **eigener** `pic_parameter_set_id` (teilt sich den ID-Raum mit dem Base View!), verweist auf Subset-SPS |
| IDR-Slice (5) | NAL 20, `non_idr_flag = 0`, `anchor_pic_flag = 1`, `view_id = 1`, `inter_view_flag = 0` |
| Non-IDR-Slice (1) | NAL 20, `non_idr_flag = 1`, `anchor_pic_flag` = 1 bei I-Bildern am GOP-Start, sonst 0 |
| SEI (6) | Timing-SEIs ggf. in MVC Scalable Nesting (SEI 37) verpacken – Form laut Phase 0 |

Technische Punkte:

- **Slice-Header neu schreiben** (geänderte `pic_parameter_set_id` → andere Bitlänge).
  Bei **CABAC** beginnt `slice_data` byte-aligned → Nutzdaten werden 1:1 kopiert. CAVLC wird nicht unterstützt
  (bei Blu-ray High Profile ohnehin CABAC).
- `ref_pic_list_modification` ist syntaktisch kompatibel zu `ref_pic_list_mvc_modification` (idc 0–3) → Bits übernehmen.
- Emulation-Prevention-Bytes nach dem Umschreiben neu einfügen.
- Performance: Ein Spielfilm hat pro View ~20+ GB. Nur Header werden in Python dekodiert; Slice-Daten werden als
  Blöcke kopiert, Start-Codes mit `bytes.find` gesucht, Datei gestreamt (nicht komplett in den RAM).
- Ggf. 3D-Offset-Metadaten (für Untertitel/Menüs in 3D) einfügen, falls Phase 0 zeigt, dass Player/tsMuxeR sie erwarten.

## Schritt 3: Validierung (in dieser Reihenfolge)

1. Analyzer-`--diff` gegen die Referenz → nur erklärbare Unterschiede
2. Decoder-Test: JMVC-Decoder und edge264 decodieren beide Views fehlerfrei
3. tsMuxeR akzeptiert `.264` + `.mvc` und erzeugt BD3D-Struktur/ISO ohne Warnungen
4. Software-Player in 3D
5. **Hardware-Player** (PS3/PS4/Standalone) – das eigentliche Abnahmekriterium
6. Langer Test: kompletter Film (Kapitelsprünge, Spulen, Seamless-Übergänge)

## Schritt 4: Integration in BD3DEnc (v0.7.0, erledigt)

- [x] Encoder-Auswahl im 3D-Tab: „BD3DEnc MVC (plattformübergreifend)“ (Standard) | „Referenz-Encoder (nur Windows)“
- [x] Kein Named-Pipe-Code nötig: ein ffmpeg-Prozess mit zwei libx264-Ausgängen (2-Pass), danach Rewriter + `verify_pair`
- [x] Fortschritt: Pass 1 0–35 %, Pass 2 35–85 %, Rewriter 85–95 %, Prüfung 96–100 %
- [x] README: ffmpeg mit libx264, Referenz-Encoder optional
- Kein ISO-Export – das Authoring übernimmt OpenBDAuth
- Der Referenz-Encoder bleibt als Fallback, bis die Abnahmekriterien unten erfüllt sind

## Abnahmekriterien

- [x] Testclip läuft auf mindestens einem Hardware-Player in 3D (2026-10-14, 153 s Clip)
- [ ] Kompletter Film läuft auf Hardware-Player inkl. Spulen/Kapitel
- [ ] Pipeline läuft unter Windows **und** Linux (macOS wenn verfügbar)
- [x] Dateigröße/Qualität gegenüber dem Referenz-Encoder dokumentiert (Testlauf 2: gleiche Größe, Qualität auf 4K-OLED gut;
  kein A/B-Vergleich mehr geplant)

## Testlauf 1 (2026-10-14) – Winter 3D Long, 153 s

Rewriter: `python -m mvctools.rewrite right.264 right.mvc [--interview-refs]`

x264 (über ffmpeg/libx264, beide Views identisch, 2-Pass, `-preset slow -b:v 12500k`):
`keyint=24:min-keyint=24:scenecut=0:open-gop=0:bframes=3:b-adapt=0:b-pyramid=none:ref=3:slices=6:weightp=0:bluray-compat=1:nal-hrd=vbr:vbv-maxrate=20000:vbv-bufsize=15000:aud=1:level=4.1:pic-struct=1:force-cfr=1`
→ gleiches Gesamtbudget wie beim Referenz-Encoder (Ø 25 / max. 40 Mbit/s, CPB 30 Mbit), aber 50:50 statt ≈ 55:45 verteilt.

| ISO | Subset-SPS | Anchor-Bilder |
|---|---|---|
| `BD3D_Test_A_Simulcast.iso` | keine Inter-View-Referenzen | I |
| `BD3D_Test_B_Ref-SPS.iso` | Inter-View-Referenzen deklariert (wie beim Referenz-Encoder), nie genutzt | I |
| `BD3D_Referenz.iso` | Output des Referenz-Encoders, gleiche tsMuxeR-Einstellungen (Kontrolle) | P (Inter-View) |

Analyzer: beide Varianten fehlerfrei, POC/Bildtyp/IDR/frame_num pro AU identisch zum Base View.
tsMuxeR akzeptiert beide ohne Warnungen (außer der auch beim Referenz-Encoder auftretenden SEI-Normalisierung).

Ergebnis Player-Test (3D-Player + 3D-Beamer):
- **A: läuft problemlos** – Autostart, Player und Beamer schalten automatisch in den 3D-Modus, Spulen/Springen ok
- B: nicht mehr nötig – Player akzeptieren I-Anchors ohne deklarierte Inter-View-Referenzen → Variante A ist Standard
- Bildqualität im Vergleich zum Referenz-Encoder: _(ausstehend)_

## Testlauf 2 (2026-10-14) – Szenenwechsel-IDR und höhere VBV-Grenzen

Anlass: übliche Werte auf Blu-ray-3D-Discs (`mvc-wissen.md`) – adaptive GOPs, bis 40 Mbit/s pro View erlaubt.

Umsetzung in `BD3DEnc.py` (`encode_3d_own`):
- **Analyse:** x264-Pass-1 nur über das linke Auge mit `scenecut=40:min-keyint=1` (jeder Schnitt wird IDR, kein
  Non-IDR-I – sonst fehlte im Dependent View das Anchor-Bild). Die I-Positionen kommen aus der Pass-1-Statistik.
- **2-Pass beide Augen gemeinsam** mit `scenecut=0` und denselben Positionen per `-/force_key_frames datei`
  (Zeitliste aus Datei, ab ffmpeg 7; inline wäre sie bei einem Film zu lang für die Kommandozeile).
- Gescheiterte Zwischenschritte (für später festgehalten):
  - `qpfile` in `-x264-params` wird von libx264 stillschweigend ignoriert (nur x264-CLI).
  - Nur das rechte Auge zu erzwingen, reicht nicht: Bei selbst erkannten Schnitten macht x264 die Bilder vor dem
    I zu P, bei erzwungenen bleiben sie B → Bildtypen weichen ab. Deshalb beide Augen gleich behandeln.
- VBV pro Auge `vbv-maxrate=28000:vbv-bufsize=30000` (vorher 20000/15000).

Test-ISO `BD3DEnc_Test.iso` (43 s, 2 Kapitel, stilles AC3; ISO gelöscht, Quelle im eigenen Testordner):
- Quelle: eigenes Stereopaar „Test 1“ (Garten, 25p ProRes) als TAB auf 23,976 umgetaktet, in 6 Abschnitten mit
  harten Schnitten neu zusammengesetzt (`Garten TAB Schnitte.mov`)
- Kapitel 1: 30 Mbit/s gesamt (höchste Voreinstellung), Kapitel 2: 50 Mbit/s gesamt als Stresstest der neuen
  VBV-Grenze (Ø 25, Spitze im 1-s-Fenster 30,6 Mbit/s pro Auge)
- Beide Teile auf ES-Ebene verkettet (jeder beginnt mit IDR + SPS), tsMuxeR 2.7.0 ohne Warnungen
- Geprüft: Verify nach Encode und nach Demux aus dem ISO OK (1030 Bilder); `bdmeta.py`: SSIF, 60/60 EP mit
  identischen PTS; Analyzer: alle Slice-Header OK, 60 IDR/Anchors, HRD 28 Mbit/s / 30 Mbit
- 30 IDR auf 515 Bilder: alle 5 harten Schnitte getroffen, die übrigen setzt x264 bei schnellen Handkamera-Schwenks
- Ergebnis Player-Test (3D-Player + 4K-OLED-3D-TV, 2026-10-14): **bestanden** – Disc startet sofort, TV schaltet
  automatisch in 3D, Spulen ok, keine Ruckler, schnelle Schnitte und starke Bewegung problemlos, kein sichtbarer
  Qualitätsunterschied zwischen linkem und rechtem Auge. Standbild-Qualität wegen des bewegten Materials noch
  nicht beurteilt (→ mit ruhigerem Material, z. B. „Winter 3D Long“, nachholen)

Vergleich mit dem Referenz-Encoder am ruhigen Material („Winter 3D Long“, 153 s, Full-TAB, 24,000 fps), zwei ISOs mit identischem
Muxing (AC3 Stereo 320 kbps, PGS-Untertitel DE, 5 Kapitel aus der EDL):

| ISO | Video | Größe Base / Dependent | GOP |
|---|---|---|---|
| `Winter_BD3DEnc_v0.7.1.iso` | neuer Weg, 25 Mbit/s gesamt | 239 / 239 MB | 157 IDR, davon 4 an Szenenwechseln |
| `Winter_Referenz.iso` | Ausgabe des Referenz-Encoders vom 28.09., Ø 25 Mbit/s | 264 / 211 MB | 154 IDR, feste 24 |

- Gleiches Gesamtbudget (478 vs. 475 MB); der Referenz-Encoder teilt ≈ 55:45, OpenBDAuth 50:50.
- Verify nach Encode und nach Demux aus dem ISO OK (3683 Bilder); `bdmeta.py`: beide Discs strukturell gleich.
- Untertitel: Der SRT→PGS-Konverter von OpenBDAuth schreibt bei 24,000 fps fälschlich 23,976 ins PCS
  (Toleranz in `fps_to_pgs_rate_byte` zu groß) – für die Test-ISOs von Hand auf 0x20 korrigiert, in OpenBDAuth
  inzwischen behoben.
- Ergebnis Player-Test `Winter_BD3DEnc_v0.7.1.iso` (4K-OLED, 2026-10-14): **bestanden** – sieht sehr gut aus,
  läuft einwandfrei. Ein direkter A/B-Vergleich mit dem Referenz-Encoder ist nicht mehr geplant – das Ergebnis genügt; die
  Test-ISOs wurden gelöscht.

## Erkenntnisse für Phase 2

Hier während der Arbeit notieren (Stolpersteine, Player-Eigenheiten, Toleranzen):

- …
