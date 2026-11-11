# Plan: macOS-Hilfsdateien („._“) nicht in die ISO

Stand: 2026-11-11 · Status: **notiert, nicht umgesetzt**

## Befund

Dasselbe Projekt (D4A) einmal unter macOS, einmal unter Windows als ISO exportiert und Datei für Datei verglichen
(beide ISOs auf F:, exFAT): Die Mac-ISO enthält **98 zusätzliche Dateien** mit `._` am Anfang, z. B.
`BDMV/._index.bdmv`, `BDMV/._MovieObject.bdmv`, `BDMV/STREAM/._00000.m2ts`, `CERTIFICATE/._BACKUP`.

Das sind AppleDouble-Dateien: macOS legt sie auf Dateisystemen ohne eigene Metadaten (exFAT, FAT32, SMB) neben jede
Datei und jeden Ordner. Die ISO-Erstellung (`modules/udf250_writer.py` über `modules/iso_tools.py`) nimmt alles mit,
was im BDMV-Ordner liegt.

Nicht die Ursache des Menüproblems in VLC: Die Windows-ISO ohne diese Dateien zeigt dasselbe Verhalten.

## Vorschlag

- Beim Einsammeln der Dateien für die ISO auslassen: Namen mit `._` am Anfang, `.DS_Store`, `.Spotlight-V100`,
  `.Trashes`, `.fseventsd` (alles, was macOS selbst anlegt). Eine Blu-ray kennt keine Dateien mit Punkt am Anfang.
- Verhindern lässt sich ihr Entstehen nicht (macOS legt sie beim Schreiben an), darum beim Packen filtern.
- Test: ein BDMV-Ordner mit `._`-Dateien ergibt dieselbe ISO wie ohne.

## Vorsicht

Die ISO-Erstellung gehört zur eingefrorenen Export-Pipeline. Die Änderung ist klein (nur Dateien auslassen, die nie
auf eine Blu-ray gehören), aber danach einmal gegen einen Player prüfen.
