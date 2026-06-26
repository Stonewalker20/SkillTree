"""Taxonomy routes for managing skill aliases and graph-style relationships between skills."""

from __future__ import annotations

from collections import deque
import re
from typing import Iterable

from fastapi import APIRouter, HTTPException, Query, Depends
from datetime import datetime, timezone
from bson import ObjectId
from app.core.auth import require_user
from app.core.db import get_db
from app.utils.learning_resources import recommended_resources, recommended_resources_for_many
from app.utils.mongo import oid_str
from app.utils.role_weights import refresh_role_weights
from app.utils.ai import cosine_similarity, embed_texts
from app.utils.skill_catalog import expand_alias_variants, unique_casefolded, normalize_skill_text
from app.models.taxonomy import (
    CareerPathDetailOut,
    LearningPathRecommendation,
    LearningPathProgressOut,
    LearningPathProgressPatchIn,
    LearningPathSkillDetailOut,
    SkillAliasesUpdate,
    SkillGraphEdge,
    SkillGraphNode,
    SkillGraphOut,
    SkillRelationIn,
    SkillRelationOut,
    SkillTrajectoryCluster,
    SkillTrajectoryOut,
    SkillTrajectoryPath,
)

router = APIRouter()

def now_utc():
    return datetime.now(timezone.utc)


def _trajectory_confidence_label(score: float) -> str:
    if score >= 80:
        return "High"
    if score >= 60:
        return "Medium"
    return "Low"


def _normalize_phrase_list(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


async def _load_profile_confirmation_entries(db, user_oid: ObjectId) -> list[dict]:
    profile = await db["resume_skill_confirmations"].find_one(
        {"user_id": user_oid, "resume_snapshot_id": None},
        {"confirmed": 1},
    )
    return list((profile or {}).get("confirmed") or [])


async def _build_personal_vector_score(
    db,
    user_oid: ObjectId,
    confirmed_entries: list[dict],
    skill_docs: dict[str, dict],
    role_text: str,
) -> float:
    confirmed_skill_names = [
        str((skill_docs.get(oid_str(entry.get("skill_id"))) or {}).get("name") or "").strip()
        for entry in confirmed_entries
        if oid_str(entry.get("skill_id"))
    ]
    evidence_docs = await db["evidence"].find(
        {"user_id": user_oid, "origin": "user"},
        {"text_excerpt": 1, "title": 1},
    ).to_list(length=100)
    resume_doc = await db["resume_snapshots"].find_one(
        {"user_id": user_oid},
        {"raw_text": 1},
        sort=[("created_at", -1)],
    )
    source_parts: list[str] = []
    if confirmed_skill_names:
        source_parts.append("Confirmed skills: " + ", ".join(_normalize_phrase_list(confirmed_skill_names)[:40]))
    for evidence in evidence_docs[:8]:
        source_parts.append(str(evidence.get("title") or ""))
        source_parts.append(str(evidence.get("text_excerpt") or "")[:300])
    if resume_doc:
        source_parts.append(str(resume_doc.get("raw_text") or "")[:1200])
    profile_text = "\n".join(part for part in source_parts if str(part or "").strip()).strip()
    if not profile_text or not role_text:
        return 0.0
    vectors, _provider = await embed_texts([profile_text, role_text])
    if len(vectors) != 2:
        return 0.0
    return round(max(0.0, min(100.0, cosine_similarity(vectors[0], vectors[1]) * 100.0)), 2)


async def _load_recent_job_history_missing_counts(db, user_oid: ObjectId) -> tuple[dict[str, int], list[str]]:
    rows = await db["job_match_runs"].find(
        {"user_id": user_oid},
        {"title": 1},
    ).sort("updated_at", -1).limit(12).to_list(length=12)
    titles: list[str] = []
    for row in rows:
        title = str(row.get("title") or "").strip()
        if title:
            titles.append(title)
    return {}, _normalize_phrase_list(titles)


async def _load_learning_progress_lookup(db, user_oid: ObjectId) -> dict[str, str]:
    rows = await db["learning_path_progress"].find({"user_id": user_oid}, {"skill_name": 1, "status": 1}).to_list(length=500)
    return {
        str(row.get("skill_name") or "").strip().casefold(): str(row.get("status") or "not_started")
        for row in rows
        if str(row.get("skill_name") or "").strip()
    }


def _build_learning_path(
    career_paths: list[SkillTrajectoryPath],
    clusters: list[SkillTrajectoryCluster],
    missing_history_counts: dict[str, int],
    recent_job_titles: list[str],
) -> list[LearningPathRecommendation]:
    if not career_paths:
        return []

    top_paths = career_paths[:3]
    cluster_name = clusters[0].category if clusters else "current"
    gap_frequency: dict[str, int] = dict(missing_history_counts)
    for path in top_paths:
        for skill in path.missing_skills[:5]:
            gap_frequency[skill] = gap_frequency.get(skill, 0) + 1
    prioritized_missing = [skill for skill, _count in sorted(gap_frequency.items(), key=lambda item: (-item[1], item[0]))]

    matched_anchor_skills: list[str] = []
    for path in top_paths:
        matched_anchor_skills.extend(path.matched_skills[:2])
    matched_anchor_skills = list(dict.fromkeys(skill for skill in matched_anchor_skills if skill))

    recommendations: list[LearningPathRecommendation] = []
    if prioritized_missing:
        recommendations.append(
            LearningPathRecommendation(
                phase="Phase 1",
                title="Close the highest-impact skill gaps",
                target_skills=prioritized_missing[:3],
                rationale=(
                    f"These missing skills appear most often across your top projected career paths and are the fastest way "
                    f"to improve fit for roles like {', '.join(path.role_name for path in top_paths[:2])}"
                    f"{f' and recent job targets such as {recent_job_titles[0]}' if recent_job_titles else ''}."
                ),
                evidence_action="Complete one focused project or evidence upload for each target skill so the gap closes with proof, not just a claim.",
            )
        )
    if matched_anchor_skills:
        recommendations.append(
            LearningPathRecommendation(
                phase="Phase 2",
                title=f"Deepen your {cluster_name} strength into role-ready proof",
                target_skills=matched_anchor_skills[:3],
                rationale=(
                    "You already have traction in these skills. Strengthening them with measurable outcomes will increase both role alignment and resume quality."
                ),
                evidence_action="Add quantified project bullets, evidence entries, or work samples that demonstrate production-level use of these skills.",
            )
        )
    if prioritized_missing or matched_anchor_skills:
        recommendations.append(
            LearningPathRecommendation(
                phase="Phase 3",
                title="Turn learning into stronger evidence",
                target_skills=(prioritized_missing[:2] + matched_anchor_skills[:2])[:4],
                rationale=(
                    "Learning path progress only improves matching if it becomes visible in your evidence library and tailored resumes."
                ),
                evidence_action="After each learning milestone, upload evidence, confirm extracted skills, and attach the result to a concrete artifact tied to your target path.",
            )
        )
    return recommendations[:3]


def _serialize_skill_doc(doc: dict, *, distance: int, node_type: str) -> SkillGraphNode:
    return SkillGraphNode(
        skill_id=oid_str(doc.get("_id")),
        name=str(doc.get("name") or "").strip(),
        category=str(doc.get("category") or "").strip(),
        aliases=[str(alias or "").strip() for alias in (doc.get("aliases") or []) if str(alias or "").strip()],
        distance=distance,
        node_type=node_type,
    )


async def _load_skill_docs(db, skill_ids: Iterable[str]) -> dict[str, dict]:
    docs: dict[str, dict] = {}
    object_ids = [ObjectId(skill_id) for skill_id in skill_ids if ObjectId.is_valid(skill_id)]
    if not object_ids:
        return docs
    rows = await db["skills"].find({"_id": {"$in": object_ids}}, {"name": 1, "category": 1, "aliases": 1}).to_list(length=len(object_ids))
    for row in rows:
        docs[oid_str(row.get("_id"))] = row
    return docs


async def _build_explicit_graph(db, root_skill_id: str, depth: int) -> tuple[dict[str, int], list[SkillGraphEdge]]:
    visited: dict[str, int] = {root_skill_id: 0}
    edges: list[SkillGraphEdge] = []
    queue: deque[tuple[str, int]] = deque([(root_skill_id, 0)])

    while queue:
        current_skill_id, current_depth = queue.popleft()
        if current_depth >= depth:
            continue
        current_oid = ObjectId(current_skill_id)
        relations = await db["skill_relations"].find(
            {"$or": [{"from_skill_id": current_oid}, {"to_skill_id": current_oid}]}
        ).to_list(length=500)
        for relation in relations:
            from_skill_id = oid_str(relation.get("from_skill_id"))
            to_skill_id = oid_str(relation.get("to_skill_id"))
            if not from_skill_id or not to_skill_id:
                continue
            neighbor_skill_id = to_skill_id if from_skill_id == current_skill_id else from_skill_id
            next_distance = current_depth + 1
            if neighbor_skill_id not in visited or next_distance < visited[neighbor_skill_id]:
                visited[neighbor_skill_id] = next_distance
                queue.append((neighbor_skill_id, next_distance))
            edges.append(
                SkillGraphEdge(
                    source_skill_id=from_skill_id,
                    target_skill_id=to_skill_id,
                    relation_type=str(relation.get("relation_type") or "related_to"),
                    edge_type="explicit",
                    weight=1.0,
                )
            )
    return visited, edges


async def _infer_semantic_edges(db, root_skill_id: str, *, limit: int) -> list[SkillGraphEdge]:
    root_doc = await db["skills"].find_one({"_id": ObjectId(root_skill_id)}, {"name": 1, "category": 1, "aliases": 1, "hidden": 1})
    if not root_doc or root_doc.get("hidden") is True:
        return []
    candidates = await db["skills"].find({"hidden": {"$ne": True}}, {"name": 1, "category": 1, "aliases": 1}).to_list(length=5000)
    root_text = " ".join(
        [
            str(root_doc.get("name") or ""),
            str(root_doc.get("category") or ""),
            " ".join(str(alias or "") for alias in (root_doc.get("aliases") or [])),
        ]
    ).strip()
    candidate_docs = [doc for doc in candidates if oid_str(doc.get("_id")) != root_skill_id]
    if not candidate_docs:
        return []
    texts = [root_text] + [
        " ".join(
            [
                str(doc.get("name") or ""),
                str(doc.get("category") or ""),
                " ".join(str(alias or "") for alias in (doc.get("aliases") or [])),
            ]
        ).strip()
        for doc in candidate_docs
    ]
    vectors, _provider = await embed_texts(texts)
    if len(vectors) != len(texts):
        return []
    root_vec = vectors[0]
    ranked: list[tuple[float, dict]] = []
    for doc, vec in zip(candidate_docs, vectors[1:], strict=False):
        score = cosine_similarity(root_vec, vec)
        if score >= 0.56:
            ranked.append((score, doc))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [
        SkillGraphEdge(
            source_skill_id=root_skill_id,
            target_skill_id=oid_str(doc.get("_id")),
            relation_type="similar_to",
            edge_type="semantic",
            weight=round(score, 4),
        )
        for score, doc in ranked[:limit]
    ]


async def _infer_cooccurrence_edges(db, collection_name: str, field_name: str, root_skill_id: str, *, limit: int, edge_type: str) -> list[SkillGraphEdge]:
    rows = await db[collection_name].find({}).to_list(length=1000)
    counts: dict[str, int] = {}
    total = 0
    for row in rows:
        raw_values = row.get(field_name) or []
        values: list[str] = []
        for value in raw_values:
            if isinstance(value, dict):
                skill_id = oid_str(value.get("skill_id"))
                if skill_id:
                    values.append(skill_id)
            else:
                skill_id = oid_str(value)
                if skill_id:
                    values.append(skill_id)
        if root_skill_id not in values:
            continue
        total += 1
        for value in values:
            if value == root_skill_id:
                continue
            counts[value] = counts.get(value, 0) + 1
    if total == 0:
        return []
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    relation_type = "co_occurs_with"
    return [
        SkillGraphEdge(
            source_skill_id=root_skill_id,
            target_skill_id=skill_id,
            relation_type=relation_type,
            edge_type=edge_type,
            weight=round(count / total, 4),
        )
        for skill_id, count in ranked[:limit]
    ]


async def _load_role_weights(db, role_id: str) -> list[dict]:
    role_oid = ObjectId(role_id)
    stored = await db["role_skill_weights"].find_one({"role_id": role_oid}, {"weights": 1})
    if stored and isinstance(stored.get("weights"), list) and stored.get("weights"):
        return list(stored.get("weights") or [])
    return await refresh_role_weights(db, role_id)

# UC 4.4 – Maintain taxonomy: manage skill aliases
@router.put("/aliases/{skill_id}")
async def set_skill_aliases(skill_id: str, payload: SkillAliasesUpdate):
    db = get_db()
    try:
        oid = ObjectId(skill_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid skill_id")

    skill = await db["skills"].find_one({"_id": oid}, {"name": 1})
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    name_key = normalize_skill_text(skill.get("name", ""))
    aliases = [
        alias
        for alias in expand_alias_variants(unique_casefolded(payload.aliases), base_name=skill.get("name", ""))
        if normalize_skill_text(alias) != name_key
    ]

    res = await db["skills"].update_one({"_id": oid}, {"$set": {"aliases": aliases, "updated_at": now_utc()}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Skill not found")

    doc = await db["skills"].find_one({"_id": oid}, {"name": 1, "category": 1, "aliases": 1})
    return {"skill_id": skill_id, "name": doc.get("name",""), "category": doc.get("category",""), "aliases": doc.get("aliases", [])}

# UC 4.4 – Maintain taxonomy: manage relationships
@router.post("/relations", response_model=SkillRelationOut)
async def create_relation(payload: SkillRelationIn):
    db = get_db()
    try:
        from_oid = ObjectId(payload.from_skill_id)
        to_oid = ObjectId(payload.to_skill_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid skill_id in relation")

    if not await db["skills"].find_one({"_id": from_oid}):
        raise HTTPException(status_code=404, detail="from_skill_id not found")
    if not await db["skills"].find_one({"_id": to_oid}):
        raise HTTPException(status_code=404, detail="to_skill_id not found")

    doc = {
        "from_skill_id": from_oid,
        "to_skill_id": to_oid,
        "relation_type": payload.relation_type,
        "created_at": now_utc(),
    }
    existing = await db["skill_relations"].find_one(
        {
            "from_skill_id": from_oid,
            "to_skill_id": to_oid,
            "relation_type": payload.relation_type,
        }
    )
    if existing:
        return {
            "id": oid_str(existing["_id"]),
            "from_skill_id": payload.from_skill_id,
            "to_skill_id": payload.to_skill_id,
            "relation_type": payload.relation_type,
            "created_at": existing.get("created_at"),
        }

    res = await db["skill_relations"].insert_one(doc)
    return {
        "id": oid_str(res.inserted_id),
        "from_skill_id": payload.from_skill_id,
        "to_skill_id": payload.to_skill_id,
        "relation_type": payload.relation_type,
        "created_at": doc["created_at"],
    }

@router.get("/relations", response_model=list[SkillRelationOut])
async def list_relations(skill_id: str | None = None):
    db = get_db()
    q = {}
    if skill_id:
        try:
            oid = ObjectId(skill_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid skill_id")
        q = {"$or": [{"from_skill_id": oid}, {"to_skill_id": oid}]}
    docs = await db["skill_relations"].find(q).sort("created_at", -1).to_list(length=500)
    out = []
    for d in docs:
        out.append(
            {
                "id": oid_str(d["_id"]),
                "from_skill_id": oid_str(d["from_skill_id"]),
                "to_skill_id": oid_str(d["to_skill_id"]),
                "relation_type": d.get("relation_type", "related_to"),
                "created_at": d.get("created_at"),
            }
        )
    return out


@router.get("/graph/{skill_id}", response_model=SkillGraphOut)
async def get_skill_graph(
    skill_id: str,
    depth: int = Query(default=1, ge=1, le=3),
    limit: int = Query(default=8, ge=1, le=25),
    include_inferred: bool = Query(default=True),
):
    db = get_db()
    if not ObjectId.is_valid(skill_id):
        raise HTTPException(status_code=400, detail="Invalid skill_id")
    root_doc = await db["skills"].find_one({"_id": ObjectId(skill_id)}, {"name": 1, "category": 1, "aliases": 1})
    if not root_doc:
        raise HTTPException(status_code=404, detail="Skill not found")

    visited, explicit_edges = await _build_explicit_graph(db, skill_id, depth)
    inferred_edges: list[SkillGraphEdge] = []
    if include_inferred:
        inferred_edges.extend(await _infer_semantic_edges(db, skill_id, limit=limit))
        inferred_edges.extend(
            await _infer_cooccurrence_edges(
                db,
                "evidence",
                "skill_ids",
                skill_id,
                limit=limit,
                edge_type="evidence_cooccurrence",
            )
        )
        inferred_edges.extend(
            await _infer_cooccurrence_edges(
                db,
                "job_ingests",
                "extracted_skills",
                skill_id,
                limit=limit,
                edge_type="job_cooccurrence",
            )
        )
        for edge in inferred_edges:
            visited.setdefault(edge.target_skill_id, 1)

    skill_docs = await _load_skill_docs(db, visited.keys())
    nodes: list[SkillGraphNode] = []
    for node_skill_id, distance in sorted(visited.items(), key=lambda item: (item[1], item[0])):
        doc = skill_docs.get(node_skill_id)
        if not doc:
            continue
        nodes.append(_serialize_skill_doc(doc, distance=distance, node_type="seed" if node_skill_id == skill_id else "neighbor"))

    seen_edges: set[tuple[str, str, str, str]] = set()
    edges: list[SkillGraphEdge] = []
    for edge in [*explicit_edges, *inferred_edges]:
        key = (edge.source_skill_id, edge.target_skill_id, edge.relation_type, edge.edge_type)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        edges.append(edge)

    return SkillGraphOut(
        root_skill_id=skill_id,
        nodes=nodes,
        edges=edges,
    )


@router.get("/trajectory", response_model=SkillTrajectoryOut)
async def get_skill_trajectory(user=Depends(require_user)):
    db = get_db()
    user_oid = user["_id"]

    confirmed_entries = await _load_profile_confirmation_entries(db, user_oid)
    if not confirmed_entries:
        return SkillTrajectoryOut(generated_at=now_utc(), clusters=[], career_paths=[], learning_path=[])

    confirmed_skill_ids = [oid_str(entry.get("skill_id")) for entry in confirmed_entries if oid_str(entry.get("skill_id"))]
    skill_docs = await _load_skill_docs(db, confirmed_skill_ids)
    evidence_docs = await db["evidence"].find(
        {"user_id": user_oid, "origin": "user"},
        {"skill_ids": 1},
    ).to_list(length=2000)
    evidence_skill_ids = {
        oid_str(skill_id)
        for evidence in evidence_docs
        for skill_id in (evidence.get("skill_ids") or [])
        if oid_str(skill_id)
    }

    cluster_buckets: dict[str, dict] = {}
    for entry in confirmed_entries:
        skill_id = oid_str(entry.get("skill_id"))
        skill_doc = skill_docs.get(skill_id)
        if not skill_doc:
            continue
        category = str(skill_doc.get("category") or "Uncategorized").strip() or "Uncategorized"
        bucket = cluster_buckets.setdefault(
            category,
            {
                "skill_count": 0,
                "evidence_backed_count": 0,
                "proficiency_total": 0.0,
                "skill_names": [],
            },
        )
        bucket["skill_count"] += 1
        if skill_id in evidence_skill_ids:
            bucket["evidence_backed_count"] += 1
        bucket["proficiency_total"] += float(entry.get("proficiency") or 0.0)
        bucket["skill_names"].append(str(skill_doc.get("name") or "").strip())

    clusters = [
        SkillTrajectoryCluster(
            category=category,
            skill_count=int(bucket["skill_count"]),
            evidence_backed_count=int(bucket["evidence_backed_count"]),
            average_proficiency=round(float(bucket["proficiency_total"]) / max(1, int(bucket["skill_count"])), 2),
            skill_names=sorted({name for name in bucket["skill_names"] if name}),
        )
        for category, bucket in cluster_buckets.items()
    ]
    clusters.sort(key=lambda item: (-item.skill_count, -item.evidence_backed_count, item.category.lower()))

    roles = await db["roles"].find({}, {"name": 1, "description": 1}).sort("name", 1).to_list(length=250)
    if not roles:
        return SkillTrajectoryOut(generated_at=now_utc(), clusters=clusters, career_paths=[], learning_path=[])

    cluster_summary_text = " | ".join(
        f"{cluster.category}: {' '.join(cluster.skill_names[:8])}" for cluster in clusters[:5]
    ).strip()
    missing_history_counts, recent_job_titles = await _load_recent_job_history_missing_counts(db, user_oid)
    learning_progress = await _load_learning_progress_lookup(db, user_oid)

    career_paths: list[SkillTrajectoryPath] = []
    confirmed_skill_id_set = set(confirmed_skill_ids)
    for role in roles:
        role_id = oid_str(role.get("_id"))
        if not role_id:
            continue
        weights = await _load_role_weights(db, role_id)
        if not weights:
            continue

        total_weight = sum(float(item.get("weight") or 0.0) for item in weights) or float(len(weights))
        matched = [item for item in weights if str(item.get("skill_id") or "").strip() in confirmed_skill_id_set]
        missing = [item for item in weights if str(item.get("skill_id") or "").strip() not in confirmed_skill_id_set]
        matched_weight = sum(float(item.get("weight") or 0.0) for item in matched)
        evidence_weight = sum(
            float(item.get("weight") or 0.0)
            for item in matched
            if str(item.get("skill_id") or "").strip() in evidence_skill_ids
        )
        weighted_coverage = matched_weight / max(total_weight, 1e-6)
        evidence_support = evidence_weight / max(total_weight, 1e-6)

        role_text = " ".join(
            [
                str(role.get("name") or ""),
                str(role.get("description") or ""),
                " ".join(str(item.get("skill_name") or "") for item in weights[:10]),
            ]
        ).strip()
        semantic_alignment = 0.0
        if cluster_summary_text and role_text:
            vectors, _provider = await embed_texts([cluster_summary_text, role_text])
            if len(vectors) == 2:
                semantic_alignment = max(0.0, min(1.0, cosine_similarity(vectors[0], vectors[1])))
        personal_vector_alignment_score = await _build_personal_vector_score(
            db,
            user_oid,
            confirmed_entries,
            skill_docs,
            role_text,
        )

        matched_skill_names = [
            str(item.get("skill_name") or "")
            for item in sorted(matched, key=lambda entry: float(entry.get("weight") or 0.0), reverse=True)[:5]
            if str(item.get("skill_name") or "")
        ]
        missing_skill_names = [
            str(item.get("skill_name") or "")
            for item in sorted(missing, key=lambda entry: float(entry.get("weight") or 0.0), reverse=True)[:5]
            if str(item.get("skill_name") or "")
        ]
        cluster_scores: dict[str, float] = {}
        for item in matched:
            skill_doc = skill_docs.get(str(item.get("skill_id") or "").strip())
            category = str((skill_doc or {}).get("category") or "Uncategorized").strip() or "Uncategorized"
            cluster_scores[category] = cluster_scores.get(category, 0.0) + float(item.get("weight") or 0.0)
        dominant_cluster = sorted(cluster_scores.items(), key=lambda pair: (-pair[1], pair[0]))[0][0] if cluster_scores else (clusters[0].category if clusters else "")
        completed_missing = [
            skill_name
            for skill_name in missing_skill_names
            if learning_progress.get(skill_name.casefold()) == "completed"
        ]
        in_progress_missing = [
            skill_name
            for skill_name in missing_skill_names
            if learning_progress.get(skill_name.casefold()) == "in_progress"
        ]
        progress_bonus_score = round(min(8.0, (len(completed_missing) * 2.5) + (len(in_progress_missing) * 1.0)), 2)

        score = round(
            (
                (weighted_coverage * 0.48)
                + (evidence_support * 0.14)
                + (semantic_alignment * 0.18)
                + ((personal_vector_alignment_score / 100.0) * 0.20)
            )
            * 100.0
            + progress_bonus_score,
            2,
        )
        reasoning = (
            f"{role.get('name', 'This path')} most closely matches your {dominant_cluster or 'current'} cluster. "
            f"You cover {round(weighted_coverage * 100)}% of this path's weighted skills"
            f"{' and already have supporting evidence behind many of them.' if evidence_support >= 0.35 else ', but you still need stronger evidence support.'}"
        )
        next_steps: list[str] = []
        if missing_skill_names:
            next_steps.append(f"Close the highest-impact gaps first: {', '.join(missing_skill_names[:3])}")
        if evidence_support < 0.35 and matched_skill_names:
            next_steps.append(f"Add stronger evidence or projects for: {', '.join(matched_skill_names[:2])}")
        if semantic_alignment < 0.45:
            next_steps.append("Add projects that use the same tooling and language common in this role family")

        career_paths.append(
            SkillTrajectoryPath(
                role_id=role_id,
                role_name=str(role.get("name") or "").strip(),
                score=score,
                confidence_label=_trajectory_confidence_label(score),
                cluster_category=dominant_cluster,
                personal_vector_alignment_score=personal_vector_alignment_score,
                progress_bonus_score=progress_bonus_score,
                matched_skills=matched_skill_names,
                missing_skills=missing_skill_names,
                top_role_skills=[
                    str(item.get("skill_name") or "")
                    for item in sorted(weights, key=lambda entry: float(entry.get("weight") or 0.0), reverse=True)[:6]
                    if str(item.get("skill_name") or "")
                ],
                reasoning=reasoning,
                next_steps=next_steps[:3],
            )
        )

    career_paths.sort(key=lambda item: (-item.score, item.role_name.lower()))
    top_career_paths = career_paths[:6]
    learning_path = _build_learning_path(top_career_paths, clusters, missing_history_counts, recent_job_titles)
    return SkillTrajectoryOut(
        generated_at=now_utc(),
        clusters=clusters,
        career_paths=top_career_paths,
        learning_path=learning_path,
    )


def _progress_skill_key(skill_name: str) -> str:
    """Normalized key used to dedupe learning-path progress rows.

    Mirrors the normalization applied in `app.main.normalize_learning_path_progress_records`
    and backed by the unique (user_id, skill_key) index, so differently-cased or aliased
    skill names ("Machine Learning" vs "machine learning") collapse to a single record.
    """
    return normalize_skill_text(skill_name)


@router.get("/learning-path/progress", response_model=list[LearningPathProgressOut])
async def list_learning_path_progress(user=Depends(require_user)):
    db = get_db()
    rows = await db["learning_path_progress"].find(
        {"user_id": user["_id"]},
        {"skill_name": 1, "skill_key": 1, "status": 1, "updated_at": 1},
    ).sort("updated_at", -1).to_list(length=500)
    # Rows arrive newest-first, so the first one seen for a given skill_key is the freshest;
    # collapse any older duplicates that normalize to the same key.
    seen_keys: set[str] = set()
    results: list[LearningPathProgressOut] = []
    for row in rows:
        skill_name = str(row.get("skill_name") or "").strip()
        if not skill_name:
            continue
        skill_key = str(row.get("skill_key") or "") or _progress_skill_key(skill_name)
        if skill_key in seen_keys:
            continue
        seen_keys.add(skill_key)
        results.append(
            LearningPathProgressOut(
                skill_name=skill_name,
                status=str(row.get("status") or "not_started"),
                updated_at=row.get("updated_at"),
            )
        )
    return results


@router.patch("/learning-path/progress", response_model=LearningPathProgressOut)
async def patch_learning_path_progress(payload: LearningPathProgressPatchIn, user=Depends(require_user)):
    db = get_db()
    skill_name = str(payload.skill_name or "").strip()
    skill_key = _progress_skill_key(skill_name)
    doc = {
        "user_id": user["_id"],
        "skill_name": skill_name,
        "skill_key": skill_key,
        "status": payload.status,
        "updated_at": now_utc(),
    }
    # Match on the normalized key (not the raw name) so it lines up with the unique
    # (user_id, skill_key) index and re-tracking the same skill under a different casing
    # updates the existing row instead of creating a duplicate.
    await db["learning_path_progress"].update_one(
        {"user_id": user["_id"], "skill_key": skill_key},
        {"$set": doc},
        upsert=True,
    )
    return LearningPathProgressOut(skill_name=skill_name, status=doc["status"], updated_at=doc["updated_at"])


@router.get("/learning-path/skill/{skill_name}", response_model=LearningPathSkillDetailOut)
async def get_learning_path_skill_detail(skill_name: str, user=Depends(require_user)):
    db = get_db()
    decoded_skill_name = str(skill_name or "").replace("%20", " ").strip()
    confirmed_entries = await _load_profile_confirmation_entries(db, user["_id"])
    confirmed_skill_ids = {oid_str(entry.get("skill_id")) for entry in confirmed_entries if oid_str(entry.get("skill_id"))}

    skill_doc = await db["skills"].find_one({"name": {"$regex": f"^{re.escape(decoded_skill_name)}$", "$options": "i"}})
    skill_id = oid_str((skill_doc or {}).get("_id"))
    evidence_support_count = 0
    graph_neighbors: list[str] = []
    if skill_id:
        evidence_support_count = await db["evidence"].count_documents({"user_id": user["_id"], "skill_ids": {"$in": [ObjectId(skill_id), skill_id]}})
        explicit_visited, _explicit_edges = await _build_explicit_graph(db, skill_id, 1)
        neighbor_docs = await _load_skill_docs(db, [sid for sid in explicit_visited.keys() if sid != skill_id])
        graph_neighbors.extend(str(doc.get("name") or "").strip() for doc in neighbor_docs.values() if str(doc.get("name") or "").strip())
        semantic_neighbors = await _infer_semantic_edges(db, skill_id, limit=5)
        semantic_docs = await _load_skill_docs(db, [edge.target_skill_id for edge in semantic_neighbors])
        graph_neighbors.extend(str(doc.get("name") or "").strip() for doc in semantic_docs.values() if str(doc.get("name") or "").strip())

    trajectory = await get_skill_trajectory(user=user)
    related_career_paths = [
        path.role_name
        for path in trajectory.career_paths
        if decoded_skill_name in path.missing_skills or decoded_skill_name in path.matched_skills or decoded_skill_name in path.top_role_skills
    ][:4]
    progress_doc = await db["learning_path_progress"].find_one({"user_id": user["_id"], "skill_name": decoded_skill_name}, {"status": 1})
    recommended_projects = [
        f"Build a scoped project that uses {decoded_skill_name} in a {path.role_name} workflow"
        for path in trajectory.career_paths[:2]
    ] or [f"Create one portfolio-ready artifact that proves {decoded_skill_name} with measurable outcomes"]

    return LearningPathSkillDetailOut(
        skill_name=decoded_skill_name,
        skill_id=skill_id or None,
        confirmed=bool(skill_id and skill_id in confirmed_skill_ids),
        evidence_support_count=int(evidence_support_count),
        graph_neighbors=_normalize_phrase_list(graph_neighbors)[:8],
        related_career_paths=_normalize_phrase_list(related_career_paths)[:4],
        recommended_projects=_normalize_phrase_list(recommended_projects)[:3],
        recommended_resources=recommended_resources(decoded_skill_name, str((skill_doc or {}).get("category") or ""), limit=3),
        progress_status=str((progress_doc or {}).get("status") or "not_started"),
    )


@router.get("/trajectory/path/{role_id}", response_model=CareerPathDetailOut)
async def get_career_path_detail(role_id: str, user=Depends(require_user)):
    trajectory = await get_skill_trajectory(user=user)
    path = next((entry for entry in trajectory.career_paths if entry.role_id == role_id), None)
    if not path:
        raise HTTPException(status_code=404, detail="Career path not found for user")

    db = get_db()
    graph_neighbor_skills: list[str] = []
    for skill_name in path.missing_skills[:3]:
        skill_doc = await db["skills"].find_one({"name": {"$regex": f"^{re.escape(skill_name)}$", "$options": "i"}})
        skill_id = oid_str((skill_doc or {}).get("_id"))
        if not skill_id:
            continue
        semantic_neighbors = await _infer_semantic_edges(db, skill_id, limit=4)
        docs = await _load_skill_docs(db, [edge.target_skill_id for edge in semantic_neighbors])
        graph_neighbor_skills.extend(str(doc.get("name") or "").strip() for doc in docs.values() if str(doc.get("name") or "").strip())

    recommended_project_ideas = [
        f"Build a portfolio project that combines {skill} with {path.cluster_category or 'your strongest cluster'} for {path.role_name}"
        for skill in path.missing_skills[:2]
    ] or [
        f"Create a measurable case study that highlights {skill} for {path.role_name}"
        for skill in path.matched_skills[:2]
    ]

    return CareerPathDetailOut(
        role_id=path.role_id,
        role_name=path.role_name,
        score=path.score,
        confidence_label=path.confidence_label,
        cluster_category=path.cluster_category,
        personal_vector_alignment_score=path.personal_vector_alignment_score,
        progress_bonus_score=path.progress_bonus_score,
        matched_skills=path.matched_skills,
        missing_skills=path.missing_skills,
        top_role_skills=path.top_role_skills,
        graph_neighbor_skills=_normalize_phrase_list(graph_neighbor_skills)[:8],
        recommended_skills_to_add=path.missing_skills[:4],
        recommended_project_ideas=_normalize_phrase_list(recommended_project_ideas)[:4],
        recommended_resources=recommended_resources_for_many(
            [(skill, path.cluster_category) for skill in path.missing_skills[:3]],
            limit=4,
        ),
        reasoning=path.reasoning,
    )
