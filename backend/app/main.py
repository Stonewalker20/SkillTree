from fastapi import FastAPI
from app.core.db import connect_to_mongo, close_mongo_connection
from app.routers.health import router as health_router
from app.routers.skills import router as skills_router
from app.routers.confirmations import router as confirmations_router
from app.routers.jobs import router as jobs_router
from app.routers.evidence import router as evidence_router
from app.routers.resumes import router as resumes_router
from app.routers.projects import router as projects_router
from app.routers.dashboard import router as dashboard_router
from app.routers.roles import router as roles_router
from app.routers.taxonomy import router as taxonomy_router
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="SkillBridge API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=False,  # set True ONLY if you use cookie-based auth
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def on_startup():
    await connect_to_mongo()

@app.on_event("shutdown")
async def on_shutdown():
    await close_mongo_connection()

app.include_router(health_router, prefix="/health", tags=["health"])
app.include_router(skills_router, prefix="/skills", tags=["skills"])
app.include_router(confirmations_router, prefix="/skills/confirmations", tags=["confirmations"])
app.include_router(jobs_router, prefix="/jobs", tags=["jobs"])
app.include_router(evidence_router, prefix="/evidence", tags=["evidence"])
app.include_router(resumes_router, prefix="/ingest/resume", tags=["resume"])
app.include_router(projects_router, prefix="/projects", tags=["projects"])
app.include_router(dashboard_router, prefix="/dashboard", tags=["dashboard"])
app.include_router(roles_router, prefix="/roles", tags=["roles"])
app.include_router(taxonomy_router, prefix="/taxonomy", tags=["taxonomy"])
