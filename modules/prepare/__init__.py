# modules/prepare/__init__.py
"""
Vorbereiten: macht aus beliebigem Material Disc-fertige Streams (.264, .mvc,
Blu-ray-Ton).

- jobs.py: Befehlsaufbau als reine Funktionen, Aufträge als Schrittfolgen, run_job – unverändert aus BD3DEnc
  übernommen (hardware-geprüfte x264-Parameter; tests/test_prepare_jobs.py hält die Befehle fest).
- Der MVC-Rewriter und die Prüfung liegen im Paket mvctools/ (ebenfalls unverändert, docs/mvc/).
"""

from modules.prepare import jobs


def use_bundled_tools():
    """ffmpeg und ffprobe wie im übrigen Programm suchen (tools/<plattform>/, dann PATH)."""
    from modules.external_tools import find_tool
    jobs.configure_tools(find_tool)
