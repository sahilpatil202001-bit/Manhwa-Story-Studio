"""
Subtitle validation rules, timestamp consistency, and readability checks.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Tuple

from manhwa_studio.logging_config import get_logger
from manhwa_studio.utils.timecodes import srt_timecode_to_seconds

logger = get_logger("manhwa_studio.subtitles.validate")


class SubtitleValidator:
    """Validates subtitle timing, order, and format compliance."""

    @staticmethod
    def validate_srt_file(srt_path: Path) -> Tuple[bool, List[str], List[str]]:
        """
        Parse and validate an SRT file.
        Returns: (is_valid, errors, warnings)
        """
        errors: List[str] = []
        warnings: List[str] = []

        if not srt_path.exists():
            errors.append(f"Subtitle file not found at: {srt_path}")
            return False, errors, warnings

        content = srt_path.read_text(encoding="utf-8").strip()
        if not content:
            errors.append("Subtitle file is empty.")
            return False, errors, warnings

        blocks = re.split(r"\n\s*\n", content)
        prev_end = 0.0

        for block_idx, block in enumerate(blocks, 1):
            lines = [line.strip() for line in block.strip().split("\n") if line.strip()]
            if len(lines) < 2:
                errors.append(f"Cue #{block_idx} is malformed: insufficient lines.")
                continue

            # First line is index or timestamp
            time_line = lines[1] if lines[0].isdigit() else lines[0]
            if "-->" not in time_line:
                errors.append(f"Cue #{block_idx} missing timing separator '-->': '{time_line}'")
                continue

            parts = time_line.split("-->")
            try:
                start_sec = srt_timecode_to_seconds(parts[0].strip())
                end_sec = srt_timecode_to_seconds(parts[1].strip())
            except Exception as e:
                errors.append(f"Cue #{block_idx} invalid timecode syntax: {e}")
                continue

            if start_sec < 0 or end_sec < 0:
                errors.append(f"Cue #{block_idx} has negative timestamp: {start_sec}s -> {end_sec}s")

            if start_sec >= end_sec:
                errors.append(f"Cue #{block_idx} start time ({start_sec}s) >= end time ({end_sec}s)")

            if start_sec < prev_end - 0.01:
                errors.append(
                    f"Cue #{block_idx} overlaps with previous cue: starts at {start_sec:.2f}s before prev ended at {prev_end:.2f}s"
                )

            duration = end_sec - start_sec
            if duration < 0.3:
                warnings.append(f"Cue #{block_idx} duration ({duration:.2f}s) is very short.")

            text_lines = lines[2:] if lines[0].isdigit() else lines[1:]
            text = " ".join(text_lines).strip()
            if not text:
                warnings.append(f"Cue #{block_idx} has empty text.")

            # Check reading speed
            chars = len(text)
            cps = chars / max(0.1, duration)
            if cps > 35: # Exceeds rapid reading threshold
                warnings.append(f"Cue #{block_idx} has high reading speed ({cps:.1f} chars/sec): '{text}'")

            prev_end = end_sec

        return len(errors) == 0, errors, warnings
