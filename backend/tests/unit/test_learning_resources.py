"""Unit tests for app/utils/learning_resources.py (pure dict-lookup helpers)."""

from __future__ import annotations

from app.utils.learning_resources import (
    CATEGORY_DEFAULTS,
    RESOURCE_CATALOG,
    recommended_resources,
    recommended_resources_for_many,
)


def test_recommended_resources_matches_catalog_case_insensitively():
    result = recommended_resources("PYTHON")
    assert result == RESOURCE_CATALOG["python"]


def test_recommended_resources_strips_whitespace_before_lookup():
    result = recommended_resources("  sql  ")
    assert result == RESOURCE_CATALOG["sql"]


def test_recommended_resources_truncates_to_limit():
    result = recommended_resources("python", limit=1)
    assert result == RESOURCE_CATALOG["python"][:1]


def test_recommended_resources_falls_back_to_category_defaults_when_no_catalog_match():
    result = recommended_resources("Some Unknown Skill", category="Programming")
    assert result == CATEGORY_DEFAULTS["Programming"]


def test_recommended_resources_returns_empty_when_no_match_and_no_category():
    assert recommended_resources("Some Unknown Skill") == []


def test_recommended_resources_returns_empty_when_category_unknown():
    assert recommended_resources("Some Unknown Skill", category="Nonexistent") == []


def test_recommended_resources_blank_skill_name_with_known_category_uses_default():
    result = recommended_resources("", category="Cloud")
    assert result == CATEGORY_DEFAULTS["Cloud"]


def test_recommended_resources_none_skill_name_does_not_raise():
    assert recommended_resources(None) == []


def test_recommended_resources_for_many_combines_and_dedupes_across_skills():
    # "ml" and "machine learning" share the first catalog entry, so it
    # should only appear once in the combined result.
    result = recommended_resources_for_many([("ml", "Data"), ("machine learning", "Data")], limit=10)
    titles = [r["title"] for r in result]
    assert titles.count("Machine Learning Specialization") == 1
    assert "Google Machine Learning Crash Course" in titles


def test_recommended_resources_for_many_stops_once_limit_reached():
    result = recommended_resources_for_many(
        [("python", "Programming"), ("sql", "Data"), ("fastapi", "Backend")], limit=3
    )
    assert len(result) == 3
    # Should be the two Python resources plus the first SQL resource, in order.
    assert result[0]["title"] == "Python Official Tutorial"
    assert result[1]["title"] == "Automate the Boring Stuff"
    assert result[2]["title"] == "SQLBolt"


def test_recommended_resources_for_many_empty_input_returns_empty_list():
    assert recommended_resources_for_many([]) == []


def test_recommended_resources_for_many_falls_back_per_skill_to_category_defaults():
    result = recommended_resources_for_many([("Unknown Skill", "Cloud")], limit=4)
    assert result == CATEGORY_DEFAULTS["Cloud"]
