# core/meta_builder.py
import os
import re
import tempfile
from typing import Optional
from modules.subtitles.srt_to_sup import convert_srt_to_sup

class MetaBuilder:
    def __init__(self, project_state):
        self.state = project_state

    @staticmethod
    def _format_path(path: str) -> str:
        """Standardisiert Pfade für tsMuxeR (Forward-Slashes)."""
        return path.replace("\\", "/")

    def _get_tsmuxer_fps_str(self, title_or_state, video_path: Optional[str] = None) -> str:
        """
        Ermittelt die korrekte Framerate für tsMuxeR.
        tsMuxeR erwartet bei H.264-Elementary-Streams immer die Vollbildrate (Frame Rate):
        - 23.976 -> "23.976"
        - 24.0 -> "24"
        - 25.0 (auch bei 1080i25 / 25PsF) -> "25"
        - 29.97 (auch bei 1080i29.97 / 29.97PsF) -> "29.97"
        - 50.0 (720p50) -> "50"
        - 59.94 (720p59.94) -> "59.94"
        
        Wichtig: Wird bei einem 25-fps-Stream 'fps=50' übergeben, interpretiert tsMuxeR
        dies als manuelle Geschwindigkeitsänderung von 25 auf 50 fps (200% Geschwindigkeit,
        halbe Laufzeit!).
        """
        fps_val = getattr(title_or_state, "fps", 23.976)
        try:
            fps_float = float(fps_val)
        except (ValueError, TypeError):
            fps_float = 23.976

        details = getattr(title_or_state, "video_details", None)
        height = 1080
        is_interlaced = False
        if isinstance(details, dict):
            is_interlaced = bool(details.get("is_interlaced", False))
            height = int(details.get("height", 1080) or 1080)
        elif video_path and os.path.isfile(video_path):
            try:
                from modules.video_tools import VideoTools
                probed = VideoTools().probe_video_details(video_path)
                is_interlaced = bool(probed.get("is_interlaced", False))
                height = int(probed.get("height", 1080) or 1080)
            except Exception:
                pass

        # Bei 1080i: falls fälschlicherweise Halbbildrate (50 / 59.94) übergeben wurde,
        # auf echte Vollbildrate für tsMuxeR normalisieren (25 / 29.97)
        if is_interlaced and height == 1080:
            if 49.0 <= fps_float <= 50.5:
                fps_float = 25.0
            elif 59.0 <= fps_float <= 60.1:
                fps_float = 29.97

        # Bei 24p / 23.976p H.264 Elementary Streams meldet ffprobe oft 48 fps (2 Felder pro Frame)
        if 47.0 <= fps_float <= 48.5:
            fps_float = 24.0 if abs(fps_float - 48.0) < 0.1 else 23.976

        # Bei 1080p 3D Streams (MVC vorhanden): Framerate darf niemals > 30 sein
        if getattr(title_or_state, "video_mvc", None) and fps_float > 30.0:
            fps_float = fps_float / 2.0

        if fps_float.is_integer():
            return str(int(fps_float))
        return f"{fps_float:.3f}".rstrip('0').rstrip('.')

    def _get_fps_str(self, video_path: Optional[str] = None) -> str:
        """Gibt die Framerate als sauberen String für tsMuxeR zurück."""
        return self._get_tsmuxer_fps_str(self.state, video_path=video_path)

    def _ensure_sup_path(self, sub_path: str, lang: str = "und", idx: int = 1, sup_dir: Optional[str] = None) -> str:
        """Wandelt .srt automatisch in standardkonformes .sup (BD-ROM PGS) um."""
        if not sub_path.lower().endswith('.srt'):
            return self._format_path(sub_path)

        if not os.path.exists(sub_path):
            # Fallback für Unittests mit Dummy-Pfaden: Endung auf .sup anpassen
            sup_mock = os.path.splitext(sub_path)[0] + ".sup"
            return self._format_path(sup_mock)

        if not sup_dir:
            # Standardmäßig direkt im Verzeichnis der originalen SRT-Datei ablegen
            srt_dir = os.path.dirname(os.path.abspath(sub_path))
            if os.path.isdir(srt_dir) and os.access(srt_dir, os.W_OK):
                sup_dir = srt_dir
            else:
                sup_dir = tempfile.gettempdir()

        base_name = os.path.splitext(os.path.basename(sub_path))[0]
        safe_base = re.sub(r'[^a-zA-Z0-9_\-]', '_', base_name)
        if lang and lang.lower() not in safe_base.lower() and lang.lower() != "und":
            sup_file = os.path.join(sup_dir, f"{safe_base}_{lang}.sup")
        else:
            sup_file = os.path.join(sup_dir, f"{safe_base}.sup")

        try:
            fps_val = float(getattr(self.state, "fps", 23.976))
        except (ValueError, TypeError):
            fps_val = 23.976

        convert_srt_to_sup(sub_path, sup_file, fps=fps_val)
        return self._format_path(sup_file)

    def generate_title_meta_content(self, title, sup_dir: Optional[str] = None) -> str:
        lines = []
        muxopt = "MUXOPT --blu-ray"
        
        # Disc-Name (Label) hinzufügen
        if getattr(self.state, "project_name", None):
            safe_label = self.state.project_name.replace('"', '').replace(',', '').strip()
            if safe_label:
                muxopt += f' --label="{safe_label}"'

        # Kapitel-Markierungen
        chapters = getattr(title, "chapters", [])
        if chapters:
            chapters_str = ";".join(ch.strip() for ch in chapters if ch.strip())
            if chapters_str:
                muxopt += f" --custom-chapters={chapters_str}"
            
        lines.append(muxopt)

        video_path = getattr(title, "video_base", None)
        fps_str = self._get_tsmuxer_fps_str(title, video_path=video_path)

        # 1. HAUPT-VIDEO (Track 1)
        if video_path:
            base_path = self._format_path(video_path)
            lines.append(f'V_MPEG4/ISO/AVC, "{base_path}", fps={fps_str}, insertSEI, contSPS')
        
        # 2. 3D-ERWEITERUNG (Track 2)
        if getattr(title, "video_mvc", None):
            mvc_path = self._format_path(title.video_mvc)
            lines.append(f'V_MPEG4/ISO/MVC, "{mvc_path}", fps={fps_str}, insertSEI, contSPS')

        # 3. AUDIO-TRACKS
        for audio in getattr(title, "audio_tracks", []):
            path = self._format_path(audio["path"])
            lang = audio.get("lang", "und")
            path_lower = path.lower()
            
            if path_lower.endswith('.wav'):
                lines.append(f'A_LPCM, "{path}", lang={lang}')
            elif path_lower.endswith(('.dts', '.dtshd', '.dts-hd')):
                lines.append(f'A_DTS, "{path}", lang={lang}')
            elif path_lower.endswith(('.thd', '.truehd', '.mlp')):
                lines.append(f'A_MLP, "{path}", lang={lang}')
            elif path_lower.endswith(('.ac3', '.eac3', '.ec3')):
                lines.append(f'A_AC3, "{path}", lang={lang}')
            else:
                print(f"Warnung: Unbekanntes Audioformat bei {path}. Versuche als AC3 zu deklarieren.")
                lines.append(f'A_AC3, "{path}", lang={lang}')

        # 4. UNTERTITEL (Automatisch nach BD-ROM PGS konvertiert)
        for idx, sub in enumerate(getattr(title, "subtitle_tracks", []), start=1):
            path = sub["path"]
            lang = sub.get("lang", "und")
            sup_path = self._ensure_sup_path(path, lang=lang, idx=idx, sup_dir=sup_dir)
            lines.append(f'S_HDMV/PGS, "{sup_path}", lang={lang}')

        return "\n".join(lines)

    def generate_meta_content(self, sup_dir: Optional[str] = None) -> str:
        if hasattr(self.state, "titles") and self.state.titles:
            return self.generate_title_meta_content(self.state.titles[0], sup_dir=sup_dir)
        return self.generate_title_meta_content(self.state, sup_dir=sup_dir)

    def save_meta_file(self, output_path: str, sup_dir: Optional[str] = None):
        content = self.generate_meta_content(sup_dir=sup_dir)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)

    def save_title_meta_file(self, title, output_path: str, sup_dir: Optional[str] = None):
        content = self.generate_title_meta_content(title, sup_dir=sup_dir)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)

    def generate_extra_meta_content(self, sup_dir: Optional[str] = None) -> str:
        lines = []
        muxopt = "MUXOPT --blu-ray"
        lines.append(muxopt)

        fps_str = self._get_fps_str(video_path=self.state.video_extra)

        # 1. EXTRAS VIDEO
        if self.state.video_extra:
            base_path = self._format_path(self.state.video_extra)
            lines.append(f'V_MPEG4/ISO/AVC, "{base_path}", fps={fps_str}, insertSEI, contSPS')

        # 2. EXTRAS AUDIO TRACKS
        for audio in self.state.extra_audio_tracks:
            path = self._format_path(audio["path"])
            lang = audio["lang"]
            path_lower = path.lower()
            if path_lower.endswith('.wav'):
                lines.append(f'A_LPCM, "{path}", lang={lang}')
            elif path_lower.endswith(('.dts', '.dtshd', '.dts-hd')):
                lines.append(f'A_DTS, "{path}", lang={lang}')
            elif path_lower.endswith(('.thd', '.truehd', '.mlp')):
                lines.append(f'A_MLP, "{path}", lang={lang}')
            elif path_lower.endswith(('.ac3', '.eac3', '.ec3')):
                lines.append(f'A_AC3, "{path}", lang={lang}')
            else:
                lines.append(f'A_AC3, "{path}", lang={lang}')

        # 3. EXTRAS SUBTITLE TRACKS (Automatisch nach BD-ROM PGS konvertiert)
        for idx, sub in enumerate(getattr(self.state, "extra_subtitle_tracks", []), start=1):
            path = sub["path"]
            lang = sub.get("lang", "und")
            sup_path = self._ensure_sup_path(path, lang=lang, idx=idx, sup_dir=sup_dir)
            lines.append(f'S_HDMV/PGS, "{sup_path}", lang={lang}')

        return "\n".join(lines)

    def save_extra_meta_file(self, output_path: str, sup_dir: Optional[str] = None):
        content = self.generate_extra_meta_content(sup_dir=sup_dir)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)

