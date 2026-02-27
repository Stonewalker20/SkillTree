from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional, List
from pydantic import BaseModel, Field

RelationType = Literal["related_to", "parent_of", "child_of", "similar_to"]

class SkillAliasesUpdate(BaseModel):
    aliases: List[str] = Field(default_factory=list)

class SkillRelationIn(BaseModel):
    from_skill_id: str = Field(..., min_length=1)
    to_skill_id: str = Field(..., min_length=1)
    relation_type: RelationType = "related_to"

class SkillRelationOut(BaseModel):
    id: str
    from_skill_id: str
    to_skill_id: str
    relation_type: RelationType
    created_at: Optional[datetime] = None
