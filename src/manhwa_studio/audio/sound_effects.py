"""
Sound effects cue positioning and mixing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional
from pydantic import BaseModel


class AudioCue(BaseModel):
    sfx_id: str
    file_path: str
    timestamp_seconds: float
    volume: float = 0.4
