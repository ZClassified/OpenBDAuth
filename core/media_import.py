# core/media_import.py
"""
Import von Mediendateien in Film-Knoten (ab v1.6.0), ohne Oberfläche:
- Dateityp-Erkennung anhand der Endung (Video, MVC, Ton, Untertitel, Kapitel)
- Vorbereitung von Tonspuren für tsMuxeR (WAV-Bereinigung, E-AC-3 aus MP4),
  unverändert übernommen aus ProjectState.add_audio_track
- vorsichtige Spracherkennung aus dem Dateinamen
"""

import os
import re
import subprocess
from typing import Optional

from core.translations import tr
from modules.external_tools import tool_path, FFMPEG, NO_CONSOLE

KIND_VIDEO = "video"
KIND_MVC = "mvc"
KIND_AUDIO = "audio"
KIND_SUBTITLE = "subtitle"
KIND_CHAPTERS = "chapters"

VIDEO_EXTS = {".264", ".h264", ".avc", ".m2ts"}
MVC_EXTS = {".mvc"}
AUDIO_EXTS = {".ac3", ".eac3", ".ec3", ".dts", ".dtshd", ".truehd", ".thd", ".wav", ".mp4"}
SUBTITLE_EXTS = {".srt", ".sup"}
CHAPTER_EXTS = {".edl"}
# Gehen nicht direkt auf die Disc, lassen sich aber vorbereiten (v1.23: Angebot „Zu Vorbereiten“)
PREPARE_EXTS = {".mov", ".mkv", ".m4v", ".avi", ".mxf", ".ts", ".webm", ".mpg", ".mpeg", ".wmv",
                ".flac", ".mka", ".aac", ".mp3", ".m4a", ".ogg", ".opus"}

# Nur eindeutige Schreibweisen, damit Wörter im Dateinamen nicht versehentlich als Sprache gelten
_LANGUAGE_ALIASES = {
    "de": "deu", "deu": "deu", "ger": "deu", "german": "deu", "deutsch": "deu",
    "en": "eng", "eng": "eng", "english": "eng", "englisch": "eng",
    "fr": "fra", "fra": "fra", "fre": "fra", "french": "fra", "francais": "fra", "französisch": "fra",
    "es": "spa", "spa": "spa", "spanish": "spa", "spanisch": "spa", "espanol": "spa",
    "it": "ita", "ita": "ita", "italian": "ita", "italienisch": "ita", "italiano": "ita",
    "nl": "nld", "nld": "nld", "dut": "nld", "dutch": "nld", "niederländisch": "nld",
    "ja": "jpn", "jpn": "jpn", "japanese": "jpn", "japanisch": "jpn",
    "sv": "swe", "swe": "swe", "swedish": "swe", "schwedisch": "swe",
    "da": "dan", "dan": "dan", "danish": "dan", "dänisch": "dan",
    "no": "nor", "nor": "nor", "norwegian": "nor", "norwegisch": "nor",
    "fi": "fin", "fin": "fin", "finnish": "fin", "finnisch": "fin",
    "pl": "pol", "pol": "pol", "polish": "pol", "polnisch": "pol",
    "pt": "por", "por": "por", "portuguese": "por", "portugiesisch": "por",
    "ru": "rus", "rus": "rus", "russian": "rus", "russisch": "rus",
    "tr": "tur", "tur": "tur", "turkish": "tur", "türkisch": "tur",
    "zh": "zho", "zho": "zho", "chi": "zho", "chinese": "zho", "chinesisch": "zho",
    "ko": "kor", "kor": "kor", "korean": "kor", "koreanisch": "kor",
}


def needs_preparing(path: str) -> bool:
    """Datei, die erst im Arbeitsbereich Vorbereiten Disc-fertig gemacht werden muss (classify_file kennt sie nicht)."""
    return classify_file(path) is None and os.path.splitext(path)[1].lower() in PREPARE_EXTS


def classify_file(path: str) -> Optional[str]:
    ext = os.path.splitext(path)[1].lower()
    if ext in VIDEO_EXTS:
        return KIND_VIDEO
    if ext in MVC_EXTS:
        return KIND_MVC
    if ext in AUDIO_EXTS:
        return KIND_AUDIO
    if ext in SUBTITLE_EXTS:
        return KIND_SUBTITLE
    if ext in CHAPTER_EXTS:
        return KIND_CHAPTERS
    return None


def guess_language(path: str, default: str = "und") -> str:
    """Erkennt eine Sprache aus dem Dateinamen (z. B. 'film_ger_51.ac3' → 'deu')."""
    name = os.path.splitext(os.path.basename(path))[0].lower()
    for token in reversed(re.split(r"[^a-zäöüéè]+", name)):
        if token in _LANGUAGE_ALIASES:
            return _LANGUAGE_ALIASES[token]
    return default


def prepare_audio_file(file_path: str) -> str:
    """
    Bereitet eine Tonspur für tsMuxeR vor und gibt den zu verwendenden Pfad zurück:
    - WAV: BWF/bext-Metadaten entfernen, 48 kHz / 24 Bit erzwingen (tsMuxeR WAV-Bug)
    - MP4: E-AC-3 verlustfrei extrahieren
    Bereits vorbereitete, aktuelle Dateien werden wiederverwendet.
    """
    lower = file_path.lower()
    if lower.endswith(".wav"):
        clean_path = os.path.splitext(file_path)[0] + "_clean.wav"
        if _is_up_to_date(clean_path, file_path):
            return clean_path
        print(tr("imp_wav_clean", file=os.path.basename(file_path)))
        cmd = [
            tool_path(FFMPEG), "-y", "-i", file_path,
            "-map_metadata", "-1",  # Strippt alle BWF/bext Metadaten
            "-fflags", "+bitexact", # Verhindert, dass FFmpeg neue Info-Chunks schreibt
            "-c:a", "pcm_s24le",    # Sichert sauberes 24-bit PCM
            "-ar", "48000",         # Erzwingt 48 kHz (Blu-ray Standard)
            clean_path
        ]
        try:
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, **NO_CONSOLE)
            return clean_path
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(tr("imp_wav_clean_failed", err=e))
            return file_path

    if lower.endswith(".mp4"):
        extracted_path = os.path.splitext(file_path)[0] + "_extracted.eac3"
        if _is_up_to_date(extracted_path, file_path):
            return extracted_path
        print(f"Extrahiere E-AC-3 Audio aus MP4: {os.path.basename(file_path)}")
        cmd = [tool_path(FFMPEG), "-y", "-i", file_path, "-vn", "-c:a", "copy", extracted_path]
        try:
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, **NO_CONSOLE)
            return extracted_path
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(tr("imp_mp4_extract_failed", err=e))
            return file_path

    return file_path


def _is_up_to_date(derived: str, source: str) -> bool:
    if not os.path.exists(derived):
        return False
    try:
        return os.path.getmtime(derived) >= os.path.getmtime(source)
    except OSError:
        return False
