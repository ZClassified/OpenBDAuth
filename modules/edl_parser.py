# modules/edl_parser.py
import re

class EDLParser:
    def parse_chapters(self, file_path: str, fps: float) -> list:
        """
        Parsed eine DaVinci Resolve EDL Datei nach Kapitelmarkern.
        Unterstützt Non-Drop-Frame (:) und Drop-Frame (;) Timecodes sowie Encoding-Fallback.
        """
        chapters = []
        fps_val = float(fps) if fps else 23.976
        if fps_val <= 0:
            fps_val = 23.976

        lines = []
        # Encoding-Fallback für maximale Kompatibilität mit Windows-Exporten
        for encoding in ('utf-8', 'utf-8-sig', 'cp1252', 'latin-1'):
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    lines = f.readlines()
                break
            except UnicodeDecodeError:
                continue

        try:
            for line in lines:
                parts = line.strip().split()
                # DaVinci EDL Format: 001 001 V C 00:00:00:00 00:00:00:01 00:00:00:00 00:00:00:01
                # Gesucht werden Video (V) Cuts (C) Events
                if len(parts) >= 8 and parts[2] == 'V' and parts[3] == 'C':
                    # Record In ist parts[6]
                    record_in = parts[6]
                    # Splitte auf ':' und ';' für Drop-Frame-Unterstützung
                    tc_parts = re.split(r'[:;]', record_in)
                    if len(tc_parts) == 4 and all(p.isdigit() for p in tc_parts):
                        hh, mm, ss, ff = [int(p) for p in tc_parts]
                        # Frames in Millisekunden umrechnen (max 999ms)
                        ms = min(int((ff / fps_val) * 1000), 999)
                        chapters.append(f"{hh:02d}:{mm:02d}:{ss:02d}.{ms:03d}")
        except Exception as e:
            print(f"Fehler beim EDL-Parsing: {e}")
            return []
        
        # Sicherstellen, dass 00:00:00.000 dabei ist
        if "00:00:00.000" not in chapters:
            chapters.append("00:00:00.000")

        # Duplikate entfernen und chronologisch sortieren
        return sorted(list(set(chapters)))
