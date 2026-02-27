"""Tailor Add-on — Portfolio Items CRUD

Endpoints:
- POST   /portfolio/items
- GET    /portfolio/items?user_id=...
- PATCH  /portfolio/items/{item_id}
- DELETE /portfolio/items/{item_id}

What is being tested:
- Create a portfolio item with bullets, links, skill_ids.
- List returns the created item.
- Patch updates priority + visibility + bullets.
- Delete removes it.

Pass criteria:
- Correct status codes and the created id appears/disappears as expected.
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

    payload = {
        "user_id": args.user_id,
        "type": "project",
        "title": "Tailor Portfolio Test Item",
        "org": "SkillBridge",
        "date_start": "2026-01",
        "date_end": "present",
        "summary": "A FastAPI service that generates tailored resumes.",
        "bullets": [
            "Built FastAPI routers and MongoDB collections for portfolio + tailoring features.",
            "Implemented deterministic selection based on skills and keyword overlap.",
        ],
        "links": ["https://github.com/example/skillbridge"],
        "skill_ids": [python_id],
        "tags": ["tailor", "test"],
        "visibility": "private",
        "priority": 1,
    }

    r = requests.post(f"{base}/portfolio/items", json=payload, timeout=15)
    assert_status(r, 200)
    item = get_json(r)
    if "id" not in item:
        die("Missing id on create")
    item_id = item["id"]
    ok("Created portfolio item")
    pretty(item)

    r = requests.get(f"{base}/portfolio/items?user_id={args.user_id}", timeout=15)
    assert_status(r, 200)
    items = get_json(r)
    if not any(x.get("id") == item_id for x in items):
        die("Created item not found in list")
    ok("List portfolio items contains created item")

    patch = {"priority": 10, "visibility": "public", "bullets": ["Updated bullet 1", "Updated bullet 2"]}
    r = requests.patch(f"{base}/portfolio/items/{item_id}", json=patch, timeout=15)
    assert_status(r, 200)
    updated = get_json(r)
    if updated.get("priority") != 10:
        die("priority not updated")
    if updated.get("visibility") != "public":
        die("visibility not updated")
    if updated.get("bullets") != patch["bullets"]:
        die("bullets not updated")
    ok("Patched portfolio item")
    pretty(updated)

    r = requests.delete(f"{base}/portfolio/items/{item_id}", timeout=15)
    assert_status(r, 200)
    out = get_json(r)
    if not out.get("deleted"):
        die("delete did not return deleted=true")
    ok("Deleted portfolio item")

    r = requests.get(f"{base}/portfolio/items?user_id={args.user_id}", timeout=15)
    assert_status(r, 200)
    items2 = get_json(r)
    if any(x.get("id") == item_id for x in items2):
        die("Deleted item still present in list")
    ok("Deleted item no longer present")


if __name__ == "__main__":
    main()
