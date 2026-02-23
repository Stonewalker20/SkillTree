#!/usr/bin/env python3
"""
seed_mongo.py — SkillBridge PR2 seeder (MongoDB)

Seeds:
- skills (taxonomy + aliases)
- resume_snapshots (from processed JSONL OR raw Kaggle resume CSVs; schema-tolerant)
- jobs (from processed JSONL OR raw Kaggle CSVs; schema-tolerant)
- evidence (minimal rows w/ image_ref for PR2 "includes images" + supports gaps query)

Key upgrades:
- Job normalization can build description from MULTIPLE fields (description + requirements + responsibilities)
- Location can be composed from city/state/country when "location" is missing
- More robust date parsing and safe batch insertion
- Skill auto-expansion from text with strong junk filtering (prevents "Re", "2014 Company Name", "000.00")
"""

from __future__ import annotations

import os
import re
import json
import glob
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd
from pymongo import MongoClient, ASCENDING
from pymongo.collection import Collection


# -----------------------------
# Config
# -----------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]  # backend/scripts/seed_mongo.py -> repo root
RAW_ROOT = REPO_ROOT / "backend" / "data" / "raw"
PROCESSED_ROOT = REPO_ROOT / "backend" / "data" / "processed"
DEFAULT_SKILLS_JSON = REPO_ROOT / "backend" / "data" / "taxonomy" / "skills.json"

DEFAULT_RESUME_ICON = "/images/resume_icon.png"
DEFAULT_EVIDENCE_ICON = "/images/project_icon.png"

NOW = lambda: datetime.now(timezone.utc)

BATCH_SIZE = 500


# -----------------------------
# Helpers
# -----------------------------
def clean_text(x: Any) -> str:
    if x is None:
        return ""
    s = str(x)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def first_existing_key(d: Dict[str, Any], candidates: List[str]) -> Optional[str]:
    """Return first candidate key that exists in dict (case-insensitive) and is non-empty."""
    lower_map = {k.lower(): k for k in d.keys()}
    for c in candidates:
        k = lower_map.get(c.lower())
        if k is not None:
            val = d.get(k)
            if val is not None and str(val).strip() != "":
                return k
    return None


def all_existing_keys(d: Dict[str, Any], candidates: List[str]) -> List[str]:
    """Return ALL candidate keys that exist in dict (case-insensitive) and are non-empty."""
    lower_map = {k.lower(): k for k in d.keys()}
    found: List[str] = []
    for c in candidates:
        k = lower_map.get(c.lower())
        if k is not None:
            val = d.get(k)
            if val is not None and str(val).strip() != "":
                found.append(k)
    return found


def first_existing_col(cols: Iterable[str], candidates: List[str]) -> Optional[str]:
    """Return first candidate col that exists (case-insensitive)."""
    lower_map = {c.lower(): c for c in cols}
    for c in candidates:
        if c.lower() in lower_map:
            return lower_map[c.lower()]
    return None


def load_jsonl(path: Path, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if limit is not None and i >= limit:
                break
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def ensure_indexes(db) -> None:
    db.skills.create_index([("name", ASCENDING)], unique=True)
    db.skills.create_index([("aliases", ASCENDING)])

    db.resume_skill_confirmations.create_index(
        [("user_id", ASCENDING), ("resume_snapshot_id", ASCENDING)],
        unique=True,
    )

    db.resume_snapshots.create_index([("user_id", ASCENDING), ("created_at", ASCENDING)])
    db.skill_extractions.create_index([("resume_snapshot_id", ASCENDING), ("created_at", ASCENDING)])

    db.evidence.create_index([("skill_ids", ASCENDING)])

    db.jobs.create_index([("title", ASCENDING)])
    db.jobs.create_index([("company", ASCENDING)])
    db.jobs.create_index([("location", ASCENDING)])
    db.jobs.create_index([("posted_at", ASCENDING)])


def connect_db(mongo_uri: str, db_name: str):
    client = MongoClient(mongo_uri)
    db = client[db_name]
    return client, db


def safe_parse_datetime(value: Any) -> datetime:
    """Best-effort parse; always returns tz-aware UTC datetime."""
    try:
        dtv = pd.to_datetime(value, errors="coerce", utc=True)
        if pd.isna(dtv):
            return NOW()
        py = dtv.to_pydatetime()
        if py.tzinfo is None:
            py = py.replace(tzinfo=timezone.utc)
        return py
    except Exception:
        return NOW()


def join_text_fields(rec: Dict[str, Any], keys: List[str], sep: str = "\n\n") -> str:
    """Join multiple non-empty fields into one text blob."""
    chunks: List[str] = []
    for k in keys:
        v = clean_text(rec.get(k))
        if v:
            chunks.append(v)
    return sep.join(chunks)


# -----------------------------
# Seeding: Skills
# -----------------------------
def seed_skills(db, skills_json: Path, wipe: bool = False) -> int:
    col: Collection = db.skills
    if wipe:
        col.delete_many({})

    if not skills_json.exists():
        raise FileNotFoundError(f"skills taxonomy file not found: {skills_json}")

    raw = skills_json.read_text(encoding="utf-8").strip()
    if not raw:
        raise ValueError(f"skills taxonomy file is empty: {skills_json}")

    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("skills.json must be a JSON array of skill objects")

    inserted = 0
    for s in data:
        name = clean_text(s.get("name", ""))
        if not name:
            continue
        doc = {
            "name": name,
            "category": clean_text(s.get("category", "")),
            "aliases": [clean_text(a) for a in (s.get("aliases") or []) if clean_text(a)],
            "tags": [clean_text(t) for t in (s.get("tags") or []) if clean_text(t)],
            "created_at": NOW(),
        }
        res = col.update_one({"name": doc["name"]}, {"$setOnInsert": doc}, upsert=True)
        if res.upserted_id is not None:
            inserted += 1

    return inserted


# -----------------------------
# Skill Auto-Expansion (filtered)
# -----------------------------
STOP = set("""
a an and are as at be been but by can could did do does for from had has have he her his i if in into is it its
just may might more most no not of on one or our out over said she should so than that the their them then there
these they this to too up us was we were what when where which who will with would you your
""".split())

SKILL_TOKEN_RE = re.compile(r"[^a-z0-9\+\#\.\- ]+")
BAD_SKILL_RE = re.compile(
    r"(^\d+(\.\d+)?$)|"        # 000.00 / 401
    r"(^\d{4}$)|"              # years
    r"(^[a-z]{1,2}$)|"         # re, de, rn
    r"(^[^\w]+$)|"             # punctuation-only
    r"(^\d+[a-z]+$)",          # 401k, etc (often not a skill; you can loosen later)
    re.IGNORECASE,
)

BAD_PHRASES = [
    "ability to",
    "equal opportunity",
    "applicants receive",
    "company name",
    "base salary",
    "benefits package",
    "receive consideration",
    "years of experience",
    "must be able",
    "all qualified applicants",
    "race color religion sex",
]

GENERIC_NGRAM_BLACKLIST = {
    "project management",
    "team player",
    "communication skills",
    "problem solving",
    "fast paced environment",
    "work independently",
}


def normalize_skill_phrase(s: str) -> str:
    s = s.lower().strip()
    s = SKILL_TOKEN_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def title_case_skill(s: str) -> str:
    overrides = {
        "c++": "C++",
        "c#": "C#",
        "node.js": "Node.js",
        "react.js": "React",
        "react": "React",
        "typescript": "TypeScript",
        "javascript": "JavaScript",
        "mongodb": "MongoDB",
        "postgresql": "PostgreSQL",
        "postgres": "PostgreSQL",
        "mysql": "MySQL",
        "aws": "AWS",
        "gcp": "GCP",
        "azure": "Azure",
        "fastapi": "FastAPI",
        "pytorch": "PyTorch",
        "tensorflow": "TensorFlow",
        "scikit learn": "scikit-learn",
        "scikit-learn": "scikit-learn",
        "rest": "REST",
        "sql": "SQL",
        "nlp": "NLP",
        "lstm": "LSTM",
        "svm": "SVM",
        "bm25": "BM25",
        "bert": "BERT",
        "ci/cd": "CI/CD",
    }
    key = s.lower()
    if key in overrides:
        return overrides[key]

    # Preserve common acronyms
    parts = []
    for w in s.split():
        if w.isalpha() and 2 <= len(w) <= 5 and w.upper() == w:
            parts.append(w)
        else:
            parts.append(w.capitalize())
    return " ".join(parts)


def guess_category(skill: str) -> str:
    s = skill.lower()
    if any(k in s for k in ["python", "java", "c++", "c#", "javascript", "typescript", "golang", "rust", "scala", "kotlin"]):
        return "Programming"
    if any(k in s for k in ["mongodb", "sql", "postgres", "mysql", "redis", "snowflake", "bigquery", "dynamodb"]):
        return "Database"
    if any(k in s for k in ["aws", "azure", "gcp", "docker", "kubernetes", "terraform", "ci/cd", "jenkins"]):
        return "DevOps/Cloud"
    if any(k in s for k in ["pytorch", "tensorflow", "nlp", "lstm", "svm", "bm25", "transformer", "bert", "mlflow"]):
        return "ML"
    if any(k in s for k in ["react", "vue", "angular", "next.js", "frontend", "css", "html"]):
        return "Frontend"
    return "Tools"


def is_good_skill_candidate(s: str) -> bool:
    s = (s or "").strip()
    if not s:
        return False
    if len(s) < 3:
        return False

    low = s.lower()
    if BAD_SKILL_RE.search(low):
        return False
    if any(p in low for p in BAD_PHRASES):
        return False

    # Too many words usually means it's boilerplate
    if low.count(" ") >= 4:
        return False

    # reject tokens that are mostly digits/punct
    alnum = sum(ch.isalnum() for ch in s)
    if alnum / max(1, len(s)) < 0.6:
        return False

    return True


def extract_skill_candidates_from_text(text: str) -> List[str]:
    """
    Lightweight candidate extractor:
    - tech tokens with symbols (C++, C#, Node.js, CI/CD)
    - 1-3 word ngrams with heavy filtering
    """
    text = clean_text(text)
    if not text:
        return []
    raw = normalize_skill_phrase(text)
    tokens = raw.split()

    toks = [t for t in tokens if t and t not in STOP and len(t) > 1]
    cands: List[str] = []

    # symbol tokens
    for t in toks:
        if any(ch in t for ch in ["+", "#", ".", "/"]):
            cands.append(t)

    # ngrams
    for n in (1, 2, 3):
        for i in range(0, len(toks) - n + 1):
            ng = " ".join(toks[i : i + n]).strip()
            if not ng:
                continue
            if ng in GENERIC_NGRAM_BLACKLIST:
                continue
            if any(w in STOP for w in ng.split()):
                continue
            if not is_good_skill_candidate(ng):
                continue
            cands.append(ng)

    return cands


def expand_skills_from_db_text(db, max_skills: int = 1500, min_freq: int = 15) -> int:
    """
    Builds additional skills by scanning jobs + resumes currently in DB.
    Inserts into skills collection with upsert by name.
    """
    skills_col: Collection = db.skills

    job_cursor = db.jobs.find({}, {"title": 1, "description": 1}).limit(10000)
    res_cursor = db.resume_snapshots.find({}, {"raw_text": 1}).limit(3000)

    freq: Dict[str, int] = {}

    def add_text(t: str):
        for c in extract_skill_candidates_from_text(t):
            freq[c] = freq.get(c, 0) + 1

    for j in job_cursor:
        add_text(j.get("title", ""))
        add_text(j.get("description", ""))

    for r in res_cursor:
        add_text(r.get("raw_text", ""))

    items = [(k, v) for k, v in freq.items() if v >= min_freq]
    items.sort(key=lambda x: x[1], reverse=True)

    inserted = 0
    for phrase, f in items[:max_skills]:
        norm = normalize_skill_phrase(phrase)
        if not is_good_skill_candidate(norm):
            continue

        name = title_case_skill(norm)
        if not is_good_skill_candidate(name):
            continue

        doc = {
            "name": name,
            "category": guess_category(name),
            "aliases": [],
            "tags": ["auto"],
            "created_at": NOW(),
        }
        res = skills_col.update_one({"name": name}, {"$setOnInsert": doc}, upsert=True)
        if res.upserted_id is not None:
            inserted += 1

    return inserted


# -----------------------------
# Seeding: Resumes (processed JSONL)
# -----------------------------
def seed_resumes(db, resumes_jsonl: Path, user_id: str, limit: int, wipe: bool = False) -> int:
    col: Collection = db.resume_snapshots
    if wipe:
        col.delete_many({})

    rows = load_jsonl(resumes_jsonl, limit=limit)
    if not rows:
        print(f"[WARN] No processed resumes found at: {resumes_jsonl}")
        return 0

    docs = []
    for r in rows:
        raw_text = clean_text(r.get("raw_text") or r.get("text") or r.get("resume") or "")
        if len(raw_text) < 200:
            continue

        docs.append(
            {
                "user_id": clean_text(r.get("user_id")) or user_id,
                "source_type": clean_text(r.get("source_type")) or "kaggle",
                "raw_text": raw_text,
                "metadata": r.get("metadata") or {"dataset": "unknown"},
                "image_ref": clean_text(r.get("image_ref")) or DEFAULT_RESUME_ICON,
                "created_at": NOW(),
            }
        )

    if not docs:
        return 0

    res = col.insert_many(docs, ordered=False)
    return len(res.inserted_ids)


def seed_resumes_from_raw_csvs(db, raw_dir: Path, user_id: str, limit: int, wipe: bool = False) -> int:
    """
    Seeds resume_snapshots from Kaggle resume-dataset CSV(s).
    Expected columns (case-insensitive):
      - ID
      - Resume_str
      - Resume_html (optional)
      - Category
    """
    col: Collection = db.resume_snapshots
    if wipe:
        col.delete_many({})

    csvs = glob.glob(str(raw_dir / "**/*.csv"), recursive=True)
    if not csvs:
        print(f"[WARN] No resume CSV files found under: {raw_dir}")
        return 0

    inserted = 0
    batch: List[Dict[str, Any]] = []

    for p in sorted(csvs, key=lambda x: -Path(x).stat().st_size):
        try:
            df = pd.read_csv(p)
        except Exception as e:
            print(f"[WARN] Failed to read {p}: {e}")
            continue

        cols = list(df.columns)
        id_col = first_existing_col(cols, ["ID", "Id", "id"])
        text_col = first_existing_col(cols, ["Resume_str", "resume_str", "Resume", "resume", "text"])
        html_col = first_existing_col(cols, ["Resume_html", "resume_html", "html"])
        cat_col = first_existing_col(cols, ["Category", "category", "label", "Label"])

        if not text_col:
            print(f"[WARN] No Resume_str-like column found in {p}. Columns: {cols[:25]}")
            continue

        for _, row in df.iterrows():
            raw_text = clean_text(row.get(text_col))
            if len(raw_text) < 120:
                continue

            resume_id = clean_text(row.get(id_col)) if id_col else ""
            category = clean_text(row.get(cat_col)) if cat_col else ""

            doc = {
                "user_id": user_id,
                "source_type": "kaggle",
                "raw_text": raw_text,
                "metadata": {
                    "dataset": "snehaanbhawal/resume-dataset",
                    "source_file": Path(p).name,
                    "resume_id": resume_id,
                    "category": category,
                },
                "image_ref": DEFAULT_RESUME_ICON,
                "created_at": NOW(),
            }

            if html_col:
                html = clean_text(row.get(html_col))
                if html:
                    doc["metadata"]["resume_html"] = html[:5000]

            batch.append(doc)

            if len(batch) >= BATCH_SIZE:
                res = col.insert_many(batch, ordered=False)
                inserted += len(res.inserted_ids)
                batch.clear()
                if inserted >= limit:
                    break

        if inserted >= limit:
            break

    if batch and inserted < limit:
        to_insert = batch[: max(0, limit - inserted)]
        if to_insert:
            res = col.insert_many(to_insert, ordered=False)
            inserted += len(res.inserted_ids)

    return min(inserted, limit)


# -----------------------------
# Seeding: Jobs (schema-tolerant)
# -----------------------------
JOB_TITLE_KEYS = ["title", "job_title", "position", "role", "jobtitle", "job title", "position_name"]

JOB_DESC_KEYS_PRIMARY = ["description", "job_description", "job description", "desc", "text", "job_details", "jobdetails"]
JOB_DESC_KEYS_SECONDARY = [
    "responsibilities",
    "responsibility",
    "requirements",
    "requirement",
    "qualifications",
    "qualification",
    "preferred_qualifications",
    "preferred qualifications",
    "benefits",
    "about",
    "summary",
    "what_youll_do",
    "what you'll do",
    "duties",
    "role_description",
    "role description",
]

JOB_COMPANY_KEYS = ["company", "company_name", "company name", "employer", "organization", "org"]
JOB_LOCATION_KEYS = ["location", "job_location", "job location", "job_location_name", "workplace", "remote"]
JOB_URL_KEYS = ["url", "job_url", "job url", "link", "posting_url", "posting url"]
JOB_DATE_KEYS = ["date", "posted_date", "posted date", "created_at", "posting_date", "posting date", "published", "listed_time"]
JOB_LEVEL_KEYS = ["level", "seniority", "seniority_level", "seniority level", "experience_level", "experience level"]
JOB_TYPE_KEYS = ["type", "employment_type", "employment type", "job_type", "job type"]
JOB_INDUSTRY_KEYS = ["industry", "industry_name", "industry name"]
JOB_FUNCTION_KEYS = ["function", "job_function", "job function", "category", "job_category", "job category"]

MIN_DESC_CHARS = 120


def compose_location(rec: Dict[str, Any]) -> str:
    """Try location field, else compose from city/state/country."""
    loc_key = first_existing_key(rec, JOB_LOCATION_KEYS)
    if loc_key:
        return clean_text(rec.get(loc_key))

    city_key = first_existing_key(rec, ["city", "job_city"])
    state_key = first_existing_key(rec, ["state", "region", "job_state"])
    country_key = first_existing_key(rec, ["country"])

    parts = []
    if city_key:
        parts.append(clean_text(rec.get(city_key)))
    if state_key:
        parts.append(clean_text(rec.get(state_key)))
    if country_key:
        parts.append(clean_text(rec.get(country_key)))

    return ", ".join([p for p in parts if p])


def normalize_job_record(rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    title_key = first_existing_key(rec, JOB_TITLE_KEYS)
    title = clean_text(rec.get(title_key)) if title_key else ""

    desc_keys = all_existing_keys(rec, JOB_DESC_KEYS_PRIMARY) + all_existing_keys(rec, JOB_DESC_KEYS_SECONDARY)
    desc = join_text_fields(rec, desc_keys, sep="\n\n") if desc_keys else ""

    if len(desc) < MIN_DESC_CHARS:
        for k in list(rec.keys()):
            kl = k.lower()
            if "description" in kl or "responsib" in kl or "require" in kl or "qualif" in kl:
                v = clean_text(rec.get(k))
                if len(v) > len(desc):
                    desc = v

    if not title or len(desc) < MIN_DESC_CHARS:
        return None

    company_key = first_existing_key(rec, JOB_COMPANY_KEYS)
    url_key = first_existing_key(rec, JOB_URL_KEYS)
    level_key = first_existing_key(rec, JOB_LEVEL_KEYS)
    type_key = first_existing_key(rec, JOB_TYPE_KEYS)
    industry_key = first_existing_key(rec, JOB_INDUSTRY_KEYS)
    function_key = first_existing_key(rec, JOB_FUNCTION_KEYS)

    location = compose_location(rec)

    posted_at = NOW()
    date_key = first_existing_key(rec, JOB_DATE_KEYS)
    if date_key:
        posted_at = safe_parse_datetime(rec.get(date_key))

    return {
        "title": title,
        "company": clean_text(rec.get(company_key)) if company_key else "",
        "location": location,
        "description": desc,
        "url": clean_text(rec.get(url_key)) if url_key else "",
        "seniority": clean_text(rec.get(level_key)) if level_key else "",
        "employment_type": clean_text(rec.get(type_key)) if type_key else "",
        "industry": clean_text(rec.get(industry_key)) if industry_key else "",
        "job_function": clean_text(rec.get(function_key)) if function_key else "",
        "source": "kaggle",
        "metadata": {
            "raw_keys": list(rec.keys())[:80],
            "title_key": title_key or "",
            "desc_keys": desc_keys[:20],
        },
        "posted_at": posted_at,
        "created_at": NOW(),
    }


def seed_jobs_from_processed_jsonl(db, jobs_jsonl: Path, limit: int, wipe: bool = False) -> int:
    col: Collection = db.jobs
    if wipe:
        col.delete_many({})

    rows = load_jsonl(jobs_jsonl, limit=limit)
    if not rows:
        print(f"[WARN] No processed jobs found at: {jobs_jsonl}")
        return 0

    docs = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        norm = normalize_job_record(r)
        if norm:
            docs.append(norm)

    if not docs:
        return 0

    res = col.insert_many(docs, ordered=False)
    return len(res.inserted_ids)


def seed_jobs_from_raw_csvs(db, raw_dir: Path, limit: int, wipe: bool = False) -> int:
    """
    Reads ALL CSVs under raw_dir recursively and attempts to normalize jobs with flexible field mapping.
    Supports description built from multiple fields (requirements/responsibilities/etc).
    """
    col: Collection = db.jobs
    if wipe:
        col.delete_many({})

    csvs = glob.glob(str(raw_dir / "**/*.csv"), recursive=True)
    if not csvs:
        print(f"[WARN] No job CSV files found under: {raw_dir}")
        return 0

    inserted = 0
    batch: List[Dict[str, Any]] = []

    for p in sorted(csvs, key=lambda x: -Path(x).stat().st_size):
        try:
            df = pd.read_csv(p)
        except Exception as e:
            print(f"[WARN] Failed to read {p}: {e}")
            continue

        for _, row in df.iterrows():
            rec = row.to_dict()
            norm = normalize_job_record(rec)
            if norm is None:
                continue

            norm["metadata"]["source_file"] = Path(p).name
            batch.append(norm)

            if len(batch) >= BATCH_SIZE:
                res = col.insert_many(batch, ordered=False)
                inserted += len(res.inserted_ids)
                batch.clear()
                if inserted >= limit:
                    break

        if inserted >= limit:
            break

    if batch and inserted < limit:
        to_insert = batch[: max(0, limit - inserted)]
        if to_insert:
            res = col.insert_many(to_insert, ordered=False)
            inserted += len(res.inserted_ids)

    return min(inserted, limit)


# -----------------------------
# Seeding: Evidence
# -----------------------------
def seed_min_evidence(db, wipe: bool = False) -> int:
    """
    Seeds a small evidence set so /skills/gaps is meaningful:
    - attaches evidence to some skills
    - leaves others with 0 evidence
    - includes image_ref to satisfy PR2 "includes images"
    """
    evidence_col: Collection = db.evidence
    skills_col: Collection = db.skills

    if wipe:
        evidence_col.delete_many({})

    skills = list(skills_col.find({}, {"_id": 1, "name": 1}).limit(10000))
    if not skills:
        print("[WARN] No skills in DB; seed skills first.")
        return 0

    attach_n = max(1, int(len(skills) * 0.4))  # attach to ~40%
    attach_skills = skills[:attach_n]

    docs = []
    for s in attach_skills:
        docs.append(
            {
                "skill_ids": [s["_id"]],
                "type": "project",
                "description": f"Example evidence artifact for {s.get('name','skill')}",
                "url": "",
                "notes": "Seeded for PR2 demo.",
                "image_ref": DEFAULT_EVIDENCE_ICON,
                "created_at": NOW(),
            }
        )

    if not docs:
        return 0

    res = evidence_col.insert_many(docs, ordered=False)
    return len(res.inserted_ids)


# -----------------------------
# Main
# -----------------------------
def main():
    parser = argparse.ArgumentParser(description="Seed SkillBridge MongoDB for PR2.")
    parser.add_argument("--mongo-uri", default=os.getenv("MONGO_URI", "mongodb://localhost:27017"))
    parser.add_argument("--db", default=os.getenv("MONGO_DB", "skillbridge"))
    parser.add_argument("--wipe", action="store_true", help="Wipe collections before seeding")

    parser.add_argument("--skills-json", default=str(DEFAULT_SKILLS_JSON))

    parser.add_argument("--seed-resumes-from", choices=["processed", "raw"], default="processed")
    parser.add_argument("--resumes-jsonl", default=str(PROCESSED_ROOT / "sample_resumes.jsonl"))
    parser.add_argument("--resumes-raw-dir", default=str(RAW_ROOT / "resume_dataset"))

    parser.add_argument("--seed-jobs-from", choices=["processed", "raw"], default="processed")
    parser.add_argument("--jobs-jsonl", default=str(PROCESSED_ROOT / "sample_jobs.jsonl"))
    parser.add_argument("--jobs-raw-dir", default=str(RAW_ROOT / "linkedin_job_postings"))

    parser.add_argument("--resume-limit", type=int, default=1000)
    parser.add_argument("--job-limit", type=int, default=1000)
    parser.add_argument("--user-id", default="student1")

    parser.add_argument("--expand-skills", action="store_true", help="Auto-expand skills from jobs/resumes text")
    parser.add_argument("--skills-max", type=int, default=1500)
    parser.add_argument("--skills-min-freq", type=int, default=15)

    args = parser.parse_args()

    client, db = connect_db(args.mongo_uri, args.db)
    try:
        ensure_indexes(db)

        print(f"[INFO] Seeding DB '{args.db}' @ {args.mongo_uri}")

        inserted_skills = seed_skills(db, Path(args.skills_json), wipe=args.wipe)
        print(f"[OK] skills upserted: {inserted_skills}")

        if args.seed_resumes_from == "processed":
            inserted_resumes = seed_resumes(
                db, Path(args.resumes_jsonl), user_id=args.user_id, limit=args.resume_limit, wipe=args.wipe
            )
        else:
            inserted_resumes = seed_resumes_from_raw_csvs(
                db, Path(args.resumes_raw_dir), user_id=args.user_id, limit=args.resume_limit, wipe=args.wipe
            )
        print(f"[OK] resume_snapshots inserted: {inserted_resumes}")

        if args.seed_jobs_from == "processed":
            inserted_jobs = seed_jobs_from_processed_jsonl(
                db, Path(args.jobs_jsonl), limit=args.job_limit, wipe=args.wipe
            )
            print(f"[OK] jobs inserted from processed JSONL: {inserted_jobs}")
        else:
            inserted_jobs = seed_jobs_from_raw_csvs(db, Path(args.jobs_raw_dir), limit=args.job_limit, wipe=args.wipe)
            print(f"[OK] jobs inserted from raw CSVs: {inserted_jobs}")

        if args.expand_skills:
            added = expand_skills_from_db_text(db, max_skills=args.skills_max, min_freq=args.skills_min_freq)
            print(f"[OK] skills auto-expanded from text: {added}")

        inserted_evidence = seed_min_evidence(db, wipe=args.wipe)
        print(f"[OK] evidence inserted: {inserted_evidence}")

        print("[DONE] Seed complete.")
        print("Next checks:")
        print(" - MongoDB Compass: verify skills, resume_snapshots, jobs, evidence")
        print(" - PR2 requirement: confirm image_ref fields exist in resume_snapshots + evidence")

    finally:
        client.close()


if __name__ == "__main__":
    main()
