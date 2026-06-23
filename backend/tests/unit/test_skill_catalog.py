"""Unit tests for app/utils/skill_catalog.py normalization and merge logic."""

from __future__ import annotations

from bson import ObjectId

from app.utils.skill_catalog import (
    canonical_skill_terms,
    expand_alias_variants,
    lexical_skill_similarity,
    merge_skill_docs,
    normalize_skill_text,
    should_use_strict_exact_match,
    unique_casefolded,
)


def test_normalize_skill_text_collapses_whitespace_and_casefolds():
    assert normalize_skill_text("  Machine   Learning  ") == "machine learning"


def test_normalize_skill_text_handles_none():
    assert normalize_skill_text(None) == ""


def test_should_use_strict_exact_match_true_for_known_short_keys():
    assert should_use_strict_exact_match("AI") is True
    assert should_use_strict_exact_match("ml") is True
    assert should_use_strict_exact_match("Go") is True


def test_should_use_strict_exact_match_true_for_blank_or_very_short():
    assert should_use_strict_exact_match("") is True
    assert should_use_strict_exact_match(None) is True
    assert should_use_strict_exact_match("zz") is True


def test_should_use_strict_exact_match_false_for_normal_skill_name():
    assert should_use_strict_exact_match("Python") is False
    assert should_use_strict_exact_match("Machine Learning") is False


def test_unique_casefolded_dedupes_preserving_first_occurrence_casing():
    result = unique_casefolded(["Python", "python", "PYTHON", "FastAPI", "", None, "  "])
    assert result == ["Python", "FastAPI"]


def test_expand_alias_variants_adds_pluralized_and_singularized_forms():
    result = expand_alias_variants(["Database"])
    assert "Databases" in result


def test_expand_alias_variants_excludes_terms_matching_base_name():
    result = expand_alias_variants(["Python", "Pythons"], base_name="Python")
    assert all(normalize_skill_text(v) != "python" for v in result)


def test_expand_alias_variants_adds_initialism_for_multiword_base_name():
    result = expand_alias_variants([], base_name="Customer Relationship Management")
    assert "CRM" in result


def test_expand_alias_variants_skips_initialism_if_it_is_a_strict_short_key():
    # "Machine Learning" initializes to "ML", which is itself a strict
    # short skill key (its own canonical entry) -- it should NOT be added
    # as a noisy two-letter alias under the longer name.
    result = expand_alias_variants([], base_name="Machine Learning")
    assert "ML" not in result


def test_canonical_skill_terms_combines_name_and_aliases():
    doc = {"name": "Python", "aliases": ["Py", "python3"]}
    terms = canonical_skill_terms(doc)
    assert terms == ["Python", "Py", "python3"]


def test_canonical_skill_terms_handles_missing_aliases():
    doc = {"name": "Python"}
    assert canonical_skill_terms(doc) == ["Python"]


def test_lexical_skill_similarity_identical_strings_returns_one():
    assert lexical_skill_similarity("Python", "python") == 1.0


def test_lexical_skill_similarity_blank_inputs_return_zero():
    assert lexical_skill_similarity("", "Python") == 0.0
    assert lexical_skill_similarity(None, None) == 0.0


def test_lexical_skill_similarity_strict_short_keys_return_zero_unless_identical():
    assert lexical_skill_similarity("AI", "Artificial Intelligence") == 0.0


def test_lexical_skill_similarity_partial_token_overlap():
    score = lexical_skill_similarity("Machine Learning Engineer", "Machine Learning")
    assert 0.0 < score <= 1.0


def test_lexical_skill_similarity_no_token_overlap_returns_zero():
    assert lexical_skill_similarity("Python", "Excel") == 0.0


def test_merge_skill_docs_groups_by_normalized_name():
    id1, id2 = ObjectId(), ObjectId()
    docs = [
        {"_id": id1, "name": "Python", "category": "Programming", "origin": "default"},
        {"_id": id2, "name": "python", "category": "Languages", "origin": "user", "created_by_user_id": ObjectId()},
    ]
    merged = merge_skill_docs(docs)
    assert len(merged) == 1
    assert merged[0]["name"] == "Python"
    assert set(merged[0]["merged_ids"]) == {str(id1), str(id2)}


def test_merge_skill_docs_skips_entries_without_name_or_id():
    docs = [{"_id": None, "name": "Python"}, {"_id": ObjectId(), "name": ""}]
    assert merge_skill_docs(docs) == []


def test_merge_skill_docs_default_origin_wins_over_user_origin():
    default_id = ObjectId()
    user_id = ObjectId()
    docs = [
        {"_id": user_id, "name": "Python", "origin": "user", "created_by_user_id": ObjectId()},
        {"_id": default_id, "name": "Python", "origin": "default"},
    ]
    merged = merge_skill_docs(docs)
    assert merged[0]["origin"] == "default"
    assert merged[0]["can_delete"] is False


def test_merge_skill_docs_can_delete_true_when_sole_creator_matches_current_user():
    creator = ObjectId()
    doc_id = ObjectId()
    docs = [{"_id": doc_id, "name": "Custom Skill", "origin": "user", "created_by_user_id": creator}]
    merged = merge_skill_docs(docs, current_user_oid=creator)
    assert merged[0]["can_delete"] is True
    assert merged[0]["created_by_user_id"] == str(creator)


def test_merge_skill_docs_can_delete_false_for_different_user():
    creator = ObjectId()
    other_user = ObjectId()
    doc_id = ObjectId()
    docs = [{"_id": doc_id, "name": "Custom Skill", "origin": "user", "created_by_user_id": creator}]
    merged = merge_skill_docs(docs, current_user_oid=other_user)
    assert merged[0]["can_delete"] is False


def test_merge_skill_docs_sorted_by_normalized_name():
    docs = [
        {"_id": ObjectId(), "name": "Zebra Skill", "origin": "default"},
        {"_id": ObjectId(), "name": "Alpha Skill", "origin": "default"},
    ]
    merged = merge_skill_docs(docs)
    assert [doc["name"] for doc in merged] == ["Alpha Skill", "Zebra Skill"]


def test_merge_skill_docs_aliases_exclude_name_itself():
    doc_id = ObjectId()
    docs = [{"_id": doc_id, "name": "Python", "aliases": ["Python", "Py"], "origin": "default"}]
    merged = merge_skill_docs(docs)
    assert "Py" in merged[0]["aliases"]
    assert all(normalize_skill_text(a) != "python" for a in merged[0]["aliases"])
