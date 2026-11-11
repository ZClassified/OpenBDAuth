"""Slice-Header (H.264 7.3.3, MVC-Variante H.7.3.3) inkl. Prüfung der CABAC-Alignment-Bits."""

from .bitstream import BitReader

SLICE_TYPE_CHARS = {0: "P", 1: "B", 2: "I", 3: "SP", 4: "SI"}


def _ref_list_mods(r, mvc):
    mods = []
    while True:
        idc = r.ue()
        if idc == 3:
            return mods
        if idc in (0, 1):
            mods.append((idc, r.ue()))
        elif idc == 2:
            mods.append((idc, r.ue()))
        elif mvc and idc in (4, 5):
            mods.append((idc, r.ue()))
        else:
            raise ValueError(f"ungültiger modification_of_pic_nums_idc {idc}")


def _pred_weight_table(r, chroma_array_type, n_l0, n_l1, is_b):
    r.ue()
    if chroma_array_type != 0:
        r.ue()
    for n in (n_l0, n_l1) if is_b else (n_l0,):
        for _ in range(n):
            if r.u1():
                r.se()
                r.se()
            if chroma_array_type != 0 and r.u1():
                for _ in range(4):
                    r.se()


def parse_slice_header(rbsp, nal, sps, pps):
    r = BitReader(rbsp)
    h = {}
    h["first_mb_in_slice"] = r.ue()
    st = r.ue()
    h["slice_type_raw"] = st
    st %= 5
    h["slice_type"] = SLICE_TYPE_CHARS[st]
    h["pic_parameter_set_id"] = r.ue()
    if sps.get("separate_colour_plane_flag"):
        r.u(2)
    h["frame_num"] = r.u(sps["log2_max_frame_num"])
    h["field_pic_flag"] = 0
    if not sps["frame_mbs_only_flag"]:
        h["field_pic_flag"] = r.u1()
        if h["field_pic_flag"]:
            h["bottom_field_flag"] = r.u1()
    is_mvc = nal.type in (20, 21)
    idr = nal.type == 5 or (is_mvc and nal.mvc and nal.mvc.get("non_idr_flag") == 0)
    h["idr"] = int(idr)
    if idr:
        h["idr_pic_id"] = r.ue()
    h["delta_pic_order_cnt_bottom"] = 0
    if sps["pic_order_cnt_type"] == 0:
        h["pic_order_cnt_lsb"] = r.u(sps["log2_max_pic_order_cnt_lsb"])
        if pps["bottom_field_pic_order_in_frame_present_flag"] and not h["field_pic_flag"]:
            h["delta_pic_order_cnt_bottom"] = r.se()
    elif sps["pic_order_cnt_type"] == 1 and not sps["delta_pic_order_always_zero_flag"]:
        h["delta_pic_order_cnt"] = [r.se()]
        if pps["bottom_field_pic_order_in_frame_present_flag"] and not h["field_pic_flag"]:
            h["delta_pic_order_cnt"].append(r.se())
    if pps["redundant_pic_cnt_present_flag"]:
        h["redundant_pic_cnt"] = r.ue()
    if st == 1:
        h["direct_spatial_mv_pred_flag"] = r.u1()
    n_l0 = pps["num_ref_idx_l0_default_active"]
    n_l1 = pps["num_ref_idx_l1_default_active"]
    if st in (0, 1, 3):
        if r.u1():
            n_l0 = r.ue() + 1
            if st == 1:
                n_l1 = r.ue() + 1
    if st in (2, 4):
        n_l0 = n_l1 = 0
    elif st != 1:
        n_l1 = 0
    h["num_ref_idx_l0_active"] = n_l0
    h["num_ref_idx_l1_active"] = n_l1
    h["mods_l0"] = []
    h["mods_l1"] = []
    if st not in (2, 4):
        if r.u1():
            h["mods_l0"] = _ref_list_mods(r, is_mvc)
        if st == 1 and r.u1():
            h["mods_l1"] = _ref_list_mods(r, is_mvc)
    if (pps["weighted_pred_flag"] and st in (0, 3)) or (pps["weighted_bipred_idc"] == 1 and st == 1):
        h["pred_weight_table"] = 1
        _pred_weight_table(r, sps["chroma_array_type"], n_l0, n_l1, st == 1)
    h["mmco"] = []
    if nal.ref_idc:
        if idr:
            h["no_output_of_prior_pics_flag"] = r.u1()
            h["long_term_reference_flag"] = r.u1()
        elif r.u1():
            while True:
                op = r.ue()
                if op == 0:
                    break
                args = []
                if op in (1, 3):
                    args.append(r.ue())
                if op == 2:
                    args.append(r.ue())
                if op in (3, 6):
                    args.append(r.ue())
                if op == 4:
                    args.append(r.ue())
                h["mmco"].append((op, *args))
    if pps["entropy_coding_mode_flag"] and st not in (2, 4):
        h["cabac_init_idc"] = r.ue()
    h["slice_qp"] = pps["pic_init_qp"] + r.se()
    if st in (3, 4):
        if st == 3:
            r.u1()
        r.se()
    if pps["deblocking_filter_control_present_flag"]:
        h["disable_deblocking_filter_idc"] = r.ue()
        if h["disable_deblocking_filter_idc"] != 1:
            h["slice_alpha_c0_offset_div2"] = r.se()
            h["slice_beta_offset_div2"] = r.se()
    h["header_bits"] = r.pos
    if pps["entropy_coding_mode_flag"]:
        ok = True
        while not r.byte_aligned():
            if r.u1() != 1:
                ok = False
        h["cabac_align_ok"] = ok
    return h
