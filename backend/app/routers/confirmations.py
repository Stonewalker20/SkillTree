from fastapi import APIRouter, Query, HTTPException
from app.core.db import get_db
from app.models.confirmations import (
    ConfirmationIn,
    ConfirmationOut,
    ConfirmedSkillEntry,
    RejectedSkill,
    EditedSkill,
)
from app.utils.mongo import oid_str
from bson import ObjectId
from datetime import datetime, timezone

router = APIRouter()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


@router.post("/", response_model=ConfirmationOut)
async def upsert_confirmation(payload: ConfirmationIn):
    db = get_db()

    # Validate snapshot id
    try:
        snapshot_oid = ObjectId(payload.resume_snapshot_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid resume_snapshot_id")

    snap = await db["resume_snapshots"].find_one({"_id": snapshot_oid})
    if not snap:
        raise HTTPException(status_code=404, detail="Resume snapshot not found")

    # Build confirmed entries with skill_name + proficiency
    confirmed_docs = []
    for entry in payload.confirmed:
        try:
            skill_oid = ObjectId(entry.skill_id)
        except Exception:
            raise HTTPException(status_code=400, detail=f"Invalid skill_id: {entry.skill_id}")

        skill = await db["skills"].find_one({"_id": skill_oid})
        if not skill:
            raise HTTPException(status_code=404, detail=f"Skill not found: {entry.skill_id}")

        skill_name = skill.get("name") or skill.get("skill_name") or "Unknown"

        confirmed_docs.append(
            {
                "skill_id": skill_oid,
                "skill_name": skill_name,
                "proficiency": entry.proficiency,
            }
        )

    # Build rejected entries with skill_name
    rejected_docs = []
    for r in payload.rejected:
        try:
            skill_oid = ObjectId(r.skill_id)
        except Exception:
            raise HTTPException(status_code=400, detail=f"Invalid rejected.skill_id: {r.skill_id}")

        skill = await db["skills"].find_one({"_id": skill_oid})
        if not skill:
            raise HTTPException(status_code=404, detail=f"Skill not found: {r.skill_id}")

        skill_name = skill.get("name") or skill.get("skill_name") or r.skill_name or "Unknown"
        rejected_docs.append({"skill_id": skill_oid, "skill_name": skill_name})

    # Edited entries: validate to_skill_id exists
    edited_docs = []
    for e in payload.edited:
        try:
            to_skill_oid = ObjectId(e.to_skill_id)
        except Exception:
            raise HTTPException(status_code=400, detail=f"Invalid edited.to_skill_id: {e.to_skill_id}")

        skill = await db["skills"].find_one({"_id": to_skill_oid})
        if not skill:
            raise HTTPException(status_code=404, detail=f"Skill not found: {e.to_skill_id}")

        edited_docs.append({"from_text": e.from_text, "to_skill_id": to_skill_oid})

    # Upsert (one confirmation per user per snapshot)
    q = {"user_id": payload.user_id, "resume_snapshot_id": snapshot_oid}
    now = now_utc()

    existing = await db["resume_skill_confirmations"].find_one(q)
    if existing:
        created_at = existing.get("created_at", now)
        await db["resume_skill_confirmations"].update_one(
            {"_id": existing["_id"]},
            {
                "$set": {
                    "confirmed": confirmed_docs,
                    "rejected": rejected_docs,
                    "edited": edited_docs,
                    "updated_at": now,
                }
            },
        )
        doc_id = existing["_id"]
    else:
        doc = {
            "user_id": payload.user_id,
            "resume_snapshot_id": snapshot_oid,
            "confirmed": confirmed_docs,
            "rejected": rejected_docs,
            "edited": edited_docs,
            "created_at": now,
            "updated_at": now,
        }
        res = await db["resume_skill_confirmations"].insert_one(doc)
        doc_id = res.inserted_id
        created_at = doc["created_at"]

    # Read back the updated document to return consistent payload
    d = await db["resume_skill_confirmations"].find_one({"_id": doc_id})

    return ConfirmationOut(
        id=oid_str(d["_id"]),
        user_id=d["user_id"],
        resume_snapshot_id=oid_str(d["resume_snapshot_id"]),
        confirmed=[
            ConfirmedSkillEntry(
                skill_id=oid_str(c["skill_id"]),
                skill_name=c.get("skill_name", ""),
                proficiency=int(c.get("proficiency", 0)),
            )
            for c in d.get("confirmed", [])
        ],
        rejected=[
            RejectedSkill(
                skill_id=oid_str(r["skill_id"]),
                skill_name=r.get("skill_name", ""),
            )
            for r in d.get("rejected", [])
        ],
        edited=[
            EditedSkill(
                from_text=e.get("from_text", ""),
                to_skill_id=oid_str(e["to_skill_id"]),
            )
            for e in d.get("edited", [])
        ],
        created_at=d.get("created_at"),
        updated_at=d.get("updated_at"),
    )


@router.get("/", response_model=list[ConfirmationOut])
async def list_confirmations(user_id: str | None = Query(default=None)):
    db = get_db()
    q = {}
    if user_id:
        q["user_id"] = user_id

    docs = await db["resume_skill_confirmations"].find(q).to_list(length=500)

    return [
        ConfirmationOut(
            id=oid_str(d["_id"]),
            user_id=d["user_id"],
            resume_snapshot_id=oid_str(d["resume_snapshot_id"]),
            confirmed=[
                ConfirmedSkillEntry(
                    skill_id=oid_str(c["skill_id"]),
                    skill_name=c.get("skill_name", ""),
                    proficiency=int(c.get("proficiency", 0)),
                )
                for c in d.get("confirmed", [])
            ],
            rejected=[
                RejectedSkill(
                    skill_id=oid_str(r["skill_id"]),
                    skill_name=r.get("skill_name", ""),
                )
                for r in d.get("rejected", [])
            ],
            edited=[
                EditedSkill(
                    from_text=e.get("from_text", ""),
                    to_skill_id=oid_str(e["to_skill_id"]),
                )
                for e in d.get("edited", [])
            ],
            created_at=d.get("created_at"),
            updated_at=d.get("updated_at"),
        )
        for d in docs
    ]