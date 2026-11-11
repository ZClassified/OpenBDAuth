# modules/bdmv/movie_object_generator.py
"""
HDMV MovieObject.bdmv Generator nach BD-ROM Part 3.

Erzeugt standardkonforme MovieObject.bdmv Binärdateien mit echten
HDMV Virtual Machine Navigations-Opcodes:
- PlayPL(playlist_id): Startet eine Playlist
- JumpTitle(title_id): Springt zu einem Titel (z. B. 0 = Menü)
- JumpObject(object_id): Springt zu einem MovieObject
"""

import struct
from typing import Dict, List, Optional

# HDMV Instruction Groups
INSN_GROUP_BRANCH = 0
INSN_GROUP_CMP = 1
INSN_GROUP_SET = 2

# Branch Subgroups
BRANCH_GOTO = 0
BRANCH_JUMP = 1
BRANCH_PLAY = 2

# Play Options
INSN_PLAY_PL = 0
INSN_PLAY_PL_PI = 1
INSN_PLAY_PL_PM = 2

# Jump Options
INSN_JUMP_OBJECT = 0
INSN_JUMP_TITLE = 1

# Set Sub-Groups: 0 = Register-Arithmetik (Move, Add, ...), 1 = SetSystem
SET_SUBGRP_SET = 0
SET_SUBGRP_SETSYSTEM = 1

# SetSystem Options (Group 2, Subgroup 1)
INSN_SET_STREAM = 1
INSN_SET_BUTTON_PAGE = 3
INSN_SET_OUTPUT_MODE = 0x0A

# Set Options (Group 2, Subgroup 0: Register-Arithmetik)
INSN_MOVE = 1
INSN_SUB = 4
INSN_AND = 9
INSN_OR = 10
INSN_SHIFT_RIGHT = 15

# Player Status Register als Quell-Operand (Bit 31 = PSR)
PSR_PRIMARY_AUDIO = 0x80000001
PSR_PG_STREAM = 0x80000002
PSR_SELECTED_BUTTON = 0x8000000A   # PSR 10: ausgewählter Button
PSR_MENU_PAGE = 0x8000000B         # PSR 11: angezeigte Menüseite
PSR_PROFILE_VERSION = 0x8000001F   # PSR 31: Player-Profil und -Version
PROFILE_5_3D = 0x00130240          # Profil 5 (3D) – dieselbe Maske prüft libbluray

# Compare Options (Group 1)
CMP_EQ = 2
CMP_NE = 3

# ─── Registerbelegung (GPR) von OpenBDAuth ─────────────────────────────────────
# Menü-Buttons merken sich Wünsche nur in Registern; der Titel des Films setzt sie beim Start um.
# Grund (Sony UBP-X700, v1.8.3): Spurwechsel aus dem Menü verwirft der Player, weil die Menü-Playlist
# die Spur nicht hat; Kapitelsprünge über JumpObject hinterlassen eine nie verworfene Unterbrechung.
# GPR 0–16 sind für OpenBDAuth reserviert (11–15: Stufe 3.1 „Letzte Auswahl merken“).
GPR_CHAPTER = 0          # Kapitelwunsch: 0 = von vorn, n = PlayListMark-Index + 1
GPR_AUDIO = 1            # Tonspur-Wunsch: 0 = unverändert, n = Tonspur n
GPR_SUBTITLE = 2         # Untertitel-Spur: n = PG-Spur n (gilt mit GPR_SUBTITLE_MODE = SUB_ON)
GPR_SUBTITLE_MODE = 3    # 0 = unverändert, SUB_ON = Spur aus GPR_SUBTITLE zeigen, SUB_OFF = aus
GPR_SCRATCH = 4          # Zwischenwert im Titel-Objekt
GPR_FILM_PLAYED = 5      # 1 = ein Film mit Sprachmenü lief; das Menü übernimmt dann dessen aktuelle Spuren
GPR_PROFILE = 6          # Zwischenwert für die 3D-Profilprüfung vor SetOutputMode
GPR_MENU_PAGE = 7        # Seitenwunsch fürs Menü (v1.13): 0 = keiner, sonst die Seite (≥ 1, Seite 0 = Startseite)
GPR_MENU_BUTTON = 8      # Button-Wunsch: 0 = Standard-Button der Seite, sonst die Button-Nummer
GPR_PAGE_NOW = 9         # Startseite: Seite, die gleich gezeigt wird (Wunsch schon zurückgesetzt)
GPR_BUTTON_NOW = 10      # Startseite: Button, der gleich ausgewählt wird
GPR_PLAY_2D = 16         # 3D-Filme in 2D (v1.20): 0 = 3D, 1 = 2D; gesetzt vom Button, der den Film startet
NO_BUTTON = 0xFFFF       # PSR 10 ohne ausgewählten Button
FLAG = 0x80000000
SUB_ON = 1
SUB_OFF = 2

def make_hdmv_cmd(
    op_cnt: int = 1,
    grp: int = INSN_GROUP_BRANCH,
    sub_grp: int = BRANCH_PLAY,
    imm_op1: int = 1,
    imm_op2: int = 0,
    branch_opt: int = INSN_PLAY_PL,
    cmp_opt: int = 0,
    set_opt: int = 0,
    dst: int = 0,
    src: int = 0
) -> bytes:
    """Packt einen 12-Byte HDMV Command nach BD-ROM Spezifikation."""
    b0 = ((op_cnt & 0x07) << 5) | ((grp & 0x03) << 3) | (sub_grp & 0x07)
    b1 = ((imm_op1 & 1) << 7) | ((imm_op2 & 1) << 6) | (branch_opt & 0x0F)
    b2 = cmp_opt & 0x0F
    b3 = set_opt & 0x1F
    return bytes([b0, b1, b2, b3]) + struct.pack(">II", dst, src)

def cmd_play_playlist(playlist_id: int) -> bytes:
    """Erzeugt den HDMV Befehl PlayPL(playlist_id)."""
    return make_hdmv_cmd(
        op_cnt=1,
        grp=INSN_GROUP_BRANCH,
        sub_grp=BRANCH_PLAY,
        imm_op1=1,
        branch_opt=INSN_PLAY_PL,
        dst=playlist_id,
        src=0
    )

def cmd_play_playlist_at_mark(playlist_id: int, mark_id: int) -> bytes:
    """
    Erzeugt den HDMV Befehl PlayPLatPM(playlist_id, mark_id).
    Wird für direkte Kapitel-Sprünge verwendet (mark_id ist der 0-basierte PlayListMark-Index).
    Zwei Operanden: Mit op_cnt=1 liest der Player die Marke nicht und startet immer bei Marke 0.
    Nur in MovieObjects erlaubt; aus einem Button heraus verwirft der Player Playlist-Befehle.
    """
    return make_hdmv_cmd(
        op_cnt=2,
        grp=INSN_GROUP_BRANCH,
        sub_grp=BRANCH_PLAY,
        imm_op1=1,
        imm_op2=1,
        branch_opt=INSN_PLAY_PL_PM,
        dst=playlist_id,
        src=mark_id
    )

def cmd_jump_title(title_id: int) -> bytes:
    """Erzeugt den HDMV Befehl JumpTitle(title_id)."""
    return make_hdmv_cmd(
        op_cnt=1,
        grp=INSN_GROUP_BRANCH,
        sub_grp=BRANCH_JUMP,
        imm_op1=1,
        branch_opt=INSN_JUMP_TITLE,
        dst=title_id,
        src=0
    )

def cmd_jump_object(object_id: int) -> bytes:
    """Erzeugt den HDMV Befehl JumpObject(object_id)."""
    return make_hdmv_cmd(
        op_cnt=1,
        grp=INSN_GROUP_BRANCH,
        sub_grp=BRANCH_JUMP,
        imm_op1=1,
        branch_opt=INSN_JUMP_OBJECT,
        dst=object_id,
        src=0
    )

def cmd_set_stream(
    audio_id: Optional[int] = None,
    subtitle_id: Optional[int] = None,
    subtitle_on: Optional[bool] = None
) -> bytes:
    """
    Erzeugt den HDMV Befehl SetStream(audio_id, subtitle_id, subtitle_on).
    Ermöglicht das Umschalten von Tonspuren und Untertiteln:
    - audio_id: 1-basierter Index der primären Tonspur (oder None = unverändert)
    - subtitle_id: 1-basierter Index der PG-Untertitelspur (oder None = unverändert)
    - subtitle_on: True (anzeigen), False (ausblenden), None (Zustand beibehalten)
    Zwei Operanden (0x51 C0 …), der zweite (IG/Winkel) leer – die übliche Form;
    mit nur einem Operanden (0x31 …, bis v1.8.4) ignorierte der Sony UBP-X700 ihn.
    """
    dst = 0
    if audio_id is not None:
        # Bit 31: Primary Audio change flag, Bits 27..16: Audio Stream ID
        dst |= 0x80000000 | ((audio_id & 0x0FFF) << 16)
    
    if subtitle_id is not None or subtitle_on is not None:
        # Bit 15: PG stream change flag
        dst |= 0x00008000
        if subtitle_on is True or (subtitle_on is None and subtitle_id is not None):
            # Bit 14: PG display flag (Untertitel einschalten)
            dst |= 0x00004000
        if subtitle_id is not None:
            # Bits 11..0: PG Stream ID
            dst |= (subtitle_id & 0x0FFF)

    return make_hdmv_cmd(
        op_cnt=2,
        grp=INSN_GROUP_SET,
        sub_grp=SET_SUBGRP_SETSYSTEM,
        imm_op1=1,
        imm_op2=1,
        branch_opt=0,
        set_opt=INSN_SET_STREAM,
        dst=dst,
        src=0
    )

def cmd_set_button_page(page_id: int) -> bytes:
    """
    Erzeugt den HDMV Befehl SetButtonPage(button, page).
    Schaltet auf eine andere Seite (Page) innerhalb der aktiven
    Interactive Composition um (z. B. Hauptseite -> Sprachauswahl).
    - dst: button_flag (Bit 31) + Button ID; 0 = Standard-Button der Zielseite
    - src: page_flag (Bit 31) + Page ID (Bits 7..0); ohne page_flag wechselt der Player nicht
    """
    return make_hdmv_cmd(
        op_cnt=2,
        grp=INSN_GROUP_SET,
        sub_grp=SET_SUBGRP_SETSYSTEM,
        imm_op1=1,
        imm_op2=1,
        branch_opt=0,
        set_opt=INSN_SET_BUTTON_PAGE,
        dst=0,
        src=0x80000000 | (page_id & 0xFF)
    )

def cmd_set_button_page_from_registers(page_register: int, button_register: Optional[int] = None) -> bytes:
    """
    SetButtonPage mit Register-Operanden (v1.13): Seite = GPR[page_register], Button = GPR[button_register].
    Wie bei SetStream stehen die Flags im Befehl (Bit 31 von dst/src), das Register liefert nur die Nummer
    (libbluray _fetch_operand: flags = value & 0xC0000000, Nummer = GPR[value & 0xFFF]).
    Ohne button_register: nur die Seite, der Player wählt deren Standard-Button.
    """
    if button_register is None:
        return make_hdmv_cmd(op_cnt=2, grp=INSN_GROUP_SET, sub_grp=SET_SUBGRP_SETSYSTEM, imm_op1=1, imm_op2=0,
                             set_opt=INSN_SET_BUTTON_PAGE, dst=0, src=FLAG | page_register)
    return make_hdmv_cmd(op_cnt=2, grp=INSN_GROUP_SET, sub_grp=SET_SUBGRP_SETSYSTEM, imm_op1=0, imm_op2=0,
                         set_opt=INSN_SET_BUTTON_PAGE, dst=FLAG | button_register, src=FLAG | page_register)


def cmd_or_gpr(register: int, value: int) -> bytes:
    """Or GPR[register] |= value (fester Wert)."""
    return make_hdmv_cmd(op_cnt=2, grp=INSN_GROUP_SET, sub_grp=SET_SUBGRP_SET, imm_op1=0, imm_op2=1,
                         set_opt=INSN_OR, dst=register, src=value)


def start_page_commands(first_page: int = 1) -> List[bytes]:
    """
    Befehle des unsichtbaren Buttons auf der Startseite (Seite 0) einer Menügruppe mit mehreren Seiten (v1.13):
    die gewünschte Seite (GPR 7) mit dem gewünschten Button (GPR 8) zeigen – ohne Seitenwunsch die erste echte
    Seite, ohne Button-Wunsch (0) deren Standard-Button. Der Button hat auto_action und ist Standard-Button der
    Startseite. SetButtonPage beendet ein Button-Programm sofort (libbluray: „terminate“); die Wünsche werden
    deshalb vorher nach GPR 9/10 umkopiert und zurückgesetzt (der Simulator erkennt GPR 9/10 als Hilfsregister).
    """
    return [
        cmd_compare_gpr(CMP_EQ, GPR_MENU_PAGE, 0), cmd_move_gpr(GPR_MENU_PAGE, first_page),
        cmd_copy_gpr(GPR_PAGE_NOW, GPR_MENU_PAGE), cmd_copy_gpr(GPR_BUTTON_NOW, GPR_MENU_BUTTON),
        cmd_move_gpr(GPR_MENU_PAGE, 0), cmd_move_gpr(GPR_MENU_BUTTON, 0),
        cmd_compare_gpr(CMP_EQ, GPR_BUTTON_NOW, 0), cmd_set_button_page_from_registers(GPR_PAGE_NOW),
        cmd_set_button_page_from_registers(GPR_PAGE_NOW, GPR_BUTTON_NOW),
    ]


def jump_menu_commands(object_id: int, page_id: int) -> List[bytes]:
    """Button, der in ein Menü einer anderen Menügruppe führt (v1.13): Seite merken, Menü-Objekt der Gruppe starten
    (Buttons dürfen keine Playlist starten, 9.1.1); dessen Startseite zeigt die Seite."""
    return [cmd_move_gpr(GPR_MENU_PAGE, page_id), cmd_jump_object(object_id)]


def film_end_commands(object_id: int, page_id: int, button_id: int = 0) -> List[bytes]:
    """Filmende in einem anderen Menü als dem Hauptmenü (v1.18): wie jump_menu_commands, dazu auf Wunsch der
    ausgewählte Button (GPR 8, z. B. der Button, der den Film gestartet hat). Die Zielgruppe hat eine Startseite."""
    cmds = [cmd_move_gpr(GPR_MENU_PAGE, page_id)]
    if button_id:
        cmds.append(cmd_move_gpr(GPR_MENU_BUTTON, button_id))
    return cmds + [cmd_jump_object(object_id)]


def menu_loop_commands(playlist_id: int, start: int, keep_page: bool, object_id: int) -> List[bytes]:
    """
    Menü-Playlist einer Gruppe abspielen. Mit keep_page (Gruppe mit Startseite) werden danach Seite und Button
    gemerkt (PSR 11/10; ohne ausgewählten Button der Standard-Button) und die Playlist per
    Goto neu gestartet; die Startseite stellt beides wieder her (behebt 11.2.4). Ohne keep_page wie bisher:
    JumpObject auf das eigene Objekt.
    start = Index, an dem PlayPL im Objekt steht.
    """
    if not keep_page:
        return [cmd_play_playlist(playlist_id), cmd_jump_object(object_id)]
    return [
        cmd_play_playlist(playlist_id),
        cmd_copy_gpr(GPR_MENU_PAGE, PSR_MENU_PAGE),
        cmd_copy_gpr(GPR_MENU_BUTTON, PSR_SELECTED_BUTTON),
        cmd_compare_gpr(CMP_EQ, GPR_MENU_BUTTON, NO_BUTTON), cmd_move_gpr(GPR_MENU_BUTTON, 0),
        cmd_goto(start),
    ]


def cmd_set_output_mode(mode: int = 1) -> bytes:
    """
    Erzeugt den BD-ROM Profile 5.0 HDMV Befehl SetOutputMode(mode):
    - mode = 0: 2D Output Mode
    - mode = 1: Stereoscopic 3D Output Mode
    Opcode: 0x31 80 00 0A (12 Bytes)
    Schaltet den HDMI-Transmitter des Hardware-Players aktiv in den 3D Frame-Packing Modus.
    """
    return make_hdmv_cmd(
        op_cnt=1,
        grp=INSN_GROUP_SET,
        sub_grp=SET_SUBGRP_SETSYSTEM,
        imm_op1=1,
        imm_op2=0,
        branch_opt=0,
        cmp_opt=0,
        set_opt=INSN_SET_OUTPUT_MODE,
        dst=mode,
        src=0
    )

def cmd_move_gpr(register: int, value: int) -> bytes:
    """Move GPR[register] = value (fester Wert)."""
    return make_hdmv_cmd(op_cnt=2, grp=INSN_GROUP_SET, sub_grp=SET_SUBGRP_SET, imm_op1=0, imm_op2=1,
                         set_opt=INSN_MOVE, dst=register, src=value)

def cmd_copy_gpr(register: int, source_register: int) -> bytes:
    """Move GPR[register] = GPR[source_register]."""
    return make_hdmv_cmd(op_cnt=2, grp=INSN_GROUP_SET, sub_grp=SET_SUBGRP_SET, imm_op1=0, imm_op2=0,
                         set_opt=INSN_MOVE, dst=register, src=source_register)

def cmd_and_gpr(register: int, value: int) -> bytes:
    """And GPR[register] &= value (fester Wert)."""
    return make_hdmv_cmd(op_cnt=2, grp=INSN_GROUP_SET, sub_grp=SET_SUBGRP_SET, imm_op1=0, imm_op2=1,
                         set_opt=INSN_AND, dst=register, src=value)

def cmd_shift_right_gpr(register: int, bits: int) -> bytes:
    """ShiftR GPR[register] >>= bits."""
    return make_hdmv_cmd(op_cnt=2, grp=INSN_GROUP_SET, sub_grp=SET_SUBGRP_SET, imm_op1=0, imm_op2=1,
                         set_opt=INSN_SHIFT_RIGHT, dst=register, src=bits)

def menu_capture_commands() -> List[bytes]:
    """
    Anfang des TopMenu-Objekts bei Discs mit Sprachmenü: Lief zuvor ein Film (GPR_FILM_PLAYED), werden dessen
    aktuelle Ton- und Untertitelspur als Wahl übernommen. Eine im Film per Fernbedienung gewählte Spur gilt so
    beim nächsten Start weiter (Move GPR = PSR1 beim Menüeintritt).
    Ohne vorherigen Film (Disc eingelegt, Menü-Schleife) bleibt alles unverändert, auch die Player-Voreinstellung.
    Die Befehle stehen vor PlayPL(0); das Objekt beginnt danach mit Index len(...) = PlayPL.
    """
    skip_to = 10
    cmds = [cmd_compare_gpr(CMP_NE, GPR_FILM_PLAYED, 1), cmd_goto(skip_to)] + stream_capture_commands()
    assert len(cmds) == skip_to
    return cmds


def stream_capture_commands() -> List[bytes]:
    """Aktuelle Ton- und Untertitelspur als Wahl übernehmen (Kern von menu_capture_commands). Steht ab v1.18 auch
    am Ende eines Films, der in einem anderen Menü als dem Hauptmenü endet: Nur das TopMenu-Objekt übernimmt die
    Spuren beim Menüeintritt, und bis dahin hat die Menü-Playlist die Spur-Register schon umgestellt."""
    return [
        cmd_move_gpr(GPR_FILM_PLAYED, 0),
        cmd_copy_gpr(GPR_AUDIO, PSR_PRIMARY_AUDIO),
        cmd_copy_gpr(GPR_SUBTITLE, PSR_PG_STREAM), cmd_and_gpr(GPR_SUBTITLE, 0x0FFF),
        # Anzeige-Flag (Bit 31) -> 1 = an (SUB_ON), 0 -> SUB_OFF
        cmd_copy_gpr(GPR_SUBTITLE_MODE, PSR_PG_STREAM), cmd_shift_right_gpr(GPR_SUBTITLE_MODE, 31),
        cmd_compare_gpr(CMP_EQ, GPR_SUBTITLE_MODE, 0), cmd_move_gpr(GPR_SUBTITLE_MODE, SUB_OFF),
    ]

def cmd_sub_gpr(register: int, value: int) -> bytes:
    """Sub GPR[register] -= value (fester Wert, nicht unter 0)."""
    return make_hdmv_cmd(op_cnt=2, grp=INSN_GROUP_SET, sub_grp=SET_SUBGRP_SET, imm_op1=0, imm_op2=1,
                         set_opt=INSN_SUB, dst=register, src=value)

def cmd_compare_gpr(cmp_opt: int, register: int, value: int) -> bytes:
    """Vergleich GPR[register] mit festem Wert; ist er falsch, überspringt der Player den nächsten Befehl."""
    return make_hdmv_cmd(op_cnt=2, grp=INSN_GROUP_CMP, sub_grp=0, imm_op1=0, imm_op2=1,
                         branch_opt=0, cmp_opt=cmp_opt, dst=register, src=value)

def cmd_goto(command_index: int) -> bytes:
    """Goto: weiter mit Befehl command_index (0-basiert) im selben MovieObject."""
    return make_hdmv_cmd(op_cnt=1, grp=INSN_GROUP_BRANCH, sub_grp=BRANCH_GOTO, imm_op1=1,
                         branch_opt=1, dst=command_index, src=0)

def cmd_play_playlist_at_mark_register(playlist_id: int, mark_register: int) -> bytes:
    """PlayPLatPM(playlist_id, GPR[mark_register]): Marke aus einem Register."""
    return make_hdmv_cmd(op_cnt=2, grp=INSN_GROUP_BRANCH, sub_grp=BRANCH_PLAY, imm_op1=1, imm_op2=0,
                         branch_opt=INSN_PLAY_PL_PM, dst=playlist_id, src=mark_register)

def cmd_set_audio_from_register(register: int) -> bytes:
    """SetStream(Ton = GPR[register]). Bei Register-Operanden stammen die Flags aus dem Befehl,
    die Spurnummer aus dem Register, dessen Nummer in Bits 27..16 steht.
    Beispiel: 51 40 00 01 80 CD 00 00 00 00 00 00 für GPR 205."""
    return make_hdmv_cmd(op_cnt=2, grp=INSN_GROUP_SET, sub_grp=SET_SUBGRP_SETSYSTEM, imm_op1=0, imm_op2=1,
                         set_opt=INSN_SET_STREAM, dst=0x80000000 | ((register & 0xFFF) << 16), src=0)

def cmd_show_subtitle_from_register(register: int) -> bytes:
    """SetStream(Untertitel = GPR[register], an); Registernummer in Bits 11..0."""
    return make_hdmv_cmd(op_cnt=2, grp=INSN_GROUP_SET, sub_grp=SET_SUBGRP_SETSYSTEM, imm_op1=0, imm_op2=1,
                         set_opt=INSN_SET_STREAM, dst=0x0000C000 | (register & 0xFFF), src=0)

def play_mode_commands(play_2d: bool) -> List[bytes]:
    """Button, der einen 3D-Film startet, auf einer Disc mit 2D-Wahl (v1.20): 3D oder 2D merken. Kapitel,
    Film → Film und Top Menu behalten die zuletzt gemerkte Wahl."""
    return [cmd_move_gpr(GPR_PLAY_2D, 1 if play_2d else 0)]

def chapter_jump_commands(title_id: int, mark_id: int) -> List[bytes]:
    """Befehle eines Kapitel-Buttons: Kapitelwunsch merken, Film als Titel starten.
    JumpTitle verwirft eine frühere Unterbrechung (Top Menu); JumpObject tat das nicht."""
    return [cmd_move_gpr(GPR_CHAPTER, mark_id + 1), cmd_jump_title(title_id)]

def stream_choice_commands(audio_id: Optional[int] = None, subtitle_id: Optional[int] = None,
                           subtitle_on: Optional[bool] = None) -> List[bytes]:
    """Befehle eines Ton-/Untertitel-Buttons: nur die Wahl merken; umgeschaltet wird beim Filmstart."""
    cmds = []
    if audio_id is not None:
        cmds.append(cmd_move_gpr(GPR_AUDIO, audio_id))
    if subtitle_id is not None:
        cmds.append(cmd_move_gpr(GPR_SUBTITLE, subtitle_id))
    if subtitle_on is True or (subtitle_on is None and subtitle_id is not None):
        cmds.append(cmd_move_gpr(GPR_SUBTITLE_MODE, SUB_ON))
    elif subtitle_on is False:
        cmds.append(cmd_move_gpr(GPR_SUBTITLE_MODE, SUB_OFF))
    return cmds

def title_commands(title: int, is_3d: bool, with_chapters: bool = False, with_streams: bool = False,
                   end_commands: Optional[List[bytes]] = None, stay_3d: bool = False,
                   with_2d_choice: bool = False) -> List[bytes]:
    """
    Befehle des MovieObjects eines Titels:
    - with_streams: gemerkte Ton-/Untertitelwahl vor dem Abspielen umsetzen (keine Menü-Playlist läuft mehr)
    - with_chapters: gemerkten Kapitelwunsch auswerten und zurücksetzen; sonst von vorn
    - end_commands (v1.18): Filmende woanders als im Hauptmenü (film_end_commands, ab v1.18.1 auch JumpTitle in
      den nächsten Film); mit with_streams werden die Spuren vorher gesichert (stream_capture_commands), damit eine
      im Film gewählte Spur auch im nächsten Film gilt
    - stay_3d (v1.18.1): 3D-Film, nach dem ein 3D-Film folgt – kein Umschalten auf 2D dazwischen
    - with_2d_choice (v1.20): 3D-Film auf einer Disc mit 2D-Wahl – GPR 16 = 1 schaltet aktiv auf 2D statt 3D
      (output_choice_commands); auf 2D-Fernsehern ändert das nichts
    Ohne die Optionen unverändert: [SetOutputMode(1)], PlayPL(t), [SetOutputMode(0)], JumpObject(1).
    """
    cmds: List[bytes] = []
    if is_3d and with_2d_choice:
        cmds += output_choice_commands(0)
    elif is_3d:
        cmds += output_mode_commands(1)      # HDMI-Transmitter vor dem Start auf 3D (nur 3D-Player)
    if with_streams:
        cmds.append(cmd_move_gpr(GPR_FILM_PLAYED, 1))   # Menü übernimmt beim Zurückkehren die aktuellen Spuren
        cmds += [
            cmd_compare_gpr(CMP_NE, GPR_AUDIO, 0), cmd_set_audio_from_register(GPR_AUDIO),
            cmd_compare_gpr(CMP_EQ, GPR_SUBTITLE_MODE, SUB_ON), cmd_show_subtitle_from_register(GPR_SUBTITLE),
            # Aus: Spur 1 mit ausgeschalteter Anzeige (eine gültige Spurnummer, falls der Player sie prüft)
            cmd_compare_gpr(CMP_EQ, GPR_SUBTITLE_MODE, SUB_OFF), cmd_set_stream(subtitle_id=1, subtitle_on=False),
        ]
    if with_chapters:
        start = len(cmds)
        chapter_at, end_at = start + 4, start + 8
        cmds += [
            cmd_compare_gpr(CMP_NE, GPR_CHAPTER, 0), cmd_goto(chapter_at),
            cmd_play_playlist(title), cmd_goto(end_at),
            cmd_copy_gpr(GPR_SCRATCH, GPR_CHAPTER), cmd_sub_gpr(GPR_SCRATCH, 1),
            cmd_move_gpr(GPR_CHAPTER, 0), cmd_play_playlist_at_mark_register(title, GPR_SCRATCH),
        ]
    else:
        cmds.append(cmd_play_playlist(title))
    if is_3d and not stay_3d:
        cmds += output_mode_commands(0)      # Nach Filmende zurück ins 2D-Menü
    if end_commands:
        if with_streams:
            cmds += stream_capture_commands()
        return cmds + list(end_commands)
    cmds.append(cmd_jump_object(1))          # Nach Filmende: zurück ins TopMenu
    return cmds

def output_mode_commands(mode: int) -> List[bytes]:
    """
    SetOutputMode nur auf Playern mit 3D-Profil (Profil 5):
    Move GPR6 = PSR31, And GPR6 & 0x130240, EQ GPR6 == 0x130240 -> SetOutputMode(mode).
    Ältere Player kennen SetOutputMode nicht (libbluray bricht bei unbekannten Befehlen ab); mit der
    Prüfung überspringen sie ihn und spielen das linke Bild in 2D.
    """
    return [
        cmd_copy_gpr(GPR_PROFILE, PSR_PROFILE_VERSION),
        cmd_and_gpr(GPR_PROFILE, PROFILE_5_3D),
        cmd_compare_gpr(CMP_EQ, GPR_PROFILE, PROFILE_5_3D),
        cmd_set_output_mode(mode),
    ]

def output_choice_commands(start: int) -> List[bytes]:
    """
    3D oder 2D nach GPR 16 (v1.20), ab Befehl start im Titel-Objekt:
    EQ GPR16 == 1 → Goto 2D · [SetOutputMode(1)] · Goto weiter · 2D: [SetOutputMode(0)] · weiter.
    Aktiv auf 2D statt nur ohne Umschaltung: Bei 3D-Discs kann der Player schon nach dem Einlegen in 3D stehen
    (index.bdmv, initial_output_mode_preference). Beide Zweige mit 3D-Profilprüfung (output_mode_commands).
    """
    to_2d = start + 3 + len(output_mode_commands(1))
    after = to_2d + len(output_mode_commands(0))
    return ([cmd_compare_gpr(CMP_EQ, GPR_PLAY_2D, 1), cmd_goto(to_2d)] + output_mode_commands(1) +
            [cmd_goto(after)] + output_mode_commands(0))

FLAGS_RESUME = 0x8000          # resume_intention (Standard, tsMuxeR)
FLAGS_MENU_NO_RESUME = 0x6000  # menu_call_mask + title_search_mask, ohne resume_intention (Konzept 11.2.5)


class MovieObject:
    """Repräsentiert ein einzelnes MovieObject mit Steuerungsbefehlen."""
    def __init__(self, commands: List[bytes] = None, flags: int = FLAGS_RESUME):
        self.commands: List[bytes] = commands or []
        self.flags = flags

    def to_bytes(self) -> bytes:
        data = bytearray()
        # Flags (16 bits): resume_intention (1b), menu_call_mask (1b), title_search_mask (1b), reserved (13b)
        # 0x8000 setzt resume_intention = 1 (Standard nach BD-ROM Part 3 / tsMuxeR)
        data.extend(struct.pack(">H", self.flags))
        # num_cmds (uint16)
        data.extend(struct.pack(">H", len(self.commands)))
        for cmd in self.commands:
            if len(cmd) != 12:
                raise ValueError("HDMV Command muss exakt 12 Bytes lang sein.")
            data.extend(cmd)
        return bytes(data)

def build_standard_movie_objects(
    num_titles: int = 1,
    auto_play_movie_after_menu: bool = False,
    titles_3d: Optional[List[int]] = None,
    has_3d: bool = False,
    chapter_titles: Optional[List[int]] = None,
    stream_titles: Optional[List[int]] = None,
    menu_groups: Optional[List[tuple]] = None,
    menu_resume: bool = True,
    title_ends: Optional[Dict[int, object]] = None,
    first_play_title: Optional[int] = None,
    with_2d_choice: bool = False
) -> bytes:
    """
    menu_groups (v1.13): [(Playlist, keep_page)] je Menügruppe, Gruppe 0 = Menü-Playlist 0 im TopMenu-Objekt 1,
    weitere Gruppen bekommen Menü-Objekte hinter den Titeln (N+2 …). keep_page: Gruppe mit Startseite – die
    Schleife merkt sich Seite und Button (menu_loop_commands), First Play springt direkt ins TopMenu.
    menu_resume=False: Menü-Objekte ohne resume_intention, mit menu_call_mask und title_search_mask
    (Test-Disc B zu 11.2.5).
    title_ends (v1.18): {Titel: film_end_commands(...)} für Filme, die nicht im Hauptmenü enden; ab v1.18.1 statt
    der Befehle auch die Nummer des Titels, der danach startet (JumpTitle, zwischen zwei 3D-Filmen ohne 2D).
    first_play_title (v1.18.1): First Play startet diesen Titel statt des Menüs (z. B. Trailer vor dem Menü).
    with_2d_choice (v1.20): Disc mit 2D-Wahl – alle 3D-Titel schalten nach GPR 16 auf 3D oder 2D.
    Ohne diese Angaben byte-gleich wie bisher.

    Erzeugt MovieObject.bdmv mit Standard-Navigation nach BD-ROM Part 3:
    - MovieObject 0 (FirstPlayback / Bootstrap):
      Startet Menü-Playlist direkt (00000.mpls).
    - MovieObject 1 (TopMenu / Menü):
      Spielt Menü-Playlist PlayPL(0) ab und loopt im TopMenu.
    - MovieObject 2..N+1 (Titel 1..N / Hauptfilm & Extras), siehe title_commands():
      Spielt PlayPL(1..N); vor 3D-Playlists wird SetOutputMode(1) aufgerufen.
      Titel in chapter_titles werten den Kapitelwunsch aus (GPR_CHAPTER), Titel in stream_titles
      setzen die im Menü gewählte Ton-/Untertitelspur vor dem Start.
      Nach Filmende automatischer Rücksprung ins TopMenu via JumpObject(1).
    """
    if titles_3d is None:
        titles_3d = [1] if has_3d else []

    chapter_titles = set(chapter_titles or [])
    stream_titles = set(stream_titles or [])
    menu_groups = list(menu_groups or [(0, False)])
    keep_main = bool(menu_groups[0][1])
    menu_flags = FLAGS_RESUME if menu_resume else FLAGS_MENU_NO_RESUME

    objects: List[MovieObject] = []

    # Object 0: FirstPlayback (Startet Menü-Playlist direkt, ohne illegales JumpTitle(0)!)
    if auto_play_movie_after_menu:
        first_pb_cmds = [
            cmd_play_playlist(0),  # Spielt Hintergrundvideo / Intro
        ]
        if 1 in titles_3d:
            first_pb_cmds += output_mode_commands(1)
        first_pb_cmds.append(cmd_jump_title(1))      # startet den Hauptfilm (Title 1)
    elif first_play_title:
        first_pb_cmds = [cmd_jump_title(first_play_title)]   # Film vor dem Menü (v1.18.1); 3D schaltet der Titel
    elif keep_main:
        first_pb_cmds = [cmd_jump_object(1)]   # das TopMenu spielt das Menü und merkt sich die Seite (v1.13)
    else:
        first_pb_cmds = [
            cmd_play_playlist(0),  # Spielt Menü-Playlist 00000.mpls mit IGS
            cmd_jump_object(1)     # Geht bei Ende ins TopMenu (MovieObject 1)
        ]
    objects.append(MovieObject(first_pb_cmds, menu_flags))

    # Object 1: TopMenu (Interaktives Menü)
    if auto_play_movie_after_menu:
        menu_cmds = [
            cmd_play_playlist(0),  # Spielt Hintergrundvideo / Intro
        ]
        if 1 in titles_3d:
            menu_cmds += output_mode_commands(1)
        menu_cmds.append(cmd_jump_title(1))      # startet den Hauptfilm (Title 1)
    else:
        # Mit Sprachmenü: zuerst die Spuren des zuletzt gelaufenen Films übernehmen (siehe menu_capture_commands)
        menu_cmds = menu_capture_commands() if stream_titles else []
        # Spielt Menü-Playlist 00000.mpls mit IGS und loopt im TopMenu (MovieObject 1)
        menu_cmds += menu_loop_commands(0, len(menu_cmds), keep_main, 1)
    objects.append(MovieObject(menu_cmds, menu_flags))

    # Object 2..N+1: Titel 1..N (Filme & Episoden)
    title_ends = title_ends or {}
    for t in range(1, num_titles + 1):
        end = title_ends.get(t)
        stay_3d = isinstance(end, int) and t in titles_3d and end in titles_3d
        if isinstance(end, int):
            end = [cmd_jump_title(end)]
        objects.append(MovieObject(title_commands(t, t in titles_3d, t in chapter_titles, t in stream_titles,
                                                  end, stay_3d, with_2d_choice)))

    # Object N+2 …: weitere Menügruppen mit eigenem Hintergrund (v1.13)
    for k, (playlist_id, keep_page) in enumerate(menu_groups[1:], start=1):
        object_id = menu_group_object(num_titles, k)
        objects.append(MovieObject(menu_loop_commands(playlist_id, 0, keep_page, object_id), menu_flags))

    # MovieObjects Payload zusammenbauen
    mobj_body = bytearray()
    mobj_body.extend(struct.pack(">H", len(objects))) # num_objects
    for obj in objects:
        mobj_body.extend(obj.to_bytes())

    # Header an Offset 40: data_len (uint32) + reserved (uint32) + mobj_body
    # data_len ist Länge von reserved(4B) + num_objects(2B) + body
    data_len = 4 + len(mobj_body)
    mobj_payload = struct.pack(">II", data_len, 0) + bytes(mobj_body)

    # File Header (40 Bytes)
    header = bytearray()
    header.extend(b"MOBJ0200")
    header.extend(struct.pack(">I", 0)) # extension_data_start = 0
    header.extend(b"\x00" * 28) # 28 Bytes Reserved

    return bytes(header) + mobj_payload

def menu_group_object(num_titles: int, group: int) -> int:
    """MovieObject einer Menügruppe: Gruppe 0 = TopMenu (1), Gruppe k ≥ 1 hinter den Titeln (N + 1 + k)."""
    return 1 if group == 0 else num_titles + 1 + group


def menu_group_playlist(num_titles: int, group: int) -> int:
    """Menü-Playlist einer Gruppe: Gruppe 0 = 00000.mpls, Gruppe k ≥ 1 hinter den Titeln (N + k)."""
    return 0 if group == 0 else num_titles + group


def write_movie_object_file(
    output_path: str,
    num_titles: int = 1,
    auto_play_movie_after_menu: bool = False,
    titles_3d: Optional[List[int]] = None,
    has_3d: bool = False,
    chapter_titles: Optional[List[int]] = None,
    stream_titles: Optional[List[int]] = None,
    menu_groups: Optional[List[tuple]] = None,
    menu_resume: bool = True,
    title_ends: Optional[Dict[int, object]] = None,
    first_play_title: Optional[int] = None,
    with_2d_choice: bool = False
):
    """Schreibt die MovieObject.bdmv Datei."""
    mobj_bytes = build_standard_movie_objects(
        num_titles=num_titles,
        auto_play_movie_after_menu=auto_play_movie_after_menu,
        titles_3d=titles_3d,
        has_3d=has_3d,
        chapter_titles=chapter_titles,
        stream_titles=stream_titles,
        menu_groups=menu_groups,
        menu_resume=menu_resume,
        title_ends=title_ends,
        first_play_title=first_play_title,
        with_2d_choice=with_2d_choice
    )
    with open(output_path, "wb") as f:
        f.write(mobj_bytes)
