# tests/test_top_bar.py
"""
Obere Leiste (v1.29.0): Marke links, Arbeitsbereiche als Reiter, Projektname mit Menü statt Neu/Öffnen/Speichern,
Rückgängig/Wiederholen nur als Symbol, „Ansicht“ statt „Arbeitsbereich“. Bei wenig Platz wird erst der Projektname
gekürzt, dann der Schriftzug ausgeblendet – kein Knopf verschwindet hinter dem »-Pfeil der Leiste.
"""

import os
import sys
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import Qt
from PySide6.QtGui import QUndoCommand
from PySide6.QtWidgets import QApplication, QToolButton

from core.translations import tr

app_instance = QApplication.instance() or QApplication(sys.argv)


def settle():
    """Größenänderung, Layout und die nachgelagerte Prüfung der Leiste abarbeiten."""
    for _ in range(3):
        app_instance.processEvents()


class TopBarCase(unittest.TestCase):
    def setUp(self):
        from gui.studio.main_window import StudioWindow
        self.win = StudioWindow(persist_layout=False)
        self.win.set_ui_lang("de")
        self.addCleanup(self.win.close)
        # Läuft zuerst (LIFO): bricht ein Test mit offener Änderung ab, wartet close() sonst auf die Rückfrage
        self.addCleanup(self.win.controller.undo_stack.setClean)
        self.win.show()
        self.win.resize(4000, 900)          # offscreen ohne Systemschriften sind Texte breiter als im Programm
        settle()

    def hidden_buttons(self):
        bar = self.win.toolbar
        return [a for a in bar.actions() if a.isVisible() and bar.widgetForAction(a) is not None
                and not bar.widgetForAction(a).isVisible()]


class TestTopBar(TopBarCase):
    def test_project_menu_replaces_file_buttons(self):
        bar = self.win.toolbar
        for act in (self.win.act_new, self.win.act_open, self.win.act_save, self.win.act_save_as):
            self.assertNotIn(act, bar.actions())
            self.assertIn(act, self.win.menu_project.actions())
            self.assertIn(act, self.win.actions())                 # Tastenkürzel gelten im ganzen Fenster
        self.assertIn(self.win.controller.project.settings.project_name, self.win.btn_project.text())

    def test_unsaved_dot_and_undo_tooltip(self):
        self.assertTrue(self.win.btn_project.icon().isNull())
        self.win.controller.undo_stack.push(QUndoCommand("Button verschieben"))
        self.assertFalse(self.win.btn_project.icon().isNull())
        self.assertIn(tr("studio_unsaved_changes", "de"), self.win.btn_project.toolTip())
        self.assertIn("Rückgängig: Button verschieben", self.win.act_undo.toolTip())
        # macOS zeigt das Kürzel als „⌘Z“, Windows/Linux als „Strg+Z“
        self.assertIn("⌘Z" if sys.platform == "darwin" else "Strg+Z", self.win.act_undo.toolTip())
        self.win.controller.undo_stack.setClean()
        self.assertTrue(self.win.btn_project.icon().isNull())

    def test_history_buttons_show_only_icons(self):
        for act in (self.win.act_undo, self.win.act_redo):
            button = self.win.toolbar.widgetForAction(act)
            self.assertEqual(button.toolButtonStyle(), Qt.ToolButtonIconOnly)
            self.assertFalse(act.icon().isNull())

    def test_view_menu_and_page_tabs(self):
        self.assertTrue(self.win.btn_workspace.text().startswith("Ansicht"))
        self.win.set_ui_lang("en")
        self.assertTrue(self.win.btn_workspace.text().startswith("View"))
        tabs = [self.win.toolbar.widgetForAction(a) for a in self.win.page_actions.values()]
        self.assertEqual({t.objectName() for t in tabs}, {"page_tab"})

    def test_brand_and_language_texts(self):
        self.assertEqual(self.win.brand.name.text(), "OpenBDAuth")
        self.assertTrue(self.win.brand.version.text().startswith("v"))
        self.assertTrue(self.win.btn_ui_lang.isVisible())
        self.assertNotIn("ⓘ", [b.text() for b in self.win.toolbar.findChildren(QToolButton)])


class TestNarrowWindow(TopBarCase):
    """Breiten aus dem gemessenen Bedarf, nicht fest: offscreen hängen die Textbreiten von den Schriften ab."""

    def resize_bar(self, width: int):
        self.win.resize(width, 800)
        settle()
        self.assertEqual(self.hidden_buttons(), [], f"bei {self.win.toolbar.width()} Pixeln")
        self.assertLessEqual(self.win._toolbar_needed_width(), self.win.toolbar.width())

    def need(self, text_width, compact) -> int:
        self.win._project_text_width = text_width
        self.win.brand.set_compact(compact)
        self.win._update_project_button(fit=False)
        return self.win._toolbar_needed_width()

    def test_project_button_in_the_middle(self):
        """v1.30.2: Projekt mittig in der Leiste – auf jeder Seite, auch nach Verkleinern."""
        from gui.studio.main_window import CENTER_MIN_GAP, PAGE_BURN, PAGE_PREPARE
        for page in ("disc", PAGE_PREPARE, PAGE_BURN):
            self.win.show_page(page)
            for width in (4000, 2400):
                self.win.resize(width, 900)
                settle()
                center = self.win.btn_project.geometry().center().x()
                offset = center - self.win.toolbar.width() / 2
                # Ist links zu wenig Platz (Abstand schon am Minimum), rückt der Knopf nach rechts – nie über andere
                # Knöpfe. Wann das passiert, hängt von der Schrift ab: unter Windows ist Vorbereiten bei 2400 px
                # zu eng, unter macOS nicht. Bei 4000 px passt es überall.
                pushed_right = offset > 0 and self.win._center_gap.width() == CENTER_MIN_GAP
                if width == 4000 or not pushed_right:
                    self.assertLessEqual(abs(offset), 2, f"{page} bei {width}")
                self.assertEqual(self.hidden_buttons(), [])

    def test_wide_window_keeps_everything(self):
        self.assertFalse(self.win.brand.compact)
        self.assertNotIn("…", self.win.btn_project.text())
        self.assertEqual(self.hidden_buttons(), [])

    def test_narrow_window_shortens_name_then_brand(self):
        from gui.studio.main_window import PAGE_PREPARE
        self.win.show_page(PAGE_PREPARE)        # die Disc-Seite lässt wegen der Docks kein so schmales Fenster zu
        self.win.controller.project.settings.project_name = "Unser großer Familienurlaub in Kanada und Alaska 2026"
        self.win._update_title()
        settle()
        full, short = self.need(None, False), self.need(160, False)
        self.assertLess(short, full)

        self.resize_bar(full - 20)               # erst der Name wird gekürzt
        self.assertIn("…", self.win.btn_project.text())
        self.assertFalse(self.win.brand.compact)

        self.resize_bar(short - 20)              # dann verschwindet der Schriftzug
        self.assertTrue(self.win.brand.compact)
        self.assertTrue(self.win.brand.version.isVisible())

        self.resize_bar(4000)                    # wieder breit: alles zurück
        self.assertFalse(self.win.brand.compact)
        self.assertNotIn("…", self.win.btn_project.text())


if __name__ == "__main__":
    unittest.main()
