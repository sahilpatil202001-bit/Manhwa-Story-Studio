"""
Output validation and production report generator.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import List, Tuple

from manhwa_studio.config import AppConfig
from manhwa_studio.logging_config import get_logger
from manhwa_studio.quality.media_probe import probe_media
from manhwa_studio.schemas import MediaProbeResult, SceneManifest, ValidationReport

logger = get_logger("manhwa_studio.quality.validate")


def validate_rendered_video(
    video_path: Path,
    config: AppConfig,
    manifest: SceneManifest,
    tolerance_seconds: float = 3.0,
) -> ValidationReport:
    """
    Perform complete post-render quality check against acceptance criteria.
    """
    errors: List[str] = []
    warnings: List[str] = []

    if not video_path.exists():
        return ValidationReport(
            is_valid=False,
            errors=[f"Rendered video file not found: {video_path}"],
            warnings=[],
        )

    probe = probe_media(video_path)

    # 1. Video stream checks
    if not probe.has_video:
        errors.append("Video stream is missing from the output container.")
    else:
        if probe.width != config.video.width or probe.height != config.video.height:
            errors.append(
                f"Resolution mismatch: expected {config.video.width}x{config.video.height}, got {probe.width}x{probe.height}."
            )

        if probe.video_codec not in ("h264", "libx264", "avc1"):
            errors.append(f"Video codec mismatch: expected H.264, got '{probe.video_codec}'.")

        if probe.fps and abs(probe.fps - config.video.fps) > 1.0:
            warnings.append(f"FPS deviation: expected {config.video.fps}, got {probe.fps}.")

    # 2. Audio stream checks
    if not probe.has_audio:
        errors.append("Audio stream is missing from the output container.")
    else:
        if probe.audio_codec not in ("aac", "mp4a"):
            warnings.append(f"Audio codec is '{probe.audio_codec}', recommended is AAC.")

    # 3. Duration check
    expected_duration = manifest.total_duration
    diff = abs(probe.duration_seconds - expected_duration)
    if diff > tolerance_seconds:
        warnings.append(
            f"Rendered duration ({probe.duration_seconds:.1f}s) deviates from expected scene timing ({expected_duration:.1f}s) by {diff:.1f}s."
        )

    is_valid = len(errors) == 0
    return ValidationReport(
        is_valid=is_valid,
        errors=errors,
        warnings=warnings,
        media_probe=probe,
    )


def generate_production_report(
    report: ValidationReport,
    manifest: SceneManifest,
    config: AppConfig,
    output_html_path: Path,
) -> Path:
    """
    Generate an HTML production verification report for human review.
    """
    output_html_path.parent.mkdir(parents=True, exist_ok=True)
    probe = report.media_probe

    scenes_rows = []
    current_time = 0.0
    for s in manifest.scenes:
        s_start = current_time
        s_end = current_time + s.duration
        current_time = s_end
        scenes_rows.append(f"""
        <tr>
            <td><strong>{html.escape(s.scene_id)}</strong></td>
            <td>{html.escape(s.scene_purpose)}</td>
            <td>{s.duration:.1f}s ({s_start:.1f}s - {s_end:.1f}s)</td>
            <td><code>{html.escape(s.image_file)}</code></td>
            <td>{html.escape(s.motion_preset.value)}</td>
            <td>{html.escape(s.narration_text)}</td>
        </tr>
        """)

    status_badge = (
        '<span style="background: #238636; color: #fff; padding: 4px 12px; border-radius: 4px; font-weight: bold;">PASSED</span>'
        if report.is_valid
        else '<span style="background: #da3633; color: #fff; padding: 4px 12px; border-radius: 4px; font-weight: bold;">FAILED</span>'
    )

    error_html = "".join(f"<li style='color: #f85149;'>{html.escape(e)}</li>" for e in report.errors)
    warning_html = "".join(f"<li style='color: #d29922;'>{html.escape(w)}</li>" for e in report.warnings)

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Production Quality Report - {html.escape(config.project.series)} Ch.{config.project.chapter}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0d1117; color: #c9d1d9; padding: 24px; }}
        h1, h2 {{ color: #f0f6fc; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 16px; font-size: 13px; }}
        th, td {{ border: 1px solid #30363d; padding: 8px 12px; text-align: left; }}
        th {{ background: #161b22; color: #58a6ff; }}
        .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 16px; margin-bottom: 20px; }}
    </style>
</head>
<body>
    <h1>Production Quality Report {status_badge}</h1>
    <p>Series: <strong>{html.escape(config.project.series)}</strong> | Chapter: <strong>{config.project.chapter} ({html.escape(config.project.title)})</strong></p>

    <div class="card">
        <h2>Media Specifications</h2>
        <p><strong>File:</strong> <code>{html.escape(probe.filepath if probe else 'N/A')}</code></p>
        <p><strong>Resolution:</strong> {probe.width if probe else 'N/A'} × {probe.height if probe else 'N/A'}</p>
        <p><strong>Duration:</strong> {probe.duration_seconds if probe else 'N/A'} seconds</p>
        <p><strong>FPS:</strong> {probe.fps if probe else 'N/A'}</p>
        <p><strong>Codecs:</strong> Video: {probe.video_codec if probe else 'N/A'} | Audio: {probe.audio_codec if probe else 'N/A'}</p>
    </div>

    {'<div class="card"><h2>Errors</h2><ul>' + error_html + '</ul></div>' if report.errors else ''}
    {'<div class="card"><h2>Warnings</h2><ul>' + warning_html + '</ul></div>' if report.warnings else ''}

    <div class="card">
        <h2>Scene Breakdown</h2>
        <table>
            <thead>
                <tr>
                    <th>Scene ID</th>
                    <th>Purpose</th>
                    <th>Duration</th>
                    <th>Artwork Panel</th>
                    <th>Motion</th>
                    <th>Narration (Hindi)</th>
                </tr>
            </thead>
            <tbody>
                {''.join(scenes_rows)}
            </tbody>
        </table>
    </div>
</body>
</html>
"""
    with open(output_html_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    return output_html_path
