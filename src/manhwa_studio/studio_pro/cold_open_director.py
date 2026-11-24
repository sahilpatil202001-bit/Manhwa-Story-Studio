"""
Cold Open Teaser & Retention Hook Engine.
Extracts the dramatic episode climax, attaches a high-tension hook voiceover,
and generates an 8-12s teaser opening to maximize viewer retention on YouTube.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image
from manhwa_studio.logging_config import get_logger
from manhwa_studio.schemas import SceneManifest, SceneItem
from manhwa_studio.studio_pro.series_manager import SeriesProfile
from manhwa_studio.studio_pro.camera_director import CameraDirector
from manhwa_studio.studio_pro.voice_director import VoiceDirector

logger = get_logger("manhwa_studio.pro.cold_open")


class ColdOpenDirector:
    """Produces a cinematic 8-12 second flash-forward hook for the start of the video."""

    def __init__(self, profile: SeriesProfile):
        self.profile = profile
        self.camera_director = CameraDirector()
        self.voice_director = VoiceDirector(profile)

    def select_climax_scene(
        self,
        manifest: SceneManifest,
        preferred_scene_id: Optional[str] = None,
    ) -> Optional[SceneItem]:
        """Find the most dramatic climax scene in the chapter."""
        if preferred_scene_id:
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
                if s.scene_id in target_ids:
                    return s

        # Score scenes in the 35%–92% window of the chapter for maximum dramatic hook impact
        best_scene: Optional[SceneItem] = None
        best_score = -1
        action_keywords = [
            "मौत", "खून", "तलवार", "ताकत", "शैतान", "धमाका", "हमला", "राक्षस", "खत्म",
            "power", "sword", "demon", "blood", "death", "attack", "sect", "master",
        ]
        n_total = len(manifest.scenes)
        for idx, s in enumerate(manifest.scenes):
            score = 0
            txt = f"{s.narration_text or ''} {s.subtitle_text or ''}".lower()
            for kw in action_keywords:
                if kw in txt:
                    score += 4
            if s.scene_purpose in ("climax", "revelation", "conflict", "turning_point"):
                score += 6
            if s.motion_preset in ("impact_shake", "zoom_in"):
                score += 5
            if int(n_total * 0.35) <= idx <= int(n_total * 0.92):
                score += 5
            if "!" in txt:
                score += 2
            if score > best_score:
                best_score = score
                best_scene = s

        if best_scene:
            return best_scene

        # Fallback to a scene in the final 20% of the chapter
        if manifest.scenes:
            idx = int(len(manifest.scenes) * 0.8)
            return manifest.scenes[idx]

        return None

    def build_cold_open(
        self,
        manifest: SceneManifest,
        artwork_dir: Path,
        output_dir: Path,
        custom_hook_text: Optional[str] = None,
        preferred_scene_id: Optional[str] = None,
    ) -> Tuple[Optional[Path], float]:
        """
        Generate a standalone cold-open video teaser (MP4 with audio) using the climax scene's
        authentic Gemini Puck voiceover (0 extra TTS calls when chapter is already voiced).
        Returns (teaser_video_path, duration_seconds).
        """
        import shutil

        output_dir.mkdir(parents=True, exist_ok=True)
        teaser_video = output_dir / "cold_open_teaser.mp4"
        teaser_audio = output_dir / "cold_open_audio.mp3"

        climax_scene = self.select_climax_scene(manifest, preferred_scene_id=preferred_scene_id)
        if not climax_scene or not climax_scene.image_file:
            logger.warning("No climax scene found for cold open; skipping.")
            return None, 0.0

        panel_path = artwork_dir / climax_scene.image_file
        if not panel_path.exists():
            logger.warning(f"Climax panel file not found: {panel_path}")
            return None, 0.0

        # 1. Reuse the climax scene's already-synthesized Gemini Puck audio if available (zero extra API calls & 100% identical voice!)
        existing_scene_audio = Path(climax_scene.actual_audio_path) if climax_scene.actual_audio_path else None
        if not custom_hook_text and existing_scene_audio and existing_scene_audio.exists() and existing_scene_audio.stat().st_size > 500:
            shutil.copy2(existing_scene_audio, teaser_audio)
            logger.info(f"Using climax scene '{climax_scene.scene_id}' Gemini Puck voiceover for Cold Open hook...")
        else:
            hook_text = custom_hook_text or (climax_scene.narration_text or climax_scene.subtitle_text or "")
            logger.info(f"Synthesizing Cold Open Gemini Puck voice hook: '{hook_text[:45]}...'")
            self.voice_director._synthesize_with_gemini(
                text=hook_text,
                output_file=teaser_audio,
                voice_id="Puck",
                rate="+2%",
            )

        # Get exact audio duration
        audio_dur = self.voice_director._get_audio_duration(teaser_audio)
        duration = max(4.5, min(11.0, audio_dur + 0.35))

        # 2. Render visual segment with dramatic zoom-in matching exact project dimensions
        visual_only = output_dir / "cold_open_visual.mp4"
        self.camera_director.render_scene_segment(
            image_path=panel_path,
            output_path=visual_only,
            duration=duration,
            motion_preset="zoom_in",
            fps=30,
        )

        # 3. Mux visual, Gemini Puck voiceover, and smooth BGM bed (no procedural sine-wave SFX)
        logger.info(f"Muxing Cold Open Teaser (duration={duration:.1f}s)...")
        from manhwa_studio.rendering.ffmpeg import get_video_encoder_args
        v_enc_args = get_video_encoder_args(quality=19, cpu_preset="veryfast", nvenc_preset="p4")
        bgm_path = Path("assets/audio/bgm/suspense_theme.wav")

        if bgm_path.exists():
            cmd = [
                "ffmpeg", "-y",
                "-i", str(visual_only),
                "-i", str(teaser_audio),
                "-stream_loop", "-1",
                "-i", str(bgm_path),
                "-filter_complex",
                f"[1:a]apad=pad_dur=0.35[v_pad];"
                f"[2:a]volume=0.14[bgm_low];"
                f"[v_pad][bgm_low]amix=inputs=2:duration=first,afade=t=out:st={max(0.5, duration - 0.45):.2f}:d=0.45[aout];"
                f"[0:v]fade=t=in:st=0:d=0.25,fade=t=out:st={max(0.5, duration - 0.45):.2f}:d=0.45[vout]",
                "-map", "[vout]",
                "-map", "[aout]",
                *v_enc_args,
                "-c:a", "aac",
                "-ar", "44100",
                "-b:a", "192k",
                "-t", f"{duration:.2f}",
                str(teaser_video),
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-i", str(visual_only),
                "-i", str(teaser_audio),
                "-filter_complex",
                f"[1:a]apad=pad_dur=0.35,afade=t=out:st={max(0.5, duration - 0.45):.2f}:d=0.45[aout];"
                f"[0:v]fade=t=in:st=0:d=0.25,fade=t=out:st={max(0.5, duration - 0.45):.2f}:d=0.45[vout]",
                "-map", "[vout]",
                "-map", "[aout]",
                *v_enc_args,
                "-c:a", "aac",
                "-ar", "44100",
                "-b:a", "192k",
                "-t", f"{duration:.2f}",
                str(teaser_video),
            ]

        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            # Fallback to CPU if NVENC failed
            cpu_cmd = [c for c in cmd if c not in ("h264_nvenc", "p4", "-cq")]
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", str(visual_only), "-i", str(teaser_audio),
                    "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k", "-shortest", str(teaser_video),
                ],
                capture_output=True,
                check=True,
            )
        try:
            import shutil
            exports_dir = output_dir.parent / "exports"
            exports_dir.mkdir(parents=True, exist_ok=True)
            series_slug = manifest.series.replace(" ", "_").replace(",", "").lower()
            shutil.copy2(teaser_video, exports_dir / f"{series_slug}_ch{manifest.chapter:03d}_cold_open.mp4")
        except Exception:
            pass

        logger.info(f"Cold Open Teaser ready at: {teaser_video} ({duration:.1f}s)")
        return teaser_video, duration
