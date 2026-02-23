from __future__ import annotations
from fastapi import APIRouter, HTTPException
from datetime import datetime, timezone
from app.core.db import get_db
from app.models.confirmation import SkillConfirmationIn, SkillConfirmationOut

router = APIRouter()


def now_utc():
    return datetime.now(timezone.utc)


@router.post("/{snapshot_id}/confirm-skills", response_model=SkillConfirmationOut)
async def confirm_skills(snapshot_id: str, payload: SkillConfirmationIn):
    db = get_db()

    doc = {
        "resume_snapshot_id": snapshot_id,
        "user_id": payload.user_id,
        "confirmed": [s.dict() for s in payload.confirmed],
        "rejected": [s.dict() for s in payload.rejected],
        "edited": [s.dict() for s in payload.edited],
        "updated_at": now_utc(),
    }

    result = await db.resume_skill_confirmations.update_one(
        {"resume_snapshot_id": snapshot_id, "user_id": payload.user_id},
        {"$set": doc, "$setOnInsert": {"created_at": now_utc()}},
        upsert=True,
    )

    saved = await db.resume_skill_confirmations.find_one(
        {"resume_snapshot_id": snapshot_id, "user_id": payload.user_id}
    )

    if not saved:
        raise HTTPException(status_code=500, detail="Failed to save confirmation.")

    return SkillConfirmationOut(
        snapshot_id=snapshot_id,
        user_id=saved["user_id"],
        confirmed=saved.get("confirmed", []),
        rejected=saved.get("rejected", []),
        edited=saved.get("edited", []),
        created_at=saved.get("created_at"),
        updated_at=saved.get("updated_at"),
    )


@router.get("/{snapshot_id}/confirm-skills", response_model=SkillConfirmationOut)
async def get_confirmation(snapshot_id: str, user_id: str = "student1"):
    db = get_db()

    saved = await db.resume_skill_confirmations.find_one(
        {"resume_snapshot_id": snapshot_id, "user_id": user_id}
    )

    if not saved:
        raise HTTPException(status_code=404, detail="No confirmation found for this snapshot.")

    return SkillConfirmationOut(
        snapshot_id=snapshot_id,
        user_id=saved["user_id"],
        confirmed=saved.get("confirmed", []),
        rejected=saved.get("rejected", []),
        edited=saved.get("edited", []),
        created_at=saved.get("created_at"),
        updated_at=saved.get("updated_at"),
    )