from __future__ import annotations

from fastapi import APIRouter, Query, HTTPException
from datetime import datetime, timezone
from bson import ObjectId
from app.core.db import get_db
from app.models.evidence import EvidenceIn, EvidenceOut
from app.utils.mongo import oid_str

router = APIRouter()

def now_utc():
    return datetime.now(timezone.utc)

@router.get("/", response_model=list[EvidenceOut])
async def list_evidence(
    user_email: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
    skill_id: str | None = Query(default=None),
    project_id: str | None = Query(default=None),
):
    db = get_db()
    q: dict = {}
    if user_email:
        q["user_email"] = user_email
    if user_id:
        q["user_id"] = user_id
    if skill_id:
        q["skill_ids"] = skill_id
    if project_id:
        q["project_id"] = project_id

    cursor = db["evidence"].find(
        q,
        {
            "user_email": 1,
            "user_id": 1,
            "type": 1,
            "title": 1,
            "source": 1,
            "text_excerpt": 1,
            "skill_ids": 1,
            "project_id": 1,
            "tags": 1,
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
                "user_email": d.get("user_email"),
                "user_id": d.get("user_id"),
                "type": d["type"],
                "title": d["title"],
                "source": d["source"],
                "text_excerpt": d["text_excerpt"],
                "skill_ids": d.get("skill_ids", []),
                "project_id": d.get("project_id"),
                "tags": d.get("tags", []),
                "created_at": d.get("created_at"),
                "updated_at": d.get("updated_at"),
            }
        )
    return out

# UC 1.3 – Add evidence artifact and associate it with a skill/project
@router.post("/", response_model=EvidenceOut)
async def create_evidence(payload: EvidenceIn):
    db = get_db()

    if not payload.user_id and not payload.user_email:
        raise HTTPException(status_code=400, detail="Provide at least one of user_id or user_email")

    # Validate optional associations
    if payload.project_id:
        try:
            proj_oid = ObjectId(payload.project_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid project_id")
        if not await db["projects"].find_one({"_id": proj_oid}):
            raise HTTPException(status_code=404, detail="Project not found")

    for sid in payload.skill_ids:
        try:
            soid = ObjectId(sid)
        except Exception:
            raise HTTPException(status_code=400, detail=f"Invalid skill_id: {sid}")
        if not await db["skills"].find_one({"_id": soid}):
            raise HTTPException(status_code=404, detail=f"Skill not found: {sid}")

    doc = payload.model_dump()
    now = now_utc()
    doc["created_at"] = now
    doc["updated_at"] = now

    res = await db["evidence"].insert_one(doc)
    return {"id": oid_str(res.inserted_id), **doc}
