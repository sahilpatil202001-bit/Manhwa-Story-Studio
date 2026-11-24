"""
Rights and authorization verification for artwork and media assets.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

from manhwa_studio.logging_config import get_logger
from manhwa_studio.schemas import AssetMetadata, RightsStatus
from manhwa_studio.utils.hashing import compute_file_sha256

logger = get_logger("manhwa_studio.rights")


class RightsManager:
    """Manages explicit copyright and authorization verification for production assets."""

    def __init__(self, rights_manifest_path: Path):
        self.rights_manifest_path = rights_manifest_path
        self.assets: Dict[str, AssetMetadata] = {}
        self.load()

    def load(self) -> None:
        """Load registered asset rights from JSON manifest."""
        if not self.rights_manifest_path.exists():
            self.assets = {}
            return

        with open(self.rights_manifest_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
            self.assets = {k: AssetMetadata.model_validate(v) for k, v in raw.items()}

    def save(self) -> None:
        """Save registered assets to JSON manifest."""
        self.rights_manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.rights_manifest_path, "w", encoding="utf-8") as f:
            serializable = {k: v.model_dump(mode="json") for k, v in self.assets.items()}
            json.dump(serializable, f, indent=2)

    def register_asset(self, metadata: AssetMetadata) -> None:
        """Register or update asset metadata."""
        self.assets[metadata.asset_id] = metadata
        self.save()

    def verify_asset(self, asset_id: str, file_path: Path) -> Tuple[bool, str]:
        """
        Verify whether an asset exists, matches its registered hash, and has authorized rights status.
        """
        if not file_path.exists():
            return False, f"Asset file not found at: {file_path}"

        current_hash = compute_file_sha256(file_path)

        metadata = self.assets.get(asset_id)
        if not metadata:
            return False, f"Asset '{asset_id}' is not registered in rights manifest. Rights declaration required."

        if metadata.sha256 != current_hash:
            return False, f"Asset '{asset_id}' SHA-256 hash mismatch. File may have been altered or corrupted."

        if not metadata.rights_status.is_authorized:
            return False, (
                f"Asset '{asset_id}' has unauthorized status: '{metadata.rights_status.value}'. "
                "Only owned, licensed, permission_granted, or public_domain_verified assets are permitted."
            )

        return True, "Authorized"

    def validate_production_readiness(self, image_paths: List[Path]) -> Tuple[bool, List[str]]:
        """
        Validate a list of images before proceeding with production rendering.
        Rejects unknown and prohibited assets.
        """
        errors: List[str] = []
        for img_path in image_paths:
            asset_id = img_path.name
            ok, msg = self.verify_asset(asset_id, img_path)
            if not ok:
                errors.append(f"[{img_path.name}] {msg}")

        return len(errors) == 0, errors
