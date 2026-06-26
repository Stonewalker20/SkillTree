"""Helpers for reading and migrating portfolio items into canonical evidence storage."""

from __future__ import annotations

from typing import Any

from app.utils.mongo import canonical_object_refs, oid_str, ref_values


def portfolio_dedupe_key(doc: dict[str, Any]) -> str:
    legacy_id = oid_str(doc.get("legacy_portfolio_item_id"))
    if legacy_id:
        return legacy_id
    return oid_str(doc.get("_id"))


def portfolio_item_to_evidence_doc(doc: dict[str, Any], *, preserve_id: bool = False) -> dict[str, Any]:
    evidence_doc = {
        "user_id": canonical_object_refs([doc.get("user_id")])[0] if canonical_object_refs([doc.get("user_id")]) else doc.get("user_id"),
        "user_email": None,
        "type": doc.get("type") if doc.get("type") in {"project", "paper", "cert", "other"} else "other",
        "title": str(doc.get("title") or "").strip(),
        "source": (doc.get("links") or [None])[0] or doc.get("org") or "structured-evidence",
        "text_excerpt": str(doc.get("summary") or "").strip() or str(doc.get("title") or "").strip(),
        "skill_ids": canonical_object_refs(doc.get("skill_ids") or []),
        "project_id": None,
        "tags": [str(value or "").strip() for value in (doc.get("tags") or []) if str(value or "").strip()],
        "origin": "user",
        "structured_evidence": True,
        "portfolio_item_type": str(doc.get("type") or "other").strip() or "other",
        "org": doc.get("org"),
        "date_start": doc.get("date_start"),
        "date_end": doc.get("date_end"),
        "summary": doc.get("summary"),
        "bullets": [str(value or "").strip() for value in (doc.get("bullets") or []) if str(value or "").strip()],
        "links": [str(value or "").strip() for value in (doc.get("links") or []) if str(value or "").strip()],
        "visibility": str(doc.get("visibility") or "private").strip() or "private",
        "priority": int(doc.get("priority") or 0),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
        "legacy_portfolio_item_id": doc.get("_id"),
    }
    if preserve_id and doc.get("_id") is not None:
        evidence_doc["_id"] = doc.get("_id")
    return evidence_doc


def serialize_portfolio_doc(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": oid_str(doc.get("_id")),
        "user_id": oid_str(doc.get("user_id")),
        "type": doc.get("portfolio_item_type", doc.get("type", "other")),
        "title": doc.get("title", ""),
        "org": doc.get("org"),
        "date_start": doc.get("date_start"),
        "date_end": doc.get("date_end"),
        "summary": doc.get("summary"),
        "bullets": doc.get("bullets", []),
        "links": doc.get("links", []),
        "skill_ids": [oid_str(value) for value in (doc.get("skill_ids") or [])],
        "tags": doc.get("tags", []),
        "visibility": doc.get("visibility", "private"),
        "priority": doc.get("priority", 0),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


async def load_legacy_portfolio_docs(db, user_id: Any) -> list[dict[str, Any]]:
    return await (
        db["portfolio_items"]
        .find({"user_id": {"$in": ref_values(user_id)}})
        .sort("priority", -1)
        .sort("updated_at", -1)
        .to_list(length=500)
    )
