"""
Production pipeline orchestrator coordinating ingestion, story, voice, subtitles, and rendering.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from manhwa_studio.audio.mix import assemble_narration_track, mix_final_audio_track
from manhwa_studio.ingestion.image_inspector import ImageInspector, natural_sort_key
from manhwa_studio.ingestion.image_manifest import generate_contact_sheet, generate_html_review_report
from manhwa_studio.logging_config import get_logger
from manhwa_studio.project_manager import ProjectManager
from manhwa_studio.quality.validate_output import generate_production_report, validate_rendered_video
from manhwa_studio.rendering.final_video import assemble_final_video, concatenate_segments
from manhwa_studio.rendering.segments import render_scene_segment
from manhwa_studio.rights import RightsManager
from manhwa_studio.ingestion.inbox_scanner import InboxChapterBatch, scan_inbox
from manhwa_studio.schemas import AssetMetadata, RightsStatus, StageStatus
from manhwa_studio.story.chapter_analyzer import create_initial_story_outline
from manhwa_studio.story.llm_title_generator import (
    generate_chapter_screenplay,
    suggest_chapter_title_and_hook,
)
from manhwa_studio.story.script_validator import ScriptValidator
from manhwa_studio.story.script_writer import (
    build_scene_manifest_from_outline,
    build_scene_manifest_from_screenplay,
    load_scene_manifest,
    save_scene_manifest,
)
from manhwa_studio.subtitles.generate import build_subtitle_segments, generate_ass, generate_srt
from manhwa_studio.subtitles.validate import SubtitleValidator
from manhwa_studio.utils.hashing import compute_file_sha256, compute_string_sha256
from manhwa_studio.voice.synthesis import VoiceSynthesisCoordinator
import shutil
from PIL import Image

logger = get_logger("manhwa_studio.pipeline")


class ProductionPipeline:
    """End-to-end automated video production coordinator."""

    def __init__(self, project_dir: Path):
        self.pm = ProjectManager(project_dir)
        self.config = self.pm.load_config()
        self.rights = RightsManager(self.pm.rights_path)

    def run_ingestion(self) -> None:
        """Scan artwork directory, detect duplicates/corrupt images, and generate review sheet."""
        logger.info("--- Stage 1: Ingestion & Inspection ---")
        t0 = time.time()
        self.pm.update_stage("ingest", StageStatus.RUNNING)

        inspector = ImageInspector(self.pm.artwork_dir)
        report = inspector.run_full_inspection()

        report_json = self.pm.reports_dir / "image_inspection.json"
        report.save_json(report_json)

        valid_images = [self.pm.artwork_dir / img["filename"] for img in report.images]

        outputs = [str(report_json)]
        if valid_images:
            contact_sheet = self.pm.reports_dir / "contact_sheet.jpg"
            generate_contact_sheet(valid_images, contact_sheet)
            outputs.append(str(contact_sheet))

            html_report = self.pm.reports_dir / "artwork_review.html"
            generate_html_review_report(report.to_dict(), html_report)
            outputs.append(str(html_report))

        dur = round(time.time() - t0, 2)
        self.pm.update_stage("ingest", StageStatus.SUCCEEDED, output_paths=outputs, duration_seconds=dur)
        logger.info(f"Ingestion completed: {report.valid_count} panels scanned and verified.")

    def run_script(self, part: int = 1, total_parts: int = 1) -> None:
        """Create structured story outline and scene manifest from ingested panels."""
        part_tag = f" (Part {part}/{total_parts})" if total_parts > 1 else ""
        logger.info(f"--- Stage 2: Story & Scene Manifest{part_tag} ---")
        t0 = time.time()
        self.pm.update_stage("story", StageStatus.RUNNING)

        inspector = ImageInspector(self.pm.artwork_dir)
        images = inspector.discover_images()

        if total_parts > 1 and len(images) > 1:
            chunk_len = len(images) // total_parts
            start_i = (part - 1) * chunk_len
            end_i = len(images) if part == total_parts else part * chunk_len
            part_images = images[start_i:end_i]
        else:
            part_images = images

        from manhwa_studio.story.llm_title_generator import filter_character_panels
        character_images = filter_character_panels(part_images)
        panel_filenames = [p.name for p in character_images]

        checkpoint_file = self.pm.scripts_dir / "screenplay_checkpoint.json"
        screenplay = generate_chapter_screenplay(
            series=self.config.project.series,
            chapter=self.config.project.chapter,
            panel_files=panel_filenames,
            sample_images=character_images if character_images else None,
            part=part,
            total_parts=total_parts,
            checkpoint_path=checkpoint_file,
        )

        manifest = build_scene_manifest_from_screenplay(
            series=self.config.project.series,
            chapter=self.config.project.chapter,
            screenplay=screenplay,
            available_panels=panel_filenames,
            default_scene_duration=4.0,
        )

        manifest_file = self.pm.scripts_dir / "scene_manifest.json"
        save_scene_manifest(manifest, manifest_file)

        dur = round(time.time() - t0, 2)
        self.pm.update_stage(
            "story",
            StageStatus.NEEDS_REVIEW,
            output_paths=[str(manifest_file)],
            duration_seconds=dur,
            error_message="Scene manifest created. Manual review and approval required before voice generation.",
        )
        logger.info("Story draft generated. User must approve before voice synthesis.")

    def run_voice(self) -> None:
        """Synthesize Hindi narration audio for approved scene manifest."""
        logger.info("--- Stage 3: Voice Generation ---")
        t0 = time.time()
        self.pm.update_stage("voice", StageStatus.RUNNING)

        manifest_file = self.pm.scripts_dir / "scene_manifest.json"
        if not manifest_file.exists():
            raise FileNotFoundError(f"Scene manifest not found at {manifest_file}. Run create-script first.")

        manifest = load_scene_manifest(manifest_file)

        # Validate manifest approval
        validator = ScriptValidator()
        is_valid, errors, warnings = validator.validate_manifest(manifest)
        if not is_valid:
            err_str = "; ".join(errors)
            self.pm.update_stage("voice", StageStatus.FAILED, error_message=err_str)
            raise ValueError(f"Script validation failed: {err_str}")

        if self.config.voice.provider == "mock":
            coordinator = VoiceSynthesisCoordinator(self.pm.audio_dir, self.config.voice)
            updated_manifest = coordinator.synthesize_manifest_narration(
                manifest,
                adjust_scene_durations=self.config.project.allow_duration_trim,
            )
        else:
            from manhwa_studio.studio_pro.series_manager import SeriesManager
            from manhwa_studio.studio_pro.voice_director import VoiceDirector

            profile = SeriesManager().get_or_create_profile(manifest.series or self.config.project.series)
            director = VoiceDirector(profile)
            director.synthesize_all_scenes(manifest, self.pm.audio_dir)
            updated_manifest = manifest
        save_scene_manifest(updated_manifest, manifest_file)

        dur = round(time.time() - t0, 2)
        outputs = [s.actual_audio_path for s in updated_manifest.scenes if s.actual_audio_path]
        self.pm.update_stage("voice", StageStatus.SUCCEEDED, output_paths=outputs, duration_seconds=dur)
        logger.info(f"Voice generation succeeded for {len(outputs)} scene segments.")

    def run_subtitles(self) -> None:
        """Generate and validate SRT and ASS subtitles from approved narration."""
        logger.info("--- Stage 4: Subtitles Generation ---")
        t0 = time.time()
        self.pm.update_stage("subtitles", StageStatus.RUNNING)

        manifest_file = self.pm.scripts_dir / "scene_manifest.json"
        manifest = load_scene_manifest(manifest_file)

        segments = build_subtitle_segments(manifest, max_words_per_line=self.config.subtitles.max_words_per_line)
        if not segments:
            raise ValueError("No subtitle text found in scene manifest.")

        srt_path = self.pm.subtitles_dir / "narration.srt"
        generate_srt(segments, srt_path)

        ass_path = self.pm.subtitles_dir / "narration.ass"
        generate_ass(
            segments,
            ass_path,
            settings=self.config.subtitles,
            video_width=self.config.video.width,
            video_height=self.config.video.height,
        )

        ok, errors, warnings = SubtitleValidator.validate_srt_file(srt_path)
        if not ok:
            err_str = "; ".join(errors)
            self.pm.update_stage("subtitles", StageStatus.FAILED, error_message=err_str)
            raise ValueError(f"Subtitle validation failed: {err_str}")

        dur = round(time.time() - t0, 2)
        self.pm.update_stage(
            "subtitles",
            StageStatus.SUCCEEDED,
            output_paths=[str(srt_path), str(ass_path)],
            duration_seconds=dur,
        )
        logger.info(f"Subtitles generated and validated: {srt_path.name}, {ass_path.name}")

    def run_render(self) -> Path:
        """Render scene segments, mix audio tracks, and assemble final 1080x1920 MP4."""
        logger.info("--- Stage 5: Video & Audio Rendering ---")
        t0 = time.time()
        self.pm.update_stage("render", StageStatus.RUNNING)

        manifest_file = self.pm.scripts_dir / "scene_manifest.json"
        manifest = load_scene_manifest(manifest_file)

        # Rights check for used artwork
        used_images = [self.pm.artwork_dir / s.image_file for s in manifest.scenes if s.image_file]
        rights_ok, rights_errors = self.rights.validate_production_readiness(used_images)
        if not rights_ok:
            err_msg = "Artwork rights verification failed: " + "; ".join(rights_errors)
            self.pm.update_stage("render", StageStatus.FAILED, error_message=err_msg)
            raise PermissionError(err_msg)

        # 1. Render visual segments
        segments_dir = self.pm.renders_dir / "segments"
        segment_paths: list[Path] = []
        for scene in manifest.scenes:
            seg_path = render_scene_segment(
                scene=scene,
                artwork_dir=self.pm.artwork_dir,
                output_dir=segments_dir,
                video_settings=self.config.video,
                fill_mode=self.config.motion.fill_mode,
                zoom_scale=self.config.motion.zoom_scale,
            )
            segment_paths.append(seg_path)

        # 2. Concatenate visual segments
        concat_list = self.pm.renders_dir / "concat_list.txt"
        merged_video = self.pm.renders_dir / "merged_video.mp4"
        concatenate_segments(segment_paths, concat_list, merged_video, fps=self.config.video.fps)

        # 3. Assemble narration and mix audio
        narration_wav = self.pm.audio_dir / "narration_full.wav"
        assemble_narration_track(manifest, narration_wav, sample_rate=self.config.audio.sample_rate)

        music_file = Path(self.config.audio.music_file) if self.config.audio.music_file else None
        mixed_audio = self.pm.audio_dir / "mixed_audio.aac"
        mix_final_audio_track(
            narration_wav=narration_wav,
            output_mixed_audio=mixed_audio,
            total_duration=manifest.total_duration,
            audio_settings=self.config.audio,
            music_file=music_file,
        )

        # 4. Assemble final MP4
        final_mp4 = self.pm.renders_dir / f"final_{self.config.project.series_slug if hasattr(self.config.project, 'series_slug') else 'episode'}.mp4"
        ass_subtitles = self.pm.subtitles_dir / "narration.ass"

        assemble_final_video(
            merged_video_path=merged_video,
            mixed_audio_path=mixed_audio,
            output_mp4_path=final_mp4,
            config=self.config,
            subtitle_ass_path=ass_subtitles,
        )

        dur = round(time.time() - t0, 2)
        self.pm.update_stage("render", StageStatus.SUCCEEDED, output_paths=[str(final_mp4)], duration_seconds=dur)
        logger.info(f"Rendering completed successfully in {dur}s: {final_mp4}")
        return final_mp4

    def run_validation(self) -> None:
        """Validate final rendered MP4 against technical acceptance criteria."""
        logger.info("--- Stage 6: Post-Render Validation ---")
        t0 = time.time()
        self.pm.update_stage("validate", StageStatus.RUNNING)

        final_candidates = list(self.pm.renders_dir.glob("final_*.mp4"))
        if not final_candidates:
            raise FileNotFoundError(f"No final rendered video found in {self.pm.renders_dir}")
        video_path = final_candidates[0]

        manifest = load_scene_manifest(self.pm.scripts_dir / "scene_manifest.json")
        report = validate_rendered_video(video_path, self.config, manifest)

        html_report = self.pm.reports_dir / "production_qa_report.html"
        generate_production_report(report, manifest, self.config, html_report)

        dur = round(time.time() - t0, 2)
        status = StageStatus.SUCCEEDED if report.is_valid else StageStatus.FAILED
        self.pm.update_stage(
            "validate",
            status,
            output_paths=[str(video_path), str(html_report)],
            duration_seconds=dur,
            error_message="; ".join(report.errors) if report.errors else None,
        )

        if not report.is_valid:
            raise RuntimeError(f"Video QA validation failed: {'; '.join(report.errors)}")

        logger.info("Validation passed! Final video matches all specifications.")


def process_inbox_batches(
    inbox_dir: Path,
    base_projects_dir: Path = Path("data/projects"),
    series_name: Optional[str] = None,
    chapter: Optional[int] = None,
    chapter_start: Optional[int] = None,
    chapter_end: Optional[int] = None,
    auto_approve: bool = False,
    auto_render: bool = False,
) -> List[Path]:
    """
    Automatically process uploaded chapter folders in the inbox dropzone:
    1. Scans inbox for chapter batches (optionally filtered by series_name and chapter).
    2. Uses Gemini or fallback heuristics to analyze panels and suggest a high-impact title and Hindi hook.
    3. Initializes the chapter project directory structure.
    4. Copies/moves images into the artwork directory.
    5. Registers authorized rights declarations with SHA-256 integrity.
    6. Runs image inspection, generates contact sheet and HTML review report.
    7. Creates the scene manifest with AI title and Hindi hook.
    8. Optionally auto-approves and renders the full video.
    """
    # Auto-extract and clean any dropped zip files in inbox dropzone
    from manhwa_studio.ingestion.chapter_cleaner import clean_and_unpack_inbox
    clean_and_unpack_inbox(inbox_dir)

    if chapter is not None and (chapter_start is not None or chapter_end is not None):
        raise ValueError("Use either a single chapter or a chapter range, not both.")
    if chapter_start is not None and chapter_end is not None and chapter_start > chapter_end:
        raise ValueError("chapter_start must not be greater than chapter_end.")

    batches = scan_inbox(
        inbox_dir,
        default_series=series_name or "Myst, Might, Mayhem",
        series_filter=series_name,
        chapter_filter=chapter,
    )
    if chapter_start is not None:
        batches = [batch for batch in batches if batch.chapter_number >= chapter_start]
    if chapter_end is not None:
        batches = [batch for batch in batches if batch.chapter_number <= chapter_end]
    if not batches:
        logger.info(f"No unprocessed chapter folders found matching criteria in: {inbox_dir}")
        return []

    processed_projects: List[Path] = []
    default_cfg_path = Path("config/default.yaml")

    for batch in batches:
        series = series_name or batch.inferred_series or "Myst, Might, Mayhem"
        ch_num = batch.chapter_number

        # Auto-detect tall webtoon strips and automatically slice them into 9:16 panels
        from manhwa_studio.ingestion.strip_slicer import slice_chapter_directory
        has_tall_strips = False
        for img_p in batch.image_paths[:5]:
            try:
                with Image.open(img_p) as im:
                    w, h = im.size
                    if h > w * 2.2:
                        has_tall_strips = True
                        break
            except Exception:
                pass

        if has_tall_strips:
            logger.info(f"Detected tall webtoon strips in '{batch.folder_path.name}'. Automatically slicing into panels...")
            sliced_panels = slice_chapter_directory(batch.folder_path, backup_originals=True)
            if sliced_panels:
                batch.image_paths = sorted(sliced_panels, key=natural_sort_key)

        logger.info(f"Processing inbox batch for '{series}' Chapter {ch_num} ({len(batch.image_paths)} panels)...")

        # 1. AI Title & Hook Analysis
        ai_suggestion = suggest_chapter_title_and_hook(
            series=series,
            chapter=ch_num,
            sample_images=batch.image_paths,
        )
        logger.info(f"AI Selected Title: '{ai_suggestion.title}' | Hook: '{ai_suggestion.hindi_hook[:30]}...'")

        # 2. Initialize project
        pm = ProjectManager.create_project(
            base_dir=base_projects_dir,
            series=series,
            chapter=ch_num,
            title=ai_suggestion.title,
            default_config_path=default_cfg_path if default_cfg_path.exists() else None,
        )

        # 3. Copy panel images into project artwork/ directory
        rm = RightsManager(pm.rights_path)
        for img_path in batch.image_paths:
            dest_path = pm.artwork_dir / img_path.name
            shutil.copy2(str(img_path), str(dest_path))

            # Compute hash and dimensions
            h = compute_file_sha256(dest_path)
            try:
                with Image.open(dest_path) as im:
                    w, h_dim = im.size
                    fmt = im.format or dest_path.suffix.lstrip(".").upper()
            except Exception:
                w, h_dim, fmt = 1080, 1920, "WEBP"

            # 4. Register rights status
            meta = AssetMetadata(
                asset_id=dest_path.name,
                file_path=str(dest_path),
                sha256=h,
                width=w,
                height=h_dim,
                format=fmt,
                source_description=f"Panel from {series} Ch.{ch_num}",
                rights_status=RightsStatus.PERMISSION_GRANTED,
                license_reference="Inbox upload for story commentary",
                attribution="Original artwork by respective copyright holders",
                allow_commercial=False,
                allow_modifications=True,
            )
            rm.register_asset(meta)

        # 5. Run Ingestion (Contact sheet + HTML review report)
        pipeline = ProductionPipeline(pm.project_dir)
        pipeline.run_ingestion()

        # 6. Generate Story Script
        pipeline.run_script()

        # Update scene manifest with AI title and opening hook if needed
        m_file = pm.scripts_dir / "scene_manifest.json"
        manifest = load_scene_manifest(m_file)
        if ai_suggestion.title and not manifest.title:
            manifest.title = ai_suggestion.title
        save_scene_manifest(manifest, m_file)

        # 7. Auto-approve and render if requested
        if auto_approve or auto_render:
            manifest.approved_by_user = True
            save_scene_manifest(manifest, m_file)

            if auto_render:
                pipeline.run_voice()
                pipeline.run_subtitles()
                pipeline.run_render()
                pipeline.run_validation()

        processed_projects.append(pm.project_dir)
        logger.info(f"Successfully processed inbox batch for Chapter {ch_num} -> {pm.project_dir}")

    return processed_projects
