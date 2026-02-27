from __future__ import annotations

from fastapi import APIRouter, HTTPException
from datetime import datetime, timezone
from bson import ObjectId
from app.core.db import get_db
from app.utils.mongo import oid_str
from app.models.taxonomy import SkillAliasesUpdate, SkillRelationIn, SkillRelationOut

router = APIRouter()

def now_utc():
    return datetime.now(timezone.utc)

# UC 4.4 – Maintain taxonomy: manage skill aliases
@router.put("/aliases/{skill_id}")
async def set_skill_aliases(skill_id: str, payload: SkillAliasesUpdate):
    db = get_db()
    try:
        oid = ObjectId(skill_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid skill_id")

    res = await db["skills"].update_one({"_id": oid}, {"$set": {"aliases": payload.aliases, "updated_at": now_utc()}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Skill not found")

    doc = await db["skills"].find_one({"_id": oid}, {"name": 1, "category": 1, "aliases": 1})
    return {"skill_id": skill_id, "name": doc.get("name",""), "category": doc.get("category",""), "aliases": doc.get("aliases", [])}

# UC 4.4 – Maintain taxonomy: manage relationships
@router.post("/relations", response_model=SkillRelationOut)
async def create_relation(payload: SkillRelationIn):
    db = get_db()
    try:
        from_oid = ObjectId(payload.from_skill_id)
        to_oid = ObjectId(payload.to_skill_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid skill_id in relation")

    if not await db["skills"].find_one({"_id": from_oid}):
        raise HTTPException(status_code=404, detail="from_skill_id not found")
    if not await db["skills"].find_one({"_id": to_oid}):
        raise HTTPException(status_code=404, detail="to_skill_id not found")

    doc = {
        "from_skill_id": from_oid,
        "to_skill_id": to_oid,
        "relation_type": payload.relation_type,
        "created_at": now_utc(),
    }
    res = await db["skill_relations"].insert_one(doc)
    return {
        "id": oid_str(res.inserted_id),
        "from_skill_id": payload.from_skill_id,
        "to_skill_id": payload.to_skill_id,
        "relation_type": payload.relation_type,
        "created_at": doc["created_at"],
    }

@router.get("/relations", response_model=list[SkillRelationOut])
async def list_relations(skill_id: str | None = None):
    db = get_db()
    q = {}
    if skill_id:
        try:
            oid = ObjectId(skill_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid skill_id")
        q = {"$or": [{"from_skill_id": oid}, {"to_skill_id": oid}]}
    docs = await db["skill_relations"].find(q).sort("created_at", -1).to_list(length=500)
    out = []
    for d in docs:
        out.append(
            {
                "id": oid_str(d["_id"]),
                "from_skill_id": oid_str(d["from_skill_id"]),
                "to_skill_id": oid_str(d["to_skill_id"]),
                "relation_type": d.get("relation_type", "related_to"),
                "created_at": d.get("created_at"),
            }
        )
    return out
