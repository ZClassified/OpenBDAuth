"""Sequence Parameter Set (H.265 7.3.2.2) mit profile_tier_level, VUI (Anhang E) und HRD-Parametern."""

from mvctools.bitstream import BitReader, ebsp_to_rbsp

PROFILE_NAMES = {1: "Main", 2: "Main 10", 3: "Main Still Picture", 4: "Range Extensions"}
COLOUR_PRIMARIES = {1: "BT.709", 2: "nicht angegeben", 5: "BT.601 625", 6: "BT.601 525", 9: "BT.2020",
                    11: "DCI-P3", 12: "Display P3"}
TRANSFER = {1: "BT.709", 2: "nicht angegeben", 6: "BT.601", 13: "sRGB", 14: "BT.2020 (10 Bit)",
            15: "BT.2020 (12 Bit)", 16: "PQ (SMPTE ST 2084)", 18: "HLG (ARIB STD-B67)"}
MATRIX = {0: "RGB", 1: "BT.709", 2: "nicht angegeben", 5: "BT.601 625", 6: "BT.601 525",
          9: "BT.2020 (nicht konstant)", 10: "BT.2020 (konstant)"}


def profile_tier_level(r, max_sub_layers_minus1):
    """profile_tier_level(1, maxNumSubLayersMinus1), 7.3.3."""
    f = {
        "general_profile_space": r.u(2),
        "general_tier_flag": r.u1(),
        "general_profile_idc": r.u(5),
        "general_profile_compatibility_flags": r.u(32),
        "general_progressive_source_flag": r.u1(),
        "general_interlaced_source_flag": r.u1(),
        "general_non_packed_constraint_flag": r.u1(),
        "general_frame_only_constraint_flag": r.u1(),
    }
    r.u(32)                                   # Einschränkungs-Flags der Range Extensions bzw. reserviert (43 Bit)
    r.u(11)
    r.u1()                                    # general_inbld_flag bzw. reserviert
    f["general_level_idc"] = r.u(8)
    present = [(r.u1(), r.u1()) for _ in range(max_sub_layers_minus1)]
    if max_sub_layers_minus1 > 0:
        for _ in range(max_sub_layers_minus1, 8):
            r.u(2)
    for profile_present, level_present in present:
        if profile_present:
            r.u(32)
            r.u(32)
            r.u(24)                           # 88 Bit Profil der Teilschicht
        if level_present:
            r.u(8)
    return f


def _scaling_list_data(r):
    for size_id in range(4):
        for _matrix_id in range(0, 6, 3 if size_id == 3 else 1):
            if not r.u1():                    # scaling_list_pred_mode_flag
                r.ue()
            else:
                coef_num = min(64, 1 << (4 + (size_id << 1)))
                if size_id > 1:
                    r.se()
                for _ in range(coef_num):
                    r.se()


def _st_ref_pic_set(r, idx, num_sets, sets):
    """st_ref_pic_set(stRpsIdx), 7.3.7; sets enthält (S0, S1) der vorherigen Sätze als Listen von DeltaPocs."""
    inter = r.u1() if idx != 0 else 0
    if inter:
        delta_idx_minus1 = r.ue() if idx == num_sets else 0
        sign = r.u1()
        abs_minus1 = r.ue()
        delta_rps = (1 - 2 * sign) * (abs_minus1 + 1)
        ref_s0, ref_s1 = sets[idx - (delta_idx_minus1 + 1)]
        ref = ref_s0 + ref_s1
        used, use_delta = [], []
        for _ in range(len(ref) + 1):
            u = r.u1()
            used.append(u)
            use_delta.append(1 if u else r.u1())
        # Ableitung 7.4.8 (Gleichungen 7-61, 7-62)
        s0, s1 = [], []
        for j in range(len(ref_s1) - 1, -1, -1):
            d = ref_s1[j] + delta_rps
            if d < 0 and use_delta[len(ref_s0) + j]:
                s0.append(d)
        if delta_rps < 0 and use_delta[len(ref)]:
            s0.append(delta_rps)
        for j in range(len(ref_s0)):
            d = ref_s0[j] + delta_rps
            if d < 0 and use_delta[j]:
                s0.append(d)
        for j in range(len(ref_s0) - 1, -1, -1):
            d = ref_s0[j] + delta_rps
            if d > 0 and use_delta[j]:
                s1.append(d)
        if delta_rps > 0 and use_delta[len(ref)]:
            s1.append(delta_rps)
        for j in range(len(ref_s1)):
            d = ref_s1[j] + delta_rps
            if d > 0 and use_delta[len(ref_s0) + j]:
                s1.append(d)
        return s0, s1
    neg, pos = r.ue(), r.ue()
    s0, s1, poc = [], [], 0
    for _ in range(neg):
        poc -= r.ue() + 1
        r.u1()
        s0.append(poc)
    poc = 0
    for _ in range(pos):
        poc += r.ue() + 1
        r.u1()
        s1.append(poc)
    return s0, s1


def _sub_layer_hrd(r, cpb_cnt, sub_pic):
    cpbs = []
    for _ in range(cpb_cnt):
        c = {"bit_rate_value_minus1": r.ue(), "cpb_size_value_minus1": r.ue()}
        if sub_pic:
            r.ue()
            r.ue()
        c["cbr_flag"] = r.u1()
        cpbs.append(c)
    return cpbs


def hrd_parameters(r, common_inf_present, max_sub_layers_minus1):
    """hrd_parameters(), E.2.2. Für jede Teilschicht die CPB-Angaben; Raten und Größen in Bit bzw. Bit/s."""
    h = {"nal_hrd_parameters_present_flag": 0, "vcl_hrd_parameters_present_flag": 0,
         "sub_pic_hrd_params_present_flag": 0}
    if common_inf_present:
        h["nal_hrd_parameters_present_flag"] = r.u1()
        h["vcl_hrd_parameters_present_flag"] = r.u1()
        if h["nal_hrd_parameters_present_flag"] or h["vcl_hrd_parameters_present_flag"]:
            h["sub_pic_hrd_params_present_flag"] = r.u1()
            if h["sub_pic_hrd_params_present_flag"]:
                r.u(8)
                r.u(5)
                r.u1()
                r.u(5)
            h["bit_rate_scale"] = r.u(4)
            h["cpb_size_scale"] = r.u(4)
            if h["sub_pic_hrd_params_present_flag"]:
                r.u(4)
            h["initial_cpb_removal_delay_length"] = r.u(5) + 1
            h["au_cpb_removal_delay_length"] = r.u(5) + 1
            h["dpb_output_delay_length"] = r.u(5) + 1
    layers = []
    for _ in range(max_sub_layers_minus1 + 1):
        s = {"fixed_pic_rate_general_flag": r.u1()}
        s["fixed_pic_rate_within_cvs_flag"] = 1 if s["fixed_pic_rate_general_flag"] else r.u1()
        s["low_delay_hrd_flag"] = 0
        if s["fixed_pic_rate_within_cvs_flag"]:
            s["elemental_duration_in_tc_minus1"] = r.ue()
        else:
            s["low_delay_hrd_flag"] = r.u1()
        s["cpb_cnt"] = 1 if s["low_delay_hrd_flag"] else r.ue() + 1
        if h["nal_hrd_parameters_present_flag"]:
            s["nal"] = _sub_layer_hrd(r, s["cpb_cnt"], h["sub_pic_hrd_params_present_flag"])
        if h["vcl_hrd_parameters_present_flag"]:
            s["vcl"] = _sub_layer_hrd(r, s["cpb_cnt"], h["sub_pic_hrd_params_present_flag"])
        layers.append(s)
    h["sub_layers"] = layers
    for s in layers:
        for key in ("nal", "vcl"):
            for c in s.get(key, []):
                c["bit_rate"] = (c["bit_rate_value_minus1"] + 1) << (6 + h.get("bit_rate_scale", 0))
                c["cpb_size"] = (c["cpb_size_value_minus1"] + 1) << (4 + h.get("cpb_size_scale", 0))
    return h


def _vui(r, max_sub_layers_minus1):
    v = {"aspect_ratio_info_present_flag": r.u1()}
    if v["aspect_ratio_info_present_flag"]:
        v["aspect_ratio_idc"] = r.u(8)
        if v["aspect_ratio_idc"] == 255:
            v["sar_width"], v["sar_height"] = r.u(16), r.u(16)
    if r.u1():                                # overscan_info_present_flag
        v["overscan_appropriate_flag"] = r.u1()
    v["video_signal_type_present_flag"] = r.u1()
    if v["video_signal_type_present_flag"]:
        v["video_format"] = r.u(3)
        v["video_full_range_flag"] = r.u1()
        v["colour_description_present_flag"] = r.u1()
        if v["colour_description_present_flag"]:
            v["colour_primaries"] = r.u(8)
            v["transfer_characteristics"] = r.u(8)
            v["matrix_coeffs"] = r.u(8)
    if r.u1():                                # chroma_loc_info_present_flag
        v["chroma_sample_loc_type_top_field"] = r.ue()
        v["chroma_sample_loc_type_bottom_field"] = r.ue()
    v["neutral_chroma_indication_flag"] = r.u1()
    v["field_seq_flag"] = r.u1()
    v["frame_field_info_present_flag"] = r.u1()
    if r.u1():                                # default_display_window_flag
        v["default_display_window"] = [r.ue(), r.ue(), r.ue(), r.ue()]
    v["vui_timing_info_present_flag"] = r.u1()
    if v["vui_timing_info_present_flag"]:
        v["num_units_in_tick"] = r.u(32)
        v["time_scale"] = r.u(32)
        if r.u1():                            # vui_poc_proportional_to_timing_flag
            r.ue()
        v["vui_hrd_parameters_present_flag"] = r.u1()
        if v["vui_hrd_parameters_present_flag"]:
            v["hrd"] = hrd_parameters(r, 1, max_sub_layers_minus1)
    if r.u1():                                # bitstream_restriction_flag
        r.u1()
        r.u1()
        r.u1()
        v["min_spatial_segmentation_idc"] = r.ue()
        v["max_bytes_per_pic_denom"] = r.ue()
        v["max_bits_per_min_cu_denom"] = r.ue()
        r.ue()
        r.ue()
    return v


def parse_sps(ebsp):
    """SPS aus dem NAL-Payload (ohne 2-Byte-Header). Liest bis einschließlich VUI."""
    r = BitReader(ebsp_to_rbsp(ebsp))
    s = {"sps_video_parameter_set_id": r.u(4)}
    s["sps_max_sub_layers_minus1"] = r.u(3)
    s["sps_temporal_id_nesting_flag"] = r.u1()
    s["ptl"] = profile_tier_level(r, s["sps_max_sub_layers_minus1"])
    s["sps_seq_parameter_set_id"] = r.ue()
    s["chroma_format_idc"] = r.ue()
    s["separate_colour_plane_flag"] = r.u1() if s["chroma_format_idc"] == 3 else 0
    s["pic_width_in_luma_samples"] = r.ue()
    s["pic_height_in_luma_samples"] = r.ue()
    crop = [0, 0, 0, 0]
    if r.u1():                                # conformance_window_flag
        crop = [r.ue(), r.ue(), r.ue(), r.ue()]
    s["conformance_window"] = crop
    s["bit_depth_luma"] = r.ue() + 8
    s["bit_depth_chroma"] = r.ue() + 8
    s["log2_max_pic_order_cnt_lsb"] = r.ue() + 4
    ordering_all = r.u1()
    first = 0 if ordering_all else s["sps_max_sub_layers_minus1"]
    s["sps_max_dec_pic_buffering"] = []
    s["sps_max_num_reorder_pics"] = []
    for _ in range(first, s["sps_max_sub_layers_minus1"] + 1):
        s["sps_max_dec_pic_buffering"].append(r.ue() + 1)
        s["sps_max_num_reorder_pics"].append(r.ue())
        r.ue()                                # sps_max_latency_increase_plus1
    s["log2_min_luma_coding_block_size"] = r.ue() + 3
    s["log2_diff_max_min_luma_coding_block_size"] = r.ue()
    r.ue()
    r.ue()
    r.ue()
    r.ue()
    if r.u1():                                # scaling_list_enabled_flag
        if r.u1():                            # sps_scaling_list_data_present_flag
            _scaling_list_data(r)
    s["amp_enabled_flag"] = r.u1()
    s["sample_adaptive_offset_enabled_flag"] = r.u1()
    if r.u1():                                # pcm_enabled_flag
        r.u(4)
        r.u(4)
        r.ue()
        r.ue()
        r.u1()
    num_sets = r.ue()
    sets = []
    for i in range(num_sets):
        sets.append(_st_ref_pic_set(r, i, num_sets, sets))
    s["num_short_term_ref_pic_sets"] = num_sets
    s["long_term_ref_pics_present_flag"] = r.u1()
    if s["long_term_ref_pics_present_flag"]:
        for _ in range(r.ue()):
            r.u(s["log2_max_pic_order_cnt_lsb"])
            r.u1()
    s["sps_temporal_mvp_enabled_flag"] = r.u1()
    s["strong_intra_smoothing_enabled_flag"] = r.u1()
    s["vui_parameters_present_flag"] = r.u1()
    s["vui"] = _vui(r, s["sps_max_sub_layers_minus1"]) if s["vui_parameters_present_flag"] else {}
    # sichtbare Größe nach dem Konformitätsfenster (bei 4:2:0 zählen die Offsets doppelt)
    sub_w = 2 if s["chroma_format_idc"] in (1, 2) else 1
    sub_h = 2 if s["chroma_format_idc"] == 1 else 1
    s["width"] = s["pic_width_in_luma_samples"] - sub_w * (crop[0] + crop[1])
    s["height"] = s["pic_height_in_luma_samples"] - sub_h * (crop[2] + crop[3])
    ctb = 1 << (s["log2_min_luma_coding_block_size"] + s["log2_diff_max_min_luma_coding_block_size"])
    s["pic_size_in_ctbs"] = (-(-s["pic_width_in_luma_samples"] // ctb)) * (-(-s["pic_height_in_luma_samples"] // ctb))
    return s


def frame_rate(sps):
    """Bilder pro Sekunde aus der VUI (bei HEVC ohne Faktor 2 wie bei H.264) oder None."""
    v = (sps or {}).get("vui", {})
    if v.get("vui_timing_info_present_flag") and v.get("num_units_in_tick"):
        return v["time_scale"] / v["num_units_in_tick"]
    return None


def hrd_cpb(sps):
    """(Bitrate in Bit/s, CPB-Größe in Bit, CBR) des ersten NAL-HRD der höchsten Teilschicht oder None."""
    hrd = (sps or {}).get("vui", {}).get("hrd")
    if not hrd or not hrd.get("nal_hrd_parameters_present_flag"):
        return None
    c = hrd["sub_layers"][-1]["nal"][0]
    return c["bit_rate"], c["cpb_size"], bool(c["cbr_flag"])
