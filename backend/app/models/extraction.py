from __future__ import annotations
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


class ExtractedSkill(BaseModel):
    skill_id: str
    skill_name: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_snippet: str = ""


class SkillExtractionOut(BaseModel):
    snapshot_id: str
    extracted: List[ExtractedSkill]
    created_at: datetime

