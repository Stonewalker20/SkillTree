from __future__ import annotations

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field

class RoleIn(BaseModel):
    name: str = Field(..., min_length=1)
    description: str = Field(default="")

class RoleOut(BaseModel):
    id: str
    name: str
    description: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class RoleTagIn(BaseModel):
    role_id: str = Field(..., min_length=1)

class RoleWeightsOut(BaseModel):
    role_id: str
    computed_at: datetime
    weights: List[dict]  # [{skill_id, skill_name, weight}]
