"""Confirmation routes that persist the user-approved skill state used across dashboards, evidence, and job matching."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.auth import require_user
from app.core.db import get_db
from app.models.confirmations import (
    ConfirmationIn,
    ConfirmationOut,
    ConfirmedSkillEntry,
    EditedSkill,
    RejectedSkill,
)
from app.utils.mongo import oid_str, ref_values
from app.utils.rewards import safe_sync_reward_counter

router = APIRouter()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_optional_oid(value: str | None, field_name: str) -> ObjectId | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return ObjectId(s)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}")


def confirmation_scope_key(snapshot_oid: ObjectId | None) -> str:
    return f"snapshot:{snapshot_oid}" if snapshot_oid is not None else "profile"


async def find_skill_by_id_ref(db, skill_id: str, field_name: str) -> dict:
    sid = str(skill_id or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}")

    queries = [{"_id": sid}]
    try:
        queries.insert(0, {"_id": ObjectId(sid)})
    except Exception:
        pass

    for query in queries:
        skill = await db["skills"].find_one(query, {"name": 1, "skill_name": 1})
        if skill:
            return skill

    raise HTTPException(status_code=404, detail=f"Skill not found: {sid}")


async def maybe_find_skill_by_id_ref(db, skill_id: str) -> dict | None:
    sid = str(skill_id or "").strip()
    if not sid:
        return None

    queries = [{"_id": sid}]
    try:
        queries.insert(0, {"_id": ObjectId(sid)})
    except Exception:
        pass

    for query in queries:
        skill = await db["skills"].find_one(query, {"name": 1, "skill_name": 1})
        if skill:
            return skill
    return None


def clamp_proficiency(v: int) -> int:
    try:
        p = int(v)
    except Exception:
        p = 1
    if p < 0:
        return 0
    if p > 5:
        return 5
    return p


def evidence_floor(evidence_count: int) -> int:
    count = max(0, int(evidence_count or 0))
    if count <= 0:
        return 0
    if count == 1:
        return 1
    if count == 2:
        return 2
    if count <= 4:
        return 3
    if count <= 6:
        return 4
    return 5


async def get_evidence_support_map(db, user_refs: list[object], skill_ids: list[object]) -> dict[str, int]:
    normalized_skill_ids = [sid for sid in skill_ids if sid is not None]
    if not normalized_skill_ids:
        return {}

    rows = await (
        db["evidence"]
        .aggregate(
            [
                {"$match": {"user_id": {"$in": user_refs}, "origin": "user", "skill_ids": {"$in": normalized_skill_ids}}},
                {"$unwind": {"path": "$skill_ids", "preserveNullAndEmptyArrays": False}},
                {"$match": {"skill_ids": {"$in": normalized_skill_ids}}},
                {"$group": {"_id": "$skill_ids", "count": {"$sum": 1}}},
            ]
        )
        .to_list(length=max(1, len(normalized_skill_ids)))
    )
    return {oid_str(row.get("_id")): int(row.get("count", 0) or 0) for row in rows}


async def serialize_confirmation_doc(db, doc: dict, user_refs: list[object], resume_snapshot_id_override: str | None = None) -> ConfirmationOut:
    confirmed_entries = doc.get("confirmed", []) or []
    evidence_support = await get_evidence_support_map(
        db,
        user_refs,
        [entry.get("skill_id") for entry in confirmed_entries],
    )
    return ConfirmationOut(
        id=oid_str(doc["_id"]) if doc.get("_id") is not None else None,
        user_id=oid_str(doc["user_id"]) if doc.get("user_id") is not None else None,
        resume_snapshot_id=resume_snapshot_id_override
        if resume_snapshot_id_override is not None
        else (oid_str(doc["resume_snapshot_id"]) if doc.get("resume_snapshot_id") else None),
        confirmed=[
            ConfirmedSkillEntry(
                skill_id=oid_str(c["skill_id"]),
                skill_name=c.get("skill_name", ""),
                proficiency=max(
                    clamp_proficiency(c.get("manual_proficiency", c.get("proficiency", 0))),
                    evidence_floor(evidence_support.get(oid_str(c.get("skill_id")), 0)),
                ),
                manual_proficiency=clamp_proficiency(c.get("manual_proficiency", c.get("proficiency", 0))),
                auto_proficiency=evidence_floor(evidence_support.get(oid_str(c.get("skill_id")), 0)),
                evidence_count=evidence_support.get(oid_str(c.get("skill_id")), 0),
            )
            for c in confirmed_entries
        ],
        rejected=[
            RejectedSkill(
                skill_id=oid_str(r.get("skill_id")),
                skill_name=r.get("skill_name", ""),
            )
            for r in doc.get("rejected", [])
            if oid_str(r.get("skill_id"))
        ],
        edited=[
            EditedSkill(
                from_text=e.get("from_text", ""),
                to_skill_id=oid_str(e.get("to_skill_id")),
            )
            for e in doc.get("edited", [])
            if oid_str(e.get("to_skill_id"))
        ],
        created_at=doc.get("created_at"),
        updated_at=doc.get("updated_at"),
    )


def merge_confirmation_docs(docs: list[dict], user_oid: ObjectId, resume_snapshot_id: str | None) -> dict:
    confirmed_map: dict[str, dict] = {}
    rejected_map: dict[str, dict] = {}
    edited_map: dict[tuple[str, str], dict] = {}

    latest_updated = None
    earliest_created = None
    canonical_id = None

    sorted_docs = sorted(
        docs,
        key=lambda d: (
            d.get("updated_at") or d.get("created_at") or datetime.min.replace(tzinfo=timezone.utc),
            d.get("created_at") or datetime.min.replace(tzinfo=timezone.utc),
        ),
        reverse=True,
    )

    for index, doc in enumerate(sorted_docs):
        if index == 0:
            canonical_id = doc.get("_id")
            latest_updated = doc.get("updated_at") or doc.get("created_at")
        created_at = doc.get("created_at")
        if created_at is not None and (earliest_created is None or created_at < earliest_created):
            earliest_created = created_at

        for entry in doc.get("confirmed", []) or []:
            sid = oid_str(entry.get("skill_id"))
            if not sid:
                continue
            if sid not in confirmed_map:
                confirmed_map[sid] = {
                    "skill_id": entry.get("skill_id"),
                    "skill_name": entry.get("skill_name", ""),
                    "proficiency": int(entry.get("proficiency", 0)),
                    "manual_proficiency": int(entry.get("manual_proficiency", entry.get("proficiency", 0))),
                }

        for entry in doc.get("rejected", []) or []:
            sid = oid_str(entry.get("skill_id"))
            if not sid:
                continue
            if sid not in rejected_map:
                rejected_map[sid] = {
                    "skill_id": entry.get("skill_id"),
                    "skill_name": entry.get("skill_name", ""),
                }

        for entry in doc.get("edited", []) or []:
            key = (str(entry.get("from_text", "")), oid_str(entry.get("to_skill_id")))
            if not key[1]:
                continue
            if key not in edited_map:
                edited_map[key] = {
                    "from_text": entry.get("from_text", ""),
                    "to_skill_id": entry.get("to_skill_id"),
                }

    return {
        "_id": canonical_id,
        "user_id": user_oid,
        "resume_snapshot_id": None if resume_snapshot_id is None else resume_snapshot_id,
        "confirmed": list(confirmed_map.values()),
        "rejected": list(rejected_map.values()),
        "edited": list(edited_map.values()),
        "created_at": earliest_created or now_utc(),
        "updated_at": latest_updated or now_utc(),
    }


@router.post("/", response_model=ConfirmationOut)
async def upsert_confirmation(payload: ConfirmationIn, user=Depends(require_user)):
    db = get_db()

    user_oid = user.get("_id")
    if not isinstance(user_oid, ObjectId):
        raise HTTPException(status_code=401, detail="Invalid user session")
    user_refs = ref_values(user_oid)

    # Optional snapshot id; None means "default profile"
    snapshot_oid = parse_optional_oid(payload.resume_snapshot_id, "resume_snapshot_id")
    scope_key = confirmation_scope_key(snapshot_oid)

    # If snapshot provided, verify it exists
    if snapshot_oid is not None:
        snap = await db["resume_snapshots"].find_one({"_id": snapshot_oid, "user_id": {"$in": user_refs}})
        if not snap:
            raise HTTPException(status_code=404, detail="Resume snapshot not found")

    # ---- Build confirmed (dedupe by skill_id, canonical names from skills collection) ----
    confirmed_map: dict[str, dict] = {}
    for entry in (payload.confirmed or []):
        sid = (getattr(entry, "skill_id", None) or "").strip()
        if not sid:
            continue
        skill = await find_skill_by_id_ref(db, sid, "skill_id")

        skill_name = (skill.get("name") or skill.get("skill_name") or "Unknown").strip()
        manual_prof = clamp_proficiency(getattr(entry, "manual_proficiency", getattr(entry, "proficiency", 0)) or 0)
        canonical_skill_id = skill.get("_id")

        # last one wins (dedupe)
        confirmed_map[str(canonical_skill_id)] = {
            "skill_id": canonical_skill_id,
            "skill_name": skill_name,
            "proficiency": manual_prof,
            "manual_proficiency": manual_prof,
        }

    confirmed_docs = list(confirmed_map.values())

    # ---- Build rejected (dedupe by skill_id, canonical names) ----
    rejected_map: dict[str, dict] = {}
    for r in (payload.rejected or []):
        sid = (getattr(r, "skill_id", None) or "").strip()
        if not sid:
            continue
        skill = await maybe_find_skill_by_id_ref(db, sid)
        if not skill:
            continue

        skill_name = (skill.get("name") or skill.get("skill_name") or "Unknown").strip()
        canonical_skill_id = skill.get("_id")
        rejected_map[str(canonical_skill_id)] = {"skill_id": canonical_skill_id, "skill_name": skill_name}

    rejected_docs = list(rejected_map.values())

    # ---- Build edited ----
    edited_docs = []
    for e in (payload.edited or []):
        to_id = (getattr(e, "to_skill_id", None) or "").strip()
        if not to_id:
            continue
        skill = await maybe_find_skill_by_id_ref(db, to_id)
        if not skill:
            continue

        edited_docs.append(
            {"from_text": getattr(e, "from_text", "") or "", "to_skill_id": skill["_id"]}
        )

    # ---- Atomic upsert (safe with unique index on (user_id, scope_key)) ----
    existing_docs = await (
        db["resume_skill_confirmations"]
        .find({"user_id": {"$in": user_refs}, "scope_key": scope_key})
        .sort("updated_at", -1)
        .to_list(length=50)
    )
    existing = existing_docs[0] if existing_docs else None
    now = now_utc()

    if existing:
        await db["resume_skill_confirmations"].update_one(
            {"_id": existing["_id"]},
            {
                "$set": {
                    "user_id": user_oid,
                    "resume_snapshot_id": snapshot_oid,
                    "scope_key": scope_key,
                    "confirmed": confirmed_docs,
                    "rejected": rejected_docs,
                    "edited": edited_docs,
                    "updated_at": now,
                }
            },
        )
        d = await db["resume_skill_confirmations"].find_one({"_id": existing["_id"]})
        stale_ids = [doc["_id"] for doc in existing_docs[1:] if doc.get("_id") is not None]
        if stale_ids:
            await db["resume_skill_confirmations"].delete_many({"_id": {"$in": stale_ids}})
    else:
        await db["resume_skill_confirmations"].insert_one(
            {
                "user_id": user_oid,
                "resume_snapshot_id": snapshot_oid,
                "scope_key": scope_key,
                "confirmed": confirmed_docs,
                "rejected": rejected_docs,
                "edited": edited_docs,
                "created_at": now,
                "updated_at": now,
            }
        )
        d = await db["resume_skill_confirmations"].find_one(
            {"user_id": user_oid, "scope_key": scope_key}
        )
    if not d:
        raise HTTPException(status_code=500, detail="Failed to read confirmation document")
    if snapshot_oid is None:
        await safe_sync_reward_counter(db, oid_str(user_oid), "profile_skills_confirmed", len(confirmed_docs))

    return await serialize_confirmation_doc(db, d, user_refs)

# GET profile confirmation (resume_snapshot_id == None) for current user
@router.get("/profile", response_model=ConfirmationOut)
async def get_profile_confirmation(user=Depends(require_user)):
    db = get_db()
    user_oid = user.get("_id")
    if not user_oid:
        raise HTTPException(status_code=401, detail="Invalid user session")
    user_refs = ref_values(user_oid)

    docs = await (
        db["resume_skill_confirmations"]
        .find({"user_id": {"$in": user_refs}, "resume_snapshot_id": {"$in": [None, ""]}})
        .sort("updated_at", -1)
        .to_list(length=50)
    )

    # If none exists, return an empty confirmation object (no 404)
    if not docs:
        now = now_utc()
        return ConfirmationOut(
            id=None,
            user_id=oid_str(user_oid),
            resume_snapshot_id=None,
            confirmed=[],
            rejected=[],
            edited=[],
            created_at=now,
            updated_at=now,
        )

    merged = merge_confirmation_docs(docs, user_oid, None)
    return await serialize_confirmation_doc(db, merged, user_refs, resume_snapshot_id_override=None)

@router.get("/", response_model=list[ConfirmationOut])
async def list_confirmations(user=Depends(require_user)):
    db = get_db()

    user_oid = user.get("_id")
    if not isinstance(user_oid, ObjectId):
        raise HTTPException(status_code=401, detail="Invalid user session")
    user_refs = ref_values(user_oid)

    docs = await db["resume_skill_confirmations"].find({"user_id": {"$in": user_refs}}).to_list(length=500)

    return [
        await serialize_confirmation_doc(
            db,
            d,
            user_refs,
            resume_snapshot_id_override=oid_str(d["resume_snapshot_id"]) if d.get("resume_snapshot_id") else None,
        )
        for d in docs
    ]
