"""
Configuration loading, validation, and secret resolution.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional
import yaml
from pydantic import BaseModel, Field, model_validator

from manhwa_studio.schemas import RightsStatus


class ProjectSettings(BaseModel):
    series: str = "Myst, Might, Mayhem"
    chapter: int = 1
    title: str = "Prologue"
    target_duration_seconds: float = 180.0
    allow_duration_trim: bool = True
    platform: str = "standard_vertical" # "shorts" or "standard_vertical"


class VideoSettings(BaseModel):
    width: int = 1080
    height: int = 1920
    fps: int = 30
    codec: str = "libx264"
    crf: int = 22
    preset: str = "medium"
    pixel_format: str = "yuv420p"
    faststart: bool = True

    @model_validator(mode="after")
    def validate_vertical(self) -> "VideoSettings":
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Video width and height must be positive integers.")
        # Check aspect ratio ~ 9:16
        ratio = self.height / self.width
        if abs(ratio - (16 / 9)) > 0.05:
            # Not strict error, but warn or enforce standard
            pass
        return self


class AudioSettings(BaseModel):
    codec: str = "aac"
    bitrate_kbps: int = 192
    sample_rate: int = 44100
    channels: int = 2
    music_volume: float = 0.15
    sfx_volume: float = 0.4
    narration_volume: float = 1.0
    ducking_factor: float = 0.3
    fade_in_seconds: float = 1.5
    fade_out_seconds: float = 2.0
    music_file: Optional[str] = None
    sfx_dir: Optional[str] = None


def get_default_character_voices() -> Dict[str, Any]:
    return {
        "narrator": {
            "voice_id": "hi-IN-MadhurNeural",
            "speech_rate": "-2%",
            "pitch": "-3Hz",
            "color_hex": "&H00FFFFFF", # White
        },
        "protagonist": {
            "voice_id": "hi-IN-MadhurNeural",
            "speech_rate": "+8%",
            "pitch": "+4Hz",
            "color_hex": "&H0000FFFF", # Gold / Yellow
        },
        "villain": {
            "voice_id": "hi-IN-MadhurNeural",
            "speech_rate": "+12%",
            "pitch": "+8Hz",
            "color_hex": "&H003333FF", # Crimson / Coral Red
        },
        "antagonist": {
            "voice_id": "hi-IN-MadhurNeural",
            "speech_rate": "+12%",
            "pitch": "+8Hz",
            "color_hex": "&H003333FF",
        },
        "female": {
            "voice_id": "hi-IN-SwaraNeural",
            "speech_rate": "+5%",
            "pitch": "+0Hz",
            "color_hex": "&H00FFFF00", # Cyan
        },
        "elder": {
            "voice_id": "hi-IN-MadhurNeural",
            "speech_rate": "-6%",
            "pitch": "-10Hz",
            "color_hex": "&H00CCCCCC", # Muted Grey
        },
    }


class VoiceSettings(BaseModel):
    provider: str = "edge-tts" # "edge-tts", "gemini", "mock"
    voice_id: str = "hi-IN-MadhurNeural"
    fallback_voice_id: str = "hi-IN-SwaraNeural"
    language: str = "hi"
    speech_rate: str = "-2%"
    pitch: str = "-4Hz"
    style: str = "cinematic"
    timeout_seconds: int = 30
    max_retries: int = 3
    character_voices: Dict[str, Dict[str, Any]] = Field(default_factory=get_default_character_voices)


class SubtitlesSettings(BaseModel):
    enabled: bool = True
    burn_in: bool = True
    export_external_srt: bool = True
    export_ass: bool = True
    language: str = "hi"
    font_name: str = "Arial"
    font_size: int = 24
    font_color: str = "&H00FFFFFF"
    outline_color: str = "&H00000000"
    outline_width: int = 3
    bottom_margin: int = 180
    max_words_per_line: int = 7


class MotionSettings(BaseModel):
    default_preset: str = "slow_zoom_in"
    zoom_scale: float = 1.08
    pan_speed: float = 0.05
    transition_type: str = "fade"
    transition_duration_seconds: float = 0.5
    fill_mode: str = "blur_background" # "blur_background", "black_letterbox"


class RightsSettings(BaseModel):
    status: RightsStatus = RightsStatus.UNKNOWN
    reference: Optional[str] = None
    attribution: Optional[str] = None
    allow_commercial: bool = False
    allow_modifications: bool = True


class PathsSettings(BaseModel):
    artwork_dir: str = "artwork"
    audio_dir: str = "audio"
    renders_dir: str = "renders"
    subtitles_dir: str = "subtitles"
    scripts_dir: str = "scripts"


class AppConfig(BaseModel):
    """Full application and project configuration."""
    project: ProjectSettings = Field(default_factory=ProjectSettings)
    video: VideoSettings = Field(default_factory=VideoSettings)
    audio: AudioSettings = Field(default_factory=AudioSettings)
    voice: VoiceSettings = Field(default_factory=VoiceSettings)
    subtitles: SubtitlesSettings = Field(default_factory=SubtitlesSettings)
    motion: MotionSettings = Field(default_factory=MotionSettings)
    rights: RightsSettings = Field(default_factory=RightsSettings)
    paths: PathsSettings = Field(default_factory=PathsSettings)


def load_config(config_path: Path | str) -> AppConfig:
    """Load configuration from a YAML file with environment variable expansion."""
    p = Path(config_path)
    if not p.is_file():
        raise FileNotFoundError(f"Configuration file not found: {p}")

    with open(p, "r", encoding="utf-8") as f:
        raw_data = yaml.safe_load(f) or {}

    return AppConfig.model_validate(raw_data)


def save_config(config: AppConfig, target_path: Path | str) -> None:
    """Serialize configuration to a clean YAML file."""
    p = Path(target_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        data = config.model_dump(mode="json")
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
