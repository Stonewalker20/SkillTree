"""UC 3.3 — Confirm / Reject Extracted Skills

Endpoint(s):
- POST /skills/confirmations   (upsert confirmation)
- GET  /skills/confirmations?user_id=...

What is being tested:
- Creating a confirmation record for (user_id, resume_snapshot_id) with:
  - confirmed skills (with proficiency)
  - rejected skills
- Listing confirmations returns the record.

Pass criteria:
- HTTP 200 on upsert
- response contains confirmed and rejected entries
- list endpoint includes the created confirmation id
"""

import requests
from tests._common import parse_args, assert_status, get_json, ok, pretty, die


def ensure_skill(base: str, name: str, category: str):
    r = requests.post(f"{base}/skills", json={"name": name, "category": category, "aliases": []}, timeout=15)
    if r.status_code == 200:
        return get_json(r)["id"]
    # fallback search
    r = requests.get(f"{base}/skills?q={name}&limit=20", timeout=15)
    assert_status(r, 200)
    rows = get_json(r)
    for s in rows:
        if s.get("name", "").lower() == name.lower():
            return s["id"]
    die(f"Could not ensure skill exists: {name}")


def main():
    args = parse_args()
    base = args.base_url.rstrip("/")

    python_id = ensure_skill(base, "Python", "Programming")
    docker_id = ensure_skill(base, "Docker", "DevOps")

    # ingest snapshot
    resume_text = "Worked with Python heavily. No Docker mentioned here."
    r = requests.post(f"{base}/ingest/resume/text", json={"user_id": args.user_id, "text": resume_text}, timeout=15)
    assert_status(r, 200)
    snapshot_id = get_json(r)["snapshot_id"]

    payload = {
        "user_id": args.user_id,
        "resume_snapshot_id": snapshot_id,
        "confirmed": [{"skill_id": python_id, "skill_name": "Python", "proficiency": 4}],
        "rejected": [{"skill_id": docker_id, "skill_name": "Docker"}],
        "edited": [],
    }

    r = requests.post(f"{base}/skills/confirmations", json=payload, timeout=20)
    assert_status(r, 200)
    conf = get_json(r)
    if conf.get("user_id") != args.user_id:
        die("user_id mismatch")
    if conf.get("resume_snapshot_id") != snapshot_id:
        die("resume_snapshot_id mismatch")
    if not conf.get("confirmed"):
        die("confirmed list empty")
    if not conf.get("rejected"):
        die("rejected list empty")

    ok("UC 3.3 confirm/reject upsert")
    pretty(conf)

    r = requests.get(f"{base}/skills/confirmations?user_id={args.user_id}", timeout=15)
    assert_status(r, 200)
    rows = get_json(r)
    if not any(x.get("id") == conf.get("id") for x in rows):
        die("Created confirmation not found in list_confirmations")

    ok("UC 3.3 list confirmations contains created record")
    print(f"Confirmation count for user {args.user_id}: {len(rows)}")


if __name__ == "__main__":
    main()
