"""Dashboard summary routes that aggregate user metrics, recent activity, and top skill category signals."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from bson import ObjectId
from app.core.db import get_db
from app.core.auth import require_user
from app.utils.mongo import oid_str, ref_values
from app.utils.portfolio_records import load_legacy_portfolio_docs

router = APIRouter()


def _score_percent(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round((numerator / denominator) * 100.0, 2)


def _safe_count(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


# UC 1.4 – Dashboard Summary (user-specific)
@router.get("/summary")
async def dashboard_summary(
    user=Depends(require_user),
    top_n: int = Query(default=8, ge=1, le=50),
):
    db = get_db()

    # ✅ Correct user id handling
    user_oid: ObjectId = user["_id"]
    user_id_str = oid_str(user_oid)
    user_refs = [user_oid, user_id_str]

    # Recent projects
    projects = await (
        db["projects"]
        .find({"user_id": {"$in": user_refs}}, {"title": 1, "description": 1, "created_at": 1})
        .sort("created_at", -1)
        .limit(10)
        .to_list(length=10)
    )
    proj_out = [
        {"id": oid_str(p["_id"]), "title": p.get("title", ""), "created_at": p.get("created_at")}
        for p in projects
    ]

    recent_activity: list[dict] = []

    recent_project_docs = await (
        db["projects"]
        .find({"user_id": {"$in": user_refs}}, {"title": 1, "created_at": 1, "updated_at": 1})
        .sort("updated_at", -1)
        .limit(10)
        .to_list(length=10)
    )
    for project in recent_project_docs:
        stamp = project.get("updated_at") or project.get("created_at")
        recent_activity.append(
            {
                "id": f"project:{oid_str(project['_id'])}",
                "type": "project",
                "action": "updated" if project.get("updated_at") and project.get("updated_at") != project.get("created_at") else "created",
                "name": project.get("title", "Project"),
                "date": stamp,
            }
        )

    recent_evidence_docs = await (
        db["evidence"]
        .find(
            {"user_id": {"$in": user_refs}, "origin": "user"},
            {"title": 1, "type": 1, "created_at": 1, "updated_at": 1},
        )
        .sort("updated_at", -1)
        .limit(10)
        .to_list(length=10)
    )
    for evidence in recent_evidence_docs:
        stamp = evidence.get("updated_at") or evidence.get("created_at")
        recent_activity.append(
            {
                "id": f"evidence:{oid_str(evidence['_id'])}",
                "type": evidence.get("type", "evidence"),
                "action": "updated" if evidence.get("updated_at") and evidence.get("updated_at") != evidence.get("created_at") else "added",
                "name": evidence.get("title", "Evidence"),
                "date": stamp,
            }
        )

    recent_activity = sorted(
        [item for item in recent_activity if item.get("date")],
        key=lambda item: item["date"],
        reverse=True,
    )[:6]

    # Evidence counts per skill (via evidence.skill_ids)
    # This expects evidence.skill_ids are strings of ObjectIds.
    top_skills = []
    rows = await (
        db["evidence"]
        .aggregate(
            [
                {"$match": {"user_id": {"$in": user_refs}}},
                {"$unwind": {"path": "$skill_ids", "preserveNullAndEmptyArrays": False}},
                {"$group": {"_id": "$skill_ids", "evidence_count": {"$sum": 1}}},
                {"$sort": {"evidence_count": -1}},
                {"$limit": top_n},
            ]
        )
        .to_list(length=top_n)
    )
    for r in rows:
        sid = r.get("_id")
        skill = await db["skills"].find_one({"_id": {"$in": ref_values(sid)}}, {"name": 1, "category": 1})
        top_skills.append(
            {
                "skill_id": oid_str(sid),
                "skill_name": (skill or {}).get("name", ""),
                "category": (skill or {}).get("category", ""),
                "evidence_count": int(r.get("evidence_count", 0)),
            }
        )

    # ✅ Count confirmed skills correctly (counts entries, not documents)
    # This counts ALL confirmed skills across all confirmations for the user.
    # If you only want profile (resume_snapshot_id == null), I’ll show that variant below.
    # ✅ Count confirmed skills for PROFILE ONLY (resume_snapshot_id == None)
    confirmed_count_rows = await (
        db["resume_skill_confirmations"]
        .aggregate(
            [
                {"$match": {"user_id": {"$in": user_refs}, "resume_snapshot_id": None}},
                {"$unwind": {"path": "$confirmed", "preserveNullAndEmptyArrays": False}},
                {"$group": {"_id": "$confirmed.skill_id"}},
                {"$count": "n"},
            ]
        )
        .to_list(length=1)
    )
    confirmed_skills = int((confirmed_count_rows[0]["n"] if confirmed_count_rows else 0))

    totals = {
        "projects": await db["projects"].count_documents({"user_id": {"$in": user_refs}}),
        "evidence": await db["evidence"].count_documents({"user_id": {"$in": user_refs}}),
        "confirmed_skills": confirmed_skills,
    }

    match_score_rows = await (
        db["job_match_runs"]
        .aggregate(
            [
                {"$match": {"user_id": {"$in": user_refs}}},
                {"$group": {"_id": None, "avg_match_score": {"$avg": "$analysis.match_score"}}},
            ]
        )
        .to_list(length=1)
    )
    average_match_score = round(float((match_score_rows[0] or {}).get("avg_match_score", 0) or 0), 2) if match_score_rows else 0.0
    tailored_resumes = await db["tailored_resumes"].count_documents({"user_id": {"$in": user_refs}})

    evidence_items = await (
        db["evidence"]
        .find({"user_id": {"$in": user_refs}, "origin": "user"}, {"type": 1, "skill_ids": 1, "structured_evidence": 1})
        .to_list(length=2000)
    )
    legacy_portfolio_items = await load_legacy_portfolio_docs(db, user_oid)
    known_portfolio_keys = {
        oid_str(item.get("legacy_portfolio_item_id")) or oid_str(item.get("_id"))
        for item in evidence_items
        if item.get("structured_evidence") is True
    }
    for item in legacy_portfolio_items:
        if oid_str(item.get("_id")) in known_portfolio_keys:
            continue
        evidence_items.append(
            {
                "_id": item.get("_id"),
                "type": item.get("type", "other"),
                "skill_ids": item.get("skill_ids", []),
                "structured_evidence": True,
            }
        )
    recent_match_runs = await (
        db["job_match_runs"]
        .find({"user_id": {"$in": user_refs}}, {"analysis": 1, "created_at": 1})
        .sort("created_at", -1)
        .limit(6)
        .to_list(length=6)
    )

    portfolio_type_counts: dict[str, int] = {}
    for item in evidence_items:
        item_type = str(item.get("type") or "other").strip() or "other"
        portfolio_type_counts[item_type] = portfolio_type_counts.get(item_type, 0) + 1

    portfolio_skill_ids = {
        oid_str(skill_id)
        for item in evidence_items
        for skill_id in (item.get("skill_ids") or [])
        if oid_str(skill_id)
    }
    evidence_skill_ids = {
        oid_str(skill_id)
        for item in evidence_items
        for skill_id in (item.get("skill_ids") or [])
        if oid_str(skill_id)
    }

    recent_job_skill_ids: set[str] = set()
    recent_match_trend: list[dict] = []
    recent_job_ids: list[ObjectId] = []
    total_recent_job_skill_count = 0
    total_recent_matched_skill_count = 0
    total_recent_evidence_backed_skill_count = 0

    for run in recent_match_runs:
        job_id = run.get("job_id")
        if isinstance(job_id, ObjectId):
            recent_job_ids.append(job_id)
        elif isinstance(job_id, str) and ObjectId.is_valid(job_id):
            recent_job_ids.append(ObjectId(job_id))

    recent_job_docs = await (
        db["job_ingests"]
        .find({"_id": {"$in": recent_job_ids}}, {"extracted_skills.skill_id": 1})
        .to_list(length=len(recent_job_ids) or 1)
    )
    job_skill_ids_by_job_id: dict[str, set[str]] = {}
    for job_doc in recent_job_docs:
        job_skill_ids_by_job_id[oid_str(job_doc.get("_id"))] = {
            str(entry.get("skill_id") or "").strip()
            for entry in (job_doc.get("extracted_skills") or [])
            if str(entry.get("skill_id") or "").strip()
        }

    for index, run in enumerate(reversed(recent_match_runs), start=1):
        analysis = run.get("analysis") or {}
        run_job_id = oid_str(run.get("job_id"))
        extracted_ids = set(job_skill_ids_by_job_id.get(run_job_id, set()))
        matched_ids = {
            str(skill_id).strip()
            for skill_id in (analysis.get("matched_skill_ids") or [])
            if str(skill_id).strip()
        }
        matched_names = {
            str(skill_name).strip()
            for skill_name in (analysis.get("matched_skills") or [])
            if str(skill_name).strip()
        }
        extracted_count = len(extracted_ids) or _safe_count(analysis.get("extracted_skill_count"))
        matched_count = (
            len(matched_ids)
            or _safe_count(analysis.get("matched_skill_count"))
            or len(matched_names)
        )
        evidence_backed_count = len(matched_ids & evidence_skill_ids)
        if matched_count > 0 and evidence_backed_count == 0:
            evidence_backed_count = min(
                matched_count,
                _safe_count(analysis.get("evidence_aligned_count")),
            )
        recent_job_skill_ids.update(extracted_ids)
        total_recent_job_skill_count += extracted_count
        total_recent_matched_skill_count += matched_count
        total_recent_evidence_backed_skill_count += evidence_backed_count
        recent_match_trend.append(
            {
                "label": f"Run {index}",
                "score": round(float(analysis.get("match_score") or 0.0), 2),
                "created_at": run.get("created_at"),
            }
        )

    portfolio_to_job_analytics = {
        "job_skill_coverage_pct": _score_percent(len(portfolio_skill_ids & recent_job_skill_ids), len(recent_job_skill_ids)),
        "matched_skill_rate_pct": _score_percent(total_recent_matched_skill_count, total_recent_job_skill_count),
        "evidence_backed_match_pct": _score_percent(total_recent_evidence_backed_skill_count, total_recent_matched_skill_count),
        "portfolio_backed_match_pct": _score_percent(total_recent_evidence_backed_skill_count, total_recent_matched_skill_count),
        "portfolio_skill_count": len(portfolio_skill_ids),
        "job_skill_count": len(recent_job_skill_ids),
    }

    portfolio_type_distribution = [
        {"type": item_type, "count": count}
        for item_type, count in sorted(portfolio_type_counts.items(), key=lambda item: (-item[1], item[0]))
    ]

    return {
        "user_id": user_id_str,
        "totals": totals,
        "average_match_score": average_match_score,
        "tailored_resumes": tailored_resumes,
        "recent_projects": proj_out,
        "recent_activity": recent_activity,
        "top_skills_by_evidence": top_skills,
        "portfolio_to_job_analytics": portfolio_to_job_analytics,
        "portfolio_type_distribution": portfolio_type_distribution,
        "recent_match_trend": recent_match_trend,
    }
