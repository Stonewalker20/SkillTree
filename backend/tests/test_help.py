"""Tests for the authenticated help-request routes (create, list mine, acknowledge)."""

from __future__ import annotations

from datetime import timedelta

from bson import ObjectId

from app.core.auth import now_utc


def _valid_payload(**overrides):
    payload = {
        "category": "billing",
        "subject": "Cannot update payment method",
        "message": "I tried updating my card on file but the form keeps rejecting it.",
        "page": "/billing",
    }
    payload.update(overrides)
    return payload


def test_create_help_request_persists_and_returns_doc(test_context):
    client = test_context["client"]
    db = test_context["db"]
    user_id = test_context["user_id"]

    response = client.post("/help/requests", headers=test_context["headers"], json=_valid_payload())
    assert response.status_code == 200

    body = response.json()
    assert body["user_id"] == user_id
    assert body["category"] == "billing"
    assert body["subject"] == "Cannot update payment method"
    assert body["page"] == "/billing"
    assert body["status"] == "open"
    assert body["admin_response"] is None
    assert body["user_has_unread_response"] is False
    assert body["admin_responded_at"] is None
    assert body["user_acknowledged_response_at"] is None
    assert body["created_at"] is not None
    assert body["id"]

    assert len(db["help_requests"].docs) == 1
    stored = db["help_requests"].docs[0]
    assert stored["user_id"] == ObjectId(user_id)
    assert stored["status"] == "open"
    assert stored["user_email_snapshot"] == "tester@example.com"
    assert stored["username_snapshot"] == "tester"


def test_create_help_request_omits_optional_page(test_context):
    client = test_context["client"]
    payload = _valid_payload()
    del payload["page"]

    response = client.post("/help/requests", headers=test_context["headers"], json=payload)
    assert response.status_code == 200
    assert response.json()["page"] is None


def test_create_help_request_rejects_short_message(test_context):
    client = test_context["client"]
    response = client.post(
        "/help/requests",
        headers=test_context["headers"],
        json=_valid_payload(message="too short"),
    )
    assert response.status_code == 422


def test_create_help_request_requires_auth(test_context):
    client = test_context["client"]
    response = client.post("/help/requests", json=_valid_payload())
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing bearer token"


def test_list_my_help_requests_returns_only_own_sorted_desc(test_context):
    client = test_context["client"]
    db = test_context["db"]
    user_oid = ObjectId(test_context["user_id"])
    other_user_oid = ObjectId()
    now = now_utc()

    db["help_requests"].docs = [
        {
            "_id": ObjectId(),
            "user_id": user_oid,
            "category": "billing",
            "subject": "Older request",
            "message": "This request was submitted earlier than the other one.",
            "page": None,
            "status": "open",
            "admin_response": None,
            "user_has_unread_response": False,
            "admin_responded_at": None,
            "user_acknowledged_response_at": None,
            "created_at": now - timedelta(days=2),
            "updated_at": now - timedelta(days=2),
        },
        {
            "_id": ObjectId(),
            "user_id": user_oid,
            "category": "bug",
            "subject": "Newer request",
            "message": "This request was submitted more recently than the other one.",
            "page": None,
            "status": "open",
            "admin_response": None,
            "user_has_unread_response": False,
            "admin_responded_at": None,
            "user_acknowledged_response_at": None,
            "created_at": now - timedelta(hours=1),
            "updated_at": now - timedelta(hours=1),
        },
        {
            "_id": ObjectId(),
            "user_id": other_user_oid,
            "category": "billing",
            "subject": "Someone else's request",
            "message": "This belongs to a different user and must not be returned.",
            "page": None,
            "status": "open",
            "admin_response": None,
            "user_has_unread_response": False,
            "admin_responded_at": None,
            "user_acknowledged_response_at": None,
            "created_at": now,
            "updated_at": now,
        },
    ]

    response = client.get("/help/requests/mine", headers=test_context["headers"])
    assert response.status_code == 200
    body = response.json()
    assert [item["subject"] for item in body] == ["Newer request", "Older request"]
    assert all(item["user_id"] == test_context["user_id"] for item in body)


def test_acknowledge_help_request_clears_unread_and_updates_user_count(test_context):
    client = test_context["client"]
    db = test_context["db"]
    user_oid = ObjectId(test_context["user_id"])
    target_id = ObjectId()
    now = now_utc()

    db["help_requests"].docs = [
        {
            "_id": target_id,
            "user_id": user_oid,
            "category": "billing",
            "subject": "Needs acknowledgement",
            "message": "An admin responded to this request and it is awaiting acknowledgement.",
            "page": None,
            "status": "resolved",
            "admin_response": "Refund issued, let us know if you have questions.",
            "user_has_unread_response": True,
            "admin_responded_at": now,
            "user_acknowledged_response_at": None,
            "created_at": now - timedelta(days=1),
            "updated_at": now,
        },
        {
            "_id": ObjectId(),
            "user_id": user_oid,
            "category": "bug",
            "subject": "Still unread",
            "message": "A second unread response that should still count afterwards.",
            "page": None,
            "status": "resolved",
            "admin_response": "Fixed in the latest release.",
            "user_has_unread_response": True,
            "admin_responded_at": now,
            "user_acknowledged_response_at": None,
            "created_at": now,
            "updated_at": now,
        },
    ]

    response = client.post(
        f"/help/requests/{target_id}/acknowledge",
        headers=test_context["headers"],
    )
    assert response.status_code == 200
    body = response.json()
    assert body["user_has_unread_response"] is False
    assert body["user_acknowledged_response_at"] is not None
    assert body["admin_response"] == "Refund issued, let us know if you have questions."

    acknowledged = next(doc for doc in db["help_requests"].docs if doc["_id"] == target_id)
    assert acknowledged["user_has_unread_response"] is False
    assert acknowledged["user_acknowledged_response_at"] is not None

    assert db["users"].docs[0]["help_unread_response_count"] == 1


def test_acknowledge_help_request_invalid_id_returns_400(test_context):
    client = test_context["client"]
    response = client.post(
        "/help/requests/not-an-object-id/acknowledge",
        headers=test_context["headers"],
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid request_id"


def test_acknowledge_help_request_missing_returns_404(test_context):
    client = test_context["client"]
    response = client.post(
        f"/help/requests/{ObjectId()}/acknowledge",
        headers=test_context["headers"],
    )
    assert response.status_code == 404


def test_acknowledge_help_request_belonging_to_other_user_returns_404(test_context):
    client = test_context["client"]
    db = test_context["db"]
    other_request_id = ObjectId()
    now = now_utc()

    db["help_requests"].docs = [
        {
            "_id": other_request_id,
            "user_id": ObjectId(),
            "category": "billing",
            "subject": "Not yours",
            "message": "This help request belongs to a different account entirely.",
            "page": None,
            "status": "resolved",
            "admin_response": "Handled.",
            "user_has_unread_response": True,
            "admin_responded_at": now,
            "user_acknowledged_response_at": None,
            "created_at": now,
            "updated_at": now,
        }
    ]

    response = client.post(
        f"/help/requests/{other_request_id}/acknowledge",
        headers=test_context["headers"],
    )
    assert response.status_code == 404
