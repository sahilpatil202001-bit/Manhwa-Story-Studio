"""
Structured chapter story breakdown and narrative structure organizer.
"""

from __future__ import annotations

from typing import Any, Dict, List
from pydantic import BaseModel, Field


class StoryBeat(BaseModel):
    beat_id: str
    phase: str # "hook", "setup", "conflict", "turning_point", "cliffhanger"
    description: str
    key_characters: List[str] = Field(default_factory=list)
    suggested_panels: List[str] = Field(default_factory=list)
    target_duration_seconds: float = 15.0
    narration_points: List[str] = Field(default_factory=list)


class ChapterStoryBreakdown(BaseModel):
    series: str
    chapter: int
    title: str
    overall_theme: str
    beats: List[StoryBeat] = Field(default_factory=list)
    verified_facts: List[str] = Field(default_factory=list)
    unresolved_questions: List[str] = Field(default_factory=list)


def create_initial_story_outline(
    series: str,
    chapter: int,
    title: str,
    panel_files: List[str],
    target_duration: float = 180.0,
) -> ChapterStoryBreakdown:
    """
    Generate a balanced 5-part narrative template mapped across available panels.
    Prevents padding or unsupported speculation by structuring verifiable story beats.
    """
    total_panels = len(panel_files)
    if total_panels == 0:
        panels_chunk = [[], [], [], [], []]
    else:
        # Distribute panels across 5 beats
        chunk_size = max(1, math_ceil := (total_panels + 4) // 5)
        panels_chunk = [
            panel_files[i * chunk_size : min((i + 1) * chunk_size, total_panels)]
            for i in range(5)
        ]

    # Target durations tailored to pacing
    d_hook = round(target_duration * 0.12, 1) # ~20s
    d_setup = round(target_duration * 0.22, 1) # ~40s
    d_conflict = round(target_duration * 0.28, 1) # ~50s
    d_turn = round(target_duration * 0.22, 1) # ~40s
    d_cliff = round(target_duration - (d_hook + d_setup + d_conflict + d_turn), 1) # ~30s

    beats = [
        StoryBeat(
            beat_id="beat_01_hook",
            phase="hook",
            description="Mysterious opening introducing the central tension.",
            suggested_panels=panels_chunk[0],
            target_duration_seconds=d_hook,
            narration_points=["Hook viewers within 3 seconds with dark suspenseful atmosphere"],
        ),
        StoryBeat(
            beat_id="beat_02_setup",
            phase="setup",
            description="Context, setting, and introduction of the protagonist or opposing forces.",
            suggested_panels=panels_chunk[1],
            target_duration_seconds=d_setup,
            narration_points=["Establish the world rules and high stakes"],
        ),
        StoryBeat(
            beat_id="beat_03_conflict",
            phase="conflict",
            description="Direct confrontation, sudden discovery, or rising danger.",
            suggested_panels=panels_chunk[2],
            target_duration_seconds=d_conflict,
            narration_points=["Build suspense with sharp, transformative storytelling"],
        ),
        StoryBeat(
            beat_id="beat_04_turning_point",
            phase="turning_point",
            description="Unforeseen move or revelation that flips the balance of power.",
            suggested_panels=panels_chunk[3],
            target_duration_seconds=d_turn,
            narration_points=["Climactic realization changing the character's fate"],
        ),
        StoryBeat(
            beat_id="beat_05_cliffhanger",
            phase="cliffhanger",
            description="Ominous question and dramatic cutoff for next chapter.",
            suggested_panels=panels_chunk[4],
            target_duration_seconds=d_cliff,
            narration_points=["Powerful closing hook leaving the audience desperate for Chapter 2"],
        ),
    ]

    return ChapterStoryBreakdown(
        series=series,
        chapter=chapter,
        title=title,
        overall_theme="Dark, calculated martial mystery and ruthless ambition",
        beats=beats,
        verified_facts=["Story events strictly limited to verified panel events"],
        unresolved_questions=["Awaiting manual confirmation of specific character names"],
    )
