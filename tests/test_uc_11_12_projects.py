"""UC 1.1 + UC 1.2 — Create Project + Link Skill to Project

What is being tested:
- UC 1.1: POST /projects creates a project entry.
- UC 1.2: POST /projects/{project_id}/skills links a skill to the project.

Pass criteria:
- Both calls return 200 and expected ids/fields.
"""

import requests
from tests._common import parse_args, assert_status, get_json, ok, pretty, die


def main():
    args = parse_args()
    base = args.base_url.rstrip("/")

    r = requests.post(
        f"{base}/projects",
        json={"user_id": args.user_id, "title": "UC1 Project Test", "description": "Created by test", "tags": ["uc1"]},
        timeout=15,
    )
    assert_status(r, 200)
    proj = get_json(r)
    if "id" not in proj:
        die("Missing project id")
    ok("UC 1.1 create project")
    pretty(proj)

    r = requests.get(f"{base}/skills?limit=1", timeout=15)
    assert_status(r, 200)
    skills = get_json(r)
    if not skills:
        die("No skills found; seed first.")
    skill_id = skills[0]["id"]

    r = requests.post(f"{base}/projects/{proj['id']}/skills", json={"skill_id": skill_id}, timeout=15)
    assert_status(r, 200)
    link = get_json(r)
    if link.get("project_id") != proj["id"]:
        die("project_id mismatch")
    if link.get("skill_id") != skill_id:
        die("skill_id mismatch")
    ok("UC 1.2 link skill to project")
    pretty(link)


if __name__ == "__main__":
    main()
