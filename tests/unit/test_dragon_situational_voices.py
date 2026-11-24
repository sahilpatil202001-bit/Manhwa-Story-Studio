"""
Unit tests for 'My Girlfriend Returned as a Dragon' profile and situational voice adaptation.
"""

from pathlib import Path
import pytest

from manhwa_studio.studio_pro.series_manager import SeriesManager
from manhwa_studio.studio_pro.voice_director import VoiceDirector
from manhwa_studio.ingestion.inbox_scanner import scan_inbox


def test_dragon_profile_creation_and_loading():
    manager = SeriesManager()
    profile = manager.get_or_create_profile("My Girlfriend Returned as a Dragon")

    assert profile.series_name == "My Girlfriend Returned as a Dragon"
    assert profile.series_slug == "my_girlfriend_returned_as_a_dragon"
    assert "Boy" in profile.character_voices
    assert "Boy (Shocked)" in profile.character_voices
    assert "Boy (Romantic)" in profile.character_voices
    assert "Girl" in profile.character_voices
    assert "Girl (Cute)" in profile.character_voices
    assert "Girl (Dragon)" in profile.character_voices
    assert "Girl (Fierce)" in profile.character_voices


def test_situational_voice_director_boy():
    manager = SeriesManager()
    profile = manager.get_or_create_profile("My Girlfriend Returned as a Dragon")
    director = VoiceDirector(profile)

    # 1. Direct situational speaker tags
    v_normal = director.resolve_voice_for_speaker("Boy")
    v_shocked = director.resolve_voice_for_speaker("Boy (Shocked)")
    v_romantic = director.resolve_voice_for_speaker("Boy (Romantic)")
    v_determined = director.resolve_voice_for_speaker("Boy (Determined)")

    # Pitch and rate should adapt to situation
    assert v_shocked.pitch == "+6Hz"
    assert v_shocked.rate == "+10%"
    assert v_romantic.pitch == "-1Hz"
    assert v_romantic.rate == "-2%"
    assert v_determined.pitch == "-3Hz"
    assert v_normal.pitch == "+1Hz"

    # 2. Contextual dialogue inference when speaker is simply "Boy"
    v_inferred_panic = director.resolve_voice_for_speaker(
        speaker="Boy",
        text="अरे बाप रे! ये क्या है?! तुम्हारे सींग कहां से आ गए?!",
    )
    assert v_inferred_panic.pitch == "+6Hz"  # Inferred Boy (Shocked)

    v_inferred_romantic = director.resolve_voice_for_speaker(
        speaker="Boy",
        text="चिंता मत करो, मैं हमेशा तुम्हारे साथ हूं... मेरा प्यार कभी कम नहीं होगा।",
    )
    assert v_inferred_romantic.pitch == "-1Hz"  # Inferred Boy (Romantic)


def test_situational_voice_director_girl():
    manager = SeriesManager()
    profile = manager.get_or_create_profile("My Girlfriend Returned as a Dragon")
    director = VoiceDirector(profile)

    # 1. Direct situational speaker tags
    v_normal = director.resolve_voice_for_speaker("Girl")
    v_cute = director.resolve_voice_for_speaker("Girl (Cute)")
    v_dragon = director.resolve_voice_for_speaker("Girl (Dragon)")
    v_fierce = director.resolve_voice_for_speaker("Girl (Fierce)")

    # Pitch and rate should adapt to situation
    assert v_cute.pitch == "+5Hz"
    assert v_cute.rate == "+6%"
    assert v_dragon.pitch == "-4Hz"
    assert v_dragon.rate == "-5%"
    assert v_fierce.pitch == "-2Hz"
    assert v_normal.pitch == "+2Hz"

    # 2. Contextual dialogue inference when speaker is simply "Girl"
    v_inferred_dragon = director.resolve_voice_for_speaker(
        speaker="Girl",
        text="तुम कमज़ोर इंसान हो... इस दुनिया पर अब ड्रैगन की हुकूमत होगी!",
    )
    assert v_inferred_dragon.pitch == "-4Hz"  # Inferred Girl (Dragon)

    v_inferred_cute = director.resolve_voice_for_speaker(
        speaker="Girl",
        text="बौदू! हीही, तुम कितने प्यारे लग रहे हो... मुझे बहुत भूख लगी है!",
    )
    assert v_inferred_cute.pitch == "+5Hz"  # Inferred Girl (Cute)


def test_inbox_scanner_dragon_folder(tmp_path: Path):
    inbox = tmp_path / "inbox"
    dragon_ch1 = inbox / "My Girlfriend Returned as a Dragon" / "ch1"
    dragon_ch1.mkdir(parents=True)
    (dragon_ch1 / "001.webp").write_bytes(b"dummy image data")
    (dragon_ch1 / "002.webp").write_bytes(b"dummy image data")

    batches = scan_inbox(inbox)
    assert len(batches) == 1
    assert "Dragon" in batches[0].inferred_series
    assert batches[0].chapter_number == 1
    assert len(batches[0].image_paths) == 2
