"""Schnelle Konsistenzprüfung eines Base-/Dependent-View-Paares (für die GUI und als CLI).

Aufruf:
    python -m mvctools.verify BASE.264 DEP.mvc
"""

import sys

from .stream import StreamParser


def verify_pair(base_path, dep_path, progress=None):
    """Prüft, ob beide Views Bild für Bild zusammenpassen.

    Rückgabe: (probleme: list[str], info: dict). Leere Problemliste = alles in Ordnung.
    """
    base = StreamParser(base_path, "Base View").parse(progress)
    dep = StreamParser(dep_path, "Dependent View").parse(progress)
    problems = []
    for sp in (base, dep):
        problems += [f"{sp.label}: {e}" for e in sp.errors[:5]]
    bp, dp = base.pictures(), dep.pictures()
    if len(bp) != len(dp):
        problems.append(f"Bildanzahl unterschiedlich: Base {len(bp)}, Dependent {len(dp)}")
    for label, pics in (("Base View", bp), ("Dependent View", dp)):
        bad = sum(1 for p in pics if not p["cabac_align_ok"])
        if bad:
            problems.append(f"{label}: {bad} Bilder mit inkonsistentem Slice-Header")
    if any(p["mvc"] is None for p in dp):
        problems.append("Dependent View enthält Slices ohne MVC-Header (kein NAL 20)")
    if set(base.pps) & set(dep.pps):
        problems.append(f"PPS-ID-Kollision zwischen den Views: {sorted(set(base.pps) & set(dep.pps))}")
    mism = 0
    first = None
    for i, (b, d) in enumerate(zip(bp, dp)):
        anchor = (d["mvc"] or {}).get("anchor_pic_flag", 0)
        ok = (b["poc"] == d["poc"] and b["idr"] == d["idr"]
              and bool(b["ref_idc"]) == bool(d["ref_idc"])
              and (b["type"] == d["type"] or (b["type"] == "I" and anchor))
              and anchor == (1 if b["type"] == "I" else 0))
        if not ok:
            mism += 1
            first = i if first is None else first
    if mism:
        problems.append(f"{mism} Bilder passen nicht zusammen (POC/Bildtyp/IDR/Anchor), erstes bei Bild {first}")
    info = {"pictures": len(bp), "base_bytes": base.total_bytes, "dep_bytes": dep.total_bytes}
    return problems, info


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print(__doc__)
        return 2
    problems, info = verify_pair(argv[0], argv[1])
    print(f"{info['pictures']} Bilder geprüft.")
    for p in problems:
        print("PROBLEM:", p)
    print("OK" if not problems else "FEHLER")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
