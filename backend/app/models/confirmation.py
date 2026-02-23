from __future__ import annotations
from pydantic import BaseModel, Field
from typing import List
from datetime import datetime


class ConfirmedSkillEntry(BaseModel):
    skill_id: str = Field(..., min_length=1)


class ConfirmationIn(BaseModel):
    user_id: str = Field(..., min_length=1)
    resume_snapshot_id: str = Field(..., min_length=1)
    confirmed: List[ConfirmedSkillEntry] = Field(default_factory=list)


class ConfirmationOut(BaseModel):
    id: str
    user_id: str
    resume_snapshot_id: str
    confirmed: List[ConfirmedSkillEntry]
    created_at: datetime
