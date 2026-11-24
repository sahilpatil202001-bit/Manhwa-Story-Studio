"""
Hashing utilities for image integrity, duplicate detection, and cache keys.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def compute_file_sha256(filepath: Path, chunk_size: int = 65536) -> str:
    """Compute SHA-256 hex digest for a file efficiently."""
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest()


def compute_string_sha256(data: str) -> str:
    """Compute SHA-256 hex digest for a string payload."""
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def compute_dict_sha256(data: dict[str, Any]) -> str:
    """Compute a deterministic hash for a dictionary structure."""
    serialized = json.dumps(data, sort_keys=True, default=str)
    return compute_string_sha256(serialized)
