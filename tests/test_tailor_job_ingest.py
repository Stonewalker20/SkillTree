"""Tailor Add-on — Job Ingest (paste job posting)

Endpoint:
- POST /tailor/job/ingest

What is being tested:
- Stores a job posting text and returns extracted skills + keywords.

Pass criteria:
- HTTP 200
- response has id, text_preview, extracted_skills(list), keywords(list)
- extracted_skills contains at least one known catalog skill when mentioned (Python/FastAPI)
"""

import requests
from _common import parse_args, assert_status, get_json, ok, pretty, die


def ensure_skill(base: str, name: str, category: str, aliases=None):
    aliases = aliases or []
    r = requests.post(f"{base}/skills", json={"name": name, "category": category, "aliases": aliases}, timeout=15)
    if r.status_code == 200:
        return get_json(r)["id"]
    r = requests.get(f"{base}/skills?q={name}&limit=25", timeout=15)
    assert_status(r, 200)
    rows = get_json(r)
    for s in rows:
        if s.get("name", "").lower() == name.lower():
            return s["id"]
    die(f"Could not ensure skill exists: {name}")


def main():
    args = parse_args()
    base = args.base_url.rstrip("/")

    ensure_skill(base, "Python", "Programming", ["python3"])
    ensure_skill(base, "FastAPI", "Framework", ["fast api"])
    ensure_skill(base, "MongoDB", "Database", ["mongo"])

    job_text = """We are hiring a Backend Engineer.

Responsibilities:
- Build FastAPI services in Python.
- Design MongoDB schemas and write queries.
- Ship features iteratively with tests.

Preferred:
- Docker, CI/CD.
"""

    payload = {
        "user_id": args.user_id,
        "title": "Backend Engineer",
        "company": "TestCo",
        "location": "MI",
        "text": job_text,
    }

    r = requests.post(f"{base}/tailor/job/ingest", json=payload, timeout=20)
    assert_status(r, 200)
    data = get_json(r)

    if not data.get("id"):
        die("Missing id")
    if not data.get("text_preview"):
        die("Missing text_preview")
    if not isinstance(data.get("extracted_skills"), list):
        die("extracted_skills not list")
    if not isinstance(data.get("keywords"), list):
        die("keywords not list")

    names = {s.get("skill_name", "").lower() for s in data["extracted_skills"]}
    if not ({"python", "fastapi", "mongodb"} & names):
        die(f"Expected Python/FastAPI/MongoDB in extracted skills; got {sorted(names)}")

    ok("Job ingest returns extracted skills + keywords")
    pretty(data)


if __name__ == "__main__":
    main()
