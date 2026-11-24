"""Anfang des Slice-Segment-Headers (H.265 7.3.6.1): erstes Segment eines Bildes, Bildtyp."""

from mvctools.bitstream import BitReader, ebsp_to_rbsp

from .nal import is_irap

SLICE_TYPES = {0: "B", 1: "P", 2: "I"}


def first_slice_flag(ebsp):
    """first_slice_segment_in_pic_flag (erstes Bit nach dem NAL-Header)."""
    return bool(ebsp) and (ebsp[0] >> 7) & 1


def parse_first_slice(ebsp, nal_type, pps_by_id):
    """Für das erste Segment eines Bildes: PPS-ID und Bildtyp ("I", "P", "B"); None, wenn der PPS fehlt."""
    r = BitReader(ebsp_to_rbsp(ebsp))
    r.u1()                                    # first_slice_segment_in_pic_flag (= 1)
    if is_irap(nal_type):
        r.u1()                                # no_output_of_prior_pics_flag
    pps_id = r.ue()
    pps = pps_by_id.get(pps_id)
    if pps is None:
        return None
    r.u(pps["num_extra_slice_header_bits"])
    return {"pps_id": pps_id, "slice_type": SLICE_TYPES.get(r.ue(), "?")}
