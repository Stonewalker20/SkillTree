"""Skill catalog routes for listing, creating, deleting, and analyzing skills available to or owned by the user."""

import re

from fastapi import APIRouter, Query, HTTPException, Depends
from app.core.db import get_db
from app.models.skill import SkillIn, SkillOut, SkillUpdate
from app.utils.ai import cosine_similarity, embed_texts, normalize_ai_preferences
from app.utils.skill_catalog import expand_alias_variants, merge_skill_docs, normalize_skill_text
from app.utils.mongo import oid_str, ref_values
from app.core.auth import require_admin_user, require_user
from bson import ObjectId
from datetime import datetime, timezone

router = APIRouter()

TEST_SKILL_PATTERN = re.compile(r"\b(test|demo|sample|mock|dummy|placeholder)\b", re.IGNORECASE)
BAD_SKILL_PATTERN = re.compile(r"(^\d+(\.\d+)?$)|(^\d{4}$)|(^[a-z]{1,2}$)|(\.$)", re.IGNORECASE)
BAD_SKILL_PHRASES = [
    "ability to",
    "equal opportunity",
    "applicants receive",
    "company name",
    "base salary",
    "benefits package",
]
ALLOWED_SHORT_SKILLS = {"c", "c#", "c++", "go", "r", "ui", "ux", "qa", "bi", "ml", "ai"}


def normalize_str_list(values: list[str] | None) -> list[str]:
    seen = set()
    out: list[str] = []
    for value in values or []:
        s = (value or "").strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def _count_occurrences(text: str, phrase: str) -> int:
    normalized_text = str(text or "")
    normalized_phrase = str(phrase or "").strip()
    if not normalized_text or not normalized_phrase:
        return 0
    if re.fullmatch(r"[A-Za-z0-9]+", normalized_phrase):
        pattern = rf"(?<![A-Za-z0-9]){re.escape(normalized_phrase)}(?![A-Za-z0-9])"
    else:
        pattern = re.escape(normalized_phrase)
    return len(re.findall(pattern, normalized_text, flags=re.IGNORECASE))


async def _extract_confidence(text: str, observed_term: str, canonical_terms: list[str]) -> float:
    mention_count = max((_count_occurrences(text, term) for term in [observed_term, *canonical_terms] if term), default=0)
    evidence_frequency = min(1.0, mention_count / 3.0) if mention_count > 0 else 0.0
    vectors, _provider = await embed_texts([observed_term, *canonical_terms], preferences=normalize_ai_preferences())
    semantic_similarity = 0.0
    if len(vectors) == len(canonical_terms) + 1:
        semantic_similarity = max((cosine_similarity(vectors[0], vec) for vec in vectors[1:]), default=0.0)
    return round(max(0.0, min(1.0, evidence_frequency * semantic_similarity)), 4)


def is_hidden_skill(doc: dict) -> bool:
    name = (doc.get("name") or "").strip()
    if not name:
        return True
    if doc.get("hidden") is True:
        return True
    low = name.lower()
    if TEST_SKILL_PATTERN.search(name):
        return True
    if low not in ALLOWED_SHORT_SKILLS and BAD_SKILL_PATTERN.search(name):
        return True
    if any(phrase in low for phrase in BAD_SKILL_PHRASES):
        return True
    return False


def serialize_skill(doc: dict, current_user_oid: ObjectId | None = None) -> dict:
    created_by = doc.get("created_by_user_id")
    origin = doc.get("origin") or ("user" if created_by else "default")
    return {
        "id": oid_str(doc["_id"]),
        "name": doc.get("name", ""),
        "category": doc.get("category", ""),
        "categories": doc.get("categories", []) or ([doc.get("category", "")] if doc.get("category") else []),
        "aliases": doc.get("aliases", []),
        "tags": doc.get("tags", []),
        "proficiency": doc.get("proficiency"),
        "last_used_at": doc.get("last_used_at"),
        "origin": origin,
        "created_by_user_id": oid_str(created_by) if created_by is not None else None,
        "can_delete": bool(doc.get("can_delete")) if "can_delete" in doc else bool(current_user_oid and created_by and oid_str(created_by) == oid_str(current_user_oid)),
        "merged_ids": doc.get("merged_ids", [oid_str(doc["_id"])]),
    }


async def _find_visible_skill_match_by_exact_term(db, term: str, current_user_oid: ObjectId | None) -> dict | None:
    normalized_term = normalize_skill_text(term)
    if not normalized_term:
        return None

    docs = await (
        db["skills"]
        .find(
            {},
            {
                "name": 1,
                "category": 1,
                "aliases": 1,
                "tags": 1,
                "proficiency": 1,
                "last_used_at": 1,
                "origin": 1,
                "created_by_user_id": 1,
                "hidden": 1,
            },
        )
        .sort([("name", 1), ("category", 1), ("_id", 1)])
        .to_list(length=20000)
    )
    visible_docs = [doc for doc in docs if not is_hidden_skill(doc)]
    merged_docs = merge_skill_docs(visible_docs, current_user_oid)
    for doc in merged_docs:
        if normalize_skill_text(doc.get("name")) == normalized_term:
            return doc
        if any(normalize_skill_text(alias) == normalized_term for alias in (doc.get("aliases") or [])):
            return doc
    return None

@router.get("/", response_model=list[SkillOut])
async def list_skills(
    q: str | None = Query(default=None, description="Search skill name"),
    category: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    skip: int = Query(default=0, ge=0),
    user=Depends(require_user),
):
    db = get_db()
    docs = await (
        db["skills"]
        .find(
            {},
            {
                "name": 1,
                "category": 1,
                "aliases": 1,
                "tags": 1,
                "proficiency": 1,
                "last_used_at": 1,
                "origin": 1,
                "created_by_user_id": 1,
                "hidden": 1,
            },
        )
        .sort([("name", 1), ("category", 1), ("_id", 1)])
        .to_list(length=20000)
    )

    visible_docs = [d for d in docs if not is_hidden_skill(d)]
    merged_docs = merge_skill_docs(visible_docs, user.get("_id"))

    if q:
        term = normalize_skill_text(q)
        merged_docs = [
            doc
            for doc in merged_docs
            if term in normalize_skill_text(doc.get("name"))
            or any(term in normalize_skill_text(alias) for alias in (doc.get("aliases") or []))
            or any(term in normalize_skill_text(cat) for cat in (doc.get("categories") or []))
        ]

    if category:
        category_key = normalize_skill_text(category)
        merged_docs = [
            doc
            for doc in merged_docs
            if category_key in {normalize_skill_text(cat) for cat in (doc.get("categories") or [doc.get("category", "")])}
        ]

    paged_docs = merged_docs[skip : skip + limit]
    return [serialize_skill(d, user.get("_id")) for d in paged_docs]

@router.post("/", response_model=SkillOut)
async def create_skill(payload: SkillIn, user=Depends(require_user)):
    db = get_db()

    name = (payload.name or "").strip()
    category = (payload.category or "").strip()
    aliases = payload.aliases or []

    if not name:
        raise HTTPException(status_code=400, detail="Skill name is required")
    if not category:
        raise HTTPException(status_code=400, detail="Skill category is required")

    existing_visible_match = await _find_visible_skill_match_by_exact_term(db, name, user.get("_id"))
    if existing_visible_match is not None:
        return serialize_skill(existing_visible_match, user.get("_id"))

    norm_aliases = expand_alias_variants(normalize_str_list(aliases), base_name=name)
    norm_tags = normalize_str_list(payload.tags)

    existing = await db["skills"].find_one({"name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}}, {"_id": 1})
    if existing:
        raise HTTPException(status_code=409, detail="Skill already exists")

    if norm_aliases:
        alias_name_hit = await db["skills"].find_one(
            {
                "name": {"$in": [re.compile(f"^{re.escape(alias)}$", re.IGNORECASE) for alias in norm_aliases]},
            },
            {"_id": 1},
        )
        if alias_name_hit:
            raise HTTPException(status_code=409, detail="A skill in this category already matches one of the aliases")

    doc = {
        "name": name,
        "category": category,
        "aliases": norm_aliases,
        "tags": norm_tags,
        "proficiency": payload.proficiency,
        "last_used_at": payload.last_used_at,
        "origin": "user",
        "created_by_user_id": user["_id"],
        "hidden": False,
        "updated_at": now_utc(),
    }

    res = await db["skills"].insert_one(doc)
    return serialize_skill({"_id": res.inserted_id, **doc}, user.get("_id"))

@router.delete("/{skill_id}")
async def delete_skill(skill_id: str, _user=Depends(require_admin_user)):
    db = get_db()
    try:
        oid = ObjectId(skill_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid skill_id")

    existing = await db["skills"].find_one({"_id": oid}, {"name": 1})
    if not existing:
        raise HTTPException(status_code=404, detail="Skill not found")

    result = await db["skills"].delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Skill not found")

    await db["resume_skill_confirmations"].update_many(
        {},
        {
            "$pull": {
                "confirmed": {"skill_id": {"$in": ref_values(oid)}},
                "rejected": {"skill_id": {"$in": ref_values(oid)}},
                "edited": {"to_skill_id": {"$in": ref_values(oid)}},
            }
        },
    )
    await db["evidence"].update_many(
        {},
        {"$pull": {"skill_ids": {"$in": ref_values(oid)}}},
    )
    await db["project_skill_links"].delete_many({"skill_id": {"$in": ref_values(oid)}})
    await db["jobs"].update_many(
        {},
        {
            "$pull": {
                "required_skill_ids": {"$in": ref_values(oid)},
                "required_skills": str(existing.get("name") or "").strip(),
            }
        },
    )
    await db["job_ingests"].update_many(
        {},
        {"$pull": {"extracted_skills": {"skill_id": {"$in": ref_values(oid)}}}},
    )
    await db["tailored_resumes"].update_many(
        {},
        {"$pull": {"selected_skill_ids": {"$in": ref_values(oid)}}},
    )
    await db["role_skill_weights"].update_many(
        {},
        {"$pull": {"weights": {"skill_id": {"$in": ref_values(oid)}}}},
    )
    await db["skill_relations"].delete_many(
        {
            "$or": [
                {"from_skill_id": {"$in": ref_values(oid)}},
                {"to_skill_id": {"$in": ref_values(oid)}},
            ]
        }
    )

    return {"ok": True}

@router.patch("/{skill_id}", response_model=SkillOut)
async def update_skill(skill_id: str, payload: SkillUpdate, _user=Depends(require_admin_user)):
    db = get_db()

    try:
        oid = ObjectId(skill_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid skill_id")

    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided to update")

    if "name" in updates:
        updates["name"] = updates["name"].strip()
        if not updates["name"]:
            raise HTTPException(status_code=400, detail="Skill name is required")
        existing = await db["skills"].find_one(
            {"_id": {"$ne": oid}, "name": {"$regex": f"^{re.escape(updates['name'])}$", "$options": "i"}},
            {"_id": 1},
        )
        if existing:
            raise HTTPException(status_code=409, detail="Skill already exists")
    if "category" in updates:
        updates["category"] = updates["category"].strip()
        if not updates["category"]:
            raise HTTPException(status_code=400, detail="Skill category is required")
    if "aliases" in updates:
        base_name = updates.get("name")
        if base_name is None:
            existing = await db["skills"].find_one({"_id": oid}, {"name": 1})
            base_name = (existing or {}).get("name", "")
        updates["aliases"] = expand_alias_variants(normalize_str_list(updates["aliases"]), base_name=base_name)
    if "tags" in updates:
        updates["tags"] = normalize_str_list(updates["tags"])

    updates["updated_at"] = now_utc()

    res = await db["skills"].update_one({"_id": oid}, {"$set": updates})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Skill not found")

    doc = await db["skills"].find_one({"_id": oid})
    return serialize_skill(doc)

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
async def extract_skills(snapshot_id: str, user=Depends(require_user)):
    db = get_db()

    try:
        sid = ObjectId(snapshot_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid snapshot_id")

    snap = await db["resume_snapshots"].find_one({"_id": sid, "user_id": {"$in": ref_values(user["_id"])}})
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
        if is_hidden_skill(s):
            continue
        aliases = s.get("aliases") or []
        candidates = [name] + aliases

        best = None
        best_conf = 0.0

        for c in candidates:
            c_norm = str(c).strip()
            if not c_norm:
                continue
            if c_norm.lower() in lowered:
                conf = await _extract_confidence(text, c_norm, [str(term or "").strip() for term in candidates if str(term or "").strip()])
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

    return {"snapshot_id": snapshot_id, "extracted": extracted, "created_at": doc["created_at"]}

@router.get("/gaps")
async def skill_gaps(threshold: int = 1):
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
        {
            "$project": {
                "name": 1,
                "evidence_count": {"$size": "$evidence_docs"},
            }
        },
        {"$match": {"evidence_count": {"$lt": threshold}}},
    ]

    rows = []
    async for doc in db["skills"].aggregate(pipeline):
        rows.append(
            {
                "skill_id": oid_str(doc["_id"]),
                "skill_name": doc["name"],
                "evidence_count": doc["evidence_count"],
            }
        )

    return rows  # ALWAYS array

@router.get("/gaps/confirmed")
async def confirmed_skill_gaps(user=Depends(require_user)):
    db = get_db()
    user_oid: ObjectId = user["_id"]
    user_refs = ref_values(user_oid)

    confirmed_ids = await db["resume_skill_confirmations"].distinct(
        "confirmed.skill_id",
        {"user_id": {"$in": user_refs}, "resume_snapshot_id": None},  # profile only
    )

    if not confirmed_ids:
        return []

    skills = await db["skills"].find({"_id": {"$in": confirmed_ids}}).to_list(length=500)

    return [{"skill_id": oid_str(s["_id"]), "skill_name": s.get("name","")} for s in skills]
