"""Authentication primitives for password hashing, session creation, token validation, and user dependency injection."""

from __future__ import annotations

from fastapi import HTTPException, Header, Depends
from typing import Optional, Dict, Any
from datetime import datetime, timezone, timedelta
import hashlib
import secrets

from app.core.db import get_db
from bson import ObjectId

TOKEN_TTL_DAYS = 30
ADMIN_ROLES = {"owner", "admin", "team"}
ROLE_PRIORITY = {
    "user": 0,
    "team": 1,
    "admin": 2,
    "owner": 3,
}
ROLE_HIERARCHY = ("user", "team", "admin", "owner")
ROLE_RANKS = {role: index for index, role in enumerate(ROLE_HIERARCHY)}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def as_utc_aware(dt: datetime) -> datetime:
    """
    Mongo can return naive datetimes (no tzinfo). In this codebase, any naive
    datetime is interpreted as UTC. Normalize to tz-aware UTC for safe comparisons.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def normalize_exp(exp: Any) -> Optional[datetime]:
    """
    Normalize an expiry value into a tz-aware UTC datetime.
    Supports:
      - datetime (naive or aware)
      - ISO-8601 string (with 'Z' or explicit offset)
    Returns None for unsupported/absent values.
    """
    if exp is None:
        return None

    if isinstance(exp, datetime):
        return as_utc_aware(exp)

    if isinstance(exp, str):
        try:
            # Accept "...Z" and "+00:00" style offsets
            parsed = datetime.fromisoformat(exp.replace("Z", "+00:00"))
            return as_utc_aware(parsed)
        except Exception:
            return None

    return None


# PBKDF2-HMAC-SHA256 iteration count for newly created/changed passwords. Raised from the
# original 120_000 per OWASP's current guidance for this algorithm. LEGACY_PBKDF2_ITERATIONS
# is kept so verify_password() can still validate hashes that were computed before this
# change, for accounts whose stored hash predates the "password_iterations" field below.
PBKDF2_ITERATIONS = 600_000
LEGACY_PBKDF2_ITERATIONS = 120_000


def _pbkdf2(password: str, salt_hex: str, iterations: int = PBKDF2_ITERATIONS) -> str:
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        iterations,
    )
    return dk.hex()


def hash_password(password: str) -> Dict[str, Any]:
    salt = secrets.token_hex(16)
    return {"salt": salt, "hash": _pbkdf2(password, salt), "iterations": PBKDF2_ITERATIONS}


def verify_password(password: str, salt: str, pw_hash: str, iterations: int = LEGACY_PBKDF2_ITERATIONS) -> bool:
    return secrets.compare_digest(_pbkdf2(password, salt, iterations), pw_hash)


def new_token() -> str:
    # URL-safe token
    return secrets.token_urlsafe(32)


def has_subscription_access(user: Dict[str, Any]) -> bool:
    role = normalize_role(user.get("role"))
    if role in ADMIN_ROLES:
        return True
    status = str(user.get("subscription_status") or "inactive").strip().lower()
    return status == "active"


def normalize_role(role: Any) -> str:
    value = str(role or "user").strip().lower()
    return value if value in ROLE_PRIORITY else "user"


def role_priority(role: Any) -> int:
    return ROLE_PRIORITY.get(normalize_role(role), 0)


def can_manage_user_role(actor_role: Any, target_role: Any, next_role: Any) -> bool:
    actor_priority = role_priority(actor_role)
    target_priority = role_priority(target_role)
    next_priority = role_priority(next_role)

    if actor_priority <= 0:
        return False
    if actor_priority <= target_priority:
        return False
    if actor_priority <= next_priority:
        return False
    return True


def can_deactivate_user(actor_role: Any, target_role: Any) -> bool:
    actor_priority = role_priority(actor_role)
    target_priority = role_priority(target_role)
    if actor_priority <= 0:
        return False
    return actor_priority > target_priority


def normalized_role(value: Any) -> str:
    role = str(value or "user").strip().lower()
    return role or "user"


def role_rank(value: Any) -> int:
    return ROLE_RANKS.get(normalized_role(value), -1)


def can_manage_role(actor_role: Any, target_role: Any) -> bool:
    return role_rank(actor_role) >= role_rank(target_role)


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

    created_at = normalize_exp(sess.get("created_at"))
    exp = normalize_exp(sess.get("expires_at"))
    if not created_at or not exp:
        await db["sessions"].delete_one({"_id": sess["_id"]})
        raise HTTPException(status_code=401, detail="Invalid token")
    if exp < created_at or exp > created_at + timedelta(days=TOKEN_TTL_DAYS):
        await db["sessions"].delete_one({"_id": sess["_id"]})
        raise HTTPException(status_code=401, detail="Invalid token")
    if exp <= now_utc():
        await db["sessions"].delete_one({"_id": sess["_id"]})
        raise HTTPException(status_code=401, detail="Token expired")

    user = await db["users"].find_one({"_id": sess["user_id"]})
    if not user:
        await db["sessions"].delete_one({"_id": sess["_id"]})
        raise HTTPException(status_code=401, detail="Invalid token")

    if user.get("is_active", True) is False:
        await db["sessions"].delete_many({"user_id": user["_id"]})
        raise HTTPException(status_code=401, detail="Account deactivated")

    return user


async def require_active_subscription(user=Depends(require_user)) -> Dict[str, Any]:
    if not has_subscription_access(user):
        raise HTTPException(status_code=402, detail="Subscription required")
    return user


async def require_admin_user(user=Depends(require_user)) -> Dict[str, Any]:
    role = normalize_role(user.get("role"))
    if role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


async def create_session(user_id: ObjectId) -> str:
    db = get_db()
    token = new_token()
    now = now_utc()
    doc = {
        "user_id": user_id,
        "token": token,
        "created_at": now,
        "expires_at": now + timedelta(days=TOKEN_TTL_DAYS),
    }
    await db["sessions"].insert_one(doc)
    return token
