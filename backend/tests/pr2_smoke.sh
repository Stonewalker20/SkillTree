#!/usr/bin/env bash
set -euo pipefail

BASE="http://127.0.0.1:8000"

echo "[1] ingest resume text"
SNAP=$(curl -s -X POST "$BASE/ingest/resume/text" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"student1","text":"Python FastAPI MongoDB Docker Git. Built REST APIs and deployed with Docker. SQL, scikit-learn, BM25."}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['snapshot_id'])")

echo "snapshot_id=$SNAP"

echo "[2] extract skills"
curl -s -X POST "$BASE/skills/extract/skills/$SNAP" | python -m json.tool

echo "[3] gaps"
curl -s "$BASE/skills/gaps?threshold=0" | python -m json.tool

