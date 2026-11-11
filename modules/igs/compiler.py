# modules/igs/compiler.py
"""
High-Level IGS (Interactive Graphics Stream) Compiler für OpenBDAuth.

Kombiniert Farbraum-Quantisierung, Blu-ray RLE-Kompression,
Segment-Generierung (ICS, PDS, ODS, END) und PES-Paketierung.
"""

from typing import List, Optional
from PIL import Image
from dataclasses import dataclass, field

from modules.igs.palette import PaletteBuilder
from modules.igs.rle import encode_rle
from modules.igs.segments import (
    ButtonDef, PageDef, build_pds_segment, build_ods_segment,
    build_ics_segment, build_end_segment, build_play_playlist_cmd,
    build_jump_title_cmd, FPS_23_976
)
from modules.igs.pes import packetize_pes

@dataclass
class MenuButton:
    """Repräsentiert einen Button im Designer mit seinen Grafiken und Ziel-Aktionen."""
    button_id: int
    x: int
    y: int
    normal_image: Image.Image
    selected_image: Image.Image
    activated_image: Image.Image
    # D-Pad Navigation
    upper_id: int
    lower_id: int
    left_id: int
    right_id: int
    # Ziel-Playlist / Ziel-Titel (z.B. 1 für Hauptfilm, 2 für Extras)
    target_playlist_id: int = 1
    nav_commands: Optional[List[bytes]] = None
    auto_action: bool = False   # löst beim Auswählen sofort aus (Startseite einer Menügruppe, v1.13)

@dataclass
class MenuPage:
    """Repräsentiert eine Menüseite (Page) mit ihren Buttons."""
    page_id: int
    buttons: List[MenuButton]
    default_selected_id: int = 1

class IGSCompiler:
    """Kompiliert eine Sammlung von Menü-Buttons in einen fertigen IGS-PES-Stream."""

    def __init__(self, width: int = 1920, height: int = 1080, fps_code: int = FPS_23_976):
        self.width = width
        self.height = height
        self.fps_code = fps_code

    def compile_pages(
        self,
        pages: List[MenuPage],
        pts_90khz: int = 54000000, # Standard: 10 Minuten Offset (600s * 90000)
        priority_images: Optional[List[Image.Image]] = None
    ) -> bytes:
        """
        Kompiliert mehrere Menüseiten (Pages) in einen vollständigen IGS-PES-Stream.
        Ermöglicht Multi-Page-Menüs (Hauptmenü, Kapitelauswahl, Sprache) via SetButtonPage.
        priority_images: Bilder, deren Farben zuerst einen Paletten-Platz bekommen (Form-Buttons,
        damit sie neben farbreichen Text-Buttons exakt bleiben); None = Palette wie bisher.
        """
        if not pages or all(len(p.buttons) == 0 for p in pages):
            raise ValueError("Mindestens eine Seite mit Buttons muss vorhanden sein.")

        # 1. Gemeinsame Palette für alle Button-Zustände aller Seiten aufbauen
        palette_builder = PaletteBuilder(palette_id=0)
        for image in priority_images or ():
            palette_builder.quantize_image(image)

        # Sammle alle Objekt-Daten: (obj_id, width, height, rle_bytes)
        ods_list = []
        page_defs: List[PageDef] = []
        next_obj_id = 0

        for page in pages:
            btn_defs: List[ButtonDef] = []
            for btn in page.buttons:
                # Normal State
                norm_indices, w, h = palette_builder.quantize_image(btn.normal_image)
                norm_rle = encode_rle(norm_indices, w, h)
                norm_obj_id = next_obj_id
                ods_list.append((norm_obj_id, w, h, norm_rle))
                next_obj_id += 1

                # Selected State
                sel_indices, w, h = palette_builder.quantize_image(btn.selected_image)
                sel_rle = encode_rle(sel_indices, w, h)
                sel_obj_id = next_obj_id
                ods_list.append((sel_obj_id, w, h, sel_rle))
                next_obj_id += 1

                # Activated State
                act_indices, w, h = palette_builder.quantize_image(btn.activated_image)
                act_rle = encode_rle(act_indices, w, h)
                act_obj_id = next_obj_id
                ods_list.append((act_obj_id, w, h, act_rle))
                next_obj_id += 1

                # Button Definition für ICS
                btn_def = ButtonDef(
                    button_id=btn.button_id,
                    numeric_select_value=btn.button_id,
                    x=btn.x,
                    y=btn.y,
                    width=w,
                    height=h,
                    upper_button_id=btn.upper_id,
                    lower_button_id=btn.lower_id,
                    left_button_id=btn.left_id,
                    right_button_id=btn.right_id,
                    normal_object_id=norm_obj_id,
                    selected_object_id=sel_obj_id,
                    activated_object_id=act_obj_id,
                    nav_commands=btn.nav_commands if btn.nav_commands is not None else [build_jump_title_cmd(btn.target_playlist_id)],
                    auto_action=btn.auto_action
                )
                btn_defs.append(btn_def)

            page_defs.append(PageDef(
                page_id=page.page_id,
                buttons=btn_defs,
                default_selected_button_id=page.default_selected_id
            ))

        # 2. Segmente generieren
        # ICS mit allen Seiten
        ics_bytes = build_ics_segment(
            video_width=self.width,
            video_height=self.height,
            frame_rate_code=self.fps_code,
            pages=page_defs
        )

        # PDS
        pds_payload = palette_builder.palette.to_pds_payload()
        pds_bytes = build_pds_segment(pds_payload)

        # END
        end_bytes = build_end_segment()

        # 3. Segmente jeweils in eigene PES-Pakete verpacken (Display Set)
        pes_packets: List[bytes] = []
        pes_packets.extend(packetize_pes(ics_bytes, pts_90khz=pts_90khz))
        pes_packets.extend(packetize_pes(pds_bytes, pts_90khz=pts_90khz))
        for obj_id, w, h, rle_data in ods_list:
            ods_bytes = build_ods_segment(obj_id, w, h, rle_data)
            pes_packets.extend(packetize_pes(ods_bytes, pts_90khz=pts_90khz))
        pes_packets.extend(packetize_pes(end_bytes, pts_90khz=pts_90khz))

        # Zusammenhängenden PES-Bytestream zurückgeben
        return b"".join(pes_packets)

    def compile_menu(
        self,
        buttons: List[MenuButton],
        default_selected_id: int = 1,
        pts_90khz: int = 54000000
    ) -> bytes:
        """
        Kompiliert eine einzelne Liste von Buttons (Page 0) in einen IGS-PES-Stream.
        Bequeme Schnittstelle für Standard-Einzelseiten-Menüs.
        """
        return self.compile_pages(
            pages=[MenuPage(page_id=0, buttons=buttons, default_selected_id=default_selected_id)],
            pts_90khz=pts_90khz
        )
