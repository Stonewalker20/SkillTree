"""Unit tests for app/utils/email_delivery.py.

`smtplib.SMTP`/`SMTP_SSL` are monkeypatched to fake context managers that
record what they were called with, so no real network connection is ever
attempted. `settings` SMTP fields are monkeypatched per test.
"""

from __future__ import annotations

from app.core.config import settings
from app.utils import email_delivery
from app.utils.email_delivery import password_reset_email_enabled, send_password_reset_email


class _FakeSmtp:
    """Records calls and is reusable as the object yielded by `with smtplib.SMTP(...) as smtp:`."""

    instances: list["_FakeSmtp"] = []

    def __init__(self, *args, **kwargs):
        self.init_args = args
        self.init_kwargs = kwargs
        self.starttls_calls: list[dict] = []
        self.login_calls: list[tuple] = []
        self.sent_messages: list[object] = []
        _FakeSmtp.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def starttls(self, **kwargs):
        self.starttls_calls.append(kwargs)

    def login(self, username, password):
        self.login_calls.append((username, password))

    def send_message(self, message):
        self.sent_messages.append(message)


def _reset_fake_smtp(monkeypatch):
    _FakeSmtp.instances = []
    monkeypatch.setattr(email_delivery.smtplib, "SMTP", _FakeSmtp)
    monkeypatch.setattr(email_delivery.smtplib, "SMTP_SSL", _FakeSmtp)


def _enable_smtp_settings(monkeypatch, **overrides):
    defaults = dict(
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_from_email="noreply@example.com",
        smtp_from_name="SkillBridge",
        smtp_reply_to="",
        smtp_username="",
        smtp_password="",
        smtp_use_ssl=False,
        smtp_use_starttls=True,
    )
    defaults.update(overrides)
    for key, value in defaults.items():
        monkeypatch.setattr(settings, key, value)


# --------------------------------------------------------------------------
# password_reset_email_enabled
# --------------------------------------------------------------------------


def test_password_reset_email_enabled_true_when_host_and_from_email_set(monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_from_email", "noreply@example.com")
    assert password_reset_email_enabled() is True


def test_password_reset_email_enabled_false_when_host_blank(monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "   ")
    monkeypatch.setattr(settings, "smtp_from_email", "noreply@example.com")
    assert password_reset_email_enabled() is False


def test_password_reset_email_enabled_false_when_from_email_blank(monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_from_email", "   ")
    assert password_reset_email_enabled() is False


# --------------------------------------------------------------------------
# send_password_reset_email
# --------------------------------------------------------------------------


def test_send_password_reset_email_noop_when_disabled(monkeypatch):
    _reset_fake_smtp(monkeypatch)
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "smtp_from_email", "")

    send_password_reset_email("user@example.com", "https://app.example.com/reset/token")

    assert _FakeSmtp.instances == []


def test_send_password_reset_email_uses_starttls_path_by_default(monkeypatch):
    _reset_fake_smtp(monkeypatch)
    _enable_smtp_settings(monkeypatch)

    send_password_reset_email("user@example.com", "https://app.example.com/reset/token", username="Jordan")

    assert len(_FakeSmtp.instances) == 1
    smtp = _FakeSmtp.instances[0]
    assert smtp.init_args == ("smtp.example.com", 587)
    assert len(smtp.starttls_calls) == 1
    assert smtp.login_calls == []  # no username configured
    assert len(smtp.sent_messages) == 1

    message = smtp.sent_messages[0]
    assert message["Subject"] == "Reset your SkillBridge password"
    assert message["From"] == "SkillBridge <noreply@example.com>"
    assert message["To"] == "user@example.com"
    assert "Reply-To" not in message
    plain_body = message.get_body(preferencelist=("plain",)).get_content()
    assert "Hi Jordan" in plain_body
    assert "https://app.example.com/reset/token" in plain_body


def test_send_password_reset_email_skips_starttls_when_disabled(monkeypatch):
    _reset_fake_smtp(monkeypatch)
    _enable_smtp_settings(monkeypatch, smtp_use_starttls=False)

    send_password_reset_email("user@example.com", "https://app.example.com/reset/token")

    smtp = _FakeSmtp.instances[0]
    assert smtp.starttls_calls == []


def test_send_password_reset_email_uses_ssl_path_when_configured(monkeypatch):
    _reset_fake_smtp(monkeypatch)
    _enable_smtp_settings(monkeypatch, smtp_use_ssl=True, smtp_use_starttls=True)

    send_password_reset_email("user@example.com", "https://app.example.com/reset/token")

    # SSL path never calls starttls even though smtp_use_starttls is True.
    smtp = _FakeSmtp.instances[0]
    assert smtp.starttls_calls == []
    assert len(smtp.sent_messages) == 1


def test_send_password_reset_email_logs_in_when_username_configured(monkeypatch):
    _reset_fake_smtp(monkeypatch)
    _enable_smtp_settings(monkeypatch, smtp_username="smtp-user", smtp_password="smtp-pass")

    send_password_reset_email("user@example.com", "https://app.example.com/reset/token")

    smtp = _FakeSmtp.instances[0]
    assert smtp.login_calls == [("smtp-user", "smtp-pass")]


def test_send_password_reset_email_includes_reply_to_when_configured(monkeypatch):
    _reset_fake_smtp(monkeypatch)
    _enable_smtp_settings(monkeypatch, smtp_reply_to="support@example.com")

    send_password_reset_email("user@example.com", "https://app.example.com/reset/token")

    message = _FakeSmtp.instances[0].sent_messages[0]
    assert message["Reply-To"] == "support@example.com"


def test_send_password_reset_email_defaults_recipient_name_to_there_when_no_username(monkeypatch):
    _reset_fake_smtp(monkeypatch)
    _enable_smtp_settings(monkeypatch)

    send_password_reset_email("user@example.com", "https://app.example.com/reset/token", username="   ")

    message = _FakeSmtp.instances[0].sent_messages[0]
    plain_body = message.get_body(preferencelist=("plain",)).get_content()
    assert "Hi there" in plain_body


def test_send_password_reset_email_includes_html_alternative_with_link(monkeypatch):
    _reset_fake_smtp(monkeypatch)
    _enable_smtp_settings(monkeypatch)

    send_password_reset_email("user@example.com", "https://app.example.com/reset/token")

    message = _FakeSmtp.instances[0].sent_messages[0]
    html_body = message.get_body(preferencelist=("html",)).get_content()
    assert 'href="https://app.example.com/reset/token"' in html_body
