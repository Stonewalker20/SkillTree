"""Unit tests for app/utils/security.py rate limiting and audit logging helpers."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.utils.security import (
    build_rate_limit_identifier,
    enforce_rate_limit,
    get_request_ip,
    record_admin_audit_event,
)


class FakeClient:
    def __init__(self, host):
        self.host = host


class FakeRequest:
    def __init__(self, client_host=None, headers=None):
        self.client = FakeClient(client_host) if client_host is not None else None
        self.headers = headers or {}


def test_get_request_ip_returns_unknown_for_none_request():
    assert get_request_ip(None) == "unknown"


def test_get_request_ip_returns_unknown_when_no_client_and_no_headers():
    request = FakeRequest(client_host=None)
    assert get_request_ip(request) == "unknown"


def test_get_request_ip_returns_client_host_when_not_a_trusted_proxy(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", "")
    request = FakeRequest(client_host="203.0.113.9", headers={"x-forwarded-for": "198.51.100.1"})
    # Not a trusted proxy, so forwarded headers must be ignored entirely.
    assert get_request_ip(request) == "203.0.113.9"


def test_get_request_ip_uses_forwarded_for_when_proxy_is_trusted(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", "10.0.0.0/8")
    request = FakeRequest(
        client_host="10.0.0.5",
        # 8.8.8.8 is a genuinely globally-routable address; RFC 5737
        # documentation ranges (203.0.113.0/24 etc.) are deliberately
        # classified as non-public by Python's ipaddress module, so they
        # would not exercise the "safe forwarded host" branch here.
        headers={"x-forwarded-for": "8.8.8.8, 10.0.0.5"},
    )
    assert get_request_ip(request) == "8.8.8.8"


def test_get_request_ip_skips_private_forwarded_for_and_falls_back_to_client(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", "10.0.0.0/8")
    request = FakeRequest(client_host="10.0.0.5", headers={"x-forwarded-for": "192.168.1.5"})
    assert get_request_ip(request) == "10.0.0.5"


def test_get_request_ip_uses_real_ip_header_when_forwarded_for_missing(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", "10.0.0.0/8")
    request = FakeRequest(client_host="10.0.0.5", headers={"x-real-ip": "1.1.1.1"})
    assert get_request_ip(request) == "1.1.1.1"


def test_build_rate_limit_identifier_combines_ip_and_lowercased_parts():
    request = FakeRequest(client_host="203.0.113.9")
    identifier = build_rate_limit_identifier(request, "Login", "  SomeScope  ")
    assert identifier == "203.0.113.9|login|somescope"


def test_build_rate_limit_identifier_skips_blank_parts():
    request = FakeRequest(client_host="203.0.113.9")
    identifier = build_rate_limit_identifier(request, "", None, "valid")
    assert identifier == "203.0.113.9|valid"


async def test_enforce_rate_limit_returns_unlimited_without_touching_db_when_non_positive(stub_db):
    result = await enforce_rate_limit(stub_db, scope="login", identifier="x", limit=0, window_seconds=60)
    assert result["remaining"] == 0
    stub_db["request_rate_limits"].find_one.assert_not_called()

    result2 = await enforce_rate_limit(stub_db, scope="login", identifier="x", limit=5, window_seconds=0)
    assert result2["remaining"] == 5
    stub_db["request_rate_limits"].find_one.assert_not_called()


async def test_enforce_rate_limit_first_request_inserts_new_window(stub_db):
    stub_db["request_rate_limits"].find_one.return_value = None

    result = await enforce_rate_limit(stub_db, scope="login", identifier="abc", limit=5, window_seconds=60)

    assert result["limit"] == 5
    assert result["remaining"] == 4
    stub_db["request_rate_limits"].insert_one.assert_called_once()
    inserted_doc = stub_db["request_rate_limits"].insert_one.call_args.args[0]
    assert inserted_doc["count"] == 1
    assert inserted_doc["scope"] == "login"
    assert inserted_doc["identifier"] == "abc"


async def test_enforce_rate_limit_increments_existing_window(stub_db):
    stub_db["request_rate_limits"].find_one.return_value = {"count": 2}

    result = await enforce_rate_limit(stub_db, scope="login", identifier="abc", limit=5, window_seconds=60)

    assert result["remaining"] == 2  # limit(5) - next_count(3)
    update_filter, update_doc = stub_db["request_rate_limits"].update_one.call_args.args
    assert update_doc["$set"]["count"] == 3


async def test_enforce_rate_limit_raises_429_when_limit_reached(stub_db):
    stub_db["request_rate_limits"].find_one.return_value = {"count": 5}

    with pytest.raises(HTTPException) as exc_info:
        await enforce_rate_limit(stub_db, scope="login", identifier="abc", limit=5, window_seconds=60)

    assert exc_info.value.status_code == 429
    stub_db["request_rate_limits"].update_one.assert_not_called()


async def test_record_admin_audit_event_writes_expected_document(stub_db):
    actor = {"_id": "actor-id-123", "email": "admin@example.com", "role": "admin"}
    request = FakeRequest(client_host="203.0.113.9", headers={"user-agent": "pytest-agent"})

    await record_admin_audit_event(
        stub_db,
        actor=actor,
        action="promote_user",
        target_type="user",
        target_id="target-1",
        details={"new_role": "team"},
        request=request,
    )

    stub_db["audit_events"].insert_one.assert_called_once()
    event = stub_db["audit_events"].insert_one.call_args.args[0]
    assert event["actor_id"] == "actor-id-123"
    assert event["actor_email"] == "admin@example.com"
    assert event["action"] == "promote_user"
    assert event["target_type"] == "user"
    assert event["target_id"] == "target-1"
    assert event["details"] == {"new_role": "team"}
    assert event["ip_address"] == "203.0.113.9"
    assert event["user_agent"] == "pytest-agent"
    assert isinstance(event["created_at"], datetime)
    assert event["created_at"].tzinfo is timezone.utc


async def test_record_admin_audit_event_defaults_when_request_is_none(stub_db):
    actor = {"_id": "actor-id", "email": "admin@example.com"}

    await record_admin_audit_event(stub_db, actor=actor, action="logout", target_type="session")

    event = stub_db["audit_events"].insert_one.call_args.args[0]
    assert event["ip_address"] == "unknown"
    assert event["user_agent"] == ""
    assert event["actor_role"] == "user"
