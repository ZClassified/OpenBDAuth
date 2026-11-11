# modules/prepare/selftest.py
"""
Selbsttest des fertigen Pakets (v1.25.1): OpenBDAuth.exe --selbsttest <Ergebnisdatei>

Prüft ohne Fenster genau den Weg, den Vorbereiten im Paket nimmt: Kindprozess über multiprocessing (im Paket startet
dieselbe EXE noch einmal), mitgeliefertes ffmpeg mit x264, je ein kurzer 2D- und 3D-Auftrag über run_task
(Zwischenordner, MVC-Rewriter, Paarprüfung, Verschieben). tools/build_release.py ruft ihn nach jedem Build auf.
Ergebnis als JSON: {"ok": bool, "result": {...}, "error": str}.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

TIMEOUT_SECONDS = 300


def child_check(progress=None) -> dict:
    """Läuft im Kindprozess: kurze 2D- und 3D-Aufträge mit den mitgelieferten Werkzeugen."""
    from modules.prepare import jobs, tasks, use_bundled_tools
    from modules.prepare.runner import run_task
    use_bundled_tools()
    result = {"ffmpeg": jobs.tool("ffmpeg"), "libx264": jobs.ffmpeg_has_libx264()}
    work = tempfile.mkdtemp(prefix="openbdauth_selftest_")
    try:
        sources = {"2d": ("testsrc2=s=1280x720:r=24:d=1", "selbsttest_2d.mp4"),
                   "3d": ("testsrc2=s=1920x2160:r=24000/1001:d=1", "selbsttest_3d.mp4")}
        for kind, (graph, name) in sources.items():
            src = os.path.join(work, name)
            subprocess.run([jobs.tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", graph, "-pix_fmt",
                            "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", src], check=True,
                           creationflags=jobs.NO_WINDOW)
            task = tasks.create_task(src)
            log = []
            outputs = run_task(task, progress=lambda share: None,
                               log=lambda text, is_progress=False: log.append(text), cancelled=lambda: False)
            result[kind] = [os.path.basename(p) for p in outputs or []]
            if progress:
                progress(0.5 if kind == "2d" else 1.0)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return result


def run(out_path: str) -> int:
    """Startet child_check in einem eigenen Prozess (wie Vorbereiten) und schreibt das Ergebnis nach out_path."""
    from modules.prepare.background import BackgroundTask
    report = {"ok": False, "result": None, "error": ""}
    try:
        task = BackgroundTask(child_check)
        end = time.time() + TIMEOUT_SECONDS
        while not task.poll():
            if time.time() > end:
                task.cancel()
                report["error"] = "Zeitüberschreitung"
                break
            time.sleep(0.1)
        if task.finished and not report["error"]:
            report["result"], report["error"] = task.result, task.error or ""
            result = task.result or {}
            report["ok"] = (not task.error and result.get("libx264") and result.get("2d") == ["selbsttest_2d.264"]
                            and result.get("3d") == ["selbsttest_3d_3D.264", "selbsttest_3d_3D.mvc"])
    except Exception as e:      # alles ins Ergebnis, das Paket hat keine Konsole
        report["error"] = f"{type(e).__name__}: {e}"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1, ensure_ascii=False)
    return 0 if report["ok"] else 1


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    index = argv.index("--selbsttest")
    out_path = argv[index + 1] if len(argv) > index + 1 else os.path.join(tempfile.gettempdir(),
                                                                          "openbdauth_selbsttest.json")
    return run(out_path)
