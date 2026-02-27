"""Run all Tailor subsystem tests (portfolio + job ingest + preview + exports).

Usage:
  python tests/run_tailor_all.py --base-url http://localhost:8000 --user-id student1
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

TESTS = [
    "test_tailor_portfolio_crud.py",
    "test_tailor_job_ingest.py",
    "test_tailor_preview_from_job.py",
    "test_tailor_exports.py",
]

def run(script: str, base_url: str, user_id: str):
    cmd = [sys.executable, str(HERE / script), "--base-url", base_url, "--user-id", user_id]
    print("\n" + "=" * 80)
    print("RUN:", " ".join(cmd))
    print("=" * 80)
    res = subprocess.run(cmd)
    if res.returncode != 0:
        raise SystemExit(res.returncode)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--user-id", default="student1")
    args = ap.parse_args()

    for t in TESTS:
        run(t, args.base_url, args.user_id)

    print("\nALL TAILOR TESTS COMPLETED")

if __name__ == "__main__":
    main()
