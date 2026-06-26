"""Pydantic schemas for resume snapshot ingestion and resume listing responses."""

from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Any, Dict
from datetime import datetime


class ResumeSnapshotIn(BaseModel):
    user_id: str | None = Field(default=None)
    text: str = Field(min_length=1)


class ResumeSnapshotOut(BaseModel):
    snapshot_id: str
    preview: str


class ResumeSnapshotListEntryOut(BaseModel):
    snapshot_id: str
    source_type: str
    filename: str | None = None
    preview: str
    created_at: datetime | None = None


class ResumeSnapshotDB(BaseModel):
    user_id: str
    source_type: str  # "paste" | "pdf" | "kaggle"
    raw_text: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    image_ref: str
    created_at: datetime
