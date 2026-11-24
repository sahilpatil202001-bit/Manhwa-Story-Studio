"""
Image discovery, integrity validation, duplicate detection, and dimension analysis.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

from manhwa_studio.logging_config import get_logger
from manhwa_studio.schemas import AssetMetadata, RightsStatus
from manhwa_studio.utils.hashing import compute_file_sha256

logger = get_logger("manhwa_studio.ingestion.inspector")

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def natural_sort_key(path: Path) -> list[Any]:
    """Sort key that handles numbers naturally (e.g. 'page_2' before 'page_10')."""
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r"(\d+)", path.stem)]


class ImageInspectionReport:
    """Aggregated inspection report for a collection of images."""

    def __init__(self) -> None:
        self.images: List[Dict[str, Any]] = []
        self.duplicates: Dict[str, List[str]] = {} # sha256 -> list of filenames
        self.corrupted: List[str] = []
        self.tall_images: List[Dict[str, Any]] = []
        self.transparent_images: List[str] = []
        self.total_scanned: int = 0
        self.valid_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_scanned": self.total_scanned,
            "valid_count": self.valid_count,
            "corrupted_count": len(self.corrupted),
            "corrupted_files": self.corrupted,
            "duplicate_clusters": {k: v for k, v in self.duplicates.items() if len(v) > 1},
            "tall_images_count": len(self.tall_images),
            "tall_images": self.tall_images,
            "transparent_images": self.transparent_images,
            "images": self.images,
        }

    def save_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)


class ImageInspector:
    """Discovers and inspects chapter artwork images."""

    def __init__(self, artwork_dir: Path):
        self.artwork_dir = artwork_dir

    def discover_images(self) -> List[Path]:
        """Find all supported image files in deterministic natural order."""
        if not self.artwork_dir.exists():
            return []

        found = [
            p for p in self.artwork_dir.iterdir()
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
        ]
        return sorted(found, key=natural_sort_key)

    def inspect_image(self, file_path: Path) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """
        Inspect a single image file for validity, dimensions, alpha transparency, and hash.
        """
        try:
            sha256 = compute_file_sha256(file_path)
            with Image.open(file_path) as img:
                img.verify()

            # Re-open after verify to read properties (verify can invalidate the image instance)
            with Image.open(file_path) as img:
                width, height = img.size
                img_format = img.format or file_path.suffix.lstrip(".").upper()
                mode = img.mode
                has_transparency = mode in ("RGBA", "LA") or (mode == "P" and "transparency" in img.info)

            aspect_ratio = round(width / height, 4) if height > 0 else 0.0
            is_extremely_tall = aspect_ratio < 0.45 # e.g. 800x2500+ manhwa strip

            details = {
                "filename": file_path.name,
                "file_path": str(file_path),
                "sha256": sha256,
                "width": width,
                "height": height,
                "format": img_format,
                "mode": mode,
                "aspect_ratio": aspect_ratio,
                "has_transparency": has_transparency,
                "is_extremely_tall": is_extremely_tall,
                "file_size_bytes": file_path.stat().st_size,
            }
            return True, details, None
        except Exception as exc:
            logger.warning(f"Failed to inspect image {file_path.name}: {exc}")
            return False, None, str(exc)

    def run_full_inspection(self) -> ImageInspectionReport:
        """Scan directory and return a comprehensive ImageInspectionReport."""
        report = ImageInspectionReport()
        files = self.discover_images()
        report.total_scanned = len(files)

        hashes: Dict[str, List[str]] = {}

        for file_path in files:
            is_valid, details, err = self.inspect_image(file_path)
            if not is_valid or details is None:
                report.corrupted.append(file_path.name)
                continue

            report.valid_count += 1
            report.images.append(details)

            # Duplicate tracker
            h = details["sha256"]
            hashes.setdefault(h, []).append(file_path.name)

            if details["is_extremely_tall"]:
                report.tall_images.append({
                    "filename": file_path.name,
                    "dimensions": f"{details['width']}x{details['height']}",
                    "aspect_ratio": details["aspect_ratio"],
                    "recommendation": "Use normalized crop coordinates (0-1) rather than downscaling full strip."
                })

            if details["has_transparency"]:
                report.transparent_images.append(file_path.name)

        report.duplicates = {k: v for k, v in hashes.items() if len(v) > 1}
        return report
