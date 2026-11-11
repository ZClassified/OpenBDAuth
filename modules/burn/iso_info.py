# modules/burn/iso_info.py
"""
Angaben zu einer ISO für den Bereich Brennen, ohne sie einzuhängen: Größe, Disc-Titel, ob ein BDMV-Ordner darin
ist und ob die Disc 3D (SSIF) enthält.

- Disc-Titel: aus dem UDF Logical Volume Descriptor (sonst Primary Volume Descriptor), gefunden über den Anker
  bei Sektor 256.
- BDMV und SSIF: Die Verzeichniseinträge (File Identifier Descriptors) liegen bei Blu-ray-ISOs am Anfang (UDF-2.50-
  Metadaten). Gesucht wird in den ersten SCAN_BYTES. Wird nichts gefunden, ist das nur ein Hinweis, kein Fehler.
"""

import os
from dataclasses import dataclass
from typing import Optional

from modules.burn.model import SECTOR

BD25_BYTES = 12_219_392 * SECTOR
BD50_BYTES = 24_438_784 * SECTOR
SCAN_BYTES = 64 * 1024 * 1024
ANCHOR_SECTOR = 256
TAG_AVDP, TAG_PVD, TAG_LVD, TAG_FID = 2, 1, 6, 257


@dataclass
class IsoInfo:
    path: str
    size: int
    label: Optional[str] = None      # None: kein UDF gefunden
    has_bdmv: bool = False
    is_3d: bool = False

    @property
    def udf(self) -> bool:
        return self.label is not None

    @property
    def fits(self) -> str:
        """bd25, bd50 oder too_large."""
        if self.size <= BD25_BYTES:
            return "bd25"
        return "bd50" if self.size <= BD50_BYTES else "too_large"


def _u16(data: bytes, pos: int) -> int:
    return int.from_bytes(data[pos:pos + 2], "little")


def _u32(data: bytes, pos: int) -> int:
    return int.from_bytes(data[pos:pos + 4], "little")


def decode_dstring(data: bytes) -> str:
    """UDF dstring: erstes Byte Kodierung (8 = 1 Byte je Zeichen, 16 = UTF-16BE), letztes Byte Länge."""
    if not data:
        return ""
    used = data[-1]
    if data[0] not in (8, 16) or used < 1 or used > len(data) - 1:
        return ""
    raw = data[1:used]
    return raw.decode("utf-16-be", "replace") if data[0] == 16 else raw.decode("latin-1")


def _read_sector(f, sector: int) -> bytes:
    f.seek(sector * SECTOR)
    return f.read(SECTOR)


def read_label(f) -> Optional[str]:
    """Disc-Titel aus der Volume Descriptor Sequence; None ohne UDF-Anker."""
    anchor = _read_sector(f, ANCHOR_SECTOR)
    if len(anchor) < 24 or _u16(anchor, 0) != TAG_AVDP:
        return None
    length, location = _u32(anchor, 16), _u32(anchor, 20)
    pvd_label = lvd_label = None
    for i in range(min(length // SECTOR, 64)):
        desc = _read_sector(f, location + i)
        if len(desc) < 16:
            break
        tag = _u16(desc, 0)
        if tag == TAG_PVD and pvd_label is None:
            pvd_label = decode_dstring(desc[24:24 + 32])
        elif tag == TAG_LVD and lvd_label is None:
            lvd_label = decode_dstring(desc[84:84 + 128])
        elif tag == 8:           # Terminating Descriptor
            break
    return lvd_label or pvd_label or ""


def has_directory(data: bytes, name: str) -> bool:
    """Gibt es einen File Identifier Descriptor mit diesem Namen (Kodierung 8)?"""
    needle = bytes([8]) + name.encode("latin-1")
    name_len = len(needle)
    pos = data.find(needle)
    while pos >= 0:
        # FID: Tag (16), Version (2), Merkmale (1), L_FI (1, Pos. 19), ICB (16), L_IU (2, Pos. 36), Name ab 38 + L_IU
        for start in range(max(0, pos - 38 - 64), pos - 37):
            if (_u16(data, start) == TAG_FID and data[start + 19] == name_len
                    and start + 38 + _u16(data, start + 36) == pos):
                return True
        pos = data.find(needle, pos + 1)
    return False


def read_iso_info(path: str) -> IsoInfo:
    """Liest die Angaben; OSError, wenn die Datei nicht lesbar ist."""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        label = read_label(f)
        f.seek(0)
        head = f.read(min(size, SCAN_BYTES))
    return IsoInfo(path=path, size=size, label=label, has_bdmv=has_directory(head, "BDMV"),
                   is_3d=has_directory(head, "SSIF"))
