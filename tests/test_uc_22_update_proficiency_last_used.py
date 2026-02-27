"""UC 2.2 — Update Skill Proficiency and Last Used Date

Endpoint(s):
- PATCH /skills/{skill_id}

What is being tested:
- Updating a skill's proficiency and last_used_at.

Pass criteria:
- HTTP 200
- returned proficiency equals requested proficiency
- returned last_used_at is not null (and parses / echoes in ISO form)
"""

from datetime import datetime, timezone
import requests
from _common import parse_args, assert_status, get_json, ok, pretty, die


def main():
    args = parse_args()
    base = args.base_url.rstrip("/")

    # create a skill to update
    r = requests.post(f"{base}/skills", json={"name": "UC22 Skill", "category": "Test", "aliases": []}, timeout=15)
    assert_status(r, 200)
    skill = get_json(r)
    sid = skill["id"]

    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    r = requests.patch(f"{base}/skills/{sid}", json={"proficiency": 5, "last_used_at": ts}, timeout=15)
    assert_status(r, 200)
    updated = get_json(r)

    if updated.get("proficiency") != 5:
        die("proficiency not updated")
    if not updated.get("last_used_at"):
        die("last_used_at missing after update")

    ok("UC 2.2 update proficiency/last_used_at")
    pretty(updated)


if __name__ == "__main__":
    main()
