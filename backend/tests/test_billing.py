"""Coverage for Stripe-ready checkout, billing portal, and webhook handling in app/routers/billing.py.

Stripe itself is never called in these tests. A small fake SDK is monkeypatched onto
`app.routers.billing.stripe_sdk` so the route logic (customer creation, session creation,
webhook event handling, and the persisted user billing fields) is exercised end to end
against the in-memory fake Mongo without any network access.
"""

from __future__ import annotations

from types import SimpleNamespace

from bson import ObjectId

from app.core.config import settings
from app.routers import billing as billing_router


class _FakeStripeAPI:
    """Generic `create()`-returning stub for a single Stripe sub-resource (Customer, Session, ...)."""

    def __init__(self, prefix: str, extra_defaults: dict | None = None):
        self.prefix = prefix
        self.extra_defaults = extra_defaults or {}
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        payload = {**self.extra_defaults, **kwargs, "id": f"{self.prefix}_{len(self.calls)}"}
        return SimpleNamespace(**payload)


class _FakeWebhookAPI:
    def __init__(self, event: dict | None = None, error: Exception | None = None):
        self.event = event
        self.error = error
        self.calls: list[tuple] = []

    def construct_event(self, raw_body, signature, secret):
        self.calls.append((raw_body, signature, secret))
        if self.error is not None:
            raise self.error
        return self.event


def _install_fake_stripe(monkeypatch, *, webhook_event: dict | None = None, webhook_error: Exception | None = None):
    fake = SimpleNamespace(
        api_key=None,
        Customer=_FakeStripeAPI("cus"),
        checkout=SimpleNamespace(Session=_FakeStripeAPI("cs", {"url": "https://stripe.test/checkout"})),
        billing_portal=SimpleNamespace(Session=_FakeStripeAPI("bps", {"url": "https://stripe.test/portal"})),
        Webhook=_FakeWebhookAPI(event=webhook_event, error=webhook_error),
    )
    monkeypatch.setattr(billing_router, "stripe_sdk", fake)
    return fake


def _configure_stripe(monkeypatch, *, secret_key: str = "sk_test_123", price_id_pro: str = "price_pro_123"):
    monkeypatch.setattr(settings, "stripe_secret_key", secret_key)
    monkeypatch.setattr(settings, "stripe_price_id_pro", price_id_pro)


def _register_inactive_user(client, *, email: str, username: str) -> dict:
    response = client.post(
        "/auth/register",
        json={"email": email, "username": username, "password": "password123456789"},
    )
    assert response.status_code == 200
    body = response.json()
    return {"token": body["token"], "user_id": body["user"]["id"], "headers": {"Authorization": f"Bearer {body['token']}"}}


def test_billing_status_unconfigured_lists_all_plans(test_context, monkeypatch):
    client = test_context["client"]
    monkeypatch.setattr(settings, "stripe_secret_key", "")
    monkeypatch.setattr(billing_router, "stripe_sdk", None)

    response = client.get("/billing/status", headers=test_context["headers"])

    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is False
    assert body["mode"] == "mock"
    assert [plan["key"] for plan in body["plans"]] == ["starter", "pro", "elite"]
    assert all(plan["checkout_available"] is False for plan in body["plans"])


def test_checkout_unconfigured_returns_unavailable(test_context, monkeypatch):
    client = test_context["client"]
    monkeypatch.setattr(settings, "stripe_secret_key", "")
    monkeypatch.setattr(billing_router, "stripe_sdk", None)
    fresh = _register_inactive_user(client, email="nostripe@example.com", username="nostripe")

    response = client.post("/billing/checkout", headers=fresh["headers"], json={"plan": "pro"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["mode"] == "mock"
    assert body["dev_fallback_available"] is True


def test_checkout_already_active_subscriber_short_circuits(test_context, monkeypatch):
    # The default seeded test_context user already has an active "pro" subscription.
    client = test_context["client"]
    _configure_stripe(monkeypatch)
    fake_stripe = _install_fake_stripe(monkeypatch)

    response = client.post("/billing/checkout", headers=test_context["headers"], json={"plan": "elite"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "already_active"
    assert body["plan"] == "pro"
    # No Stripe call should happen once the user already has access.
    assert fake_stripe.Customer.calls == []
    assert fake_stripe.checkout.Session.calls == []


def test_checkout_creates_stripe_session_and_persists_customer(test_context, monkeypatch):
    client = test_context["client"]
    _configure_stripe(monkeypatch)
    fake_stripe = _install_fake_stripe(monkeypatch)
    fresh = _register_inactive_user(client, email="newcustomer@example.com", username="newcustomer")

    response = client.post("/billing/checkout", headers=fresh["headers"], json={"plan": "pro"})

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "stripe"
    assert body["status"] == "created"
    assert body["checkout_url"] == "https://stripe.test/checkout"
    assert body["session_id"] == "cs_1"
    assert body["customer_id"] == "cus_1"
    assert len(fake_stripe.Customer.calls) == 1
    assert fake_stripe.Customer.calls[0]["email"] == "newcustomer@example.com"

    stored_user = next(
        doc for doc in test_context["db"]["users"].docs if doc["_id"] == ObjectId(fresh["user_id"])
    )
    assert stored_user["stripe_customer_id"] == "cus_1"
    assert stored_user["stripe_checkout_session_id"] == "cs_1"
    assert stored_user["billing_provider"] == "stripe"


def test_checkout_invalid_plan_rejected(test_context, monkeypatch):
    client = test_context["client"]
    _configure_stripe(monkeypatch)
    _install_fake_stripe(monkeypatch)
    fresh = _register_inactive_user(client, email="badplan@example.com", username="badplan")

    response = client.post("/billing/checkout", headers=fresh["headers"], json={"plan": "ultimate"})

    assert response.status_code == 400


def test_billing_portal_unavailable_without_customer_id(test_context, monkeypatch):
    client = test_context["client"]
    _configure_stripe(monkeypatch)
    _install_fake_stripe(monkeypatch)
    fresh = _register_inactive_user(client, email="noportal@example.com", username="noportal")

    response = client.post("/billing/portal", headers=fresh["headers"])

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["portal_url"] is None


def test_billing_portal_creates_session_for_existing_customer(test_context, monkeypatch):
    client = test_context["client"]
    _configure_stripe(monkeypatch)
    fake_stripe = _install_fake_stripe(monkeypatch)
    fresh = _register_inactive_user(client, email="hascustomer@example.com", username="hascustomer")
    test_context["db"]["users"].docs[
        [doc["_id"] for doc in test_context["db"]["users"].docs].index(ObjectId(fresh["user_id"]))
    ]["stripe_customer_id"] = "cus_existing"

    response = client.post("/billing/portal", headers=fresh["headers"])

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "created"
    assert body["portal_url"] == "https://stripe.test/portal"
    assert body["customer_id"] == "cus_existing"
    assert fake_stripe.billing_portal.Session.calls[0]["customer"] == "cus_existing"


def test_webhook_noop_when_secret_not_configured(test_context, monkeypatch):
    client = test_context["client"]
    monkeypatch.setattr(settings, "stripe_webhook_secret", "")
    monkeypatch.setattr(billing_router, "stripe_sdk", None)

    response = client.post("/billing/webhook", content=b"{}", headers={"stripe-signature": "irrelevant"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "noop"
    assert body["received"] is True


def test_webhook_invalid_signature_returns_400(test_context, monkeypatch):
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test")
    _install_fake_stripe(monkeypatch, webhook_error=ValueError("bad signature"))
    client = test_context["client"]

    response = client.post("/billing/webhook", content=b"{}", headers={"stripe-signature": "bad"})

    assert response.status_code == 400
    assert "Invalid Stripe webhook signature" in response.json()["detail"]


def test_webhook_checkout_completed_activates_subscription(test_context, monkeypatch):
    client = test_context["client"]
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test")
    fresh = _register_inactive_user(client, email="webhookuser@example.com", username="webhookuser")

    event = {
        "id": "evt_1",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_remote_1",
                "customer": "cus_remote_1",
                "subscription": "sub_remote_1",
                "client_reference_id": fresh["user_id"],
                "metadata": {"plan": "elite"},
            }
        },
    }
    _install_fake_stripe(monkeypatch, webhook_event=event)

    response = client.post("/billing/webhook", content=b"{}", headers={"stripe-signature": "valid"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"
    assert body["event_type"] == "checkout.session.completed"

    stored_user = next(
        doc for doc in test_context["db"]["users"].docs if doc["_id"] == ObjectId(fresh["user_id"])
    )
    assert stored_user["subscription_status"] == "active"
    assert stored_user["subscription_plan"] == "elite"
    assert stored_user["stripe_customer_id"] == "cus_remote_1"
    assert stored_user["stripe_subscription_id"] == "sub_remote_1"

    webhook_events = test_context["db"]["billing_events"].docs
    assert any(doc["event_id"] == "evt_1" and doc["handled"] is True for doc in webhook_events)


def test_webhook_subscription_deleted_deactivates_user(test_context, monkeypatch):
    client = test_context["client"]
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test")
    fresh = _register_inactive_user(client, email="cancelme@example.com", username="cancelme")
    user_index = [doc["_id"] for doc in test_context["db"]["users"].docs].index(ObjectId(fresh["user_id"]))
    test_context["db"]["users"].docs[user_index].update(
        {
            "subscription_status": "active",
            "subscription_plan": "pro",
            "stripe_customer_id": "cus_remote_2",
            "stripe_subscription_id": "sub_remote_2",
        }
    )

    event = {
        "id": "evt_2",
        "type": "customer.subscription.deleted",
        "data": {"object": {"id": "sub_remote_2", "customer": "cus_remote_2"}},
    }
    _install_fake_stripe(monkeypatch, webhook_event=event)

    response = client.post("/billing/webhook", content=b"{}", headers={"stripe-signature": "valid"})

    assert response.status_code == 200
    assert response.json()["status"] == "processed"

    stored_user = test_context["db"]["users"].docs[user_index]
    assert stored_user["subscription_status"] == "inactive"
    assert stored_user["subscription_plan"] is None


def test_webhook_unknown_customer_is_ignored(test_context, monkeypatch):
    client = test_context["client"]
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test")
    event = {
        "id": "evt_3",
        "type": "customer.subscription.updated",
        "data": {"object": {"id": "sub_unknown", "customer": "cus_unknown"}},
    }
    _install_fake_stripe(monkeypatch, webhook_event=event)

    response = client.post("/billing/webhook", content=b"{}", headers={"stripe-signature": "valid"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ignored"

    webhook_events = test_context["db"]["billing_events"].docs
    assert any(doc["event_id"] == "evt_3" and doc["handled"] is False for doc in webhook_events)
