"""
Safe FFmpeg and FFprobe subprocess execution wrappers.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

from manhwa_studio.logging_config import get_logger

logger = get_logger("manhwa_studio.rendering.ffmpeg")


def find_executable(name: str, env_var: str) -> str:
    """Find path to executable in PATH or from environment variable override."""
    override = os.environ.get(env_var)
    if override and Path(override).exists():
        return override

    found = shutil.which(name)
    if found:
        return found

    raise FileNotFoundError(
        f"Required executable '{name}' was not found in PATH or '{env_var}'. "
        f"Please install {name} or specify its location."
    )


def get_ffmpeg_path() -> str:
    return find_executable("ffmpeg", "STUDIO_FFMPEG_PATH")


def get_ffprobe_path() -> str:
    return find_executable("ffprobe", "STUDIO_FFPROBE_PATH")


_GPU_ENCODER: Optional[str] = None


def detect_gpu_encoder() -> str:
    """
    Auto-detect the fastest working hardware H.264 encoder on this system:
    1. h264_nvenc (NVIDIA GPU)
    2. h264_amf (AMD Radeon GPU)
    3. h264_qsv (Intel QuickSync GPU)
    4. h264_mf (Windows MediaFoundation Hardware Encoder)
    Falls back to 'libx264' (CPU) if no hardware encoder succeeds.
    """
    global _GPU_ENCODER
    if _GPU_ENCODER is not None:
        return _GPU_ENCODER

    if os.environ.get("STUDIO_DISABLE_GPU", "").strip().lower() in ("1", "true", "yes"):
        _GPU_ENCODER = "libx264"
        return _GPU_ENCODER

    try:
        ffmpeg_exe = get_ffmpeg_path()
    except Exception:
        _GPU_ENCODER = "libx264"
        return _GPU_ENCODER

    candidates = [
        ("h264_nvenc", ["-c:v", "h264_nvenc", "-preset", "p4"]),
        ("h264_amf", ["-c:v", "h264_amf", "-quality", "balanced"]),
        ("h264_qsv", ["-c:v", "h264_qsv", "-preset", "fast"]),
    ]

    for enc_name, enc_flags in candidates:
        try:
            cmd = [
                ffmpeg_exe,
                "-hide_banner",
                "-loglevel", "error",
                "-f", "lavfi",
                "-i", "color=c=black:s=256x256:d=0.1",
                *enc_flags,
                "-pix_fmt", "yuv420p",
                "-f", "null",
                "-",
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=6)
            if res.returncode == 0:
                _GPU_ENCODER = enc_name
                logger.info(f"Hardware GPU video encoder detected and enabled: {enc_name}")
                return _GPU_ENCODER
        except Exception:
            continue

    _GPU_ENCODER = "libx264"
    logger.info("No hardware H.264 encoder detected; using multi-threaded CPU libx264.")
    return _GPU_ENCODER


def is_nvenc_available() -> bool:
    """Return True if any GPU hardware encoder (NVENC, AMF, QSV) is active."""
    return detect_gpu_encoder() != "libx264"


def get_video_encoder_args(
    quality: int = 20,
    cpu_preset: str = "veryfast",
    nvenc_preset: str = "p4",
    use_gpu: bool = True,
) -> List[str]:
    """
    Return optimal FFmpeg video codec arguments for the detected GPU (`h264_nvenc`,
    `h264_amf`, `h264_qsv`) or fall back to `libx264`.
    """
    enc = detect_gpu_encoder() if use_gpu else "libx264"
    if enc == "h264_nvenc":
        return [
            "-c:v", "h264_nvenc",
            "-preset", nvenc_preset,
            "-rc", "vbr",
            "-cq", str(quality),
            "-pix_fmt", "yuv420p",
        ]
    elif enc == "h264_amf":
        return [
            "-c:v", "h264_amf",
            "-quality", "balanced",
            "-rc", "cqp",
            "-qp_i", str(quality),
            "-qp_p", str(quality),
            "-pix_fmt", "yuv420p",
        ]
    elif enc == "h264_qsv":
        return [
            "-c:v", "h264_qsv",
            "-preset", "fast",
            "-global_quality", str(quality),
            "-pix_fmt", "yuv420p",
        ]
    return [
        "-c:v", "libx264",
        "-preset", cpu_preset,
        "-crf", str(quality),
        "-pix_fmt", "yuv420p",
    ]



def run_ffmpeg_command(
    args: List[str],
    timeout_seconds: Optional[int] = 600,
) -> subprocess.CompletedProcess[str]:
    """
    Execute an FFmpeg command with safe list-based arguments.
    Raises RuntimeError on non-zero exit with stderr details.
    """
    ffmpeg_exe = get_ffmpeg_path()
    full_cmd = [ffmpeg_exe, "-hide_banner", "-loglevel", "error"] + args

    logger.debug(f"Running FFmpeg: {' '.join(full_cmd[:8])}...")

    try:
        proc = subprocess.run(
            full_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"FFmpeg command timed out after {timeout_seconds}s.") from exc
    except Exception as exc:
        raise RuntimeError(f"Failed to start FFmpeg subprocess: {exc}") from exc

    if proc.returncode != 0:
        err_msg = proc.stderr.strip() or proc.stdout.strip()
        logger.error(f"FFmpeg failed with exit code {proc.returncode}:\n{err_msg}")
        raise RuntimeError(f"FFmpeg command failed ({proc.returncode}): {err_msg}")

    return proc
