"""
Inbox scanner: discovers dropped chapter folders, parses chapter numbers, and organizes panel files.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from manhwa_studio.ingestion.image_inspector import SUPPORTED_EXTENSIONS, natural_sort_key
from manhwa_studio.logging_config import get_logger

logger = get_logger("manhwa_studio.ingestion.inbox")


class InboxChapterBatch(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    folder_path: Path
    inferred_series: Optional[str] = None
    chapter_number: int
    image_paths: List[Path] = Field(default_factory=list)


def parse_chapter_number(name: str) -> int:
    """Extract chapter number from names like 'ch_1', 'chapter_02', 'myst_ch3', '05'."""
    # Look for patterns like ch1, ch_1, chapter 1, etc.
    match = re.search(r"(?:chapter|ch|c)[_.\s-]*(\d+)", name, re.IGNORECASE)
    if match:
        return int(match.group(1))

    # Look for trailing or isolated number
    numbers = re.findall(r"\d+", name)
    if numbers:
        return int(numbers[-1])

    return 1


def scan_inbox(
    inbox_dir: Path,
    default_series: str = "Myst, Might, Mayhem",
    series_filter: Optional[str] = None,
    chapter_filter: Optional[int] = None,
) -> List[InboxChapterBatch]:
    """
    Scan inbox directory for subfolders containing manhwa images.
    Returns list of discovered chapter batches sorted by chapter number.
    Supports:
    1. Single chapter folder passed directly (e.g. assets/inbox/The Greatest Estate Developer/ch1/)
    2. Series subfolders (assets/inbox/<Series Name>/<ch1>/)
    3. Flat chapter folders (assets/inbox/<ch1>/)
    4. Filtering by series_filter and chapter_filter.
    """
    if not inbox_dir.exists():
        return []

    # Check if inbox_dir ITSELF is a single chapter directory containing images directly
    direct_images_here = [
        f for f in inbox_dir.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    if direct_images_here:
        sorted_images = sorted(direct_images_here, key=natural_sort_key)
        ch_num = parse_chapter_number(inbox_dir.name)
        inferred = default_series

        parent_name = inbox_dir.parent.name
        if parent_name.lower() not in ("inbox", "assets", "data"):
            inferred = parent_name.replace("_", " ").strip()
        name_lower = inbox_dir.name.lower() + " " + parent_name.lower()
        if "estate" in name_lower or "developer" in name_lower or "lloyd" in name_lower:
            inferred = "The Greatest Estate Developer"
        elif "myst" in name_lower and "mayhem" in name_lower:
            inferred = "Myst, Might, Mayhem"
        elif ("girlfriend" in name_lower and "dragon" in name_lower) or "dragon_girlfriend" in name_lower:
            inferred = "My Girlfriend Returned as a Dragon"

        batch = InboxChapterBatch(
            folder_path=inbox_dir,
            inferred_series=series_filter or inferred,
            chapter_number=chapter_filter if chapter_filter is not None else ch_num,
            image_paths=sorted_images,
        )
        return [batch]

    # Check for series override file in inbox dropzone
    series_override_file = inbox_dir / "series.txt"
    if series_override_file.exists():
        txt = series_override_file.read_text(encoding="utf-8").strip()
        if txt:
            default_series = txt
            logger.info(f"Loaded active series override from {series_override_file}: '{default_series}'")

    batches: List[InboxChapterBatch] = []

    for entry in inbox_dir.iterdir():
        if not entry.is_dir() or entry.name.startswith("."):
            continue

        direct_images = [
            f for f in entry.iterdir()
            if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
        ]

        if direct_images:
            # Case 1: Direct chapter folder (e.g. assets/inbox/ch1/)
            sorted_images = sorted(direct_images, key=natural_sort_key)
            ch_num = parse_chapter_number(entry.name)

            # Detect series from folder name if folder is like "greatest_estate_developer_ch1"
            inferred = default_series
            name_lower = entry.name.lower()
            if "estate" in name_lower or "developer" in name_lower or "lloyd" in name_lower:
                inferred = "The Greatest Estate Developer"
            elif "myst" in name_lower and "mayhem" in name_lower:
                inferred = "Myst, Might, Mayhem"
            elif ("girlfriend" in name_lower and "dragon" in name_lower) or "dragon_girlfriend" in name_lower:
                inferred = "My Girlfriend Returned as a Dragon"

            batches.append(
                InboxChapterBatch(
                    folder_path=entry,
                    inferred_series=inferred,
                    chapter_number=ch_num,
                    image_paths=sorted_images,
                )
            )
        else:
            # Case 2: Nested series folder (e.g. assets/inbox/The Greatest Estate Developer/ch1/)
            series_name = entry.name.replace("_", " ").strip()
            subfolders = [s for s in entry.iterdir() if s.is_dir() and not s.name.startswith(".")]
            for sub in subfolders:
                sub_images = [
                    f for f in sub.iterdir()
                    if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
                ]
                if not sub_images:
                    continue

                sorted_images = sorted(sub_images, key=natural_sort_key)
                ch_num = parse_chapter_number(sub.name)

                batches.append(
                    InboxChapterBatch(
                        folder_path=sub,
                        inferred_series=series_name,
                        chapter_number=ch_num,
                        image_paths=sorted_images,
                    )
                )

    # Apply series and chapter filters if requested
    if series_filter:
        s_norm = series_filter.lower().strip()
        batches = [b for b in batches if s_norm in b.inferred_series.lower() or b.inferred_series.lower() in s_norm]

    if chapter_filter is not None:
        batches = [b for b in batches if b.chapter_number == chapter_filter]

    batches.sort(key=lambda b: (b.inferred_series, b.chapter_number))
    logger.info(f"Discovered {len(batches)} chapter batch(es) in inbox: {[(b.inferred_series, b.folder_path.name) for b in batches]}")
    return batches
