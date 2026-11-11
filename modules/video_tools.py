# modules/video_tools.py
"""
Video-Tools für OpenBDAuth:
- ffprobe-basierte Analyse von Stream-Parametern (Framerate, Auflösung, SAR/DAR, Halbbilder)
- Pre-Flight Compliance Checker für Blu-ray Disc (BD-ROM Part 3 Spezifikation)
"""

import subprocess
import os
import json
from typing import Dict, List, Any, Optional

from core.translations import tr
from modules.external_tools import find_tool, FFMPEG, FFPROBE, NO_CONSOLE


WARNING_FIELDS = ("title", "message", "consequence", "recommendation")


class ComplianceWarning:
    def __init__(
        self,
        code: str,
        title: str,
        message: str,
        consequence: str,
        recommendation: str,
        severity: str = "warning",
        params: Optional[dict] = None,
    ):
        self.code = code
        self.title = title
        self.message = message
        self.consequence = consequence
        self.recommendation = recommendation
        self.severity = severity
        self.params = params

    @classmethod
    def of(cls, code: str, severity: str = "warning", **params) -> "ComplianceWarning":
        """Hinweis aus seinem Code (v1.27.2): Texte aus core/translations.py (cw_<code>_title …) in der Sprache der
        Oberfläche. Die Werte werden mitgespeichert, damit warning_text() ihn später in der dann gültigen Sprache
        zeigt."""
        texts = [tr(f"cw_{code.lower()}_{field}", **params) for field in WARNING_FIELDS]
        return cls(code, *texts, severity=severity, params=params)

    def to_dict(self) -> dict:
        data = {
            "code": self.code,
            "title": self.title,
            "message": self.message,
            "consequence": self.consequence,
            "recommendation": self.recommendation,
            "severity": self.severity
        }
        if self.params is not None:
            data["params"] = self.params
        return data


def warning_text(warning: dict, field: str) -> str:
    """Text eines gespeicherten Hinweises in der Sprache der Oberfläche (v1.27.2). Hinweise aus älteren Projekten
    (ohne Werte) zeigen den gespeicherten Text."""
    from core.translations import TEXTS
    key = f"cw_{str(warning.get('code', '')).lower()}_{field}"
    params = warning.get("params")
    if params is not None and key in TEXTS["de"]:
        return tr(key, **params)
    return warning.get(field, "")


class VideoTools:
    def __init__(self, ffmpeg_path: Optional[str] = None):
        self.ffmpeg_path = ffmpeg_path or find_tool(FFMPEG) or "ffmpeg"

    def _get_ffprobe_path(self) -> str:
        """Findet ffprobe sicher, auch wenn ffmpeg mit absolutem Pfad übergeben wurde."""
        if os.path.dirname(self.ffmpeg_path):
            dir_name = os.path.dirname(self.ffmpeg_path)
            base_name = os.path.basename(self.ffmpeg_path).lower()
            probe_name = "ffprobe.exe" if base_name.endswith(".exe") else "ffprobe"
            candidate = os.path.join(dir_name, probe_name)
            if os.path.exists(candidate):
                return candidate
        return find_tool(FFPROBE) or "ffprobe"

    def probe_video_details(self, video_path: str, is_3d_hint: bool = False) -> Dict[str, Any]:
        """
        Liest alle relevanten Video-Attribute via ffprobe im JSON-Format aus
        und führt eine Blu-ray Pre-Flight Compliance-Prüfung durch.
        """
        details: Dict[str, Any] = {
            "width": 0,
            "height": 0,
            "fps": 23.976,
            "fps_raw": "",
            "codec_name": "",
            "sar": "1:1",
            "dar": "16:9",
            "field_order": "unknown",
            "is_interlaced": False,
            "warnings": []
        }

        try:
            ffprobe_path = self._get_ffprobe_path()
            cmd = [
                ffprobe_path, "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height,r_frame_rate,avg_frame_rate,sample_aspect_ratio,display_aspect_ratio,field_order,codec_name",
                "-of", "json", video_path
            ]
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **NO_CONSOLE)
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                streams = data.get("streams", [])
                if streams:
                    st = streams[0]
                    details["width"] = int(st.get("width") or 0)
                    details["height"] = int(st.get("height") or 0)
                    details["codec_name"] = str(st.get("codec_name") or "")
                    details["sar"] = str(st.get("sample_aspect_ratio") or "1:1")
                    details["dar"] = str(st.get("display_aspect_ratio") or "")
                    details["field_order"] = str(st.get("field_order") or "unknown")

                    field_order = details["field_order"].lower()
                    if field_order in ("tt", "bb", "tb", "bt", "interlaced"):
                        details["is_interlaced"] = True
                    else:
                        details["is_interlaced"] = False

                    # PsF / Fake-Interlaced Erkennung für H.264 Streams:
                    # ffprobe meldet bei PsF oft 'progressive', da der Bildinhalt aus progressiven Vollbildern besteht.
                    # tsMuxeR und BD-ROM Part 3 werten jedoch das SPS frame_mbs_only_flag (0 = 1080i/PsF)
                    # sowie die x264 SEI Optionen (interlaced=fake) aus.
                    if not details["is_interlaced"] and (details["codec_name"].lower() in ("h264", "avc") or video_path.lower().endswith((".264", ".h264", ".avc"))):
                        if self._detect_h264_psf(video_path):
                            details["is_interlaced"] = True
                            details["is_psf"] = True
                            details["field_order"] = "psf (1080i)"

                    # FPS Ermittlung über r_frame_rate / avg_frame_rate
                    r_fps = str(st.get("r_frame_rate") or "")
                    avg_fps = str(st.get("avg_frame_rate") or "")
                    fps_candidate = r_fps or avg_fps
                    details["fps_raw"] = fps_candidate
                    details["fps"] = self._compute_effective_fps(fps_candidate, details["height"], is_3d_hint)
        except Exception:
            # Fallback auf Basis-Methode
            details["fps"] = self.get_fps(video_path, is_3d_hint=is_3d_hint)

        # Compliance Check durchführen
        warnings = self.check_compliance(details)
        details["warnings"] = [w.to_dict() for w in warnings]
        return details

    def _compute_effective_fps(self, fps_raw: str, height: int, is_3d_hint: bool = False) -> float:
        """Wendet das bewährte Veto- und Korrektursystem auf die Roh-Framerate an."""
        if not fps_raw:
            return 23.976

        if '/' in fps_raw:
            num, den = fps_raw.split('/', 1)
            try:
                den_int = int(den)
                if den_int == 0:
                    fps = 23.976
                else:
                    fps = int(num) / den_int
            except ValueError:
                fps = 23.976
        else:
            try:
                fps = float(fps_raw)
            except ValueError:
                fps = 23.976

        # --- DAS "VETO"-SYSTEM ---
        # 1. Roh-Streams melden oft 25.0 fps bei 3D/MVC wegen SPS/PPS Header-Problem
        if fps == 25.0 and is_3d_hint:
            return 23.976

        # 2. Raw Stream Korrektur (23.976 / 24 fps verdoppelt -> 23.976 / 24.0)
        if 47.0 <= fps <= 48.5:
            if abs(fps - 48.0) < 0.1:
                return 24.0
            return 23.976

        # 3. 50/60 fps Unterscheidung:
        # 720p50 und 720p59.94 sind standardkonforme progressive Blu-ray-Formate!
        # Bei 1080 sind 50/60 Felder/s interlaced (1080i) -> für tsMuxeR halbieren (25 / 29.97).
        if 49.0 <= fps <= 50.5:
            return 50.0 if height == 720 else 25.0
        elif 59.0 <= fps <= 60.1:
            return 59.94 if height == 720 else 29.97
        elif fps > 49.0:
            return fps / 2.0

        return round(fps, 3)

    def get_fps(self, video_path: str, is_3d_hint: bool = False) -> float:
        """Kompatible Schnellmethode zur Ermittlung der FPS."""
        try:
            ffprobe_path = self._get_ffprobe_path()
            cmd = [
                ffprobe_path, "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=r_frame_rate,height",
                "-of", "default=noprint_wrappers=1:nokey=0", video_path
            ]
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **NO_CONSOLE)
            lines = result.stdout.strip().splitlines()

            fps_raw = ""
            height = 0
            for line in lines:
                if line.startswith("r_frame_rate="):
                    fps_raw = line.split("=", 1)[1].strip()
                elif line.startswith("height="):
                    try:
                        height = int(line.split("=", 1)[1].strip())
                    except ValueError:
                        height = 0

            return self._compute_effective_fps(fps_raw, height, is_3d_hint)
        except Exception:
            return 23.976

    @staticmethod
    def _parse_sps_frame_mbs_only(sps_bytes: bytes) -> Optional[int]:
        """Extrahiert frame_mbs_only_flag (0 = interlaced/PsF, 1 = progressive) aus bereinigten SPS-Bytes."""
        try:
            class BitReader:
                def __init__(self, data: bytes):
                    self.data = data
                    self.byte_idx = 0
                    self.bit_idx = 7
                def read_bit(self) -> int:
                    if self.byte_idx >= len(self.data): return 0
                    b = (self.data[self.byte_idx] >> self.bit_idx) & 1
                    self.bit_idx -= 1
                    if self.bit_idx < 0:
                        self.bit_idx = 7
                        self.byte_idx += 1
                    return b
                def read_bits(self, n: int) -> int:
                    val = 0
                    for _ in range(n): val = (val << 1) | self.read_bit()
                    return val
                def read_ue(self) -> int:
                    zeros = 0
                    while self.read_bit() == 0:
                        zeros += 1
                        if zeros > 32: return 0
                    val = self.read_bits(zeros)
                    return (1 << zeros) - 1 + val
                def read_se(self) -> int:
                    val = self.read_ue()
                    sign = 1 if (val & 1) else -1
                    return sign * ((val + 1) // 2)

            br = BitReader(sps_bytes)
            profile_idc = br.read_bits(8)
            br.read_bits(8) # constraints
            level_idc = br.read_bits(8)
            br.read_ue() # seq_parameter_set_id
            if profile_idc in (100, 110, 122, 244, 44, 83, 86, 118, 128, 138, 139, 134):
                chroma_format_idc = br.read_ue()
                if chroma_format_idc == 3:
                    br.read_bit() # separate_colour_plane_flag
                br.read_ue() # bit_depth_luma_minus8
                br.read_ue() # bit_depth_chroma_minus8
                br.read_bit() # qpprime_y_zero_transform_bypass_flag
                seq_scaling_matrix_present = br.read_bit()
                if seq_scaling_matrix_present:
                    cnt = 12 if chroma_format_idc == 3 else 8
                    for _ in range(cnt):
                        if br.read_bit(): # present
                            size = 16 if _ < 6 else 64
                            last_scale, next_scale = 8, 8
                            for _ in range(size):
                                if next_scale != 0:
                                    delta = br.read_se()
                                    next_scale = (last_scale + delta + 256) % 256
                                last_scale = last_scale if next_scale == 0 else next_scale
            br.read_ue() # log2_max_frame_num_minus4
            poc_type = br.read_ue()
            if poc_type == 0:
                br.read_ue() # log2_max_pic_order_cnt_lsb_minus4
            elif poc_type == 1:
                br.read_bit() # delta_pic_order_always_zero_flag
                br.read_se() # offset_for_non_ref_pic
                br.read_se() # offset_for_top_to_bottom_field
                n = br.read_ue()
                for _ in range(n): br.read_se()
            br.read_ue() # max_num_ref_frames
            br.read_bit() # gaps_in_frame_num_value_allowed_flag
            br.read_ue() # pic_width_in_mbs_minus1
            br.read_ue() # pic_height_in_map_units_minus1
            return br.read_bit() # frame_mbs_only_flag
        except Exception:
            return None

    @classmethod
    def _detect_h264_psf(cls, video_path: str) -> bool:
        """
        Erkennt, ob ein H.264 Video als 25PsF / Fake-Interlaced enkodiert ist:
        1. Schneller Header-Check auf x264 SEI Optionen (interlaced=fake).
        2. Bitstream-Analyse des H.264 Sequence Parameter Sets (frame_mbs_only_flag == 0).
        """
        try:
            if not os.path.exists(video_path) or not os.path.isfile(video_path):
                return False
            with open(video_path, "rb") as f:
                header_data = f.read(262144) # Erste 256 KB
            if b"interlaced=fake" in header_data:
                return True
            pos = 0
            while True:
                idx = header_data.find(b"\x00\x00\x01", pos)
                if idx == -1: break
                if idx + 3 < len(header_data):
                    nal_type = header_data[idx + 3] & 0x1F
                    if nal_type == 7: # SPS
                        nxt = header_data.find(b"\x00\x00\x01", idx + 3)
                        sps_raw = header_data[idx + 4:nxt] if nxt != -1 else header_data[idx + 4:idx + 120]
                        clean = bytearray()
                        k = 0
                        while k < len(sps_raw):
                            if k + 2 < len(sps_raw) and sps_raw[k] == 0 and sps_raw[k + 1] == 0 and sps_raw[k + 2] == 3:
                                clean.extend(sps_raw[k:k + 2])
                                k += 3
                            else:
                                clean.append(sps_raw[k])
                                k += 1
                        flag = cls._parse_sps_frame_mbs_only(clean)
                        if flag == 0:
                            return True
                        elif flag == 1:
                            return False
                pos = idx + 3
        except Exception:
            pass
        return False

    def check_compliance(self, video_details: Dict[str, Any]) -> List[ComplianceWarning]:
        """
        Prüft ein Video gegen die BD-ROM Part 3 Spezifikation.
        Gibt eine Liste von nicht-blockierenden Warnungen zurück.
        """
        warnings: List[ComplianceWarning] = []
        width = video_details.get("width", 0)
        height = video_details.get("height", 0)
        fps = video_details.get("fps", 23.976)
        is_interlaced = video_details.get("is_interlaced", False)
        sar = video_details.get("sar", "1:1")
        dar = video_details.get("dar", "")

        # Ohne Stream-Daten ist keine Prüfung möglich
        if width == 0 or height == 0:
            return warnings

        # -------------------------------------------------------------
        # 1. PRÜFUNG: AUFLÖSUNG
        # -------------------------------------------------------------
        # BD-ROM zulässige Auflösungen: 1920x1080, 1440x1080, 1280x720, 720x576, 720x480
        valid_resolutions = [
            (1920, 1080),
            (1440, 1080),
            (1280, 720),
            (720, 576),
            (720, 480),
        ]
        if (width, height) not in valid_resolutions:
            warnings.append(ComplianceWarning.of("NON_STANDARD_RESOLUTION", width=width, height=height))

        # -------------------------------------------------------------
        # 2. PRÜFUNG: SEITENVERHÄLTNIS / ANAMORPH (2.39:1 / 21:9)
        # -------------------------------------------------------------
        # Bei 1920x1080 ist per BD-ROM NUR SAR 1:1 und DAR 16:9 zulässig.
        if width == 1920 and height == 1080:
            is_anamorphic = False
            dar_desc = dar

            # Prüfe SAR (Sample Aspect Ratio)
            if sar and sar not in ("1:1", "0:1", "unknown", "N/A"):
                is_anamorphic = True

            # Prüfe DAR (Display Aspect Ratio) numerisch
            if dar:
                try:
                    if ':' in dar:
                        d_num, d_den = dar.split(':', 1)
                        dar_val = float(d_num) / float(d_den)
                    elif '/' in dar:
                        d_num, d_den = dar.split('/', 1)
                        dar_val = float(d_num) / float(d_den)
                    else:
                        dar_val = float(dar)

                    # 16:9 = 1.7778. Wenn DAR z. B. > 1.85 (2.35:1 oder 2.39:1) oder < 1.70
                    if abs(dar_val - (16.0 / 9.0)) > 0.08:
                        is_anamorphic = True
                        if abs(dar_val - 2.39) < 0.05 or abs(dar_val - 2.35) < 0.05:
                            dar_desc = f"{dar_val:.2f}:1"
                except (ValueError, ZeroDivisionError):
                    pass

            if is_anamorphic:
                dar_str = dar_desc if dar_desc else tr("cw_anamorphic")
                warnings.append(ComplianceWarning.of("ANAMORPHIC_ASPECT_RATIO", dar=dar_str))

        # -------------------------------------------------------------
        # 3. PRÜFUNG: FRAMERATE (1080p25 / 1080p30 Vollbild)
        # -------------------------------------------------------------
        if height == 1080 and not is_interlaced:
            # Fall A: 1080p25
            if 24.8 <= fps <= 25.2:
                warnings.append(ComplianceWarning.of("UNOFFICIAL_1080P25"))

            # Fall B: 1080p30 / 1080p29.97
            elif 29.5 <= fps <= 30.5:
                warnings.append(ComplianceWarning.of("UNOFFICIAL_1080P30"))

            # Fall C: 1080p50 / 1080p60
            elif fps >= 49.0:
                warnings.append(ComplianceWarning.of("UNOFFICIAL_1080P50_60", fps=f"{fps:.0f}",
                                                      fps_exact=f"{fps:.2f}"))

        # -------------------------------------------------------------
        # 4. PRÜFUNG: EXAKT 30 / 60 FPS STATT 29.97 / 59.94
        # -------------------------------------------------------------
        # Die Blu-ray kennt nur die NTSC-Raten; die Disc spielt das Bild 0,1 % langsamer ab, der Ton nicht.
        raw = self._parse_rate(video_details.get("fps_raw", ""))
        if raw is not None and (abs(raw - 30.0) < 0.001 or abs(raw - 60.0) < 0.001):
            exact = raw / 2 if fps < raw * 0.75 else raw   # 1080i: 60 Halbbilder = 30 Vollbilder
            warnings.append(ComplianceWarning.of("EXACT_30_FPS", fps=f"{exact:.0f}",
                                                 ntsc=f"{exact * 1000 / 1001:.2f}", num=f"{exact * 1000:.0f}"))

        return warnings

    @staticmethod
    def _parse_rate(rate: str) -> Optional[float]:
        """'30/1' oder '29.97' → Bilder pro Sekunde; None, wenn nicht lesbar."""
        try:
            if "/" in rate:
                num, den = rate.split("/", 1)
                return int(num) / int(den)
            return float(rate)
        except (ValueError, ZeroDivisionError):
            return None
