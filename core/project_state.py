# core/project_state.py
"""
Zentrales Datenmodell für OpenBDAuth (Release 1.0.1).
Unterstützt titel-basiertes Authoring (MediaTitle), Multi-Title-Verwaltung,
Projekt-Serialisierung (.bdproj / JSON) und Rückwärtskompatibilität.
"""

import os
import json
from typing import List, Dict, Optional, Tuple
from core.constants import APP_VERSION

class MediaTitle:
    """Repräsentiert einen einzelnen eigenständigen Titel (Film, Episode, Extra) auf der Blu-ray."""
    def __init__(self, name: str = "Hauptfilm", is_main: bool = True):
        self.name = name
        self.is_main = is_main
        self.video_base: Optional[str] = None
        self.video_mvc: Optional[str] = None
        self.fps: float = 23.976
        self.audio_tracks: List[Dict[str, str]] = []     # [{"path": str, "lang": str}]
        self.subtitle_tracks: List[Dict[str, str]] = []  # [{"path": str, "lang": str}]
        self.chapters: List[str] = []                    # ["00:00:00.000", ...]
        self.menu_btn_text: Optional[str] = None         # Individueller Menü-Button-Text
        self.video_details: Optional[dict] = None
        self.compliance_warnings: List[dict] = []
        self.warnings_acknowledged: bool = False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "is_main": self.is_main,
            "video_base": self.video_base,
            "video_mvc": self.video_mvc,
            "fps": self.fps,
            "audio_tracks": [dict(t) for t in self.audio_tracks],
            "subtitle_tracks": [dict(t) for t in self.subtitle_tracks],
            "chapters": list(self.chapters),
            "menu_btn_text": self.menu_btn_text,
            "video_details": self.video_details,
            "compliance_warnings": self.compliance_warnings,
            "warnings_acknowledged": self.warnings_acknowledged,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MediaTitle":
        title = cls(
            name=data.get("name", "Neuer Titel"),
            is_main=data.get("is_main", False)
        )
        title.video_base = data.get("video_base")
        title.video_mvc = data.get("video_mvc")
        title.fps = float(data.get("fps", 23.976))
        title.audio_tracks = list(data.get("audio_tracks", []))
        title.subtitle_tracks = list(data.get("subtitle_tracks", []))
        title.chapters = list(data.get("chapters", []))
        title.menu_btn_text = data.get("menu_btn_text")
        title.video_details = data.get("video_details")
        title.compliance_warnings = list(data.get("compliance_warnings", []))
        title.warnings_acknowledged = bool(data.get("warnings_acknowledged", False))
        return title


class ProjectState:
    def __init__(self):
        self.app_lang = "de"
        # Basis-Informationen
        self.project_name = "Untitled_Project"
        self.output_path = ""
        self.export_format = "folder"  # "folder" oder "iso"
        self.clean_iso_temp = True     # Temporäre BDMV-Dateien nach ISO-Erstellung bereinigen
        self.disc_title_meta = False   # Titel im Player schreiben (BDMV/META/DL, nur Studio)
        self.disc_title = ""           # Titel im Player (leer = Disc-Name)

        # HDMV Menü-Optionen (Out-of-Mux)
        self.enable_menu = True
        self.menu_bg_image = None
        self.menu_bg_video: Optional[str] = None
        self.menu_bg_audio: Optional[str] = None
        self.menu_duration: float = 30.0
        self.menu_btn1_text = "FILM STARTEN"
        self.menu_btn2_text = "EXTRAS"
        self.menu_show_btn2 = False
        self.menu_show_chapters = False
        self.menu_btn_chapters_text = "KAPITEL"
        self.menu_show_audio = False
        self.menu_btn_audio_text = "SPRACHE"
        self.menu_no_buttons_test = False  # Hardware-Diagnose: Menü ohne Buttons (Hintergrund als Intro)
        self.custom_button_positions = {}  # Dict: (page_id, button_id) -> (x, y)

        # Titel-Verwaltung (Master-Detail)
        self.titles: List[MediaTitle] = [MediaTitle(name="Hauptfilm", is_main=True)]
        self.current_title_index: int = 0

    # -------------------------------------------------------------
    # RÜCKWÄRTSKOMPATIBILITÄTS-PROPERTIES (Titel 1 / Hauptfilm)
    # -------------------------------------------------------------
    @property
    def video_base(self) -> Optional[str]:
        return self.titles[0].video_base if self.titles else None

    @video_base.setter
    def video_base(self, val: Optional[str]):
        if self.titles:
            self.titles[0].video_base = val

    @property
    def video_mvc(self) -> Optional[str]:
        return self.titles[0].video_mvc if self.titles else None

    @video_mvc.setter
    def video_mvc(self, val: Optional[str]):
        if self.titles:
            self.titles[0].video_mvc = val

    @property
    def fps(self) -> float:
        return self.titles[0].fps if self.titles else 23.976

    @fps.setter
    def fps(self, val: float):
        if self.titles:
            self.titles[0].fps = val

    @property
    def audio_tracks(self) -> List[Dict[str, str]]:
        return self.titles[0].audio_tracks if self.titles else []

    @audio_tracks.setter
    def audio_tracks(self, val: List[Dict[str, str]]):
        if self.titles:
            self.titles[0].audio_tracks = val

    @property
    def subtitle_tracks(self) -> List[Dict[str, str]]:
        return self.titles[0].subtitle_tracks if self.titles else []

    @subtitle_tracks.setter
    def subtitle_tracks(self, val: List[Dict[str, str]]):
        if self.titles:
            self.titles[0].subtitle_tracks = val

    @property
    def chapters(self) -> List[str]:
        return self.titles[0].chapters if self.titles else []

    @chapters.setter
    def chapters(self, val: List[str]):
        if self.titles:
            self.titles[0].chapters = val

    # Extras (Titel 2 Delegation)
    @property
    def video_extra(self) -> Optional[str]:
        if len(self.titles) > 1:
            return self.titles[1].video_base
        return None

    @video_extra.setter
    def video_extra(self, val: Optional[str]):
        if val:
            if len(self.titles) < 2:
                extra = MediaTitle(name="Extras", is_main=False)
                extra.video_base = val
                self.titles.append(extra)
            else:
                self.titles[1].video_base = val
        else:
            if len(self.titles) > 1:
                self.titles[1].video_base = None

    @property
    def extra_audio_tracks(self) -> List[Dict[str, str]]:
        if len(self.titles) > 1:
            return self.titles[1].audio_tracks
        return []

    @extra_audio_tracks.setter
    def extra_audio_tracks(self, val: List[Dict[str, str]]):
        if len(self.titles) < 2:
            extra = MediaTitle(name="Extras", is_main=False)
            extra.audio_tracks = val
            self.titles.append(extra)
        else:
            self.titles[1].audio_tracks = val

    # -------------------------------------------------------------
    # TITEL-VERWALTUNG
    # -------------------------------------------------------------
    def add_title(self, name: str = "Neuer Titel", is_main: bool = False) -> MediaTitle:
        new_title = MediaTitle(name=name, is_main=is_main)
        self.titles.append(new_title)
        self.current_title_index = len(self.titles) - 1
        return new_title

    def remove_title(self, index: int) -> bool:
        if index <= 0 or index >= len(self.titles):
            return False  # Hauptfilm (Index 0) ist geschützt
        self.titles.pop(index)
        if self.current_title_index >= len(self.titles):
            self.current_title_index = len(self.titles) - 1
        return True

    def get_current_title(self) -> MediaTitle:
        if 0 <= self.current_title_index < len(self.titles):
            return self.titles[self.current_title_index]
        return self.titles[0]

    @property
    def compliance_warnings(self) -> List[dict]:
        return self.titles[0].compliance_warnings if self.titles else []

    def get_all_compliance_warnings(self) -> List[Tuple[str, List[dict]]]:
        """Gibt alle Titel mit aktiven Kompatibilitätswarnungen zurück: [(title_name, warnings), ...]"""
        result = []
        for t in self.titles:
            if t.compliance_warnings:
                result.append((t.name, t.compliance_warnings))
        return result

    # -------------------------------------------------------------
    # Tonspur hinzufügen, WAV vorher für tsMuxeR bereinigen (BWF-Metadaten)
    # -------------------------------------------------------------
    def add_audio_track(self, file_path: str, language_name: str, is_extra: bool = False, title_index: Optional[int] = None):
        from core.constants import resolve_language_code
        lang_code = resolve_language_code(language_name)

        # WAV-Bereinigung / E-AC-3-Extraktion für tsMuxeR (siehe core/media_import.py)
        from core.media_import import prepare_audio_file
        file_path = prepare_audio_file(file_path)

        # Ziel-Titel bestimmen
        target_idx = 0
        if title_index is not None and 0 <= title_index < len(self.titles):
            target_idx = title_index
        elif is_extra:
            if len(self.titles) < 2:
                self.add_title(name="Extras", is_main=False)
            target_idx = 1

        self.titles[target_idx].audio_tracks.append({"path": file_path, "lang": lang_code})

    def add_extra_audio_track(self, file_path: str, language_name: str):
        self.add_audio_track(file_path, language_name, is_extra=True)

    def add_subtitle_track(self, file_path: str, language_name: str, title_index: Optional[int] = None):
        from core.constants import resolve_language_code
        lang_code = resolve_language_code(language_name)
        target_idx = 0
        if title_index is not None and 0 <= title_index < len(self.titles):
            target_idx = title_index
        self.titles[target_idx].subtitle_tracks.append({"path": file_path, "lang": lang_code})

    # -------------------------------------------------------------
    # PROJEKT-SERIALISIERUNG (.bdproj / JSON)
    # -------------------------------------------------------------
    def to_dict(self) -> dict:
        # Tuple-Keys (page_id, button_id) in String "page,button" für sauberes JSON wandeln
        custom_pos = {
            f"{k[0]},{k[1]}": [v[0], v[1]]
            for k, v in self.custom_button_positions.items()
        }
        return {
            "version": APP_VERSION,
            "app_lang": self.app_lang,
            "project_name": self.project_name,
            "output_path": self.output_path,
            "export_format": self.export_format,
            "clean_iso_temp": self.clean_iso_temp,
            "enable_menu": self.enable_menu,
            "menu_bg_image": self.menu_bg_image,
            "menu_bg_video": self.menu_bg_video,
            "menu_bg_audio": self.menu_bg_audio,
            "menu_duration": self.menu_duration,
            "menu_btn1_text": self.menu_btn1_text,
            "menu_btn2_text": self.menu_btn2_text,
            "menu_show_btn2": self.menu_show_btn2,
            "menu_show_chapters": self.menu_show_chapters,
            "menu_btn_chapters_text": self.menu_btn_chapters_text,
            "menu_show_audio": self.menu_show_audio,
            "menu_btn_audio_text": self.menu_btn_audio_text,
            "menu_no_buttons_test": self.menu_no_buttons_test,
            "custom_button_positions": custom_pos,
            "titles": [t.to_dict() for t in self.titles]
        }

    def from_dict(self, data: dict):
        self.app_lang = data.get("app_lang", "de")
        self.project_name = data.get("project_name", "Untitled_Project")
        self.output_path = data.get("output_path", "")
        self.export_format = data.get("export_format", "folder")
        self.clean_iso_temp = bool(data.get("clean_iso_temp", True))
        self.enable_menu = data.get("enable_menu", True)
        self.menu_bg_image = data.get("menu_bg_image")
        self.menu_bg_video = data.get("menu_bg_video")
        self.menu_bg_audio = data.get("menu_bg_audio")
        self.menu_duration = float(data.get("menu_duration", 30.0))
        self.menu_btn1_text = data.get("menu_btn1_text", "FILM STARTEN")
        self.menu_btn2_text = data.get("menu_btn2_text", "EXTRAS")
        self.menu_show_btn2 = data.get("menu_show_btn2", False)
        self.menu_show_chapters = data.get("menu_show_chapters", False)
        self.menu_btn_chapters_text = data.get("menu_btn_chapters_text", "KAPITEL")
        self.menu_show_audio = data.get("menu_show_audio", False)
        self.menu_btn_audio_text = data.get("menu_btn_audio_text", "SPRACHE")
        self.menu_no_buttons_test = bool(data.get("menu_no_buttons_test", False))

        raw_pos = data.get("custom_button_positions", {})
        self.custom_button_positions = {}
        for k, v in raw_pos.items():
            try:
                parts = [int(p.strip()) for p in k.split(",")]
                if len(parts) == 2:
                    self.custom_button_positions[(parts[0], parts[1])] = (int(v[0]), int(v[1]))
            except Exception:
                pass

        titles_data = data.get("titles", [])
        if titles_data:
            self.titles = [MediaTitle.from_dict(t) for t in titles_data]
        else:
            self.titles = [MediaTitle(name="Hauptfilm", is_main=True)]
        self.current_title_index = 0

    def save_to_file(self, filepath: str):
        """Speichert den gesamten Projektstatus in eine .bdproj (JSON) Datei."""
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    def load_from_file(self, filepath: str):
        """Lädt einen kompletten Projektstatus aus einer .bdproj (JSON) Datei."""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.from_dict(data)
