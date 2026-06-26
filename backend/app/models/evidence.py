"""Pydantic schemas for evidence creation, patching, and serialized evidence records."""

from __future__ import annotations

from pydantic import BaseModel, Field
from typing import List, Literal, Optional
from datetime import datetime

EvidenceType = Literal["resume", "paper", "job_posting", "project", "cert", "other"]
EvidenceOrigin = Literal["user", "system"]

class EvidenceIn(BaseModel):
    # Keep user_email for backward compatibility; allow user_id for user-specific dashboards.
    user_email: Optional[str] = Field(default=None, min_length=3)
    user_id: Optional[str] = Field(default=None, min_length=1)

    type: EvidenceType
    title: str = Field(..., min_length=1)
    source: str = Field(..., min_length=1)  # URL, filename, citation, etc.
    # May be empty when the evidence is a link: the create handler derives the excerpt from
    # the fetched page and rejects the request (400) only if nothing usable can be produced.
    text_excerpt: str = ""

    # NEW: associations
    skill_ids: List[str] = Field(default_factory=list)
    # Skills the extractor derived from the evidence text vs. skills the user attached by
    # hand are tracked separately so manual choices survive a re-extraction pass.
    extracted_skill_ids: List[str] = Field(default_factory=list)
    manual_skill_ids: List[str] = Field(default_factory=list)
    manual_skill_names: List[str] = Field(default_factory=list)
    project_id: Optional[str] = None

    # misc metadata
    tags: List[str] = Field(default_factory=list)
    origin: EvidenceOrigin = "user"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class EvidenceOut(BaseModel):
    id: str
    user_email: Optional[str] = None
    user_id: Optional[str] = None
    type: EvidenceType
    title: str
    source: str
    text_excerpt: str
    skill_ids: List[str] = Field(default_factory=list)
    extracted_skill_ids: List[str] = Field(default_factory=list)
    manual_skill_ids: List[str] = Field(default_factory=list)
    manual_skill_names: List[str] = Field(default_factory=list)
    project_id: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    origin: EvidenceOrigin = "user"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class EvidencePatch(BaseModel):
    type: Optional[EvidenceType] = None
    title: Optional[str] = Field(default=None, min_length=1)
    source: Optional[str] = Field(default=None, min_length=1)
    text_excerpt: Optional[str] = Field(default=None, min_length=1)
    skill_ids: Optional[List[str]] = None
    extracted_skill_ids: Optional[List[str]] = None
    manual_skill_ids: Optional[List[str]] = None
    manual_skill_names: Optional[List[str]] = None
    project_id: Optional[str] = None
    tags: Optional[List[str]] = None
