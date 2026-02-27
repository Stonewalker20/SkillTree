"""UC 2.1 — Add a Skill with Category/Tags

Endpoint:
- POST /skills

What is being tested:
- Creating a skill with: name, category, aliases, tags.
- Verifying the response includes an id and echoes the stored fields.
- Verifying the skill can be retrieved via GET /skills?q=...

Pass criteria:
- POST returns 200 and includes id, name, category, aliases, tags
- GET search returns an entry matching the created id/name
"""

import requests
from _common import parse_args, assert_status, get_json, ok, pretty, die


def main():
    args = parse_args()
    base = args.base_url.rstrip("/")

    unique_name = "Skill UC2.1 Test Skill"

    payload = {
        "name": unique_name,
        "category": "Testing",
        "aliases": ["uc21-skill-alias"],
        "tags": ["capstone", "uc2", "skill-management"],
        "proficiency": 3,
    }

    r = requests.post(f"{base}/skills", json=payload, timeout=15)

    # If your API rejects duplicates, fall back to search
    if r.status_code == 200:
        created = get_json(r)
        if not created.get("id"):
            die("Create skill did not return id")
        if created.get("name") != unique_name:
            die("Create skill did not echo name")
        if created.get("category") != payload["category"]:
            die("Create skill did not echo category")
        if created.get("aliases") != payload["aliases"]:
            die("Create skill did not echo aliases")
        # tags might be new; if backend not updated, this will fail (intentionally)
        if created.get("tags") != payload["tags"]:
            die(f"Create skill did not echo tags. got={created.get('tags')}")
        ok("Created skill")
        pretty(created)
        created_id = created["id"]
    else:
        # could be duplicate / validation differences
        assert_status(r, 200)

    # Search
    r = requests.get(f"{base}/skills?q={unique_name}&limit=25", timeout=15)
    assert_status(r, 200)
    rows = get_json(r)
    if not any(s.get("name") == unique_name for s in rows):
        die("Created skill not found in search results")
    ok("Skill found via search")


if __name__ == "__main__":
    main()
