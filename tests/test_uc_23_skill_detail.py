"""UC 2.3 — Skill Detail

What is being tested:
- GET /skills/{skill_id}/detail?user_id=... returns:
  - skill
  - linked_projects
  - linked_evidence

Pass criteria:
- keys exist.
"""

import requests
from tests._common import parse_args, assert_status, get_json, ok, pretty, die


def main():
    args = parse_args()
    base = args.base_url.rstrip("/")

    r = requests.get(f"{base}/skills?limit=1", timeout=15)
    assert_status(r, 200)
    skills = get_json(r)
    if not skills:
        die("No skills found")
    sid = skills[0]["id"]

    r = requests.get(f"{base}/skills/{sid}/detail?user_id={args.user_id}", timeout=15)
    assert_status(r, 200)
    data = get_json(r)
    for k in ["skill", "linked_projects", "linked_evidence"]:
        if k not in data:
            die(f"Missing {k}")

    ok("UC 2.3 skill detail")
    pretty(data)


if __name__ == "__main__":
    main()
