"""Tailor Add-on — Export PDF/DOCX

Endpoints:
- POST /tailor/job/ingest
- POST /tailor/preview
- GET  /tailor/{tailored_id}/export/pdf
- GET  /tailor/{tailored_id}/export/docx

What is being tested:
- Generate a tailored resume.
- Download PDF and DOCX exports.

Pass criteria:
- Export responses return 200
- Content-Type matches PDF / DOCX
- Response body length is non-trivial (> 1KB)
"""

import requests
from _common import parse_args, assert_status, get_json, ok, die


def main():
    args = parse_args()
    base = args.base_url.rstrip("/")

    job_text = """ML Engineer.

Need Python. Bonus: FastAPI and MongoDB.
"""

    r = requests.post(
        f"{base}/tailor/job/ingest",
        json={"user_id": args.user_id, "title": "ML Engineer", "company": "TestCo", "location": "Remote", "text": job_text},
        timeout=20,
    )
    assert_status(r, 200)
    job_id = get_json(r)["id"]

    r = requests.post(
        f"{base}/tailor/preview",
        json={"user_id": args.user_id, "job_id": job_id, "template": "ats_v1"},
        timeout=25,
    )
    assert_status(r, 200)
    tailored_id = get_json(r)["id"]
    ok(f"Generated tailored resume: {tailored_id}")

    # PDF
    r = requests.get(f"{base}/tailor/{tailored_id}/export/pdf", timeout=30)
    assert_status(r, 200)
    ct = r.headers.get("content-type", "")
    if "application/pdf" not in ct:
        die(f"Expected application/pdf, got {ct}")
    if len(r.content) < 1024:
        die("PDF too small; export likely failed")
    ok("PDF export OK")

    # DOCX
    r = requests.get(f"{base}/tailor/{tailored_id}/export/docx", timeout=30)
    assert_status(r, 200)
    ct = r.headers.get("content-type", "")
    if "application/vnd.openxmlformats-officedocument.wordprocessingml.document" not in ct:
        die(f"Expected DOCX content-type, got {ct}")
    if len(r.content) < 1024:
        die("DOCX too small; export likely failed")
    ok("DOCX export OK")


if __name__ == "__main__":
    main()
