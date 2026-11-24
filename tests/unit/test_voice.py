"""
Unit tests for TTS synthesis and caching mechanisms.
"""

from pathlib import Path
import pytest
from manhwa_studio.config import VoiceSettings
from manhwa_studio.schemas import SceneItem, SceneManifest
from manhwa_studio.voice.provider_factory import MockTTSProvider
from manhwa_studio.voice.synthesis import VoiceSynthesisCoordinator


def test_mock_tts_provider(tmp_path: Path):
    provider = MockTTSProvider()
    out_wav = tmp_path / "test.wav"
    duration = provider.synthesize("यह एक परीक्षण वाक्य है।", out_wav)

    assert out_wav.exists()
    assert duration >= 2.0
    assert out_wav.stat().st_size > 1000 # Contains real audio PCM frames


def test_voice_coordinator_caching(tmp_path: Path):
    audio_dir = tmp_path / "audio"
    settings = VoiceSettings(provider="mock")
    coord = VoiceSynthesisCoordinator(audio_dir, settings)

    manifest = SceneManifest(
        series="Test",
        chapter=1,
        title="Test",
        target_duration=4.0,
        approved_by_user=True,
        scenes=[
            SceneItem(scene_id="s1", duration=2.0, image_file="img.jpg", narration_text="पहला टेस्ट"),
        ],
    )

    # First synthesis
    updated = coord.synthesize_manifest_narration(manifest)
    first_path = updated.scenes[0].actual_audio_path
    assert first_path is not None
    assert Path(first_path).exists()

    # Second synthesis should hit cache
    cached_updated = coord.synthesize_manifest_narration(manifest)
    assert cached_updated.scenes[0].actual_audio_path == first_path
