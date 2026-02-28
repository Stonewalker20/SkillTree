from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


class JobIngestIn(BaseModel):
    user_id: str
    title: str | None = None
    company: str | None = None
    location: str | None = None
    text: str = Field(..., min_length=50, description="Full job posting text")


class ExtractedSkill(BaseModel):
    skill_id: str
    skill_name: str
    matched_on: str = Field(..., description="name|alias")
    count: int = 1


class JobIngestOut(BaseModel):
    id: str
    user_id: str
    title: str | None = None
    company: str | None = None
    location: str | None = None
    text_preview: str
    extracted_skills: list[ExtractedSkill]
    keywords: list[str]
    created_at: datetime | None = None


class TailorPreviewIn(BaseModel):
    user_id: str
    job_id: str | None = Field(default=None, description="Job ingest id")
    job_text: str | None = Field(default=None, description="Optional job text if job_id not provided")
    template: str = Field(default="ats_v1", description="Template name")
    max_items: int = Field(default=4, ge=1, le=10)
    max_bullets_per_item: int = Field(default=4, ge=1, le=10)


class ResumeSection(BaseModel):
    title: str
    lines: list[str]


class TailoredResumeOut(BaseModel):
    id: str
    user_id: str
    job_id: str | None = None
    template: str
    selected_skill_ids: list[str]
    selected_item_ids: list[str]
    sections: list[ResumeSection]
    plain_text: str
    created_at: datetime | None = None
