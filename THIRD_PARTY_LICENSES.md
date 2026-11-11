# Fremdkomponenten und Lizenzen

OpenBDAuth bringt die folgenden Komponenten mit. Die Lizenztexte liegen im Paket im Ordner `licenses/` und bei
den Werkzeugen in `tools/<plattform>/licenses/`.

| Komponente | Version | Verwendung | Lizenz | Quelle |
|---|---|---|---|---|
| FFmpeg (ffmpeg, ffprobe), Build von gyan.dev „essentials“ (Windows) | 9.0.2 | Menü-Hintergründe, Analyse von Video und Ton, Encoding im Arbeitsbereich Vorbereiten | GPL-3.0 (gebaut mit `--enable-gpl --enable-version3`, u. a. mit x264; ohne `--enable-nonfree`, also weitergebbar) | Build: https://github.com/GyanD/codexffmpeg/releases/tag/9.0.2 · Quellcode: https://github.com/FFmpeg/FFmpeg/commit/946fcce07b (Konfiguration in `ffmpeg-README.txt`) |
| FFmpeg (ffmpeg, ffprobe), statischer Build von BtbN „linux64-gpl“ (Linux) | 9.0.2 (n9.0.2-17-g2a571b6068) | wie oben | GPL-3.0 (`--enable-gpl --enable-version3`, u. a. mit x264; ohne `--enable-nonfree`) | Build: https://github.com/BtbN/FFmpeg-Builds/releases/tag/autobuild-2026-09-30-13-08 · Quellcode: https://github.com/FFmpeg/FFmpeg/commit/2a571b6068 · Build-Skripte: https://github.com/BtbN/FFmpeg-Builds |
| FFmpeg (ffmpeg, ffprobe), statischer Build von Martin Riedl (macOS, Apple Silicon) | 9.0.2 | wie oben | GPL-3.0 (`--enable-gpl --enable-version3`, u. a. mit x264; ohne `--enable-nonfree`) | Build: https://ffmpeg.martin-riedl.de/ (Release 9.0.2, arm64) · Quellcode: https://github.com/FFmpeg/FFmpeg/tree/n9.0.2 · Build-Skripte: https://git.martin-riedl.de/ffmpeg/build-script |
| x264 (im FFmpeg-Build enthalten, keine eigene Datei) | wie im FFmpeg-Build | Video-Encoding im Arbeitsbereich Vorbereiten (2D und beide Augen bei 3D) | GPL-2.0-or-later (`licenses/GPL-3.0.txt` deckt die GPL-3.0 des FFmpeg-Builds ab) | https://code.videolan.org/videolan/x264 |
| tsMuxeR (ursprünglich von Roman Vasilenko) | 2.7.0 | Muxen der Filme | Apache-2.0 (das Projekt hat keine NOTICE-Datei) | https://github.com/justdan96/tsMuxer/releases/tag/2.7.0 |
| Qt über PySide6 / Shiboken6 | 6.11.2 | Oberfläche | LGPL-3.0-only – Qt ist wahlweise unter LGPL-3.0, GPL-2.0 oder GPL-3.0 lizenziert, OpenBDAuth nutzt die LGPL (`licenses/LGPL-3.0.txt`, `licenses/GPL-3.0.txt`) | https://download.qt.io/official_releases/QtForPython/ · Qt-Bibliotheken liegen als einzelne Dateien im Programmordner und lassen sich austauschen |
| Pillow | 12.1.0 | Bilder, Button-Grafiken | MIT-CMU | https://github.com/python-pillow/Pillow |
| comtypes (nur Windows-Paket) | 1.4.16 | Brennen über IMAPI2, den Brenndienst von Windows | MIT (`licenses/comtypes-LICENSE.txt`) | https://github.com/enthought/comtypes |
| Python | 3.12.9 | Laufzeit | PSF-2.0; die mitgelieferten Bibliotheken OpenSSL (Apache-2.0), libffi (MIT), bzip2, xz und die Microsoft-Laufzeit (VC++) unter ihren eigenen Lizenzen – alle Texte in `licenses/Python-LICENSE.txt` | https://www.python.org/ |
| Liberation Sans | 2.1.5 | Schrift auf der Disc (Menüs) | SIL OFL 1.1 | https://github.com/liberationfonts/liberation-fonts |
| Noto Sans | 2.015 | Schrift auf der Disc (Untertitel) | SIL OFL 1.1 | https://github.com/notofonts/latin-greek-cyrillic |
| Systembibliotheken von Ubuntu 22.04 (nur Linux-Paket), u. a. X11/xcb, xkbcommon, GLib, D-Bus, fontconfig, FreeType, ICU-Daten aus Qt | wie im Paket aufgeführt | Laufzeit unter Linux (von PyInstaller mitgenommen) | je Paket eigene Lizenz, überwiegend MIT, BSD und LGPL-2.1+ – Texte und Paketversionen in `licenses/linux-system/` | Quellcode: https://launchpad.net/ubuntu/jammy (Quellpakete der aufgeführten Versionen) · LGPL-Bibliotheken liegen als einzelne Dateien im Paket und lassen sich austauschen |
| PyInstaller-Startprogramm | 6.22.0 | Start des Pakets | GPL-2.0-or-later mit Ausnahme: Die GPL erstreckt sich nicht auf das damit gebündelte Programm | https://pyinstaller.org/ |

FFmpeg und tsMuxeR laufen als eigene Programme; OpenBDAuth ruft sie auf, bindet ihren Code aber nicht ein.

Der Encoder im Arbeitsbereich Vorbereiten (`modules/prepare/`) und der MVC-Rewriter (`mvctools/`) stammen aus dem
Schwesterprojekt BD3DEnc desselben Autors (übernommen mit v1.21) und sind Teil von OpenBDAuth – keine
Fremdkomponenten.

Hinweis: H.264 und MVC sind in manchen Ländern patentrechtlich geschützt. Wer Discs gewerblich vertreibt, sollte
das für sein Land prüfen.
