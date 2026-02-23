from __future__ import annotations
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


class ConfirmedSkill(BaseModel):
    skill_id: str
    skill_name: str
    proficiency: int = Field(default=0, ge=0, le=5)


class RejectedSkill(BaseModel):
    skill_id: str
    skill_name: str


class EditedSkill(BaseModel):
    from_text: str
    to_skill_id: str


class SkillConfirmationIn(BaseModel):
    user_id: str = Field(default="student1")
    confirmed: List[ConfirmedSkill] = []
    rejected: List[RejectedSkill] = []
    edited: List[EditedSkill] = []


class SkillConfirmationOut(BaseModel):
    snapshot_id: str
    user_id: str
    confirmed: List[ConfirmedSkill] = []
    rejected: List[RejectedSkill] = []
    edited: List[EditedSkill] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None