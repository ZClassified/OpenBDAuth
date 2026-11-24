# modules/prepare/checks.py
"""
Prüfungen beim Import in den Film-Knoten: 3D-Videos (v1.21, Basis-Video .264 und Dependent View .mvc) und
HEVC-Ströme für Ultra HD Blu-ray (UHD-Plan, Weg B: fertiger Strom, wird nicht neu kodiert, sondern geprüft).

Ergebnisse im Format der Kompatibilitätshinweise (modules/video_tools.ComplianceWarning.to_dict):
- severity "error": Das Paar passt nachweislich nicht zusammen (mvctools.verify). Der Preflight meldet es als
  Fehler, Bestätigen hilft nicht – tsMuxeR würde es klaglos muxen, der Player zeigt aber kein sauberes 3D.
- severity "warning": Format außerhalb dessen, was Blu-ray 3D vorsieht (wie die übrigen Hinweise bestätigbar).

Die Import-Regel ist großzügiger als das, was Vorbereiten erzeugt (Konzept, „Ton“ und „Eine Regel für
Blu-ray-tauglich“): 720p mit 50/59,94 fps wird angenommen, auch wenn Vorbereiten nur 1080p mit 23,976/24 fps baut.
"""

import os
from typing import Callable, List, Optional

from core.translations import tr
from modules.prepare.jobs import is_bd3d_fps
from modules.video_tools import ComplianceWarning

PAIR_PROBLEMS_SHOWN = 5


def _is_720p_3d_fps(fps: float) -> bool:
    return abs(fps - 50.0) < 0.05 or abs(fps - 60000 / 1001) < 0.05


def stereo_format_warnings(details: Optional[dict]) -> List[dict]:
    """Hinweis, wenn Auflösung und Bildrate des Basis-Videos nicht zu Blu-ray 3D passen."""
    if not details:
        return []
    width, height, fps = details.get("width", 0), details.get("height", 0), float(details.get("fps") or 0)
    if not width or not height:
        return []
    if (width, height) == (1920, 1080) and is_bd3d_fps(fps):
        return []
    if (width, height) == (1280, 720) and _is_720p_3d_fps(fps):
        return []
    return [ComplianceWarning.of("STEREO_FORMAT", width=width, height=height, fps=f"{fps:.3f}").to_dict()]


def check_pair(base_path: str, mvc_path: str,
               progress: Optional[Callable[[float], None]] = None) -> List[dict]:
    """
    Prüft, ob Basis-Video und Dependent View Bild für Bild zusammenpassen (mvctools.verify: Bildanzahl, POC,
    Bildtypen, IDR/Anchor, PPS-IDs). progress(Anteil 0..1) über beide Dateien. Leere Liste = in Ordnung.
    """
    from mvctools.verify import verify_pair

    base_size = max(os.path.getsize(base_path), 1)
    total = base_size + max(os.path.getsize(mvc_path), 1)

    def report(label, offset):
        if progress:
            progress(min(1.0, ((base_size if label == "Dependent View" else 0) + offset) / total))

    problems, info = verify_pair(base_path, mvc_path, progress=report)
    if not problems:
        return []
    shown = problems[:PAIR_PROBLEMS_SHOWN]
    more = len(problems) - len(shown)
    details = "; ".join(shown) + (tr("cw_more", n=more) if more > 0 else "")
    return [ComplianceWarning.of("MVC_PAIR_MISMATCH", severity="error", details=details).to_dict()]


def unchecked_warning(reason: str) -> dict:
    """Hinweis, wenn die Paar-Prüfung abgebrochen wurde oder nicht lief (bestätigbar wie andere Hinweise)."""
    return ComplianceWarning.of("MVC_PAIR_UNCHECKED", reason=reason).to_dict()


def check_hevc(path: str, progress: Optional[Callable[[float], None]] = None) -> dict:
    """
    Prüft einen HEVC-Strom nach den Regeln für Ultra HD Blu-ray (hevctools.check). Rückgabe: {"warnings": [...],
    "details": {...}} – Fehler als ein Hinweis mit severity "error" (Bestätigen hilft nicht), Warnungen als ein
    bestätigbarer Hinweis; details ergänzt die Kenndaten (Dauer, Bildanzahl, HDR-Werte).
    """
    from hevctools.check import ERROR, WARNING, check_stream

    size = max(os.path.getsize(path), 1)
    findings, info = check_stream(path, progress=(lambda _label, offset: progress(min(1.0, offset / size)))
                                  if progress else None)
    warnings = []
    for level, code in ((ERROR, "HEVC_UHD_ERROR"), (WARNING, "HEVC_UHD_WARNING")):
        texts = [f.text for f in findings if f.level == level]
        if texts:
            shown = texts[:PAIR_PROBLEMS_SHOWN]
            more = len(texts) - len(shown)
            details = "; ".join(shown) + (tr("cw_more", n=more) if more > 0 else "")
            warnings.append(ComplianceWarning.of(code, severity="error" if level == ERROR else "warning",
                                                 details=details).to_dict())
    details = {"duration_s": info["duration"]} if info.get("duration") else {}
    if info.get("dynamic_range"):
        details["dynamic_range"] = info["dynamic_range"]
    details["pictures"] = info.get("pictures", 0)
    return {"warnings": warnings, "details": details}


def hevc_unchecked_warning(reason: str) -> dict:
    """Hinweis, wenn die HEVC-Prüfung abgebrochen wurde oder nicht lief (bestätigbar)."""
    return ComplianceWarning.of("HEVC_UNCHECKED", reason=reason).to_dict()
