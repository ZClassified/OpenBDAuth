# modules/prepare/tasks.py
"""
Aufträge im Arbeitsbereich Vorbereiten (v1.22, ohne Qt): Quelle, Art, Einstellungen, Ausgabeordner, Status.

Ein Auftrag fasst das Disc-Projekt nie an (Konzept, Grundsatz 2). Er merkt sich höchstens einen Film als
Vorschlag fürs Übernehmen; übernommen wird per Klick über den bestehenden Import.

Ablauf: create_task (Quelle prüfen, Vorbelegung) → Einstellungen im Inspektor → modules.prepare.runner.run_task
in einem eigenen Prozess (encodiert nach _unfertig/, verschiebt erst nach der Prüfung) → fertige Dateien.
"""

import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

from modules.prepare import jobs, use_bundled_tools

OUT_DIR_NAME = "Disc-fertig"          # fester Name, unabhängig von der Oberflächensprache (Konzept, Ausgabeordner)
STAGING_DIR_NAME = "_unfertig"        # darin entsteht ein Auftrag; fertige Dateien werden erst danach verschoben

KIND_2D, KIND_3D, KIND_AUDIO = "2d", "3d", "audio"
WAITING, RUNNING, DONE, FAILED, CANCELLED = "waiting", "running", "done", "failed", "cancelled"

BITRATES_2D = (25, 20, 15)                 # Mbit/s (Mittel), wie BD3DEnc
BUDGETS_3D = (30000, 25000, 20000)         # kbit/s für beide Augen zusammen

# Kapazität für den Füllstand (v1.23): BD-25/BD-50 in Bytes, wie auf der Hülle
DISC_SIZES = {"bd25": 25_000_000_000, "bd50": 50_000_000_000}
COPY_KBPS_GUESS = 1536                     # 1:1-Ton ohne bekannte Bitrate: wie DTS 5.1
QUEUE_VERSION = 1


class SourceRejected(ValueError):
    """Die Quelle ist nicht Blu-ray-tauglich; problems = [(Code, Details)] aus jobs.source_problems."""

    def __init__(self, problems: list, text: str = ""):
        super().__init__(text or jobs.describe_problems(problems))
        self.problems = problems


@dataclass
class PrepareTask:
    id: str
    source: str
    kind: str
    video: Optional[jobs.SourceInfo] = None
    audio: Optional[jobs.AudioSource] = None
    layout: Optional[str] = None           # erkanntes 3D-Format der Quelle ("tab" / "sbs")
    # 2D
    bitrate_2d: int = 20
    target_720p: bool = False
    psf_25: bool = True                    # 30/60 fps werden immer an 29,97/59,94 angepasst (v1.25, keine Wahl)
    # 3D
    total_kbps: int = 25000
    # Ton
    audio_track: int = 0
    audio_format: str = ""
    # Ziel
    out_dir: str = ""
    target_film_id: Optional[str] = None   # Vorschlag beim Übernehmen, mehr nicht
    confirmed: bool = False                # v1.23: Einstellungen festgelegt (geändert oder „Passt so“)
    # Lauf
    status: str = WAITING
    progress: float = 0.0
    outputs: List[str] = field(default_factory=list)   # fertige Dateien (nach Erfolg)
    error: str = ""
    log: List[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return os.path.basename(self.source)

    @property
    def is_video(self) -> bool:
        return self.kind in (KIND_2D, KIND_3D)

    @property
    def editable(self) -> bool:
        return self.status != RUNNING

    @property
    def duration(self) -> float:
        if self.video is not None:
            return self.video.duration
        return self.audio.duration if self.audio is not None else 0.0

    def track(self) -> Optional[jobs.AudioTrack]:
        if self.audio is None or not self.audio.tracks:
            return None
        return self.audio.tracks[min(self.audio_track, len(self.audio.tracks) - 1)]


def default_out_dir(source: str, common_dir: Optional[str] = None) -> str:
    """Ausgabeordner: ein gemeinsamer Ordner für alle (v1.23) oder Disc-fertig neben der Quelle."""
    return common_dir or os.path.join(os.path.dirname(source), OUT_DIR_NAME)


def create_task(path: str, common_dir: Optional[str] = None) -> PrepareTask:
    """Liest die Quelle und belegt den Auftrag vor (2D/3D aus der Auflösung, 720p/1080 aus der Bildrate).
    SourceRejected, wenn die Quelle nicht Blu-ray-tauglich ist; ValueError, wenn sie weder Bild noch Ton hat;
    jobs.ProbeError, wenn ffprobe die Datei nicht lesen kann; OSError, wenn ffprobe nicht startet."""
    # Wie run_task: das mitgelieferte ffprobe, nicht das aus dem PATH (v1.27.4). Bis dahin nahm das Hinzufügen im
    # Hauptprozess das ffprobe aus dem PATH – unter Linux mit den Bibliotheken des Pakets, ohne PATH-ffprobe gar keins.
    use_bundled_tools()
    task = PrepareTask(id=uuid.uuid4().hex[:8], source=path, kind=KIND_2D,
                       out_dir=default_out_dir(path, common_dir))
    try:
        video = jobs.probe_video(path)
    except jobs.ProbeError:
        raise
    except ValueError:
        video = None
    if video is None:
        task.kind = KIND_AUDIO
        task.audio = jobs.probe_audio(path)    # ValueError: weder Bild noch Ton
        task.audio_format = jobs.audio_track_options(task.track())[0]
        return task
    task.video = video
    task.layout = jobs.stereo_layout(video.width, video.height)
    task.kind = KIND_3D if task.layout else KIND_2D
    problems = jobs.source_problems(video, task.kind)
    if problems:
        raise SourceRejected(problems)
    task.target_720p = bool(jobs.forced_720p(video.fps_str))
    return task


def set_kind(task: PrepareTask, kind: str) -> list:
    """2D/3D umstellen (z. B. ein echtes 2D-Panorama in 3840 × 1080). Gibt die Probleme der neuen Art zurück und
    stellt nur um, wenn es keine gibt."""
    if not task.is_video or kind not in (KIND_2D, KIND_3D):
        return []
    problems = jobs.source_problems(task.video, kind)
    if not problems:
        task.kind = kind
    return problems


def resolution_choice(task: PrepareTask) -> Optional[bool]:
    """None: 720p und 1080 wählbar (23,976/24 fps); sonst die Vorgabe der Bildrate (True = nur 720p)."""
    return jobs.forced_720p(task.video.fps_str) if task.video is not None else None


def build_job(task: PrepareTask, out_dir: Optional[str] = None, adaptive: bool = True) -> jobs.Job:
    """Der Auftrag als jobs.Job, mit Ausgaben in out_dir (Vorgabe: der Ausgabeordner des Auftrags)."""
    out_dir = out_dir or task.out_dir
    if task.kind == KIND_2D:
        return jobs.build_2d_job(task.video, task.bitrate_2d, task.target_720p, task.psf_25, conform_fps=True,
                                 out_dir=out_dir)
    if task.kind == KIND_3D:
        return jobs.build_3d_job(task.video, task.total_kbps, out_dir=out_dir, adaptive=adaptive)
    # Spur angeben bei Videos, mehreren Spuren und 1:1 (wie BD3DEnc); eine einfache WAV heißt danach <Name>.<Endung>
    audio = task.audio
    needs_track = audio.has_video or len(audio.tracks) > 1 or "1:1" in task.audio_format
    track = task.track() if needs_track else None
    return jobs.build_audio_job(task.source, task.audio_format, task.duration, track=track, out_dir=out_dir)


def planned_outputs(task: PrepareTask) -> List[str]:
    """Zieldateien im Ausgabeordner (so heißen sie nach dem Verschieben)."""
    return list(build_job(task).outputs)


def staging_dir(task: PrepareTask) -> str:
    return os.path.join(task.out_dir, STAGING_DIR_NAME, task.id)


def _existing_folder(folder: str) -> Optional[str]:
    """Der Ordner selbst oder sein nächster vorhandener Elternordner (der Ausgabeordner entsteht erst beim Start)."""
    while folder and not os.path.isdir(folder):
        parent = os.path.dirname(folder)
        if parent == folder:
            return None
        folder = parent
    return folder or None


def space_shortfall(task: PrepareTask) -> Optional[Tuple[int, int]]:
    """(benötigt, frei) in Bytes, wenn auf dem Laufwerk des Ausgabeordners voraussichtlich zu wenig Platz ist."""
    folder = _existing_folder(task.out_dir)
    if folder is None:
        return None
    try:
        free = shutil.disk_usage(folder).free
    except OSError:
        return None
    needed = build_job(task).space_needed
    return (needed, free) if needed > free else None


# --- Warteschlange (v1.23) ------------------------------------------------------------------------

def estimated_size(task: PrepareTask) -> int:
    """Geschätzte Größe der fertigen Dateien in Bytes (Laufzeit × mittlere Bitrate) für den Füllstand."""
    seconds = task.duration
    if task.kind == KIND_2D:
        return int(seconds * task.bitrate_2d * 125_000)
    if task.kind == KIND_3D:
        return int(seconds * task.total_kbps * 125)
    track = task.track()
    channels = track.channels if track else 2
    if "LPCM" in task.audio_format:
        return int(seconds * 48000 * 3 * (6 if "Downmix" in task.audio_format else channels))
    match = re.search(r"(\d+) kbps", task.audio_format)
    kbps = int(match.group(1)) if match else COPY_KBPS_GUESS
    return int(seconds * kbps * 125)


def duplicate_outputs(task_list: List[PrepareTask]) -> List[str]:
    """Zieldateien, die mehr als ein Auftrag schreiben würde (z. B. gleich benannte Quellen aus verschiedenen
    Ordnern in einem gemeinsamen Ausgabeordner)."""
    seen: Dict[str, str] = {}
    duplicates = []
    for task in task_list:
        try:
            outputs = planned_outputs(task)
        except ValueError:
            continue
        for path in outputs:
            key = os.path.normcase(os.path.abspath(path))
            if key in seen and seen[key] != task.id and path not in duplicates:
                duplicates.append(path)
            seen.setdefault(key, task.id)
    return duplicates


def remaining_seconds(elapsed: float, progress: float) -> Optional[float]:
    """Restzeit aus der bisherigen Geschwindigkeit; None, solange zu wenig Fortschritt da ist."""
    if progress < 0.02 or elapsed <= 0:
        return None
    return elapsed * (1.0 - progress) / progress


def task_to_dict(task: PrepareTask) -> dict:
    data = asdict(task)
    data.pop("log", None)
    data.pop("progress", None)
    if data["status"] == RUNNING:          # halbfertig: wird verworfen, nicht fortgesetzt
        data["status"] = WAITING
    return data


def task_from_dict(data: dict) -> PrepareTask:
    # Felder früherer Versionen (z. B. conform_fps bis v1.24) still übergehen, statt die Warteschlange zu verlieren
    known = set(PrepareTask.__dataclass_fields__)
    data = {k: v for k, v in data.items() if k in known}
    video, audio = data.pop("video", None), data.pop("audio", None)
    task = PrepareTask(**data)
    if video:
        task.video = jobs.SourceInfo(**video)
    if audio:
        tracks = [jobs.AudioTrack(**t) for t in audio.get("tracks", [])]
        task.audio = jobs.AudioSource(audio["path"], tracks, audio.get("duration", 0.0),
                                      audio.get("has_video", False))
    if task.status == RUNNING:
        task.status = WAITING
    return task


def save_queue(path: str, task_list: List[PrepareTask]):
    """Aufträge in eine eigene Datei (nicht in das Disc-Projekt, Konzept: Warteschlange)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"version": QUEUE_VERSION, "tasks": [task_to_dict(t) for t in task_list]}, f, indent=1,
                  ensure_ascii=False)
    os.replace(tmp, path)


def load_queue(path: str) -> List[PrepareTask]:
    """Gespeicherte Aufträge; unfertige stehen wieder auf „wartet“. Zwischenordner, die ein Absturz hinterlassen
    hat, werden entfernt. Eine unlesbare oder fremde Datei ergibt eine leere Liste."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("version") != QUEUE_VERSION:
            return []
        task_list = [task_from_dict(d) for d in data.get("tasks", [])]
    except (OSError, ValueError, TypeError, KeyError):
        return []
    for task in task_list:
        remove_staging(task)
    return task_list


def remove_staging(task: PrepareTask):
    shutil.rmtree(staging_dir(task), ignore_errors=True)
    try:
        os.rmdir(os.path.dirname(staging_dir(task)))
    except OSError:
        pass


def queue_space_shortfall(task_list: List[PrepareTask]) -> Optional[Tuple[int, int]]:
    """Wie space_shortfall für eine ganze Warteschlange, je Laufwerk: alle Ergebnisse zusammen plus der größte
    Zwischenbedarf eines Auftrags (sie laufen nacheinander und räumen ihre Zwischendateien jeweils weg)."""
    drives: Dict[int, list] = {}
    for task in task_list:
        folder = _existing_folder(task.out_dir)
        if folder is None:
            continue
        try:
            device, free = os.stat(folder).st_dev, shutil.disk_usage(folder).free
            result, peak = estimated_size(task), build_job(task).space_needed
        except (OSError, ValueError):
            continue
        entry = drives.setdefault(device, [0, 0, free])
        entry[0] += result
        entry[1] = max(entry[1], peak - result)
    for results, extra, free in drives.values():
        if results + extra > free:
            return results + extra, free
    return None
