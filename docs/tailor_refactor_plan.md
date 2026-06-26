# tailor.py Split: Evaluation and Recommended Plan

`backend/app/routers/tailor.py` is 3,736 lines and ~100 functions: it's the largest file in the
backend by a wide margin and combines four distinct concerns that currently have no module
boundary between them. This doc evaluates splitting it and lays out a concrete plan. **No code
was moved as part of this pass** — see "Why this wasn't executed automatically" below.

## Current structure (by line range)

| Range | Concern | Notes |
| --- | --- | --- |
| 1-125 | Imports, `router = APIRouter()`, `TAILORED_RESUME_TEMPLATES` config dict | Module-level state |
| 127-518 | Generic text/display helpers + RAG search & user-vector routes | `_clean_display_text`, `_plain_language_excerpt`, `search_rag_context`, `get_user_skill_vector` |
| 520-1290 | Job match scoring engine | Tokenization, skill matching, coverage scoring, gap/strength insight building (`_match_skills`, `_score_item`, `_build_gap_insights`, `_classify_job_skill_priority`) |
| 1292-2067 | Resume template & section engine | Parsing uploaded resumes into sections, building sections from templates, rewriting bullets (`_parse_resume_sections`, `_build_sections_from_resume_template`, `_rewrite_uploaded_resume_raw_text`) |
| 2068-3380 | HTTP route handlers | `ingest_job`, `match_job` (~600 lines), `preview_tailored_resume` (~240 lines), resume CRUD routes, history routes, AI settings routes, `rewrite_tailored_resume_bullets` |
| 3382-3736 | DOCX/PDF export rendering + export routes | `_docx_from_sections`, `_pdf_from_sections`, `export_docx`, `export_pdf` |

The route handlers in the 2068-3380 block are mostly orchestration: they call into the helpers
defined earlier in the file rather than containing their own large blocks of novel logic. That's
good news for splitting — the heavy lifting is already factored into named functions, just not
into separate files.

## Import-surface analysis (why this is lower-risk than it looks)

Searched the whole backend for anything that imports from this file. Only three places do, and
all three import only the `router` object itself, never any of the internal helpers:

- `backend/app/main.py`: `from app.routers.tailor import router as tailor_router`
- `backend/app/routers/__init__.py`: `from .tailor import router as tailor_router`
- `backend/app/models/__init__.py` imports from `app/models/tailor.py` (the Pydantic schema
  file) — a different file, unaffected by this split.

No other router, test, or util module reaches into `tailor.py`'s private helpers. That means a
split can be done as a pure internal reorganization: `app/routers/tailor.py` keeps the
`APIRouter` and all `@router.*` handlers (so its public shape is unchanged), and the four helper
groups move into new sibling modules that `tailor.py` imports from.

## Proposed module breakdown

```
backend/app/routers/tailor.py            # router + route handlers only, imports from below
backend/app/utils/tailor_text.py         # generic text/display helpers (127-467, 520-613)
backend/app/utils/tailor_matching.py     # skill matching & scoring engine (613-1290)
backend/app/utils/tailor_resume_builder.py  # resume template/section parsing & rewriting (1292-2067)
backend/app/utils/tailor_export.py       # DOCX/PDF rendering (3382-3664)
```

`TAILORED_RESUME_TEMPLATES` and `DEFAULT_RESUME_TEMPLATE_TEX` would move into
`tailor_resume_builder.py` alongside the template logic that consumes them.

This mirrors the existing convention in `backend/app/utils/` (already home to `ai.py`,
`skill_catalog.py`, `rag.py`, `job_records.py`, etc.), so it's consistent with how the rest of
the backend is organized rather than introducing a new pattern.

## Migration procedure (recommended, for whoever runs this with test execution available)

1. Create the four new files one at a time, in the order listed above (text helpers first,
   since matching/resume-builder/export all depend on them).
2. For each file: cut the relevant functions out of `tailor.py`, paste into the new module,
   add the imports the moved code needs, then add an import line back in `tailor.py` for
   whatever it still calls from that group.
3. After each single-file move: run `pytest -q` (specifically
   `pytest tests/test_resumes_dashboard_and_tailor.py -v`, which is the test file that exercises
   this router) before moving on to the next group. Don't batch multiple moves before testing —
   if something breaks, you want to know which move caused it.
4. Run `ruff check app` after the full split to confirm no unused imports were left behind in
   `tailor.py` and no missing imports in the new files.
5. Only after all four moves pass tests, consider whether `match_job` and
   `preview_tailored_resume` (the two largest route handlers, ~600 and ~240 lines respectively)
   are worth decomposing further internally. That's a separate, smaller follow-up — file-level
   splitting and in-function decomposition are different risk profiles and shouldn't be done in
   the same pass.

## Why this wasn't executed automatically

This sandbox has no package-registry network access, so `pytest` cannot be run here to verify
behavior is preserved after moving ~3,000 lines of interdependent code by hand. A split this
size done via text edits, with no test run in between to catch a transcription mistake or a
missed import, is exactly the kind of change that can silently break job matching or resume
generation — the product's core features — without anyone noticing until a user hits it.
Given that, and that this was already flagged as the highest-risk item in the audit, the safer
deliverable is this plan rather than a best-effort mechanical split. The import-surface analysis
above means the actual move, when done locally with the test suite available, should be
low-risk to execute step by step.
