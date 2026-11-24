"""
Filesystem and path manipulation utilities.
"""

from __future__ import annotations

import re
from pathlib import Path


def safe_slug(text: str) -> str:
    """Convert arbitrary title/series text into a filesystem-safe directory slug."""
    text = text.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "_", text)
    return text.strip("_") or "unnamed"


def resolve_project_path(base_dir: Path | str, subpath: Path | str) -> Path:
    """Ensure subpath is safely resolved inside base_dir or returned as absolute."""
    p = Path(subpath)
    if p.is_absolute():
        return p
    return (Path(base_dir) / p).resolve()


def ensure_directory(path: Path) -> Path:
    """Ensure that the given directory exists, creating parents if needed."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def clean_filename(filename: str) -> str:
    """Clean filename of unwanted characters for FFmpeg and command arguments."""
    return re.sub(r'[<>:"/\\|?*]', "_", filename)
