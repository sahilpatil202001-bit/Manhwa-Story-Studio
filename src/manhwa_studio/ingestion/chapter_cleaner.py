"""
Chapter Cleaner & Unpacker:
Extracts clean manhwa chapter images from zip archives, removes ads, junk, and duplicate files,
and prepares the chapter folder for immediate ingestion.
"""

from __future__ import annotations

import os
import re
import sys
import zipfile
from pathlib import Path
from typing import List, Optional, Tuple

from manhwa_studio.logging_config import get_logger

logger = get_logger("manhwa_studio.ingestion.cleaner")

ALLOWED_EXTENSIONS = (".webp", ".png", ".jpg", ".jpeg")
DELETE_ZIP_AFTER_EXTRACT = True


def extract_page_number(filename: str) -> int:
    """Extract integer page number for natural numerical sorting."""
    match = re.search(r"(\d+)", filename)
    return int(match.group(1)) if match else 0


def is_valid_chapter_image(filename: str) -> Tuple[bool, str]:
    """
    Checks if a filename inside the zip is a clean chapter page.
    Returns (is_valid, normalized_filename).
    Filters out ads, duplicate copies (_1, _copy), svg icons, credits, and non-numeric files.
    """
    clean_name = filename.strip().rstrip(". ")
    base_name = os.path.basename(clean_name)
    
    # Check for valid format: purely numeric filename + valid extension (e.g. 001.webp, 02.jpg)
    pattern = rf"^\d+\.(?:{'|'.join(ext.lstrip('.') for ext in ALLOWED_EXTENSIONS)})$"
    if re.match(pattern, base_name, re.IGNORECASE):
        stem = Path(base_name).stem
        if stem.isdigit():
            return True, base_name
            
    return False, ""


def process_chapter_zip(
    zip_path: Path,
    delete_zip: bool = True,
    dry_run: bool = False,
) -> bool:
    """
    Extracts only valid chapter images directly into the chapter folder,
    then removes the zip file.
    """
    target_folder = zip_path.parent
    logger.info(f"Processing chapter archive: {zip_path.name} in {target_folder.name}")
    
    valid_entries: List[Tuple[zipfile.ZipInfo, str]] = []
    removed_count = 0
    seen_names = set()

    try:
        with zipfile.ZipFile(zip_path, "r") as z_in:
            for item in z_in.infolist():
                if item.is_dir():
                    continue

                is_valid, clean_name = is_valid_chapter_image(item.filename)
                if is_valid and clean_name not in seen_names:
                    seen_names.add(clean_name)
                    valid_entries.append((item, clean_name))
                else:
                    removed_count += 1

        if not valid_entries:
            logger.warning(f"No valid chapter images found in {zip_path.name}! Leaving zip intact.")
            return False

        # Sort pages numerically
        valid_entries.sort(key=lambda x: extract_page_number(x[1]))

        logger.info(
            f"Found {len(valid_entries)} clean pages ({valid_entries[0][1]} to {valid_entries[-1][1]}). "
            f"Ignored {removed_count} junk/duplicate entries."
        )

        if dry_run:
            logger.info(f"[DRY RUN] Would extract {len(valid_entries)} images to {target_folder} and delete {zip_path.name}.")
            return True

        # Extract only valid images directly into chapter directory
        with zipfile.ZipFile(zip_path, "r") as z_in:
            for item, clean_name in valid_entries:
                data = z_in.read(item.filename)
                out_path = target_folder / clean_name
                out_path.write_bytes(data)

        logger.info(f"Extracted {len(valid_entries)} clean images into {target_folder}")

        if delete_zip:
            bak_path = zip_path.with_suffix(".zip.bak")
            if bak_path.exists():
                bak_path.unlink()
            zip_path.unlink()
            logger.info(f"Deleted source zip archive: {zip_path.name}")

        return True

    except Exception as e:
        logger.error(f"Error processing {zip_path.name}: {e}")
        return False


def find_all_chapter_zips(root_dir: Path) -> List[Path]:
    """Find all zip files across chapter folders under root_dir."""
    zip_files = []
    for p in root_dir.rglob("*.zip"):
        if p.name.endswith(".tmp.zip"):
            continue
        zip_files.append(p)
    zip_files.sort(key=lambda p: (extract_page_number(p.parent.name), p.name))
    return zip_files


def resolve_target_zips(root_dir: Path, folder_specs: Optional[List[str]] = None) -> List[Path]:
    """
    Finds zip files based on user-specified chapter folder names or numbers.
    Supports:
      - Folder specs: ['ch2', 'ch3'], ['ch2,ch3']
      - Numbers: ['2', '3'] -> matches 'ch2', 'chapter2', 'ch 2', '2'
      - Empty/None -> searches all folders under root_dir
    """
    if not folder_specs:
        return find_all_chapter_zips(root_dir)

    tokens = []
    for spec in folder_specs:
        for part in spec.split(","):
            p_clean = part.strip()
            if p_clean:
                tokens.append(p_clean)

    matched_zips = []
    for token in tokens:
        target_dirs = []
        direct_path = Path(token)

        if direct_path.is_dir():
            target_dirs.append(direct_path)
        elif (root_dir / token).is_dir():
            target_dirs.append(root_dir / token)
        elif token.isdigit():
            candidates = [f"ch{token}", f"chapter{token}", f"ch {token}", f"chapter {token}", token]
            found = False
            for cand in candidates:
                cand_path = root_dir / cand
                if cand_path.is_dir():
                    target_dirs.append(cand_path)
                    found = True
                    break
            if not found:
                # Also search recursive under series subfolders (e.g. assets/inbox/<series>/ch2)
                for cand in candidates:
                    for sub in root_dir.rglob(cand):
                        if sub.is_dir():
                            target_dirs.append(sub)
                            found = True
        else:
            # Fuzzy match folder in root_dir
            for sub in root_dir.rglob(token):
                if sub.is_dir():
                    target_dirs.append(sub)

        for td in target_dirs:
            for z in td.glob("*.zip"):
                if not z.name.endswith(".tmp.zip"):
                    matched_zips.append(z)

    # Deduplicate preserving order
    unique_zips: List[Path] = []
    seen = set()
    for z in matched_zips:
        if z not in seen:
            seen.add(z)
            unique_zips.append(z)

    unique_zips.sort(key=lambda p: (extract_page_number(p.parent.name), p.name))
    return unique_zips


def clean_and_unpack_inbox(
    root_dir: Path,
    folders: Optional[List[str]] = None,
    delete_zip: bool = True,
    dry_run: bool = False,
) -> int:
    """
    High-level entry point to clean and unpack zip archives in inbox or asset folders.
    Returns number of chapters successfully processed.
    """
    zips = resolve_target_zips(root_dir, folders)
    if not zips:
        logger.info(f"No zip archives found to clean in: {root_dir}")
        return 0

    count = 0
    for z in zips:
        if process_chapter_zip(z, delete_zip=delete_zip, dry_run=dry_run):
            count += 1

    return count
