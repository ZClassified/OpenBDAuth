# modules/ssif_tools.py
"""
Werkzeuge für stereoskopische 3D Blu-ray Streams (MVC - Multiview Video Coding & SSIF).

Erzeugt standardkonforme 3D-Streams nach BD-ROM Part 3 / Profile 5.0:
- Muxing des 3D-Titels (Base AVC + Dependent MVC) mittels tsMuxeR zu einem temporären ISO,
  um den offiziellen Stereoscopic Interleaved File (.ssif) Stream und die exakten Extents zu generieren.
- Schnelle, native Python-Extraktion beider Transport-Streams (Basis- und MVC-Auge) und ClipInfos (.clpi)
  direkt aus dem ISO ohne PowerShell-Mounting, ohne Laufwerksbuchstaben und ohne Windows-Dateisperren.
- Bereitstellung der Interleaving-Metadaten für den UDF 2.50 Master-Engine zur Erstellung von 3D-ISOs
  mit interaktiven Menüs und physikalisch verschachtelten Sektoren.
"""

import os
import struct
import subprocess
from typing import Optional, Dict, Tuple, List

from modules.external_tools import NO_CONSOLE


class Mpls3DBytes(bytes):
    """Subklasse von bytes, die Metadaten für das 3D-Extent-Interleaving trägt."""
    title_3d_info: Dict


def _parse_tsmuxer_iso(iso_path: str) -> Tuple[bytes, bytes, bytes, List[Tuple[int, int]], List[Tuple[int, int]], int, int]:
    """
    Liest aus einem von tsMuxeR generierten temporären 3D-ISO mit reinem Python:
    - clpi0_data (Basis-ClipInfo)
    - clpi1_data (MVC-ClipInfo)
    - mpls_data (3D Playlist)
    - base_extents: Liste von (lbn, size)
    - mvc_extents: Liste von (lbn, size)
    - ssif_offset: Byte-Offset im ISO
    - ssif_len: Länge des SSIF-Streams in Bytes
    """
    with open(iso_path, 'rb') as f:
        meta_base = 320

        def read_efe(icb_lbn):
            abs_sec = meta_base + icb_lbn
            f.seek(abs_sec * 2048)
            efe = f.read(2048)
            info_len = struct.unpack('<Q', efe[56:64])[0]
            alloc_len = struct.unpack('<I', efe[212:216])[0]
            desc = efe[216:216+alloc_len]
            return info_len, desc

        def get_dir_entries(icb_lbn):
            info_len, desc = read_efe(icb_lbn)
            dir_len, dir_lbn = struct.unpack('<II', desc[:8])
            f.seek((meta_base + dir_lbn) * 2048)
            dir_data = f.read(dir_len)
            pos = 0
            entries = {}
            while pos < len(dir_data):
                tid = struct.unpack('<H', dir_data[pos:pos+2])[0]
                if tid != 257:
                    break
                fc = dir_data[pos+18]
                lfi = dir_data[pos+19]
                file_icb = struct.unpack('<I', dir_data[pos+24:pos+28])[0]
                liu = struct.unpack('<H', dir_data[pos+36:pos+38])[0]
                name = dir_data[pos+38+liu:pos+38+liu+lfi][1:].decode('latin1', errors='ignore')
                pos = ((pos + 38 + liu + lfi) + 3) & ~3
                if name:
                    entries[name] = (bool(fc & 0x02), file_icb)
            return entries

        root_entries = get_dir_entries(2)
        bdmv_icb = root_entries['BDMV'][1]
        bdmv_entries = get_dir_entries(bdmv_icb)

        clip_entries = get_dir_entries(bdmv_entries['CLIPINF'][1])
        pl_entries = get_dir_entries(bdmv_entries['PLAYLIST'][1])
        stream_entries = get_dir_entries(bdmv_entries['STREAM'][1])
        ssif_entries = get_dir_entries(stream_entries['SSIF'][1])

        def read_file_payload(icb):
            info_len, desc = read_efe(icb)
            ext_len, ext_lbn = struct.unpack('<II', desc[:8])
            f.seek((288 + ext_lbn) * 2048)
            return f.read(info_len)

        def read_extents_list(icb):
            info_len, desc = read_efe(icb)
            exts = []
            for i in range(0, len(desc), 16):
                el, ep = struct.unpack('<II', desc[i:i+8])
                exts.append((ep, el))
            return exts

        clpi0_data = read_file_payload(clip_entries['00000.clpi'][1])
        clpi1_data = read_file_payload(clip_entries['00001.clpi'][1])
        mpls_data = read_file_payload(pl_entries['00000.mpls'][1])

        base_extents = read_extents_list(stream_entries['00000.m2ts'][1])
        mvc_extents = read_extents_list(stream_entries['00001.m2ts'][1])

        ssif_len, ssif_desc = read_efe(ssif_entries['00000.ssif'][1])
        ssif_ext_len, ssif_ext_lbn = struct.unpack('<II', ssif_desc[:8])
        ssif_offset = (288 + ssif_ext_lbn) * 2048

        return clpi0_data, clpi1_data, mpls_data, base_extents, mvc_extents, ssif_offset, ssif_len


def mux_3d_title(
    tsmuxer_bin: str,
    meta_path: str,
    tmp_dir: str,
    base_clip_str: str,
    mvc_clip_str: str,
    dest_bdmv: str,
    log_callback=None
) -> Mpls3DBytes:
    """
    Muxed einen 3D-Titel (AVC + MVC) mit tsMuxeR:
    1. Erzeugt temporär ein ISO-Image im Arbeitsverzeichnis, um den standardkonformen
       SSIF-Interleave-Stream und exakte Sektor-Extents für Hardware-Player zu generieren.
    2. Extrahiert mit schnellem nativem Python (ohne Windows-Mounting):
       - ClipInfos (.clpi) für Basis- und MVC-Auge
       - Transport-Streams (.m2ts) für Basis- und MVC-Auge
    3. Hängt 3D-Interleaving-Metadaten an das Rückgabe-Objekt an, damit der UDF 2.50 Writer
       beim ISO-Export das physikalische Extent-Interleaving direkt in die Master-Disc schreibt.
    4. Gibt die Rohdaten von 00000.mpls (als Mpls3DBytes) zum Patchen zurück.
    """
    def _log(msg):
        if log_callback:
            log_callback(msg)

    stream_dir = os.path.join(dest_bdmv, "STREAM")
    clipinf_dir = os.path.join(dest_bdmv, "CLIPINF")
    ssif_dir = os.path.join(stream_dir, "SSIF")
    playlist_dir = os.path.join(dest_bdmv, "PLAYLIST")
    for d in [stream_dir, clipinf_dir, ssif_dir, playlist_dir]:
        os.makedirs(d, exist_ok=True)

    dest_root = os.path.dirname(os.path.normpath(dest_bdmv))
    tmp_iso = os.path.join(dest_root, f"tmp_3d_{base_clip_str}.iso")
    if os.path.exists(tmp_iso):
        try:
            os.remove(tmp_iso)
        except OSError:
            pass

    _log("  Erzeuge 3D MVC Stream und SSIF Interleave mit tsMuxeR...")
    iso_cmd = [tsmuxer_bin, meta_path, tmp_iso]
    proc_iso = subprocess.run(iso_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **NO_CONSOLE)
    if proc_iso.returncode != 0:
        err = proc_iso.stderr.strip() or proc_iso.stdout.strip()
        raise RuntimeError(f"tsMuxeR Fehler beim 3D-Muxen: {err}")

    _log("  Lese 3D-Strukturen und Extents direkt aus dem Stream...")
    clpi0_data, clpi1_data, mpls_data, base_extents, mvc_extents, ssif_offset, ssif_len = _parse_tsmuxer_iso(tmp_iso)

    # 1. ClipInfos schreiben
    dest_c0 = os.path.join(clipinf_dir, f"{base_clip_str}.clpi")
    dest_c1 = os.path.join(clipinf_dir, f"{mvc_clip_str}.clpi")
    with open(dest_c0, "wb") as f:
        f.write(clpi0_data)
    with open(dest_c1, "wb") as f:
        f.write(clpi1_data)

    # 2. Transport-Streams (.m2ts) für Basis- und MVC-Auge extrahieren
    # (für den Ordner-Export und Software-Player, die kein SSIF lesen)
    dest_m0 = os.path.join(stream_dir, f"{base_clip_str}.m2ts")
    dest_m1 = os.path.join(stream_dir, f"{mvc_clip_str}.m2ts")

    with open(tmp_iso, 'rb') as f_iso:
        with open(dest_m0, 'wb') as f_base:
            for lbn, sz in base_extents:
                f_iso.seek((288 + lbn) * 2048)
                f_base.write(f_iso.read(sz))

        with open(dest_m1, 'wb') as f_mvc:
            for lbn, sz in mvc_extents:
                f_iso.seek((288 + lbn) * 2048)
                f_mvc.write(f_iso.read(sz))

    _log(f"  3D Base-Stream (AVC) bereitgestellt: {base_clip_str}.m2ts")
    _log(f"  3D Erweiterungs-Stream (MVC) bereitgestellt: {mvc_clip_str}.m2ts")

    # 3. Metadaten für UDF 2.50 Extent-Interleaving binden
    result = Mpls3DBytes(mpls_data)
    result.title_3d_info = {
        "base_clip_str": base_clip_str,
        "mvc_clip_str": mvc_clip_str,
        "tmp_iso": tmp_iso,
        "base_extents": base_extents,
        "mvc_extents": mvc_extents,
        "ssif_offset": ssif_offset,
        "ssif_len": ssif_len
    }

    return result
