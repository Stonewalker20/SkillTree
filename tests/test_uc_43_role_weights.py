"""UC 4.3 — Compute Role Skill Weights

What is being tested:
- GET /roles returns at least one role.
- POST /roles/{role_id}/compute_weights computes weights using approved jobs.
- GET /roles/{role_id}/weights returns stored weights.

Pass criteria:
- responses include role_id, computed_at, weights(list)
"""

import requests
from _common import parse_args, assert_status, get_json, ok, pretty, die


def main():
    args = parse_args()
    base = args.base_url.rstrip("/")

    r = requests.get(f"{base}/roles", timeout=15)
    assert_status(r, 200)
    roles = get_json(r)
    if not roles:
        die("No roles found; seed first.")
    role_id = roles[0]["id"]

    r = requests.post(f"{base}/roles/{role_id}/compute_weights", timeout=20)
    assert_status(r, 200)
    comp = get_json(r)
    for k in ["role_id", "computed_at", "weights"]:
        if k not in comp:
            die(f"Missing {k}")
    ok("UC 4.3 compute weights")
    pretty(comp)

    r = requests.get(f"{base}/roles/{role_id}/weights", timeout=15)
    assert_status(r, 200)
    stored = get_json(r)
    for k in ["role_id", "computed_at", "weights"]:
        if k not in stored:
            die(f"Missing {k} in stored weights")
    ok("UC 4.3 get weights")
    pretty(stored)


if __name__ == "__main__":
    main()
