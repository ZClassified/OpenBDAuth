# modules/udf250_writer.py
"""
Pure Python UDF 2.50 Disc Image Master Engine für OpenBDAuth.
Erzeugt standardkonforme Blu-ray UDF 2.50 ISO-Images nach BD-ROM Part 3 / Profile 5.0:
- Unterstützt volles physikalisches Extent-Interleaving für stereoskopische 3D-Streams (SSIF / MVC).
- Ermöglicht 3D-Blu-rays MIT interaktiven Menüs, ohne doppelte Nutzdatenblöcke auf der Disc zu speichern.
- Funktioniert vollständig ohne externe Abhängigkeiten (kein IMAPI2FS, kein ImgBurn, kein PowerShell-Mount).
"""

import os
import struct
import datetime
from typing import List, Tuple, Dict, Optional, Callable


SECTOR_SIZE = 2048
ALLOC_BLOCK_SIZE = 64 * 1024  # 32 Sektoren
METADATA_START_ADDR = (640 * 1024) // SECTOR_SIZE  # Sektor 320
PARTITION_START_ADDR = (576 * 1024) // SECTOR_SIZE  # Sektor 288
MAX_EXTENTS_IN_EXTFILE = (SECTOR_SIZE - 216 - 32) // 16  # 112 Extents
MAX_EXTENTS_IN_EXTCONT = (SECTOR_SIZE - 24 - 32) // 16   # 124 Extents
# Extent-Länge: 30 Bit (die oberen 2 Bit sind der Extent-Typ), ganze Sektoren -> knapp 1 GiB pro Extent
MAX_EXTENT_LEN = (1 << 30) - SECTOR_SIZE
# Ein Ordner belegt genau einen Sektor mit File Identifier Descriptors: 40 Bytes für den Eintrag des übergeordneten
# Ordners, 52 Bytes je Datei mit einem Namen wie „00001.m2ts“ -> höchstens 38 Clips in BDMV/STREAM (Konzept 11.2.6)
PARENT_FID_LEN = 40
MAX_DIR_ENTRIES = (SECTOR_SIZE - PARENT_FID_LEN) // 52

# CRC-16 CCITT
CRC16_TABLE = [
    0x0000, 0x1021, 0x2042, 0x3063, 0x4084, 0x50A5, 0x60C6, 0x70E7, 0x8108, 0x9129, 0xA14A, 0xB16B, 0xC18C, 0xD1AD,
    0xE1CE, 0xF1EF, 0x1231, 0x0210, 0x3273, 0x2252, 0x52B5, 0x4294, 0x72F7, 0x62D6, 0x9339, 0x8318, 0xB37B, 0xA35A,
    0xD3BD, 0xC39C, 0xF3FF, 0xE3DE, 0x2462, 0x3443, 0x0420, 0x1401, 0x64E6, 0x74C7, 0x44A4, 0x5485, 0xA56A, 0xB54B,
    0x8528, 0x9509, 0xE5EE, 0xF5CF, 0xC5AC, 0xD58D, 0x3653, 0x2672, 0x1611, 0x0630, 0x76D7, 0x66F6, 0x5695, 0x46B4,
    0xB75B, 0xA77A, 0x9719, 0x8738, 0xF7DF, 0xE7FE, 0xD79D, 0xC7BC, 0x48C4, 0x58E5, 0x6886, 0x78A7, 0x0840, 0x1861,
    0x2802, 0x3823, 0xC9CC, 0xD9ED, 0xE98E, 0xF9AF, 0x8948, 0x9969, 0xA90A, 0xB92B, 0x5AF5, 0x4AD4, 0x7AB7, 0x6A96,
    0x1A71, 0x0A50, 0x3A33, 0x2A12, 0xDBFD, 0xCBDC, 0xFBBF, 0xEB9E, 0x9B79, 0x8B58, 0xBB3B, 0xAB1A, 0x6CA6, 0x7C87,
    0x4CE4, 0x5CC5, 0x2C22, 0x3C03, 0x0C60, 0x1C41, 0xEDAE, 0xFD8F, 0xCDEC, 0xDDCD, 0xAD2A, 0xBD0B, 0x8D68, 0x9D49,
    0x7E97, 0x6EB6, 0x5ED5, 0x4EF4, 0x3E13, 0x2E32, 0x1E51, 0x0E70, 0xFF9F, 0xEFBE, 0xDFDD, 0xCFFC, 0xBF1B, 0xAF3A,
    0x9F59, 0x8F78, 0x9188, 0x81A9, 0xB1CA, 0xA1EB, 0xD10C, 0xC12D, 0xF14E, 0xE16F, 0x1080, 0x00A1, 0x30C2, 0x20E3,
    0x5004, 0x4025, 0x7046, 0x6067, 0x83B9, 0x9398, 0xA3FB, 0xB3DA, 0xC33D, 0xD31C, 0xE37F, 0xF35E, 0x02B1, 0x1290,
    0x22F3, 0x32D2, 0x4235, 0x5214, 0x6277, 0x7256, 0xB5EA, 0xA5CB, 0x95A8, 0x8589, 0xF56E, 0xE54F, 0xD52C, 0xC50D,
    0x34E2, 0x24C3, 0x14A0, 0x0481, 0x7466, 0x6447, 0x5424, 0x4405, 0xA7DB, 0xB7FA, 0x8799, 0x97B8, 0xE75F, 0xF77E,
    0xC71D, 0xD73C, 0x26D3, 0x36F2, 0x0691, 0x16B0, 0x6657, 0x7676, 0x4615, 0x5634, 0xD94C, 0xC96D, 0xF90E, 0xE92F,
    0x99C8, 0x89E9, 0xB98A, 0xA9AB, 0x5844, 0x4865, 0x7806, 0x6827, 0x18C0, 0x08E1, 0x3882, 0x28A3, 0xCB7D, 0xDB5C,
    0xEB3F, 0xFB1E, 0x8BF9, 0x9BD8, 0xABBB, 0xBB9A, 0x4A75, 0x5A54, 0x6A37, 0x7A16, 0x0AF1, 0x1AD0, 0x2AB3, 0x3A92,
    0xFD2E, 0xED0F, 0xDD6C, 0xCD4D, 0xBDAA, 0xAD8B, 0x9DE8, 0x8DC9, 0x7C26, 0x6C07, 0x5C64, 0x4C45, 0x3CA2, 0x2C83,
    0x1CE0, 0x0CC1, 0xEF1F, 0xFF3E, 0xCF5D, 0xDF7C, 0xAF9B, 0xBFBA, 0x8FD9, 0x9FF8, 0x6E17, 0x7E36, 0x4E55, 0x5E74,
    0x2E93, 0x3EB2, 0x0ED1, 0x1EF0
]


def crc16(data: bytes) -> int:
    crc = 0
    for b in data:
        crc = ((crc << 8) & 0xFFFF) ^ CRC16_TABLE[((crc >> 8) ^ b) & 0xFF]
    return crc


def write_desc_tag(tag_id: int, tag_loc: int, desc_crc: int, desc_crc_len: int) -> bytes:
    tag = bytearray(16)
    struct.pack_into('<HHBBHHHI', tag, 0,
                     tag_id,
                     3,   # version 3 (UDF 2.50)
                     0,   # checksum placeholder
                     0,   # reserved
                     1,   # tag serial number
                     desc_crc,
                     desc_crc_len,
                     tag_loc)
    cksum = sum(tag) & 0xFF
    tag[4] = cksum
    return bytes(tag)


def pack_descriptor(tag_id: int, tag_loc: int, payload: bytes, total_len: int = 512) -> bytes:
    full_payload = payload.ljust(total_len - 16, b'\x00')
    c = crc16(full_payload)
    tag = write_desc_tag(tag_id, tag_loc, c, len(full_payload))
    block = tag + full_payload
    return block.ljust(SECTOR_SIZE, b'\x00')


def make_timestamp(dt: datetime.datetime) -> bytes:
    type_and_tz = (1 << 12)
    return struct.pack('<HhBBBBBBBB',
                       type_and_tz,
                       dt.year,
                       dt.month,
                       dt.day,
                       dt.hour,
                       dt.minute,
                       dt.second,
                       0, 0, 0)


def dstring(text: str, length: int) -> bytes:
    raw = text.encode('latin1')
    if len(raw) >= length:
        raw = raw[:length - 1]
    content_len = len(raw) + 1
    pad_len = length - 1 - content_len
    return bytes([8]) + raw + b'\x00' * pad_len + bytes([content_len])


def udf_string(text: str, length: int) -> bytes:
    raw = text.encode('latin1')
    res = bytearray(length)
    res[1:1+len(raw)] = raw
    res[length - 8] = 0x50
    res[length - 7] = 0x02
    return bytes(res)


def write_long_ad(length: int, pos: int, partition: int = 0, obj_id: int = 0) -> bytes:
    return struct.pack('<IIHHI', length, pos, partition, 0, obj_id)


def split_extent(lbn: int, size: int) -> List[Tuple[int, int]]:
    """Teilt einen zusammenhängenden Bereich in Extents von höchstens MAX_EXTENT_LEN Bytes.
    Ein einzelner Extent über 1 GiB würde in die Typ-Bits überlaufen (Datei unlesbar)."""
    extents = []
    while size > MAX_EXTENT_LEN:
        extents.append((lbn, MAX_EXTENT_LEN))
        lbn += MAX_EXTENT_LEN // SECTOR_SIZE
        size -= MAX_EXTENT_LEN
    extents.append((lbn, size))
    return extents


def fid_len(name: str) -> int:
    """Länge des File Identifier Descriptors eines Eintrags (Tag, Kopf, Name als d-String, auf 4 Bytes aufgefüllt)."""
    data = 22 + 1 + len(name.encode('latin1'))
    return 16 + data + (4 - data % 4) % 4


class DirectoryTooLargeError(ValueError):
    """Ein Ordner hat mehr Einträge, als in einen Sektor passen (Konzept 11.2.6)."""


class UDFEntry:
    def __init__(self, name: str, is_dir: bool, obj_id: int, is_realtime: bool = False):
        self.name = name
        self.is_dir = is_dir
        self.obj_id = obj_id
        self.is_realtime = is_realtime
        self.subdirs: List['UDFEntry'] = []
        self.files: List['UDFEntry'] = []
        self.parent: Optional['UDFEntry'] = None
        self.sector_num = 0
        self.file_size = 0
        self.extents: List[Tuple[int, int]] = []
        self.source_path: Optional[str] = None
        self.source_bytes: Optional[bytes] = None
        self.source_iso_slice: Optional[Tuple[str, int, int]] = None

    def add_child(self, child: 'UDFEntry'):
        child.parent = self
        if child.is_dir:
            self.subdirs.append(child)
        else:
            self.files.append(child)

    def path(self) -> str:
        parts, entry = [], self
        while entry.parent is not None:
            parts.append(entry.name)
            entry = entry.parent
        return "/".join(reversed(parts))

    def get_child(self, name: str) -> Optional['UDFEntry']:
        for d in self.subdirs:
            if d.name.upper() == name.upper():
                return d
        for f in self.files:
            if f.name.upper() == name.upper():
                return f
        return None


class UDF250Writer:
    def __init__(self, output_path: str, volume_label: str = "BD_DISC", disk_size: int = 0):
        self.output_path = output_path
        self.volume_label = volume_label if volume_label else "BD_DISC"
        self.disk_size = disk_size
        self.app_id = "*tsMuxeR 2.7.0"
        self.imp_id = "*tsMuxeR 7006ba3"
        self.vol_id = 0x7006BA3
        self.now = datetime.datetime.now()

        self.root = UDFEntry("", True, 0)
        self.system_stream_dir = UDFEntry("", True, 0)
        self.metadata_mapping_file = UDFEntry("*UDF Unique ID Mapping Data", False, 0)
        self.system_stream_dir.add_child(self.metadata_mapping_file)

        self.obj_uniq_id = 16
        self.metadata_len = 0x30000  # 192KB = 96 Sektoren
        self.partition_start_lbn = PARTITION_START_ADDR  # 288
        self.metadata_lbn = METADATA_START_ADDR  # 320
        self.metadata_mirror_lbn = 0
        self.partition_end_lbn = 0
        self.system_stream_lbn = 0
        self.mapping_entries: Dict[int, Tuple[int, int]] = {}
        self.total_files = 0
        self.total_dirs = 0
        self._tag_base_addr = 0
        self._cur_metadata_sec = 0

    def get_or_create_dir(self, path: str) -> UDFEntry:
        parts = [p for p in path.replace('\\', '/').strip('/').split('/') if p]
        curr = self.root
        for part in parts:
            child = curr.get_child(part)
            if not child:
                child = UDFEntry(part, True, self.obj_uniq_id)
                self.obj_uniq_id += 1
                curr.add_child(child)
            curr = child
        return curr

    def add_file(self, rel_path: str, src_path: Optional[str] = None, data: Optional[bytes] = None, is_realtime: bool = False) -> UDFEntry:
        parts = [p for p in rel_path.replace('\\', '/').strip('/').split('/') if p]
        dir_parts = parts[:-1]
        file_name = parts[-1]

        parent = self.root
        for part in dir_parts:
            child = parent.get_child(part)
            if not child:
                child = UDFEntry(part, True, self.obj_uniq_id)
                self.obj_uniq_id += 1
                parent.add_child(child)
            parent = child

        child = parent.get_child(file_name)
        if not child:
            child = UDFEntry(file_name, False, self.obj_uniq_id, is_realtime=is_realtime)
            self.obj_uniq_id += 1
            parent.add_child(child)

        child.source_path = src_path
        child.source_bytes = data
        if data is not None:
            child.file_size = len(data)
        elif src_path is not None and os.path.exists(src_path):
            child.file_size = os.path.getsize(src_path)
        return child

    def add_interleaved_3d(self,
                           base_rel_path: str,
                           mvc_rel_path: str,
                           ssif_rel_path: str,
                           ssif_source_path: str,
                           base_extents: List[Tuple[int, int]],
                           mvc_extents: List[Tuple[int, int]],
                           ssif_slice: Optional[Tuple[str, int, int]] = None):
        """
        Registriert einen stereoskopischen 3D-Titel für physikalisches UDF-Extent-Interleaving:
        - ssif_rel_path: BDMV/STREAM/SSIF/00000.ssif (wird physisch als zusammenhängender Stream geschrieben)
        - base_rel_path: BDMV/STREAM/00000.m2ts (referenziert die Basis-Extents innerhalb des SSIF-Streams)
        - mvc_rel_path: BDMV/STREAM/00001.m2ts (referenziert die MVC-Extents innerhalb des SSIF-Streams)
        """
        ssif_entry = self.add_file(ssif_rel_path, src_path=ssif_source_path, is_realtime=True)
        if ssif_slice:
            ssif_entry.source_iso_slice = ssif_slice
            ssif_entry.file_size = ssif_slice[2]

        base_entry = self.add_file(base_rel_path, is_realtime=True)
        base_entry.file_size = sum(sz for _, sz in base_extents)

        mvc_entry = self.add_file(mvc_rel_path, is_realtime=True)
        mvc_entry.file_size = sum(sz for _, sz in mvc_extents)

        ssif_entry._is_3d_ssif = True
        base_entry._is_3d_base = True
        base_entry._orig_extents = base_extents
        mvc_entry._is_3d_mvc = True
        mvc_entry._orig_extents = mvc_extents
        ssif_entry._base_child = base_entry
        ssif_entry._mvc_child = mvc_entry

    @staticmethod
    def _entry_sectors(entity: UDFEntry, extent_count: int) -> int:
        if entity.is_dir:
            return 2
        if extent_count <= MAX_EXTENTS_IN_EXTFILE:
            return 1
        sz = extent_count - 1 - MAX_EXTENTS_IN_EXTFILE
        return 1 + (sz + MAX_EXTENTS_IN_EXTCONT - 1) // MAX_EXTENTS_IN_EXTCONT

    def _count_metadata_sectors(self, entity: UDFEntry) -> int:
        """Sektoren, die _allocate_entity für diesen Teilbaum belegen wird – noch bevor die Extents feststehen."""
        if hasattr(entity, '_orig_extents'):
            extent_count = len(entity._orig_extents)
        else:
            extent_count = len(split_extent(0, entity.file_size))
        total = self._entry_sectors(entity, extent_count)
        for child in entity.files + entity.subdirs:
            total += self._count_metadata_sectors(child)
        return total

    def _allocate_entity(self, entity: UDFEntry, sector_num: int) -> int:
        if not entity.is_dir and entity.obj_id != 0:
            self.total_files += 1
        elif entity.is_dir:
            self.total_dirs += 1

        entity.sector_num = sector_num
        sector_num += self._entry_sectors(entity, len(entity.extents))
        if entity.obj_id != 0:
            parent_sec = entity.parent.sector_num if entity.parent else 0
            self.mapping_entries[entity.obj_id] = (parent_sec, entity.sector_num)

        for f in entity.files:
            sector_num = self._allocate_entity(f, sector_num)
        for d in entity.subdirs:
            sector_num = self._allocate_entity(d, sector_num)
        return sector_num

    def check_directories(self):
        """Vor dem Schreiben: Jeder Ordner muss mit allen Einträgen in einen Sektor passen (_serialize_dir).
        Größere Ordner sind nach UDF erlaubt, hier aber nicht umgesetzt (Konzept 11.2.6)."""
        def walk(entry: UDFEntry):
            children = entry.files + entry.subdirs
            if PARENT_FID_LEN + sum(fid_len(c.name) for c in children) > SECTOR_SIZE:
                raise DirectoryTooLargeError(
                    f"Ordner {entry.path()} hat {len(children)} Einträge – die ISO fasst höchstens "
                    f"{MAX_DIR_ENTRIES} Clips pro Ordner. Der BDMV-Ordner bleibt erhalten.")
            for d in entry.subdirs:
                walk(d)
        walk(self.root)

    def _tag_loc(self, abs_sec: int) -> int:
        return abs_sec - self._tag_base_addr

    def _write_extended_file_entry(self,
                                  fout,
                                  is_named_stream: bool,
                                  obj_id: int,
                                  file_type: int,
                                  info_len: int,
                                  alloc_pos: int,
                                  link_count: int,
                                  extents: Optional[List[Tuple[int, int]]] = None) -> int:
        cur_pos = fout.tell()
        abs_sec = cur_pos // SECTOR_SIZE
        tag_loc = self._tag_loc(abs_sec)

        buf = bytearray(SECTOR_SIZE)
        if file_type in (5, 249):
            icb_flags = 0x0021
        else:
            icb_flags = 0x0020
        if is_named_stream:
            icb_flags += 0x2000
        struct.pack_into('<IHHHBB6sH', buf, 16, 0, 4, 0, 1, 0, file_type, b'\x00'*6, icb_flags)

        struct.pack_into('<II', buf, 36, 0xFFFFFFFF, 0xFFFFFFFF)
        if file_type >= 250:
            perms = 0x0000
            assert link_count == 0
        elif file_type in (5, 249):
            perms = 0x1084
            assert link_count == 1
        else:
            perms = 0x14A5
        struct.pack_into('<IH', buf, 44, perms, link_count)

        struct.pack_into('<QQ', buf, 56, info_len, info_len)
        blocks_rec = (info_len + SECTOR_SIZE - 1) // SECTOR_SIZE
        struct.pack_into('<II', buf, 72, blocks_rec, 0)

        ts_bytes = make_timestamp(self.now)
        buf[80:92] = ts_bytes
        buf[92:104] = ts_bytes
        buf[104:116] = ts_bytes
        buf[116:128] = ts_bytes
        struct.pack_into('<I', buf, 128, 1)

        buf[169:169+len(self.imp_id)] = self.imp_id.encode('latin1')
        buf[200] = obj_id

        sectors_written = 0
        if file_type not in (5, 249):
            struct.pack_into('<III', buf, 212, 8, info_len, alloc_pos)
            c = crc16(buf[16:224])
            buf[:16] = write_desc_tag(266, tag_loc, c, 224 - 16)
            fout.write(buf)
            sectors_written += 1
        elif extents is None or len(extents) == 0:
            struct.pack_into('<I', buf, 212, 16)
            buf[216:232] = write_long_ad(info_len, alloc_pos, 0, 0)
            c = crc16(buf[16:232])
            buf[:16] = write_desc_tag(266, tag_loc, c, 232 - 16)
            fout.write(buf)
            sectors_written += 1
        else:
            idx_end = min(MAX_EXTENTS_IN_EXTFILE, len(extents))
            if len(extents) - idx_end == 1:
                idx_end += 1
            alloc_bytes_len = 16 * idx_end
            has_cont = idx_end < len(extents)
            if has_cont:
                alloc_bytes_len += 16
            struct.pack_into('<I', buf, 212, alloc_bytes_len)

            cpos = 216
            for i in range(idx_end):
                elbn, esz = extents[i]
                if esz > MAX_EXTENT_LEN:
                    raise ValueError(f"Extent mit {esz} Bytes ist länger als erlaubt ({MAX_EXTENT_LEN})")
                buf[cpos:cpos+16] = write_long_ad(esz, elbn, 0, 0)
                cpos += 16
            if has_cont:
                buf[cpos:cpos+16] = write_long_ad(SECTOR_SIZE | 0xC0000000, tag_loc + 1, 1, 0)
                cpos += 16
            c = crc16(buf[16:cpos])
            buf[:16] = write_desc_tag(266, tag_loc, c, cpos - 16)
            fout.write(buf)
            sectors_written += 1

            idx_start = idx_end
            while idx_start < len(extents):
                idx_end = min(idx_start + MAX_EXTENTS_IN_EXTCONT, len(extents))
                if len(extents) - idx_end == 1:
                    idx_end += 1
                cbuf = bytearray(SECTOR_SIZE)
                c_tag_loc = self._tag_loc(fout.tell() // SECTOR_SIZE)
                c_has_cont = idx_end < len(extents)
                cpos = 24
                for i in range(idx_start, idx_end):
                    elbn, esz = extents[i]
                    if esz > MAX_EXTENT_LEN:
                        raise ValueError(f"Extent mit {esz} Bytes ist länger als erlaubt ({MAX_EXTENT_LEN})")
                    cbuf[cpos:cpos+16] = write_long_ad(esz, elbn, 0, 0)
                    cpos += 16
                if c_has_cont:
                    cbuf[cpos:cpos+16] = write_long_ad(SECTOR_SIZE | 0xC0000000, c_tag_loc + 1, 1, 0)
                    cpos += 16
                alloc_len = cpos - 24
                struct.pack_into('<I', cbuf, 20, alloc_len)
                c = crc16(cbuf[16:cpos])
                cbuf[:16] = write_desc_tag(258, c_tag_loc, c, cpos - 16)
                fout.write(cbuf)
                sectors_written += 1
                idx_start = idx_end

        return sectors_written

    def _serialize_dir(self, fout, entry: UDFEntry):
        buf = bytearray(SECTOR_SIZE)
        writer_pos = 0

        parent_loc = self._tag_loc(fout.tell() // SECTOR_SIZE + 1)
        parent_id = entry.parent.obj_id if entry.parent else 0
        parent_sec = entry.parent.sector_num if entry.parent else 2

        fid_hdr = bytearray(38)
        struct.pack_into('<HBBI', fid_hdr, 16, 1, 0x0A, 0, 0x0800)
        fid_hdr[20:36] = write_long_ad(0x0800, parent_sec, 1, parent_id)
        struct.pack_into('<H', fid_hdr, 36, 0)

        # Die Füllbytes auf 4 Bytes gehören zum Deskriptor und zählen zur CRC-Länge (wie bei tsMuxeR: 24)
        parent_fid_data = fid_hdr[16:38] + b'\x00' * 2
        c = crc16(parent_fid_data)
        fid_tag = write_desc_tag(257, parent_loc, c, len(parent_fid_data))
        buf[writer_pos:writer_pos+16] = fid_tag
        buf[writer_pos+16:writer_pos+16+len(parent_fid_data)] = parent_fid_data
        writer_pos += 16 + len(parent_fid_data)

        children = entry.files + entry.subdirs
        for child in children:
            child_loc = self._tag_loc(fout.tell() // SECTOR_SIZE + 1)
            char_byte = 0x02 if child.is_dir else 0x00
            name_dstr = bytes([8]) + child.name.encode('latin1')
            l_fi = len(name_dstr)

            fid_hdr = bytearray(38)
            struct.pack_into('<HBBI', fid_hdr, 16, 1, char_byte, l_fi, 0x0800)
            fid_hdr[20:36] = write_long_ad(0x0800, child.sector_num, 1, child.obj_id)
            struct.pack_into('<H', fid_hdr, 36, 0)

            full_fid_data = fid_hdr[16:38] + name_dstr
            pad = (4 - len(full_fid_data) % 4) % 4
            if pad > 0:
                full_fid_data += b'\x00' * pad

            c = crc16(full_fid_data)
            fid_tag = write_desc_tag(257, child_loc, c, len(full_fid_data))

            tot_len = 16 + len(full_fid_data)
            buf[writer_pos:writer_pos+16] = fid_tag
            buf[writer_pos+16:writer_pos+tot_len] = full_fid_data
            writer_pos += tot_len

        if writer_pos > SECTOR_SIZE:
            raise DirectoryTooLargeError(f"Ordner {entry.path()} passt nicht in die ISO")

        self._write_extended_file_entry(fout, False, entry.obj_id, 4, writer_pos, entry.sector_num + 1, len(entry.subdirs) + 1)
        fout.write(buf)

    def _write_entity(self, fout, entry: UDFEntry):
        meta_offset = self._cur_metadata_sec
        fout.seek((meta_offset + entry.sector_num) * SECTOR_SIZE)
        if entry.is_dir:
            self._serialize_dir(fout, entry)
        else:
            ftype = 249 if entry.is_realtime else 5
            self._write_extended_file_entry(fout, False, entry.obj_id, ftype, entry.file_size, entry.sector_num, 1, entry.extents)

        for f in entry.files:
            self._write_entity(fout, f)
        for d in entry.subdirs:
            self._write_entity(fout, d)

    def _write_metadata(self, fout, start_lbn: int):
        fout.seek(start_lbn * SECTOR_SIZE)
        self._cur_metadata_sec = start_lbn

        fsd = bytearray(512)
        fsd[16:28] = make_timestamp(self.now)
        struct.pack_into('<HHIIII', fsd, 28, 3, 3, 1, 1, 0, 0)
        fsd[48] = 0
        fsd[49:49+len("OSTA Compressed Unicode")] = b"OSTA Compressed Unicode"
        fsd[112:112+128] = dstring(self.volume_label, 128)
        fsd[240] = 0
        fsd[241:241+len("OSTA Compressed Unicode")] = b"OSTA Compressed Unicode"
        fsd[304:304+32] = dstring(self.volume_label, 32)
        fsd[400:416] = write_long_ad(0x0800, 2, 1, 0)
        fsd[416:448] = udf_string("*OSTA UDF Compliant", 32)
        fsd[442] = 0x03
        fsd[448:464] = write_long_ad(0, 0, 0, 0)
        fsd[464:480] = write_long_ad(0x0800, self.system_stream_lbn, 1, 0)

        c = crc16(fsd[16:512])
        fsd[:16] = write_desc_tag(256, 0, c, 512 - 16)
        fout.write(bytes(fsd).ljust(SECTOR_SIZE, b'\x00'))

        term_buf = bytearray(512)
        c = crc16(term_buf[16:512])
        term_buf[:16] = write_desc_tag(8, 1, c, 512 - 16)
        fout.write(term_buf.ljust(SECTOR_SIZE, b'\x00'))

        self._write_entity(fout, self.root)
        self._write_entity(fout, self.system_stream_dir)

    def build_iso(self, progress_callback=None):
        def _log(msg):
            if progress_callback:
                progress_callback(msg)
            else:
                print(msg)

        self.check_directories()
        _log("Initialisiere UDF 2.50 Disc Image...")
        with open(self.output_path, 'wb') as fout:
            fout.write(b'\x00' * (32 * 1024))
            fout.write(b'\x00BEA01\x01'.ljust(SECTOR_SIZE, b'\x00'))
            fout.write(b'\x00NSR03\x01'.ljust(SECTOR_SIZE, b'\x00'))
            fout.write(b'\x00TEA01\x01'.ljust(SECTOR_SIZE, b'\x00'))

            pad_to_576k = (576 * 1024) - fout.tell()
            if pad_to_576k > 0:
                fout.write(b'\x00' * pad_to_576k)
            assert fout.tell() == 576 * 1024

            fout.write(b'\x00' * (64 * 1024))
            assert fout.tell() == 640 * 1024

            # Dateieinträge hinter dem Ende der Metadatendatei sind für Player unsichtbar (Dateien mit 0 Byte)
            # und überschreiben die Unique-ID-Tabelle. Kleine Discs behalten die bewährten 96 Sektoren.
            needed = (2 + self._count_metadata_sectors(self.root)
                      + self._count_metadata_sectors(self.system_stream_dir)) * SECTOR_SIZE
            if needed > self.metadata_len:
                self.metadata_len = (needed + ALLOC_BLOCK_SIZE - 1) // ALLOC_BLOCK_SIZE * ALLOC_BLOCK_SIZE
                _log(f"Metadatenbereich auf {self.metadata_len // SECTOR_SIZE} Sektoren vergrößert")

            fout.write(b'\x00' * (self.metadata_len + ALLOC_BLOCK_SIZE))

            payload_start_sec = fout.tell() // SECTOR_SIZE
            assert payload_start_sec == METADATA_START_ADDR + (self.metadata_len + ALLOC_BLOCK_SIZE) // SECTOR_SIZE

            all_files: List[UDFEntry] = []
            def collect_files(entry: UDFEntry):
                for f in entry.files:
                    if f.name != "*UDF Unique ID Mapping Data":
                        all_files.append(f)
                for d in entry.subdirs:
                    collect_files(d)
            collect_files(self.root)

            ssif_files = [f for f in all_files if getattr(f, '_is_3d_ssif', False)]
            regular_files = [f for f in all_files if not getattr(f, '_is_3d_ssif', False) and not getattr(f, '_is_3d_base', False) and not getattr(f, '_is_3d_mvc', False)]

            m2ts_files = [f for f in regular_files if f.name.lower().endswith('.m2ts')]
            small_files = [f for f in regular_files if not f.name.lower().endswith('.m2ts')]

            write_queue = ssif_files + m2ts_files + small_files

            _log(f"Schreibe {len(write_queue)} Nutzdaten-Dateien in das ISO...")
            for entry in write_queue:
                start_sec = fout.tell() // SECTOR_SIZE
                rel_lbn = start_sec - self.partition_start_lbn

                if getattr(entry, '_is_3d_ssif', False):
                    _log(f"  Schreibe 3D Interleaved Stream: {entry.name} ({entry.file_size} Bytes)...")
                    if entry.source_iso_slice:
                        slice_iso, s_off, s_len = entry.source_iso_slice
                        with open(slice_iso, 'rb') as s_in:
                            s_in.seek(s_off)
                            copied = 0
                            buf_size = 1024 * 1024 * 4
                            while copied < s_len:
                                to_read = min(buf_size, s_len - copied)
                                chunk = s_in.read(to_read)
                                fout.write(chunk)
                                copied += len(chunk)
                    elif entry.source_path:
                        with open(entry.source_path, 'rb') as s_in:
                            while True:
                                chunk = s_in.read(1024 * 1024 * 4)
                                if not chunk:
                                    break
                                fout.write(chunk)

                    entry.extents = split_extent(rel_lbn, entry.file_size)
                    base_e = entry._base_child
                    mvc_e = entry._mvc_child

                    orig_first_lbn = min(mvc_e._orig_extents[0][0], base_e._orig_extents[0][0])
                    base_e.extents = [(rel_lbn + (olbn - orig_first_lbn), osz) for olbn, osz in base_e._orig_extents]
                    mvc_e.extents = [(rel_lbn + (olbn - orig_first_lbn), osz) for olbn, osz in mvc_e._orig_extents]
                else:
                    if entry.source_bytes is not None:
                        fout.write(entry.source_bytes)
                    elif entry.source_path and os.path.exists(entry.source_path):
                        with open(entry.source_path, 'rb') as s_in:
                            while True:
                                chunk = s_in.read(1024 * 1024 * 2)
                                if not chunk:
                                    break
                                fout.write(chunk)

                    rem = entry.file_size % SECTOR_SIZE
                    if rem > 0:
                        fout.write(b'\x00' * (SECTOR_SIZE - rem))

                    entry.extents = split_extent(rel_lbn, entry.file_size)

            while (fout.tell() % ALLOC_BLOCK_SIZE) != (1024 * 62):
                fout.write(b'\x00' * SECTOR_SIZE)

            self.metadata_mirror_lbn = (fout.tell() // SECTOR_SIZE) + 1
            self._tag_base_addr = self.partition_start_lbn
            self._write_extended_file_entry(fout, False, 0, 251, self.metadata_len, self.metadata_mirror_lbn - self.partition_start_lbn, 0)

            fout.write(b'\x00' * self.metadata_len)
            self.partition_end_lbn = fout.tell() // SECTOR_SIZE
            fout.write(b'\x00' * (32 * SECTOR_SIZE))

            _log("Serialisiere UDF 2.50 Metadaten und Deskriptoren...")
            sector_num = 2
            self.system_stream_lbn = self._allocate_entity(self.root, sector_num)
            metadata_end = self._allocate_entity(self.system_stream_dir, self.system_stream_lbn)
            if metadata_end > self.metadata_len // SECTOR_SIZE:
                raise ValueError(f"UDF-Metadaten brauchen {metadata_end} Sektoren, reserviert sind {self.metadata_len // SECTOR_SIZE}")

            mapping_offset = (METADATA_START_ADDR * SECTOR_SIZE) + self.metadata_len
            fout.seek(mapping_offset)
            map_buf = bytearray(ALLOC_BLOCK_SIZE)
            map_buf[:len(self.imp_id)] = self.imp_id.encode('latin1')
            struct.pack_into('<IIII', map_buf, 32, 0, len(self.mapping_entries), 0, 0)
            mpos = 48
            for uid, (parent_lbn, obj_lbn) in self.mapping_entries.items():
                struct.pack_into('<IIIHH', map_buf, mpos, uid, parent_lbn, obj_lbn, 1, 1)
                mpos += 16
            fout.write(map_buf)
            self.metadata_mapping_file.file_size = mpos
            self.metadata_mapping_file.extents = [(self.metadata_lbn - self.partition_start_lbn + (self.metadata_len // SECTOR_SIZE), mpos)]

            self._tag_base_addr = self.metadata_mirror_lbn
            self._write_metadata(fout, self.metadata_mirror_lbn)

            fout.seek(576 * 1024)
            self._tag_base_addr = self.partition_start_lbn
            self._write_extended_file_entry(fout, False, 0, 250, self.metadata_len, self.metadata_lbn - self.partition_start_lbn, 0)

            self._tag_base_addr = self.metadata_lbn
            self._write_metadata(fout, self.metadata_lbn)

            self._tag_base_addr = 0

            def write_vds(start_sec: int):
                fout.seek(start_sec * SECTOR_SIZE)

                # 1. PVD (Tag 1)
                pvd = bytearray(512)
                struct.pack_into('<II', pvd, 16, 0, 0)
                pvd[24:24+32] = dstring(self.volume_label, 32)
                struct.pack_into('<HHHHII', pvd, 56, 1, 1, 2, 2, 1, 1)
                vol_set_id = f"{self.vol_id:08X}        {self.volume_label}"
                pvd[72:72+128] = dstring(vol_set_id, 128)
                pvd[200] = 0
                pvd[201:201+len("OSTA Compressed Unicode")] = b"OSTA Compressed Unicode"
                pvd[264] = 0
                pvd[265:265+len("OSTA Compressed Unicode")] = b"OSTA Compressed Unicode"
                pvd[344] = 0
                pvd[345:345+len(self.app_id)] = self.app_id.encode('latin1')
                pvd[376:388] = make_timestamp(self.now)
                pvd[388] = 0
                pvd[389:389+len(self.imp_id)] = self.imp_id.encode('latin1')
                pvd[420:420+len(self.app_id)] = self.app_id.encode('latin1')
                pvd[488] = 1
                c = crc16(pvd[16:512])
                pvd[:16] = write_desc_tag(1, start_sec, c, 512 - 16)
                fout.write(bytes(pvd).ljust(SECTOR_SIZE, b'\x00'))

                # 2. ImpUse (Tag 4)
                imp = bytearray(512)
                struct.pack_into('<I', imp, 16, 1)
                imp[20:52] = udf_string("*UDF LV Info", 32)
                imp[52] = 0
                imp[53:53+len("OSTA Compressed Unicode")] = b"OSTA Compressed Unicode"
                imp[116:244] = dstring(self.volume_label, 128)
                imp[0x161:0x161+len(self.imp_id)] = self.imp_id.encode('latin1')
                imp[0x180:0x180+len(self.app_id)] = self.app_id.encode('latin1')
                fout.write(pack_descriptor(4, start_sec + 1, imp[16:512]))

                # 3. Partition Descriptor (Tag 5)
                pd = bytearray(512)
                struct.pack_into('<IHH', pd, 16, 2, 1, 0)
                pd[25:25+6] = b"+NSR03"
                part_len = self.partition_end_lbn - self.partition_start_lbn
                struct.pack_into('<III', pd, 184, 1, self.partition_start_lbn, part_len)
                pd[0xC5:0xC5+len(self.imp_id)] = self.imp_id.encode('latin1')
                pd[0xE4:0xE4+len(self.app_id)] = self.app_id.encode('latin1')
                fout.write(pack_descriptor(5, start_sec + 2, pd[16:512]))

                # 4. Logical Volume Descriptor (Tag 6)
                lvd = bytearray(512)
                struct.pack_into('<I', lvd, 16, 3)
                lvd[20] = 0
                lvd[21:21+len("OSTA Compressed Unicode")] = b"OSTA Compressed Unicode"
                lvd[84:84+128] = dstring(self.volume_label, 128)
                struct.pack_into('<I', lvd, 212, 2048)
                lvd[216:248] = udf_string("*OSTA UDF Compliant", 32)
                lvd[242] = 0x03
                lvd[249] = 0x10
                lvd[256] = 0x01
                struct.pack_into('<I', lvd, 264, 70)
                struct.pack_into('<I', lvd, 268, 2)
                lvd[272] = 0
                lvd[273:273+len(self.imp_id)] = self.imp_id.encode('latin1')
                lvd[304:304+len(self.app_id)] = self.app_id.encode('latin1')
                struct.pack_into('<II', lvd, 432, 0x8000, 0x40)

                # Type 1 map
                lvd[440] = 1; lvd[441] = 6
                struct.pack_into('<HH', lvd, 442, 1, 0)

                # Type 2 map
                lvd[446] = 2; lvd[447] = 64
                lvd[450:482] = udf_string("*UDF Metadata Partition", 32)
                struct.pack_into('<HHHH', lvd, 482, 1, 0, 0, 0)
                mirror_hdr_loc = self.metadata_mirror_lbn - 1 - self.partition_start_lbn
                struct.pack_into('<HH', lvd, 490, mirror_hdr_loc & 0xFFFF, mirror_hdr_loc >> 16)
                struct.pack_into('<HH', lvd, 494, 0xFFFF, 0xFFFF)
                struct.pack_into('<HHH', lvd, 498, 0x20, 0x00, 0x20)
                lvd[504] = 1
                c = crc16(lvd[16:510])
                lvd[:16] = write_desc_tag(6, start_sec + 3, c, 510 - 16)
                fout.write(bytes(lvd).ljust(SECTOR_SIZE, b'\x00'))

                # 5. Unallocated Space Descriptor (Tag 7)
                unalloc = bytearray(24)
                struct.pack_into('<I', unalloc, 16, 4)
                fout.write(pack_descriptor(7, start_sec + 4, unalloc[16:24], total_len=24))

                # 6. Terminating Descriptor (Tag 8)
                term = bytearray(512)
                fout.write(pack_descriptor(8, start_sec + 5, term[16:512]))

            write_vds(32)

            fout.seek(64 * SECTOR_SIZE)
            lvid = bytearray(512)
            ts = make_timestamp(self.now)
            lvid[16:28] = ts
            struct.pack_into('<III', lvid, 28, 1, 0, 0)
            struct.pack_into('<II', lvid, 40, self.obj_uniq_id, 0)
            app_id_len = len(self.app_id)
            part_len = self.partition_end_lbn - self.partition_start_lbn
            struct.pack_into('<IIII', lvid, 72, 2, 46 + app_id_len, 0, 0)
            struct.pack_into('<II', lvid, 88, part_len, self.metadata_len // SECTOR_SIZE)
            lvid[97:97+len(self.imp_id)] = self.imp_id.encode('latin1')
            struct.pack_into('<IIHHH', lvid, 128, self.total_files, self.total_dirs, 0x0250, 0x0250, 0x0250)
            lvid[142:142+app_id_len] = self.app_id.encode('latin1')
            tot_lvid_len = 142 + app_id_len
            fout.write(pack_descriptor(9, 64, lvid[16:tot_lvid_len], total_len=tot_lvid_len))

            term = bytearray(512)
            fout.write(pack_descriptor(8, 65, term[16:512]))

            fout.seek(256 * SECTOR_SIZE)
            avdp_payload = struct.pack('<IIII', 0x8000, 32, 0x8000, self.partition_end_lbn + (ALLOC_BLOCK_SIZE // SECTOR_SIZE))
            fout.write(pack_descriptor(2, 256, avdp_payload))

            eof_pos = self.partition_end_lbn * SECTOR_SIZE
            avdp_sec = (eof_pos + ALLOC_BLOCK_SIZE - SECTOR_SIZE) // SECTOR_SIZE
            fout.seek(avdp_sec * SECTOR_SIZE)
            fout.write(pack_descriptor(2, avdp_sec, avdp_payload))

            write_vds(avdp_sec + 1)

            full_file_size = eof_pos + (512 * 1024) + ALLOC_BLOCK_SIZE
            fout.seek(0, 2)
            pad_needed = (full_file_size - SECTOR_SIZE) - fout.tell()
            if pad_needed > 0:
                fout.write(b'\x00' * pad_needed)

            last_sec = fout.tell() // SECTOR_SIZE
            fout.write(pack_descriptor(2, last_sec, avdp_payload))

        _log(f"[OK] UDF 2.50 Image erfolgreich erstellt: {self.output_path} ({os.path.getsize(self.output_path)} Bytes)")


def create_udf250_iso_from_tree(
    source_dir: str,
    iso_path: str,
    volume_label: str = "BD_DISC",
    interleaved_3d_streams: Optional[List[Dict]] = None,
    log_callback: Optional[Callable[[str], None]] = None
) -> bool:
    """
    Erstellt ein standardkonformes UDF 2.50 Blu-ray ISO aus einem Quellverzeichnis (enthält BDMV).
    
    :param source_dir: Ordner, der BDMV (und optional CERTIFICATE) enthält
    :param iso_path: Zieldateipfad für die .iso-Datei
    :param volume_label: Disc-Label
    :param interleaved_3d_streams: Optionale Liste von 3D-Stream-Metadaten für Extent-Interleaving:
           [{
               "base_clip_str": "00004",
               "mvc_clip_str": "00005",
               "tmp_iso": "path/to/tmp_3d_00004.iso",
               "base_extents": [...],
               "mvc_extents": [...],
               "ssif_offset": 917504,
               "ssif_len": 120582144
           }]
    :param log_callback: Optionale Logging-Callback
    :return: True bei Erfolg, False bei Fehler
    """
    def _log(msg):
        if log_callback:
            log_callback(msg)
        else:
            print(msg)

    bdmv_dir = os.path.join(source_dir, "BDMV")
    if not os.path.exists(bdmv_dir):
        _log(f"Fehler: BDMV-Ordner nicht gefunden unter: {bdmv_dir}")
        return False

    # Pflicht-Verzeichnisse für BD-ROM Part 3
    for sub in ["AUXDATA", "BACKUP", "BDJO", "JAR", "META", "PLAYLIST", "CLIPINF", "STREAM"]:
        os.makedirs(os.path.join(bdmv_dir, sub), exist_ok=True)
    os.makedirs(os.path.join(bdmv_dir, "BACKUP", "PLAYLIST"), exist_ok=True)
    os.makedirs(os.path.join(bdmv_dir, "BACKUP", "CLIPINF"), exist_ok=True)

    cert_dir = os.path.join(source_dir, "CERTIFICATE")
    os.makedirs(os.path.join(cert_dir, "BACKUP"), exist_ok=True)

    if os.path.exists(iso_path):
        try:
            os.remove(iso_path)
        except OSError as e:
            _log(f"Fehler: Konnte bestehende ISO nicht ueberschreiben: {e}")
            return False

    writer = UDF250Writer(iso_path, volume_label=volume_label)

    # 3D Stream Maps zur Filterung normaler Dateien
    interleaved_map = {}
    if interleaved_3d_streams:
        for item in interleaved_3d_streams:
            base_str = item["base_clip_str"]
            mvc_str = item["mvc_clip_str"]
            interleaved_map[f"{base_str}.m2ts".upper()] = item
            interleaved_map[f"{mvc_str}.m2ts".upper()] = item
            interleaved_map[f"{base_str}.ssif".upper()] = item

    # Ordner und reguläre Dateien hinzufügen
    for root_name in ["BDMV", "CERTIFICATE"]:
        src_root = os.path.join(source_dir, root_name)
        if not os.path.exists(src_root):
            continue
        writer.get_or_create_dir(root_name)
        for root, dirs, files in os.walk(src_root):
            rel_dir = os.path.relpath(root, source_dir).replace('\\', '/')
            writer.get_or_create_dir(rel_dir)
            for f in files:
                rel_file = os.path.join(rel_dir, f).replace('\\', '/')
                f_upper = f.upper()
                # Falls Datei Teil eines 3D-Interleaves ist, wird sie gesondert registriert
                if f_upper in interleaved_map:
                    continue
                full_src = os.path.join(root, f)
                is_realtime = f_upper.endswith(".M2TS")
                writer.add_file(rel_file, src_path=full_src, is_realtime=is_realtime)

    # 3D Interleaved Streams registrieren
    if interleaved_3d_streams:
        for item in interleaved_3d_streams:
            base_str = item["base_clip_str"]
            mvc_str = item["mvc_clip_str"]
            base_rel = f"BDMV/STREAM/{base_str}.m2ts"
            mvc_rel = f"BDMV/STREAM/{mvc_str}.m2ts"
            ssif_rel = f"BDMV/STREAM/SSIF/{base_str}.ssif"
            
            slice_info = (item["tmp_iso"], item["ssif_offset"], item["ssif_len"])
            writer.add_interleaved_3d(
                base_rel_path=base_rel,
                mvc_rel_path=mvc_rel,
                ssif_rel_path=ssif_rel,
                ssif_source_path=item["tmp_iso"],
                base_extents=item["base_extents"],
                mvc_extents=item["mvc_extents"],
                ssif_slice=slice_info
            )

    try:
        writer.build_iso(progress_callback=_log)
        return True
    except Exception as ex:
        _log(f"❌ Fehler bei der ISO-Erstellung: {ex}")
        try:
            if os.path.exists(iso_path):
                os.remove(iso_path)          # keine halbfertige ISO liegen lassen
        except OSError:
            pass
        return False
