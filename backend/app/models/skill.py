from __future__ import annotations
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


class SkillIn(BaseModel):
    name: str = Field(..., min_length=1)
    category: str = Field(..., min_length=1)
    aliases: List[str] = Field(default_factory=list)
    proficiency: Optional[int] = None
    last_used_at: Optional[datetime] = None


class SkillOut(BaseModel):
    id: str
    name: str
    category: str
    aliases: List[str]
    proficiency: Optional[int] = None
    last_used_at: Optional[datetime] = None

class SkillUpdate(BaseModel):
    proficiency: Optional[int] = Field(default=None, ge=0, le=5)
    last_used_at: Optional[datetime] = None