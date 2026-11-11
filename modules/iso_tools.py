# modules/iso_tools.py
"""
Werkzeuge zur Erstellung standardkonformer Blu-ray UDF 2.50 ISO-Images.
Nutzt die native Python UDF 2.50 Master Engine mit Unterstützung für
physikalisches 3D SSIF Extent-Interleaving (auf allen Systemen gleich).
"""

import re
from typing import Optional, List, Dict, Callable


def sanitize_volume_label(name: str) -> str:
    """
    Bereinigt den Disc-Namen für UDF 2.50 (max. 30 Zeichen, ASCII/Alphanumerisch, keine Sonderzeichen).
    """
    if not name:
        return "BD_DISC"
    cleaned = re.sub(r'[^A-Za-z0-9_]', '', name.strip().replace(' ', '_'))
    return cleaned[:30] if cleaned else "BD_DISC"


def create_udf_iso(
    source_dir: str,
    iso_path: str,
    volume_label: str = "BD_DISC",
    interleaved_3d_streams: Optional[List[Dict]] = None,
    log_callback: Optional[Callable[[str], None]] = None
) -> bool:
    """
    Erstellt ein standardkonformes UDF 2.50 Blu-ray ISO-Image aus einem BDMV-Verzeichnis.
    Verwendet die native OpenBDAuth UDF 2.50 Engine mit Unterstützung für 3D MVC Extent-Interleaving.
    Scheitert sie, gibt es keinen Ausweg über ein anderes Werkzeug (bis v1.18.1: Windows IMAPI2FS, nie auf
    Hardware geprüft und hat zweimal Fehler verdeckt, Konzept 11.2.6): der Export bricht mit der Meldung ab.

    :param source_dir: Ordner, der BDMV enthält (z. B. Zielordner des Exports)
    :param iso_path: Zieldateipfad für die .iso-Datei
    :param volume_label: Disc-Label (Name der Disc)
    :param interleaved_3d_streams: Optionale 3D Interleaving-Metadaten
    :param log_callback: Optionale Callback-Funktion für Log-Ausgaben
    :return: True bei Erfolg, False bei Fehler
    """
    from modules.udf250_writer import create_udf250_iso_from_tree
    return create_udf250_iso_from_tree(
        source_dir=source_dir,
        iso_path=iso_path,
        volume_label=sanitize_volume_label(volume_label),
        interleaved_3d_streams=interleaved_3d_streams,
        log_callback=log_callback
    )
