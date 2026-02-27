from __future__ import annotations

from fastapi import APIRouter, Query
from bson import ObjectId
from app.core.db import get_db
from app.utils.mongo import oid_str

router = APIRouter()

# UC 1.4 – Dashboard Summary (Skill coverage + evidence + recent projects)
@router.get("/summary")
async def dashboard_summary(user_id: str = Query(..., min_length=1), top_n: int = Query(default=10, ge=1, le=50)):
    db = get_db()

    # Recent projects
    projects = await (
        db["projects"]
        .find({"user_id": user_id}, {"title": 1, "description": 1, "created_at": 1})
        .sort("created_at", -1)
        .limit(10)
        .to_list(length=10)
    )
    proj_out = [{"id": oid_str(p["_id"]), "title": p.get("title",""), "created_at": p.get("created_at")} for p in projects]

    # Evidence counts per skill (via evidence.skill_ids)
    pipeline = [
        {"$match": {"user_id": user_id}},
        {"$unwind": {"path": "$skill_ids", "preserveNullAndEmptyArrays": False}},
        {"$group": {"_id": "$skill_ids", "evidence_count": {"$sum": 1}}},
        {"$sort": {"evidence_count": -1}},
        {"$limit": top_n},
        {
            "$lookup": {
                "from": "skills",
                "let": {"sid": "$_id"},
                "pipeline": [
                    {"$match": {"$expr": {"$eq": ["$_id", {"$toObjectId": "$$sid"}]}}},
                    {"$project": {"name": 1, "category": 1}},
                ],
                "as": "skill",
            }
        },
    ]

    # Mongo $toObjectId needs MongoDB 4.0+; if your cluster doesn't support it, keep the basic counts.
    # We'll try the pipeline and fall back to a less strict join if it errors.
    top_skills = []
    try:
        rows = await db["evidence"].aggregate(pipeline).to_list(length=top_n)
        for r in rows:
            skill_doc = (r.get("skill") or [{}])[0]
            top_skills.append({
                "skill_id": r["_id"],
                "skill_name": skill_doc.get("name", ""),
                "category": skill_doc.get("category", ""),
                "evidence_count": int(r.get("evidence_count", 0)),
            })
    except Exception:
        # fallback: just counts
        rows = await (
            db["evidence"]
            .aggregate([
                {"$match": {"user_id": user_id}},
                {"$unwind": {"path": "$skill_ids", "preserveNullAndEmptyArrays": False}},
                {"$group": {"_id": "$skill_ids", "evidence_count": {"$sum": 1}}},
                {"$sort": {"evidence_count": -1}},
                {"$limit": top_n},
            ])
            .to_list(length=top_n)
        )
        top_skills = [{"skill_id": r["_id"], "evidence_count": int(r.get("evidence_count", 0))} for r in rows]

    totals = {
        "projects": await db["projects"].count_documents({"user_id": user_id}),
        "evidence": await db["evidence"].count_documents({"user_id": user_id}),
        "confirmed_skills": await db["resume_skill_confirmations"].count_documents({"user_id": user_id}),
    }

    return {"user_id": user_id, "totals": totals, "recent_projects": proj_out, "top_skills_by_evidence": top_skills}
