"""
Timecode conversion and formatting utilities for subtitles and FFmpeg.
"""

from __future__ import annotations

import math


def seconds_to_srt_timecode(seconds: float) -> str:
    """
    Convert seconds to SRT timecode format: HH:MM:SS,mmm
    Example: 83.456 -> 00:01:23,456
    """
    if seconds < 0:
        seconds = 0.0

    total_ms = int(round(seconds * 1000.0))
    ms = total_ms % 1000
    total_seconds = total_ms // 1000
    s = total_seconds % 60
    total_minutes = total_seconds // 60
    m = total_minutes % 60
    h = total_minutes // 60

    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def seconds_to_ass_timecode(seconds: float) -> str:
    """
    Convert seconds to ASS timecode format: H:MM:SS.cc (centiseconds)
    Example: 83.456 -> 0:01:23.46
    """
    if seconds < 0:
        seconds = 0.0

    total_cs = int(round(seconds * 100.0))
    cs = total_cs % 100
    total_seconds = total_cs // 100
    s = total_seconds % 60
    total_minutes = total_seconds // 60
    m = total_minutes % 60
    h = total_minutes // 60

    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def srt_timecode_to_seconds(timecode: str) -> float:
    """
    Parse an SRT timecode (HH:MM:SS,mmm) into seconds float.
    """
    timecode = timecode.strip().replace(".", ",")
    parts = timecode.split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid SRT timecode format: '{timecode}'")

    hours = int(parts[0])
    minutes = int(parts[1])
    sec_parts = parts[2].split(",")
    seconds = int(sec_parts[0])
    milliseconds = int(sec_parts[1]) if len(sec_parts) > 1 else 0

    return hours * 3600.0 + minutes * 60.0 + seconds + (milliseconds / 1000.0)


def format_duration(seconds: float) -> str:
    """Format duration into human readable string e.g. 3m 00s or 45.2s."""
    m, s = divmod(seconds, 60)
    if m > 0:
        return f"{int(m)}m {s:04.1f}s"
    return f"{s:04.1f}s"
