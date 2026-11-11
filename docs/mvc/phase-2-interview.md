# Phase 2 – Echtes MVC mit Inter-View-Prädiktion

Ziel: Der Dependent View nutzt das gleichzeitige Bild des Base View als Referenz und wird dadurch kleiner,
**bei gleicher Qualität beider Augen**. Komplett eigener MVC-Code, plattformübergreifend.

Voraussetzung: Phase 1 abgeschlossen (Rewriter, Validierungskette und Player-Tests funktionieren).

## Entscheidungen

- **2026-10-14:** erst nach der Integration in OpenBDAuth. Phase 1 leistet, was der Referenz-Encoder vorher
  geleistet hat; Phase 2 ist die „Königsdisziplin“ für danach.
- **2026-11-11:**
  - In OpenBDAuth gibt es künftig genau zwei Varianten zur Wahl: **volle Größe** (Phase 1, beide Augen
    unabhängig, maximale Qualität) und **echtes MVC** (Phase 2). Eine Sparvariante, die einem Auge einfach
    weniger Bitrate gibt, kommt nicht.
  - **Gleicher QP auf beiden Augen.** Übliche Blu-ray-3D-Streams codieren das rechte Auge zusätzlich etwa
    3 QP gröber; das übernehmen wir nicht. Die Ersparnis kommt allein aus der Inter-View-Prädiktion.
  - Entwicklung in einem **eigenen Repository** (x264-Patch, eigener Build, Messreihen). Nach OpenBDAuth kommt
    das Ergebnis erst als fertiges Bauteil, nach bestandenem Player-Test – so wie `mvctools/` aus BD3DEnc kam.

## Was eine Analyse bestehender Streams zeigt

Ausgewertet per Decodierung, nicht nur über die Header (eigener MVC-Decoder, bitgleich zu FRIMDecode64):

**Effizientes Muster, wie bei Blu-ray 3D üblich** (1080p23,976, 5019 Bilder, 6 Slices, CABAC,
`max_num_ref_frames 2`, jedes I-Bild ist IDR, Closed GOP ≈ 1 s, `I P B B P …`, B-Bilder nicht referenziert;
Subset-SPS `anchor_refs L0 = [0]`, `non_anchor_refs L0 = [0]`):

| Bildpaar links / rechts | Anzahl | Inter-View genutzt | Größe rechts/links | Ø QP links → rechts |
|---|---|---|---|---|
| IDR / Anchor-P (1 Referenz = Inter-View) | 225 | 100 % | 53,4 % | 11,3 → 13,1 |
| P / P (2 Referenzen: zeitlich + Inter-View an L0[1]) | 1754 | 100 % | 48,7 % | 12,4 → 15,3 |
| B / B (nur zeitlich) | 3034 | 0 % | 59,2 % | 15,8 → 18,6 |
| B / P nicht referenziert, nur Inter-View | 6 | 100 % | 1,1 % | 24,0 → 27,3 |
| **gesamt** | 5019 | | **51,8 %** | |

- Inter-View steckt **nur in P-Bildern** (Anchor und normale P); B-Bilder sind rein zeitlich. Die 59 % bei den
  B-Bildern kommen also allein vom gröberen QP.
- Faustregel: +3 QP ≈ −30 % Bitrate. Grob die Hälfte der Ersparnis dieses Musters geht auf den gröberen QP
  zurück. Mit **gleichem QP** ist deshalb weniger zu erwarten, grob geschätzt rechts ≈ 70–80 % von links
  (Gesamtgröße etwa −10 bis −15 % gegenüber Phase 1). Das ist die erste Messung, die der Prototyp liefern muss.
- Die Weighted-Prediction-Tabellen in diesem Muster sind leer (Encoder-Artefakt) – nicht nachbauen.
- Die frühere Header-Analyse ([mvc-wissen.md](mvc-wissen.md)) zeigt dasselbe Bild (49,9 %, QP ≈ +2).

**3D-Camcorder** (Panasonic HDC-Z10000, JVC GS-TD1) nutzen Inter-View nur im Anchor-Bild und sparen praktisch
nichts (rechts ≈ 100 % von links). Für die Disc-Kompatibilität ist das aber ein nützlicher Hinweis: Auch die
kleinste Form (nur Anchor als P) wird von MVC-Decodern erwartet.

## Zielmuster für den Encoder

Wie das effiziente Muster, aber mit gleichem QP:

- Anchor im Dependent View: **P-Bild mit Inter-View als einziger Referenz** (statt I-Bild wie in Phase 1)
- normale P-Bilder: genau 2 Referenzen – letztes eigenes Referenzbild + Inter-View an L0[1]
  (`ref_pic_list_mvc_modification`, idc 4/5)
- B-Bilder: rein zeitlich, wie bisher
- Struktur wie Phase 1: Closed GOP, jedes I = IDR, IDR-Positionen beider Augen gleich, `max_num_ref_frames 2`
- Signalisierung: `num_anchor_refs`/`num_non_anchor_refs = 1` im Subset-SPS, `inter_view_flag = 1` im
  Base View

## Was zusätzlich nötig ist

- Rekonstruiertes (decodiertes) Bild des Base View pro Zeitpunkt beim Encode des rechten Auges verfügbar machen
- Dieses Bild als zusätzliche Referenz in Liste 0 des Dependent View einfügen
- Disparitätsschätzung (= Bewegungsschätzung zwischen linkem und rechtem Bild, überwiegend horizontal)
- MVC-DPB-Verwaltung: Inter-View-Referenzen leben nur innerhalb einer Access Unit
- HRD/VBV über beide Views gemeinsam einhalten
- MVC-Rewriter (`mvctools/rewrite.py`): Subset-SPS mit Inter-View-Referenzen, Listenmodifikation idc 4/5

Alles andere aus Phase 1 (NAL-20-Header, SEIs, Muxing) wird wiederverwendet.

**Prüfkette:** ffmpeg kann H.264-MVC nicht decodieren, und Fehler bei Inter-View-Prädiktion zeigen sich nicht
in den Headern (`verify`), sondern erst im decodierten Bild. Gelöst durch einen eigenen MVC-Decoder (Python +
ffmpeg, plattformübergreifend, bitgleich zu FRIMDecode64 verifiziert – auch am effizienten Muster). Er schreibt den
Dependent View in normales H.264 um und fügt dafür das benötigte linke Bild als Kopie oder als verlustfreies
I_PCM-Bild ein. Er wird das Prüfwerkzeug für Phase 2.

## Lösungswege

### A – x264 erweitern (Fork/Patch) – gewählt
Base View normal mit x264; beim Encode des Dependent View wird das rekonstruierte Base-Bild als
Referenz injiziert. x264s Bewegungsschätzung, RDO, Ratenkontrolle und CABAC bleiben erhalten.
- **+** Beste Qualität pro Aufwand, ausgereifte Ratenkontrolle
- **–** Eingriff in x264-Interna (Referenzlisten, Frame-Threading), Fork muss gepflegt und für alle Plattformen
  gebaut werden. Lizenz passt: x264 ist GPL-2 oder später, OpenBDAuth GPL-3.

Ohne Patch geht es nicht: x264 wählt seine Referenzen selbst, und das Inter-View-Bild muss bitgleich zur
Rekonstruktion des Base View sein.

### B – Eigener Encoder nur für den Dependent View
x264 für den Base View, eigener H.264-Encoder (C oder Rust) für das rechte Auge.
- **+** Volle Kontrolle, perfekt auf MVC zugeschnitten
- **–** Benötigt komplette H.264-Encoder-Bausteine (Transformation, CABAC, Bewegungsschätzung,
  Ratenkontrolle, Deblocking-identische Rekonstruktion des Base View)

### C – Komplett eigener MVC-Encoder (beide Views)
- **+** Unabhängig von x264, ein Guss
- **–** Größter Aufwand; Qualität von x264 zu erreichen ist ein langer Weg

## Meilensteine (Weg A, im eigenen Repository)

1. x264 als Bibliothek bzw. Programm bauen (Windows/Linux/macOS), Build reproduzierbar dokumentieren
2. Zwei Encoder-Instanzen in einem Prozess, synchron pro Access Unit
3. Inter-View-Referenz nur für Anchor-Bilder (P statt I) – kleinster sinnvoller Schritt; mit dem Decoder prüfen
4. Inter-View-Referenz auch für normale P-Bilder (Zielmuster)
5. **Messung bei gleichem QP:** Größe und Qualität (PSNR/SSIM) gegen Phase 1 – entscheidet, ob sich der Weg lohnt
6. Ratenkontrolle über beide Views abgestimmt (2-Pass, VBV gemeinsam)
7. Player-Test (Sony UBP-X700 und BDP-S4200, Panasonic), danach Übernahme nach OpenBDAuth als Wahl
   „volle Größe“ / „echtes MVC“

## Abnahmekriterien

- [ ] Hardware-Player-Test wie Phase 1
- [ ] Messbare Ersparnis gegenüber Phase 1 bei gleicher Qualität beider Augen
- [ ] Builds für Windows, Linux, macOS
