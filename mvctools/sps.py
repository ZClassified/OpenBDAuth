"""SPS, Subset-SPS (MVC-Extension), VUI und HRD (H.264 7.3.2.1, E.1, H.7.3.2.1.4, H.14)."""

from .bitstream import BitReader

HIGH_PROFILES = {100, 110, 122, 244, 44, 83, 86, 118, 128, 138, 139, 134, 135}
MVC_PROFILES = {118, 128, 134}
PROFILE_NAMES = {
    66: "Baseline", 77: "Main", 88: "Extended", 100: "High", 110: "High 10",
    122: "High 4:2:2", 244: "High 4:4:4", 118: "Multiview High", 128: "Stereo High",
}


def _scaling_list(r, size):
    last = nxt = 8
    for _ in range(size):
        if nxt != 0:
            nxt = (last + r.se() + 256) % 256
        last = last if nxt == 0 else nxt


def parse_hrd(r):
    hrd = {"cpb_cnt_minus1": r.ue(), "bit_rate_scale": r.u(4), "cpb_size_scale": r.u(4), "cpbs": []}
    for _ in range(hrd["cpb_cnt_minus1"] + 1):
        br = r.ue()
        cs = r.ue()
        cbr = r.u1()
        hrd["cpbs"].append({
            "bit_rate": (br + 1) << (6 + hrd["bit_rate_scale"]),
            "cpb_size": (cs + 1) << (4 + hrd["cpb_size_scale"]),
            "cbr_flag": cbr,
        })
    hrd["initial_cpb_removal_delay_length"] = r.u(5) + 1
    hrd["cpb_removal_delay_length"] = r.u(5) + 1
    hrd["dpb_output_delay_length"] = r.u(5) + 1
    hrd["time_offset_length"] = r.u(5)
    return hrd


def parse_vui(r):
    v = {}
    if r.u1():
        v["aspect_ratio_idc"] = r.u(8)
        if v["aspect_ratio_idc"] == 255:
            v["sar"] = (r.u(16), r.u(16))
    if r.u1():
        v["overscan_appropriate_flag"] = r.u1()
    if r.u1():
        v["video_format"] = r.u(3)
        v["video_full_range_flag"] = r.u1()
        if r.u1():
            v["colour_primaries"] = r.u(8)
            v["transfer_characteristics"] = r.u(8)
            v["matrix_coefficients"] = r.u(8)
    if r.u1():
        v["chroma_sample_loc_type_top"] = r.ue()
        v["chroma_sample_loc_type_bottom"] = r.ue()
    if r.u1():
        v["num_units_in_tick"] = r.u(32)
        v["time_scale"] = r.u(32)
        v["fixed_frame_rate_flag"] = r.u1()
    if r.u1():
        v["nal_hrd"] = parse_hrd(r)
    if r.u1():
        v["vcl_hrd"] = parse_hrd(r)
    if "nal_hrd" in v or "vcl_hrd" in v:
        v["low_delay_hrd_flag"] = r.u1()
    v["pic_struct_present_flag"] = r.u1()
    if r.u1():
        v["bitstream_restriction"] = {
            "motion_vectors_over_pic_boundaries_flag": r.u1(),
            "max_bytes_per_pic_denom": r.ue(),
            "max_bits_per_mb_denom": r.ue(),
            "log2_max_mv_length_horizontal": r.ue(),
            "log2_max_mv_length_vertical": r.ue(),
            "max_num_reorder_frames": r.ue(),
            "max_dec_frame_buffering": r.ue(),
        }
    return v


def parse_sps_data(r):
    s = {}
    s["profile_idc"] = r.u(8)
    s["profile"] = PROFILE_NAMES.get(s["profile_idc"], "?")
    flags = r.u(8)
    s["constraint_flags"] = f"{flags:08b}"
    s["level_idc"] = r.u(8)
    s["seq_parameter_set_id"] = r.ue()
    s["chroma_format_idc"] = 1
    s["separate_colour_plane_flag"] = 0
    if s["profile_idc"] in HIGH_PROFILES:
        s["chroma_format_idc"] = r.ue()
        if s["chroma_format_idc"] == 3:
            s["separate_colour_plane_flag"] = r.u1()
        s["bit_depth_luma"] = r.ue() + 8
        s["bit_depth_chroma"] = r.ue() + 8
        s["qpprime_y_zero_transform_bypass_flag"] = r.u1()
        s["seq_scaling_matrix_present_flag"] = r.u1()
        if s["seq_scaling_matrix_present_flag"]:
            for i in range(8 if s["chroma_format_idc"] != 3 else 12):
                if r.u1():
                    _scaling_list(r, 16 if i < 6 else 64)
    s["log2_max_frame_num"] = r.ue() + 4
    s["pic_order_cnt_type"] = r.ue()
    if s["pic_order_cnt_type"] == 0:
        s["log2_max_pic_order_cnt_lsb"] = r.ue() + 4
    elif s["pic_order_cnt_type"] == 1:
        s["delta_pic_order_always_zero_flag"] = r.u1()
        s["offset_for_non_ref_pic"] = r.se()
        s["offset_for_top_to_bottom_field"] = r.se()
        n = r.ue()
        s["offset_for_ref_frame"] = [r.se() for _ in range(n)]
    s["max_num_ref_frames"] = r.ue()
    s["gaps_in_frame_num_value_allowed_flag"] = r.u1()
    w = r.ue() + 1
    h = r.ue() + 1
    s["frame_mbs_only_flag"] = r.u1()
    if not s["frame_mbs_only_flag"]:
        s["mb_adaptive_frame_field_flag"] = r.u1()
    s["direct_8x8_inference_flag"] = r.u1()
    s["width"] = w * 16
    s["height"] = h * 16 * (2 - s["frame_mbs_only_flag"])
    if r.u1():
        crop = [r.ue() for _ in range(4)]
        s["frame_cropping"] = crop
        cx = 1 if s["chroma_format_idc"] in (0, 3) else 2
        cy = (1 if s["chroma_format_idc"] in (0, 2, 3) else 2) * (2 - s["frame_mbs_only_flag"])
        s["width"] -= cx * (crop[0] + crop[1])
        s["height"] -= cy * (crop[2] + crop[3])
    s["chroma_array_type"] = 0 if s["separate_colour_plane_flag"] else s["chroma_format_idc"]
    if r.u1():
        s["vui"] = parse_vui(r)
    return s


def parse_sps(rbsp):
    return parse_sps_data(BitReader(rbsp))


def parse_mvc_extension(r):
    m = {}
    n = r.ue() + 1
    m["num_views"] = n
    m["view_id"] = [r.ue() for _ in range(n)]
    m["anchor_refs"] = []
    for i in range(1, n):
        l0 = [r.ue() for _ in range(r.ue())]
        l1 = [r.ue() for _ in range(r.ue())]
        m["anchor_refs"].append({"view": m["view_id"][i], "l0": l0, "l1": l1})
    m["non_anchor_refs"] = []
    for i in range(1, n):
        l0 = [r.ue() for _ in range(r.ue())]
        l1 = [r.ue() for _ in range(r.ue())]
        m["non_anchor_refs"].append({"view": m["view_id"][i], "l0": l0, "l1": l1})
    m["level_values"] = []
    for _ in range(r.ue() + 1):
        lv = {"level_idc": r.u(8), "ops": []}
        for _ in range(r.ue() + 1):
            op = {"temporal_id": r.u(3)}
            op["target_view_ids"] = [r.ue() for _ in range(r.ue() + 1)]
            op["num_views"] = r.ue() + 1
            lv["ops"].append(op)
        m["level_values"].append(lv)
    return m


def parse_mvc_vui(r):
    ops = []
    for _ in range(r.ue() + 1):
        op = {"temporal_id": r.u(3)}
        op["target_output_view_ids"] = [r.ue() for _ in range(r.ue() + 1)]
        if r.u1():
            op["num_units_in_tick"] = r.u(32)
            op["time_scale"] = r.u(32)
            op["fixed_frame_rate_flag"] = r.u1()
        if r.u1():
            op["nal_hrd"] = parse_hrd(r)
        if r.u1():
            op["vcl_hrd"] = parse_hrd(r)
        if "nal_hrd" in op or "vcl_hrd" in op:
            op["low_delay_hrd_flag"] = r.u1()
        op["pic_struct_present_flag"] = r.u1()
        ops.append(op)
    return ops


def parse_subset_sps(rbsp):
    r = BitReader(rbsp)
    s = parse_sps_data(r)
    if s["profile_idc"] in MVC_PROFILES:
        s["bit_equal_to_one"] = r.u1()
        s["mvc"] = parse_mvc_extension(r)
        if r.u1():
            s["mvc_vui"] = parse_mvc_vui(r)
        s["additional_extension2_flag"] = r.u1()
    return s


def hrd_context(sps, view_id=None):
    """HRD-Parameter für SEI-Parsing. Für MVC-Views wird – falls vorhanden – die MVC-VUI benutzt."""
    if sps is None:
        return None
    src = sps.get("vui", {})
    if view_id is not None:
        for op in sps.get("mvc_vui", []):
            if view_id in op["target_output_view_ids"] or not src:
                src = op
                break
    return {
        "nal_hrd": src.get("nal_hrd"),
        "vcl_hrd": src.get("vcl_hrd"),
        "pic_struct_present_flag": src.get("pic_struct_present_flag", 0),
    }


def frame_rate(sps):
    v = sps.get("vui", {})
    if v.get("num_units_in_tick"):
        return v["time_scale"] / (2 * v["num_units_in_tick"])
    return None
