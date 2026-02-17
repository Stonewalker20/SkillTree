from __future__ import annotations
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from datetime import datetime, timezone
from app.core.db import get_db
from app.models.resume import ResumeSnapshotIn, ResumeSnapshotOut
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

    res = await db.resume_snapshots.insert_one(doc)
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

    res = await db.resume_snapshots.insert_one(doc)
    preview = raw_text[:200] + ("..." if len(raw_text) > 200 else "")
    return {"snapshot_id": str(res.inserted_id), "preview": preview}

