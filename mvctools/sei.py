"""SEI-Nachrichten (H.264 7.3.2.3, D.1, H.13) inkl. MVC Scalable Nesting."""

from .bitstream import BitReader

SEI_NAMES = {
    0: "buffering_period",
    1: "pic_timing",
    4: "user_data_registered_itu_t_t35",
    5: "user_data_unregistered",
    6: "recovery_point",
    37: "mvc_scalable_nesting",
    38: "view_scalability_info",
    45: "frame_packing_arrangement",
}


def sei_name(t):
    return SEI_NAMES.get(t, f"sei_{t}")


def _read_varlen(data, pos):
    v = 0
    while data[pos] == 0xFF:
        v += 255
        pos += 1
    return v + data[pos], pos + 1


def _hex(b, n=48):
    s = b[:n].hex(" ")
    return s + (" …" if len(b) > n else "")


def _ascii(b, n=48):
    return "".join(chr(c) if 32 <= c < 127 else "." for c in b[:n])


def _buffering_period(r, hrd_ctx_for_sps):
    f = {"seq_parameter_set_id": r.ue()}
    hrd = hrd_ctx_for_sps(f["seq_parameter_set_id"])
    if hrd is None:
        f["_hinweis"] = "HRD unbekannt, Rest nicht dekodiert"
        return f
    for key in ("nal_hrd", "vcl_hrd"):
        h = hrd.get(key)
        if h:
            n = h["initial_cpb_removal_delay_length"]
            f[key] = [{"initial_cpb_removal_delay": r.u(n), "initial_cpb_removal_delay_offset": r.u(n)}
                      for _ in h["cpbs"]]
    return f


def _pic_timing(r, hrd):
    f = {}
    if hrd is None:
        f["_hinweis"] = "HRD unbekannt, nicht dekodiert"
        return f
    h = hrd.get("nal_hrd") or hrd.get("vcl_hrd")
    if h:
        f["cpb_removal_delay"] = r.u(h["cpb_removal_delay_length"])
        f["dpb_output_delay"] = r.u(h["dpb_output_delay_length"])
    if hrd.get("pic_struct_present_flag"):
        f["pic_struct"] = r.u(4)
    return f


def _payload(ptype, data, ctx, nested_view):
    """Dekodiert eine SEI-Payload. ctx: Objekt mit hrd_for_sps(id, view) und hrd_active(view)."""
    r = BitReader(data)
    if ptype == 0:
        return _buffering_period(r, lambda sid: ctx.hrd_for_sps(sid, nested_view))
    if ptype == 1:
        return _pic_timing(r, ctx.hrd_active(nested_view))
    if ptype == 5:
        return {"uuid": data[:16].hex(), "data_hex": _hex(data[16:]), "data_ascii": _ascii(data[16:]),
                "data_len": len(data) - 16}
    if ptype == 4:
        return {"country_code": data[0] if data else None, "data_hex": _hex(data[1:]),
                "data_ascii": _ascii(data[1:])}
    if ptype == 6:
        return {"recovery_frame_cnt": r.ue(), "exact_match_flag": r.u1(), "broken_link_flag": r.u1()}
    if ptype == 37:
        f = {"operation_point_flag": r.u1()}
        view = None
        if not f["operation_point_flag"]:
            f["all_view_components_in_au_flag"] = r.u1()
            if not f["all_view_components_in_au_flag"]:
                f["sei_view_id"] = [r.u(10) for _ in range(r.ue() + 1)]
                view = f["sei_view_id"][0]
        else:
            f["sei_op_view_id"] = [r.u(10) for _ in range(r.ue() + 1)]
            f["sei_op_temporal_id"] = r.u(3)
            view = f["sei_op_view_id"][-1]
        while not r.byte_aligned():
            r.u1()
        f["nested"] = parse_sei_messages(data[r.pos >> 3:], ctx, nested_view=view)
        return f
    return {"raw_hex": _hex(data)}


def parse_sei_messages(rbsp, ctx, nested_view=None):
    msgs = []
    pos = 0
    n = len(rbsp)
    while pos < n and not (pos == n - 1 and rbsp[pos] == 0x80):
        ptype, pos = _read_varlen(rbsp, pos)
        psize, pos = _read_varlen(rbsp, pos)
        data = rbsp[pos:pos + psize]
        pos += psize
        m = {"type": ptype, "name": sei_name(ptype), "size": psize}
        try:
            m["fields"] = _payload(ptype, data, ctx, nested_view)
        except Exception as e:  # Analyse soll bei exotischen Payloads nicht abbrechen
            m["fields"] = {"_fehler": str(e), "raw_hex": _hex(data)}
        msgs.append(m)
        if nested_view is not None and ptype != 37:
            break  # mvc_scalable_nesting enthält genau eine sei_message
    return msgs


def sei_keys(msgs, prefix=""):
    """Flache Schlüssel wie '37>0' für verschachtelte Nachrichten."""
    keys = []
    for m in msgs:
        k = f"{prefix}{m['type']}"
        keys.append(k)
        for sub in m.get("fields", {}).get("nested", []) if isinstance(m.get("fields"), dict) else []:
            keys.extend(sei_keys([sub], k + ">"))
    return keys
