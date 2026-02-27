# SkillBridge

**AI-Powered Resume Intelligence & Career Alignment Platform**

---

## Badges

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-Async%20API%20Framework-009688.svg)
![MongoDB](https://img.shields.io/badge/Database-MongoDB-47A248.svg)
![React](https://img.shields.io/badge/Frontend-React-61DAFB.svg)
![Vite](https://img.shields.io/badge/Bundler-Vite-646CFF.svg)
![License](https://img.shields.io/badge/License-MIT-black.svg)
![Status](https://img.shields.io/badge/Status-Active%20Development-success.svg)
![Architecture](https://img.shields.io/badge/Architecture-Modular%20Monolith-informational.svg)

---

## Overview

**SkillBridge** is a full-stack web platform that transforms unstructured resumes into structured, analyzable skill intelligence.

The system ingests resume data, extracts and normalizes skills, maps them to standardized role models, and generates explainable job-alignment analytics.

SkillBridge is built as a modular, database-driven architecture designed for scalability, clarity, and production readiness.

---

## Problem

Hiring workflows rely on:

* Unstructured resumes
* Inconsistent skill terminology
* Manual comparison of job requirements
* Limited visibility into skill gaps

SkillBridge converts free-form career data into structured intelligence and produces measurable alignment insights.

---

## User Roles

### Candidate

* Upload resume
* Confirm extracted skills
* Analyze job alignment
* Identify skill gaps
* Map projects to skills

### Administrator

* Manage skill taxonomy
* Define and weight job roles
* Maintain role versions
* Monitor analytics integrity

Each role interacts with a distinct feature set and system view.

---

## System Architecture

SkillBridge is organized into five production-level subsystems.

---

### 1. Resume Ingestion & Snapshot Management

* Upload resume
* Parse and extract content
* Create structured snapshot
* Version resume history
* Compare snapshots

---

### 2. Skill Extraction & Confirmation Engine

* Display detected skills
* Confirm / reject skills
* Normalize aliases
* Add missing skills
* Categorize competencies

---

### 3. Job Role Library & Weight Modeling

* Create job roles
* Define required skills
* Assign weighted importance
* Version role definitions
* Archive deprecated roles

---

### 4. Job Match & Gap Analytics

* Compute alignment score
* Identify missing skills
* Rank compatible roles
* Generate explainable breakdown
* Store match history

---

### 5. Portfolio Mapping & Evidence Tracking

* Create project entries
* Map skills to artifacts
* Assign proficiency level
* Track growth over time
* Generate skill-evidence reports

---

## Database Architecture

Core MongoDB collections:

* `users`
* `resume_snapshots`
* `skills`
* `confirmed_skills`
* `job_roles`
* `role_skill_weights`
* `match_results`
* `portfolio_projects`

The design supports:

* Snapshot versioning
* Skill normalization
* Weighted scoring models
* Historical analytics tracking

---

## Technology Stack

### Backend

* Python
* FastAPI
* MongoDB
* Pydantic
* Async I/O

### Frontend

* React
* Vite
* REST API integration
* Responsive UI

### DevOps

* Git
* Modular router architecture
* Container-ready backend structure

---

## Competitive Positioning

SkillBridge is not a basic resume parser. It is a structured intelligence system featuring:

* Weighted role modeling
* Skill confirmation workflows
* Resume version tracking
* Explainable alignment scoring
* Portfolio evidence mapping

---

## Current Development Status

* Resume ingestion API operational
* MongoDB schema implemented
* Skill confirmation flow active
* Role modeling subsystem deployed
* Weighted match scoring integrated
* Frontend integration in progress

---

## Roadmap

* Semantic skill expansion via NLP
* Role similarity clustering
* Visual analytics dashboards
* API documentation portal
* Production deployment pipeline

---

## Repository Structure

```
backend/
  app/
    routers/
    models/
    core/
    utils/
  main.py

frontend/
  src/
    components/
    pages/
```

---

## Contributors

**Cordell Stonecipher**
Machine Learning Engineer
System Architecture, Backend Development, Data Modeling, Analytics Engine

**Spencer Roeren**
Frontend Development & UI Integration Support
