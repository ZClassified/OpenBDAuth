# modules/subtitles/srt_to_sup.py
"""
SRT-zu-PGS-Konverter (.sup).

Wandelt Text-Untertitel (.srt) in standardkonforme Blu-ray Presentation
Graphic Stream (PGS / SUP) Bitmaps um:
- Rendern mit Pillow (1920x1080)
- weiße Schrift mit schwarzer Kontur
- BT.709 YCbCrA Farbpalette mit Transparenz
- BD-ROM Part 3 konformes RLE-Packing (PCS, WDS, PDS, ODS, END)
- Bild-Untertitel statt Text, weil tsMuxeR unter Windows ohne FreeType gebaut ist und Textuntertitel nicht rendert
"""

import os
import re
import struct
from typing import List, Tuple, Optional, Callable
from PIL import Image, ImageDraw, ImageFont

from modules.igs.rle import encode_rle

# BD-ROM Part 3 / PGS PCS frame_rate byte:
# 0x10 = 23.976fps, 0x20 = 24fps, 0x30 = 25fps,
# 0x40 = 29.97fps,  0x60 = 50fps, 0x70 = 59.94fps
_FPS_TO_PGS_RATE = {
    23.976: 0x10,
    24.0:   0x20,
    25.0:   0x30,
    29.97:  0x40,
    50.0:   0x60,
    59.94:  0x70,
}

def fps_to_pgs_rate_byte(fps: float) -> int:
    """Gibt den BD-ROM PGS PCS frame_rate_type Byte-Wert für die angegebene FPS zurück."""
    # Nächstliegende Bildrate wählen – 23.976 und 24.0 liegen nur 0.024 auseinander,
    # ein „erster Treffer innerhalb der Toleranz“ würde 24 fps als 23.976 einordnen.
    known_fps = min(_FPS_TO_PGS_RATE, key=lambda k: abs(fps - k))
    if abs(fps - known_fps) < 0.1:
        return _FPS_TO_PGS_RATE[known_fps]
    return 0x10  # Fallback: 23.976fps


def parse_timestamp_to_seconds(ts_str: str) -> float:
    """Konvertiert 'hh:mm:ss,mmm' oder 'hh:mm:ss.mmm' in Sekunden (float)."""
    ts_str = ts_str.strip().replace(",", ".")
    parts = ts_str.split(":")
    if len(parts) == 3:
        h = float(parts[0])
        m = float(parts[1])
        s = float(parts[2])
        return h * 3600.0 + m * 60.0 + s
    elif len(parts) == 2:
        m = float(parts[0])
        s = float(parts[1])
        return m * 60.0 + s
    return float(ts_str)


def parse_srt_file(srt_path: str) -> List[Tuple[float, float, str]]:
    """
    Liest eine .srt-Datei mit Encoding-Fallback ein und gibt eine Liste von
    (start_sec, end_sec, text) Tupeln zurück.
    """
    raw_content = None
    for enc in ["utf-8-sig", "utf-8", "cp1252", "latin-1"]:
        try:
            with open(srt_path, "r", encoding=enc) as f:
                raw_content = f.read()
            break
        except (UnicodeDecodeError, OSError):
            continue

    if raw_content is None:
        raise ValueError(f"Konnte Untertitel-Datei {srt_path} mit keinem unterstützten Zeichensatz lesen.")

    # Bereinigen von Windows-Zeilenumbrüchen
    raw_content = raw_content.replace("\r\n", "\n").replace("\r", "\n")

    # Regex für SRT-Blöcke:
    # 1. Ziffern
    # 2. Timecode --> Timecode
    # 3. Text
    pattern = re.compile(
        r'(?:^|\n+)(?:\d+)\s*\n'
        r'(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3})'
        r'[^\n]*\n'
        r'([\s\S]*?)(?=(?:\n+\d+\s*\n\d{1,2}:\d{2}:\d{2})|\Z)',
        re.MULTILINE
    )

    cues: List[Tuple[float, float, str]] = []
    for match in pattern.finditer(raw_content):
        start_str = match.group(1)
        end_str = match.group(2)
        text_str = match.group(3).strip()

        # HTML- / ASS-Tags entfernen (<i>, <b>, <font ...>, {...})
        clean_text = re.sub(r'<[^>]+>', '', text_str)
        clean_text = re.sub(r'\{[^}]+\}', '', clean_text)
        clean_text = clean_text.strip()

        if clean_text:
            start_sec = parse_timestamp_to_seconds(start_str)
            end_sec = parse_timestamp_to_seconds(end_str)
            if end_sec > start_sec:
                cues.append((start_sec, end_sec, clean_text))

    return cues


def rgba_to_ycbcr_bt709(r: int, g: int, b: int, a: int) -> Tuple[int, int, int, int]:
    """Konvertiert RGBA nach ITU-R BT.709 YCbCrA für BD-ROM PGS."""
    if a == 0:
        return 0, 128, 128, 0
    y = int(0.2126 * r + 0.7152 * g + 0.0722 * b)
    cb = int(128 - 0.1146 * r - 0.3854 * g + 0.5000 * b)
    cr = int(128 + 0.5000 * r - 0.4542 * g - 0.0458 * b)
    return max(0, min(255, y)), max(0, min(255, cr)), max(0, min(255, cb)), a


def make_sup_segment(pts_90k: int, dts_90k: int, seg_type: int, payload: bytes) -> bytes:
    """Erzeugt ein einzelnes BD-ROM PGS Segment mit 'PG' Header."""
    header = b"PG" + struct.pack(">IIBH", pts_90k, dts_90k, seg_type, len(payload))
    return header + payload


def has_cjk(text: str) -> bool:
    """Prüft, ob der Text ostasiatische CJK-Zeichen (Japanisch, Chinesisch, Koreanisch) enthält."""
    for ch in text:
        cp = ord(ch)
        if (
            0x3000 <= cp <= 0x303F or  # CJK Symbols and Punctuation
            0x3040 <= cp <= 0x309F or  # Hiragana
            0x30A0 <= cp <= 0x30FF or  # Katakana
            0x31F0 <= cp <= 0x31FF or  # Katakana Phonetic Extensions
            0x4E00 <= cp <= 0x9FFF or  # CJK Unified Ideographs (Kanji)
            0x3400 <= cp <= 0x4DBF or  # CJK Unified Ideographs Extension A
            0xAC00 <= cp <= 0xD7AF or  # Hangul Syllables (Korean)
            0xFF00 <= cp <= 0xFFEF     # Halfwidth and Fullwidth Forms
        ):
            return True
    return False


def get_subtitle_font(text: str, font_size: int = 48) -> ImageFont.FreeTypeFont:
    """Mitgelieferte Untertitelschrift (Noto Sans); für CJK-Text eine passende Systemschrift."""
    from modules.fonts import load_subtitle_font
    return load_subtitle_font(font_size, needs_cjk=has_cjk(text))


def render_subtitle_image(
    text: str,
    font_size: int = 48,
    outline_size: int = 3
) -> Tuple[int, int, bytes, bytes]:
    """
    Rendert mehrzeiligen Untertiteltext in ein transparentes RGBA-Bild,
    erzeugt eine 8-Bit-PGS-Farbpalette mit vollständig transparentem
    Hintergrund und weichem Anti-Aliasing, und komprimiert via BD-ROM RLE.
    Gibt (img_w, img_h, pds_payload_bytes, rle_data_bytes) zurück.
    """
    font = get_subtitle_font(text, font_size)

    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if not lines:
        lines = [""]

    dummy_img = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    draw = ImageDraw.Draw(dummy_img)

    line_bboxes = [draw.textbbox((0, 0), line, font=font) for line in lines]
    text_w = max(b[2] - b[0] for b in line_bboxes)
    line_h = max(b[3] - b[1] for b in line_bboxes) + int(font_size * 0.28)
    total_h = line_h * len(lines)

    # Bildmaße mit Padding für Outline berechnen (auf 8 bzw. 2 Pixel ausgerichtet)
    pad = outline_size * 2 + 8
    img_w = ((text_w + pad * 2 + 7) // 8) * 8
    img_h = ((total_h + pad * 2 + 1) // 2) * 2

    img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    y_off = pad
    for line in lines:
        lb = draw.textbbox((0, 0), line, font=font)
        lw = lb[2] - lb[0]
        x_off = (img_w - lw) // 2

        # 1. Schwarze Kontur / Outline für optimalen Kontrast
        for dx in range(-outline_size, outline_size + 1):
            for dy in range(-outline_size, outline_size + 1):
                if dx * dx + dy * dy <= outline_size * outline_size:
                    draw.text((x_off + dx, y_off + dy), line, font=font, fill=(0, 0, 0, 255))

        # 2. Text in Reinweiß
        draw.text((x_off, y_off), line, font=font, fill=(255, 255, 255, 255))
        y_off += line_h

    # RGBA-Pixel extrahieren
    if hasattr(img, "get_flattened_data"):
        raw_list = list(img.get_flattened_data())
        if raw_list and isinstance(raw_list[0], tuple):
            pixel_tuples = raw_list
        else:
            pixel_tuples = [
                (raw_list[i], raw_list[i+1], raw_list[i+2], raw_list[i+3])
                for i in range(0, len(raw_list), 4)
            ]
    else:
        pixel_tuples = list(img.getdata())

    # Pixel quantisieren: Alpha < 12 gilt als transparent
    # 16-Stufen Quantisierung für harmonisches Anti-Aliasing (max. ~32-64 Farben)
    def quantize_pixel(r: int, g: int, b: int, a: int) -> Tuple[int, int, int, int]:
        if a < 12:
            return 0, 0, 0, 0
        aq = min(255, ((a + 8) // 16) * 16)
        rq = min(255, ((r + 8) // 16) * 16)
        gq = min(255, ((g + 8) // 16) * 16)
        bq = min(255, ((b + 8) // 16) * 16)
        return rq, gq, bq, aq

    quantized_pixels = [quantize_pixel(*p) for p in pixel_tuples]

    # Einzigartige sichtbare Farben sammeln (maximal 254 sichtbare Farben)
    unique_visible = list({p for p in quantized_pixels if p != (0, 0, 0, 0)})
    # Sortieren nach Alpha und Helligkeit für eine deterministische Palette
    unique_visible.sort(key=lambda c: (c[3], 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]))
    unique_visible = unique_visible[:254]

    color_to_id = {(0, 0, 0, 0): 0}
    for idx, c in enumerate(unique_visible):
        color_to_id[c] = idx + 1

    # Palette aufbauen:
    # Eintrag 0 ist transparent (T=0), sonst erscheint ein schwarzer Kasten
    pds_entries = bytearray()
    pds_entries.extend(bytes([0, 0, 128, 128, 0]))

    for idx, (r, g, b, a) in enumerate(unique_visible):
        entry_id = idx + 1
        y, cr, cb, _ = rgba_to_ycbcr_bt709(r, g, b, a)
        pds_entries.extend(bytes([entry_id, y, cr, cb, a]))

    # Pixel in Paletten-IDs umwandeln
    remapped_pixels = [color_to_id.get(p, 0) for p in quantized_pixels]

    # RLE Kompression nach BD-ROM Spezifikation
    rle_data = encode_rle(remapped_pixels, img_w, img_h)

    return img_w, img_h, bytes(pds_entries), rle_data


def build_sup_cue_bytes(
    text: str,
    start_sec: float,
    end_sec: float,
    comp_num: int = 0,
    font_size: int = 48,
    bottom_margin: int = 70,
    fps: float = 23.976
) -> bytes:
    """
    Erzeugt die kompletten Binärdaten für eine Untertitel-Einblendung und
    die anschließende Ausblendung im .sup Format.
    """
    start_pts = int(round(start_sec * 90000))
    end_pts = int(round(end_sec * 90000))

    img_w, img_h, pds_bytes, rle_data = render_subtitle_image(text, font_size=font_size)

    # Zentriert am unteren Bildschirmrand platzieren
    x = max(0, (1920 - img_w) // 2)
    y = max(0, 1080 - img_h - bottom_margin)

    # Koordinaten auf gerade Zahlen ausrichten
    x = (x // 2) * 2
    y = (y // 2) * 2

    out = bytearray()

    # -------------------------------------------------------------------------
    # 1. DISPLAY SET: Untertitel anzeigen (start_pts)
    # -------------------------------------------------------------------------
    # PCS (Presentation Composition Segment, 0x16)
    pcs_payload = bytearray()
    pcs_payload.extend(struct.pack(">HH", 1920, 1080)) # Video Width, Height
    pcs_payload.append(fps_to_pgs_rate_byte(fps))      # Frame Rate: dynamisch aus Projekt-FPS
    pcs_payload.extend(struct.pack(">H", comp_num & 0xFFFF))
    pcs_payload.append(0x80) # Composition State: Epoch Start
    pcs_payload.append(0x00) # Palette update flag
    pcs_payload.append(0x00) # Palette ID
    pcs_payload.append(1)    # 1 Composition Object
    pcs_payload.extend(struct.pack(">H", 0)) # Object ID 0
    pcs_payload.append(0)    # Window ID 0
    pcs_payload.append(0)    # Cropped flag (False)
    pcs_payload.extend(struct.pack(">HH", x, y))
    out.extend(make_sup_segment(start_pts, start_pts, 0x16, pcs_payload))

    # WDS (Window Definition Segment, 0x17)
    wds_payload = bytearray()
    wds_payload.append(1) # 1 Window
    wds_payload.append(0) # Window ID 0
    wds_payload.extend(struct.pack(">HHHH", x, y, img_w, img_h))
    out.extend(make_sup_segment(start_pts, start_pts, 0x17, wds_payload))

    # PDS (Palette Definition Segment, 0x14)
    pds_payload = bytearray([0x00, 0x00]) + pds_bytes # Palette ID 0, Version 0
    out.extend(make_sup_segment(start_pts, start_pts, 0x14, pds_payload))

    # ODS (Object Definition Segment, 0x15)
    ods_payload = bytearray()
    ods_payload.extend(struct.pack(">H", 0)) # Object ID 0
    ods_payload.append(0) # Version 0
    ods_payload.append(0xC0) # Sequence Descriptor: First & Last in sequence
    ods_data_len = 4 + len(rle_data)
    ods_payload.extend(bytes([
        (ods_data_len >> 16) & 0xFF,
        (ods_data_len >> 8) & 0xFF,
        ods_data_len & 0xFF
    ]))
    ods_payload.extend(struct.pack(">HH", img_w, img_h))
    ods_payload.extend(rle_data)
    out.extend(make_sup_segment(start_pts, start_pts, 0x15, ods_payload))

    # END (End of Display Set, 0x80)
    out.extend(make_sup_segment(start_pts, start_pts, 0x80, b""))

    # -------------------------------------------------------------------------
    # 2. CLEAR DISPLAY SET: Untertitel ausblenden (end_pts)
    # -------------------------------------------------------------------------
    clear_pcs = bytearray()
    clear_pcs.extend(struct.pack(">HH", 1920, 1080))
    clear_pcs.append(fps_to_pgs_rate_byte(fps))
    clear_pcs.extend(struct.pack(">H", (comp_num + 1) & 0xFFFF))
    clear_pcs.append(0x00) # Normal State
    clear_pcs.append(0x00) # Palette update flag
    clear_pcs.append(0x00) # Palette ID
    clear_pcs.append(0)    # 0 Objects -> CLEAR SCREEN!
    out.extend(make_sup_segment(end_pts, end_pts, 0x16, clear_pcs))

    clear_wds = bytearray([0x00]) # 0 Windows
    out.extend(make_sup_segment(end_pts, end_pts, 0x17, clear_wds))

    out.extend(make_sup_segment(end_pts, end_pts, 0x80, b""))

    return bytes(out)


def convert_srt_to_sup(
    srt_path: str,
    sup_path: str,
    fps: float = 23.976,
    font_size: int = 48,
    log_callback: Optional[Callable[[str], None]] = None
) -> str:
    """
    Konvertiert eine .srt-Datei vollständig in eine normgerechte .sup (PGS) Datei.
    """
    if log_callback:
        log_callback(f"Parse SRT: {os.path.basename(srt_path)}...")

    cues = parse_srt_file(srt_path)
    if not cues:
        # Erzeuge leere aber valide SUP-Datei, falls keine Cues vorhanden sind
        with open(sup_path, "wb") as f:
            pass
        return sup_path

    if log_callback:
        log_callback(f"Rendere {len(cues)} Untertitel nach BD-ROM PGS (.sup)...")

    os.makedirs(os.path.dirname(os.path.abspath(sup_path)), exist_ok=True)
    with open(sup_path, "wb") as f_out:
        for idx, (start_sec, end_sec, text) in enumerate(cues):
            comp_num = (idx * 2) & 0xFFFF
            cue_bytes = build_sup_cue_bytes(
                text=text,
                start_sec=start_sec,
                end_sec=end_sec,
                comp_num=comp_num,
                font_size=font_size,
                fps=fps
            )
            f_out.write(cue_bytes)

    if log_callback:
        log_callback(f"✓ PGS-Untertitel erfolgreich erstellt: {os.path.basename(sup_path)} ({len(cues)} Einträge)")

    return sup_path
