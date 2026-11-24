"""Picture Parameter Set (H.265 7.3.2.3) – nur der Anfang, den der Slice-Header braucht."""

from mvctools.bitstream import BitReader, ebsp_to_rbsp


def parse_pps(ebsp):
    r = BitReader(ebsp_to_rbsp(ebsp))
    return {
        "pps_pic_parameter_set_id": r.ue(),
        "pps_seq_parameter_set_id": r.ue(),
        "dependent_slice_segments_enabled_flag": r.u1(),
        "output_flag_present_flag": r.u1(),
        "num_extra_slice_header_bits": r.u(3),
    }
