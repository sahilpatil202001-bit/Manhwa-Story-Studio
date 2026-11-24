"""
Unit tests for image inspection, natural sorting, and duplicate detection.
"""

from pathlib import Path
from PIL import Image
import pytest
from manhwa_studio.ingestion.image_inspector import ImageInspector, natural_sort_key


def test_natural_sorting():
    paths = [
        Path("page_10.jpg"),
        Path("page_1.jpg"),
        Path("page_2.jpg"),
        Path("page_20.jpg"),
    ]
    sorted_paths = sorted(paths, key=natural_sort_key)
    expected = [Path("page_1.jpg"), Path("page_2.jpg"), Path("page_10.jpg"), Path("page_20.jpg")]
    assert sorted_paths == expected


def test_inspector_with_synthetic_images(tmp_path: Path):
    art_dir = tmp_path / "artwork"
    art_dir.mkdir()

    # Create normal image
    img1 = Image.new("RGB", (800, 1200), color=(100, 150, 200))
    img1.save(art_dir / "panel_1.jpg")

    # Create duplicate image
    img1.save(art_dir / "panel_2_dupe.jpg")

    # Create extremely tall manhwa strip
    tall = Image.new("RGB", (600, 3000), color=(50, 50, 50))
    tall.save(art_dir / "panel_3_tall.jpg")

    inspector = ImageInspector(art_dir)
    report = inspector.run_full_inspection()

    assert report.total_scanned == 3
    assert report.valid_count == 3
    assert len(report.duplicates) == 1 # Has duplicate cluster
    assert len(report.tall_images) == 1
    assert report.tall_images[0]["filename"] == "panel_3_tall.jpg"
