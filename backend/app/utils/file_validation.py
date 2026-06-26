"""Magic-byte / content-sniffing checks for user uploads.

Filename extensions and client-supplied `Content-Type` headers are both fully attacker-
controlled and must never be trusted on their own to decide how an uploaded file is stored,
served, or parsed. A request can claim any extension and any Content-Type regardless of what
bytes actually follow. The helpers here inspect the real file content and confirm it matches
the format the upload claims to be, closing the classic "polyglot file with an allowed
extension" gap (e.g. an HTML/SVG payload renamed to `avatar.png`).

These are deliberately dependency-free (stdlib only) so they impose no new install requirement.
"""

from __future__ import annotations

import zipfile
from io import BytesIO

# Canonical sniffed-image-type -> content-type we serve back, regardless of what the
# uploading client claimed in its Content-Type header.
IMAGE_CONTENT_TYPES: dict[str, str] = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}


def sniff_image_type(content: bytes) -> str | None:
    """Return "png", "jpeg", or "webp" if `content` actually starts with that image
    format's magic bytes, else None. Ignores filename and any declared content-type."""
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if content.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if len(content) >= 12 and content[0:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "webp"
    return None


def sniff_pdf(content: bytes) -> bool:
    """True if `content` contains the PDF magic bytes near the start of the file.

    Most PDFs start with `%PDF-` at byte 0, but some producers prepend a byte-order mark
    or a small amount of leading whitespace, so this checks the first 1KB rather than only
    byte 0 -- matching common practice for PDF sniffers.
    """
    return b"%PDF-" in content[:1024]


def sniff_docx(content: bytes) -> bool:
    """True if `content` is a real Office Open XML *word processing* document.

    DOCX is a zip archive, so a bare "PK\\x03\\x04" signature check would also match plain
    zip files, XLSX, and PPTX. Instead, this opens the archive and confirms it has the
    manifest entry that's specific to a word-processing document.
    """
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            names = archive.namelist()
    except zipfile.BadZipFile:
        return False
    return "word/document.xml" in names
