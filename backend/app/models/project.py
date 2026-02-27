from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field

class ProjectIn(BaseModel):
    user_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    description: str = Field(default="")
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    tags: List[str] = Field(default_factory=list)

class ProjectOut(BaseModel):
    id: str
    user_id: str
    title: str
    description: str = ""
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    tags: List[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class ProjectSkillLinkIn(BaseModel):
    skill_id: str = Field(..., min_length=1)

class ProjectSkillLinkOut(BaseModel):
    id: str
    project_id: str
    skill_id: str
    created_at: Optional[datetime] = None
