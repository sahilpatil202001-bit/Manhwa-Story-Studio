"""
Series Profile Manager: Handles multi-manhwa series configurations, genres,
voice casting rosters, BGM palettes, and visual branding presets.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml
from pydantic import BaseModel, Field

from manhwa_studio.logging_config import get_logger

logger = get_logger("manhwa_studio.pro.series")


class VoiceSetting(BaseModel):
    provider: str = "gemini"  # "gemini" or "edge-tts"
    voice_id: str = "gemini:Puck"
    rate: str = "+2%"
    pitch: str = "+0Hz"
    volume: str = "+0%"
    description: str = "Gemini Indian Human: Puck (Young Expressive Hero)"


class SubtitleStyle(BaseModel):
    font_name: str = "Arial"
    font_size: int = 44
    primary_color: str = "&H00FFFFFF"      # White
    secondary_color: str = "&H0000FFFF"    # Yellow highlight
    outline_color: str = "&H00000000"      # Black
    back_color: str = "&H80000000"         # Semi-transparent black shadow
    outline_width: int = 4
    shadow_depth: int = 2
    bold: bool = True
    pop_animation: bool = True


class SeriesProfile(BaseModel):
    series_name: str
    series_slug: str
    genre: str = Field(default="murim", description="murim, system_hunter, dark_fantasy, romance_isekai, modern_action")
    tone: str = Field(default="dark", description="dark, heroic, intense, emotional, comedic")
    narrator_voice: VoiceSetting = Field(
        default_factory=lambda: VoiceSetting(
            provider="gemini",
            voice_id="gemini:Puck",
            rate="+2%",
            pitch="+0Hz",
            description="Gemini Indian Human: Puck (Young Expressive Hero)"
        )
    )
    character_voices: Dict[str, VoiceSetting] = Field(
        default_factory=dict,
        description="Explicit mapping from character name or alias to VoiceSetting"
    )
    archetype_voices: Dict[str, VoiceSetting] = Field(
        default_factory=lambda: {
            "hero_male": VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+2%", pitch="+0Hz", description="Young heroic Indian male protagonist - Puck (+2%, +0Hz)"),
            "hero_young": VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+2%", pitch="+0Hz", description="Teenage/young Indian male protagonist - Puck"),
            "rival_cool": VoiceSetting(provider="gemini", voice_id="gemini:Charon", rate="+0%", pitch="+0Hz", description="Cool stoic swordsman / knight - Charon"),
            "schemer_witty": VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+2%", pitch="+0Hz", description="Cunning, witty, charismatic young Indian lead - Puck"),
            "female_lead": VoiceSetting(provider="gemini", voice_id="gemini:Aoede", rate="+2%", pitch="+0Hz", description="Expressive young woman / female lead - Aoede"),
            "female_young": VoiceSetting(provider="gemini", voice_id="gemini:Leda", rate="+4%", pitch="+0Hz", description="Bright youthful girl / teen / spirit - Leda"),
            "elder_master": VoiceSetting(provider="gemini", voice_id="gemini:Fenrir", rate="-2%", pitch="+0Hz", description="Veteran master / clan leader - Fenrir"),
            "villain_dark": VoiceSetting(provider="gemini", voice_id="gemini:Fenrir", rate="-2%", pitch="+0Hz", description="Dangerous antagonist / assassin - Fenrir"),
            "crowd_guard": VoiceSetting(provider="gemini", voice_id="gemini:Charon", rate="+0%", pitch="+0Hz", description="Guards / soldiers / disciples - Charon"),
            "system_ai": VoiceSetting(provider="gemini", voice_id="gemini:Zephyr", rate="+2%", pitch="+0Hz", description="Crisp AI / System interface - Zephyr"),
        }
    )
    bgm_genre: str = "murim_traditional"
    bgm_ducking_volume: float = 0.12  # BGM volume during speech (0.0 to 1.0)
    bgm_normal_volume: float = 0.35   # BGM volume during silence/transition
    subtitle_style: SubtitleStyle = Field(default_factory=SubtitleStyle)
    thumbnail_tags: List[str] = Field(default_factory=lambda: ["हिन्दी Manhwa", "Comic Dub", "Full Recap"])


class SeriesManager:
    """Manages creation, storage, and retrieval of Series Profiles for diverse manhwa titles."""

    def __init__(self, profiles_dir: Optional[Path] = None):
        self.profiles_dir = profiles_dir or (Path("configs") / "series_profiles")
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        self.global_defaults_file = self.profiles_dir.parent / "global_voice_defaults.yaml"
        self._ensure_default_templates()

    def get_global_voice_defaults(self) -> Dict[str, Any]:
        """Dynamically load active global voice & BGM defaults for any new manhwa."""
        defaults: Dict[str, Any] = {
            "narrator_voice_id": "gemini:Puck",
            "narrator_rate": "+2%",
            "narrator_pitch": "+0Hz",
            "protagonist_voice_id": "gemini:Puck",
            "protagonist_rate": "+2%",
            "protagonist_pitch": "+0Hz",
            "bgm_ducking_volume": 0.12,
            "bgm_normal_volume": 0.35,
        }
        if self.global_defaults_file.exists():
            try:
                loaded = yaml.safe_load(self.global_defaults_file.read_text(encoding="utf-8")) or {}
                if isinstance(loaded, dict):
                    defaults.update({k: v for k, v in loaded.items() if v is not None})
            except Exception as exc:
                logger.warning(f"Failed to read global_voice_defaults.yaml: {exc}")
        return defaults

    def save_global_voice_defaults(
        self,
        voice_id: str,
        rate: str = "+2%",
        pitch: str = "+0Hz",
        bgm_ducking_volume: float = 0.12,
        bgm_normal_volume: float = 0.35,
    ) -> None:
        """Persist new global voice & BGM defaults so future manhwas inherit them dynamically."""
        data = {
            "narrator_voice_id": voice_id,
            "narrator_rate": rate,
            "narrator_pitch": pitch,
            "protagonist_voice_id": voice_id,
            "protagonist_rate": rate,
            "protagonist_pitch": pitch,
            "bgm_ducking_volume": float(bgm_ducking_volume),
            "bgm_normal_volume": float(bgm_normal_volume),
        }
        self.global_defaults_file.parent.mkdir(parents=True, exist_ok=True)
        self.global_defaults_file.write_text(
            yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

    def _ensure_default_templates(self) -> None:
        """Create standard genre template profiles if they don't already exist."""
        templates = {
            "the_greatest_estate_developer": SeriesProfile(
                series_name="The Greatest Estate Developer",
                series_slug="the_greatest_estate_developer",
                genre="fantasy_comedy",
                tone="witty_comedic_charismatic",
                bgm_genre="fantasy_adventure",
                narrator_voice=VoiceSetting(
                    provider="gemini",
                    voice_id="gemini:Puck",
                    rate="+2%",
                    pitch="+0Hz",
                    description="Gemini Indian Human: Puck (Young Expressive Hero)"
                ),
                character_voices={
                    "Lloyd": VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+2%", pitch="+0Hz", description="Lloyd Frontera (Kim Suho) - Gemini Indian Human: Puck"),
                    "Lloyd Frontera": VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+2%", pitch="+0Hz", description="Lloyd Frontera"),
                    "Kim Suho": VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+2%", pitch="+0Hz", description="Kim Suho"),
                    "Javier": VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+2%", pitch="+0Hz", description="Javier Asrahan (Puck)"),
                    "Javier Asrahan": VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+2%", pitch="+0Hz", description="Javier Asrahan"),
                    "Alicia": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+2%", pitch="+0Hz", description="Queen Alicia Termina - regal monarch (Kore)"),
                    "Podong": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+2%", pitch="+0Hz", description="Cute summoned elemental spirit (Kore)"),
                    "Poby": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+2%", pitch="+0Hz", description="Cute summoned elemental spirit (Kore)"),
                    "Count Frontera": VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+2%", pitch="+0Hz", description="Count Arcos Frontera (Puck)"),
                    "Countess Frontera": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+2%", pitch="+0Hz", description="Countess Frontera (Kore)"),
                    "Julien": VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+2%", pitch="+0Hz", description="Julien Frontera (Puck)"),
                },
            ),
            "murim_martial_arts": SeriesProfile(
                series_name="Murim Martial Arts Template",
                series_slug="murim_template",
                genre="murim",
                tone="intense",
                bgm_genre="murim_traditional",
                narrator_voice=VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+2%", pitch="+0Hz", description="Gemini Indian Human: Puck (+2%, +0Hz)"),
                character_voices={
                    "Mok Gyeongwun": VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+2%", pitch="+0Hz", description="First Heavenly Demon"),
                    "Cheon Ma": VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+2%", pitch="+0Hz", description="Heavenly Demon Sovereign"),
                    "Grandfather": VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+2%", pitch="+0Hz", description="Wise Grandfather"),
                },
            ),
            "system_hunter_rpg": SeriesProfile(
                series_name="System / Hunter RPG Template",
                series_slug="system_hunter_template",
                genre="system_hunter",
                tone="heroic",
                bgm_genre="epic_synthwave",
                narrator_voice=VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+2%", pitch="+0Hz", description="Gemini Indian Human: Puck (+2%, +0Hz)"),
                character_voices={
                    "System": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+2%", pitch="+0Hz", description="System Notification Indian AI"),
                },
            ),
            "dark_fantasy_revenge": SeriesProfile(
                series_name="Dark Fantasy / Revenge Template",
                series_slug="dark_fantasy_template",
                genre="dark_fantasy",
                tone="dark",
                bgm_genre="dark_cinematic",
                narrator_voice=VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+2%", pitch="+0Hz", description="Gemini Indian Human: Puck (+2%, +0Hz)"),
                character_voices={
                    "Antagonist": VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+2%", pitch="+0Hz", description="Sinister villain"),
                },
            ),
            "romance_villainess": SeriesProfile(
                series_name="Romance / Otome Villainess Template",
                series_slug="romance_villainess_template",
                genre="romance_isekai",
                tone="dramatic",
                bgm_genre="emotional_orchestral",
                narrator_voice=VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+2%", pitch="+0Hz", description="Gemini Indian Human: Puck (+2%, +0Hz)"),
                character_voices={
                    "Duke": VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+2%", pitch="+0Hz", description="Suave romantic male lead"),
                },
            ),
        }

        for slug, profile in templates.items():
            profile.series_slug = slug
            self.apply_genre_default_roster(profile)
            p_file = self.profiles_dir / f"{slug}.yaml"
            if not p_file.exists():
                self.save_profile(profile, p_file)

    def _slugify(self, name: str) -> str:
        import re
        return re.sub(r"[^a-zA-Z0-9]+", "_", name.strip()).lower().strip("_")

    def save_profile(self, profile: SeriesProfile, target_path: Optional[Path] = None) -> Path:
        """Persist a series profile to YAML."""
        out_path = target_path or (self.profiles_dir / f"{profile.series_slug}.yaml")
        data = profile.model_dump()
        out_path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
        logger.info(f"Saved series profile for '{profile.series_name}' to {out_path}")
        return out_path

    def load_profile(self, series_slug: str) -> Optional[SeriesProfile]:
        """Load a profile by its slug name and dynamically sync with global voice defaults."""
        p_file = self.profiles_dir / f"{series_slug}.yaml"
        if not p_file.exists():
            # Try fuzzy match in profiles directory
            for f in self.profiles_dir.glob("*.yaml"):
                if f.stem.lower() == series_slug.lower() or series_slug.lower() in f.stem.lower():
                    p_file = f
                    break

        if not p_file.exists():
            return None

        try:
            content = yaml.safe_load(p_file.read_text(encoding="utf-8"))
            prof = SeriesProfile(**content)
            g_def = self.get_global_voice_defaults()
            target_male_vid = str(g_def.get("narrator_voice_id", "gemini:Puck"))
            target_male_rate = str(g_def.get("narrator_rate", "+2%"))
            target_male_pitch = str(g_def.get("narrator_pitch", "+0Hz"))
            changed = False

            if prof.narrator_voice.voice_id != target_male_vid or prof.narrator_voice.provider != "gemini":
                prof.narrator_voice.provider = "gemini" if target_male_vid.startswith("gemini:") else "edge-tts"
                prof.narrator_voice.voice_id = target_male_vid
                prof.narrator_voice.rate = target_male_rate
                prof.narrator_voice.pitch = target_male_pitch
                changed = True

            # Preserve distinct per-character and archetype voices (never overwrite them to a single voice)
            if changed:
                self.save_profile(prof, p_file)
            return prof
        except Exception as e:
            logger.error(f"Failed to load series profile from {p_file}: {e}")
            return None

    def get_or_create_profile(self, series_name: str, genre: str = "murim") -> SeriesProfile:
        """Get existing profile for series or create a tailored one automatically."""
        import re
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", series_name.strip()).lower().strip("_")
        existing = self.load_profile(slug)
        if existing:
            return existing

        # Create tailored profile based on series name and genre
        profile = SeriesProfile(
            series_name=series_name,
            series_slug=slug,
            genre=genre,
        )

        # Pre-seed specific known series like The Greatest Estate Developer
        if "estate" in slug or "developer" in slug or "lloyd" in slug:
            profile.series_name = "The Greatest Estate Developer"
            profile.genre = "fantasy_comedy"
            profile.tone = "witty_comedic_charismatic"
            profile.bgm_genre = "fantasy_adventure"
            profile.narrator_voice = VoiceSetting(
                provider="gemini",
                voice_id="gemini:Puck",
                rate="+2%",
                pitch="+0Hz",
                description="Gemini Indian Human: Puck (Young Expressive Hero)"
            )
            profile.character_voices = {
                "Lloyd": VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+2%", pitch="+0Hz", description="Lloyd Frontera (Kim Suho) - Gemini Indian Human: Puck"),
                "Lloyd Frontera": VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+2%", pitch="+0Hz", description="Lloyd Frontera"),
                "Kim Suho": VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+2%", pitch="+0Hz", description="Kim Suho"),
                "Javier": VoiceSetting(provider="gemini", voice_id="gemini:Charon", rate="+0%", pitch="+0Hz", description="Javier Asrahan - stoic, calm Grand Swordmaster (Charon)"),
                "Javier Asrahan": VoiceSetting(provider="gemini", voice_id="gemini:Charon", rate="+0%", pitch="+0Hz", description="Javier Asrahan"),
                "Alicia": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+0%", pitch="+0Hz", description="Queen Alicia Termina - regal monarch (Kore)"),
                "Queen": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+0%", pitch="+0Hz", description="Queen - regal dignified monarch (Kore)"),
                "Podong": VoiceSetting(provider="gemini", voice_id="gemini:Aoede", rate="+4%", pitch="+0Hz", description="Cute summoned elemental spirit (Aoede)"),
                "Poby": VoiceSetting(provider="gemini", voice_id="gemini:Aoede", rate="+4%", pitch="+0Hz", description="Cute summoned elemental spirit (Aoede)"),
                "Count Frontera": VoiceSetting(provider="gemini", voice_id="gemini:Charon", rate="+0%", pitch="+0Hz", description="Count Arcos Frontera (Charon)"),
                "Countess Frontera": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+0%", pitch="+0Hz", description="Countess Frontera (Kore)"),
                "Julien": VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+2%", pitch="+0Hz", description="Julien Frontera (Puck)"),
                "Lady": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+0%", pitch="+0Hz", description="Noble lady / noblewoman (Kore)"),
                "Girl": VoiceSetting(provider="gemini", voice_id="gemini:Aoede", rate="+2%", pitch="+0Hz", description="Young girl / maid / servant girl (Aoede)"),
                "Maid": VoiceSetting(provider="gemini", voice_id="gemini:Aoede", rate="+2%", pitch="+0Hz", description="Maid / servant (Aoede)"),
                "Woman": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+0%", pitch="+0Hz", description="Generic adult woman (Kore)"),
                "Princess": VoiceSetting(provider="gemini", voice_id="gemini:Aoede", rate="+2%", pitch="+0Hz", description="Princess (Aoede)"),
                "Mother": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+0%", pitch="+0Hz", description="Mother / maternal figure (Kore)"),
                "Duchess": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+0%", pitch="+0Hz", description="Duchess / high noblewoman (Kore)"),
                "Noblewoman": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+0%", pitch="+0Hz", description="Noblewoman (Kore)"),
                "Servant": VoiceSetting(provider="gemini", voice_id="gemini:Aoede", rate="+2%", pitch="+0Hz", description="Female servant / attendant (Aoede)"),
            }
        # Pre-seed specific known series like Myst, Might, Mayhem
        elif "myst" in slug and "mayhem" in slug:
            profile.genre = "murim"
            profile.tone = "dark"
            profile.narrator_voice = VoiceSetting(
                provider="gemini",
                voice_id="gemini:Puck",
                rate="+2%",
                pitch="+0Hz",
                description="Gemini Indian Human: Puck (+2%, +0Hz)"
            )
            profile.character_voices["Mok Gyeongwun"] = VoiceSetting(
                provider="gemini", voice_id="gemini:Puck", rate="+2%", pitch="+0Hz", description="Cold, calculative young Indian protagonist"
            )
            profile.character_voices["Cheon Ma"] = VoiceSetting(
                provider="gemini", voice_id="gemini:Charon", rate="+0%", pitch="+0Hz", description="Heavenly Demon form"
            )
            profile.character_voices["Grandfather"] = VoiceSetting(
                provider="gemini", voice_id="gemini:Charon", rate="+0%", pitch="+0Hz", description="Elder / Grandfather"
            )
            profile.character_voices["Young Woman"] = VoiceSetting(
                provider="gemini", voice_id="gemini:Kore", rate="+0%", pitch="+0Hz", description="Female survivor"
            )
            profile.character_voices["Girl"] = VoiceSetting(
                provider="gemini", voice_id="gemini:Aoede", rate="+2%", pitch="+0Hz", description="Young girl"
            )
            profile.character_voices["Lady"] = VoiceSetting(
                provider="gemini", voice_id="gemini:Kore", rate="+0%", pitch="+0Hz", description="Noble lady / woman"
            )
            profile.character_voices["Woman"] = VoiceSetting(
                provider="gemini", voice_id="gemini:Kore", rate="+0%", pitch="+0Hz", description="Adult female character"
            )
            profile.character_voices["Mother"] = VoiceSetting(
                provider="gemini", voice_id="gemini:Kore", rate="+0%", pitch="+0Hz", description="Mother / elder woman"
            )
            profile.character_voices["Noblewoman"] = VoiceSetting(
                provider="gemini", voice_id="gemini:Kore", rate="+0%", pitch="+0Hz", description="Noblewoman"
            )
        # Pre-seed Nano Machine
        elif "nano" in slug and "machine" in slug:
            profile.series_name = "Nano Machine"
            profile.genre = "murim"
            profile.tone = "dark_heroic_intense"
            profile.bgm_genre = "murim_traditional"
            profile.narrator_voice = VoiceSetting(
                provider="gemini",
                voice_id="gemini:Puck",
                rate="+2%",
                pitch="+0Hz",
                description="Gemini Indian Human: Puck (+2%, +0Hz)"
            )
            profile.character_voices = {
                # Nano Machine (System AI) - Attractive, Classy Indian Female Assistant (Kore)
                "Nano": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+2%", pitch="+0Hz", description="Nano Machine - natural, classy Indian female AI assistant"),
                "Nano (Normal)": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+2%", pitch="+0Hz", description="Nano Machine - sleek, charming Indian guide"),
                "Nano (Warning)": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+5%", pitch="+0Hz", description="Nano Machine - urgent high-energy alert"),
                "Nano (Emergency)": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+5%", pitch="+0Hz", description="Nano Machine - emergency danger alert"),
                "Nano (Analysis)": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+3%", pitch="+0Hz", description="Nano Machine - fast meridian & martial scan"),
                "Nano (Combat)": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+4%", pitch="+0Hz", description="Nano Machine - rapid combat simulation"),
                "System": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+2%", pitch="+0Hz", description="Nano Machine AI interface"),
                "System (Warning)": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+5%", pitch="+0Hz", description="System Emergency Alert"),
                "System (Analysis)": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+3%", pitch="+0Hz", description="System Medical & Martial Analysis"),
                # Cheon Yeo-Woon (Protagonist) - Gemini Indian Human: Puck (+2%, +0Hz)
                "Cheon Yeo-Woon": VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+2%", pitch="+0Hz", description="Cheon Yeo-Woon - Gemini Indian Human: Puck"),
                "Cheon Yeo-Woon (Normal)": VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+2%", pitch="+0Hz", description="Cheon Yeo-Woon - sharp & composed young master"),
                "Cheon Yeo-Woon (Cold)": VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+1%", pitch="+0Hz", description="Cheon Yeo-Woon - cold, sharp, fearless aura"),
                "Cheon Yeo-Woon (Ruthless)": VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+1%", pitch="+0Hz", description="Cheon Yeo-Woon - ruthless dominance"),
                "Cheon Yeo-Woon (Wounded)": VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+5%", pitch="+0Hz", description="Cheon Yeo-Woon - intense battle strain"),
                "Cheon Yeo-Woon (Pain)": VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+5%", pitch="+0Hz", description="Cheon Yeo-Woon - meridian reconstruction"),
                "Cheon Yeo-Woon (Enraged)": VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+6%", pitch="+0Hz", description="Cheon Yeo-Woon - explosive battle shout"),
                "Cheon Yeo-Woon (Respectful)": VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+2%", pitch="+0Hz", description="Cheon Yeo-Woon - warm & respectful"),
                "Yeo-Woon": VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+2%", pitch="+0Hz", description="Cheon Yeo-Woon"),
                "Yeowun": VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+2%", pitch="+0Hz", description="Cheon Yeo-Woon"),
                "Guard Jang": VoiceSetting(provider="gemini", voice_id="gemini:Charon", rate="+0%", pitch="+0Hz", description="Guard Jang - loyal Indian Hinglish swordsman"),
                "Guard Jang (Wounded)": VoiceSetting(provider="gemini", voice_id="gemini:Charon", rate="+4%", pitch="+0Hz", description="Guard Jang - urgent battle shout"),
                "Sub-Meng": VoiceSetting(provider="gemini", voice_id="gemini:Fenrir", rate="+2%", pitch="+0Hz", description="Sub-Meng - energetic muscular ally"),
                "Cadet": VoiceSetting(provider="gemini", voice_id="gemini:Fenrir", rate="+2%", pitch="+0Hz", description="Young Academy Cadet / Rival"),
                "Instructor": VoiceSetting(provider="gemini", voice_id="gemini:Charon", rate="+0%", pitch="+0Hz", description="Demonic Academy Instructor"),
                "Lord": VoiceSetting(provider="gemini", voice_id="gemini:Charon", rate="+0%", pitch="+0Hz", description="Lord of the Demonic Cult"),
                "Lord Cheon": VoiceSetting(provider="gemini", voice_id="gemini:Charon", rate="+0%", pitch="+0Hz", description="Lord Cheon Yujong - Supreme Demon Lord"),
                "Grand Guardian": VoiceSetting(provider="gemini", voice_id="gemini:Charon", rate="+0%", pitch="+0Hz", description="Grand Guardian Marakim"),
                "Elder": VoiceSetting(provider="gemini", voice_id="gemini:Charon", rate="+0%", pitch="+0Hz", description="Clan Elder"),
                "Assassin": VoiceSetting(provider="gemini", voice_id="gemini:Fenrir", rate="+2%", pitch="+0Hz", description="Masked Assassin / Enemy"),
                "Lady Hwa": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+0%", pitch="+0Hz", description="Lady Hwa (Mother)"),
                "Mun Ku": VoiceSetting(provider="gemini", voice_id="gemini:Aoede", rate="+2%", pitch="+0Hz", description="Mun Ku - lively, energetic young Indian heroine"),
                "Lady Mun": VoiceSetting(provider="gemini", voice_id="gemini:Aoede", rate="+2%", pitch="+0Hz", description="Mun Ku - lively young heroine"),
                "Girl": VoiceSetting(provider="gemini", voice_id="gemini:Aoede", rate="+2%", pitch="+0Hz", description="Young female disciple"),
                "Lady": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+0%", pitch="+0Hz", description="Noble lady / martial artist"),
                "Woman": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+0%", pitch="+0Hz", description="Female character"),
                "Mother": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+0%", pitch="+0Hz", description="Mother / maternal figure"),
                "Noblewoman": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+0%", pitch="+0Hz", description="Noblewoman of the Demonic Cult"),
            }
            profile.thumbnail_tags = ["नैनो मशीन", "Nano Machine Hindi", "Demonic Cult", "Full Recap"]
        # Pre-seed My Girlfriend Returned as a Dragon
        elif ("girlfriend" in slug and "dragon" in slug) or "dragon_girlfriend" in slug:
            profile.series_name = "My Girlfriend Returned as a Dragon"
            profile.genre = "urban_fantasy_romance"
            profile.tone = "romantic_comedic_action"
            profile.bgm_genre = "epic_fantasy_romance"
            profile.narrator_voice = VoiceSetting(
                provider="gemini",
                voice_id="gemini:Puck",
                rate="+2%",
                pitch="+0Hz",
                description="Gemini Indian Human: Puck (+2%, +0Hz)"
            )
            profile.character_voices = {
                "Boy": VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+2%", pitch="+0Hz", description="Boyfriend - normal conversational"),
                "Boy (Normal)": VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+2%", pitch="+0Hz", description="Boyfriend - normal"),
                "Boy (Shocked)": VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+6%", pitch="+0Hz", description="Boyfriend - terrified panic at dragon power"),
                "Boy (Panicked)": VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+6%", pitch="+0Hz", description="Boyfriend - panicked"),
                "Boy (Romantic)": VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+1%", pitch="+0Hz", description="Boyfriend - gentle caring"),
                "Boy (Determined)": VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+3%", pitch="+0Hz", description="Boyfriend - serious protective"),
                "Boy (Angry)": VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+5%", pitch="+0Hz", description="Boyfriend - angry battle shout"),
                "Boy (Comedic)": VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+4%", pitch="+0Hz", description="Boyfriend - awkward comedy reaction"),
                "Boyfriend": VoiceSetting(provider="gemini", voice_id="gemini:Puck", rate="+2%", pitch="+0Hz", description="Boyfriend"),
                "Girl": VoiceSetting(provider="gemini", voice_id="gemini:Aoede", rate="+2%", pitch="+0Hz", description="Girlfriend - sweet modern girl"),
                "Girl (Normal)": VoiceSetting(provider="gemini", voice_id="gemini:Aoede", rate="+2%", pitch="+0Hz", description="Girlfriend - sweet normal"),
                "Girl (Cute)": VoiceSetting(provider="gemini", voice_id="gemini:Aoede", rate="+4%", pitch="+0Hz", description="Girlfriend - cute, playful, pouting"),
                "Girl (Teasing)": VoiceSetting(provider="gemini", voice_id="gemini:Aoede", rate="+3%", pitch="+0Hz", description="Girlfriend - teasing"),
                "Girl (Romantic)": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+0%", pitch="+0Hz", description="Girlfriend - affectionate whisper"),
                "Girl (Dragon)": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+0%", pitch="+0Hz", description="Ancient Dragon Queen form - majestic goddess"),
                "Girl (Fierce)": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+2%", pitch="+0Hz", description="Dragon Girl - protective dragon roar"),
                "Girl (Angry)": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+2%", pitch="+0Hz", description="Dragon Girl - angry"),
                "Girlfriend": VoiceSetting(provider="gemini", voice_id="gemini:Aoede", rate="+2%", pitch="+0Hz", description="Girlfriend"),
                "Dragon Girl": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+0%", pitch="+0Hz", description="Dragon Girl hybrid form"),
                "Dragon": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+0%", pitch="+0Hz", description="Ancient Dragon form"),
                "Dragon Elder": VoiceSetting(provider="gemini", voice_id="gemini:Charon", rate="+0%", pitch="+0Hz", description="Wise Ancient Dragon Elder"),
                "Dragon King": VoiceSetting(provider="gemini", voice_id="gemini:Charon", rate="+0%", pitch="+0Hz", description="Dragon King"),
                "Villain": VoiceSetting(provider="gemini", voice_id="gemini:Fenrir", rate="+2%", pitch="+0Hz", description="Sinister rival cultivator"),
                "System": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+2%", pitch="+0Hz", description="Dragon System Notification"),
                "Lady": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+0%", pitch="+0Hz", description="Generic lady / noble woman"),
                "Woman": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+0%", pitch="+0Hz", description="Adult female character"),
                "Mother": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+0%", pitch="+0Hz", description="Mother / maternal figure"),
            }
            profile.thumbnail_tags = [
                "My Girlfriend Returned as a Dragon",
                "Girlfriend Dragon Hindi",
                "Dragon Girlfriend Manhwa",
                "Comic Dub",
                "Full Recap",
            ]
        else:
            # Any new or unknown manhwa automatically gets the rich 12-role multi-voice roster!
            self.apply_genre_default_roster(profile)

        self.save_profile(profile)
        return profile

    def apply_genre_default_roster(self, profile: SeriesProfile) -> SeriesProfile:
        """
        Dynamically populate a new or custom SeriesProfile with a rich 12-role voice cast
        using the active settings from `configs/global_voice_defaults.yaml` (and any saved
        genre template profile in `configs/series_profiles/`).
        """
        g_def = self.get_global_voice_defaults()
        nav_vid = str(g_def.get("narrator_voice_id", "gemini:Puck"))
        nav_rate = str(g_def.get("narrator_rate", "+2%"))
        nav_pitch = str(g_def.get("narrator_pitch", "+0Hz"))
        hero_vid = str(g_def.get("protagonist_voice_id", nav_vid))
        hero_rate = str(g_def.get("protagonist_rate", nav_rate))
        hero_pitch = str(g_def.get("protagonist_pitch", nav_pitch))
        nav_provider = "gemini" if nav_vid.startswith("gemini:") else "edge-tts"
        hero_provider = "gemini" if hero_vid.startswith("gemini:") else "edge-tts"

        profile.bgm_ducking_volume = float(g_def.get("bgm_ducking_volume", 0.12))
        profile.bgm_normal_volume = float(g_def.get("bgm_normal_volume", 0.35))
        profile.narrator_voice = VoiceSetting(
            provider=nav_provider,
            voice_id=nav_vid,
            rate=nav_rate,
            pitch=nav_pitch,
            description=f"Dynamic Studio Narrator ({nav_vid})",
        )

        genre = (profile.genre or "murim").lower()
        if genre in ("system_hunter", "modern_action"):
            profile.bgm_genre = "epic_synthwave"
            profile.character_voices.update({
                "Protagonist": VoiceSetting(provider=hero_provider, voice_id=hero_vid, rate=hero_rate, pitch=hero_pitch, description=f"Main Hunter / Player ({hero_vid})"),
                "Protagonist (Cold)": VoiceSetting(provider=hero_provider, voice_id=hero_vid, rate=hero_rate, pitch=hero_pitch, description="Awakened Sovereign / Cool & Fearless"),
                "Protagonist (Battle)": VoiceSetting(provider=hero_provider, voice_id=hero_vid, rate=hero_rate, pitch=hero_pitch, description="Intense Combat Shout"),
                "System": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+2%", pitch="+0Hz", description="Sleek Indian Female System AI Interface (Kore)"),
                "System (Warning)": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+2%", pitch="+0Hz", description="Emergency Quest / Penalty Alert (Kore)"),
                "Rival": VoiceSetting(provider=hero_provider, voice_id=hero_vid, rate=hero_rate, pitch=hero_pitch, description=f"Cool S-Rank Hunter / Rival ({hero_vid})"),
                "Guild Master": VoiceSetting(provider=hero_provider, voice_id=hero_vid, rate=hero_rate, pitch=hero_pitch, description=f"Veteran Guild Master ({hero_vid})"),
                "Boss / Villain": VoiceSetting(provider=hero_provider, voice_id=hero_vid, rate=hero_rate, pitch=hero_pitch, description=f"Dungeon Boss / Antagonist ({hero_vid})"),
                "Heroine": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+2%", pitch="+0Hz", description="Classy Female Hunter / Indian Heroine (Kore)"),
                "Girl": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+2%", pitch="+0Hz", description="Young Female Character / Sister (Kore)"),
                "Guard / Hunter": VoiceSetting(provider=hero_provider, voice_id=hero_vid, rate=hero_rate, pitch=hero_pitch, description=f"Party Member / Side Hunter ({hero_vid})"),
            })
        elif genre in ("fantasy_comedy", "isekai"):
            profile.bgm_genre = "fantasy_adventure"
            profile.character_voices.update({
                "Protagonist": VoiceSetting(provider=hero_provider, voice_id=hero_vid, rate=hero_rate, pitch=hero_pitch, description=f"Witty Young Indian Schemer ({hero_vid})"),
                "Knight / Rival": VoiceSetting(provider=hero_provider, voice_id=hero_vid, rate=hero_rate, pitch=hero_pitch, description=f"Handsome Stoic Loyal Swordsman ({hero_vid})"),
                "Queen / Empress": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+2%", pitch="+0Hz", description="Regal Monarch (Kore)"),
                "Noble Lady": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+2%", pitch="+0Hz", description="Classy Noblewoman / Heroine (Kore)"),
                "Lord / Count": VoiceSetting(provider=hero_provider, voice_id=hero_vid, rate=hero_rate, pitch=hero_pitch, description=f"Noble Father / Elder ({hero_vid})"),
                "Spirit / Mascot": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+2%", pitch="+0Hz", description="Cute Energetic Summon / Mascot (Kore)"),
                "Villain": VoiceSetting(provider=hero_provider, voice_id=hero_vid, rate=hero_rate, pitch=hero_pitch, description=f"Corrupt Noble / Antagonist ({hero_vid})"),
            })
        else:
            profile.bgm_genre = "murim_traditional"
            profile.character_voices.update({
                "Protagonist": VoiceSetting(provider=hero_provider, voice_id=hero_vid, rate=hero_rate, pitch=hero_pitch, description=f"Young Martial Artist ({hero_vid})"),
                "Protagonist (Cold)": VoiceSetting(provider=hero_provider, voice_id=hero_vid, rate=hero_rate, pitch=hero_pitch, description="Cold, Fearless Demonic Aura"),
                "Protagonist (Wounded)": VoiceSetting(provider=hero_provider, voice_id=hero_vid, rate=hero_rate, pitch=hero_pitch, description="Injured / Intense Struggle"),
                "Loyal Guard / Rival": VoiceSetting(provider=hero_provider, voice_id=hero_vid, rate=hero_rate, pitch=hero_pitch, description=f"Loyal Swordsman / Rival Disciple ({hero_vid})"),
                "Sect Leader / Lord": VoiceSetting(provider=hero_provider, voice_id=hero_vid, rate=hero_rate, pitch=hero_pitch, description=f"Supreme Patriarch / Cult Lord ({hero_vid})"),
                "Elder / Master": VoiceSetting(provider=hero_provider, voice_id=hero_vid, rate=hero_rate, pitch=hero_pitch, description=f"Clan Elder / Grandmaster ({hero_vid})"),
                "Villain / Assassin": VoiceSetting(provider=hero_provider, voice_id=hero_vid, rate=hero_rate, pitch=hero_pitch, description=f"Dangerous Enemy / Blood Cultist ({hero_vid})"),
                "System / AI": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+2%", pitch="+0Hz", description="Sleek Indian Female System / Spirit Guide (Kore)"),
                "Heroine / Lady": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+2%", pitch="+0Hz", description="Classy Female Martial Artist / Heroine (Kore)"),
                "Mother": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+2%", pitch="+0Hz", description="Maternal Figure (Kore)"),
                "Girl": VoiceSetting(provider="gemini", voice_id="gemini:Kore", rate="+2%", pitch="+0Hz", description="Young Female Disciple (Kore)"),
            })
        return profile

    def onboard_new_series(
        self,
        series_name: str,
        genre: str = "murim",
        use_ai_cast: bool = True,
        inbox_root: Path = Path("assets/inbox"),
    ) -> SeriesProfile:
        """
        Onboard a brand-new manhwa series:
        1. Creates the `assets/inbox/<Series Name>/` dropzone directory.
        2. Initializes a rich multi-voice SeriesProfile with genre defaults.
        3. Optionally queries Gemini AI to discover canon character names for `<series_name>`
           and maps each character to distinct Native Indian Human Voices (+0Hz natural pitch).
        """
        clean_name = series_name.strip()
        inbox_dir = inbox_root / clean_name
        inbox_dir.mkdir(parents=True, exist_ok=True)

        profile = self.get_or_create_profile(clean_name, genre=genre)
        self.apply_genre_default_roster(profile)

        if use_ai_cast:
            try:
                import json
                import os
                import re
                from google import genai
                from manhwa_studio.env_config import get_env_config

                api_key = os.getenv("GEMINI_API_KEY", "").strip()
                if api_key:
                    client = genai.Client(api_key=api_key)
                    model_name = get_env_config().gemini_metadata_model
                    prompt = (
                        f"You are an expert on Korean Manhwa / Webtoons.\n"
                        f"Series Name: '{clean_name}' (Genre: {genre}).\n"
                        f"Return a JSON array of the top 6 to 8 main/recurring characters from '{clean_name}' "
                        f"with their role archetype so we can assign distinct Indian Human Neural TTS voices.\n"
                        f"Valid archetype values: 'protagonist', 'protagonist_cold', 'rival_male', 'elder_male', 'villain_male', 'system_ai', 'heroine_female', 'young_female'.\n"
                        f"Format strictly as JSON array:\n"
                        f'[{{"name": "Character Name", "archetype": "protagonist", "description": "Short role description"}}]'
                    )
                    resp = client.models.generate_content(model=model_name, contents=prompt)
                    raw = (resp.text or "").strip()
                    m = re.search(r"\[.*\]", raw, flags=re.DOTALL)
                    if m:
                        chars = json.loads(m.group(0))
                        g_def = self.get_global_voice_defaults()
                        hero_vid = str(g_def.get("protagonist_voice_id", g_def.get("narrator_voice_id", "gemini:Puck")))
                        hero_rate = str(g_def.get("protagonist_rate", g_def.get("narrator_rate", "+2%")))
                        hero_pitch = str(g_def.get("protagonist_pitch", g_def.get("narrator_pitch", "+0Hz")))
                        voice_map = {
                            "protagonist": (hero_vid, hero_rate, hero_pitch),
                            "protagonist_cold": (hero_vid, hero_rate, hero_pitch),
                            "rival_male": (hero_vid, hero_rate, hero_pitch),
                            "elder_male": (hero_vid, hero_rate, hero_pitch),
                            "villain_male": (hero_vid, hero_rate, hero_pitch),
                            "system_ai": ("gemini:Kore", "+2%", "+0Hz"),
                            "heroine_female": ("gemini:Kore", "+2%", "+0Hz"),
                            "young_female": ("gemini:Kore", "+2%", "+0Hz"),
                        }
                        for item in chars:
                            c_name = str(item.get("name", "")).strip()
                            arch = str(item.get("archetype", "protagonist")).strip().lower()
                            desc = str(item.get("description", arch)).strip()
                            if c_name:
                                vid, rate, pitch = voice_map.get(arch, (hero_vid, hero_rate, hero_pitch))
                                profile.character_voices[c_name] = VoiceSetting(
                                    provider="gemini" if vid.startswith("gemini:") else "edge-tts",
                                    voice_id=vid,
                                    rate=rate,
                                    pitch=pitch,
                                    description=desc,
                                )
                                if arch == "protagonist":
                                    profile.character_voices[f"{c_name} (Cold)"] = VoiceSetting(
                                        provider="gemini" if hero_vid.startswith("gemini:") else "edge-tts",
                                        voice_id=hero_vid,
                                        rate="+1%",
                                        pitch=hero_pitch,
                                        description=f"{c_name} - Cold & Fearless mode",
                                    )
                                    profile.character_voices[f"{c_name} (Wounded)"] = VoiceSetting(
                                        provider="gemini" if hero_vid.startswith("gemini:") else "edge-tts",
                                        voice_id=hero_vid,
                                        rate="+5%",
                                        pitch=hero_pitch,
                                        description=f"{c_name} - Injured / Battle strain",
                                    )
            except Exception as e:
                logger.warning(f"AI character auto-cast skipped for '{clean_name}': {e}")

        self.save_profile(profile)
        return profile

    def list_profiles(self) -> List[str]:
        """List all available series profile slugs."""
        return [f.stem for f in self.profiles_dir.glob("*.yaml")]
