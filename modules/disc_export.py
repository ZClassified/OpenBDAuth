# modules/disc_export.py
"""
Export-Ablauf einer Blu-ray (tsMuxeR, Multi-Title, 3D/SSIF, HDMV-Menü, UDF 2.50 ISO).

Unverändert aus der früheren Oberfläche (ExportWorker.run, bis v1.11.2) übernommen; der Ablauf
ist auf Hardware verifiziert. Einziger Zusatz: optionale pages_specs, die an
inject_menu_into_bdmv weitergereicht werden (Menüseiten aus dem Node-Graphen).
Ohne pages_specs entstehen die Menüseiten wie bisher aus den Menü-Einstellungen.
"""

import os
import re
import shutil
import subprocess
import tempfile
from typing import Callable, List, Optional, Tuple

from core.meta_builder import MetaBuilder
from core.translations import tr
from modules.mux_engine import find_tsmuxer
from modules.external_tools import NO_CONSOLE


def normalize_3d_fps(project):
    """3D-Hauptfilm mit 23–25 fps wird als 23,976 fps gemuxt (MVC kennt nur 23,976 / 24)."""
    if project.video_mvc and 23.0 <= project.fps <= 25.0:
        project.fps = 23.976


def menu_injection_args(project, pages_specs: Optional[List[Tuple[int, list]]] = None) -> dict:
    """Argumente für inject_menu_into_bdmv (ohne bdmv_dir) – gemeinsam für den Export und die
    Simulation aus dem Projekt (modules/sim_disc.py), damit beide dasselbe Menü erzeugen."""
    valid_titles = [t for t in project.titles if t.video_base]
    return dict(
        bg_image_path=project.menu_bg_image,
        btn1_text=project.menu_btn1_text,
        btn2_text=project.menu_btn2_text,
        duration_sec=getattr(project, "menu_duration", 30.0),
        fps=project.fps,
        lang="deu" if project.app_lang == "de" else "eng",
        num_titles=max(1, len(valid_titles)),
        project=project,
        bg_video_path=getattr(project, "menu_bg_video", None),
        bg_audio_path=getattr(project, "menu_bg_audio", None),
        pages_specs=pages_specs,
        menu_groups=getattr(project, "menu_groups", None),     # v1.13: weitere Menügruppen (Export-Adapter)
        menu_resume=getattr(project, "menu_resume", True),
        title_ends=getattr(project, "title_ends", None),       # v1.18: Filmende in einem anderen Menü / Film
        first_play_title=getattr(project, "first_play_title", None),   # v1.18.1: Film vor dem Menü
        with_2d_choice=getattr(project, "with_2d_choice", False),      # v1.20: 3D-Filme wahlweise in 2D
    )


def export_disc(
    project,
    log: Callable[[str], None],
    progress: Callable[[float], None],
    pages_specs: Optional[List[Tuple[int, list]]] = None,
    on_disc_ready: Optional[Callable[[str], None]] = None,
) -> Tuple[bool, str]:
    """Führt den kompletten Export aus. Gibt (Erfolg, Meldung) zurück.

    on_disc_ready(Zielordner) wird aufgerufen, sobald die BDMV-Struktur fertig ist – vor der
    ISO-Erstellung und dem Aufräumen (z. B. für den Disc-Simulator). Fehler darin brechen den Export nicht ab.
    """
    try:
        log(tr("log_start", project.app_lang))
        dest = project.output_path

        # 3D Sanity
        normalize_3d_fps(project)

        meta_path = os.path.join(dest, "job.meta")
        MetaBuilder(project).save_meta_file(meta_path)

        raw_name = (project.project_name or "").strip()
        safe_name = raw_name if raw_name else "BD_DISC"
        is_iso_requested = (project.export_format == "iso")

        # Prüfen auf Single-Title Direktstart (kein Menü, keine Extras/Titel 2..N)
        titles = getattr(project, "titles", [])
        additional_titles = titles[1:] if len(titles) > 1 else []
        if not additional_titles and project.video_extra:
            from core.project_state import MediaTitle
            legacy_extra = MediaTitle(name="Extras", is_main=False)
            legacy_extra.video_base = project.video_extra
            legacy_extra.audio_tracks = getattr(project, "extra_audio_tracks", [])
            additional_titles = [legacy_extra]

        direct_iso_mode = is_iso_requested and (not project.enable_menu) and (not additional_titles)

        if direct_iso_mode:
            iso_target = os.path.join(dest, f"{safe_name}.iso")
            if os.path.exists(iso_target):
                try:
                    os.remove(iso_target)
                except OSError:
                    pass
            mux_dest = iso_target
            t0 = titles[0] if titles else project
            if getattr(t0, "video_mvc", None):
                log(tr("log_3d_direct_iso"))
            else:
                log("⚡ Direkt-Export: tsMuxeR erzeugt UDF 2.50 ISO direkt...")
        else:
            mux_dest = dest

        tsmuxer_bin = find_tsmuxer()
        if not tsmuxer_bin:
            log(tr("log_tsmuxer_not_found", project.app_lang))
            return False, tr("log_tsmuxer_missing_short")

        cmd = [tsmuxer_bin, meta_path, mux_dest]
        process = subprocess.Popen(
            cmd,
            **NO_CONSOLE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace"
        )

        for line in process.stdout:
            line_str = line.strip()
            if "Processed" in line_str and "frames" in line_str:
                continue

            pct_match = re.search(r'(\d+\.\d+)%\s*complete', line_str)
            if pct_match:
                val = float(pct_match.group(1))
                scale = 0.85 if project.enable_menu else 1.0
                progress((val / 100.0) * scale)
            else:
                if line_str:
                    log(line_str)

        process.wait()

        if process.returncode != 0:
            err_msg = tr("log_error", project.app_lang).format(code=process.returncode)
            log(err_msg)
            return False, err_msg

        if direct_iso_mode:
            if getattr(project, "disc_title_meta", False):
                log(tr("log_disc_title_direct_iso", project.app_lang))
            log(tr("log_iso_success", project.app_lang).format(path=mux_dest))
            if getattr(project, "clean_iso_temp", True):
                meta_file = os.path.join(dest, "job.meta")
                if os.path.exists(meta_file):
                    try:
                        os.remove(meta_file)
                    except OSError:
                        pass
            progress(1.0)
            log(tr("log_finish", project.app_lang))
            return True, tr("log_finish", project.app_lang)

        # 1. Multi-Title Muxing für Titel 2..N (Episoden, Bonusmaterial etc.)
        titles = getattr(project, "titles", [])
        additional_titles = titles[1:] if len(titles) > 1 else []
        if not additional_titles and project.video_extra:
            from core.project_state import MediaTitle
            legacy_extra = MediaTitle(name="Extras", is_main=False)
            legacy_extra.video_base = project.video_extra
            legacy_extra.audio_tracks = getattr(project, "extra_audio_tracks", [])
            additional_titles = [legacy_extra]

        # Start-Clip-ID für Titel 2..N dynamisch ermitteln:
        t0 = titles[0] if titles else project
        t1_is_3d = bool(getattr(t0, "video_mvc", None))

        collected_3d_streams = []

        # Sicherstellen, dass das standardkonforme SSIF-Verzeichnis für 3D-Player existiert
        if t1_is_3d or any(bool(getattr(t, "video_mvc", None)) for t in additional_titles):
            os.makedirs(os.path.join(dest, "BDMV", "STREAM", "SSIF"), exist_ok=True)

        # Falls Titel 1 3D ist, sicherstellen, dass auch für Titel 1 der offizielle SSIF-Stream existiert
        if t1_is_3d and not os.path.exists(os.path.join(dest, "BDMV", "STREAM", "SSIF", "00000.ssif")):
            from modules.ssif_tools import mux_3d_title
            try:
                mpls_t1_raw = mux_3d_title(
                    tsmuxer_bin=tsmuxer_bin,
                    meta_path=meta_path,
                    tmp_dir=dest,
                    base_clip_str="00000",
                    mvc_clip_str="00001",
                    dest_bdmv=os.path.join(dest, "BDMV"),
                    log_callback=lambda msg: log(msg)
                )
                if hasattr(mpls_t1_raw, "title_3d_info"):
                    collected_3d_streams.append(mpls_t1_raw.title_3d_info)
                with open(os.path.join(dest, "BDMV", "PLAYLIST", "00000.mpls"), "wb") as fout:
                    fout.write(mpls_t1_raw)
            except Exception as ex_t1:
                log(tr("log_3d_ssif_note", err=ex_t1))

        if project.enable_menu:
            next_clip_id = 4 if t1_is_3d else 3
        else:
            next_clip_id = 2 if t1_is_3d else 1

        for idx, extra_title in enumerate(additional_titles, start=2):
            if not extra_title.video_base:
                continue
            is_3d = bool(getattr(extra_title, "video_mvc", None))
            log(f"Muxe Titel {idx}: {extra_title.name} {'(3D MVC)' if is_3d else ''}...")
            progress(0.85 + (0.06 * ((idx - 1) / max(1, len(additional_titles)))))

            base_clip_str = f"{next_clip_id:05d}"
            target_mpls = os.path.join(dest, "BDMV", "PLAYLIST", f"{idx:05d}.mpls")

            with tempfile.TemporaryDirectory() as tmp_extra:
                extra_meta = os.path.join(tmp_extra, f"title_{idx}.meta")
                MetaBuilder(project).save_title_meta_file(extra_title, extra_meta)

                if is_3d:
                    mvc_clip_str = f"{next_clip_id + 1:05d}"
                    next_clip_id += 2

                    from modules.ssif_tools import mux_3d_title
                    try:
                        mpls_raw = mux_3d_title(
                            tsmuxer_bin=tsmuxer_bin,
                            meta_path=extra_meta,
                            tmp_dir=tmp_extra,
                            base_clip_str=base_clip_str,
                            mvc_clip_str=mvc_clip_str,
                            dest_bdmv=os.path.join(dest, "BDMV"),
                            log_callback=lambda msg: log(msg)
                        )
                        if hasattr(mpls_raw, "title_3d_info"):
                            collected_3d_streams.append(mpls_raw.title_3d_info)
                        # Playlist patchen (Base- und MVC-Clip-Referenzen ersetzen)
                        mpls_patched = mpls_raw.replace(b"00000M2TS", f"{base_clip_str}M2TS".encode("ascii"))
                        mpls_patched = mpls_patched.replace(b"00001M2TS", f"{mvc_clip_str}M2TS".encode("ascii"))
                        with open(target_mpls, "wb") as fout:
                            fout.write(mpls_patched)
                    except Exception as ex_3d:
                        err_msg = tr("log_mux_3d_error", n=idx, name=extra_title.name, err=ex_3d)
                        log(err_msg)
                        return False, err_msg
                else:
                    next_clip_id += 1
                    extra_dest = os.path.join(tmp_extra, f"bdmv_title_{idx}")
                    extra_cmd = [tsmuxer_bin, extra_meta, extra_dest]
                    proc_extra = subprocess.run(extra_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **NO_CONSOLE)
                    if proc_extra.returncode == 0:
                        extra_m2ts_src = os.path.join(extra_dest, "BDMV", "STREAM", "00000.m2ts")
                        extra_clpi_src = os.path.join(extra_dest, "BDMV", "CLIPINF", "00000.clpi")
                        extra_mpls_src = os.path.join(extra_dest, "BDMV", "PLAYLIST", "00000.mpls")

                        target_m2ts = os.path.join(dest, "BDMV", "STREAM", f"{base_clip_str}.m2ts")
                        target_clpi = os.path.join(dest, "BDMV", "CLIPINF", f"{base_clip_str}.clpi")

                        if os.path.exists(extra_m2ts_src):
                            shutil.copy2(extra_m2ts_src, target_m2ts)
                            shutil.copy2(extra_clpi_src, target_clpi)
                            with open(extra_mpls_src, "rb") as fin:
                                mpls_raw = fin.read()
                            mpls_patched = mpls_raw.replace(b"00000M2TS", f"{base_clip_str}M2TS".encode("ascii"))
                            with open(target_mpls, "wb") as fout:
                                fout.write(mpls_patched)
                    else:
                        err_detail = proc_extra.stderr.strip() or proc_extra.stdout.strip() or f"Exit-Code {proc_extra.returncode}"
                        err_msg = tr("log_mux_error", n=idx, name=extra_title.name, err=err_detail)
                        log(err_msg)
                        return False, err_msg

        # 2. HDMV Menü Injektion
        if project.enable_menu:
            log(tr("log_menu_generating", project.app_lang))
            progress(0.92)

            from modules.menu_author import inject_menu_into_bdmv
            bdmv_dir = os.path.join(dest, "BDMV")
            inject_menu_into_bdmv(bdmv_dir=bdmv_dir, **menu_injection_args(project, pages_specs))
            log(tr("log_menu_success", project.app_lang))

        # 2.5 BD-ROM Part 3 Stream-Attribut-Patch (1080i Hardware-Player Compliance)
        from modules.mux_engine import fix_1080i_stream_attributes
        bdmv_dir = os.path.join(dest, "BDMV")
        patched_headers = fix_1080i_stream_attributes(bdmv_dir)
        if patched_headers > 0:
            log(f"BD-ROM Part 3 Stream-Attribute optimiert ({patched_headers} Header korrigiert)")

        # 2.6 Disc-Titel für den Player (BDMV/META/DL/bdmt_*.xml), nur auf Wunsch
        if getattr(project, "disc_title_meta", False):
            from modules.bdmv.meta_generator import write_disc_title_meta
            title = (getattr(project, "disc_title", "") or "").strip() or safe_name
            write_disc_title_meta(bdmv_dir, title)
            log(tr("log_disc_title", project.app_lang).format(name=title))

        if on_disc_ready is not None:
            try:
                on_disc_ready(dest)
            except Exception as ex:
                log(tr("log_disc_check_failed", err=ex))

        # 3. UDF 2.50 ISO Erstellung
        if is_iso_requested:
            log(tr("log_iso_generating", project.app_lang).format(name=safe_name))
            progress(0.95)

            from modules.iso_tools import create_udf_iso
            iso_target = os.path.join(dest, f"{safe_name}.iso")
            iso_success = create_udf_iso(
                source_dir=dest,
                iso_path=iso_target,
                volume_label=safe_name,
                interleaved_3d_streams=collected_3d_streams if collected_3d_streams else None,
                log_callback=lambda msg: log(msg)
            )
            if iso_success:
                log(tr("log_iso_success", project.app_lang).format(path=iso_target))

                # Temporäre 3D-ISOs nach erfolgreichem Muxen bereinigen
                if collected_3d_streams:
                    for item in collected_3d_streams:
                        tmp_iso_path = item.get("tmp_iso")
                        if tmp_iso_path and os.path.exists(tmp_iso_path):
                            try:
                                os.remove(tmp_iso_path)
                            except OSError:
                                pass

                # Automatisches Bereinigen von BDMV, CERTIFICATE & job.meta
                if getattr(project, "clean_iso_temp", True):
                    log(tr("log_cleaning_temp", project.app_lang))
                    import time
                    time.sleep(0.5)

                    bdmv_path = os.path.join(dest, "BDMV")
                    cert_path = os.path.join(dest, "CERTIFICATE")
                    meta_file = os.path.join(dest, "job.meta")

                    if os.path.exists(bdmv_path):
                        try:
                            shutil.rmtree(bdmv_path, ignore_errors=True)
                        except Exception as ex:
                            log(f"Hinweis: BDMV-Bereinigung: {ex}")
                    if os.path.exists(cert_path):
                        try:
                            shutil.rmtree(cert_path, ignore_errors=True)
                        except Exception as ex:
                            log(f"Hinweis: CERTIFICATE-Bereinigung: {ex}")
                    if os.path.exists(meta_file):
                        try:
                            os.remove(meta_file)
                        except OSError:
                            pass

                    log(tr("log_cleaned_temp_success", project.app_lang))
            else:
                log(tr("log_iso_error", project.app_lang))
                return False, tr("log_iso_error", project.app_lang).lstrip("❌ ")
        else:
            # Bei reinem Ordner-Export: job.meta nach erfolgreichem Muxen entfernen
            meta_file = os.path.join(dest, "job.meta")
            if os.path.exists(meta_file):
                try:
                    os.remove(meta_file)
                except OSError:
                    pass

        progress(1.0)
        log(tr("log_finish", project.app_lang))
        return True, tr("log_finish", project.app_lang)

    except Exception as e:
        err = tr("log_exception", project.app_lang).format(err=str(e))
        log(err)
        return False, err
