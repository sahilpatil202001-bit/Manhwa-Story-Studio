"""
LLM Title & Hook generator: analyzes manhwa chapters using Google Gemini or cinematic fallback heuristics.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.request
from io import BytesIO
from pathlib import Path
from typing import List, Optional
from PIL import Image
from pydantic import BaseModel, Field

from manhwa_studio.env_config import get_env_config
from manhwa_studio.logging_config import get_logger

logger = get_logger("manhwa_studio.story.llm")


class ChapterAISuggestion(BaseModel):
    title: str
    alternative_titles: List[str] = Field(default_factory=list)
    hindi_hook: str
    summary: str
    provider: str = "gemini"


def get_base64_thumbnail(image_path: Path, max_size: int | tuple = 512) -> Optional[str]:
    """Create a lightweight JPEG thumbnail encoded in Base64 for multimodal vision analysis."""
    try:
        with Image.open(image_path) as img:
            thumb = img.convert("RGB")
            max_wh = max_size if isinstance(max_size, tuple) else (max_size, max_size)
            thumb.thumbnail(max_wh, Image.Resampling.LANCZOS)
            buf = BytesIO()
            thumb.save(buf, format="JPEG", quality=80)
            return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception as e:
        logger.warning(f"Could not prepare image thumbnail for {image_path.name}: {e}")
        return None


def generate_fallback_suggestion(series: str, chapter: int) -> ChapterAISuggestion:
    """Intelligent offline fallback title and hook when API key or network is absent."""
    curated_titles = [
        "The Monster Opens Its Eyes",
        "Cradle of Blood and Madness",
        "Descent of the Living Calamity",
        "The Ruthless Shadow Strikes",
        "When the Predator Becomes Prey",
        "A Deal Sealed in Blood",
        "The Unbreakable Curse",
        "Wrath of the Nameless Demon",
        "Breaking the Chains of Fate",
        "The Final Reckoning Begins",
    ]
    idx = (chapter - 1) % len(curated_titles)
    selected_title = curated_titles[idx]
    alts = [curated_titles[(idx + 1) % len(curated_titles)], curated_titles[(idx + 2) % len(curated_titles)]]

    hooks = [
        "रात का सन्नाटा और मौत की आहट... इस अंधेरी दुनिया में सिर्फ वही जिंदा रहता है, जो सबसे बेरहम हो।",
        "जब सबने सोचा कि वह खत्म हो चुका है, तब अंधेरे से एक ऐसा साया निकला जिसने सबको थर्रा दिया।",
        "दुश्मनों को लगा कि वे शिकारी हैं... पर वे यह भूल गए कि मौत उनके बिल्कुल पीछे खड़ी थी।",
    ]
    hook = hooks[(chapter - 1) % len(hooks)]

    return ChapterAISuggestion(
        title=selected_title,
        alternative_titles=alts,
        hindi_hook=hook,
        summary=f"Dramatic story progression of {series} in Chapter {chapter}.",
        provider="curated_fallback",
    )


GEMINI_MODELS = [
    "gemini-3.5-flash-lite",   # High-throughput, fastest reliable Flash model
    "gemini-3-flash-preview",  # Fast Gemini 3 Flash
    "gemini-3.8-flash",        # Latest 3.8 flagship Flash model
    "gemini-flash-latest",     # Stable Google alias
]

OLLAMA_DEFAULT_MODEL = "qwen2.5vl:7b"

_MODEL_COOLDOWNS: dict[str, float] = {}
_INVALID_KEYS: set[str] = set()
_PREFERRED_MODEL: Optional[str] = None


def get_all_gemini_api_keys(api_key: Optional[str] = None) -> List[str]:
    """
    Extract and deduplicate all comma-separated Gemini API keys from `api_key`, `os.environ`, and `.env`.
    Supports both Google AI Studio Authorization keys (`AQ...`, default since May 2026) and Standard keys (`AIza...`).
    """
    raw_parts: List[str] = []
    if api_key and api_key.strip():
        raw_parts.append(api_key.strip("\"' "))
    for env_k, env_v in sorted(os.environ.items()):
        if env_k in ("GEMINI_API_KEY", "GEMINI_API_KEYS") or env_k.startswith("GEMINI_API_KEY_"):
            if env_v and env_v.strip():
                raw_parts.append(env_v.strip("\"' "))
    env_file = Path(".env")
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k_name, k_val = s.split("=", 1)
                k_name = k_name.strip()
                if k_name in ("GEMINI_API_KEY", "GEMINI_API_KEYS") or k_name.startswith("GEMINI_API_KEY_"):
                    raw_parts.append(k_val.strip("\"' "))

    keys: List[str] = []
    for part in raw_parts:
        for k in part.split(","):
            k_clean = k.strip("\"' ")
            if k_clean and k_clean not in keys and k_clean not in _INVALID_KEYS:
                keys.append(k_clean)
    return keys


_KEY_CURSOR: int = 0
_OPENAI_AUTH_FAILED: bool = False
_GROQ_KEY_CURSOR: int = 0
_OPENROUTER_KEY_CURSOR: int = 0
_DEAD_PROVIDER_KEYS: set[str] = set()  # Blacklist keys that return 401/402/403 so failover is instant


def _parse_multi_keys(env_vars: List[str], explicit_key: Optional[str] = None) -> List[str]:
    """Parse comma/newline-separated API keys from explicit arg and env vars, skipping placeholders & dead keys."""
    raw_items: List[str] = []
    if explicit_key:
        raw_items.append(explicit_key)
    for var in env_vars:
        val = os.environ.get(var, "")
        if val:
            raw_items.append(val)
    keys: List[str] = []
    for chunk in raw_items:
        for part in chunk.replace("\n", ",").split(","):
            k = part.strip().strip('"').strip("'")
            if not k or k.startswith("your_") or len(k) < 10:
                continue
            if k not in keys and k not in _DEAD_PROVIDER_KEYS:
                keys.append(k)
    return keys


def _extract_json_payload(raw_text: str) -> Any:
    """Safely parse JSON from LLM responses even if wrapped in ```json ... ``` markdown fences."""
    import re
    txt = (raw_text or "").strip()
    if not txt:
        raise ValueError("Empty LLM response")
    if txt.startswith("```"):
        txt = re.sub(r"^```(?:json)?\s*", "", txt, flags=re.IGNORECASE)
        txt = re.sub(r"\s*```$", "", txt)
    try:
        return json.loads(txt)
    except Exception:
        # Try extracting first JSON object or array
        m = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", txt)
        if m:
            return json.loads(m.group(1))
        raise


def _query_openai_compat_vision(
    provider_name: str,
    endpoint_url: str,
    api_keys: List[str],
    models: List[str],
    prompt_text: str,
    image_panels: List[tuple[str, str]],
    extra_headers: Optional[Dict[str, str]] = None,
    timeout: int = 60,
) -> Optional[tuple[Any, str]]:
    """
    Generic resilient OpenAI-compatible Vision caller with:
      - Multi-key round-robin rotation
      - Per-(key, model) 429 cooldown
      - Instant key blacklisting on 401/402/403 (invalid or out-of-credit key)
      - 503 backoff & automatic failover to next key/model
    """
    global _GROQ_KEY_CURSOR, _OPENROUTER_KEY_CURSOR
    import time

    if not api_keys or not models:
        return None

    content: List[dict] = [{"type": "text", "text": prompt_text}]
    for p_name, b64_img in image_panels:
        content.append({"type": "text", "text": f"Panel: {p_name}"})
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"},
        })

    n_keys = len(api_keys)
    cursor = _GROQ_KEY_CURSOR if provider_name == "Groq" else _OPENROUTER_KEY_CURSOR

    for model_name in models:
        clean_model = model_name.strip()
        if not clean_model:
            continue
        start_offset = cursor % n_keys
        ordered_keys = [
            (((start_offset + i) % n_keys) + 1, api_keys[(start_offset + i) % n_keys])
            for i in range(n_keys)
        ]
        transient_fails = 0
        for k_idx, single_key in ordered_keys:
            if single_key in _DEAD_PROVIDER_KEYS:
                continue
            cd_token = f"{provider_name}:{single_key[-6:]}:{clean_model}"
            if _MODEL_COOLDOWNS.get(cd_token, 0.0) > time.time():
                continue

            if provider_name == "Groq":
                _GROQ_KEY_CURSOR = k_idx % n_keys
            else:
                _OPENROUTER_KEY_CURSOR = k_idx % n_keys

            payload = {
                "model": clean_model,
                "messages": [{"role": "user", "content": content}],
                "response_format": {"type": "json_object"},
                "temperature": 0.5,
            }
            headers = {
                "Authorization": f"Bearer {single_key}",
                "Content-Type": "application/json",
                "User-Agent": "ManhwaStoryStudioPro/2.0",
            }
            if extra_headers:
                headers.update(extra_headers)

            try:
                req = urllib.request.Request(
                    endpoint_url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers=headers,
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    res_data = json.loads(resp.read().decode("utf-8"))
                    raw_text = res_data["choices"][0]["message"]["content"]
                    parsed = _extract_json_payload(raw_text)
                    logger.info(
                        f"Successfully queried {provider_name} with model '{clean_model}' "
                        f"(key {k_idx}/{n_keys}: ...{single_key[-6:]})"
                    )
                    return parsed, f"{provider_name.lower()}:{clean_model}"
            except Exception as exc:
                err_str = str(exc)
                if any(c in err_str for c in ("401", "402", "403", "Unauthorized", "Payment Required")):
                    _DEAD_PROVIDER_KEYS.add(single_key)
                    logger.warning(
                        f"{provider_name} key ...{single_key[-6:]} invalid or out of credits ({err_str}) — "
                        f"blacklisting key and failing over..."
                    )
                    continue
                if "429" in err_str or "Too Many Requests" in err_str:
                    _MODEL_COOLDOWNS[cd_token] = time.time() + get_env_config().rate_limit_cooldown_sec
                    logger.info(
                        f"{provider_name} model '{clean_model}' hit rate limit (429) on key ...{single_key[-6:]}, trying next key/model..."
                    )
                    continue
                if "404" in err_str:
                    logger.warning(f"{provider_name} model '{clean_model}' not found (404), trying next model...")
                    break
                if "503" in err_str or "502" in err_str or "timed out" in err_str.lower():
                    transient_fails += 1
                    logger.warning(f"{provider_name} model '{clean_model}' transient error on key ...{single_key[-6:]}: {exc}")
                    if transient_fails >= min(3, max(2, n_keys)):
                        break
                    time.sleep(1.5 * transient_fails)
                    continue
                logger.warning(f"{provider_name} model '{clean_model}' failed on key ...{single_key[-6:]}: {exc}")
                continue
    return None


def query_openrouter_api(
    prompt_text: str,
    image_panels: List[tuple[str, str]],
    api_key: Optional[str] = None,
    timeout: int = 75,
) -> Optional[tuple[Any, str]]:
    """Query OpenRouter Vision models (supports comma-separated OPENROUTER_API_KEY / OPENROUTER_API_KEYS)."""
    keys = _parse_multi_keys(["OPENROUTER_API_KEY", "OPENROUTER_API_KEYS"], explicit_key=api_key)
    if not keys:
        return None
    models = get_env_config().openrouter_models or [
        "google/gemini-2.5-flash",
        "qwen/qwen2.5-vl-72b-instruct",
        "google/gemini-2.5-flash-lite",
        "meta-llama/llama-4-scout",
    ]
    return _query_openai_compat_vision(
        provider_name="OpenRouter",
        endpoint_url="https://openrouter.ai/api/v1/chat/completions",
        api_keys=keys,
        models=models,
        prompt_text=prompt_text,
        image_panels=image_panels,
        extra_headers={
            "HTTP-Referer": "https://manhwa-story-studio.local",
            "X-Title": "Manhwa Story Studio Pro",
        },
        timeout=timeout,
    )


def query_groq_api(
    prompt_text: str,
    image_panels: List[tuple[str, str]],
    api_key: Optional[str] = None,
    timeout: int = 60,
) -> Optional[tuple[Any, str]]:
    """
    Query Groq Vision models (Llama 4 Scout / Maverick).
    Automatically splits batches larger than 4 images into sub-chunks (Groq's 5-image limit)
    and merges the resulting JSON scenes cleanly so zero panels are ever dropped!
    """
    keys = _parse_multi_keys(["GROQ_API_KEY", "GROQ_API_KEYS"], explicit_key=api_key)
    if not keys:
        return None
    models = get_env_config().groq_models or [
        "meta-llama/llama-4-scout-17b-16e-instruct",
        "meta-llama/llama-4-maverick-17b-128e-instruct",
    ]

    if len(image_panels) <= 4:
        return _query_openai_compat_vision(
            provider_name="Groq",
            endpoint_url="https://api.groq.com/openai/v1/chat/completions",
            api_keys=keys,
            models=models,
            prompt_text=prompt_text,
            image_panels=image_panels,
            timeout=timeout,
        )

    # Auto-chunk into sub-batches of 4 images to respect Groq's max-5-images-per-request limit
    merged_scenes: List[dict] = []
    merged_meta: Dict[str, Any] = {}
    last_model = "groq:llama-4-scout"

    for start in range(0, len(image_panels), 4):
        sub_panels = image_panels[start : start + 4]
        sub_names = ", ".join(p[0] for p in sub_panels)
        sub_prompt = (
            f"{prompt_text}\n\n"
            f"IMPORTANT: Return JSON ONLY for these {len(sub_panels)} attached panels in exact order: {sub_names}."
        )
        res = _query_openai_compat_vision(
            provider_name="Groq",
            endpoint_url="https://api.groq.com/openai/v1/chat/completions",
            api_keys=keys,
            models=models,
            prompt_text=sub_prompt,
            image_panels=sub_panels,
            timeout=timeout,
        )
        if not res:
            return None
        sub_parsed, last_model = res
        if isinstance(sub_parsed, dict):
            if not merged_meta:
                for k in ("title", "hindi_hook", "summary", "alternative_titles"):
                    if k in sub_parsed:
                        merged_meta[k] = sub_parsed[k]
            merged_scenes.extend(sub_parsed.get("scenes", []))
        elif isinstance(sub_parsed, list):
            merged_scenes.extend(sub_parsed)

    if merged_meta:
        merged_meta["scenes"] = merged_scenes
        return merged_meta, last_model
    return {"scenes": merged_scenes}, last_model


def query_gemini_api(payload: dict, api_key: str, timeout: int = 60) -> Optional[tuple[dict, str]]:
    """
    Try candidate Gemini models across all configured comma-separated Gemini API keys
    using Google AI Studio (`generativelanguage.googleapis.com`) and the `x-goog-api-key` header,
    supporting both Authorization (`AQ...`) and Standard (`AIza...`) keys.
    Uses round-robin key rotation across all keys + short backoff on 503 bursts.
    """
    global _PREFERRED_MODEL, _KEY_CURSOR
    import time

    api_keys = get_all_gemini_api_keys(api_key)
    if not api_keys:
        logger.warning("No valid GEMINI_API_KEY found.")
        return None

    raw_models = get_env_config().gemini_models or GEMINI_MODELS
    norm_models: List[str] = []
    for m in raw_models:
        m_clean = m.strip()
        if m_clean and m_clean not in norm_models:
            norm_models.append(m_clean)
    for m in GEMINI_MODELS:
        if m not in norm_models:
            norm_models.append(m)

    now = time.time()
    candidates: List[str] = []

    if _PREFERRED_MODEL and _PREFERRED_MODEL in norm_models and now >= _MODEL_COOLDOWNS.get(_PREFERRED_MODEL, 0):
        candidates.append(_PREFERRED_MODEL)

    for m in norm_models:
        if m not in candidates and now >= _MODEL_COOLDOWNS.get(m, 0):
            candidates.append(m)

    for m in norm_models:
        if m not in candidates:
            candidates.append(m)

    norm_payload = dict(payload)
    if "contents" in norm_payload and isinstance(norm_payload["contents"], list):
        norm_contents = []
        for c_item in norm_payload["contents"]:
            if isinstance(c_item, dict) and "role" not in c_item:
                norm_contents.append({"role": "user", **c_item})
            else:
                norm_contents.append(c_item)
        norm_payload["contents"] = norm_contents

    for model_name in candidates:
        clean_model = model_name.replace("models/", "")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_model}:generateContent"
        transient_model_failures = 0
        # Rotate starting key so all configured keys (1..N) share load evenly
        n_keys = len(api_keys)
        start_offset = _KEY_CURSOR % n_keys
        ordered_keys = [
            (((start_offset + i) % n_keys) + 1, api_keys[(start_offset + i) % n_keys])
            for i in range(n_keys)
        ]
        # Cap per-request timeout on slow preview models so one hang never stalls for 60s x 5
        eff_timeout = min(timeout, 35) if "preview" in clean_model else timeout

        for k_idx, single_key in ordered_keys:
            cd_token = f"{single_key[-6:]}:{clean_model}"
            if _MODEL_COOLDOWNS.get(cd_token, 0.0) > time.time():
                continue

            _KEY_CURSOR = k_idx % n_keys
            try:
                req = urllib.request.Request(
                    url,
                    data=json.dumps(norm_payload).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "x-goog-api-key": single_key,
                    },
                )
                with urllib.request.urlopen(req, timeout=eff_timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    logger.info(
                        f"Successfully queried Gemini with model '{clean_model}' (key {k_idx}/{n_keys}: ...{single_key[-6:]})"
                    )
                    _PREFERRED_MODEL = clean_model
                    return data, clean_model
            except Exception as exc:
                err_str = str(exc)
                if "429" in err_str or "Too Many Requests" in err_str:
                    _MODEL_COOLDOWNS[cd_token] = time.time() + get_env_config().rate_limit_cooldown_sec
                    logger.info(
                        f"Gemini model '{clean_model}' hit rate limit (429) on key ...{single_key[-6:]}, trying next key/model..."
                    )
                elif "404" in err_str:
                    logger.warning(f"Gemini model '{clean_model}' failed ({exc}), attempting next model...")
                    break
                elif "503" in err_str or "timed out" in err_str.lower():
                    transient_model_failures += 1
                    logger.warning(
                        f"Gemini model '{clean_model}' overloaded/timeout on key ...{single_key[-6:]} ({exc})"
                    )
                    if transient_model_failures >= min(3, max(2, n_keys)):
                        _MODEL_COOLDOWNS[clean_model] = time.time() + 20.0
                        logger.info(f"Switching away from overloaded model '{clean_model}' to next model...")
                        break
                    # Brief backoff on 503 bursts so Google backend recovers instead of hammering 0ms apart
                    time.sleep(1.5 * transient_model_failures)
                else:
                    logger.warning(f"Gemini model '{clean_model}' on key ...{single_key[-6:]} failed ({exc}), attempting next...")
    return None


def query_openai_api(
    prompt_text: str,
    image_panels: List[tuple[str, str]],
    api_key: Optional[str] = None,
    timeout: int = 40,
) -> Optional[tuple[dict, str]]:
    """Query OpenAI chat completions (gpt-4o-mini or gpt-4o) using vision and json mode."""
    global _OPENAI_AUTH_FAILED
    if _OPENAI_AUTH_FAILED:
        return None
    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key or key.startswith("your_"):
        return None

    content: List[dict] = [{"type": "text", "text": prompt_text}]
    for p_name, b64_img in image_panels:
        content.append({"type": "text", "text": f"Panel: {p_name}"})
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64_img}", "detail": "low"},
        })

    openai_models = get_env_config().openai_models or ["gpt-4o-mini", "gpt-4o"]
    for model_name in openai_models:
        payload = {
            "model": model_name,
            "messages": [{"role": "user", "content": content}],
            "response_format": {"type": "json_object"},
            "temperature": 0.5,
        }
        url = "https://api.openai.com/v1/chat/completions"
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                raw_text = res_data["choices"][0]["message"]["content"]
                parsed = json.loads(raw_text)
                logger.info(f"Successfully queried OpenAI with model '{model_name}'")
                return parsed, model_name
        except Exception as exc:
            if "401" in str(exc) or "Unauthorized" in str(exc):
                _OPENAI_AUTH_FAILED = True
                logger.info("OpenAI API key unauthorized (401) — disabling OpenAI fallback for this run.")
                return None
            logger.warning(f"OpenAI model '{model_name}' failed ({exc}), attempting next...")
            continue
    return None


def query_ollama_api(
    prompt_text: str,
    image_panels: List[tuple[str, str]],
    timeout: int = 600,
) -> Optional[tuple[dict | list, str]]:
    """Run a vision prompt against a local Ollama model without an API key.

    Ollama accepts base64-encoded images in its local ``/api/chat`` endpoint.
    ``format: json`` makes Qwen return machine-readable output while keeping the
    request compatible with current Ollama releases.
    """
    model_name = os.environ.get("OLLAMA_MODEL", OLLAMA_DEFAULT_MODEL).strip() or OLLAMA_DEFAULT_MODEL
    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
    # Vision batches contain eight 512px panels. Qwen's 128k default context
    # wastes considerable VRAM on consumer GPUs; 16k leaves ample room for
    # these panels, the prompt, and the short JSON response.
    try:
        num_ctx = max(4096, int(os.environ.get("OLLAMA_NUM_CTX", "16384")))
    except ValueError:
        num_ctx = 16384
    payload = {
        "model": model_name,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.5, "num_ctx": num_ctx},
        "keep_alive": "15m",
        "messages": [{
            "role": "user",
            "content": prompt_text,
            "images": [image_b64 for _, image_b64 in image_panels],
        }],
    }
    try:
        req = urllib.request.Request(
            f"{host}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        raw_json = data.get("message", {}).get("content", "")
        if not raw_json:
            raise ValueError(f"Ollama returned no message content: {data.get('error', 'unknown error')}")
        parsed = json.loads(raw_json)
        logger.info(f"Successfully queried local Ollama model '{model_name}'")
        return parsed, f"ollama/{model_name}"
    except Exception as exc:
        logger.warning(f"Local Ollama model '{model_name}' failed ({exc})")
        return None


def suggest_chapter_title_and_hook(
    series: str,
    chapter: int,
    sample_images: Optional[List[Path]] = None,
    api_key: Optional[str] = None,
) -> ChapterAISuggestion:
    """
    Analyze chapter panels and request high-impact YouTube Shorts title and Hindi hook from Gemini.
    Falls back gracefully to curated cinematic presets if no API key is configured.
    """
    provider_pref = os.environ.get("LLM_PROVIDER", "gemini").strip().lower()
    key = api_key or os.environ.get("GEMINI_API_KEY")
    if not key and provider_pref != "ollama":
        raise ValueError("GEMINI_API_KEY is not configured in .env or environment. Please add GEMINI_API_KEY to your .env file.")

    prompt_text = (
        f"You are a professional video producer crafting high-CTR YouTube Shorts / Reels for manhwa story explainers.\n"
        f"Series: {series}\n"
        f"Chapter: {chapter}\n"
        f"Generate a compelling, suspenseful title in English (under 7 words), 2 alternative titles, "
        f"and one dramatic opening Hindi narration hook line (in Devanagari Hindi) that captures viewer attention in 3 seconds.\n"
        f"Output strictly valid JSON with keys: title, alternative_titles, hindi_hook, summary."
    )

    parts: List[dict] = [{"text": prompt_text}]
    ollama_images: List[tuple[str, str]] = []

    # Optionally attach cover panel thumbnail for vision inspection
    if sample_images and len(sample_images) > 0:
        b64_thumb = get_base64_thumbnail(sample_images[0])
        if b64_thumb:
            ollama_images.append((sample_images[0].name, b64_thumb))
            parts.append({
                "inlineData": {
                    "mimeType": "image/jpeg",
                    "data": b64_thumb,
                }
            })

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.7,
        },
    }

    try:
        parsed = None
        model_used = "unknown"
        if provider_pref == "ollama":
            result = query_ollama_api(prompt_text, ollama_images)
            if not result:
                raise RuntimeError("Local Ollama could not generate a title and hook. Is Ollama running and is the model installed?")
            parsed, model_used = result
        else:
            # Ordered failover for Title + Hook: preferred provider first, then Gemini -> OpenRouter -> Groq
            if provider_pref == "openrouter":
                res_or = query_openrouter_api(prompt_text, ollama_images, timeout=30)
                if res_or:
                    parsed, model_used = res_or
            elif provider_pref == "groq":
                res_gr = query_groq_api(prompt_text, ollama_images, timeout=30)
                if res_gr:
                    parsed, model_used = res_gr

            if not parsed and key:
                res = query_gemini_api(payload, key, timeout=25)
                if res:
                    data, model_used = res
                    raw_json = data["candidates"][0]["content"]["parts"][0]["text"]
                    parsed = _extract_json_payload(raw_json)

            if not parsed and provider_pref != "openrouter":
                res_or = query_openrouter_api(prompt_text, ollama_images, timeout=30)
                if res_or:
                    parsed, model_used = res_or

            if not parsed and provider_pref != "groq":
                res_gr = query_groq_api(prompt_text, ollama_images, timeout=30)
                if res_gr:
                    parsed, model_used = res_gr

            if not parsed:
                raise RuntimeError(
                    f"All configured providers (Gemini/OpenRouter/Groq) failed to generate title and hook for Chapter {chapter}."
                )
        if not isinstance(parsed, dict):
            raise ValueError("model returned a JSON value other than an object")
        suggestion = ChapterAISuggestion(
            title=parsed.get("title", f"Chapter {chapter} Revealed"),
            alternative_titles=parsed.get("alternative_titles", []),
            hindi_hook=parsed.get("hindi_hook", "एक नई खौफनाक शुरुआत..."),
            summary=parsed.get("summary", ""),
            provider=model_used,
        )
        logger.info(f"{model_used} suggested title: '{suggestion.title}' for Ch.{chapter}")
        return suggestion
    except Exception as exc:
        raise RuntimeError(f"Failed parsing Gemini title output for Chapter {chapter}: {exc}. Stopping execution as requested.")


class DialogueSceneItem(BaseModel):
    speaker: str = "Narrator"
    speaker_gender: Optional[str] = None
    scene_purpose: str = "dialogue"
    hindi_text: str = ""
    suggested_panel: str = ""
    motion_preset: str = "slow_zoom_in"


class ChapterScreenplay(BaseModel):
    title: str
    hindi_hook: str
    scenes: List[DialogueSceneItem] = Field(default_factory=list)
    provider: str = "gemini"


def is_character_or_action_panel(fpath: Path, index: int = 0, total: int = 100) -> bool:
    """
    Check if a panel actually features a character, face, or combat action,
    discarding speech-bubble-only frames, blank gutters, low-detail sky/clouds intro panels,
    and translator/scanlation credit banners at the very start or end of a chapter.
    """
    try:
        import cv2
        import numpy as np

        img = cv2.imread(str(fpath))
        if img is None:
            return False
        h, w = img.shape[:2]
        if h < 80 or w < 80:
            return False

        # Very thin horizontal strips are usually divider banners or website watermarks
        if h < int(w * 0.22):
            return False

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        std_val = float(np.std(gray))
        # Discard pure monochrome blank gutters / scroll spacing bars
        if std_val < 10.0:
            return False

        # For the first 2 panels or last 2 panels, filter out nearly-empty sky/gradient/logo filler panels
        if index < 2 or index >= total - 2:
            edges = cv2.Canny(gray, 60, 160)
            edge_density = float(np.count_nonzero(edges)) / float(h * w)
            if std_val < 18.0 and edge_density < 0.008:
                return False

        return True
    except Exception as e:
        logger.debug(f"Panel check error: {e}")
        return True


def filter_character_panels(panel_paths: List[Path]) -> List[Path]:
    """Filter out empty gutter separators and blank intro/outro filler panels while preserving all story panels."""
    total = len(panel_paths)
    valid = [p for i, p in enumerate(panel_paths) if is_character_or_action_panel(p, index=i, total=total)]
    return valid if len(valid) >= 5 else panel_paths


def generate_chapter_screenplay(
    series: str,
    chapter: int,
    panel_files: List[str],
    sample_images: Optional[List[Path]] = None,
    api_key: Optional[str] = None,
    part: int = 1,
    total_parts: int = 1,
    checkpoint_path: Optional[Path] = None,
) -> ChapterScreenplay:
    """
    Generate an engaging single-narrator Hindi storytelling recap script with Gemini Flash,
    covering the panels in sequential order without large skips.
    Resilient with auto-checkpointing, 4-attempt progressive backoff, and rate pacing.
    """
    provider_pref = os.environ.get("LLM_PROVIDER", "gemini").strip().lower()
    key = api_key or os.environ.get("GEMINI_API_KEY")

    # panel_files is already partitioned for this specific part by pipeline.py
    active_panels = panel_files

    if not key and provider_pref != "ollama":
        raise ValueError("GEMINI_API_KEY is not configured in .env or environment. Cannot generate AI comic dub.")

    part_context = f"Part {part} of {total_parts}" if total_parts > 1 else "Complete Story"
    total_panels = len(active_panels)
    image_lookup = {p.name: p for p in sample_images} if sample_images else {}

    # Batch panels in chunks of 8 to 10 for complete, unbroken panel-by-panel coverage
    batch_size = get_env_config().llm_batch_size
    all_scenes: List[DialogueSceneItem] = []
    episode_title = f"{series} - Chapter {chapter}"
    episode_hook = "एक नई खौफनाक दास्तान शुरू होती है..."
    active_model_used = "gemini-2.5-flash"

    batches = [active_panels[i : i + batch_size] for i in range(0, total_panels, batch_size)]
    logger.info(f"Generating full sequential comic dub for {total_panels} panels across {len(batches)} batches (0 skipped panels).")

    import time

    completed_batches: dict[str, list[dict]] = {}
    if checkpoint_path and checkpoint_path.exists():
        try:
            ckpt_data = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            if ckpt_data.get("chapter") == chapter and ckpt_data.get("series") == series:
                completed_batches = ckpt_data.get("completed_batches", {})
                episode_title = ckpt_data.get("episode_title", episode_title)
                episode_hook = ckpt_data.get("episode_hook", episode_hook)
                active_model_used = ckpt_data.get("active_model_used", active_model_used)
                logger.info(
                    f"Found screenplay checkpoint with {len(completed_batches)}/{len(batches)} batches completed. Resuming..."
                )
        except Exception as e:
            logger.warning(f"Could not read screenplay checkpoint: {e}")

    for b_idx, batch in enumerate(batches):
        b_key = str(b_idx)
        if b_key in completed_batches:
            logger.info(f"Loaded Batch {b_idx + 1}/{len(batches)} ({len(batch)} panels) from checkpoint.")
            for sc in completed_batches[b_key]:
                all_scenes.append(
                    DialogueSceneItem(
                        speaker=sc.get("speaker", "Narrator"),
                        speaker_gender=sc.get("speaker_gender"),
                        scene_purpose=sc.get("scene_purpose", "dialogue"),
                        hindi_text=sc.get("hindi_text", ""),
                        suggested_panel=sc.get("suggested_panel", ""),
                        motion_preset=sc.get("motion_preset", "pan_up"),
                    )
                )
            continue

        is_first_batch = (b_idx == 0)
        is_last_batch = (b_idx == len(batches) - 1)

        cliffhanger_note = (
            "For the very last panel, provide a high-stakes cliffhanger line urging viewers to follow/subscribe for the next part!"
            if is_last_batch and total_parts > 1 and part < total_parts
            else ""
        )

        series_context_lower = series.lower()
        situational_casting_rule = ""
        if "girlfriend" in series_context_lower and "dragon" in series_context_lower:
            situational_casting_rule = (
                "8. SITUATIONAL SPEAKER CASTING FOR 'My Girlfriend Returned as a Dragon':\n"
                "   - Boy: 'Boy' (normal speech), 'Boy (Shocked)' (panicked/screaming at dragon powers), 'Boy (Romantic)' (tender/loving), 'Boy (Determined)' (serious/protective).\n"
                "   - Girl: 'Girl' (normal girlfriend), 'Girl (Cute)' (playful/pouting/teasing), 'Girl (Dragon)' (regal ancient dragon queen), 'Girl (Fierce)' (protective rage/dragon roar).\n"
                "   - 'Narrator': for scene setup and non-dialogue narration.\n"
            )
        elif "nano" in series_context_lower and "machine" in series_context_lower:
            situational_casting_rule = (
                "8. SITUATIONAL SPEAKER CASTING FOR 'Nano Machine':\n"
                "   - Protagonist: 'Cheon Yeo-Woon' (normal confident young master), 'Cheon Yeo-Woon (Wounded)' (in severe pain/poisoned/struggling), 'Cheon Yeo-Woon (Cold)' (chilling ruthless demonic sovereign), 'Cheon Yeo-Woon (Enraged)' (furious battle roar).\n"
                "   - Nano Machine AI: 'Nano' (attractive, smooth, human-like AI assistant), 'Nano (Warning)' (urgent danger/poison alert), 'Nano (Analysis)' (meridian scan & martial transfer), 'Nano (Combat)' (battle trajectory simulation).\n"
                "   - Allies & Rivals: 'Guard Jang', 'Guard Jang (Wounded)', 'Sub-Meng', 'Lady Mun', 'Cadet'.\n"
                "   - Elders, Masters & Enemies: 'Lord Cheon', 'Grand Guardian', 'Elder', 'Instructor', 'Assassin', 'Lady'.\n"
                "   - 'Narrator': for cinematic narration.\n"
            )

        if not situational_casting_rule:
            try:
                from manhwa_studio.studio_pro.series_manager import SeriesManager
                prof = SeriesManager().get_or_create_profile(series)
                valid_speakers = list(prof.character_voices.keys())[:24]
                if valid_speakers:
                    speaker_list_str = ", ".join(f"'{sp}'" for sp in valid_speakers)
                    situational_casting_rule = (
                        f"8. MULTI-VOICE SPEAKER CASTING FOR '{series}':\n"
                        f"   - Assign 'speaker' using one of these configured character/role voices whenever a character speaks: {speaker_list_str}.\n"
                        f"   - Use 'Narrator' ONLY for third-person scene narration, never when a character is speaking in a bubble.\n"
                    )
            except Exception:
                pass

        opening_hook_rule = (
            "7. FIRST-SCENE HIGH-RETENTION HOOK (MANDATORY FOR BATCH 1):\n"
            "   - Panel 1 and Panel 2 are the FIRST 10 SECONDS of the video! Viewers click away if you start with slow weather, sky, or scenery descriptions.\n"
            "   - Even if Panel 1 shows a building, sky, or landscape, DO NOT describe the weather or scenery! Instead, open with an explosive, high-stakes dramatic hook or mystery question about the protagonist's danger, revenge, or power (e.g., 'जिस इंसान को पूरी दुनिया ने मरा हुआ समझ लिया था, आज वही मौत बनकर वापस लौट आया है!').\n"
            if is_first_batch
            else ""
        )

        registry_roster_block = ""
        try:
            from manhwa_studio.story.character_registry import CharacterRegistry
            char_reg = CharacterRegistry(series)
            roster_str = char_reg.format_roster_for_prompt()
            if roster_str:
                registry_roster_block = f"{roster_str}\n\n"
        except Exception:
            pass

        prompt_text = (
            f"You are an elite anime & manhwa comic dub director and translator.\n"
            f"Series: '{series}', Chapter {chapter} ({part_context}), Batch {b_idx + 1} of {len(batches)}.\n"
            f"Attached are {len(batch)} CONSECUTIVE manhwa panels in exact reading order: {', '.join(batch)}.\n\n"
            f"{registry_roster_block}"
            f"CRITICAL RULES FOR 100% AUTHENTIC COMIC DUB (ZERO SKIPPED PANELS):\n"
            f"1. ZERO SKIPPED PANELS: You MUST return a dialogue scene for EVERY SINGLE ONE of the {len(batch)} attached panels in exact order.\n"
            f"2. NO SILENCE OR ELLIPSES ('...'): Spoken voiceover is required for EVERY panel. 'hindi_text' must NEVER be empty or just dots ('...'). Every panel MUST contain real Hindi words for voice acting.\n"
            f"3. MODERN ENERGETIC CONVERSATIONAL HINDI IN 100% DEVANAGARI SCRIPT:\n"
            f"   - Speak like an official Netflix/Crunchyroll Hindi anime dubber! Use natural everyday spoken Hindi mixed with modern action terms written in DEVANAGARI script (e.g., सिस्टम, लेवल, पॉवर, ऑरा, अटैक, टेक्निक, स्वॉर्ड, स्किल, मास्टर, यंग मास्टर, क्लैन, गार्ड, डेंजर, टारगेट, बॉस, सीक्रेट, स्पीड, चैलेंज).\n"
            f"   - Write ALL words in Devanagari script (do NOT use Latin/English alphabet letters) so the Indian TTS voice maintains a 100% consistent Indian accent without shifting to a British/UK accent.\n"
            f"   - STRICTLY AVOID hard, textbook, bookish, or Sanskritized Hindi words (DO NOT use words like 'आत्मा-संयोजन', 'अवलोकन', 'कदाचित', 'प्रतीक्षा', 'विनाशकारी', 'साजिशों का साया', 'मंजर', 'सन्नाटा', 'प्रहार', 'आंतरिक ऊर्जा').\n"
            f"   - GOOD EXAMPLES: 'इस कल्ट में हर कदम पर मौत खड़ी है, पर आज उसका सामना असली शैतान से होने वाला है!'\n"
            f"   - GOOD EXAMPLES: 'यह खतरनाक सीन देख कर भी उसका रिएक्शन एकदम कोल्ड और निडर था!'\n"
            f"   - GOOD EXAMPLES: 'वॉर्निंग मास्टर! आपकी बॉडी में खतरनाक जहर फैल रहा है, नैनो स्कैन तुरंत शुरू हो रहा है!'\n"
            f"4. TRANSLATE WHAT CHARACTERS ACTUALLY SPEAK: Read the speech bubbles and text in each panel and translate them directly into punchy, natural spoken Hindi dialogue (Devanagari script).\n"
            f"5. SILENT / ACTION / COVER PANELS: If a panel has no speech bubble, set 'speaker': 'Narrator' (or the character's internal reaction) and give a punchy, high-tension 1-sentence Hindi line that drives curiosity.\n"
            f"6. MOTION: Assign 'motion_preset': 'pan_up' (bottom-to-up vertical webtoon slide) or 'pan_down'.\n"
            f"{opening_hook_rule}"
            f"{cliffhanger_note}\n"
            f"{situational_casting_rule}\n"
            f"Output strictly valid JSON with keys: 'title', 'hindi_hook', 'scenes': list of {{"
            f"'suggested_panel': str, 'speaker': str, 'hindi_text': str, 'motion_preset': 'pan_up' | 'pan_down'}}"
        )

        parts: List[dict] = [{"text": prompt_text}]
        batch_images_b64: List[tuple[str, str]] = []

        for p_name in batch:
            p_file = image_lookup.get(p_name)
            if p_file and p_file.exists():
                b64_thumb = get_base64_thumbnail(p_file, max_size=512)
                if b64_thumb:
                    batch_images_b64.append((p_name, b64_thumb))
                    parts.append({"text": f"Panel: {p_name}"})
                    parts.append({
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": b64_thumb,
                        }
                    })

        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": {
                    "type": "OBJECT",
                    "properties": {
                        "title": {"type": "STRING"},
                        "hindi_hook": {"type": "STRING"},
                        "scenes": {
                            "type": "ARRAY",
                            "items": {
                                "type": "OBJECT",
                                "properties": {
                                    "suggested_panel": {"type": "STRING"},
                                    "speaker": {"type": "STRING"},
                                    "hindi_text": {"type": "STRING"},
                                    "motion_preset": {"type": "STRING", "enum": ["pan_up", "pan_down"]},
                                },
                                "required": ["suggested_panel", "speaker", "hindi_text", "motion_preset"],
                            },
                        },
                    },
                    "required": ["scenes"],
                },
                "temperature": 0.5,
            },
        }

        parsed = None
        # Set OLLAMA_FALLBACK=1 to try the local model after Gemini fails.
        # LLM_PROVIDER=ollama uses only the local model and is fully offline.
        use_ollama = provider_pref == "ollama" or os.environ.get("OLLAMA_FALLBACK", "").lower() in {"1", "true", "yes"}
        max_batch_attempts = get_env_config().max_batch_attempts

        for attempt in range(1, max_batch_attempts + 1):
            # 1. If explicitly requested, use the selected provider first.
            if provider_pref == "openrouter":
                res_or = query_openrouter_api(prompt_text, batch_images_b64)
                if res_or:
                    parsed, active_model_used = res_or
            elif provider_pref == "groq":
                res_gr = query_groq_api(prompt_text, batch_images_b64)
                if res_gr:
                    parsed, active_model_used = res_gr
            elif provider_pref == "openai":
                res_oa = query_openai_api(prompt_text, batch_images_b64)
                if res_oa:
                    parsed, active_model_used = res_oa
            elif provider_pref == "ollama":
                res_ollama = query_ollama_api(prompt_text, batch_images_b64)
                if res_ollama:
                    parsed, active_model_used = res_ollama

            # 2. Try Gemini unless Ollama is the explicitly selected provider.
            if not parsed and key and provider_pref != "ollama":
                res = query_gemini_api(payload, key, timeout=60)
                if res:
                    data, model_used = res
                    active_model_used = model_used
                    try:
                        raw_json = data["candidates"][0]["content"]["parts"][0]["text"]
                        parsed = _extract_json_payload(raw_json)
                    except Exception as e:
                        logger.warning(f"Failed to parse Gemini JSON output: {e}")

            # 3. Seamless failover to OpenRouter Vision (Gemini 2.5 Flash / Qwen2.5-VL-72B / Llama 4)
            if not parsed and provider_pref not in {"openrouter", "ollama"}:
                res_or = query_openrouter_api(prompt_text, batch_images_b64)
                if res_or:
                    parsed, active_model_used = res_or

            # 4. Seamless failover to Groq Free Vision (Llama 4 Scout / Maverick, auto-chunked <= 4 imgs)
            if not parsed and provider_pref not in {"groq", "ollama"}:
                res_gr = query_groq_api(prompt_text, batch_images_b64)
                if res_gr:
                    parsed, active_model_used = res_gr

            # 5. Optional local Ollama fallback if explicitly enabled via OLLAMA_FALLBACK=1
            if not parsed and use_ollama and provider_pref != "ollama":
                res_ollama = query_ollama_api(prompt_text, batch_images_b64)
                if res_ollama:
                    parsed, active_model_used = res_ollama

            # 6. OpenAI remains an opt-in fallback when it is configured.
            if not parsed and provider_pref not in {"openai", "ollama"}:
                res_oa = query_openai_api(prompt_text, batch_images_b64)
                if res_oa:
                    parsed, active_model_used = res_oa

            if parsed:
                break

            if attempt < max_batch_attempts:
                wait_sec = attempt * 15
                logger.warning(
                    f"Batch {b_idx + 1}/{len(batches)} models temporarily busy/rate-limited. "
                    f"Waiting {wait_sec}s for rate limits to reset before attempt {attempt + 1}/{max_batch_attempts}..."
                )
                time.sleep(wait_sec)

        if not parsed:
            raise RuntimeError(
                f"LLM generation failed for Batch {b_idx + 1}/{len(batches)} (Panels: {', '.join(batch)}) "
                f"in Chapter {chapter} (Part {part}). All candidate models failed after {max_batch_attempts} attempts. Stopping execution as requested."
            )

        if isinstance(parsed, list):
            scenes_list = parsed
            parsed_dict = {}
        elif isinstance(parsed, dict):
            scenes_list = parsed.get("scenes", [])
            parsed_dict = parsed
        else:
            scenes_list = []
            parsed_dict = {}

        if is_first_batch and parsed_dict:
            import re
            raw_ep_title = str(parsed_dict.get("title") or episode_title).strip()
            raw_ep_title = re.sub(r"[-–—:\s]*\b(?:Batch|Part)\s*\d+\b", "", raw_ep_title, flags=re.IGNORECASE).strip(" -–—:()")
            episode_title = raw_ep_title or f"{series} - Chapter {chapter}"
            episode_hook = parsed_dict.get("hindi_hook", episode_hook)

        batch_scenes_map = {}
        for sc in scenes_list:
            if isinstance(sc, dict):
                panel_name = sc.get("suggested_panel", "")
                if panel_name in batch:
                    batch_scenes_map[panel_name] = sc
                elif f"{panel_name}.webp" in batch:
                    batch_scenes_map[f"{panel_name}.webp"] = sc
                elif panel_name.replace(".webp", "") in [b.replace(".webp", "") for b in batch]:
                    for b in batch:
                        if b.startswith(panel_name) or panel_name.startswith(b.replace(".webp", "")):
                            batch_scenes_map[b] = sc
                            break

        # Assemble scenes for this batch ensuring 100% panel coverage
        batch_recorded: List[dict] = []
        for p_name in batch:
            if p_name in batch_scenes_map:
                sc = batch_scenes_map[p_name]
            else:
                p_pos = batch.index(p_name)
                if p_pos < len(scenes_list) and isinstance(scenes_list[p_pos], dict):
                    sc = scenes_list[p_pos]
                else:
                    sc = {
                        "speaker": "Narrator",
                        "hindi_text": "भाई, अब यहाँ से story और भी ज्यादा intense और crazy होने वाली है!",
                        "motion_preset": "pan_up",
                    }
                    logger.warning(
                        f"Panel '{p_name}' was not explicitly covered by Gemini in Batch {b_idx + 1}, using context beat."
                    )

            speaker = sc.get("speaker", "Narrator")
            raw_text = sc.get("hindi_text") or sc.get("dialogue") or sc.get("narration") or sc.get("text") or sc.get("line") or ""
            hindi_text = str(raw_text).strip()
            motion = sc.get("motion_preset", "pan_up")

            clean_test = hindi_text.strip(" .?!,;:_-\t\n")
            if not clean_test:
                if speaker and speaker.lower() != "narrator":
                    hindi_text = f"{speaker} एकदम cold reaction के साथ सामने देख रहा था!"
                else:
                    speaker = "Narrator"
                    hindi_text = "पूरे माहौल में अचानक एक deadly tension फैल गई!"
                logger.warning(f"Panel '{p_name}' had silent text from Gemini, adapted to narration: '{hindi_text}'")

            speaker_gender: Optional[str] = None
            try:
                from manhwa_studio.story.character_registry import (
                    CharacterRegistry,
                    NARRATOR_ALIASES,
                    strip_speaker_modifiers,
                )
                if strip_speaker_modifiers(speaker).lower() in NARRATOR_ALIASES:
                    speaker_gender = "narrator"
                else:
                    char_reg = CharacterRegistry(series)
                    prof = char_reg.resolve_or_confirm_character(
                        speaker=speaker,
                        panel_path=image_lookup.get(p_name),
                        dialogue_text=hindi_text,
                        allow_gemini=bool(key),
                    )
                    if prof:
                        tag_m = re.search(r"(\s*[\(\[\-].*)$", speaker)
                        tag_sfx = tag_m.group(1) if tag_m else ""
                        if prof.canonical_name and prof.canonical_name.lower() != strip_speaker_modifiers(speaker).lower():
                            speaker = f"{prof.canonical_name}{tag_sfx}"
                        speaker_gender = prof.gender
            except Exception:
                pass

            scene_item = DialogueSceneItem(
                speaker=speaker,
                speaker_gender=speaker_gender,
                scene_purpose="dialogue",
                hindi_text=hindi_text,
                suggested_panel=p_name,
                motion_preset=motion if motion in ["pan_up", "pan_down"] else "pan_up",
            )
            all_scenes.append(scene_item)
            batch_recorded.append(scene_item.model_dump())

        completed_batches[b_key] = batch_recorded
        if checkpoint_path:
            try:
                ckpt_obj = {
                    "series": series,
                    "chapter": chapter,
                    "part": part,
                    "episode_title": episode_title,
                    "episode_hook": episode_hook,
                    "active_model_used": active_model_used,
                    "completed_batches": completed_batches,
                }
                checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
                checkpoint_path.write_text(json.dumps(ckpt_obj, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as e:
                logger.warning(f"Could not save screenplay checkpoint: {e}")

        time.sleep(get_env_config().batch_delay_sec) # Prevent API rate throttling between consecutive batches

    if not all_scenes:
        raise RuntimeError(f"No scenes were generated by Gemini for Chapter {chapter} (Part {part}). Stopping execution as requested.")

    # Remove temporary checkpoint on successful full completion
    if checkpoint_path and checkpoint_path.exists():
        try:
            checkpoint_path.unlink(missing_ok=True)
        except Exception:
            pass

    logger.info(f"Successfully generated sequential screenplay with {len(all_scenes)} scenes covering all {total_panels} panels using model '{active_model_used}'.")
    return ChapterScreenplay(
        title=episode_title,
        hindi_hook=episode_hook,
        scenes=all_scenes,
        provider=active_model_used,
    )



def modernize_existing_manifest_to_hinglish(project_dir: Path) -> int:
    """
    Rewrites an existing chapter's `scripts/scene_manifest.json` from pure/textbook Hindi
    into Young, Energetic Modern Hinglish (Hindi + natural English words) using Gemini,
    and clears old cached `audio/*.mp3` files so fresh youthful voices are synthesized on render.
    Returns the number of scenes modernized.
    """
    m_file = project_dir / "scripts" / "scene_manifest.json"
    if not m_file.exists():
        raise FileNotFoundError(f"scene_manifest.json not found in {project_dir}")

    data = json.loads(m_file.read_text(encoding="utf-8"))
    scenes = data.get("scenes", [])
    if not scenes:
        return 0

    series = data.get("series", "Manhwa")
    chapter = data.get("chapter", 1)
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        env_file = Path(".env")
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("GEMINI_API_KEY="):
                    key = line.split("=", 1)[1].strip("\"' ")
                    break
    if not key:
        raise ValueError("GEMINI_API_KEY is required to modernize scripts with Gemini.")

    try:
        from manhwa_studio.studio_pro.series_manager import SeriesManager
        prof = SeriesManager().get_or_create_profile(series)
        valid_speakers = list(prof.character_voices.keys())[:24]
    except Exception:
        valid_speakers = []

    speaker_hint = (
        f"Also upgrade generic 'speaker' tags to match these character voices where appropriate: {', '.join(valid_speakers)}."
        if valid_speakers
        else ""
    )

    chunk_size = 25
    updated_count = 0

    for start_i in range(0, len(scenes), chunk_size):
        chunk = scenes[start_i : start_i + chunk_size]
        input_items = [
            {
                "scene_id": sc.get("scene_id"),
                "speaker": sc.get("speaker", "Narrator"),
                "text": sc.get("narration_text") or sc.get("subtitle_text") or "",
            }
            for sc in chunk
        ]

        prompt = (
            f"You are an official Netflix / Crunchyroll Hindi Anime & Manhwa Voice Director.\n"
            f"Series: '{series}', Chapter {chapter}.\n"
            f"Below is a JSON list of scenes. Rewrite every 'text' into CLEAN, CLASSY, DIGNIFIED MODERN HINGLISH (simple everyday Devanagari Hindi mixed naturally with standard English words).\n\n"
            f"RULES:\n"
            f"1. Mix natural, dignified English nouns/terms inside simple Hindi sentences: e.g. 'System', 'Level', 'Power', 'Aura', 'Attack', 'Defense', 'Technique', 'Sword', 'Skill', 'Master', 'Young Master', 'Danger', 'Warning', 'Target', 'Secret', 'Speed', 'Scan', 'Challenge', 'Plan', 'Formula', 'Magic', 'Guard'.\n"
            f"2. Remove difficult textbook/Sanskritized Hindi words (like 'अवलोकन', 'प्रहार', 'मंजर', 'सन्नाटा', 'खामोशी से देखता रहा', 'आंतरिक ऊर्जा', 'चमत्कारी', 'साजिश', 'कदाचित').\n"
            f"3. STRICTLY FORBIDDEN (NO CHAPPRI / TAPORI SLANG!): NEVER use street/tapori/chappri words like 'यार', 'अरे यार', 'भाई', 'अरे भाई', 'अबे', 'बे', 'bro', 'Shit', 'मस्त', 'बवाल', 'कांड', 'फाड़ू', 'ट्रिगर', 'नेक्स्ट लेवल', 'Literally', 'Crazy'.\n"
            f"4. Keep ALL male and female characters sounding dignified, intelligent, and natural—like an official movie or anime dub!\n"
            f"5. Set 'speaker_gender' to 'female' ONLY when a female character (girl, woman, lady, queen, female disciple, female AI) is speaking, and 'male' when a male character or narrator is speaking (ensure Hindi verb gender matches!).\n"
            f"6. {speaker_hint}\n"
            f"7. Return strictly a JSON object with key 'scenes' containing items with 'scene_id', 'speaker', 'speaker_gender' ('male'|'female'), and 'text'.\n\n"
            f"INPUT SCENES:\n{json.dumps(input_items, ensure_ascii=False)}"
        )

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": {
                    "type": "OBJECT",
                    "properties": {
                        "scenes": {
                            "type": "ARRAY",
                            "items": {
                                "type": "OBJECT",
                                "properties": {
                                    "scene_id": {"type": "STRING"},
                                    "speaker": {"type": "STRING"},
                                    "speaker_gender": {"type": "STRING", "enum": ["male", "female"]},
                                    "text": {"type": "STRING"},
                                },
                                "required": ["scene_id", "speaker", "speaker_gender", "text"],
                            },
                        }
                    },
                    "required": ["scenes"],
                },
                "temperature": 0.55,
            },
        }

        parsed = None
        for attempt in range(1, 4):
            res = query_gemini_api(payload, key, timeout=65)
            if not res:
                if attempt == 3:
                    raise RuntimeError(f"Gemini API failed while modernizing scenes {start_i + 1}-{start_i + len(chunk)}")
                continue

            resp_data, _ = res
            raw_json = resp_data["candidates"][0]["content"]["parts"][0]["text"]
            try:
                parsed = json.loads(raw_json)
                break
            except Exception as parse_err:
                import re
                # Fallback regex extraction if LLM produced minor trailing/inner syntax noise
                extracted = []
                pattern = re.compile(
                    r'"scene_id"\s*:\s*"([^"]+)"[^{}]*?"speaker"\s*:\s*"([^"]*)"[^{}]*?"text"\s*:\s*"((?:[^"\\]|\\.)*)"',
                    re.DOTALL,
                )
                for m in pattern.finditer(raw_json):
                    extracted.append({
                        "scene_id": m.group(1),
                        "speaker": m.group(2),
                        "text": m.group(3).replace('\\"', '"'),
                    })
                if extracted:
                    parsed = {"scenes": extracted}
                    logger.info(f"Recovered {len(extracted)} scenes via resilient JSON regex parser.")
                    break
                logger.warning(f"Attempt {attempt}/3 JSON parse warning on scenes {start_i + 1}-{start_i + len(chunk)}: {parse_err}")

        if not parsed:
            logger.warning(f"Skipping chunk {start_i + 1}-{start_i + len(chunk)} after 3 parse attempts.")
            continue

        rewritten_list = parsed.get("scenes", parsed) if isinstance(parsed, dict) else parsed
        lookup = {item.get("scene_id"): item for item in rewritten_list if isinstance(item, dict) and item.get("scene_id")}

        for sc in chunk:
            sid = sc.get("scene_id")
            if sid in lookup:
                new_txt = str(lookup[sid].get("text") or "").strip()
                new_spk = str(lookup[sid].get("speaker") or sc.get("speaker") or "Narrator").strip()
                new_gen = str(lookup[sid].get("speaker_gender") or "").strip().lower()
                if new_txt:
                    sc["narration_text"] = new_txt
                    sc["subtitle_text"] = new_txt
                    sc["speaker"] = new_spk
                    if new_gen in ("male", "female"):
                        sc["speaker_gender"] = new_gen
                    sc["actual_audio_path"] = None
                    sc["actual_audio_duration"] = None
                    updated_count += 1

    data["approved_by_user"] = True
    data["modernized_hinglish"] = True
    tmp_file = m_file.with_suffix(".tmp")
    tmp_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_file.replace(m_file)

    # Clear old cached scene MP3s so the new young energetic voice is synthesized cleanly
    audio_dir = project_dir / "audio"
    if audio_dir.exists():
        for mp3 in audio_dir.glob("*.mp3"):
            try:
                mp3.unlink()
            except Exception:
                pass

    logger.info(f"Modernized {updated_count}/{len(scenes)} scenes to energetic Hinglish in {m_file}")
    return updated_count
