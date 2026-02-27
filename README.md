# SkillBridge

### Career Intelligence & Resume Optimization Platform

---

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-Async%20Backend-009688.svg)
![MongoDB](https://img.shields.io/badge/Database-MongoDB-47A248.svg)
![React](https://img.shields.io/badge/Frontend-React-61DAFB.svg)
![Docker](https://img.shields.io/badge/Containerized-Docker-2496ED.svg)
![Architecture](https://img.shields.io/badge/Architecture-Modular%20System-informational.svg)
![Status](https://img.shields.io/badge/Status-Active%20Development-success.svg)
![License](https://img.shields.io/badge/License-MIT-black.svg)

---

**SkillBridge** is a containerized, full-stack career intelligence system that converts unstructured resumes into structured, analyzable skill intelligence.

The platform:

* Extracts and normalizes skills
* Quantifies job alignment
* Identifies measurable skill gaps
* Generates resume tailoring guidance
* Maps skills to supporting portfolio evidence

The system is designed as a modular architecture with database-backed workflows and Docker-based deployment for reproducibility.

---

# Why This Project Is Engineering-Grade

SkillBridge is:

* Fully containerized using Docker
* Backend–frontend separated
* Database-driven (MongoDB)
* Built with asynchronous APIs
* Architected with subsystem isolation
* Designed for scalable deployment

It is structured as a production-style service rather than a prototype script.

---

# System Architecture

SkillBridge is composed of six modular subsystems:

1. Resume Ingestion & Snapshot Engine
2. Skill Confirmation & Normalization
3. Job Role Library & Weighted Modeling
4. Match & Gap Analytics
5. Tailor Engine (Resume Optimization)
6. Portfolio Intelligence & Evidence Mapping

Each subsystem interacts with MongoDB through structured models and version-controlled data flows.

---

# Containerized Deployment

SkillBridge runs in Docker containers for consistent development and deployment environments.

## Services

* `backend` — FastAPI service
* `frontend` — React + Vite client
* `mongo` — MongoDB database

## Example Docker Compose Architecture

```
Client (Browser)
        ↓
Frontend Container (React + Vite)
        ↓
Backend Container (FastAPI)
        ↓
MongoDB Container
```

## Benefits of Containerization

* Environment reproducibility
* Isolated dependency management
* Simplified onboarding
* Production-ready deployment path
* Scalable service orchestration

---

# Running the System

## Option 1 — Docker (Recommended)

```bash
docker compose up --build
```

Backend:

```
http://localhost:8000
```

Frontend:

```
http://localhost:3000
```

MongoDB runs as an internal service.

---

## Option 2 — Local Development

Backend:

```bash
uvicorn app.main:app --reload
```

Frontend:

```bash
npm run dev
```

---

# Data Architecture

Core MongoDB collections:

* `users`
* `resume_snapshots`
* `skills`
* `confirmed_skills`
* `job_roles`
* `role_skill_weights`
* `match_results`
* `tailor_sessions`
* `portfolio_projects`

The schema supports:

* Resume versioning
* Skill normalization
* Weighted scoring
* Tailoring history tracking
* Longitudinal portfolio evolution

---

# End-to-End Workflow

1. Resume upload
2. Skill extraction
3. Skill confirmation
4. Role selection
5. Match score computation
6. Tailoring recommendation generation
7. Portfolio evidence linkage

The output is a structured alignment and optimization plan.

---

# Technology Stack

### Backend

* Python
* FastAPI
* Async MongoDB
* Pydantic validation

### Frontend

* React
* Vite
* REST integration

### Infrastructure

* Docker
* Docker Compose
* Modular service architecture

---

# Current Status

* Resume ingestion API operational
* Skill confirmation workflow active
* Role modeling implemented
* Match scoring integrated
* Tailor engine functional
* Portfolio subsystem integrated
* Docker-based deployment configured

---

# Roadmap

* Semantic similarity scoring
* Role clustering models
* Analytics dashboards
* Automated resume rewriting
* Cloud deployment configuration

---

# Repository Structure

```
backend/
  app/
    routers/
    models/
    core/
    utils/
  main.py
  Dockerfile

frontend/
  src/
  Dockerfile

docker-compose.yml
```

---

# Contributors

**Cordell Stonecipher**
Machine Learning Engineer
System Architecture · Backend Engineering · Data Modeling · Analytics Design · Containerization

**Spencer Roeren**
Frontend Engineering Support · UI Integration
