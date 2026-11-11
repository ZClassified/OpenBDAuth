# modules/igs/rle.py
"""
Blu-ray Run-Length-Encoding (RLE) für HDMV Interactive Graphics (ODS)
und Presentation Graphics (PGS) nach BD-ROM Part 3 Spezifikation.

Codierungsregeln pro Scanline:
- Einzelnes Pixel mit color != 0:
    1 Byte: color (0x01..0xFF)
- Byte 0x00 kündigt Steuerfolge an (2 bis 4 Bytes):
    0x00 0x00: End of Line (EOL)
    0x00 (0x00 | L): L Pixel mit color = 0 (1 <= L <= 63)
    0x00 (0x40 | L_hi) L_lo: L Pixel mit color = 0 (64 <= L <= 16383)
    0x00 (0x80 | L) C: L Pixel mit Farbe C (1 <= L <= 63)
    0x00 (0xC0 | L_hi) L_lo C: L Pixel mit Farbe C (64 <= L <= 16383)
"""

from typing import List, Union

def encode_line_rle(line: List[int]) -> bytes:
    """Encodiert eine einzelne Scanline (Liste von 8-bit Farb-Indizes) nach BD-ROM RLE."""
    result = bytearray()
    i = 0
    n = len(line)

    while i < n:
        color = line[i]
        # Zähle Länge des Runs gleicher Pixel
        run_len = 1
        while i + run_len < n and line[i + run_len] == color and run_len < 16383:
            run_len += 1

        if color != 0 and run_len == 1:
            # Ein einzelnes von 0 verschiedenes Pixel wird direkt als 1 Byte codiert
            result.append(color)
        elif color == 0:
            # Transparente / Null-Pixel
            if run_len <= 63:
                result.append(0x00)
                result.append(run_len & 0x3F)
            else:
                result.append(0x00)
                result.append(0x40 | ((run_len >> 8) & 0x3F))
                result.append(run_len & 0xFF)
        else:
            # Farbige Pixel (color != 0, run_len >= 2)
            if run_len <= 63:
                result.append(0x00)
                result.append(0x80 | (run_len & 0x3F))
                result.append(color & 0xFF)
            else:
                result.append(0x00)
                result.append(0xC0 | ((run_len >> 8) & 0x3F))
                result.append(run_len & 0xFF)
                result.append(color & 0xFF)

        i += run_len

    # Jede Zeile MUSS mit EOL (0x00, 0x00) abgeschlossen werden
    result.append(0x00)
    result.append(0x00)
    return bytes(result)

def encode_rle(pixels: Union[List[int], bytes, bytearray], width: int, height: int) -> bytes:
    """
    Encodiert eine 2D-Bitmap (width x height, 8-Bit-Farb-Indizes)
    in einen BD-ROM ODS-konformen RLE-Bytestream.
    """
    if len(pixels) != width * height:
        raise ValueError(f"Pixelanzahl ({len(pixels)}) stimmt nicht mit {width}x{height} = {width * height} überein.")

    out = bytearray()
    for y in range(height):
        start = y * width
        line = list(pixels[start:start + width])
        out.extend(encode_line_rle(line))

    return bytes(out)

def decode_rle(data: bytes, width: int, height: int) -> List[int]:
    """
    Dekodiert einen BD-ROM RLE-Bytestream zurück in ein flaches Array
    von width x height Pixeln. Nützlich zur Verifikation und Gegenprobe.
    """
    pixels: List[int] = []
    i = 0
    data_len = len(data)

    for _ in range(height):
        line_pixels: List[int] = []
        while i < data_len:
            b1 = data[i]
            i += 1

            if b1 != 0x00:
                line_pixels.append(b1)
            else:
                # b1 == 0x00 -> Steuerfolge
                if i >= data_len:
                    break
                b2 = data[i]
                i += 1

                if b2 == 0x00:
                    # End of Line
                    break

                flag = b2 & 0xC0
                if flag == 0x00:
                    # 0x00 (0x00 | L): L Nullen
                    run_len = b2 & 0x3F
                    line_pixels.extend([0] * run_len)
                elif flag == 0x40:
                    # 0x00 (0x40 | L_hi) L_lo: L Nullen
                    b3 = data[i]
                    i += 1
                    run_len = ((b2 & 0x3F) << 8) | b3
                    line_pixels.extend([0] * run_len)
                elif flag == 0x80:
                    # 0x00 (0x80 | L) C: L mal Farbe C
                    run_len = b2 & 0x3F
                    c = data[i]
                    i += 1
                    line_pixels.extend([c] * run_len)
                elif flag == 0xC0:
                    # 0x00 (0xC0 | L_hi) L_lo C: L mal Farbe C
                    b3 = data[i]
                    i += 1
                    run_len = ((b2 & 0x3F) << 8) | b3
                    c = data[i]
                    i += 1
                    line_pixels.extend([c] * run_len)

        if len(line_pixels) != width:
            raise ValueError(f"Dekodierte Zeilenlänge {len(line_pixels)} weicht von Sollbreite {width} ab.")
        pixels.extend(line_pixels)

    return pixels
