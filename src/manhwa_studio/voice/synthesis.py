"""
Voice synthesis coordinator with hash-based caching and timeline synchronization.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from manhwa_studio.config import VoiceSettings
from manhwa_studio.logging_config import get_logger
from manhwa_studio.schemas import SceneManifest
from manhwa_studio.utils.hashing import compute_string_sha256
from manhwa_studio.voice.provider_factory import get_tts_provider

logger = get_logger("manhwa_studio.voice.synthesis")


class VoiceSynthesisCoordinator:
    """Coordinates batch speech generation, cache checks, and timeline synchronization."""

    def __init__(self, audio_dir: Path, voice_settings: VoiceSettings):
        self.audio_dir = audio_dir
        self.segments_dir = audio_dir / "segments"
        self.cache_file = audio_dir / "voice_cache.json"
        self.voice_settings = voice_settings
        self.provider = get_tts_provider(voice_settings.provider)
        self.cache: Dict[str, Dict[str, Any]] = self._load_cache()

    def _load_cache(self) -> Dict[str, Any]:
        if self.cache_file.exists():
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Could not load voice cache: {e}")
        return {}

    def _save_cache(self) -> None:
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        with open(self.cache_file, "w", encoding="utf-8") as f:
            json.dump(self.cache, f, indent=2)

    def resolve_voice_for_speaker(self, speaker: str) -> Tuple[str, str, str]:
        """Resolve voice_id, speech_rate, and pitch for a given speaker."""
        spk_lower = (speaker or "narrator").strip().lower()
        char_map = getattr(self.voice_settings, "character_voices", {})

        # Check direct or semantic match
        if spk_lower in char_map:
            cfg = char_map[spk_lower]
            return cfg.get("voice_id", self.voice_settings.voice_id), cfg.get("speech_rate", "-1%"), cfg.get("pitch", "-2Hz")
        elif any(k in spk_lower for k in ["hero", "protagonist", "mok", "gyeongwoon"]):
            cfg = char_map.get("protagonist", {})
            return cfg.get("voice_id", self.voice_settings.voice_id), cfg.get("speech_rate", "-1%"), cfg.get("pitch", "-2Hz")
        elif any(k in spk_lower for k in ["villain", "enemy", "bandit", "antagonist", "guard"]):
            cfg = char_map.get("villain", {})
            return cfg.get("voice_id", self.voice_settings.voice_id), cfg.get("speech_rate", "+2%"), cfg.get("pitch", "+2Hz")
        elif any(k in spk_lower for k in ["female", "woman", "girl", "assassin", "sister"]):
            cfg = char_map.get("female", {})
            return cfg.get("voice_id", getattr(self.voice_settings, "fallback_voice_id", "hi-IN-SwaraNeural")), cfg.get("speech_rate", "-1%"), cfg.get("pitch", "+0Hz")
        elif any(k in spk_lower for k in ["elder", "master", "old", "clan"]):
            cfg = char_map.get("elder", {})
            return cfg.get("voice_id", self.voice_settings.voice_id), cfg.get("speech_rate", "-4%"), cfg.get("pitch", "-6Hz")

        # Fallback to general voice settings
        return self.voice_settings.voice_id, self.voice_settings.speech_rate, self.voice_settings.pitch

    def compute_cache_key(self, text: str, voice_id: str, speech_rate: str, pitch: str) -> str:
        """Calculate a unique cache key based on text and voice settings."""
        payload = f"{text}|{self.voice_settings.provider}|{voice_id}|{speech_rate}|{pitch}"
        return compute_string_sha256(payload)

    def synthesize_manifest_narration(
        self,
        manifest: SceneManifest,
        adjust_scene_durations: bool = True,
    ) -> SceneManifest:
        """
        Synthesize audio for every scene in manifest with multi-character voice resolution and caching.
        """
        self.segments_dir.mkdir(parents=True, exist_ok=True)

        for scene in manifest.scenes:
            text = scene.narration_text.strip()
            if not text:
                continue

            speaker = getattr(scene, "speaker", "Narrator")
            voice_id, rate, pitch = self.resolve_voice_for_speaker(speaker)

            cache_key = self.compute_cache_key(text, voice_id, rate, pitch)
            cached_entry = self.cache.get(cache_key)

            # Check if cached audio exists on disk
            if cached_entry and Path(cached_entry["file_path"]).exists():
                audio_path = Path(cached_entry["file_path"])
                duration = cached_entry["duration"]
                logger.info(f"Using cached audio for [{speaker}] scene '{scene.scene_id}': {audio_path.name} ({duration:.2f}s)")
            else:
                out_name = f"{scene.scene_id}_{cache_key[:8]}"
                target_base = self.segments_dir / out_name
                duration = self.provider.synthesize(
                    text=text,
                    output_path=target_base,
                    voice_id=voice_id,
                    speech_rate=rate,
                    pitch=pitch,
                    timeout_seconds=self.voice_settings.timeout_seconds,
                )
                candidates = list(self.segments_dir.glob(f"{out_name}.*"))
                audio_path = candidates[0] if candidates else target_base

                self.cache[cache_key] = {
                    "file_path": str(audio_path),
                    "duration": duration,
                    "scene_id": scene.scene_id,
                    "speaker": speaker,
                    "voice_id": voice_id,
                }
                self._save_cache()
                logger.info(f"Synthesized voice for [{speaker}] in scene '{scene.scene_id}': {duration:.2f}s")

            scene.actual_audio_path = str(audio_path)
            scene.actual_audio_duration = duration

            # Tight duration synchronization: eliminate long awkward pauses between scenes
            if adjust_scene_durations:
                new_dur = max(2.5, round(duration + 0.3, 1))
                if abs(new_dur - scene.duration) > 0.15:
                    logger.info(
                        f"Synchronized scene '{scene.scene_id}' duration to narration: {new_dur:.1f}s (was {scene.duration:.1f}s)."
                    )
                    scene.duration = new_dur

        return manifest
