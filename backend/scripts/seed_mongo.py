"""seed_mongo.py

Seeds MongoDB with demo data for SkillBridge remaining use cases.

Seeds:
- skills (with aliases)
- resume_snapshots (+ optional skill_extractions doc)
- resume_skill_confirmations (confirmed skills for snapshot)
- projects + project_skill_links
- evidence (linked to skill_ids and project_id)
- roles
- jobs (pending + approved) tagged to roles and with required_skill_ids
- skill_relations (taxonomy)

Usage:
  python seed_mongo.py --mongo-uri "mongodb://localhost:27017" --db skillbridge --drop

Requires:
  pip install pymongo bson
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from typing import Dict, List
from bson import ObjectId
from pymongo import MongoClient


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mongo-uri", required=True)
    ap.add_argument("--db", default="skillbridge")
    ap.add_argument("--drop", action="store_true")
    ap.add_argument("--user-id", default="student1")
    return ap.parse_args()


def drop_if_requested(db, drop: bool):
    if not drop:
        return
    for c in [
        "skills",
        "resume_snapshots",
        "skill_extractions",
        "resume_skill_confirmations",
        "projects",
        "project_skill_links",
        "evidence",
        "roles",
        "role_skill_weights",
        "skill_relations",
        "jobs",
    ]:
        db[c].drop()


def upsert_skill(db, name: str, category: str, aliases: List[str] | None = None) -> ObjectId:
    aliases = aliases or []
    existing = db["skills"].find_one({"name": name})
    doc = {
        "name": name,
        "category": category,
        "aliases": aliases,
        "proficiency": 3,
        "last_used_at": now_utc(),
        "created_at": now_utc(),
        "updated_at": now_utc(),
    }
    if existing:
        db["skills"].update_one({"_id": existing["_id"]}, {"$set": doc})
        return existing["_id"]
    return db["skills"].insert_one(doc).inserted_id


def main():
    args = parse_args()
    client = MongoClient(args.mongo_uri)
    db = client[args.db]

    drop_if_requested(db, args.drop)

    # 1) Skills
    skill_ids: Dict[str, ObjectId] = {}
    skill_ids["Python"] = upsert_skill(db, "Python", "Programming", ["python3"])
    skill_ids["FastAPI"] = upsert_skill(db, "FastAPI", "Framework", ["fast api"])
    skill_ids["MongoDB"] = upsert_skill(db, "MongoDB", "Database", ["mongo"])
    skill_ids["Docker"] = upsert_skill(db, "Docker", "DevOps", [])
    skill_ids["React"] = upsert_skill(db, "React", "Frontend", ["reactjs"])
    skill_ids["PyTorch"] = upsert_skill(db, "PyTorch", "ML", ["torch"])
    skill_ids["MLflow"] = upsert_skill(db, "MLflow", "MLOps", [])
    skill_ids["DVC"] = upsert_skill(db, "DVC", "MLOps", [])
    skill_ids["MLOps"] = upsert_skill(db, "MLOps", "MLOps", ["ml ops", "mlops"])

    # 2) Resume snapshot
    resume_text = (
        "Experience with Python, FastAPI, MongoDB, Docker, and React. "
        "Built ML pipelines using PyTorch, MLflow, and DVC."
    )
    snapshot_id = db["resume_snapshots"].insert_one(
        {
            "user_id": args.user_id,
            "source_type": "seed",
            "raw_text": resume_text,
            "metadata": {"source": "seed_mongo.py"},
            "image_ref": "/images/resume_icon.png",
            "created_at": now_utc(),
        }
    ).inserted_id

    # 3) Extraction (optional)
    extracted = []
    for k in ["Python", "FastAPI", "MongoDB", "Docker", "React", "PyTorch", "MLflow", "DVC", "MLOps"]:
        extracted.append({"skill_id": str(skill_ids[k]), "skill_name": k, "confidence": 0.9, "evidence_snippet": "seed"})
    db["skill_extractions"].insert_one({"resume_snapshot_id": snapshot_id, "skills": extracted, "created_at": now_utc()})

    # 4) Confirmations (store skill_id as ObjectId to match your confirmation pipeline)
    confirmed_entries = []
    for k in ["Python", "FastAPI", "MongoDB", "Docker", "React"]:
        confirmed_entries.append({"skill_id": skill_ids[k], "skill_name": k, "confidence": 0.9})
    db["resume_skill_confirmations"].insert_one(
        {
            "user_id": args.user_id,
            "resume_snapshot_id": snapshot_id,
            "confirmed": confirmed_entries,
            "rejected": [],
            "created_at": now_utc(),
        }
    )

    # 5) Projects + links
    proj1 = db["projects"].insert_one(
        {
            "user_id": args.user_id,
            "title": "SkillBridge Backend",
            "description": "FastAPI + MongoDB backend for capstone.",
            "tags": ["capstone", "backend"],
            "created_at": now_utc(),
            "updated_at": now_utc(),
        }
    ).inserted_id

    for s in ["Python", "FastAPI", "MongoDB", "Docker"]:
        db["project_skill_links"].update_one(
            {"project_id": proj1, "skill_id": skill_ids[s]},
            {"$setOnInsert": {"project_id": proj1, "skill_id": skill_ids[s], "created_at": now_utc()}},
            upsert=True,
        )

    # 6) Evidence
    db["evidence"].insert_one(
        {
            "user_id": args.user_id,
            "user_email": None,
            "type": "project",
            "title": "API Repo README",
            "source": "https://github.com/example/skillbridge",
            "text_excerpt": "Implements FastAPI routers and Mongo collections.",
            "skill_ids": [str(skill_ids["FastAPI"]), str(skill_ids["MongoDB"])],
            "project_id": str(proj1),
            "tags": ["github"],
            "created_at": now_utc(),
            "updated_at": now_utc(),
        }
    )

    # 7) Roles
    role_backend = db["roles"].insert_one(
        {"name": "Backend Engineer", "description": "API + DB + deployment.", "created_at": now_utc(), "updated_at": now_utc()}
    ).inserted_id

    role_ml = db["roles"].insert_one(
        {"name": "ML Engineer", "description": "Training + MLOps pipelines.", "created_at": now_utc(), "updated_at": now_utc()}
    ).inserted_id

    # 8) Jobs
    db["jobs"].insert_many(
        [
            {
                "title": "Junior Backend Engineer",
                "company": "Campus Lab",
                "location": "Rochester Hills, MI",
                "source": "seed",
                "description_excerpt": "Build FastAPI services; manage MongoDB; containerize with Docker.",
                "required_skills": ["FastAPI", "MongoDB", "Docker", "Python"],
                "required_skill_ids": [str(skill_ids["FastAPI"]), str(skill_ids["MongoDB"]), str(skill_ids["Docker"]), str(skill_ids["Python"])],
                "role_ids": [str(role_backend)],
                "moderation_status": "approved",
                "moderation_reason": None,
                "submitted_by_user_id": args.user_id,
                "created_at": now_utc(),
                "updated_at": now_utc(),
            },
            {
                "title": "ML Engineer Intern",
                "company": "OU Research",
                "location": "Auburn Hills, MI",
                "source": "seed",
                "description_excerpt": "Train PyTorch models; track with MLflow; version data with DVC.",
                "required_skills": ["PyTorch", "MLflow", "DVC", "Python"],
                "required_skill_ids": [str(skill_ids["PyTorch"]), str(skill_ids["MLflow"]), str(skill_ids["DVC"]), str(skill_ids["Python"])],
                "role_ids": [str(role_ml)],
                "moderation_status": "approved",
                "moderation_reason": None,
                "submitted_by_user_id": args.user_id,
                "created_at": now_utc(),
                "updated_at": now_utc(),
            },
            {
                "title": "Unverified Posting",
                "company": "Unknown",
                "location": "Remote",
                "source": "seed",
                "description_excerpt": "Suspicious posting pending moderation.",
                "required_skills": ["Python"],
                "required_skill_ids": [str(skill_ids["Python"])],
                "role_ids": [],
                "moderation_status": "pending",
                "moderation_reason": None,
                "submitted_by_user_id": "anon",
                "created_at": now_utc(),
                "updated_at": now_utc(),
            },
        ]
    )

    # 9) Taxonomy relation
    db["skill_relations"].insert_one(
        {"from_skill_id": skill_ids["FastAPI"], "to_skill_id": skill_ids["Python"], "relation_type": "related_to", "created_at": now_utc()}
    )

    print("Seed complete.")
    print(f"DB: {args.db}")
    print(f"user_id: {args.user_id}")
    print(f"SNAPSHOT_ID: {snapshot_id}")
    print(f"role_backend_id: {role_backend}")
    print(f"role_ml_id: {role_ml}")


if __name__ == "__main__":
    main()
