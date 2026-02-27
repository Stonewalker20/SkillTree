from __future__ import annotations

from fastapi import APIRouter, Query, HTTPException
from datetime import datetime, timezone
from bson import ObjectId
from app.core.db import get_db
from app.utils.mongo import oid_str
from app.models.project import (
    ProjectIn,
    ProjectOut,
    ProjectSkillLinkIn,
    ProjectSkillLinkOut,
)

router = APIRouter()

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

@router.get("/", response_model=list[ProjectOut])
async def list_projects(user_id: str | None = Query(default=None)):
    db = get_db()
    q = {}
    if user_id:
        q["user_id"] = user_id
    docs = await db["projects"].find(q).sort("created_at", -1).to_list(length=500)
    out = []
    for d in docs:
        out.append(
            {
                "id": oid_str(d["_id"]),
                "user_id": d.get("user_id", ""),
                "title": d.get("title", ""),
                "description": d.get("description", ""),
                "start_date": d.get("start_date"),
                "end_date": d.get("end_date"),
                "tags": d.get("tags", []),
                "created_at": d.get("created_at"),
                "updated_at": d.get("updated_at"),
            }
        )
    return out

@router.post("/", response_model=ProjectOut)
async def create_project(payload: ProjectIn):
    db = get_db()
    now = now_utc()
    doc = payload.model_dump()
    doc["created_at"] = now
    doc["updated_at"] = now
    res = await db["projects"].insert_one(doc)
    return {"id": oid_str(res.inserted_id), **doc}

@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(project_id: str):
    db = get_db()
    try:
        oid = ObjectId(project_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid project_id")
    d = await db["projects"].find_one({"_id": oid})
    if not d:
        raise HTTPException(status_code=404, detail="Project not found")
    return {
        "id": oid_str(d["_id"]),
        "user_id": d.get("user_id", ""),
        "title": d.get("title", ""),
        "description": d.get("description", ""),
        "start_date": d.get("start_date"),
        "end_date": d.get("end_date"),
        "tags": d.get("tags", []),
        "created_at": d.get("created_at"),
        "updated_at": d.get("updated_at"),
    }

# UC 1.2 – Link skill to project
@router.post("/{project_id}/skills", response_model=ProjectSkillLinkOut)
async def link_skill_to_project(project_id: str, payload: ProjectSkillLinkIn):
    db = get_db()
    try:
        project_oid = ObjectId(project_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid project_id")
    try:
        skill_oid = ObjectId(payload.skill_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid skill_id")

    if not await db["projects"].find_one({"_id": project_oid}):
        raise HTTPException(status_code=404, detail="Project not found")
    if not await db["skills"].find_one({"_id": skill_oid}):
        raise HTTPException(status_code=404, detail="Skill not found")

    # upsert link
    q = {"project_id": project_oid, "skill_id": skill_oid}
    existing = await db["project_skill_links"].find_one(q)
    if existing:
        return {
            "id": oid_str(existing["_id"]),
            "project_id": oid_str(existing["project_id"]),
            "skill_id": oid_str(existing["skill_id"]),
            "created_at": existing.get("created_at"),
        }

    doc = {**q, "created_at": now_utc()}
    res = await db["project_skill_links"].insert_one(doc)
    return {
        "id": oid_str(res.inserted_id),
        "project_id": project_id,
        "skill_id": payload.skill_id,
        "created_at": doc["created_at"],
    }

@router.get("/{project_id}/skills", response_model=list[dict])
async def list_project_skills(project_id: str):
    db = get_db()
    try:
        project_oid = ObjectId(project_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid project_id")

    pipeline = [
        {"$match": {"project_id": project_oid}},
        {
            "$lookup": {
                "from": "skills",
                "localField": "skill_id",
                "foreignField": "_id",
                "as": "skill",
            }
        },
        {"$unwind": {"path": "$skill", "preserveNullAndEmptyArrays": True}},
        {
            "$project": {
                "_id": 1,
                "project_id": 1,
                "skill_id": 1,
                "created_at": 1,
                "skill_name": "$skill.name",
                "skill_category": "$skill.category",
            }
        },
    ]
    rows = await db["project_skill_links"].aggregate(pipeline).to_list(length=500)
    for r in rows:
        r["id"] = oid_str(r["_id"])
        r["project_id"] = oid_str(r["project_id"])
        r["skill_id"] = oid_str(r["skill_id"])
        del r["_id"]
    return rows
