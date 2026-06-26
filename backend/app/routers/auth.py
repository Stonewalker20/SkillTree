"""Authentication routes for account creation, login, profile updates, logout, and account deletion."""

from __future__ import annotations

from datetime import timedelta
import hashlib
import logging
import re
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Request
from pymongo.errors import DuplicateKeyError
import secrets

from app.core.db import get_db
from app.core.auth import (
    TOKEN_TTL_DAYS,
    LEGACY_PBKDF2_ITERATIONS,
    hash_password,
    verify_password,
    create_session,
    require_user,
    has_subscription_access,
    now_utc,
    normalize_exp,
)
from app.models.auth import (
    RegisterIn,
    LoginIn,
    AuthOut,
    UserOut,
    UserPatch,
    UserOnboardingOut,
    UserOnboardingPatchIn,
    PasswordChangeIn,
    PasswordResetRequestIn,
    PasswordResetConfirmIn,
    PasswordResetOut,
    SubscriptionActivateIn,
)
from app.utils.email_delivery import password_reset_email_enabled, send_password_reset_email
from app.utils.mongo import oid_str, unique_strings
from app.utils.media_storage import avatar_storage_key_from_user, get_avatar_storage_provider
from app.utils.file_validation import sniff_image_type, IMAGE_CONTENT_TYPES
from app.utils.security import AUTH_RATE_LIMITS, build_rate_limit_identifier, enforce_rate_limit
from app.core.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)
AVATAR_PRESETS = {
    "midnight",
    "sunset",
    "mint",
    "ember",
    "violet",
    "slate",
    "ocean",
    "sunrise",
    "forest",
    "rosewood",
    "cobalt",
    "aurora",
    "sandstone",
    "orchid",
}
ALLOWED_AVATAR_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
SUBSCRIPTION_DEFAULT_PLAN = "pro"
SUBSCRIPTION_DEFAULT_STATUS = "inactive"
SUBSCRIPTION_PLAN_KEYS = {"starter", "pro", "elite"}
PASSWORD_RESET_COLLECTION = "password_reset_tokens"


def serialize_onboarding_state(user: dict) -> tuple[UserOnboardingOut | None, bool]:
    raw = user.get("onboarding")
    if not isinstance(raw, dict):
        return None, True

    completed_steps = unique_strings(raw.get("completed_steps"))
    state = UserOnboardingOut(
        started_at=normalize_exp(raw.get("started_at")),
        last_step=str(raw.get("last_step") or "").strip() or None,
        completed_steps=completed_steps,
        completed_at=normalize_exp(raw.get("completed_at")),
        dismissed_at=normalize_exp(raw.get("dismissed_at")),
    )
    is_new_user = state.completed_at is None and state.dismissed_at is None
    return state, is_new_user


def serialize_user_out(user: dict) -> UserOut:
    subscription_status = str(user.get("subscription_status") or SUBSCRIPTION_DEFAULT_STATUS).strip().lower() or SUBSCRIPTION_DEFAULT_STATUS
    subscription_plan = str(user.get("subscription_plan") or "").strip() or None
    onboarding, is_new_user = serialize_onboarding_state(user)
    if has_subscription_access(user):
        subscription_status = "active"
        subscription_plan = subscription_plan or "admin"
    elif subscription_status == "active" and not subscription_plan:
        subscription_plan = SUBSCRIPTION_DEFAULT_PLAN
    return UserOut(
        id=oid_str(user["_id"]),
        email=user["email"],
        username=user["username"],
        role=user.get("role", "user"),
        avatar_url=str(user.get("avatar_url") or "").strip() or None,
        avatar_preset=str(user.get("avatar_preset") or "").strip() or None,
        subscription_status=subscription_status,
        subscription_plan=subscription_plan,
        subscription_started_at=user.get("subscription_started_at"),
        subscription_renewal_at=user.get("subscription_renewal_at"),
        billing_provider=str(user.get("billing_provider") or "").strip() or None,
        stripe_customer_id=str(user.get("stripe_customer_id") or "").strip() or None,
        stripe_subscription_id=str(user.get("stripe_subscription_id") or "").strip() or None,
        stripe_checkout_session_id=str(user.get("stripe_checkout_session_id") or "").strip() or None,
        help_unread_response_count=max(0, int(user.get("help_unread_response_count") or 0)),
        is_new_user=is_new_user,
        onboarding=onboarding,
    )


def _password_parts_for_user(user: dict) -> tuple[str | None, str | None, int]:
    password_salt = user.get("password_salt")
    password_hash = user.get("password_hash")
    password_iterations = user.get("password_iterations")
    if isinstance(password_hash, dict):
        password_salt = password_hash.get("salt")
        password_iterations = password_hash.get("iterations", password_iterations)
        password_hash = password_hash.get("hash")
    # Accounts created before the PBKDF2 iteration count was raised don't carry an explicit
    # password_iterations field; their hash was computed at the old default, so fall back to
    # that value rather than the current (higher) one.
    return password_salt, password_hash, int(password_iterations or LEGACY_PBKDF2_ITERATIONS)


async def _delete_avatar_if_present(user: dict):
    storage = get_avatar_storage_provider()
    try:
        await storage.delete_avatar(avatar_storage_key_from_user(user))
    except Exception:
        # Avatar cleanup is best-effort. A storage delete failure should not block
        # profile updates or account deletion when the new media has already been saved.
        pass


def is_user_active(user: dict) -> bool:
    return user.get("is_active", True) is not False


def _session_expiry_state(session: dict) -> str | None:
    created_at = normalize_exp(session.get("created_at"))
    expires_at = normalize_exp(session.get("expires_at"))
    if not created_at or not expires_at:
        return "invalid"
    if expires_at < created_at:
        return "invalid"
    if expires_at > created_at + timedelta(days=TOKEN_TTL_DAYS):
        return "invalid"
    if expires_at <= now_utc():
        return "expired"
    return None


def _hash_password_reset_token(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def _build_password_reset_url(token: str) -> str:
    base = settings.public_app_url.rstrip("/")
    return f"{base}/reset-password?token={token}"


async def _issue_password_reset_token(user: dict) -> str:
    db = get_db()
    issued_at = now_utc()
    raw_token = secrets.token_urlsafe(32)
    await db[PASSWORD_RESET_COLLECTION].delete_many({"user_id": user["_id"]})
    await db[PASSWORD_RESET_COLLECTION].insert_one(
        {
            "user_id": user["_id"],
            "token_hash": _hash_password_reset_token(raw_token),
            "created_at": issued_at,
            "expires_at": issued_at + timedelta(minutes=max(5, int(settings.password_reset_token_ttl_minutes or 60))),
            "used_at": None,
        }
    )
    return raw_token

@router.post("/register", response_model=AuthOut)
async def register(payload: RegisterIn, request: Request):
    db = get_db()
    await enforce_rate_limit(
        db,
        scope="auth.register",
        identifier=build_rate_limit_identifier(request, payload.email, payload.username),
        limit=AUTH_RATE_LIMITS["register"][0],
        window_seconds=AUTH_RATE_LIMITS["register"][1],
    )

    existing = await db["users"].find_one(
        {
            "$or": [
                {"email": payload.email},
                {"username": {"$regex": f"^{re.escape(payload.username)}$", "$options": "i"}},
            ]
        }
    )
    if existing:
        raise HTTPException(status_code=409, detail="User already exists")

    password_parts = hash_password(payload.password)

    doc = {
        "email": payload.email,
        "username": payload.username,
        "password_salt": password_parts["salt"],
        "password_hash": password_parts["hash"],
        "password_iterations": password_parts["iterations"],
        "role": "user",
        "is_active": True,
        "avatar_preset": "midnight",
        "subscription_status": SUBSCRIPTION_DEFAULT_STATUS,
        "subscription_plan": None,
        "subscription_started_at": None,
        "subscription_renewal_at": None,
        "billing_provider": None,
        "stripe_customer_id": None,
        "stripe_subscription_id": None,
        "stripe_checkout_session_id": None,
        "help_unread_response_count": 0,
        "avatar_storage_key": None,
        "onboarding": {"completed_steps": []},
        "created_at": now_utc(),
    }

    try:
        res = await db["users"].insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="User already exists")

    token = await create_session(res.inserted_id)

    return AuthOut(
        token=token,
        user=serialize_user_out({**doc, "_id": res.inserted_id}),
    )


@router.post("/login", response_model=AuthOut)
async def login(payload: LoginIn, request: Request):
    db = get_db()
    await enforce_rate_limit(
        db,
        scope="auth.login",
        identifier=build_rate_limit_identifier(request, payload.email),
        limit=AUTH_RATE_LIMITS["login"][0],
        window_seconds=AUTH_RATE_LIMITS["login"][1],
    )

    user = await db["users"].find_one(
        {"$or": [{"email": payload.email}, {"username": payload.email}]}
    )

    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not is_user_active(user):
        raise HTTPException(status_code=403, detail="Account deactivated")

    password_salt, password_hash, password_iterations = _password_parts_for_user(user)

    if not password_salt or not password_hash:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not verify_password(payload.password, password_salt, password_hash, password_iterations):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = await create_session(user["_id"])

    return AuthOut(
        token=token,
        user=serialize_user_out(user),
    )


@router.post("/password-reset/request", response_model=PasswordResetOut)
async def request_password_reset(payload: PasswordResetRequestIn, request: Request):
    db = get_db()
    await enforce_rate_limit(
        db,
        scope="auth.password_reset_request",
        identifier=build_rate_limit_identifier(request, payload.email),
        limit=AUTH_RATE_LIMITS["password_reset_request"][0],
        window_seconds=AUTH_RATE_LIMITS["password_reset_request"][1],
    )

    response = PasswordResetOut(
        message="If that email is registered, a password reset link is ready."
    )
    user = await db["users"].find_one({"email": payload.email})
    if not user or not is_user_active(user):
        return response

    raw_token = await _issue_password_reset_token(user)
    reset_url = _build_password_reset_url(raw_token)
    if password_reset_email_enabled():
        try:
            send_password_reset_email(
                recipient_email=user["email"],
                reset_url=reset_url,
                username=str(user.get("username") or "").strip() or None,
            )
        except Exception:
            logger.exception("Failed to send password reset email")
    if settings.app_env_normalized == "development":
        response.reset_url = reset_url
    return response


@router.post("/password-reset/confirm", response_model=PasswordResetOut)
async def confirm_password_reset(payload: PasswordResetConfirmIn, request: Request):
    db = get_db()
    await enforce_rate_limit(
        db,
        scope="auth.password_reset_confirm",
        identifier=build_rate_limit_identifier(request, payload.token),
        limit=AUTH_RATE_LIMITS["password_reset_confirm"][0],
        window_seconds=AUTH_RATE_LIMITS["password_reset_confirm"][1],
    )

    token_hash = _hash_password_reset_token(payload.token)
    token_doc = await db[PASSWORD_RESET_COLLECTION].find_one({"token_hash": token_hash})
    if not token_doc:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    if token_doc.get("used_at") is not None:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    expires_at = normalize_exp(token_doc.get("expires_at"))
    if not expires_at or expires_at <= now_utc():
        await db[PASSWORD_RESET_COLLECTION].delete_one({"_id": token_doc["_id"]})
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    user = await db["users"].find_one({"_id": token_doc.get("user_id")})
    if not user or not is_user_active(user):
        await db[PASSWORD_RESET_COLLECTION].delete_one({"_id": token_doc["_id"]})
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    password_salt, password_hash, password_iterations = _password_parts_for_user(user)
    if (
        password_salt
        and password_hash
        and verify_password(payload.new_password, password_salt, password_hash, password_iterations)
    ):
        raise HTTPException(status_code=400, detail="New password must be different")

    changed_at = now_utc()
    password_parts = hash_password(payload.new_password)
    await db["users"].update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "password_salt": password_parts["salt"],
                "password_hash": password_parts["hash"],
                "password_iterations": password_parts["iterations"],
                "password_changed_at": changed_at,
                "updated_at": changed_at,
            }
        },
    )
    await db["sessions"].delete_many({"user_id": user["_id"]})
    await db[PASSWORD_RESET_COLLECTION].delete_many({"user_id": user["_id"]})
    return PasswordResetOut(message="Password reset complete. You can sign in with your new password.")


@router.get("/me", response_model=UserOut)
async def me(user=Depends(require_user)):
    return serialize_user_out(user)


@router.get("/me/onboarding", response_model=UserOnboardingOut)
async def get_my_onboarding_state(user=Depends(require_user)):
    onboarding, _is_new_user = serialize_onboarding_state(user)
    return onboarding or UserOnboardingOut(completed_steps=[])


@router.patch("/me", response_model=UserOut)
async def patch_me(payload: UserPatch, user=Depends(require_user)):
    db = get_db()

    updates = payload.model_dump(exclude_none=True)
    if "avatar_preset" in updates:
        avatar_preset = str(updates["avatar_preset"] or "").strip().lower()
        if avatar_preset and avatar_preset not in AVATAR_PRESETS:
            raise HTTPException(status_code=400, detail="Invalid avatar preset")
        updates["avatar_preset"] = avatar_preset or None
        if avatar_preset:
            await _delete_avatar_if_present(user)
            updates["avatar_url"] = None
            updates["avatar_storage_key"] = None

    if updates:
        updates["updated_at"] = now_utc()
        await db["users"].update_one(
            {"_id": user["_id"]},
            {"$set": updates},
        )

    updated = await db["users"].find_one({"_id": user["_id"]})
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")

    return serialize_user_out(updated)


@router.patch("/me/onboarding", response_model=UserOnboardingOut)
async def patch_my_onboarding_state(payload: UserOnboardingPatchIn, user=Depends(require_user)):
    db = get_db()
    raw_updates = payload.model_dump(exclude_none=True)
    current_state = user.get("onboarding") if isinstance(user.get("onboarding"), dict) else {}
    next_state = dict(current_state)
    for key, value in raw_updates.items():
        next_state[key] = value
    if "completed_steps" in raw_updates:
        next_state["completed_steps"] = unique_strings(raw_updates.get("completed_steps"))
    if next_state.get("completed_at") and not next_state.get("started_at"):
        next_state["started_at"] = next_state["completed_at"]
    next_state["last_step"] = str(next_state.get("last_step") or "").strip() or None
    await db["users"].update_one(
        {"_id": user["_id"]},
        {"$set": {"onboarding": next_state, "updated_at": now_utc()}},
    )
    updated = await db["users"].find_one({"_id": user["_id"]})
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    onboarding, _is_new_user = serialize_onboarding_state(updated)
    return onboarding or UserOnboardingOut(completed_steps=[])


@router.post("/me/subscription", response_model=UserOut)
async def activate_subscription(payload: SubscriptionActivateIn, request: Request, user=Depends(require_user)):
    db = get_db()
    await enforce_rate_limit(
        db,
        scope="auth.subscription",
        identifier=build_rate_limit_identifier(request, user["_id"]),
        limit=AUTH_RATE_LIMITS["subscription"][0],
        window_seconds=AUTH_RATE_LIMITS["subscription"][1],
    )
    current_status = str(user.get("subscription_status") or SUBSCRIPTION_DEFAULT_STATUS).strip().lower()
    if has_subscription_access(user) and current_status == "active":
        return serialize_user_out(user)

    if settings.app_env_normalized != "development":
        raise HTTPException(
            status_code=409,
            detail="Mock subscription activation is only available in development. Use billing checkout in staging or production.",
        )

    requested_plan = str(payload.plan or SUBSCRIPTION_DEFAULT_PLAN).strip().lower() or SUBSCRIPTION_DEFAULT_PLAN
    if requested_plan not in SUBSCRIPTION_PLAN_KEYS:
        raise HTTPException(status_code=400, detail="Invalid subscription plan.")

    activated_at = now_utc()
    renewal_at = activated_at + timedelta(days=30)
    await db["users"].update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "subscription_status": "active",
                "subscription_plan": requested_plan,
                "subscription_started_at": user.get("subscription_started_at") or activated_at,
                "subscription_renewal_at": renewal_at,
                "billing_provider": "mock",
                "stripe_customer_id": None,
                "stripe_subscription_id": None,
                "stripe_checkout_session_id": None,
                "updated_at": activated_at,
            }
        },
    )
    updated = await db["users"].find_one({"_id": user["_id"]})
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    return serialize_user_out(updated)


@router.post("/me/password", response_model=AuthOut)
async def change_password(payload: PasswordChangeIn, request: Request, user=Depends(require_user)):
    db = get_db()
    await enforce_rate_limit(
        db,
        scope="auth.password_change",
        identifier=build_rate_limit_identifier(request, user["_id"]),
        limit=AUTH_RATE_LIMITS["password_change"][0],
        window_seconds=AUTH_RATE_LIMITS["password_change"][1],
    )

    password_salt, password_hash, password_iterations = _password_parts_for_user(user)
    if not password_salt or not password_hash:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not verify_password(payload.current_password, password_salt, password_hash, password_iterations):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    if secrets.compare_digest(payload.current_password, payload.new_password):
        raise HTTPException(status_code=400, detail="New password must be different")

    changed_at = now_utc()
    password_parts = hash_password(payload.new_password)
    await db["users"].update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "password_salt": password_parts["salt"],
                "password_hash": password_parts["hash"],
                "password_iterations": password_parts["iterations"],
                "password_changed_at": changed_at,
                "updated_at": changed_at,
            }
        },
    )
    await db["sessions"].delete_many({"user_id": user["_id"]})
    token = await create_session(user["_id"])

    updated = await db["users"].find_one({"_id": user["_id"]})
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")

    return AuthOut(token=token, user=serialize_user_out(updated))


@router.post("/me/avatar", response_model=UserOut)
async def upload_avatar(request: Request, file: UploadFile = File(...), user=Depends(require_user)):
    db = get_db()
    await enforce_rate_limit(
        db,
        scope="auth.avatar_upload",
        identifier=build_rate_limit_identifier(request, user["_id"]),
        limit=AUTH_RATE_LIMITS["avatar_upload"][0],
        window_seconds=AUTH_RATE_LIMITS["avatar_upload"][1],
    )
    if not has_subscription_access(user):
        raise HTTPException(status_code=402, detail="Active subscription required for profile image uploads")

    filename = str(file.filename or "").strip()
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_AVATAR_SUFFIXES:
        raise HTTPException(status_code=400, detail="Unsupported avatar file type")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Avatar file is empty")
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Avatar file is too large")

    # The extension check above only constrains the filename, which is fully attacker-
    # controlled. Sniff the actual bytes so a polyglot file (e.g. HTML/SVG renamed to
    # "avatar.png") can't slip through, and derive the stored content-type from the
    # verified bytes rather than the client-supplied (also spoofable) header.
    sniffed_type = sniff_image_type(content)
    if sniffed_type is None:
        raise HTTPException(status_code=400, detail="File content does not match a supported image format")

    storage = get_avatar_storage_provider()
    stored = await storage.upload_avatar(
        user_id=oid_str(user["_id"]),
        filename=filename,
        content=content,
        content_type=IMAGE_CONTENT_TYPES[sniffed_type],
    )
    await _delete_avatar_if_present(user)

    await db["users"].update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "avatar_url": stored.url,
                "avatar_storage_key": stored.storage_key,
                "avatar_preset": None,
                "updated_at": now_utc(),
            }
        },
    )
    updated = await db["users"].find_one({"_id": user["_id"]})
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    return serialize_user_out(updated)


@router.delete("/me")
async def delete_me(user=Depends(require_user)):
    db = get_db()
    await _delete_avatar_if_present(user)
    await db["users"].delete_one({"_id": user["_id"]})
    await db["sessions"].delete_many({"user_id": user["_id"]})

    return {"ok": True}


@router.post("/logout")
async def logout(user=Depends(require_user)):
    db = get_db()
    await db["sessions"].delete_many({"user_id": user["_id"]})
    return {"ok": True}
