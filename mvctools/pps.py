"""PPS (H.264 7.3.2.2)."""

from .bitstream import BitReader, BitstreamError
from .sps import _scaling_list


def parse_pps(rbsp, sps_lookup):
    """sps_lookup(sps_id) liefert das referenzierte (Subset-)SPS oder None."""
    r = BitReader(rbsp)
    p = {}
    p["pic_parameter_set_id"] = r.ue()
    p["seq_parameter_set_id"] = r.ue()
    p["entropy_coding_mode_flag"] = r.u1()
    p["entropy"] = "CABAC" if p["entropy_coding_mode_flag"] else "CAVLC"
    p["bottom_field_pic_order_in_frame_present_flag"] = r.u1()
    p["num_slice_groups"] = r.ue() + 1
    if p["num_slice_groups"] > 1:
        raise BitstreamError("Slice Groups (FMO) werden nicht unterstützt")
    p["num_ref_idx_l0_default_active"] = r.ue() + 1
    p["num_ref_idx_l1_default_active"] = r.ue() + 1
    p["weighted_pred_flag"] = r.u1()
    p["weighted_bipred_idc"] = r.u(2)
    p["pic_init_qp"] = r.se() + 26
    p["pic_init_qs"] = r.se() + 26
    p["chroma_qp_index_offset"] = r.se()
    p["deblocking_filter_control_present_flag"] = r.u1()
    p["constrained_intra_pred_flag"] = r.u1()
    p["redundant_pic_cnt_present_flag"] = r.u1()
    p["transform_8x8_mode_flag"] = 0
    if r.more_rbsp_data():
        p["transform_8x8_mode_flag"] = r.u1()
        p["pic_scaling_matrix_present_flag"] = r.u1()
        if p["pic_scaling_matrix_present_flag"]:
            sps = sps_lookup(p["seq_parameter_set_id"]) or {}
            n = 6 + (2 if sps.get("chroma_format_idc", 1) != 3 else 6) * p["transform_8x8_mode_flag"]
            for i in range(n):
                if r.u1():
                    _scaling_list(r, 16 if i < 6 else 64)
        p["second_chroma_qp_index_offset"] = r.se()
    return p
