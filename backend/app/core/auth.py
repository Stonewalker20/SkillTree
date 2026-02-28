from __future__ import annotations

from fastapi import HTTPException, Header
from typing import Optional, Dict, Any
from datetime import datetime, timezone, timedelta
import hashlib
import secrets

from app.core.db import get_db
from bson import ObjectId

TOKEN_TTL_DAYS = 30

def now_utc():
    return datetime.now(timezone.utc)

def _pbkdf2(password: str, salt_hex: str, iterations: int = 120_000) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), iterations)
    return dk.hex()

def hash_password(password: str) -> Dict[str, Any]:
    salt = secrets.token_hex(16)
    return {"salt": salt, "hash": _pbkdf2(password, salt)}

def verify_password(password: str, salt: str, pw_hash: str) -> bool:
    return secrets.compare_digest(_pbkdf2(password, salt), pw_hash)

def new_token() -> str:
    # URL-safe token
    return secrets.token_urlsafe(32)

async def require_user(authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    """Return user doc for Bearer token or raise 401."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    db = get_db()
    sess = await db["sessions"].find_one({"token": token})
    if not sess:
        raise HTTPException(status_code=401, detail="Invalid token")

    exp = sess.get("expires_at")
    if exp and exp < now_utc():
        # best-effort cleanup
        await db["sessions"].delete_one({"_id": sess["_id"]})
        raise HTTPException(status_code=401, detail="Token expired")

    user = await db["users"].find_one({"_id": sess["user_id"]})
    if not user:
        await db["sessions"].delete_one({"_id": sess["_id"]})
        raise HTTPException(status_code=401, detail="Invalid token")

    return user

async def create_session(user_id: ObjectId) -> str:
    db = get_db()
    token = new_token()
    doc = {
        "user_id": user_id,
        "token": token,
        "created_at": now_utc(),
        "expires_at": now_utc() + timedelta(days=TOKEN_TTL_DAYS),
    }
    await db["sessions"].insert_one(doc)
    return token
