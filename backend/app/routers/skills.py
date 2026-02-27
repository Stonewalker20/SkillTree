from __future__ import annotations

from fastapi import APIRouter, Query, HTTPException
from app.core.db import get_db
from app.models.skill import SkillIn, SkillOut, SkillUpdate
from app.utils.mongo import oid_str
from bson import ObjectId
from datetime import datetime, timezone

router = APIRouter()

def now_utc():
    return datetime.now(timezone.utc)

def make_snippet(text: str, needle: str, window: int = 80) -> str:
    t = text.lower()
    n = needle.lower()
    idx = t.find(n)
    if idx == -1:
        return ""
    start = max(0, idx - window)
    end = min(len(text), idx + len(needle) + window)
    return text[start:end].strip()

@router.get("/", response_model=list[SkillOut])
async def list_skills(
    q: str | None = Query(default=None, description="Search skill name"),
    category: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    skip: int = Query(default=0, ge=0),
):
    db = get_db()
    filt: dict = {}
    if q:
        filt["name"] = {"$regex": q, "$options": "i"}
    if category:
        filt["category"] = category

    cursor = (
        db["skills"]
        .find(
            filt,
            {
                "name": 1,
                "category": 1,
                "aliases": 1,
                "proficiency": 1,
                "last_used_at": 1,
            },
        )
        .sort("name", 1)
        .skip(skip)
        .limit(limit)
    )
    docs = await cursor.to_list(length=limit)
    return [
        {
            "id": oid_str(d["_id"]),
            "name": d.get("name", ""),
            "category": d.get("category", ""),
            "aliases": d.get("aliases", []),
            "proficiency": d.get("proficiency"),
            "last_used_at": d.get("last_used_at"),
        }
        for d in docs
    ]

@router.post("/", response_model=SkillOut)
async def create_skill(payload: SkillIn):
    db = get_db()
    doc = payload.model_dump()
    doc["created_at"] = now_utc()
    doc["updated_at"] = doc["created_at"]
    res = await db["skills"].insert_one(doc)
    return {"id": oid_str(res.inserted_id), **doc}

# UC 2.2 – Update Skill Proficiency and Last Used Date (already implemented, keep single PATCH)
@router.patch("/{skill_id}", response_model=SkillOut)
async def update_skill(skill_id: str, payload: SkillUpdate):
    db = get_db()
    try:
        oid = ObjectId(skill_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid skill_id")

    updates = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided to update")

    updates["updated_at"] = now_utc()

    res = await db["skills"].update_one({"_id": oid}, {"$set": updates})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Skill not found")

    doc = await db["skills"].find_one({"_id": oid})
    return {
        "id": oid_str(doc["_id"]),
        "name": doc.get("name", ""),
        "category": doc.get("category", ""),
        "aliases": doc.get("aliases", []),
        "proficiency": doc.get("proficiency"),
        "last_used_at": doc.get("last_used_at"),
    }

# UC 3.2 – Skill Extraction (existing in your prior file)
@router.post("/extract/skills/{snapshot_id}")
async def extract_skills(snapshot_id: str):
    db = get_db()
    try:
        sid = ObjectId(snapshot_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid snapshot_id")

    snap = await db["resume_snapshots"].find_one({"_id": sid})
    if not snap:
        raise HTTPException(status_code=404, detail="Resume snapshot not found")

    text = (snap.get("raw_text") or "")
    if len(text) < 50:
        raise HTTPException(status_code=400, detail="Snapshot text too short")

    # Pull skills (Motor async)
    skills_cursor = db["skills"].find({}, {"name": 1, "aliases": 1}).limit(20000)
    skills = await skills_cursor.to_list(length=20000)

    found = []
    lowered = text.lower()

    for s in skills:
        name = (s.get("name") or "").strip()
        aliases = s.get("aliases") or []
        candidates = [name] + aliases

        best = None
        best_conf = 0.0

        for c in candidates:
            c_norm = str(c).strip()
            if not c_norm:
                continue
            if c_norm.lower() in lowered:
                conf = 0.9 if c_norm.lower() == name.lower() else 0.75
                if conf > best_conf:
                    best_conf = conf
                    best = c_norm

        if best and name:
            found.append(
                {
                    "skill_id": oid_str(s["_id"]),
                    "skill_name": name,
                    "confidence": best_conf,
                    "evidence_snippet": make_snippet(text, best),
                }
            )

    uniq = {item["skill_id"]: item for item in found}
    extracted = list(uniq.values())

    doc = {
        "resume_snapshot_id": sid,
        "skills": extracted,
        "created_at": now_utc(),
    }
    await db["skill_extractions"].insert_one(doc)

    return {"snapshot_id": snapshot_id, "extracted": extracted, "created_at": doc["created_at"]}

# UC 2.4 – Skill Gap Analysis (existing)
@router.get("/gaps")
async def skill_gaps(threshold: int = Query(default=0, ge=0, le=10)):
    db = get_db()
    pipeline = [
        {
            "$lookup": {
                "from": "evidence",
                "localField": "_id",
                "foreignField": "skill_ids",
                "as": "evidence_docs",
            }
        },
        {"$addFields": {"evidence_count": {"$size": "$evidence_docs"}}},
        {"$match": {"evidence_count": {"$lte": threshold}}},
        {"$project": {"name": 1, "category": 1, "evidence_count": 1}},
        {"$sort": {"evidence_count": 1, "name": 1}},
        {"$limit": 200},
    ]
    cursor = db["skills"].aggregate(pipeline)
    rows = await cursor.to_list(length=200)
    for r in rows:
        r["_id"] = oid_str(r["_id"])
    return {"threshold": threshold, "results": rows}

# UC 2.4 – Confirmed Skill Gaps (already implemented, fixing syntax error in Query)
@router.get("/gaps/confirmed")
async def confirmed_skill_gaps(
    user_id: str = Query(..., description="User identifier"),
    threshold: int = Query(default=0, ge=0, le=100),
):
    db = get_db()
    pipeline = [
        {"$match": {"user_id": user_id}},
        {"$unwind": "$confirmed"},
        {"$group": {"_id": "$confirmed.skill_id"}},
        {
            "$lookup": {
                "from": "skills",
                "localField": "_id",
                "foreignField": "_id",
                "as": "skill",
            }
        },
        {
            "$lookup": {
                "from": "evidence",
                "localField": "_id",
                "foreignField": "skill_ids",
                "as": "evidence_docs",
            }
        },
        {"$addFields": {"evidence_count": {"$size": "$evidence_docs"}}},
        {"$match": {"evidence_count": {"$lte": threshold}}},
    ]
    cursor = db["resume_skill_confirmations"].aggregate(pipeline)
    rows = await cursor.to_list(length=500)

    out = []
    for r in rows:
        skill_doc = r["skill"][0] if r.get("skill") else {}
        out.append(
            {
                "skill_id": oid_str(r["_id"]),
                "skill_name": skill_doc.get("name", ""),
                "category": skill_doc.get("category", ""),
                "evidence_count": int(r.get("evidence_count", 0)),
            }
        )
    return {"user_id": user_id, "threshold": threshold, "results": out}

# UC 2.3 – View Skill Detail with Linked Projects/Evidence
@router.get("/{skill_id}/detail")
async def skill_detail(skill_id: str, user_id: str | None = Query(default=None)):
    db = get_db()
    try:
        skill_oid = ObjectId(skill_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid skill_id")

    skill = await db["skills"].find_one({"_id": skill_oid})
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    # projects linked via project_skill_links
    pipeline = [
        {"$match": {"skill_id": skill_oid}},
        {
            "$lookup": {
                "from": "projects",
                "localField": "project_id",
                "foreignField": "_id",
                "as": "project",
            }
        },
        {"$unwind": {"path": "$project", "preserveNullAndEmptyArrays": True}},
        {"$project": {"project_id": 1, "title": "$project.title", "created_at": "$project.created_at"}},
        {"$sort": {"created_at": -1}},
    ]
    proj_rows = await db["project_skill_links"].aggregate(pipeline).to_list(length=200)
    projects = [{"project_id": oid_str(r["project_id"]), "title": r.get("title",""), "created_at": r.get("created_at")} for r in proj_rows if r.get("project_id")]

    # evidence linked directly
    ev_q = {"skill_ids": skill_id}
    if user_id:
        ev_q["user_id"] = user_id
    evidence = await db["evidence"].find(ev_q).sort("created_at", -1).limit(50).to_list(length=50)
    evidence_out = [
        {
            "id": oid_str(e["_id"]),
            "type": e.get("type"),
            "title": e.get("title"),
            "source": e.get("source"),
            "project_id": e.get("project_id"),
            "created_at": e.get("created_at"),
        }
        for e in evidence
    ]

    return {
        "skill": {
            "id": oid_str(skill["_id"]),
            "name": skill.get("name",""),
            "category": skill.get("category",""),
            "aliases": skill.get("aliases", []),
            "proficiency": skill.get("proficiency"),
            "last_used_at": skill.get("last_used_at"),
        },
        "linked_projects": projects,
        "linked_evidence": evidence_out,
    }
