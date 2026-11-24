"""
Unit tests for Nano Machine situational voices, System AI attractive human voice, and character casting.
"""

from pathlib import Path
import pytest

from manhwa_studio.studio_pro.series_manager import SeriesManager
from manhwa_studio.studio_pro.voice_director import VoiceDirector


def test_nano_machine_profile_loading():
    manager = SeriesManager()
    profile = manager.get_or_create_profile("Nano Machine")

    assert profile.series_name == "Nano Machine"
    assert profile.series_slug == "nano_machine"
    assert "Nano" in profile.character_voices
    assert "Nano (Warning)" in profile.character_voices
    assert "Nano (Analysis)" in profile.character_voices
    assert "Cheon Yeo-Woon" in profile.character_voices
    assert "Cheon Yeo-Woon (Cold)" in profile.character_voices
    assert "Cheon Yeo-Woon (Wounded)" in profile.character_voices
    assert "Guard Jang (Wounded)" in profile.character_voices


def test_nano_system_ai_attractive_situational_voices():
    manager = SeriesManager()
    profile = manager.get_or_create_profile("Nano Machine")
    director = VoiceDirector(profile)

    # 1. Direct situational speaker tags
    v_normal = director.resolve_voice_for_speaker("Nano")
    v_warning = director.resolve_voice_for_speaker("Nano (Warning)")
    v_analysis = director.resolve_voice_for_speaker("Nano (Analysis)")
    v_combat = director.resolve_voice_for_speaker("Nano (Combat)")

    # Natural, attractive human-like AI (not robotic)
    assert v_normal.pitch == "+1Hz"
    assert v_normal.rate == "+1%"
    assert v_warning.pitch == "+4Hz"
    assert v_warning.rate == "+7%"
    assert v_analysis.pitch == "+1Hz"
    assert v_analysis.rate == "+0%"
    assert v_combat.pitch == "+2Hz"
    assert v_combat.rate == "+4%"

    # 2. Contextual dialogue inference when speaker is simply "Nano" or "System"
    v_inferred_warn = director.resolve_voice_for_speaker(
        speaker="Nano",
        text="चेतावनी! उपयोगकर्ता के शरीर में घातक जहर पाया गया है। तत्काल उपचार आवश्यक है।",
    )
    assert v_inferred_warn.pitch == "+4Hz"  # Inferred Nano (Warning)

    v_inferred_analysis = director.resolve_voice_for_speaker(
        speaker="System",
        text="मेरिडियन पुनर्निर्माण प्रक्रिया शुरू हो रही है... डीएनए विश्लेषण पूरा हुआ।",
    )
    assert v_inferred_analysis.pitch == "+1Hz"  # Inferred Nano (Analysis)


def test_cheon_yeowun_situational_voices():
    manager = SeriesManager()
    profile = manager.get_or_create_profile("Nano Machine")
    director = VoiceDirector(profile)

    # 1. Direct situational speaker tags
    v_normal = director.resolve_voice_for_speaker("Cheon Yeo-Woon")
    v_cold = director.resolve_voice_for_speaker("Cheon Yeo-Woon (Cold)")
    v_wounded = director.resolve_voice_for_speaker("Cheon Yeo-Woon (Wounded)")
    v_enraged = director.resolve_voice_for_speaker("Cheon Yeo-Woon (Enraged)")

    assert v_normal.pitch == "-2Hz"
    assert v_cold.pitch == "-5Hz"
    assert v_cold.rate == "-2%"
    assert v_wounded.pitch == "+3Hz"
    assert v_wounded.rate == "+5%"
    assert v_enraged.pitch == "-2Hz"
    assert v_enraged.rate == "+4%"

    # 2. Contextual dialogue inference when speaker is simply "Cheon Yeo-Woon"
    v_inferred_cold = director.resolve_voice_for_speaker(
        speaker="Cheon Yeo-Woon",
        text="अगर तुमने दोबारा मेरी तरफ देखा... तो मैं तुम्हारी दोनों बाहें काट दूंगा।",
    )
    assert v_inferred_cold.pitch == "-5Hz"  # Inferred Cold Demonic Sovereign

    v_inferred_pain = director.resolve_voice_for_speaker(
        speaker="Cheon Yeo-Woon",
        text="आह! इतना असहनीय दर्द... मेरे पूरे शरीर में जहर फैल रहा है!",
    )
    assert v_inferred_pain.pitch == "+3Hz"  # Inferred Wounded / Pain
