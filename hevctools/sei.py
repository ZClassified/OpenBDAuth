"""SEI-Nachrichten (H.265 7.3.5, Anhang D): HDR-Metadaten, HDR10+, Encoder-Angaben, HRD-Pufferung."""

from mvctools.bitstream import BitReader, ebsp_to_rbsp

BUFFERING_PERIOD = 0
PIC_TIMING = 1
USER_DATA_REGISTERED = 4
USER_DATA_UNREGISTERED = 5
RECOVERY_POINT = 6
ACTIVE_PARAMETER_SETS = 129
MASTERING_DISPLAY = 137
CONTENT_LIGHT_LEVEL = 144
ALTERNATIVE_TRANSFER = 147

SEI_NAMES = {
    BUFFERING_PERIOD: "buffering_period",
    PIC_TIMING: "pic_timing",
    USER_DATA_REGISTERED: "user_data_registered_itu_t_t35",
    USER_DATA_UNREGISTERED: "user_data_unregistered",
    RECOVERY_POINT: "recovery_point",
    ACTIVE_PARAMETER_SETS: "active_parameter_sets",
    MASTERING_DISPLAY: "mastering_display_colour_volume",
    CONTENT_LIGHT_LEVEL: "content_light_level_info",
    ALTERNATIVE_TRANSFER: "alternative_transfer_characteristics",
}

# HDR10+ (SMPTE ST 2094-40): ITU-T T.35 USA (0xB5), Samsung (0x003C), Anwendung 4
HDR10PLUS_PREFIX = bytes([0xB5, 0x00, 0x3C, 0x00, 0x01, 0x04])


def sei_name(t):
    return SEI_NAMES.get(t, f"sei_{t}")


def split_sei_messages(ebsp):
    """[(payloadType, payload)] aus dem Payload einer SEI-NAL-Unit (ohne 2-Byte-Header)."""
    data = ebsp_to_rbsp(ebsp)
    out, pos = [], 0
    while pos < len(data) and not (pos == len(data) - 1 and data[pos] == 0x80):
        ptype = 0
        while pos < len(data) and data[pos] == 0xFF:
            ptype += 255
            pos += 1
        if pos >= len(data):
            break
        ptype += data[pos]
        pos += 1
        psize = 0
        while pos < len(data) and data[pos] == 0xFF:
            psize += 255
            pos += 1
        if pos >= len(data):
            break
        psize += data[pos]
        pos += 1
        out.append((ptype, data[pos:pos + psize]))
        pos += psize
    return out


def mastering_display(payload):
    """Mastering Display Colour Volume: Primärfarben und Weißpunkt in CIE xy, Helligkeit in cd/m²."""
    r = BitReader(payload)
    prim = [(r.u(16) * 0.00002, r.u(16) * 0.00002) for _ in range(3)]
    white = (r.u(16) * 0.00002, r.u(16) * 0.00002)
    max_lum, min_lum = r.u(32) * 0.0001, r.u(32) * 0.0001
    return {"primaries": [tuple(round(c, 5) for c in p) for p in prim],
            "white_point": tuple(round(c, 5) for c in white),
            "max_luminance": round(max_lum, 4), "min_luminance": round(min_lum, 4)}


def content_light_level(payload):
    r = BitReader(payload)
    return {"max_cll": r.u(16), "max_fall": r.u(16)}


def unregistered_text(payload):
    """Lesbarer Text nach der 16-Byte-UUID (x265 schreibt dort Version und Optionen), sonst None."""
    text = bytes(payload[16:]).split(b"\x00", 1)[0]
    try:
        decoded = text.decode("ascii")
    except UnicodeDecodeError:
        return None
    return decoded if decoded and all(32 <= ord(c) < 127 for c in decoded) else None


def is_hdr10plus(payload):
    return bytes(payload[:len(HDR10PLUS_PREFIX)]) == HDR10PLUS_PREFIX


def buffering_period(payload, sps):
    """Anfangsverzögerung des ersten NAL-HRD (90-kHz-Takt) oder None, wenn der HRD unbekannt ist."""
    hrd = (sps or {}).get("vui", {}).get("hrd")
    if not hrd or not hrd.get("nal_hrd_parameters_present_flag"):
        return None
    r = BitReader(payload)
    r.ue()                                    # bp_seq_parameter_set_id
    irap_cpb = 0
    if not hrd["sub_pic_hrd_params_present_flag"]:
        irap_cpb = r.u1()
    if irap_cpb:
        r.u(hrd["au_cpb_removal_delay_length"])
        r.u(hrd["dpb_output_delay_length"])
    r.u1()                                    # concatenation_flag
    r.u(hrd["au_cpb_removal_delay_length"])
    n = hrd["initial_cpb_removal_delay_length"]
    return {"initial_cpb_removal_delay": r.u(n), "initial_cpb_removal_offset": r.u(n)}
