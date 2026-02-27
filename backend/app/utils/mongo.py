from __future__ import annotations
from bson import ObjectId

def oid_str(oid: ObjectId) -> str:
    return str(oid)

def to_object_id(id_str: str) -> ObjectId:
    return ObjectId(id_str)

