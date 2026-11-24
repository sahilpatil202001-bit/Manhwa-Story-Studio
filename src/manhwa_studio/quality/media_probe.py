"""
FFprobe wrapper to inspect and validate audio/video media containers and streams.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from manhwa_studio.logging_config import get_logger
from manhwa_studio.rendering.ffmpeg import get_ffprobe_path
from manhwa_studio.schemas import MediaProbeResult

logger = get_logger("manhwa_studio.quality.probe")


def probe_media(file_path: Path) -> MediaProbeResult:
    """
    Run ffprobe in JSON mode on target media file and return structured probe result.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"Media file not found for probe: {file_path}")

    ffprobe_exe = get_ffprobe_path()
    cmd = [
        ffprobe_exe,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(file_path.resolve()),
    ]

    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"FFprobe failed on {file_path.name}: {proc.stderr}")

    data: Dict[str, Any] = json.loads(proc.stdout)
    fmt = data.get("format", {})
    streams = data.get("streams", [])

    duration = float(fmt.get("duration", 0.0))
    size_bytes = int(fmt.get("size", file_path.stat().st_size))
    bitrate = float(fmt.get("bit_rate", 0)) / 1000.0 if fmt.get("bit_rate") else None
    format_name = fmt.get("format_name", "")

    has_video = False
    has_audio = False
    width = None
    height = None
    fps = None
    video_codec = None
    pix_fmt = None
    audio_codec = None
    audio_rate = None
    audio_channels = None

    for s in streams:
        c_type = s.get("codec_type")
        if c_type == "video" and not has_video:
            has_video = True
            width = int(s.get("width", 0))
            height = int(s.get("height", 0))
            video_codec = s.get("codec_name")
            pix_fmt = s.get("pix_fmt")
            # Calculate FPS from r_frame_rate e.g. "30/1"
            r_rate = s.get("r_frame_rate", "30/1")
            try:
                num, den = map(int, r_rate.split("/"))
                fps = round(num / den, 2) if den > 0 else 30.0
            except Exception:
                fps = 30.0
        elif c_type == "audio" and not has_audio:
            has_audio = True
            audio_codec = s.get("codec_name")
            audio_rate = int(s.get("sample_rate", 0))
            audio_channels = int(s.get("channels", 0))

    aspect_str = f"{width}:{height}" if width and height else None

    return MediaProbeResult(
        filepath=str(file_path),
        format_name=format_name,
        duration_seconds=round(duration, 2),
        size_bytes=size_bytes,
        bitrate_kbps=round(bitrate, 1) if bitrate else None,
        has_video=has_video,
        has_audio=has_audio,
        width=width,
        height=height,
        aspect_ratio=aspect_str,
        fps=fps,
        video_codec=video_codec,
        pixel_format=pix_fmt,
        audio_codec=audio_codec,
        audio_sample_rate=audio_rate,
        audio_channels=audio_channels,
    )
