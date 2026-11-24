"""
Background music looping, fading, and preparation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from manhwa_studio.logging_config import get_logger

logger = get_logger("manhwa_studio.audio.music")


def build_music_filter(
    target_duration: float,
    volume: float = 0.15,
    fade_in: float = 1.5,
    fade_out: float = 2.0,
) -> str:
    """
    Build FFmpeg audio filter to loop, trim, adjust volume, and apply fade-in/out to music track.
    """
    start_fade_out = max(0.0, target_duration - fade_out)
    return (
        f"aloop=loop=-1:size=2e+09,"
        f"atrim=duration={target_duration},"
        f"volume={volume:.2f},"
        f"afade=t=in:st=0:d={fade_in},"
        f"afade=t=out:st={start_fade_out}:d={fade_out}"
    )
