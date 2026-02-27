"""UC 4.1 — Moderate Job Postings

What is being tested:
- GET /jobs?status=pending returns at least one job (from seed).
- PATCH /jobs/{job_id}/moderate sets status=rejected with a reason.

Pass criteria:
- response reflects updated moderation_status and moderation_reason.
"""

import requests
from tests._common import parse_args, assert_status, get_json, ok, pretty, die


def main():
    args = parse_args()
    base = args.base_url.rstrip("/")

    r = requests.get(f"{base}/jobs?status=pending", timeout=15)
    assert_status(r, 200)
    jobs = get_json(r)
    if not jobs:
        die("No pending jobs found; seed should create one.")
    job_id = jobs[0]["id"]

    payload = {"moderation_status": "rejected", "moderation_reason": "Rejected by UC test."}
    r = requests.patch(f"{base}/jobs/{job_id}/moderate", json=payload, timeout=15)
    assert_status(r, 200)
    j = get_json(r)

    if j.get("moderation_status") != "rejected":
        die("Status not updated")
    if j.get("moderation_reason") != payload["moderation_reason"]:
        die("Reason not updated")

    ok("UC 4.1 moderation")
    pretty(j)


if __name__ == "__main__":
    main()
