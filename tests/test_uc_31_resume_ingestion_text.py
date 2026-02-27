"""UC 3.1 — Resume Ingestion (Paste/Text)

Endpoint(s):
- POST /ingest/resume/text

What is being tested:
- The API accepts pasted resume text and returns a snapshot_id + preview.

Pass criteria:
- HTTP 200
- response has snapshot_id (string) and preview (string)
- preview is a prefix of the original text (up to ~200 chars)
"""

import requests
from _common import parse_args, assert_status, get_json, ok, pretty, die


def main():
    args = parse_args()
    base = args.base_url.rstrip("/")

    resume_text = (
        "Cordell test resume. Experience with Python, FastAPI, and MongoDB. "
        "Also used Docker and React in capstone."
    )

    r = requests.post(
        f"{base}/ingest/resume/text",
        json={"user_id": args.user_id, "text": resume_text},
        timeout=15,
    )
    assert_status(r, 200)
    data = get_json(r)

    sid = data.get("snapshot_id")
    preview = data.get("preview")
    if not sid or not isinstance(sid, str):
        die("Missing/invalid snapshot_id")
    if not preview or not isinstance(preview, str):
        die("Missing/invalid preview")
    if not resume_text.startswith(preview.replace("...", "")) and preview.replace("...", "") not in resume_text:
        die("Preview does not appear to match input text prefix")

    ok("UC 3.1 resume ingestion (text)")
    pretty(data)


if __name__ == "__main__":
    main()
