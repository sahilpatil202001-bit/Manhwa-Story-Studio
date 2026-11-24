"""
Individual scene segment rendering engine.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from manhwa_studio.config import VideoSettings
from manhwa_studio.logging_config import get_logger
from manhwa_studio.rendering.ffmpeg import get_video_encoder_args, run_ffmpeg_command
from manhwa_studio.schemas import SceneItem
from manhwa_studio.visuals.crop import apply_normalized_crop
from manhwa_studio.visuals.motion import build_scene_visual_filter

logger = get_logger("manhwa_studio.rendering.segments")


def render_scene_segment(
    scene: SceneItem,
    artwork_dir: Path,
    output_dir: Path,
    video_settings: VideoSettings,
    fill_mode: str = "blur_background",
    zoom_scale: float = 1.08,
) -> Path:
    """
    Render a single SceneItem into a 1080x1920 30fps MP4 segment.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    segment_mp4 = output_dir / f"{scene.scene_id}.mp4"
    if segment_mp4.exists() and segment_mp4.stat().st_size > 1000:
        from manhwa_studio.quality.media_probe import probe_media
        try:
            p = probe_media(segment_mp4)
            if abs(p.duration_seconds - scene.duration) < 0.25:
                return segment_mp4
        except Exception:
            pass

    raw_img = artwork_dir / scene.image_file
    if not raw_img.exists():
        raise FileNotFoundError(f"Artwork image for scene '{scene.scene_id}' not found at: {raw_img}")

    # Prepare framed and gutter-trimmed image
    framed_img = output_dir / f"{scene.scene_id}_framed.jpg"
    apply_normalized_crop(raw_img, scene.crop, framed_img)
    input_image = framed_img

    filter_complex = build_scene_visual_filter(
        motion=scene.motion_preset,
        duration=scene.duration,
        width=video_settings.width,
        height=video_settings.height,
        fps=video_settings.fps,
        fill_mode=fill_mode,
        zoom_scale=zoom_scale,
    )

    v_enc_args = get_video_encoder_args(quality=video_settings.crf, cpu_preset=video_settings.preset, nvenc_preset="p4")
    cmd = [
        "-loop", "1",
        "-i", str(input_image.resolve()),
        "-filter_complex", filter_complex,
        "-map", "[v_out]",
        *v_enc_args,
        "-t", f"{scene.duration:.3f}",
        "-r", str(video_settings.fps),
        "-an", # Visual only for individual segments
        "-y", str(segment_mp4),
    ]

    run_ffmpeg_command(cmd)
    logger.info(f"Rendered segment '{scene.scene_id}' ({scene.duration:.1f}s) to: {segment_mp4.name}")
    return segment_mp4
