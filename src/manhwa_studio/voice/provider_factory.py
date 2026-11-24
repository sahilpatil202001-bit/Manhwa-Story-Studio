"""
TTS provider factory and provider implementations: Mock, Edge-TTS, and Local.
"""

from __future__ import annotations

import asyncio
import math
import struct
import wave
from pathlib import Path
from typing import Optional

from manhwa_studio.logging_config import get_logger
from manhwa_studio.voice.base import BaseTTSProvider

logger = get_logger("manhwa_studio.voice.factory")


class MockTTSProvider(BaseTTSProvider):
    """
    Mock TTS provider generating clean synthetic audio tones for tests and offline workflows.
    Zero external dependencies or paid API keys required.
    """

    @property
    def name(self) -> str:
        return "mock"

    def synthesize(
        self,
        text: str,
        output_path: Path,
        voice_id: str = "mock-hindi-voice",
        speech_rate: str = "+0%",
        pitch: str = "-5Hz",
        timeout_seconds: int = 30,
    ) -> float:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # Ensure .wav extension for raw PCM generation
        wav_path = output_path.with_suffix(".wav")

        words = text.split()
        # Reasonable speaking rate: ~2.5 words per second (0.4s per word), min 2.0 seconds
        duration = max(2.0, round(len(words) * 0.4, 2))

        sample_rate = 24000
        total_samples = int(sample_rate * duration)
        frequency = 220.0 # Warm, deep tone

        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(1) # mono
            wf.setsampwidth(2) # 16-bit
            wf.setframerate(sample_rate)

            # Generate gentle sine wave tone with attack/decay
            frames = bytearray()
            for i in range(total_samples):
                # Envelope
                env = 1.0
                if i < 2400: # Fade in 0.1s
                    env = i / 2400.0
                elif i > total_samples - 2400: # Fade out 0.1s
                    env = (total_samples - i) / 2400.0

                sample = int(3000.0 * env * math.sin(2.0 * math.pi * frequency * (i / sample_rate)))
                frames.extend(struct.pack("<h", sample))

            wf.writeframes(frames)

        logger.info(f"Mock TTS generated {duration}s audio for {len(words)} words at: {wav_path}")
        return duration


class EdgeTTSProvider(BaseTTSProvider):
    """
    Microsoft Edge Neural TTS provider. Free, no API key needed, high-quality natural Hindi.
    """

    @property
    def name(self) -> str:
        return "edge-tts"

    def synthesize(
        self,
        text: str,
        output_path: Path,
        voice_id: str = "hi-IN-MadhurNeural",
        speech_rate: str = "+0%",
        pitch: str = "-5Hz",
        timeout_seconds: int = 30,
    ) -> float:
        import asyncio
        import subprocess
        import time
        import edge_tts

        output_path.parent.mkdir(parents=True, exist_ok=True)
        mp3_path = output_path.with_suffix(".mp3")

        text_clean = (text or "").strip()
        # If text has no alphanumeric characters (e.g. only punctuation like "...", "—"), generate brief silence
        if not any(c.isalnum() for c in text_clean):
            logger.warning(f"EdgeTTS text has no alphanumeric characters: '{text}'. Generating silence fallback.")
            try:
                subprocess.run(
                    ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=24000", "-t", "1.5", "-c:a", "libmp3lame", str(mp3_path)],
                    capture_output=True,
                    check=True,
                )
                return 1.5
            except Exception as exc:
                logger.error(f"FFmpeg silence creation failed: {exc}")
                return 1.5

        async def _run(rate: str, ptch: str) -> None:
            communicate = edge_tts.Communicate(
                text=text_clean,
                voice=voice_id,
                rate=rate,
                pitch=ptch,
            )
            await asyncio.wait_for(communicate.save(str(mp3_path)), timeout=timeout_seconds)

        # Retry logic with rate/pitch fallback if needed
        success = False
        attempts = [
            (speech_rate, pitch),
            ("+0%", "+0Hz"),
        ]
        last_error = None
        for attempt_idx, (r, p) in enumerate(attempts, 1):
            try:
                asyncio.run(_run(r, p))
                success = True
                break
            except Exception as exc:
                last_error = exc
                logger.warning(f"EdgeTTS attempt {attempt_idx} failed: {exc}. Retrying...")
                time.sleep(1.0)

        if not success:
            logger.error(f"EdgeTTS synthesis failed for voice '{voice_id}': {last_error}. Generating fallback audio.")
            try:
                fallback_dur = max(2.0, round(len(text_clean.split()) * 0.4, 2))
                subprocess.run(
                    ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=24000", "-t", str(fallback_dur), "-c:a", "libmp3lame", str(mp3_path)],
                    capture_output=True,
                    check=True,
                )
                return fallback_dur
            except Exception as exc:
                logger.error(f"Failed to generate fallback silence: {exc}")
                raise last_error

        # Measure duration with ffprobe or estimate
        from manhwa_studio.quality.media_probe import probe_media
        try:
            probe = probe_media(mp3_path)
            duration = probe.duration_seconds
        except Exception:
            words = text_clean.split()
            duration = max(2.0, round(len(words) * 0.4, 2))

        logger.info(f"EdgeTTS generated {duration:.2f}s audio at: {mp3_path}")
        return duration


class ElevenLabsTTSProvider(BaseTTSProvider):
    """
    ElevenLabs Voice AI Provider. Produces hyper-realistic, human-quality voice acting
    with breath sounds, emotional nuance, and cinematic pacing.
    """

    @property
    def name(self) -> str:
        return "elevenlabs"

    def synthesize(
        self,
        text: str,
        output_path: Path,
        voice_id: str = "pNInz6obpgDQGcFmaJgB",
        speech_rate: str = "+0%",
        pitch: str = "+0Hz",
        timeout_seconds: int = 45,
    ) -> float:
        import json
        import os
        import urllib.request

        api_key = os.environ.get("ELEVENLABS_API_KEY")
        if not api_key:
            raise ValueError("ELEVENLABS_API_KEY environment variable is not set. Add it to .env")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        mp3_path = output_path.with_suffix(".mp3")

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": api_key,
        }
        data = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 0.45,
                "similarity_boost": 0.85,
                "style": 0.25,
                "use_speaker_boost": True,
            },
        }
        req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
            with open(mp3_path, "wb") as f:
                f.write(response.read())

        from manhwa_studio.quality.media_probe import probe_media
        probe = probe_media(mp3_path)
        logger.info(f"ElevenLabs generated {probe.duration_seconds:.2f}s realistic audio at: {mp3_path}")
        return probe.duration_seconds


class OpenAITTSProvider(BaseTTSProvider):
    """
    OpenAI TTS Provider (tts-1-hd) producing warm, natural studio voice narration.
    """

    @property
    def name(self) -> str:
        return "openai"

    def synthesize(
        self,
        text: str,
        output_path: Path,
        voice_id: str = "onyx",
        speech_rate: str = "+0%",
        pitch: str = "+0Hz",
        timeout_seconds: int = 45,
    ) -> float:
        import json
        import os
        import urllib.request

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is not set. Add it to .env")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        mp3_path = output_path.with_suffix(".mp3")

        url = "https://api.openai.com/v1/audio/speech"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        data = {
            "model": "tts-1-hd",
            "input": text,
            "voice": voice_id if voice_id in ("alloy", "echo", "fable", "onyx", "nova", "shimmer") else "onyx",
            "response_format": "mp3",
        }
        req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
            with open(mp3_path, "wb") as f:
                f.write(response.read())

        from manhwa_studio.quality.media_probe import probe_media
        probe = probe_media(mp3_path)
        logger.info(f"OpenAI TTS generated {probe.duration_seconds:.2f}s audio at: {mp3_path}")
        return probe.duration_seconds


class GeminiTTSProvider(BaseTTSProvider):
    """
    Google Gemini Neural Voice Provider (`gemini-3.8-flash-tts`).
    Produces studio-quality human voice storytelling (e.g. Fenrir, Puck, Kore, Charon).
    """

    @property
    def name(self) -> str:
        return "gemini"

    def synthesize(
        self,
        text: str,
        output_path: Path,
        voice_id: str = "Fenrir",
        speech_rate: str = "+0%",
        pitch: str = "+0Hz",
        timeout_seconds: int = 45,
    ) -> float:
        import base64
        import json
        import os
        import subprocess
        import time
        import urllib.error
        import urllib.request

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            env_file = Path(".env")
            if env_file.exists():
                for line in env_file.read_text(encoding="utf-8").splitlines():
                    if line.startswith("GEMINI_API_KEY="):
                        api_key = line.split("=", 1)[1].strip("\"' ")
                        break

        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is not set. Add it to .env")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        target_path = output_path.with_suffix(".mp3")
        temp_wav = output_path.with_suffix(".gemini.wav")

        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent"
        clean_text = (text or "").strip()
        if not clean_text:
            clean_text = "..."

        first_key = [k.strip("\"' ") for k in api_key.split(",") if k.strip()][0]

        payload = {
            "contents": [{
                "role": "user",
                "parts": [{"text": clean_text}]
            }],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "languageCode": "hi-IN",
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {
                            "voiceName": voice_id if voice_id in ("Fenrir", "Puck", "Kore", "Charon", "Aoede", "Zephyr") else "Puck"
                        }
                    }
                }
            }
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": first_key},
        )

        # Retry loop handling potential 429 rate limits
        last_error = None
        for attempt in range(1, 4):
            try:
                with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                    resp_data = json.loads(resp.read().decode("utf-8"))
                    cand = resp_data["candidates"][0]["content"]["parts"][0]
                    audio_b64 = cand.get("inlineData", {}).get("data")
                    if not audio_b64:
                        raise RuntimeError("Gemini returned empty audio data")

                    raw_wav = base64.b64decode(audio_b64)
                    if raw_wav[:4] == b"RIFF":
                        temp_wav.write_bytes(raw_wav)
                    else:
                        import wave
                        with wave.open(str(temp_wav), "wb") as wf:
                            wf.setnchannels(1)
                            wf.setsampwidth(2)
                            wf.setframerate(24000)
                            wf.writeframes(raw_wav)
                    break
            except urllib.error.HTTPError as he:
                last_error = he
                logger.warning(f"Gemini TTS HTTP error (attempt {attempt}/3): {he.code} - {he.reason}")
                time.sleep(2.0 * attempt)
            except Exception as exc:
                last_error = exc
                logger.warning(f"Gemini TTS request error (attempt {attempt}/3): {exc}")
                time.sleep(2.0 * attempt)
        else:
            raise RuntimeError(f"Gemini TTS failed after 3 attempts: {last_error}")

        # Convert WAV to MP3 using ffmpeg
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(temp_wav), "-c:a", "libmp3lame", "-b:a", "192k", str(target_path)],
                capture_output=True,
                check=True,
            )
            if temp_wav.exists():
                try:
                    temp_wav.unlink()
                except Exception:
                    pass
        except Exception as exc:
            logger.error(f"FFmpeg conversion of Gemini WAV to MP3 failed: {exc}")
            raise

        from manhwa_studio.quality.media_probe import probe_media
        probe = probe_media(target_path)
        logger.info(f"Gemini TTS ({voice_id}) generated {probe.duration_seconds:.2f}s audio at: {target_path}")
        return probe.duration_seconds


def get_tts_provider(provider_name: str) -> BaseTTSProvider:
    """Factory resolver for configured TTS provider."""
    normalized = provider_name.strip().lower()
    if normalized == "mock":
        return MockTTSProvider()
    elif normalized in ("gemini", "gemini-tts", "gemini_tts", "google"):
        return GeminiTTSProvider()
    elif normalized in ("edge-tts", "edgetts"):
        return EdgeTTSProvider()
    elif normalized in ("elevenlabs", "eleven-labs", "11labs"):
        return ElevenLabsTTSProvider()
    elif normalized in ("openai", "openai-tts"):
        return OpenAITTSProvider()
    else:
        logger.warning(f"Unknown provider '{provider_name}', falling back to GeminiTTSProvider.")
        return GeminiTTSProvider()
