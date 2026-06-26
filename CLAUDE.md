# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SkillBridge is a full-stack career intelligence platform that helps users collect evidence of their skills, confirm them, analyze job fit, and generate tailored resumes. It uses a FastAPI backend with MongoDB persistence, local transformer models for semantic matching (with a rule-based fallback), and a React/Vite frontend with Tailwind CSS and Radix UI.

**Version:** 0.5.0

## Architecture Overview

### Frontend (React 18 + Vite 6)

- **Location:** `frontend/src/app/`
- **Routing:** React Router 7 (file: `routes.tsx`)
- **Theme:** Tailwind 4 with next-themes for light/dark mode
- **UI Components:** Radix UI primitives + custom components in `frontend/src/app/components/ui/`
- **State Management:** React Context (AuthContext, ActivityContext, AccountPreferencesContext)
- **API Client:** Single centralized service in `frontend/src/app/services/api.ts` (handles all HTTP requests)
- **Pages:** Lazy-loaded under `frontend/src/app/pages/` (Landing, Login, SignUp, Skills, Evidence, Jobs, TailoredResumes, Admin, etc.)

Key architecture patterns:
- ProtectedRoute component enforces authentication and role-based access
- Vite proxy in dev mode rewrites `/api/*` → `http://localhost:8000`
- Build splits dependencies by type (recharts, radix-ui, mui, react-dnd, router, etc.)

### Backend (FastAPI + Motor/MongoDB + Local Transformers)

- **Location:** `backend/app/`
- **Entry point:** `backend/app/main.py` (lifespan hooks, middleware, router registration)
- **Configuration:** Pydantic Settings in `backend/app/core/config.py`
- **Database:** Motor (async MongoDB driver) with connection in `backend/app/core/db.py`
- **Auth:** Token-based sessions in `backend/app/core/auth.py` (PBKDF2 hashing, 30-day TTL)
- **Routers:** Modular API endpoints under `backend/app/routers/` (auth, skills, evidence, jobs, tailor, admin, etc.)
- **Models:** Pydantic schemas and DB helpers in `backend/app/models/`
- **Utilities:** Shared logic in `backend/app/utils/` including:
  - `ai.py` - Local transformer inference with caching and fallback modes
  - `skill_catalog.py` - Skill normalization and merging
  - `rag.py` - RAG chunking and vector storage
  - `media_storage.py` - Local or S3 avatar uploads
  - `security.py` - Rate limiting and throttling
  - `file_validation.py` - Magic-byte/content-sniffing checks for uploads (avatar images, resume PDF/DOCX); never trust filename extension or client-supplied content-type alone

Startup flow:
1. Lifespan hook validates settings, connects to MongoDB, creates indexes
2. Optionally prewarms local transformer models
3. Configures CORS middleware
4. Mounts media routes if using local storage
5. Registers all routers behind subscription gate (except auth, health, billing, help, rewards)

### Database (MongoDB)

Key collections:
- `users` - User accounts with role, subscription status, avatar, preferences
- `sessions` - Bearer tokens with TTL expiry
- `password_reset_tokens` - Password reset tokens with TTL expiry
- `skills` - User skill confirmations with proficiency and evidence links
- `evidence` - Ingested text, PDFs, or DOCX files with extracted skills
- `job_match_runs` - Saved job analyses with skill coverage and alignment scores
- `tailored_resumes` - Generated resumes with skill/job associations
- `jobs` - Job postings (user-submitted or ingested) with role associations
- `projects` - User projects with associated skills
- `portfolio` - Portfolio entries linking to projects/skills
- `rag_chunks` - Vector embeddings and text chunks for semantic search
- `audit_events` - Admin action logs
- `user_rewards` - Achievements and gamification state
- `learning_path_progress` - Skill development tracking

All collections use MongoDB indexes for hot paths (auth, job matches, resumes, etc.).

### AI Pipeline

Two modes:
1. **Local Transformer (auto or explicit `local-transformer`):** Uses sentence-transformers for embeddings and deberta for zero-shot skill classification. Optional flan-t5 for resume rewriting.
2. **Local Fallback (`local-fallback`):** Hash-based keyword matching and rule systems when transformer models are unavailable.
3. **OpenAI Mode (when `OPENAI_API_KEY` is set):** Uses hosted OpenAI embeddings and chat models.

Models are loaded on-demand with LRU caching. Inference device can be CPU (`LOCAL_MODEL_DEVICE=-1`) or GPU (device index).

Check which AI mode is active:
```bash
curl http://localhost:8000/tailor/settings/status
```

ML sandbox for model tuning and notebook experimentation: `backend/ml_sandbox/` (notebooks, datasets, artifacts). Changes here do not affect production until moved into `backend/app/`.

## Development Setup

### Prerequisites

- Python 3.10+
- Node.js 18+
- npm
- MongoDB 7 (local or Docker)

### Initial Setup

```bash
# Backend
cd backend
python3 -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt

# Frontend
cd ../frontend
npm install
```

### Running Locally

**MongoDB** (if not already running):
```bash
docker compose -f infra/docker-compose.yml up -d
```

**Backend** (from `backend/` directory):
```bash
source .venv/bin/activate
uvicorn app.main:app --reload
# API docs: http://localhost:8000/docs
```

**Frontend** (from `frontend/` directory, in another terminal):
```bash
npm run dev
# App: http://localhost:5173
```

Environment files:
- `backend/.env` (copy from `.env.example` or `.env.staging.example`)
- `frontend/.env` (copy from `.env.example`)

Key local dev settings:
- `APP_ENV=development`
- `ALLOWED_ORIGINS=http://localhost:5173`
- `MONGO_URI=mongodb://localhost:27017`
- `MEDIA_STORAGE_MODE=local`
- `LOCAL_MODEL_PREWARM=true` (optional, loads transformers at startup)
- `ADMIN_OWNER_EMAILS=owner@example.com` — emails listed here get owner role on registration
- `ADMIN_TEAM_EMAILS=team@example.com` — emails listed here get team role on registration

## Common Development Commands

### Backend

```bash
cd backend

# Install or update dependencies
pip install -r requirements.txt

# Run with auto-reload
uvicorn app.main:app --reload

# Run tests (all)
pytest -q

# Run specific test file
pytest tests/test_auth_and_health.py -v

# Run tests matching a pattern
pytest -k "test_skill" -v

# Install dev dependencies for testing
pip install -r requirements-dev.txt

# Run tests with coverage (requires requirements-dev.txt)
pytest -q --cov=app --cov-report=term-missing
```

### Frontend

```bash
cd frontend

# Install dependencies
npm install

# Dev server (Vite with hot reload)
npm run dev

# Build for production
npm run build

# Lint and fix
npm run lint
npm run lint:fix

# Format and check formatting (Prettier)
npm run format
npm run format:check

# Run tests
npm test

# Watch mode for tests
npm run test:watch

# Run tests with coverage
npm run test:coverage
```

## Code Patterns and Conventions

### Backend

- **Router registration:** All routers are included in `main.py` with optional subscription gate and tags for OpenAPI docs
- **Pydantic models:** Request/response schemas live alongside their usage (see `models/` directory)
- **Database access:** Use `get_db()` dependency from `core/db.py`; Motor is async, so use `await`
- **Auth:** Use `require_user()` dependency from `core/auth.py` to inject authenticated user; roles are strings ("user", "team", "admin", "owner")
- **Errors:** Raise `HTTPException` with appropriate status codes; 401 for missing/invalid auth, 403 for insufficient permissions
- **Timestamps:** Use `datetime.now(timezone.utc)` for UTC-aware datetimes
- **Rate limiting:** Implemented in routers for auth, evidence, jobs, and tailor endpoints

### Frontend

- **Pages:** Lazy-loaded with `lazy()` and `Suspense` for code-splitting
- **API calls:** All go through `services/api.ts`; use async/await
- **Context:** AuthContext provides auth state and login/logout functions
- **Components:** UI primitives from Radix wrapped with Tailwind classes
- **Error handling:** `RouteErrorBoundary` catches route errors; individual components should handle API errors
- **Styling:** Tailwind 4 with classname merging via `clsx`; custom components are shadcn-inspired
- **Formatting:** Prettier config in `frontend/.prettierrc.json`; run `npm run format` to write, `npm run format:check` to verify in CI without modifying files

## Testing

### Backend

Tests use pytest with a fake Mongo fixture (`tests/fake_mongo.py`). Test files:
- `test_auth_and_health.py` - Auth flow, session validation, health checks
- `test_api_surface.py` - Route existence and HTTP contract
- `test_evidence_and_confirmations.py` - Evidence ingestion, skill extraction, confirmations
- `test_skills_and_taxonomy.py` - Skill catalog and taxonomy endpoints
- `test_resumes_dashboard_and_tailor.py` - Resume generation, job match, tailoring
- `test_admin.py` - Admin actions, user role management, audit logs

Run all: `pytest -q`
Run specific: `pytest tests/test_auth_and_health.py::test_register -v`
Run with coverage: `pytest -q --cov=app --cov-report=term-missing` (config in `backend/pyproject.toml`)

### Frontend

Vitest runs in jsdom mode (config + setup file: `frontend/vitest.config.ts`, `frontend/src/test/setup.ts`). Test files live in `frontend/src/test/`:
- `avatarPresets.test.ts` - Avatar preset logic
- `headerTheme.test.ts` - Theme detection
- `rewardsSummary.test.ts` - Rewards calculation
- `dashboardPage.test.tsx`, `jobsPage.test.tsx`, `evidencePage.test.tsx`, `skillsPage.test.tsx`, `adminPage.test.tsx`, `adminMlflowPage.test.tsx` - Page-level smoke tests for `Dashboard`, `Jobs`, `Evidence`, `Skills`, `Admin`, `AdminMlflow`; render the real page component inside `MemoryRouter` with `AuthContext`/`ActivityContext`/`AccountPreferencesContext` and `services/api` mocked via `vi.mock`, then assert it renders a stable heading without throwing. These guard against render-breaking regressions; they do not cover interactive flows.

Run tests: `npm test`
Watch mode: `npm run test:watch`
Run with coverage: `npm run test:coverage` (config in `frontend/vitest.config.ts`)

## Key Files and Workflows

### Adding a New API Endpoint

1. Create a Pydantic schema in `backend/app/models/`
2. Create or extend a router in `backend/app/routers/`
3. Use `require_user()` dependency if auth is needed
4. Include the router in `backend/app/main.py` (with `prefix`, `tags`, and optional `dependencies=[Depends(require_active_subscription)]`)
5. Add tests in `backend/tests/`

### Adding a New Frontend Page

1. Create the component in `frontend/src/app/pages/`
2. Lazy-load it in `routes.tsx`
3. Add route config with title and optional role gates
4. Use `ProtectedRoute` wrapper for authenticated pages
5. Call API endpoints via `services/api.ts`

### Skill Extraction and Matching

- Evidence ingestion calls `utils/ai.py` functions for semantic extraction
- Local fallback in `utils/skill_catalog.py` uses keyword matching and inflection (plurals, singulars)
- Embeddings are cached in `rag_chunks` collection for RAG queries
- Zero-shot classification filters extracted skills by relevance

### Job Match Analysis

- Located in `backend/app/routers/tailor.py` (159KB—largest file)
- Combines skill coverage, semantic alignment, and keyword overlap
- Results are saved to `job_match_runs` for dashboard display
- Uses RAG chunk embeddings for similarity scoring

## Deployment Checklist

See `docs/deployment_guide.md` and `docs/env_matrix.md` for full details. Quick summary:

1. **Environment:** Use `backend/.env.staging.example` or `.env.production.example`
2. **MongoDB:** Must point to managed instance (not localhost) in staging/production
3. **CORS:** Set `ALLOWED_ORIGINS` to match deployed frontend domain exactly
4. **Media:** Use `MEDIA_STORAGE_MODE=s3` with valid credentials (not `local`)
5. **Billing:** Configure Stripe keys and price IDs if subscription checkout is enabled
6. **Frontend build:** Set `VITE_API_BASE` to deployed backend URL
7. **Smoke tests:** Register, request password reset, run job match, generate resume
8. **Deploy order:** Backend first, then frontend

## Performance Considerations

- Local transformer models load on-demand with LRU caching; prewarming on startup is optional
- Embedding lookups use MongoDB indexes on user_id + source_type
- Session lookups use TTL indexes for automatic cleanup
- Build chunks are split to avoid loading unnecessary dependencies (e.g., recharts only for analytics)
- API requests are throttled per user/IP to prevent abuse

## Common Issues

**Health check endpoints:** `GET /health/` and `GET /health/db_counts` — use these for uptime monitoring and to verify the backend and database are reachable.

**MongoDB connection fails:** Verify `MONGO_URI` is correct and MongoDB is running. Local dev defaults to `mongodb://127.0.0.1:27017` (not localhost) to avoid IPv6 issues.

**Transformer models fail to load:** Check disk space and `LOCAL_MODEL_DEVICE` setting. Fallback mode will activate automatically.

**CORS errors on frontend:** Verify `ALLOWED_ORIGINS` includes the frontend URL exactly (scheme, domain, and port matter).

**Password reset emails not sent:** Configure `SMTP_HOST`, `SMTP_USERNAME`, `SMTP_PASSWORD`, and `SMTP_FROM_EMAIL`.

## Git and Release

Current version: `0.5.0` (in `frontend/package.json`, `backend/app/main.py`)

Release docs:
- `docs/launch_plan.md` - Beta/production readiness plan
- `docs/release_runbook_checklist.md` - Release checklist
- `docs/ship_checklist.md` - Feature parity and completeness tracker

## Additional Resources

- [backend/README.md](backend/README.md) - Backend-specific setup and media storage details
- [frontend/README.md](frontend/README.md) - Frontend scripts and deployment
- [docs/observability.md](docs/observability.md) - Request logging and monitoring
- [docs/skillbridge_erd.md](docs/skillbridge_erd.md) - Database schema diagrams
