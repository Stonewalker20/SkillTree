"""Evidence analysis and CRUD routes that ingest user artifacts, extract skills, and keep retrieval indexes synchronized."""

from __future__ import annotations

from fastapi import APIRouter, Query, HTTPException, Depends, UploadFile, File, Form, Request
from app.core.auth import require_user
from datetime import datetime, timezone
from app.core.db import get_db
from app.models.evidence import EvidenceIn, EvidenceOut, EvidencePatch
from app.utils.ai import extract_skill_candidates, embed_texts, cosine_similarity, normalize_ai_preferences
from app.utils.link_extraction import (
    LinkExtractionError,
    extract_link_evidence_content,
    github_evidence_title,
    is_github_url,
    is_http_url,
)
from app.utils.rag import delete_rag_document, sync_rag_document
from app.utils.rewards import safe_increment_reward_counter
from app.utils.security import AI_RATE_LIMITS, build_rate_limit_identifier, enforce_rate_limit
from app.utils.skill_catalog import (
    build_canonical_skill_index,
    lexical_skill_similarity,
    merge_skill_docs,
    normalize_skill_text,
    should_use_strict_exact_match,
)
from app.utils.text_safety import sanitize_user_evidence_text
from app.utils.file_validation import sniff_pdf, sniff_docx
from app.utils.mongo import oid_str, ref_query, ref_values, to_object_id, try_object_id
import json
import io
import os
import re
import logging
from hashlib import sha1

router = APIRouter()
LOGGER = logging.getLogger(__name__)

TEST_SKILL_PATTERN = re.compile(r"\b(test|demo|sample|mock|dummy|placeholder)\b", re.IGNORECASE)
BAD_SKILL_PATTERN = re.compile(r"(^\d+(\.\d+)?$)|(^\d{4}$)|(^[a-z]{1,2}$)|(\.$)", re.IGNORECASE)
BAD_SKILL_PHRASES = [
    "ability to",
    "equal opportunity",
    "applicants receive",
    "company name",
    "base salary",
    "benefits package",
]
ALLOWED_SHORT_SKILLS = {"c", "c#", "c++", "go", "r", "ui", "ux", "qa", "bi", "ml", "ai"}
MAX_EVIDENCE_UPLOAD_BYTES = 5 * 1024 * 1024

def now_utc():
    return datetime.now(timezone.utc)


def is_hidden_skill(doc: dict) -> bool:
    name = (doc.get("name") or "").strip()
    if not name:
        return True
    if doc.get("hidden") is True:
        return True
    low = name.lower()
    if TEST_SKILL_PATTERN.search(name):
        return True
    if low not in ALLOWED_SHORT_SKILLS and BAD_SKILL_PATTERN.search(name):
        return True
    if any(phrase in low for phrase in BAD_SKILL_PHRASES):
        return True
    return False


def serialize_evidence(doc: dict) -> dict:
    extracted_skill_ids = [oid_str(x) for x in doc.get("extracted_skill_ids", []) if oid_str(x)]
    stored_manual_skill_ids = [oid_str(x) for x in doc.get("manual_skill_ids", []) if oid_str(x)]
    fallback_skill_ids = [oid_str(x) for x in doc.get("skill_ids", []) if oid_str(x)]
    manual_skill_ids = stored_manual_skill_ids or [
        skill_id for skill_id in fallback_skill_ids if skill_id not in set(extracted_skill_ids)
    ]
    skill_ids = []
    seen_skill_ids: set[str] = set()
    for skill_id in [*extracted_skill_ids, *manual_skill_ids, *fallback_skill_ids]:
        if not skill_id or skill_id in seen_skill_ids:
            continue
        seen_skill_ids.add(skill_id)
        skill_ids.append(skill_id)
    return {
        "id": oid_str(doc["_id"]),
        "user_email": doc.get("user_email"),
        "user_id": oid_str(doc.get("user_id")) if doc.get("user_id") is not None else None,
        "type": doc["type"],
        "title": doc["title"],
        "source": doc["source"],
        "text_excerpt": str(doc.get("text_excerpt") or ""),
        "skill_ids": skill_ids,
        "extracted_skill_ids": extracted_skill_ids,
        "manual_skill_ids": manual_skill_ids,
        "manual_skill_names": [str(value or "").strip() for value in (doc.get("manual_skill_names") or []) if str(value or "").strip()],
        "project_id": oid_str(doc.get("project_id")) if doc.get("project_id") is not None else None,
        "tags": doc.get("tags", []),
        "origin": doc.get("origin", "user"),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


def extract_text_from_upload(filename: str, raw: bytes) -> str:
    lower = (filename or "").lower()
    if lower.endswith(".pdf"):
        # The filename extension is attacker-controlled, so confirm the bytes are
        # actually a PDF before handing them to the parser.
        if not sniff_pdf(raw):
            raise HTTPException(status_code=400, detail="File content does not match a valid PDF.")
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(raw))
        return sanitize_user_evidence_text("\n".join((page.extract_text() or "") for page in reader.pages).strip())
    if lower.endswith(".docx"):
        if not sniff_docx(raw):
            raise HTTPException(status_code=400, detail="File content does not match a valid DOCX.")
        from docx import Document

        doc = Document(io.BytesIO(raw))
        return sanitize_user_evidence_text("\n".join(p.text for p in doc.paragraphs).strip())
    if lower.endswith(".txt") or lower.endswith(".md"):
        return sanitize_user_evidence_text(raw.decode("utf-8", errors="ignore").strip())
    raise HTTPException(status_code=400, detail="Unsupported file type. Use PDF, DOCX, or TXT.")


def make_excerpt(text: str) -> str:
    return sanitize_user_evidence_text(str(text or "").strip())


def infer_source(url: str | None, filename: str | None) -> str:
    if url and url.strip():
        return url.strip()
    if filename and filename.strip():
        return filename.strip()
    return "manual-entry"


async def require_owned_project_id(db, user: dict, project_id: str | None) -> object | None:
    cleaned = str(project_id or "").strip()
    if not cleaned:
        return None

    try:
        project_oid = to_object_id(cleaned)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid project_id")

    own_project = await db["projects"].find_one({"_id": project_oid, **ref_query("user_id", user["_id"])}, {"_id": 1})
    if own_project:
        return project_oid

    if await db["projects"].find_one({"_id": project_oid}, {"_id": 1}):
        raise HTTPException(status_code=403, detail="You do not have access to this project")

    raise HTTPException(status_code=404, detail="Project not found")


def normalize_skill_ids(skill_ids: list[str] | None) -> list[object]:
    normalized: list[object] = []
    for sid in skill_ids or []:
        oid = try_object_id(sid)
        if oid is None or oid in normalized:
            continue
        if oid not in normalized:
            normalized.append(oid)
    return normalized


def normalize_text_list(values: list[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        text = str(value or "").strip()
        if not text:
            continue
        key = normalize_skill_text(text)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def parse_form_list(value: str | None) -> list[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = None
    if isinstance(parsed, list):
        return normalize_text_list([str(item or "").strip() for item in parsed])
    return normalize_text_list([part.strip() for part in raw.split(",") if part.strip()])


def combine_skill_refs(*skill_id_sets: list[object]) -> list[object]:
    combined: list[object] = []
    seen: set[str] = set()
    for values in skill_id_sets:
        for value in values or []:
            skill_id = oid_str(value)
            if not skill_id or skill_id in seen:
                continue
            seen.add(skill_id)
            combined.append(value)
    return combined


def should_derive_text_from_source(text: str | None, source: str | None) -> bool:
    cleaned = str(text or "").strip()
    source_text = str(source or "").strip()
    if len(cleaned) < 20:
        return True
    lowered = cleaned.casefold()
    if lowered.startswith("github link:") or lowered == source_text.casefold():
        return True
    if is_http_url(cleaned):
        return True
    return False


async def derive_link_content(url: str | None) -> dict:
    cleaned = str(url or "").strip()
    if not cleaned or not is_http_url(cleaned):
        return {"title": "", "text_excerpt": "", "source_kind": ""}
    try:
        extracted = await extract_link_evidence_content(cleaned)
    except LinkExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    excerpt = make_excerpt(" ".join(part for part in [extracted.description, extracted.text] if part))
    return {
        "title": extracted.title,
        "text_excerpt": excerpt,
        "source_kind": extracted.source_kind,
    }


async def extract_catalog_skill_ids(visible_skills: list[dict], text: str, ai_preferences: dict | None = None) -> list[object]:
    matches = await extract_skill_matches_from_catalog(visible_skills, text, ai_preferences=ai_preferences)
    return normalize_skill_ids(
        [str(match.get("skill_id") or "").strip() for match in matches if not str(match.get("skill_id") or "").startswith("candidate:")]
    )


async def resolve_manual_skill_ids(
    db,
    user: dict,
    visible_skills: list[dict],
    *,
    manual_skill_ids: list[str] | None = None,
    manual_skill_names: list[str] | None = None,
) -> tuple[list[object], list[str]]:
    normalized_skill_ids = normalize_skill_ids(manual_skill_ids)
    normalized_names = normalize_text_list(manual_skill_names)
    if not normalized_names:
        return normalized_skill_ids, []

    name_index: dict[str, dict] = {}
    for skill in visible_skills:
        names = [(skill.get("name") or "").strip()]
        names.extend(str(alias or "").strip() for alias in (skill.get("aliases") or []))
        for label in names:
            key = normalize_skill_text(label)
            if key and key not in name_index:
                name_index[key] = skill

    resolved_names: list[str] = []
    for skill_name in normalized_names:
        key = normalize_skill_text(skill_name)
        matched = name_index.get(key)
        if matched is not None:
            oid = try_object_id(matched.get("_id"))
            if oid is not None and oid not in normalized_skill_ids:
                normalized_skill_ids.append(oid)
            resolved_names.append(str(matched.get("name") or skill_name).strip() or skill_name)
            continue

        now = now_utc()
        created_doc = {
            "name": skill_name,
            "category": "General",
            "categories": ["General"],
            "aliases": [],
            "tags": ["manual-evidence"],
            "origin": "user",
            "created_by_user_id": user["_id"],
            "hidden": False,
            "created_at": now,
            "updated_at": now,
        }
        result = await db["skills"].insert_one(created_doc)
        created_doc["_id"] = result.inserted_id
        visible_skills.append(created_doc)
        name_index[key] = created_doc
        normalized_skill_ids.append(result.inserted_id)
        resolved_names.append(skill_name)

    return normalized_skill_ids, resolved_names


async def resolve_evidence_payload_skills(
    db,
    user: dict,
    visible_skills: list[dict],
    *,
    legacy_skill_ids: list[str] | None = None,
    extracted_skill_ids: list[str] | None = None,
    manual_skill_ids: list[str] | None = None,
    manual_skill_names: list[str] | None = None,
) -> tuple[list[object], list[object], list[object], list[str]]:
    normalized_extracted_skill_ids = normalize_skill_ids(extracted_skill_ids)
    normalized_manual_skill_ids, resolved_manual_skill_names = await resolve_manual_skill_ids(
        db,
        user,
        visible_skills,
        manual_skill_ids=[*(legacy_skill_ids or []), *(manual_skill_ids or [])],
        manual_skill_names=manual_skill_names,
    )
    combined_skill_ids = combine_skill_refs(normalized_extracted_skill_ids, normalized_manual_skill_ids)
    return normalized_extracted_skill_ids, normalized_manual_skill_ids, combined_skill_ids, resolved_manual_skill_names


async def safe_sync_rag_document(
    db,
    *,
    user_id: str,
    source_type: str,
    source_id: str,
    title: str,
    text: str,
    preferences: dict | None = None,
    metadata: dict | None = None,
) -> None:
    try:
        await sync_rag_document(
            db,
            user_id=user_id,
            source_type=source_type,
            source_id=source_id,
            title=title,
            text=text,
            preferences=preferences,
            metadata=metadata,
        )
    except Exception as exc:
        LOGGER.warning(
            "Failed to sync rag document for evidence %s: %s",
            source_id,
            exc,
            exc_info=True,
        )


def _candidate_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[A-Za-z][A-Za-z0-9+.#-]{1,}", str(value or "").lower())
        if token not in {"and", "the", "with", "for", "using", "use", "skill", "skills"}
    }


def _count_phrase_occurrences(text: str, phrase: str) -> int:
    normalized_text = str(text or "")
    normalized_phrase = str(phrase or "").strip()
    if not normalized_text or not normalized_phrase:
        return 0
    if re.fullmatch(r"[A-Za-z0-9]+", normalized_phrase):
        pattern = rf"(?<![A-Za-z0-9]){re.escape(normalized_phrase)}(?![A-Za-z0-9])"
    else:
        pattern = re.escape(normalized_phrase)
    return len(re.findall(pattern, normalized_text, flags=re.IGNORECASE))


def _evidence_frequency(text: str, terms: list[str]) -> float:
    max_count = max((_count_phrase_occurrences(text, term) for term in terms if term), default=0)
    if max_count <= 0:
        return 0.0
    # Confidence must stay bounded even when a phrase is repeated many times.
    return round(min(1.0, max_count / 3.0), 4)


async def _semantic_similarity_to_terms(observed_text: str, canonical_terms: list[str], ai_preferences: dict | None = None) -> float:
    cleaned_terms = [str(term or "").strip() for term in canonical_terms if str(term or "").strip()]
    observed = str(observed_text or "").strip()
    if not observed or not cleaned_terms:
        return 0.0

    vectors, _provider = await embed_texts([observed, *cleaned_terms], preferences=ai_preferences)
    if len(vectors) != len(cleaned_terms) + 1:
        return 0.0

    observed_vec = vectors[0]
    semantic_similarity = max((cosine_similarity(observed_vec, vec) for vec in vectors[1:]), default=0.0)
    return round(max(0.0, min(1.0, semantic_similarity)), 4)


async def _compute_skill_confidence(text: str, observed_terms: list[str], canonical_terms: list[str], ai_preferences: dict | None = None) -> float:
    frequency = _evidence_frequency(text, [*observed_terms, *canonical_terms])
    semantic_similarity = await _semantic_similarity_to_terms(
        observed_terms[0] if observed_terms else "",
        canonical_terms or observed_terms,
        ai_preferences=ai_preferences,
    )
    return round(max(0.0, min(1.0, frequency * semantic_similarity)), 4)


async def _semantic_catalog_match(candidate_name: str, visible_skills: list[dict], ai_preferences: dict | None = None) -> tuple[dict | None, str | None]:
    candidate_tokens = _candidate_tokens(candidate_name)
    shortlist: list[tuple[dict, str, float]] = []
    strict_exact = should_use_strict_exact_match(candidate_name)
    for skill in visible_skills:
        names = [(skill.get("name") or "").strip()]
        names.extend(str(alias or "").strip() for alias in (skill.get("aliases") or []))
        for label in names:
            if not label:
                continue
            lexical_score = lexical_skill_similarity(candidate_name, label)
            if strict_exact:
                if lexical_score >= 1.0:
                    shortlist.append((skill, label, lexical_score))
                continue
            label_tokens = _candidate_tokens(label)
            token_overlap = len(candidate_tokens & label_tokens)
            overlap_ratio = token_overlap / max(1, len(candidate_tokens | label_tokens))
            combined_lexical = max(lexical_score, overlap_ratio)
            if combined_lexical >= 0.34:
                shortlist.append((skill, label, combined_lexical))

    shortlist.sort(key=lambda item: item[2], reverse=True)
    shortlist = shortlist[:20]
    if not shortlist:
        return None, None

    texts = [candidate_name] + [label for _skill, label, _score in shortlist]
    vectors, provider = await embed_texts(texts, preferences=ai_preferences)
    if len(vectors) != len(texts):
        return None, None

    candidate_vec = vectors[0]
    best_skill = None
    best_score = 0.0
    for (skill, _label, lexical_score), vec in zip(shortlist, vectors[1:], strict=False):
        semantic_score = cosine_similarity(candidate_vec, vec)
        combined_score = (semantic_score * 0.72) + (lexical_score * 0.28)
        if combined_score > best_score:
            best_score = combined_score
            best_skill = skill

    threshold = 0.98 if strict_exact else 0.56
    if best_skill is None or best_score < threshold:
        return None, provider
    return best_skill, provider


async def extract_skill_matches(db, text: str, ai_preferences: dict | None = None) -> list[dict]:
    visible_skills = await _load_visible_skill_catalog(db)
    return await extract_skill_matches_from_catalog(visible_skills, text, ai_preferences=ai_preferences)


async def _load_visible_skill_catalog(db) -> list[dict]:
    skills = await db["skills"].find({}, {"name": 1, "aliases": 1, "category": 1, "hidden": 1}).to_list(length=5000)
    return merge_skill_docs([skill for skill in skills if not is_hidden_skill(skill)])


async def extract_skill_matches_from_catalog(visible_skills: list[dict], text: str, ai_preferences: dict | None = None) -> list[dict]:
    text = sanitize_user_evidence_text(text)
    lowered = (text or "").lower()
    if not lowered:
        return []

    exact_index, term_index = build_canonical_skill_index(visible_skills)
    skill_by_id = {oid_str(skill.get("_id")): skill for skill in visible_skills}
    matches: dict[str, dict] = {}

    for skill in visible_skills:
        name = (skill.get("name") or "").strip()
        if not name:
            continue
        sid = oid_str(skill.get("_id"))
        candidates = [(name, "name")] + [((alias or "").strip(), "alias") for alias in (skill.get("aliases") or [])]
        best = None
        for token, matched_on in candidates:
            if not token:
                continue
            if matched_on == "alias" and should_use_strict_exact_match(token) and normalize_skill_text(token) != normalize_skill_text(name):
                continue
            pattern = rf"(?<![A-Za-z0-9]){re.escape(token.lower())}(?![A-Za-z0-9])"
            if re.search(pattern, lowered):
                best = matched_on
                break
        if best:
            canonical_terms = [token for token, _matched_on in candidates if token]
            confidence = await _compute_skill_confidence(
                lowered,
                observed_terms=[token for token, matched_on in candidates if matched_on == best][:1] or [name],
                canonical_terms=canonical_terms,
                ai_preferences=ai_preferences,
            )
            matches[sid] = {
                "skill_id": sid,
                "skill_name": name,
                "category": skill.get("category", ""),
                "matched_on": best,
                "confidence": confidence,
                "is_new": False,
            }

    ai_candidates, provider = await extract_skill_candidates(text, max_candidates=25, preferences=ai_preferences)

    for candidate in ai_candidates:
        candidate_name = str(candidate.get("name") or "").strip()
        if not candidate_name:
            continue
        candidate_key = normalize_skill_text(candidate_name)
        matched_skill = exact_index.get(candidate_key)
        matched_on = "ai-exact" if matched_skill is not None else None
        strict_exact = should_use_strict_exact_match(candidate_name)

        if matched_skill is None and not strict_exact:
            best_skill = None
            best_score = 0.0
            for skill_id, terms in term_index.items():
                for term in terms:
                    score = lexical_skill_similarity(candidate_key, term)
                    if score > best_score:
                        best_score = score
                        best_skill = skill_by_id.get(skill_id)
            if best_skill is not None and best_score >= 0.72:
                matched_skill = best_skill
                matched_on = "ai-lexical"
        if matched_skill is None:
            matched_skill, provider = await _semantic_catalog_match(candidate_name, visible_skills, ai_preferences=ai_preferences)
            if matched_skill is not None:
                matched_on = f"ai-transformer:{provider}"
        if matched_skill is not None:
            sid = oid_str(matched_skill.get("_id"))
            if sid not in matches:
                canonical_terms = canonical_skill_terms = [
                    str(matched_skill.get("name") or "").strip(),
                    *[str(alias or "").strip() for alias in (matched_skill.get("aliases") or [])],
                ]
                confidence = await _compute_skill_confidence(
                    lowered,
                    observed_terms=[candidate_name],
                    canonical_terms=canonical_skill_terms,
                    ai_preferences=ai_preferences,
                )
                matches[sid] = {
                    "skill_id": sid,
                    "skill_name": matched_skill.get("name", candidate_name),
                    "category": matched_skill.get("category", "") or candidate.get("category", ""),
                    "matched_on": matched_on or "ai-semantic",
                    "confidence": confidence,
                    "is_new": False,
                }
            continue

        if strict_exact:
            # Do not invent short/acronym skills like "ML" unless they resolve to the live catalog.
            continue

        synthetic_id = "candidate:" + sha1(candidate_name.lower().encode("utf-8")).hexdigest()[:12]
        confidence = await _compute_skill_confidence(
            lowered,
            observed_terms=[candidate_name],
            canonical_terms=[candidate_name],
            ai_preferences=ai_preferences,
        )
        matches[synthetic_id] = {
            "skill_id": synthetic_id,
            "skill_name": candidate_name,
            "category": str(candidate.get("category") or "").strip() or "General",
            "matched_on": f"ai-candidate:{provider}",
            "confidence": confidence,
            "is_new": True,
        }

    return sorted(matches.values(), key=lambda item: (item["skill_name"].lower(), item["skill_id"]))


def build_analysis_item(
    title: str,
    evidence_type: str,
    source: str,
    text: str,
    filename: str | None,
    extracted_skills: list[dict],
    manual_skill_ids: list[object],
    manual_skill_names: list[str],
    index: int,
) -> dict:
    key_source = filename or source or title or str(index)
    analysis_id = f"analysis:{sha1(f'{index}:{key_source}'.encode('utf-8')).hexdigest()[:12]}"
    extracted_skill_ids = normalize_skill_ids(
        [str(skill.get("skill_id") or "").strip() for skill in extracted_skills if not str(skill.get("skill_id") or "").startswith("candidate:")]
    )
    combined_skill_ids = [oid_str(value) for value in combine_skill_refs(extracted_skill_ids, manual_skill_ids)]
    return {
        "analysis_id": analysis_id,
        "title": title,
        "type": evidence_type,
        "source": source,
        "text_excerpt": make_excerpt(text),
        "filename": filename,
        "extracted_skills": extracted_skills,
        "skill_ids": combined_skill_ids,
        "extracted_skill_ids": [oid_str(value) for value in extracted_skill_ids],
        "manual_skill_ids": [oid_str(value) for value in manual_skill_ids],
        "manual_skill_names": manual_skill_names,
    }


@router.post("/analyze")
async def analyze_evidence(
    request: Request,
    title: str | None = Form(default=None),
    type: str = Form(default="project"),
    text: str | None = Form(default=None),
    url: str | None = Form(default=None),
    manual_skill_ids: str | None = Form(default=None),
    manual_skill_names: str | None = Form(default=None),
    file: UploadFile | None = File(default=None),
    files: list[UploadFile] | None = File(default=None),
    user=Depends(require_user),
):
    db = get_db()
    await enforce_rate_limit(
        db,
        scope="ai.evidence_analyze",
        identifier=build_rate_limit_identifier(request, user["_id"]),
        limit=AI_RATE_LIMITS["evidence_analyze"][0],
        window_seconds=AI_RATE_LIMITS["evidence_analyze"][1],
    )
    ai_preferences = normalize_ai_preferences((user or {}).get("ai_preferences"))
    visible_skills = await _load_visible_skill_catalog(db)
    resolved_manual_skill_ids, resolved_manual_skill_names = await resolve_manual_skill_ids(
        db,
        user,
        visible_skills,
        manual_skill_ids=parse_form_list(manual_skill_ids),
        manual_skill_names=parse_form_list(manual_skill_names),
    )
    upload_list = [upload for upload in (files or []) if upload is not None]
    if file is not None:
        upload_list.append(file)

    items: list[dict] = []
    manual_text = sanitize_user_evidence_text((text or "").strip())
    derived_url = str(url or "").strip()
    link_content = await derive_link_content(derived_url) if derived_url else {"title": "", "text_excerpt": "", "source_kind": ""}
    if manual_text or link_content.get("text_excerpt"):
        analysis_text = manual_text
        if link_content.get("text_excerpt"):
            analysis_text = sanitize_user_evidence_text(
                " ".join(part for part in [manual_text, link_content.get("title"), link_content.get("text_excerpt")] if part).strip()
            )
        extracted_skills = await extract_skill_matches_from_catalog(visible_skills, analysis_text, ai_preferences=ai_preferences)
        resolved_title = (title or "").strip() or str(link_content.get("title") or "").strip() or "Untitled Evidence"
        items.append(
            build_analysis_item(
                resolved_title,
                type,
                infer_source(derived_url, None),
                analysis_text,
                None,
                extracted_skills,
                resolved_manual_skill_ids,
                resolved_manual_skill_names,
                0,
            )
        )

    for index, upload in enumerate(upload_list, start=len(items)):
        filename = upload.filename or "upload"
        raw = await upload.read()
        if not raw:
            continue
        if len(raw) > MAX_EVIDENCE_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Evidence uploads must be 5 MB or smaller")
        extracted_text = extract_text_from_upload(filename, raw)
        if len(extracted_text.strip()) < 20:
            continue
        extracted_skills = await extract_skill_matches_from_catalog(visible_skills, extracted_text, ai_preferences=ai_preferences)
        resolved_title = os.path.splitext(filename)[0] or "Untitled Evidence"
        items.append(
            build_analysis_item(
                resolved_title,
                type,
                infer_source(None, filename),
                extracted_text,
                filename,
                extracted_skills,
                resolved_manual_skill_ids,
                resolved_manual_skill_names,
                index,
            )
        )

    if not items:
        raise HTTPException(status_code=400, detail="Provide at least 20 characters of evidence text, a supported link, or one or more supported files")

    return {
        "items": items,
        "user_id": oid_str(user["_id"]),
    }

@router.get("/", response_model=list[EvidenceOut])
async def list_evidence(
    user_email: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
    skill_id: str | None = Query(default=None),
    project_id: str | None = Query(default=None),
    origin: str | None = Query(default=None),
    user=Depends(require_user),
):
    db = get_db()
    effective_user_id = oid_str(user.get("_id"))
    if user_id and oid_str(user_id) != effective_user_id:
        raise HTTPException(status_code=403, detail="You can only list your own evidence")

    q: dict = ref_query("user_id", effective_user_id)
    if user_email:
        q["user_email"] = user_email
    if skill_id:
        q["skill_ids"] = {"$in": ref_values(skill_id)}
    if project_id:
        q.update(ref_query("project_id", project_id))
    if origin:
        q["origin"] = origin

    cursor = db["evidence"].find(
        q,
        {
            "user_email": 1,
            "user_id": 1,
            "type": 1,
            "title": 1,
            "source": 1,
            "text_excerpt": 1,
            "skill_ids": 1,
            "extracted_skill_ids": 1,
            "manual_skill_ids": 1,
            "manual_skill_names": 1,
            "project_id": 1,
            "tags": 1,
            "origin": 1,
            "created_at": 1,
            "updated_at": 1,
        },
    ).sort("created_at", -1)

    docs = await cursor.to_list(length=500)
    return [serialize_evidence(d) for d in docs]

# UC 1.3 – Add evidence artifact and associate it with a skill/project
@router.post("/", response_model=EvidenceOut)
async def create_evidence(payload: EvidenceIn, user=Depends(require_user)):
    db = get_db()
    ai_preferences = normalize_ai_preferences((user or {}).get("ai_preferences"))
    visible_skills = await _load_visible_skill_catalog(db)
    source = str(payload.source or "").strip()
    text_excerpt = sanitize_user_evidence_text(str(payload.text_excerpt or "").strip())
    link_content = {"title": "", "text_excerpt": "", "source_kind": ""}
    if is_http_url(source):
        link_content = await derive_link_content(source)
        if should_derive_text_from_source(text_excerpt, source):
            text_excerpt = sanitize_user_evidence_text(str(link_content.get("text_excerpt") or "").strip())
    if not text_excerpt:
        raise HTTPException(status_code=400, detail="Provide evidence text, upload-derived text, or a supported link that can be summarized")

    project_id = await require_owned_project_id(db, user, payload.project_id)

    extracted_skill_ids = normalize_skill_ids(payload.extracted_skill_ids)
    if not extracted_skill_ids:
        extracted_skill_ids = await extract_catalog_skill_ids(visible_skills, text_excerpt, ai_preferences=ai_preferences)
    extracted_skill_ids, manual_skill_ids, skill_ids, resolved_manual_skill_names = await resolve_evidence_payload_skills(
        db,
        user,
        visible_skills,
        legacy_skill_ids=payload.skill_ids,
        extracted_skill_ids=[oid_str(value) for value in extracted_skill_ids],
        manual_skill_ids=payload.manual_skill_ids,
        manual_skill_names=payload.manual_skill_names,
    )

    doc = {
        "user_email": payload.user_email,
        "type": payload.type,
        "title": str(payload.title or "").strip() or str(link_content.get("title") or "").strip() or (github_evidence_title(source) if is_github_url(source) else "Untitled Evidence"),
        "source": source,
        "text_excerpt": text_excerpt,
        "skill_ids": skill_ids,
        "extracted_skill_ids": extracted_skill_ids,
        "manual_skill_ids": manual_skill_ids,
        "manual_skill_names": resolved_manual_skill_names,
        "user_id": user["_id"],
        "project_id": project_id,
        "tags": payload.tags or [],
        "origin": payload.origin or "user",
        "created_at": now_utc(),
        "updated_at": now_utc(),
    }

    res = await db["evidence"].insert_one(doc)
    # Keep the retrieval index in sync with the persisted evidence text so job match
    # and tailoring can ground future generations on this exact document.
    await safe_sync_rag_document(
        db,
        user_id=oid_str(user["_id"]),
        source_type="evidence",
        source_id=oid_str(res.inserted_id),
        title=doc.get("title", ""),
        text=doc.get("text_excerpt", ""),
        preferences=ai_preferences,
        metadata={"evidence_type": doc.get("type", "other"), "origin": doc.get("origin", "user")},
    )
    await safe_increment_reward_counter(db, oid_str(user["_id"]), "evidence_saved")

    return EvidenceOut(
        **serialize_evidence({"_id": res.inserted_id, **doc}),
    )


@router.patch("/{evidence_id}", response_model=EvidenceOut)
async def patch_evidence(evidence_id: str, payload: EvidencePatch, user=Depends(require_user)):
    db = get_db()
    ai_preferences = normalize_ai_preferences((user or {}).get("ai_preferences"))

    try:
        evidence_oid = to_object_id(evidence_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid evidence_id")

    existing = await db["evidence"].find_one({"_id": evidence_oid})
    if not existing:
        raise HTTPException(status_code=404, detail="Evidence not found")

    if oid_str(existing.get("user_id")) != oid_str(user["_id"]):
        raise HTTPException(status_code=403, detail="You do not have access to this evidence")

    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided to update")

    visible_skills = await _load_visible_skill_catalog(db)
    source = str(updates.get("source", existing.get("source")) or "").strip()
    text_excerpt = sanitize_user_evidence_text(str(updates.get("text_excerpt", existing.get("text_excerpt")) or "").strip())
    if is_http_url(source) and should_derive_text_from_source(text_excerpt, source):
        link_content = await derive_link_content(source)
        if link_content.get("text_excerpt"):
            text_excerpt = sanitize_user_evidence_text(str(link_content.get("text_excerpt") or "").strip())
            updates["text_excerpt"] = text_excerpt
        if not str(updates.get("title") or "").strip() and not str(existing.get("title") or "").strip():
            updates["title"] = str(link_content.get("title") or "").strip() or github_evidence_title(source)
    elif "text_excerpt" in updates:
        updates["text_excerpt"] = text_excerpt

    if "extracted_skill_ids" in updates or "manual_skill_ids" in updates or "manual_skill_names" in updates or "skill_ids" in updates or "text_excerpt" in updates or "source" in updates:
        extracted_input = updates.get("extracted_skill_ids")
        if extracted_input is None:
            extracted_input = [oid_str(value) for value in (existing.get("extracted_skill_ids") or [])]
            if ("text_excerpt" in updates or "source" in updates) and text_excerpt:
                extracted_input = [oid_str(value) for value in await extract_catalog_skill_ids(visible_skills, text_excerpt, ai_preferences=ai_preferences)]

        manual_input = updates.get("manual_skill_ids")
        if manual_input is None and ("manual_skill_names" in updates or "skill_ids" in updates):
            manual_input = updates.get("skill_ids") or [oid_str(value) for value in (existing.get("manual_skill_ids") or existing.get("skill_ids") or [])]
        elif manual_input is None:
            manual_input = [oid_str(value) for value in (existing.get("manual_skill_ids") or existing.get("skill_ids") or [])]

        manual_names_input = updates.get("manual_skill_names")
        if manual_names_input is None:
            manual_names_input = existing.get("manual_skill_names") or []

        extracted_skill_ids, manual_skill_ids, combined_skill_ids, resolved_manual_skill_names = await resolve_evidence_payload_skills(
            db,
            user,
            visible_skills,
            legacy_skill_ids=[],
            extracted_skill_ids=extracted_input,
            manual_skill_ids=manual_input,
            manual_skill_names=manual_names_input,
        )
        updates["extracted_skill_ids"] = extracted_skill_ids
        updates["manual_skill_ids"] = manual_skill_ids
        updates["manual_skill_names"] = resolved_manual_skill_names
        updates["skill_ids"] = combined_skill_ids

    if "skill_ids" in updates and "manual_skill_ids" not in updates and "extracted_skill_ids" not in updates:
        updates["skill_ids"] = normalize_skill_ids(updates.get("skill_ids") or [])
    if "project_id" in updates:
        updates["project_id"] = await require_owned_project_id(db, user, updates["project_id"])

    updates["updated_at"] = now_utc()
    await db["evidence"].update_one({"_id": evidence_oid}, {"$set": updates})

    updated = await db["evidence"].find_one({"_id": evidence_oid})
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to load updated evidence")

    # Evidence edits must immediately change retrieval results; re-indexing here keeps
    # the derived rag_chunks collection aligned with the canonical evidence record.
    await safe_sync_rag_document(
        db,
        user_id=oid_str(user["_id"]),
        source_type="evidence",
        source_id=evidence_id,
        title=updated.get("title", ""),
        text=updated.get("text_excerpt", ""),
        preferences=ai_preferences,
        metadata={"evidence_type": updated.get("type", "other"), "origin": updated.get("origin", "user")},
    )

    return EvidenceOut(**serialize_evidence(updated))


@router.delete("/{evidence_id}")
async def delete_evidence(evidence_id: str, user=Depends(require_user)):
    db = get_db()

    try:
        evidence_oid = to_object_id(evidence_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid evidence_id")

    existing = await db["evidence"].find_one({"_id": evidence_oid}, {"user_id": 1, "title": 1, "skill_ids": 1})
    if not existing:
        raise HTTPException(status_code=404, detail="Evidence not found")

    if oid_str(existing.get("user_id")) != oid_str(user["_id"]):
        raise HTTPException(status_code=403, detail="You do not have access to this evidence")

    skill_ids = list(existing.get("skill_ids") or [])
    await db["evidence"].delete_one({"_id": evidence_oid})

    removed_skill_ids: list[str] = []
    if skill_ids:
        remaining_skill_ids = set(
            oid_str(value)
            for value in await db["evidence"].distinct(
                "skill_ids",
                {"user_id": {"$in": ref_values(user["_id"])}, "origin": "user"},
            )
        )
        removable = [sid for sid in skill_ids if oid_str(sid) not in remaining_skill_ids]
        if removable:
            removable_refs: list[object] = []
            for sid in removable:
                removable_refs.extend(ref_values(sid))
            await db["resume_skill_confirmations"].update_many(
                {"user_id": {"$in": ref_values(user["_id"])}},
                {
                    "$pull": {
                        "confirmed": {"skill_id": {"$in": removable_refs}},
                        "rejected": {"skill_id": {"$in": removable_refs}},
                    }
                },
            )
            removed_skill_ids = [oid_str(sid) for sid in removable]

            # If a removed skill is a user-created custom skill with no remaining evidence
            # and no remaining profile confirmation, delete the orphaned skill record too.
            for sid in removable:
                skill_doc = await db["skills"].find_one(
                    {"_id": {"$in": ref_values(sid)}},
                    {"created_by_user_id": 1},
                )
                if not skill_doc:
                    continue
                if oid_str(skill_doc.get("created_by_user_id")) != oid_str(user["_id"]):
                    continue

                still_confirmed = await db["resume_skill_confirmations"].find_one(
                    {
                        "user_id": {"$in": ref_values(user["_id"])},
                        "confirmed.skill_id": {"$in": ref_values(sid)},
                    },
                    {"_id": 1},
                )
                if still_confirmed:
                    continue

                still_in_evidence = await db["evidence"].find_one(
                    {
                        "user_id": {"$in": ref_values(user["_id"])},
                        "skill_ids": {"$in": ref_values(sid)},
                    },
                    {"_id": 1},
                )
                if still_in_evidence:
                    continue

                await db["skills"].delete_one({"_id": {"$in": ref_values(sid)}})

    # Delete the derived retrieval rows after the source evidence is removed.
    await delete_rag_document(
        db,
        user_id=oid_str(user["_id"]),
        source_type="evidence",
        source_id=evidence_id,
    )

    return {
        "ok": True,
        "id": evidence_id,
        "title": existing.get("title", "Evidence"),
        "removed_skill_ids": removed_skill_ids,
    }
