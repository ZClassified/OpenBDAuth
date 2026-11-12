# main.py
"""
Haupt-Einstiegspunkt für OpenBDAuth.
Initialisiert die PySide6 (Qt 6) Application mit dem Design-System aus gui/theme.py (apply_theme).
Im fertigen Paket (PyInstaller, ohne Konsole) erscheinen Startfehler als Meldungsfenster (v1.19.2).
"""

import sys
import traceback
from PySide6.QtWidgets import QApplication, QMessageBox
from gui.theme import apply_theme


def main():
    print("Starte OpenBDAuth (PySide6 / Qt 6)...")
    app = QApplication(sys.argv)
    try:
        apply_theme(app)
        from gui.icons import use_app_icon
        use_app_icon(app)

        from gui.studio.main_window import StudioWindow
        window = StudioWindow()
        window.show()

        sys.exit(app.exec())
    except Exception:
        details = traceback.format_exc()
        if sys.stdin is None or getattr(sys, "frozen", False):
            QMessageBox.critical(None, "OpenBDAuth", "OpenBDAuth konnte nicht gestartet werden.\n\n" + details)
            sys.exit(1)
        print("\n" + "=" * 50)
        print("KRITISCHER FEHLER BEIM STARTEN DER GUI:")
        print("=" * 50)
        print(details)
        print("=" * 50 + "\n")
        input("Drücke Enter, um das Fenster zu schließen...")


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()   # Prüf- und Encoding-Prozesse im fertigen Paket (modules/prepare/background.py)
    from modules.external_tools import restore_system_library_path
    restore_system_library_path()      # Linux-Paket: Systemprogramme mit ihren eigenen Bibliotheken starten
    if "--selbsttest" in sys.argv:     # Paket ohne Fenster prüfen (modules/prepare/selftest.py, build_release.py)
        from modules.prepare.selftest import main as selftest
        sys.exit(selftest())
    main()
