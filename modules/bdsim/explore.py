# modules/bdsim/explore.py
"""
Automatischer Durchlauf durch eine Disc: ab „Disc einlegen“ wird jeder Button auf jeder
erreichten Menüseite gedrückt, jede Playlist läuft zu Ende und die Top-Menu-Taste wird probiert.
Das Ergebnis ist ein Bericht mit Fehlern, Warnungen und Hinweisen samt dem Weg dorthin.
"""

from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from core.translations import tr
from modules.bdsim.disc import Disc, Composition, Page, NO_BUTTON
from modules.bdsim.hdmv import GRP_SET, SET_SETSYSTEM, PSR_PRIMARY_AUDIO, PSR_PG_STREAM
from modules.bdsim.player import (
    Player, Finding, STATE_MENU, STATE_FILM, STATE_STOPPED, STATE_IDLE,
)

LEVELS = ("fehler", "warnung", "hinweis")
LEVEL_ICON = {"fehler": "⛔", "warnung": "⚠", "hinweis": "ℹ"}


@dataclass
class Report:
    tv_3d: bool
    findings: List[Finding] = field(default_factory=list)
    titles_reached: Set[int] = field(default_factory=set)
    playlists_reached: Set[int] = field(default_factory=set)
    pages_reached: Set[Tuple[int, int]] = field(default_factory=set)   # (Playlist, Seite)
    title_paths: Dict[int, List[str]] = field(default_factory=dict)
    states: int = 0
    truncated: bool = False

    def count(self, level: str) -> int:
        return sum(1 for f in self.findings if f.level == level)

    @property
    def ok(self) -> bool:
        return self.count("fehler") == 0 and self.count("warnung") == 0


class _Collector:
    def __init__(self, report: Report):
        self.report = report
        self._seen: Set[Tuple[str, str]] = set()

    def add(self, finding: Finding, path: List[str]):
        key = (finding.code, finding.text)
        if key in self._seen:
            return
        self._seen.add(key)
        finding.path = list(path)
        self.report.findings.append(finding)

    def new(self, level: str, code: str, text: str, path: List[str]):
        self.add(Finding(level, code, text), path)


def explore(disc: Disc, tv_3d: bool = True, max_states: int = 50000) -> Report:
    report = Report(tv_3d=tv_3d)
    out = _Collector(report)

    for problem in disc.read_problems:
        out.new("fehler", "lesefehler", problem, [])
    for pl_id, comp in sorted(disc.compositions.items()):
        _check_composition(disc, pl_id, comp, out)
    _check_movie_objects(disc, out)

    start = Player(disc, tv_3d=tv_3d)
    start.insert_disc()
    first_path = [tr("sim_insert_disc")]
    _collect(start, first_path, out, report)

    queue = deque([(start, first_path)])
    visited = {start.snapshot()}
    # (Playlist, Seite, Button) -> [hat irgendwo etwas bewirkt, Weg der ersten Betätigung, Text]
    button_effects: Dict[Tuple[int, int, int], list] = {}

    while queue:
        if len(visited) >= max_states:
            report.truncated = True
            break
        player, path = queue.popleft()

        if player.state == STATE_MENU:
            here = tr("sim_menu_page", pl=f"{player.playlist_id:05d}", page=player.page_id)
            report.pages_reached.add((player.playlist_id, player.page_id))
            before = player.snapshot()
            for button in player.valid_buttons():
                child = player.copy()
                child.activate_button(button.button_id)
                label = tr("sim_button_press", here=here, id=button.button_id, cmds=_commands_text(button.commands))
                child_path = path + [label]
                _check_stream_choice(player, child, button, child_path, out)
                _collect(child, child_path, out, report)
                effect = button_effects.setdefault(
                    (player.playlist_id, player.page_id, button.button_id),
                    [False, child_path, tr("sim_button_no_effect", here=here, id=button.button_id,
                                           cmds=_commands_text(button.commands) or tr("sim_none"))])
                effect[0] |= child.snapshot() != before
                _enqueue(child, child_path, visited, queue)

            if player.machine.suspended is not None:
                child = player.copy()
                child.press("top_menu")
                child_path = path + [tr("sim_top_menu_key", here=here)]
                _collect(child, child_path, out, report)
                _enqueue(child, child_path, visited, queue)

            child = player.copy()
            resets: List[int] = []
            child.on_menu_loop_reset = resets.append
            child.playlist_end()
            child_path = path + [tr("sim_menu_loop_ends", here=here)]
            if resets:
                out.new("hinweis", "menue_schleife_seite",
                        tr("sim_menu_loop_page", pl=f"{player.playlist_id:05d}", page=resets[0]),
                        child_path)
            _collect(child, child_path, out, report)
            _enqueue(child, child_path, visited, queue)

        elif player.state == STATE_FILM:
            here = tr("sim_playlist_title", pl=f"{player.playlist_id:05d}", title=player.title)
            child = player.copy()
            child.playlist_end()
            child_path = path + [tr("sim_plays_to_end", here=here)]
            _collect(child, child_path, out, report)
            _enqueue(child, child_path, visited, queue)

            child = player.copy()
            child.press("top_menu")
            child_path = path + [tr("sim_top_menu_key", here=here)]
            _collect(child, child_path, out, report)
            _enqueue(child, child_path, visited, queue)

        elif player.state in (STATE_STOPPED, STATE_IDLE):
            last_object = player.machine.log[-1] if player.machine.log else "–"
            out.new("warnung", "wiedergabe_endet",
                    tr("sim_dead_end", last=last_object), path)

    report.states = len(visited)
    for changed, first_path, text in button_effects.values():
        if not changed:
            out.new("warnung", "button_ohne_wirkung", text, first_path)
    _check_reachability(disc, report, out)
    report.findings.sort(key=lambda f: LEVELS.index(f.level))
    return report


def _enqueue(player: Player, path: List[str], visited: set, queue: deque):
    snap = player.snapshot()
    if snap not in visited:
        visited.add(snap)
        queue.append((player, path))


def _collect(player: Player, path: List[str], out: _Collector, report: Report):
    """Übernimmt die Befunde und Wiedergaben eines Schritts."""
    for f in player.findings:
        out.add(f, path)
    player.findings = []
    for rec in player.playback_log:
        report.playlists_reached.add(rec.playlist_id)
        pl = player.disc.playlists.get(rec.playlist_id)
        if rec.playlist_id not in player.disc.compositions and 1 <= rec.title <= len(player.disc.index.titles):
            report.titles_reached.add(rec.title)
            report.title_paths.setdefault(rec.title, list(path))
        if pl is None:
            continue
        where = f"Playlist {rec.playlist_id:05d}"
        if rec.start_mark is not None:
            where += tr("sim_from_mark", mark=rec.start_mark)
        if pl.is_3d and report.tv_3d and not rec.output_3d and rec.wants_2d:
            out.new("hinweis", "3d_film_in_2d",
                    tr("sim_3d_in_2d", where=where), path)
        elif pl.is_3d and report.tv_3d and not rec.output_3d:
            out.new("warnung", "3d_ohne_umschaltung",
                    tr("sim_3d_no_switch", where=where), path)
        if rec.playlist_id not in player.disc.compositions:
            # Filme ganz ohne Ton- oder Untertitelspuren ignorieren die Wahl; nur echte Lücken melden
            audio_count = pl.count("audio")
            if audio_count and rec.audio > audio_count:
                out.new("warnung", "tonspur_fehlt",
                        tr("sim_audio_missing", where=where, n=rec.audio, count=audio_count), path)
            pg_count = pl.count("pg")
            if pg_count and rec.pg_on and rec.pg_stream != 0xFFF and rec.pg_stream > pg_count:
                out.new("warnung", "untertitel_fehlt",
                        tr("sim_subs_missing", where=where, n=rec.pg_stream, count=pg_count), path)
    player.playback_log = []


def _check_stream_choice(before: Player, after: Player, button, path: List[str], out: _Collector):
    """Spurwahl im Menü, für die die Menü-Playlist keine passende Spur hat: Der Sony UBP-X700 verwirft sie
    (Disc A, v1.8.3). Die Wahl gehört in ein Register und wird beim Filmstart umgesetzt."""
    menu_pl = before.disc.playlists.get(before.playlist_id)
    if menu_pl is None or after.state != STATE_MENU or after.playlist_id != before.playlist_id:
        return   # Button hat einen Film gestartet: dort umgesetzte Spurwahl ist korrekt
    advice = tr("sim_choice_advice")
    new_audio = after.regs.psr[PSR_PRIMARY_AUDIO]
    if new_audio != before.regs.psr[PSR_PRIMARY_AUDIO] and new_audio > menu_pl.count("audio"):
        out.new("warnung", "spurwahl_im_menue",
                tr("sim_menu_audio_choice", pl=f"{before.playlist_id:05d}", id=button.button_id, n=new_audio,
                   count=menu_pl.count("audio")) + advice, path)
    old_pg, new_pg = before.regs.psr[PSR_PG_STREAM], after.regs.psr[PSR_PG_STREAM]
    # Nur Buttons, die ausdrücklich Untertitel wählen (Ton-Buttons ändern die Anzeige nur als Nebenwirkung)
    selects_pg = any(c.grp == GRP_SET and c.sub_grp == SET_SETSYSTEM and c.set_opt == 1 and c.dst & 0x8000
                     for c in button.commands)
    if selects_pg and new_pg != old_pg and ((new_pg & 0xFFF) > menu_pl.count("pg") or not menu_pl.count("pg")):
        out.new("warnung", "spurwahl_im_menue",
                tr("sim_menu_subs_choice", pl=f"{before.playlist_id:05d}", id=button.button_id,
                   count=menu_pl.count("pg")) + advice, path)


def _commands_text(commands) -> str:
    return "; ".join(c.text() for c in commands)


def _check_composition(disc: Disc, pl_id: int, comp: Composition, out: _Collector):
    """Prüfungen ohne Durchlauf: Pfeiltasten, Grafiken, Seiten-IDs, Ton-Buttons."""
    where = tr("sim_menu", pl=f"{pl_id:05d}")
    page_ids = [p.page_id for p in comp.pages]
    if len(set(page_ids)) != len(page_ids):
        out.new("fehler", "seite_doppelt", tr("sim_page_ids_twice", where=where, ids=page_ids), [])
    if comp.display_sets > 1:
        out.new("hinweis", "mehrere_display_sets",
                tr("sim_display_sets", where=where, n=comp.display_sets), [])
    films_have_pg = any(pl.count("pg") for pid, pl in disc.playlists.items() if pid not in disc.compositions)

    for page in comp.pages:
        here = tr("sim_where_page", where=where, page=page.page_id)
        buttons = {b.button_id: b for b in page.buttons()}
        ids = [b.button_id for b in page.buttons()]
        if len(set(ids)) != len(ids):
            out.new("fehler", "button_doppelt", tr("sim_button_ids_twice", here=here, ids=ids), [])
        if page.default_selected_button != NO_BUTTON and page.default_selected_button not in buttons:
            out.new("fehler", "standard_button_fehlt",
                    tr("sim_default_button_missing", here=here, id=page.default_selected_button), [])

        for b in page.buttons():
            for state_name, (start, end) in ((tr("sim_state_normal"), b.normal), (tr("sim_state_selected"), b.selected),
                                             (tr("sim_state_activated"), b.activated)):
                for obj in {start, end}:
                    if obj != NO_BUTTON and obj not in comp.objects:
                        out.new("fehler", "grafik_fehlt",
                                tr("sim_graphic_missing", here=here, id=b.button_id, state=state_name, obj=obj), [])
            for direction, target in ((tr("sim_dir_up"), b.upper), (tr("sim_dir_down"), b.lower),
                                      (tr("sim_dir_left"), b.left), (tr("sim_dir_right"), b.right)):
                if target not in buttons:
                    out.new("warnung", "nachbar_fehlt",
                            tr("sim_neighbour_missing", here=here, id=b.button_id, dir=direction, target=target), [])
            if films_have_pg:
                for cmd in b.commands:
                    if (cmd.grp == GRP_SET and cmd.sub_grp == SET_SETSYSTEM and cmd.set_opt == 1
                            and cmd.imm_op1 and cmd.dst & 0x80000000 and not cmd.dst & 0x4000):
                        out.new("hinweis", "ton_schaltet_untertitel_aus",
                                tr("sim_audio_turns_subs_off", here=here, id=b.button_id, cmd=cmd.text()), [])

        # Pfeiltasten: Alle Buttons vom Start-Button aus erreichbar?
        start = page.default_selected_button if page.default_selected_button in buttons else (ids[0] if ids else None)
        if start is None:
            continue
        seen = {start}
        todo = [start]
        while todo:
            b = buttons[todo.pop()]
            for target in (b.upper, b.lower, b.left, b.right):
                if target in buttons and target not in seen:
                    seen.add(target)
                    todo.append(target)
        for bid in ids:
            if bid not in seen:
                out.new("warnung", "pfeiltasten_unerreichbar",
                        tr("sim_arrow_unreachable", here=here, id=bid, start=start), [])


def _check_movie_objects(disc: Disc, out: _Collector):
    """Statische Prüfungen der MovieObjects."""
    # SetOutputMode ohne 3D-Profilprüfung (PSR 31) davor: ältere Player kennen den Befehl nicht
    for mo in disc.movie_objects:
        for i, cmd in enumerate(mo.commands):
            if cmd.grp == GRP_SET and cmd.sub_grp == SET_SETSYSTEM and cmd.set_opt == 0x0A:
                guarded = i > 0 and mo.commands[i - 1].grp == 1 and mo.commands[i - 1].src == 0x00130240
                if not guarded:
                    out.new("hinweis", "3d_ohne_profilpruefung",
                            tr("sim_3d_no_profile_check", mo=mo.object_id, cmd=cmd.text()), [])
                    break
    _check_audio_hint(disc, out)


def _check_audio_hint(disc: Disc, out: _Collector):
    """Hinweis zu Test 13: Ein Ton-Umschalten ohne Untertitel-Angabe schaltet laut libbluray die Untertitel aus."""
    if not any(pl.count("pg") for pid, pl in disc.playlists.items() if pid not in disc.compositions):
        return
    for mo in disc.movie_objects:
        for cmd in mo.commands:
            if (cmd.grp == GRP_SET and cmd.sub_grp == SET_SETSYSTEM and cmd.set_opt == 1
                    and cmd.dst & 0x80000000 and not cmd.dst & 0x4000):
                out.new("hinweis", "ton_schaltet_untertitel_aus",
                        tr("sim_mo_audio_turns_subs_off", mo=mo.object_id, cmd=cmd.text()), [])
                return


def _check_reachability(disc: Disc, report: Report, out: _Collector):
    for n, entry in enumerate(disc.index.titles, start=1):
        if not entry.is_hdmv:
            out.new("hinweis", "titel_bdj", tr("sim_title_bdj", n=n), [])
        elif n not in report.titles_reached:
            out.new("warnung", "titel_unerreichbar", tr("sim_title_never", n=n, mo=entry.mobj_id), [])
    for pl_id, comp in disc.compositions.items():
        if pl_id not in report.playlists_reached:
            continue
        for page in comp.pages:
            # Durchgangsseite (Startseite einer Menügruppe, v1.13): ihr Standard-Button löst sofort aus
            default = next((b for b in page.buttons() if b.button_id == page.default_selected_button), None)
            if default is not None and default.auto_action:
                continue
            if (pl_id, page.page_id) not in report.pages_reached:
                out.new("warnung", "seite_unerreichbar",
                        tr("sim_page_unreachable", pl=f"{pl_id:05d}", page=page.page_id), [])
    if report.truncated:
        out.new("hinweis", "durchlauf_abgebrochen",
                tr("sim_truncated", n=report.states), [])


def merge_findings(reports: List[Report]) -> List[Finding]:
    """Befunde mehrerer Durchläufe (z. B. 3D- und 2D-Fernseher) ohne Doppelte, nach Stufe sortiert."""
    seen: Set[Tuple[str, str]] = set()
    merged = []
    for report in reports:
        for f in report.findings:
            if (f.code, f.text) not in seen:
                seen.add((f.code, f.text))
                merged.append(f)
    merged.sort(key=lambda f: LEVELS.index(f.level))
    return merged


# ─────────────────────────────── Textbericht ───────────────────────────────

def describe_disc(disc: Disc, detailed: bool = False) -> List[str]:
    lines = []
    idx = disc.index
    lines.append(tr("sim_titles", n=len(idx.titles)) + (tr("sim_has_3d") if idx.has_3d_content else ""))
    for pl_id, pl in sorted(disc.playlists.items()):
        comp = disc.compositions.get(pl_id)
        kind = tr("sim_kind_menu") if comp is not None and comp.ui_model == 0 else \
            (tr("sim_kind_3d_film") if pl.is_3d else tr("sim_kind_film"))
        detail = tr("sim_playlist_detail", s=f"{pl.duration_sec:.0f}", audio=pl.count("audio"), pg=pl.count("pg"),
                    marks=len(pl.chapter_marks))
        if pl.count("ig"):
            ig = pl.ig_streams()[0]
            where = tr("sim_ig_in_clip") if ig.entry_type == 1 else tr("sim_ig_subpath")
            if comp is None:
                detail += tr("sim_ig_unreadable", where=where)
            elif comp.ui_model == 1:
                detail += tr("sim_popup", where=where)
        lines.append(f"  {pl_id:05d}.mpls  {kind:8s} {detail}")
    for pl_id, comp in sorted(disc.compositions.items()):
        pages = ", ".join(tr("sim_page_buttons", page=p.page_id, n=len(p.buttons())) for p in comp.pages)
        lines.append("  " + tr("sim_menu", pl=f"{pl_id:05d}") + f": {pages}")
        if not detailed:
            continue
        for p in comp.pages:
            for b in p.buttons():
                lines.append("      " + tr("sim_page_button_cmds", page=p.page_id, id=b.button_id,
                                              cmds=_commands_text(b.commands) or tr("sim_no_commands")))
    for mo in disc.movie_objects if detailed else []:
        lines.append(f"  MovieObject {mo.object_id}: {_commands_text(mo.commands) or tr('sim_empty')}")
    return lines


def format_report(disc: Disc, reports: List[Report], detailed: bool = False) -> str:
    lines = [f"Disc: {disc.bdmv_dir}", ""]
    lines += describe_disc(disc, detailed)
    for report in reports:
        tv = tr("sim_tv_3d") if report.tv_3d else tr("sim_tv_2d")
        lines += ["", "─" * 72, tr("sim_run_with", tv=tv, n=report.states), "─" * 72]
        titles = ", ".join(str(t) for t in sorted(report.titles_reached)) or tr("sim_none")
        lines.append(tr("sim_titles_reached", titles=titles, n=len(disc.index.titles)))
        if not report.findings:
            lines.append(tr("sim_no_findings"))
        for f in report.findings:
            lines.append(f"{LEVEL_ICON[f.level]} {f.text}")
            if f.path:
                lines.append("     " + tr("sim_path", path=" → ".join(f.path)))
        summary = ", ".join(f"{report.count(l)} {name}" for l, name in
                            (("fehler", tr("sim_errors")), ("warnung", tr("sim_warnings")), ("hinweis", tr("sim_hints"))))
        lines.append(tr("sim_result", summary=summary))
    return "\n".join(lines)
