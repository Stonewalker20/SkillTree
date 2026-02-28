from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from datetime import datetime, timezone
from bson import ObjectId

from app.core.db import get_db
from app.models.portfolio import PortfolioItemIn, PortfolioItemOut, PortfolioItemPatch
from app.utils.mongo import oid_str

router = APIRouter()

def now_utc():
    return datetime.now(timezone.utc)

@router.post("/items", response_model=PortfolioItemOut)
async def create_portfolio_item(payload: PortfolioItemIn):
    db = get_db()
    doc = payload.model_dump()
    doc["created_at"] = now_utc()
    doc["updated_at"] = now_utc()
    res = await db["portfolio_items"].insert_one(doc)
    return {"id": oid_str(res.inserted_id), **doc}

@router.get("/items", response_model=list[PortfolioItemOut])
async def list_portfolio_items(
    user_id: str = Query(...),
    type: str | None = Query(default=None),
    visibility: str | None = Query(default=None),
):
    db = get_db()
    q: dict = {"user_id": user_id}
    if type:
        q["type"] = type
    if visibility:
        q["visibility"] = visibility

    cursor = db["portfolio_items"].find(q).sort("priority", -1).sort("updated_at", -1)
    docs = await cursor.to_list(length=500)
    out = []
    for d in docs:
        out.append(
            {
                "id": oid_str(d["_id"]),
                "user_id": d["user_id"],
                "type": d.get("type", "other"),
                "title": d.get("title", ""),
                "org": d.get("org"),
                "date_start": d.get("date_start"),
                "date_end": d.get("date_end"),
                "summary": d.get("summary"),
                "bullets": d.get("bullets", []),
                "links": d.get("links", []),
                "skill_ids": d.get("skill_ids", []),
                "tags": d.get("tags", []),
                "visibility": d.get("visibility", "private"),
                "priority": d.get("priority", 0),
                "created_at": d.get("created_at"),
                "updated_at": d.get("updated_at"),
            }
        )
    return out

@router.patch("/items/{item_id}", response_model=PortfolioItemOut)
async def patch_portfolio_item(item_id: str, payload: PortfolioItemPatch):
    db = get_db()
    try:
        oid = ObjectId(item_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid item_id")

    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    updates["updated_at"] = now_utc()

    res = await db["portfolio_items"].update_one({"_id": oid}, {"$set": updates})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Portfolio item not found")

    d = await db["portfolio_items"].find_one({"_id": oid})
    return {
        "id": oid_str(d["_id"]),
        "user_id": d["user_id"],
        "type": d.get("type", "other"),
        "title": d.get("title", ""),
        "org": d.get("org"),
        "date_start": d.get("date_start"),
        "date_end": d.get("date_end"),
        "summary": d.get("summary"),
        "bullets": d.get("bullets", []),
        "links": d.get("links", []),
        "skill_ids": d.get("skill_ids", []),
        "tags": d.get("tags", []),
        "visibility": d.get("visibility", "private"),
        "priority": d.get("priority", 0),
        "created_at": d.get("created_at"),
        "updated_at": d.get("updated_at"),
    }

@router.delete("/items/{item_id}")
async def delete_portfolio_item(item_id: str):
    db = get_db()
    try:
        oid = ObjectId(item_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid item_id")

    res = await db["portfolio_items"].delete_one({"_id": oid})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Portfolio item not found")
    return {"deleted": True, "id": item_id}
