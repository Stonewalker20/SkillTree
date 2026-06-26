"""Unit tests for app/utils/mongo.py id/ref normalization helpers."""

from __future__ import annotations

import pytest
from bson import ObjectId

from app.utils.mongo import (
    canonical_object_ref,
    canonical_object_refs,
    oid_str,
    ref_query,
    ref_values,
    to_object_id,
    try_object_id,
    unique_strings,
)


def test_oid_str_returns_empty_string_for_none():
    assert oid_str(None) == ""


def test_oid_str_stringifies_objectid():
    oid = ObjectId()
    assert oid_str(oid) == str(oid)


def test_try_object_id_passes_through_existing_objectid():
    oid = ObjectId()
    assert try_object_id(oid) is oid


def test_try_object_id_parses_valid_hex_string():
    oid = ObjectId()
    assert try_object_id(str(oid)) == oid


def test_try_object_id_returns_none_for_blank_or_invalid():
    assert try_object_id(None) is None
    assert try_object_id("") is None
    assert try_object_id("   ") is None
    assert try_object_id("not-a-valid-oid") is None


def test_to_object_id_raises_value_error_for_invalid_input():
    with pytest.raises(ValueError):
        to_object_id("not-a-valid-oid")


def test_to_object_id_returns_objectid_for_valid_input():
    oid = ObjectId()
    assert to_object_id(str(oid)) == oid


def test_canonical_object_ref_is_alias_for_try_object_id():
    oid = ObjectId()
    assert canonical_object_ref(str(oid)) == oid
    assert canonical_object_ref("garbage") is None


def test_canonical_object_refs_dedupes_and_skips_invalid():
    oid1 = ObjectId()
    oid2 = ObjectId()
    values = [str(oid1), str(oid1), oid2, "garbage", None, ""]
    result = canonical_object_refs(values)
    assert result == [oid1, oid2]


def test_unique_strings_dedupes_case_insensitively_and_strips():
    result = unique_strings([" Python ", "python", "FastAPI", None, "", "  ", "fastapi"])
    assert result == ["Python", "FastAPI"]


def test_ref_values_for_valid_objectid_string_returns_oid_and_str_forms():
    oid = ObjectId()
    result = ref_values(str(oid))
    assert result == [oid, str(oid)]


def test_ref_values_for_non_objectid_string_returns_single_string():
    result = ref_values("not-an-oid")
    assert result == ["not-an-oid"]


def test_ref_values_for_blank_returns_empty_list():
    assert ref_values(None) == []
    assert ref_values("") == []
    assert ref_values("   ") == []


def test_ref_query_returns_empty_dict_when_no_values():
    assert ref_query("user_id", None) == {}
    assert ref_query("user_id", "") == {}


def test_ref_query_uses_plain_equality_when_single_value():
    result = ref_query("user_id", "plain-string-id")
    assert result == {"user_id": "plain-string-id"}


def test_ref_query_uses_in_operator_when_multiple_values():
    oid = ObjectId()
    result = ref_query("user_id", str(oid))
    assert result == {"user_id": {"$in": [oid, str(oid)]}}
