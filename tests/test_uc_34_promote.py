"""UC 3.4 — Promote confirmed resume skills into portfolio entities

What is being tested:
- POST /ingest/resume/{snapshot_id}/promote promotes confirmed skills.

Note:
- Requires env var SNAPSHOT_ID because there is no API endpoint to list snapshots.

Pass criteria:
- response includes project_id and promoted count.
"""

import os
import requests
from tests._common import parse_args, assert_status, get_json, ok, pretty, die


def main():
    args = parse_args()
    base = args.base_url.rstrip("/")

    snapshot_id = os.environ.get("SNAPSHOT_ID")
    if not snapshot_id:
        die("Set SNAPSHOT_ID to the resume_snapshots _id printed by seed_mongo.py")

    r = requests.post(f"{base}/ingest/resume/{snapshot_id}/promote", data={"user_id": args.user_id}, timeout=20)
    assert_status(r, 200)
    data = get_json(r)

    if "project_id" not in data:
        die("Missing project_id")
    if "promoted" not in data:
        die("Missing promoted")

    ok("UC 3.4 promote")
    pretty(data)


if __name__ == "__main__":
    main()
