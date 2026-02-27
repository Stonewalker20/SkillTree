from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from datetime import datetime, timezone
from bson import ObjectId
from app.core.db import get_db
from app.utils.mongo import oid_str
from app.models.role import RoleIn, RoleOut

router = APIRouter()

def now_utc():
    return datetime.now(timezone.utc)

@router.get("/", response_model=list[RoleOut])
async def list_roles():
    db = get_db()
    docs = await db["roles"].find({}).sort("name", 1).to_list(length=500)
    return [
        {
            "id": oid_str(d["_id"]),
            "name": d.get("name",""),
            "description": d.get("description",""),
            "created_at": d.get("created_at"),
            "updated_at": d.get("updated_at"),
        }
        for d in docs
    ]

@router.post("/", response_model=RoleOut)
async def create_role(payload: RoleIn):
    db = get_db()
    now = now_utc()
    doc = payload.model_dump()
    doc["created_at"] = now
    doc["updated_at"] = now
    # unique name-ish
    existing = await db["roles"].find_one({"name": {"$regex": f"^{payload.name}$", "$options": "i"}})
    if existing:
        raise HTTPException(status_code=409, detail="Role already exists")
    res = await db["roles"].insert_one(doc)
    return {"id": oid_str(res.inserted_id), **doc}

# UC 4.3 – Aggregate postings by role and compute skill weights
# Simple heuristic: weight = (# approved jobs in role that mention skill_id) / (# approved jobs in role)
@router.post("/{role_id}/compute_weights")
async def compute_role_weights(role_id: str):
    db = get_db()
    try:
        role_oid = ObjectId(role_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid role_id")

    role = await db["roles"].find_one({"_id": role_oid})
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    # pull approved jobs tagged with this role
    jobs = await db["jobs"].find(
        {"moderation_status": "approved", "role_ids": role_id},
        {"required_skill_ids": 1, "required_skills": 1},
    ).to_list(length=2000)

    total = len(jobs)
    if total == 0:
        weights = []
    else:
        counts = {}
        for j in jobs:
            for sid in (j.get("required_skill_ids") or []):
                counts[sid] = counts.get(sid, 0) + 1
        # normalize
        weights = [{"skill_id": sid, "weight": counts[sid] / total} for sid in sorted(counts, key=lambda k: counts[k], reverse=True)]
        # add skill name if available
        for w in weights[:200]:
            try:
                soid = ObjectId(w["skill_id"])
                s = await db["skills"].find_one({"_id": soid}, {"name": 1})
                w["skill_name"] = (s or {}).get("name", "")
            except Exception:
                w["skill_name"] = ""

    doc = {
        "role_id": role_oid,
        "role_name": role.get("name",""),
        "computed_at": now_utc(),
        "weights": weights,
    }

    await db["role_skill_weights"].update_one(
        {"role_id": role_oid},
        {"$set": doc},
        upsert=True,
    )

    return {"role_id": role_id, "computed_at": doc["computed_at"], "weights": weights}

@router.get("/{role_id}/weights")
async def get_role_weights(role_id: str):
    db = get_db()
    try:
        role_oid = ObjectId(role_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid role_id")

    doc = await db["role_skill_weights"].find_one({"role_id": role_oid})
    if not doc:
        raise HTTPException(status_code=404, detail="No weights computed yet")
    return {
        "role_id": role_id,
        "computed_at": doc.get("computed_at"),
        "weights": doc.get("weights", []),
    }
