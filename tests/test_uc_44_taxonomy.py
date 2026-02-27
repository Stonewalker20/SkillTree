"""UC 4.4 — Maintain Taxonomy (aliases + relationships)

What is being tested:
- PUT /taxonomy/aliases/{skill_id} updates skills.aliases.
- POST /taxonomy/relations creates a relation between two skills.
- GET /taxonomy/relations?skill_id=... returns the relation.

Pass criteria:
- alias response matches requested list
- relation create returns id
- filtered relation list includes created relation id
"""

import requests
from _common import parse_args, assert_status, get_json, ok, pretty, die


def main():
    args = parse_args()
    base = args.base_url.rstrip("/")

    r = requests.get(f"{base}/skills?limit=2", timeout=15)
    assert_status(r, 200)
    skills = get_json(r)
    if len(skills) < 2:
        die("Need 2 skills")
    a, b = skills[0]["id"], skills[1]["id"]

    aliases = ["alias_one", "alias_two"]
    r = requests.put(f"{base}/taxonomy/aliases/{a}", json={"aliases": aliases}, timeout=15)
    assert_status(r, 200)
    data = get_json(r)
    if data.get("aliases") != aliases:
        die("Aliases mismatch")
    ok("UC 4.4 alias update")
    pretty(data)

    payload = {"from_skill_id": a, "to_skill_id": b, "relation_type": "related_to"}
    r = requests.post(f"{base}/taxonomy/relations", json=payload, timeout=15)
    assert_status(r, 200)
    rel = get_json(r)
    if "id" not in rel:
        die("Missing relation id")
    ok("UC 4.4 relation create")
    pretty(rel)

    r = requests.get(f"{base}/taxonomy/relations?skill_id={a}", timeout=15)
    assert_status(r, 200)
    rows = get_json(r)
    if not any(x.get("id") == rel["id"] for x in rows):
        die("Relation not found in list")
    ok("UC 4.4 relation list")
    print(f"Relations involving {a}: {len(rows)}")


if __name__ == "__main__":
    main()
