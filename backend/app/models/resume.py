from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional
from datetime import datetime


class ResumeSnapshotIn(BaseModel):
    user_id: str = Field(default="student1")
    text: str = Field(min_length=1)


class ResumeSnapshotOut(BaseModel):
    snapshot_id: str
    preview: str


class ResumeSnapshotDB(BaseModel):
    user_id: str
    source_type: str  # "paste" | "pdf" | "kaggle"
    raw_text: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    image_ref: str
    created_at: datetime

