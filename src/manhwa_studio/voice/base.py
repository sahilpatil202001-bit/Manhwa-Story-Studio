"""
Base class definition for Text-to-Speech providers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class BaseTTSProvider(ABC):
    """Abstract interface for TTS engines."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the provider."""
        pass

    @abstractmethod
    def synthesize(
        self,
        text: str,
        output_path: Path,
        voice_id: str = "hi-IN-MadhurNeural",
        speech_rate: str = "+0%",
        pitch: str = "-5Hz",
        timeout_seconds: int = 30,
    ) -> float:
        """
        Synthesize text into an audio file.
        Returns:
            float: Actual measured duration of the generated audio in seconds.
        """
        pass
