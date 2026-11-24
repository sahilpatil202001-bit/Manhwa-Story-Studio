"""
YouTube Upload & SEO Kit Generator.
Generates dynamic, chapter-specific viral high-CTR titles, structured chapter timestamps,
SEO descriptions, and targeted tags for maximum YouTube reach and audience retention.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from manhwa_studio.logging_config import get_logger
from manhwa_studio.schemas import SceneManifest
from manhwa_studio.studio_pro.series_manager import SeriesProfile

logger = get_logger("manhwa_studio.pro.youtube_kit")


class YouTubeKitGenerator:
    """Generates complete, chapter-specific copy-paste ready YouTube publishing metadata."""

    def __init__(self, profile: SeriesProfile):
        self.profile = profile

    def _get_gemini_api_key(self) -> Optional[str]:
        """Resolve Gemini API key from environment or .env file."""
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            env_file = Path(".env")
            if env_file.exists():
                for line in env_file.read_text(encoding="utf-8").splitlines():
                    if line.startswith("GEMINI_API_KEY="):
                        key = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
        return key

    def fetch_chapter_ai_metadata(self, manifest: SceneManifest) -> Dict[str, any]:
        """
        Query Gemini to generate dynamic, chapter-specific titles, synopsis,
        and story beat titles based on what actually happens in this chapter.
        Falls back to intelligent screenplay analysis if Gemini is offline.
        """
        api_key = self._get_gemini_api_key()
        if not api_key:
            logger.info("No GEMINI_API_KEY found; using dynamic screenplay analysis for YouTube kit.")
            return self._fallback_screenplay_analysis(manifest)

        try:
            from manhwa_studio.story.llm_title_generator import query_gemini_api

            # Sample key dialogue scenes across the chapter
            scenes = manifest.scenes or []
            step = max(1, len(scenes) // 15)
            sample_beats = []
            for i, s in enumerate(scenes[::step][:15]):
                txt = (s.narration_text or s.subtitle_text or "").strip()
                if txt:
                    sample_beats.append(f"Scene {i+1} ({s.speaker or 'Narrator'}): {txt}")

            beats_text = "\n".join(sample_beats)
            prompt = f"""You are a top YouTube viral creator and Hindi manhwa recap strategist.
Series Title: {self.profile.series_name}
Genre: {self.profile.genre}
Chapter: {manifest.chapter}

Here are the key narrative moments from this specific chapter:
{beats_text}

Task:
Generate YouTube publishing metadata tailored SPECIFICALLY to the unique events of Chapter {manifest.chapter}.
Requirements:
1. "titles": Exactly 5 viral, high-CTR YouTube titles (mix of English and conversational Hindi/Hinglish).
   - CRITICAL RULE FOR VIEWS: NEVER put the series name first! The first 45 characters MUST be a shocking curiosity hook / trope (so mobile viewers scrolling YouTube Home click immediately), followed by "| {self.profile.series_name} Ch {manifest.chapter} in Hindi".
   - Examples of tone:
     * "Sabse Khunkhar Sword Saint Ek Bhikhari Ke Badan Mein Zinda Hua?! 🔥 | {self.profile.series_name} Ch {manifest.chapter} in Hindi"
     * "Bina Kisi Darr Ke Sabko Maut Ke Ghaat Utaar Diya?! 😈 | {self.profile.series_name} Chapter {manifest.chapter} Recap"
     * "Sabne Use Kamzor Samjha Par Wo Asli Demon God Nikla! ⚔️ | {self.profile.series_name} Ch {manifest.chapter} Explained"
2. "thumbnail_badges": 3 short, 2-to-3 word UPPERCASE curiosity badges to put on the thumbnail (e.g. ["LEVEL 999?!", "ZINDA HUA?!", "MAUT KA KHEL"]).
3. "synopsis": An emotional, high-tension 2-3 sentence Hindi synopsis for the video description highlighting THIS chapter's unique plot twists.
4. "beat_labels": A list of 6 to 8 short, unique, exciting chapter beat labels in chronological order (e.g. ["Khunkhar Shaitan Ki Talash", "The Cold-Blooded Massacre", "Face-to-Face With Death", "Mok Sword Manor Entry", "Vow of Ultimate Vengeance"]).

Output strictly in valid JSON format with keys: "titles", "thumbnail_badges", "synopsis", "beat_labels".
"""
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "temperature": 0.7,
                },
            }

            res = query_gemini_api(payload, api_key, timeout=25)
            if res:
                data, model_name = res
                raw_json = data["candidates"][0]["content"]["parts"][0]["text"]
                parsed = json.loads(raw_json)
                logger.info(f"Generated dynamic YouTube metadata via Gemini ({model_name}) for Ch.{manifest.chapter}")
                return {
                    "titles": parsed.get("titles", []),
                    "thumbnail_badges": parsed.get("thumbnail_badges", ["LEVEL 999?!", "ASLI SHAITAN!", "MAUT KA KHEL"]),
                    "synopsis": parsed.get("synopsis", ""),
                    "beat_labels": parsed.get("beat_labels", []),
                }
        except Exception as e:
            logger.warning(f"Gemini YouTube metadata generation failed ({e}); falling back to screenplay analyzer.")

        return self._fallback_screenplay_analysis(manifest)

    def _fallback_screenplay_analysis(self, manifest: SceneManifest) -> Dict[str, any]:
        """
        Dynamically construct unique titles, synopsis, and timestamps by analyzing
        the actual words, character names, and climax in this chapter's screenplay.
        """
        series = self.profile.series_name
        ch = manifest.chapter
        scenes = manifest.scenes or []

        # Analyze keywords present in this chapter
        full_text = " ".join([f"{s.narration_text or ''} {s.subtitle_text or ''}" for s in scenes]).lower()

        # Find climax / highest impact scene
        climax_dialogue = ""
        for s in reversed(scenes):
            txt = (s.narration_text or s.subtitle_text or "").strip()
            if any(k in txt for k in ["मार", "मौत", "बदला", "तलवार", "शैतान", "खौफ", "ताकत"]):
                climax_dialogue = txt
                break

        # Detect specific plot themes
        has_revenge = "दादा" in full_text or "बदला" in full_text or "इंसाफ" in full_text
        has_massacre = "मार" in full_text or "लाश" in full_text or "खून" in full_text or "चीख" in full_text
        has_clan = "क्लेन" in full_text or "मैनर" in full_text or "घराना" in full_text or "तलवार" in full_text
        has_psycho = "हंस" in full_text or "पागल" in full_text or "मुस्कान" in full_text or "खौफनाक" in full_text

        titles = []
        if has_psycho and has_massacre:
            titles.append(f"He Smiled While Massacring Dozens?! 😈 | {series} Chapter {ch} in Hindi")
            titles.append(f"Darr Ya Maut? Asli Rakshas Ka Psycho Roop 🔥 | {series} Ch {ch} Hindi Recap")
            titles.append(f"Badla Ya Maut? Asli Khauf Ki Shuruwat! ⚔️ | {series} Chapter {ch} Explained")
        elif has_revenge:
            titles.append(f"Dada Ki Maut Ka Badla! Asli Rakshas Ka Khauf Shuru ⚔️ | {series} Chapter {ch} Recap")
            titles.append(f"Bina Martial Arts Ke Sabko Maut Ke Ghaat Utaar Diya?! 🔥 | {series} Ch {ch} in Hindi")
            titles.append(f"The Vow of Blood & Vengeance! | {series} Chapter {ch} Full Story Explained")
        elif has_clan:
            titles.append(f"Entering The Forbidden Sword Manor! ⚔️ | {series} Chapter {ch} Hindi Recap")
            titles.append(f"The Dark Secret Behind The Clan Massacre! 🔥 | {series} Ch {ch} Explained")
            titles.append(f"{series} Chapter {ch} - The Next Demon Heir Awakens | Hindi Recap")
        else:
            titles.append(f"The Terrifying Rise of The Demon God! 🔥 | {series} Chapter {ch} in Hindi")
            titles.append(f"He Showed No Mercy To His Enemies! ⚔️ | {series} Ch {ch} Hindi Recap")
            titles.append(f"{series} - Chapter {ch} Full Episode Story Explained in Hindi")

        # Dynamic synopsis
        first_scene_text = scenes[0].narration_text if scenes else "Kahani ka naya mod shuru hota hai."
        synopsis = (
            f"{series} ke Chapter {ch} me dekhiye ek behad khaufnaak mod! "
            f"{first_scene_text[:110]}... "
            f"Kya hero is daldal se bach kar apna badla le payega? Janiye is thrilling Hindi recap me!"
        )

        # Dynamic beat labels
        beat_labels = [
            f"Ch.{ch}: The Beginning",
            "A Dangerous Confrontation",
            "The True Face of Terror",
            "Unleashing Hidden Power",
            "Behind The Enemy Lines",
            "The Final Climax Confrontation ⚔️",
        ]

        return {
            "titles": titles,
            "thumbnail_badges": ["LEVEL 999?!", "ASLI SHAITAN!", "MAUT KA KHEL"],
            "synopsis": synopsis,
            "beat_labels": beat_labels,
        }

    def generate_timestamps(
        self,
        manifest: SceneManifest,
        cold_open_duration: float = 0.0,
        beat_labels: Optional[List[str]] = None,
        max_chapters: int = 8,
        speed: float = 1.0,
    ) -> List[Tuple[str, str]]:
        """
        Generate clean, non-repeating YouTube chapter timestamps
        using the dynamic beat labels and exact audio timings (scaled by playback speed).
        """
        timestamps: List[Tuple[str, str]] = []
        spd = max(0.25, float(speed or 1.0))

        current_time = 0.0
        if cold_open_duration > 0.5:
            timestamps.append((self._format_time(0.0), "Teaser Hook 🔥"))
            current_time += cold_open_duration / spd

        if not manifest.scenes:
            timestamps.append((self._format_time(current_time), f"Ch.{manifest.chapter}: Begin"))
            return timestamps

        total_scenes = len(manifest.scenes)
        labels = beat_labels or []

        # If we have AI beat labels, distribute them evenly across the scenes
        num_beats = max(4, min(len(labels), max_chapters)) if labels else min(6, total_scenes)
        step = max(1, total_scenes // num_beats)

        running_time = current_time
        used_labels = set()

        for beat_idx in range(num_beats):
            scene_idx = min(beat_idx * step, total_scenes - 1)
            time_str = self._format_time(running_time)

            if beat_idx == 0:
                beat_title = labels[0] if labels else f"Ch.{manifest.chapter}: The Beginning"
            elif beat_idx < len(labels):
                beat_title = labels[beat_idx]
            else:
                beat_title = f"Story Beat {beat_idx + 1}"

            # Clean up label if it already has "0:00 - " prefix from AI
            beat_title = re.sub(r"^\d+:\d+\s*[-–]\s*", "", beat_title).strip()

            if beat_title not in used_labels:
                timestamps.append((time_str, beat_title))
                used_labels.add(beat_title)

            # Advance running time to the next milestone (scaled by playback speed)
            next_scene_idx = min((beat_idx + 1) * step, total_scenes)
            for sc_i in range(scene_idx, next_scene_idx):
                sc = manifest.scenes[sc_i]
                dur = (sc.actual_audio_duration or sc.duration or 4.0) / spd
                running_time += dur

        return timestamps

    def _format_time(self, seconds: float) -> str:
        """Format seconds into MM:SS or HH:MM:SS format."""
        s = int(seconds)
        m = s // 60
        sec = s % 60
        h = m // 60
        if h > 0:
            m = m % 60
            return f"{h:02d}:{m:02d}:{sec:02d}"
        return f"{m:02d}:{sec:02d}"

    def generate_description(
        self,
        manifest: SceneManifest,
        timestamps: List[Tuple[str, str]],
        synopsis: str,
    ) -> str:
        """Generate a complete SEO-optimized description with timestamps, credits, and links."""
        series = self.profile.series_name
        ch = manifest.chapter

        ts_lines = [f"{time_str} - {title}" for time_str, title in timestamps]
        ts_block = "\n".join(ts_lines)

        clean_series_tag = re.sub(r"[^A-Za-z0-9]", "", series)
        genre_tag = re.sub(r"[^A-Za-z0-9]", "", (self.profile.genre or "Action").title())
        tags = [
            f"#{clean_series_tag}",
            f"#{clean_series_tag}Chapter{ch}",
            "#ManhwaInHindi",
            "#ManhwaRecap",
            "#HindiManhwaExplanation",
            f"#{genre_tag}Manhwa",
            "#AnimeRecapInHindi",
            "#WebtoonHindi",
        ]
        tag_block = " ".join(tags)

        desc = f"""🔥 {series} - Chapter {ch} Full Story Explained in Hindi | Manhwa Recap

{synopsis}

📌 Timestamps:
{ts_block}

⚡ About This Series:
• Series: {series}
• Chapter: {ch}
• Genre: {self.profile.genre.title()} / Action / Martial Arts
• Language: Hindi Dubbed / Conversational Narration

🔔 Subscribe to the channel for upcoming chapters and full-movie marathons!
Leave a LIKE if you enjoyed the recap and drop your favorite moment in the comments below!

📜 Copyright & Fair Use Disclaimer:
All artwork and character illustrations belong to their respective creators, publishers, and manhwa artists. 
This video is created under Fair Use for educational, review, critique, and transformative storytelling purposes.

{tag_block}
"""
        return desc.strip()

    def generate_tags(self, manifest: SceneManifest) -> List[str]:
        """Generate targeted keyword tags for the YouTube tags field."""
        series = self.profile.series_name
        s_clean = series.replace(",", "").lower()
        ch = manifest.chapter
        base_tags = [
            f"{s_clean} hindi",
            f"{s_clean} chapter {ch}",
            f"{s_clean} ch {ch} hindi",
            f"{s_clean} full story",
            f"{s_clean} recap in hindi",
        ]
        for t in (self.profile.thumbnail_tags or []):
            t_low = t.lower()
            if t_low not in base_tags:
                base_tags.append(t_low)
        base_tags.extend([
            "manhwa recap hindi",
            "manhwa in hindi",
            f"best {self.profile.genre.replace('_', ' ')} manhwa in hindi",
            "hindi manhwa recap",
            "manhwa explanation in hindi",
            "action manhwa hindi dubbed",
            "webtoon recap hindi",
            "anime recap hindi",
            "manhwa story studio",
        ])
        return base_tags

    def build_youtube_kit(
        self,
        manifest: SceneManifest,
        output_txt_file: Path,
        cold_open_duration: float = 0.0,
        speed: float = 1.0,
    ) -> Path:
        """Assemble all metadata into a single easy-to-use text file and return the path."""
        logger.info(f"Generating dynamic YouTube Publishing Kit for '{manifest.series}' Chapter {manifest.chapter} (speed={speed}x)...")
        
        # 1. Fetch AI / dynamic metadata specific to this chapter
        ai_data = self.fetch_chapter_ai_metadata(manifest)
        titles = ai_data.get("titles") or [f"{manifest.series} Chapter {manifest.chapter} Full Recap in Hindi"]
        synopsis = ai_data.get("synopsis") or f"{manifest.series} Chapter {manifest.chapter} full story explained in Hindi."
        beat_labels = ai_data.get("beat_labels") or []

        # 2. Build timestamps with dynamic beat labels (scaled by playback speed)
        timestamps = self.generate_timestamps(
            manifest,
            cold_open_duration=cold_open_duration,
            beat_labels=beat_labels,
            speed=speed,
        )

        # 3. Assemble description and tags
        description = self.generate_description(manifest, timestamps, synopsis=synopsis)
        tags = self.generate_tags(manifest)

        # 4. Format into final deliverable
        badges = ai_data.get("thumbnail_badges") or ["LEVEL 999?!", "ASLI SHAITAN!", "MAUT KA KHEL"]
        title_lines = [f"{i+1}) {t}" for i, t in enumerate(titles[:5])]
        badge_lines = " | ".join(f'"{b}"' for b in badges[:3])
        content = f"""================================================================================
                    YOUTUBE PUBLISHING METADATA KIT
Series: {self.profile.series_name} | Chapter: {manifest.chapter}
Generated by Manhwa Story Studio Pro Suite (Chapter-Specific AI Engine)
================================================================================

🎯 RECOMMENDED HIGH-CTR TITLES (Curiosity Hook First for Browse Feed CTR):
{chr(10).join(title_lines)}

🖼️ THUMBNAIL 2-WORD TEXT BADGE IDEAS (Use with tight facial expression zoom):
{badge_lines}

📌 PINNED COMMENT (Copy-paste into Pinned Comment & Shorts Funnel):
🔥 Part {manifest.chapter + 1} aur Full Marathon Movie dekhne ke liye Channel ko SUBSCRIBE karein! Aapka favorite moment kaunsa tha? Comment me batao 👇⚔️

--------------------------------------------------------------------------------
📝 DESCRIPTION (Copy & paste into YouTube Video Description):
--------------------------------------------------------------------------------
{description}

--------------------------------------------------------------------------------
🏷️ TAGS (Comma-separated, copy-paste into YouTube Studio Tags box):
--------------------------------------------------------------------------------
{', '.join(tags)}

================================================================================
"""
        output_txt_file.parent.mkdir(parents=True, exist_ok=True)
        output_txt_file.write_text(content, encoding="utf-8")
        logger.info(f"Saved complete dynamic YouTube Upload Kit to: {output_txt_file}")
        return output_txt_file

    def _collect_marathon_story_beats(
        self,
        chapter_nums: List[int],
        projects_base_dir: Optional[Path] = None,
    ) -> List[str]:
        """Sample key narration/dialogue beats across all chapters in a marathon range."""
        base_dir = projects_base_dir or (Path("data") / "projects")
        slug = self.profile.series_slug or re.sub(r"[^a-z0-9]+", "_", self.profile.series_name.lower()).strip("_")
        beats: List[str] = []

        for ch in chapter_nums:
            manifest_path = base_dir / slug / f"chapter_{ch:03d}" / "scripts" / "scene_manifest.json"
            if not manifest_path.exists():
                continue
            try:
                manifest = SceneManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
                scenes = manifest.scenes or []
                if not scenes:
                    continue
                step = max(1, len(scenes) // 3)
                for s in scenes[::step][:3]:
                    txt = (s.narration_text or s.subtitle_text or "").strip()
                    if txt:
                        beats.append(f"Ch.{ch}: {txt[:180]}")
            except Exception:
                continue
        return beats

    def fetch_marathon_ai_metadata(
        self,
        chapter_nums: List[int],
        projects_base_dir: Optional[Path] = None,
    ) -> Dict[str, any]:
        """
        Generate dynamic, series- and arc-specific Marathon titles, synopsis, badges, and hashtags
        from the actual chapter `scene_manifest.json` files (via Gemini, with screenplay fallback).
        """
        series = self.profile.series_name
        ch_start = chapter_nums[0] if chapter_nums else 1
        ch_end = chapter_nums[-1] if chapter_nums else 1
        beats = self._collect_marathon_story_beats(chapter_nums, projects_base_dir=projects_base_dir)
        api_key = self._get_gemini_api_key()

        if api_key and beats:
            try:
                from manhwa_studio.story.llm_title_generator import query_gemini_api

                beats_text = "\n".join(beats[:18])
                prompt = f"""You are a top YouTube viral creator and Hindi manhwa marathon strategist.
Series Title: {series}
Genre: {self.profile.genre}
Chapters Covered: Chapter {ch_start} to Chapter {ch_end}

Here are key narrative moments from these chapters:
{beats_text}

Task:
Generate YouTube publishing metadata tailored SPECIFICALLY to {series} (Chapters {ch_start} to {ch_end}).
Do NOT copy tropes from other series — base everything strictly on the story beats above.
Requirements:
1. "titles": Exactly 5 viral, high-CTR YouTube Marathon titles (mix of English & conversational Hindi/Hinglish).
   - First 45 characters MUST be a shocking curiosity hook from THESE chapters, followed by "| {series} Ch {ch_start}–{ch_end} Full Movie in Hindi".
2. "thumbnail_badges": 3 short 2-3 word UPPERCASE badges for the thumbnail.
3. "synopsis": An engaging 3-4 sentence Hindi synopsis summarizing the actual plot arc of Chapters {ch_start} to {ch_end} of {series}.
4. "hashtags": 6 to 8 relevant hashtags (e.g. #{re.sub(r'[^A-Za-z0-9]', '', series)}, #ManhwaInHindi, #ManhwaFullMovie, etc.).

Output strictly in valid JSON with keys: "titles", "thumbnail_badges", "synopsis", "hashtags".
"""
                payload = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"responseMimeType": "application/json", "temperature": 0.7},
                }
                res = query_gemini_api(payload, api_key, timeout=25)
                if res:
                    data, model_name = res
                    parsed = json.loads(data["candidates"][0]["content"]["parts"][0]["text"])
                    logger.info(f"Generated dynamic Marathon YouTube metadata via Gemini ({model_name}) for {series} Ch.{ch_start}-{ch_end}")
                    return parsed
            except Exception as e:
                logger.warning(f"Gemini Marathon metadata failed ({e}); using dynamic screenplay fallback.")

        # Dynamic screenplay fallback (never hardcoded to another series)
        clean_tag = re.sub(r"[^A-Za-z0-9]", "", series)
        genre_label = (self.profile.genre or "Action").replace("_", " ").title()
        genre_tag = re.sub(r"[^A-Za-z0-9]", "", genre_label)
        hook_snippet = beats[0].split(":", 1)[-1].strip()[:120] if beats else f"{series} ki dhamakedar shuruwat"
        climax_snippet = beats[-1].split(":", 1)[-1].strip()[:120] if len(beats) > 1 else "ek zabardast cliffhanger aur action-packed mod"

        titles = [
            f"Ek Aisi Kahani Jo Aapke Hosh Uda Degi! 🔥 | {series} Ch {ch_start}–{ch_end} Full Movie in Hindi",
            f"Shuruwat Se Ant Tak Non-Stop Action & Twist! ⚡ | {series} (Ch {ch_start}–{ch_end}) Hindi Marathon",
            f"Kya Hero Apne Sabse Bade Challenge Ko Jeet Payega?! 🤯 | {series} Full Story Explained in Hindi",
            f"Zero Se Hero Tak Ka Sabse Khatarnak Safar! ⚔️ | {series} Ch {ch_start}–{ch_end} Hindi Dub",
            f"Watch The Complete Epic Arc Without Any Breaks! 💀 | {series} Chapters {ch_start}–{ch_end} Movie",
        ]
        synopsis = (
            f"Is full-length Hindi Manhwa Movie me dekhiye {series} ke Chapter {ch_start} se Chapter {ch_end} tak ki poori kahani ek saath! "
            f"Kahani ki shuruwat hoti hai jab {hook_snippet}... aur aage chal kar {climax_snippet}... "
            f"Pura {genre_label} marathon end tak zaroor dekhein aur batayein aapka favorite scene kaunsa tha!"
        )
        hashtags = [
            f"#{clean_tag}",
            f"#{clean_tag}Ch{ch_start}To{ch_end}",
            "#ManhwaInHindi",
            "#ManhwaFullMovie",
            "#ManhwaRecapHindi",
            f"#{genre_tag}Manhwa",
            "#AnimeRecapHindi",
        ]
        return {
            "titles": titles,
            "thumbnail_badges": ["FULL MOVIE 🔥", f"CH {ch_start}–{ch_end}", "NON-STOP ⚡"],
            "synopsis": synopsis,
            "hashtags": hashtags,
        }

    def build_marathon_youtube_kit(
        self,
        chapter_nums: List[int],
        timestamps: List[Tuple[str, str]],
        output_txt_file: Path,
        total_duration_mins: float = 0.0,
        projects_base_dir: Optional[Path] = None,
    ) -> Path:
        """
        Generate a complete, dynamic viral YouTube Upload Kit specifically optimized for Long / Marathon Videos
        (Series-specific AI/Screenplay Titles, Synopsis, Clickable Timestamps, Hashtags, and SEO Tags).
        """
        series = self.profile.series_name
        s_clean = series.replace(",", "").lower()
        ch_start = chapter_nums[0] if chapter_nums else 1
        ch_end = chapter_nums[-1] if chapter_nums else 1
        ch_range = f"Chapters {ch_start} to {ch_end}"

        ai_data = self.fetch_marathon_ai_metadata(chapter_nums, projects_base_dir=projects_base_dir)
        titles = ai_data.get("titles") or [f"{series} ({ch_range}) Full Movie Explained in Hindi"]
        synopsis = ai_data.get("synopsis") or f"{series} ({ch_range}) full story explained in Hindi."
        badges = ai_data.get("thumbnail_badges") or ["FULL MOVIE 🔥", f"CH {ch_start}–{ch_end}", "NON-STOP ⚡"]
        hashtags = ai_data.get("hashtags") or [
            f"#{re.sub(r'[^A-Za-z0-9]', '', series)}",
            "#ManhwaInHindi",
            "#ManhwaFullMovie",
            "#ManhwaRecapHindi",
        ]

        ts_lines = [f"{t_str} - {label}" for t_str, label in timestamps]
        if not ts_lines or not ts_lines[0].startswith("00:00"):
            ts_lines.insert(0, f"00:00 - Chapter {ch_start}: The Story Begins 🔥")
        ts_block = "\n".join(ts_lines)

        genre_clean = (self.profile.genre or "action").replace("_", " ").lower()
        tags = [
            f"{s_clean} full movie in hindi",
            f"{s_clean} chapter {ch_start} to {ch_end} in hindi",
            f"{s_clean} marathon hindi",
            f"{s_clean} explained in hindi",
            "manhwa full movie in hindi",
            "manhwa marathon hindi",
            "manhwa recap in hindi",
            "new manhwa explained in hindi",
            f"best {genre_clean} manhwa in hindi",
            "anime recap hindi",
        ]
        for t in (self.profile.thumbnail_tags or []):
            t_low = t.lower()
            if t_low not in tags:
                tags.append(t_low)

        title_lines = "\n".join(f"{i+1}) {t}" for i, t in enumerate(titles[:5]))
        badge_lines = " | ".join(f'"{b}"' for b in badges[:3])
        hashtag_line = " ".join(hashtags)
        content = f"""================================================================================
                MARATHON MOVIE YOUTUBE PUBLISHING METADATA KIT
Series: {series} | {ch_range} ({total_duration_mins:.1f} mins)
Generated by Manhwa Story Studio Pro Suite (Dynamic Marathon Retention Engine)
================================================================================

🎯 5 VIRAL MARATHON TITLES (Hook in First 45 Chars for Maximum Home/Browse CTR):
{title_lines}

🖼️ THUMBNAIL 2-WORD BADGE IDEAS (Place next to close-up glowing eyes/face):
{badge_lines}

📌 PINNED COMMENT & SHORTS FUNNEL (Pin this comment on both Marathon & Shorts):
🔥 Next Part (Chapter {ch_end + 1}+) jaldi aane wala hai! Abhi SUBSCRIBE karein aur comment me "PART 2" likhein! 👇⚔️

--------------------------------------------------------------------------------
📝 DESCRIPTION (Copy & paste into YouTube Video Description):
--------------------------------------------------------------------------------
🔥 {series} ({ch_range}) Full Movie Story Explained in Hindi | Seamless Marathon Recap

{synopsis}

📌 Clickable Chapter Timestamps:
{ts_block}

⚡ About This Marathon:
• Series: {series}
• Chapters Covered: {ch_range}
• Audio: High-Energy Conversational Hindi Narration
• Genre: {self.profile.genre.replace('_', ' ').title()} / Manhwa Recap

{hashtag_line}

--------------------------------------------------------------------------------
🏷️ TAGS (Comma-separated, copy-paste into YouTube Studio Tags box):
--------------------------------------------------------------------------------
{', '.join(tags)}
================================================================================
"""
        output_txt_file.parent.mkdir(parents=True, exist_ok=True)
        output_txt_file.write_text(content, encoding="utf-8")
        logger.info(f"Saved Marathon YouTube Upload Kit to: {output_txt_file}")
        return output_txt_file
