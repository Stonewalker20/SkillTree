"""Smoke tests covering authentication flows and health endpoints."""

from types import SimpleNamespace
from pathlib import Path
import secrets

from bson import ObjectId

from app.core.auth import _pbkdf2, LEGACY_PBKDF2_ITERATIONS, PBKDF2_ITERATIONS
from app.core.config import settings
from app.utils.security import get_request_ip

def test_health_endpoints(test_context):
    client = test_context["client"]
    db = test_context["db"]

    assert client.get("/health/").json() == {"status": "ok"}

    locked = client.get("/health/db_counts", headers=test_context["headers"])
    assert locked.status_code == 403

    db["users"].docs[0]["role"] = "admin"
    counts = client.get("/health/db_counts", headers=test_context["headers"])
    assert counts.status_code == 200
    assert counts.json()["skills"] >= 2


def test_forwarded_headers_are_only_trusted_from_configured_proxies(monkeypatch):
    request = SimpleNamespace(
        headers={"x-forwarded-for": "8.8.8.8, 10.0.0.4", "x-real-ip": "1.1.1.1"},
        client=SimpleNamespace(host="10.1.2.3"),
    )

    assert get_request_ip(request) == "10.1.2.3"

    monkeypatch.setattr(settings, "trusted_proxy_cidrs", "10.0.0.0/8")
    trusted_request = SimpleNamespace(
        headers={"x-forwarded-for": "8.8.8.8, 10.0.0.4", "x-real-ip": "1.1.1.1"},
        client=SimpleNamespace(host="10.1.2.3"),
    )

    assert get_request_ip(trusted_request) == "8.8.8.8"


def test_auth_register_login_profile_and_logout(test_context):
    client = test_context["client"]
    register = client.post(
        "/auth/register",
        json={"email": "newuser@example.com", "username": "newuser", "password": "password123456789"},
    )
    assert register.status_code == 200
    token = register.json()["token"]
    assert register.json()["user"]["subscription_status"] == "inactive"

    login = client.post("/auth/login", json={"email": "newuser@example.com", "password": "password123456789"})
    assert login.status_code == 200
    auth_headers = {"Authorization": f"Bearer {login.json()['token']}"}

    me = client.get("/auth/me", headers=auth_headers)
    assert me.status_code == 200
    assert me.json()["username"] == "newuser"

    patch = client.patch("/auth/me", headers=auth_headers, json={"username": "renamed"})
    assert patch.status_code == 200
    assert patch.json()["username"] == "renamed"

    preset = client.patch("/auth/me", headers=auth_headers, json={"avatar_preset": "ember"})
    assert preset.status_code == 200
    assert preset.json()["avatar_preset"] == "ember"
    assert preset.json()["avatar_url"] is None

    locked_upload = client.post(
        "/auth/me/avatar",
        headers=auth_headers,
        files={"file": ("avatar.png", b"\x89PNG\r\n\x1a\nfake-image-content", "image/png")},
    )
    assert locked_upload.status_code == 402
    assert locked_upload.json()["detail"] == "Active subscription required for profile image uploads"

    activated = client.post("/auth/me/subscription", headers=auth_headers, json={"plan": "starter"})
    assert activated.status_code == 200
    assert activated.json()["subscription_plan"] == "starter"

    uploaded = client.post(
        "/auth/me/avatar",
        headers=auth_headers,
        files={"file": ("avatar.png", b"\x89PNG\r\n\x1a\nfake-image-content", "image/png")},
    )
    assert uploaded.status_code == 200
    first_avatar_url = uploaded.json()["avatar_url"]
    assert first_avatar_url.startswith("/media/avatars/")
    assert uploaded.json()["avatar_preset"] is None
    first_avatar_name = first_avatar_url.rsplit("/", 1)[-1]
    assert (Path(settings.user_avatar_upload_path) / first_avatar_name).exists()

    uploaded_again = client.post(
        "/auth/me/avatar",
        headers=auth_headers,
        files={"file": ("avatar.png", b"\x89PNG\r\n\x1a\nupdated-image-content", "image/png")},
    )
    assert uploaded_again.status_code == 200
    second_avatar_url = uploaded_again.json()["avatar_url"]
    assert second_avatar_url.startswith("/media/avatars/")
    assert second_avatar_url != first_avatar_url
    assert not (Path(settings.user_avatar_upload_path) / first_avatar_name).exists()
    assert (Path(settings.user_avatar_upload_path) / second_avatar_url.rsplit("/", 1)[-1]).exists()

    logout = client.post("/auth/logout", headers=auth_headers)
    assert logout.status_code == 200

    delete = client.delete("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert delete.status_code == 401


def test_login_succeeds_for_legacy_low_iteration_password_hash(test_context):
    # Accounts created before the PBKDF2 hardening pass have no "password_iterations" field
    # and their hash was computed at the old (lower) iteration count. Login must keep working
    # for them without forcing a password reset.
    client = test_context["client"]
    db = test_context["db"]

    assert PBKDF2_ITERATIONS > LEGACY_PBKDF2_ITERATIONS

    salt = secrets.token_hex(16)
    legacy_hash = _pbkdf2("legacy-password-123", salt, LEGACY_PBKDF2_ITERATIONS)
    db["users"].docs[0]["password_salt"] = salt
    db["users"].docs[0]["password_hash"] = legacy_hash
    db["users"].docs[0].pop("password_iterations", None)

    login = client.post(
        "/auth/login",
        json={"email": "tester@example.com", "password": "legacy-password-123"},
    )
    assert login.status_code == 200

    wrong = client.post(
        "/auth/login",
        json={"email": "tester@example.com", "password": "not-the-right-password"},
    )
    assert wrong.status_code == 401


def test_register_stores_current_pbkdf2_iteration_count(test_context):
    client = test_context["client"]
    db = test_context["db"]

    register = client.post(
        "/auth/register",
        json={"email": "freshaccount@example.com", "username": "freshaccount", "password": "password123456789"},
    )
    assert register.status_code == 200

    stored = next(doc for doc in db["users"].docs if doc["email"] == "freshaccount@example.com")
    assert stored["password_iterations"] == PBKDF2_ITERATIONS


def test_auth_register_defaults_to_user_for_admin_allowlisted_email(test_context, monkeypatch):
    client = test_context["client"]
    monkeypatch.setattr(settings, "admin_owner_emails", "owner@example.com")
    monkeypatch.setattr(settings, "admin_team_emails", "team@example.com")

    register = client.post(
        "/auth/register",
        json={"email": "owner@example.com", "username": "ownerish", "password": "password123456789"},
    )
    assert register.status_code == 200
    payload = register.json()
    assert payload["user"]["role"] == "user"


def test_subscription_activation_unlocks_core_routes(test_context):
    client = test_context["client"]
    register = client.post(
        "/auth/register",
        json={"email": "locked@example.com", "username": "lockeduser", "password": "password123456789"},
    )
    assert register.status_code == 200
    auth_headers = {"Authorization": f"Bearer {register.json()['token']}"}

    me = client.get("/auth/me", headers=auth_headers)
    assert me.status_code == 200
    assert me.json()["subscription_status"] == "inactive"

    locked_dashboard = client.get("/dashboard/summary", headers=auth_headers)
    assert locked_dashboard.status_code == 402
    assert locked_dashboard.json()["detail"] == "Subscription required"

    unlocked_rewards = client.get("/rewards/summary", headers=auth_headers)
    assert unlocked_rewards.status_code == 200
    assert unlocked_rewards.json()["total_count"] >= 1

    billing_status = client.get("/billing/status", headers=auth_headers)
    assert billing_status.status_code == 200
    assert [plan["key"] for plan in billing_status.json()["plans"]] == ["starter", "pro", "elite"]

    activated = client.post("/auth/me/subscription", headers=auth_headers, json={"plan": "elite"})
    assert activated.status_code == 200
    assert activated.json()["subscription_status"] == "active"
    assert activated.json()["subscription_plan"] == "elite"

    unlocked_dashboard = client.get("/dashboard/summary", headers=auth_headers)
    assert unlocked_dashboard.status_code == 200


def test_deactivated_user_cannot_login_or_use_existing_session(test_context):
    client = test_context["client"]
    db = test_context["db"]

    db["users"].docs[0]["is_active"] = False

    login = client.post("/auth/login", json={"email": "tester@example.com", "password": "password123"})
    assert login.status_code == 403
    assert login.json()["detail"] == "Account deactivated"

    me = client.get("/auth/me", headers=test_context["headers"])
    assert me.status_code == 401
    assert me.json()["detail"] == "Account deactivated"
    assert db["sessions"].docs == []


def test_password_change_verifies_current_password_and_rotates_session(test_context):
    client = test_context["client"]
    headers = test_context["headers"]

    wrong = client.post(
        "/auth/me/password",
        headers=headers,
        json={"current_password": "wrongpass123", "new_password": "newpassword123456"},
    )
    assert wrong.status_code == 401
    assert wrong.json()["detail"] == "Current password is incorrect"

    changed = client.post(
        "/auth/me/password",
        headers=headers,
        json={"current_password": "password123", "new_password": "newpassword123456"},
    )
    assert changed.status_code == 200
    changed_payload = changed.json()
    assert changed_payload["token"]
    assert changed_payload["user"]["email"] == "tester@example.com"

    stale_me = client.get("/auth/me", headers=headers)
    assert stale_me.status_code == 401

    new_headers = {"Authorization": f"Bearer {changed_payload['token']}"}
    fresh_me = client.get("/auth/me", headers=new_headers)
    assert fresh_me.status_code == 200

    old_login = client.post("/auth/login", json={"email": "tester@example.com", "password": "password123"})
    assert old_login.status_code == 401

    new_login = client.post("/auth/login", json={"email": "tester@example.com", "password": "newpassword123456"})
    assert new_login.status_code == 200


def test_password_reset_flow_rotates_credentials_and_sessions(test_context):
    client = test_context["client"]
    db = test_context["db"]
    original_headers = test_context["headers"]
    sent_password_reset_emails = test_context["sent_password_reset_emails"]

    request_reset = client.post("/auth/password-reset/request", json={"email": "tester@example.com"})
    assert request_reset.status_code == 200
    payload = request_reset.json()
    assert payload["ok"] is True
    assert payload["reset_url"].startswith(settings.public_app_url)
    assert len(db["password_reset_tokens"].docs) == 1
    assert len(sent_password_reset_emails) == 1
    assert sent_password_reset_emails[0]["recipient_email"] == "tester@example.com"

    reset_token = payload["reset_url"].split("token=", 1)[-1]
    confirm = client.post(
        "/auth/password-reset/confirm",
        json={"token": reset_token, "new_password": "renewedpass12345"},
    )
    assert confirm.status_code == 200
    assert confirm.json()["ok"] is True
    assert db["password_reset_tokens"].docs == []

    stale_me = client.get("/auth/me", headers=original_headers)
    assert stale_me.status_code == 401

    old_login = client.post("/auth/login", json={"email": "tester@example.com", "password": "password123"})
    assert old_login.status_code == 401

    new_login = client.post("/auth/login", json={"email": "tester@example.com", "password": "renewedpass12345"})
    assert new_login.status_code == 200


def test_password_reset_request_is_generic_for_unknown_email(test_context):
    client = test_context["client"]
    db = test_context["db"]
    sent_password_reset_emails = test_context["sent_password_reset_emails"]

    response = client.post("/auth/password-reset/request", json={"email": "missing@example.com"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["reset_url"] is None
    assert db["password_reset_tokens"].docs == []
    assert sent_password_reset_emails == []


def test_password_reset_token_cannot_be_reused(test_context):
    client = test_context["client"]

    request_reset = client.post("/auth/password-reset/request", json={"email": "tester@example.com"})
    token = request_reset.json()["reset_url"].split("token=", 1)[-1]

    first = client.post(
        "/auth/password-reset/confirm",
        json={"token": token, "new_password": "renewedpass12345"},
    )
    assert first.status_code == 200

    second = client.post(
        "/auth/password-reset/confirm",
        json={"token": token, "new_password": "anotherpass12345"},
    )
    assert second.status_code == 400
    assert second.json()["detail"] == "Invalid or expired reset token"


def test_auth_login_is_rate_limited_per_identity(test_context):
    client = test_context["client"]
    email = "tester@example.com"

    for _ in range(8):
        response = client.post("/auth/login", json={"email": email, "password": "wrong-password"})
        assert response.status_code == 401

    limited = client.post("/auth/login", json={"email": email, "password": "wrong-password"})
    assert limited.status_code == 429
    assert limited.json()["detail"] == "Rate limit exceeded"


def test_sessions_with_missing_expiry_are_rejected_and_removed(test_context):
    client = test_context["client"]
    db = test_context["db"]
    user_id = db["users"].docs[0]["_id"]
    session_id = ObjectId()
    db["sessions"].docs.append(
        {
            "_id": session_id,
            "user_id": user_id,
            "token": "missing-expiry-token",
            "created_at": db["sessions"].docs[0]["created_at"],
            "expires_at": None,
        }
    )

    response = client.get("/auth/me", headers={"Authorization": "Bearer missing-expiry-token"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid token"
    assert all(doc["token"] != "missing-expiry-token" for doc in db["sessions"].docs)
