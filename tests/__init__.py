# tests/__init__.py
"""
Aufräumen am Ende des Testlaufs: Die Tests schließen ihre Fenster nur (close() blendet aus), gelöscht werden sie
nicht. Nach einem vollen Lauf leben so über hundert Hauptfenster mit Tausenden Widgets bis zum Interpreter-Ende,
und PySide6 baut sie beim Herunterfahren in beliebiger Reihenfolge ab – unter macOS stürzt Python dabei ab
(SIGSEGV in ~QSpinBox, obwohl alle Tests grün sind). Deshalb hier vorher geordnet löschen.
"""

import atexit
import gc

from PySide6 import QtCore  # noqa: F401 – vorher importieren: atexit ruft zuletzt Registriertes zuerst auf


def _delete_leftover_widgets():
    """
    Einzeln löschen und danach neu nachsehen: Popups (z. B. die Liste eines QCompleter) gehören ihrem Besitzer
    und verschwinden mit ihm – vorab mitgelöscht würden sie doppelt freigegeben. Deshalb zuerst die echten
    Fenster, dann was übrig bleibt.
    """
    import shiboken6
    from PySide6.QtCore import QCoreApplication, QEvent, Qt
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        return

    def is_popup(widget):
        return widget.windowType() in (Qt.Popup, Qt.ToolTip)

    for popups_too in (False, True):
        while True:
            left = [w for w in QApplication.topLevelWidgets()
                    if shiboken6.isValid(w) and w.parent() is None and (popups_too or not is_popup(w))]
            if not left:
                break
            left[0].deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    gc.collect()


atexit.register(_delete_leftover_widgets)
