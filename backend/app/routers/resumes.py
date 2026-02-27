from __future__ import annotations

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from datetime import datetime, timezone
from bson import ObjectId
from app.core.db import get_db
from app.models.resume import ResumeSnapshotIn, ResumeSnapshotOut
from app.utils.mongo import oid_str
from pypdf import PdfReader
import io

router = APIRouter()

def now_utc():
    return datetime.now(timezone.utc)

def extract_pdf_text(file_bytes: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        parts = []
        for page in reader.pages:
            t = page.extract_text() or ""
            parts.append(t)
        return "\n".join(parts).strip()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse PDF: {e}")

# UC 3.1 – Resume Ingestion (already implemented)
@router.post("/text", response_model=ResumeSnapshotOut)
async def ingest_resume_text(payload: ResumeSnapshotIn):
    db = get_db()
    raw_text = payload.text.strip()
    if len(raw_text) < 10:
        raise HTTPException(status_code=400, detail="Resume text too short.")

    doc = {
        "user_id": payload.user_id,
        "source_type": "paste",
        "raw_text": raw_text,
        "metadata": {"source": "paste"},
        "image_ref": "/images/resume_icon.png",
        "created_at": now_utc(),
    }
    res = await db["resume_snapshots"].insert_one(doc)
    preview = raw_text[:200] + ("..." if len(raw_text) > 200 else "")
    return {"snapshot_id": str(res.inserted_id), "preview": preview}

@router.post("/pdf", response_model=ResumeSnapshotOut)
async def ingest_resume_pdf(user_id: str = Form(...), file: UploadFile = File(...)):
    db = get_db()
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
    b = await file.read()
    if not b:
        raise HTTPException(status_code=400, detail="Empty file.")
    raw_text = extract_pdf_text(b)
    if len(raw_text) < 50:
        raise HTTPException(status_code=400, detail="Extracted PDF text too short.")

    doc = {
        "user_id": user_id,
        "source_type": "pdf",
        "raw_text": raw_text,
        "metadata": {"source": "pdf", "filename": file.filename},
        "image_ref": "/images/resume_icon.png",
        "created_at": now_utc(),
    }
    res = await db["resume_snapshots"].insert_one(doc)
    preview = raw_text[:200] + ("..." if len(raw_text) > 200 else "")
    return {"snapshot_id": str(res.inserted_id), "preview": preview}

# UC 3.4 – Save confirmed resume-derived skills/projects into dashboard entities
# Minimal implementation: converts confirmed skills into evidence records (type="resume") tied to user_id,
# and optionally creates a "Resume: <date>" project to anchor evidence.
@router.post("/{snapshot_id}/promote")
async def promote_confirmed_skills(snapshot_id: str, user_id: str = Form(...)):
    db = get_db()
    try:
        snap_oid = ObjectId(snapshot_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid snapshot_id")

    snap = await db["resume_snapshots"].find_one({"_id": snap_oid})
    if not snap:
        raise HTTPException(status_code=404, detail="Resume snapshot not found")

    conf = await db["resume_skill_confirmations"].find_one({"user_id": user_id, "resume_snapshot_id": snap_oid})
    if not conf:
        raise HTTPException(status_code=404, detail="No confirmation found for this user + snapshot")

    confirmed = conf.get("confirmed", [])
    if not confirmed:
        return {"snapshot_id": snapshot_id, "user_id": user_id, "promoted": 0, "project_id": None}

    # Create (or reuse) a resume project anchor
    proj_title = f"Resume Snapshot {snapshot_id[:8]}"
    existing_proj = await db["projects"].find_one({"user_id": user_id, "title": proj_title})
    if existing_proj:
        project_oid = existing_proj["_id"]
    else:
        pdoc = {
            "user_id": user_id,
            "title": proj_title,
            "description": "Auto-created from resume promotion.",
            "tags": ["resume"],
            "created_at": now_utc(),
            "updated_at": now_utc(),
        }
        pres = await db["projects"].insert_one(pdoc)
        project_oid = pres.inserted_id

    # Promote each confirmed skill: link project<->skill + create evidence
    promoted = 0
    for c in confirmed:
        skill_oid = c.get("skill_id")
        if not skill_oid:
            continue

        # link project-skill
        await db["project_skill_links"].update_one(
            {"project_id": project_oid, "skill_id": skill_oid},
            {"$setOnInsert": {"project_id": project_oid, "skill_id": skill_oid, "created_at": now_utc()}},
            upsert=True,
        )

        # evidence record (dedupe by snapshot+skill)
        q = {
            "user_id": user_id,
            "type": "resume",
            "project_id": oid_str(project_oid),
            "skill_ids": [oid_str(skill_oid)],
            "source": f"resume_snapshot:{snapshot_id}",
        }
        exists = await db["evidence"].find_one(q)
        if exists:
            continue

        edoc = {
            "user_id": user_id,
            "user_email": None,
            "type": "resume",
            "title": c.get("skill_name", "Resume Evidence"),
            "source": f"resume_snapshot:{snapshot_id}",
            "text_excerpt": "Promoted from confirmed resume skills.",
            "skill_ids": [oid_str(skill_oid)],
            "project_id": oid_str(project_oid),
            "tags": ["resume", "promoted"],
            "created_at": now_utc(),
            "updated_at": now_utc(),
        }
        await db["evidence"].insert_one(edoc)
        promoted += 1

    return {"snapshot_id": snapshot_id, "user_id": user_id, "promoted": promoted, "project_id": oid_str(project_oid)}
