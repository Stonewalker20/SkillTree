"""Local retrieval helpers that chunk user documents, persist embeddings, and rank relevant evidence snippets for RAG workflows."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Iterable

from app.utils.ai import cosine_similarity, embed_texts, normalize_ai_preferences
from app.utils.mongo import oid_str, ref_values, to_object_id


_RAG_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "your", "will", "have", "has", "into",
    "using", "used", "their", "they", "them", "must", "plus", "able", "work", "team", "role",
    "more", "less", "some", "many", "each", "make", "made", "over", "under", "than", "then",
}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _clean_text(text: str) -> str:
    value = str(text or "")
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _tokenize_for_retrieval(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[A-Za-z][A-Za-z0-9+.#-]{1,}", _clean_text(text).lower())
        if token not in _RAG_STOPWORDS
    }


def _lexical_overlap_score(query_text: str, candidate_text: str) -> float:
    query_tokens = _tokenize_for_retrieval(query_text)
    candidate_tokens = _tokenize_for_retrieval(candidate_text)
    if not query_tokens or not candidate_tokens:
        return 0.0

    overlap = query_tokens & candidate_tokens
    if not overlap:
        return 0.0

    coverage = len(overlap) / len(query_tokens)
    density = len(overlap) / len(candidate_tokens)
    return round((coverage * 0.8) + (density * 0.2), 4)


def split_text_into_chunks(text: str, chunk_size: int = 500, overlap: int = 80) -> list[str]:
    # Retrieval quality is much better when we embed focused slices of text instead of
    # entire documents. This chunker keeps enough overlap that context near a chunk
    # boundary is still retrievable in one piece.
    cleaned = _clean_text(text)
    if not cleaned:
        return []
    words = cleaned.split()
    if not words:
        return []
    chunk_size = max(80, int(chunk_size))
    overlap = max(0, min(int(overlap), chunk_size // 2))
    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = min(len(words), start + chunk_size)
        chunk = " ".join(words[start:end]).strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(words):
            break
        start = max(start + 1, end - overlap)
    return chunks


async def sync_rag_document(
    db,
    *,
    user_id: str,
    source_type: str,
    source_id: str,
    title: str,
    text: str,
    preferences: dict | None = None,
    metadata: dict | None = None,
) -> int:
    # Re-index the full source document on every write so retrieval stays consistent
    # with the user-visible evidence/resume record. That keeps the contract simple:
    # the source of truth is the main collection, and rag_chunks is a derived index.
    prefs = normalize_ai_preferences(preferences)
    source_oid = to_object_id(source_id)
    user_oid = to_object_id(user_id)
    await db["rag_chunks"].delete_many(
        {
            "user_id": {"$in": ref_values(user_id)},
            "source_type": source_type,
            "source_id": source_oid,
        }
    )

    chunks = split_text_into_chunks(text)
    if not chunks:
        return 0

    vectors, provider = await embed_texts(chunks, preferences=prefs)
    now = now_utc()
    count = 0
    for index, (chunk, vector) in enumerate(zip(chunks, vectors)):
        await db["rag_chunks"].insert_one(
            {
                "user_id": user_oid,
                "source_type": source_type,
                "source_id": source_oid,
                "title": _clean_text(title) or source_type.title(),
                "text": chunk,
                "chunk_index": index,
                "embedding": list(vector or []),
                "embedding_provider": provider,
                "metadata": metadata or {},
                "created_at": now,
                "updated_at": now,
            }
        )
        count += 1
    return count


async def delete_rag_document(db, *, user_id: str, source_type: str, source_id: str) -> int:
    result = await db["rag_chunks"].delete_many(
        {
            "user_id": {"$in": ref_values(user_id)},
            "source_type": source_type,
            "source_id": {"$in": ref_values(source_id)},
        }
    )
    return int(result.deleted_count or 0)


async def retrieve_rag_context(
    db,
    *,
    user_id: str,
    query_text: str,
    preferences: dict | None = None,
    limit: int = 5,
    source_types: Iterable[str] | None = None,
) -> list[dict]:
    # Retrieval is intentionally kept local and simple: fetch the user's indexed chunks,
    # embed the query once, then rank by cosine similarity. That avoids introducing a
    # separate vector database while keeping the grounding path inspectable.
    query = _clean_text(query_text)
    if not query:
        return []
    prefs = normalize_ai_preferences(preferences)
    search: dict = {"user_id": {"$in": ref_values(user_id)}}
    allowed_source_types = [str(value or "").strip() for value in (source_types or []) if str(value or "").strip()]
    if allowed_source_types:
        search["source_type"] = {"$in": allowed_source_types}
    docs = await db["rag_chunks"].find(search).to_list(length=2000)
    if not docs:
        return []

    query_vectors, provider = await embed_texts([query], preferences=prefs)
    if not query_vectors:
        return []
    query_vec = query_vectors[0]

    ranked: list[dict] = []
    for doc in docs:
        vector = list(doc.get("embedding") or [])
        score = cosine_similarity(query_vec, vector) if vector else 0.0
        provider_name = provider
        if score <= 0:
            score = _lexical_overlap_score(query, f"{doc.get('title') or ''} {doc.get('text') or ''}")
            provider_name = "lexical-overlap"
        if score <= 0:
            continue
        ranked.append(
            {
                "source_type": str(doc.get("source_type") or ""),
                "source_id": oid_str(doc.get("source_id")),
                "title": _clean_text(doc.get("title") or ""),
                "snippet": _clean_text(doc.get("text") or ""),
                "score": round(float(score), 4),
                "chunk_index": int(doc.get("chunk_index") or 0),
                "provider": provider_name,
                "metadata": doc.get("metadata") or {},
            }
        )

    ranked.sort(key=lambda item: (-item["score"], item["title"].lower(), item["chunk_index"]))
    deduped: list[dict] = []
    seen: set[tuple[str, str, int]] = set()
    for item in ranked:
        # One stored chunk should appear at most once in the final context list.
        key = (item["source_type"], item["source_id"], item["chunk_index"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= max(1, int(limit)):
            break
    return deduped
