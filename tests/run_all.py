"""
Run all SkillBridge use-case tests that match the current FastAPI router set.

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
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

HERE = Path(__file__).resolve().parent


# ---------- Terminal styling (no external deps) ----------
def _use_color(no_color: bool) -> bool:
    # Respect NO_COLOR and explicit flag
    if no_color:
        return False
    if os.environ.get("NO_COLOR") is not None:
        return False
    # Basic TTY check
    return sys.stdout.isatty()


def _c(s: str, code: str, enabled: bool) -> str:
    if not enabled:
        return s
    return f"\x1b[{code}m{s}\x1b[0m"


def _bold(s: str, enabled: bool) -> str:
    return _c(s, "1", enabled)


def _dim(s: str, enabled: bool) -> str:
    return _c(s, "2", enabled)


def _green(s: str, enabled: bool) -> str:
    return _c(s, "32", enabled)


def _red(s: str, enabled: bool) -> str:
    return _c(s, "31", enabled)


def _yellow(s: str, enabled: bool) -> str:
    return _c(s, "33", enabled)


def _hr(width: int = 88) -> str:
    return "=" * width


def _truncate_lines(text: str, max_lines: int) -> str:
    if max_lines <= 0:
        return text
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    head = lines[: max_lines]
    omitted = len(lines) - max_lines
    return "\n".join(head) + f"\n... ({omitted} more lines truncated) ..."


@dataclass
class TestResult:
    name: str
    script: str
    returncode: int
    seconds: float
    output: str


def run_script(script: str, base_url: str, user_id: str, timeout: Optional[int]) -> TestResult:
    cmd = [sys.executable, str(HERE / script), "--base-url", base_url, "--user-id", user_id]

    start = time.perf_counter()
    try:
        # capture_output=True so we can show clean summaries and only dump output on failures
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.perf_counter() - start
        out = (proc.stdout or "") + (proc.stderr or "")
        return TestResult(name=Path(script).stem, script=script, returncode=proc.returncode, seconds=elapsed, output=out)
    except subprocess.TimeoutExpired as e:
        elapsed = time.perf_counter() - start
        out = ""
        if e.stdout:
            out += e.stdout if isinstance(e.stdout, str) else e.stdout.decode(errors="replace")
        if e.stderr:
            out += e.stderr if isinstance(e.stderr, str) else e.stderr.decode(errors="replace")
        out += f"\n[runner] TIMEOUT after {timeout}s\n"
        return TestResult(name=Path(script).stem, script=script, returncode=124, seconds=elapsed, output=out)


def print_header(base_url: str, user_id: str, color: bool):
    print(_bold("SkillBridge Test Runner", color))
    print(_dim(f"base_url: {base_url} | user_id: {user_id}", color))
    print(_hr())


def print_result_line(res: TestResult, color: bool):
    status = "PASS" if res.returncode == 0 else "FAIL"
    badge = _green(f"[{status}]", color) if status == "PASS" else _red(f"[{status}]", color)

    # fixed-ish width alignment
    name = f"{res.name}"
    timing = f"{res.seconds:6.2f}s"
    rc = f"rc={res.returncode}"

    print(f"{badge}  {name:<48}  {timing:>8}  {_dim(rc, color)}")


def print_failure_output(res: TestResult, color: bool, max_output_lines: int):
    print(_red(_hr(), color))
    print(_red(f"FAILED: {res.script} (rc={res.returncode})", color))
    print(_red(_hr(), color))
    if res.output.strip():
        print(_truncate_lines(res.output.rstrip(), max_output_lines))
    else:
        print(_dim("[no output captured]", color))
    print()


def print_summary(results: List[TestResult], color: bool):
    total = len(results)
    passed = sum(1 for r in results if r.returncode == 0)
    failed = total - passed
    secs = sum(r.seconds for r in results)

    print(_hr())
    label = "ALL TESTS PASSED" if failed == 0 else "TESTS FAILED"
    label_colored = _green(label, color) if failed == 0 else _red(label, color)
    print(_bold(label_colored, color))
    print(_dim(f"passed: {passed} | failed: {failed} | total: {total} | time: {secs:.2f}s", color))

    if failed:
        print(_dim("\nFailed tests:", color))
        for r in results:
            if r.returncode != 0:
                print(f" - {r.script} (rc={r.returncode})")
    print(_hr())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--user-id", default="Jack Stone")
    ap.add_argument("--fail-fast", action="store_true", help="Stop on first failure.")
    ap.add_argument("--show-output", action="store_true", help="Always print each test's captured output.")
    ap.add_argument("--max-output-lines", type=int, default=250, help="Max lines to print per test output block.")
    ap.add_argument("--timeout", type=int, default=None, help="Per-test timeout in seconds.")
    ap.add_argument("--no-color", action="store_true", help="Disable ANSI colors.")
    args = ap.parse_args()

    color = _use_color(args.no_color)
    print_header(args.base_url, args.user_id, color)

    # Ordered roughly by user-facing flows:
    scripts = [
        # Portfolio CRUD + Tailor pipeline (new)
        "test_tailor_portfolio_crud.py",
        "test_tailor_job_ingest.py",
        "test_tailor_preview_from_job.py",
        "test_tailor_exports.py",

        # Existing
        "test_uc_11_12_projects.py",
        "test_uc_13_evidence.py",
        "test_uc_14_dashboard.py",
        "test_uc_22_update_proficiency_last_used.py",
        "test_uc_23_skill_detail.py",
        "test_uc_24_confirmed_skill_gaps_user_specific.py",
        "test_uc_31_resume_ingestion_text.py",
        "test_uc_32_skill_extraction.py",
        "test_uc_33_confirm_reject_extracted_skills.py",
        "test_uc_34_promote.py",
        "test_uc_41_moderation.py",
        "test_uc_42_roles_and_tagging.py",
        "test_uc_43_role_weights.py",
        "test_uc_44_taxonomy.py",
    ]

    results: List[TestResult] = []

    for script in scripts:
        # Pre-flight: script exists
        p = HERE / script
        if not p.exists():
            res = TestResult(
                name=Path(script).stem,
                script=script,
                returncode=2,
                seconds=0.0,
                output=f"[runner] missing test file: {p}\n",
            )
            results.append(res)
            print_result_line(res, color)
            print_failure_output(res, color, args.max_output_lines)
            if args.fail_fast:
                break
            continue

        res = run_script(script, args.base_url, args.user_id, args.timeout)
        results.append(res)
        print_result_line(res, color)

        if args.show_output:
            print(_dim(_hr(), color))
            print(_dim(f"OUTPUT: {script}", color))
            print(_dim(_hr(), color))
            print(_truncate_lines(res.output.rstrip(), args.max_output_lines) if res.output else _dim("[no output captured]", color))
            print()

        if res.returncode != 0 and not args.show_output:
            print_failure_output(res, color, args.max_output_lines)
            if args.fail_fast:
                break

    print_summary(results, color)

    # Exit non-zero if anything failed
    if any(r.returncode != 0 for r in results):
        raise SystemExit(1)

    print("\n" + _green("ALL SELECTED TESTS COMPLETED", color))


if __name__ == "__main__":
    main()