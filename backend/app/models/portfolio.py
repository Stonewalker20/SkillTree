from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field
from typing import Literal


PortfolioItemType = Literal[
    "project",
    "paper",
    "work",
    "cert",
    "award",
    "activity",
    "other",
]


class PortfolioItemIn(BaseModel):
    user_id: str = Field(..., description="Owner user id")
    type: PortfolioItemType = Field(..., description="Portfolio item category")
    title: str = Field(..., min_length=1)
    org: str | None = None
    date_start: str | None = Field(default=None, description="YYYY-MM or YYYY-MM-DD (string to keep simple)")
    date_end: str | None = Field(default=None, description="YYYY-MM or YYYY-MM-DD, or 'present'")
    summary: str | None = Field(default=None, description="Short description")
    bullets: list[str] = Field(default_factory=list, description="Achievement bullets")
    links: list[str] = Field(default_factory=list, description="URLs or identifiers")
    skill_ids: list[str] = Field(default_factory=list, description="Normalized skill ids (string ObjectIds)")
    tags: list[str] = Field(default_factory=list)
    visibility: Literal["public", "private"] = "private"
    priority: int = Field(default=0, description="Higher = more likely to be selected")


class PortfolioItemPatch(BaseModel):
    type: PortfolioItemType | None = None
    title: str | None = None
    org: str | None = None
    date_start: str | None = None
    date_end: str | None = None
    summary: str | None = None
    bullets: list[str] | None = None
    links: list[str] | None = None
    skill_ids: list[str] | None = None
    tags: list[str] | None = None
    visibility: Literal["public", "private"] | None = None
    priority: int | None = None


class PortfolioItemOut(PortfolioItemIn):
    id: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
