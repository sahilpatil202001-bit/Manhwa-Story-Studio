"""
Final MP4 assembly: segment concatenation, audio muxing, subtitle burning, and faststart encoding.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from manhwa_studio.config import AppConfig
from manhwa_studio.logging_config import get_logger
from manhwa_studio.rendering.ffmpeg import get_video_encoder_args, run_ffmpeg_command

logger = get_logger("manhwa_studio.rendering.final")


def escape_ffmpeg_path(path: Path) -> str:
    """Escape Windows file paths for FFmpeg filter arguments (subtitles filter)."""
    p_str = str(path.resolve()).replace("\\", "/")
    # Colons in Windows drive letters (C:) must be escaped as C\\: in ffmpeg filters
    p_str = p_str.replace(":", "\\:")
    p_str = p_str.replace("'", "\\'")
    return p_str


def concatenate_segments(
    segment_paths: List[Path],
    concat_list_file: Path,
    output_merged_video: Path,
    fps: int = 30,
) -> Path:
    """
    Concatenate all rendered segment MP4s into a single video stream using FFmpeg concat demuxer.
    """
    if not segment_paths:
        raise ValueError("Cannot concatenate: segment_paths is empty.")

    concat_list_file.parent.mkdir(parents=True, exist_ok=True)
    with open(concat_list_file, "w", encoding="utf-8") as f:
        for seg in segment_paths:
            # Use forward slashes in concat file
            clean_path = str(seg.resolve()).replace("\\", "/")
            f.write(f"file '{clean_path}'\n")

    cmd = [
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_list_file),
        "-c:v", "copy",
        "-an",
        "-y", str(output_merged_video),
    ]

    try:
        run_ffmpeg_command(cmd)
    except Exception as exc:
        # Fallback to GPU/CPU transcode concat if copy failed
        logger.warning(f"Concat stream copy failed, falling back to transcode concat: {exc}")
        v_enc_args = get_video_encoder_args(quality=20, cpu_preset="fast", nvenc_preset="p4")
        reencode_cmd = [
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list_file),
            *v_enc_args,
            "-r", str(fps),
            "-an",
            "-y", str(output_merged_video),
        ]
        run_ffmpeg_command(reencode_cmd)

    return output_merged_video


def assemble_final_video(
    merged_video_path: Path,
    mixed_audio_path: Path,
    output_mp4_path: Path,
    config: AppConfig,
    subtitle_ass_path: Optional[Path] = None,
) -> Path:
    """
    Mux merged video and mixed audio into final MP4, optionally burning in ASS/SRT subtitles.
    """
    output_mp4_path.parent.mkdir(parents=True, exist_ok=True)

    inputs = [
        "-i", str(merged_video_path.resolve()),
        "-i", str(mixed_audio_path.resolve()),
    ]

    v_filters: List[str] = []

    # Burn subtitles if requested and available
    if config.subtitles.enabled and config.subtitles.burn_in and subtitle_ass_path and subtitle_ass_path.exists():
        escaped_sub = escape_ffmpeg_path(subtitle_ass_path)
        v_filters.append(f"ass='{escaped_sub}'")

    cmd = inputs.copy()

    if v_filters:
        cmd.extend(["-vf", ",".join(v_filters)])
        cmd.extend(get_video_encoder_args(quality=config.video.crf, cpu_preset=config.video.preset, nvenc_preset="p4"))
    else:
        # Stream copy video if no filters needed
        cmd.extend(["-c:v", "copy"])

    cmd.extend([
        "-c:a", config.audio.codec,
        "-b:a", f"{config.audio.bitrate_kbps}k",
        "-pix_fmt", config.video.pixel_format,
        "-shortest",
    ])

    if config.video.faststart:
        cmd.extend(["-movflags", "+faststart"])

    cmd.extend(["-y", str(output_mp4_path.resolve())])

    run_ffmpeg_command(cmd)
    logger.info(f"Assembled final production MP4 at: {output_mp4_path}")
    return output_mp4_path
