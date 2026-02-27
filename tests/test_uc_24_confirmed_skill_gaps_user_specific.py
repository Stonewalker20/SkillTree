"""UC 2.4 — Confirmed Skill Gaps (User-Specific)

Endpoint(s):
- GET /skills/gaps/confirmed?user_id=...&threshold=...

What is being tested:
- After confirming a skill for the user, /skills/gaps/confirmed returns it when evidence_count <= threshold.

Pass criteria:
- HTTP 200
- results list returned
- at least one result corresponds to a skill that was confirmed for this user

Note:
- This relies on the current implementation counting evidence docs; if your evidence collection is empty,
  evidence_count will be 0 and the skill should appear for threshold=0.
"""

import requests
from _common import parse_args, assert_status, get_json, ok, pretty, die


def ensure_skill(base: str, name: str, category: str):
    r = requests.post(f"{base}/skills", json={"name": name, "category": category, "aliases": []}, timeout=15)
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

    python_id = ensure_skill(base, "Python", "Programming")

    # ingest snapshot
    r = requests.post(
        f"{base}/ingest/resume/text",
        json={"user_id": args.user_id, "text": "Python experience only."},
        timeout=15,
    )
    assert_status(r, 200)
    snapshot_id = get_json(r)["snapshot_id"]

    # confirm Python
    payload = {
        "user_id": args.user_id,
        "resume_snapshot_id": snapshot_id,
        "confirmed": [{"skill_id": python_id, "skill_name": "Python", "proficiency": 3}],
        "rejected": [],
        "edited": [],
    }
    r = requests.post(f"{base}/skills/confirmations", json=payload, timeout=20)
    assert_status(r, 200)
    conf = get_json(r)
    ok("Confirmation created for UC 2.4 precondition")
    print("confirmation_id:", conf.get("id"))

    r = requests.get(f"{base}/skills/gaps/confirmed?user_id={args.user_id}&threshold=0", timeout=20)
    assert_status(r, 200)
    data = get_json(r)
    results = data.get("results")
    if not isinstance(results, list):
        die("results is not a list")

    # Expect confirmed python to show up when evidence_count is low
    if not any(x.get("skill_id") == python_id for x in results):
        die("Confirmed Python did not appear in confirmed skill gaps results")

    ok("UC 2.4 confirmed skill gaps")
    pretty(data)


if __name__ == "__main__":
    main()
