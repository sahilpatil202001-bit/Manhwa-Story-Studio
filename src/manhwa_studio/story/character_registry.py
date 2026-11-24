"""
Per-Manhwa Character Face & Identity Registry.
Crops character faces from panels, confirms character name, gender, age, and look
once via Gemini Vision (using manhwa name + cropped face), and caches the confirmed
profile + face image per manhwa so Gemini is never called repeatedly for known characters.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image
from pydantic import BaseModel, Field

from manhwa_studio.logging_config import get_logger

logger = get_logger("manhwa_studio.story.character_registry")

# Valid Gemini 2.5 Flash TTS voices supported for multi-character dubbing
GEMINI_TTS_VOICES = {
    "Puck", "Charon", "Kore", "Fenrir", "Aoede", "Zephyr",
    "Leda", "Orus", "Algenib", "Callirrhoe", "Autonoe",
    "Enceladus", "Iapetus", "Umbriel", "Algieba", "Despina",
    "Erinome", "Rasalgethi", "Laomedeia", "Achernar", "Alnilam",
    "Schedar", "Gacrux", "Pulcherrima", "Achird", "Zubenelgenubi",
    "Vindemiatrix", "Sadachbia", "Sadaltager", "Sulafat",
}

NARRATOR_ALIASES = {"", "narrator", "सूत्रधार", "कथावाचक", "storyteller"}

_MALE_NAME_HINTS = {
    "boy", "boyfriend", "man", "guy", "ladka", "hero", "protagonist", "king", "prince",
    "lord", "duke", "count", "elder", "master", "brother", "father", "dad", "grandpa",
    "guard", "knight", "soldier", "villain", "assassin", "boss",
}
_FEMALE_NAME_HINTS = {
    "girl", "girlfriend", "woman", "lady", "ladki", "aurat", "queen", "princess",
    "empress", "duchess", "countess", "sister", "mother", "mom", "maiden", "maid",
    "heroine", "female",
}


def infer_gender_hint(name: str) -> Optional[str]:
    """Return 'male' or 'female' if `name` has an explicit gender keyword, else None."""
    tokens = set(re.findall(r"[a-z]+", (name or "").lower()))
    has_m = bool(tokens & _MALE_NAME_HINTS)
    has_f = bool(tokens & _FEMALE_NAME_HINTS)
    if has_f and not has_m:
        return "female"
    if has_m and not has_f:
        return "male"
    return None


def slugify_name(name: str) -> str:
    """Normalize a series or character name into a safe filesystem slug."""
    s = re.sub(r"[^a-z0-9]+", "_", (name or "unknown").strip().lower()).strip("_")
    return s or "unknown"


def strip_speaker_modifiers(speaker: str) -> str:
    """Strip situational tags like '(Shocked)', '[Angry]', or '- Wounded' from speaker."""
    cleaned = re.sub(r"\s*[\(\[\-].*$", "", (speaker or "").strip()).strip()
    return cleaned or "Narrator"


def select_gemini_voice(
    gender: str,
    age_group: str = "young_adult",
    look_archetype: str = "supporting_male",
) -> Tuple[str, str, str]:
    """
    Map (gender, age_group, look_archetype) to an expressive Gemini TTS voice, rate, and pitch.
    - Female / Girl -> female Gemini voices (Leda, Aoede, Kore, Zephyr)
    - Male / Boy / Elder / Villain -> male Gemini voices (Puck, Charon, Fenrir, Orus)
    """
    g = (gender or "male").strip().lower()
    age = (age_group or "young_adult").strip().lower()
    look = (look_archetype or "").strip().lower()

    is_system_ai = look in ("system_ai", "system", "ai") or "system_ai" in look

    if g == "female":
        if is_system_ai:
            return "gemini:Zephyr", "+2%", "+0Hz"
        if age in ("child", "teen") or any(k in look for k in ("cute", "young", "girl", "spirit")):
            return "gemini:Leda", "+4%", "+0Hz"
        if age in ("adult", "elder") or any(k in look for k in ("regal", "queen", "mature", "elder", "villain")):
            return "gemini:Kore", "+0%", "+0Hz"
        return "gemini:Aoede", "+2%", "+0Hz"

    # Male voices
    if is_system_ai:
        return "gemini:Orus", "+2%", "+0Hz"
    if age in ("adult", "elder") or any(k in look for k in ("elder", "master", "villain", "dark", "boss")):
        return "gemini:Fenrir", "-2%", "+0Hz"
    if any(k in look for k in ("stoic", "knight", "rival", "cool", "guard")):
        return "gemini:Charon", "+0%", "+0Hz"
    if age in ("child", "teen") or any(k in look for k in ("boy", "young", "hero")):
        return "gemini:Puck", "+2%", "+0Hz"
    return "gemini:Puck", "+2%", "+0Hz"


def compute_face_dhash(image_path: Path) -> Optional[str]:
    """Compute a 64-bit difference hash (dHash) hex string for a cropped face image."""
    try:
        with Image.open(image_path) as img:
            gray = img.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
            pixels = np.asarray(gray, dtype=np.int16)
            diff = pixels[:, 1:] > pixels[:, :-1]
            bits = 0
            for val in diff.flatten():
                bits = (bits << 1) | int(bool(val))
            return f"{bits:016x}"
    except Exception:
        return None


def dhash_distance(hash_a: Optional[str], hash_b: Optional[str]) -> int:
    """Hamming distance between two 64-bit hex dHashes (lower = more similar)."""
    if not hash_a or not hash_b:
        return 64
    try:
        xor_val = int(hash_a, 16) ^ int(hash_b, 16)
        return xor_val.bit_count()
    except Exception:
        return 64


# Distinct F5-Hindi / Multi-Voice casting pools (mapped to real local reference WAVs)
MALE_VOICE_POOL: List[Tuple[str, str, str]] = [
    ("gemini:Puck", "+2%", "+0Hz"),      # Young expressive male (demo_gemini_puck.wav)
    ("gemini:Charon", "+0%", "+0Hz"),    # Calm, cool, stoic male (demo_gemini_charon.wav)
    ("gemini:Fenrir", "-2%", "+0Hz"),    # Deep, commanding elder/boss (demo_gemini_fenrir.wav)
    ("gemini:Algenib", "-1%", "+0Hz"),   # Gritty, sharp rival/antagonist (demo_gemini_algenib.wav)
    ("gemini:Puck", "+5%", "+0Hz"),      # Energetic/brisk young male #2
    ("gemini:Charon", "-3%", "+0Hz"),    # Measured senior male #2
    ("gemini:Algenib", "+3%", "+0Hz"),   # Hot-headed/intense male #3
    ("gemini:Fenrir", "-5%", "+0Hz"),    # Heavy ancient/sovereign male #2
]

FEMALE_VOICE_POOL: List[Tuple[str, str, str]] = [
    ("gemini:Kore", "+0%", "+0Hz"),      # Mature / regal female (demo_gemini_kore.wav)
    ("gemini:Leda", "+3%", "+0Hz"),      # Bright youthful girl (ref_female_young.wav)
    ("gemini:Aoede", "+2%", "+0Hz"),     # Expressive female lead (demo_gemini_kore.wav)
    ("gemini:Zephyr", "+2%", "+0Hz"),    # Crisp System / AI (ref_female_young.wav)
    ("gemini:Leda", "+0%", "+0Hz"),      # Calm gentle girl #2
    ("gemini:Kore", "-2%", "+0Hz"),      # Dignified elder/queen #2
]


def select_distinct_voice(
    gender: str,
    age_group: str = "young_adult",
    look_archetype: str = "supporting_male",
    used_slots: Optional[set[Tuple[str, str]]] = None,
) -> Tuple[str, str, str]:
    """
    Pick a role-appropriate voice that avoids colliding with already-assigned
    characters in the same series whenever an unused voice slot is available.
    """
    preferred = select_gemini_voice(gender, age_group, look_archetype)
    if not used_slots:
        return preferred

    pref_key = (preferred[0], preferred[1])
    if pref_key not in used_slots:
        return preferred

    pool = FEMALE_VOICE_POOL if (gender or "male").strip().lower() == "female" else MALE_VOICE_POOL
    # Prefer unused distinct base voice_id first (different reference WAV!), then unused (voice_id, rate)
    used_base_ids = {vid for vid, _ in used_slots}
    for vid, rate, pitch in pool:
        if vid not in used_base_ids:
            return vid, rate, pitch
    for vid, rate, pitch in pool:
        if (vid, rate) not in used_slots:
            return vid, rate, pitch
    return preferred


def infer_local_character_traits(
    speaker_name: str,
    dialogue_text: str = "",
) -> Tuple[str, str, str]:
    """
    Zero-API local heuristic to infer (gender, age_group, look_archetype)
    for new characters when running 100% offline / Cloud GPU without Gemini API.
    """
    spk = (speaker_name or "").strip().lower()
    txt = (dialogue_text or "").strip()

    gender = infer_gender_hint(spk)
    if not gender:
        if any(k in spk for k in ("nano", "system", "lady", "miss", "madam", "iseol", "soso", "mun ku", "alicia", "her", "she")):
            gender = "female"
        elif re.search(r"\b(रही\s+हूँ|रही\s+थी|करूँगी|करूंगी|जाऊँगी|जाऊंगी|कहती\s+हूँ|सकती\s+हूँ)\b", txt):
            gender = "female"
        else:
            gender = "male"

    if any(k in spk for k in ("nano", "system", "ai")):
        return gender, "young_adult", "system_ai"
    if any(k in spk for k in ("elder", "master", "grandpa", "grandfather", "patriarch", "sect leader", "old", "lord", "chief")):
        return gender, "elder", "wise_elder" if gender == "male" else "regal_woman"
    if any(k in spk for k in ("villain", "assassin", "demon", "enemy", "bandit", "killer", "boss", "traitor")):
        return gender, "adult", "villain_dark" if gender == "male" else "regal_woman"
    if any(k in spk for k in ("guard", "knight", "captain", "commander", "instructor", "rival", "swordsman", "warrior")):
        return gender, "adult", "stoic_knight" if gender == "male" else "regal_woman"
    if any(k in spk for k in ("kid", "child", "little", "boy", "girl", "teen", "junior", "cadet", "disciple")):
        return gender, "teen", "young_hero" if gender == "male" else "cute_girl"
    if any(k in spk for k in ("queen", "empress", "duchess", "countess", "mother", "lady")):
        return "female", "adult", "regal_woman"

    return gender, "young_adult", "supporting_female" if gender == "female" else "supporting_male"


class CharacterProfile(BaseModel):
    """Persistent confirmed profile for a single manhwa character."""
    char_id: str
    canonical_name: str
    aliases: List[str] = Field(default_factory=list)
    gender: str = "male"  # "male" | "female"
    age_group: str = "young_adult"  # "child" | "teen" | "young_adult" | "adult" | "elder"
    estimated_age: str = ""  # e.g. "16", "24", "60+"
    role: str = "supporting"  # "main_protagonist" | "female_lead" | "antagonist" | "elder" | "supporting"
    look_archetype: str = "supporting_male"
    visual_description: str = ""
    face_image_path: Optional[str] = None  # Relative to series registry dir
    face_dhash: Optional[str] = None
    gemini_voice_id: str = "gemini:Puck"
    voice_rate: str = "+2%"
    voice_pitch: str = "+0Hz"
    voice_locked: bool = True
    confirmed: bool = True
    source: str = "gemini_vision"


class SeriesCharacterRegistryData(BaseModel):
    """Serialized JSON structure for a single manhwa's character registry."""
    series_name: str
    series_slug: str
    characters: Dict[str, CharacterProfile] = Field(default_factory=dict)


class CharacterRegistry:
    """
    Manages per-manhwa cropped character faces and confirmed character identities.
    Always checks local cache (by name/alias and face dHash) before calling Gemini Vision.
    """

    def __init__(self, series_name: str, registry_root: Optional[Path] = None):
        self.series_name = series_name
        self.series_slug = slugify_name(series_name)
        root = registry_root or (Path("configs") / "character_registry")
        self.series_dir = root / self.series_slug
        self.faces_dir = self.series_dir / "faces"
        self.registry_file = self.series_dir / "registry.json"
        self.data = self._load()

    def _load(self) -> SeriesCharacterRegistryData:
        if self.registry_file.exists():
            try:
                raw = json.loads(self.registry_file.read_text(encoding="utf-8"))
                return SeriesCharacterRegistryData(**raw)
            except Exception as exc:
                logger.warning(f"Failed to load character registry {self.registry_file}: {exc}")
        return SeriesCharacterRegistryData(
            series_name=self.series_name,
            series_slug=self.series_slug,
        )

    def save(self) -> None:
        """Persist the per-manhwa character registry to disk."""
        self.series_dir.mkdir(parents=True, exist_ok=True)
        self.faces_dir.mkdir(parents=True, exist_ok=True)
        self.registry_file.write_text(
            self.data.model_dump_json(indent=2),
            encoding="utf-8",
        )

    def find_by_name(self, speaker_name: str) -> Optional[CharacterProfile]:
        """Look up a confirmed character by canonical name or alias (case-insensitive)."""
        base = strip_speaker_modifiers(speaker_name).lower()
        if base in NARRATOR_ALIASES:
            return None

        slug = slugify_name(base)
        if slug in self.data.characters:
            return self.data.characters[slug]

        for prof in self.data.characters.values():
            if prof.canonical_name.strip().lower() == base:
                return prof
            if any(a.strip().lower() == base for a in prof.aliases):
                return prof
        return None

    def find_by_face_hash(self, face_dhash: Optional[str], max_distance: int = 10) -> Optional[CharacterProfile]:
        """Find a stored character whose cropped face visually matches `face_dhash`."""
        if not face_dhash:
            return None
        best_prof: Optional[CharacterProfile] = None
        best_dist = max_distance + 1
        for prof in self.data.characters.values():
            if not prof.face_dhash:
                continue
            dist = dhash_distance(face_dhash, prof.face_dhash)
            if dist < best_dist:
                best_dist = dist
                best_prof = prof
        return best_prof

    @staticmethod
    def detect_face_boxes(image_path: Path) -> List[Tuple[int, int, int, int]]:
        """
        Detect character face bounding boxes (x, y, w, h) in a manhwa panel using OpenCV.
        Returns boxes sorted by area (largest face first) with generous portrait padding.
        """
        if not image_path.exists():
            return []
        try:
            img_arr = np.fromfile(str(image_path), dtype=np.uint8)
            bgr = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)
            if bgr is None:
                return []
            h_img, w_img = bgr.shape[:2]
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            gray = cv2.equalizeHist(gray)

            cascade_names = [
                "haarcascade_frontalface_default.xml",
                "haarcascade_frontalface_alt2.xml",
                "haarcascade_profileface.xml",
            ]
            raw_boxes: List[Tuple[int, int, int, int]] = []
            for cname in cascade_names:
                cpath = os.path.join(cv2.data.haarcascades, cname)
                if not os.path.exists(cpath):
                    continue
                clf = cv2.CascadeClassifier(cpath)
                detected = clf.detectMultiScale(
                    gray,
                    scaleFactor=1.1,
                    minNeighbors=4,
                    minSize=(40, 40),
                )
                if len(detected) > 0:
                    for (x, y, w, h) in detected:
                        raw_boxes.append((int(x), int(y), int(w), int(h)))
                    break  # Use the first cascade that finds faces cleanly

            if not raw_boxes:
                return []

            # Expand boxes by ~35% (extra top for hair) and clamp to panel dimensions
            padded: List[Tuple[int, int, int, int]] = []
            for (x, y, w, h) in raw_boxes:
                pad_x = int(w * 0.30)
                pad_top = int(h * 0.45)
                pad_bot = int(h * 0.25)
                x1 = max(0, x - pad_x)
                y1 = max(0, y - pad_top)
                x2 = min(w_img, x + w + pad_x)
                y2 = min(h_img, y + h + pad_bot)
                if (x2 - x1) >= 32 and (y2 - y1) >= 32:
                    padded.append((x1, y1, x2 - x1, y2 - y1))

            padded.sort(key=lambda b: b[2] * b[3], reverse=True)
            return padded
        except Exception as exc:
            logger.debug(f"OpenCV face detection skipped on {image_path.name}: {exc}")
            return []

    def crop_and_save_face(
        self,
        panel_path: Path,
        char_slug: str,
        box_xywh: Optional[Tuple[int, int, int, int]] = None,
        box_2d_norm: Optional[List[int]] = None,
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Crop a character face from `panel_path` and save it under `faces/<char_slug>.jpg`.
        Returns (relative_face_path, face_dhash).
        """
        if not panel_path.exists():
            return None, None
        try:
            self.faces_dir.mkdir(parents=True, exist_ok=True)
            out_path = self.faces_dir / f"{char_slug}.jpg"
            with Image.open(panel_path) as img:
                rgb = img.convert("RGB")
                w_img, h_img = rgb.size

                if box_2d_norm and len(box_2d_norm) == 4:
                    ymin, xmin, ymax, xmax = box_2d_norm
                    x1 = max(0, int((xmin / 1000.0) * w_img))
                    y1 = max(0, int((ymin / 1000.0) * h_img))
                    x2 = min(w_img, int((xmax / 1000.0) * w_img))
                    y2 = min(h_img, int((ymax / 1000.0) * h_img))
                    # Add 15% breathing margin
                    bw, bh = max(1, x2 - x1), max(1, y2 - y1)
                    x1 = max(0, x1 - int(bw * 0.15))
                    y1 = max(0, y1 - int(bh * 0.20))
                    x2 = min(w_img, x2 + int(bw * 0.15))
                    y2 = min(h_img, y2 + int(bh * 0.15))
                elif box_xywh:
                    x, y, w, h = box_xywh
                    x1, y1 = max(0, x), max(0, y)
                    x2, y2 = min(w_img, x + w), min(h_img, y + h)
                else:
                    return None, None

                if (x2 - x1) < 24 or (y2 - y1) < 24:
                    return None, None

                crop = rgb.crop((x1, y1, x2, y2))
                crop.thumbnail((256, 256), Image.Resampling.LANCZOS)
                crop.save(out_path, format="JPEG", quality=90)

            dhash = compute_face_dhash(out_path)
            rel_path = f"faces/{char_slug}.jpg"
            return rel_path, dhash
        except Exception as exc:
            logger.debug(f"Face crop failed for {char_slug}: {exc}")
            return None, None

    def register_character(
        self,
        canonical_name: str,
        gender: str = "male",
        age_group: str = "young_adult",
        look_archetype: str = "supporting_male",
        visual_description: str = "",
        aliases: Optional[List[str]] = None,
        face_rel_path: Optional[str] = None,
        face_dhash: Optional[str] = None,
        source: str = "gemini_vision",
        estimated_age: str = "",
        role: str = "supporting",
    ) -> CharacterProfile:
        """Create or update a confirmed CharacterProfile in the per-manhwa registry."""
        clean_name = canonical_name.strip()
        char_id = slugify_name(clean_name)
        eff_gender = gender if gender in ("male", "female") else "male"
        existing = self.data.characters.get(char_id)

        # Preserve a character's permanently locked voice if already cast (and gender-compatible)
        if existing and getattr(existing, "voice_locked", True) and existing.gemini_voice_id and existing.gender == eff_gender:
            voice_id = existing.gemini_voice_id
            rate = existing.voice_rate
            pitch = existing.voice_pitch
        else:
            used_slots = {
                (p.gemini_voice_id, p.voice_rate)
                for cid, p in self.data.characters.items()
                if cid != char_id and p.gender == eff_gender and p.gemini_voice_id
            }
            voice_id, rate, pitch = select_distinct_voice(
                eff_gender, age_group, look_archetype, used_slots=used_slots
            )

        merged_aliases = list(existing.aliases) if existing else []
        for a in (aliases or []):
            a_clean = a.strip()
            a_hint = infer_gender_hint(a_clean)
            if a_hint and a_hint != eff_gender:
                continue  # Never attach an opposite-gender alias (e.g. 'Boy' on a female character)
            if a_clean and a_clean.lower() != clean_name.lower() and a_clean not in merged_aliases:
                merged_aliases.append(a_clean)

        profile = CharacterProfile(
            char_id=char_id,
            canonical_name=clean_name,
            aliases=merged_aliases,
            gender=eff_gender,
            age_group=age_group,
            estimated_age=estimated_age or (existing.estimated_age if existing else ""),
            role=role or (existing.role if existing else "supporting"),
            look_archetype=look_archetype,
            visual_description=visual_description or (existing.visual_description if existing else ""),
            face_image_path=face_rel_path or (existing.face_image_path if existing else None),
            face_dhash=face_dhash or (existing.face_dhash if existing else None),
            gemini_voice_id=voice_id,
            voice_rate=rate,
            voice_pitch=pitch,
            confirmed=True,
            source=source,
        )
        self.data.characters[char_id] = profile
        self.save()
        return profile

    def _query_gemini_for_character(
        self,
        image_to_inspect: Path,
        candidate_speaker: str,
        dialogue_text: str,
        need_face_box: bool,
    ) -> Optional[Dict[str, Any]]:
        """Call Gemini Vision once to confirm character name, gender, age, look, and optional face box."""
        try:
            from manhwa_studio.story.llm_title_generator import (
                get_all_gemini_api_keys,
                get_base64_thumbnail,
                query_gemini_api,
            )

            keys = get_all_gemini_api_keys()
            if not keys:
                return None

            b64 = get_base64_thumbnail(image_to_inspect, max_size=512)
            if not b64:
                return None

            known_roster = [
                f"- {p.canonical_name} ({p.gender}, {p.age_group}, {p.look_archetype})"
                for p in list(self.data.characters.values())[:25]
            ]
            roster_text = (
                "Already confirmed characters in this manhwa:\n" + "\n".join(known_roster)
                if known_roster
                else "No characters confirmed yet for this manhwa."
            )
            box_instruction = (
                "Also return 'face_box_2d': [ymin, xmin, ymax, xmax] (integers 0-1000) around the speaking character's face."
                if need_face_box
                else "Set 'face_box_2d' to null."
            )

            prompt = (
                f"Manhwa / Series Name: '{self.series_name}'\n"
                f"Candidate Speaker Tag: '{candidate_speaker}'\n"
                f"Spoken Line: '{dialogue_text[:200]}'\n"
                f"{roster_text}\n\n"
                f"Task: Use web search (Google Search) and inspect the attached character face/panel from '{self.series_name}'.\n"
                f"1. Confirm the character's true canonical name in '{self.series_name}'. If multiple characters appear in the panel, focus ONLY on the speaker matching '{candidate_speaker}' and the spoken line. NEVER rename a male speaker like 'Boy' to 'Girl' or a female speaker like 'Girl' to 'Boy'.\n"
                f"2. Identify gender ('male' or 'female'). In Murim manhwa, male warriors often have long hair—check jawline, eyes, chest, and wiki/context.\n"
                f"3. Identify age_group ('child', 'teen', 'young_adult', 'adult', 'elder') and estimated_age (e.g. '16', '24', '55+').\n"
                f"4. Identify role ('main_protagonist', 'female_lead', 'antagonist', 'elder', or 'supporting').\n"
                f"5. Identify look_archetype (one of: 'young_hero', 'cute_girl', 'regal_woman', 'stoic_knight', 'villain_dark', 'wise_elder', 'system_ai', 'supporting_male', 'supporting_female').\n"
                f"6. Give a 5-10 word visual_description (hair color/style, outfit, vibe).\n"
                f"7. {box_instruction}\n"
                f"Return strictly a single JSON object with keys: canonical_name, gender, age_group, estimated_age, role, look_archetype, visual_description, face_box_2d."
            )

            # Try web-search grounded Gemini first so canon character name & age are verified accurately
            grounded_payload = {
                "contents": [{
                    "parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": "image/jpeg", "data": b64}},
                    ]
                }],
                "tools": [{"google_search": {}}],
                "generationConfig": {"temperature": 0.1},
            }
            res = query_gemini_api(grounded_payload, keys[0], timeout=30)
            if res:
                resp_data, _ = res
                raw_text = resp_data["candidates"][0]["content"]["parts"][0].get("text", "")
                m = re.search(r"\{[\s\S]*\}", raw_text)
                if m:
                    try:
                        return json.loads(m.group(0))
                    except Exception:
                        pass

            # Fallback to strict JSON mode without search tool if grounded response wasn't valid JSON
            payload = {
                "contents": [{
                    "parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": "image/jpeg", "data": b64}},
                    ]
                }],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "temperature": 0.1,
                },
            }

            res = query_gemini_api(payload, keys[0], timeout=25)
            if res:
                resp_data, _ = res
                raw_text = resp_data["candidates"][0]["content"]["parts"][0]["text"]
                return json.loads(raw_text)
        except Exception as exc:
            logger.debug(f"Gemini character confirmation failed for '{candidate_speaker}': {exc}")
        return None

    def resolve_or_confirm_character(
        self,
        speaker: str,
        panel_path: Optional[Path] = None,
        dialogue_text: str = "",
        allow_gemini: bool = True,
    ) -> Optional[CharacterProfile]:
        """
        Cache-first character resolution for a manhwa:
        1. Return immediately if `speaker` is already confirmed in `registry.json` (0 Gemini calls).
        2. Crop face locally with OpenCV; if `face_dhash` matches a stored character, return immediately (0 Gemini calls).
        3. Otherwise, call Gemini Vision ONCE with (manhwa name + face/panel), store face & profile, and reuse forever.
        """
        base_name = strip_speaker_modifiers(speaker)
        if base_name.lower() in NARRATOR_ALIASES:
            return None

        # 1. Name / Alias cache hit
        cached = self.find_by_name(base_name)
        if cached and cached.confirmed:
            # Opportunistically crop & attach face locally if missing
            if not cached.face_image_path and panel_path and panel_path.exists():
                boxes = self.detect_face_boxes(panel_path)
                if boxes:
                    rel, dhash = self.crop_and_save_face(panel_path, cached.char_id, box_xywh=boxes[0])
                    if rel:
                        cached.face_image_path = rel
                        cached.face_dhash = dhash
                        self.save()
            return cached

        # 2. Local OpenCV face crop + perceptual dHash match (never match across opposite gender hints)
        name_gender_hint = infer_gender_hint(base_name)
        cv_boxes = self.detect_face_boxes(panel_path) if (panel_path and panel_path.exists()) else []
        temp_face_path: Optional[Path] = None
        temp_dhash: Optional[str] = None
        if cv_boxes and panel_path:
            temp_slug = f"_tmp_{slugify_name(base_name)}"
            rel_tmp, temp_dhash = self.crop_and_save_face(panel_path, temp_slug, box_xywh=cv_boxes[0])
            if rel_tmp:
                temp_face_path = self.series_dir / rel_tmp
                matched = self.find_by_face_hash(temp_dhash, max_distance=10)
                if matched and matched.confirmed and (not name_gender_hint or matched.gender == name_gender_hint):
                    # Clean up temp face and record alias
                    if temp_face_path.exists():
                        temp_face_path.unlink(missing_ok=True)
                    if base_name not in matched.aliases and base_name.lower() != matched.canonical_name.lower():
                        matched.aliases.append(base_name)
                        self.save()
                    logger.info(
                        f"Matched panel face to stored character '{matched.canonical_name}' "
                        f"({matched.gender}, {matched.gemini_voice_id}) [0 API calls]."
                    )
                    return matched

        # 3. Not in cache -> Confirm once with Gemini Vision (if allowed and panel available)
        if allow_gemini and panel_path and panel_path.exists():
            inspect_img = temp_face_path if (temp_face_path and temp_face_path.exists()) else panel_path
            need_box = temp_face_path is None
            info = self._query_gemini_for_character(
                image_to_inspect=inspect_img,
                candidate_speaker=base_name,
                dialogue_text=dialogue_text,
                need_face_box=need_box,
            )
            if info and isinstance(info, dict):
                canon_name = (info.get("canonical_name") or base_name).strip()
                gender = (info.get("gender") or "male").strip().lower()
                # Guard against multi-character panels where Gemini picked the opposite-gender face
                if name_gender_hint and gender != name_gender_hint:
                    canon_name = base_name
                    gender = name_gender_hint
                age_group = (info.get("age_group") or "young_adult").strip().lower()
                estimated_age = str(info.get("estimated_age") or "").strip()
                role = (info.get("role") or "supporting").strip().lower()
                look = (info.get("look_archetype") or ("supporting_female" if gender == "female" else "supporting_male")).strip().lower()
                vis_desc = (info.get("visual_description") or "").strip()
                box_2d = info.get("face_box_2d")

                char_slug = slugify_name(canon_name)
                final_rel: Optional[str] = None
                final_dhash: Optional[str] = None

                if temp_face_path and temp_face_path.exists():
                    final_face = self.faces_dir / f"{char_slug}.jpg"
                    if final_face != temp_face_path:
                        temp_face_path.replace(final_face)
                    final_rel = f"faces/{char_slug}.jpg"
                    final_dhash = temp_dhash
                elif isinstance(box_2d, list) and len(box_2d) == 4 and "not visible" not in vis_desc.lower():
                    final_rel, final_dhash = self.crop_and_save_face(panel_path, char_slug, box_2d_norm=box_2d)

                aliases = [base_name] if base_name.lower() != canon_name.lower() else []
                profile = self.register_character(
                    canonical_name=canon_name,
                    gender=gender,
                    age_group=age_group,
                    look_archetype=look,
                    visual_description=vis_desc,
                    aliases=aliases,
                    face_rel_path=final_rel,
                    face_dhash=final_dhash,
                    source="gemini_vision",
                    estimated_age=estimated_age,
                    role=role,
                )
                logger.info(
                    f"Confirmed & stored character '{profile.canonical_name}' for '{self.series_name}': "
                    f"gender={profile.gender}, age={profile.age_group}, look={profile.look_archetype}, "
                    f"voice={profile.gemini_voice_id}"
                )
                return profile

        # 4. Zero-API Local Auto-Cast (Cloud GPU / Ollama mode):
        # Assign a distinct, permanently locked voice on first appearance so every character
        # keeps the exact same voice across all future chapters without calling Gemini API.
        loc_gender, loc_age, loc_look = infer_local_character_traits(base_name, dialogue_text)
        char_slug = slugify_name(base_name)
        final_rel: Optional[str] = None
        final_dhash: Optional[str] = None
        if temp_face_path and temp_face_path.exists():
            final_face = self.faces_dir / f"{char_slug}.jpg"
            if final_face != temp_face_path:
                temp_face_path.replace(final_face)
            final_rel = f"faces/{char_slug}.jpg"
            final_dhash = temp_dhash

        profile = self.register_character(
            canonical_name=base_name,
            gender=loc_gender,
            age_group=loc_age,
            look_archetype=loc_look,
            face_rel_path=final_rel,
            face_dhash=final_dhash,
            source="local_auto_cast",
        )
        logger.info(
            f"Auto-cast & locked character '{profile.canonical_name}' for '{self.series_name}' [0 API calls]: "
            f"gender={profile.gender}, age={profile.age_group}, voice={profile.gemini_voice_id} ({profile.voice_rate})"
        )
        return profile

    def format_roster_for_prompt(self) -> str:
        """Format confirmed characters into a concise prompt block for LLM storytelling consistency."""
        if not self.data.characters:
            return ""
        lines = [
            f"KNOWN CHARACTERS SO FAR FOR '{self.series_name}' "
            f"(use these exact names when THESE specific characters speak—never confuse them with other manhwas; "
            f"if a DIFFERENT or NEW character speaks—especially of the opposite gender—use that new character's own name/role, e.g. 'Boy' vs 'Girl'):"
        ]
        for prof in list(self.data.characters.values())[:30]:
            alias_str = f" (aliases: {', '.join(prof.aliases[:3])})" if prof.aliases else ""
            desc_str = f" — {prof.visual_description}" if prof.visual_description else ""
            lines.append(
                f"  - {prof.canonical_name}{alias_str} [{prof.gender}, {prof.age_group}, {prof.look_archetype}]{desc_str}"
            )
        return "\n".join(lines)

