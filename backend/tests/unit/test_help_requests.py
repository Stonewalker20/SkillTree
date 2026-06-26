"""Unit tests for app/utils/help_requests.py, mocking all Mongo calls."""

from __future__ import annotations

from datetime import datetime, timezone

from app.utils.help_requests import refresh_user_help_unread_count


async def test_refresh_user_help_unread_count_queries_and_updates_with_count(stub_db):
    stub_db["help_requests"].count_documents.return_value = 3

    result = await refresh_user_help_unread_count(stub_db, "user-123")

    assert result == 3

    stub_db["help_requests"].count_documents.assert_called_once_with(
        {"user_id": "user-123", "user_has_unread_response": True}
    )

    stub_db["users"].update_one.assert_called_once()
    update_filter, update_doc = stub_db["users"].update_one.call_args.args
    assert update_filter == {"_id": "user-123"}
    assert update_doc["$set"]["help_unread_response_count"] == 3
    assert isinstance(update_doc["$set"]["updated_at"], datetime)
    assert update_doc["$set"]["updated_at"].tzinfo is timezone.utc


async def test_refresh_user_help_unread_count_returns_zero_when_no_unread(stub_db):
    stub_db["help_requests"].count_documents.return_value = 0

    result = await refresh_user_help_unread_count(stub_db, "user-456")

    assert result == 0
    update_doc = stub_db["users"].update_one.call_args.args[1]
    assert update_doc["$set"]["help_unread_response_count"] == 0


async def test_refresh_user_help_unread_count_casts_count_to_int(stub_db):
    # Mongo's count_documents can return non-int-typed numeric results in
    # some driver paths; the helper should coerce explicitly via int().
    stub_db["help_requests"].count_documents.return_value = 5.0

    result = await refresh_user_help_unread_count(stub_db, "user-789")

    assert result == 5
    assert isinstance(result, int)
