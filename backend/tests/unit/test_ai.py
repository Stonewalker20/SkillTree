"""Unit tests for app/utils/ai.py, mocking every model load and pipeline call.

Per the "mock everything" testing approach, these tests never load a real
sentence-transformers/transformers model. Loader functions are monkeypatched
directly, or have their underlying lazy imports replaced via sys.modules, so
the tests run instantly and deterministically regardless of what ML packages
are actually installed.
"""

from __future__ import annotations

import sys

import pytest

from app.core.config import settings
from app.utils import ai


@pytest.fixture(autouse=True)
def _reset_ai_module_state(monkeypatch):
    """Every model cache / global flag in ai.py is module-level mutable state.

    Without resetting it before each test, whichever test runs first to
    populate _SENTENCE_MODELS (etc.) would leak its fake model into every
    later test that requests the same model name.
    """
    monkeypatch.setattr(ai, "_SENTENCE_MODELS", {})
    monkeypatch.setattr(ai, "_ZERO_SHOT_PIPELINES", {})
    monkeypatch.setattr(ai, "_REWRITE_PIPELINES", {})
    monkeypatch.setattr(ai, "_EMBED_CACHE", ai.OrderedDict())
    monkeypatch.setattr(ai, "_CLASSIFY_CACHE", ai.OrderedDict())
    monkeypatch.setattr(ai, "_TORCH_RUNTIME_CONFIGURED", False)
    yield


# --------------------------------------------------------------------------
# normalize_ai_preferences
# --------------------------------------------------------------------------


def test_normalize_ai_preferences_defaults_when_none():
    prefs = ai.normalize_ai_preferences(None)
    assert prefs == {
        "inference_mode": "auto",
        "embedding_model": settings.local_embedding_model,
        "zero_shot_model": settings.local_zero_shot_model,
        "rewrite_model": settings.local_rewrite_model,
    }


def test_normalize_ai_preferences_invalid_mode_falls_back_to_auto():
    prefs = ai.normalize_ai_preferences({"inference_mode": "not-a-real-mode"})
    assert prefs["inference_mode"] == "auto"


def test_normalize_ai_preferences_accepts_known_mode_case_insensitively():
    prefs = ai.normalize_ai_preferences({"inference_mode": "LOCAL-FALLBACK"})
    assert prefs["inference_mode"] == "local-fallback"


def test_normalize_ai_preferences_unknown_embedding_model_falls_back_to_default():
    prefs = ai.normalize_ai_preferences({"embedding_model": "some/unlisted-model"})
    assert prefs["embedding_model"] == settings.local_embedding_model


def test_normalize_ai_preferences_accepts_valid_alternate_models():
    prefs = ai.normalize_ai_preferences(
        {
            "embedding_model": "sentence-transformers/all-MiniLM-L12-v2",
            "zero_shot_model": "facebook/bart-large-mnli",
            "rewrite_model": "google/flan-t5-base",
        }
    )
    assert prefs["embedding_model"] == "sentence-transformers/all-MiniLM-L12-v2"
    assert prefs["zero_shot_model"] == "facebook/bart-large-mnli"
    assert prefs["rewrite_model"] == "google/flan-t5-base"


# --------------------------------------------------------------------------
# _cache_get / _cache_put (LRU cache helpers)
# --------------------------------------------------------------------------


def test_cache_put_then_get_round_trips_value():
    cache = ai.OrderedDict()
    ai._cache_put(cache, "key1", [1.0, 2.0])
    assert ai._cache_get(cache, "key1") == [1.0, 2.0]


def test_cache_get_returns_none_for_missing_key():
    cache = ai.OrderedDict()
    assert ai._cache_get(cache, "missing") is None


def test_cache_get_moves_key_to_most_recently_used_end():
    cache = ai.OrderedDict()
    ai._cache_put(cache, "a", 1)
    ai._cache_put(cache, "b", 2)
    ai._cache_get(cache, "a")
    assert list(cache.keys()) == ["b", "a"]


def test_cache_put_evicts_oldest_when_over_limit(monkeypatch):
    monkeypatch.setattr(ai, "_CACHE_LIMIT", 2)
    cache = ai.OrderedDict()
    ai._cache_put(cache, "a", 1)
    ai._cache_put(cache, "b", 2)
    ai._cache_put(cache, "c", 3)
    assert list(cache.keys()) == ["b", "c"]


def test_cache_put_overwriting_existing_key_refreshes_position():
    cache = ai.OrderedDict()
    ai._cache_put(cache, "a", 1)
    ai._cache_put(cache, "b", 2)
    ai._cache_put(cache, "a", 99)
    assert list(cache.keys()) == ["b", "a"]
    assert cache["a"] == 99


# --------------------------------------------------------------------------
# _tokenize / _normalize / hashed_embedding / cosine_similarity
# --------------------------------------------------------------------------


def test_tokenize_lowercases_and_strips_stopwords():
    tokens = ai._tokenize("Using Python AND FastAPI for the project")
    assert "using" not in tokens
    assert "for" not in tokens
    assert "the" not in tokens
    assert "python" in tokens
    assert "fastapi" in tokens


def test_tokenize_handles_none_and_empty_string():
    assert ai._tokenize(None) == []
    assert ai._tokenize("") == []


def test_tokenize_drops_short_tokens_below_three_chars():
    # The pattern requires at least 3 chars total ([A-Za-z] + 2 more).
    tokens = ai._tokenize("go ml ai python")
    assert "python" in tokens
    assert "go" not in tokens
    assert "ml" not in tokens


def test_normalize_scales_vector_to_unit_length():
    result = ai._normalize([3.0, 4.0])
    assert result == pytest.approx([0.6, 0.8])


def test_normalize_returns_input_unchanged_for_zero_vector():
    assert ai._normalize([0.0, 0.0]) == [0.0, 0.0]


def test_hashed_embedding_is_deterministic_for_same_text():
    first = ai.hashed_embedding("python fastapi mongodb")
    second = ai.hashed_embedding("python fastapi mongodb")
    assert first == second


def test_hashed_embedding_differs_for_different_text():
    first = ai.hashed_embedding("python")
    second = ai.hashed_embedding("javascript")
    assert first != second


def test_hashed_embedding_respects_requested_dims():
    vec = ai.hashed_embedding("python developer", dims=32)
    assert len(vec) == 32


def test_hashed_embedding_blank_text_returns_zero_vector():
    vec = ai.hashed_embedding("", dims=16)
    assert vec == [0.0] * 16


def test_cosine_similarity_identical_vectors_is_one():
    vec = ai._normalize([1.0, 2.0, 3.0])
    assert ai.cosine_similarity(vec, vec) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors_is_zero():
    assert ai.cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_cosine_similarity_mismatched_lengths_returns_zero():
    assert ai.cosine_similarity([1.0, 2.0], [1.0]) == 0.0


def test_cosine_similarity_empty_vectors_returns_zero():
    assert ai.cosine_similarity([], []) == 0.0
    assert ai.cosine_similarity(None, [1.0]) == 0.0


# --------------------------------------------------------------------------
# _load_sentence_transformer / _load_zero_shot_pipeline / _load_rewrite_pipeline
#
# These lazily `import` optional ML packages inside the function body. Rather
# than requiring the real packages, we inject fake modules into sys.modules
# for the duration of each test via monkeypatch.setitem (which restores the
# previous entry automatically afterward).
# --------------------------------------------------------------------------


class _FakeSentenceTransformer:
    instances = []

    def __init__(self, model_name):
        self.model_name = model_name
        _FakeSentenceTransformer.instances.append(self)


def test_load_sentence_transformer_returns_instance_and_caches_it(monkeypatch):
    _FakeSentenceTransformer.instances = []
    fake_module = type(sys)("sentence_transformers")
    fake_module.SentenceTransformer = _FakeSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

    result = ai._load_sentence_transformer("fake-model")

    assert isinstance(result, _FakeSentenceTransformer)
    assert result.model_name == "fake-model"
    assert ai._SENTENCE_MODELS["fake-model"] is result


def test_load_sentence_transformer_uses_cache_without_reconstructing(monkeypatch):
    sentinel = object()
    ai._SENTENCE_MODELS["cached-model"] = sentinel

    fake_module = type(sys)("sentence_transformers")

    def boom(_model_name):
        raise AssertionError("should not reconstruct a cached model")

    fake_module.SentenceTransformer = boom
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

    assert ai._load_sentence_transformer("cached-model") is sentinel


def test_load_sentence_transformer_defaults_to_settings_model_when_blank(monkeypatch):
    fake_module = type(sys)("sentence_transformers")
    fake_module.SentenceTransformer = _FakeSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

    ai._load_sentence_transformer("   ")

    assert settings.local_embedding_model in ai._SENTENCE_MODELS


def test_load_sentence_transformer_returns_none_when_package_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    assert ai._load_sentence_transformer("any-model") is None


def test_load_sentence_transformer_returns_none_when_constructor_raises(monkeypatch):
    fake_module = type(sys)("sentence_transformers")

    def raising_ctor(_model_name):
        raise RuntimeError("model download failed")

    fake_module.SentenceTransformer = raising_ctor
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

    assert ai._load_sentence_transformer("bad-model") is None


def test_load_zero_shot_pipeline_returns_instance_and_caches_it(monkeypatch):
    calls = []

    def fake_pipeline(task, model, device, framework):
        calls.append({"task": task, "model": model, "device": device, "framework": framework})
        return f"pipeline-for-{model}"

    fake_module = type(sys)("transformers")
    fake_module.pipeline = fake_pipeline
    monkeypatch.setitem(sys.modules, "transformers", fake_module)

    result = ai._load_zero_shot_pipeline("fake-zero-shot-model")

    assert result == "pipeline-for-fake-zero-shot-model"
    assert ai._ZERO_SHOT_PIPELINES["fake-zero-shot-model"] == result
    assert calls[0]["task"] == "zero-shot-classification"


def test_load_zero_shot_pipeline_returns_none_on_exception(monkeypatch):
    fake_module = type(sys)("transformers")

    def raising_pipeline(*_args, **_kwargs):
        raise RuntimeError("boom")

    fake_module.pipeline = raising_pipeline
    monkeypatch.setitem(sys.modules, "transformers", fake_module)

    assert ai._load_zero_shot_pipeline("any-model") is None


def test_load_rewrite_pipeline_returns_instance_and_caches_it(monkeypatch):
    calls = []

    def fake_pipeline(task, model, device, framework):
        calls.append(task)
        return f"rewrite-pipeline-for-{model}"

    fake_module = type(sys)("transformers")
    fake_module.pipeline = fake_pipeline
    monkeypatch.setitem(sys.modules, "transformers", fake_module)

    result = ai._load_rewrite_pipeline("fake-rewrite-model")

    assert result == "rewrite-pipeline-for-fake-rewrite-model"
    assert calls[0] == "text2text-generation"
    assert ai._REWRITE_PIPELINES["fake-rewrite-model"] is result


def test_load_rewrite_pipeline_returns_none_when_package_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "transformers", None)
    assert ai._load_rewrite_pipeline("any-model") is None


# --------------------------------------------------------------------------
# _configure_torch_runtime
# --------------------------------------------------------------------------


def test_configure_torch_runtime_calls_torch_setup_once(monkeypatch):
    calls = {"threads": 0, "interop": 0}

    fake_torch = type(sys)("torch")
    fake_torch.set_num_threads = lambda _n: calls.__setitem__("threads", calls["threads"] + 1)
    fake_torch.set_num_interop_threads = lambda _n: calls.__setitem__("interop", calls["interop"] + 1)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    ai._configure_torch_runtime()
    ai._configure_torch_runtime()

    assert calls["threads"] == 1
    assert calls["interop"] == 1
    assert ai._TORCH_RUNTIME_CONFIGURED is True


def test_configure_torch_runtime_tolerates_missing_torch(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", None)
    ai._configure_torch_runtime()
    assert ai._TORCH_RUNTIME_CONFIGURED is True


# --------------------------------------------------------------------------
# release_local_models
# --------------------------------------------------------------------------


def test_release_local_models_clears_caches_and_cpus_models():
    cpu_calls = []

    class FakeModel:
        def cpu(self):
            cpu_calls.append(self)

    ai._SENTENCE_MODELS["m1"] = FakeModel()
    ai._ZERO_SHOT_PIPELINES["m2"] = FakeModel()
    ai._EMBED_CACHE["k"] = [1.0]
    ai._CLASSIFY_CACHE["k"] = (True, "General")

    ai.release_local_models()

    assert len(cpu_calls) == 2
    assert ai._SENTENCE_MODELS == {}
    assert ai._ZERO_SHOT_PIPELINES == {}
    assert ai._EMBED_CACHE == {}
    assert ai._CLASSIFY_CACHE == {}


def test_release_local_models_tolerates_objects_without_cpu_method():
    ai._SENTENCE_MODELS["m1"] = object()
    ai.release_local_models()
    assert ai._SENTENCE_MODELS == {}


def test_release_local_models_tolerates_cpu_raising():
    class BrokenModel:
        def cpu(self):
            raise RuntimeError("cannot move to cpu")

    ai._SENTENCE_MODELS["m1"] = BrokenModel()
    ai.release_local_models()
    assert ai._SENTENCE_MODELS == {}


# --------------------------------------------------------------------------
# get_inference_status
# --------------------------------------------------------------------------


def test_get_inference_status_local_fallback_mode_never_loads_models(monkeypatch):
    def fail(*_a, **_k):
        raise AssertionError("loader should not be called when mode is local-fallback")

    monkeypatch.setattr(ai, "_load_sentence_transformer", fail)
    monkeypatch.setattr(ai, "_load_zero_shot_pipeline", fail)
    monkeypatch.setattr(ai, "_load_rewrite_pipeline", fail)

    status = ai.get_inference_status({"inference_mode": "local-fallback"})

    assert status["provider_mode"] == "Local Fallback"
    assert status["embeddings_provider"] == "local-hash"
    assert status["rewrite_provider"] == "local-rule"
    assert status["embedding_model"] == "hashed-embedding-v1"
    assert status["rewrite_model"] == "resume-rule-rewriter-v1"


def test_get_inference_status_reports_transformer_provider_when_models_load(monkeypatch):
    monkeypatch.setattr(ai, "_load_sentence_transformer", lambda _m: object())
    monkeypatch.setattr(ai, "_load_zero_shot_pipeline", lambda _m: object())
    monkeypatch.setattr(ai, "_load_rewrite_pipeline", lambda _m: object())

    status = ai.get_inference_status({"inference_mode": "auto"})

    assert status["provider_mode"] == "Local Transformer"
    assert status["embeddings_provider"] == "local-transformer"
    assert status["rewrite_provider"] == "local-llm"
    assert status["embedding_model"] == settings.local_embedding_model
    assert status["rewrite_model"] == settings.local_rewrite_model


def test_get_inference_status_falls_back_when_loaders_return_none(monkeypatch):
    monkeypatch.setattr(ai, "_load_sentence_transformer", lambda _m: None)
    monkeypatch.setattr(ai, "_load_zero_shot_pipeline", lambda _m: None)
    monkeypatch.setattr(ai, "_load_rewrite_pipeline", lambda _m: None)

    status = ai.get_inference_status({"inference_mode": "auto"})

    assert status["provider_mode"] == "Local Fallback"
    assert status["embeddings_provider"] == "local-hash"
    assert status["rewrite_provider"] == "local-rule"


# --------------------------------------------------------------------------
# warm_local_models
# --------------------------------------------------------------------------


async def test_warm_local_models_touches_embedding_extraction_and_rewrite_paths(monkeypatch):
    calls = []

    async def fake_embed_texts(_texts, preferences=None):
        calls.append("embed")
        return [], "local-hash"

    async def fake_extract(_text, max_candidates=5, preferences=None):
        calls.append("extract")
        return [], "local-rule"

    async def fake_rewrite(_job_text, _bullets, focus="balanced"):
        calls.append("rewrite")
        return [], "local-rule"

    monkeypatch.setattr(ai, "embed_texts", fake_embed_texts)
    monkeypatch.setattr(ai, "extract_skill_candidates", fake_extract)
    monkeypatch.setattr(ai, "rewrite_resume_bullets", fake_rewrite)

    result = await ai.warm_local_models()

    assert calls == ["embed", "extract", "rewrite"]
    assert result["provider_mode"] in {"Local Transformer", "Local Fallback"}


# --------------------------------------------------------------------------
# embed_texts
# --------------------------------------------------------------------------


async def test_embed_texts_empty_input_returns_empty_list():
    result, provider = await ai.embed_texts([])
    assert result == []
    assert provider == "local-hash"


async def test_embed_texts_local_fallback_mode_uses_hashed_embedding(monkeypatch):
    def fail(*_a, **_k):
        raise AssertionError("should not load a transformer model in local-fallback mode")

    monkeypatch.setattr(ai, "_load_sentence_transformer", fail)

    vectors, provider = await ai.embed_texts(["python developer"], preferences={"inference_mode": "local-fallback"})

    assert provider == "local-hash"
    assert vectors == [ai.hashed_embedding("python developer")]


async def test_embed_texts_uses_transformer_model_when_available(monkeypatch):
    class FakeModel:
        def __init__(self):
            self.encode_calls = []

        def encode(self, texts, normalize_embeddings, batch_size):
            self.encode_calls.append(list(texts))
            return [[0.1, 0.2] for _ in texts]

    fake_model = FakeModel()
    monkeypatch.setattr(ai, "_load_sentence_transformer", lambda _m: fake_model)

    vectors, provider = await ai.embed_texts(["alpha", "beta"])

    assert provider == "local-transformer"
    assert vectors == [[0.1, 0.2], [0.1, 0.2]]
    assert fake_model.encode_calls == [["alpha", "beta"]]


async def test_embed_texts_skips_already_cached_text(monkeypatch):
    class FakeModel:
        def __init__(self):
            self.encode_calls = []

        def encode(self, texts, normalize_embeddings, batch_size):
            self.encode_calls.append(list(texts))
            return [[0.9, 0.9] for _ in texts]

    fake_model = FakeModel()
    monkeypatch.setattr(ai, "_load_sentence_transformer", lambda _m: fake_model)
    cache_key = f"{settings.local_embedding_model}|cached text"
    ai._EMBED_CACHE[cache_key] = [0.5, 0.5]

    vectors, provider = await ai.embed_texts(["cached text", "new text"])

    assert provider == "local-transformer"
    assert fake_model.encode_calls == [["new text"]]
    assert vectors[0] == [0.5, 0.5]
    assert vectors[1] == [0.9, 0.9]


async def test_embed_texts_falls_back_to_hash_when_encode_raises(monkeypatch):
    class FakeModel:
        def encode(self, *_args, **_kwargs):
            raise RuntimeError("encode failed")

    monkeypatch.setattr(ai, "_load_sentence_transformer", lambda _m: FakeModel())

    vectors, provider = await ai.embed_texts(["python"])

    assert provider == "local-hash"
    assert vectors == [ai.hashed_embedding("python")]


async def test_embed_texts_falls_back_to_hash_when_model_unavailable(monkeypatch):
    monkeypatch.setattr(ai, "_load_sentence_transformer", lambda _m: None)

    vectors, provider = await ai.embed_texts(["python"])

    assert provider == "local-hash"
    assert vectors == [ai.hashed_embedding("python")]


# --------------------------------------------------------------------------
# _rewrite_locally / _rewrite_prompt / _rewrite_with_local_llm
# --------------------------------------------------------------------------


def test_rewrite_locally_adds_delivered_prefix_when_no_action_verb_present():
    result = ai._rewrite_locally("python fastapi", ["dashboards for internal teams"], "balanced")
    assert result == ["- Delivered dashboards for internal teams Aligned with python requirements."]


def test_rewrite_locally_keeps_existing_action_verb_and_appends_alignment():
    result = ai._rewrite_locally("python fastapi mongodb", ["Built dashboards for clients"], "balanced")
    assert result == ["- Built dashboards for clients Aligned with python requirements."]


def test_rewrite_locally_ats_focus_appends_top_two_keywords():
    result = ai._rewrite_locally("python fastapi mongodb experience required", ["wrote some code"], "ats")
    assert result == ["- Delivered wrote some code Relevant keywords: python, fastapi."]


def test_rewrite_locally_impact_focus_appends_impact_sentence():
    result = ai._rewrite_locally("python", ["wrote some code"], "impact")
    assert result == ["- Delivered wrote some code Highlighted measurable impact and ownership."]


def test_rewrite_locally_skips_blank_bullets_but_keeps_valid_ones():
    result = ai._rewrite_locally("python", ["   ", "did stuff"], "balanced")
    assert result == ["- Delivered did stuff Aligned with python requirements."]


def test_rewrite_locally_strips_leading_dash_or_asterisk():
    result = ai._rewrite_locally("python", ["- did stuff"], "balanced")
    assert result == ["- Delivered did stuff Aligned with python requirements."]


def test_rewrite_locally_no_keywords_leaves_sentence_unmodified_by_focus_branch():
    result = ai._rewrite_locally("", ["built dashboards"], "balanced")
    assert result == ["- Built dashboards"]


def test_rewrite_prompt_includes_focus_instruction_job_text_and_bullet():
    prompt = ai._rewrite_prompt("Looking for a   Python dev", "- built things", "ats")
    assert "Keep ATS-friendly keywords from the job posting when they are truthful." in prompt
    assert "Job posting: Looking for a Python dev" in prompt
    assert "Original bullet: built things" in prompt


def test_rewrite_prompt_unknown_focus_defaults_to_balanced_instruction():
    prompt = ai._rewrite_prompt("job", "bullet", "not-a-real-focus")
    assert "Balance clarity, relevance, and measurable impact." in prompt


def test_rewrite_with_local_llm_returns_none_when_pipeline_unavailable(monkeypatch):
    monkeypatch.setattr(ai, "_load_rewrite_pipeline", lambda _m=None: None)
    assert ai._rewrite_with_local_llm("job", ["bullet"], "balanced") is None


def test_rewrite_with_local_llm_strips_prompt_echo_and_appends_period(monkeypatch):
    def fake_pipeline(prompt, max_new_tokens, do_sample, num_beams, truncation):
        return [{"generated_text": prompt + "Improved the dashboard performance"}]

    monkeypatch.setattr(ai, "_load_rewrite_pipeline", lambda _m=None: fake_pipeline)

    result = ai._rewrite_with_local_llm("job text", ["original bullet"], "balanced")

    assert result == (["- Improved the dashboard performance."], "local-llm")


def test_rewrite_with_local_llm_returns_none_when_pipeline_call_raises(monkeypatch):
    def raising_pipeline(*_a, **_k):
        raise RuntimeError("inference failed")

    monkeypatch.setattr(ai, "_load_rewrite_pipeline", lambda _m=None: raising_pipeline)

    assert ai._rewrite_with_local_llm("job", ["bullet"], "balanced") is None


def test_rewrite_with_local_llm_returns_none_when_all_outputs_blank(monkeypatch):
    def fake_pipeline(*_a, **_k):
        return [{"generated_text": ""}]

    monkeypatch.setattr(ai, "_load_rewrite_pipeline", lambda _m=None: fake_pipeline)

    assert ai._rewrite_with_local_llm("job", ["bullet"], "balanced") is None


# --------------------------------------------------------------------------
# rewrite_resume_bullets
# --------------------------------------------------------------------------


async def test_rewrite_resume_bullets_empty_bullets_returns_empty_local_rule():
    result = await ai.rewrite_resume_bullets("job", ["   ", ""])
    assert result == ([], "local-rule")


async def test_rewrite_resume_bullets_local_fallback_mode_uses_rule_rewriter(monkeypatch):
    def fail_if_called(*_a, **_k):
        raise AssertionError("should not attempt the LLM path in local-fallback mode")

    monkeypatch.setattr(ai, "_rewrite_with_local_llm", fail_if_called)

    result = await ai.rewrite_resume_bullets(
        "python", ["built dashboards"], preferences={"inference_mode": "local-fallback"}
    )

    assert result == (ai._rewrite_locally("python", ["built dashboards"], "balanced"), "local-rule")


async def test_rewrite_resume_bullets_uses_llm_result_when_available(monkeypatch):
    monkeypatch.setattr(ai, "_rewrite_with_local_llm", lambda *_a, **_k: (["- llm bullet."], "local-llm"))

    result = await ai.rewrite_resume_bullets("python", ["bullet"])

    assert result == (["- llm bullet."], "local-llm")


async def test_rewrite_resume_bullets_falls_back_to_rule_when_llm_unavailable(monkeypatch):
    monkeypatch.setattr(ai, "_rewrite_with_local_llm", lambda *_a, **_k: None)

    result = await ai.rewrite_resume_bullets("python", ["did stuff"])

    assert result == (ai._rewrite_locally("python", ["did stuff"], "balanced"), "local-rule")


# --------------------------------------------------------------------------
# _extract_candidates_locally (ground-truthed against the real regex logic)
# --------------------------------------------------------------------------


def test_extract_candidates_locally_finds_phrase_after_trigger_word():
    result = ai._extract_candidates_locally("experience with Kubernetes")
    names = [c["name"] for c in result]
    assert names == ["Kubernetes", "experience with Kubernetes"]


def test_extract_candidates_locally_splits_comma_separated_skills_block():
    result = ai._extract_candidates_locally("Skills: Python, FastAPI, MongoDB")
    names = [c["name"] for c in result]
    assert names == ["Python", "FastAPI", "MongoDB", "Skills: Python", "Skills"]


def test_extract_candidates_locally_respects_max_candidates_limit():
    many = ", ".join(f"Tool{i}" for i in range(50))
    result = ai._extract_candidates_locally(f"Skills: {many}", max_candidates=5)
    assert len(result) == 5


def test_extract_candidates_locally_dedupes_case_insensitively():
    result = ai._extract_candidates_locally("experience with Python. experience with PYTHON")
    names = [c["name"] for c in result]
    assert names == ["Python. experience with PYTHON", "Python"]


def test_extract_candidates_locally_blank_text_returns_empty_list():
    assert ai._extract_candidates_locally("") == []
    assert ai._extract_candidates_locally(None) == []


# --------------------------------------------------------------------------
# _classify_candidate_locally
# --------------------------------------------------------------------------


def test_classify_candidate_locally_rejects_blank_name():
    assert ai._classify_candidate_locally("") == (False, "")
    assert ai._classify_candidate_locally(None) == (False, "")


def test_classify_candidate_locally_rejects_bad_prefixes():
    assert ai._classify_candidate_locally("Responsible for testing") == (False, "")
    assert ai._classify_candidate_locally("ability to learn quickly") == (False, "")


def test_classify_candidate_locally_rejects_employment_boilerplate():
    assert ai._classify_candidate_locally("we are an equal opportunity employer") == (False, "")
    assert ai._classify_candidate_locally("salary and benefits included") == (False, "")


def test_classify_candidate_locally_accepts_generic_skill_name():
    assert ai._classify_candidate_locally("Python") == (True, "General")
    assert ai._classify_candidate_locally("go") == (True, "General")


# --------------------------------------------------------------------------
# extract_skill_candidates
# --------------------------------------------------------------------------


async def test_extract_skill_candidates_blank_text_returns_empty_local_rule():
    result = await ai.extract_skill_candidates("   ")
    assert result == ([], "local-rule")


async def test_extract_skill_candidates_local_fallback_mode_skips_classifier_pipeline(monkeypatch):
    def fail_if_called(*_a, **_k):
        raise AssertionError("zero-shot pipeline should not load in local-fallback mode")

    monkeypatch.setattr(ai, "_load_zero_shot_pipeline", fail_if_called)
    monkeypatch.setattr(
        ai,
        "_extract_candidates_locally",
        lambda _text, max_candidates=50: [
            {"name": "Python", "category": ""},
            {"name": "responsible for testing", "category": ""},
            {"name": "FastAPI", "category": ""},
        ],
    )

    result, provider = await ai.extract_skill_candidates("anything", preferences={"inference_mode": "local-fallback"})

    assert provider == "local-rule"
    assert result == [
        {"name": "Python", "category": "General"},
        {"name": "FastAPI", "category": "General"},
    ]


async def test_extract_skill_candidates_uses_classifier_and_falls_back_locally_on_low_confidence(monkeypatch):
    monkeypatch.setattr(
        ai,
        "_extract_candidates_locally",
        lambda _text, max_candidates=50: [{"name": "Python", "category": ""}, {"name": "Excel", "category": ""}],
    )

    def fake_classifier(batch, _labels, multi_label, batch_size):
        responses = {
            "Python": {"labels": ["programming language", "not a skill"], "scores": [0.9, 0.05]},
            "Excel": {"labels": ["not a skill", "software tool"], "scores": [0.6, 0.3]},
        }
        return [responses[name] for name in batch]

    monkeypatch.setattr(ai, "_load_zero_shot_pipeline", lambda _m: fake_classifier)

    result, provider = await ai.extract_skill_candidates("anything")

    assert provider == "local-transformer"
    assert {"name": "Python", "category": "Programming"} in result
    # "Excel" was classified "not a skill" by the model, so it falls back to
    # the local rule-based classifier, which accepts it as a generic skill.
    assert {"name": "Excel", "category": "General"} in result


async def test_extract_skill_candidates_uses_cache_and_never_calls_classifier(monkeypatch):
    monkeypatch.setattr(
        ai, "_extract_candidates_locally", lambda _text, max_candidates=50: [{"name": "Python", "category": ""}]
    )
    cache_key = f"{settings.local_zero_shot_model}|python"
    ai._CLASSIFY_CACHE[cache_key] = (True, "Cloud")

    def fail_if_called(*_a, **_k):
        raise AssertionError("classifier should not be invoked for an already-cached name")

    monkeypatch.setattr(ai, "_load_zero_shot_pipeline", lambda _m: fail_if_called)

    result, provider = await ai.extract_skill_candidates("anything")

    assert provider == "local-transformer"
    assert result == [{"name": "Python", "category": "Cloud"}]


async def test_extract_skill_candidates_falls_back_locally_when_classifier_call_raises(monkeypatch):
    monkeypatch.setattr(
        ai,
        "_extract_candidates_locally",
        lambda _text, max_candidates=50: [{"name": "Python", "category": ""}, {"name": "go", "category": ""}],
    )

    def raising_classifier(*_a, **_k):
        raise RuntimeError("inference backend unavailable")

    monkeypatch.setattr(ai, "_load_zero_shot_pipeline", lambda _m: raising_classifier)

    result, provider = await ai.extract_skill_candidates("anything")

    assert provider == "local-transformer"
    assert {"name": "Python", "category": "General"} in result
    assert {"name": "go", "category": "General"} in result


async def test_extract_skill_candidates_dedupes_case_insensitive_keeping_first_occurrence(monkeypatch):
    monkeypatch.setattr(
        ai,
        "_extract_candidates_locally",
        lambda _text, max_candidates=50: [
            {"name": "Python", "category": ""},
            {"name": "python", "category": ""},
            {"name": "PYTHON", "category": ""},
        ],
    )
    monkeypatch.setattr(
        ai, "_load_zero_shot_pipeline", lambda _m: (lambda batch, *_a, **_k: [{"labels": ["programming language"], "scores": [0.9]} for _ in batch])
    )

    result, provider = await ai.extract_skill_candidates("anything")

    assert provider == "local-transformer"
    assert result == [{"name": "Python", "category": "Programming"}]


async def test_extract_skill_candidates_respects_max_candidates_limit(monkeypatch):
    candidates = [{"name": f"Skill{i}", "category": ""} for i in range(10)]
    monkeypatch.setattr(ai, "_extract_candidates_locally", lambda _text, max_candidates=50: candidates)
    monkeypatch.setattr(
        ai, "_load_zero_shot_pipeline", lambda _m: (lambda batch, *_a, **_k: [{"labels": ["programming language"], "scores": [0.9]} for _ in batch])
    )

    result, provider = await ai.extract_skill_candidates("anything", max_candidates=3)

    assert provider == "local-transformer"
    assert len(result) == 3
