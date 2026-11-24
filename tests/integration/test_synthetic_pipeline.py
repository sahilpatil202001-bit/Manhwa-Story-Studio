"""
Integration test: End-to-end rendering and FFprobe validation of a synthetic vertical video.
"""

from pathlib import Path
from PIL import Image, ImageDraw
import pytest

from manhwa_studio.config import AppConfig
from manhwa_studio.pipeline import ProductionPipeline
from manhwa_studio.project_manager import ProjectManager
from manhwa_studio.quality.media_probe import probe_media
from manhwa_studio.rights import RightsManager
from manhwa_studio.schemas import AssetMetadata, RightsStatus
from manhwa_studio.story.script_writer import load_scene_manifest, save_scene_manifest
from manhwa_studio.utils.hashing import compute_file_sha256


def create_synthetic_panel(path: Path, text: str, color: tuple[int, int, int]) -> None:
    """Create a synthetic test image panel with label."""
    img = Image.new("RGB", (720, 1280), color=color)
    draw = ImageDraw.Draw(img)
    draw.text((40, 60), text, fill=(255, 255, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", quality=90)


def test_end_to_end_synthetic_render(tmp_path: Path):
    """
    Test the full production pipeline from synthetic panel ingestion to final 1080x1920 MP4 rendering.
    """
    proj_dir = tmp_path / "synthetic_project"
    pm = ProjectManager(proj_dir)

    # Initialize subdirectories
    pm.artwork_dir.mkdir(parents=True)
    pm.audio_dir.mkdir(parents=True)
    pm.renders_dir.mkdir(parents=True)
    pm.subtitles_dir.mkdir(parents=True)
    pm.scripts_dir.mkdir(parents=True)
    pm.reports_dir.mkdir(parents=True)

    # 1. Create synthetic panels
    panel1 = pm.artwork_dir / "panel_01.jpg"
    panel2 = pm.artwork_dir / "panel_02.jpg"
    create_synthetic_panel(panel1, "Synthetic Scene 1", (40, 20, 60))
    create_synthetic_panel(panel2, "Synthetic Scene 2", (20, 50, 40))

    # 2. Register authorized rights
    rm = RightsManager(pm.rights_path)
    for p in [panel1, panel2]:
        meta = AssetMetadata(
            asset_id=p.name,
            file_path=str(p),
            sha256=compute_file_sha256(p),
            width=720,
            height=1280,
            format="JPEG",
            rights_status=RightsStatus.PERMISSION_GRANTED,
            source_description="Synthetic Test Fixture",
        )
        rm.register_asset(meta)

    # 3. Save config using mock voice provider and short duration for fast test
    cfg = AppConfig()
    cfg.project.series = "Synthetic Test Series"
    cfg.project.chapter = 1
    cfg.project.title = "Integration Test"
    cfg.project.target_duration_seconds = 4.0
    cfg.voice.provider = "mock" # Fast synthetic audio
    cfg.video.crf = 28 # Fast encoding
    cfg.video.preset = "ultrafast" # Speed up test
    pm.save_config(cfg)

    # 4. Run pipeline stages
    pipeline = ProductionPipeline(proj_dir)
    pipeline.run_ingestion()
    pipeline.run_script()

    # Approve script and trim scene durations for quick test
    m_file = pm.scripts_dir / "scene_manifest.json"
    manifest = load_scene_manifest(m_file)
    manifest.approved_by_user = True
    manifest.scenes = manifest.scenes[:2] # 2 scenes
    manifest.scenes[0].duration = 2.0
    manifest.scenes[1].duration = 2.0
    manifest.target_duration = 4.0
    save_scene_manifest(manifest, m_file)

    pipeline.run_voice()
    pipeline.run_subtitles()
    final_video = pipeline.run_render()

    assert final_video.exists()
    assert final_video.stat().st_size > 50000

    # 5. FFprobe validation
    probe = probe_media(final_video)
    assert probe.has_video is True
    assert probe.has_audio is True
    assert probe.width == 1080
    assert probe.height == 1920
    assert probe.video_codec in ("h264", "avc1")
    assert probe.audio_codec in ("aac", "mp4a")
    assert probe.duration_seconds >= 3.0 # Within expected bounds

    # Post-render validation stage
    pipeline.run_validation()
    qa_report = pm.reports_dir / "production_qa_report.html"
    assert qa_report.exists()
