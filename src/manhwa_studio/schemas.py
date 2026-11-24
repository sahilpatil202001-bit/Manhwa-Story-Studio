"""
Pydantic schemas and data models for Manhwa Story Studio.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class RightsStatus(str, Enum):
    OWNED = "owned"
    LICENSED = "licensed"
    PERMISSION_GRANTED = "permission_granted"
    PUBLIC_DOMAIN_VERIFIED = "public_domain_verified"
    OTHER_AUTHORIZED_USE = "other_authorized_use"
    UNKNOWN = "unknown"
    PROHIBITED = "prohibited"

    @property
    def is_authorized(self) -> bool:
        """Return True if this status allows production use."""
        return self in {
            RightsStatus.OWNED,
            RightsStatus.LICENSED,
            RightsStatus.PERMISSION_GRANTED,
            RightsStatus.PUBLIC_DOMAIN_VERIFIED,
            RightsStatus.OTHER_AUTHORIZED_USE,
        }


class AssetMetadata(BaseModel):
    """Metadata describing a source artwork image or audio asset."""
    asset_id: str
    file_path: str
    sha256: str
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    format: str
    source_description: str = ""
    rights_status: RightsStatus = RightsStatus.UNKNOWN
    license_reference: Optional[str] = None
    attribution: Optional[str] = None
    allow_commercial: bool = False
    allow_modifications: bool = True
    aspect_ratio: float = 0.0

    @model_validator(mode="after")
    def compute_aspect(self) -> "AssetMetadata":
        if self.height > 0:
            self.aspect_ratio = round(self.width / self.height, 4)
        return self


class NormalizedCrop(BaseModel):
    """Normalized crop coordinates within range [0.0, 1.0]."""
    x: float = Field(0.0, ge=0.0, le=1.0)
    y: float = Field(0.0, ge=0.0, le=1.0)
    width: float = Field(1.0, gt=0.0, le=1.0)
    height: float = Field(1.0, gt=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_bounds(self) -> "NormalizedCrop":
        if self.x + self.width > 1.0001:
            raise ValueError(f"Crop width extends beyond image boundary (x={self.x}, w={self.width})")
        if self.y + self.height > 1.0001:
            raise ValueError(f"Crop height extends beyond image boundary (y={self.y}, h={self.height})")
        return self


class MotionPreset(str, Enum):
    STATIC = "static"
    SLOW_ZOOM_IN = "slow_zoom_in"
    SLOW_ZOOM_OUT = "slow_zoom_out"
    PAN_UP = "pan_up"
    PAN_DOWN = "pan_down"
    PAN_LEFT = "pan_left"
    PAN_RIGHT = "pan_right"


class TransitionType(str, Enum):
    NONE = "none"
    FADE = "fade"
    CROSSFADE = "crossfade"


class VoiceProfile(BaseModel):
    """Voice configuration profile for a specific character or narrator."""
    voice_id: str = "hi-IN-MadhurNeural"
    speech_rate: str = "+0%"
    pitch: str = "+0Hz"
    style: str = "cinematic"
    color_hex: str = "&H00FFFFFF" # Subtitle color in ASS hex format


class SceneItem(BaseModel):
    """A distinct scene segment in the video timeline."""
    scene_id: str
    scene_purpose: str = "narrative" # hook, conflict, turning_point, cliffhanger, conclusion
    duration: float = Field(..., gt=0.0, description="Duration of this scene in seconds")
    image_file: str
    crop: Optional[NormalizedCrop] = None
    motion_preset: MotionPreset = MotionPreset.SLOW_ZOOM_IN
    transition: TransitionType = TransitionType.FADE
    transition_duration: float = Field(0.5, ge=0.0, le=2.0)
    speaker: str = "Narrator" # Narrator, Protagonist, Villain, Female, Elder, etc.
    speaker_gender: Optional[str] = None # "male", "female", or "narrator" (detected from character face & dialogue)
    narration_text: str = ""
    subtitle_text: str = ""
    audio_cues: List[str] = Field(default_factory=list)
    supporting_panel_ids: List[str] = Field(default_factory=list)
    verification_notes: str = ""
    actual_audio_path: Optional[str] = None
    actual_audio_duration: Optional[float] = None


class SceneManifest(BaseModel):
    """Structured scene timeline and narrative script for video production."""
    series: str
    chapter: int
    title: str
    target_duration: float = Field(180.0, gt=0.0)
    scenes: List[SceneItem] = Field(default_factory=list)
    approved_by_user: bool = False
    verification_notes: str = ""

    @property
    def total_duration(self) -> float:
        """Calculate total visual scene duration."""
        return sum(s.duration for s in self.scenes)

    def validate_timing(self, tolerance_seconds: float = 5.0) -> list[str]:
        """Validate scene manifest timing against target duration."""
        warnings: list[str] = []
        total = self.total_duration
        diff = abs(total - self.target_duration)
        if diff > tolerance_seconds:
            warnings.append(
                f"Total scene duration ({total:.1f}s) differs from target ({self.target_duration:.1f}s) by {diff:.1f}s."
            )
        for scene in self.scenes:
            if not scene.image_file:
                warnings.append(f"Scene '{scene.scene_id}' has no image assigned.")
            if scene.duration < 1.0:
                warnings.append(f"Scene '{scene.scene_id}' duration is unusually short ({scene.duration:.1f}s).")
        return warnings


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"
    SKIPPED = "skipped"


class StageRecord(BaseModel):
    status: StageStatus = StageStatus.PENDING
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    input_hash: Optional[str] = None
    config_hash: Optional[str] = None
    output_paths: List[str] = Field(default_factory=list)
    error_message: Optional[str] = None
    tool_versions: Dict[str, str] = Field(default_factory=dict)


class ProjectState(BaseModel):
    """Project lifecycle state tracking to support resumability and caching."""
    series: str
    chapter: int
    created_at: str
    updated_at: str
    stages: Dict[str, StageRecord] = Field(default_factory=dict)


class MediaProbeResult(BaseModel):
    """FFprobe media stream and container diagnostic findings."""
    filepath: str
    format_name: str
    duration_seconds: float
    size_bytes: int
    bitrate_kbps: Optional[float] = None
    has_video: bool = False
    has_audio: bool = False
    width: Optional[int] = None
    height: Optional[int] = None
    aspect_ratio: Optional[str] = None
    fps: Optional[float] = None
    video_codec: Optional[str] = None
    pixel_format: Optional[str] = None
    audio_codec: Optional[str] = None
    audio_sample_rate: Optional[int] = None
    audio_channels: Optional[int] = None


class ValidationReport(BaseModel):
    """Quality assurance and compliance report."""
    is_valid: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    media_probe: Optional[MediaProbeResult] = None
