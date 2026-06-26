"""Application entrypoint that assembles the FastAPI app, lifecycle hooks, middleware, router registration, and database indexes."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from app.core.db import connect_to_mongo, close_mongo_connection, get_db
from app.core.auth import require_active_subscription
from app.routers.health import router as health_router
from app.routers.skills import router as skills_router
from app.routers.confirmations import router as confirmations_router
from app.routers.jobs import router as jobs_router
from app.routers.evidence import router as evidence_router
from app.routers.resumes import router as resumes_router
from app.routers.projects import router as projects_router
from app.routers.dashboard import router as dashboard_router
from app.routers.roles import router as roles_router
from app.routers.taxonomy import router as taxonomy_router
from app.routers.tailor import router as tailor_router
from app.routers.portfolio import router as portfolio_router
from app.routers.auth import router as auth_router
from app.routers.help import router as help_router
from app.routers.billing import router as billing_router
from app.routers.admin import router as admin_router
from app.routers.rewards import router as rewards_router
from app.core.config import settings
from app.utils.observability import configure_logging, emit_app_event, request_logging_middleware
from app.utils.ai import get_inference_status, release_local_models, warm_local_models
from app.utils.skill_catalog import normalize_skill_text
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime

def _sort_datetime(value):
    if isinstance(value, datetime):
        return value
    return datetime.min

async def normalize_learning_path_progress_records():
    db = get_db()
    collection = db["learning_path_progress"]
    if not hasattr(collection, "find"):
        return
    rows = await collection.find(
        {},
        {"_id": 1, "user_id": 1, "skill_name": 1, "skill_key": 1, "status": 1, "created_at": 1, "updated_at": 1},
    ).to_list(length=5000)

    grouped: dict[tuple[str, str], list[dict]] = {}
    invalid_ids: list[object] = []

    for row in rows:
        normalized_key = normalize_skill_text(row.get("skill_key") or row.get("skill_name"))
        if not normalized_key or row.get("user_id") is None:
            if row.get("_id") is not None:
                invalid_ids.append(row["_id"])
            continue
        grouped.setdefault((str(row.get("user_id")), normalized_key), []).append(row)

    if invalid_ids:
        await collection.delete_many({"_id": {"$in": invalid_ids}})

    for (_user_id, normalized_key), docs in grouped.items():
        docs.sort(
            key=lambda doc: (
                _sort_datetime(doc.get("updated_at")),
                _sort_datetime(doc.get("created_at")),
                str(doc.get("_id") or ""),
            ),
            reverse=True,
        )
        keeper = docs[0]
        if str(keeper.get("skill_key") or "") != normalized_key:
            await db["learning_path_progress"].update_one(
                {"_id": keeper["_id"]},
                {"$set": {"skill_key": normalized_key}},
            )
        stale_ids = [doc["_id"] for doc in docs[1:] if doc.get("_id") is not None]
        if stale_ids:
            await collection.delete_many({"_id": {"$in": stale_ids}})

async def ensure_indexes():
    # These indexes support the hot paths we exercise on every authenticated session:
    # login/session lookup, saved analyses, tailored resumes, and the derived RAG index.
    db = get_db()
    await db["users"].create_index("email", unique=True)
    await db["users"].create_index("username", unique=True)
    await db["sessions"].create_index("token", unique=True)
    await db["sessions"].create_index("expires_at", expireAfterSeconds=0)
    await db["password_reset_tokens"].create_index("token_hash", unique=True)
    await db["password_reset_tokens"].create_index("expires_at", expireAfterSeconds=0)
    await db["job_match_runs"].create_index([("user_id", 1), ("created_at", -1)])
    await db["tailored_resumes"].create_index([("user_id", 1), ("created_at", -1)])
    await db["rag_chunks"].create_index([("user_id", 1), ("source_type", 1), ("source_id", 1), ("chunk_index", 1)])
    await db["user_rewards"].create_index("user_id", unique=True)
    await db["billing_events"].create_index("event_id", unique=True)
    await db["request_rate_limits"].create_index("expires_at", expireAfterSeconds=0)
    await db["audit_events"].create_index([("created_at", -1), ("actor_id", 1), ("action", 1)])
    await db["jobs"].create_index("job_ingest_id", unique=True, sparse=True)
    await db["jobs"].create_index("moderation_status")
    await db["jobs"].create_index([("submitted_by_user_id", 1), ("created_at", -1)])
    await db["jobs"].create_index("role_ids")
    await db["project_skill_links"].create_index([("project_id", 1), ("skill_id", 1)], unique=True)
    await db["project_skill_links"].create_index("project_id")
    await normalize_learning_path_progress_records()
    await db["learning_path_progress"].create_index(
        [("user_id", 1), ("skill_key", 1)],
        unique=True,
        partialFilterExpression={"skill_key": {"$type": "string"}},
    )
    await db["resume_skill_confirmations"].create_index([("user_id", 1), ("scope_key", 1)], unique=True)
    await db["skill_relations"].create_index([("from_skill_id", 1), ("to_skill_id", 1), ("relation_type", 1)], unique=True)
    await db["evidence"].create_index([("user_id", 1), ("origin", 1), ("updated_at", -1)])
    await db["evidence"].create_index([("user_id", 1), ("structured_evidence", 1), ("updated_at", -1)])
    await db["help_requests"].create_index([("user_id", 1), ("created_at", -1)])
    await db["help_requests"].create_index([("status", 1), ("created_at", -1)])

def ensure_local_media_dirs():
    # User-uploaded avatars are served as local static files. The directory must
    # exist before requests arrive so uploads and static serving share one path.
    if settings.media_storage_mode_normalized == "local":
        settings.user_avatar_upload_path.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # FastAPI lifespan keeps startup/shutdown work in one place and avoids the
    # deprecated on_event hooks. This is the right place to connect the database,
    # materialize indexes, and optionally prewarm local ML models.
    configure_logging("DEBUG" if settings.app_env_normalized == "development" else "INFO")
    issues = settings.validate_runtime_settings()
    if issues:
        raise RuntimeError("Invalid runtime settings:\n- " + "\n- ".join(issues))
    emit_app_event(
        "app_startup",
        app_env=settings.app_env_normalized,
        mongo_db=settings.mongo_db,
        allowed_origins_count=len(settings.allowed_origins_list),
    )
    ensure_local_media_dirs()
    await connect_to_mongo()
    await ensure_indexes()
    if settings.local_model_prewarm:
        await warm_local_models()
    status = get_inference_status()
    emit_app_event(
        "ai_mode_ready",
        provider_mode=status["provider_mode"],
        embeddings_provider=status["embeddings_provider"],
        embedding_model=status["embedding_model"],
    )
    try:
        yield
    finally:
        emit_app_event("app_shutdown", app_env=settings.app_env_normalized)
        release_local_models()
        await close_mongo_connection()


app = FastAPI(title="SkillBridge API", version="0.5.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.middleware("http")(request_logging_middleware)

if settings.media_storage_mode_normalized == "local":
    settings.user_avatar_upload_path.parent.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=str(settings.user_avatar_upload_path.parent)), name="media")

app.include_router(health_router, prefix="/health", tags=["health"])
subscription_gate = [Depends(require_active_subscription)]

app.include_router(skills_router, prefix="/skills", tags=["skills"], dependencies=subscription_gate)
app.include_router(confirmations_router, prefix="/skills/confirmations", tags=["confirmations"], dependencies=subscription_gate)
app.include_router(jobs_router, prefix="/jobs", tags=["jobs"], dependencies=subscription_gate)
app.include_router(evidence_router, prefix="/evidence", tags=["evidence"], dependencies=subscription_gate)
app.include_router(resumes_router, prefix="/ingest/resume", tags=["resume"], dependencies=subscription_gate)
app.include_router(projects_router, prefix="/projects", tags=["projects"], dependencies=subscription_gate)
app.include_router(dashboard_router, prefix="/dashboard", tags=["dashboard"], dependencies=subscription_gate)
app.include_router(roles_router, prefix="/roles", tags=["roles"], dependencies=subscription_gate)
app.include_router(taxonomy_router, prefix="/taxonomy", tags=["taxonomy"], dependencies=subscription_gate)
app.include_router(tailor_router, prefix="/tailor", tags=["tailor"], dependencies=subscription_gate)
app.include_router(portfolio_router, prefix="/portfolio", tags=["portfolio"], dependencies=subscription_gate)
app.include_router(rewards_router, prefix="/rewards", tags=["rewards"])
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(help_router, prefix="/help", tags=["help"])
app.include_router(billing_router, prefix="/billing", tags=["billing"])
app.include_router(admin_router, prefix="/admin", tags=["admin"], dependencies=subscription_gate)
