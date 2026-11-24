"""
Unit tests for schema validation, normalized crops, and scene manifests.
"""

import pytest
from manhwa_studio.schemas import (
    MotionPreset,
    NormalizedCrop,
    SceneItem,
    SceneManifest,
    TransitionType,
)
from manhwa_studio.story.script_validator import ScriptValidator


def test_normalized_crop_validation():
    # Valid crop
    crop = NormalizedCrop(x=0.1, y=0.1, width=0.8, height=0.8)
    assert crop.width == 0.8

    # Invalid crop extending past boundary
    with pytest.raises(ValueError):
        NormalizedCrop(x=0.5, y=0.2, width=0.6, height=0.5)


def test_scene_manifest_and_validator():
    manifest = SceneManifest(
        series="Test Series",
        chapter=1,
        title="Test Ch",
        target_duration=10.0,
        approved_by_user=False,
        scenes=[
            SceneItem(
                scene_id="s1",
                duration=5.0,
                image_file="panel_1.jpg",
                narration_text="पहला दृश्य।",
            ),
            SceneItem(
                scene_id="s2",
                duration=5.0,
                image_file="panel_2.jpg",
                narration_text="दूसरा दृश्य।",
            ),
        ],
    )

    assert manifest.total_duration == 10.0

    validator = ScriptValidator(tolerance_seconds=1.0)
    # Fails because approved_by_user is False
    ok, errors, warnings = validator.validate_manifest(manifest)
    assert not ok
    assert any("approved_by_user" in e for e in errors)

    # Approve and re-validate
    manifest.approved_by_user = True
    ok, errors, warnings = validator.validate_manifest(manifest)
    assert ok
    assert len(errors) == 0
