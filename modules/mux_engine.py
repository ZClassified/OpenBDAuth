# modules/mux_engine.py
import os

def find_tsmuxer() -> str | None:
    """tsMuxeR suchen: tools/<plattform>/, tools/, PATH (modules/external_tools.py, ab v1.19.1)."""
    from modules.external_tools import find_tool, TSMUXER
    return find_tool(TSMUXER)


def fix_1080i_stream_attributes(bdmv_dir: str) -> int:
    """
    Korrigiert tsMuxeR 1080i Video-Attribut-Bytes in CLPI und MPLS auf standardkonforme Werte:
    tsMuxeR schreibt bei fps=50 den Code 0x46 (1080i @ 50fps) und bei fps=59.94 den Code 0x47.
    Der offizielle BD-ROM Part 3 Standard definiert 1080i jedoch ausschließlich als:
    - 0x43 (1080i @ 25fps / 50 Felder/s)
    - 0x44 (1080i @ 29.97fps / 59.94 Felder/s)
    
    Diese Funktion durchsucht BDMV/CLIPINF und BDMV/PLAYLIST (inkl. BACKUP) und patcht
    die Stream-Attribute atomar.
    Gibt die Anzahl der durchgeführten Korrekturen zurück.
    """
    if not os.path.exists(bdmv_dir):
        return 0

    # Unterstütze Übergabe von dest-Verzeichnis oder direktem BDMV-Verzeichnis
    if os.path.basename(os.path.normpath(bdmv_dir)).upper() != "BDMV":
        sub_bdmv = os.path.join(bdmv_dir, "BDMV")
        if os.path.isdir(sub_bdmv):
            bdmv_dir = sub_bdmv

    patched_count = 0
    replacements = [
        (b"\x1b\x46", b"\x1b\x43"),  # H.264 1080i: 50 -> 25
        (b"\x1b\x47", b"\x1b\x44"),  # H.264 1080i: 59.94 -> 29.97
    ]

    for sub in ["", "BACKUP"]:
        base_dir = os.path.join(bdmv_dir, sub) if sub else bdmv_dir
        for folder_name in ["CLIPINF", "PLAYLIST"]:
            target_dir = os.path.join(base_dir, folder_name)
            if not os.path.isdir(target_dir):
                continue
            for fname in os.listdir(target_dir):
                fpath = os.path.join(target_dir, fname)
                if not os.path.isfile(fpath):
                    continue
                ext = fname.lower()
                if not (ext.endswith(".clpi") or ext.endswith(".mpls")):
                    continue

                try:
                    with open(fpath, "rb") as f:
                        data = bytearray(f.read())

                    modified = False
                    for pattern, repl in replacements:
                        idx = 0
                        while True:
                            pos = data.find(pattern, idx)
                            if pos == -1:
                                break
                            data[pos:pos + len(pattern)] = repl
                            modified = True
                            patched_count += 1
                            idx = pos + len(pattern)

                    if modified:
                        with open(fpath, "wb") as f:
                            f.write(data)
                except Exception as ex:
                    print(f"Warnung: Fehler beim Patchen der Header in {fname}: {ex}")

    return patched_count

