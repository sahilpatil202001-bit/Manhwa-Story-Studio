"""
Manhwa Story Studio
Automated video production pipeline for manhwa story explainers.
"""

__version__ = "0.1.0"

import os
from pathlib import Path


def _load_env_file() -> None:
    env_path = Path(".env")
    if not env_path.exists():
        # Look in current working directory and parent dirs
        cwd = Path.cwd()
        for p in [cwd / ".env", cwd.parent / ".env"]:
            if p.exists():
                env_path = p
                break
    if env_path.exists():
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    if k and v and not v.startswith("your_"):
                        os.environ[k] = v
        except Exception:
            pass


_load_env_file()
