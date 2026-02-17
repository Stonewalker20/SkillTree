from fastapi import APIRouter
from app.core.db import get_db

router = APIRouter()

@router.get("/health")
async def health():
    db = get_db()
    cols = await db.list_collection_names()
    return {"status": "ok", "db": db.name, "collections": cols}

@router.get("/db_counts")
async def db_counts():
    db = get_db()
    return {
        "db": str(db.name),
        "skills": await db["skills"].count_documents({}),
        "resume_snapshots": await db["resume_snapshots"].count_documents({}),
        "evidence": await db["evidence"].count_documents({}),
        "jobs": await db["jobs"].count_documents({}),
    }



