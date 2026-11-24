"""
Validation rules and QA checks for story scripts and scene manifests.
"""

from __future__ import annotations

from typing import List, Tuple

from manhwa_studio.logging_config import get_logger
from manhwa_studio.schemas import SceneManifest

logger = get_logger("manhwa_studio.story.validator")


class ScriptValidator:
    """Enforces narrative coherence, timing bounds, and approval gating."""

    def __init__(self, tolerance_seconds: float = 5.0):
        self.tolerance_seconds = tolerance_seconds

    def validate_manifest(self, manifest: SceneManifest) -> Tuple[bool, List[str], List[str]]:
        """
        Validate scene manifest.
        Returns: (is_valid, errors, warnings)
        """
        errors: List[str] = []
        warnings: List[str] = []

        if not manifest.scenes:
            errors.append("Scene manifest contains no scenes.")
            return False, errors, warnings

        # 1. User approval gate
        if not manifest.approved_by_user:
            errors.append(
                "Scene manifest has NOT been approved by the user (approved_by_user is False). "
                "Review the script and set approved_by_user to True before generating voice audio."
            )

        # 2. Timing validation
        total_time = manifest.total_duration
        target = manifest.target_duration
        diff = abs(total_time - target)
        if diff > self.tolerance_seconds:
            warnings.append(
                f"Total scene duration ({total_time:.1f}s) deviates from target ({target:.1f}s) by {diff:.1f}s."
            )

        # 3. Individual scene checks
        seen_texts = set()
        for idx, scene in enumerate(manifest.scenes):
            scene_ref = scene.scene_id or f"Index {idx+1}"

            if not scene.image_file:
                errors.append(f"Scene '{scene_ref}' has no image file assigned.")

            if scene.duration <= 0.5:
                errors.append(f"Scene '{scene_ref}' duration is too short ({scene.duration}s). Minimum is 0.5s.")
            elif scene.duration > 60.0:
                warnings.append(f"Scene '{scene_ref}' duration is unusually long ({scene.duration}s).")

            if not scene.narration_text.strip():
                warnings.append(f"Scene '{scene_ref}' has empty narration text.")
            else:
                norm_text = scene.narration_text.strip().lower()
                if norm_text in seen_texts:
                    warnings.append(f"Scene '{scene_ref}' has repeated narration text.")
                seen_texts.add(norm_text)

            # Crop boundary validation
            if scene.crop:
                if scene.crop.x + scene.crop.width > 1.0001 or scene.crop.y + scene.crop.height > 1.0001:
                    errors.append(f"Scene '{scene_ref}' has crop extending beyond 1.0.")

        is_valid = len(errors) == 0
        return is_valid, errors, warnings
