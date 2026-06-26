"""Shared pytest fixtures, fake services, and seeded backend state for contract and smoke tests."""

from __future__ import annotations

from pathlib import Path
import sys
from datetime import timedelta

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import app
from app.core import db as core_db
from app.core.auth import hash_password, now_utc
from app.core.config import settings
from app.routers import evidence as evidence_router
from app.routers import tailor as tailor_router
from app.routers import taxonomy as taxonomy_router
from app.routers import auth as auth_router

from .fake_mongo import FakeDatabase, FakeMongoClient


def _fake_embed_texts(texts: list[str], preferences: dict | None = None):
    vectors = []
    for text in texts:
        lower = str(text or "").lower()
        vector = [
            1.0 if "python" in lower else 0.0,
            1.0 if "ml" in lower or "machine learning" in lower else 0.0,
            1.0 if "fastapi" in lower or "api" in lower else 0.0,
            1.0 if "dashboard" in lower or "analytics" in lower else 0.0,
        ]
        vectors.append(vector)
    return vectors, "test-embed"


async def _async_fake_embed_texts(texts: list[str], preferences: dict | None = None):
    return _fake_embed_texts(texts, preferences=preferences)


async def _async_fake_extract_skill_candidates(text: str, max_candidates: int = 25, preferences: dict | None = None):
    lower = str(text or "").lower()
    candidates = []
    if "python" in lower:
        candidates.append({"name": "Python", "category": "Programming"})
    if "machine learning" in lower or "ml" in lower:
        candidates.append({"name": "ML", "category": "Data"})
    if "fastapi" in lower:
        candidates.append({"name": "FastAPI", "category": "Backend"})
    return candidates[:max_candidates], "test-transformer"


async def _async_fake_rewrite(job_text: str, bullets: list[str], focus: str, preferences: dict | None = None):
    return [f"- Rewritten ({focus}): {bullet[2:] if bullet.startswith('- ') else bullet}" for bullet in bullets], "test-rewriter"


def _seed(fake_db: FakeDatabase):
    user_id = ObjectId()
    skill_python = ObjectId()
    skill_ml = ObjectId()
    role_id = ObjectId()
    session_id = ObjectId()
    password_parts = hash_password("password123")
    seeded_now = now_utc()

    fake_db["users"].docs = [
        {
            "_id": user_id,
            "email": "tester@example.com",
            "username": "tester",
            "password_salt": password_parts["salt"],
            "password_hash": password_parts["hash"],
            "password_iterations": password_parts["iterations"],
            "role": "user",
            "subscription_status": "active",
            "subscription_plan": "pro",
            "subscription_started_at": seeded_now,
            "subscription_renewal_at": seeded_now + timedelta(days=30),
            "created_at": seeded_now,
        }
    ]
    fake_db["sessions"].docs = [
        {
            "_id": session_id,
            "user_id": user_id,
            "token": "test-token",
            "created_at": seeded_now,
            "expires_at": seeded_now + timedelta(days=30),
        }
    ]
    fake_db["skills"].docs = [
        {
            "_id": skill_python,
            "name": "Python",
            "category": "Programming",
            "categories": ["Programming"],
            "aliases": ["Py"],
            "tags": ["language"],
            "origin": "default",
            "hidden": False,
            "created_at": seeded_now,
            "updated_at": seeded_now,
        },
        {
            "_id": skill_ml,
            "name": "ML",
            "category": "Data",
            "categories": ["Data"],
            "aliases": ["Machine Learning"],
            "tags": ["ai"],
            "origin": "default",
            "hidden": False,
            "created_at": seeded_now,
            "updated_at": seeded_now,
        },
    ]
    fake_db["roles"].docs = [
        {
            "_id": role_id,
            "name": "ML Engineer",
            "description": "Build ML systems",
            "created_at": seeded_now,
            "updated_at": seeded_now,
        }
    ]
    fake_db["role_skill_weights"].docs = [
        {
            "_id": ObjectId(),
            "role_id": role_id,
            "role_name": "ML Engineer",
            "computed_at": seeded_now,
            "weights": [
                {"skill_id": str(skill_python), "skill_name": "Python", "weight": 0.9},
                {"skill_id": str(skill_ml), "skill_name": "ML", "weight": 1.0},
            ],
        }
    ]
    return {
        "user_id": str(user_id),
        "token": "test-token",
        "skill_python": str(skill_python),
        "skill_ml": str(skill_ml),
        "role_id": str(role_id),
    }


@pytest.fixture()
def test_context(monkeypatch):
    fake_db = FakeDatabase()
    seeded = _seed(fake_db)
    core_db._client = FakeMongoClient(fake_db)
    avatar_dir = Path(__file__).resolve().parent / ".tmp_avatars"
    avatar_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "user_avatar_upload_dir", str(avatar_dir))

    async def _noop():
        return None

    monkeypatch.setattr("app.main.connect_to_mongo", _noop)
    monkeypatch.setattr("app.main.close_mongo_connection", _noop)
    monkeypatch.setattr("app.main.ensure_indexes", _noop)
    monkeypatch.setattr("app.main.warm_local_models", _noop)
    monkeypatch.setattr(
        "app.main.get_inference_status",
        lambda *_args, **_kwargs: {
            "provider_mode": "test",
            "embeddings_provider": "test",
            "rewrite_provider": "test",
            "embedding_model": "fake-embed",
            "rewrite_model": "fake-rewriter",
        },
    )
    monkeypatch.setattr("app.main.settings.local_model_prewarm", False)
    sent_password_reset_emails: list[dict[str, str]] = []
    monkeypatch.setattr(auth_router, "password_reset_email_enabled", lambda: True)
    monkeypatch.setattr(
        auth_router,
        "send_password_reset_email",
        lambda recipient_email, reset_url, username=None: sent_password_reset_emails.append(
            {"recipient_email": recipient_email, "reset_url": reset_url, "username": username or ""}
        ),
    )
    monkeypatch.setattr(evidence_router, "extract_skill_candidates", _async_fake_extract_skill_candidates)
    monkeypatch.setattr(evidence_router, "embed_texts", _async_fake_embed_texts)
    monkeypatch.setattr(tailor_router, "embed_texts", _async_fake_embed_texts)
    monkeypatch.setattr(taxonomy_router, "embed_texts", _async_fake_embed_texts)
    monkeypatch.setattr(tailor_router, "rewrite_resume_bullets", _async_fake_rewrite)
    monkeypatch.setattr(
        tailor_router,
        "get_inference_status",
        lambda *_args, **_kwargs: {
            "provider_mode": "test",
            "embeddings_provider": "test",
            "rewrite_provider": "test",
            "embedding_model": "fake-embed",
            "rewrite_model": "fake-rewriter",
        },
    )

    with TestClient(app) as client:
        yield {
            "client": client,
            "db": fake_db,
            "headers": {"Authorization": f"Bearer {seeded['token']}"},
            "sent_password_reset_emails": sent_password_reset_emails,
            **seeded,
        }

    core_db._client = None
