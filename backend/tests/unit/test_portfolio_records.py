"""Unit tests for app/utils/portfolio_records.py (pure transforms + one Mongo read)."""

from __future__ import annotations

from bson import ObjectId

from app.utils.mongo import ref_values
from app.utils.portfolio_records import (
    load_legacy_portfolio_docs,
    portfolio_dedupe_key,
    portfolio_item_to_evidence_doc,
    serialize_portfolio_doc,
)


# --------------------------------------------------------------------------
# portfolio_dedupe_key
# --------------------------------------------------------------------------


def test_portfolio_dedupe_key_prefers_legacy_id_when_present():
    doc = {"_id": ObjectId(), "legacy_portfolio_item_id": "some-legacy-id"}
    assert portfolio_dedupe_key(doc) == "some-legacy-id"


def test_portfolio_dedupe_key_falls_back_to_doc_id():
    doc_id = ObjectId()
    doc = {"_id": doc_id}
    assert portfolio_dedupe_key(doc) == str(doc_id)


def test_portfolio_dedupe_key_blank_when_neither_present():
    assert portfolio_dedupe_key({}) == ""


# --------------------------------------------------------------------------
# portfolio_item_to_evidence_doc
# --------------------------------------------------------------------------


def test_portfolio_item_to_evidence_doc_maps_core_fields():
    user_id = ObjectId()
    skill_id = ObjectId()
    legacy_id = ObjectId()
    doc = {
        "_id": legacy_id,
        "user_id": str(user_id),
        "type": "project",
        "title": "  My Project  ",
        "summary": "  A short summary  ",
        "links": ["https://example.com/repo", "https://example.com/other"],
        "org": "Acme Co",
        "skill_ids": [str(skill_id), "not-an-oid"],
        "tags": [" tag1 ", "", "tag2"],
        "bullets": [" did a thing ", ""],
        "visibility": "public",
        "priority": 5,
    }

    result = portfolio_item_to_evidence_doc(doc)

    assert result["user_id"] == user_id
    assert result["type"] == "project"
    assert result["title"] == "My Project"
    assert result["source"] == "https://example.com/repo"
    assert result["text_excerpt"] == "A short summary"
    assert result["skill_ids"] == [skill_id]
    assert result["tags"] == ["tag1", "tag2"]
    assert result["bullets"] == ["did a thing"]
    assert result["visibility"] == "public"
    assert result["priority"] == 5
    assert result["legacy_portfolio_item_id"] == legacy_id
    assert result["structured_evidence"] is True
    assert result["origin"] == "user"
    assert "_id" not in result


def test_portfolio_item_to_evidence_doc_defaults_type_to_other_for_unknown_value():
    result = portfolio_item_to_evidence_doc({"type": "not-a-valid-type"})
    assert result["type"] == "other"
    assert result["portfolio_item_type"] == "not-a-valid-type"


def test_portfolio_item_to_evidence_doc_source_falls_back_to_org_then_default():
    result_with_org = portfolio_item_to_evidence_doc({"org": "Acme Co"})
    assert result_with_org["source"] == "Acme Co"

    result_without_anything = portfolio_item_to_evidence_doc({})
    assert result_without_anything["source"] == "structured-evidence"


def test_portfolio_item_to_evidence_doc_text_excerpt_falls_back_to_title_when_no_summary():
    result = portfolio_item_to_evidence_doc({"title": "  My Title  "})
    assert result["text_excerpt"] == "My Title"


def test_portfolio_item_to_evidence_doc_user_id_falls_back_to_raw_value_when_invalid():
    result = portfolio_item_to_evidence_doc({"user_id": "not-an-oid"})
    assert result["user_id"] == "not-an-oid"


def test_portfolio_item_to_evidence_doc_preserve_id_includes_id_when_true():
    doc_id = ObjectId()
    result = portfolio_item_to_evidence_doc({"_id": doc_id}, preserve_id=True)
    assert result["_id"] == doc_id


def test_portfolio_item_to_evidence_doc_preserve_id_false_by_default():
    doc_id = ObjectId()
    result = portfolio_item_to_evidence_doc({"_id": doc_id})
    assert "_id" not in result


# --------------------------------------------------------------------------
# serialize_portfolio_doc
# --------------------------------------------------------------------------


def test_serialize_portfolio_doc_maps_expected_fields():
    doc_id = ObjectId()
    user_id = ObjectId()
    skill_id = ObjectId()
    doc = {
        "_id": doc_id,
        "user_id": user_id,
        "portfolio_item_type": "project",
        "title": "My Project",
        "org": "Acme",
        "summary": "Summary text",
        "bullets": ["did a thing"],
        "links": ["https://example.com"],
        "skill_ids": [skill_id],
        "tags": ["tag1"],
        "visibility": "public",
        "priority": 2,
    }

    result = serialize_portfolio_doc(doc)

    assert result["id"] == str(doc_id)
    assert result["user_id"] == str(user_id)
    assert result["type"] == "project"
    assert result["title"] == "My Project"
    assert result["skill_ids"] == [str(skill_id)]
    assert result["visibility"] == "public"
    assert result["priority"] == 2


def test_serialize_portfolio_doc_falls_back_to_type_then_other_when_portfolio_item_type_missing():
    assert serialize_portfolio_doc({"type": "cert"})["type"] == "cert"
    assert serialize_portfolio_doc({})["type"] == "other"


def test_serialize_portfolio_doc_defaults_for_missing_optional_fields():
    result = serialize_portfolio_doc({})
    assert result["id"] == ""
    assert result["user_id"] == ""
    assert result["title"] == ""
    assert result["bullets"] == []
    assert result["links"] == []
    assert result["skill_ids"] == []
    assert result["tags"] == []
    assert result["visibility"] == "private"
    assert result["priority"] == 0


# --------------------------------------------------------------------------
# load_legacy_portfolio_docs (one Mongo read, fully mocked)
# --------------------------------------------------------------------------


async def test_load_legacy_portfolio_docs_queries_by_user_id_and_returns_results(stub_db):
    user_id = str(ObjectId())
    docs = [{"_id": ObjectId(), "title": "A"}, {"_id": ObjectId(), "title": "B"}]
    stub_db["portfolio_items"].set_find_results(docs)

    result = await load_legacy_portfolio_docs(stub_db, user_id)

    assert result == docs
    stub_db["portfolio_items"].find.assert_called_once_with({"user_id": {"$in": ref_values(user_id)}})


async def test_load_legacy_portfolio_docs_returns_empty_list_when_no_matches(stub_db):
    stub_db["portfolio_items"].set_find_results([])
    result = await load_legacy_portfolio_docs(stub_db, str(ObjectId()))
    assert result == []
