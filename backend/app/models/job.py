from __future__ import annotations

from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from datetime import datetime

ModerationStatus = Literal["pending", "approved", "rejected"]

class JobIn(BaseModel):
    title: str = Field(..., min_length=1)
    company: str = Field(..., min_length=1)
    location: str = Field(..., min_length=1)
    source: str = Field(..., min_length=1)
    description_excerpt: str = Field(..., min_length=1)

    # Existing field: free-text list
    required_skills: List[str] = Field(default_factory=list)

    # NEW: normalized linkage (optional)
    required_skill_ids: List[str] = Field(default_factory=list)

    # NEW: role tags
    role_ids: List[str] = Field(default_factory=list)

    # Submission metadata (optional)
    submitted_by_user_id: Optional[str] = None

class JobOut(BaseModel):
    id: str
    title: str
    company: str
    location: str
    source: str
    description_excerpt: str
    required_skills: List[str] = Field(default_factory=list)
    required_skill_ids: List[str] = Field(default_factory=list)
    role_ids: List[str] = Field(default_factory=list)
    moderation_status: ModerationStatus = "approved"
    moderation_reason: Optional[str] = None
    submitted_by_user_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class JobModerationIn(BaseModel):
    moderation_status: ModerationStatus
    moderation_reason: Optional[str] = None

class JobRoleTagIn(BaseModel):
    role_id: str = Field(..., min_length=1)
