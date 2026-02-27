"""UC 4.2 — Role CRUD + Tag Posting by Role

What is being tested:
- POST /roles creates a role (or returns 409 if exists).
- POST /jobs creates an approved job.
- POST /jobs/{job_id}/roles attaches role_id to the job.

Pass criteria:
- job.role_ids contains role_id after tagging.
"""

import requests
from tests._common import parse_args, assert_status, get_json, ok, pretty, die

ROLE_NAME = "UC Test Role"


def main():
    args = parse_args()
    base = args.base_url.rstrip("/")

    r = requests.post(f"{base}/roles", json={"name": ROLE_NAME, "description": "Created by UC tests."}, timeout=15)
    if r.status_code == 409:
        ok("Role already exists (409) - looking up id")
        r2 = requests.get(f"{base}/roles", timeout=15)
        assert_status(r2, 200)
        roles = get_json(r2)
        role_id = next((x["id"] for x in roles if x["name"].lower() == ROLE_NAME.lower()), None)
        if not role_id:
            die("Role exists but not found in list")
    else:
        assert_status(r, 200)
        role_id = get_json(r)["id"]
        ok("Role created")

    job_payload = {
        "title": "UC Role Tagging Job",
        "company": "TestCo",
        "location": "MI",
        "source": "uc-test",
        "description_excerpt": "Validates role tagging.",
        "required_skills": ["Python"],
        "required_skill_ids": [],
        "role_ids": [],
    }
    r = requests.post(f"{base}/jobs", json=job_payload, timeout=15)
    assert_status(r, 200)
    job = get_json(r)
    job_id = job["id"]

    r = requests.post(f"{base}/jobs/{job_id}/roles", json={"role_id": role_id}, timeout=15)
    assert_status(r, 200)
    tagged = get_json(r)

    if role_id not in (tagged.get("role_ids") or []):
        die("role_id not present after tagging")

    ok("UC 4.2 role tagging")
    pretty(tagged)


if __name__ == "__main__":
    main()
