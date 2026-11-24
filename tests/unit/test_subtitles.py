"""
Unit tests for subtitle generation, chunking, and validation.
"""

from pathlib import Path
import pytest
from manhwa_studio.config import SubtitlesSettings
from manhwa_studio.schemas import SceneItem, SceneManifest
from manhwa_studio.subtitles.generate import build_subtitle_segments, generate_ass, generate_srt
from manhwa_studio.subtitles.validate import SubtitleValidator


def test_subtitle_generation_and_validation(tmp_path: Path):
    manifest = SceneManifest(
        series="Test",
        chapter=1,
        title="Test",
        target_duration=6.0,
        approved_by_user=True,
        scenes=[
            SceneItem(
                scene_id="s1",
                duration=3.0,
                image_file="img1.jpg",
                subtitle_text="यह एक रहस्यमयी कहानी की शुरुआत है।",
            ),
            SceneItem(
                scene_id="s2",
                duration=3.0,
                image_file="img2.jpg",
                subtitle_text="और आगे क्या हुआ जानने के लिए तैयार रहें।",
            ),
        ],
    )

    segments = build_subtitle_segments(manifest, max_words_per_line=5)
    assert len(segments) >= 2

    # Check non-overlapping order
    for i in range(len(segments) - 1):
        assert segments[i][0] < segments[i][1]
        assert segments[i][1] <= segments[i + 1][0] + 0.05

    # Export SRT
    srt_file = tmp_path / "subs.srt"
    generate_srt(segments, srt_file)
    assert srt_file.exists()

    # Validate SRT
    ok, errors, warnings = SubtitleValidator.validate_srt_file(srt_file)
    assert ok
    assert len(errors) == 0

    # Export ASS
    ass_file = tmp_path / "subs.ass"
    generate_ass(segments, ass_file, SubtitlesSettings())
    assert ass_file.exists()
    assert "PlayResY: 1920" in ass_file.read_text(encoding="utf-8")
