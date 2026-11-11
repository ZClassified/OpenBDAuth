# modules/burn/checks.py
"""
Prüfung vor dem Brennen (wie der Preflight des Exports): Fehler sperren „Brennen“, Warnungen fragen nach.
Die Meldungen sind Schlüssel für core/translations.py; die Oberfläche übersetzt sie.
"""

from dataclasses import dataclass, field
from typing import List, Optional

from modules.burn.iso_info import IsoInfo
from modules.burn.model import Drive, Media

ERROR, WARNING = "error", "warning"


@dataclass
class BurnIssue:
    level: str
    key: str
    args: dict = field(default_factory=dict)


def _gb(n: int) -> str:
    return f"{n / 1e9:.2f}"


def check_burn(iso: Optional[IsoInfo], drive: Optional[Drive], media: Optional[Media],
               iso_error: Optional[str] = None) -> List[BurnIssue]:
    issues: List[BurnIssue] = []
    if iso_error:
        issues.append(BurnIssue(ERROR, "burn_err_iso_unreadable", {"err": iso_error}))
    elif iso is None:
        issues.append(BurnIssue(ERROR, "burn_err_no_iso"))
    if drive is None:
        issues.append(BurnIssue(ERROR, "burn_err_no_drive"))
        return issues
    if drive.can_write_bd is False:
        issues.append(BurnIssue(ERROR, "burn_err_drive_no_bd", {"drive": drive.name}))
        return issues
    if media is None or not media.present:
        issues.append(BurnIssue(ERROR, "burn_err_no_media"))
        return issues
    if media.busy:
        issues.append(BurnIssue(ERROR, "burn_err_media_busy"))
        return issues
    if not media.is_bd:
        issues.append(BurnIssue(ERROR, "burn_err_not_bd", {"kind": media.kind or media.media_class or "?"}))
        return issues
    if not media.writable:
        issues.append(BurnIssue(ERROR, "burn_err_not_writable", {"kind": media.kind}))
        return issues
    if iso is not None and iso.size > media.capacity_bytes:
        issues.append(BurnIssue(ERROR, "burn_err_too_large",
                                {"size": _gb(iso.size), "free": _gb(media.capacity_bytes)}))
    if media.needs_erase:
        issues.append(BurnIssue(WARNING, "burn_warn_erase"))
    if iso is not None and not iso.has_bdmv:
        issues.append(BurnIssue(WARNING, "burn_warn_no_bdmv"))
    return issues


def has_errors(issues: List[BurnIssue]) -> bool:
    return any(i.level == ERROR for i in issues)
