from __future__ import annotations

from pydantic import BaseModel, Field
from typing import List, Literal, Optional
from datetime import datetime

EvidenceType = Literal["resume", "paper", "job_posting", "project", "cert", "other"]

class EvidenceIn(BaseModel):
    # Keep user_email for backward compatibility; allow user_id for user-specific dashboards.
    user_email: Optional[str] = Field(default=None, min_length=3)
    user_id: Optional[str] = Field(default=None, min_length=1)

    type: EvidenceType
    title: str = Field(..., min_length=1)
    source: str = Field(..., min_length=1)  # URL, filename, citation, etc.
    text_excerpt: str = Field(..., min_length=1)

    # NEW: associations
    skill_ids: List[str] = Field(default_factory=list)
    project_id: Optional[str] = None

    # misc metadata
    tags: List[str] = Field(default_factory=list)
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
    project_id: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
