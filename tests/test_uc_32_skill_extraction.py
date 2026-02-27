"""UC 3.2 — Skill Extraction from Resume Snapshot

Endpoint(s):
- POST /skills/extract/skills/{snapshot_id}

What is being tested:
- After ingesting a resume snapshot, calling extraction returns a list of extracted skills.

Pass criteria:
- HTTP 200
- response has snapshot_id, extracted(list), created_at
- extracted contains at least one known skill (e.g., Python) when that skill exists in the skills catalog

Notes:
- This test ensures the skill exists by creating it first via POST /skills.
"""

import requests
from _common import parse_args, assert_status, get_json, ok, pretty, die


def ensure_skill(base: str, name: str, category: str, aliases=None):
    aliases = aliases or []
    # Create skill (may duplicate; acceptable for testing)
    r = requests.post(f"{base}/skills", json={"name": name, "category": category, "aliases": aliases}, timeout=15)
    if r.status_code == 200:
        return get_json(r)["id"]
    # If your API later adds a uniqueness constraint, fall back to searching.
    r = requests.get(f"{base}/skills?q={name}&limit=10", timeout=15)
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

    resume_text = (
        "Experience with Python, FastAPI, and MongoDB. "
        "Deployed services with Docker."
    )

    r = requests.post(f"{base}/ingest/resume/text", json={"user_id": args.user_id, "text": resume_text}, timeout=15)
    assert_status(r, 200)
    snap = get_json(r)
    snapshot_id = snap["snapshot_id"]

    r = requests.post(f"{base}/skills/extract/skills/{snapshot_id}", timeout=25)
    assert_status(r, 200)
    data = get_json(r)

    extracted = data.get("extracted")
    if not isinstance(extracted, list):
        die("extracted is not a list")

    # Expect at least one of the known skills to appear
    names = {e.get("skill_name", "").lower() for e in extracted}
    if not ({"python", "fastapi", "mongodb"} & names):
        die(f"Expected at least one known skill in extracted; got: {sorted(names)}")

    ok("UC 3.2 skill extraction")
    pretty(data)


if __name__ == "__main__":
    main()
