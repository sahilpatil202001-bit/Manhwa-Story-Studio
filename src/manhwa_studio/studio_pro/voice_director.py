"""
Multi-Voice Character Casting & Audio Synthesis Engine.
Assigns distinct, character-tailored voices (gender, age, pitch, speed)
to every character in the scene manifest for an authentic anime/comic dub experience.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import edge_tts
from manhwa_studio.logging_config import get_logger
from manhwa_studio.schemas import SceneManifest, SceneItem
from manhwa_studio.studio_pro.series_manager import SeriesProfile, VoiceSetting

logger = get_logger("manhwa_studio.pro.voice")


class VoiceDirector:
    """Manages multi-voice casting, voice selection heuristics, and batch speech synthesis."""

    def __init__(self, profile: SeriesProfile):
        from manhwa_studio.env_config import get_env_config
        self.profile = profile
        self.env_cfg = get_env_config()
        self._gemini_circuit_broken = False
        self._gemini_cooldown_until: float = 0.0

    def resolve_voice_for_speaker(
        self,
        speaker: str,
        text: Optional[str] = None,
        scene_purpose: Optional[str] = None,
    ) -> VoiceSetting:
        """Resolve the optimal VoiceSetting based on speaker name, situational modifiers, profile, or archetype."""
        clean_speaker = (speaker or "").strip()

        # 1. Check if speaker is Narrator
        if not clean_speaker or clean_speaker.lower() in ["narrator", "सूत्रधार", "कथावाचक"]:
            return self.profile.narrator_voice

        # 2. If speaker has an explicit situation tag (e.g. 'Boy (Shocked)', 'Girl (Cute)', 'Hero [Angry]'), exact match takes top priority
        if "(" in clean_speaker or " - " in clean_speaker or "[" in clean_speaker:
            for char_name, setting in self.profile.character_voices.items():
                if char_name.lower() == clean_speaker.lower():
                    return setting

        # 3. Contextual situational inference for generic speakers (Boy / Girl / Lead) based on dialogue or scene
        name_lower = clean_speaker.lower()
        dialogue = (text or "").lower()
        purpose = (scene_purpose or "").lower()

        # Is this a Boy / Male Lead speaker?
        is_boy = any(k in name_lower for k in ["boy", "boyfriend", "suho", "protagonist", "hero", "male lead", "ladka", "chen"])
        # Is this a Girl / Female Lead / Dragon Girlfriend speaker?
        is_girl = any(k in name_lower for k in ["girl", "girlfriend", "dragon", "female", "lady", "ladki"])

        if is_boy:
            # Check panic / shocked situation
            shocked_words = ["अरे बाप रे", "ये क्या है", "हे भगवान", "भागो", "बचाओ", "क्या?!", "ड्रैगन?!", "हो क्या रहा है", "मदद", "रुको"]
            if any(w in dialogue for w in shocked_words) or "?!" in dialogue or "!! " in dialogue:
                for k in ["Boy (Shocked)", "Boy (Panicked)"]:
                    if k in self.profile.character_voices:
                        return self.profile.character_voices[k]
            # Check romantic situation
            romantic_words = ["प्यार", "मेरी जान", "चिंता मत करो", "तुम ठीक हो", "खूबसूरत", "हमेशा साथ", "डरो मत"]
            if any(w in dialogue for w in romantic_words):
                for k in ["Boy (Romantic)"]:
                    if k in self.profile.character_voices:
                        return self.profile.character_voices[k]
            # Check determined / battle situation
            battle_words = ["तेरी हिम्मत", "खत्म कर दूंगा", "मरने के लिए", "बदला", "छोड़ूंगा नहीं", "लड़ेंगे"]
            if any(w in dialogue for w in battle_words) or purpose in ["conflict", "cliffhanger"]:
                for k in ["Boy (Determined)", "Boy (Angry)"]:
                    if k in self.profile.character_voices:
                        return self.profile.character_voices[k]
            # Fallback to Boy in character voices if available
            for k in ["Boy", "Boy (Normal)", "Boyfriend"]:
                if k in self.profile.character_voices:
                    return self.profile.character_voices[k]

        if is_girl:
            # Check Dragon form / ancient majesty
            dragon_words = ["ड्रैगन", "मेरी हुकूमत", "कमज़ोर इंसान", "राख", "मेरी असली ताकत", "अग्नि", "मौत", "मेरी प्रजा"]
            if any(w in dialogue for w in dragon_words) or "dragon" in name_lower:
                for k in ["Girl (Dragon)", "Dragon", "Ancient Dragon"]:
                    if k in self.profile.character_voices:
                        return self.profile.character_voices[k]
            # Check fierce battle roar
            fierce_words = ["कीड़े", "मूर्ख", "तूने उसे छुआ", "भस्म", "तेरा अंत"]
            if any(w in dialogue for w in fierce_words) or ("!" in dialogue and purpose in ["conflict", "turning_point"]):
                for k in ["Girl (Fierce)", "Girl (Angry)"]:
                    if k in self.profile.character_voices:
                        return self.profile.character_voices[k]
            # Check cute / playful / teasing
            cute_words = ["बौदू", "हीही", "शरारत", "सुनो ना", "मुझे भूख लगी है", "प्यारे", "बेवकूफ", "तुम मेरे हो"]
            if any(w in dialogue for w in cute_words):
                for k in ["Girl (Cute)", "Girl (Teasing)"]:
                    if k in self.profile.character_voices:
                        return self.profile.character_voices[k]
            # Check romantic
            if any(w in dialogue for w in ["सिर्फ तुम्हारी", "डरो मत", "मैं तुम्हारे साथ हूं", "प्यार"]):
                for k in ["Girl (Romantic)"]:
                    if k in self.profile.character_voices:
                        return self.profile.character_voices[k]
            # Fallback to Girl in character voices if available
            for k in ["Girl", "Girl (Normal)", "Girlfriend"]:
                if k in self.profile.character_voices:
                    return self.profile.character_voices[k]

        # Is this Cheon Yeo-Woon / Protagonist in Nano Machine?
        is_yeowun = any(k in name_lower for k in ["cheon", "yeo-woon", "yeowun", "yeo woon", "yeo_woon"])
        if is_yeowun:
            # Check wounded / severe pain / survival
            pain_words = ["दर्द", "जहर", "बचाओ", "मरना नहीं", "खून", "आह", "चीख", "तड़प", "सांस", "जिंदा"]
            if any(w in dialogue for w in pain_words) or ("!" in dialogue and purpose in ["conflict", "hook"]):
                for k in ["Cheon Yeo-Woon (Wounded)", "Cheon Yeo-Woon (Pain)"]:
                    if k in self.profile.character_voices:
                        return self.profile.character_voices[k]
            # Check cold / ruthless / demonic sovereign
            cold_words = ["हाथ काट", "बाहें काट", "काट दूंगा", "कीड़े", "तेरा अंत", "मौत", "खामोश", "गद्दार", "टुकड़े", "बदला", "बेरहम", "मार डालूंगा"]
            if any(w in dialogue for w in cold_words):
                for k in ["Cheon Yeo-Woon (Cold)", "Cheon Yeo-Woon (Ruthless)"]:
                    if k in self.profile.character_voices:
                        return self.profile.character_voices[k]
            # Check enraged battle roar
            enraged_words = ["तेरी हिम्मत", "चीर दूंगा", "कुचल"]
            if any(w in dialogue for w in enraged_words):
                for k in ["Cheon Yeo-Woon (Enraged)", "Cheon Yeo-Woon (Angry)"]:
                    if k in self.profile.character_voices:
                        return self.profile.character_voices[k]
            # Check gentle / respectful
            respectful_words = ["गार्ड जांग", "मां", "शुक्रिया", "चिंता मत करो"]
            if any(w in dialogue for w in respectful_words):
                for k in ["Cheon Yeo-Woon (Respectful)"]:
                    if k in self.profile.character_voices:
                        return self.profile.character_voices[k]
            # Fallback
            for k in ["Cheon Yeo-Woon", "Cheon Yeo-Woon (Normal)", "Yeo-Woon"]:
                if k in self.profile.character_voices:
                    return self.profile.character_voices[k]

        # Is this Nano Machine / System AI?
        is_nano = any(k in name_lower for k in ["nano", "system", "ai interface", "nanomachine"])
        if is_nano:
            # Emergency / Warning
            warning_words = ["चेतावनी", "खतरा", "जहर", "warning", "emergency", "danger", "alert", "हानि", "आपातकाल", "शत्रु", "घायल"]
            if any(w in dialogue for w in warning_words) or "!" in dialogue:
                for k in ["Nano (Warning)", "Nano (Emergency)", "System (Warning)"]:
                    if k in self.profile.character_voices:
                        return self.profile.character_voices[k]
            # Medical / Scan / Martial arts analysis
            analysis_words = ["विश्लेषण", "स्कैनिंग", "मेरिडियन", "डीएनए", "इलाज", "पुनर्निर्माण", "लोडिंग", "तकनीक", "मास्टर", "स्वॉर्ड", "ऊर्जा"]
            if any(w in dialogue for w in analysis_words):
                for k in ["Nano (Analysis)", "System (Analysis)"]:
                    if k in self.profile.character_voices:
                        return self.profile.character_voices[k]
            # Combat simulation
            combat_words = ["सिमुलेशन", "प्रक्षेपवक्र", "दिशा", "काउंटर", "वार"]
            if any(w in dialogue for w in combat_words):
                for k in ["Nano (Combat)"]:
                    if k in self.profile.character_voices:
                        return self.profile.character_voices[k]
            # Fallback
            for k in ["Nano", "Nano (Normal)", "System"]:
                if k in self.profile.character_voices:
                    return self.profile.character_voices[k]

        # Is this Guard Jang?
        is_jang = "jang" in name_lower or "guard" in name_lower
        if is_jang:
            if any(w in dialogue for w in ["भागो", "यंग मास्टर", "खतरा", "बचकर", "रुकिए", "खून", "जल्दी"]):
                for k in ["Guard Jang (Wounded)"]:
                    if k in self.profile.character_voices:
                        return self.profile.character_voices[k]
            for k in ["Guard Jang", "Jang Ba-Gok"]:
                if k in self.profile.character_voices:
                    return self.profile.character_voices[k]

        # 4. Check profile character voices for named characters (exact & substring match)
        for char_name, setting in sorted(self.profile.character_voices.items(), key=lambda x: len(x[0]), reverse=True):
            if char_name.lower() in clean_speaker.lower() or clean_speaker.lower() in char_name.lower():
                return setting

        # 5. Analyze speaker name archetypes using semantic keywords
        # Female archetype
        female_keywords = ["woman", "girl", "lady", "sister", "maiden", "mother", "queen", "princess", "aurat", "ladki"]
        if any(k in name_lower for k in female_keywords):
            if "young" in name_lower or "little" in name_lower:
                return self.profile.archetype_voices.get("female_young", self.profile.archetype_voices["female_lead"])
            return self.profile.archetype_voices["female_lead"]

        # Elder / Master archetype
        elder_keywords = ["elder", "master", "grandpa", "grandfather", "old", "patriarch", "doctor", "daada", "dada", "guru"]
        if any(k in name_lower for k in elder_keywords):
            return self.profile.archetype_voices["elder_master"]

        # Villain / Assassin archetype
        villain_keywords = ["assassin", "killer", "shadow", "demon", "devil", "bandit", "traitor", "enemy", "kaatil"]
        if any(k in name_lower for k in villain_keywords):
            return self.profile.archetype_voices["villain_dark"]

        # Guard / Crowd archetype
        crowd_keywords = ["guard", "soldier", "warrior", "subordinate", "disciple", "crowd", "man"]
        if any(k in name_lower for k in crowd_keywords):
            return self.profile.archetype_voices["crowd_guard"]

        # Knight / Swordsman / Loyal vassal archetype
        knight_keywords = ["knight", "swordsman", "swordmaster", "javier", "commander", "paladin"]
        if any(k in name_lower for k in knight_keywords):
            if "knight_loyal" in self.profile.archetype_voices:
                return self.profile.archetype_voices["knight_loyal"]
            if "rival_cool" in self.profile.archetype_voices:
                return self.profile.archetype_voices["rival_cool"]

        # Schemer / Witty / Merchant archetype
        schemer_keywords = ["lloyd", "engineer", "contractor", "architect", "merchant", "clever", "schemer"]
        if any(k in name_lower for k in schemer_keywords):
            if "schemer_witty" in self.profile.archetype_voices:
                return self.profile.archetype_voices["schemer_witty"]

        # Spirit / Elemental / Mascot archetype
        spirit_keywords = ["spirit", "podong", "poby", "elemental", "fairy", "mascot"]
        if any(k in name_lower for k in spirit_keywords):
            if "female_young" in self.profile.archetype_voices:
                return self.profile.archetype_voices["female_young"]

        # Default to heroic male protagonist voice
        return self.profile.archetype_voices.get("hero_male", self.profile.narrator_voice)

    @staticmethod
    def humanize_text_for_natural_speech(text: str) -> str:
        """
        Prepare Hindi / Hinglish text so Neural & LLM TTS models speak with natural
        human breathing pauses, classy anime-dub prosody, and zero tapori/chappri slang.
        """
        import re

        clean = (text or "").strip()
        if not clean:
            return "..."

        # Remove stray markdown formatting or brackets that confuse TTS prosody
        clean = re.sub(r"[\*\_`#~]+", "", clean)
        clean = re.sub(r"\s*—\s*|\s*--\s*", ", ", clean)
        clean = re.sub(r"\.{3,}", ", ", clean)
        clean = re.sub(r"!{2,}", "!", clean)
        clean = re.sub(r"\?{2,}", "?", clean)

        # Strip/replace tapori / chappri / street slang so characters sound classy and dignified
        slang_replacements = [
            (r"अबे चुप कर बे!?", "चुप रहो!"),
            (r"अबे ओए!?", "सुनो!"),
            (r"\bअबे\b\s*,?", ""),
            (r"\s+\bबे\s*!", "!"),
            (r"ओह\s+शिट!?", "अरे नहीं!"),
            (r"ओ\s+शिट!?", "अरे नहीं!"),
            (r"\bशिट\b!?", "अरे नहीं!"),
            (r"Shit\s*यार\s*,?\s*", "अरे नहीं, "),
            (r"\bShit\b\s*,?\s*", "अरे नहीं, "),
            (r"कौन सा\s+non-?sense\s+बक रहा है", "कैसी बेकार की बातें कर रहा है"),
            (r"बक रहा है", "बोल रहा है"),
            (r"अरे वाह भाई!?", "वाह!"),
            (r"अरे यार\s*,?\s*", ""),
            (r"अरे भाई\s*,?\s*", "देखो, "),
            (r"तो चलो यार\s*,?\s*", "तो चलिए, "),
            (r"चलो यार\s*,?\s*", "चलिए, "),
            (r"एकदम\s+Next\s+Level", "शानदार"),
            (r"मस्त\s+Attitude", "शानदार अंदाज़"),
            (r"मस्त\s+", "शानदार "),
            (r"अपने\s+Lloyd\s+भाई", "Lloyd"),
            (r"Lloyd\s+भाई", "Lloyd"),
            (r"\s+bro\s*!", "!"),
            (r"\b[Bb]ro\b\s*,?", ""),
            (r"ट्रिगर हो गया", "भड़क उठा"),
            (r"ट्रैश पेपर", "बेकार कागज़"),
            (r"फालतू बकवास", "बेकार की बातें"),
            (r"दिमाग घूम गया", "होश उड़ गए"),
            (r"\s+यार\s*([,!।?])", r"\1"),
            (r"\bयार\s*,?\s*", ""),
        ]
        for pat, rep in slang_replacements:
            clean = re.sub(pat, rep, clean, flags=re.IGNORECASE)

        # Add natural micro-breath commas after common conversational Hindi/Hinglish openers
        for opener in ("सुनो", "देखो", "लेकिन", "असल में", "सच में", "तभी"):
            clean = re.sub(rf"\b({opener})\s+(?![,!\?।])", r"\1, ", clean)

        clean = re.sub(r"\s+", " ", clean).strip(" ,")
        return clean or "..."

    @staticmethod
    def devanagari_to_roman_hinglish(text: str) -> str:
        """
        Convert Devanagari Hindi words into natural phonetic Roman Hinglish while preserving
        existing English words intact. Used when synthesizing with Latin-script Indian voices
        like `en-IN-PrabhatNeural` or `en-IN-NeerjaNeural` so they speak the full Hindi+English
        sentence with an authentic modern Indian accent without skipping Devanagari characters.
        """
        vowels = {
            "अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo",
            "ऋ": "ri", "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au", "ऑ": "o", "ऍ": "e",
        }
        matras = {
            "ा": "aa", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo",
            "ृ": "ri", "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ॉ": "o", "ॅ": "e",
        }
        consonants = {
            "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n",
            "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "n",
            "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
            "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
            "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
            "य": "y", "र": "r", "ल": "l", "व": "v", "ळ": "l",
            "श": "sh", "ष": "sh", "स": "s", "ह": "h",
        }
        nukta_map = {
            "क": "q", "ख": "kh", "ग": "g", "ज": "z", "ड": "d", "ढ": "rh", "फ": "f",
        }

        out: List[str] = []
        n = len(text)
        i = 0
        while i < n:
            ch = text[i]
            if ch in vowels:
                out.append(vowels[ch])
                i += 1
            elif ch in consonants:
                base = consonants[ch]
                if i + 1 < n and text[i + 1] == "़":
                    base = nukta_map.get(ch, base)
                    i += 1

                # Check next character for matra or virama
                if i + 1 < n and text[i + 1] == "्":
                    out.append(base)
                    i += 2
                elif i + 1 < n and text[i + 1] in matras:
                    out.append(base + matras[text[i + 1]])
                    i += 2
                else:
                    # Word-final schwa deletion for natural spoken Hindi
                    next_ch = text[i + 1] if (i + 1 < n) else " "
                    is_word_end = not ("\u0900" <= next_ch <= "\u097F")
                    if is_word_end:
                        out.append(base)
                    else:
                        out.append(base + "a")
                    i += 1
            elif ch in matras:
                out.append(matras[ch])
                i += 1
            elif ch in ("ं", "ँ"):
                out.append("n")
                i += 1
            elif ch == "ः":
                out.append("h")
                i += 1
            elif ch in ("।", "॥"):
                out.append(".")
                i += 1
            elif ch in ("्", "़"):
                i += 1
            else:
                out.append(ch)
                i += 1

        return "".join(out)

    _ENGLISH_TO_DEVANAGARI_LEXICON: Dict[str, str] = {
        "mount": "माउंट", "hua": "हुआ", "sect": "सेक्ट", "murim": "मुरिम", "world": "वर्ल्ड",
        "power": "पावर", "powers": "पावर्स", "level": "लेवल", "levels": "लेवल्स", "system": "सिस्टम",
        "master": "मास्टर", "masters": "मास्टर्स", "grandmaster": "ग्रैंडमास्टर", "young": "यंग",
        "leader": "लीडर", "sword": "स्वॉर्ड", "swords": "स्वॉर्ड्स", "swordmaster": "स्वॉर्डमास्टर",
        "blade": "ब्लेड", "technique": "टेक्नीक", "techniques": "टेक्नीक्स", "martial": "मार्शल",
        "art": "आर्ट", "arts": "आर्ट्स", "energy": "एनर्जी", "qi": "ची", "ki": "की", "mana": "माना",
        "aura": "ऑरा", "demonic": "डेमोनिक", "demon": "डेमन", "demons": "डेमन्स", "cult": "कल्ट",
        "heavenly": "हेवनली", "dragon": "ड्रैगन", "dragons": "ड्रैगन्स", "king": "किंग", "queen": "क्वीन",
        "lord": "लॉर्ड", "elder": "एल्डर", "elders": "एल्डर्स", "disciple": "डिसाइपल", "disciples": "डिसाइपल्स",
        "senior": "सीनियर", "junior": "जूनियर", "brother": "ब्रदर", "sister": "सिस्टर",
        "chung": "चुंग", "myung": "म्युंग", "baek": "बैक", "cheon": "चियोन", "yeo": "यियो", "woon": "वून",
        "yeowun": "यियोवून", "mok": "मोक", "gyeongwun": "ग्योंगवून", "lloyd": "लॉयड", "frontera": "फ्रॉन्टेरा",
        "javier": "जेवियर", "asrahan": "असराहान", "suho": "सुहो", "kim": "किम", "alicia": "एलिसिया",
        "podong": "पोडोंग", "poby": "पोबी", "julien": "जूलियन", "arcos": "आर्कोस", "jang": "जांग",
        "nano": "नैनो", "machine": "मशीन", "quest": "क्वेस्ट", "status": "स्टेटस", "skill": "स्किल",
        "skills": "स्किल्स", "attack": "अटैक", "defense": "डिफेंस", "speed": "स्पीड", "strength": "स्ट्रेंथ",
        "stamina": "स्टैमिना", "point": "पॉइंट", "points": "पॉइंट्स", "rank": "रैंक", "hunter": "हंटर",
        "hunters": "हंटर्स", "dungeon": "डंजन", "boss": "बॉस", "monster": "मॉन्स्टर", "monsters": "मॉन्स्टर्स",
        "guild": "गिल्ड", "gate": "गेट", "awakening": "अवेकनिंग", "player": "प्लेयर", "warning": "वॉर्निंग",
        "alert": "अलर्ट", "emergency": "इमरजेंसी", "danger": "डेंजर", "dangerous": "डेंजरस",
        "scan": "स्कैन", "scanning": "स्कैनिंग", "target": "टारगेट", "locked": "लॉक्ड", "complete": "कम्प्लीट",
        "success": "सक्सेस", "failed": "फेल्ड", "error": "एरर", "loading": "लोडिंग", "mode": "मोड",
        "normal": "नॉर्मल", "special": "स्पेशल", "secret": "सीक्रेट", "hidden": "हिडन", "ancient": "एंशिएंट",
        "divine": "डिवाइन", "supreme": "सुप्रीम", "ultimate": "अल्टीमेट", "final": "फाइनल",
        "first": "फर्स्ट", "second": "सेकंड", "third": "थर्ड", "next": "नेक्स्ट", "mysterious": "मिस्टीरियस",
        "mystery": "मिस्ट्री", "shocked": "शॉक्ड", "shock": "शॉक", "surprise": "सरप्राइज",
        "impossible": "इम्पॉसिबल", "unbelievable": "अनबिलीवेबल", "crazy": "क्रेज़ी", "mad": "मैड",
        "genius": "जीनियस", "talent": "टैलेंट", "legend": "लेजेंड", "legendary": "लेजेंडरी",
        "history": "हिस्ट्री", "future": "फ्यूचर", "past": "पास्ट", "time": "टाइम", "space": "स्पेस",
        "life": "लाइफ", "death": "डेथ", "blood": "ब्लड", "fire": "फायर", "ice": "आइस", "wind": "विंड",
        "lightning": "लाइटनिंग", "thunder": "थंडर", "shadow": "शैडो", "dark": "डार्क", "light": "लाइट",
        "soul": "सोल", "spirit": "स्पिरिट", "body": "बॉडी", "mind": "माइंड", "heart": "हार्ट",
        "core": "कोर", "meridian": "मेरिडियन", "meridians": "मेरिडियन्स", "dantian": "दांतियन",
        "elixir": "एलिक्सिर", "pill": "पिल", "poison": "पॉइज़न", "training": "ट्रेनिंग", "battle": "बैटल",
        "fight": "फाइट", "fighting": "फाइटिंग", "war": "वॉर", "victory": "विक्ट्री", "defeat": "डिफीट",
        "revenge": "रिवेंज", "plan": "प्लान", "idea": "आइडिया", "chance": "चांस", "luck": "लक",
        "fate": "फेट", "destiny": "डेस्टिनी", "promise": "प्रॉमिस", "truth": "ट्रुथ", "real": "रियल",
        "fake": "फेक", "true": "ट्रू", "false": "फॉल्स", "ready": "रेडी", "start": "स्टार्ट",
        "stop": "स्टॉप", "wait": "वेट", "move": "मूव", "run": "रन", "jump": "जंप", "strike": "स्ट्राइक",
        "slash": "स्लैश", "crush": "क्रश", "break": "ब्रेक", "destroy": "डिस्ट्रॉय", "kill": "किल",
        "save": "सेव", "protect": "प्रोटेक्ट", "help": "हेल्प", "control": "कंट्रोल", "limit": "लिमिट",
        "limits": "लिमिट्स", "test": "टेस्ट", "exam": "एग्जाम", "academy": "एकेडमी", "clan": "क्लैन",
        "family": "फैमिली", "house": "हाउस", "palace": "पैलेस", "castle": "कैसल", "empire": "एम्पायर",
        "kingdom": "किंगडम", "estate": "एस्टेट", "developer": "डेवलपर", "engineer": "इंजीनियर",
        "engineering": "इंजीनियरिंग", "building": "बिल्डिंग", "project": "प्रोजेक्ट", "money": "मनी",
        "gold": "गोल्ड", "silver": "सिल्वर", "contract": "कॉन्ट्रैक्ट", "deal": "डील", "knight": "नाइट",
        "knights": "नाइट्स", "guard": "गार्ड", "guards": "गार्ड्स", "soldier": "सोल्जर", "soldiers": "सोल्जर्स",
        "army": "आर्मी", "general": "जनरल", "commander": "कमांडर", "captain": "कैप्टन", "chief": "चीफ",
        "hero": "हीरो", "villain": "विलेन", "enemy": "एनिमी", "enemies": "एनिमीज़", "friend": "फ्रेंड",
        "friends": "फ्रेंड्स", "partner": "पार्टनर", "team": "टीम", "group": "ग्रुप", "member": "मेंबर",
        "members": "मेंबर्स", "return": "रिटर्न", "of": "ऑफ", "the": "द", "and": "एंड", "in": "इन",
        "on": "ऑन", "to": "टू", "for": "फॉर", "with": "विद", "from": "फ्रॉम", "by": "बाय",
        "no": "नो", "yes": "यस", "ok": "ओके", "okay": "ओके", "what": "व्हाट", "why": "व्हाई",
        "how": "हाउ", "who": "हू", "when": "व्हेन", "where": "व्हेयर", "now": "नाउ", "then": "देन",
        "here": "हियर", "there": "देयर", "all": "ऑल", "one": "वन", "two": "टू", "three": "थ्री",
        "four": "फोर", "five": "फाइव", "ten": "टेन", "hundred": "हंड्रेड", "thousand": "थाउजेंड",
        "million": "मिलियन", "billion": "बिलियन", "zero": "ज़ीरो", "full": "फुल", "half": "हाफ",
        "double": "डबल", "triple": "ट्रिपल", "super": "सुपर", "hyper": "हाइपर", "ultra": "अल्ट्रा",
        "mega": "मेगा", "max": "मैक्स", "maximum": "मैक्सिमम", "minimum": "मिनिमम", "high": "हाई",
        "low": "लो", "top": "टॉप", "bottom": "बॉटम", "left": "लेफ्ट", "right": "राइट", "center": "सेंटर",
        "front": "फ्रंट", "back": "बैक", "side": "साइड", "inside": "इनसाइड", "outside": "आउटसाइड",
        "up": "अप", "down": "डाउन", "over": "ओवर", "under": "अंडर", "again": "अगेन", "never": "नेवर",
        "always": "ऑलवेज", "maybe": "मेबी", "sure": "श्योर", "sorry": "सॉरी", "thanks": "थैंक्स",
        "thank": "थैंक", "you": "यू", "please": "प्लीज", "welcome": "वेलकम", "hello": "हेलो",
        "hi": "हाय", "bye": "बाय", "good": "गुड", "bad": "बैड", "best": "बेस्ट", "worst": "वर्स्ट",
        "better": "बेटर", "new": "न्यू", "old": "ओल्ड", "big": "बिग", "small": "स्मॉल", "great": "ग्रेट",
        "strong": "स्ट्रॉन्ग", "weak": "वीक", "fast": "फास्ट", "slow": "स्लो", "hard": "हार्ड",
        "easy": "इज़ी", "free": "फ्री", "safe": "सेफ", "dead": "डेड", "alive": "अलाइव", "smart": "स्मार्ट",
        "fool": "फूल", "idiot": "इडियट", "stupid": "स्टुपिड", "monster": "मॉन्स्टर", "beast": "बीस्ट",
        "god": "गॉड", "devil": "डेविल", "angel": "एंजेल", "ghost": "घोस्ट", "zombie": "ज़ॉम्बी",
        "magic": "मैजिक", "spell": "स्पेल", "curse": "कर्स", "blessing": "ब्लेसिंग", "miracle": "मिरेकल",
        "treasure": "ट्रेज़र", "weapon": "वेपन", "weapons": "वेपन्स", "armor": "आर्मर", "shield": "शील्ड",
        "spear": "स्पीयर", "bow": "बो", "arrow": "एरो", "dagger": "डैगर", "fist": "फिस्ट", "palm": "पाम",
        "kick": "किक", "punch": "पंच", "step": "स्टेप", "steps": "स्टेप्स", "shadow": "शैडो",
        "blossom": "ब्लॉसम", "plum": "प्लम", "flower": "फ्लावर", "petal": "पेटल", "petals": "पेटल्स",
        "mountain": "माउंटेन", "peak": "पीक", "river": "रिवर", "sea": "सी", "ocean": "ओशन", "sky": "स्काई",
        "heaven": "हेवन", "earth": "अर्थ", "hell": "हेल", "star": "स्टार", "stars": "स्टार्स",
        "sun": "सन", "moon": "मून", "cloud": "क्लाउड", "clouds": "क्लाउड्स", "rain": "रेन", "snow": "स्नो",
        "storm": "स्टॉर्म", "flame": "फ्लेम", "flames": "फ्लेम्स", "ash": "ऐश", "ashes": "ऐशेज",
        "dust": "डस्ट", "stone": "स्टोन", "rock": "रॉक", "iron": "आयरन", "steel": "स्टील",
        "chain": "चेन", "chains": "चेन्स", "seal": "सील", "barrier": "बैरियर", "formation": "फॉर्मेशन",
        "array": "अरे", "portal": "पोर्टल", "tower": "टावर", "hall": "हॉल", "room": "रूम", "door": "डोर",
        "road": "रोड", "path": "पाथ", "way": "वे", "line": "लाइन", "rule": "रूल", "rules": "रूल्स",
        "law": "लॉ", "order": "ऑर्डर", "command": "कमांड", "mission": "मिशन", "task": "टास्क",
        "job": "जॉब", "work": "वर्क", "game": "गेम", "story": "स्टोरी", "chapter": "चैप्टर",
        "part": "पार्ट", "scene": "सीन", "end": "एंड", "beginning": "बिगिनिंग",
    }

    @classmethod
    def _phonetic_english_word_to_devanagari(cls, word: str) -> str:
        """Convert an arbitrary Latin-script English word into phonetic Devanagari so Gemini TTS never triggers a UK/British accent."""
        w = word.lower().strip()
        if not w:
            return ""
        if w in cls._ENGLISH_TO_DEVANAGARI_LEXICON:
            return cls._ENGLISH_TO_DEVANAGARI_LEXICON[w]
        # Handle common suffixes on known words
        if w.endswith("s") and w[:-1] in cls._ENGLISH_TO_DEVANAGARI_LEXICON:
            return cls._ENGLISH_TO_DEVANAGARI_LEXICON[w[:-1]] + "्स"
        if w.endswith("ed") and w[:-2] in cls._ENGLISH_TO_DEVANAGARI_LEXICON:
            return cls._ENGLISH_TO_DEVANAGARI_LEXICON[w[:-2]] + "्ड"
        if w.endswith("ing") and w[:-3] in cls._ENGLISH_TO_DEVANAGARI_LEXICON:
            return cls._ENGLISH_TO_DEVANAGARI_LEXICON[w[:-3]] + "िंग"

        # Digraph & character-level phonetic transliteration into Devanagari
        digraphs = [
            ("tion", "शन"), ("sion", "ज़न"), ("sh", "श"), ("ch", "च"), ("th", "थ"),
            ("ph", "फ"), ("gh", "ग"), ("ck", "क"), ("ng", "ंग"), ("qu", "क्व"),
            ("ee", "ी"), ("oo", "ू"), ("ea", "ी"), ("ai", "े"), ("ay", "े"),
            ("ou", "ाउ"), ("ow", "ाउ"), ("au", "ॉ"), ("aw", "ॉ"),
        ]
        cons_map = {
            "b": "ब", "c": "क", "d": "ड", "f": "फ", "g": "ग", "h": "ह", "j": "ज",
            "k": "क", "l": "ल", "m": "म", "n": "न", "p": "प", "q": "क", "r": "र",
            "s": "स", "t": "ट", "v": "व", "w": "व", "x": "क्स", "y": "य", "z": "ज़",
        }
        vowel_initial = {"a": "ए", "e": "इ", "i": "आइ", "o": "ओ", "u": "अ"}
        vowel_matra = {"a": "ा", "e": "े", "i": "ि", "o": "ो", "u": "ु"}

        # Strip silent trailing 'e' on words longer than 3 chars
        if len(w) > 3 and w.endswith("e") and not w.endswith(("ee", "le", "re")):
            w = w[:-1]

        out: List[str] = []
        i = 0
        n = len(w)
        prev_was_cons = False
        while i < n:
            matched_dg = False
            for dg, rep in digraphs:
                if w.startswith(dg, i):
                    out.append(rep)
                    i += len(dg)
                    prev_was_cons = not rep[0] in "ािीुूेैोौं"
                    matched_dg = True
                    break
            if matched_dg:
                continue
            ch = w[i]
            if ch in cons_map:
                # Collapse double consonants (e.g., 'll' -> 'l')
                if i + 1 < n and w[i + 1] == ch:
                    i += 1
                out.append(cons_map[ch])
                prev_was_cons = True
            elif ch in vowel_initial:
                if prev_was_cons:
                    if ch != "u":  # 'u' after consonant acts as inherent schwa 'अ'
                        out.append(vowel_matra[ch])
                else:
                    out.append(vowel_initial[ch])
                prev_was_cons = False
            i += 1
        return "".join(out) or word

    @classmethod
    def ensure_pure_devanagari_for_indian_accent(cls, text: str) -> str:
        """
        Convert any Latin-script English words inside a Hindi+English sentence into
        Devanagari phonetics before sending to Gemini TTS. This guarantees Gemini's
        `Puck` voice stays 100% in its native Indian (`hi-IN`) accent and NEVER switches
        into a British/UK English accent on English words.
        """
        import re

        def _repl(match: re.Match) -> str:
            word = match.group(0)
            return cls._phonetic_english_word_to_devanagari(word)

        return re.sub(r"[A-Za-z]+", _repl, text)

    @staticmethod
    def _sanitize_human_pitch(voice_id: str, pitch: str) -> str:
        """
        Prevent metallic phase-vocoder pitch distortion on neural human voices.
        Indian & Multilingual Neural voices sound 100% organic at +0Hz; shifting pitch
        invokes a DSP phase-vocoder that introduces robotic artifacts.
        """
        import re

        p = (pitch or "+0Hz").strip()
        if "MultilingualNeural" in (voice_id or ""):
            return "+0Hz"
        m = re.match(r"^([+-]?\d+)\s*Hz$", p, flags=re.IGNORECASE)
        if m:
            hz_val = int(m.group(1))
            if -4 <= hz_val <= 4:
                return "+0Hz"
        return p

    _GEMINI_TTS_COOLDOWNS: Dict[str, float] = {}
    _LAST_GEMINI_TTS_TS: float = 0.0
    _PREFERRED_TTS_MODEL: Optional[str] = None
    _GEMINI_DAILY_QUOTA_EXHAUSTED: bool = False
    _F5_HINDI_MODEL: Any = None

    @classmethod
    def _is_f5_hindi_available(cls) -> bool:
        """Return True if f5_tts + CUDA GPU are available for fast local Hindi synthesis."""
        try:
            import importlib.util
            if importlib.util.find_spec("f5_tts") is None or importlib.util.find_spec("torch") is None:
                return False
            import torch
            return bool(torch.cuda.is_available())
        except Exception:
            return False

    @classmethod
    def _get_f5_hindi_model(cls) -> Any:
        """Load and cache SPRINGLab/F5-Hindi-24KHz on CUDA (with HF/Torch caches kept in workspace .cache)."""
        if cls._F5_HINDI_MODEL is not None:
            return cls._F5_HINDI_MODEL

        cache_root = Path.cwd() / ".cache"
        os.environ.setdefault("HF_HOME", str(cache_root / "huggingface"))
        os.environ.setdefault("TORCH_HOME", str(cache_root / "torch"))

        import torch
        from huggingface_hub import hf_hub_download
        from f5_tts.api import F5TTS

        device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Loading SPRINGLab/F5-Hindi-24KHz (F5TTS_Small) on {device}...")
        ckpt = hf_hub_download("SPRINGLab/F5-Hindi-24KHz", "model_2500000.safetensors")
        vocab = hf_hub_download("SPRINGLab/F5-Hindi-24KHz", "vocab.txt")
        cls._F5_HINDI_MODEL = F5TTS(
            model="F5TTS_Small",
            ckpt_file=ckpt,
            vocab_file=vocab,
            device=device,
        )
        return cls._F5_HINDI_MODEL

    @staticmethod
    def _resolve_f5_ref_audio(
        voice_name: str,
        gender: str = "male",
        age_group: str = "young_adult",
    ) -> Tuple[Path, str, float]:
        """
        Select an age- and gender-matched reference WAV clip, transcript, and F5 speed
        for F5-Hindi zero-shot voice cloning.
        """
        v = (voice_name or "Puck").replace("gemini:", "").strip().lower()
        g = (gender or "male").strip().lower()
        age = (age_group or "young_adult").strip().lower()

        default_ref_text = "तुमने बहुत बड़ी गलती कर दी, अब तुम्हारा अंत निश्चित है।"
        young_female_ref_text = "चिंता मत करो बेबी, अब इस दुनिया पर सिर्फ हमारी हुकूमत होगी!"
        story_puck_text = "तो दोस्तों, अब कहानी में वो जबरदस्त मोड़ आने वाला है, जिसे देखकर सबके होश उड़ जाएंगे!"
        story_charon_text = "इतनी जल्दी हार मानने वाला मैं नहीं हूँ, अब असली खेल तो अभी शुरू हुआ है।"
        story_fenrir_text = "तुम्हें अंदाज़ा भी नहीं है कि तुमने आज किस ताकत को जगा दिया है, अब अंजाम भुगतने के लिए तैयार रहो।"
        story_algenib_text = "कमाल है, इतने हमलों के बाद भी तुम खड़े हो? लेकिन इस बार बचने का कोई रास्ता नहीं मिलेगा!"
        story_kore_text = "मुझे तुम पर पूरा भरोसा था, लेकिन आज जो सच सामने आया है वो सब कुछ बदल देगा।"
        story_leda_text = "अरे सुनो तो सही! इतना सीरियस होने की ज़रूरत नहीं है, अभी तो सबसे मज़ेदार हिस्सा बाकी है!"

        if g == "female" or v in ("kore", "aoede", "leda", "zephyr", "callirrhoe", "autonoe"):
            if age in ("child", "teen") or v in ("leda", "zephyr"):
                spd = 1.03 if age in ("child", "teen") else 1.01
                for yf_p, yf_txt in (
                    (Path("exports/voice_refs/story_leda.wav"), story_leda_text),
                    (Path("exports/voice_refs/ref_female_young.wav"), young_female_ref_text),
                ):
                    if yf_p.exists():
                        return yf_p, yf_txt, spd
            spd = 0.98 if age == "elder" else 1.00
            candidates = [
                (Path("exports/voice_refs/story_kore.wav"), story_kore_text, spd),
                (Path("exports/demo_gemini_kore.wav"), default_ref_text, spd),
                (Path("exports/voice_refs/ref_female_young.wav"), young_female_ref_text, spd),
            ]
        elif v == "algenib":
            spd = 0.98 if age == "elder" else 1.00
            candidates = [
                (Path("exports/voice_refs/story_algenib.wav"), story_algenib_text, spd),
                (Path("exports/demo_gemini_algenib.wav"), default_ref_text, spd),
                (Path("exports/demo_gemini_fenrir.wav"), default_ref_text, spd),
                (Path("exports/demo_gemini_puck.wav"), default_ref_text, spd),
            ]
        elif age in ("elder",) or v == "fenrir":
            spd = 0.96 if age == "elder" else 0.99
            candidates = [
                (Path("exports/voice_refs/story_fenrir.wav"), story_fenrir_text, spd),
                (Path("exports/demo_gemini_fenrir.wav"), default_ref_text, spd),
                (Path("exports/demo_gemini_algenib.wav"), default_ref_text, spd),
                (Path("exports/demo_gemini_puck.wav"), default_ref_text, spd),
            ]
        elif v in ("charon", "orus") or age == "adult":
            candidates = [
                (Path("exports/voice_refs/story_charon.wav"), story_charon_text, 1.00),
                (Path("exports/demo_gemini_charon.wav"), default_ref_text, 1.00),
                (Path("exports/demo_gemini_puck.wav"), default_ref_text, 1.00),
            ]
        else:
            spd = 1.03 if age in ("child", "teen") else 1.01
            candidates = [
                (Path("exports/voice_refs/story_puck.wav"), story_puck_text, spd),
                (Path("exports/demo_gemini_puck.wav"), default_ref_text, spd),
                (Path("exports/demo_gemini_charon.wav"), default_ref_text, spd),
            ]

        for p, rtxt, spd in candidates:
            if p.exists():
                return p, rtxt, spd
        raise FileNotFoundError(
            "No reference voice clip found in exports/ (expected demo_gemini_puck.wav / demo_gemini_kore.wav)."
        )

    def _synthesize_with_f5_hindi(
        self,
        text: str,
        output_file: Path,
        voice_name: str = "Puck",
        gender: str = "male",
        rate: str = "+2%",
        age_group: str = "young_adult",
    ) -> None:
        """Synthesize natural Hindi speech locally using SPRINGLab/F5-Hindi-24KHz + FFmpeg mastering."""
        model = self._get_f5_hindi_model()
        ref_file, ref_text, age_speed = self._resolve_f5_ref_audio(voice_name, gender, age_group=age_group)
        devanagari_text = self.ensure_pure_devanagari_for_indian_accent(
            self.humanize_text_for_natural_speech(text)
        )
        temp_wav = output_file.with_suffix(".f5_temp.wav")
        output_file.parent.mkdir(parents=True, exist_ok=True)
        model.infer(
            ref_file=str(ref_file),
            ref_text=ref_text,
            gen_text=devanagari_text,
            file_wave=str(temp_wav),
            speed=age_speed,
            nfe_step=32,
            cfg_strength=2.2,
            remove_silence=True,
            cross_fade_duration=0.12,
        )
        self._enhance_vocal_audio(temp_wav, output_file, rate=rate or "+2%")
        if temp_wav.exists():
            try:
                temp_wav.unlink()
            except Exception:
                pass

    def _enhance_vocal_audio(self, raw_audio: Path, target_audio: Path, rate: str = "+0%") -> None:
        """
        Apply Modern Storytelling Broadcast Mastering Chain via FFmpeg:
        - Strips sluggish dead silence at start/end/mid-sentence so speech never feels lagging
        - Warm 165Hz chest body, clean 290Hz de-mud, crisp 3.4kHz & 7.5kHz studio presence
        - Gentle vocal compression for intimate, upfront Gemini-like storytelling clarity
        """
        atempo_filter = ""
        m = re.match(r"^([+-]?\d+)\s*%$", (rate or "+0%").strip())
        if m:
            pct = int(m.group(1))
            if pct != 0:
                factor = max(0.75, min(1.50, 1.0 + (pct / 100.0)))
                atempo_filter = f"atempo={factor:.2f},"

        filter_str = (
            "silenceremove=start_periods=1:start_silence=0.03:start_threshold=-42dB:"
            "stop_periods=-1:stop_duration=0.20:stop_threshold=-42dB,"
            f"{atempo_filter}"
            "highpass=f=75,"
            "equalizer=f=165:t=q:w=1.2:g=1.4,"
            "equalizer=f=290:t=q:w=1.5:g=-2.0,"
            "equalizer=f=3400:t=q:w=1.2:g=2.2,"
            "equalizer=f=7500:t=q:w=1.4:g=1.2,"
            "acompressor=threshold=-18dB:ratio=2.4:attack=8:release=110:makeup=1.5,"
            "afade=t=in:st=0:d=0.015,"
            "apad=pad_dur=0.06,"
            "loudnorm=I=-15:TP=-1.2:LRA=10"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", str(raw_audio),
            "-af", filter_str,
            "-c:a", "libmp3lame",
            "-b:a", "192k",
            str(target_audio),
        ]
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
        except Exception as exc:
            logger.warning(f"Audio enhancement filter failed ({exc}), falling back to raw audio.")
            shutil.copy(str(raw_audio), str(target_audio))

    def _request_gemini_tts_pcm(
        self,
        tts_prompt: str,
        clean_voice: str = "Puck",
        is_batch: bool = False,
    ) -> bytes:
        """
        Request 24,000 Hz 16-bit mono signed PCM audio bytes from Google Gemini Native Audio TTS.
        Locks strictly to ONE voice ('Puck'), ONE Indian language code ('hi-IN'), and pure Devanagari
        phonetics across all configured Google AI Studio Gemini API keys (supporting both `AQ.` Authorization
        keys and `AIza` Standard keys via the `x-goog-api-key` header).
        """
        import base64
        import io
        import json
        import os
        import time
        import urllib.error
        import urllib.request
        import wave

        raw_key_parts: List[str] = []
        for env_k, env_v in sorted(os.environ.items()):
            if env_k in ("GEMINI_API_KEY", "GEMINI_API_KEYS") or env_k.startswith("GEMINI_API_KEY_"):
                if env_v and env_v.strip():
                    raw_key_parts.append(env_v.strip("\"' "))

        env_file = Path(".env")
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line_s = line.strip()
                if not line_s or line_s.startswith("#") or "=" not in line_s:
                    continue
                k_name, k_val = line_s.split("=", 1)
                k_name = k_name.strip()
                if k_name in ("GEMINI_API_KEY", "GEMINI_API_KEYS") or k_name.startswith("GEMINI_API_KEY_"):
                    raw_key_parts.append(k_val.strip("\"' "))

        api_keys: List[str] = []
        for part in raw_key_parts:
            for k in part.split(","):
                k_clean = k.strip("\"' ")
                if k_clean and k_clean not in api_keys:
                    api_keys.append(k_clean)

        if not api_keys:
            raise ValueError("GEMINI_API_KEY is required for Gemini TTS voice synthesis.")

        # Validate requested Gemini voice against supported prebuilt voices (default: Puck)
        # and convert any Latin English words into Devanagari phonetics so Gemini TTS
        # never switches to a UK/British English accent
        from manhwa_studio.story.character_registry import GEMINI_TTS_VOICES
        clean_voice = (clean_voice or "Puck").replace("gemini:", "").strip()
        if clean_voice not in GEMINI_TTS_VOICES:
            clean_voice = "Puck"
        devanagari_prompt = self.ensure_pure_devanagari_for_indian_accent(tts_prompt)

        # Lock strictly to 'gemini-2.5-flash-preview-tts' across ALL configured AI Studio keys (AIza + AQ.)
        # so the Puck voice timbre stays 100% identical to your previously built chapters
        candidates = [
            ("gemini-2.5-flash-preview-tts", "generateContent"),
        ]

        elapsed = time.time() - VoiceDirector._LAST_GEMINI_TTS_TS
        if elapsed < 2.0:
            time.sleep(2.0 - elapsed)

        max_rounds = 12 if is_batch else 5
        last_error: Optional[Exception] = None

        for round_idx in range(1, max_rounds + 1):
            for model_name, ep_type in candidates:
                for key_idx, api_key in enumerate(api_keys, start=1):
                    cd_key = f"{api_key[-6:]}:{model_name}"
                    if VoiceDirector._GEMINI_TTS_COOLDOWNS.get(cd_key, 0.0) > time.time():
                        continue

                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
                    payload = {
                        "contents": [{
                            "role": "user",
                            "parts": [{"text": devanagari_prompt}]
                        }],
                        "generationConfig": {
                            "responseModalities": ["AUDIO"],
                            "speechConfig": {
                                "languageCode": "hi-IN",
                                "voiceConfig": {
                                    "prebuiltVoiceConfig": {
                                        "voiceName": clean_voice
                                    }
                                },
                            },
                        },
                    }

                    req = urllib.request.Request(
                        url,
                        data=json.dumps(payload).encode("utf-8"),
                        headers={
                            "Content-Type": "application/json",
                            "x-goog-api-key": api_key,
                        },
                    )

                    try:
                        VoiceDirector._LAST_GEMINI_TTS_TS = time.time()
                        timeout_sec = 95 if is_batch else 40
                        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                            resp_data = json.loads(resp.read().decode("utf-8"))
                            cand = resp_data["candidates"][0]["content"]["parts"][0]
                            audio_b64 = cand.get("inlineData", {}).get("data")

                            if not audio_b64:
                                raise RuntimeError(f"Gemini ({model_name}) returned empty audio")

                            raw_bytes = base64.b64decode(audio_b64)
                            VoiceDirector._GEMINI_TTS_COOLDOWNS.pop(cd_key, None)
                            # Cleanly unwrap RIFF WAV container (used by Gemini 3.8 TTS) to pure 24kHz 16-bit mono PCM
                            if raw_bytes[:4] == b"RIFF":
                                try:
                                    with wave.open(io.BytesIO(raw_bytes), "rb") as wf:
                                        return wf.readframes(wf.getnframes())
                                except Exception:
                                    if len(raw_bytes) > 44:
                                        return raw_bytes[44:]
                            return raw_bytes

                    except urllib.error.HTTPError as he:
                        last_error = he
                        err_body = ""
                        try:
                            err_body = he.read().decode("utf-8", errors="ignore")
                        except Exception:
                            pass
                        if he.code in (400, 401, 403, 404):
                            VoiceDirector._GEMINI_TTS_COOLDOWNS[cd_key] = time.time() + 1800.0
                            logger.warning(
                                f"Gemini API key [{key_idx}/{len(api_keys)}] (...{api_key[-6:]}) "
                                f"rejected on {model_name} (HTTP {he.code}): {err_body[:180]}"
                            )
                            continue
                        elif he.code == 429:
                            if "PerDay" in err_body:
                                # Daily quota exhausted on this key+model; rotate to next key
                                VoiceDirector._GEMINI_TTS_COOLDOWNS[cd_key] = time.time() + 1800.0
                                if len(api_keys) > 1:
                                    logger.info(
                                        f"Gemini API key [{key_idx}/{len(api_keys)}] (...{api_key[-6:]}) "
                                        f"reached daily quota on {model_name}; rotating to next Gemini key..."
                                    )
                            else:
                                # Per-Minute RPM limit
                                VoiceDirector._GEMINI_TTS_COOLDOWNS[cd_key] = time.time() + 21.0
                            continue
                    except Exception as exc:
                        last_error = exc
                        continue

            if round_idx < max_rounds:
                now2 = time.time()
                short_waits = [
                    cd - now2
                    for cd in VoiceDirector._GEMINI_TTS_COOLDOWNS.values()
                    if 0.0 < (cd - now2) <= 35.0
                ]
                if short_waits:
                    wait_s = max(8.0, min(short_waits) + 1.0)
                    logger.info(f"Pacing Gemini TTS RPM window ({wait_s:.1f}s before retry {round_idx + 1}/{max_rounds})...")
                    time.sleep(wait_s)
                else:
                    # All configured Gemini keys hit daily quota limits
                    VoiceDirector._GEMINI_DAILY_QUOTA_EXHAUSTED = True
                    break

        raise RuntimeError(
            f"All {len(api_keys)} configured Gemini API key(s) exhausted Gemini TTS quota ({last_error}). "
            f"Stopping execution instead of falling back to default voice."
        )

    def _split_pcm_into_scenes(
        self,
        pcm_bytes: bytes,
        texts: List[str],
        sample_rate: int = 24000,
    ) -> List[bytes]:
        """
        Split a batched 24,000 Hz 16-bit signed mono PCM recording into N contiguous, non-overlapping
        scene PCM slices using Global Dynamic Programming (Viterbi) Silence-Valley Alignment.
        - Evaluates each scene's individual duration (f - prev_f) against its text weight so speaking-rate
          variations never accumulate drift across the batch.
        - Heavily penalizes non-silent frames so boundaries always land in true inter-sentence pauses.
        - Snaps boundaries to exact zero-crossings and keeps slices 100% contiguous so concatenating
          scene_001..scene_N reconstructs the unbroken studio recording without a single cut word or pop.
        """
        from array import array
        import math

        n_scenes = len(texts)
        if n_scenes <= 1:
            return [pcm_bytes]

        num_samples = len(pcm_bytes) // 2
        samples = array("h")
        samples.frombytes(pcm_bytes[: num_samples * 2])

        # 20ms frame = 480 samples at 24,000 Hz (50 frames/sec)
        frame_len = 480
        num_frames = max(1, len(samples) // frame_len)
        if num_frames < n_scenes * 6:
            chunk = max(2, (len(samples) // n_scenes))
            return [
                samples[i * chunk : (i + 1) * chunk if i < n_scenes - 1 else len(samples)].tobytes()
                for i in range(n_scenes)
            ]

        # Compute RMS energy for each 20ms frame
        rms: List[float] = []
        for f_idx in range(num_frames):
            base = f_idx * frame_len
            seg = samples[base : base + frame_len]
            mean_sq = sum(s * s for s in seg) / float(frame_len)
            rms.append(math.sqrt(mean_sq))

        # Smooth RMS with a 7-frame (140ms) moving window to identify true inter-sentence silence valleys
        smooth_rms: List[float] = []
        for f_idx in range(num_frames):
            w_lo = max(0, f_idx - 3)
            w_hi = min(num_frames, f_idx + 4)
            smooth_rms.append(sum(rms[w_lo:w_hi]) / float(w_hi - w_lo))

        max_rms = max(smooth_rms) if smooth_rms else 1.0
        active_thresh = max(100.0, max_rms * 0.05)

        f_start = 0
        while f_start < num_frames - 1 and smooth_rms[f_start] < active_thresh:
            f_start += 1
        f_end = num_frames - 1
        while f_end > f_start + 1 and smooth_rms[f_end] < active_thresh:
            f_end -= 1

        span = max(n_scenes * 6, f_end - f_start)

        # Weight each scene by spoken character count plus punctuation pause weight
        weights: List[float] = []
        for t in texts:
            t_str = t.strip()
            punct_bonus = 6.0 * sum(t_str.count(p) for p in (",", "।", "!", "?", "."))
            weights.append(max(12.0, float(len(t_str)) + punct_bonus))
        total_w = sum(weights)
        expected_durs = [span * (w / total_w) for w in weights]

        # Precompute frame silence cost (0 in deep silence valleys, high during active speech)
        node_cost: List[float] = []
        for f_idx in range(num_frames):
            e_norm = smooth_rms[f_idx] / float(max(1.0, max_rms))
            is_local_min = (
                f_idx > 0
                and f_idx < num_frames - 1
                and smooth_rms[f_idx] <= smooth_rms[f_idx - 1]
                and smooth_rms[f_idx] <= smooth_rms[f_idx + 1]
            )
            if e_norm < 0.045:
                c = e_norm * 1.5 - (0.25 if is_local_min else 0.0)
            elif e_norm < 0.10:
                c = 0.4 + e_norm * 4.0 - (0.15 if is_local_min else 0.0)
            else:
                # Active speech syllable — strong penalty so we never split mid-word
                c = 4.5 + e_norm * 18.0
            node_cost.append(c)

        # Global Dynamic Programming over (boundary_idx k in 1..n_scenes-1, frame_idx)
        # Step size of 2 frames (40ms) keeps DP instantaneous (<4ms) while refining to 1-frame minima after
        min_scene_f = max(25, int(min(expected_durs) * 0.35))
        cum_exp: List[float] = [float(f_start)]
        for d in expected_durs:
            cum_exp.append(cum_exp[-1] + d)

        n_splits = n_scenes - 1
        dp_tables: List[Dict[int, float]] = [{} for _ in range(n_splits)]
        backptr: List[Dict[int, int]] = [{} for _ in range(n_splits)]

        for k in range(n_splits):
            center_f = int(cum_exp[k + 1])
            window_r = max(90, int(span * 0.28))
            lo_f = max(f_start + (k + 1) * min_scene_f, center_f - window_r)
            hi_f = min(f_end - (n_splits - k) * min_scene_f, center_f + window_r)
            if lo_f >= hi_f:
                lo_f = max(1, min(num_frames - 2, center_f - 20))
                hi_f = max(lo_f + 1, min(num_frames - 1, center_f + 20))

            mu_k = expected_durs[k]
            tol_k = max(30.0, mu_k * 0.42)

            # Candidate frames for boundary k (every 2 frames plus any deep silence minima)
            cand_frames = sorted(
                set(range(lo_f, hi_f + 1, 2))
                | {
                    f
                    for f in range(lo_f, hi_f + 1)
                    if smooth_rms[f] < max_rms * 0.07
                }
            )

            for f in cand_frames:
                nc = node_cost[f]
                if k == 0:
                    dur_0 = float(f - f_start)
                    dev_0 = (dur_0 - mu_k) / tol_k
                    score = nc + (dev_0 * dev_0)
                    if n_splits == 1:
                        dur_last = float(f_end - f)
                        tol_last = max(30.0, expected_durs[-1] * 0.42)
                        dev_last = (dur_last - expected_durs[-1]) / tol_last
                        score += dev_last * dev_last
                    dp_tables[0][f] = score
                    backptr[0][f] = 0
                else:
                    best_prev = -1
                    best_val = float("inf")
                    for prev_f, prev_score in dp_tables[k - 1].items():
                        d_cur = f - prev_f
                        if d_cur < min_scene_f:
                            continue
                        dev = ( float(d_cur) - mu_k ) / tol_k
                        val = prev_score + nc + (dev * dev)
                        if val < best_val:
                            best_val = val
                            best_prev = prev_f
                    if best_prev != -1:
                        if k == n_splits - 1:
                            dur_last = float(f_end - f)
                            tol_last = max(30.0, expected_durs[-1] * 0.42)
                            dev_last = (dur_last - expected_durs[-1]) / tol_last
                            best_val += dev_last * dev_last
                        dp_tables[k][f] = best_val
                        backptr[k][f] = best_prev

        # Backtrack optimal split frames
        if dp_tables[-1]:
            curr_f = min(dp_tables[-1], key=lambda x: dp_tables[-1][x])
            chosen_internal: List[int] = [curr_f]
            for k in range(n_splits - 1, 0, -1):
                curr_f = backptr[k][curr_f]
                chosen_internal.append(curr_f)
            chosen_internal.reverse()
        else:
            # Fallback proportional split if DP window was degenerate
            chosen_internal = [int(cum_exp[k + 1]) for k in range(n_splits)]

        # Fine-tune each chosen frame within +-3 frames to the exact minimum RMS frame,
        # then snap to the nearest zero-crossing sample so boundaries are 100% click-free and contiguous
        split_samples: List[int] = [0]
        for k, f_cand in enumerate(chosen_internal):
            r_lo = max(1, f_cand - 3)
            r_hi = min(num_frames - 2, f_cand + 3)
            best_f = min(range(r_lo, r_hi + 1), key=lambda idx: rms[idx])
            center_sample = best_f * frame_len + (frame_len // 2)
            s_lo = max(split_samples[-1] + 2400, center_sample - 240)
            s_hi = min(len(samples) - (n_splits - k) * 2400, center_sample + 240)
            if s_lo < s_hi:
                best_s = min(range(s_lo, s_hi), key=lambda s_idx: abs(samples[s_idx]))
            else:
                best_s = max(split_samples[-1] + 480, min(len(samples) - 480, center_sample))
            split_samples.append(best_s)
        split_samples.append(len(samples))

        return [
            samples[split_samples[i] : split_samples[i + 1]].tobytes()
            for i in range(n_scenes)
        ]

    def _master_batch_pcm(self, pcm_bytes: bytes, temp_dir: Path, rate: str = "+2%") -> bytes:
        """
        Master an entire multi-scene Gemini batch recording as a single continuous wave
        (highpass + presence EQ + tempo + loudness normalization) BEFORE slicing into scenes.
        Prevents per-slice loudnorm AGC pumping and mid-sentence padding gaps.
        """
        import wave

        raw_wav = temp_dir / "_batch_raw.wav"
        mastered_wav = temp_dir / "_batch_mastered.wav"
        with wave.open(str(raw_wav), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(pcm_bytes)

        atempo_filter = ""
        m = re.match(r"^([+-]?\d+)\s*%$", (rate or "+0%").strip())
        if m:
            pct = int(m.group(1))
            if pct != 0:
                factor = max(0.75, min(1.50, 1.0 + (pct / 100.0)))
                atempo_filter = f"atempo={factor:.2f},"

        filter_str = (
            f"{atempo_filter}"
            "highpass=f=75,"
            "equalizer=f=280:t=q:w=1.5:g=-1.8,"
            "equalizer=f=3200:t=q:w=1.2:g=1.6,"
            "loudnorm=I=-16:TP=-1.5:LRA=11,"
            "aresample=24000"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", str(raw_wav),
            "-af", filter_str,
            "-ac", "1",
            "-ar", "24000",
            "-c:a", "pcm_s16le",
            str(mastered_wav),
        ]
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
            with wave.open(str(mastered_wav), "rb") as rf:
                mastered_pcm = rf.readframes(rf.getnframes())
            if len(mastered_pcm) > 4800:
                return mastered_pcm
        except Exception as exc:
            logger.warning(f"Batch PCM mastering fallback to raw PCM: {exc}")
        finally:
            for p in (raw_wav, mastered_wav):
                if p.exists():
                    try:
                        p.unlink()
                    except Exception:
                        pass
        return pcm_bytes

    def _synthesize_batch_with_gemini(
        self,
        batch_items: List[Tuple[SceneItem, Path, VoiceSetting, str]],
    ) -> bool:
        """
        Synthesize a chronological batch of up to 12 scenes in a SINGLE Gemini TTS API call,
        master the continuous batch wave once, and split into contiguous scene MP3s at silence valleys.
        """
        import wave

        if not batch_items or VoiceDirector._GEMINI_DAILY_QUOTA_EXHAUSTED:
            return False

        clean_voice = batch_items[0][3]
        rate_str = batch_items[0][2].rate or "+2%"
        out_dir = batch_items[0][1].parent
        texts = [
            self.humanize_text_for_natural_speech(sc.narration_text or sc.subtitle_text or "...")
            for sc, _, _, _ in batch_items
        ]
        # Ensure every scene ends with clear sentence-final punctuation so Gemini TTS pauses cleanly
        formatted_lines: List[str] = []
        for t in texts:
            t_clean = t.strip()
            if not t_clean.endswith(("।", "!", "?", ".")):
                t_clean += "।"
            formatted_lines.append(t_clean)

        # Join with clean paragraph breaks (no ellipses '...' so Gemini never sighs/hums between scenes)
        combined_prompt = "\n\n".join(formatted_lines)

        try:
            raw_pcm = self._request_gemini_tts_pcm(
                tts_prompt=combined_prompt,
                clean_voice=clean_voice,
                is_batch=True,
            )
            mastered_pcm = self._master_batch_pcm(raw_pcm, out_dir, rate=rate_str)
            pcm_slices = self._split_pcm_into_scenes(mastered_pcm, formatted_lines)
            for (scene_obj, out_file, voice_cfg, _), slice_bytes in zip(batch_items, pcm_slices):
                temp_wav = out_file.with_suffix(".temp.wav")
                with wave.open(str(temp_wav), "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(24000)
                    wf.writeframes(slice_bytes)
                cmd = [
                    "ffmpeg", "-y",
                    "-i", str(temp_wav),
                    "-c:a", "libmp3lame",
                    "-b:a", "192k",
                    str(out_file),
                ]
                subprocess.run(cmd, capture_output=True, check=True)
                if temp_wav.exists():
                    try:
                        temp_wav.unlink()
                    except Exception:
                        pass
            return True
        except Exception as batch_err:
            logger.warning(f"Batched Gemini TTS ({clean_voice}, {len(batch_items)} scenes) failed: {batch_err}")
            if "PerDay" in str(batch_err):
                VoiceDirector._GEMINI_DAILY_QUOTA_EXHAUSTED = True
            return False

    def _synthesize_with_gemini(
        self,
        text: str,
        output_file: Path,
        voice_id: str = "Puck",
        rate: str = "+2%",
    ) -> None:
        """
        Synthesize ultra-realistic human speech for a single scene/preview using Google Gemini Native Audio TTS.
        """
        import wave

        if VoiceDirector._GEMINI_DAILY_QUOTA_EXHAUSTED:
            raise RuntimeError("Gemini TTS daily free-tier quota reached")

        from manhwa_studio.story.character_registry import GEMINI_TTS_VOICES
        clean_text = self.humanize_text_for_natural_speech(text)
        clean_voice = (voice_id or "Puck").replace("gemini:", "").strip()
        if clean_voice not in GEMINI_TTS_VOICES:
            clean_voice = "Puck"

        pcm_bytes = self._request_gemini_tts_pcm(
            tts_prompt=clean_text,
            clean_voice=clean_voice,
            is_batch=False,
        )
        temp_wav = output_file.with_suffix(".temp.wav")
        with wave.open(str(temp_wav), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(pcm_bytes)

        self._enhance_vocal_audio(temp_wav, output_file, rate=rate or "+2%")
        if temp_wav.exists():
            try:
                temp_wav.unlink()
            except Exception:
                pass

    _STRICT_MALE_SPEAKERS = (
        "narrator", "सूत्रधार", "कथावाचक", "protagonist", "hero", "main lead",
        "chung myung", "baek cheon", "yoon jong", "jo gul", "hyun jong", "hyun sang", "hyun young", "un geom", "un am",
        "lloyd", "lloyd frontera", "kim suho", "javier", "javier asrahan", "julien", "count frontera", "arcos",
        "cheon yeo-woon", "yeo-woon", "yeowun", "cheon ma", "mok gyeongwun", "guard jang", "sub-meng", "marakim",
        "boy", "boyfriend", "ladka", "man", "guy", "brother", "father", "dad", "grandpa", "grandfather", "son", "uncle",
        "sect leader", "elder", "master", "grandmaster", "patriarch", "lord", "count", "duke", "king", "prince",
        "knight", "guard", "loyal guard", "rival", "soldier", "swordsman", "warrior", "cadet", "instructor",
        "villain", "assassin", "bandit", "boss", "antagonist", "dragon king", "dragon elder",
    )

    _STRICT_FEMALE_SPEAKERS = (
        "yu iseol", "iseol", "tang soso", "soso", "alicia", "queen alicia", "countess", "countess frontera",
        "mun ku", "lady mun", "lady hwa", "nano", "podong", "poby",
        "girl", "girlfriend", "dragon girl", "woman", "young woman", "lady", "noble lady", "noblewoman",
        "queen", "empress", "princess", "duchess", "mother", "mom", "sister", "maiden", "maid", "heroine",
        "female", "ladki", "aurat",
    )

    def detect_scene_gender(self, scene: SceneItem) -> str:
        """
        Accurately classify whether the speaking character in `scene` is 'female' or 'male'
        using a 3-layer cascade:
        1. Canon Male & Female Character Protection (prevents long-haired Murim male heroes from getting female voices
           and ensures female characters like Yu Iseol, Alicia, Mun Ku, Girlfriend always get female voices).
        2. Explicit `scene.speaker_gender` from multimodal panel face detection.
        3. First-person Hindi verb morphology ('रही हूँ', 'करूँगी', 'जाऊँगी' vs 'रहा हूँ', 'करूँगा', 'जाऊँगा').
        """
        spk = (getattr(scene, "speaker", "") or "Narrator").strip().lower()
        spk_base = re.sub(r"\s*[\(\[\-].*$", "", spk).strip()
        text = (getattr(scene, "narration_text", "") or getattr(scene, "subtitle_text", "") or "").strip()

        # Layer 1A: Exact or token match against strict male roles/characters
        if spk_base in self._STRICT_MALE_SPEAKERS or any(
            re.search(rf"\b{re.escape(m)}\b", spk_base) for m in self._STRICT_MALE_SPEAKERS
        ):
            # Ensure Female keywords like 'lady' or 'girl' aren't explicitly in speaker name
            if not any(f in spk for f in ("lady", "girl", "woman", "queen", "mother", "sister", "countess", "princess", "duchess", "maid", "heroine", "nano")):
                return "male"

        # Layer 1B: Match against strict female roles/characters
        if spk_base in self._STRICT_FEMALE_SPEAKERS or any(
            re.search(rf"\b{re.escape(f)}\b", spk_base) for f in self._STRICT_FEMALE_SPEAKERS
        ):
            return "female"

        # Layer 2: Explicit speaker_gender from Vision LLM panel face inspection
        explicit_gender = (getattr(scene, "speaker_gender", None) or "").strip().lower()
        if explicit_gender == "female":
            return "female"
        if explicit_gender in ("male", "narrator"):
            return "male"

        # Layer 3: First-person Hindi verb gender morphology in spoken dialogue
        fem_verb_patterns = (
            r"\bमैं\b[^।!?]{0,40}\b(रही\s+हूँ|रही\s+थी|करूँगी|करूंगी|जाऊँगी|जाऊंगी|आऊँगी|आऊंगी|बताऊँगी|छोड़ूँगी|लूँगी|दूँगी|कहती\s+हूँ|चाहती\s+हूँ|सकती\s+हूँ|गई\s+हूँ|गई\s+थी)\b",
            r"\b(करूँगी|करूंगी|जाऊँगी|जाऊंगी|रही\s+हूँ|सकती\s+हूँ|चाहती\s+हूँ)\b",
        )
        male_verb_patterns = (
            r"\bमैं\b[^।!?]{0,40}\b(रहा\s+हूँ|रहा\s+था|करूँगा|करूंगा|जाऊँगा|जाऊंगा|आऊँगा|आऊंगा|बताऊँगा|छोड़ूँगा|लूँगा|दूँगा|कहता\s+हूँ|चाहता\s+हूँ|सकता\s+हूँ|गया\s+हूँ|गया\s+था)\b",
            r"\b(करूँगा|करूंगा|जाऊँगा|जाऊंगा|रहा\s+हूँ|सकता\s+हूँ|चाहता\s+हूँ)\b",
        )
        if any(re.search(p, text) for p in fem_verb_patterns) and not any(re.search(p, text) for p in male_verb_patterns):
            return "female"

        return "male"

    def verify_chapter_genders_from_panels(
        self,
        manifest: SceneManifest,
        artwork_dir: Optional[Path] = None,
        registry: Optional[Any] = None,
    ) -> None:
        """
        Inspect scenes in `manifest`:
        1. Resolve each speaking character against the per-manhwa `CharacterRegistry` (cache-first by name/alias
           and cropped face dHash). Only new/unconfirmed characters trigger a single Gemini Vision call with
           manhwa name + cropped face to confirm canonical name, gender, age, and look, then store it for reuse.
        2. Enforce grammatical gender consistency in first-person Hindi verbs so male speakers never use
           feminine self-verbs ('रही हूँ' -> 'रहा हूँ') and female speakers never use masculine self-verbs ('रहा हूँ' -> 'रही हूँ').
        """
        from manhwa_studio.story.character_registry import (
            CharacterRegistry,
            NARRATOR_ALIASES,
            strip_speaker_modifiers,
        )

        reg = registry or CharacterRegistry(self.profile.series_name)
        llm_prov = os.environ.get("LLM_PROVIDER", "gemini").strip().lower()
        tts_prov = os.environ.get("TTS_PROVIDER", "auto").strip().lower()
        # In F5-Hindi / Ollama mode, use instant zero-API local auto-casting so pro-render never burns Gemini quota
        has_api_key = (
            llm_prov != "ollama"
            and tts_prov not in ("f5_hindi", "f5", "indicf5")
            and bool(os.environ.get("GEMINI_API_KEY", "").strip() or os.environ.get("GEMINI_API_KEYS", "").strip())
        )

        for sc in manifest.scenes:
            raw_spk = (sc.speaker or "Narrator").strip()
            base_spk = strip_speaker_modifiers(raw_spk)
            if base_spk.lower() in NARRATOR_ALIASES:
                sc.speaker_gender = "narrator"
                continue

            panel_path = (artwork_dir / sc.image_file) if (artwork_dir and sc.image_file) else None
            profile = reg.resolve_or_confirm_character(
                speaker=raw_spk,
                panel_path=panel_path,
                dialogue_text=sc.narration_text or sc.subtitle_text or "",
                allow_gemini=has_api_key,
            )
            if profile:
                # Preserve any situational tag like '(Shocked)' while updating to confirmed canonical name
                tag_match = re.search(r"(\s*[\(\[\-].*)$", raw_spk)
                tag_suffix = tag_match.group(1) if tag_match else ""
                if profile.canonical_name and profile.canonical_name.lower() != base_spk.lower():
                    sc.speaker = f"{profile.canonical_name}{tag_suffix}"
                sc.speaker_gender = profile.gender

        # Assign final resolved speaker_gender and fix any first-person Hindi verb gender mismatches
        for sc in manifest.scenes:
            if (getattr(sc, "speaker_gender", None) or "").lower() == "narrator":
                continue
            gender = self.detect_scene_gender(sc)
            sc.speaker_gender = gender
            txt = sc.narration_text or sc.subtitle_text or ""
            if gender == "male" and "मैं" in txt:
                txt = re.sub(r"\bरही\s+हूँ\b", "रहा हूँ", txt)
                txt = re.sub(r"\bकरूँगी\b|\bकरूंगी\b", "करूँगा", txt)
                txt = re.sub(r"\bजाऊँगी\b|\bजाऊंगी\b", "जाऊँगा", txt)
                txt = re.sub(r"\bछोड़ूँगी\b|\bछोडूंगी\b", "छोड़ूँगा", txt)
                sc.narration_text = txt
                sc.subtitle_text = txt
            elif gender == "female" and "मैं" in txt:
                txt = re.sub(r"\bरहा\s+हूँ\b", "रही हूँ", txt)
                txt = re.sub(r"\bकरूँगा\b|\bकरूंगा\b", "करूँगी", txt)
                txt = re.sub(r"\bजाऊँगा\b|\bजाऊंगा\b", "जाऊँगी", txt)
                txt = re.sub(r"\bछोड़ूँगा\b|\bछोडूंगा\b", "छोड़ूँगी", txt)
                sc.narration_text = txt
                sc.subtitle_text = txt

    def _enhance_female_vocal(self, raw_audio: Path, target_audio: Path) -> None:
        """Transparent organic human female vocal mastering."""
        self._enhance_vocal_audio(raw_audio, target_audio)

    def _enhance_dragon_vocal(self, raw_audio: Path, target_audio: Path) -> None:
        """Mastering EQ with mythical resonance and depth for Ancient Dragon voices."""
        filter_str = (
            "highpass=f=65,"
            "equalizer=f=110:t=q:w=1.2:g=2.5,"
            "aecho=0.8:0.7:35:0.15,"
            "apad=pad_dur=0.22,"
            "loudnorm=I=-16:TP=-1.5:LRA=12"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", str(raw_audio),
            "-af", filter_str,
            "-c:a", "libmp3lame",
            "-b:a", "192k",
            str(target_audio),
        ]
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
        except Exception as exc:
            logger.warning(f"Dragon vocal enhancement failed ({exc}), falling back to raw audio.")
            shutil.copy(str(raw_audio), str(target_audio))

    def _enhance_system_ai_vocal(self, raw_audio: Path, target_audio: Path) -> None:
        """Transparent, natural human vocal mastering for System / Nano AI."""
        self._enhance_vocal_audio(raw_audio, target_audio)

    def _apply_adaptive_vocal_enhancement(
        self,
        raw_audio: Path,
        target_audio: Path,
        voice_setting: VoiceSetting,
        scene: Optional[SceneItem] = None,
    ) -> None:
        """Apply transparent organic vocal mastering (or dragon resonance if dragon speaker)."""
        desc = (voice_setting.description or "").lower()
        speaker = (getattr(scene, "speaker", "") or "").lower() if scene else ""

        if "dragon" in desc or "dragon" in speaker:
            self._enhance_dragon_vocal(raw_audio, target_audio)
        else:
            self._enhance_vocal_audio(raw_audio, target_audio)

    async def _synthesize_scene_async(
        self,
        scene: SceneItem,
        output_file: Path,
        voice_setting: VoiceSetting,
    ) -> float:
        """Synthesize natural human speech for a single scene using Gemini Native Audio (Puck, Charon, Fenrir, Kore, Aoede)."""
        raw_text = (scene.narration_text or scene.subtitle_text or "").strip()
        text = self.humanize_text_for_natural_speech(raw_text)

        provider = getattr(voice_setting, "provider", "gemini").lower()
        vid_raw = (voice_setting.voice_id or "gemini:Puck").strip()
        vid_lower = vid_raw.lower()
        spk_lower = (getattr(scene, "speaker", "") or "").lower()

        from manhwa_studio.story.character_registry import GEMINI_TTS_VOICES

        is_explicit_gemini = (
            provider == "gemini"
            or vid_lower.startswith("gemini:")
            or vid_raw in GEMINI_TTS_VOICES
        )
        is_preview_edge = (getattr(scene, "scene_id", "") == "preview") and not is_explicit_gemini

        if not is_preview_edge:
            gemini_voice = vid_raw.replace("gemini:", "").strip()
            if gemini_voice not in GEMINI_TTS_VOICES:
                gemini_voice = "Puck"
            rate_str = getattr(voice_setting, "rate", "+2%") or "+2%"

            tts_pref = os.environ.get("TTS_PROVIDER", "auto").strip().lower()
            use_f5_local = (tts_pref in ("f5_hindi", "f5", "indicf5")) or (
                tts_pref == "auto" and self._is_f5_hindi_available()
            )
            if use_f5_local:
                sc_gender = getattr(scene, "speaker_gender", None) or self.detect_scene_gender(scene)
                await asyncio.to_thread(
                    self._synthesize_with_f5_hindi,
                    text,
                    output_file,
                    gemini_voice,
                    sc_gender,
                    rate_str,
                )
            else:
                await asyncio.to_thread(
                    self._synthesize_with_gemini,
                    text,
                    output_file,
                    gemini_voice,
                    rate_str,
                )
            if output_file.exists() and output_file.stat().st_size > 500:
                return self._get_audio_duration(output_file)
            raise RuntimeError(
                f"TTS failed to synthesize audio for scene '{scene.scene_id}'. "
                f"Default voice fallback is disabled so voice remains 100% consistent."
            )

        # Studio-Remastered Free Indian Neural Path (ONLY used when explicitly previewing an Edge-TTS voice)
        detected_gender = self.detect_scene_gender(scene)
        is_female_role = (
            detected_gender == "female"
            or vid_lower in (
                "gemini:kore", "kore", "gemini:aoede", "aoede", "gemini:zephyr", "zephyr",
                "mr-in-aarohineural", "en-in-neerjaneural", "hi-in-swaraneural",
            )
        )

        if is_preview_edge and "neural" in vid_lower:
            resolved_vid = vid_raw
            effective_rate = voice_setting.rate or "+4%"
            safe_pitch = voice_setting.pitch or "+0Hz"
        elif is_female_role:
            resolved_vid = "hi-IN-SwaraNeural"
            effective_rate = "+3%"
            safe_pitch = "-2Hz"
        else:
            resolved_vid = "hi-IN-MadhurNeural"
            effective_rate = "+9%"
            safe_pitch = "+2Hz"

        if resolved_vid.lower().startswith("en-in-"):
            text = self.devanagari_to_roman_hinglish(text)

        temp_raw = output_file.with_suffix(".raw.mp3")
        last_tts_err: Optional[Exception] = None
        for attempt in range(1, 4):
            try:
                communicate = edge_tts.Communicate(
                    text=text,
                    voice=resolved_vid,
                    rate=effective_rate,
                    pitch=safe_pitch,
                    volume=voice_setting.volume or "+0%",
                )
                await communicate.save(str(temp_raw))
                if temp_raw.exists() and temp_raw.stat().st_size > 0:
                    break
            except Exception as err:
                last_tts_err = err
                await asyncio.sleep(1.0 * attempt)

        if temp_raw.exists() and temp_raw.stat().st_size > 0:
            if is_female_role:
                # Velvet de-essed female mastering chain (cuts 4.2kHz harshness, adds 220Hz warm body)
                fem_filter = (
                    "highpass=f=85,"
                    "equalizer=f=220:t=q:w=1.2:g=1.5,"
                    "equalizer=f=4200:t=q:w=1.8:g=-3.0,"
                    "afade=t=in:st=0:d=0.02,"
                    "apad=pad_dur=0.14,"
                    "loudnorm=I=-16:TP=-1.5:LRA=11"
                )
                subprocess.run(
                    ["ffmpeg", "-y", "-i", str(temp_raw), "-af", fem_filter, "-c:a", "libmp3lame", "-b:a", "192k", str(output_file)],
                    capture_output=True, check=False,
                )
            else:
                # Crisp youthful male mastering chain (cuts 260Hz boxiness, boosts 3.4kHz presence)
                male_filter = (
                    "highpass=f=80,"
                    "equalizer=f=260:t=q:w=1.5:g=-2.5,"
                    "equalizer=f=3400:t=q:w=1.2:g=2.2,"
                    "afade=t=in:st=0:d=0.02,"
                    "apad=pad_dur=0.14,"
                    "loudnorm=I=-16:TP=-1.5:LRA=11"
                )
                subprocess.run(
                    ["ffmpeg", "-y", "-i", str(temp_raw), "-af", male_filter, "-c:a", "libmp3lame", "-b:a", "192k", str(output_file)],
                    capture_output=True, check=False,
                )
            if not output_file.exists() or output_file.stat().st_size == 0:
                self._apply_adaptive_vocal_enhancement(temp_raw, output_file, voice_setting, scene)
            if temp_raw.exists():
                try:
                    temp_raw.unlink()
                except Exception:
                    pass
            return self._get_audio_duration(output_file)
        else:
            raise RuntimeError(f"TTS generated empty audio for scene {scene.scene_id} ({last_tts_err})")

    def synthesize_speech(
        self,
        text: str,
        output_path: Path,
        speaker_role: str = "Narrator",
        pitch: Optional[str] = None,
        rate: Optional[str] = None,
    ) -> float:
        """Synchronously synthesize text to Indian human speech."""
        setting = self.resolve_voice_for_speaker(speaker_role)
        v_pitch = self._sanitize_human_pitch(setting.voice_id, pitch or setting.pitch)
        v_rate = rate or setting.rate
        clean_text = self.humanize_text_for_natural_speech(text)
        vid = setting.voice_id if "Neural" in setting.voice_id else "hi-IN-MadhurNeural"
        if vid.lower().startswith("en-in-"):
            clean_text = self.devanagari_to_roman_hinglish(clean_text)

        async def _run():
            com = edge_tts.Communicate(
                text=clean_text,
                voice=vid,
                rate=v_rate,
                pitch=v_pitch,
                volume=setting.volume,
            )
            temp_raw = output_path.with_suffix(".raw.mp3")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            await com.save(str(temp_raw))
            if temp_raw.exists() and temp_raw.stat().st_size > 0:
                self._enhance_vocal_audio(temp_raw, output_path)
                if temp_raw.exists():
                    try:
                        temp_raw.unlink()
                    except Exception:
                        pass
            else:
                raise RuntimeError(f"EdgeTTS failed to generate audio for text: {clean_text[:30]}")

        asyncio.run(_run())
        return self._get_audio_duration(output_path)

    def _get_audio_duration(self, audio_path: Path) -> float:
        """Get exact audio duration using ffprobe."""
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return float(res.stdout.strip())
        except Exception:
            # Fallback estimation based on file size
            return 3.5

    def resolve_multi_character_voice(
        self,
        scene: SceneItem,
        registry: Optional[Any] = None,
    ) -> VoiceSetting:
        """
        Resolve the optimal Gemini TTS VoiceSetting for `scene` using:
        1. Narrator -> series narrator_voice
        2. Confirmed per-manhwa CharacterRegistry (gender + age + look -> Aoede/Leda/Kore/Puck/Charon/Fenrir)
        3. SeriesProfile situational/character_voices (preserving emotional rate adjustments)
        4. Gender-safe fallback so female/girl characters never receive a male voice.
        """
        from manhwa_studio.story.character_registry import (
            GEMINI_TTS_VOICES,
            NARRATOR_ALIASES,
            select_gemini_voice,
            strip_speaker_modifiers,
        )

        raw_spk = (getattr(scene, "speaker", "") or "Narrator").strip()
        base_spk = strip_speaker_modifiers(raw_spk)
        if base_spk.lower() in NARRATOR_ALIASES or (getattr(scene, "speaker_gender", None) or "").lower() == "narrator":
            return self.profile.narrator_voice

        profile_setting = self.resolve_voice_for_speaker(
            speaker=raw_spk,
            text=getattr(scene, "narration_text", None),
            scene_purpose=getattr(scene, "scene_purpose", None),
        )
        reg_prof = registry.find_by_name(base_spk) if registry else None

        if reg_prof and reg_prof.confirmed:
            # Keep situational rate if profile_setting has a custom rate, otherwise use registry rate
            eff_rate = profile_setting.rate if profile_setting.rate not in ("", "+2%") else reg_prof.voice_rate
            return VoiceSetting(
                provider="gemini",
                voice_id=reg_prof.gemini_voice_id,
                rate=eff_rate,
                pitch=reg_prof.voice_pitch,
                description=f"{reg_prof.canonical_name} ({reg_prof.gender}, {reg_prof.age_group}, {reg_prof.look_archetype})",
            )

        gender = self.detect_scene_gender(scene)
        vid = (profile_setting.voice_id or "gemini:Puck").replace("gemini:", "").strip()
        # Prevent legacy single-Puck series profiles from giving male Puck voice to female/girl speakers
        if gender == "female" and vid in ("Puck", "Charon", "Fenrir", "Orus"):
            spk_l = raw_spk.lower()
            age_hint = "teen" if any(k in spk_l for k in ("girl", "young", "little", "sister", "cute", "ladki")) else "young_adult"
            look_hint = "regal_woman" if any(k in spk_l for k in ("queen", "empress", "dragon", "lady", "mother", "countess")) else "cute_girl"
            f_vid, f_rate, f_pitch = select_gemini_voice("female", age_group=age_hint, look_archetype=look_hint)
            return VoiceSetting(
                provider="gemini",
                voice_id=f_vid,
                rate=profile_setting.rate if profile_setting.rate not in ("", "+2%") else f_rate,
                pitch=f_pitch,
                description=f"Female ({age_hint}/{look_hint}) -> {f_vid}",
            )

        if vid not in GEMINI_TTS_VOICES:
            m_vid, m_rate, m_pitch = select_gemini_voice(gender)
            return VoiceSetting(provider="gemini", voice_id=m_vid, rate=m_rate, pitch=m_pitch)

        return profile_setting

    def synthesize_all_scenes(
        self,
        manifest: SceneManifest,
        output_dir: Path,
        min_scene_duration: Optional[float] = None,
        buffer_seconds: Optional[float] = None,
        force_rebuild: bool = False,
    ) -> Dict[str, Tuple[Path, float, str]]:
        """
        Synthesize speech for all scenes in manifest using multi-character Gemini TTS voices
        matched to each character's confirmed gender, age, and look.
        Updates each scene with actual_audio_path and actual_audio_duration.
        Returns mapping: scene_id -> (audio_path, duration, speaker_voice_description).
        """
        from manhwa_studio.story.character_registry import CharacterRegistry

        if min_scene_duration is None:
            min_scene_duration = self.env_cfg.min_scene_sec
        if buffer_seconds is None:
            buffer_seconds = self.env_cfg.scene_buffer_sec
        output_dir.mkdir(parents=True, exist_ok=True)
        results: Dict[str, Tuple[Path, float, str]] = {}

        # Reset quota flag at the start of a chapter batch run so multi-key rotation can run fresh
        VoiceDirector._GEMINI_DAILY_QUOTA_EXHAUSTED = False

        # Determine active TTS engine:
        # 'auto' -> use local F5-Hindi-24KHz on CUDA GPU (unlimited, fast); fall back to Gemini TTS on CPU-only servers
        tts_pref = os.environ.get("TTS_PROVIDER", "auto").strip().lower()
        use_f5_hindi = (tts_pref in ("f5_hindi", "f5", "indicf5")) or (
            tts_pref == "auto" and self._is_f5_hindi_available()
        )
        engine_tag = "v14_f5_hindi_local" if use_f5_hindi else "v13_multi_character_gemini"
        engine_marker = output_dir / f".voice_engine_{engine_tag}"
        if force_rebuild or not engine_marker.exists():
            seg_dir = output_dir.parent / "renders" / "segments"
            logger.info(f"Purging legacy cached scene audio & visual segments for {engine_tag}...")
            for old_mp3 in output_dir.glob("*.mp3"):
                try:
                    old_mp3.unlink()
                except Exception:
                    pass
            if seg_dir.exists():
                for old_seg in seg_dir.glob("*.mp4"):
                    try:
                        old_seg.unlink()
                    except Exception:
                        pass
            for old_marker in output_dir.glob(".voice_engine_*"):
                try:
                    old_marker.unlink()
                except Exception:
                    pass
            try:
                engine_marker.write_text(engine_tag, encoding="utf-8")
            except Exception:
                pass

        engine_label = "Local F5-Hindi-24KHz (GPU)" if use_f5_hindi else "Multi-Character Gemini TTS"
        logger.info(f"Beginning {engine_label} dubbing for {len(manifest.scenes)} scenes (Series: '{self.profile.series_name}')...")

        # 0. Crop & confirm character faces/names/genders/ages once per manhwa (cache-first)
        artwork_dir = output_dir.parent / "artwork"
        registry = CharacterRegistry(self.profile.series_name)
        self.verify_chapter_genders_from_panels(manifest, artwork_dir=artwork_dir, registry=registry)

        # 1. Pre-clean dialogue text and assign gender/age/look-matched Gemini voice per scene
        scene_configs: List[Tuple[SceneItem, Path, VoiceSetting, str]] = []
        pending_items: List[Tuple[SceneItem, Path, VoiceSetting, str]] = []

        for scene in manifest.scenes:
            cleaned_line = self.humanize_text_for_natural_speech(scene.narration_text or scene.subtitle_text or "")
            scene.narration_text = cleaned_line
            scene.subtitle_text = cleaned_line
            out_file = output_dir / f"{scene.scene_id}.mp3"

            voice_cfg = self.resolve_multi_character_voice(scene, registry=registry)
            gemini_voice = (voice_cfg.voice_id or "gemini:Puck").replace("gemini:", "").strip()

            item_tuple = (scene, out_file, voice_cfg, gemini_voice)
            scene_configs.append(item_tuple)
            if not (out_file.exists() and out_file.stat().st_size > 500):
                pending_items.append(item_tuple)

        # 2. Synthesize pending scenes via Local F5-Hindi-24KHz (if GPU/enabled) OR batched Gemini TTS
        if pending_items and use_f5_hindi:
            logger.info(f"Synthesizing {len(pending_items)} pending scenes locally with SPRINGLab/F5-Hindi-24KHz...")
            for p_idx, (sc, out_file, voice_cfg, voice_name) in enumerate(pending_items, start=1):
                sc_gender = getattr(sc, "speaker_gender", None) or self.detect_scene_gender(sc)
                reg_prof = registry.find_by_name(sc.speaker or "")
                sc_age = reg_prof.age_group if reg_prof else "young_adult"
                self._synthesize_with_f5_hindi(
                    text=sc.narration_text or sc.subtitle_text or "",
                    output_file=out_file,
                    voice_name=voice_name,
                    gender=sc_gender,
                    rate=voice_cfg.rate or "+2%",
                    age_group=sc_age,
                )
                if p_idx % 10 == 0 or p_idx == len(pending_items):
                    logger.info(f"F5-Hindi progress: [{p_idx}/{len(pending_items)}] scenes -> {sc.speaker} ({voice_name})")
        elif pending_items:
            max_batch_size = 36
            from collections import defaultdict
            grouped_by_voice: Dict[Tuple[str, str], List[Tuple[SceneItem, Path, VoiceSetting, str]]] = defaultdict(list)
            for item in pending_items:
                grouped_by_voice[(item[3], item[2].rate or "+2%")].append(item)

            voice_batches: List[List[Tuple[SceneItem, Path, VoiceSetting, str]]] = []
            for items in grouped_by_voice.values():
                for i in range(0, len(items), max_batch_size):
                    voice_batches.append(items[i : i + max_batch_size])

            total_batches = len(voice_batches)
            for b_idx, batch_slice in enumerate(voice_batches):
                first_id = batch_slice[0][0].scene_id
                last_id = batch_slice[-1][0].scene_id
                b_voice = batch_slice[0][3]
                logger.info(
                    f"Synthesizing Gemini TTS Batch [{b_idx + 1}/{total_batches}] for voice 'gemini:{b_voice}' "
                    f"({len(batch_slice)} scenes: {first_id}..{last_id})..."
                )
                ok = self._synthesize_batch_with_gemini(batch_slice)
                if not ok:
                    # If not daily quota exhaustion (e.g., transient large-batch timeout), retry in 12-scene Gemini sub-batches
                    if not VoiceDirector._GEMINI_DAILY_QUOTA_EXHAUSTED and len(batch_slice) > 12:
                        sub_size = 12
                        sub_ok_all = True
                        for s_idx in range(0, len(batch_slice), sub_size):
                            sub_slice = batch_slice[s_idx : s_idx + sub_size]
                            logger.info(
                                f"Retrying smaller Gemini TTS Sub-Batch ({len(sub_slice)} scenes: "
                                f"{sub_slice[0][0].scene_id}..{sub_slice[-1][0].scene_id})..."
                            )
                            if not self._synthesize_batch_with_gemini(sub_slice):
                                sub_ok_all = False
                                break
                        ok = sub_ok_all

                if not ok:
                    voiced_count = sum(
                        1 for _, f_path, _, _ in scene_configs if f_path.exists() and f_path.stat().st_size > 500
                    )
                    raise RuntimeError(
                        f"STOPPED: Gemini TTS quota reached or failed on batch {first_id}..{last_id} "
                        f"({voiced_count}/{len(scene_configs)} scenes already saved in '{output_dir}'). "
                        f"Default voice fallback is disabled. Add another Gemini API key to GEMINI_API_KEY in .env "
                        f"(comma-separated) or re-run when quota resets to resume from {first_id}."
                    )

        # 3. Verify all scene audio files & compute exact durations (strictly no default voice or Gemini fallback in F5 mode)
        for idx, (scene, out_file, voice_cfg, gemini_voice) in enumerate(scene_configs):
            if out_file.exists() and out_file.stat().st_size > 500:
                dur = self._get_audio_duration(out_file)
            elif use_f5_hindi:
                sc_gender = getattr(scene, "speaker_gender", None) or self.detect_scene_gender(scene)
                reg_prof = registry.find_by_name(scene.speaker or "")
                sc_age = reg_prof.age_group if reg_prof else "young_adult"
                self._synthesize_with_f5_hindi(
                    text=scene.narration_text or scene.subtitle_text or "",
                    output_file=out_file,
                    voice_name=gemini_voice,
                    gender=sc_gender,
                    rate=voice_cfg.rate or "+2%",
                    age_group=sc_age,
                )
                dur = self._get_audio_duration(out_file)
            else:
                dur = asyncio.run(self._synthesize_scene_async(scene, out_file, voice_cfg))

            # Update scene duration to fit voice seamlessly with a comfortable breathing buffer
            scene.actual_audio_path = str(out_file)
            scene.actual_audio_duration = dur
            scene.duration = max(dur + buffer_seconds, min_scene_duration)

            results[scene.scene_id] = (out_file, dur, f"{scene.speaker} [gemini:{gemini_voice}]")

            if (idx + 1) % 15 == 0 or idx == len(manifest.scenes) - 1:
                logger.info(f"Voiced [{idx + 1}/{len(manifest.scenes)}] scenes -> {scene.speaker} ({gemini_voice}): {dur:.2f}s")

        logger.info(f"Successfully completed {engine_label} multi-character dubbing for all {len(manifest.scenes)} scenes.")
        return results
