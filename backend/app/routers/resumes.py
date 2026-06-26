"""Resume ingestion routes for pasted or uploaded resumes plus promotion flows that turn confirmed resume skills into user data."""

from __future__ import annotations

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from datetime import datetime, timezone
from bson import ObjectId
from bson.binary import Binary
from app.core.db import get_db
from app.core.auth import require_user
from app.models.resume import ResumeSnapshotIn, ResumeSnapshotOut, ResumeSnapshotListEntryOut
from app.utils.ai import normalize_ai_preferences
from app.utils.rag import sync_rag_document
from app.utils.mongo import oid_str, ref_values
from app.utils.rewards import safe_increment_reward_counter
from app.utils.file_validation import sniff_pdf, sniff_docx
from pypdf import PdfReader
from docx import Document
import io

router = APIRouter()
MAX_RESUME_UPLOAD_BYTES = 5 * 1024 * 1024

def now_utc():
    return datetime.now(timezone.utc)


def _scoped_user_id(user: dict, requested_user_id: str | None = None) -> str:
    effective_user_id = oid_str(user["_id"])
    candidate = str(requested_user_id or "").strip()
    if candidate and candidate != effective_user_id:
        raise HTTPException(status_code=403, detail="user_id must match authenticated user")
    return effective_user_id

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


def extract_docx_text(file_bytes: bytes) -> str:
    try:
        document = Document(io.BytesIO(file_bytes))
        parts: list[str] = []
        for paragraph in document.paragraphs:
            text = str(paragraph.text or "")
            if not text.strip():
                parts.append("")
                continue
            style_name = str(getattr(paragraph.style, "name", "") or "").lower()
            normalized = text.strip()
            if style_name.startswith("list") and not normalized.startswith(("- ", "* ", "\u2022 ")):
                normalized = f"- {normalized}"
            parts.append(normalized)
        return "\n".join(parts).strip()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse DOCX: {e}")

# UC 3.1 – Resume Ingestion
@router.post("/text", response_model=ResumeSnapshotOut)
async def ingest_resume_text(payload: ResumeSnapshotIn, user=Depends(require_user)):
    db = get_db()
    ai_preferences = normalize_ai_preferences((user or {}).get("ai_preferences"))
    raw_text = payload.text.strip()
    if len(raw_text) < 10:
        raise HTTPException(status_code=400, detail="Resume text too short.")
    _scoped_user_id(user, oid_str(payload.user_id))

    doc = {
        "user_id": user["_id"],
        "source_type": "paste",
        "raw_text": raw_text,
        "metadata": {"source": "paste"},
        "image_ref": "/images/resume_icon.png",
        "created_at": now_utc(),
    }
    res = await db["resume_snapshots"].insert_one(doc)
    # Resume snapshots are a high-value grounding source for both tailoring and job
    # analysis, so we index them as soon as they are persisted.
    await sync_rag_document(
        db,
        user_id=oid_str(user["_id"]),
        source_type="resume_snapshot",
        source_id=oid_str(res.inserted_id),
        title="Resume Snapshot",
        text=raw_text,
        preferences=ai_preferences,
        metadata={"source_type": "paste"},
    )
    await safe_increment_reward_counter(db, oid_str(user["_id"]), "resume_snapshots_uploaded")
    preview = raw_text[:200] + ("..." if len(raw_text) > 200 else "")
    return {"snapshot_id": str(res.inserted_id), "preview": preview}

@router.post("/pdf", response_model=ResumeSnapshotOut)
async def ingest_resume_pdf(user_id: str = Form(...), file: UploadFile = File(...), user=Depends(require_user)):
    db = get_db()
    ai_preferences = normalize_ai_preferences((user or {}).get("ai_preferences"))
    user_id = _scoped_user_id(user, user_id)
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
    b = await file.read()
    if not b:
        raise HTTPException(status_code=400, detail="Empty file.")
    if len(b) > MAX_RESUME_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Resume uploads must be 5 MB or smaller.")
    if not sniff_pdf(b):
        raise HTTPException(status_code=400, detail="File content does not match a valid PDF.")
    raw_text = extract_pdf_text(b)
    if len(raw_text) < 50:
        raise HTTPException(status_code=400, detail="Extracted PDF text too short.")

    doc = {
        "user_id": user["_id"],
        "source_type": "pdf",
        "raw_text": raw_text,
        "metadata": {"source": "pdf", "filename": file.filename},
        "image_ref": "/images/resume_icon.png",
        "created_at": now_utc(),
    }
    res = await db["resume_snapshots"].insert_one(doc)
    # PDF uploads follow the same contract as pasted resumes: one canonical snapshot
    # record plus a derived retrieval index over the extracted text.
    await sync_rag_document(
        db,
        user_id=oid_str(user["_id"]),
        source_type="resume_snapshot",
        source_id=oid_str(res.inserted_id),
        title=file.filename or "Resume Snapshot",
        text=raw_text,
        preferences=ai_preferences,
        metadata={"source_type": "pdf", "filename": file.filename},
    )
    await safe_increment_reward_counter(db, oid_str(user["_id"]), "resume_snapshots_uploaded")
    preview = raw_text[:200] + ("..." if len(raw_text) > 200 else "")
    return {"snapshot_id": str(res.inserted_id), "preview": preview}


@router.post("/docx", response_model=ResumeSnapshotOut)
async def ingest_resume_docx(user_id: str = Form(...), file: UploadFile = File(...), user=Depends(require_user)):
    db = get_db()
    ai_preferences = normalize_ai_preferences((user or {}).get("ai_preferences"))
    user_id = _scoped_user_id(user, user_id)
    if not file.filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Only DOCX files are supported.")
    b = await file.read()
    if not b:
        raise HTTPException(status_code=400, detail="Empty file.")
    if len(b) > MAX_RESUME_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Resume uploads must be 5 MB or smaller.")
    if not sniff_docx(b):
        raise HTTPException(status_code=400, detail="File content does not match a valid DOCX.")
    raw_text = extract_docx_text(b)
    if len(raw_text) < 50:
        raise HTTPException(status_code=400, detail="Extracted DOCX text too short.")

    doc = {
        "user_id": user["_id"],
        "source_type": "docx",
        "raw_text": raw_text,
        "source_document": Binary(b),
        "metadata": {
            "source": "docx",
            "filename": file.filename,
            "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        },
        "image_ref": "/images/resume_icon.png",
        "created_at": now_utc(),
    }
    res = await db["resume_snapshots"].insert_one(doc)
    await sync_rag_document(
        db,
        user_id=oid_str(user["_id"]),
        source_type="resume_snapshot",
        source_id=oid_str(res.inserted_id),
        title=file.filename or "Resume Snapshot",
        text=raw_text,
        preferences=ai_preferences,
        metadata={"source_type": "docx", "filename": file.filename},
    )
    await safe_increment_reward_counter(db, oid_str(user["_id"]), "resume_snapshots_uploaded")
    preview = raw_text[:200] + ("..." if len(raw_text) > 200 else "")
    return {"snapshot_id": str(res.inserted_id), "preview": preview}


@router.get("/", response_model=list[ResumeSnapshotListEntryOut])
async def list_resume_snapshots(user_id: str | None = None, user=Depends(require_user)):
    db = get_db()
    user_id = _scoped_user_id(user, user_id)
    docs = await (
        db["resume_snapshots"]
        .find({"user_id": {"$in": ref_values(user_id)}})
        .sort("created_at", -1)
        .limit(50)
        .to_list(length=50)
    )
    return [
        ResumeSnapshotListEntryOut(
            snapshot_id=oid_str(doc.get("_id")),
            source_type=str(doc.get("source_type") or "unknown"),
            filename=str((doc.get("metadata") or {}).get("filename") or "").strip() or None,
            preview=str(doc.get("raw_text") or "")[:200] + ("..." if len(str(doc.get("raw_text") or "")) > 200 else ""),
            created_at=doc.get("created_at"),
        )
        for doc in docs
    ]

# UC 3.4 – Save confirmed resume-derived skills/projects into dashboard entities
# Minimal implementation: converts confirmed skills into evidence records (type="resume") tied to user_id,
# and optionally creates a "Resume: <date>" project to anchor evidence.
@router.post("/{snapshot_id}/promote")
async def promote_confirmed_skills(snapshot_id: str, user_id: str | None = Form(None), user=Depends(require_user)):
    db = get_db()
    user_id = _scoped_user_id(user, user_id)
    try:
        snap_oid = ObjectId(snapshot_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid snapshot_id")

    snap = await db["resume_snapshots"].find_one({"_id": snap_oid, "user_id": {"$in": ref_values(user_id)}})
    if not snap:
        raise HTTPException(status_code=404, detail="Resume snapshot not found")

    user_ref_values = ref_values(user_id)
    conf = await db["resume_skill_confirmations"].find_one(
        {"user_id": {"$in": user_ref_values}, "resume_snapshot_id": {"$in": [snap_oid, snapshot_id]}}
    )
    if not conf:
        raise HTTPException(status_code=404, detail="No confirmation found for this user + snapshot")

    confirmed = conf.get("confirmed", [])
    if not confirmed:
        return {"snapshot_id": snapshot_id, "user_id": user_id, "promoted": 0, "project_id": None}

    # Create (or reuse) a resume project anchor
    proj_title = f"Resume Snapshot {snapshot_id[:8]}"
    user_oid = user["_id"]
    existing_proj = await db["projects"].find_one({"user_id": {"$in": user_ref_values}, "title": proj_title})
    if existing_proj:
        project_oid = existing_proj["_id"]
    else:
        pdoc = {
            "user_id": user_oid,
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
            "user_id": user_oid,
            "type": "resume",
            "project_id": project_oid,
            "skill_ids": [skill_oid],
            "source": f"resume_snapshot:{snapshot_id}",
        }
        exists = await db["evidence"].find_one(q)
        if exists:
            continue

        edoc = {
            "user_id": user_oid,
            "user_email": None,
            "type": "resume",
            "title": c.get("skill_name", "Resume Evidence"),
            "source": f"resume_snapshot:{snapshot_id}",
            "text_excerpt": "Promoted from confirmed resume skills.",
            "skill_ids": [skill_oid],
            "project_id": project_oid,
            "tags": ["resume", "promoted"],
            "origin": "system",
            "created_at": now_utc(),
            "updated_at": now_utc(),
        }
        await db["evidence"].insert_one(edoc)
        promoted += 1

    return {"snapshot_id": snapshot_id, "user_id": user_id, "promoted": promoted, "project_id": oid_str(project_oid)}
