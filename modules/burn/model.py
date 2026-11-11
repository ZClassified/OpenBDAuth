# modules/burn/model.py
"""
Gemeinsame Datenklassen für den Arbeitsbereich Brennen (Plan docs/plaene/brennen.md).

Gebrannt wird immer eine fertige ISO, Sektor für Sektor. Die Backends (je System eines) kennen Laufwerke und
Medien und rufen den Brenner des Systems auf; Dateisystem und 3D-Interleaving kommen nur aus unserer UDF-Engine.
"""

from dataclasses import dataclass, field
from typing import List, Optional

SECTOR = 2048

# Phasen eines Brennvorgangs (Anzeige, Abbrechen, Fehlermeldung)
PHASE_PREPARE, PHASE_ERASE, PHASE_WRITE, PHASE_VERIFY, PHASE_EJECT = "prepare", "erase", "write", "verify", "eject"

SPEED_AUTO = ""          # das Laufwerk wählt (hdiutil: max)


class BurnError(Exception):
    """Brennen fehlgeschlagen. phase: in welcher Phase (PHASE_*)."""

    def __init__(self, message: str, phase: str = PHASE_WRITE):
        super().__init__(message)
        self.phase = phase


class BurnCancelled(Exception):
    """Abgebrochen. phase: in welcher Phase."""

    def __init__(self, phase: str = PHASE_PREPARE):
        super().__init__(phase)
        self.phase = phase


@dataclass
class Drive:
    key: str                         # eindeutig je Sitzung, z. B. „1“ (drutil-Index)
    name: str                        # Hersteller und Modell
    can_write_bd: Optional[bool] = None   # None = unbekannt
    device: str = ""                 # Kennung für den Brenner des Systems (z. B. IOService-Pfad)
    interconnect: str = ""           # USB, SATA …


@dataclass
class Media:
    present: bool = False
    media_class: str = ""            # BD, DVD, CD
    kind: str = ""                   # BD-R, BD-RE, BD-ROM, DVD+R …
    blank: bool = False
    appendable: bool = False
    erasable: bool = False
    overwritable: bool = False
    busy: bool = False               # Medium wird gerade erkannt oder ist belegt
    free_blocks: int = 0
    used_blocks: int = 0
    overwritable_blocks: int = 0
    speeds: List[str] = field(default_factory=list)   # z. B. ["2x", "4x"]
    status: str = ""                 # Beschreibung des Systems, z. B. „Finalized Disc“

    @property
    def is_bd(self) -> bool:
        return self.media_class.upper() == "BD" or self.kind.upper().startswith("BD")

    @property
    def is_rewritable(self) -> bool:
        return self.erasable or self.kind.upper().startswith("BD-RE")

    @property
    def needs_erase(self) -> bool:
        """BD-RE mit Daten: vor dem Brennen löschen."""
        return self.is_rewritable and not self.blank

    @property
    def writable(self) -> bool:
        """Leer oder löschbar (eine BD-R mit Daten lässt sich nicht mehr ganz beschreiben)."""
        return self.blank or self.is_rewritable

    @property
    def capacity_bytes(self) -> int:
        """Platz für die ISO: bei löschbaren Medien die ganze Disc, sonst der freie Platz."""
        blocks = self.free_blocks
        if self.is_rewritable:
            blocks = max(blocks, self.free_blocks + self.used_blocks, self.overwritable_blocks)
        return blocks * SECTOR


@dataclass
class BurnOptions:
    speed: str = SPEED_AUTO          # "" oder z. B. "4x"
    verify: bool = False             # Disc nach dem Brennen prüfen (Vorgabe aus, Plan)
    erase: bool = False              # BD-RE vorher löschen (bestätigt)


@dataclass
class BurnResult:
    verified: bool = False
