"""Run all SkillBridge use-case tests that match the current FastAPI router set.

This runner assumes these router prefixes from main.py:
- /ingest/resume
- /skills
- /skills/confirmations

It includes tests for:
- UC 3.1 Resume ingestion (text)
- UC 3.2 Skill extraction
- UC 3.3 Confirm/Reject extracted skills
- UC 2.2 Update proficiency + last_used
- UC 2.4 Confirmed skill gaps (user-specific)

If you have additional endpoints (projects, dashboard, roles, moderation, taxonomy),
keep your older test files and run them separately or extend this runner.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


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

    run("test_uc_31_resume_ingestion_text.py", args.base_url, args.user_id)
    run("test_uc_32_skill_extraction.py", args.base_url, args.user_id)
    run("test_uc_33_confirm_reject_extracted_skills.py", args.base_url, args.user_id)
    run("test_uc_22_update_proficiency_last_used.py", args.base_url, args.user_id)
    run("test_uc_24_confirmed_skill_gaps_user_specific.py", args.base_url, args.user_id)

    print("\nALL SELECTED TESTS COMPLETED")


if __name__ == "__main__":
    main()
