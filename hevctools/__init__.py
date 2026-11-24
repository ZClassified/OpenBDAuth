"""hevctools – Analyse und Prüfung von HEVC-Elementarströmen (H.265) für Ultra HD Blu-ray.

Reines Python (nur Standardbibliothek), läuft auf Windows, Linux und macOS. Aufbau wie mvctools/, dessen
Bit-Leser (Exp-Golomb, Emulation Prevention) mitbenutzt wird. Siehe docs/plaene/uhd.md (Phase 2).

    python -m hevctools.analyze FILM.hevc [--json out.json]     ausführlicher Bericht
    python -m hevctools.check FILM.hevc [--range hdr10]          Prüfung nach den Regeln für UHD-Blu-ray
"""
