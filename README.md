Below is a **polished, public-facing README** suitable for GitHub. It is concise, professional, and written to read well to instructors, recruiters, and external reviewers. You can copy this verbatim.

---

# SkillTree

**SkillTree** is a web application designed to organize, validate, and match technical skills using real supporting evidence such as resumes, research papers, projects, and job listings. Instead of relying on shallow keyword matching, SkillTree models skills as structured entities backed by concrete artifacts, enabling more transparent and explainable skill–job alignment.

This repository contains the **backend services, database schema, and development data** that power the application.

---

## Motivation

Traditional skill-matching systems treat resumes and job postings as unstructured text, often leading to poor matches and opaque scoring. SkillTree addresses this by:

* Normalizing skills into a shared taxonomy
* Linking each skill to verifiable evidence
* Storing job requirements in a structured, queryable form
* Producing interpretable match results that highlight strengths and gaps

The result is a system that is easier to audit, extend, and reason about.

---

## Technology Stack

**Backend**

* FastAPI (Python)
* Async MongoDB access via Motor

**Database**

* MongoDB (NoSQL)
* Docker Compose for local development

**Tooling**

* Docker
* Python 3.10+
* JSON-based seed datasets

---

## System Overview

At a high level, SkillTree consists of:

* A FastAPI backend exposing REST endpoints
* A MongoDB database storing skills, evidence, and matches
* A frontend (developed separately) that consumes the API

This repository focuses on the **backend and data layer**.

---

## Database Design

Core collections:

* **users** – application users (students, admins)
* **skills** – canonical skill definitions and aliases
* **evidence** – resumes, papers, projects, certifications
* **jobs** – job listings with required skills
* **matches** – computed user–job alignment results

All collections include realistic sample data to support development and testing.

---

## Repository Structure

```
skilltree/
  backend/        # FastAPI application
  data/seed/      # Sample MongoDB seed data
  infra/          # Docker Compose configuration
  docs/           # Technical documentation
```

---

## Running the Project Locally

### 1. Start MongoDB

```bash
cd infra
docker compose up -d
```

### 2. Install backend dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 3. Seed the database

```bash
python scripts/seed_mongo.py
```

### 4. Run the API server

```bash
uvicorn app.main:app --reload
```

### 5. Health check

Navigate to:

```
http://localhost:8000/health
```

---

## Development Status

This project is under active development.

Current focus:

* Backend infrastructure
* Database modeling
* Data ingestion and normalization
* API support for frontend development

Advanced matching logic, authentication, and deployment are planned for later phases.

---

## Team

* **Backend & Database:** Cordell Stonecipher
* **Frontend/UI:** Spencer
* **Data Collection & Curation:** Justin Elia, Jennifer Gonzalelz

---

## License

MIT License

---
