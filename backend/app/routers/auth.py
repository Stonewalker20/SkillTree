from __future__ import annotations

from fastapi import APIRouter, HTTPException, Depends, Header
from datetime import datetime, timezone, timedelta
from bson import ObjectId

from app.core.db import get_db
from app.core.auth import hash_password, verify_password, create_session, require_user, now_utc
from app.models.auth import RegisterIn, LoginIn, AuthOut, UserOut, UserPatch
from app.utils.mongo import oid_str

router = APIRouter(prefix="/auth", tags=["auth"])

SESSION_HOURS = 24

def now_utc():
    return datetime.now(timezone.utc)

async def create_session(user_oid: ObjectId) -> str:
    db = get_db()
    token = secrets.token_hex(32)
    await db["sessions"].insert_one({
        "token": token,
        "user_id": user_oid,  # IMPORTANT: store as ObjectId
        "created_at": now_utc(),
        "expires_at": now_utc() + timedelta(hours=SESSION_HOURS),
    })
    return token

async def require_user(authorization: str = Header(default="")):
    """
    Expects: Authorization: Bearer <token>
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")

    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")

    db = get_db()
    sess = await db["sessions"].find_one({"token": token})
    if not sess:
        raise HTTPException(status_code=401, detail="Invalid token")

    if sess.get("expires_at") and sess["expires_at"] < now_utc():
        await db["sessions"].delete_one({"_id": sess["_id"]})
        raise HTTPException(status_code=401, detail="Token expired")

    user = await db["users"].find_one({"_id": sess["user_id"]})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return user

@router.post("/register", response_model=AuthOut)
async def register(payload: RegisterIn):
    db = get_db()
    existing = await db["users"].find_one({"email": payload.email.lower()})
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    pw = hash_password(payload.password)
    doc = {
        "email": payload.email.lower(),
        "username": payload.username,
        "role": "user",
        "password_salt": pw["salt"],
        "password_hash": pw["hash"],
        "created_at": now_utc(),
        "updated_at": now_utc(),
    }
    res = await db["users"].insert_one(doc)
    token = await create_session(res.inserted_id)
    user = {"id": oid_str(res.inserted_id), "email": doc["email"], "username": doc["username"], "role": doc["role"]}
    return {"token": token, "user": user}

@router.post("/login", response_model=AuthOut)
async def login(payload: LoginIn):
    db = get_db()
    user = await db["users"].find_one({"email": payload.email.lower()})
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not verify_password(payload.password, user.get("password_salt",""), user.get("password_hash","")):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = await create_session(user["_id"])
    out_user = {"id": oid_str(user["_id"]), "email": user["email"], "username": user.get("username",""), "role": user.get("role","user")}
    return {"token": token, "user": out_user}

@router.get("/me", response_model=UserOut)
async def me(user = Depends(require_user)):
    return {"id": oid_str(user["_id"]), "email": user["email"], "username": user.get("username",""), "role": user.get("role","user")}

@router.patch("/me", response_model=UserOut)
async def patch_me(payload: UserPatch, user = Depends(require_user)):
    db = get_db()
    updates = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided to update")

    if "email" in updates:
        updates["email"] = updates["email"].lower()
        # unique check
        existing = await db["users"].find_one({"email": updates["email"], "_id": {"$ne": user["_id"]}})
        if existing:
            raise HTTPException(status_code=409, detail="Email already in use")

    updates["updated_at"] = now_utc()
    await db["users"].update_one({"_id": user["_id"]}, {"$set": updates})
    doc = await db["users"].find_one({"_id": user["_id"]})
    return {"id": oid_str(doc["_id"]), "email": doc["email"], "username": doc.get("username",""), "role": doc.get("role","user")}

@router.post("/logout")
async def logout(user = Depends(require_user)):
    # delete all sessions for this user for simplicity
    db = get_db()
    await db["sessions"].delete_many({"user_id": user["_id"]})
    return {"ok": True}

@router.delete("/me")
async def delete_me(user=Depends(require_user)):
    db = get_db()
    uid = user["_id"]

    # 1) remove sessions first (log them out everywhere)
    await db["sessions"].delete_many({"user_id": uid})

    # 2) optional: remove user-owned content (adjust collections to your schema)
    await db["skills"].delete_many({"user_id": str(uid)})            # if skills store user_id as string
    await db["evidence"].delete_many({"user_id": str(uid)})          # if evidence store user_id as string
    await db["portfolio_items"].delete_many({"user_id": str(uid)})   # if portfolio_items store user_id as string
    await db["job_ingests"].delete_many({"user_id": str(uid)})       # your tailor ingest uses user_id string
    await db["tailored_resumes"].delete_many({"user_id": str(uid)})  # your tailor preview stores user_id string
    await db["projects"].delete_many({"user_id": str(uid)})          # if used

    # 3) delete the user itself
    res = await db["users"].delete_one({"_id": uid})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="User not found")

    return {"ok": True}