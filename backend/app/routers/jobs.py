from __future__ import annotations

from fastapi import APIRouter, Query, HTTPException
from datetime import datetime, timezone
from bson import ObjectId
from app.core.db import get_db
from app.models.job import JobIn, JobOut, JobModerationIn, JobRoleTagIn
from app.utils.mongo import oid_str

router = APIRouter()

def now_utc():
    return datetime.now(timezone.utc)

@router.get("/", response_model=list[JobOut])
async def list_jobs(
    status: str | None = Query(default=None, description="pending|approved|rejected"),
    role_id: str | None = Query(default=None),
):
    db = get_db()
    q: dict = {}
    if status:
        q["moderation_status"] = status
    if role_id:
        q["role_ids"] = role_id

    cursor = db["jobs"].find(
        q,
        {
            "title": 1,
            "company": 1,
            "location": 1,
            "source": 1,
            "description_excerpt": 1,
            "required_skills": 1,
            "required_skill_ids": 1,
            "role_ids": 1,
            "moderation_status": 1,
            "moderation_reason": 1,
            "submitted_by_user_id": 1,
            "created_at": 1,
            "updated_at": 1,
        },
    ).sort("created_at", -1)

    docs = await cursor.to_list(length=500)
    out = []
    for d in docs:
        out.append(
            {
                "id": oid_str(d["_id"]),
                "title": d.get("title", ""),
                "company": d.get("company", ""),
                "location": d.get("location", ""),
                "source": d.get("source", ""),
                "description_excerpt": d.get("description_excerpt", ""),
                "required_skills": d.get("required_skills", []),
                "required_skill_ids": d.get("required_skill_ids", []),
                "role_ids": d.get("role_ids", []),
                "moderation_status": d.get("moderation_status", "approved"),
                "moderation_reason": d.get("moderation_reason"),
                "submitted_by_user_id": d.get("submitted_by_user_id"),
                "created_at": d.get("created_at"),
                "updated_at": d.get("updated_at"),
            }
        )
    return out

# Community submission (defaults to pending)
@router.post("/submit", response_model=JobOut)
async def submit_job(payload: JobIn):
    db = get_db()
    now = now_utc()
    doc = payload.model_dump()
    doc["moderation_status"] = "pending"
    doc["moderation_reason"] = None
    doc["created_at"] = now
    doc["updated_at"] = now
    res = await db["jobs"].insert_one(doc)
    return {"id": oid_str(res.inserted_id), **doc}

# Direct create (admin/system) defaults to approved (keeps your original POST /jobs behavior but safer)
@router.post("/", response_model=JobOut)
async def create_job(payload: JobIn):
    db = get_db()
    now = now_utc()
    doc = payload.model_dump()
    doc["moderation_status"] = "approved"
    doc["moderation_reason"] = None
    doc["created_at"] = now
    doc["updated_at"] = now
    res = await db["jobs"].insert_one(doc)
    return {"id": oid_str(res.inserted_id), **doc}

# UC 4.1 – Moderate job postings (approve/reject)
@router.patch("/{job_id}/moderate", response_model=JobOut)
async def moderate_job(job_id: str, payload: JobModerationIn):
    db = get_db()
    try:
        oid = ObjectId(job_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid job_id")

    updates = {
        "moderation_status": payload.moderation_status,
        "moderation_reason": payload.moderation_reason,
        "updated_at": now_utc(),
    }
    res = await db["jobs"].update_one({"_id": oid}, {"$set": updates})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Job not found")

    d = await db["jobs"].find_one({"_id": oid})
    return {
        "id": oid_str(d["_id"]),
        "title": d.get("title", ""),
        "company": d.get("company", ""),
        "location": d.get("location", ""),
        "source": d.get("source", ""),
        "description_excerpt": d.get("description_excerpt", ""),
        "required_skills": d.get("required_skills", []),
        "required_skill_ids": d.get("required_skill_ids", []),
        "role_ids": d.get("role_ids", []),
        "moderation_status": d.get("moderation_status", "pending"),
        "moderation_reason": d.get("moderation_reason"),
        "submitted_by_user_id": d.get("submitted_by_user_id"),
        "created_at": d.get("created_at"),
        "updated_at": d.get("updated_at"),
    }

# UC 4.2 – Tag a posting by role (role_id)
@router.post("/{job_id}/roles", response_model=JobOut)
async def add_role_tag(job_id: str, payload: JobRoleTagIn):
    db = get_db()
    try:
        oid = ObjectId(job_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid job_id")
    try:
        role_oid = ObjectId(payload.role_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid role_id")

    if not await db["roles"].find_one({"_id": role_oid}):
        raise HTTPException(status_code=404, detail="Role not found")

    await db["jobs"].update_one({"_id": oid}, {"$addToSet": {"role_ids": payload.role_id}, "$set": {"updated_at": now_utc()}})
    d = await db["jobs"].find_one({"_id": oid})
    if not d:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "id": oid_str(d["_id"]),
        "title": d.get("title", ""),
        "company": d.get("company", ""),
        "location": d.get("location", ""),
        "source": d.get("source", ""),
        "description_excerpt": d.get("description_excerpt", ""),
        "required_skills": d.get("required_skills", []),
        "required_skill_ids": d.get("required_skill_ids", []),
        "role_ids": d.get("role_ids", []),
        "moderation_status": d.get("moderation_status", "pending"),
        "moderation_reason": d.get("moderation_reason"),
        "submitted_by_user_id": d.get("submitted_by_user_id"),
        "created_at": d.get("created_at"),
        "updated_at": d.get("updated_at"),
    }
