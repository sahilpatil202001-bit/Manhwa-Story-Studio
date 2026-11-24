"""
SRT and ASS subtitle generation with mobile safe zone styling and Unicode Hindi support.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

from manhwa_studio.config import SubtitlesSettings
from manhwa_studio.logging_config import get_logger
from manhwa_studio.schemas import SceneManifest
from manhwa_studio.utils.timecodes import seconds_to_ass_timecode, seconds_to_srt_timecode

logger = get_logger("manhwa_studio.subtitles.generate")


def split_narration_chunks(text: str, max_words: int = 7) -> List[str]:
    """Split narration text into bite-sized subtitle lines suited for vertical video mobile screens."""
    words = text.strip().split()
    if not words:
        return []
    chunks = []
    for i in range(0, len(words), max_words):
        chunks.append(" ".join(words[i : i + max_words]))
    return chunks


def build_subtitle_segments(
    manifest: SceneManifest,
    max_words_per_line: int = 7,
) -> List[Tuple[float, float, str, str]]:
    """
    Generate sequential (start_time, end_time, text, speaker) segments from SceneManifest.
    """
    timeline: List[Tuple[float, float, str, str]] = []
    current_time = 0.0

    for scene in manifest.scenes:
        dur = scene.duration
        scene_start = current_time
        scene_end = current_time + dur
        speaker = getattr(scene, "speaker", "Narrator") or "Narrator"

        raw_text = scene.subtitle_text or scene.narration_text
        chunks = split_narration_chunks(raw_text, max_words=max_words_per_line)

        if not chunks:
            current_time = scene_end
            continue

        # Sync subtitle display duration to the actual spoken voiceover duration
        speech_dur = min(dur, scene.actual_audio_duration) if getattr(scene, "actual_audio_duration", None) else dur
        chunk_duration = speech_dur / len(chunks)
        for idx, chunk in enumerate(chunks):
            c_start = scene_start + (idx * chunk_duration)
            c_end = scene_start + ((idx + 1) * chunk_duration)
            timeline.append((c_start, max(c_start + 0.1, c_end - 0.05), chunk, speaker))

        current_time = scene_end

    return timeline


def generate_srt(segments: List[Tuple[float, float, str, str]], output_path: Path) -> Path:
    """Generate a standard UTF-8 SRT subtitle file with optional speaker labels."""
    lines = []
    for idx, (start, end, text, speaker) in enumerate(segments, 1):
        lines.append(str(idx))
        lines.append(f"{seconds_to_srt_timecode(start)} --> {seconds_to_srt_timecode(end)}")
        if speaker and speaker.lower() != "narrator":
            lines.append(f"[{speaker}]: {text}")
        else:
            lines.append(text)
        lines.append("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.info(f"Generated SRT with {len(segments)} segments at: {output_path}")
    return output_path


def generate_ass(
    segments: List[Tuple[float, float, str, str]],
    output_path: Path,
    settings: SubtitlesSettings,
    video_width: int = 1080,
    video_height: int = 1920,
) -> Path:
    """
    Generate an Advanced SubStation Alpha (.ass) file with distinct colored styles per character speaker.
    """
    ass_template = f"""[Script Info]
Title: Manhwa Story Studio Multi-Character Subtitles
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.601
PlayResX: {video_width}
PlayResY: {video_height}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{settings.font_name},{settings.font_size * 2},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,{settings.outline_width * 2},2,2,40,40,{settings.bottom_margin},1
Style: Protagonist,{settings.font_name},{settings.font_size * 2 + 2},&H0000FFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,{settings.outline_width * 2 + 1},2,2,40,40,{settings.bottom_margin},1
Style: Villain,{settings.font_name},{settings.font_size * 2 + 2},&H003333FF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,{settings.outline_width * 2 + 1},2,2,40,40,{settings.bottom_margin},1
Style: Female,{settings.font_name},{settings.font_size * 2},&H00FFFF00,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,{settings.outline_width * 2},2,2,40,40,{settings.bottom_margin},1
Style: Elder,{settings.font_name},{settings.font_size * 2},&H00CCCCCC,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,{settings.outline_width * 2},2,2,40,40,{settings.bottom_margin},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for start, end, text, speaker in segments:
        s_time = seconds_to_ass_timecode(start)
        e_time = seconds_to_ass_timecode(end)

        spk_lower = speaker.lower()
        if any(k in spk_lower for k in ["hero", "protagonist", "mok", "gyeongwoon"]):
            style_name = "Protagonist"
        elif any(k in spk_lower for k in ["villain", "enemy", "bandit", "antagonist"]):
            style_name = "Villain"
        elif any(k in spk_lower for k in ["female", "woman", "girl", "assassin", "sister"]):
            style_name = "Female"
        elif any(k in spk_lower for k in ["elder", "master", "old"]):
            style_name = "Elder"
        else:
            style_name = "Default"

        safe_text = text.replace("{", "\\{").replace("}", "\\}")
        events.append(f"Dialogue: 0,{s_time},{e_time},{style_name},{speaker},0,0,0,,{safe_text}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(ass_template + "\n".join(events) + "\n")

    logger.info(f"Generated multi-character styled ASS subtitles at: {output_path}")
    return output_path
