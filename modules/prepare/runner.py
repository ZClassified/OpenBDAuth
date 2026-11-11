# modules/prepare/runner.py
"""
Ausführung eines Auftrags (v1.22) – läuft im eigenen Prozess (modules/prepare/background.BackgroundTask).

- stream_command: ffmpeg zeilenweise mitlesen (Fortschritt aus time=, Protokoll), Abbrechen beendet ffmpeg selbst
  (unter Windows enden Kindprozesse nicht mit dem Elternprozess). Vorlage: run_command_streaming in BD3DEnc.py.
- run_task: encodiert in <Ausgabeordner>/_unfertig/<Auftrag>/, prüft die Ergebnisse und verschiebt sie erst dann
  in den Ausgabeordner. Eine Datei mit fertigem Namen ist damit immer vollständig und geprüft; bei Fehler oder
  Abbruch bleibt nichts liegen.
"""

import os
import queue
import re
import shutil
import subprocess
import threading
from typing import Callable, List, Optional

from core.translations import tr
from modules.prepare import jobs, tasks, use_bundled_tools

TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")
POLL_SECONDS = 0.2


class TaskFailed(RuntimeError):
    pass


def _read_lines(stream, lines: "queue.Queue"):
    """ffmpeg trennt Fortschrittszeilen mit \\r, alles andere mit \\n."""
    buffer = bytearray()
    for chunk in iter(lambda: stream.read(256), b""):
        for b in chunk:
            if b in (10, 13):
                if buffer:
                    lines.put(buffer.decode("utf-8", errors="replace"))
                    buffer.clear()
            else:
                buffer.append(b)
    if buffer:
        lines.put(buffer.decode("utf-8", errors="replace"))
    lines.put(None)


def stream_command(step: jobs.Step, job: jobs.Job, log: Callable, progress: Callable[[float], None],
                   cancelled: Callable[[], bool]) -> int:
    """run_cmd für jobs.run_job: Ausgabe streamen, Fortschritt im Abschnitt step.progress, Abbrechen jederzeit."""
    log(jobs.banner(step.title))
    log("> " + subprocess.list2cmdline(step.cmd))
    try:
        proc = subprocess.Popen(step.cmd, cwd=job.cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                creationflags=jobs.NO_WINDOW)
    except OSError as e:
        log(tr("prep_log_start_error", err=e))
        return -1
    lines: "queue.Queue" = queue.Queue()
    threading.Thread(target=_read_lines, args=(proc.stdout, lines), daemon=True).start()
    lo, hi = step.progress
    while True:
        if cancelled():
            proc.kill()
            proc.wait()
            return jobs.CANCELLED
        try:
            line = lines.get(timeout=POLL_SECONDS)
        except queue.Empty:
            continue
        if line is None:
            break
        line = line.strip()
        if not line:
            continue
        match = TIME_RE.search(line)
        if match and job.duration > 0:
            seconds = int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))
            progress(lo + (hi - lo) * min(0.99, max(0.0, seconds / job.duration)))
        is_progress = line.startswith(("frame=", "size="))
        log(line, is_progress=is_progress)
    return proc.wait()


def check_outputs(job: jobs.Job, kind: str):
    """Ergebnisse vor dem Verschieben prüfen (3D prüft der Auftrag selbst mit verify_pair)."""
    for path in job.outputs:
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            raise TaskFailed(tr("prep_result_missing", file=os.path.basename(path)))
    first = job.outputs[0]
    try:
        if kind == tasks.KIND_AUDIO:
            jobs.probe_audio(first)
        else:
            info = jobs.probe_video(first)
            if not info.width or not info.height:
                raise ValueError(tr("prep_no_picture_size"))
    except ValueError as e:
        raise TaskFailed(tr("prep_result_unreadable", file=os.path.basename(first), err=e))


def run_task(task: tasks.PrepareTask, progress: Callable[[float], None], log: Callable,
             cancelled: Callable[[], bool]) -> Optional[List[str]]:
    """
    Führt den Auftrag aus und gibt die fertigen Dateien im Ausgabeordner zurück; None bei Abbruch.
    TaskFailed bei einem Fehler (das Protokoll steht dann schon in log).
    """
    use_bundled_tools()
    staging = tasks.staging_dir(task)
    os.makedirs(staging, exist_ok=True)
    adaptive = task.kind != tasks.KIND_3D or jobs.ffmpeg_supports_option_files()
    try:
        job = tasks.build_job(task, out_dir=staging, adaptive=adaptive)
        ret = jobs.run_job(job, run_cmd=lambda step, j: stream_command(step, j, log, progress, cancelled),
                           log=log, progress=progress, cancelled=cancelled)
        if ret == jobs.CANCELLED:
            return None
        if ret != 0:
            raise TaskFailed(tr("prep_step_failed", code=ret))
        check_outputs(job, task.kind)
        finished = []
        for path in job.outputs:
            target = os.path.join(task.out_dir, os.path.basename(path))
            os.replace(path, target)        # gleiches Laufwerk: in einem Schritt
            finished.append(target)
        progress(1.0)
        return finished
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        try:
            os.rmdir(os.path.dirname(staging))      # _unfertig, wenn leer
        except OSError:
            pass
