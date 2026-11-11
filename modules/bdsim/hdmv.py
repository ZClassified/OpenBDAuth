# modules/bdsim/hdmv.py
"""
HDMV-Navigationsbefehle (BD-ROM Part 3) für den Disc-Simulator:
Decodierung, lesbare Darstellung und Ausführung einzelner Befehle.

Maßstab für das Verhalten ist libbluray (src/libbluray/hdmv/hdmv_vm.c). Abweichungen vom
Standard, die ein Player still ignoriert, meldet die Maschine als Befund, statt abzubrechen.
"""

import random
import struct
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from core.translations import tr

# Gruppen
GRP_BRANCH, GRP_CMP, GRP_SET = 0, 1, 2
# Branch-Untergruppen
BRANCH_GOTO, BRANCH_JUMP, BRANCH_PLAY = 0, 1, 2
# Set-Untergruppen
SET_SET, SET_SETSYSTEM = 0, 1

GOTO_OPS = {0: "Nop", 1: "Goto", 2: "Break"}
JUMP_OPS = {0: "JumpObject", 1: "JumpTitle", 2: "CallObject", 3: "CallTitle", 4: "Resume"}
PLAY_OPS = {0: "PlayPL", 1: "PlayPLatPI", 2: "PlayPLatPM", 3: "TerminatePL", 4: "LinkPI", 5: "LinkMK"}
CMP_OPS = {1: "BC", 2: "EQ", 3: "NE", 4: "GE", 5: "GT", 6: "LE", 7: "LT"}
SET_OPS = {1: "Move", 2: "Swap", 3: "Add", 4: "Sub", 5: "Mul", 6: "Div", 7: "Mod", 8: "Rnd",
           9: "And", 10: "Or", 11: "Xor", 12: "BitSet", 13: "BitClr", 14: "ShiftL", 15: "ShiftR"}
SETSYSTEM_OPS = {1: "SetStream", 2: "SetNVTimer", 3: "SetButtonPage", 4: "EnableButton",
                 5: "DisableButton", 6: "SetSecondaryStream", 7: "PopUpMenuOff", 8: "StillOn",
                 9: "StillOff", 0x0A: "SetOutputMode", 0x0B: "SetStreamSS", 0x10: "SetSystem0x10"}

# Player Status Register
PSR_IG_STREAM = 0
PSR_PRIMARY_AUDIO = 1
PSR_PG_STREAM = 2
PSR_ANGLE = 3
PSR_TITLE = 4
PSR_CHAPTER = 5
PSR_PLAYLIST = 6
PSR_PLAYITEM = 7
PSR_SELECTED_BUTTON = 10
PSR_MENU_PAGE = 11
PSR_3D_STATUS = 22

NUM_GPR = 4096
NUM_PSR = 128

# Operandenzahl der System-Befehle nach BD-ROM Part 3
SETSYSTEM_OPERANDS = {1: 2, 2: 2, 3: 2, 4: 1, 5: 1, 6: 2, 7: 0, 8: 0, 9: 0, 0x0A: 1, 0x0B: 2}


@dataclass(frozen=True)
class Command:
    raw: bytes
    op_cnt: int
    grp: int
    sub_grp: int
    imm_op1: bool
    imm_op2: bool
    branch_opt: int
    cmp_opt: int
    set_opt: int
    dst: int
    src: int

    @property
    def name(self) -> str:
        if self.grp == GRP_BRANCH:
            table = {BRANCH_GOTO: GOTO_OPS, BRANCH_JUMP: JUMP_OPS, BRANCH_PLAY: PLAY_OPS}.get(self.sub_grp, {})
            return table.get(self.branch_opt, f"Branch?{self.sub_grp}.{self.branch_opt}")
        if self.grp == GRP_CMP:
            return CMP_OPS.get(self.cmp_opt, f"Cmp?{self.cmp_opt}")
        if self.grp == GRP_SET:
            table = {SET_SET: SET_OPS, SET_SETSYSTEM: SETSYSTEM_OPS}.get(self.sub_grp, {})
            return table.get(self.set_opt, f"Set?{self.sub_grp}.{self.set_opt}")
        return f"Gruppe?{self.grp}"

    def _operand(self, imm: bool, value: int) -> str:
        if imm:
            return f"0x{value:08X}" if value > 0xFFFF else str(value)
        if value & 0x80000000:
            return f"PSR{value & 0x7F}"
        return f"GPR{value & 0xFFF}"

    def text(self) -> str:
        """Lesbare Darstellung, z. B. 'JumpTitle(2)' oder 'SetButtonPage(Seite 1)'."""
        n = self.name
        a = self._operand(self.imm_op1, self.dst)
        b = self._operand(self.imm_op2, self.src)
        if self.grp == GRP_SET and self.sub_grp == SET_SETSYSTEM:
            if self.set_opt == 3:
                parts = []
                if self.dst & 0x80000000 or not self.imm_op1:
                    parts.append(f"Button {a if not self.imm_op1 else self.dst & 0xFFFF}")
                if self.op_cnt > 1 and (self.src & 0x80000000 or not self.imm_op2):
                    parts.append(tr("sim_cmd_page", n=b if not self.imm_op2 else self.src & 0xFF))
                return f"SetButtonPage({', '.join(parts) or 'ohne Wirkung'})"
            if self.set_opt == 1 and self.imm_op1:
                return f"SetStream({describe_set_stream(self.dst, self.src if self.op_cnt > 1 else 0)})"
            if self.set_opt == 1:
                parts = []
                if self.dst & 0x80000000:
                    parts.append(tr("sim_cmd_audio_gpr", n=(self.dst >> 16) & 0xFFF))
                if self.dst & 0x8000:
                    parts.append(tr("sim_cmd_subs_gpr", n=self.dst & 0xFFF))
                parts.append(tr("sim_cmd_subs_on") if self.dst & 0x4000 else tr("sim_cmd_subs_off"))
                return f"SetStream({', '.join(parts)})"
            if self.set_opt == 0x0A:
                return f"SetOutputMode({'3D' if self.dst & 1 else '2D'})" if self.imm_op1 else f"SetOutputMode({a})"
        if self.op_cnt == 0 or (self.grp == GRP_BRANCH and self.sub_grp == BRANCH_GOTO and self.branch_opt != 1):
            return n
        if self.op_cnt == 1:
            return f"{n}({a})"
        if self.grp == GRP_SET and self.sub_grp == SET_SET:
            return f"{n}({a}, {b})"
        return f"{n}({a}, {b})"


def decode_command(raw: bytes) -> Command:
    b0, b1, b2, b3 = raw[0], raw[1], raw[2], raw[3]
    dst, src = struct.unpack(">II", raw[4:12])
    return Command(bytes(raw), op_cnt=b0 >> 5, grp=(b0 >> 3) & 0x03, sub_grp=b0 & 0x07,
                   imm_op1=bool(b1 & 0x80), imm_op2=bool(b1 & 0x40), branch_opt=b1 & 0x0F,
                   cmp_opt=b2 & 0x0F, set_opt=b3 & 0x1F, dst=dst, src=src)


def describe_set_stream(dst: int, src: int) -> str:
    parts = []
    if dst & 0x80000000:
        parts.append(tr("sim_cmd_audio", n=(dst >> 16) & 0xFFF))
    if dst & 0x8000:
        parts.append(tr("sim_cmd_subs", n=dst & 0xFFF))
    parts.append(tr("sim_cmd_subs_on") if dst & 0x4000 else tr("sim_cmd_subs_off"))
    if src & 0x80000000:
        parts.append(f"IG {(src >> 16) & 0xFF}")
    if src & 0x8000:
        parts.append(f"Winkel {src & 0xFF}")
    return ", ".join(parts)


# ─────────────────────────────── Ereignisse der Maschine ───────────────────────────────

@dataclass
class Event:
    """Ergebnis eines Schritts, das der Player umsetzen muss."""
    kind: str          # play, link, stop_play, title, object_changed, button_page, enable_button,
                       # disable_button, popup_off, end, ig_end, error
    a: int = 0
    b: int = 0
    c: int = 0


class _SparseGPR(dict):
    """4096 GPR, gespeichert nur mit Werten ungleich 0 (schnelles Kopieren und Vergleichen im Durchlauf)."""

    def __missing__(self, key):
        return 0

    def __setitem__(self, key, value):
        if value:
            super().__setitem__(key, value)
        else:
            self.pop(key, None)


def _gpr(value: int) -> Optional[int]:
    return None if value & 0x80000000 else value & 0xFFF


def command_registers(cmd: "Command") -> Tuple[set, set]:
    """(gelesene, geschriebene) GPRs eines Befehls; PSRs zählen nicht."""
    reads, writes = set(), set()
    read = lambda value: reads.add(_gpr(value)) if _gpr(value) is not None else None
    if cmd.grp == GRP_SET and cmd.sub_grp == SET_SETSYSTEM and cmd.set_opt in (1, 6, 3):
        for imm, value in ((cmd.imm_op1, cmd.dst), (cmd.imm_op2, cmd.src))[:max(1, cmd.op_cnt)]:
            if not imm:
                reads.add(value & 0xFFF)
                if cmd.set_opt in (1, 6):
                    reads.add((value >> 16) & 0xFFF)
    elif cmd.grp == GRP_SET and cmd.sub_grp == SET_SET:
        target = _gpr(cmd.dst)
        if target is not None:
            writes.add(target)
            if cmd.set_opt != 1:
                reads.add(target)
        if cmd.op_cnt > 1 and not cmd.imm_op2:
            read(cmd.src)
            if cmd.set_opt == 2 and _gpr(cmd.src) is not None:
                writes.add(_gpr(cmd.src))
    else:
        if cmd.op_cnt > 0 and not cmd.imm_op1:
            read(cmd.dst)
        if cmd.op_cnt > 1 and not cmd.imm_op2:
            read(cmd.src)
    return reads, writes


def scratch_registers(command_lists) -> frozenset:
    """
    GPRs, deren Wert zwischen zwei Befehlsfolgen keine Rolle spielt: In jeder Folge (MovieObject, Button), die sie
    liest, werden sie vorher ohne Bedingung beschrieben (z. B. GPR 9 der Startseite einer Menügruppe, v1.13).
    Der automatische Durchlauf unterscheidet Zustände dann nicht nach ihnen. Vorsichtig: Folgen mit Goto zählen
    jedes Lesen als echt, und ein Befehl direkt nach einem Vergleich schreibt nur bedingt.
    """
    written_anywhere, live = set(), set()
    for commands in command_lists:
        has_goto = any(c.grp == GRP_BRANCH and c.sub_grp == BRANCH_GOTO for c in commands)
        written, conditional = set(), False
        for cmd in commands:
            reads, writes = command_registers(cmd)
            live |= reads if has_goto else reads - written
            written_anywhere |= writes
            if not conditional:
                written |= writes
            conditional = cmd.grp == GRP_CMP
    return frozenset(written_anywhere - live)


class Registers:
    def __init__(self):
        self.gpr = _SparseGPR()
        self.psr = [0] * NUM_PSR
        # Startwerte wie libbluray (bd_registers_init)
        self.psr[PSR_IG_STREAM] = 1
        self.psr[PSR_PRIMARY_AUDIO] = 1
        self.psr[PSR_PG_STREAM] = 0x0FFF
        self.psr[PSR_ANGLE] = 1
        self.psr[PSR_TITLE] = 0xFF
        self.psr[PSR_CHAPTER] = 0xFFFF
        self.psr[PSR_SELECTED_BUTTON] = 0xFFFF

    def read(self, reg: int) -> int:
        if reg & 0x80000000:
            return self.psr[reg & 0x7F]
        return self.gpr[reg & 0xFFF]

    def snapshot(self, ignore: frozenset = frozenset()) -> Tuple:
        gprs = tuple(sorted((k, v) for k, v in self.gpr.items() if k not in ignore))
        return gprs, self.psr[PSR_PRIMARY_AUDIO], self.psr[PSR_PG_STREAM], self.psr[PSR_3D_STATUS] & 1

    def copy(self) -> "Registers":
        r = Registers.__new__(Registers)
        r.gpr = _SparseGPR(self.gpr)
        r.psr = list(self.psr)
        return r


Report = Callable[[str, str, str], None]   # (Stufe, Code, Text)


class Machine:
    """
    HDMV-Maschine. Führt MovieObjects oder – im Menü – die Befehle eines Buttons aus.
    Der Player ruft run() auf und setzt die zurückgegebenen Ereignisse um.
    """

    MAX_STEPS = 10000

    def __init__(self, movie_objects, title_count: int, report: Optional[Report] = None,
                 player_3d: bool = True, seed: int = 1):
        self.movie_objects = movie_objects
        self.title_count = title_count
        self.regs = Registers()
        self.player_3d = player_3d
        # PSR 31 (Profil/Version): 3D-Player melden Profil 5, ältere Profil 2 (BD-Live)
        self.regs.psr[31] = 0x00130240 if player_3d else 0x00030200
        self.object_id: Optional[int] = None
        self.pc = 0
        self.ig_commands: Optional[List[Command]] = None
        self.ig_pc = 0
        self.suspended: Optional[Tuple[int, int, List[int]]] = None
        self.waiting_for_play = False
        self.wants_2d = False      # das laufende MovieObject hat SetOutputMode(2D) gewählt (2D-Start eines 3D-Films)
        self.report: Report = report or (lambda level, code, text: None)
        self.log: List[str] = []
        self._rng = random.Random(seed)

    # ─── Zustand ───
    def copy(self) -> "Machine":
        m = Machine.__new__(Machine)
        m.__dict__.update(self.__dict__)
        m.regs = self.regs.copy()
        m.log = list(self.log)
        m._rng = random.Random(self._rng.random())
        return m

    def snapshot(self, ignore: frozenset = frozenset()) -> Tuple:
        suspended = self.suspended[:2] if self.suspended else None
        return (self.object_id, self.pc, self.waiting_for_play, suspended, self.regs.snapshot(ignore))

    # ─── Einstieg ───
    def start_object(self, object_id: int):
        self.object_id = object_id
        self.pc = 0
        self.ig_commands = None
        self.waiting_for_play = False
        self.wants_2d = False

    def start_button(self, commands: List[Command]):
        self.ig_commands = list(commands)
        self.ig_pc = 0

    def playlist_ended(self):
        """Die mit PlayPL gestartete Playlist ist zu Ende: weiter mit dem nächsten Befehl."""
        if self.waiting_for_play:
            self.waiting_for_play = False
            self.pc += 1

    # ─── Ausführung ───
    def run(self) -> List[Event]:
        """Führt Befehle aus, bis die Maschine auf den Player wartet. Gibt die Ereignisse zurück."""
        events: List[Event] = []
        for _ in range(self.MAX_STEPS):
            in_ig = self.ig_commands is not None
            if in_ig:
                if self.ig_pc >= len(self.ig_commands):
                    self.ig_commands = None
                    events.append(Event("ig_end"))
                    return events
                cmd = self.ig_commands[self.ig_pc]
            else:
                if self.object_id is None or self.waiting_for_play:
                    return events
                obj = self._object(self.object_id)
                if obj is None:
                    self.report("fehler", "objekt_fehlt", tr("sim_mobj_missing", mo=self.object_id))
                    self.object_id = None
                    events.append(Event("end"))
                    return events
                if self.pc >= len(obj.commands):
                    self.log.append(tr("sim_mobj_end", mo=self.object_id))
                    self.object_id = None
                    events.append(Event("end"))
                    return events
                cmd = obj.commands[self.pc]

            where = "Button" if in_ig else f"MObj {self.object_id}/{self.pc}"
            self.log.append(f"{where}: {cmd.text()}")
            self._check_operand_count(cmd)
            step_events, blocking = self._step(cmd, in_ig)
            events.extend(step_events)
            if blocking:
                return events
        self.report("fehler", "endlosschleife",
                    tr("sim_endless_loop", mo=self.object_id, n=self.MAX_STEPS))
        self.object_id = None
        self.ig_commands = None
        events.append(Event("end"))
        return events

    def _check_operand_count(self, cmd: Command):
        """Der Player liest nur so viele Operanden, wie op_cnt angibt; weitere Werte gehen verloren."""
        if (cmd.op_cnt < 2 and cmd.src) or (cmd.op_cnt < 1 and cmd.dst):
            ignored = f"0x{cmd.src:X}" if cmd.op_cnt < 2 and cmd.src else f"0x{cmd.dst:X}"
            self.report("fehler", "operand_ignoriert",
                        tr("sim_operand_ignored", name=cmd.name, raw=cmd.raw.hex(), n=cmd.op_cnt, value=ignored))

    def _object(self, object_id: int):
        if 0 <= object_id < len(self.movie_objects):
            return self.movie_objects[object_id]
        return None

    def _advance(self, in_ig: bool, n: int = 1):
        if in_ig:
            self.ig_pc += n
        else:
            self.pc += n

    def _fetch(self, cmd: Command) -> Tuple[int, int]:
        setstream = cmd.grp == GRP_SET and cmd.sub_grp == SET_SETSYSTEM and cmd.set_opt in (1, 6)
        setbuttonpage = cmd.grp == GRP_SET and cmd.sub_grp == SET_SETSYSTEM and cmd.set_opt == 3
        dst = src = 0
        if cmd.op_cnt > 0:
            dst = self._operand(setstream, setbuttonpage, cmd.imm_op1, cmd.dst)
        if cmd.op_cnt > 1:
            src = self._operand(setstream, setbuttonpage, cmd.imm_op2, cmd.src)
        return dst, src

    def _operand(self, setstream: bool, setbuttonpage: bool, imm: bool, value: int) -> int:
        if imm:
            return value
        if setstream:
            flags = value & 0xF000F000
            return flags | (self.regs.read(value & 0xFFF) & 0xFFF) | ((self.regs.read((value >> 16) & 0xFFF) & 0xFFF) << 16)
        if setbuttonpage:
            return (value & 0xC0000000) | (self.regs.read(value & 0xFFF) & 0x3FFFFFFF)
        return self.regs.read(value)

    def _step(self, cmd: Command, in_ig: bool) -> Tuple[List[Event], bool]:
        if cmd.grp == GRP_BRANCH:
            return self._branch(cmd, in_ig)
        if cmd.grp == GRP_CMP:
            self._compare(cmd, in_ig)
            return [], False
        if cmd.grp == GRP_SET and cmd.sub_grp == SET_SET:
            self._set(cmd, in_ig)
            return [], False
        if cmd.grp == GRP_SET and cmd.sub_grp == SET_SETSYSTEM:
            return self._setsystem(cmd, in_ig)
        self.report("fehler", "befehl_unbekannt", f"Unbekannter Befehl {cmd.raw.hex()} (Gruppe {cmd.grp})")
        self._advance(in_ig)
        return [], False

    # ─── Branch ───
    def _branch(self, cmd: Command, in_ig: bool) -> Tuple[List[Event], bool]:
        dst, src = self._fetch(cmd)
        if cmd.sub_grp == BRANCH_GOTO:
            if cmd.branch_opt == 0:
                self._advance(in_ig)
            elif cmd.branch_opt == 1:
                if in_ig:
                    self.ig_pc = dst
                else:
                    self.pc = dst
            elif cmd.branch_opt == 2:
                if in_ig:
                    self.ig_pc = len(self.ig_commands)
                else:
                    self.object_id = None
                    return [Event("end")], True
            else:
                self._unknown(cmd, in_ig)
            return [], False

        if cmd.sub_grp == BRANCH_JUMP:
            op = cmd.branch_opt
            if op in (0, 2):                       # JumpObject / CallObject
                if self._object(dst) is None:
                    self.report("fehler", "objekt_fehlt", tr("sim_cmd_mobj_missing", cmd=cmd.text(), mo=dst))
                    self._advance(in_ig)
                    return [], False
                if op == 2:
                    self._suspend()
                self.ig_commands = None
                self.start_object(dst)
                return [Event("object_changed", dst)], False
            if op in (1, 3):                       # JumpTitle / CallTitle
                if not 1 <= dst <= self.title_count:
                    self.report("fehler", "titel_fehlt",
                                tr("sim_cmd_title_missing", cmd=cmd.text(), n=dst, count=self.title_count))
                    self._advance(in_ig)
                    return [], False
                if op == 3:
                    self._suspend()
                else:
                    self.suspended = None
                self.ig_commands = None
                return [Event("title", dst)], True
            if op == 4:                            # Resume
                if self.suspended is None:
                    self.report("warnung", "resume_ohne_call", "Resume ohne vorheriges CallObject/CallTitle")
                    self._advance(in_ig)
                    return [], False
                obj_id, pc, psr = self.suspended
                self.suspended = None
                self.regs.psr[:len(psr)] = psr
                self.ig_commands = None
                self.object_id, self.pc, self.waiting_for_play = obj_id, pc + 1, False
                return [Event("object_changed", obj_id)], False
            self._unknown(cmd, in_ig)
            return [], False

        if cmd.sub_grp == BRANCH_PLAY:
            op = cmd.branch_opt
            if op in (0, 1, 2):
                if in_ig:
                    self.report("fehler", "playlist_im_button",
                                tr("sim_playpl_in_button", cmd=cmd.text()))
                    self.ig_commands = None
                    return [Event("ig_end")], True
                self.waiting_for_play = True
                return [Event("play", dst, op, src)], True
            if op == 3:                            # TerminatePL
                if in_ig:
                    self.ig_commands = None
                    self.playlist_ended()
                    return [Event("stop_play")], False
                self._advance(in_ig)
                return [], False
            if op in (4, 5):                       # LinkPI / LinkMK
                if not in_ig:
                    self.report("fehler", "link_im_objekt",
                                f"{cmd.text()} im MovieObject: Link-Befehle sind nur in Buttons erlaubt")
                    self._advance(in_ig)
                    return [], False
                self.ig_commands = None
                return [Event("link", op, dst)], True
            self._unknown(cmd, in_ig)
            return [], False

        self._unknown(cmd, in_ig)
        return [], False

    def _suspend(self):
        self.suspended = (self.object_id, self.pc, list(self.regs.psr[:32]))

    # ─── Vergleich ───
    def _compare(self, cmd: Command, in_ig: bool):
        dst, src = self._fetch(cmd)
        op = cmd.cmp_opt
        results = {1: (dst & ~src) == 0, 2: dst == src, 3: dst != src, 4: dst >= src,
                   5: dst > src, 6: dst <= src, 7: dst < src}
        if op not in results:
            self._unknown(cmd, in_ig)
            return
        self._advance(in_ig, 1 if results[op] else 2)

    # ─── Register-Arithmetik ───
    def _set(self, cmd: Command, in_ig: bool):
        if cmd.imm_op1:
            self.report("fehler", "rechnen_mit_festem_ziel",
                        tr("sim_arith_immediate_dst", cmd=cmd.text(), byte=f"0x{cmd.raw[0]:02X}"))
        target = cmd.dst
        if target & 0x80000000:
            self.report("fehler", "psr_schreiben", tr("sim_psr_write", cmd=cmd.text()))
            self._advance(in_ig)
            return
        target &= 0xFFF
        _, src = self._fetch(cmd)
        cur = self.regs.gpr[target]
        op = cmd.set_opt
        mask = 0xFFFFFFFF
        if op == 1:
            new = src
        elif op == 2:
            if cmd.imm_op2:
                self.report("fehler", "swap_mit_wert", f"{cmd.text()}: Swap braucht zwei Register")
                self._advance(in_ig)
                return
            other = cmd.src & 0xFFF
            new = self.regs.gpr[other]
            self.regs.gpr[other] = cur
        elif op == 3:
            new = min(cur + src, mask)
        elif op == 4:
            new = max(cur - src, 0)
        elif op == 5:
            new = min(cur * src, mask)
        elif op in (6, 7):
            if src == 0:
                self.report("fehler", "division_durch_null", f"{cmd.text()}: Division durch 0")
                self._advance(in_ig)
                return
            new = cur // src if op == 6 else cur % src
        elif op == 8:
            new = self._rng.randint(1, src) if src else 0
        elif op == 9:
            new = cur & src
        elif op == 10:
            new = cur | src
        elif op == 11:
            new = cur ^ src
        elif op == 12:
            new = cur | (1 << (src & 31))
        elif op == 13:
            new = cur & ~(1 << (src & 31))
        elif op == 14:
            new = (cur << (src & 31)) & mask
        elif op == 15:
            new = cur >> (src & 31)
        else:
            self._unknown(cmd, in_ig)
            return
        self.regs.gpr[target] = new & mask
        self._advance(in_ig)

    # ─── System-Befehle ───
    def _setsystem(self, cmd: Command, in_ig: bool) -> Tuple[List[Event], bool]:
        dst, src = self._fetch(cmd)
        op = cmd.set_opt
        expected = SETSYSTEM_OPERANDS.get(op)
        if expected is not None and cmd.op_cnt != expected:
            sony = tr("sim_sony_ignores") if op == 1 else ""
            self.report("fehler" if op == 1 else "warnung", "operandenzahl",
                        tr("sim_operand_count", name=cmd.name, raw=cmd.raw.hex(), n=cmd.op_cnt, expected=expected) + sony)
        events: List[Event] = []
        if op == 1:
            self._set_stream(dst, src)
        elif op == 3:
            if not (dst & 0x80000000) and not (src & 0x80000000):
                self.report("warnung", "seitenwechsel_ohne_ziel",
                            tr("sim_setbuttonpage_no_flag", cmd=cmd.text()))
            if in_ig:
                self.ig_commands = None
                return [Event("button_page", dst, src)], True
            if dst & 0x80000000:
                self.regs.psr[PSR_SELECTED_BUTTON] = dst & 0xFFFF
            if src & 0x80000000:
                self.regs.psr[PSR_MENU_PAGE] = src & 0xFF
        elif op in (4, 5):
            events.append(Event("enable_button" if op == 4 else "disable_button", dst & 0xFFFF))
        elif op == 7:
            events.append(Event("popup_off"))
        elif op == 0x0A:
            self.wants_2d = not dst & 1
            if self.player_3d:
                if dst & 1:
                    self.regs.psr[PSR_3D_STATUS] |= 1
                else:
                    self.regs.psr[PSR_3D_STATUS] &= ~1
        elif op in (2, 6, 8, 9, 0x0B, 0x10):
            pass
        else:
            self._unknown(cmd, in_ig)
            return events, False
        self._advance(in_ig)
        return events, False

    def _set_stream(self, dst: int, src: int):
        """Wie libbluray _set_stream: das Anzeige-Flag der Untertitel wird immer übernommen."""
        psr = self.regs.psr
        if dst & 0x80000000:
            psr[PSR_PRIMARY_AUDIO] = (dst >> 16) & 0xFFF
        if src & 0x80000000:
            psr[PSR_IG_STREAM] = (src >> 16) & 0xFF
        if src & 0x8000:
            psr[PSR_ANGLE] = src & 0xFF
        pg = psr[PSR_PG_STREAM]
        if dst & 0x8000:
            pg = (dst & 0xFFF) | (pg & 0xFFFFF000)
        pg = ((dst & 0x4000) << 17) | (pg & 0x7FFFFFFF)
        psr[PSR_PG_STREAM] = pg

    def _unknown(self, cmd: Command, in_ig: bool):
        self.report("fehler", "befehl_unbekannt", f"Unbekannter Befehl {cmd.text()} ({cmd.raw.hex()})")
        self._advance(in_ig)
