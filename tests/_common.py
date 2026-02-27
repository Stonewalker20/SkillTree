from __future__ import annotations

import argparse
import json
import sys
import requests


def die(msg: str):
    print(f"FAIL: {msg}")
    sys.exit(1)


def ok(msg: str):
    print(f"OK: {msg}")


def pretty(obj):
    print(json.dumps(obj, indent=2, default=str))


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--user-id", default="Jack Stone")
    return ap.parse_args()


def assert_status(resp: requests.Response, code: int):
    if resp.status_code != code:
        print("Response status:", resp.status_code)
        print("Response body:", resp.text)
        die(f"Expected status {code}")


def get_json(resp: requests.Response):
    try:
        return resp.json()
    except Exception:
        print("Non-JSON response:", resp.text)
        raise
