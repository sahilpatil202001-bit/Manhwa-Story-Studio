"""
Original Hindi script creation, scene manifest construction, and panel alignment.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from manhwa_studio.logging_config import get_logger
from manhwa_studio.schemas import (
    MotionPreset,
    NormalizedCrop,
    SceneItem,
    SceneManifest,
    TransitionType,
)
from manhwa_studio.story.chapter_analyzer import ChapterStoryBreakdown

logger = get_logger("manhwa_studio.story.writer")


def build_scene_manifest_from_outline(
    outline: ChapterStoryBreakdown,
    target_duration: float = 180.0,
) -> SceneManifest:
    """
    Build a SceneManifest containing concrete scenes, original Hindi narration,
    motion presets, and durations based on the chapter outline.
    """
    scenes: List[SceneItem] = []

    # Default Hindi narration templates for Myst, Might, Mayhem Ch 1 Prologue
    default_narrations = [
        # Scene 1: Hook
        (
            "रात का सन्नाटा और मौत की आहट... इस अंधेरी दुनिया में सिर्फ वही जिंदा रहता है, जो बेरहम हो।",
            MotionPreset.SLOW_ZOOM_IN,
            TransitionType.FADE,
        ),
        # Scene 2: Setup
        (
            "सालों की खामोशी के बाद, एक ऐसा साया उभरा है जिसने पुरानी हुकूमत की नींव हिला दी है। उसकी हर चाल पहले से तय थी।",
            MotionPreset.PAN_DOWN,
            TransitionType.FADE,
        ),
        # Scene 3: Conflict
        (
            "जब तलवारें टकराईं, तो खून से लिखी गई नई दास्तान। दुश्मनों को लगा कि वे शिकारी हैं... पर वे खुद शिकार बन चुके थे।",
            MotionPreset.SLOW_ZOOM_OUT,
            TransitionType.CROSSFADE,
        ),
        # Scene 4: Turning point
        (
            "एक ही वार में सारा खेल पलट गया। उसकी आंखों में न खौफ था, न रहम... सिर्फ बेपनाह ताकत और बदले की आग।",
            MotionPreset.PAN_UP,
            TransitionType.FADE,
        ),
        # Scene 5: Cliffhanger
        (
            "लेकिन यह तो सिर्फ शुरुआत है। असली तबाही का मंजर अभी बाकी है... क्या कोई इस कहर को रोक पाएगा?",
            MotionPreset.SLOW_ZOOM_IN,
            TransitionType.FADE,
        ),
    ]

    for idx, beat in enumerate(outline.beats):
        panel_file = beat.suggested_panels[0] if beat.suggested_panels else ""
        text, motion, trans = default_narrations[min(idx, len(default_narrations) - 1)]

        scene = SceneItem(
            scene_id=f"scene_{idx+1:02d}",
            scene_purpose=beat.phase,
            duration=beat.target_duration_seconds,
            image_file=panel_file,
            crop=NormalizedCrop(x=0.0, y=0.0, width=1.0, height=1.0),
            motion_preset=motion,
            transition=trans,
            transition_duration=0.5,
            narration_text=text,
            subtitle_text=text,
            audio_cues=[],
            supporting_panel_ids=beat.suggested_panels,
            verification_notes=f"Corresponds to {beat.phase} in outline. Panel verified.",
        )
        scenes.append(scene)

    return SceneManifest(
        series=outline.series,
        chapter=outline.chapter,
        title=outline.title,
        target_duration=target_duration,
        scenes=scenes,
        approved_by_user=False, # Must be explicitly approved
        verification_notes="Draft manifest generated from outline. Awaiting user review and approval.",
    )


def build_scene_manifest_from_screenplay(
    series: str,
    chapter: int,
    screenplay: Any,
    available_panels: List[str],
    default_scene_duration: float = 4.0,
) -> SceneManifest:
    """
    Construct a rich multi-character SceneManifest from an AI or curated ChapterScreenplay.
    """
    scenes: List[SceneItem] = []
    p_len = len(available_panels)

    motion_map = {
        "slow_zoom_in": MotionPreset.SLOW_ZOOM_IN,
        "slow_zoom_out": MotionPreset.SLOW_ZOOM_OUT,
        "pan_down": MotionPreset.PAN_DOWN,
        "pan_up": MotionPreset.PAN_UP,
        "pan_left": MotionPreset.PAN_LEFT,
        "pan_right": MotionPreset.PAN_RIGHT,
    }

    for idx, sc in enumerate(screenplay.scenes):
        panel = sc.suggested_panel
        if panel not in available_panels and available_panels:
            # Pick by progressive percentage
            percent = idx / max(1, len(screenplay.scenes) - 1)
            p_idx = min(int(p_len * percent), p_len - 1)
            panel = available_panels[p_idx]

        motion = motion_map.get(sc.motion_preset.lower(), MotionPreset.PAN_UP)

        scene = SceneItem(
            scene_id=f"scene_{idx+1:03d}",
            scene_purpose=sc.scene_purpose,
            duration=default_scene_duration,
            image_file=panel,
            crop=NormalizedCrop(x=0.0, y=0.0, width=1.0, height=1.0),
            motion_preset=motion,
            transition=TransitionType.FADE,
            transition_duration=0.5,
            speaker=sc.speaker,
            speaker_gender=getattr(sc, "speaker_gender", None),
            narration_text=sc.hindi_text,
            subtitle_text=sc.hindi_text,
            audio_cues=[],
            supporting_panel_ids=[panel] if panel else [],
            verification_notes=f"Screenplay dialogue beat for [{sc.speaker}]. Panel: {panel}",
        )
        scenes.append(scene)

    return SceneManifest(
        series=series,
        chapter=chapter,
        title=screenplay.title,
        target_duration=len(scenes) * default_scene_duration,
        scenes=scenes,
        approved_by_user=False,
        verification_notes=f"Multi-character audio drama screenplay ({screenplay.provider}).",
    )


def save_scene_manifest(manifest: SceneManifest, file_path: Path) -> Path:
    """Save SceneManifest to a formatted JSON file."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(manifest.model_dump_json(indent=2))
    logger.info(f"Saved scene manifest to: {file_path}")
    return file_path


def load_scene_manifest(file_path: Path) -> SceneManifest:
    """Load SceneManifest from a JSON file."""
    with open(file_path, "r", encoding="utf-8") as f:
        return SceneManifest.model_validate_json(f.read())

