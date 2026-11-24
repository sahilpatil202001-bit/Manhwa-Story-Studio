"""
Instagram Video Compatibility Exporter & Publishing Guide Generator.

Converts 16:9 chapter renders or long-form marathon movies into Instagram-compatible
1080x1920 (9:16 vertical) MP4s, automatically splitting videos that exceed Instagram's
duration limits (e.g. <=18 min for standard Reels/Feed, or <=2.75 min for Reels Explore reach),
and generates a ready-to-paste INSTAGRAM_PUBLISHING_GUIDE.md with YouTube & Instagram CTAs.
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from manhwa_studio.logging_config import get_logger
from manhwa_studio.rendering.ffmpeg import (
    get_ffmpeg_path,
    get_ffprobe_path,
    get_video_encoder_args,
    is_nvenc_available,
)

logger = get_logger("manhwa_studio.pro.instagram")


def _resolve_ffmpeg() -> str:
    try:
        return get_ffmpeg_path()
    except FileNotFoundError:
        win_fallback = Path(r"C:\ffmpeg\bin\ffmpeg.exe")
        if win_fallback.exists():
            return str(win_fallback)
        raise


def _resolve_ffprobe() -> Optional[str]:
    try:
        return get_ffprobe_path()
    except FileNotFoundError:
        win_fallback = Path(r"C:\ffmpeg\bin\ffprobe.exe")
        if win_fallback.exists():
            return str(win_fallback)
        return None


def probe_video_info(video_path: Path) -> Tuple[int, int, float]:
    """Return (width, height, duration_sec) for an MP4 video."""
    ffprobe = _resolve_ffprobe()
    if ffprobe:
        try:
            cmd = [
                ffprobe,
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-show_entries", "format=duration",
                "-of", "csv=s=x:p=0",
                str(video_path),
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            lines = [ln.strip() for ln in res.stdout.strip().splitlines() if ln.strip()]
            w, h = 1920, 1080
            dur = 0.0
            for ln in lines:
                if "x" in ln:
                    parts = ln.split("x")
                    w, h = int(parts[0]), int(parts[1])
                else:
                    dur = float(ln)
            if dur > 0:
                return w, h, dur
        except Exception:
            pass

    # Fallback to OpenCV if ffprobe is unavailable
    try:
        import cv2
        cap = cv2.VideoCapture(str(video_path))
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1920
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1080
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
        cap.release()
        return w, h, float(frames / fps) if fps > 0 else 0.0
    except Exception:
        return 1920, 1080, 0.0


def build_aspect_filter(src_w: int, src_h: int, aspect: str = "9x16") -> Optional[str]:
    """
    Build the FFmpeg -vf filter string for Instagram compatibility.
    For 16:9 manhwa renders (e.g. 1920x1080) where the vertical panel is centered,
    crops the centered 9:16 strip and scales to 1080x1920 with SAR 1:1.
    """
    if aspect != "9x16":
        return None

    if src_w > src_h:
        crop_w = int(round(src_h * 9 / 16))
        if crop_w % 2 != 0:
            crop_w += 1
        crop_w = min(crop_w, src_w)
        crop_x = max(0, (src_w - crop_w) // 2)
        return f"crop={crop_w}:{src_h}:{crop_x}:0,scale=1080:1920:flags=lanczos,setsar=1,format=yuv420p"

    return "scale=1080:1920:flags=lanczos,setsar=1,format=yuv420p"


def find_chapter_video(chapter_dir: Path, speed: float = 1.25) -> Optional[Path]:
    """Locate the best rendered video for a chapter matching the requested speed."""
    renders_dir = chapter_dir / "renders"
    exports_dir = chapter_dir / "exports"
    speed_tag = f"{speed:g}"

    candidates: List[Path] = []
    if abs(speed - 1.0) < 0.01:
        candidates.append(renders_dir / "final_video.mp4")
    else:
        candidates.extend([
            renders_dir / f"final_video_{speed_tag}x.mp4",
            renders_dir / "final_video_1.25x.mp4",
            renders_dir / "final_video.mp4",
        ])
    if exports_dir.exists():
        candidates.extend(sorted(exports_dir.glob("*_pro.mp4")))

    for c in candidates:
        if c.exists() and c.stat().st_size > 50_000:
            return c
    return None


class InstagramExporter:
    """Exports chapters or marathon videos into Instagram-compatible 9:16 MP4s + Guide."""

    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = (root_dir or Path(".")).resolve()
        self.projects_dir = self.root_dir / "data" / "projects"
        self.exports_dir = self.root_dir / "exports" / "instagram"

    def _transcode_segment(
        self,
        input_video: Path,
        output_video: Path,
        vf_filter: Optional[str],
        start_sec: Optional[float] = None,
        duration_sec: Optional[float] = None,
        prefer_cpu: bool = True,
    ) -> Path:
        ffmpeg_exe = _resolve_ffmpeg()
        output_video.parent.mkdir(parents=True, exist_ok=True)

        base_in: List[str] = [ffmpeg_exe, "-y"]
        if start_sec is not None and start_sec > 0:
            base_in.extend(["-ss", f"{start_sec:.2f}"])
        if duration_sec is not None and duration_sec > 0:
            base_in.extend(["-t", f"{duration_sec:.2f}"])
        base_in.extend(["-i", str(input_video)])

        vf_args = ["-vf", vf_filter] if vf_filter else []
        audio_args = ["-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "128k", "-movflags", "+faststart"]

        if not prefer_cpu and is_nvenc_available():
            v_args = get_video_encoder_args(quality=19, cpu_preset="veryfast", nvenc_preset="p4")
            cmd = [*base_in, *vf_args, *v_args, *audio_args, str(output_video)]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode == 0:
                return output_video
            logger.warning("GPU encode failed, falling back to CPU libx264...")

        if vf_filter:
            v_cpu = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-threads", "4"]
        else:
            v_cpu = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-threads", "4", "-pix_fmt", "yuv420p"]

        cmd = [*base_in, *vf_args, *v_cpu, *audio_args, str(output_video)]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"FFmpeg Instagram export failed: {res.stderr[-500:]}")
        return output_video

    def _convert_single_source(
        self,
        source_video: Path,
        output_stem_path: Path,
        max_minutes: float = 18.0,
        aspect: str = "9x16",
        prefer_cpu: bool = False,
    ) -> List[Dict[str, Any]]:
        src_w, src_h, dur_sec = probe_video_info(source_video)
        vf_filter = build_aspect_filter(src_w, src_h, aspect=aspect)
        max_sec = max_minutes * 60.0 if max_minutes > 0 else 0.0

        results: List[Dict[str, Any]] = []
        if max_sec > 0 and dur_sec > max_sec + 2.0:
            num_parts = math.ceil(dur_sec / max_sec)
            for idx in range(num_parts):
                start = idx * max_sec
                seg_dur = min(max_sec, dur_sec - start)
                if seg_dur < 3.0:
                    continue
                out_file = output_stem_path.parent / f"{output_stem_path.stem}_part{idx + 1:02d}{output_stem_path.suffix}"
                logger.info(f"Exporting {out_file.name} ({start:.1f}s -> +{seg_dur:.1f}s)...")
                self._transcode_segment(
                    source_video, out_file, vf_filter,
                    start_sec=start, duration_sec=seg_dur, prefer_cpu=prefer_cpu,
                )
                results.append({
                    "filename": out_file.name,
                    "path": str(out_file.relative_to(self.root_dir)).replace("\\", "/"),
                    "duration_sec": round(seg_dur, 1),
                    "start_sec": round(start, 1),
                    "end_sec": round(start + seg_dur, 1),
                    "part": idx + 1,
                    "total_parts": num_parts,
                })
        else:
            logger.info(f"Exporting {output_stem_path.name} ({dur_sec/60:.2f} min)...")
            self._transcode_segment(
                source_video, output_stem_path, vf_filter, prefer_cpu=prefer_cpu,
            )
            results.append({
                "filename": output_stem_path.name,
                "path": str(output_stem_path.relative_to(self.root_dir)).replace("\\", "/"),
                "duration_sec": round(dur_sec, 1),
                "start_sec": 0.0,
                "end_sec": round(dur_sec, 1),
                "part": 1,
                "total_parts": 1,
            })

        return results

    def export_chapters(
        self,
        series_slug: str,
        chapter_start: int,
        chapter_end: int,
        speed: float = 1.25,
        max_minutes: float = 18.0,
        aspect: str = "9x16",
        yt_handle: str = "",
        ig_handle: str = "",
        prefer_cpu: bool = False,
    ) -> Dict[str, Any]:
        """Convert rendered chapters in [chapter_start, chapter_end] to Instagram-compatible MP4s."""
        series_dir = self.projects_dir / series_slug
        if not series_dir.exists():
            raise FileNotFoundError(f"Series directory not found: {series_dir}")

        out_dir = self.exports_dir / series_slug
        out_dir.mkdir(parents=True, exist_ok=True)
        speed_tag = f"{speed:g}x"
        aspect_tag = "9x16" if aspect == "9x16" else "16x9"

        exported_items: List[Dict[str, Any]] = []
        for ch in range(chapter_start, chapter_end + 1):
            ch_dir = series_dir / f"chapter_{ch:03d}"
            src_video = find_chapter_video(ch_dir, speed=speed)
            if not src_video:
                logger.warning(f"No rendered video found for {series_slug} Ch.{ch} (skipping).")
                continue

            out_path = out_dir / f"{series_slug}_ch{ch:03d}_{speed_tag}_{aspect_tag}.mp4"
            items = self._convert_single_source(
                src_video, out_path, max_minutes=max_minutes, aspect=aspect, prefer_cpu=prefer_cpu,
            )
            for it in items:
                it["chapter"] = ch
            exported_items.extend(items)

        if not exported_items:
            raise RuntimeError(f"No rendered chapter videos found for {series_slug} Ch.{chapter_start}–{chapter_end}.")

        guide_path = self.write_publishing_guide(
            out_dir=out_dir,
            series_slug=series_slug,
            exported_items=exported_items,
            yt_handle=yt_handle,
            ig_handle=ig_handle,
        )
        return {
            "output_dir": str(out_dir.relative_to(self.root_dir)).replace("\\", "/"),
            "guide_path": str(guide_path.relative_to(self.root_dir)).replace("\\", "/"),
            "exported_files": exported_items,
        }

    def export_marathon(
        self,
        marathon_path: Path,
        series_slug: Optional[str] = None,
        max_minutes: float = 18.0,
        aspect: str = "9x16",
        yt_handle: str = "",
        ig_handle: str = "",
        prefer_cpu: bool = False,
    ) -> Dict[str, Any]:
        """Split a compiled marathon MP4 into Instagram-compatible 9:16 parts + Guide."""
        src = marathon_path if marathon_path.is_absolute() else (self.root_dir / marathon_path)
        if not src.exists():
            raise FileNotFoundError(f"Marathon video not found: {src}")

        folder_slug = series_slug or src.stem
        out_dir = self.exports_dir / folder_slug
        out_dir.mkdir(parents=True, exist_ok=True)
        aspect_tag = "9x16" if aspect == "9x16" else "16x9"
        out_stem = out_dir / f"{src.stem}_{aspect_tag}.mp4"

        exported_items = self._convert_single_source(
            src, out_stem, max_minutes=max_minutes, aspect=aspect, prefer_cpu=prefer_cpu,
        )
        ts_file = src.with_suffix(".timestamps.txt")
        guide_path = self.write_publishing_guide(
            out_dir=out_dir,
            series_slug=folder_slug,
            exported_items=exported_items,
            yt_handle=yt_handle,
            ig_handle=ig_handle,
            marathon_timestamps_path=ts_file if ts_file.exists() else None,
        )
        return {
            "output_dir": str(out_dir.relative_to(self.root_dir)).replace("\\", "/"),
            "guide_path": str(guide_path.relative_to(self.root_dir)).replace("\\", "/"),
            "exported_files": exported_items,
        }

    def _infer_series_meta(self, slug_or_folder: str) -> Tuple[str, str, str]:
        """Return (resolved_series_slug, pretty_series_name, genre) from configs/series_profiles."""
        profiles_dir = self.root_dir / "configs" / "series_profiles"
        best_slug = slug_or_folder
        if profiles_dir.exists():
            # Exact match first, then prefix match (e.g. marathon stem starting with series_slug)
            candidates = sorted(profiles_dir.glob("*.yaml"), key=lambda p: len(p.stem), reverse=True)
            for pf in candidates:
                if slug_or_folder == pf.stem or slug_or_folder.startswith(pf.stem + "_"):
                    best_slug = pf.stem
                    try:
                        data = yaml.safe_load(pf.read_text(encoding="utf-8")) or {}
                        return (
                            best_slug,
                            str(data.get("series_name") or best_slug.replace("_", " ").title()),
                            str(data.get("genre") or "action"),
                        )
                    except Exception:
                        break
        return best_slug, best_slug.replace("_", " ").title(), "action"

    def _genre_hashtags(self, genre: str) -> List[str]:
        g = (genre or "").lower()
        mapping = {
            "murim": ["#MurimManhwa", "#MartialArtsManhwa", "#CultivationManhwa", "#SwordManhwa"],
            "system": ["#SystemManhwa", "#HunterManhwa", "#SoloLeveling", "#DungeonManhwa"],
            "fantasy": ["#FantasyManhwa", "#IsekaiManhwa", "#MagicManhwa", "#OverpoweredMC"],
            "romance": ["#RomanceManhwa", "#OtomeIsekai", "#VillainessManhwa", "#ManhwaLove"],
            "dark": ["#DarkFantasyManhwa", "#RevengeManhwa", "#OverpoweredMC", "#AntiHero"],
        }
        for key, tags in mapping.items():
            if key in g:
                return tags
        return ["#ActionManhwa", "#OverpoweredMC", "#ManhwaRecommendations", "#WebtoonEdit"]

    def _read_chapter_hook(self, series_slug: str, chapter: int) -> Tuple[str, str]:
        """Extract a chapter title & short teaser from existing YouTube kit if available."""
        ch_dir = self.projects_dir / series_slug / f"chapter_{chapter:03d}"
        kit_candidates = [
            ch_dir / "exports" / f"{series_slug}_ch{chapter:03d}_youtube_kit.txt",
            ch_dir / "reports" / "youtube_upload_kit.txt",
        ]
        for kc in kit_candidates:
            if kc.exists():
                text = kc.read_text(encoding="utf-8", errors="ignore")
                title_match = re.search(r"^1\)\s*(.+)$", text, re.MULTILINE)
                title = title_match.group(1).strip() if title_match else f"Chapter {chapter} (Hindi Dub)"
                desc_match = re.search(r"Full Story Explained in Hindi.*?\n\n(.+?)\n\n", text, re.DOTALL)
                teaser = desc_match.group(1).strip() if desc_match else ""
                return title, teaser
        return "", ""

    def _sample_manifest_lines(self, series_slug: str, chapter: int, limit: int = 10) -> List[str]:
        """Sample key dialogue/narration lines from a chapter's scene_manifest.json."""
        m_file = self.projects_dir / series_slug / f"chapter_{chapter:03d}" / "scripts" / "scene_manifest.json"
        if not m_file.exists():
            return []
        try:
            data = json.loads(m_file.read_text(encoding="utf-8"))
            scenes = data.get("scenes", [])
            if not scenes:
                return []
            step = max(1, len(scenes) // limit)
            lines: List[str] = []
            for s in scenes[::step][:limit]:
                txt = str(s.get("narration_text") or "").strip()
                spk = str(s.get("speaker") or "Narrator").strip()
                if txt:
                    lines.append(f"[{spk}]: {txt}")
            return lines
        except Exception:
            return []

    def _parse_marathon_chapters_for_window(
        self, timestamps_path: Optional[Path], start_sec: float, end_sec: float
    ) -> List[Tuple[int, str]]:
        """Find which chapters from a marathon .timestamps.txt fall inside [start_sec, end_sec]."""
        if not timestamps_path or not timestamps_path.exists():
            return []
        entries: List[Tuple[float, int, str]] = []
        for ln in timestamps_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            m = re.match(r"^(?:(\d+):)?(\d{1,2}):(\d{2})\s*-\s*(.+)$", ln.strip())
            if not m:
                continue
            hrs = int(m.group(1) or 0)
            mins = int(m.group(2))
            secs = int(m.group(3))
            t_sec = hrs * 3600 + mins * 60 + secs
            label = m.group(4).strip()
            ch_m = re.search(r"Chapter\s+(\d+)", label, re.IGNORECASE)
            ch_num = int(ch_m.group(1)) if ch_m else 0
            entries.append((float(t_sec), ch_num, label))

        if not entries:
            return []

        matched: List[Tuple[int, str]] = []
        for idx, (t_start, ch_num, label) in enumerate(entries):
            t_end = entries[idx + 1][0] if idx + 1 < len(entries) else float("inf")
            if t_end > start_sec and t_start < end_sec:
                matched.append((ch_num, label))
        return matched

    def _get_gemini_api_key(self) -> str:
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if api_key:
            return api_key
        env_file = self.root_dir / ".env"
        if env_file.exists():
            for ln in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                if ln.strip().startswith("GEMINI_API_KEY="):
                    val = ln.split("=", 1)[1].strip().strip('"').strip("'")
                    if val:
                        return val
        return ""

    def _generate_dynamic_metadata(
        self,
        series_slug: str,
        series_name: str,
        genre: str,
        item: Dict[str, Any],
        yt_ref: str,
        ig_ref: str,
        marathon_timestamps_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """Dynamically generate Title, Description, Pinned Comment, and Hashtags via Gemini + smart fallback."""
        ch = item.get("chapter")
        part = int(item.get("part") or 1)
        total_parts = int(item.get("total_parts") or 1)
        tag_slug = re.sub(r"[^A-Za-z0-9]", "", series_name)
        genre_tags = self._genre_hashtags(genre)

        story_lines: List[str] = []
        kit_title, kit_teaser = ("", "")
        chapter_labels: List[str] = []

        if ch:
            kit_title, kit_teaser = self._read_chapter_hook(series_slug, int(ch))
            story_lines = self._sample_manifest_lines(series_slug, int(ch), limit=10)
            part_tag = f" (Part {part}/{total_parts})" if total_parts > 1 else ""
            context_label = f"Chapter {ch}{part_tag}"
        else:
            start_s = float(item.get("start_sec") or 0.0)
            end_s = float(item.get("end_sec") or 0.0)
            overlaps = self._parse_marathon_chapters_for_window(marathon_timestamps_path, start_s, end_s)
            for ov_ch, ov_label in overlaps:
                chapter_labels.append(ov_label)
                if ov_ch and len(story_lines) < 10:
                    story_lines.extend(self._sample_manifest_lines(series_slug, ov_ch, limit=4))
            context_label = f"Part {part}/{total_parts}" + (f" ({', '.join(chapter_labels[:3])})" if chapter_labels else "")

        base_tags = [
            f"#{tag_slug}",
            f"#{tag_slug}Hindi",
            "#ManhwaInHindi",
            "#ManhwaRecap",
            "#HindiManhwa",
            "#ManhwaHindiDub",
            "#WebtoonIndia",
            "#AnimeHindi",
            "#ReelsIndia",
            "#AnimeReels",
            *genre_tags,
        ]
        # Deduplicate while preserving order
        seen_t = set()
        dedup_tags = [t for t in base_tags if not (t.lower() in seen_t or seen_t.add(t.lower()))]

        fallback_title = kit_title or f"{series_name} — {context_label} | Hindi Dub 🔥⚔️"
        if story_lines and not kit_teaser:
            snippet = story_lines[0].split(":", 1)[-1].strip()
            climax = story_lines[-1].split(":", 1)[-1].strip()
            fallback_desc = f"{snippet[:110]}...\n\n⚡ {climax[:110]}"
        else:
            fallback_desc = kit_teaser or f"{series_name} ({context_label}) ka zabardast action aur drama ab Hindi Dub mein!"

        fallback = {
            "title": fallback_title,
            "description": fallback_desc,
            "pinned_comment": (
                f"🔥 {context_label} kaisa laga? Comment mein batao!\n"
                f"👉 Instagram par FOLLOW karein (@{ig_ref}) aur Full Marathons ke liye YouTube SUBSCRIBE zaroor karein ({yt_ref})! 🔔"
            ),
            "hashtags": " ".join(dedup_tags[:18]),
            "topics": ["Anime", "Comics & Manga", "Entertainment"],
        }

        api_key = self._get_gemini_api_key()
        if not api_key or not (story_lines or kit_teaser or chapter_labels):
            return fallback

        try:
            from google import genai
            from manhwa_studio.env_config import get_env_config

            model_name = get_env_config().gemini_metadata_model
            client = genai.Client(api_key=api_key)
            context_block = "\n".join(story_lines[:10]) if story_lines else (kit_teaser or "\n".join(chapter_labels))
            prompt = (
                f"You are an Instagram Reels growth strategist for an Indian Hindi-dubbed Manhwa/Anime channel.\n"
                f"Series: '{series_name}' | Genre: '{genre}' | Segment: '{context_label}'\n"
                f"Story context / dialogue lines:\n{context_block}\n\n"
                f"Return ONLY a JSON object with:\n"
                f"1. 'title': Catchy Hinglish Instagram Reel/Cover title under 80 characters with 1-2 emojis.\n"
                f"2. 'description': 2 short punchy Hinglish hook paragraphs summarizing what happens in this segment (no links/hashtags).\n"
                f"3. 'pinned_comment': 1 short engaging question for viewers in Hinglish (no links).\n"
                f"4. 'hashtags': Array of 15-18 relevant Instagram hashtags (e.g. '#{tag_slug}', '#ManhwaInHindi', genre & character tags).\n"
                f"5. 'topics': Array of 3 Instagram Reel topic categories."
            )
            resp = client.models.generate_content(model=model_name, contents=prompt)
            raw = (resp.text or "").strip()
            m = re.search(r"\{.*\}", raw, flags=re.DOTALL)
            if m:
                parsed = json.loads(m.group(0))
                if parsed.get("title"):
                    fallback["title"] = str(parsed["title"]).strip()
                if parsed.get("description"):
                    fallback["description"] = str(parsed["description"]).strip()
                if parsed.get("pinned_comment"):
                    fallback["pinned_comment"] = (
                        f"{str(parsed['pinned_comment']).strip()}\n"
                        f"👉 Instagram par FOLLOW karein (@{ig_ref}) aur Full Marathons ke liye YouTube SUBSCRIBE karein ({yt_ref})! 🔔"
                    )
                if parsed.get("hashtags"):
                    ht = parsed["hashtags"]
                    if isinstance(ht, list):
                        fallback["hashtags"] = " ".join(str(x).strip() for x in ht if str(x).strip())
                    else:
                        fallback["hashtags"] = str(ht).strip()
                if isinstance(parsed.get("topics"), list) and parsed["topics"]:
                    fallback["topics"] = [str(t) for t in parsed["topics"][:3]]
        except Exception as e:
            logger.warning(f"Gemini Instagram metadata skipped for {item.get('filename')} ({e}); using smart fallback.")

        return fallback

    def write_publishing_guide(
        self,
        out_dir: Path,
        series_slug: str,
        exported_items: List[Dict[str, Any]],
        yt_handle: str = "",
        ig_handle: str = "",
        marathon_timestamps_path: Optional[Path] = None,
    ) -> Path:
        """Create INSTAGRAM_PUBLISHING_GUIDE.md with dynamic AI titles, descriptions, hashtags & YT/IG CTAs."""
        resolved_slug, pretty_name, genre = self._infer_series_meta(series_slug)
        ig_ref = ig_handle.strip().lstrip("@") or "[YOUR_IG_HANDLE]"
        yt_ref = yt_handle.strip() or "[YOUR_YOUTUBE_LINK]"

        lines: List[str] = [
            f"# 📸 Instagram Account & Publishing Kit — *{pretty_name}* (Hindi Dub)",
            "",
            f"**Genre:** `{genre}` | **Total Videos:** `{len(exported_items)}`",
            "",
            "---",
            "",
            "## 1. Instagram Account & Broadcast Channel Setup",
            "* **Account Type:** `Professional` → `Creator` (`Video Creator`)",
            "* **Bio:**",
            "```text",
            f"⚔️ {pretty_name} & Best Manhwa Recaps in Hindi!",
            "🔥 Daily Action Episodes & Epic Hindi Dubs",
            f"👇 Full 1+ Hr Marathons on YouTube — Subscribe Now! ({yt_ref})",
            "```",
            "* **Broadcast Channel Welcome Message:**",
            "```text",
            "Swagat hai Sabhi Manhwa Lovers ka! 🔥⚔️",
            f"👉 Instagram par FOLLOW zaroor karein (@{ig_ref}) aur full 1+ hour movie marathons ke liye hamare YouTube channel ko SUBSCRIBE karna mat bhoolna! 🔔👇",
            f"{yt_ref}",
            "```",
            "",
            "---",
            "",
            "## 2. Ready-to-Post Titles, Descriptions & Hashtags",
            "",
        ]

        for idx, item in enumerate(exported_items, start=1):
            fname = item["filename"]
            dur_min = round(float(item.get("duration_sec", 0)) / 60.0, 2)
            ch = item.get("chapter")
            part_label = f" (Part {item['part']}/{item['total_parts']})" if item.get("total_parts", 1) > 1 else ""
            ep_heading = f"Chapter {ch}{part_label} — `{fname}` ({dur_min} min)" if ch else f"Part {item.get('part', idx)} — `{fname}` ({dur_min} min)"

            meta = self._generate_dynamic_metadata(
                series_slug=resolved_slug,
                series_name=pretty_name,
                genre=genre,
                item=item,
                yt_ref=yt_ref,
                ig_ref=ig_ref,
                marathon_timestamps_path=marathon_timestamps_path,
            )

            lines.extend([
                f"### {ep_heading}",
                f"* **Reel / Cover Title:** `{meta['title']}`",
                f"* **Reel Topics:** `{'`, `'.join(meta['topics'])}`",
                "",
                "**Caption / Description:**",
                "```text",
                meta["title"],
                "",
                meta["description"],
                "",
                f"👉 Daily Hindi Manhwa Recaps ke liye Instagram par FOLLOW karein (@{ig_ref})!",
                f"📺 Full 1-Hour+ Marathons aur latest chapters ke liye hamara YouTube Channel SUBSCRIBE zaroor karein (Link in Bio: {yt_ref})! 🔔❤️",
                "```",
                "",
                "**Pinned Comment:**",
                "```text",
                meta["pinned_comment"],
                "```",
                "",
                "**Hashtags & Tags:**",
                "```text",
                meta["hashtags"],
                "```",
                "",
                "---",
                "",
            ])

        guide_file = out_dir / "INSTAGRAM_PUBLISHING_GUIDE.md"
        guide_file.write_text("\n".join(lines), encoding="utf-8")
        return guide_file

    def regenerate_guide_for_folder(
        self,
        folder_name: str,
        yt_handle: str = "",
        ig_handle: str = "",
    ) -> Path:
        """Regenerate INSTAGRAM_PUBLISHING_GUIDE.md dynamically for an existing exports/instagram/<folder>."""
        out_dir = self.exports_dir / folder_name
        if not out_dir.exists():
            raise FileNotFoundError(f"Instagram export folder not found: {out_dir}")

        mp4s = sorted(out_dir.glob("*.mp4"))
        if not mp4s:
            raise RuntimeError(f"No .mp4 files found in {out_dir}")

        items: List[Dict[str, Any]] = []
        total = len(mp4s)
        running_sec = 0.0
        for idx, mp4 in enumerate(mp4s, start=1):
            _, _, dur_sec = probe_video_info(mp4)
            ch_m = re.search(r"_ch(\d+)", mp4.name, re.IGNORECASE)
            part_m = re.search(r"_part(\d+)", mp4.name, re.IGNORECASE)
            items.append({
                "filename": mp4.name,
                "path": str(mp4.relative_to(self.root_dir)).replace("\\", "/"),
                "duration_sec": round(dur_sec, 1),
                "start_sec": round(running_sec, 1),
                "end_sec": round(running_sec + dur_sec, 1),
                "chapter": int(ch_m.group(1)) if ch_m else None,
                "part": int(part_m.group(1)) if part_m else idx,
                "total_parts": total if part_m else 1,
            })
            running_sec += dur_sec

        ts_candidate = self.root_dir / "exports" / "marathons" / f"{folder_name}.timestamps.txt"
        return self.write_publishing_guide(
            out_dir=out_dir,
            series_slug=folder_name,
            exported_items=items,
            yt_handle=yt_handle,
            ig_handle=ig_handle,
            marathon_timestamps_path=ts_candidate if ts_candidate.exists() else None,
        )
