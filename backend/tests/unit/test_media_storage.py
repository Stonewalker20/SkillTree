"""Unit tests for app/utils/media_storage.py.

Pure helpers (`_safe_suffix`, `_join_url`, `_normalize_public_base`,
`_bucket_object_url`, `_aws_signing_key`) are exercised directly with no
mocking. `LocalAvatarStorage` touches a real (throwaway, per-test temporary)
directory rather than mocking `pathlib.Path`, since exercising actual
filesystem read/write/delete semantics is the point of those tests.
`S3CompatibleAvatarStorage` mocks `urlopen` so no real network call is ever
made, and `now_utc`/`secrets.token_hex` are monkeypatched wherever
determinism is required.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock
from urllib.error import HTTPError, URLError

from app.core.config import settings
from app.utils import media_storage
from app.utils.media_storage import (
    LocalAvatarStorage,
    S3CompatibleAvatarStorage,
    StoredMedia,
    _aws_signing_key,
    _bucket_object_url,
    _join_url,
    _normalize_public_base,
    _safe_suffix,
    avatar_storage_key_from_user,
    get_avatar_storage_provider,
)


FIXED_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


class _FakeResponse:
    def __init__(self, status: int = 200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


# --------------------------------------------------------------------------
# now_utc / _safe_suffix
# --------------------------------------------------------------------------


def test_now_utc_returns_utc_aware_datetime():
    result = media_storage.now_utc()
    assert isinstance(result, datetime)
    assert result.tzinfo is timezone.utc


def test_safe_suffix_lowercases_and_allows_known_extensions():
    assert _safe_suffix("photo.PNG") == ".png"
    assert _safe_suffix("photo.jpg") == ".jpg"
    assert _safe_suffix("photo.jpeg") == ".jpeg"
    assert _safe_suffix("photo.webp") == ".webp"


def test_safe_suffix_returns_empty_string_for_disallowed_or_missing_extension():
    assert _safe_suffix("photo.gif") == ""
    assert _safe_suffix("noext") == ""


# --------------------------------------------------------------------------
# _avatar_filename
# --------------------------------------------------------------------------


def test_avatar_filename_builds_expected_pattern(monkeypatch):
    monkeypatch.setattr(media_storage, "now_utc", lambda: FIXED_NOW)
    monkeypatch.setattr(media_storage.secrets, "token_hex", lambda n: "deadbeef")

    result = media_storage._avatar_filename("user-1", "photo.PNG")

    expected_ms = int(FIXED_NOW.timestamp() * 1000)
    assert result == f"user-1-{expected_ms}-deadbeef.png"


def test_avatar_filename_drops_suffix_for_disallowed_extension(monkeypatch):
    monkeypatch.setattr(media_storage, "now_utc", lambda: FIXED_NOW)
    monkeypatch.setattr(media_storage.secrets, "token_hex", lambda n: "deadbeef")

    result = media_storage._avatar_filename("user-1", "photo.gif")
    assert result.endswith("deadbeef")  # no extension appended


# --------------------------------------------------------------------------
# _join_url / _normalize_public_base / _bucket_object_url
# --------------------------------------------------------------------------


def test_join_url_handles_slashes_on_either_side():
    assert _join_url("https://cdn.example.com", "avatars/foo.png") == "https://cdn.example.com/avatars/foo.png"
    assert _join_url("https://cdn.example.com/", "/avatars/foo.png") == "https://cdn.example.com/avatars/foo.png"


def test_normalize_public_base_strips_trailing_slash():
    assert _normalize_public_base("https://cdn.example.com/") == "https://cdn.example.com"
    assert _normalize_public_base("https://cdn.example.com") == "https://cdn.example.com"


def test_bucket_object_url_quotes_key_and_keeps_path_separators():
    url = _bucket_object_url("https://s3.example.com/", "my-bucket", "avatars/a b.png")
    assert url == "https://s3.example.com/my-bucket/avatars/a%20b.png"


# --------------------------------------------------------------------------
# _aws_signing_key
# --------------------------------------------------------------------------


def test_aws_signing_key_is_32_bytes_and_deterministic():
    key1 = _aws_signing_key("secret123", "20260101", "us-east-1")
    key2 = _aws_signing_key("secret123", "20260101", "us-east-1")
    assert len(key1) == 32
    assert key1 == key2


def test_aws_signing_key_differs_when_inputs_differ():
    base = _aws_signing_key("secret123", "20260101", "us-east-1")
    assert _aws_signing_key("other-secret", "20260101", "us-east-1") != base
    assert _aws_signing_key("secret123", "20260102", "us-east-1") != base
    assert _aws_signing_key("secret123", "20260101", "eu-west-1") != base


# --------------------------------------------------------------------------
# LocalAvatarStorage
# --------------------------------------------------------------------------


async def test_local_avatar_storage_upload_writes_file_and_returns_stored_media(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        upload_dir = Path(tmp) / "avatars"
        monkeypatch.setattr(media_storage, "_avatar_filename", lambda user_id, filename: "fixed-key.png")
        storage = LocalAvatarStorage(upload_dir)

        result = await storage.upload_avatar(user_id="user-1", filename="photo.png", content=b"binary-data")

        assert result == StoredMedia(storage_key="fixed-key.png", url="/media/avatars/fixed-key.png")
        assert (upload_dir / "fixed-key.png").read_bytes() == b"binary-data"


async def test_local_avatar_storage_upload_creates_missing_directory(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        upload_dir = Path(tmp) / "does" / "not" / "exist"
        monkeypatch.setattr(media_storage, "_avatar_filename", lambda user_id, filename: "fixed-key.png")
        storage = LocalAvatarStorage(upload_dir)

        await storage.upload_avatar(user_id="user-1", filename="photo.png", content=b"x")

        assert upload_dir.is_dir()


async def test_local_avatar_storage_delete_removes_existing_file():
    with tempfile.TemporaryDirectory() as tmp:
        upload_dir = Path(tmp)
        target = upload_dir / "to-delete.png"
        target.write_bytes(b"x")
        storage = LocalAvatarStorage(upload_dir)

        await storage.delete_avatar("to-delete.png")

        assert not target.exists()


async def test_local_avatar_storage_delete_tolerates_missing_file():
    with tempfile.TemporaryDirectory() as tmp:
        storage = LocalAvatarStorage(Path(tmp))
        await storage.delete_avatar("never-existed.png")  # should not raise


async def test_local_avatar_storage_delete_noop_for_blank_key():
    with tempfile.TemporaryDirectory() as tmp:
        storage = LocalAvatarStorage(Path(tmp))
        await storage.delete_avatar(None)
        await storage.delete_avatar("   ")  # should not raise either


async def test_local_avatar_storage_delete_confines_to_upload_dir_via_path_name():
    # A traversal-style key is reduced to its basename, so delete_avatar can
    # only ever touch a file directly inside upload_dir.
    with tempfile.TemporaryDirectory() as tmp:
        upload_dir = Path(tmp)
        safe_file = upload_dir / "passed.png"
        safe_file.write_bytes(b"x")
        storage = LocalAvatarStorage(upload_dir)

        await storage.delete_avatar("../../etc/passed.png")

        assert not safe_file.exists()


# --------------------------------------------------------------------------
# S3CompatibleAvatarStorage construction and key/url helpers
# --------------------------------------------------------------------------


def _make_s3_storage(**overrides):
    kwargs = dict(
        endpoint_url="https://s3.example.com/",
        bucket="  my-bucket  ",
        region="  us-east-1  ",
        access_key_id="  AKIA123  ",
        secret_access_key="  secret123  ",
        public_base_url=None,
        key_prefix="avatars",
    )
    kwargs.update(overrides)
    return S3CompatibleAvatarStorage(**kwargs)


def test_s3_storage_constructor_strips_all_string_fields():
    storage = _make_s3_storage()
    assert storage.endpoint_url == "https://s3.example.com"
    assert storage.bucket == "my-bucket"
    assert storage.region == "us-east-1"
    assert storage.access_key_id == "AKIA123"
    assert storage.secret_access_key == "secret123"
    assert storage.public_base_url == ""
    assert storage.key_prefix == "avatars"


def test_s3_storage_object_key_uses_prefix_when_set(monkeypatch):
    monkeypatch.setattr(media_storage, "_avatar_filename", lambda user_id, filename: "stem.png")
    storage = _make_s3_storage(key_prefix="avatars")
    assert storage._object_key("user-1", "photo.png") == "avatars/stem.png"


def test_s3_storage_object_key_no_prefix_when_blank(monkeypatch):
    monkeypatch.setattr(media_storage, "_avatar_filename", lambda user_id, filename: "stem.png")
    storage = _make_s3_storage(key_prefix="")
    assert storage._object_key("user-1", "photo.png") == "stem.png"


def test_s3_storage_public_url_uses_public_base_when_set():
    storage = _make_s3_storage(public_base_url="https://cdn.example.com/")
    assert storage._public_url("avatars/stem.png") == "https://cdn.example.com/avatars/stem.png"


def test_s3_storage_public_url_falls_back_to_bucket_object_url_when_no_public_base():
    storage = _make_s3_storage(public_base_url=None)
    assert storage._public_url("avatars/stem.png") == "https://s3.example.com/my-bucket/avatars/stem.png"


# --------------------------------------------------------------------------
# S3CompatibleAvatarStorage._signed_request
# --------------------------------------------------------------------------


def test_signed_request_builds_expected_headers_and_authorization(monkeypatch):
    monkeypatch.setattr(media_storage, "now_utc", lambda: FIXED_NOW)
    storage = _make_s3_storage()

    request = storage._signed_request("PUT", "avatars/stem.png", b"payload-bytes", content_type="image/png")

    amz_date = "20260101T120000Z"
    assert request.headers["X-amz-date"] == amz_date
    assert request.headers["Content-type"] == "image/png"
    assert request.headers["Content-length"] == str(len(b"payload-bytes"))
    auth = request.headers["Authorization"]
    assert auth.startswith("AWS4-HMAC-SHA256 Credential=AKIA123/20260101/us-east-1/s3/aws4_request, ")
    assert "SignedHeaders=host;x-amz-content-sha256;x-amz-date" in auth
    assert "Signature=" in auth
    signature = auth.split("Signature=")[-1]
    assert len(signature) == 64
    assert request.get_method() == "PUT"
    assert request.data == b"payload-bytes"


def test_signed_request_omits_content_type_header_when_not_given(monkeypatch):
    monkeypatch.setattr(media_storage, "now_utc", lambda: FIXED_NOW)
    storage = _make_s3_storage()
    request = storage._signed_request("DELETE", "avatars/stem.png", b"")
    assert "Content-type" not in request.headers
    assert request.data is None
    assert request.get_method() == "DELETE"


# --------------------------------------------------------------------------
# S3CompatibleAvatarStorage.upload_avatar / delete_avatar
# --------------------------------------------------------------------------


async def test_s3_storage_upload_avatar_success(monkeypatch):
    monkeypatch.setattr(media_storage, "_avatar_filename", lambda user_id, filename: "stem.png")
    monkeypatch.setattr(media_storage, "urlopen", MagicMock(return_value=_FakeResponse(200)))
    storage = _make_s3_storage(public_base_url="https://cdn.example.com")

    result = await storage.upload_avatar(user_id="user-1", filename="photo.png", content=b"data")

    assert result == StoredMedia(storage_key="avatars/stem.png", url="https://cdn.example.com/avatars/stem.png")


async def test_s3_storage_upload_avatar_raises_runtime_error_on_bad_status(monkeypatch):
    monkeypatch.setattr(media_storage, "_avatar_filename", lambda user_id, filename: "stem.png")
    monkeypatch.setattr(media_storage, "urlopen", MagicMock(return_value=_FakeResponse(503)))
    storage = _make_s3_storage()

    try:
        await storage.upload_avatar(user_id="user-1", filename="photo.png", content=b"data")
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "503" in str(exc)


async def test_s3_storage_upload_avatar_wraps_http_error(monkeypatch):
    monkeypatch.setattr(media_storage, "_avatar_filename", lambda user_id, filename: "stem.png")
    monkeypatch.setattr(
        media_storage, "urlopen", MagicMock(side_effect=HTTPError("http://x", 403, "Forbidden", None, None))
    )
    storage = _make_s3_storage()

    try:
        await storage.upload_avatar(user_id="user-1", filename="photo.png", content=b"data")
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "403" in str(exc)


async def test_s3_storage_upload_avatar_wraps_url_error(monkeypatch):
    monkeypatch.setattr(media_storage, "_avatar_filename", lambda user_id, filename: "stem.png")
    monkeypatch.setattr(media_storage, "urlopen", MagicMock(side_effect=URLError("connection refused")))
    storage = _make_s3_storage()

    try:
        await storage.upload_avatar(user_id="user-1", filename="photo.png", content=b"data")
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "connection refused" in str(exc)


async def test_s3_storage_delete_avatar_noop_for_blank_key(monkeypatch):
    fake_urlopen = MagicMock(return_value=_FakeResponse(200))
    monkeypatch.setattr(media_storage, "urlopen", fake_urlopen)
    storage = _make_s3_storage()

    await storage.delete_avatar(None)
    await storage.delete_avatar("   ")

    fake_urlopen.assert_not_called()


async def test_s3_storage_delete_avatar_success(monkeypatch):
    monkeypatch.setattr(media_storage, "urlopen", MagicMock(return_value=_FakeResponse(204)))
    storage = _make_s3_storage()
    await storage.delete_avatar("avatars/stem.png")  # should not raise


async def test_s3_storage_delete_avatar_tolerates_404(monkeypatch):
    monkeypatch.setattr(
        media_storage, "urlopen", MagicMock(side_effect=HTTPError("http://x", 404, "Not Found", None, None))
    )
    storage = _make_s3_storage()
    await storage.delete_avatar("avatars/missing.png")  # should not raise


async def test_s3_storage_delete_avatar_reraises_non_404_http_error(monkeypatch):
    monkeypatch.setattr(
        media_storage, "urlopen", MagicMock(side_effect=HTTPError("http://x", 500, "Server Error", None, None))
    )
    storage = _make_s3_storage()

    try:
        await storage.delete_avatar("avatars/stem.png")
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "500" in str(exc)


async def test_s3_storage_delete_avatar_wraps_url_error(monkeypatch):
    monkeypatch.setattr(media_storage, "urlopen", MagicMock(side_effect=URLError("timed out")))
    storage = _make_s3_storage()

    try:
        await storage.delete_avatar("avatars/stem.png")
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "timed out" in str(exc)


# --------------------------------------------------------------------------
# get_avatar_storage_provider
# --------------------------------------------------------------------------


def test_get_avatar_storage_provider_returns_s3_when_mode_is_s3(monkeypatch):
    monkeypatch.setattr(settings, "media_storage_mode", "s3")
    monkeypatch.setattr(settings, "media_s3_endpoint_url", "https://s3.example.com")
    monkeypatch.setattr(settings, "media_s3_bucket", "my-bucket")
    monkeypatch.setattr(settings, "media_s3_region", "us-east-1")
    monkeypatch.setattr(settings, "media_s3_access_key_id", "AKIA123")
    monkeypatch.setattr(settings, "media_s3_secret_access_key", "secret123")
    monkeypatch.setattr(settings, "media_s3_public_base_url", "")
    monkeypatch.setattr(settings, "media_s3_key_prefix", "avatars")

    provider = get_avatar_storage_provider()

    assert isinstance(provider, S3CompatibleAvatarStorage)
    assert provider.bucket == "my-bucket"
    assert provider.region == "us-east-1"


def test_get_avatar_storage_provider_returns_local_by_default(monkeypatch):
    monkeypatch.setattr(settings, "media_storage_mode", "local")

    provider = get_avatar_storage_provider()

    assert isinstance(provider, LocalAvatarStorage)
    assert provider.upload_dir == settings.user_avatar_upload_path


# --------------------------------------------------------------------------
# avatar_storage_key_from_user
# --------------------------------------------------------------------------


def test_avatar_storage_key_from_user_prefers_explicit_storage_key():
    assert avatar_storage_key_from_user({"avatar_storage_key": "abc.png"}) == "abc.png"


def test_avatar_storage_key_from_user_parses_local_media_prefix():
    assert avatar_storage_key_from_user({"avatar_url": "/media/avatars/xyz.png"}) == "xyz.png"


def test_avatar_storage_key_from_user_strips_s3_bucket_prefix_when_mode_is_s3(monkeypatch):
    monkeypatch.setattr(settings, "media_storage_mode", "s3")
    monkeypatch.setattr(settings, "media_s3_bucket", "my-bucket")

    user = {"avatar_url": "https://s3.example.com/my-bucket/avatars/xyz.png"}
    assert avatar_storage_key_from_user(user) == "avatars/xyz.png"


def test_avatar_storage_key_from_user_keeps_full_path_when_no_bucket_prefix_match(monkeypatch):
    monkeypatch.setattr(settings, "media_storage_mode", "s3")
    monkeypatch.setattr(settings, "media_s3_bucket", "my-bucket")

    user = {"avatar_url": "https://cdn.example.com/avatars/xyz.png"}
    assert avatar_storage_key_from_user(user) == "avatars/xyz.png"


def test_avatar_storage_key_from_user_returns_none_when_no_avatar_url():
    assert avatar_storage_key_from_user({}) is None


def test_avatar_storage_key_from_user_returns_none_when_url_has_no_path(monkeypatch):
    monkeypatch.setattr(settings, "media_storage_mode", "local")
    assert avatar_storage_key_from_user({"avatar_url": "https://example.com"}) is None
