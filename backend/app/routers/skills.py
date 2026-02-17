from fastapi import APIRouter, Query, HTTPException
from app.core.db import get_db
from app.models.skill import SkillIn, SkillOut
from app.utils.mongo import oid_str
from bson import ObjectId
from datetime import datetime, timezone

router = APIRouter()

@router.get("/", response_model=list[SkillOut])
async def list_skills():
    db = get_db()
    cursor = db["skills"].find({}, {"name": 1, "category": 1, "aliases": 1})
    docs = await cursor.to_list(length=500)
    return [{"id": oid_str(d["_id"]), "name": d["name"], "category": d["category"], "aliases": d.get("aliases", [])} for d in docs]

@router.post("/", response_model=SkillOut)
async def create_skill(payload: SkillIn):
    db = get_db()
    doc = payload.model_dump()
    res = await db["skills"].insert_one(doc)
    return {"id": oid_str(res.inserted_id), **doc}

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
            found.append({
                "skill_id": oid_str(s["_id"]),
                "skill_name": name,
                "confidence": best_conf,
                "evidence_snippet": make_snippet(text, best),
            })

    uniq = {item["skill_id"]: item for item in found}
    extracted = list(uniq.values())

    doc = {
        "resume_snapshot_id": sid,
        "skills": extracted,
        "created_at": now_utc(),
    }
    await db["skill_extractions"].insert_one(doc)

    #remove before release
    print("snapshot_text_len:", len(text))
    print("skills_loaded:", len(skills))


    return {"snapshot_id": snapshot_id, "extracted": extracted, "created_at": doc["created_at"]}

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

    # stringify ids for JSON
    for r in rows:
        r["_id"] = oid_str(r["_id"])

    return {"threshold": threshold, "results": rows}


