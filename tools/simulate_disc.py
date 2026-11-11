#!/usr/bin/env python3
# tools/simulate_disc.py
"""
Disc-Simulator (Befehlszeile): spielt die Navigation einer fertigen Disc automatisch durch
und meldet Fehler, Warnungen und Hinweise – ohne zu brennen.

Aufruf:
    python tools/simulate_disc.py <Disc-Ordner | BDMV-Ordner | .iso>
    python tools/simulate_disc.py disc.iso --tv 2d        # nur Durchlauf mit 2D-Fernseher
    python tools/simulate_disc.py disc.iso --struktur     # zusätzlich alle Befehle auflisten
    python tools/simulate_disc.py disc.iso --fenster      # Disc im Simulator-Fenster durchklicken

Eine ISO wird unter Windows schreibgeschützt eingehängt und danach wieder ausgehängt.
Rückgabewert: 0 = keine Fehler/Warnungen, 1 = Befunde, 2 = Disc nicht lesbar.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.bdsim.disc import load_disc, DiscReadError
from modules.bdsim.source import mounted_iso
from modules.bdsim.explore import explore, format_report

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def open_window(disc) -> int:
    from PySide6.QtWidgets import QApplication
    from gui.theme import apply_theme
    from gui.studio.simulator import SimulatorWindow
    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(app)
    window = SimulatorWindow(disc)
    window.show()
    return app.exec()


def run(path: str, tvs, show_structure: bool, window: bool = False) -> int:
    disc = load_disc(path)
    if window:
        return open_window(disc)
    reports = [explore(disc, tv_3d=tv) for tv in tvs]
    print(format_report(disc, reports, detailed=show_structure))
    return 0 if all(r.ok for r in reports) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenBDAuth Disc-Simulator")
    parser.add_argument("path", help="Disc-Ordner, BDMV-Ordner oder .iso")
    parser.add_argument("--tv", choices=("3d", "2d", "beide"), default="beide",
                        help="Fernseher für den Durchlauf (Standard: beide)")
    parser.add_argument("--struktur", action="store_true", help="alle Buttons und MovieObjects mit Befehlen auflisten")
    parser.add_argument("--fenster", action="store_true", help="Disc im Simulator-Fenster durchklicken")
    args = parser.parse_args()
    tvs = {"3d": [True], "2d": [False], "beide": [True, False]}[args.tv]
    try:
        if args.path.lower().endswith(".iso"):
            with mounted_iso(args.path) as drive:
                return run(drive, tvs, args.struktur, args.fenster)
        return run(args.path, tvs, args.struktur, args.fenster)
    except DiscReadError as ex:
        print(f"⛔ {ex}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
