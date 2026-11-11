# Phase 2 – Echtes MVC mit Inter-View-Prädiktion

Ziel: Der Dependent View nutzt das gleichzeitige Bild des Base View als Referenz →
typischerweise 30–50 % weniger Bitrate im rechten Auge bzw. deutlich bessere Qualität bei
gleicher Gesamtbitrate. Komplett eigener MVC-Code, plattformübergreifend.

Voraussetzung: Phase 1 abgeschlossen (Rewriter, Validierungskette und Player-Tests funktionieren).

**Zeitpunkt (Entscheidung 2026-10-14):** erst nach der Integration in OpenBDAuth. Der jetzige Weg (Phase 1)
leistet, was der Referenz-Encoder vorher geleistet hat; Phase 2 ist die „Königsdisziplin“ für danach.

**Erster Schritt, bevor Encoder-Code entsteht:** einen MVC-fähigen Decoder in die Testkette holen
(JM-Referenzdecoder oder edge264). ffmpeg kann H.264-MVC nicht decodieren, und bei Inter-View-Prädiktion
zeigen sich Fehler nicht mehr in den Headern (`verify`), sondern erst im decodierten Bild. Danach den
Gewinn des kleinsten Schritts messen (Anchor als P statt I). Die Testsuite liefert dafür schon synthetisches
Stereo-Material mit bekannter Disparität (`tests/util.py`, rechtes Auge um 16 Pixel verschoben).
Erwarteter Gewinn nach üblichen Werten: Dependent ≈ 50–64 % des Base View statt 100 % → bei gleicher
Qualität grob 20–25 % weniger Gesamtgröße.
Alles aus Phase 1 (Subset-SPS, NAL-20-Header, SEIs, Muxing) wird wiederverwendet –
neu ist nur die eigentliche Codierung des rechten Auges.

## Was zusätzlich nötig ist

- Rekonstruiertes (decodiertes) Bild des Base View pro Zeitpunkt verfügbar machen
- Dieses Bild als zusätzliche Referenz in Liste 0/1 des Dependent View einfügen
- Disparitätsschätzung (= Bewegungsschätzung zwischen linkem und rechtem Bild, überwiegend horizontal)
- Signalisierung: `num_anchor_refs`/`num_non_anchor_refs` im Subset-SPS, `inter_view_flag = 1` im Base View,
  `ref_pic_list_mvc_modification` (idc 4/5) in den Slice-Headern
- Anchor Pictures als P-Bilder mit ausschließlich Inter-View-Referenz statt I-Bilder (großer Bitraten-Gewinn)
- MVC-DPB-Verwaltung: Inter-View-Referenzen leben nur innerhalb einer Access Unit
- HRD/VBV über beide Views gemeinsam einhalten

## Lösungswege (Entscheidung nach Phase 1)

### A – x264 erweitern (Fork/Patch)
Base View normal mit x264; beim Encode des Dependent View wird das rekonstruierte Base-Bild als
Referenz injiziert. x264s Bewegungsschätzung, RDO, Ratenkontrolle und CABAC bleiben erhalten.
- **+** Beste Qualität pro Aufwand, ausgereifte Ratenkontrolle
- **–** Eingriff in x264-Interna (Referenzlisten, Frame-Threading), GPL-Lizenz, Fork muss gepflegt
  und für alle Plattformen gebaut werden

### B – Eigener Encoder nur für den Dependent View
x264 für den Base View, eigener H.264-Encoder (C oder Rust) für das rechte Auge.
- **+** Volle Kontrolle, eigene Lizenz, perfekt auf MVC zugeschnitten
- **–** Benötigt komplette H.264-Encoder-Bausteine (Transformation, CABAC, Bewegungsschätzung,
  Ratenkontrolle, Deblocking-identische Rekonstruktion des Base View)

### C – Komplett eigener MVC-Encoder (beide Views)
- **+** Unabhängig von x264, ein Guss
- **–** Größter Aufwand; Qualität von x264 zu erreichen ist ein langer Weg

**Aktuelle Tendenz:** A als Hauptweg (schnellster Weg zu echtem MVC in hoher Qualität), B/C als
mögliches Langzeitprojekt. Der Engpass ist das Debuggen von Bitstreams und das Testen auf echter Hardware.

## Meilensteine (Weg A)

1. x264 als Bibliothek bauen (Windows/Linux/macOS), Build reproduzierbar dokumentieren
2. Zwei Encoder-Instanzen in einem Prozess, synchron pro Access Unit
3. Inter-View-Referenz nur für Anchor Pictures (P statt I) – kleinster sinnvoller Schritt, bereits messbarer Gewinn
4. Inter-View-Referenz auch für Non-Anchor-Bilder
5. Ratenkontrolle über beide Views abgestimmt
6. Validierungskette aus Phase 1 + Vergleich Bitrate/Qualität (PSNR/SSIM) gegen Phase 1 und dem Referenz-Encoder

## Abnahmekriterien

- [ ] Hardware-Player-Test wie Phase 1
- [ ] Messbare Bitraten-Ersparnis gegenüber Phase 1 bei gleicher Qualität
- [ ] Builds für Windows, Linux, macOS
