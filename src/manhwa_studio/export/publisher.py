"""
Publishing and packaging engine: generates organized videos, high-CTR YouTube thumbnails,
and formatted YouTube metadata text files (Title, Description, Tags) ready for upload.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from manhwa_studio.logging_config import get_logger
from manhwa_studio.schemas import SceneManifest

logger = get_logger("manhwa_studio.export.publisher")


def get_system_font(font_names: List[str], size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Find the first available system font or return default."""
    for name in font_names:
        font_path = Path(f"C:/Windows/Fonts/{name}")
        if font_path.exists():
            try:
                return ImageFont.truetype(str(font_path), size)
            except Exception:
                continue
    return ImageFont.load_default()


def generate_youtube_thumbnail(
    artwork_path: Path,
    series_name: str,
    chapter: int,
    part: int,
    hook_text: str,
    output_path: Path,
    aspect: str = "9:16",
) -> Path:
    """
    Generate an eye-catching, high-CTR YouTube thumbnail:
    - 9:16 vertical cover (1080x1920) for YouTube Shorts, Reels, and TikTok
    - Enhanced contrast/vibrancy with stylized blurred background and bold typography
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    raw = Image.open(artwork_path).convert("RGB")
    w, h = raw.size

    if aspect == "9:16":
        target_w, target_h = 1080, 1920
    else:
        target_w, target_h = 1280, 720

    arr = np.array(raw)

    # 1. Background layer: blurred and darkened
    sf_bg = max(target_w / w, target_h / h)
    bg = cv2.resize(arr, (int(w * sf_bg), int(h * sf_bg)))
    x0 = max(0, (bg.shape[1] - target_w) // 2)
    y0 = max(0, (bg.shape[0] - target_h) // 2)
    bg_cropped = bg[y0 : y0 + target_h, x0 : x0 + target_w]
    if bg_cropped.shape[0] < target_h or bg_cropped.shape[1] < target_w:
        bg_cropped = cv2.resize(bg_cropped, (target_w, target_h))

    bg_blurred = cv2.GaussianBlur(bg_cropped, (51, 51), 35)
    bg_dimmed = (bg_blurred * 0.35).astype(np.uint8)

    # 2. Foreground: centered panel
    if aspect == "9:16":
        sf_fg = target_w / w
        fg_max_h = int(target_h * 0.78)
        fg_scaled_h = int(h * sf_fg)
        fg_scaled = cv2.resize(arr, (target_w, fg_scaled_h))
        if fg_scaled.shape[0] > fg_max_h:
            fg_scaled = fg_scaled[:fg_max_h, :]

        # Boost contrast and saturation slightly for pop
        fg_pil = Image.fromarray(fg_scaled)
        fg_pil = ImageEnhance.Contrast(fg_pil).enhance(1.15)
        fg_pil = ImageEnhance.Color(fg_pil).enhance(1.15)
        fg_final = np.array(fg_pil)

        canvas = bg_dimmed.copy()
        y_pos = (target_h - fg_final.shape[0]) // 2
        canvas[y_pos : y_pos + fg_final.shape[0], :] = fg_final
    else:
        # Landscape 16:9
        sf_fg = target_h / h
        fg_scaled_w = int(w * sf_fg)
        fg_scaled = cv2.resize(arr, (fg_scaled_w, target_h))
        canvas = bg_dimmed.copy()
        x_pos = (target_w - fg_scaled.shape[1]) // 2
        canvas[:, x_pos : x_pos + fg_scaled.shape[1]] = fg_scaled

    # 3. Typography and badges
    overlay = Image.fromarray(canvas)
    draw = ImageDraw.Draw(overlay, "RGBA")

    if aspect == "9:16":
        # Top header banner
        draw.rectangle([0, 0, target_w, 230], fill=(0, 0, 0, 190))
        # Bottom footer banner
        draw.rectangle([0, target_h - 220, target_w, target_h], fill=(0, 0, 0, 210))

        font_large = get_system_font(["impact.ttf", "arialbd.ttf"], 74)
        font_med = get_system_font(["arialbd.ttf", "impact.ttf"], 44)
        font_hook = get_system_font(["impact.ttf", "arialbd.ttf"], 54)

        # Series Title
        draw.text((target_w // 2, 60), series_name.upper(), font=font_med, fill=(255, 215, 0), anchor="mm")
        # Chapter / Part Badge
        badge_text = f"CHAPTER {chapter} • PART {part}"
        draw.text((target_w // 2, 145), badge_text, font=font_large, fill=(255, 255, 255), anchor="mm")
        # Hook bottom
        draw.text((target_w // 2, target_h - 110), hook_text.upper(), font=font_hook, fill=(255, 55, 55), anchor="mm")
    else:
        # Landscape
        draw.rectangle([0, 0, target_w, 140], fill=(0, 0, 0, 190))
        draw.rectangle([0, target_h - 130, target_w, target_h], fill=(0, 0, 0, 210))
        font_large = get_system_font(["impact.ttf", "arialbd.ttf"], 58)
        font_med = get_system_font(["arialbd.ttf", "impact.ttf"], 36)
        draw.text((target_w // 2, 40), series_name.upper(), font=font_med, fill=(255, 215, 0), anchor="mm")
        draw.text((target_w // 2, 95), f"CHAPTER {chapter} • PART {part}", font=font_large, fill=(255, 255, 255), anchor="mm")
        draw.text((target_w // 2, target_h - 65), hook_text.upper(), font=font_large, fill=(255, 55, 55), anchor="mm")

    overlay.save(output_path, quality=95)
    logger.info(f"Generated YouTube thumbnail: {output_path.name}")
    return output_path


def generate_youtube_metadata_file(
    series_name: str,
    chapter: int,
    part: int,
    total_parts: int,
    manifest: SceneManifest,
    output_file: Path,
) -> Path:
    """
    Generate YouTube-ready metadata (Title, Description with timestamps, and Tags)
    formatted specifically for YouTube Shorts / Video uploads.
    """
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # 1. Title
    if part == 1:
        yt_title = f"{manifest.title} | {series_name} Ch.{chapter} Part {part} #Shorts"
    else:
        yt_title = f"{manifest.title} | {series_name} Ch.{chapter} Finale Part {part} #Shorts"

    if len(yt_title) > 95:
        yt_title = f"{series_name} Ch.{chapter} Part {part}: {manifest.title} #Shorts"

    # 2. Timestamps from manifest scenes
    timestamps_lines = []
    current_sec = 0.0
    for i, sc in enumerate(manifest.scenes):
        mins = int(current_sec // 60)
        secs = int(current_sec % 60)
        time_str = f"{mins}:{secs:02d}"
        beat_name = sc.scene_purpose.replace("_", " ").title()
        timestamps_lines.append(f"{time_str} - Beat {i+1} ({beat_name})")
        current_sec += sc.duration

    timestamps_block = "\n".join(timestamps_lines[:7])  # top 7 key beats

    # 3. Tags
    series_clean = series_name.lower().replace(",", "")
    tags = [
        series_clean,
        f"{series_clean} chapter {chapter}",
        f"{series_clean} chapter {chapter} part {part}",
        f"{series_clean} in hindi",
        "nano machine prequel",
        "mok gyeongwun",
        "cheon ma",
        "first heavenly demon",
        "manhwa recap hindi",
        "webtoon recap hindi",
        "manhwa explained in hindi",
        "best action manhwa",
        "top murim manhwa",
        "overpowered mc manhwa",
        "anime recap hindi",
        "youtube shorts manhwa",
    ]
    tags_str = ", ".join(tags)

    # 4. Description
    summary_text = (
        f"800 years before Nano Machine, the legendary saga of Mok Gyeongwun begins! "
        f"Watch the dark, thrilling origin story of the First Heavenly Demon as he faces "
        f"deadly assassins, treacherous plots, and awakens a terrifying ancient power."
    )

    content = f"""================================================================================
YOUTUBE VIDEO PUBLISHING METADATA
Series: {series_name} | Chapter {chapter} (Part {part} of {total_parts})
================================================================================

[VIDEO TITLE]
{yt_title}

--------------------------------------------------------------------------------
[DESCRIPTION]
{summary_text}

🔥 Series: {series_name} (괴력난신)
📖 Chapter: {chapter} (Part {part}/{total_parts})
🎧 Language: Hindi Commentary / Story Recap
⚡ {"Watch Part 2 for the ultimate conclusion!" if part == 1 else "Thanks for watching! Subscribe for Chapter 2!"}

⏱️ TIMESTAMPS:
{timestamps_block}

📌 HASHTAGS:
#manhwa #nanomachine #mystmightmayhem #manhwarecap #webtoon #hindi #shorts #actionmanhwa #murim

--------------------------------------------------------------------------------
[TAGS (Copy & Paste into YouTube Studio)]
{tags_str}

================================================================================
Generated automatically by Manhwa Story Studio
"""

    output_file.write_text(content, encoding="utf-8")
    logger.info(f"Generated YouTube metadata file: {output_file.name}")
    return output_file


def package_chapter_part(
    project_dir: Path,
    chapter: int,
    part: int,
    total_parts: int,
    rendered_mp4: Path,
    manifest: SceneManifest,
    artwork_dir: Path,
    base_export_dir: Path,
) -> Dict[str, Path]:
    """
    Package rendered video, thumbnail, and metadata into organized chapter-wise directories:
    - exports/videos/chapter_{chapter}/ch{chapter} - part {part}.mp4
    - exports/thumbnails/chapter_{chapter}/ch{chapter} - part {part}.jpg
    - exports/metadata/chapter_{chapter}/ch{chapter} - part {part}.txt
    """
    ch_folder = f"chapter_{chapter}"
    videos_dir = base_export_dir / "videos" / ch_folder
    thumbs_dir = base_export_dir / "thumbnails" / ch_folder
    meta_dir = base_export_dir / "metadata" / ch_folder

    videos_dir.mkdir(parents=True, exist_ok=True)
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)

    file_stem = f"ch{chapter} - part {part}"

    # 1. Video export
    dest_video = videos_dir / f"{file_stem}.mp4"
    if rendered_mp4.exists():
        shutil.copy2(rendered_mp4, dest_video)
        logger.info(f"Exported video to: {dest_video}")
    else:
        dest_video = rendered_mp4

    # 2. Pick best thumbnail panel
    # Choose climax or dramatic hook panel from manifest
    candidate_panels = [sc.image_file for sc in manifest.scenes if sc.image_file]
    if part == 1:
        # Prefer spirit herb or wounded master
        preferred = ["panel_015.webp", "panel_016.webp", "panel_001.webp", "panel_050.webp"]
    else:
        # Prefer psychotic demonic smile or counter-attack
        preferred = ["panel_198.webp", "panel_130.webp", "panel_175.webp", "panel_095.webp"]

    chosen_panel = candidate_panels[-1] if candidate_panels else "panel_001.webp"
    for p in preferred:
        if (artwork_dir / p).exists():
            chosen_panel = p
            break

    thumb_panel_path = artwork_dir / chosen_panel

    # Hook text for thumbnail
    hook_text = "BEFORE THE DEMON" if part == 1 else "THE DEMON AWAKES!"

    # 3. Generate Thumbnail
    dest_thumb = thumbs_dir / f"{file_stem}.jpg"
    generate_youtube_thumbnail(
        artwork_path=thumb_panel_path,
        series_name=manifest.series,
        chapter=chapter,
        part=part,
        hook_text=hook_text,
        output_path=dest_thumb,
        aspect="9:16",
    )

    # Also generate 16:9 landscape version for standard YouTube player
    dest_thumb_landscape = thumbs_dir / f"{file_stem}_landscape.jpg"
    generate_youtube_thumbnail(
        artwork_path=thumb_panel_path,
        series_name=manifest.series,
        chapter=chapter,
        part=part,
        hook_text=hook_text,
        output_path=dest_thumb_landscape,
        aspect="16:9",
    )

    # 4. Generate Metadata TXT
    dest_meta = meta_dir / f"{file_stem}.txt"
    generate_youtube_metadata_file(
        series_name=manifest.series,
        chapter=chapter,
        part=part,
        total_parts=total_parts,
        manifest=manifest,
        output_file=dest_meta,
    )

    return {
        "video": dest_video,
        "thumbnail": dest_thumb,
        "thumbnail_landscape": dest_thumb_landscape,
        "metadata": dest_meta,
    }
