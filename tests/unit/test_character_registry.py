"""
Unit tests for Per-Manhwa Character Face & Identity Registry and Multi-Voice Casting.
"""

from pathlib import Path
from unittest.mock import patch
from PIL import Image, ImageDraw

from manhwa_studio.schemas import SceneItem, SceneManifest
from manhwa_studio.story.character_registry import (
    CharacterRegistry,
    compute_face_dhash,
    dhash_distance,
    select_gemini_voice,
)
from manhwa_studio.studio_pro.series_manager import SeriesManager
from manhwa_studio.studio_pro.voice_director import VoiceDirector


def _make_dummy_panel(path: Path, color: tuple[int, int, int] = (200, 180, 160)) -> None:
    """Create a synthetic manhwa panel with distinct visual features for deterministic dHash."""
    img = Image.new("RGB", (400, 600), color=(240, 240, 245))
    draw = ImageDraw.Draw(img)
    # Draw stylized head/face region in upper center
    draw.ellipse((120, 80, 280, 260), fill=color, outline=(20, 20, 20), width=4)
    draw.rectangle((155, 140, 185, 155), fill=(30, 30, 50))
    draw.rectangle((215, 140, 245, 155), fill=(30, 30, 50))
    draw.arc((175, 190, 225, 220), start=0, end=180, fill=(120, 40, 40), width=3)
    img.save(path, format="JPEG")


def test_voice_selection_by_gender_age_look():
    assert select_gemini_voice("female", "teen", "cute_girl")[0] == "gemini:Leda"
    assert select_gemini_voice("female", "young_adult", "supporting_female")[0] == "gemini:Aoede"
    assert select_gemini_voice("female", "adult", "regal_woman")[0] == "gemini:Kore"
    assert select_gemini_voice("female", "young_adult", "system_ai")[0] == "gemini:Zephyr"

    assert select_gemini_voice("male", "teen", "young_hero")[0] == "gemini:Puck"
    assert select_gemini_voice("male", "young_adult", "stoic_knight")[0] == "gemini:Charon"
    assert select_gemini_voice("male", "elder", "wise_elder")[0] == "gemini:Fenrir"
    assert select_gemini_voice("male", "adult", "villain_dark")[0] == "gemini:Fenrir"


def test_per_manhwa_registry_caches_after_single_gemini_call(tmp_path: Path):
    reg_root = tmp_path / "character_registry"
    panel_1 = tmp_path / "panel_001.jpg"
    panel_2 = tmp_path / "panel_002.jpg"
    _make_dummy_panel(panel_1, color=(230, 200, 190))
    _make_dummy_panel(panel_2, color=(230, 200, 190))

    gemini_calls = []

    def fake_gemini(self, image_to_inspect, candidate_speaker, dialogue_text, need_face_box):
        gemini_calls.append((self.series_name, candidate_speaker))
        return {
            "canonical_name": "Yu Iseol",
            "gender": "female",
            "age_group": "young_adult",
            "look_archetype": "regal_woman",
            "visual_description": "Long black hair, calm cold swordswoman",
            "face_box_2d": [130, 300, 440, 700],
        }

    reg = CharacterRegistry("Return of the Mount Hua Sect", registry_root=reg_root)
    with patch.object(CharacterRegistry, "_query_gemini_for_character", fake_gemini):
        # First call: not in cache -> calls Gemini ONCE, crops face, saves to registry
        prof1 = reg.resolve_or_confirm_character(
            speaker="Girl",
            panel_path=panel_1,
            dialogue_text="चुपचाप आगे चलो।",
            allow_gemini=True,
        )
        assert prof1 is not None
        assert prof1.canonical_name == "Yu Iseol"
        assert prof1.gender == "female"
        assert prof1.gemini_voice_id == "gemini:Kore"
        assert prof1.face_image_path == "faces/yu_iseol.jpg"
        assert (reg.series_dir / "faces" / "yu_iseol.jpg").exists()
        assert len(gemini_calls) == 1

        # Second call with same name OR alias -> 0 Gemini calls
        prof2 = reg.resolve_or_confirm_character(
            speaker="Yu Iseol (Cold)",
            panel_path=panel_2,
            dialogue_text="मेरी तलवार तैयार है।",
            allow_gemini=True,
        )
        assert prof2 is not None
        assert prof2.canonical_name == "Yu Iseol"
        assert len(gemini_calls) == 1  # Still 1!

        # Third call with alias 'Girl' -> 0 Gemini calls
        prof3 = reg.resolve_or_confirm_character(
            speaker="Girl",
            panel_path=panel_2,
            allow_gemini=True,
        )
        assert prof3 is not None
        assert prof3.canonical_name == "Yu Iseol"
        assert len(gemini_calls) == 1  # Still 1!

    # Reload from disk in a new instance -> still cached, prompt roster populated
    reg_reloaded = CharacterRegistry("Return of the Mount Hua Sect", registry_root=reg_root)
    assert reg_reloaded.find_by_name("Yu Iseol") is not None
    assert reg_reloaded.find_by_name("Girl") is not None
    roster_prompt = reg_reloaded.format_roster_for_prompt()
    assert "Yu Iseol" in roster_prompt
    assert "female" in roster_prompt

    # Different manhwa has its own isolated registry
    other_reg = CharacterRegistry("Nano Machine", registry_root=reg_root)
    assert other_reg.find_by_name("Yu Iseol") is None


def test_face_dhash_matching_and_voice_director_resolution(tmp_path: Path):
    reg_root = tmp_path / "character_registry"
    panel_1 = tmp_path / "p1.jpg"
    _make_dummy_panel(panel_1, color=(210, 175, 155))

    reg = CharacterRegistry("Test Manhwa", registry_root=reg_root)
    rel, dhash = reg.crop_and_save_face(panel_1, "tang_soso", box_2d_norm=[130, 300, 440, 700])
    assert rel == "faces/tang_soso.jpg"
    assert dhash is not None
    assert dhash_distance(dhash, compute_face_dhash(reg.series_dir / rel)) == 0

    reg.register_character(
        canonical_name="Tang Soso",
        gender="female",
        age_group="teen",
        look_archetype="cute_girl",
        face_rel_path=rel,
        face_dhash=dhash,
    )

    sm = SeriesManager(profiles_dir=tmp_path / "profiles")
    profile = sm.get_or_create_profile("Test Manhwa")
    director = VoiceDirector(profile)

    s_female = SceneItem(
        scene_id="scene_001",
        duration=3.0,
        image_file="p1.jpg",
        speaker="Tang Soso",
        narration_text="अरे वाह, ये तो कमाल है!",
    )
    s_narrator = SceneItem(
        scene_id="scene_002",
        duration=3.0,
        image_file="p1.jpg",
        speaker="Narrator",
        narration_text="और फिर जंग शुरू हो गई।",
    )

    v_female = director.resolve_multi_character_voice(s_female, registry=reg)
    v_narr = director.resolve_multi_character_voice(s_narrator, registry=reg)

    assert v_female.voice_id == "gemini:Leda"
    assert v_narr.voice_id == profile.narrator_voice.voice_id

