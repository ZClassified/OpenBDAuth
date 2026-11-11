# Eigener MVC-Encoder für Blu-ray 3D – Roadmap

*Übernommen aus BD3DEnc (v0.8.1) mit OpenBDAuth v1.21.0. Pfade wie `BD3DEnc.py` oder `jobs.py` beziehen sich auf
BD3DEnc; in OpenBDAuth liegen der Encoder-Code in `modules/prepare/jobs.py` und der MVC-Rewriter in `mvctools/`.*

Ziel: den bisherigen Referenz-Encoder (nur Windows, basiert auf einem eingestellten SDK) durch eine
**plattformübergreifende** Lösung ersetzen, die aus einem Top-and-Bottom-Video (1920x2160)
einen **Blu-ray-3D-konformen** MVC-Stream erzeugt (`.264` Base View + `.mvc` Dependent View),
der mit tsMuxeR zu einer 3D-Blu-ray gemuxt werden kann.

## Phasen

| Phase | Dokument | Inhalt | Status |
|---|---|---|---|
| 0 | – | Bitstream-Analyzer (`mvctools.analyze`) und Auswertung von Referenzmaterial | Analyzer fertig; Ergebnisse in [mvc-wissen.md](mvc-wissen.md) |
| 1 | [phase-1-simulcast.md](phase-1-simulcast.md) | MVC **ohne** Inter-View-Prädiktion: 2× x264 + eigener MVC-Rewriter | Player-Test bestanden, in BD3DEnc v0.7.0 integriert, v0.7.1 mit Szenenwechsel-IDR und höheren VBV-Grenzen; Langzeittests offen |
| 2 | [phase-2-interview.md](phase-2-interview.md) | Echtes MVC **mit** Inter-View-Prädiktion (eigener Code) | geplant – erst nach der OpenBDAuth-Integration |

Gesammeltes Wissen, Spezifikationsdetails und offene Fragen: [mvc-wissen.md](mvc-wissen.md)

Phase 0 ist die gemeinsame Grundlage: Der Analyzer wird in beiden Phasen als
Validierungswerkzeug weiterverwendet. Phase 2 baut auf den Erkenntnissen aus Phase 1 auf,
ersetzt sie aber nicht – Phase 1 bleibt als robuster Fallback-Modus im Tool erhalten.

## Begriffe

- **Base View** – linkes Auge, normaler H.264-Stream (`.264`). Jeder 2D-Player spielt ihn ab.
- **Dependent View** – rechtes Auge, eigener Stream (`.mvc`) mit MVC-Syntax (H.264 Annex H).
  Ein Dependent View existiert in **beiden** Phasen – er ist Pflicht für Blu-ray 3D.
- **Inter-View-Prädiktion** – der Dependent View referenziert das gleichzeitige Bild des
  Base View (spart typischerweise 30–50 % Bitrate im rechten Auge). Laut Standard optional.
  - Phase 1: **ohne** → rechtes Auge wird unabhängig codiert, nur in MVC-Syntax verpackt
    („Simulcast in MVC-Syntax“). Gesamtdatei ca. 25–50 % größer bei gleicher Qualität.
  - Phase 2: **mit** → effizientes, „echtes“ MVC.
- **Anchor Picture** – Bild im Dependent View an einem Random-Access-Punkt (gehört zum
  IDR/I-Bild des Base View); darf nur Inter-View-Referenzen nutzen (in Phase 1: I-Slices).

## Leitplanken

1. **Blu-ray-Konformität vor allem anderen.** Die BD-Spezifikation ist nicht öffentlich –
   Konformität wird empirisch abgesichert: Header-Vergleich mit Streams des Referenz-Encoders und üblichen
   Werten, tsMuxeR-Akzeptanz, Tests auf Hardware-Playern.
2. **Plattformübergreifend** (Windows, Linux, macOS). Nur Abhängigkeiten, die auf allen drei
   Plattformen laufen (ffmpeg, x264, tsMuxeR, Python-Standardbibliothek).
3. **Eigener Code für alles MVC-Spezifische.** Fremdcode nur als austauschbare Engine
   (x264 für die eigentliche Bildkompression) oder als Prüfwerkzeug (Decoder).

## Zukunft des Codes

`mvctools/` und dieses Verzeichnis wandern bei der Integration in OpenBDAuth unverändert dorthin; die
MVC-Weiterentwicklung (Phase 2) geht danach dort weiter. Siehe [../integration-openbdauth.md](../integration-openbdauth.md)
und die Gesamtübersicht [../README.md](../README.md).

## Ablage

- `docs/mvc/` – Pläne und Wissen (versioniert)
- `samples/` – Testclips und Referenzstreams (**nicht** versioniert, siehe `.gitignore`)
