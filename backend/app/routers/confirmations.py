from fastapi import APIRouter, Query, HTTPException
from app.core.db import get_db
from app.models.confirmation import ConfirmationIn, ConfirmationOut, ConfirmedSkillEntry
from app.utils.mongo import oid_str
from bson import ObjectId
from datetime import datetime, timezone

router = APIRouter()


def now_utc():
    return datetime.now(timezone.utc)


@router.post("/", response_model=ConfirmationOut)
async def create_confirmation(payload: ConfirmationIn):
    db = get_db()

    try:
        snapshot_oid = ObjectId(payload.resume_snapshot_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid resume_snapshot_id")

    snap = await db["resume_snapshots"].find_one({"_id": snapshot_oid})
    if not snap:
        raise HTTPException(status_code=404, detail="Resume snapshot not found")

    confirmed_oids = []
    for entry in payload.confirmed:
        try:
            oid = ObjectId(entry.skill_id)
        except Exception:
            raise HTTPException(status_code=400, detail=f"Invalid skill_id: {entry.skill_id}")
        skill = await db["skills"].find_one({"_id": oid})
        if not skill:
            raise HTTPException(status_code=404, detail=f"Skill not found: {entry.skill_id}")
        confirmed_oids.append({"skill_id": oid})

    doc = {
        "user_id": payload.user_id,
        "resume_snapshot_id": snapshot_oid,
        "confirmed": confirmed_oids,
        "created_at": now_utc(),
    }
    res = await db["resume_skill_confirmations"].insert_one(doc)

    return ConfirmationOut(
        id=oid_str(res.inserted_id),
        user_id=doc["user_id"],
        resume_snapshot_id=oid_str(doc["resume_snapshot_id"]),
        confirmed=[ConfirmedSkillEntry(skill_id=oid_str(c["skill_id"])) for c in doc["confirmed"]],
        created_at=doc["created_at"],
    )


@router.get("/", response_model=list[ConfirmationOut])
async def list_confirmations(user_id: str | None = Query(default=None)):
    db = get_db()
    q = {}
    if user_id:
        q["user_id"] = user_id

    cursor = db["resume_skill_confirmations"].find(q)
    docs = await cursor.to_list(length=500)
    return [
        ConfirmationOut(
            id=oid_str(d["_id"]),
            user_id=d["user_id"],
            resume_snapshot_id=oid_str(d["resume_snapshot_id"]),
            confirmed=[ConfirmedSkillEntry(skill_id=oid_str(c["skill_id"])) for c in d.get("confirmed", [])],
            created_at=d["created_at"],
        )
        for d in docs
    ]
