"""
Transition filters for smooth visual segment transitions.
"""

from __future__ import annotations

from manhwa_studio.schemas import TransitionType


def get_transition_filter(transition: TransitionType, duration: float, total_duration: float) -> str:
    """
    Generate video fade filters for scene heads or tails.
    """
    if transition == TransitionType.FADE:
        fade_dur = min(0.5, duration / 4.0)
        start_out = max(0.0, total_duration - fade_dur)
        return f"fade=t=in:st=0:d={fade_dur},fade=t=out:st={start_out}:d={fade_dur}"
    return "null"
