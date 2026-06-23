"""Unit tests for app/utils/job_records.py (pure transformation/merge logic)."""

from __future__ import annotations

from bson import ObjectId

from app.utils.job_records import (
    derive_required_skills,
    hydrate_job_doc,
    linked_job_ingest_oid,
    normalize_extracted_skills,
    serialize_extracted_skill,
)


# --------------------------------------------------------------------------
# serialize_extracted_skill
# --------------------------------------------------------------------------


def test_serialize_extracted_skill_returns_none_when_no_name_and_no_id():
    assert serialize_extracted_skill({"skill_name": "  ", "skill_id": "not-an-oid"}) is None


def test_serialize_extracted_skill_builds_expected_fields():
    skill_id = ObjectId()
    result = serialize_extracted_skill(
        {"skill_id": skill_id, "skill_name": "Python", "matched_on": "alias", "count": 3}
    )
    assert result == {
        "skill_id": str(skill_id),
        "skill_name": "Python",
        "matched_on": "alias",
        "count": 3,
    }


def test_serialize_extracted_skill_defaults_matched_on_to_name_when_blank():
    result = serialize_extracted_skill({"skill_name": "Python", "matched_on": "   "})
    assert result["matched_on"] == "name"


def test_serialize_extracted_skill_defaults_count_to_one_when_missing():
    result = serialize_extracted_skill({"skill_name": "Python"})
    assert result["count"] == 1


def test_serialize_extracted_skill_count_zero_falls_back_to_one():
    # `entry.get("count") or 1` treats a stored 0 as falsy, so it is
    # silently coerced to 1 rather than preserved as zero.
    result = serialize_extracted_skill({"skill_name": "Python", "count": 0})
    assert result["count"] == 1


def test_serialize_extracted_skill_skill_id_blank_when_only_name_present():
    result = serialize_extracted_skill({"skill_name": "Python"})
    assert result["skill_id"] == ""


# --------------------------------------------------------------------------
# normalize_extracted_skills
# --------------------------------------------------------------------------


def test_normalize_extracted_skills_skips_non_dict_entries():
    assert normalize_extracted_skills(["not-a-dict", 123, None]) == []


def test_normalize_extracted_skills_calls_model_dump_on_pydantic_like_objects():
    class FakeModel:
        def model_dump(self):
            return {"skill_name": "Python", "count": 2}

    result = normalize_extracted_skills([FakeModel()])
    assert len(result) == 1
    assert result[0]["skill_name"] == "Python"
    assert result[0]["count"] == 2


def test_normalize_extracted_skills_groups_by_skill_id_and_sums_counts():
    skill_id = ObjectId()
    entries = [
        {"skill_id": skill_id, "skill_name": "Python", "count": 2},
        {"skill_id": skill_id, "skill_name": "Python", "count": 3},
    ]
    result = normalize_extracted_skills(entries)
    assert len(result) == 1
    assert result[0]["count"] == 5


def test_normalize_extracted_skills_groups_by_normalized_name_when_no_id():
    entries = [
        {"skill_name": "Python", "count": 1},
        {"skill_name": "python", "count": 1},
        {"skill_name": "  PYTHON  ", "count": 1},
    ]
    result = normalize_extracted_skills(entries)
    assert len(result) == 1
    assert result[0]["count"] == 3


def test_normalize_extracted_skills_backfills_missing_skill_name_on_existing_group():
    skill_id = ObjectId()
    entries = [
        {"skill_id": skill_id, "skill_name": "", "count": 1},
        {"skill_id": skill_id, "skill_name": "Python", "count": 1},
    ]
    result = normalize_extracted_skills(entries)
    assert result[0]["skill_name"] == "Python"
    assert result[0]["count"] == 2


def test_normalize_extracted_skills_skips_entries_with_no_id_and_no_name():
    entries = [{"skill_name": "  ", "count": 1}]
    assert normalize_extracted_skills(entries) == []


def test_normalize_extracted_skills_count_always_clamped_to_at_least_one():
    entries = [{"skill_name": "Python", "count": -5}]
    result = normalize_extracted_skills(entries)
    assert result[0]["count"] == 1


def test_normalize_extracted_skills_defaults_matched_on_to_name():
    entries = [{"skill_name": "Python"}]
    result = normalize_extracted_skills(entries)
    assert result[0]["matched_on"] == "name"


# --------------------------------------------------------------------------
# derive_required_skills
# --------------------------------------------------------------------------


def test_derive_required_skills_returns_unique_names_and_ids_in_order():
    id1, id2 = ObjectId(), ObjectId()
    extracted = [
        {"skill_name": "Python", "skill_id": id1},
        {"skill_name": "python", "skill_id": id1},  # duplicate id, duplicate (casefolded) name
        {"skill_name": "FastAPI", "skill_id": id2},
    ]
    names, ids = derive_required_skills(extracted)
    assert names == ["Python", "FastAPI"]
    assert ids == [id1, id2]


def test_derive_required_skills_keeps_name_even_when_id_missing():
    extracted = [{"skill_name": "Python", "skill_id": None}]
    names, ids = derive_required_skills(extracted)
    assert names == ["Python"]
    assert ids == []


def test_derive_required_skills_skips_invalid_id_but_keeps_name():
    extracted = [{"skill_name": "Python", "skill_id": "not-an-oid"}]
    names, ids = derive_required_skills(extracted)
    assert names == ["Python"]
    assert ids == []


def test_derive_required_skills_handles_empty_input():
    assert derive_required_skills([]) == ([], [])


# --------------------------------------------------------------------------
# linked_job_ingest_oid
# --------------------------------------------------------------------------


def test_linked_job_ingest_oid_none_for_non_dict():
    assert linked_job_ingest_oid(None) is None
    assert linked_job_ingest_oid("not-a-dict") is None


def test_linked_job_ingest_oid_none_when_field_missing():
    assert linked_job_ingest_oid({}) is None


def test_linked_job_ingest_oid_returns_oid_when_valid():
    ingest_id = ObjectId()
    result = linked_job_ingest_oid({"job_ingest_id": str(ingest_id)})
    assert result == ingest_id


# --------------------------------------------------------------------------
# hydrate_job_doc
# --------------------------------------------------------------------------


def test_hydrate_job_doc_overlays_fields_from_ingest_when_non_blank():
    job_doc = {"title": "Old Title", "company": "Old Co"}
    ingest_doc = {"title": "New Title", "company": "", "location": "Remote", "text": "Full job text here."}

    merged = hydrate_job_doc(job_doc, ingest_doc)

    assert merged["title"] == "New Title"
    assert merged["company"] == "Old Co"  # blank ingest company does not overwrite
    assert merged["location"] == "Remote"
    assert merged["description_full"] == "Full job text here."


def test_hydrate_job_doc_truncates_description_excerpt_over_220_chars():
    long_text = "word " * 100  # well over 220 characters once joined
    merged = hydrate_job_doc({}, {"text": long_text})

    excerpt = merged["description_excerpt"]
    assert len(excerpt) == 223  # 220 chars + "..."
    assert excerpt.endswith("...")


def test_hydrate_job_doc_no_ellipsis_when_excerpt_under_220_chars():
    merged = hydrate_job_doc({}, {"text": "short job description"})
    assert merged["description_excerpt"] == "short job description"
    assert not merged["description_excerpt"].endswith("...")


def test_hydrate_job_doc_derives_required_skills_from_ingest_extracted_skills():
    skill_id = ObjectId()
    ingest_doc = {"extracted_skills": [{"skill_name": "Python", "skill_id": skill_id}]}
    merged = hydrate_job_doc({}, ingest_doc)
    assert merged["required_skills"] == ["Python"]
    assert merged["required_skill_ids"] == [skill_id]


def test_hydrate_job_doc_without_ingest_normalizes_existing_required_skills():
    valid_id = ObjectId()
    job_doc = {
        "required_skills": ["Python", "python", ""],
        "required_skill_ids": [valid_id, "not-an-oid"],
    }
    merged = hydrate_job_doc(job_doc, None)
    assert merged["required_skills"] == ["Python"]
    assert merged["required_skill_ids"] == [valid_id]


def test_hydrate_job_doc_filters_role_ids_to_valid_object_ids():
    valid_id = ObjectId()
    job_doc = {"role_ids": [valid_id, "garbage", None]}
    merged = hydrate_job_doc(job_doc, None)
    assert merged["role_ids"] == [valid_id]


def test_hydrate_job_doc_converts_submitted_by_user_id_when_valid():
    user_id = ObjectId()
    merged = hydrate_job_doc({"submitted_by_user_id": str(user_id)}, None)
    assert merged["submitted_by_user_id"] == user_id


def test_hydrate_job_doc_keeps_submitted_by_user_id_unchanged_when_not_a_valid_oid():
    merged = hydrate_job_doc({"submitted_by_user_id": "not-an-oid"}, None)
    assert merged["submitted_by_user_id"] == "not-an-oid"


def test_hydrate_job_doc_does_not_mutate_input_dict():
    job_doc = {"title": "Original"}
    hydrate_job_doc(job_doc, {"title": "Changed"})
    assert job_doc["title"] == "Original"
