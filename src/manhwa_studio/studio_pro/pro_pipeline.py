"""
Pro Studio Production Pipeline.
Orchestrates multi-voice dubbing, mood BGM with auto-ducking, kinetic anime subtitles,
advanced camera FX (shake/zoom), and viral high-CTR thumbnail packaging.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Union

from manhwa_studio.logging_config import get_logger
from manhwa_studio.project_manager import ProjectManager
from manhwa_studio.rendering.ffmpeg import get_video_encoder_args, is_nvenc_available
from manhwa_studio.schemas import SceneManifest
from manhwa_studio.story.script_writer import load_scene_manifest, save_scene_manifest
from manhwa_studio.studio_pro.series_manager import SeriesManager, SeriesProfile
from manhwa_studio.studio_pro.voice_director import VoiceDirector
from manhwa_studio.studio_pro.audio_director import AudioDirector
from manhwa_studio.studio_pro.kinetic_subtitles import KineticSubtitleGenerator
from manhwa_studio.studio_pro.camera_director import CameraDirector
from manhwa_studio.studio_pro.thumbnail_designer import ThumbnailDesigner
from manhwa_studio.studio_pro.youtube_kit import YouTubeKitGenerator
from manhwa_studio.studio_pro.cold_open_director import ColdOpenDirector

logger = get_logger("manhwa_studio.pro.pipeline")


class ProPipeline:
    """End-to-End Pro Production Pipeline for cinematic Hindi comic dubs."""

    def __init__(self, project_dir: Path, series_profile: Optional[SeriesProfile] = None):
        self.pm = ProjectManager(project_dir)
        self.sm = SeriesManager()

        # Load or auto-create series profile
        from manhwa_studio.env_config import get_env_config
        self.env_cfg = get_env_config()
        if series_profile:
            self.profile = series_profile
        else:
            # Detect series name from project
            m_file = self.pm.scripts_dir / "scene_manifest.json"
            series_name = self.env_cfg.default_series
            if m_file.exists():
                try:
                    data = json.loads(m_file.read_text(encoding="utf-8"))
                    series_name = data.get("series") or series_name
                except Exception:
                    pass
            self.profile = self.sm.get_or_create_profile(series_name)

        self.voice_director = VoiceDirector(self.profile)
        self.audio_director = AudioDirector(self.profile)
        self.sub_generator = KineticSubtitleGenerator(self.profile)
        self.camera_director = CameraDirector()
        self.thumbnail_designer = ThumbnailDesigner(self.profile)
        self.youtube_kit = YouTubeKitGenerator(self.profile)
        self.cold_open_director = ColdOpenDirector(self.profile)

    def run_multi_voice(self, force_rebuild: bool = False) -> SceneManifest:
        """Execute Stage: Multi-Voice character dubbing."""
        m_file = self.pm.scripts_dir / "scene_manifest.json"
        if not m_file.exists():
            raise FileNotFoundError(f"Scene manifest not found at {m_file}. Please run story generation first.")

        manifest = load_scene_manifest(m_file)
        logger.info(f"--- Pro Stage: Multi-Voice Dubbing for '{manifest.series}' Ch.{manifest.chapter} ---")

        self.voice_director.synthesize_all_scenes(manifest, self.pm.audio_dir, force_rebuild=force_rebuild)
        save_scene_manifest(manifest, m_file)
        return manifest

    def run_audio_mastering(self, manifest: SceneManifest) -> Path:
        """Execute Stage: Concatenate voice and mix with mood BGM & SFX."""
        logger.info("--- Pro Stage: Dynamic BGM & Audio Mastering ---")
        voice_track = self.pm.audio_dir / "concatenated_voice.mp3"
        master_audio = self.pm.audio_dir / "master_soundtrack.mp3"

        self.audio_director.build_voice_timeline(manifest, voice_track)
        self.audio_director.mix_master_soundtrack(manifest, voice_track, master_audio)
        return master_audio

    def run_kinetic_subtitles(self, manifest: SceneManifest) -> Path:
        """Execute Stage: Kinetic Anime Subtitles with pop animations."""
        logger.info("--- Pro Stage: Kinetic Pop Subtitles ---")
        ass_path = self.pm.subtitles_dir / "kinetic_subtitles.ass"
        self.sub_generator.generate_ass(
            manifest,
            ass_path,
            video_width=self.camera_director.target_width,
            video_height=self.camera_director.target_height,
        )
        return ass_path

    def run_pro_render(
        self,
        manifest: SceneManifest,
        master_audio: Path,
        subtitles_file: Optional[Path] = None,
        output_video: Optional[Path] = None,
        burn_subtitles: bool = False,
        force_rebuild_segments: bool = False,
    ) -> Path:
        """
        Execute Stage: Video Rendering with Camera FX (Screen shake, slow zoom, webtoon slide)
        and burnt-in animated kinetic subtitles.
        """
        logger.info("--- Pro Stage: Camera FX & Video Rendering ---")
        target_video = output_video or (self.pm.renders_dir / "final_video.mp4")
        target_video.parent.mkdir(parents=True, exist_ok=True)

        segments_dir = self.pm.renders_dir / "segments"
        segments_dir.mkdir(parents=True, exist_ok=True)

        tw = self.camera_director.target_width
        th = self.camera_director.target_height
        fps = self.env_cfg.pro_fps
        panel_layout = (self.env_cfg.panel_layout or "hybrid").strip().lower()
        if panel_layout not in ("hybrid", "wide_zoom", "dual_panel", "classic"):
            panel_layout = "hybrid"

        v_enc_args = get_video_encoder_args(quality=self.env_cfg.video_quality, cpu_preset="veryfast", nvenc_preset="p4")
        enc_label = "GPU (h264_nvenc)" if is_nvenc_available() else "CPU (libx264)"

        import hashlib
        import json as _json
        from manhwa_studio.studio_pro.audio_director import AudioDirector

        ffmpeg_bin = AudioDirector._resolve_media_tool("ffmpeg")

        def _probe_seg_dur(seg_path: Path, fallback: float) -> float:
            return AudioDirector._probe_audio_duration(seg_path, fallback, stream_selector="v:0")

        # Invalidate cached visual segments if layout, resolution, fps, panels, or scene durations changed
        sig_payload = _json.dumps(
            {
                "layout": panel_layout,
                "fps": fps,
                "tw": tw,
                "th": th,
                "scenes": [
                    (sc.scene_id, sc.image_file, round(float(sc.actual_audio_duration or sc.duration), 4))
                    for sc in manifest.scenes
                ],
            },
            sort_keys=True,
        ).encode("utf-8")
        render_sig = hashlib.sha1(sig_payload).hexdigest()[:12]
        sig_marker = segments_dir / f".render_sig_{render_sig}"
        if not sig_marker.exists():
            for pattern in ("seg_*.mp4", ".render_sig_*", ".panel_layout_*"):
                for old_item in segments_dir.glob(pattern):
                    try:
                        old_item.unlink()
                    except Exception:
                        pass
            try:
                sig_marker.write_text(render_sig, encoding="utf-8")
            except Exception:
                pass

        from manhwa_studio.studio_pro.camera_director import prepare_clean_panel

        clean_cache_dir = segments_dir / "_clean_panels"
        prepared_panels: List[Optional[tuple]] = []
        for scene in manifest.scenes:
            img_path = self.pm.artwork_dir / scene.image_file
            if not img_path.exists():
                prepared_panels.append(None)
            elif panel_layout == "classic":
                prepared_panels.append((img_path, (tw, th), (tw // 2, th // 2)))
            else:
                prepared_panels.append(prepare_clean_panel(img_path, clean_cache_dir))

        segment_paths: List[Path] = []
        logger.info(
            f"Rendering {len(manifest.scenes)} visual segments ({tw}x{th}, layout={panel_layout}) via {enc_label}..."
        )

        prev_valid_panel = None
        audio_cursor = 0.0
        video_cursor = 0.0
        for idx, scene in enumerate(manifest.scenes):
            sc_audio_dur = float(scene.actual_audio_duration or scene.duration)
            panel_info = prepared_panels[idx]
            if panel_info is None:
                if prev_valid_panel is not None:
                    logger.warning(f"Image missing for scene {scene.scene_id}: {scene.image_file}; reusing previous panel to preserve A/V sync")
                    panel_info = prev_valid_panel
                else:
                    logger.warning(f"Image missing for scene {scene.scene_id}: {scene.image_file}")
                    audio_cursor += sc_audio_dur
                    continue

            clean_p, size, focus = panel_info
            img_path = self.pm.artwork_dir / scene.image_file
            fallback_src = img_path if img_path.exists() else clean_p
            seg_file = segments_dir / f"seg_{idx:03d}_{scene.scene_id}.mp4"
            audio_cursor += sc_audio_dur
            dur = max(0.20, audio_cursor - video_cursor)

            should_render = force_rebuild_segments or not (seg_file.exists() and seg_file.stat().st_size > 10000)

            if should_render:
                energy = self.camera_director.classify_scene_energy(scene)
                aspect = size[0] / max(1, size[1])

                use_dual = False
                if panel_layout == "dual_panel" and prev_valid_panel is not None:
                    use_dual = True
                elif panel_layout == "hybrid" and prev_valid_panel is not None:
                    # Hybrid Auto-Director: Wide Zoom for hooks, impact, reveal, aftermath, landscape panels & rhythm beats;
                    # Dual Panel for back-to-back portrait dialogue/reaction beats.
                    if energy == "dialogue" and aspect < 0.95 and (idx % 3 != 0):
                        use_dual = True

                if use_dual:
                    prev_p, prev_size, prev_focus = prev_valid_panel
                    active_side = "right" if (idx % 2 == 1) else "left"
                    if active_side == "right":
                        l_p, l_sz, l_fc = prev_p, prev_size, prev_focus
                        r_p, r_sz, r_fc = clean_p, size, focus
                    else:
                        l_p, l_sz, l_fc = clean_p, size, focus
                        r_p, r_sz, r_fc = prev_p, prev_size, prev_focus

                    fc_graph = self.camera_director.build_dual_panel_filter(
                        scene, l_sz, l_fc, r_sz, r_fc, dur, active_side=active_side, fps=fps
                    )
                    cmd = [
                        ffmpeg_bin, "-y",
                        "-loop", "1", "-i", str(l_p),
                        "-loop", "1", "-i", str(r_p),
                        "-t", f"{dur:.4f}",
                        "-filter_complex", fc_graph,
                        "-map", "[v_out]",
                        *v_enc_args,
                        "-an",
                        str(seg_file),
                    ]
                elif panel_layout == "classic":
                    vf_filter = self.camera_director.build_ffmpeg_filter(scene, dur, fps=fps)
                    cmd = [
                        ffmpeg_bin, "-y",
                        "-loop", "1", "-i", str(fallback_src),
                        "-t", f"{dur:.4f}",
                        "-vf", vf_filter,
                        *v_enc_args,
                        "-an",
                        str(seg_file),
                    ]
                else:
                    vf_filter = self.camera_director.build_wide_zoom_filter(scene, size, focus, dur, fps=fps)
                    cmd = [
                        ffmpeg_bin, "-y",
                        "-loop", "1", "-i", str(clean_p),
                        "-t", f"{dur:.4f}",
                        "-vf", vf_filter,
                        *v_enc_args,
                        "-an",
                        str(seg_file),
                    ]

                res = subprocess.run(cmd, capture_output=True, text=True)
                if res.returncode != 0:
                    err_msg = res.stderr[-300:].strip()
                    logger.warning(f"Motion filter or GPU encode failed on {seg_file.name}, trying CPU fallback: {err_msg}")
                    if use_dual:
                        fallback_cmd = [
                            ffmpeg_bin, "-y",
                            "-loop", "1", "-i", str(l_p),
                            "-loop", "1", "-i", str(r_p),
                            "-t", f"{dur:.4f}",
                            "-filter_complex", fc_graph,
                            "-map", "[v_out]",
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", str(self.env_cfg.video_quality), "-pix_fmt", "yuv420p",
                            "-an", str(seg_file),
                        ]
                        res_fb = subprocess.run(fallback_cmd, capture_output=True, text=True)
                        if res_fb.returncode != 0:
                            simple_vf = (
                                f"split[bg_in][fg_in];"
                                f"[bg_in]scale={tw}:{th}:force_original_aspect_ratio=increase,crop={tw}:{th},boxblur=25:5,eq=brightness=-0.15[bg];"
                                f"[fg_in]scale=w={tw}:h={th}:force_original_aspect_ratio=decrease[fg];"
                                f"[bg][fg]overlay=(W-w)/2:(H-h)/2,fps={fps}"
                            )
                            subprocess.run(
                                [ffmpeg_bin, "-y", "-loop", "1", "-i", str(fallback_src), "-t", f"{dur:.4f}", "-vf", simple_vf, "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-an", str(seg_file)],
                                capture_output=True, check=True,
                            )
                    else:
                        fallback_cmd = [
                            ffmpeg_bin, "-y", "-loop", "1", "-i", str(clean_p if panel_layout != "classic" else fallback_src),
                            "-t", f"{dur:.4f}",
                            "-vf", vf_filter,
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", str(self.env_cfg.video_quality), "-pix_fmt", "yuv420p",
                            "-an", str(seg_file),
                        ]
                        res_fb = subprocess.run(fallback_cmd, capture_output=True, text=True)
                        if res_fb.returncode != 0:
                            simple_vf = (
                                f"split[bg_in][fg_in];"
                                f"[bg_in]scale={tw}:{th}:force_original_aspect_ratio=increase,crop={tw}:{th},boxblur=25:5,eq=brightness=-0.15[bg];"
                                f"[fg_in]scale=w={tw}:h={th}:force_original_aspect_ratio=decrease[fg];"
                                f"[bg][fg]overlay=(W-w)/2:(H-h)/2,fps={fps}"
                            )
                            subprocess.run(
                                [ffmpeg_bin, "-y", "-loop", "1", "-i", str(fallback_src), "-t", f"{dur:.4f}", "-vf", simple_vf, "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-an", str(seg_file)],
                                capture_output=True, check=True,
                            )

            actual_seg_dur = _probe_seg_dur(seg_file, dur)
            video_cursor += actual_seg_dur
            prev_valid_panel = panel_info
            segment_paths.append(seg_file)
            if (idx + 1) % 25 == 0 or idx == len(manifest.scenes) - 1:
                logger.info(f"Rendered [{idx + 1}/{len(manifest.scenes)}] visual segments.")

        logger.info(
            f"Visual timeline synced: video={video_cursor:.3f}s vs audio={audio_cursor:.3f}s (drift={video_cursor - audio_cursor:+.3f}s)"
        )

        # Stitch visual segments into raw video
        concat_file = segments_dir / "concat_list.txt"
        lines = [f"file '{p.resolve().as_posix()}'" for p in segment_paths]
        concat_file.write_text("\n".join(lines), encoding="utf-8")

        raw_video = self.pm.renders_dir / "raw_stitched.mp4"
        stitch_cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
            "-c", "copy",
            str(raw_video),
        ]
        subprocess.run(stitch_cmd, capture_output=True, check=True)

        # Mux master soundtrack and video (burn subtitles only if requested)
        if burn_subtitles and subtitles_file and subtitles_file.exists():
            logger.info(f"Burning kinetic subtitles and muxing master soundtrack into final export: {target_video.name}...")
            sub_escaped = subtitles_file.resolve().as_posix().replace(":", r"\:")
            burn_cmd = [
                "ffmpeg", "-y",
                "-i", str(raw_video),
                "-i", str(master_audio),
                "-vf", f"ass='{sub_escaped}'",
                *v_enc_args,
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
                str(target_video),
            ]
            res = subprocess.run(burn_cmd, capture_output=True, text=True)
            if res.returncode != 0:
                logger.warning(f"ASS subtitle burn failed ({res.stderr[-300:]}), rendering without burnt-in text...")
                direct_mux = [
                    "ffmpeg", "-y",
                    "-i", str(raw_video),
                    "-i", str(master_audio),
                    "-c:v", "copy",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-shortest",
                    str(target_video),
                ]
                subprocess.run(direct_mux, capture_output=True, check=True)
        else:
            logger.info(f"Muxing clean video and master soundtrack (clean artwork, no captions): {target_video.name}...")
            direct_mux = [
                "ffmpeg", "-y",
                "-i", str(raw_video),
                "-i", str(master_audio),
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
                str(target_video),
            ]
            subprocess.run(direct_mux, capture_output=True, check=True)

        # Mirror output in project's exports folder
        exports_dir = self.pm.project_dir / "exports"
        exports_dir.mkdir(parents=True, exist_ok=True)
        series_slug = manifest.series.replace(" ", "_").replace(",", "").lower()
        export_copy = exports_dir / f"{series_slug}_ch{manifest.chapter:03d}_pro.mp4"
        try:
            import shutil
            shutil.copy2(target_video, export_copy)
            logger.info(f"Export mirrored to: {export_copy}")
        except Exception:
            pass

        logger.info(f"Pro Render completely succeeded: {target_video}")
        return target_video

    def run_pro_thumbnail(
        self,
        manifest: SceneManifest,
        specific_scene_id: Optional[str] = None,
        specific_panel: Optional[Union[Path, str]] = None,
        include_captions: bool = False,
        custom_hook: Optional[str] = None,
        custom_output: Optional[Path] = None,
    ) -> Path:
        """Execute Stage: Generate YouTube thumbnail from a key dramatic scene without text overlays."""
        thumb_path = custom_output or (self.pm.project_dir / "reports" / "pro_thumbnail.jpg")
        hook_text = custom_hook or (manifest.scenes[0].narration_text if manifest.scenes else manifest.title)
        self.thumbnail_designer.generate_pro_thumbnail(
            artwork_dir=self.pm.artwork_dir,
            manifest=manifest,
            output_file=thumb_path,
            hindi_hook=hook_text,
            custom_panel=specific_panel,
            custom_scene_id=specific_scene_id,
            include_caption=include_captions,
        )

        try:
            import shutil
            exports_dir = self.pm.project_dir / "exports"
            exports_dir.mkdir(parents=True, exist_ok=True)
            series_slug = manifest.series.replace(" ", "_").replace(",", "").lower()
            shutil.copy2(thumb_path, exports_dir / f"{series_slug}_ch{manifest.chapter:03d}_thumbnail.jpg")
        except Exception:
            pass

        return thumb_path

    def run_youtube_kit(
        self,
        manifest: SceneManifest,
        cold_open_duration: float = 0.0,
        custom_output: Optional[Path] = None,
        speed: float = 1.0,
    ) -> Path:
        """Execute Stage: Generate YouTube viral titles, SEO description, chapter timestamps, and tags."""
        kit_path = custom_output or (self.pm.project_dir / "reports" / "youtube_upload_kit.txt")
        self.youtube_kit.build_youtube_kit(
            manifest=manifest,
            output_txt_file=kit_path,
            cold_open_duration=cold_open_duration,
            speed=speed,
        )
        try:
            import shutil
            exports_dir = self.pm.project_dir / "exports"
            exports_dir.mkdir(parents=True, exist_ok=True)
            series_slug = manifest.series.replace(" ", "_").replace(",", "").lower()
            shutil.copy2(kit_path, exports_dir / f"{series_slug}_ch{manifest.chapter:03d}_youtube_kit.txt")
        except Exception:
            pass
        return kit_path

    def run_cold_open(
        self,
        manifest: SceneManifest,
        preferred_scene_id: Optional[str] = None,
        custom_hook: Optional[str] = None,
    ) -> Tuple[Optional[Path], float]:
        """Execute Stage: Generate high-tension 8-12s flash-forward teaser hook."""
        out_dir = self.pm.project_dir / "cold_open"
        return self.cold_open_director.build_cold_open(
            manifest=manifest,
            artwork_dir=self.pm.artwork_dir,
            output_dir=out_dir,
            custom_hook_text=custom_hook,
            preferred_scene_id=preferred_scene_id,
        )

    def apply_speed(self, video: Path, speed: float) -> Path:
        """Apply playback speed multiplier to a video using FFmpeg.

        Uses ``setpts`` for the video stream and ``atempo`` for the audio stream.
        ``atempo`` supports [0.5, 2.0] natively; values outside that range are
        chained automatically (e.g. 3x → two atempo=1.73 filters).

        Args:
            video: Source video file path.
            speed: Playback speed multiplier (e.g. 1.5 for 50 % faster).

        Returns:
            Path to the speed-adjusted output file (``<stem>_1.5x.mp4``).
        """
        if speed == 1.0:
            return video

        out_path = video.with_stem(video.stem + f"_{speed}x")
        pts_factor = round(1.0 / speed, 6)

        # Build atempo filter chain — atempo only accepts [0.5, 2.0]
        import math

        atempo_filters: List[str] = []
        remaining = speed
        while remaining > 2.0:
            atempo_filters.append("atempo=2.0")
            remaining /= 2.0
        while remaining < 0.5:
            atempo_filters.append("atempo=0.5")
            remaining /= 0.5
        atempo_filters.append(f"atempo={round(remaining, 6)}")
        atempo_chain = ",".join(atempo_filters)

        filter_complex = (
            f"[0:v]setpts={pts_factor}*PTS[v];"
            f"[0:a]{atempo_chain}[a]"
        )

        v_enc_args = get_video_encoder_args(quality=20, cpu_preset="fast", nvenc_preset="p4")
        enc_label = "GPU (h264_nvenc)" if is_nvenc_available() else "CPU (libx264)"
        logger.info(f"Applying {speed}x speed to {video.name} → {out_path.name} via {enc_label}")

        cmd = [
            "ffmpeg", "-y",
            "-i", str(video),
            "-filter_complex", filter_complex,
            "-map", "[v]", "-map", "[a]",
            *v_enc_args,
            "-c:a", "aac", "-b:a", "192k",
            str(out_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 and is_nvenc_available():
            logger.warning("NVENC speed-up failed, retrying with CPU libx264...")
            cpu_cmd = [
                "ffmpeg", "-y",
                "-i", str(video),
                "-filter_complex", filter_complex,
                "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k",
                str(out_path),
            ]
            result = subprocess.run(cpu_cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise RuntimeError(
                f"FFmpeg speed-up failed (exit {result.returncode}):\n{result.stderr}"
            )
        logger.info(f"Speed-adjusted video saved: {out_path}")
        return out_path

    def _stitch_bookends(
        self,
        body_video: Path,
        output_video: Path,
        cold_open_clip: Optional[Path] = None,
        include_outro: bool = True,
    ) -> Path:
        """
        Stitch optional Cold Open teaser at the start and 'To Be Continued' (`to_be_continued_black.mp4`)
        at the very end of `body_video` into `output_video`.
        """
        from manhwa_studio.studio_pro.marathon_engine import MarathonEngine

        me = MarathonEngine(self.profile)
        res_dim = me._get_video_dimensions(body_video)
        sr, layout = me._get_video_audio_info(body_video)
        ac_num = "2" if layout == "stereo" else "1"

        parts: List[Path] = []
        temp_files: List[Path] = []

        if cold_open_clip and cold_open_clip.exists() and cold_open_clip.stat().st_size > 1000:
            # Ensure cold_open_clip matches exact resolution and audio sample_rate/channels
            co_norm = self.pm.renders_dir / "_temp_cold_open_norm.mp4"
            w, h = res_dim
            v_enc_args = get_video_encoder_args(quality=19, cpu_preset="veryfast", nvenc_preset="p4")
            cmd_co = [
                "ffmpeg", "-y",
                "-i", str(cold_open_clip),
                "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,fps=30,format=yuv420p",
                *v_enc_args,
                "-c:a", "aac", "-ar", str(sr), "-ac", ac_num, "-b:a", "192k",
                str(co_norm),
            ]
            r_co = subprocess.run(cmd_co, capture_output=True, text=True)
            if r_co.returncode == 0 and co_norm.exists() and co_norm.stat().st_size > 1000:
                parts.append(co_norm)
                temp_files.append(co_norm)

        parts.append(body_video)

        if include_outro:
            outro_norm = self.pm.renders_dir / "_temp_tbc_outro.mp4"
            if me.prepare_outro_clip(outro_norm, resolution=res_dim, audio_sr=sr, audio_layout=layout):
                parts.append(outro_norm)
                temp_files.append(outro_norm)

        if len(parts) == 1:
            if body_video.resolve() != output_video.resolve():
                shutil.copy2(body_video, output_video)
            return output_video

        concat_txt = self.pm.renders_dir / "_temp_bookends_concat.txt"
        concat_txt.write_text(
            "\n".join(f"file '{p.resolve().as_posix()}'" for p in parts),
            encoding="utf-8",
        )
        temp_files.append(concat_txt)

        out_tmp = output_video.with_suffix(".stitched.mp4")
        copy_cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_txt),
            "-c", "copy",
            "-movflags", "+faststart",
            str(out_tmp),
        ]
        res = subprocess.run(copy_cmd, capture_output=True, text=True)
        if res.returncode != 0 or not out_tmp.exists() or out_tmp.stat().st_size < 10000:
            v_enc_args = get_video_encoder_args(quality=19, cpu_preset="fast", nvenc_preset="p4")
            enc_cmd = [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", str(concat_txt),
                *v_enc_args,
                "-c:a", "aac", "-ar", str(sr), "-ac", ac_num, "-b:a", "192k",
                "-movflags", "+faststart",
                str(out_tmp),
            ]
            subprocess.run(enc_cmd, capture_output=True, check=False)

        if out_tmp.exists() and out_tmp.stat().st_size > 10000:
            out_tmp.replace(output_video)

        for tf in temp_files:
            try:
                if tf.exists():
                    tf.unlink()
            except Exception:
                pass

        return output_video

    def run_full_pro_production(
        self,
        force_rebuild_segments: bool = False,
        burn_subtitles: bool = False,
        include_thumbnail_captions: bool = False,
        thumbnail_scene_id: Optional[str] = None,
        thumbnail_panel: Optional[Path] = None,
        enable_cold_open: bool = True,
        enable_outro: bool = False,
        export_short: bool = True,
        speed: float = 1.0,
    ) -> Dict[str, Path]:
        """Execute the complete end-to-end Pro production suite.

        Args:
            force_rebuild_segments: Force re-render all camera-FX segments.
            burn_subtitles: Burn subtitles into video pixels.
            include_thumbnail_captions: Add text badges to thumbnail.
            thumbnail_scene_id: Override scene for thumbnail artwork.
            thumbnail_panel: Override specific panel for thumbnail artwork.
            enable_cold_open: Prepend a dramatic cold-open teaser clip (default: True).
            enable_outro: Append 'To Be Continued' (`to_be_continued_black.mp4`) at the end of this chapter (default: False so marathons only show it once at the very end).
            export_short: Auto-export a 45s 9:16 Vertical YouTube Short from the chapter climax (default: True).
            speed: Playback speed multiplier (e.g. 1.25 or 1.5).
        """
        manifest = self.run_multi_voice(force_rebuild=force_rebuild_segments)
        master_audio = self.run_audio_mastering(manifest)
        subs = self.run_kinetic_subtitles(manifest)
        base_vid = self.run_pro_render(
            manifest,
            master_audio,
            subtitles_file=subs,
            burn_subtitles=burn_subtitles,
            force_rebuild_segments=force_rebuild_segments,
        )

        # Save gapless 1.0x chapter_body.mp4 BEFORE bookends so MarathonEngine can stitch chapters with zero gap
        chapter_body_1x = self.pm.renders_dir / "chapter_body.mp4"
        try:
            shutil.copy2(base_vid, chapter_body_1x)
        except Exception:
            chapter_body_1x = base_vid

        # Optional speed-up pass on the clean chapter body
        if speed != 1.0:
            final_vid = self.apply_speed(base_vid, speed)
            chapter_body_speed = self.pm.renders_dir / f"chapter_body_{speed:g}x.mp4"
            try:
                shutil.copy2(final_vid, chapter_body_speed)
            except Exception:
                chapter_body_speed = final_vid
        else:
            final_vid = base_vid
            chapter_body_speed = chapter_body_1x

        # Generate Cold Open teaser (reusing already-voiced Gemini Puck climax audio)
        cold_open_clip: Optional[Path] = None
        cold_open_dur = 0.0
        if enable_cold_open:
            try:
                cold_open_clip, cold_open_dur = self.run_cold_open(manifest, preferred_scene_id=thumbnail_scene_id)
                if cold_open_clip and speed != 1.0:
                    cold_open_clip = self.apply_speed(cold_open_clip, speed)
                    cold_open_dur = cold_open_dur / speed
            except Exception as co_err:
                logger.warning(f"Cold Open generation skipped ({co_err})")
                cold_open_clip = None
                cold_open_dur = 0.0

        # Stitch [Cold Open + Chapter Body + To Be Continued Outro] into final_vid
        if cold_open_clip or enable_outro:
            final_vid = self._stitch_bookends(
                body_video=chapter_body_speed,
                output_video=final_vid,
                cold_open_clip=cold_open_clip,
                include_outro=enable_outro,
            )
            # Update export mirror with the complete bookended video
            try:
                exports_dir = self.pm.project_dir / "exports"
                exports_dir.mkdir(parents=True, exist_ok=True)
                series_slug = manifest.series.replace(" ", "_").replace(",", "").lower()
                shutil.copy2(final_vid, exports_dir / f"{series_slug}_ch{manifest.chapter:03d}_pro.mp4")
            except Exception:
                pass

        # Auto-generate 45s 9:16 Vertical YouTube Short from the chapter climax to drive views & subscribers
        short_video_path: Optional[Path] = None
        if export_short:
            try:
                from manhwa_studio.studio_pro.social_media_director import SocialMediaDirector
                smd = SocialMediaDirector(self.profile)
                exports_dir = self.pm.project_dir / "exports"
                exports_dir.mkdir(parents=True, exist_ok=True)
                series_slug = manifest.series.replace(" ", "_").replace(",", "").lower()
                short_out = exports_dir / f"{series_slug}_ch{manifest.chapter:03d}_short_9x16.mp4"
                short_video_path = smd.build_vertical_reel_video(
                    source_video=chapter_body_speed,
                    output_reel_mp4=short_out,
                    manifest=manifest,
                    speed=speed,
                    clip_duration=45.0,
                )
                logger.info(f"Auto-exported 9:16 Vertical YouTube Short: {short_video_path}")
            except Exception as sh_err:
                logger.warning(f"Auto YouTube Short generation skipped: {sh_err}")

        thumb = self.run_pro_thumbnail(
            manifest,
            specific_scene_id=thumbnail_scene_id,
            specific_panel=thumbnail_panel,
            include_captions=include_thumbnail_captions,
        )

        yt_kit = self.run_youtube_kit(manifest, cold_open_duration=cold_open_dur, speed=speed)

        # Optional automatic temp segment cleanup if STUDIO_AUTO_CLEAN_SEGMENTS=1
        if self.env_cfg.auto_clean_segments and final_vid.exists() and final_vid.stat().st_size > 50000:
            try:
                seg_dir = self.pm.renders_dir / "segments"
                if seg_dir.exists():
                    shutil.rmtree(seg_dir, ignore_errors=True)
                raw_stitched = self.pm.renders_dir / "raw_stitched.mp4"
                if raw_stitched.exists():
                    raw_stitched.unlink(missing_ok=True)
                logger.info("Auto-cleaned intermediate render segments (STUDIO_AUTO_CLEAN_SEGMENTS=1).")
            except Exception:
                pass

        res_dict: Dict[str, Path] = {
            "video": final_vid,
            "master_audio": master_audio,
            "subtitles": subs,
            "thumbnail": thumb,
            "youtube_kit": yt_kit,
        }
        if short_video_path and short_video_path.exists():
            res_dict["short_video"] = short_video_path
        return res_dict

