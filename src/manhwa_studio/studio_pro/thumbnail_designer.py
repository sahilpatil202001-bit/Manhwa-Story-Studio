"""
High-CTR YouTube Thumbnail Designer.
Automates visual contrast grading, dark gradient vignettes, character focus crops,
and bold Hindi teaser typography for maximum YouTube click-through rates.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import List, Optional, Tuple, Union

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageStat
from manhwa_studio.logging_config import get_logger
from manhwa_studio.schemas import SceneManifest
from manhwa_studio.studio_pro.series_manager import SeriesProfile

logger = get_logger("manhwa_studio.pro.thumbnail")


class ThumbnailDesigner:
    """Generates viral, high-contrast, bold-typography YouTube thumbnails."""

    def __init__(self, profile: SeriesProfile, target_size: Tuple[int, int] = (1280, 720)):
        self.profile = profile
        self.target_size = target_size

    def select_best_thumbnail_panel(
        self,
        artwork_dir: Path,
        manifest: Optional[SceneManifest] = None,
        preferred_scene_id: Optional[str] = None,
        preferred_panel: Optional[Union[str, Path]] = None,
    ) -> Path:
        """
        Intelligently select the key dramatic scene panel for thumbnail generation,
        or use a user-specified scene or panel.
        """
        # 1. Direct user preference for panel filename or path
        if preferred_panel:
            p_val = Path(preferred_panel)
            candidates = [
                p_val,
                artwork_dir / p_val.name,
                artwork_dir / f"{p_val.name}.webp",
                artwork_dir / f"{p_val.name}.jpg",
            ]
            for cand in candidates:
                if cand.exists() and cand.is_file():
                    logger.info(f"Using user-specified thumbnail panel: {cand.name}")
                    return cand

        # 2. Direct user preference for scene ID (supports 'scene_090', 'scene_90', '090', '90')
        if preferred_scene_id and manifest:
            clean_id = str(preferred_scene_id).strip().lower()
            target_ids = {clean_id}
            if clean_id.isdigit():
                num = int(clean_id)
                target_ids.update({f"scene_{num:03d}", f"scene_{num:02d}", f"scene_{num}"})
            elif clean_id.startswith("scene_"):
                num_part = clean_id.replace("scene_", "")
                if num_part.isdigit():
                    num = int(num_part)
                    target_ids.update({f"scene_{num:03d}", f"scene_{num:02d}", f"scene_{num}"})

            for s in manifest.scenes:
                if s.scene_id in target_ids and s.image_file:
                    c = artwork_dir / s.image_file
                    if c.exists():
                        logger.info(f"Using user-specified scene '{s.scene_id}' panel: {c.name}")
                        return c

        # 3. Automatic intelligent scoring based on dramatic screenplay moments and visual quality
        if manifest and manifest.scenes:
            scored_scenes = []
            keywords = [
                "पकड़", "गला", "दम घुटने", "चेओन मा", "डेमन", "demon", "शैतान",
                "वार", "खून", "कत्ल", "मौत", "हत्या", "रहस्य", "अवतार", "सच",
                "ताकत", "चीख", "जाल", "कैद", "आंखें", "तलवार",
            ]
            for s in manifest.scenes:
                if not s.image_file:
                    continue
                panel_file = artwork_dir / s.image_file
                if not panel_file.exists():
                    continue

                score = 0
                text = f"{s.narration_text or ''} {s.subtitle_text or ''}".lower()
                for kw in keywords:
                    if kw in text:
                        score += 8

                if s.scene_purpose in ["climax", "revelation", "action"]:
                    score += 10
                if s.motion_preset == "impact_shake":
                    score += 6

                # Inspect image visual quality: penalize washed-out dialogue speech bubbles
                try:
                    with Image.open(panel_file) as p_img:
                        hsv_img = p_img.convert("HSV")
                        stat = ImageStat.Stat(hsv_img)
                        s_mean = stat.mean[1]  # Saturation
                        v_mean = stat.mean[2]  # Brightness / Value

                        # If panel is washed-out white/grey (typical of text speech bubbles)
                        if v_mean > 150 and s_mean < 60:
                            score -= 20
                        elif s_mean > 80:
                            score += 12  # Rich vibrant colors (character artwork, dramatic background)
                except Exception:
                    pass

                # Favor high-detail illustration panels over tiny fragments
                try:
                    score += min(panel_file.stat().st_size // 25000, 10)
                except Exception:
                    pass

                scored_scenes.append((score, panel_file))

            if scored_scenes:
                scored_scenes.sort(key=lambda x: x[0], reverse=True)
                selected = scored_scenes[0][1]
                logger.info(f"Auto-selected most dramatic scene panel for thumbnail: {selected.name} (score: {scored_scenes[0][0]})")
                return selected

        # 4. Fallback: select largest artwork panel in the directory
        panels = sorted(
            list(artwork_dir.glob("*.webp")) + list(artwork_dir.glob("*.jpg")),
            key=lambda p: p.stat().st_size,
            reverse=True,
        )
        if panels:
            return panels[0]

        raise FileNotFoundError(f"No artwork images found in {artwork_dir}")

    def enhance_image(self, img: Image.Image) -> Image.Image:
        """Apply vibrant anime grading: contrast, saturation, and sharp details."""
        # 1. Boost color saturation
        sat_enhancer = ImageEnhance.Color(img)
        img = sat_enhancer.enhance(1.28)

        # 2. Boost contrast
        con_enhancer = ImageEnhance.Contrast(img)
        img = con_enhancer.enhance(1.22)

        # 3. Boost sharpness
        shp_enhancer = ImageEnhance.Sharpness(img)
        img = shp_enhancer.enhance(1.25)

        return img

    def add_vignette_and_dark_gradient(self, img: Image.Image) -> Image.Image:
        """Add dark bottom and side gradient so text is razor-sharp and high contrast."""
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        w, h = img.size

        # Bottom dark gradient (lower 40% of the image)
        for y in range(int(h * 0.55), h):
            ratio = max(0.0, min(1.0, (y - h * 0.55) / (h * 0.45)))
            alpha = int(220 * (ratio ** 1.3))
            draw.line([(0, y), (w, y)], fill=(0, 0, 0, alpha))

        # Left dark gradient for side badges
        for x in range(0, int(w * 0.45)):
            ratio = max(0.0, min(1.0, 1.0 - (x / (w * 0.45))))
            alpha = int(140 * ratio)
            draw.line([(x, 0), (x, h)], fill=(0, 0, 0, alpha))

        base_rgba = img.convert("RGBA")
        combined = Image.alpha_composite(base_rgba, overlay)
        return combined.convert("RGB")

    def _get_font(self, size: int, is_hindi: bool = False, bold: bool = True) -> ImageFont.ImageFont:
        """Load system TrueType font supporting English badges or Devanagari Hindi."""
        if is_hindi:
            hindi_fonts = [
                "C:\\Windows\\Fonts\\mangalb.ttf",
                "C:\\Windows\\Fonts\\mangal.ttf",
                "C:\\Windows\\Fonts\\utsaahb.ttf",
                "C:\\Windows\\Fonts\\utsaah.ttf",
                "mangalb.ttf",
                "mangal.ttf",
            ]
            for fn in hindi_fonts:
                try:
                    return ImageFont.truetype(fn, size)
                except Exception:
                    continue

        latin_fonts = [
            "C:\\Windows\\Fonts\\arialbd.ttf" if bold else "C:\\Windows\\Fonts\\arial.ttf",
            "arialbd.ttf" if bold else "arial.ttf",
            "C:\\Windows\\Fonts\\seguiemj.ttf",
        ]
        for fn in latin_fonts:
            try:
                return ImageFont.truetype(fn, size)
            except Exception:
                continue
        return ImageFont.load_default()

    def generate_pro_thumbnail(
        self,
        artwork_dir: Path,
        manifest: SceneManifest,
        output_file: Path,
        hindi_hook: Optional[str] = None,
        custom_panel: Optional[Path] = None,
        custom_scene_id: Optional[str] = None,
        include_caption: bool = False,
    ) -> Path:
        """
        Build an ultra-engaging, high-CTR YouTube thumbnail with character focus
        from a specific dramatic scene. Captions/text are omitted by default for pure clean artwork.
        """
        source_panel = self.select_best_thumbnail_panel(
            artwork_dir,
            manifest=manifest,
            preferred_scene_id=custom_scene_id,
            preferred_panel=custom_panel,
        )
        logger.info(f"Generating Pro YouTube thumbnail using panel: {source_panel.name} (include_caption={include_caption})")

        with Image.open(source_panel) as raw_img:
            # Crop/Fit into 16:9 aspect ratio centered
            w, h = raw_img.size
            target_w, target_h = self.target_size
            target_aspect = target_w / target_h
            current_aspect = w / h

            if current_aspect > target_aspect:
                # Image is wider: crop sides
                new_w = int(h * target_aspect)
                left = (w - new_w) // 2
                cropped = raw_img.crop((left, 0, left + new_w, h))
            else:
                # Image is taller: take top-to-middle portion (character face/upper body)
                new_h = int(w / target_aspect)
                top = int(h * 0.05) if h > new_h * 1.2 else (h - new_h) // 2
                cropped = raw_img.crop((0, top, w, min(h, top + new_h)))

            resized = cropped.resize((target_w, target_h), Image.Resampling.LANCZOS)

        # 1. Apply vibrant anime grading
        final_img = self.enhance_image(resized)

        # 2. Add text badges and Hindi teaser captions only if explicitly requested
        if include_caption:
            final_img = self.add_vignette_and_dark_gradient(final_img)
            draw = ImageDraw.Draw(final_img)

            # Add Top Chapter Badge
            badge_text = f"CHAPTER {manifest.chapter}"
            badge_font = self._get_font(32, bold=True)
            bx, by = 48, 44
            bbox = draw.textbbox((bx, by), badge_text, font=badge_font)
            pad = 12
            draw.rounded_rectangle(
                [bbox[0] - pad, bbox[1] - pad + 2, bbox[2] + pad, bbox[3] + pad - 2],
                radius=8,
                fill=(220, 20, 40),
                outline=(255, 255, 255),
                width=2,
            )
            draw.text((bx, by), badge_text, font=badge_font, fill=(255, 255, 255))

            # Add Series Watermark
            tag_text = self.profile.series_name.upper()
            if len(tag_text) > 22:
                tag_text = tag_text[:20] + "..."
            tag_font = self._get_font(24, bold=True)
            t_bbox = draw.textbbox((0, 0), tag_text, font=tag_font)
            tx = target_w - (t_bbox[2] - t_bbox[0]) - 50
            draw.text((tx, by + 4), tag_text, font=tag_font, fill=(240, 240, 240), stroke_width=2, stroke_fill=(0, 0, 0))

            # Add Bottom Bold Hindi Teaser Text
            teaser_text = hindi_hook or "800 साल पुराना शैतान जाग उठा!"
            if len(teaser_text) > 36:
                teaser_text = teaser_text[:33] + "..."

            hook_font = self._get_font(52, is_hindi=True, bold=True)
            hx = 48
            hy = target_h - 130

            for ox in [-4, -3, 3, 4]:
                for oy in [-4, -3, 3, 4]:
                    draw.text((hx + ox, hy + oy), teaser_text, font=hook_font, fill=(0, 0, 0))

            draw.text((hx, hy), teaser_text, font=hook_font, fill=(255, 225, 0))

            # Sub-hook
            sub_text = manifest.title or f"{self.profile.series_name} - Ch.{manifest.chapter}"
            sub_font = self._get_font(26, bold=True)
            draw.text((hx, hy + 66), sub_text, font=sub_font, fill=(255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0))

            # Outer Border
            draw.rectangle([0, 0, target_w - 1, target_h - 1], outline=(255, 215, 0), width=3)

        output_file.parent.mkdir(parents=True, exist_ok=True)
        final_img.save(output_file, quality=95)
        logger.info(f"Successfully saved thumbnail at: {output_file}")
        return output_file
