"""Local AI utilities for embeddings, skill extraction support, rewrite helpers, and transformer fallback behavior."""

from __future__ import annotations

import atexit
import gc
import hashlib
import math
import os
import re
from collections import OrderedDict
from typing import Iterable

from app.core.config import settings


# Avoid tokenizer/process helper fan-out on macOS/Python 3.12, which can
# leave semaphore warnings behind during interpreter shutdown.
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("HF_ENABLE_PARALLEL_LOADING", "false")


STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "your", "will", "have", "has", "into",
    "using", "used", "their", "they", "them", "must", "plus", "able", "work", "team", "role",
    "more", "less", "some", "many", "each", "make", "made", "over", "under", "than", "then",
}

SKILL_LABELS = [
    "technical skill",
    "software tool",
    "framework or library",
    "programming language",
    "cloud platform",
    "data skill",
    "soft skill",
    "not a skill",
]

SKILL_CATEGORY_BY_LABEL = {
    "technical skill": "Technical",
    "software tool": "Tooling",
    "framework or library": "Frameworks",
    "programming language": "Programming",
    "cloud platform": "Cloud",
    "data skill": "Data",
    "soft skill": "Professional",
    "not a skill": "",
}

_SENTENCE_MODEL = None
_ZERO_SHOT_PIPELINE = None
_REWRITE_PIPELINE = None
_TORCH_RUNTIME_CONFIGURED = False
_EMBED_CACHE: "OrderedDict[str, list[float]]" = OrderedDict()
_CLASSIFY_CACHE: "OrderedDict[str, tuple[bool, str]]" = OrderedDict()
_CACHE_LIMIT = 2048
_SENTENCE_MODELS: dict[str, object] = {}
_ZERO_SHOT_PIPELINES: dict[str, object] = {}
_REWRITE_PIPELINES: dict[str, object] = {}

DEFAULT_INFERENCE_MODE = "auto"
AVAILABLE_INFERENCE_MODES = ["auto", "local-transformer", "local-fallback"]


def normalize_ai_preferences(preferences: dict | None = None) -> dict[str, str]:
    raw = preferences or {}
    mode = str(raw.get("inference_mode") or DEFAULT_INFERENCE_MODE).strip().lower()
    if mode not in AVAILABLE_INFERENCE_MODES:
        mode = DEFAULT_INFERENCE_MODE

    embedding_model = str(raw.get("embedding_model") or settings.local_embedding_model).strip()
    if embedding_model not in settings.local_embedding_model_options_list:
        embedding_model = settings.local_embedding_model

    zero_shot_model = str(raw.get("zero_shot_model") or settings.local_zero_shot_model).strip()
    if zero_shot_model not in settings.local_zero_shot_model_options_list:
        zero_shot_model = settings.local_zero_shot_model

    rewrite_model = str(raw.get("rewrite_model") or settings.local_rewrite_model).strip()
    if rewrite_model not in settings.local_rewrite_model_options_list:
        rewrite_model = settings.local_rewrite_model

    return {
        "inference_mode": mode,
        "embedding_model": embedding_model,
        "zero_shot_model": zero_shot_model,
        "rewrite_model": rewrite_model,
    }


def _cache_get(cache: OrderedDict, key: str):
    if key not in cache:
        return None
    value = cache.pop(key)
    cache[key] = value
    return value


def _cache_put(cache: OrderedDict, key: str, value) -> None:
    if key in cache:
        cache.pop(key)
    cache[key] = value
    while len(cache) > _CACHE_LIMIT:
        cache.popitem(last=False)


def _tokenize(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9+.#-]{2,}", (text or "").lower())
    return [word for word in words if word not in STOPWORDS]


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vec))
    if norm <= 0:
        return vec
    return [value / norm for value in vec]


def hashed_embedding(text: str, dims: int = 128) -> list[float]:
    vec = [0.0] * dims
    for token in _tokenize(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        slot = int.from_bytes(digest[:4], "big") % dims
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        weight = 1.0 + min(len(token), 12) / 12.0
        vec[slot] += sign * weight
    return _normalize(vec)


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return round(sum(a * b for a, b in zip(left, right, strict=False)), 4)


def _load_sentence_transformer(model_name: str | None = None):
    chosen_model = str(model_name or settings.local_embedding_model).strip() or settings.local_embedding_model
    if chosen_model in _SENTENCE_MODELS:
        return _SENTENCE_MODELS[chosen_model]
    try:
        from sentence_transformers import SentenceTransformer

        _configure_torch_runtime()
        _SENTENCE_MODELS[chosen_model] = SentenceTransformer(chosen_model)
        return _SENTENCE_MODELS[chosen_model]
    except Exception:
        return None


def _load_zero_shot_pipeline(model_name: str | None = None):
    chosen_model = str(model_name or settings.local_zero_shot_model).strip() or settings.local_zero_shot_model
    if chosen_model in _ZERO_SHOT_PIPELINES:
        return _ZERO_SHOT_PIPELINES[chosen_model]
    try:
        from transformers import pipeline

        _configure_torch_runtime()
        _ZERO_SHOT_PIPELINES[chosen_model] = pipeline(
            "zero-shot-classification",
            model=chosen_model,
            device=settings.local_model_device,
            framework="pt",
        )
        return _ZERO_SHOT_PIPELINES[chosen_model]
    except Exception:
        return None


def _load_rewrite_pipeline(model_name: str | None = None):
    chosen_model = str(model_name or settings.local_rewrite_model).strip() or settings.local_rewrite_model
    if chosen_model in _REWRITE_PIPELINES:
        return _REWRITE_PIPELINES[chosen_model]
    try:
        from transformers import pipeline

        _configure_torch_runtime()
        _REWRITE_PIPELINES[chosen_model] = pipeline(
            "text2text-generation",
            model=chosen_model,
            device=settings.local_model_device,
            framework="pt",
        )
        return _REWRITE_PIPELINES[chosen_model]
    except Exception:
        return None


def _configure_torch_runtime() -> None:
    global _TORCH_RUNTIME_CONFIGURED
    if _TORCH_RUNTIME_CONFIGURED:
        return
    try:
        import torch

        torch.set_num_threads(1)
        if hasattr(torch, "set_num_interop_threads"):
            torch.set_num_interop_threads(1)
    except Exception:
        pass
    _TORCH_RUNTIME_CONFIGURED = True


def release_local_models() -> None:
    global _SENTENCE_MODEL, _ZERO_SHOT_PIPELINE, _REWRITE_PIPELINE, _EMBED_CACHE, _CLASSIFY_CACHE, _SENTENCE_MODELS, _ZERO_SHOT_PIPELINES, _REWRITE_PIPELINES

    for obj in list(_SENTENCE_MODELS.values()) + list(_ZERO_SHOT_PIPELINES.values()) + list(_REWRITE_PIPELINES.values()) + [_SENTENCE_MODEL, _ZERO_SHOT_PIPELINE, _REWRITE_PIPELINE]:
        if obj is None:
            continue
        model = getattr(obj, "model", obj)
        try:
            if hasattr(model, "cpu"):
                model.cpu()
        except Exception:
            pass

    _SENTENCE_MODEL = None
    _ZERO_SHOT_PIPELINE = None
    _REWRITE_PIPELINE = None
    _SENTENCE_MODELS.clear()
    _ZERO_SHOT_PIPELINES.clear()
    _REWRITE_PIPELINES.clear()
    _EMBED_CACHE.clear()
    _CLASSIFY_CACHE.clear()
    gc.collect()


atexit.register(release_local_models)


def get_inference_status(preferences: dict | None = None) -> dict[str, str]:
    prefs = normalize_ai_preferences(preferences)
    force_fallback = prefs["inference_mode"] == "local-fallback"
    embed_model = None if force_fallback else _load_sentence_transformer(prefs["embedding_model"])
    zero_shot = None if force_fallback else _load_zero_shot_pipeline(prefs["zero_shot_model"])
    rewrite_model = None if force_fallback else _load_rewrite_pipeline(prefs["rewrite_model"])
    embeddings_provider = "local-transformer" if embed_model is not None else "local-hash"
    rewrite_provider = "local-llm" if rewrite_model is not None else "local-rule"
    return {
        "provider_mode": "Local Transformer" if embed_model is not None or zero_shot is not None else "Local Fallback",
        "embeddings_provider": embeddings_provider,
        "rewrite_provider": rewrite_provider,
        "embedding_model": prefs["embedding_model"] if embed_model is not None else "hashed-embedding-v1",
        "rewrite_model": prefs["rewrite_model"] if rewrite_model is not None else "resume-rule-rewriter-v1",
    }


async def warm_local_models() -> dict[str, str]:
    prefs = normalize_ai_preferences()
    status = get_inference_status(prefs)
    # Touch both paths so the first real request does not pay model init cost.
    await embed_texts(["python fastapi mongodb", "machine learning project experience"], preferences=prefs)
    await extract_skill_candidates("Python, FastAPI, MongoDB, machine learning, leadership", max_candidates=5, preferences=prefs)
    await rewrite_resume_bullets("python fastapi ml dashboards", ["Built analytics APIs for internal users."], focus="balanced")
    return get_inference_status(prefs) if status else status


async def embed_texts(texts: Iterable[str], preferences: dict | None = None) -> tuple[list[list[float]], str]:
    cleaned = [str(text or "").strip() for text in texts]
    if not cleaned:
        return [], "local-hash"

    prefs = normalize_ai_preferences(preferences)
    if prefs["inference_mode"] == "local-fallback":
        return [hashed_embedding(text) for text in cleaned], "local-hash"

    model_name = prefs["embedding_model"]
    model = _load_sentence_transformer(model_name)
    if model is not None:
        try:
            results: list[list[float] | None] = [None] * len(cleaned)
            missing_indices: list[int] = []
            missing_texts: list[str] = []
            for index, text in enumerate(cleaned):
                cache_key = f"{model_name}|{text}"
                cached = _cache_get(_EMBED_CACHE, cache_key)
                if cached is not None:
                    results[index] = cached
                else:
                    missing_indices.append(index)
                    missing_texts.append(text)

            if missing_texts:
                vectors = model.encode(missing_texts, normalize_embeddings=True, batch_size=min(32, len(missing_texts)))
                for index, row in zip(missing_indices, vectors, strict=False):
                    vector = list(map(float, row))
                    results[index] = vector
                    _cache_put(_EMBED_CACHE, f"{model_name}|{cleaned[index]}", vector)

            return [list(row or hashed_embedding(cleaned[index])) for index, row in enumerate(results)], "local-transformer"
        except Exception:
            pass

    return [hashed_embedding(text) for text in cleaned], "local-hash"


def _rewrite_locally(job_text: str, bullets: list[str], focus: str) -> list[str]:
    keywords = []
    seen = set()
    for token in _tokenize(job_text):
        if token in seen:
            continue
        seen.add(token)
        keywords.append(token)
        if len(keywords) >= 6:
            break

    rewritten: list[str] = []
    for bullet in bullets:
        base = re.sub(r"^\s*[-*]\s*", "", str(bullet or "").strip())
        if not base:
            continue
        sentence = base[0].upper() + base[1:] if len(base) > 1 else base.upper()
        if not re.search(r"\b(led|built|designed|implemented|delivered|improved|developed|launched|automated|optimized)\b", sentence, re.IGNORECASE):
            sentence = f"Delivered {sentence[0].lower() + sentence[1:]}" if len(sentence) > 1 else f"Delivered {sentence.lower()}"
        if focus == "ats" and keywords:
            sentence = f"{sentence} Relevant keywords: {', '.join(keywords[:2])}."
        elif focus == "impact":
            sentence = f"{sentence} Highlighted measurable impact and ownership."
        else:
            if keywords:
                sentence = f"{sentence} Aligned with {keywords[0]} requirements."
        rewritten.append(f"- {sentence}")
    return rewritten


def _rewrite_prompt(job_text: str, bullet: str, focus: str) -> str:
    trimmed_job = " ".join(str(job_text or "").split())[:900]
    trimmed_bullet = re.sub(r"^\s*[-*]\s*", "", str(bullet or "").strip())
    focus_instruction = {
        "ats": "Keep ATS-friendly keywords from the job posting when they are truthful.",
        "impact": "Emphasize measurable impact, ownership, and outcomes.",
        "balanced": "Balance clarity, relevance, and measurable impact.",
    }.get(focus, "Balance clarity, relevance, and measurable impact.")
    return (
        "Rewrite the resume bullet to be concise, truthful, and professional. "
        "Do not invent experience. Keep it one bullet line. "
        f"{focus_instruction}\n"
        f"Job posting: {trimmed_job}\n"
        f"Original bullet: {trimmed_bullet}\n"
        "Rewritten bullet:"
    )


def _rewrite_with_local_llm(job_text: str, bullets: list[str], focus: str, model_name: str | None = None) -> tuple[list[str], str] | None:
    pipeline = _load_rewrite_pipeline(model_name)
    if pipeline is None:
        return None

    rewritten: list[str] = []
    for bullet in bullets:
        prompt = _rewrite_prompt(job_text, bullet, focus)
        try:
            outputs = pipeline(
                prompt,
                max_new_tokens=72,
                do_sample=False,
                num_beams=4,
                truncation=True,
            )
        except Exception:
            return None
        if not outputs:
            continue
        text = str(outputs[0].get("generated_text") or "").strip()
        if text.lower().startswith(prompt.lower()):
            text = text[len(prompt):].strip()
        text = re.sub(r"^\s*[-*]\s*", "", text).strip()
        if not text:
            continue
        if not text.endswith("."):
            text += "."
        rewritten.append(f"- {text}")

    if not rewritten:
        return None
    return rewritten, "local-llm"


async def rewrite_resume_bullets(job_text: str, bullets: list[str], focus: str = "balanced", preferences: dict | None = None) -> tuple[list[str], str]:
    cleaned = [re.sub(r"^\s*[-*]\s*", "", str(bullet or "").strip()) for bullet in bullets if str(bullet or "").strip()]
    if not cleaned:
        return [], "local-rule"
    prefs = normalize_ai_preferences(preferences)
    if prefs["inference_mode"] == "local-fallback":
        return _rewrite_locally(job_text, cleaned, focus), "local-rule"
    rewritten = _rewrite_with_local_llm(job_text, cleaned, focus, prefs["rewrite_model"])
    if rewritten is not None:
        return rewritten
    return _rewrite_locally(job_text, cleaned, focus), "local-rule"


def _extract_candidates_locally(text: str, max_candidates: int = 40) -> list[dict]:
    lowered = str(text or "")
    patterns = [
        r"(?:experience with|experienced in|proficient in|knowledge of|using|built with|worked with|familiar with|expertise in)\s+([A-Za-z0-9+.#/\- ]{2,80})",
        r"(?:skills|technologies|tools|frameworks|platforms)\s*:\s*([A-Za-z0-9+.#/\-, ]{2,160})",
    ]

    phrases: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, lowered, re.IGNORECASE):
            block = match.group(1)
            for part in re.split(r",|/| and |\bor\b", block):
                phrase = part.strip(" .;:()[]{}")
                if 2 <= len(phrase) <= 50:
                    phrases.append(phrase)

    lines = [line.strip(" -*•\t") for line in lowered.splitlines() if line.strip()]
    for line in lines:
        if len(line) < 8:
            continue
        for part in re.split(r",|;|/|\band\b", line):
            phrase = part.strip(" .;:()[]{}")
            if 2 <= len(phrase) <= 50:
                phrases.append(phrase)

    tech_tokens = re.findall(r"\b[A-Za-z][A-Za-z0-9+.#-]{1,24}\b", lowered)
    for token in tech_tokens:
        if any(ch.isupper() for ch in token) or any(ch in token for ch in "+#."):
            phrases.append(token)

    out: list[dict] = []
    seen: set[str] = set()
    for phrase in phrases:
        normalized = re.sub(r"\s+", " ", phrase).strip()
        key = normalized.lower()
        if key in seen or key in STOPWORDS or len(key) < 2:
            continue
        if re.fullmatch(r"\d+(\.\d+)?", key):
            continue
        if len(key.split()) > 5:
            continue
        seen.add(key)
        out.append({"name": normalized, "category": ""})
        if len(out) >= max_candidates:
            break
    return out


def _classify_candidate_locally(name: str) -> tuple[bool, str]:
    low = str(name or "").strip().lower()
    if not low:
        return False, ""
    bad_prefixes = ("responsible for", "ability to", "ability in", "candidate should", "must be able")
    if any(low.startswith(prefix) for prefix in bad_prefixes):
        return False, ""
    if len(low.split()) == 1 and len(low) < 2:
        return False, ""
    if re.search(r"\b(salary|benefits|equal opportunity|applicants|company)\b", low):
        return False, ""
    return True, "General"


async def extract_skill_candidates(text: str, max_candidates: int = 25, preferences: dict | None = None) -> tuple[list[dict], str]:
    cleaned = str(text or "").strip()
    if not cleaned:
        return [], "local-rule"

    prefs = normalize_ai_preferences(preferences)
    local_candidates = _extract_candidates_locally(cleaned, max_candidates=max_candidates * 2)
    classifier = None if prefs["inference_mode"] == "local-fallback" else _load_zero_shot_pipeline(prefs["zero_shot_model"])
    if classifier is None:
        filtered: list[dict] = []
        for candidate in local_candidates:
            ok, category = _classify_candidate_locally(candidate.get("name", ""))
            if not ok:
                continue
            filtered.append({"name": candidate["name"], "category": category})
            if len(filtered) >= max_candidates:
                break
        return filtered, "local-rule"

    filtered: list[dict] = []
    uncached_names: list[str] = []
    for candidate in local_candidates:
        name = str(candidate.get("name") or "").strip()
        if not name:
            continue
        cache_key = f"{prefs['zero_shot_model']}|{name.casefold()}"
        cached = _cache_get(_CLASSIFY_CACHE, cache_key)
        if cached is not None:
            ok, category = cached
            if ok:
                filtered.append({"name": name, "category": category})
            if len(filtered) >= max_candidates:
                break
            continue
        uncached_names.append(name)

    for start in range(0, len(uncached_names), 16):
        batch = uncached_names[start : start + 16]
        try:
            batch_result = classifier(batch, SKILL_LABELS, multi_label=False, batch_size=min(8, len(batch)))
            if isinstance(batch_result, dict):
                batch_result = [batch_result]
        except Exception:
            batch_result = [None] * len(batch)

        for name, result in zip(batch, batch_result, strict=False):
            ok = False
            category = ""
            if isinstance(result, dict):
                labels = result.get("labels") or []
                scores = result.get("scores") or []
                if labels and scores:
                    top_label = str(labels[0])
                    top_score = float(scores[0])
                    if top_label != "not a skill" and top_score >= 0.25:
                        ok = True
                        category = SKILL_CATEGORY_BY_LABEL.get(top_label, "General")
            if not ok:
                ok, category = _classify_candidate_locally(name)
            _cache_put(_CLASSIFY_CACHE, f"{prefs['zero_shot_model']}|{name.casefold()}", (ok, category))
            if ok:
                filtered.append({"name": name, "category": category})
            if len(filtered) >= max_candidates:
                break
        if len(filtered) >= max_candidates:
            break

    deduped: list[dict] = []
    seen: set[str] = set()
    for candidate in filtered:
        key = str(candidate.get("name") or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped[:max_candidates], "local-transformer" if deduped else "local-rule"
