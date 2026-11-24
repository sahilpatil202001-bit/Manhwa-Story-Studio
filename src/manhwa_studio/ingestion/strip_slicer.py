"""
Smart Manhwa Webtoon Strip Slicer:
Automatically slices tall scrolling webtoon strips along natural panel gutters into 9:16 vertical video scenes.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import List, Tuple
from PIL import Image

from manhwa_studio.ingestion.image_inspector import natural_sort_key
from manhwa_studio.logging_config import get_logger

logger = get_logger("manhwa_studio.ingestion.slicer")


def find_best_gutter(
    gray_img: Image.Image,
    start_y: int,
    end_y: int,
    sample_step: int = 15,
) -> int:
    """
    Search between start_y and end_y for the row with the most uniform color (gutter margin).
    Returns the y-coordinate of the best gutter line.
    """
    w, h = gray_img.size
    best_y = (start_y + end_y) // 2
    min_variance = float("inf")

    # Clamp search window
    start_y = max(0, start_y)
    end_y = min(h - 1, end_y)

    sample_xs = [int(i * w / sample_step) for i in range(sample_step)]

    for y in range(start_y, end_y, 2):
        pts = [gray_img.getpixel((x, y)) for x in sample_xs]
        variance = max(pts) - min(pts)

        if variance < min_variance:
            min_variance = variance
            best_y = y
            # If completely solid row, we found an ideal cut line
            if variance == 0:
                break

    return best_y


def calculate_slice_points(
    img: Image.Image,
    target_aspect: float = 9 / 16, # width / height
    tolerance_ratio: float = 0.25,
) -> List[int]:
    """
    Calculate cut line Y-coordinates down the strip, snapping cuts to panel gutters.
    """
    w, h = img.size
    aspect_ratio = w / h
    if aspect_ratio >= 0.45:
        # Not a tall strip; no slicing needed
        return [0, h]

    gray = img.convert("L")
    ideal_panel_h = int(w / target_aspect) # e.g. 800 * 16 / 9 = ~1422px
    tolerance_px = int(ideal_panel_h * tolerance_ratio) # +/- ~350px

    slice_points = [0]
    current_y = 0

    while current_y < h:
        ideal_next_y = current_y + ideal_panel_h
        if ideal_next_y >= h - (ideal_panel_h * 0.4):
            # Close to the bottom; snap to final row
            slice_points.append(h)
            break

        search_start = max(current_y + 400, ideal_next_y - tolerance_px)
        search_end = min(h - 100, ideal_next_y + tolerance_px)

        cut_y = find_best_gutter(gray, search_start, search_end)
        slice_points.append(cut_y)
        current_y = cut_y

    return slice_points


def slice_strip_file(
    input_file: Path,
    output_dir: Path,
    base_prefix: str,
    target_aspect: float = 9 / 16,
) -> List[Path]:
    """
    Slice an individual tall strip file into multiple 9:16 friendly panels.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    results: List[Path] = []

    with Image.open(input_file) as img:
        w, h = img.size
        aspect = w / h

        if aspect >= 0.45:
            # Standard panel, save as single output
            out_file = output_dir / f"{base_prefix}.webp"
            img.save(out_file, "WEBP", quality=95)
            return [out_file]

        cuts = calculate_slice_points(img, target_aspect=target_aspect)
        logger.info(f"Slicing tall strip {input_file.name} ({w}x{h}) into {len(cuts)-1} panels along gutters...")

        for i in range(len(cuts) - 1):
            top = cuts[i]
            bottom = cuts[i + 1]
            if bottom <= top + 10:
                continue

            panel_img = img.crop((0, top, w, bottom))
            out_file = output_dir / f"{base_prefix}_{i+1:02d}.webp"
            panel_img.save(out_file, "WEBP", quality=95)
            results.append(out_file)

    return results


def slice_chapter_directory(
    folder_path: Path,
    backup_originals: bool = True,
    target_aspect: float = 9 / 16,
) -> List[Path]:
    """
    Slice all tall webtoon strips in a chapter directory:
    - Automatically backs up raw long strips to `_raw_strips/`.
    - Generates neatly sequenced panels (`panel_001.webp`, `panel_002.webp`, etc.).
    """
    supported = {".webp", ".jpg", ".jpeg", ".png"}
    files = [
        f for f in folder_path.iterdir()
        if f.is_file() and f.suffix.lower() in supported and not f.name.startswith("panel_")
    ]
    if not files:
        logger.warning(f"No unsliced strips found in {folder_path}")
        return []

    sorted_files = sorted(files, key=natural_sort_key)
    raw_backup_dir = folder_path / "_raw_strips"
    temp_sliced_dir = folder_path / "_temp_sliced"

    if backup_originals:
        raw_backup_dir.mkdir(exist_ok=True)

    all_sliced_panels: List[Path] = []

    # Slice into temporary directory first
    for idx, f in enumerate(sorted_files, 1):
        strip_prefix = f"strip_{idx:03d}"
        sliced = slice_strip_file(f, temp_sliced_dir, strip_prefix, target_aspect=target_aspect)
        all_sliced_panels.extend(sliced)

    # Move originals to backup folder (or delete if not backing up)
    for f in sorted_files:
        if backup_originals:
            dest = raw_backup_dir / f.name
            shutil.move(str(f), str(dest))
        else:
            f.unlink()

    # Move and rename sliced panels to sequential panel_001.webp, panel_002.webp, etc.
    final_panels: List[Path] = []
    all_sliced_panels.sort(key=natural_sort_key)

    import time
    for idx, sliced_file in enumerate(all_sliced_panels, 1):
        target_name = f"panel_{idx:03d}.webp"
        final_dest = folder_path / target_name
        
        # If target file already exists (e.g. from an interrupted run), remove it first
        if final_dest.exists():
            try:
                final_dest.unlink()
            except Exception:
                pass

        # Windows-safe move with retry to avoid WinError 32
        moved = False
        for attempt in range(5):
            try:
                shutil.copy2(str(sliced_file), str(final_dest))
                sliced_file.unlink()
                moved = True
                break
            except Exception:
                time.sleep(0.1)

        if not moved:
            shutil.copy2(str(sliced_file), str(final_dest))

        final_panels.append(final_dest)

    # Clean up temp directory
    if temp_sliced_dir.exists():
        shutil.rmtree(temp_sliced_dir, ignore_errors=True)

    logger.info(f"Chapter slicing complete! Generated {len(final_panels)} panels in {folder_path.name}")
    return final_panels
