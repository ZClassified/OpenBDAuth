# modules/bdsim/player.py
"""
Simulierter Blu-ray-Player: verbindet die HDMV-Maschine mit Playlist-Wiedergabe und dem
Grafik-Controller des Menüs (Seiten, Button-Auswahl, Pfeiltasten, Aktivieren).

Verhalten nach BD-ROM Part 3 und libbluray (graphics_controller.c):
- Beim Start eines Menüs wird Seite 0 gezeigt.
- Ausgewählter Button: Standard-Button der Seite, sonst PSR 10, sonst erster gültiger Button.
- SetButtonPage aus einem Button beendet dessen Befehlsliste.

Top-Menu-Taste wie auf dem Sony UBP-X700 beobachtet (Disc A, v1.8.3): Hat das laufende MovieObject
resume_intention, merkt sich der Player die Wiedergabe als unterbrochen. Eine bereits gemerkte
Unterbrechung bleibt dabei bestehen (libbluray würde sie ersetzen). Top Menu im Menü setzt eine
gemerkte Unterbrechung fort. Nur JumpTitle verwirft sie, JumpObject nicht.
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set, Tuple

from modules.bdsim.disc import Disc, Composition, Page, Button, NO_BUTTON
from modules.bdsim.hdmv import (
    Machine, Event, PSR_TITLE, PSR_PLAYLIST, PSR_CHAPTER, PSR_SELECTED_BUTTON, PSR_MENU_PAGE,
    PSR_3D_STATUS, PSR_PRIMARY_AUDIO, PSR_PG_STREAM,
)
from core.translations import tr

# Zustände
STATE_IDLE = "idle"
STATE_MENU = "menu"          # Playlist mit IG-Menü läuft, wartet auf Eingabe
STATE_FILM = "film"          # Playlist ohne Menü läuft
STATE_STOPPED = "stopped"    # Wiedergabe beendet, keine Navigation mehr

KEYS_ARROW = {"up": "upper", "down": "lower", "left": "left", "right": "right"}


@dataclass
class Finding:
    level: str               # "fehler", "warnung", "hinweis"
    code: str
    text: str
    path: List[str] = field(default_factory=list)


@dataclass
class PlaybackRecord:
    """Protokoll eines Playlist-Starts für die Auswertung."""
    playlist_id: int
    title: int
    start_mark: Optional[int]
    output_3d: bool
    audio: int
    pg_stream: int
    pg_on: bool
    wants_2d: bool = False     # das Titel-Objekt hat vor dem Start ausdrücklich 2D gewählt


class Player:
    def __init__(self, disc: Disc, tv_3d: bool = True, player_3d: bool = True):
        self.disc = disc
        self.tv_3d = tv_3d
        self.findings: List[Finding] = []
        self.machine = Machine(disc.movie_objects, len(disc.index.titles), self._report, player_3d=player_3d)
        self.state = STATE_IDLE
        self.playlist_id: Optional[int] = None
        self.start_mark: Optional[int] = None
        self.composition: Optional[Composition] = None
        self.page_id = 0
        self.enabled: Dict[int, int] = {}          # BOG-Index -> gültiger Button der aktuellen Seite
        self.playback_log: List[PlaybackRecord] = []
        self.on_menu_loop_reset: Optional[Callable[[int], None]] = None
        self.suspended_playback: Optional[Tuple[int, Optional[int]]] = None   # (Playlist, Startmarke)

    # ─────────────── Zustand ───────────────
    def copy(self) -> "Player":
        p = Player.__new__(Player)
        p.__dict__.update(self.__dict__)
        p.machine = self.machine.copy()
        p.machine.report = p._report
        p.findings = []
        p.enabled = dict(self.enabled)
        p.playback_log = []
        return p

    def snapshot(self) -> Tuple:
        """Zustand ohne ausgewählten Button und ohne Hilfsregister (für den automatischen Durchlauf)."""
        return (self.state, self.playlist_id, self.start_mark, self.page_id,
                tuple(sorted(self.enabled.items())), self.suspended_playback,
                self.machine.snapshot(self.disc.scratch_registers))

    @property
    def regs(self):
        return self.machine.regs

    @property
    def title(self) -> int:
        return self.regs.psr[PSR_TITLE]

    @property
    def selected_button(self) -> int:
        return self.regs.psr[PSR_SELECTED_BUTTON]

    @property
    def output_3d(self) -> bool:
        return bool(self.regs.psr[PSR_3D_STATUS] & 1) and self.tv_3d

    def current_page(self) -> Optional[Page]:
        return self.composition.page(self.page_id) if self.composition else None

    def valid_buttons(self) -> List[Button]:
        """Die aktuell gültigen Buttons der Seite (je BOG einer)."""
        page = self.current_page()
        if not page:
            return []
        result = []
        for idx, group in enumerate(page.groups):
            bid = self.enabled.get(idx, NO_BUTTON)
            for b in group.buttons:
                if b.button_id == bid:
                    result.append(b)
        return result

    def _report(self, level: str, code: str, text: str):
        self.findings.append(Finding(level, code, text))

    # ─────────────── Bedienung ───────────────
    def insert_disc(self):
        entry = self.disc.index.first_play
        if not entry.is_hdmv:
            self._report("fehler", "first_play_fehlt", tr("sim_first_playback_no_mobj"))
            self.state = STATE_STOPPED
            return
        self.machine.start_object(entry.mobj_id)
        self._run()

    def press(self, key: str):
        """Taste der Fernbedienung: up, down, left, right, ok, top_menu, audio, subtitle."""
        if key == "top_menu":
            self._top_menu()
        elif key in ("audio", "subtitle"):
            self._cycle_stream(key)
        elif self.state == STATE_MENU:
            if key in KEYS_ARROW:
                self._move(KEYS_ARROW[key])
            elif key == "ok":
                self._activate(self.selected_button)

    def playlist_end(self):
        """Die laufende Playlist ist zu Ende (Film vorbei oder Menü-Schleife abgelaufen)."""
        if self.state not in (STATE_MENU, STATE_FILM):
            return
        leaving_page = self.page_id if self.state == STATE_MENU else 0
        self._stop_playback()
        self.machine.playlist_ended()
        self._run()
        # Nach dem Neustart eine andere Seite als vorher (ohne Startseite: wieder Seite 0, offener Punkt 11.2.4)
        if leaving_page and self.state == STATE_MENU and self.page_id != leaving_page and self.on_menu_loop_reset:
            self.on_menu_loop_reset(leaving_page)

    def _cycle_stream(self, key: str):
        """Ton-/Untertitel-Taste während eines Films: nächste Spur (Untertitel: aus → 1 → … → n → aus)."""
        pl = self.disc.playlists.get(self.playlist_id) if self.state == STATE_FILM else None
        if pl is None:
            return
        psr = self.regs.psr
        if key == "audio" and pl.count("audio"):
            psr[PSR_PRIMARY_AUDIO] = psr[PSR_PRIMARY_AUDIO] % pl.count("audio") + 1
        elif key == "subtitle" and pl.count("pg"):
            number, shown = psr[PSR_PG_STREAM] & 0xFFF, bool(psr[PSR_PG_STREAM] & 0x80000000)
            if not shown or number > pl.count("pg"):
                psr[PSR_PG_STREAM] = 0x80000001
            elif number < pl.count("pg"):
                psr[PSR_PG_STREAM] = 0x80000000 | (number + 1)
            else:
                psr[PSR_PG_STREAM] = number   # aus, Spurnummer bleibt
        self.machine.log.append(tr("sim_remote_audio_key" if key == "audio" else "sim_remote_subtitle_key"))

    def select_button(self, button_id: int):
        """Auswahl ohne Aktivieren (z. B. Maus über einem Button)."""
        if self.state == STATE_MENU:
            self._select(button_id)

    def skip_chapter(self, step: int):
        """Kapitel-Taste der Fernbedienung (+1 / -1) während eines Films. Die Wiedergabezeit wird nicht simuliert:
        als aktuelles Kapitel gilt die zuletzt angesprungene Marke."""
        if self.state != STATE_FILM or self.playlist_id not in self.disc.playlists:
            return
        entries = self.disc.playlists[self.playlist_id].chapter_marks
        if not entries:
            return
        current = self.start_mark if self.start_mark in entries else entries[0]
        pos = entries.index(current) + step
        if 0 <= pos < len(entries):
            self.start_mark = entries[pos]
            self.regs.psr[PSR_CHAPTER] = pos + 1

    def chapter_position(self) -> Tuple[int, int]:
        """(aktuelles Kapitel 1-basiert, Anzahl Kapitel) der laufenden Film-Playlist, sonst (0, 0)."""
        pl = self.disc.playlists.get(self.playlist_id) if self.state == STATE_FILM else None
        if pl is None or not pl.chapter_marks:
            return 0, 0
        entries = pl.chapter_marks
        current = self.start_mark if self.start_mark in entries else entries[0]
        return entries.index(current) + 1, len(entries)

    def activate_button(self, button_id: int):
        """Wählt einen Button direkt aus und drückt OK (für den automatischen Durchlauf)."""
        if self.state != STATE_MENU:
            return
        self._select(button_id)
        self._activate(button_id)

    # ─────────────── Wiedergabe ───────────────
    def _run(self):
        events = self.machine.run()
        while events:
            follow_up: List[Event] = []
            for ev in events:
                more = self._handle(ev)
                if more:
                    follow_up.extend(more)
            events = follow_up

    def _handle(self, ev: Event) -> Optional[List[Event]]:
        if ev.kind == "play":
            return self._start_playlist(ev.a, ev.b, ev.c)
        if ev.kind == "title":
            self._stop_playback()
            self.regs.psr[PSR_TITLE] = ev.a
            obj = self.disc.title_object(ev.a)
            if obj is None:
                self._report("fehler", "titel_ohne_objekt", tr("sim_title_no_mobj", n=ev.a))
                self.state = STATE_STOPPED
                return None
            self.machine.start_object(obj)
            return self.machine.run()
        if ev.kind == "object_changed":
            self._stop_playback()
            return None
        if ev.kind == "end":
            self._stop_playback()
            self.state = STATE_STOPPED
            return None
        if ev.kind == "stop_play":
            self._stop_playback()
            return None
        if ev.kind == "button_page":
            return self._set_button_page(ev.a, ev.b)
        if ev.kind in ("enable_button", "disable_button"):
            self._enable_button(ev.a, ev.kind == "enable_button")
            return None
        if ev.kind == "link":
            if ev.a == 5 and self.playlist_id in self.disc.playlists:
                marks = self.disc.playlists[self.playlist_id].marks
                if ev.b >= len(marks):
                    self._report("fehler", "marke_fehlt",
                                 f"LinkMK({ev.b}): Playlist {self.playlist_id:05d} hat nur {len(marks)} Marken")
            return None
        return None

    def _start_playlist(self, playlist_id: int, play_op: int, position: int) -> Optional[List[Event]]:
        pl = self.disc.playlists.get(playlist_id)
        if pl is None:
            self._report("fehler", "playlist_fehlt", tr("sim_playlist_missing", pl=f"{playlist_id:05d}"))
            self.machine.playlist_ended()
            return self.machine.run()

        start_mark = None
        if play_op == 2:
            if position >= len(pl.marks):
                self._report("fehler", "marke_fehlt",
                             tr("sim_mark_missing", mark=position, pl=f"{playlist_id:05d}", n=len(pl.marks)))
            start_mark = position
            self.regs.psr[PSR_CHAPTER] = position + 1
        elif play_op == 1 and position >= len(pl.items):
            self._report("fehler", "playitem_fehlt",
                         f"Start bei PlayItem {position}, Playlist {playlist_id:05d} hat nur {len(pl.items)}")

        comp = self.disc.compositions.get(playlist_id)
        if self.machine.suspended is not None and self.machine.object_id is not None and comp is None:
            self._report("warnung", "unterbrechung_bleibt",
                         tr("sim_jumpobject_resume"))

        self.playlist_id = playlist_id
        self.start_mark = start_mark
        self.regs.psr[PSR_PLAYLIST] = playlist_id
        pg = self.regs.psr[PSR_PG_STREAM]
        self.playback_log.append(PlaybackRecord(
            playlist_id, self.title, start_mark, self.output_3d,
            self.regs.psr[PSR_PRIMARY_AUDIO], pg & 0xFFF, bool(pg & 0x80000000), self.machine.wants_2d))

        if comp is not None and comp.ui_model == 0:
            self.state = STATE_MENU
            self.composition = comp
            return self._select_page(0)
        else:
            self.state = STATE_FILM
            self.composition = None
        return None

    def _stop_playback(self):
        if self.state in (STATE_MENU, STATE_FILM):
            self.state = STATE_IDLE
        self.playlist_id = None
        self.start_mark = None
        self.composition = None

    def _top_menu(self):
        entry = self.disc.index.top_menu
        if not entry.is_hdmv:
            self._report("warnung", "kein_top_menu", tr("sim_no_top_menu"))
            return
        current = self.machine.object_id
        obj = self.disc.movie_objects[current] if current is not None and 0 <= current < len(self.disc.movie_objects) else None
        if obj is not None and obj.menu_call_mask:
            return
        if self.state == STATE_MENU and self.machine.suspended is not None:
            self._resume()
            return
        if self.state == STATE_FILM and obj is not None and obj.resume_intention and self.machine.suspended is None:
            self.machine.suspended = (current, self.machine.pc, list(self.regs.psr[:32]))
            self.suspended_playback = (self.playlist_id, self.start_mark)
        self._stop_playback()
        self.machine.start_object(entry.mobj_id)
        self._run()

    def _resume(self):
        """Setzt die gemerkte Unterbrechung fort (Wiedergabe an derselben Stelle)."""
        obj_id, pc, psr = self.machine.suspended
        self.machine.suspended = None
        playlist_id, start_mark = self.suspended_playback or (None, None)
        self.suspended_playback = None
        self._stop_playback()
        self.regs.psr[:len(psr)] = psr
        self.machine.object_id, self.machine.pc = obj_id, pc
        self.machine.ig_commands = None
        self.machine.waiting_for_play = True
        self.machine.log.append(f"Fortsetzen: MObj {obj_id}/{pc}")
        if playlist_id is not None:
            self.playlist_id, self.start_mark = playlist_id, start_mark
            self.state = STATE_FILM

    # ─────────────── Grafik-Controller ───────────────
    def _select_page(self, page_id: int, button_id: Optional[int] = None) -> Optional[List[Event]]:
        """Seite zeigen und einen Button auswählen. Hat der ausgewählte Button auto_action, löst er sofort aus
        (Startseite einer Menügruppe, v1.13); dann kommen die Ereignisse seiner Befehle zurück."""
        page = self.composition.page(page_id) if self.composition else None
        if page is None:
            self._report("fehler", "seite_fehlt", tr("sim_page_missing", page=page_id))
            return None
        self.page_id = page_id
        self.regs.psr[PSR_MENU_PAGE] = page_id
        self.enabled = {idx: g.default_valid_button for idx, g in enumerate(page.groups)}
        valid_ids = {b.button_id for b in self.valid_buttons()}

        if button_id is not None:
            if button_id in valid_ids:
                self.regs.psr[PSR_SELECTED_BUTTON] = button_id
                return self._auto_action()
            self._report("fehler", "button_fehlt", tr("sim_setbuttonpage_invalid", id=button_id, page=page_id))

        # Reihenfolge wie libbluray _find_selected_button_id: Standard-Button, PSR 10, erster gültiger Button
        chosen = NO_BUTTON
        if page.default_selected_button in valid_ids:
            chosen = page.default_selected_button
        elif self.selected_button in valid_ids:
            chosen = self.selected_button
        else:
            for b in page.buttons():
                if b.button_id in valid_ids:
                    chosen = b.button_id
                    break
        self.regs.psr[PSR_SELECTED_BUTTON] = chosen
        return self._auto_action()

    def _auto_action(self) -> Optional[List[Event]]:
        """Ausgewählter Button mit auto_action: seine Befehle laufen sofort (wie beim Weiterschalten auf ihn)."""
        button = next((b for b in self.valid_buttons() if b.button_id == self.selected_button), None)
        if button is None or not button.auto_action or not button.commands:
            return None
        self.machine.start_button(button.commands)
        return self.machine.run()

    def _set_button_page(self, dst: int, src: int) -> Optional[List[Event]]:
        button_flag = bool(dst & 0x80000000)
        button_id = dst & 0xFFFF
        if src & 0x80000000:
            return self._select_page(src & 0xFF, button_id=button_id if button_flag else None)
        elif button_flag:
            self._select(button_id)
        return None

    def _select(self, button_id: int):
        if button_id in {b.button_id for b in self.valid_buttons()}:
            self.regs.psr[PSR_SELECTED_BUTTON] = button_id

    def _enable_button(self, button_id: int, enable: bool):
        page = self.current_page()
        if not page:
            return
        for idx, g in enumerate(page.groups):
            if any(b.button_id == button_id for b in g.buttons):
                if enable:
                    self.enabled[idx] = button_id
                elif self.enabled.get(idx) == button_id:
                    self.enabled[idx] = NO_BUTTON
                return
        self._report("fehler", "button_fehlt", tr("sim_enable_button_missing", id=button_id, page=self.page_id))

    def _move(self, direction: str):
        current = next((b for b in self.valid_buttons() if b.button_id == self.selected_button), None)
        if current is None:
            return
        target = getattr(current, direction)
        if target == current.button_id:
            return
        target_btn = next((b for b in self.valid_buttons() if b.button_id == target), None)
        if target_btn is None:
            return
        self.regs.psr[PSR_SELECTED_BUTTON] = target
        if target_btn.auto_action:
            self._activate(target)

    def _activate(self, button_id: int):
        button = next((b for b in self.valid_buttons() if b.button_id == button_id), None)
        if button is None:
            return
        if not button.commands:
            return
        self.machine.start_button(button.commands)
        self._run()
