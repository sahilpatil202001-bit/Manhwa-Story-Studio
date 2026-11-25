"""
Dynamic Mood-Adaptive BGM & Sound Effects (SFX) Engine.
Analyzes scene sentiment/action, auto-mixes background music with intelligent voice-ducking,
and inserts cinematic sound impacts (slashes, booms, risers) on dramatic panels.
"""

from __future__ import annotations

import math
import os
import struct
import subprocess
import wave
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from manhwa_studio.logging_config import get_logger
from manhwa_studio.schemas import SceneManifest, SceneItem
from manhwa_studio.studio_pro.series_manager import SeriesProfile

logger = get_logger("manhwa_studio.pro.audio")


class AudioDirector:
    """Oversees mood detection, procedural SFX generation, and multi-track audio mixing."""

    def __init__(self, profile: SeriesProfile, audio_assets_dir: Optional[Path] = None):
        self.profile = profile
        self.audio_assets_dir = audio_assets_dir or (Path("assets") / "audio")
        self.bgm_dir = self.audio_assets_dir / "bgm"
        self.sfx_dir = self.audio_assets_dir / "sfx"
        self._ensure_asset_library()

    def _ensure_asset_library(self) -> None:
        """Ensure BGM and SFX directories exist, generating procedural fallback assets if needed."""
        self.bgm_dir.mkdir(parents=True, exist_ok=True)
        self.sfx_dir.mkdir(parents=True, exist_ok=True)

        # Check existing cinematic suspense track in parent audio dir
        existing_suspense = self.audio_assets_dir / "cinematic_suspense.wav"
        target_suspense = self.bgm_dir / "suspense_theme.wav"
        if existing_suspense.exists() and not target_suspense.exists():
            import shutil
            shutil.copy(str(existing_suspense), str(target_suspense))

        # Procedural sine-wave SFX disabled to prevent synthetic electronic/glitch sounds during narration
        return

    def _generate_procedural_sfx(self) -> None:
        """Disabled procedural sine-wave synthesis to prevent electronic glitch sounds."""
        return

    def _synth_impact_boom(self, path: Path) -> None:
        """Generate a low cinematic bass drop / impact hit."""
        sample_rate = 44100
        duration = 2.5
        n_samples = int(sample_rate * duration)
        with wave.open(str(path), "w") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            data = bytearray()
            for i in range(n_samples):
                t = i / sample_rate
                # Pitch drops from 120Hz to 35Hz
                freq = 120 * math.exp(-t * 2.8) + 35
                env = math.exp(-t * 1.6)
                val = math.sin(2 * math.pi * freq * t) * env
                # Add slight noise transient at start (0 to 0.05s)
                if t < 0.06:
                    val += (math.sin(t * 8000) * 0.4) * (1 - t / 0.06)
                sample = int(max(-1.0, min(1.0, val)) * 32000)
                data.extend(struct.pack("<h", sample))
            wav_file.writeframes(data)

    def _synth_sword_slash(self, path: Path) -> None:
        """Generate a metallic sword clash/slash whoosh."""
        sample_rate = 44100
        duration = 1.2
        n_samples = int(sample_rate * duration)
        with wave.open(str(path), "w") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            data = bytearray()
            for i in range(n_samples):
                t = i / sample_rate
                # High frequency metallic sweep (2200Hz down to 400Hz)
                freq = 2400 * math.exp(-t * 4.5) + 380
                env = math.exp(-t * 3.2)
                val = (math.sin(2 * math.pi * freq * t) + 0.3 * math.sin(2 * math.pi * (freq * 1.5) * t)) * env
                sample = int(max(-1.0, min(1.0, val)) * 28000)
                data.extend(struct.pack("<h", sample))
            wav_file.writeframes(data)

    def _synth_tension_riser(self, path: Path) -> None:
        """Generate a tension pitch riser."""
        sample_rate = 44100
        duration = 3.0
        n_samples = int(sample_rate * duration)
        with wave.open(str(path), "w") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            data = bytearray()
            for i in range(n_samples):
                t = i / sample_rate
                # Pitch rises from 80Hz to 600Hz
                freq = 80 + 520 * (t / duration) ** 2
                env = (t / duration) ** 1.8
                val = math.sin(2 * math.pi * freq * t) * env
                sample = int(max(-1.0, min(1.0, val)) * 26000)
                data.extend(struct.pack("<h", sample))
            wav_file.writeframes(data)

    def _synth_dark_pulse(self, path: Path) -> None:
        """Generate a dark ominous heartbeat pulse."""
        sample_rate = 44100
        duration = 2.0
        n_samples = int(sample_rate * duration)
        with wave.open(str(path), "w") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            data = bytearray()
            for i in range(n_samples):
                t = i / sample_rate
                freq = 55 + 15 * math.sin(2 * math.pi * 3.0 * t)
                env = math.exp(-((t % 0.8) * 3.5))
                val = math.sin(2 * math.pi * freq * t) * env
                sample = int(max(-1.0, min(1.0, val)) * 30000)
                data.extend(struct.pack("<h", sample))
            wav_file.writeframes(data)

    def _synth_bone_crack(self, path: Path) -> None:
        """Generate a sharp, violent bone crack / throat choke crunch."""
        sample_rate = 44100
        duration = 0.8
        n_samples = int(sample_rate * duration)
        with wave.open(str(path), "w") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            data = bytearray()
            for i in range(n_samples):
                t = i / sample_rate
                # Quick snap transient (1800Hz crack down to 120Hz crunch)
                freq = 1800 * math.exp(-t * 18.0) + 120 * math.exp(-t * 4.0) + 40
                env = math.exp(-t * 9.0)
                # Add irregular crunch bursts
                crunch = math.sin(2 * math.pi * freq * t)
                if t < 0.12:
                    crunch += (math.sin(t * 12500) * 0.6) * (1 - t / 0.12)
                val = crunch * env
                sample = int(max(-1.0, min(1.0, val)) * 31000)
                data.extend(struct.pack("<h", sample))
            wav_file.writeframes(data)

    def _synth_metal_clash(self, path: Path) -> None:
        """Generate a dual-sword ringing metal clash."""
        sample_rate = 44100
        duration = 1.8
        n_samples = int(sample_rate * duration)
        with wave.open(str(path), "w") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            data = bytearray()
            for i in range(n_samples):
                t = i / sample_rate
                # Twin ringing frequencies with slow exponential decay
                env = math.exp(-t * 2.2)
                f1, f2, f3 = 1420, 2840, 4260
                val = (0.5 * math.sin(2 * math.pi * f1 * t) +
                       0.3 * math.sin(2 * math.pi * f2 * t) +
                       0.2 * math.sin(2 * math.pi * f3 * t)) * env
                sample = int(max(-1.0, min(1.0, val)) * 28000)
                data.extend(struct.pack("<h", sample))
            wav_file.writeframes(data)

    def _synth_whoosh(self, path: Path) -> None:
        """Generate a fast aerodynamic dash / whoosh sound."""
        sample_rate = 44100
        duration = 0.9
        n_samples = int(sample_rate * duration)
        with wave.open(str(path), "w") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            data = bytearray()
            for i in range(n_samples):
                t = i / sample_rate
                # Bell-shaped envelope peaking in the middle
                env = math.sin(math.pi * (t / duration)) ** 2
                freq = 300 + 900 * math.sin(math.pi * (t / duration))
                val = math.sin(2 * math.pi * freq * t) * env
                sample = int(max(-1.0, min(1.0, val)) * 27000)
                data.extend(struct.pack("<h", sample))
            wav_file.writeframes(data)

    def _synth_dark_aura(self, path: Path) -> None:
        """Generate a demonic low-frequency dark aura rumble."""
        sample_rate = 44100
        duration = 3.5
        n_samples = int(sample_rate * duration)
        with wave.open(str(path), "w") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            data = bytearray()
            for i in range(n_samples):
                t = i / sample_rate
                env = math.sin(math.pi * (t / duration)) ** 1.2
                # Sub-bass rumble around 42Hz with 84Hz harmonic
                val = (math.sin(2 * math.pi * 42 * t) + 0.4 * math.sin(2 * math.pi * 84 * t)) * env
                sample = int(max(-1.0, min(1.0, val)) * 29000)
                data.extend(struct.pack("<h", sample))
            wav_file.writeframes(data)

    def detect_scene_mood(self, scene: SceneItem) -> str:
        """Classify scene mood: 'combat', 'suspense', 'sorrow', or 'neutral'."""
        text = f"{scene.narration_text or ''} {scene.subtitle_text or ''}".lower()

        combat_words = ["धमाका", "हमला", "तलवार", "वार", "काट", "खून", "लड़ाई", "चीख", "strike", "attack", "slash", "blood", "kill", "चोट", "टुकड़े"]
        if any(w in text for w in combat_words):
            return "combat"

        sorrow_words = ["दादाजी", "रोने", "दुख", "याद", "छोड़कर", "चले गए", "दर्द", "आँसू", "sad", "loss", "grief", "alone", "मासूमियत"]
        if any(w in text for w in sorrow_words):
            return "sorrow"

        suspense_words = ["सन्नाटा", "साया", "खौफ", "अंधेरा", "साजिश", "खामोशी", "मौत", "लाश", "mystery", "shadow", "death", "silent", "creepy", "राक्षस", "शैतान"]
        if any(w in text for w in suspense_words):
            return "suspense"

        return "neutral"

    def select_sfx_for_scene(self, scene: SceneItem) -> Optional[Path]:
        """Disabled procedural sine-wave SFX triggers so narration and BGM play cleanly without glitch sounds."""
        return None

    @staticmethod
    def _resolve_media_tool(tool_name: str) -> str:
        """Resolve ffmpeg/ffprobe binary path with Windows fallback."""
        import os
        import shutil

        try:
            from manhwa_studio.rendering.ffmpeg import get_ffmpeg_path, get_ffprobe_path

            return get_ffprobe_path() if tool_name == "ffprobe" else get_ffmpeg_path()
        except Exception:
            found = shutil.which(tool_name)
            if found:
                return found
            if os.name == "nt":
                win_fallback = Path(r"C:\ffmpeg\bin") / f"{tool_name}.exe"
                if win_fallback.exists():
                    return str(win_fallback)
            return tool_name

    @classmethod
    def _probe_audio_duration(cls, path: Path, fallback: float, stream_selector: str = "a:0") -> float:
        """Probe exact encoded duration of a media file via ffprobe."""
        ffprobe_bin = cls._resolve_media_tool("ffprobe")
        queries = (
            ["-show_entries", "format=duration"],
            ["-select_streams", stream_selector, "-show_entries", "stream=duration"],
        )
        for q_args in queries:
            try:
                res = subprocess.run(
                    [
                        ffprobe_bin,
                        "-v", "error",
                        *q_args,
                        "-of", "default=noprint_wrappers=1:nokey=1",
                        str(path),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if res.returncode == 0 and res.stdout.strip():
                    for line in res.stdout.strip().splitlines():
                        raw = line.strip()
                        if raw and raw != "N/A":
                            val = float(raw)
                            if val > 0.05:
                                return val
            except Exception:
                pass
        return fallback

    def build_voice_timeline(self, manifest: SceneManifest, output_voice_track: Path) -> float:
        """
        Concatenate all individual scene audio clips with exact probed durations and async PTS alignment.
        Returns total audio duration in seconds.
        """
        concat_list_file = output_voice_track.with_suffix(".concat.txt")
        lines = []

        total_dur = 0.0
        for sc in manifest.scenes:
            if sc.actual_audio_path and Path(sc.actual_audio_path).exists():
                ap = Path(sc.actual_audio_path)
                exact_d = self._probe_audio_duration(ap, float(sc.actual_audio_duration or sc.duration))
                sc.actual_audio_duration = exact_d
                lines.append(f"file '{ap.resolve().as_posix()}'")
                total_dur += exact_d
            else:
                logger.warning(f"Audio missing for scene {sc.scene_id}")

        concat_list_file.write_text("\n".join(lines), encoding="utf-8")

        ffmpeg_bin = self._resolve_media_tool("ffmpeg")
        cmd = [
            ffmpeg_bin,
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list_file),
            "-af", "aresample=async=1:first_pts=0",
            "-c:a", "libmp3lame",
            "-b:a", "192k",
            str(output_voice_track),
        ]
        subprocess.run(cmd, capture_output=True, check=True)
        if concat_list_file.exists():
            concat_list_file.unlink()

        return total_dur

    def mix_master_soundtrack(
        self,
        manifest: SceneManifest,
        voice_track: Path,
        output_master_audio: Path,
        bgm_track: Optional[Path] = None,
    ) -> Path:
        """
        Mixes concatenated voiceover, looping mood BGM with sidechain ducking,
        and triggers punchy sound effects at key timestamps.
        """
        # Determine BGM source
        from manhwa_studio.env_config import get_env_config
        env_bgm = Path(get_env_config().default_bgm_file)
        bgm_file = bgm_track or (env_bgm if env_bgm.exists() else (self.bgm_dir / "suspense_theme.wav"))
        if not bgm_file.exists():
            # Fallback to any audio file in assets
            any_bgm = list(self.bgm_dir.glob("*.wav")) + list(self.audio_assets_dir.glob("*.wav"))
            bgm_file = any_bgm[0] if any_bgm else None

        duck_vol = self.profile.bgm_ducking_volume
        norm_vol = self.profile.bgm_normal_volume

        if not bgm_file or not bgm_file.exists():
            # If no BGM exists, just use normalized voice track
            import shutil
            shutil.copy(str(voice_track), str(output_master_audio))
            logger.info("No BGM available; master track exported with voice only.")
            return output_master_audio

        logger.info(f"Mixing master soundtrack: Voice + BGM ('{bgm_file.name}') with ducking ({duck_vol:.2f})...")

        env_cfg = get_env_config()
        sfx_events: List[Tuple[float, Path]] = []
        if env_cfg.enable_sfx and manifest.scenes:
            running_t = 0.0
            last_sfx_t = -10.0
            for sc in manifest.scenes:
                dur = sc.actual_audio_duration or sc.duration or 4.0
                if running_t - last_sfx_t >= 8.0 and len(sfx_events) < 12:
                    sfx_path = self.select_sfx_for_scene(sc)
                    if sfx_path and sfx_path.exists():
                        sfx_events.append((running_t, sfx_path))
                        last_sfx_t = running_t
                running_t += dur

        # Build dynamic mood-adaptive volume expression across chapter timeline
        # so combat/climax moments feel intense while sorrow/dialogue stays subtle
        mood_vol_expr_parts: List[str] = []
        if manifest.scenes:
            t_cursor = 0.0
            for sc in manifest.scenes:
                dur = float(sc.actual_audio_duration or sc.duration or 3.0)
                mood = self.detect_scene_mood(sc)
                t_end = t_cursor + dur
                if mood == "combat":
                    # Swell BGM energy by +25% on intense action scenes
                    mood_vol_expr_parts.append(f"between(t,{t_cursor:.2f},{t_end:.2f})*1.25")
                elif mood == "sorrow":
                    # Soften BGM by -20% on emotional/sorrow scenes
                    mood_vol_expr_parts.append(f"between(t,{t_cursor:.2f},{t_end:.2f})*0.80")
                t_cursor = t_end

        # Base BGM bed volume (kept clean so Puck's voice is 100% crystal clear)
        base_bed_vol = max(0.07, min(0.18, float(duck_vol or 0.10)))
        if mood_vol_expr_parts and len(mood_vol_expr_parts) <= 45:
            mood_mult = "1.0+" + "+".join(
                p.replace("*1.25", "*0.25").replace("*0.80", "*(-0.20)") for p in mood_vol_expr_parts[:45]
            )
            bgm_vol_filter = f"volume='{base_bed_vol:.3f}*({mood_mult})':eval=frame"
        else:
            bgm_vol_filter = f"volume={base_bed_vol:.3f}"

        # Build FFmpeg inputs and filter_complex with vocal clarity EQ + automatic sidechain ducking
        cmd = [
            "ffmpeg",
            "-y",
            "-i", str(voice_track),
            "-i", str(bgm_file),
        ]

        sfx_vol = max(0.05, min(1.0, env_cfg.sfx_volume))
        if sfx_events:
            sfx_filter_parts = [
                "[0:a]highpass=f=75,acompressor=threshold=-18dB:ratio=2.2:attack=12:release=160,volume=1.18,asplit=2[vox][sc]",
                f"[1:a]aloop=loop=-1:size=2e+09,lowpass=f=3800,{bgm_vol_filter}[bgm_raw]",
                "[bgm_raw][sc]sidechaincompress=threshold=0.025:ratio=6:attack=25:release=350[bgm]",
            ]
            mix_labels = ["[vox]", "[bgm]"]
            for idx, (ts_sec, sfx_p) in enumerate(sfx_events):
                in_idx = idx + 2
                cmd.extend(["-i", str(sfx_p)])
                delay_ms = max(0, int(ts_sec * 1000))
                lbl = f"[sfx{idx}]"
                sfx_filter_parts.append(f"[{in_idx}:a]volume={sfx_vol},adelay={delay_ms}|{delay_ms}{lbl}")
                mix_labels.append(lbl)
            total_inputs = len(mix_labels)
            sfx_filter_parts.append(
                f"{''.join(mix_labels)}amix=inputs={total_inputs}:duration=first:dropout_transition=2:normalize=0[outa]"
            )
            filter_complex = ";".join(sfx_filter_parts)
            logger.info(f"Injecting {len(sfx_events)} combat/aura SFX cues at volume={sfx_vol:.2f}")
        else:
            filter_complex = (
                "[0:a]highpass=f=75,acompressor=threshold=-18dB:ratio=2.2:attack=12:release=160,volume=1.18,asplit=2[vox][sc];"
                f"[1:a]aloop=loop=-1:size=2e+09,lowpass=f=3800,{bgm_vol_filter}[bgm_raw];"
                "[bgm_raw][sc]sidechaincompress=threshold=0.025:ratio=6:attack=25:release=350[bgm];"
                "[vox][bgm]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[outa]"
            )

        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[outa]",
            "-c:a", "libmp3lame",
            "-b:a", "192k",
            str(output_master_audio),
        ])

        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            logger.warning(f"FFmpeg ducking mix failed ({res.stderr[:200]}), falling back to direct overlay...")
            # Simple overlay fallback
            simple_cmd = [
                "ffmpeg",
                "-y",
                "-i", str(voice_track),
                "-stream_loop", "-1",
                "-i", str(bgm_file),
                "-filter_complex", f"[1:a]volume={duck_vol}[b];[0:a][b]amix=inputs=2:duration=first[out]",
                "-map", "[out]",
                "-c:a", "libmp3lame",
                str(output_master_audio),
            ]
            subprocess.run(simple_cmd, capture_output=True, check=True)

        logger.info(f"Master soundtrack successfully mixed: {output_master_audio}")
        return output_master_audio
