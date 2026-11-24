"""
Social Media & Short-Form Viral Pack Director (YouTube Community Posts + Instagram Reels & Carousels + YT Shorts).

Generates from any chapter project:
1. YouTube Community Post Image (1080x1080 1:1) + Poll & Teaser Text
2. Instagram 4-Slide Portrait Carousel Post (1080x1350 4:5) + Caption & Hashtags
3. Instagram Reel / YouTube Short 9:16 Vertical Highlight Video (1080x1920, 35-55s) using GPU acceleration
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from manhwa_studio.env_config import get_env_config
from manhwa_studio.logging_config import get_logger
from manhwa_studio.rendering.ffmpeg import get_video_encoder_args, is_nvenc_available
from manhwa_studio.schemas import SceneItem, SceneManifest
from manhwa_studio.studio_pro.series_manager import SeriesProfile
from manhwa_studio.studio_pro.thumbnail_designer import ThumbnailDesigner

logger = get_logger("manhwa_studio.pro.social")


class SocialMediaDirector:
    """Produces YouTube Community Posts, Instagram 4:5 Carousels, and 9:16 Reels/Shorts."""

    def __init__(self, profile: SeriesProfile):
        self.profile = profile
        self.thumb_designer = ThumbnailDesigner(profile)
        self.env_cfg = get_env_config()

    def _get_font(self, size: int, is_hindi: bool = False, bold: bool = True) -> ImageFont.ImageFont:
        return self.thumb_designer._get_font(size=size, is_hindi=is_hindi, bold=bold)

    def select_key_story_panels(
        self,
        artwork_dir: Path,
        manifest: SceneManifest,
        count: int = 4,
    ) -> List[Tuple[Path, Optional[SceneItem]]]:
        """
        Pick `count` distinct, visually vibrant panels across the chapter arc:
        1. Best Climax / Cover Panel
        2. Early Conflict / Setup Panel (~20% mark)
        3. Mid-Chapter Action / Escalation Panel (~55% mark)
        4. Final Cliffhanger Panel (~85% mark)
        """
        scenes = [s for s in (manifest.scenes or []) if s.image_file and (artwork_dir / s.image_file).exists()]
        if not scenes:
            all_imgs = sorted(list(artwork_dir.glob("*.webp")) + list(artwork_dir.glob("*.jpg")))
            return [(p, None) for p in all_imgs[:count]]

        # 1. Best dramatic panel for Cover (Slide 1)
        best_panel = self.thumb_designer.select_best_thumbnail_panel(artwork_dir, manifest=manifest)
        best_scene = next((s for s in scenes if (artwork_dir / s.image_file) == best_panel), scenes[-1])

        selected: List[Tuple[Path, Optional[SceneItem]]] = [(best_panel, best_scene)]
        used_files = {best_panel.name}

        # Pick 3 narrative progression beats at ~20%, ~55%, ~85% of the chapter
        n = len(scenes)
        target_indices = [
            max(0, int(n * 0.20)),
            max(0, int(n * 0.55)),
            max(0, int(n * 0.85)),
        ]
        for idx in target_indices:
            # Search around idx for an unused panel
            for offset in range(0, n):
                for candidate_idx in (idx + offset, idx - offset):
                    if 0 <= candidate_idx < n:
                        sc = scenes[candidate_idx]
                        p_file = artwork_dir / sc.image_file
                        if p_file.exists() and p_file.name not in used_files:
                            selected.append((p_file, sc))
                            used_files.add(p_file.name)
                            break
                if len(selected) >= count or (len(selected) > target_indices.index(idx) + 1):
                    break

        return selected[:count]

    def _render_framed_post_image(
        self,
        panel_path: Path,
        target_size: Tuple[int, int],
        top_badge: str = "",
        bottom_headline: str = "",
        sub_footer: str = "",
        slide_badge: str = "",
        include_overlays: bool = True,
    ) -> Image.Image:
        """
        Render a high-contrast social media card (1080x1080 1:1 or 1080x1350 4:5)
        using a dark blurred background + sharp enhanced foreground panel + bold typography.
        """
        tw, th = target_size
        with Image.open(panel_path) as raw:
            src = raw.convert("RGB")
            sw, sh = src.size

            # 1. Blurred atmospheric background filling the canvas
            bg_scale = max(tw / sw, th / sh)
            bg_w, bg_h = int(sw * bg_scale), int(sh * bg_scale)
            bg_img = src.resize((bg_w, bg_h), Image.Resampling.LANCZOS)
            left = max(0, (bg_w - tw) // 2)
            top = max(0, (bg_h - th) // 2)
            bg_crop = bg_img.crop((left, top, left + tw, top + th))
            bg_blur = bg_crop.filter(ImageFilter.GaussianBlur(radius=22))
            bg_dark = ImageEnhance.Brightness(bg_blur).enhance(0.32)

            # 2. Enhanced foreground panel fit cleanly in the center/upper-center
            enhanced_fg = self.thumb_designer.enhance_image(src)
            fg_scale = min(tw / sw, (th * 0.86) / sh)
            # If the panel aspect ratio is close to canvas, fill width
            if abs((sw / sh) - (tw / th)) < 0.38:
                fg_scale = max(tw / sw, th / sh)
                fg_w, fg_h = int(sw * fg_scale), int(sh * fg_scale)
                fg_resized = enhanced_fg.resize((fg_w, fg_h), Image.Resampling.LANCZOS)
                cx = max(0, (fg_w - tw) // 2)
                cy = max(0, int((fg_h - th) * 0.15))
                canvas = fg_resized.crop((cx, cy, cx + tw, cy + th))
            else:
                fg_w = tw
                fg_h = int(sh * (tw / sw))
                fg_resized = enhanced_fg.resize((fg_w, fg_h), Image.Resampling.LANCZOS)
                canvas = bg_dark.copy()
                if fg_h >= th:
                    cy = max(0, int((fg_h - th) * 0.12))
                    canvas = fg_resized.crop((0, cy, tw, cy + th))
                else:
                    y_off = (th - fg_h) // 2
                    canvas.paste(fg_resized, (0, y_off))

        if not include_overlays:
            return canvas

        # 3. Smooth top & bottom dark gradient vignette for legible text
        rgba = canvas.convert("RGBA")
        grad = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
        gdraw = ImageDraw.Draw(grad)

        for y in range(0, int(th * 0.18)):
            ratio = max(0.0, min(1.0, 1.0 - (y / (th * 0.18))))
            gdraw.line([(0, y), (tw, y)], fill=(0, 0, 0, int(175 * (ratio ** 1.3))))

        for y in range(int(th * 0.62), th):
            ratio = max(0.0, min(1.0, (y - th * 0.62) / (th * 0.38)))
            gdraw.line([(0, y), (tw, y)], fill=(0, 0, 0, int(235 * (ratio ** 1.25))))

        merged = Image.alpha_composite(rgba, grad).convert("RGB")
        draw = ImageDraw.Draw(merged)

        # Top-left pill badge (e.g. "NANO MACHINE • CH 21")
        if top_badge:
            b_font = self._get_font(28, bold=True)
            bx, by = 42, 38
            bbox = draw.textbbox((bx, by), top_badge, font=b_font)
            pad_x, pad_y = 16, 10
            draw.rounded_rectangle(
                [bbox[0] - pad_x, bbox[1] - pad_y, bbox[2] + pad_x, bbox[3] + pad_y],
                radius=10,
                fill=(225, 29, 72),
                outline=(255, 255, 255),
                width=2,
            )
            draw.text((bx, by), top_badge, font=b_font, fill=(255, 255, 255))

        # Top-right slide indicator (e.g. "1/4" or "SWIPE ->")
        if slide_badge:
            s_font = self._get_font(24, bold=True)
            sb = draw.textbbox((0, 0), slide_badge, font=s_font)
            sw_txt = sb[2] - sb[0]
            sx, sy = tw - sw_txt - 46, 42
            draw.rounded_rectangle(
                [sx - 14, sy - 8, sx + sw_txt + 14, sy + (sb[3] - sb[1]) + 10],
                radius=10,
                fill=(15, 23, 42),
                outline=(148, 163, 184),
                width=1,
            )
            draw.text((sx, sy), slide_badge, font=s_font, fill=(248, 250, 252))

        # Bottom headline (Hindi or English hook)
        if bottom_headline:
            has_devanagari = any("\u0900" <= ch <= "\u097f" for ch in bottom_headline)
            h_font = self._get_font(44 if has_devanagari else 42, is_hindi=has_devanagari, bold=True)
            clean_head = bottom_headline.strip()
            if len(clean_head) > 48:
                clean_head = clean_head[:45] + "..."
            hx = 44
            hy = th - 145
            draw.text(
                (hx, hy),
                clean_head,
                font=h_font,
                fill=(250, 204, 21),
                stroke_width=3,
                stroke_fill=(0, 0, 0),
            )

        # Bottom sub-footer CTA
        if sub_footer:
            f_font = self._get_font(25, bold=True)
            draw.text(
                (44, th - 72),
                sub_footer,
                font=f_font,
                fill=(255, 255, 255),
                stroke_width=2,
                stroke_fill=(0, 0, 0),
            )

        return merged

    def generate_social_copy(self, manifest: SceneManifest) -> Dict[str, Any]:
        """
        Generate high-engagement copy for:
        1. YouTube Community Post (Teaser + 4 Poll Options)
        2. Instagram Post & Reel Caption (Hinglish + Hindi + 25 Hashtags)
        3. YouTube Shorts / Instagram Reel Title & Hook
        """
        series = self.profile.series_name
        ch = manifest.chapter
        scenes = manifest.scenes or []

        # Default high-engagement fallback copy
        opening_line = scenes[0].narration_text if scenes else f"{series} Chapter {ch} ab live hai!"
        climax_line = scenes[-1].narration_text if scenes else "Kahani ek khatarnaak mod par pahunch chuki hai!"

        s_tag = series.replace(" ", "").replace(",", "")
        fallback_data = {
            "yt_community_post": (
                f"🔥 {series.upper()} — CHAPTER {ch} (FULL HINDI DUB) OUT NOW! ⚔️\n\n"
                f"{opening_line}\n\n"
                f"⚡ Is chapter me aage jo hua usne sabke hosh uda diye: \"{climax_line[:90]}...\"\n\n"
                f"👇 Neeche Poll me vote karo aur Full Video abhi dekho! 🔔"
            ),
            "yt_poll_question": f"{series} Chapter {ch} me aapko sabse khatarnaak moment kaunsa laga? 🔥",
            "yt_poll_options": [
                "⚔️ Main Hero Ka Ruthless Counter-Attack!",
                "💀 Villain / Enemy KiSabse Badi Bhool",
                "⚡ Deadly Power / System Awakening",
                "🍿 Next Chapter Waiting! (Drop Part 2 Fast)",
            ],
            "ig_caption": (
                f"He showed ZERO mercy in Chapter {ch}! 🔥⚔️ | {series} (Ch.{ch} Hindi Dub)\n\n"
                f"💬 \"{climax_line[:100]}\"\n\n"
                f"👉 Swipe through the slides & watch the full cinematic Hindi episode on our YouTube channel (Link in Bio)!\n"
                f"🔔 Follow for daily Manhwa Recaps, Murim Action & Full Marathon Movies in Hindi!\n\n"
                f"#ManhwaInHindi #{s_tag} #{s_tag}Edit #ManhwaRecap #ManhwaEdit #WebtoonIndia "
                f"#AnimeHindi #MurimManhwa #OverpoweredMC #ManhwaRecommendations #HindiDub "
                f"#ReelsIndia #AnimeReels #WebtoonEdit #SoloLeveling #NanoMachine #ActionManhwa"
            ),
            "reel_title": f"When He Unleashed His True Power! 💀🔥 | {series} Ch.{ch} #Shorts #Manhwa",
            "slide_headlines": [
                f"{series} Ch.{ch}: The Storm Begins! 🔥",
                "एक खौफनाक साज़िश और अचानक हमला!",
                "जब असली ताकत जाग उठी! ⚡",
                "Full Hindi Episode Out Now on YouTube! 🍿",
            ],
        }

        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key or not scenes:
            return fallback_data

        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            model_name = self.env_cfg.gemini_metadata_model
            sample_lines = "\n".join(
                [f"- [{s.speaker}]: {s.narration_text}" for s in scenes[:: max(1, len(scenes) // 10)][:10]]
            )
            prompt = (
                f"You are a viral YouTube & Instagram growth strategist for an Indian Manhwa/Anime channel.\n"
                f"Series: '{series}' | Chapter: {ch}\n"
                f"Key dialogue lines from this chapter:\n{sample_lines}\n\n"
                f"Return a JSON object with:\n"
                f"1. 'yt_community_post': Exciting Hinglish/Hindi YouTube Community Post announcing Chapter {ch} (3-4 short punchy paragraphs with emojis).\n"
                f"2. 'yt_poll_question': Engaging question for a YouTube Community Poll about what happens in Chapter {ch}.\n"
                f"3. 'yt_poll_options': Array of 4 short poll choices (each under 55 characters).\n"
                f"4. 'ig_caption': Viral Instagram Reels/Carousel caption in Hinglish + 20 relevant hashtags.\n"
                f"5. 'reel_title': High-CTR YouTube Shorts / Instagram Reel title under 85 characters.\n"
                f"6. 'slide_headlines': Array of 4 short punchy headlines (max 38 chars each) for a 4-slide Instagram carousel."
            )
            resp = client.models.generate_content(model=model_name, contents=prompt)
            raw = (resp.text or "").strip()
            m = re.search(r"\{.*\}", raw, flags=re.DOTALL)
            if m:
                parsed = json.loads(m.group(0))
                for k in fallback_data:
                    if k in parsed and parsed[k]:
                        fallback_data[k] = parsed[k]
        except Exception as e:
            logger.warning(f"Gemini social copy generation skipped ({e}); using smart fallback.")

        return fallback_data

    def extract_climax_window(
        self,
        manifest: SceneManifest,
        target_duration_sec: float = 45.0,
        speed: float = 1.25,
    ) -> Tuple[float, float]:
        """
        Find the best 35-52 second climax timestamp window (start_sec, duration_sec)
        in the rendered chapter video (accounting for `speed`).
        """
        scenes = manifest.scenes or []
        spd = max(0.25, float(speed or 1.0))
        if not scenes:
            return (0.0, 40.0)

        # Compute cumulative start time and score for each scene
        starts: List[float] = []
        durs: List[float] = []
        scores: List[int] = []
        t = 0.0
        action_words = ["मार", "मौत", "खून", "तलवार", "शैतान", "धमाका", "ताकत", "चेतावनी", "नैनो", "हमला"]

        for idx, sc in enumerate(scenes):
            dur = (sc.actual_audio_duration or sc.duration or 4.0) / spd
            starts.append(t)
            durs.append(dur)
            t += dur

            sc_score = 0
            txt = f"{sc.narration_text or ''} {sc.subtitle_text or ''}"
            for w in action_words:
                if w in txt:
                    sc_score += 5
            if sc.motion_preset == "impact_shake":
                sc_score += 8
            # Favor scenes in the second half (50% - 90%) of the chapter
            if 0.45 * len(scenes) <= idx <= 0.92 * len(scenes):
                sc_score += 6
            scores.append(sc_score)

        total_video_dur = t
        if total_video_dur <= target_duration_sec + 4.0:
            return (0.0, max(10.0, total_video_dur))

        # Sliding window to find the highest-scoring ~45s contiguous segment
        best_start = max(0.0, total_video_dur * 0.55)
        best_dur = min(target_duration_sec, total_video_dur - best_start)
        best_score = -1

        for i in range(len(scenes)):
            win_dur = 0.0
            win_score = 0
            for j in range(i, len(scenes)):
                win_dur += durs[j]
                win_score += scores[j]
                if win_dur >= target_duration_sec:
                    break
            if 28.0 <= win_dur <= 58.0 and win_score > best_score:
                best_score = win_score
                best_start = starts[i]
                best_dur = min(56.0, win_dur)

        return (round(best_start, 2), round(best_dur, 2))

    def build_vertical_reel_video(
        self,
        source_video: Path,
        output_reel_mp4: Path,
        manifest: SceneManifest,
        speed: float = 1.25,
        clip_duration: float = 45.0,
        start_offset: Optional[float] = None,
    ) -> Path:
        """
        Convert a 16:9 chapter video climax window into a 9:16 Vertical (1080x1920)
        Instagram Reel / YouTube Short with GPU hardware encoding.
        """
        output_reel_mp4.parent.mkdir(parents=True, exist_ok=True)
        auto_start, auto_dur = self.extract_climax_window(
            manifest, target_duration_sec=clip_duration, speed=speed
        )
        start_sec = start_offset if (start_offset is not None and start_offset >= 0) else auto_start
        dur_sec = min(175.0, max(15.0, clip_duration if clip_duration else auto_dur))

        # Reframe 1920x1080 -> 1080x1920:
        # Background fills 1080x1920 with atmospheric blur; foreground scales center artwork to 1080 width
        # so the vertical webtoon panel fills the phone screen cleanly!
        vf_complex = (
            "[0:v]split=2[vbg][vfg];"
            "[vbg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=25:5,eq=brightness=-0.18[bg];"
            "[vfg]crop=1080:1080:420:0,scale=1080:1440:force_original_aspect_ratio=increase,crop=1080:1440[fg];"
            "[bg][fg]overlay=0:(H-h)/2,"
            f"fade=t=in:st=0:d=0.35,fade=t=out:st={max(1.0, dur_sec - 0.6):.2f}:d=0.6,format=yuv420p[outv];"
            f"[0:a]afade=t=in:st=0:d=0.25,afade=t=out:st={max(1.0, dur_sec - 0.6):.2f}:d=0.6[outa]"
        )

        v_enc_args = get_video_encoder_args(quality=19, cpu_preset="fast", nvenc_preset="p4")
        cmd = [
            "ffmpeg",
            "-y",
            "-ss", f"{start_sec:.2f}",
            "-t", f"{dur_sec:.2f}",
            "-i", str(source_video),
            "-filter_complex", vf_complex,
            "-map", "[outv]",
            "-map", "[outa]",
            *v_enc_args,
            "-c:a", "aac",
            "-b:a", "192k",
            str(output_reel_mp4),
        ]

        logger.info(
            f"Rendering 9:16 Instagram Reel / YT Short ({start_sec:.1f}s -> +{dur_sec:.1f}s) from {source_video.name}..."
        )
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0 and is_nvenc_available():
            logger.warning("NVENC Reel encode failed; retrying with CPU libx264...")
            cpu_cmd = [
                "ffmpeg",
                "-y",
                "-ss", f"{start_sec:.2f}",
                "-t", f"{dur_sec:.2f}",
                "-i", str(source_video),
                "-filter_complex", vf_complex,
                "-map", "[outv]",
                "-map", "[outa]",
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "20",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "192k",
                str(output_reel_mp4),
            ]
            res = subprocess.run(cpu_cmd, capture_output=True, text=True)

        if res.returncode != 0:
            raise RuntimeError(f"Failed to build 9:16 Reel video: {res.stderr[-400:]}")

        return output_reel_mp4

    def build_complete_social_pack(
        self,
        project_dir: Path,
        manifest: SceneManifest,
        include_overlays: bool = True,
        reel_duration: float = 45.0,
        reel_start_sec: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Generate the complete YouTube Community Post + Instagram 4-Slide Carousel + 9:16 Reel Video
        and save everything into `<project_dir>/social/` and `exports/social/`.
        """
        social_dir = project_dir / "social"
        social_dir.mkdir(parents=True, exist_ok=True)
        artwork_dir = project_dir / "artwork"
        renders_dir = project_dir / "renders"

        series = self.profile.series_name
        ch = manifest.chapter

        # 1. Generate AI / smart social copy
        copy_data = self.generate_social_copy(manifest)
        headlines = copy_data.get("slide_headlines") or [
            f"{series} Ch.{ch} Out Now!",
            "A Deadly Confrontation!",
            "Unleashing True Power!",
            "Watch Full Episode on YouTube!",
        ]

        # 2. Select 4 key story panels
        selected_panels = self.select_key_story_panels(artwork_dir, manifest, count=4)
        if not selected_panels:
            raise FileNotFoundError(f"No artwork panels found in {artwork_dir}")

        # 3. Generate YouTube Community Post Image (1080x1080 1:1 Square)
        yt_post_img_path = social_dir / "youtube_community_post_1x1.jpg"
        yt_img = self._render_framed_post_image(
            panel_path=selected_panels[0][0],
            target_size=(1080, 1080),
            top_badge=f"NEW EPISODE • CHAPTER {ch}",
            bottom_headline=headlines[0],
            sub_footer=f"{series.upper()} (FULL HINDI DUB ON YOUTUBE)",
            slide_badge="YT POST",
            include_overlays=include_overlays,
        )
        yt_img.save(yt_post_img_path, quality=95)

        # 4. Generate 4-Slide Instagram Portrait Carousel (1080x1350 4:5)
        carousel_paths: List[Path] = []
        total_slides = len(selected_panels)
        for idx, (p_path, sc_item) in enumerate(selected_panels):
            slide_num = idx + 1
            out_slide = social_dir / f"ig_carousel_slide_{slide_num}.jpg"
            head = headlines[idx] if idx < len(headlines) else (sc_item.narration_text if sc_item else f"Chapter {ch}")
            footer = (
                "SWIPE FOR MORE 👉"
                if slide_num < total_slides
                else "🔥 FULL HINDI EPISODE ON YOUTUBE (LINK IN BIO)"
            )
            slide_img = self._render_framed_post_image(
                panel_path=p_path,
                target_size=(1080, 1350),
                top_badge=f"{series.upper()[:18]} • CH.{ch}",
                bottom_headline=head,
                sub_footer=footer,
                slide_badge=f"{slide_num}/{total_slides}",
                include_overlays=include_overlays,
            )
            slide_img.save(out_slide, quality=95)
            carousel_paths.append(out_slide)

        # 5. Generate 9:16 Vertical Instagram Reel / YouTube Short (if a rendered chapter video exists)
        reel_path: Optional[Path] = None
        source_mp4: Optional[Path] = None
        detected_speed = 1.25
        if renders_dir.exists():
            # Prefer 1.25x or 1.5x rendered video if present, else final_video.mp4
            for candidate_name, spd in [
                ("final_video_1.25x.mp4", 1.25),
                ("final_video_1.5x.mp4", 1.5),
                ("final_video.mp4", 1.0),
            ]:
                cand = renders_dir / candidate_name
                if cand.exists() and cand.stat().st_size > 50000:
                    source_mp4 = cand
                    detected_speed = spd
                    break

        if source_mp4:
            try:
                target_reel = social_dir / "ig_yt_reel_9x16.mp4"
                reel_path = self.build_vertical_reel_video(
                    source_video=source_mp4,
                    output_reel_mp4=target_reel,
                    manifest=manifest,
                    speed=detected_speed,
                    clip_duration=reel_duration,
                    start_offset=reel_start_sec,
                )
            except Exception as e:
                logger.warning(f"Could not generate 9:16 Reel video: {e}")

        # 6. Write formatted `social_media_kit.txt` & `social_pack.json`
        poll_opts_formatted = "\n".join([f"  [ ] {opt}" for opt in copy_data["yt_poll_options"]])
        kit_text = f"""================================================================================
         YOUTUBE COMMUNITY POST & INSTAGRAM REELS/CAROUSEL KIT
Series: {series} | Chapter: {ch}
================================================================================

📢 1. YOUTUBE COMMUNITY POST TEXT (Copy & Paste into YouTube Community Tab):
--------------------------------------------------------------------------------
{copy_data['yt_community_post']}

📊 YOUTUBE COMMUNITY POLL QUESTION:
{copy_data['yt_poll_question']}
{poll_opts_formatted}

--------------------------------------------------------------------------------
📸 2. INSTAGRAM CAROUSEL & REELS CAPTION (Copy & Paste into Instagram):
--------------------------------------------------------------------------------
{copy_data['ig_caption']}

--------------------------------------------------------------------------------
📱 3. YOUTUBE SHORTS / INSTAGRAM REEL TITLE:
--------------------------------------------------------------------------------
{copy_data['reel_title']}
================================================================================
"""
        kit_txt_path = social_dir / "social_media_kit.txt"
        kit_txt_path.write_text(kit_text, encoding="utf-8")

        meta_json_path = social_dir / "social_pack.json"
        meta_payload = {
            "series": series,
            "series_slug": self.profile.series_slug,
            "chapter": ch,
            "yt_post_image": str(yt_post_img_path),
            "ig_carousel_images": [str(p) for p in carousel_paths],
            "reel_video": str(reel_path) if reel_path and reel_path.exists() else None,
            "kit_txt": str(kit_txt_path),
            "copy": copy_data,
        }
        meta_json_path.write_text(json.dumps(meta_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        # Mirror to top-level `exports/social/<series_slug>/ch_<NNN>/` for easy access
        try:
            import shutil
            export_social = Path("exports") / "social" / self.profile.series_slug / f"chapter_{ch:03d}"
            export_social.mkdir(parents=True, exist_ok=True)
            for f in social_dir.glob("*"):
                if f.is_file():
                    shutil.copy2(f, export_social / f.name)
        except Exception:
            pass

        return meta_payload
