"""Sanitization helpers for free-form text pulled out of user-supplied evidence.

Evidence text arrives from many attacker-influenced sources -- pasted strings, uploaded
PDF/DOCX/TXT files, and scraped links. Before that text is stored, indexed for retrieval,
or handed to model inference, it should be normalized so that control characters, null
bytes, and other byte-level junk can't corrupt downstream storage, logs, or prompts.

These helpers are deliberately dependency-free (stdlib only) so they impose no new install
requirement.
"""

from __future__ import annotations

import re
import unicodedata

# Characters we always strip outright: NULs and the C0/C1 control ranges, but excluding
# the common whitespace controls (tab, newline, carriage return) which we normalize below.
_CONTROL_CHARS = "".join(
    ch
    for ch in map(chr, list(range(0x00, 0x20)) + list(range(0x7F, 0xA0)))
    if ch not in ("\t", "\n", "\r")
)
_CONTROL_RE = re.compile(f"[{re.escape(_CONTROL_CHARS)}]")

# Collapse runs of horizontal whitespace and limit consecutive blank lines.
_HORIZONTAL_WS_RE = re.compile(r"[^\S\r\n]+")
_EXCESS_NEWLINES_RE = re.compile(r"\n{3,}")

# Standalone headings that introduce a trailing citations/bibliography block. When evidence
# text (e.g. a pasted paper) ends with one of these sections, it is noise for skill extraction
# and storage, so the heading and everything after it is dropped.
_REFERENCES_HEADING_RE = re.compile(
    r"^(references|reference list|bibliography|works cited|citations)\s*:?\s*$",
    re.IGNORECASE,
)

# Upper bound on stored evidence text to keep documents and prompts bounded.
MAX_EVIDENCE_TEXT_CHARS = 200_000


def _strip_references_section(text: str) -> str:
    """Drop a trailing citations/references block introduced by a standalone heading.

    Only a heading that appears after the first line is treated as a section break, so text
    that merely starts with the word "References" is left untouched.
    """
    lines = text.split("\n")
    for index, line in enumerate(lines):
        if index > 0 and _REFERENCES_HEADING_RE.match(line.strip()):
            return "\n".join(lines[:index]).strip()
    return text


def sanitize_user_evidence_text(text: str | None, *, max_chars: int = MAX_EVIDENCE_TEXT_CHARS) -> str:
    """Return a cleaned, bounded version of user-supplied evidence text.

    The cleaning steps:
      * coerce ``None`` / non-strings to ``""``
      * Unicode-normalize to NFC for consistent storage and comparison
      * drop NUL bytes and other C0/C1 control characters (keeping tab/newline/CR)
      * normalize line endings to ``\\n`` and collapse excessive blank lines
      * collapse runs of horizontal whitespace and trim trailing spaces per line
      * drop a trailing citations/references section if one is present
      * cap the result at ``max_chars`` characters

    It is safe to call on already-clean text and is idempotent.
    """
    if not text:
        return ""
    if not isinstance(text, str):
        text = str(text)

    text = unicodedata.normalize("NFC", text)

    # Normalize line endings first so the control-character pass keeps real newlines.
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    text = _CONTROL_RE.sub("", text)

    # Collapse horizontal whitespace, then trim trailing spaces on each line.
    text = _HORIZONTAL_WS_RE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))

    # Limit consecutive blank lines to at most one.
    text = _EXCESS_NEWLINES_RE.sub("\n\n", text)

    # Drop a trailing citations/references block if one is present.
    text = _strip_references_section(text)

    text = text.strip()

    if max_chars is not None and max_chars >= 0 and len(text) > max_chars:
        text = text[:max_chars].rstrip()

    return text
