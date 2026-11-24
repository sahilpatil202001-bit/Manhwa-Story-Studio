"""
Unit tests for configuration loading and validation.
"""

from pathlib import Path
import pytest
from manhwa_studio.config import AppConfig, load_config, save_config


def test_default_config_loading(tmp_path: Path):
    cfg = AppConfig()
    assert cfg.video.width == 1080
    assert cfg.video.height == 1920
    assert cfg.video.fps == 30
    assert cfg.project.series == "Myst, Might, Mayhem"

    target_file = tmp_path / "test_config.yaml"
    save_config(cfg, target_file)
    assert target_file.exists()

    loaded = load_config(target_file)
    assert loaded.project.series == cfg.project.series
    assert loaded.video.fps == 30
