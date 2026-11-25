"""
Centralized Environment Configuration Manager for Manhwa Story Studio Pro.
Reads and writes dynamic studio settings from `.env` and `os.environ` so zero
operational parameters need to be hardcoded in source files.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


def load_dotenv_into_environ(env_path: Optional[Path] = None, override: bool = False) -> Dict[str, str]:
    """Load key=value pairs from `.env` into `os.environ` without external dependencies."""
    p = env_path or Path(".env")
    loaded: Dict[str, str] = {}
    if not p.exists():
        return loaded

    try:
        for raw_line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            key = k.strip()
            val = v.strip()
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            loaded[key] = val
            if override or key not in os.environ:
                os.environ[key] = val
    except Exception:
        pass
    return loaded


def _env_str(key: str, default: str) -> str:
    val = os.environ.get(key)
    if val is None or val.strip() == "":
        return default
    return val.strip()


def _env_int(key: str, default: int) -> int:
    val = os.environ.get(key)
    if val is None or val.strip() == "":
        return default
    try:
        return int(float(val.strip()))
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    val = os.environ.get(key)
    if val is None or val.strip() == "":
        return default
    try:
        return float(val.strip())
    except ValueError:
        return default


def _env_bool(key: str, default: bool) -> bool:
    val = os.environ.get(key)
    if val is None or val.strip() == "":
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _env_list(key: str, default: List[str]) -> List[str]:
    val = os.environ.get(key)
    if val is None or val.strip() == "":
        return list(default)
    items = [x.strip() for x in val.split(",") if x.strip()]
    return items if items else list(default)


class StudioEnvConfig(BaseModel):
    """Dynamic runtime settings resolved from `.env` and environment variables."""

    # 1. General & Default Series
    default_series: str = Field(default="Nano Machine")
    dashboard_host: str = Field(default="127.0.0.1")
    dashboard_port: int = Field(default=8765)

    # 2. AI / LLM Screenplay Settings
    llm_provider: str = Field(default="gemini")
    gemini_models: List[str] = Field(
        default_factory=lambda: [
            "gemini-3.5-flash-lite",
            "gemini-3-flash-preview",
            "gemini-3.8-flash",
            "gemini-flash-latest",
        ]
    )
    openai_models: List[str] = Field(default_factory=lambda: ["gpt-6-luna", "gpt-6.1-terra", "gpt-4o-mini"])
    groq_models: List[str] = Field(
        default_factory=lambda: [
            "qwen/qwen3.8-27b",
            "meta-models/muse-spark-open",
        ]
    )
    openrouter_models: List[str] = Field(
        default_factory=lambda: [
            "google/gemini-2.5-flash",
            "qwen/qwen2.5-vl-72b-instruct",
            "google/gemini-2.5-flash-lite",
            "meta-llama/llama-4-scout",
        ]
    )
    ollama_fallback: bool = Field(default=False)
    ollama_host: str = Field(default="http://127.0.0.1:11434")
    ollama_model: str = Field(default="qwen2.5vl:7b")
    ollama_num_ctx: int = Field(default=16384)
    llm_batch_size: int = Field(default=8)
    vision_thumb_size: int = Field(default=512)
    batch_delay_sec: float = Field(default=2.0)
    rate_limit_cooldown_sec: float = Field(default=45.0)
    max_batch_attempts: int = Field(default=4)

    # 3. Video Rendering & GPU Settings
    pro_width: int = Field(default=1920)
    pro_height: int = Field(default=1080)
    pro_fps: int = Field(default=30)
    video_quality: int = Field(default=19)
    audio_bitrate: str = Field(default="192k")
    default_speed: float = Field(default=1.25)
    disable_gpu: bool = Field(default=False)
    auto_clean_segments: bool = Field(default=False)
    enable_ambient_aura: bool = Field(default=True)
    enable_scene_microfade: bool = Field(default=True)
    panel_layout: str = Field(default="hybrid")  # "hybrid", "wide_zoom", "dual_panel", "classic"

    # 4. Voice Synthesis & Audio Mastering
    default_male_voice: str = Field(default="gemini:Puck")
    default_female_voice: str = Field(default="gemini:Puck")
    min_scene_sec: float = Field(default=2.4)
    scene_buffer_sec: float = Field(default=0.18)
    voice_pad_sec: float = Field(default=0.16)
    target_lufs: float = Field(default=-16.0)
    default_bgm_file: str = Field(default="assets/audio/bgm/suspense_theme.wav")
    enable_sfx: bool = Field(default=False)
    sfx_volume: float = Field(default=0.0)

    # 5. Marathon, Outro & Fonts
    bumper_duration_sec: float = Field(default=0.0)
    outro_video_file: str = Field(default="assets/video/to_be_continued_black.mp4")
    font_latin: str = Field(default="C:\\Windows\\Fonts\\arialbd.ttf")
    font_hindi: str = Field(default="C:\\Windows\\Fonts\\mangal.ttf")

    @classmethod
    def load(cls, env_path: Optional[Path] = None, reload_file: bool = True) -> "StudioEnvConfig":
        if reload_file:
            load_dotenv_into_environ(env_path=env_path, override=True)

        return cls(
            default_series=_env_str("STUDIO_DEFAULT_SERIES", "Nano Machine"),
            dashboard_host=_env_str("STUDIO_DASHBOARD_HOST", "127.0.0.1"),
            dashboard_port=_env_int("STUDIO_DASHBOARD_PORT", 8765),
            llm_provider=_env_str("LLM_PROVIDER", "gemini"),
            gemini_models=_env_list(
                "STUDIO_GEMINI_MODELS",
                [
                    "gemini-3.5-flash-lite",
                    "gemini-3-flash-preview",
                    "gemini-3.8-flash",
                    "gemini-flash-latest",
                ],
            ),
            openai_models=_env_list("STUDIO_OPENAI_MODELS", ["gpt-6-luna", "gpt-6.1-terra", "gpt-4o-mini"]),
            groq_models=_env_list(
                "STUDIO_GROQ_MODELS",
                [
                    "qwen/qwen3.8-27b",
                    "meta-models/muse-spark-open",
                ],
            ),
            openrouter_models=_env_list(
                "STUDIO_OPENROUTER_MODELS",
                [
                    "google/gemini-2.5-flash",
                    "qwen/qwen2.5-vl-72b-instruct",
                    "google/gemini-2.5-flash-lite",
                    "meta-llama/llama-4-scout",
                ],
            ),
            ollama_fallback=_env_bool("OLLAMA_FALLBACK", False),
            ollama_host=_env_str("OLLAMA_HOST", "http://127.0.0.1:11434"),
            ollama_model=_env_str("OLLAMA_MODEL", "qwen2.5vl:7b"),
            ollama_num_ctx=_env_int("OLLAMA_NUM_CTX", 16384),
            llm_batch_size=max(1, _env_int("STUDIO_LLM_BATCH_SIZE", 8)),
            vision_thumb_size=max(128, _env_int("STUDIO_VISION_THUMB_SIZE", 512)),
            batch_delay_sec=max(0.0, _env_float("STUDIO_BATCH_DELAY_SEC", 2.0)),
            rate_limit_cooldown_sec=max(5.0, _env_float("STUDIO_RATE_LIMIT_COOLDOWN_SEC", 45.0)),
            max_batch_attempts=max(1, _env_int("STUDIO_MAX_BATCH_ATTEMPTS", 4)),
            pro_width=max(360, _env_int("STUDIO_PRO_WIDTH", 1920)),
            pro_height=max(360, _env_int("STUDIO_PRO_HEIGHT", 1080)),
            pro_fps=max(15, _env_int("STUDIO_PRO_FPS", 30)),
            video_quality=max(10, min(35, _env_int("STUDIO_VIDEO_QUALITY", 19))),
            audio_bitrate=_env_str("STUDIO_AUDIO_BITRATE", "192k"),
            default_speed=max(0.25, _env_float("STUDIO_DEFAULT_SPEED", 1.25)),
            disable_gpu=_env_bool("STUDIO_DISABLE_GPU", False),
            auto_clean_segments=_env_bool("STUDIO_AUTO_CLEAN_SEGMENTS", False),
            enable_ambient_aura=_env_bool("STUDIO_ENABLE_AMBIENT_AURA", True),
            enable_scene_microfade=_env_bool("STUDIO_ENABLE_SCENE_MICROFADE", True),
            panel_layout=_env_str("STUDIO_PANEL_LAYOUT", "hybrid").lower(),
            default_male_voice=_env_str("STUDIO_DEFAULT_MALE_VOICE", "gemini:Puck"),
            default_female_voice=_env_str("STUDIO_DEFAULT_FEMALE_VOICE", "gemini:Puck"),
            min_scene_sec=max(1.0, _env_float("STUDIO_MIN_SCENE_SEC", 2.4)),
            scene_buffer_sec=max(0.0, _env_float("STUDIO_SCENE_BUFFER_SEC", 0.18)),
            voice_pad_sec=max(0.0, _env_float("STUDIO_VOICE_PAD_SEC", 0.16)),
            target_lufs=_env_float("STUDIO_TARGET_LUFS", -16.0),
            default_bgm_file=_env_str("STUDIO_DEFAULT_BGM", "assets/audio/bgm/suspense_theme.wav"),
            enable_sfx=_env_bool("STUDIO_ENABLE_SFX", False),
            sfx_volume=max(0.0, min(1.5, _env_float("STUDIO_SFX_VOLUME", 0.0))),
            bumper_duration_sec=max(0.0, _env_float("STUDIO_BUMPER_DURATION_SEC", 0.0)),
            outro_video_file=_env_str("STUDIO_OUTRO_VIDEO", "assets/video/to_be_continued_black.mp4"),
            font_latin=_env_str("STUDIO_FONT_LATIN", "C:\\Windows\\Fonts\\arialbd.ttf"),
            font_hindi=_env_str("STUDIO_FONT_HINDI", "C:\\Windows\\Fonts\\mangal.ttf"),
        )

    def to_env_Mapping(self) -> Dict[str, str]:
        """Convert current settings to `.env` key-value strings."""
        return {
            "STUDIO_DEFAULT_SERIES": self.default_series,
            "STUDIO_DASHBOARD_HOST": self.dashboard_host,
            "STUDIO_DASHBOARD_PORT": str(self.dashboard_port),
            "LLM_PROVIDER": self.llm_provider,
            "STUDIO_GEMINI_MODELS": ",".join(self.gemini_models),
            "STUDIO_OPENAI_MODELS": ",".join(self.openai_models),
            "STUDIO_GROQ_MODELS": ",".join(self.groq_models),
            "STUDIO_OPENROUTER_MODELS": ",".join(self.openrouter_models),
            "OLLAMA_FALLBACK": "1" if self.ollama_fallback else "0",
            "OLLAMA_HOST": self.ollama_host,
            "OLLAMA_MODEL": self.ollama_model,
            "OLLAMA_NUM_CTX": str(self.ollama_num_ctx),
            "STUDIO_LLM_BATCH_SIZE": str(self.llm_batch_size),
            "STUDIO_VISION_THUMB_SIZE": str(self.vision_thumb_size),
            "STUDIO_BATCH_DELAY_SEC": str(self.batch_delay_sec),
            "STUDIO_RATE_LIMIT_COOLDOWN_SEC": str(self.rate_limit_cooldown_sec),
            "STUDIO_MAX_BATCH_ATTEMPTS": str(self.max_batch_attempts),
            "STUDIO_PRO_WIDTH": str(self.pro_width),
            "STUDIO_PRO_HEIGHT": str(self.pro_height),
            "STUDIO_PRO_FPS": str(self.pro_fps),
            "STUDIO_VIDEO_QUALITY": str(self.video_quality),
            "STUDIO_AUDIO_BITRATE": self.audio_bitrate,
            "STUDIO_DEFAULT_SPEED": str(self.default_speed),
            "STUDIO_DISABLE_GPU": "1" if self.disable_gpu else "0",
            "STUDIO_AUTO_CLEAN_SEGMENTS": "1" if self.auto_clean_segments else "0",
            "STUDIO_ENABLE_AMBIENT_AURA": "1" if self.enable_ambient_aura else "0",
            "STUDIO_ENABLE_SCENE_MICROFADE": "1" if self.enable_scene_microfade else "0",
            "STUDIO_PANEL_LAYOUT": self.panel_layout,
            "STUDIO_DEFAULT_MALE_VOICE": self.default_male_voice,
            "STUDIO_DEFAULT_FEMALE_VOICE": self.default_female_voice,
            "STUDIO_MIN_SCENE_SEC": str(self.min_scene_sec),
            "STUDIO_SCENE_BUFFER_SEC": str(self.scene_buffer_sec),
            "STUDIO_VOICE_PAD_SEC": str(self.voice_pad_sec),
            "STUDIO_TARGET_LUFS": str(self.target_lufs),
            "STUDIO_DEFAULT_BGM": self.default_bgm_file,
            "STUDIO_ENABLE_SFX": "1" if self.enable_sfx else "0",
            "STUDIO_SFX_VOLUME": str(self.sfx_volume),
            "STUDIO_BUMPER_DURATION_SEC": str(self.bumper_duration_sec),
            "STUDIO_OUTRO_VIDEO": self.outro_video_file,
            "STUDIO_FONT_LATIN": self.font_latin,
            "STUDIO_FONT_HINDI": self.font_hindi,
        }


def get_env_config() -> StudioEnvConfig:
    """Load and return the current dynamic studio environment configuration."""
    return StudioEnvConfig.load()


def get_studio_outro_video_path() -> Path:
    """Return the configured 'To Be Continued' outro video Path."""
    return Path(get_env_config().outro_video_file)


def update_dotenv_values(updates: Dict[str, Any], env_path: Optional[Path] = None) -> StudioEnvConfig:
    """
    Safely update `.env` file preserving existing comments and API keys,
    and refresh `os.environ` in-place.
    """
    p = env_path or Path(".env")
    lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []

    # Map field names or ENV keys to canonical ENV keys
    current = StudioEnvConfig.load(env_path=p)
    current_dict = current.model_dump()

    for k, v in updates.items():
        if k in current_dict:
            if isinstance(current_dict[k], list) and isinstance(v, str):
                current_dict[k] = [x.strip() for x in v.split(",") if x.strip()]
            else:
                current_dict[k] = v

    updated_cfg = StudioEnvConfig(**current_dict)
    env_map = updated_cfg.to_env_Mapping()

    # Also allow direct uppercase ENV keys in updates (excluding masked secrets)
    for k, v in updates.items():
        if k.isupper() and isinstance(v, (str, int, float, bool)):
            s_val = str(v).strip()
            if s_val and not s_val.startswith("***"):
                env_map[k] = s_val

    seen_keys = set()
    new_lines: List[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k_part = stripped.split("=", 1)[0].strip()
            if k_part in env_map:
                new_lines.append(f"{k_part}={env_map[k_part]}")
                seen_keys.add(k_part)
                os.environ[k_part] = env_map[k_part]
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    missing_keys = [k for k in env_map if k not in seen_keys]
    if missing_keys:
        if new_lines and new_lines[-1].strip() != "":
            new_lines.append("")
        new_lines.append("# --- Dynamic Studio Pro Configuration ---")
        for k in missing_keys:
            new_lines.append(f"{k}={env_map[k]}")
            os.environ[k] = env_map[k]

    tmp = p.with_suffix(".env.tmp")
    tmp.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    tmp.replace(p)

    # Reset cached GPU detection if STUDIO_DISABLE_GPU changed
    try:
        import manhwa_studio.rendering.ffmpeg as ff_mod
        ff_mod._GPU_ENCODER = None
    except Exception:
        pass

    return StudioEnvConfig.load(env_path=p)

