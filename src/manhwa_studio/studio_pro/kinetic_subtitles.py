"""
Kinetic Animated Anime Subtitle Engine.
Generates stylized Advanced SubStation Alpha (.ass) subtitles with pop animations,
character speaker tags, and keyword color highlights for high YouTube retention.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from manhwa_studio.logging_config import get_logger
from manhwa_studio.schemas import SceneManifest, SceneItem
from manhwa_studio.studio_pro.series_manager import SeriesProfile, SubtitleStyle

logger = get_logger("manhwa_studio.pro.subtitles")


class KineticSubtitleGenerator:
    """Creates animated, high-contrast, pop-in .ass subtitles tailored for Hindi comic dubs."""

    def __init__(self, profile: SeriesProfile):
        self.profile = profile
        self.style = profile.subtitle_style

    def format_timestamp(self, seconds: float) -> str:
        """Format seconds into ASS timestamp format: H:MM:SS.cs"""
        hrs = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        cs = int(round((seconds - int(seconds)) * 100))
        if cs >= 100:
            secs += 1
            cs -= 100
        return f"{hrs}:{mins:02d}:{secs:02d}.{cs:02d}"

    def highlight_keywords_in_text(self, text: str) -> str:
        """
        Highlight dramatic keywords with distinct colors:
        - Red: Danger, death, blood, attack (&H0033FF)
        - Yellow/Gold: Powers, names, titles, legendary items (&H00FFFF)
        - Cyan/Purple: Heavenly demon, aura, mystery (&HFF9900)
        """
        highlighted = text

        # Red keyword patterns (Blood, kill, murder, danger)
        red_words = [r"\bखून\b", r"\bमौत\b", r"\bलाश\b", r"\bकाट\b", r"\bवार\b", r"\bहमला\b", r"\bखौफनाक\b", r"\bबेरहमी\b", r"\bकातिल\b"]
        for rw in red_words:
            highlighted = re.sub(rw, r"{\\c&H0033FF&}\g<0>{\\c&H00FFFFFF&}", highlighted)

        # Yellow/Gold keyword patterns (Names, titles, power)
        gold_words = [r"\bहेवनली डेमन\b", r"\bचेओन मा\b", r"\bचोन मा\b", r"\bनैनो मशीन\b", r"\bमोक ग्योंगवून\b", r"\bमोक ग्योंगवुन\b", r"\bदादाजी\b"]
        for gw in gold_words:
            highlighted = re.sub(gw, r"{\\c&H00FFFF&}\g<0>{\\c&H00FFFFFF&}", highlighted)

        return highlighted

    def generate_ass(
        self,
        manifest: SceneManifest,
        output_path: Path,
        video_width: int = 1080,
        video_height: int = 1920,
    ) -> Path:
        """Compile scene dialogue and narration into an animated .ass subtitle file."""
        st = self.style
        is_vertical = video_height > video_width
        margin_v = 260 if is_vertical else 75
        tag_margin_v = margin_v + (70 if is_vertical else 55)
        font_sz = max(st.font_size, 52) if is_vertical else st.font_size
        font_name = "Nirmala UI" if (not st.font_name or st.font_name.lower() in ["arial", "sans-serif", "helvetica"]) else st.font_name

        header = f"""[Script Info]
Title: {manifest.series} - Chapter {manifest.chapter} Kinetic Subtitles
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: {video_width}
PlayResY: {video_height}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: AnimePop,{font_name},{font_sz},{st.primary_color},{st.secondary_color},{st.outline_color},{st.back_color},-1,0,0,0,100,100,1,0,1,{st.outline_width},{st.shadow_depth},2,60,60,{margin_v},1
Style: SpeakerTag,{font_name},{int(font_sz * 0.7)},&H0000FFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,1,0,1,3,1,2,60,60,{tag_margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        dialogue_lines: List[str] = []
        current_time = 0.0

        for scene in manifest.scenes:
            dur = scene.actual_audio_duration or scene.duration
            # Slight padding before and after dialogue for clean pacing
            start_t = current_time + 0.05
            end_t = current_time + max(dur, 1.2) - 0.05

            start_str = self.format_timestamp(start_t)
            end_str = self.format_timestamp(end_t)

            speaker = (scene.speaker or "").strip()
            raw_text = (scene.subtitle_text or scene.narration_text or "").strip()

            if not raw_text:
                current_time += scene.duration
                continue

            # Add pop animation tag: scale from 108% down to 100% in 120ms
            pop_tag = r"{\t(0,120,\fscx108\fscy108)\t(120,220,\fscx100\fscy100)}" if st.pop_animation else ""

            # Highlight dramatic keywords
            styled_text = self.highlight_keywords_in_text(raw_text)

            # If a distinct character is speaking (not generic narrator), show a sleek speaker badge above dialogue
            if speaker and speaker.lower() not in ["narrator", "सूत्रधार"]:
                # Speaker badge line
                speaker_badge = f"{pop_tag}[ {speaker.upper()} ]"
                dialogue_lines.append(
                    f"Dialogue: 1,{start_str},{end_str},SpeakerTag,,0,0,0,,{speaker_badge}"
                )

            # Main animated dialogue line
            final_line = f"{pop_tag}{styled_text}"
            dialogue_lines.append(
                f"Dialogue: 0,{start_str},{end_str},AnimePop,,0,0,0,,{final_line}"
            )

            current_time += scene.duration

        content = header + "\n".join(dialogue_lines) + "\n"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
        logger.info(f"Generated kinetic anime subtitles ({len(dialogue_lines)} events) at: {output_path}")
        return output_path
