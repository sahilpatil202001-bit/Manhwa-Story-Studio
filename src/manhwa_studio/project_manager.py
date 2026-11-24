"""
Project lifecycle, workspace structure, and stage state manager.
"""

from __future__ import annotations

import datetime
import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from manhwa_studio.config import AppConfig, load_config, save_config
from manhwa_studio.logging_config import get_logger
from manhwa_studio.schemas import ProjectState, StageRecord, StageStatus
from manhwa_studio.utils.hashing import compute_dict_sha256
from manhwa_studio.utils.paths import ensure_directory, safe_slug

logger = get_logger("manhwa_studio.project")


class ProjectManager:
    """Manages project directories, project-level configurations, and stage execution state."""

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir.resolve()
        self.config_path = self.project_dir / "project.yaml"
        self.state_path = self.project_dir / "state.json"
        self.rights_path = self.project_dir / "rights_manifest.json"
        self.artwork_dir = self.project_dir / "artwork"
        self.audio_dir = self.project_dir / "audio"
        self.renders_dir = self.project_dir / "renders"
        self.subtitles_dir = self.project_dir / "subtitles"
        self.scripts_dir = self.project_dir / "scripts"
        self.reports_dir = self.project_dir / "reports"

    @classmethod
    def create_project(
        cls,
        base_dir: Path,
        series: str,
        chapter: int,
        title: str,
        default_config_path: Optional[Path] = None,
    ) -> "ProjectManager":
        """Initialize a new project directory with standard subdirectories and default config."""
        series_slug = safe_slug(series)
        proj_dir = base_dir / series_slug / f"chapter_{chapter:03d}"
        manager = cls(proj_dir)

        # Create all subdirectories
        for d in [
            manager.artwork_dir,
            manager.audio_dir,
            manager.renders_dir,
            manager.subtitles_dir,
            manager.scripts_dir,
            manager.reports_dir,
        ]:
            ensure_directory(d)

        # Load or create base config
        if default_config_path and default_config_path.exists():
            cfg = load_config(default_config_path)
        else:
            cfg = AppConfig()

        cfg.project.series = series
        cfg.project.chapter = chapter
        cfg.project.title = title

        save_config(cfg, manager.config_path)

        # Initialize state.json
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        state = ProjectState(
            series=series,
            chapter=chapter,
            created_at=now,
            updated_at=now,
            stages={
                "init": StageRecord(status=StageStatus.SUCCEEDED, completed_at=now),
                "ingest": StageRecord(status=StageStatus.PENDING),
                "story": StageRecord(status=StageStatus.PENDING),
                "voice": StageRecord(status=StageStatus.PENDING),
                "subtitles": StageRecord(status=StageStatus.PENDING),
                "render": StageRecord(status=StageStatus.PENDING),
                "validate": StageRecord(status=StageStatus.PENDING),
            },
        )
        manager.save_state(state)

        # Initialize empty rights manifest if absent
        if not manager.rights_path.exists():
            with open(manager.rights_path, "w", encoding="utf-8") as f:
                json.dump({}, f, indent=2)

        logger.info(f"Initialized new project for '{series}' Ch.{chapter} at: {proj_dir}")
        return manager

    def load_config(self) -> AppConfig:
        """Load and return project configuration."""
        return load_config(self.config_path)

    def save_config(self, config: AppConfig) -> None:
        """Save updated project configuration."""
        save_config(config, self.config_path)

    def load_state(self) -> ProjectState:
        """Load project state atomically."""
        if not self.state_path.exists():
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            return ProjectState(
                series="Unknown",
                chapter=1,
                created_at=now,
                updated_at=now,
            )
        with open(self.state_path, "r", encoding="utf-8") as f:
            return ProjectState.model_validate_json(f.read())

    def save_state(self, state: ProjectState) -> None:
        """Save state atomically using a temporary file to prevent corruption."""
        state.updated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        temp_file = self.state_path.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            f.write(state.model_dump_json(indent=2))
        shutil.move(str(temp_file), str(self.state_path))

    def update_stage(
        self,
        stage_name: str,
        status: StageStatus,
        output_paths: Optional[List[str]] = None,
        error_message: Optional[str] = None,
        input_hash: Optional[str] = None,
        config_hash: Optional[str] = None,
        duration_seconds: Optional[float] = None,
    ) -> None:
        """Update a stage's progress record."""
        state = self.load_state()
        record = state.stages.get(stage_name, StageRecord())
        record.status = status
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        if status == StageStatus.RUNNING:
            record.started_at = now
            record.error_message = None
        elif status in {StageStatus.SUCCEEDED, StageStatus.FAILED, StageStatus.NEEDS_REVIEW}:
            record.completed_at = now
            if output_paths is not None:
                record.output_paths = output_paths
            if error_message is not None:
                record.error_message = error_message
            if input_hash is not None:
                record.input_hash = input_hash
            if config_hash is not None:
                record.config_hash = config_hash
            if duration_seconds is not None:
                record.duration_seconds = duration_seconds

        state.stages[stage_name] = record
        self.save_state(state)

    def should_skip_stage(self, stage_name: str, current_input_hash: str, current_config_hash: str) -> bool:
        """Determine if a stage can be resumed/skipped because inputs and config have not changed."""
        state = self.load_state()
        record = state.stages.get(stage_name)
        if not record or record.status != StageStatus.SUCCEEDED:
            return False

        if record.input_hash == current_input_hash and record.config_hash == current_config_hash:
            # Check that recorded outputs actually exist on disk
            for out in record.output_paths:
                if not Path(out).exists():
                    return False
            return True
        return False
