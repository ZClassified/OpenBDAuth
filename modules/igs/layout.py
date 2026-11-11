# modules/igs/layout.py
"""
Menü-Layout- und D-Pad-Navigations-Engine für OpenBDAuth.

Verwaltet dynamische Menü-Layouts für Blu-ray HDMV-Menüs:
- 1-Spalten-Layouts (z. B. Hauptmenüs mit 1..4 Buttons)
- 2-Spalten- und Grid-Layouts (z. B. Kapitelauswahl, Sprachauswahl)
- Automatische 4-Wege D-Pad Nachbarschafts-Berechnung (Fernbedienungs-Navigation)
- Vordefinierte Vorlagen für Haupt-, Kapitel- und Audiomenüs.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict
from modules.bdmv.movie_object_generator import (
    cmd_play_playlist,
    cmd_jump_title,
    cmd_set_button_page,
    chapter_jump_commands,
    stream_choice_commands,
    play_mode_commands,
)

@dataclass
class MenuButtonSpec:
    """
    High-Level Spezifikation eines interaktiven Buttons vor dem Rendern und Kompilieren.
    """
    button_id: int
    text: str
    action_type: str = "jump_title"  # "jump_title", "play_chapter", "set_stream", "set_page", "custom"
    target_title_id: int = 1                 # Titel des Films (auch für Kapitel- und Spur-Buttons)
    target_chapter_id: int = 1               # Kapitelnummer im Menü (1-basiert)
    chapter_time: Optional[str] = None       # Kapitel-Zeitstempel "HH:MM:SS.mmm" (für Marken-Zuordnung)
    target_mark_id: Optional[int] = None     # Aufgelöster PlayListMark-Index (0-basiert), gesetzt beim Export
    target_audio_id: Optional[int] = None
    target_subtitle_id: Optional[int] = None
    target_subtitle_on: Optional[bool] = None
    target_page_id: int = 0
    nav_commands: Optional[List[bytes]] = None
    play_2d: Optional[bool] = None           # v1.20, nur "jump_title" auf einen 3D-Film: 3D/2D merken; None = nichts

    # Geometrische Platzierung (Canvas 1920x1080)
    x: Optional[int] = None
    y: Optional[int] = None
    width: int = 380
    height: int = 70

    # 4-Wege D-Pad Pfeiltasten-Referenzen (Button-IDs)
    upper_id: Optional[int] = None
    lower_id: Optional[int] = None
    left_id: Optional[int] = None
    right_id: Optional[int] = None

    # Form-Button (modules.button_shapes.ShapeStyle); None = Text-Button mit Beschriftung
    shape: Optional[object] = None

    # v1.13: Standard-Button seiner Seite; unsichtbarer Button (keine Grafik); löst beim Auswählen sofort aus
    is_default: bool = False
    invisible: bool = False
    auto_action: bool = False

    def get_nav_commands(self) -> List[bytes]:
        """Gibt die 12-Byte HDMV Bytecode-Befehle für diesen Button zurück."""
        if self.nav_commands is not None:
            return self.nav_commands

        if self.action_type == "jump_title":
            prefix = play_mode_commands(self.play_2d) if self.play_2d is not None else []
            return prefix + [cmd_jump_title(self.target_title_id)]
        elif self.action_type == "play_chapter":
            # Kapitelwunsch merken und den Film als Titel starten; der Titel springt an die Marke.
            # PlayListMark-Index 0-basiert: Kapitel 1 = Marke 0
            mark_id = self.target_mark_id if self.target_mark_id is not None else max(0, self.target_chapter_id - 1)
            return chapter_jump_commands(self.target_title_id, mark_id)
        elif self.action_type == "set_stream":
            # Nur merken; der Titel schaltet beim Filmstart um (die Menü-Playlist hat die Spuren nicht)
            return stream_choice_commands(
                audio_id=self.target_audio_id,
                subtitle_id=self.target_subtitle_id,
                subtitle_on=self.target_subtitle_on
            )
        elif self.action_type == "set_page":
            return [cmd_set_button_page(self.target_page_id)]
        elif self.action_type == "play_playlist":
            return [cmd_play_playlist(self.target_title_id)]
        else:
            return [cmd_jump_title(self.target_title_id)]


class MenuLayoutEngine:
    """Berechnet Positionen und D-Pad Verknüpfungen für Menü-Buttons."""

    @staticmethod
    def layout_column(
        buttons: List[MenuButtonSpec],
        canvas_width: int = 1920,
        canvas_height: int = 1080,
        btn_w: int = 380,
        btn_h: int = 70,
        start_y: Optional[int] = None,
        spacing: int = 24,
        align: str = "center"
    ) -> List[MenuButtonSpec]:
        """
        Ordnet Buttons in einer vertikalen Spalte an und verknüpft Pfeiltasten (Up/Down Wrap-Around).
        """
        n = len(buttons)
        if n == 0:
            return buttons

        # Automatische Y-Positionierung falls nicht explizit vorgegeben
        if start_y is None:
            total_block_h = n * btn_h + (n - 1) * spacing
            if n == 1:
                start_y = 660
            elif n == 2:
                start_y = 620
                spacing = 30
            else:
                start_y = max(450, 720 - (total_block_h // 2))

        # X-Positionierung
        if align == "center":
            x_pos = (canvas_width - btn_w) // 2
        elif align == "left":
            x_pos = 150
        elif align == "right":
            x_pos = canvas_width - btn_w - 150
        else:
            x_pos = (canvas_width - btn_w) // 2

        # Buttons positionieren und D-Pad verknüpfen
        for i, btn in enumerate(buttons):
            btn.width = btn_w
            btn.height = btn_h
            btn.x = x_pos if btn.x is None else btn.x
            btn.y = (start_y + i * (btn_h + spacing)) if btn.y is None else btn.y

            # D-Pad Navigation: Vertikaler Wrap-Around
            if n == 1:
                btn.upper_id = btn.button_id
                btn.lower_id = btn.button_id
                btn.left_id = btn.button_id
                btn.right_id = btn.button_id
            else:
                prev_id = buttons[(i - 1) % n].button_id
                next_id = buttons[(i + 1) % n].button_id
                btn.upper_id = prev_id if btn.upper_id is None else btn.upper_id
                btn.lower_id = next_id if btn.lower_id is None else btn.lower_id
                btn.left_id = btn.button_id if btn.left_id is None else btn.left_id
                btn.right_id = btn.button_id if btn.right_id is None else btn.right_id

        return buttons

    @staticmethod
    def layout_grid(
        buttons: List[MenuButtonSpec],
        cols: int = 2,
        canvas_width: int = 1920,
        canvas_height: int = 1080,
        btn_w: int = 360,
        btn_h: int = 65,
        start_x: Optional[int] = None,
        start_y: Optional[int] = None,
        spacing_x: int = 40,
        spacing_y: int = 25
    ) -> List[MenuButtonSpec]:
        """
        Ordnet Buttons in einem 2D-Raster an (z. B. für Kapitel oder Optionen)
        mit vollständiger 4-Wege D-Pad Verknüpfung und Wrap-Around.
        """
        n = len(buttons)
        if n == 0:
            return buttons

        cols = max(1, min(cols, n))
        rows = (n + cols - 1) // cols

        total_grid_w = cols * btn_w + (cols - 1) * spacing_x
        total_grid_h = rows * btn_h + (rows - 1) * spacing_y

        if start_x is None:
            start_x = (canvas_width - total_grid_w) // 2
        if start_y is None:
            start_y = max(420, 680 - (total_grid_h // 2))

        # 2D Matrix für schnelles Nachschlagen: grid[r][c] = MenuButtonSpec
        grid: List[List[Optional[MenuButtonSpec]]] = [[None for _ in range(cols)] for _ in range(rows)]
        for i, btn in enumerate(buttons):
            r = i // cols
            c = i % cols
            btn.width = btn_w
            btn.height = btn_h
            btn.x = start_x + c * (btn_w + spacing_x) if btn.x is None else btn.x
            btn.y = start_y + r * (btn_h + spacing_y) if btn.y is None else btn.y
            grid[r][c] = btn

        # 4-Wege D-Pad Verknüpfungen für jeden Eintrag ermitteln
        for r in range(rows):
            for c in range(cols):
                btn = grid[r][c]
                if btn is None:
                    continue

                # Up: Vorherige Zeile in selber Spalte (mit Wrap-Around)
                up_btn = None
                for step in range(1, rows + 1):
                    target_r = (r - step) % rows
                    if grid[target_r][c] is not None:
                        up_btn = grid[target_r][c]
                        break
                btn.upper_id = up_btn.button_id if (up_btn and btn.upper_id is None) else btn.button_id

                # Down: Nächste Zeile in selber Spalte (mit Wrap-Around)
                down_btn = None
                for step in range(1, rows + 1):
                    target_r = (r + step) % rows
                    if grid[target_r][c] is not None:
                        down_btn = grid[target_r][c]
                        break
                btn.lower_id = down_btn.button_id if (down_btn and btn.lower_id is None) else btn.button_id

                # Left: Vorherige Spalte in selber Zeile (mit Wrap-Around)
                left_btn = None
                for step in range(1, cols + 1):
                    target_c = (c - step) % cols
                    if grid[r][target_c] is not None:
                        left_btn = grid[r][target_c]
                        break
                btn.left_id = left_btn.button_id if (left_btn and btn.left_id is None) else btn.button_id

                # Right: Nächste Spalte in selber Zeile (mit Wrap-Around)
                right_btn = None
                for step in range(1, cols + 1):
                    target_c = (c + step) % cols
                    if grid[r][target_c] is not None:
                        right_btn = grid[r][target_c]
                        break
                btn.right_id = right_btn.button_id if (right_btn and btn.right_id is None) else btn.button_id

        return buttons

    @staticmethod
    def _block_start_y(block_h: int, canvas_height: int = 1080) -> int:
        """Oberkante eines Button-Blocks: wie layout_grid, aber nie unter den unteren Bildrand (5 %)."""
        start_y = max(420, 680 - block_h // 2)
        return max(60, min(start_y, canvas_height - canvas_height // 20 - block_h))

    @staticmethod
    def _place_row(row: List[MenuButtonSpec], y: int, btn_w: int, btn_h: int, spacing_x: int,
                   start_x: Optional[int] = None, canvas_width: int = 1920):
        """Setzt eine Button-Zeile; ohne start_x zentriert."""
        if start_x is None:
            start_x = (canvas_width - (len(row) * btn_w + (len(row) - 1) * spacing_x)) // 2
        for c, btn in enumerate(row):
            btn.width = btn_w
            btn.height = btn_h
            btn.x = start_x + c * (btn_w + spacing_x) if btn.x is None else btn.x
            btn.y = y if btn.y is None else btn.y

    @staticmethod
    def _nearest(candidates: List[MenuButtonSpec], ref: MenuButtonSpec) -> MenuButtonSpec:
        """Button, dessen Mitte waagerecht am nächsten an ref liegt (bei Gleichstand der linke)."""
        center = ref.x + ref.width / 2
        return min(candidates, key=lambda b: (abs(b.x + b.width / 2 - center), b.x))

    @classmethod
    def _link_rows(cls, rows: List[List[MenuButtonSpec]]):
        """
        Pfeiltasten für Button-Zeilen: links/rechts innerhalb der Zeile, oben/unten in die vorige bzw.
        nächste Zeile auf den waagerecht nächsten Button, jeweils mit Wrap-Around.
        """
        rows = [r for r in rows if r]
        for i, row in enumerate(rows):
            above = rows[(i - 1) % len(rows)]
            below = rows[(i + 1) % len(rows)]
            for c, btn in enumerate(row):
                if btn.left_id is None:
                    btn.left_id = row[(c - 1) % len(row)].button_id
                if btn.right_id is None:
                    btn.right_id = row[(c + 1) % len(row)].button_id
                if btn.upper_id is None:
                    btn.upper_id = cls._nearest(above, btn).button_id
                if btn.lower_id is None:
                    btn.lower_id = cls._nearest(below, btn).button_id

    @classmethod
    def layout_fixed_grid(
        cls,
        grid_buttons: List[MenuButtonSpec],
        nav_buttons: List[MenuButtonSpec],
        cols: int = 4,
        btn_w: int = 360,
        btn_h: int = 65,
        spacing_x: int = 40,
        spacing_y: int = 25,
        nav_gap: int = 60,
        min_rows: int = 0,
        canvas_width: int = 1920,
        canvas_height: int = 1080
    ) -> List[MenuButtonSpec]:
        """
        Inhalts-Buttons (z. B. Kapitel) im festen Raster mit cols Spalten, Reihen nach Bedarf;
        Navigations-Buttons als zentrierte Zeile darunter. Das Raster ist immer cols Spalten breit
        und mindestens min_rows Reihen hoch, damit Plätze und Navigationszeile beim Blättern
        zwischen Seiten stehen bleiben (auch bei weniger Buttons auf der letzten Seite).
        Pfeiltasten siehe _link_rows: aus der unteren Raster-Reihe nach unten in die
        Navigationszeile, von dort nach oben zurück ins Raster.
        """
        cols = max(1, cols)
        rows = [grid_buttons[i:i + cols] for i in range(0, len(grid_buttons), cols)]
        grid_cols = cols if grid_buttons else 0
        n_rows = max(len(rows), min_rows if grid_buttons else 0)
        block_h = n_rows * btn_h + max(0, n_rows - 1) * spacing_y
        if nav_buttons:
            block_h += (nav_gap if rows else 0) + btn_h
        y = cls._block_start_y(block_h, canvas_height)

        grid_x = (canvas_width - (grid_cols * btn_w + (grid_cols - 1) * spacing_x)) // 2
        for r, row in enumerate(rows):
            cls._place_row(row, y + r * (btn_h + spacing_y), btn_w, btn_h, spacing_x, start_x=grid_x,
                           canvas_width=canvas_width)
        if nav_buttons:
            nav_y = y + n_rows * (btn_h + spacing_y) - spacing_y + nav_gap if n_rows else y
            cls._place_row(nav_buttons, nav_y, btn_w, btn_h, spacing_x, canvas_width=canvas_width)

        cls._link_rows(rows + [nav_buttons])
        return grid_buttons + nav_buttons

    @classmethod
    def layout_two_columns(
        cls,
        left_buttons: List[MenuButtonSpec],
        right_buttons: List[MenuButtonSpec],
        nav_buttons: List[MenuButtonSpec],
        btn_w: int = 360,
        btn_h: int = 65,
        column_gap: int = 80,
        spacing_x: int = 40,
        spacing_y: int = 25,
        nav_gap: int = 60,
        canvas_width: int = 1920,
        canvas_height: int = 1080
    ) -> List[MenuButtonSpec]:
        """
        Zwei Spalten (z. B. Ton links, Untertitel rechts), Navigations-Buttons als Zeile darunter.
        Pfeiltasten: oben/unten innerhalb der Spalte, aus der letzten Zeile in die Navigationszeile;
        links/rechts in die andere Spalte auf gleicher Höhe (oder deren letzten Button).
        Die Navigationszeile führt nach oben in die nächstgelegene Spalte.
        """
        columns = [c for c in (left_buttons, right_buttons) if c]
        n_rows = max((len(c) for c in columns), default=0)
        block_h = n_rows * btn_h + max(0, n_rows - 1) * spacing_y
        if nav_buttons:
            block_h += (nav_gap if n_rows else 0) + btn_h
        top = cls._block_start_y(block_h, canvas_height)

        total_w = len(columns) * btn_w + max(0, len(columns) - 1) * column_gap
        x = (canvas_width - total_w) // 2
        for column in columns:
            for r, btn in enumerate(column):
                cls._place_row([btn], top + r * (btn_h + spacing_y), btn_w, btn_h, spacing_x, start_x=x)
            x += btn_w + column_gap
        if nav_buttons:
            nav_y = top + (n_rows * (btn_h + spacing_y) - spacing_y + nav_gap if n_rows else 0)
            cls._place_row(nav_buttons, nav_y, btn_w, btn_h, spacing_x, canvas_width=canvas_width)

        for k, column in enumerate(columns):
            other = columns[(k + 1) % len(columns)]
            for r, btn in enumerate(column):
                entry_below = cls._nearest(nav_buttons, btn) if nav_buttons else column[0]
                entry_above = cls._nearest(nav_buttons, btn) if nav_buttons else column[-1]
                if btn.upper_id is None:
                    btn.upper_id = column[r - 1].button_id if r > 0 else entry_above.button_id
                if btn.lower_id is None:
                    btn.lower_id = column[r + 1].button_id if r + 1 < len(column) else entry_below.button_id
                side = other[min(r, len(other) - 1)].button_id
                if btn.left_id is None:
                    btn.left_id = side
                if btn.right_id is None:
                    btn.right_id = side
        for c, btn in enumerate(nav_buttons):
            if btn.left_id is None:
                btn.left_id = nav_buttons[(c - 1) % len(nav_buttons)].button_id
            if btn.right_id is None:
                btn.right_id = nav_buttons[(c + 1) % len(nav_buttons)].button_id
            if columns:
                column = min(columns, key=lambda col: abs(col[0].x + btn_w / 2 - (btn.x + btn.width / 2)))
                if btn.upper_id is None:
                    btn.upper_id = column[-1].button_id
                if btn.lower_id is None:
                    btn.lower_id = column[0].button_id
            else:
                btn.upper_id = btn.button_id if btn.upper_id is None else btn.upper_id
                btn.lower_id = btn.button_id if btn.lower_id is None else btn.lower_id
        return left_buttons + right_buttons + nav_buttons

    @staticmethod
    def link_spatial(buttons: List[MenuButtonSpec]) -> List[MenuButtonSpec]:
        """
        Pfeiltasten aus der tatsächlichen Lage (für frei verschobene Buttons, v1.9.3): In jeder Richtung
        der nächste Button im 45°-Kegel der Pfeilrichtung, dessen Mitte mindestens eine halbe
        Button-Größe weiter liegt; seitlicher Versatz zählt doppelt. Liegt im Kegel nichts, geht es schräg
        in Pfeilrichtung weiter (z. B. aus der unteren Reihe eines breiten Rasters in die schmalere
        Navigationszeile darunter, v1.12); gibt es auch dort nichts, zur gegenüberliegenden Seite
        (Wrap-Around), dort zum am besten ausgerichteten Button. Ohne Ziel: der Button selbst.
        Überschreibt vorhandene Verknüpfungen.
        """
        def center(b):
            return b.x + b.width / 2, b.y + b.height / 2

        directions = (("upper_id", 1, -1), ("lower_id", 1, 1), ("left_id", 0, -1), ("right_id", 0, 1))
        for btn in buttons:
            here = center(btn)
            others = [o for o in buttons if o is not btn]
            for attr, axis, sign in directions:
                size = btn.height if axis == 1 else btn.width

                def primary(o):
                    return (center(o)[axis] - here[axis]) * sign

                def lateral(o):
                    return abs(center(o)[1 - axis] - here[1 - axis])

                ahead = [o for o in others if primary(o) > size / 2]
                in_cone = [o for o in ahead if lateral(o) <= primary(o)]
                behind = [o for o in others if primary(o) < -size / 2]
                if in_cone:
                    target = min(in_cone, key=lambda o: (primary(o) + 2 * lateral(o), o.button_id))
                elif ahead:
                    target = min(ahead, key=lambda o: (primary(o) + 2 * lateral(o), o.button_id))
                elif behind:
                    far = min(primary(o) for o in behind)
                    target = min(behind, key=lambda o: (2 * lateral(o) + primary(o) - far, o.button_id))
                else:
                    target = btn
                setattr(btn, attr, target.button_id)
        return buttons

    @classmethod
    def auto_layout(
        cls,
        buttons: List[MenuButtonSpec],
        max_column_items: int = 4
    ) -> List[MenuButtonSpec]:
        """Wählt automatisch 1-Spalten- oder 2-Spalten-Layout je nach Buttonanzahl."""
        if len(buttons) <= max_column_items:
            return cls.layout_column(buttons)
        else:
            return cls.layout_grid(buttons, cols=2)


# =========================================================================
# Vordefinierte Standard-Vorlagen (Templates)
# =========================================================================

def build_main_menu_specs(
    has_extras: bool = False,
    has_chapters: bool = False,
    has_audio: bool = False,
    play_text: str = "FILM STARTEN",
    extras_text: str = "EXTRAS",
    chapters_text: str = "KAPITEL",
    audio_text: str = "TON & UNTERTITEL",
    main_title_id: int = 1,
    extra_title_id: int = 2,
    chapter_page_id: int = 1,
    audio_page_id: int = 2,
    additional_titles: Optional[List[Tuple[int, str]]] = None,
    titles: Optional[List[object]] = None
) -> List[MenuButtonSpec]:
    """
    Erzeugt Button-Spezifikationen für das Hauptmenü.
    Unterstützt sowohl klassische 1-2 Titel Discs als auch dynamische Multi-Title Discs
    (z. B. Episoden 1..N oder Film + mehrere Bonus-Features).
    """
    buttons: List[MenuButtonSpec] = []
    btn_id = 1

    # Button 1: Titel 1 / Film starten
    buttons.append(MenuButtonSpec(
        button_id=btn_id,
        text=play_text,
        action_type="jump_title",
        target_title_id=main_title_id
    ))
    btn_id += 1

    has_multi = False
    if additional_titles is not None:
        has_multi = True
        for t_id, t_text in additional_titles:
            buttons.append(MenuButtonSpec(
                button_id=btn_id,
                text=t_text,
                action_type="jump_title",
                target_title_id=t_id
            ))
            btn_id += 1
    elif titles is not None and len(titles) > 1:
        has_multi = True
        for idx, t in enumerate(titles[1:], start=2):
            t_txt = getattr(t, "menu_btn_text", None) or getattr(t, "name", f"TITEL {idx}").upper()
            buttons.append(MenuButtonSpec(
                button_id=btn_id,
                text=t_txt,
                action_type="jump_title",
                target_title_id=idx
            ))
            btn_id += 1

    # Kapitelmenü (falls vorhanden)
    if has_chapters:
        buttons.append(MenuButtonSpec(
            button_id=btn_id,
            text=chapters_text,
            action_type="set_page",
            target_page_id=chapter_page_id
        ))
        btn_id += 1

    # Ton / Sprachmenü (falls vorhanden)
    if has_audio:
        buttons.append(MenuButtonSpec(
            button_id=btn_id,
            text=audio_text,
            action_type="set_page",
            target_page_id=audio_page_id
        ))
        btn_id += 1

    # Bonusmaterial / Extras (Legacy-Fallback nur falls keine Multi-Titles angegeben wurden)
    if not has_multi and has_extras:
        buttons.append(MenuButtonSpec(
            button_id=btn_id,
            text=extras_text,
            action_type="jump_title",
            target_title_id=extra_title_id
        ))
        btn_id += 1

    return MenuLayoutEngine.auto_layout(buttons)


def build_chapter_menu_specs(
    chapters: List[Dict[str, str]],
    main_playlist_id: int = 1,
    return_title_id: int = 0,
    return_page_id: Optional[int] = None,
    back_text: str = "ZURÜCK",
    chapter_prefix: str = "KAPITEL"
) -> List[MenuButtonSpec]:
    """
    Erzeugt Button-Spezifikationen für ein Kapitelauswahl-Menü.
    chapters: Liste von Dicts mit z. B. {"name": "Kapitel 1", "time": "00:00:00"}
              oder Strings von Zeitstempeln.
    return_page_id: Wenn gesetzt, führt der Zurück-Button einen Seitenwechsel
                    (SetButtonPage) aus, ansonsten einen Title-Sprung (JumpTitle).
    """
    buttons: List[MenuButtonSpec] = []
    btn_id = 1

    for i, ch in enumerate(chapters, start=1):
        ch_time = None
        if isinstance(ch, dict):
            name = ch.get("name", f"{chapter_prefix} {i}")
            ch_time = ch.get("time")
        elif isinstance(ch, str):
            name = f"{chapter_prefix} {i}"
            ch_time = ch
        else:
            name = f"{chapter_prefix} {i}"

        buttons.append(MenuButtonSpec(
            button_id=btn_id,
            text=name,
            action_type="play_chapter",
            target_title_id=main_playlist_id,
            target_chapter_id=i,
            chapter_time=ch_time
        ))
        btn_id += 1

    # Zurück-Button
    if return_page_id is not None:
        buttons.append(MenuButtonSpec(
            button_id=btn_id,
            text=back_text,
            action_type="set_page",
            target_page_id=return_page_id
        ))
    else:
        buttons.append(MenuButtonSpec(
            button_id=btn_id,
            text=back_text,
            action_type="jump_title",
            target_title_id=return_title_id
        ))

    # Grid-Layout für Kapitel
    cols = 2 if len(buttons) > 4 else 1
    if cols == 1:
        return MenuLayoutEngine.layout_column(buttons, btn_w=340, btn_h=60, spacing=20)
    else:
        return MenuLayoutEngine.layout_grid(buttons, cols=2, btn_w=340, btn_h=60, spacing_x=30, spacing_y=20)


def build_audio_menu_specs(
    audio_tracks: List[Dict[str, str]],
    subtitle_tracks: List[Dict[str, str]],
    return_title_id: int = 0,
    return_page_id: Optional[int] = None,
    back_text: str = "ZURÜCK",
    sub_off_text: str = "UNTERTITEL AUS"
) -> List[MenuButtonSpec]:
    """
    Erzeugt Button-Spezifikationen für ein Ton- & Untertitel-Auswahlmenü
    mit sauberen Sprachnamen (Deutsch, English etc.) aus ISO 639-2 Codes.
    """
    from core.constants import language_menu_name

    buttons: List[MenuButtonSpec] = []
    btn_id = 1

    # Audio Spuren
    for i, trk in enumerate(audio_tracks, start=1):
        buttons.append(MenuButtonSpec(
            button_id=btn_id,
            text=f"TON: {language_menu_name(trk.get('lang', 'und'))}",
            action_type="set_stream",
            target_audio_id=i
        ))
        btn_id += 1

    # Untertitel Spuren
    for j, sub in enumerate(subtitle_tracks, start=1):
        buttons.append(MenuButtonSpec(
            button_id=btn_id,
            text=f"UNTERTITEL: {language_menu_name(sub.get('lang', 'und'))}",
            action_type="set_stream",
            target_subtitle_id=j,
            target_subtitle_on=True
        ))
        btn_id += 1

    # Option "Untertitel aus"
    if subtitle_tracks:
        buttons.append(MenuButtonSpec(
            button_id=btn_id,
            text=sub_off_text,
            action_type="set_stream",
            target_subtitle_on=False
        ))
        btn_id += 1

    # Zurück-Button
    if return_page_id is not None:
        buttons.append(MenuButtonSpec(
            button_id=btn_id,
            text=back_text,
            action_type="set_page",
            target_page_id=return_page_id
        ))
    else:
        buttons.append(MenuButtonSpec(
            button_id=btn_id,
            text=back_text,
            action_type="jump_title",
            target_title_id=return_title_id
        ))

    cols = 2 if len(buttons) > 4 else 1
    if cols == 1:
        return MenuLayoutEngine.layout_column(buttons, btn_w=350, btn_h=60, spacing=20)
    else:
        return MenuLayoutEngine.layout_grid(buttons, cols=2, btn_w=350, btn_h=60, spacing_x=30, spacing_y=20)
