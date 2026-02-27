"""UC 1.4 — Dashboard Summary Query

What is being tested:
- GET /dashboard/summary?user_id=... returns totals + recent projects + top skills by evidence.

Pass criteria:
- totals has keys: projects, evidence, confirmed_skills
- recent_projects is list
- top_skills_by_evidence is list
"""

import requests
from _common import parse_args, assert_status, get_json, ok, pretty, die


def main():
    args = parse_args()
    base = args.base_url.rstrip("/")

    r = requests.get(f"{base}/dashboard/summary?user_id={args.user_id}", timeout=15)
    assert_status(r, 200)
    data = get_json(r)

    totals = data.get("totals")
    if not totals:
        die("Missing totals")
    for k in ["projects", "evidence", "confirmed_skills"]:
        if k not in totals:
            die(f"Missing totals.{k}")
    if not isinstance(data.get("recent_projects"), list):
        die("recent_projects not list")
    if not isinstance(data.get("top_skills_by_evidence"), list):
        die("top_skills_by_evidence not list")

    ok("UC 1.4 dashboard summary")
    pretty(data)


if __name__ == "__main__":
    main()
