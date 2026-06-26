"""Unit tests for app/utils/link_extraction.py, mocking every network call.

No real HTTP request or DNS lookup is ever made: `_fetch_html`'s opener is
replaced with an in-memory fake, and `socket.getaddrinfo` is monkeypatched
for the hostname-resolution branch of `_is_safe_remote_host`.
"""

from __future__ import annotations

import socket
from urllib.error import HTTPError, URLError

import pytest

from app.utils import link_extraction
from app.utils.link_extraction import (
    LinkExtractionError,
    LinkExtractionResult,
    _extract_link_sync,
    _extract_meta,
    _extract_title_tag,
    _fetch_html,
    _github_fallback,
    _is_safe_remote_host,
    _is_safe_remote_url,
    _parse_html,
    _strip_html,
    _website_fallback,
    extract_link_evidence_content,
    github_evidence_title,
    is_github_url,
    is_http_url,
)


# --------------------------------------------------------------------------
# is_http_url / is_github_url / github_evidence_title
# --------------------------------------------------------------------------


def test_is_http_url_true_for_http_and_https():
    assert is_http_url("http://example.com") is True
    assert is_http_url("https://example.com/path") is True


def test_is_http_url_false_for_other_schemes_or_blank():
    assert is_http_url("ftp://example.com") is False
    assert is_http_url("not a url") is False
    assert is_http_url(None) is False
    assert is_http_url("") is False


def test_is_github_url_true_for_github_and_subdomains():
    assert is_github_url("https://github.com/octocat/hello") is True
    assert is_github_url("https://WWW.GitHub.com/octocat") is True
    assert is_github_url("https://gist.github.com/octocat") is True


def test_is_github_url_false_for_other_hosts():
    assert is_github_url("https://example.com") is False
    assert is_github_url("https://notgithub.com") is False
    assert is_github_url(None) is False


def test_github_evidence_title_returns_owner_repo_and_strips_git_suffix():
    assert github_evidence_title("https://github.com/octocat/Hello-World.git") == "octocat/Hello-World"


def test_github_evidence_title_single_path_segment():
    assert github_evidence_title("https://github.com/octocat") == "octocat"


def test_github_evidence_title_no_path_segments_returns_default():
    assert github_evidence_title("https://github.com/") == "GitHub Evidence"
    assert github_evidence_title(None) == "GitHub Evidence"


# --------------------------------------------------------------------------
# _extract_meta / _extract_title_tag / _strip_html
# --------------------------------------------------------------------------


def test_extract_meta_finds_first_matching_name_and_unescapes_entities():
    html = '<meta property="og:title" content="Hello &amp; World">'
    assert _extract_meta(html, "og:title", "twitter:title") == "Hello & World"


def test_extract_meta_falls_through_candidate_names_in_order():
    html = '<meta name="description" content="Plain desc">'
    assert _extract_meta(html, "og:description", "twitter:description", "description") == "Plain desc"


def test_extract_meta_returns_blank_when_no_tag_matches():
    assert _extract_meta('<meta charset="utf-8">', "og:title") == ""


def test_extract_title_tag_collapses_internal_whitespace():
    html = "<title>  Multi\n  Line   Title </title>"
    assert _extract_title_tag(html) == "Multi Line Title"


def test_extract_title_tag_returns_blank_when_missing():
    assert _extract_title_tag("<html><body>no title</body></html>") == ""


def test_strip_html_removes_scripts_styles_and_tags():
    html = (
        "<html><head><title>Ignored</title></head>"
        "<body><script>var x=1;</script><style>.a{color:red}</style>"
        "<p>Hello   World</p></body></html>"
    )
    assert _strip_html(html) == "Ignored Hello World"


# --------------------------------------------------------------------------
# _is_safe_remote_host / _is_safe_remote_url
# --------------------------------------------------------------------------


def test_is_safe_remote_host_false_for_blank_localhost_and_dot_local():
    assert _is_safe_remote_host("") is False
    assert _is_safe_remote_host("localhost") is False
    assert _is_safe_remote_host("localhost.localdomain") is False
    assert _is_safe_remote_host("printer.local") is False


def test_is_safe_remote_host_ip_literal_public_is_safe():
    assert _is_safe_remote_host("8.8.8.8") is True


def test_is_safe_remote_host_ip_literal_private_or_loopback_is_unsafe():
    assert _is_safe_remote_host("10.0.0.5") is False
    assert _is_safe_remote_host("127.0.0.1") is False
    assert _is_safe_remote_host("169.254.1.1") is False


def test_is_safe_remote_host_resolves_hostname_and_allows_public_address(monkeypatch):
    def fake_getaddrinfo(host, port, type=None):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(link_extraction.socket, "getaddrinfo", fake_getaddrinfo)
    assert _is_safe_remote_host("example.com") is True


def test_is_safe_remote_host_resolves_hostname_and_rejects_private_address(monkeypatch):
    def fake_getaddrinfo(host, port, type=None):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.9", 0))]

    monkeypatch.setattr(link_extraction.socket, "getaddrinfo", fake_getaddrinfo)
    assert _is_safe_remote_host("internal.example.com") is False


def test_is_safe_remote_host_returns_false_when_dns_resolution_fails(monkeypatch):
    def fake_getaddrinfo(host, port, type=None):
        raise OSError("name resolution failed")

    monkeypatch.setattr(link_extraction.socket, "getaddrinfo", fake_getaddrinfo)
    assert _is_safe_remote_host("does-not-resolve.example.com") is False


def test_is_safe_remote_url_false_for_non_http_scheme():
    assert _is_safe_remote_url("ftp://example.com") is False


def test_is_safe_remote_url_true_for_public_https_url(monkeypatch):
    def fake_getaddrinfo(host, port, type=None):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(link_extraction.socket, "getaddrinfo", fake_getaddrinfo)
    assert _is_safe_remote_url("https://example.com/page") is True


# --------------------------------------------------------------------------
# _github_fallback / _website_fallback / _parse_html
# --------------------------------------------------------------------------


def test_github_fallback_builds_result_for_repo_root():
    result = _github_fallback("https://github.com/octocat/Hello-World")
    assert result.source_kind == "github"
    assert result.title == "octocat/Hello-World"
    assert result.description == "GitHub repository"
    assert "octocat/Hello-World" in result.text


def test_github_fallback_describes_deeper_path_segments():
    result = _github_fallback("https://github.com/octocat/Hello-World/blob/main/README.md")
    assert "blob main README.md" in result.description


def test_website_fallback_builds_result_from_host_and_path():
    result = _website_fallback("https://example.com/some-path/here")
    assert result.source_kind == "website"
    assert result.title == "example.com"
    assert "some path here" in result.text


def test_parse_html_prefers_og_title_then_title_tag():
    html = '<title>Fallback</title><meta property="og:title" content="OG Title">'
    result = _parse_html("https://example.com/page", html)
    assert result.title == "OG Title"
    assert result.source_kind == "website"


def test_parse_html_falls_back_to_title_tag_when_no_meta():
    html = "<title>Page Title</title><p>Body text</p>"
    result = _parse_html("https://example.com/page", html)
    assert result.title == "Page Title"


def test_parse_html_github_url_without_title_uses_github_evidence_title():
    html = "<p>no title or meta here</p>"
    result = _parse_html("https://github.com/octocat/Hello-World", html)
    assert result.source_kind == "github"
    assert result.title == "octocat/Hello-World"


def test_parse_html_no_title_anywhere_falls_back_to_netloc():
    html = "<p>nothing useful</p>"
    result = _parse_html("https://example.com/page", html)
    assert result.title == "example.com"


# --------------------------------------------------------------------------
# _fetch_html (mocked urllib opener; no real network access)
# --------------------------------------------------------------------------


class FakeHeaders:
    def __init__(self, content_length=None, charset="utf-8"):
        self._content_length = content_length
        self._charset = charset

    def get(self, name):
        if name == "Content-Length":
            return self._content_length
        return None

    def get_content_charset(self):
        return self._charset


class FakeResponse:
    def __init__(self, body: bytes, content_length=None, charset="utf-8"):
        self.headers = FakeHeaders(content_length, charset)
        self._body = body

    def read(self, n):
        return self._body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakeOpener:
    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc

    def open(self, _request, timeout=None):
        if self._exc is not None:
            raise self._exc
        return self._response


def test_fetch_html_returns_decoded_body(monkeypatch):
    monkeypatch.setattr(
        link_extraction, "build_opener", lambda *_a: FakeOpener(response=FakeResponse(b"<html>Hello</html>"))
    )
    assert _fetch_html("https://example.com") == "<html>Hello</html>"


def test_fetch_html_raises_when_content_length_header_exceeds_limit(monkeypatch):
    big = str(link_extraction.MAX_REMOTE_FETCH_BYTES + 1)
    monkeypatch.setattr(
        link_extraction,
        "build_opener",
        lambda *_a: FakeOpener(response=FakeResponse(b"<html></html>", content_length=big)),
    )
    with pytest.raises(LinkExtractionError):
        _fetch_html("https://example.com")


def test_fetch_html_raises_when_body_exceeds_limit_without_content_length_header(monkeypatch):
    body = b"a" * (link_extraction.MAX_REMOTE_FETCH_BYTES + 10)
    monkeypatch.setattr(link_extraction, "build_opener", lambda *_a: FakeOpener(response=FakeResponse(body)))
    with pytest.raises(LinkExtractionError):
        _fetch_html("https://example.com")


def test_fetch_html_wraps_http_error(monkeypatch):
    exc = HTTPError("https://example.com", 404, "Not Found", None, None)
    monkeypatch.setattr(link_extraction, "build_opener", lambda *_a: FakeOpener(exc=exc))
    with pytest.raises(LinkExtractionError):
        _fetch_html("https://example.com")


def test_fetch_html_wraps_url_error(monkeypatch):
    monkeypatch.setattr(link_extraction, "build_opener", lambda *_a: FakeOpener(exc=URLError("dns failure")))
    with pytest.raises(LinkExtractionError):
        _fetch_html("https://example.com")


# --------------------------------------------------------------------------
# _extract_link_sync / extract_link_evidence_content
# --------------------------------------------------------------------------


def test_extract_link_sync_rejects_non_http_url():
    with pytest.raises(LinkExtractionError):
        _extract_link_sync("not-a-url")


def test_extract_link_sync_rejects_unsafe_url(monkeypatch):
    monkeypatch.setattr(link_extraction, "_is_safe_remote_url", lambda _url: False)
    with pytest.raises(LinkExtractionError):
        _extract_link_sync("https://example.com")


def test_extract_link_sync_parses_html_when_fetch_succeeds(monkeypatch):
    monkeypatch.setattr(link_extraction, "_is_safe_remote_url", lambda _url: True)
    monkeypatch.setattr(link_extraction, "_fetch_html", lambda _url: "<title>Example Page</title>")

    result = _extract_link_sync("https://example.com")

    assert isinstance(result, LinkExtractionResult)
    assert result.title == "Example Page"
    assert result.source_kind == "website"


def test_extract_link_sync_uses_github_fallback_when_html_is_empty(monkeypatch):
    monkeypatch.setattr(link_extraction, "_is_safe_remote_url", lambda _url: True)
    monkeypatch.setattr(link_extraction, "_fetch_html", lambda _url: "")

    result = _extract_link_sync("https://github.com/octocat/Hello-World")

    assert result.source_kind == "github"
    assert result.title == "octocat/Hello-World"


def test_extract_link_sync_uses_website_fallback_when_html_is_empty(monkeypatch):
    monkeypatch.setattr(link_extraction, "_is_safe_remote_url", lambda _url: True)
    monkeypatch.setattr(link_extraction, "_fetch_html", lambda _url: "")

    result = _extract_link_sync("https://example.com/page")

    assert result.source_kind == "website"
    assert result.title == "example.com"


async def test_extract_link_evidence_content_delegates_to_sync_helper(monkeypatch):
    expected = LinkExtractionResult(
        url="https://example.com", source_kind="website", title="T", description="D", text="X"
    )
    monkeypatch.setattr(link_extraction, "_extract_link_sync", lambda _url: expected)

    result = await extract_link_evidence_content("https://example.com")

    assert result is expected
