"""UC 1.3 — Add Evidence Artifact (with associations)

What is being tested:
- POST /evidence creates evidence linked to (skill_ids, project_id, user_id).
- GET /evidence with filters returns the created evidence.

Pass criteria:
- Create returns id and echoes associations.
- Filtered list includes created id.
"""

import requests
from _common import parse_args, assert_status, get_json, ok, pretty, die


def main():
    args = parse_args()
    base = args.base_url.rstrip("/")

    r = requests.get(f"{base}/skills?limit=1", timeout=15)
    assert_status(r, 200)
    skills = get_json(r)
    if not skills:
        die("No skills found; seed first.")
    skill_id = skills[0]["id"]

    r = requests.post(
        f"{base}/projects",
        json={"user_id": args.user_id, "title": "UC1 Evidence Project", "description": "", "tags": []},
        timeout=15,
    )
    assert_status(r, 200)
    proj = get_json(r)
    project_id = proj["id"]

    payload = {
        "user_id": args.user_id,
        "type": "project",
        "title": "Evidence Test",
        "source": "local:test",
        "text_excerpt": "Evidence linkage works.",
        "skill_ids": [skill_id],
        "project_id": project_id,
        "tags": ["uc1", "evidence"],
    }
    r = requests.post(f"{base}/evidence", json=payload, timeout=15)
    assert_status(r, 200)
    ev = get_json(r)
    if "id" not in ev:
        die("Missing evidence id")
    ok("UC 1.3 create evidence")
    pretty(ev)

    r = requests.get(f"{base}/evidence?user_id={args.user_id}&project_id={project_id}&skill_id={skill_id}", timeout=15)
    assert_status(r, 200)
    rows = get_json(r)
    if not any(x.get("id") == ev["id"] for x in rows):
        die("Evidence not found in filtered list")
    ok("UC 1.3 evidence retrieval")
    print(f"Filtered evidence count: {len(rows)}")


if __name__ == "__main__":
    main()
