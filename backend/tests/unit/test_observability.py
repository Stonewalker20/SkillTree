"""Unit tests for app/utils/observability.py logging and request-middleware helpers."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.utils import observability
from app.utils.observability import emit_app_event, request_logging_middleware


class FakeHandler:
    def __init__(self):
        self.formatter = None

    def setFormatter(self, fmt):
        self.formatter = fmt


class FakeLogger:
    def __init__(self, name):
        self.name = name
        self.handlers = []
        self.level = None
        self.info_calls = []

    def addHandler(self, handler):
        self.handlers.append(handler)

    def setLevel(self, level):
        self.level = level

    def info(self, message):
        self.info_calls.append(message)


class FakeLoggingModule:
    """Stand-in for the stdlib `logging` module used inside observability.py."""

    INFO = "INFO"
    DEBUG = "DEBUG"
    WARNING = "WARNING"

    def __init__(self):
        self._loggers: dict[str, FakeLogger] = {}

    def getLogger(self, name=None):
        key = name or "<root>"
        if key not in self._loggers:
            self._loggers[key] = FakeLogger(key)
        return self._loggers[key]

    def StreamHandler(self):
        return FakeHandler()

    def Formatter(self, fmt):
        return fmt


def test_configure_logging_adds_handler_once_and_sets_levels(monkeypatch):
    fake_logging = FakeLoggingModule()
    monkeypatch.setattr(observability, "logging", fake_logging)

    observability.configure_logging("DEBUG")
    root = fake_logging.getLogger()
    target = fake_logging.getLogger(observability.LOGGER_NAME)
    assert len(root.handlers) == 1
    assert root.level == "DEBUG"
    assert target.level == "DEBUG"

    observability.configure_logging("WARNING")
    assert len(root.handlers) == 1  # no duplicate handler on second call
    assert root.level == "WARNING"


def test_configure_logging_defaults_to_info_for_unknown_level_name(monkeypatch):
    fake_logging = FakeLoggingModule()
    monkeypatch.setattr(observability, "logging", fake_logging)

    observability.configure_logging("not-a-real-level")

    assert fake_logging.getLogger().level == "INFO"


def test_emit_app_event_logs_sorted_json_payload(monkeypatch):
    fake_logging = FakeLoggingModule()
    monkeypatch.setattr(observability, "logging", fake_logging)

    emit_app_event("user_signup", user_id="abc123", plan="pro")

    target = fake_logging.getLogger(observability.LOGGER_NAME)
    assert len(target.info_calls) == 1
    payload = json.loads(target.info_calls[0])
    assert payload == {"event": "user_signup", "user_id": "abc123", "plan": "pro"}


def test_emit_app_event_serializes_non_json_native_values_with_str(monkeypatch):
    fake_logging = FakeLoggingModule()
    monkeypatch.setattr(observability, "logging", fake_logging)

    class Weird:
        def __str__(self):
            return "weird-value"

    emit_app_event("custom_event", thing=Weird())

    target = fake_logging.getLogger(observability.LOGGER_NAME)
    payload = json.loads(target.info_calls[0])
    assert payload["thing"] == "weird-value"


def make_fake_request(method="GET", path="/api/things", headers=None, client_host="203.0.113.9"):
    return SimpleNamespace(
        headers=headers or {},
        method=method,
        url=SimpleNamespace(path=path),
        client=SimpleNamespace(host=client_host) if client_host else None,
    )


async def test_request_logging_middleware_success_sets_request_id_header_and_emits_event(monkeypatch):
    emitted = []
    monkeypatch.setattr(observability, "_emit", lambda event, **fields: emitted.append((event, fields)))

    request = make_fake_request(headers={"user-agent": "pytest-agent"})
    response = SimpleNamespace(headers={}, status_code=200)

    async def call_next(_request):
        return response

    result = await request_logging_middleware(request, call_next)

    assert result is response
    assert "X-Request-ID" in response.headers
    assert len(emitted) == 1
    event_name, fields = emitted[0]
    assert event_name == "http_request"
    assert fields["status_code"] == 200
    assert fields["method"] == "GET"
    assert fields["path"] == "/api/things"
    assert fields["client_ip"] == "203.0.113.9"
    assert fields["user_agent"] == "pytest-agent"
    assert fields["request_id"] == response.headers["X-Request-ID"]


async def test_request_logging_middleware_reuses_incoming_request_id_header(monkeypatch):
    emitted = []
    monkeypatch.setattr(observability, "_emit", lambda event, **fields: emitted.append((event, fields)))

    request = make_fake_request(headers={"x-request-id": "incoming-id-123"})
    response = SimpleNamespace(headers={}, status_code=201)

    async def call_next(_request):
        return response

    await request_logging_middleware(request, call_next)

    assert response.headers["X-Request-ID"] == "incoming-id-123"
    assert emitted[0][1]["request_id"] == "incoming-id-123"


async def test_request_logging_middleware_logs_500_and_reraises_on_exception(monkeypatch):
    emitted = []
    monkeypatch.setattr(observability, "_emit", lambda event, **fields: emitted.append((event, fields)))

    request = make_fake_request()

    async def call_next(_request):
        raise RuntimeError("downstream boom")

    with pytest.raises(RuntimeError, match="downstream boom"):
        await request_logging_middleware(request, call_next)

    assert len(emitted) == 1
    event_name, fields = emitted[0]
    assert event_name == "http_request"
    assert fields["status_code"] == 500
    assert fields["error_type"] == "RuntimeError"
