"""Tailor Add-on — Tailor Preview (from job_id)

Endpoints:
- POST /tailor/job/ingest
- POST /tailor/preview

What is being tested:
- Ingest a job posting.
- Ensure at least one portfolio item exists for the user.
- Generate tailored resume preview using job_id.

Pass criteria:
- HTTP 200
- response has: id, sections(list), plain_text, selected_item_ids, selected_skill_ids
- plain_text includes section titles (SUMMARY/SKILLS/RELEVANT WORK)
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


def ensure_portfolio_item(base: str, user_id: str, skill_ids: list[str]) -> str:
    payload = {
        "user_id": user_id,
        "type": "project",
        "title": "Resume Tailor Engine",
        "org": "SkillBridge",
        "summary": "Selection-based tailoring engine on top of portfolio items.",
        "bullets": [
            "Normalized skills and evidence into a portfolio graph to support job-specific selection.",
            "Generated ATS-friendly resume previews with export to PDF/DOCX.",
        ],
        "links": [],
        "skill_ids": skill_ids,
        "tags": ["tailor"],
        "visibility": "private",
        "priority": 5,
    }
    r = requests.post(f"{base}/portfolio/items", json=payload, timeout=15)
    assert_status(r, 200)
    return get_json(r)["id"]


def main():
    args = parse_args()
    base = args.base_url.rstrip("/")

    python_id = ensure_skill(base, "Python", "Programming", ["python3"])
    fastapi_id = ensure_skill(base, "FastAPI", "Framework", ["fast api"])
    mongodb_id = ensure_skill(base, "MongoDB", "Database", ["mongo"])

    item_id = ensure_portfolio_item(base, args.user_id, [python_id, fastapi_id, mongodb_id])
    ok(f"Ensured portfolio item exists: {item_id}")

    job_text = """Backend Engineer role.

We need Python and FastAPI experience, plus MongoDB data modeling.
Bonus: Docker and CI.
"""
    r = requests.post(
        f"{base}/tailor/job/ingest",
        json={"user_id": args.user_id, "title": "Backend Engineer", "company": "TestCo", "location": "MI", "text": job_text},
        timeout=20,
    )
    assert_status(r, 200)
    job = get_json(r)
    job_id = job["id"]
    ok(f"Ingested job: {job_id}")

    r = requests.post(
        f"{base}/tailor/preview",
        json={"user_id": args.user_id, "job_id": job_id, "template": "ats_v1", "max_items": 3, "max_bullets_per_item": 3},
        timeout=25,
    )
    assert_status(r, 200)
    out = get_json(r)

    for k in ["id", "sections", "plain_text", "selected_item_ids", "selected_skill_ids"]:
        if k not in out:
            die(f"Missing {k} in response")

    if not isinstance(out["sections"], list) or len(out["sections"]) == 0:
        die("sections empty")
    txt = out["plain_text"]
    if "SUMMARY" not in txt.upper():
        die("plain_text missing SUMMARY section")
    if "SKILLS" not in txt.upper():
        die("plain_text missing SKILLS section")
    if "RELEVANT WORK" not in txt.upper():
        die("plain_text missing RELEVANT WORK section")

    ok("Tailor preview generated from job_id")
    pretty(out)


if __name__ == "__main__":
    main()
