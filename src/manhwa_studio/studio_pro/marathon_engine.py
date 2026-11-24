"""
Marathon Video Compilation Engine.
Aggregates multiple sequential manhwa chapters into full-movie recap compilations
(e.g., Chapters 1–5 Full Recap) complete with chapter title bumpers and YouTube timestamps.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont
from manhwa_studio.logging_config import get_logger
from manhwa_studio.rendering.ffmpeg import get_video_encoder_args, is_nvenc_available
from manhwa_studio.schemas import SceneManifest
from manhwa_studio.studio_pro.series_manager import SeriesProfile

logger = get_logger("manhwa_studio.pro.marathon")


class MarathonEngine:
    """Combines individual chapter renders into a long-form marathon video with timestamps."""

    def __init__(self, profile: SeriesProfile, projects_base_dir: Optional[Path] = None):
        from manhwa_studio.env_config import get_env_config
        self.profile = profile
        self.env_cfg = get_env_config()
        self.base_dir = projects_base_dir or (Path("data") / "projects")

    def _format_timestamp(self, seconds: float) -> str:
        """Format seconds into HH:MM:SS or MM:SS."""
        hrs = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        if hrs > 0:
            return f"{hrs:02d}:{mins:02d}:{secs:02d}"
        return f"{mins:02d}:{secs:02d}"

    def _get_video_duration(self, video_path: Path) -> float:
        """Get exact duration of an mp4 video using ffprobe."""
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return float(res.stdout.strip())
        except Exception:
            return 0.0

    def _get_video_dimensions(self, video_path: Path) -> Tuple[int, int]:
        """Get exact width and height of a video using ffprobe."""
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=s=x:p=0",
            str(video_path),
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            parts = res.stdout.strip().split("x")
            return int(parts[0]), int(parts[1])
        except Exception:
            return 1080, 1920

    def _get_video_audio_info(self, video_path: Path) -> Tuple[int, str]:
        """Get exact audio sample rate and channel layout using ffprobe."""
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=sample_rate,channels",
            "-of", "csv=s=x:p=0",
            str(video_path),
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            parts = res.stdout.strip().split("x")
            sr = int(parts[0])
            ch = int(parts[1])
            layout = "stereo" if ch == 2 else "mono"
            return sr, layout
        except Exception:
            return 48000, "mono"

    def create_chapter_bumper(
        self,
        chapter_num: int,
        chapter_title: str,
        output_video: Path,
        duration: float = 2.5,
        resolution: Tuple[int, int] = (1080, 1920),
        audio_sr: int = 48000,
        audio_layout: str = "mono",
    ) -> Path:
        """Create a sleek animated chapter title transition bumper matching video dimensions."""
        w, h = resolution
        img = Image.new("RGB", (w, h), (10, 10, 14))
        draw = ImageDraw.Draw(img)

        # Draw red border frame
        pad = int(min(w, h) * 0.04)
        draw.rectangle([pad, pad, w - pad, h - pad], outline=(180, 20, 30), width=4)

        # Scale font sizes relative to dimensions
        font_size_large = int(min(w, h) * 0.085)

        font_large = ImageFont.load_default()
        latin_candidates = [self.env_cfg.font_latin, "C:\\Windows\\Fonts\\arialbd.ttf", "arialbd.ttf", "arial.ttf"]
        for fn in latin_candidates:
            try:
                font_large = ImageFont.truetype(fn, font_size_large)
                break
            except Exception:
                continue

        # Draw centered CHAPTER header only (no bottom 'Batch 1' subtitle line)
        header_text = f"CHAPTER {chapter_num}"
        bbox1 = draw.textbbox((0, 0), header_text, font=font_large)
        tx1 = (w - (bbox1[2] - bbox1[0])) // 2
        ty1 = (h - (bbox1[3] - bbox1[1])) // 2
        draw.text((tx1, ty1), header_text, font=font_large, fill=(230, 30, 40))

        temp_img = output_video.with_suffix(".card.jpg")
        img.save(temp_img, quality=95)

        # Render bumper video matching exact resolution and aspect ratio
        v_enc_args = get_video_encoder_args(quality=19, cpu_preset="veryfast", nvenc_preset="p4")
        cmd = [
            "ffmpeg",
            "-y",
            "-loop", "1",
            "-i", str(temp_img),
            "-f", "lavfi",
            "-i", f"anullsrc=r={audio_sr}:cl={audio_layout}",
            "-t", str(duration),
            "-vf", f"scale={w}:{h},fade=t=in:st=0:d=0.4,fade=t=out:st={duration - 0.4}:d=0.4,fps=30",
            *v_enc_args,
            "-c:a", "aac",
            "-ar", str(audio_sr),
            "-ac", "2" if audio_layout == "stereo" else "1",
            "-b:a", "192k",
            str(output_video),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            cpu_cmd = [
                "ffmpeg", "-y", "-loop", "1", "-i", str(temp_img),
                "-f", "lavfi", "-i", f"anullsrc=r={audio_sr}:cl={audio_layout}",
                "-t", str(duration),
                "-vf", f"scale={w}:{h},fade=t=in:st=0:d=0.4,fade=t=out:st={duration - 0.4}:d=0.4,fps=30",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-ar", str(audio_sr), "-ac", "2" if audio_layout == "stereo" else "1", "-b:a", "192k",
                str(output_video),
            ]
            subprocess.run(cpu_cmd, capture_output=True, check=True)
        if temp_img.exists():
            temp_img.unlink()

        return output_video

    def prepare_outro_clip(
        self,
        output_video: Path,
        resolution: Tuple[int, int] = (1920, 1080),
        audio_sr: int = 44100,
        audio_layout: str = "stereo",
    ) -> Optional[Path]:
        """
        Format `assets/video/to_be_continued_black.mp4` to match the exact resolution, framerate (30fps),
        and AAC audio stream (sample rate + channel layout) of the main video so it stitches seamlessly
        at the very end of the video.
        """
        outro_src = Path(getattr(self.env_cfg, "outro_video_file", "assets/video/to_be_continued_black.mp4"))
        if not outro_src.exists():
            outro_src = Path("assets/video/to_be_continued_black.mp4")
        if not outro_src.exists():
            logger.warning(f"To Be Continued outro video not found at {outro_src}; skipping outro.")
            return None

        w, h = resolution
        ac_num = "2" if audio_layout == "stereo" else "1"
        v_enc_args = get_video_encoder_args(quality=19, cpu_preset="veryfast", nvenc_preset="p4")
        vf_str = (
            f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,fps=30,format=yuv420p"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", str(outro_src),
            "-f", "lavfi",
            "-i", f"anullsrc=r={audio_sr}:cl={audio_layout}",
            "-vf", vf_str,
            "-map", "0:v:0",
            "-map", "1:a:0",
            *v_enc_args,
            "-c:a", "aac",
            "-ar", str(audio_sr),
            "-ac", ac_num,
            "-b:a", "192k",
            "-shortest",
            str(output_video),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            cpu_cmd = [
                "ffmpeg", "-y",
                "-i", str(outro_src),
                "-f", "lavfi",
                "-i", f"anullsrc=r={audio_sr}:cl={audio_layout}",
                "-vf", vf_str,
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-ar", str(audio_sr), "-ac", ac_num, "-b:a", "192k",
                "-shortest",
                str(output_video),
            ]
            subprocess.run(cpu_cmd, capture_output=True, check=False)

        if output_video.exists() and output_video.stat().st_size > 1000:
            return output_video
        return None

    def compile_marathon(
        self,
        chapter_nums: List[int],
        output_file: Path,
        include_bumpers: bool = False,
        include_outro: bool = True,
        speed: float = 1.0,
    ) -> Tuple[Path, str]:
        """
        Stitch multiple rendered chapters into a full-movie marathon compilation with ZERO gap
        between chapters, and append the 'To Be Continued' video (`to_be_continued_black.mp4`)
        at the very end of the marathon.
        Returns (output_video_path, youtube_timestamps_markdown).
        """
        series_dir = self.base_dir / self.profile.series_slug
        if not series_dir.exists():
            # Try fuzzy match
            for d in self.base_dir.iterdir():
                if d.is_dir() and (self.profile.series_slug in d.name or d.name in self.profile.series_slug):
                    series_dir = d
                    break

        if not series_dir.exists():
            raise FileNotFoundError(f"Series directory not found for '{self.profile.series_slug}' in {self.base_dir}")

        segment_videos: List[Path] = []
        timestamps: List[Tuple[float, str]] = []
        current_playback_time = 0.0

        bumper_dir = series_dir / "reports" / "marathon_temp"
        bumper_dir.mkdir(parents=True, exist_ok=True)

        for ch in chapter_nums:
            ch_folder = series_dir / f"chapter_{ch:03d}"
            # Locate rendered video (prefer gapless `chapter_body` stream so there is no mid-marathon outro/gap)
            if speed != 1.0:
                speed_label = f"{speed:g}x"
                possible_paths = [
                    ch_folder / "renders" / f"chapter_body_{speed_label}.mp4",
                    ch_folder / "renders" / f"final_video_{speed_label}.mp4",
                ]
            else:
                possible_paths = [
                    ch_folder / "renders" / "chapter_body.mp4",
                    ch_folder / "renders" / "final_video.mp4",
                    ch_folder / "exports" / f"chapter_{ch:03d}.mp4",
                    Path("exports") / "videos" / f"chapter_{ch}" / f"ch{ch} - part 1.mp4",
                    Path("exports") / "videos" / f"ch{ch}.mp4",
                ]
            video_path = None
            for p in possible_paths:
                if p.exists() and p.stat().st_size > 1000000:
                    video_path = p
                    break

            if not video_path:
                render_kind = f"{speed:g}x speed" if speed != 1.0 else "normal-speed"
                logger.warning(f"No {render_kind} rendered video found for Chapter {ch} in {ch_folder}, skipping...")
                continue

            # Load chapter title from manifest if available and strip any 'Batch X' / 'Part X' noise
            m_path = ch_folder / "scripts" / "scene_manifest.json"
            ch_title = f"Chapter {ch}"
            if m_path.exists():
                try:
                    import re
                    m_data = json.loads(m_path.read_text(encoding="utf-8"))
                    raw_t = str(m_data.get("title") or "").strip()
                    raw_t = re.sub(r"[-–—:\s]*\b(?:Batch|Part)\s*\d+\b", "", raw_t, flags=re.IGNORECASE).strip(" -–—:")
                    if raw_t:
                        ch_title = raw_t
                except Exception:
                    pass

            # Optional Chapter Bumper Card (disabled by default for 100% seamless chapter transitions)
            if include_bumpers and self.env_cfg.bumper_duration_sec > 0.1:
                bumper_dur = self.env_cfg.bumper_duration_sec
                bumper_path = bumper_dir / f"bumper_ch{ch}.mp4"
                res_dim = self._get_video_dimensions(video_path)
                sr, layout = self._get_video_audio_info(video_path)
                self.create_chapter_bumper(ch, ch_title, bumper_path, duration=bumper_dur, resolution=res_dim, audio_sr=sr, audio_layout=layout)
                segment_videos.append(bumper_path)
                current_playback_time += bumper_dur

            # Record YouTube Timestamp
            timestamps.append((current_playback_time, f"Chapter {ch}: {ch_title}"))

            # Add main chapter video
            segment_videos.append(video_path)
            vid_dur = self._get_video_duration(video_path)
            current_playback_time += vid_dur

        if not segment_videos:
            raise RuntimeError(f"No valid chapter videos could be gathered for chapters: {chapter_nums}")

        # Append 'To Be Continued' (`assets/video/to_be_continued_black.mp4`) once at the VERY END of the Marathon video
        if include_outro:
            last_vid = segment_videos[-1]
            res_dim = self._get_video_dimensions(last_vid)
            sr, layout = self._get_video_audio_info(last_vid)
            outro_prepared = bumper_dir / "to_be_continued_outro.mp4"
            if self.prepare_outro_clip(outro_prepared, resolution=res_dim, audio_sr=sr, audio_layout=layout):
                segment_videos.append(outro_prepared)
                outro_dur = self._get_video_duration(outro_prepared)
                current_playback_time += outro_dur
                logger.info(f"Appended 'To Be Continued' outro clip ({outro_dur:.1f}s) to the end of the marathon.")

        # Normalize audio parameters across segments before stream-copy concatenation
        # so mismatched sample rates (e.g. 24 kHz vs 48 kHz) do not corrupt MP4 stts tables.
        target_dim = self._get_video_dimensions(segment_videos[0])
        target_sr, target_layout = self._get_video_audio_info(segment_videos[0])
        target_ac = "2" if target_layout == "stereo" else "1"
        can_stream_copy = True
        normalized_segments: List[Path] = []
        for idx, seg_path in enumerate(segment_videos):
            seg_dim = self._get_video_dimensions(seg_path)
            seg_sr, seg_layout = self._get_video_audio_info(seg_path)
            if seg_dim != target_dim:
                can_stream_copy = False
                normalized_segments.append(seg_path)
                continue
            if seg_sr != target_sr or seg_layout != target_layout:
                norm_path = bumper_dir / f"norm_audio_{idx:03d}.mp4"
                logger.info(
                    f"Normalizing audio for {seg_path.name} ({seg_sr}Hz {seg_layout} -> {target_sr}Hz {target_layout})..."
                )
                norm_cmd = [
                    "ffmpeg", "-y", "-i", str(seg_path),
                    "-c:v", "copy",
                    "-c:a", "aac", "-ar", str(target_sr), "-ac", target_ac, "-b:a", "192k",
                    str(norm_path),
                ]
                norm_res = subprocess.run(norm_cmd, capture_output=True, text=True)
                if norm_res.returncode == 0 and norm_path.exists() and norm_path.stat().st_size > 1000:
                    normalized_segments.append(norm_path)
                else:
                    can_stream_copy = False
                    normalized_segments.append(seg_path)
            else:
                normalized_segments.append(seg_path)
        segment_videos = normalized_segments

        # Concatenate all video segments
        concat_list = bumper_dir / "marathon_concat.txt"
        lines = [f"file '{p.resolve().as_posix()}'" for p in segment_videos]
        concat_list.write_text("\n".join(lines), encoding="utf-8")

        output_file.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"Stitching {len(segment_videos)} segments into Marathon Video: {output_file.name}...")

        # 1. Try ultra-fast lossless stream copy first (completes in seconds) when streams match
        copy_res = None
        if can_stream_copy:
            copy_cmd = [
                "ffmpeg",
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_list),
                "-c", "copy",
                "-movflags", "+faststart",
                str(output_file),
            ]
            copy_res = subprocess.run(copy_cmd, capture_output=True, text=True)

        if copy_res is not None and copy_res.returncode == 0 and output_file.exists() and output_file.stat().st_size > 1000000:
            logger.info("Marathon compiled in seconds via lossless stream copy (-c copy)!")
        else:
            # 2. Fallback to GPU NVENC (or CPU libx264 if NVENC unavailable)
            v_enc_args = get_video_encoder_args(quality=20, cpu_preset="fast", nvenc_preset="p4")
            enc_label = "GPU (h264_nvenc)" if is_nvenc_available() else "CPU (libx264)"
            logger.info(f"Stream parameters varied; encoding marathon via {enc_label}...")
            enc_cmd = [
                "ffmpeg",
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_list),
                *v_enc_args,
                "-c:a", "aac",
                "-b:a", "192k",
                "-movflags", "+faststart",
                str(output_file),
            ]
            enc_res = subprocess.run(enc_cmd, capture_output=True, text=True)
            if enc_res.returncode != 0 and is_nvenc_available():
                logger.warning("NVENC marathon encode failed, falling back to CPU libx264...")
                cpu_cmd = [
                    "ffmpeg",
                    "-y",
                    "-f", "concat",
                    "-safe", "0",
                    "-i", str(concat_list),
                    "-c:v", "libx264",
                    "-preset", "fast",
                    "-crf", "20",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-movflags", "+faststart",
                    str(output_file),
                ]
                subprocess.run(cpu_cmd, capture_output=True, check=True)
            elif enc_res.returncode != 0:
                raise RuntimeError(f"Marathon FFmpeg compilation failed: {enc_res.stderr[-500:]}")

        # Generate complete Marathon YouTube Upload Kit with Viral Curiosity Titles, Timestamps & Tags
        from manhwa_studio.studio_pro.youtube_kit import YouTubeKitGenerator

        formatted_ts = [(self._format_timestamp(t_sec), label) for t_sec, label in timestamps]
        meta_file = output_file.with_suffix(".timestamps.txt")
        yt_kit = YouTubeKitGenerator(self.profile)
        yt_kit.build_marathon_youtube_kit(
            chapter_nums=chapter_nums,
            timestamps=formatted_ts,
            output_txt_file=meta_file,
            total_duration_mins=current_playback_time / 60.0,
        )
        metadata_text = meta_file.read_text(encoding="utf-8")

        logger.info(f"Successfully generated Marathon Video ({current_playback_time/60:.1f} mins) with full YouTube Kit at {meta_file}")
        return output_file, metadata_text
