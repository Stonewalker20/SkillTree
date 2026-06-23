"""Unit tests for app/utils/rag.py.

All Mongo calls go through `stub_db`. The only third-party-model-backed
dependency, `embed_texts` (imported from app.utils.ai), is monkeypatched on
every test that would otherwise invoke it so no transformer ever loads.
`cosine_similarity` and `normalize_ai_preferences` are left as the real,
pure, dependency-free functions from ai.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from bson import ObjectId

from app.utils import rag
from app.utils.mongo import ref_values, to_object_id


FIXED_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_now_utc_returns_utc_aware_datetime():
    result = rag.now_utc()
    assert isinstance(result, datetime)
    assert result.tzinfo is timezone.utc


def test_clean_text_collapses_whitespace_and_strips():
    assert rag._clean_text("  a   b\n\tc  ") == "a b c"


def test_clean_text_handles_none():
    assert rag._clean_text(None) == ""


def test_tokenize_for_retrieval_drops_single_char_tokens_and_stopwords():
    tokens = rag._tokenize_for_retrieval("The Quick Brown Fox and the lazy dog")
    assert tokens == {"quick", "brown", "fox", "lazy", "dog"}


def test_tokenize_for_retrieval_keeps_symbol_heavy_tech_tokens():
    tokens = rag._tokenize_for_retrieval("Python, C++, ASP.NET, Go, I am a dev")
    assert tokens == {"python", "c++", "asp.net", "go", "am", "dev"}


def test_lexical_overlap_score_returns_zero_when_either_side_has_no_tokens():
    assert rag._lexical_overlap_score("", "python fastapi") == 0.0
    assert rag._lexical_overlap_score("python", "") == 0.0


def test_lexical_overlap_score_returns_zero_when_no_overlap():
    assert rag._lexical_overlap_score("python fastapi", "completely unrelated topic") == 0.0


def test_lexical_overlap_score_weights_coverage_and_density():
    score = rag._lexical_overlap_score(
        "python fastapi backend", "I used python and fastapi for the backend service"
    )
    assert score == 0.95


# --------------------------------------------------------------------------
# split_text_into_chunks
# --------------------------------------------------------------------------


def test_split_text_into_chunks_returns_empty_for_blank_text():
    assert rag.split_text_into_chunks("   ") == []


def test_split_text_into_chunks_single_chunk_when_short():
    assert rag.split_text_into_chunks("hello world", chunk_size=100, overlap=20) == ["hello world"]


def test_split_text_into_chunks_splits_with_overlap_for_long_text():
    text = " ".join(f"word{i}" for i in range(300))
    chunks = rag.split_text_into_chunks(text, chunk_size=100, overlap=20)
    assert len(chunks) == 4
    assert chunks[0].split()[0] == "word0"
    assert chunks[0].split()[-1] == "word99"
    assert chunks[1].split()[0] == "word80"  # next chunk starts 20 words back from the prior end
    assert chunks[-1].split()[-1] == "word299"


def test_split_text_into_chunks_clamps_chunk_size_to_minimum_of_80():
    text = " ".join(f"w{i}" for i in range(50))
    chunks = rag.split_text_into_chunks(text, chunk_size=10, overlap=5)
    assert len(chunks) == 1
    assert len(chunks[0].split()) == 50


# --------------------------------------------------------------------------
# sync_rag_document
# --------------------------------------------------------------------------


async def test_sync_rag_document_deletes_existing_chunks_before_reinserting(stub_db, monkeypatch):
    monkeypatch.setattr(rag, "now_utc", lambda: FIXED_NOW)
    monkeypatch.setattr(rag, "embed_texts", AsyncMock(return_value=([[0.1, 0.2]], "mock-provider")))

    user_id = str(ObjectId())
    source_id = str(ObjectId())

    count = await rag.sync_rag_document(
        stub_db,
        user_id=user_id,
        source_type="evidence",
        source_id=source_id,
        title="My Title",
        text="hello world",
    )

    assert count == 1
    stub_db["rag_chunks"].delete_many.assert_called_once_with(
        {
            "user_id": {"$in": ref_values(user_id)},
            "source_type": "evidence",
            "source_id": to_object_id(source_id),
        }
    )
    stub_db["rag_chunks"].insert_one.assert_called_once()
    inserted = stub_db["rag_chunks"].insert_one.call_args.args[0]
    assert inserted["title"] == "My Title"
    assert inserted["text"] == "hello world"
    assert inserted["chunk_index"] == 0
    assert inserted["embedding"] == [0.1, 0.2]
    assert inserted["embedding_provider"] == "mock-provider"
    assert inserted["metadata"] == {}
    assert inserted["created_at"] == FIXED_NOW
    assert inserted["source_id"] == to_object_id(source_id)


async def test_sync_rag_document_returns_zero_and_skips_embedding_when_text_blank(stub_db, monkeypatch):
    fake_embed = AsyncMock(return_value=([], "mock-provider"))
    monkeypatch.setattr(rag, "embed_texts", fake_embed)

    count = await rag.sync_rag_document(
        stub_db,
        user_id=str(ObjectId()),
        source_type="evidence",
        source_id=str(ObjectId()),
        title="Title",
        text="   ",
    )

    assert count == 0
    fake_embed.assert_not_called()
    stub_db["rag_chunks"].insert_one.assert_not_called()
    stub_db["rag_chunks"].delete_many.assert_called_once()


async def test_sync_rag_document_blank_title_falls_back_to_capitalized_source_type(stub_db, monkeypatch):
    monkeypatch.setattr(rag, "now_utc", lambda: FIXED_NOW)
    monkeypatch.setattr(rag, "embed_texts", AsyncMock(return_value=([[0.0]], "mock-provider")))

    await rag.sync_rag_document(
        stub_db,
        user_id=str(ObjectId()),
        source_type="evidence",
        source_id=str(ObjectId()),
        title="   ",
        text="hello",
    )

    inserted = stub_db["rag_chunks"].insert_one.call_args.args[0]
    assert inserted["title"] == "Evidence"


async def test_sync_rag_document_inserts_one_doc_per_chunk(stub_db, monkeypatch):
    monkeypatch.setattr(rag, "now_utc", lambda: FIXED_NOW)
    # sync_rag_document chunks with the library defaults (chunk_size=500,
    # overlap=80), so use the same defaults here to know how many chunks
    # to expect; 1200 words yields 3 chunks under those defaults.
    text = " ".join(f"word{i}" for i in range(1200))
    chunks = rag.split_text_into_chunks(text)
    assert len(chunks) == 3
    fake_vectors = [[float(i)] for i in range(len(chunks))]
    monkeypatch.setattr(rag, "embed_texts", AsyncMock(return_value=(fake_vectors, "mock-provider")))

    count = await rag.sync_rag_document(
        stub_db,
        user_id=str(ObjectId()),
        source_type="evidence",
        source_id=str(ObjectId()),
        title="Title",
        text=text,
        metadata={"k": "v"},
    )

    assert count == len(chunks) == stub_db["rag_chunks"].insert_one.await_count
    last_call_doc = stub_db["rag_chunks"].insert_one.call_args.args[0]
    assert last_call_doc["chunk_index"] == len(chunks) - 1
    assert last_call_doc["metadata"] == {"k": "v"}


# --------------------------------------------------------------------------
# delete_rag_document
# --------------------------------------------------------------------------


async def test_delete_rag_document_builds_expected_filter_and_returns_count(stub_db):
    user_id = str(ObjectId())
    source_id = str(ObjectId())
    stub_db["rag_chunks"].delete_many.return_value = MagicMock(deleted_count=3)

    result = await rag.delete_rag_document(stub_db, user_id=user_id, source_type="evidence", source_id=source_id)

    assert result == 3
    stub_db["rag_chunks"].delete_many.assert_called_once_with(
        {
            "user_id": {"$in": ref_values(user_id)},
            "source_type": "evidence",
            "source_id": {"$in": ref_values(source_id)},
        }
    )


async def test_delete_rag_document_returns_zero_when_deleted_count_is_none(stub_db):
    stub_db["rag_chunks"].delete_many.return_value = MagicMock(deleted_count=None)

    result = await rag.delete_rag_document(
        stub_db, user_id=str(ObjectId()), source_type="evidence", source_id=str(ObjectId())
    )

    assert result == 0


# --------------------------------------------------------------------------
# retrieve_rag_context
# --------------------------------------------------------------------------


async def test_retrieve_rag_context_returns_empty_for_blank_query(stub_db):
    result = await rag.retrieve_rag_context(stub_db, user_id=str(ObjectId()), query_text="   ")
    assert result == []
    stub_db["rag_chunks"].find.assert_not_called()


async def test_retrieve_rag_context_returns_empty_when_no_stored_chunks(stub_db, monkeypatch):
    stub_db["rag_chunks"].set_find_results([])
    monkeypatch.setattr(rag, "embed_texts", AsyncMock(return_value=([[1.0, 0.0]], "mock-provider")))

    result = await rag.retrieve_rag_context(stub_db, user_id=str(ObjectId()), query_text="python")
    assert result == []


async def test_retrieve_rag_context_returns_empty_when_query_embedding_is_empty(stub_db, monkeypatch):
    stub_db["rag_chunks"].set_find_results([{"title": "x", "text": "y", "embedding": [1.0]}])
    monkeypatch.setattr(rag, "embed_texts", AsyncMock(return_value=([], "mock-provider")))

    result = await rag.retrieve_rag_context(stub_db, user_id=str(ObjectId()), query_text="python")
    assert result == []


async def test_retrieve_rag_context_ranks_by_cosine_similarity_and_filters_low_score(stub_db, monkeypatch):
    source_a, source_b = ObjectId(), ObjectId()
    stub_db["rag_chunks"].set_find_results(
        [
            {
                "source_type": "evidence",
                "source_id": source_a,
                "title": "Python Project",
                "text": "Built with Python and FastAPI",
                "embedding": [1.0, 0.0],
                "chunk_index": 0,
            },
            {
                "source_type": "evidence",
                "source_id": source_b,
                "title": "Unrelated",
                "text": "Something else entirely",
                "embedding": [0.0, 1.0],
                "chunk_index": 0,
            },
        ]
    )
    monkeypatch.setattr(rag, "embed_texts", AsyncMock(return_value=([[1.0, 0.0]], "mock-provider")))

    result = await rag.retrieve_rag_context(stub_db, user_id=str(ObjectId()), query_text="python fastapi")

    assert len(result) == 1
    assert result[0]["title"] == "Python Project"
    assert result[0]["score"] == 1.0
    assert result[0]["provider"] == "mock-provider"


async def test_retrieve_rag_context_falls_back_to_lexical_overlap_when_no_embedding(stub_db, monkeypatch):
    source_id = ObjectId()
    stub_db["rag_chunks"].set_find_results(
        [
            {
                "source_type": "evidence",
                "source_id": source_id,
                "title": "Python Project",
                "text": "Built with Python and FastAPI",
                "embedding": [],
                "chunk_index": 0,
            }
        ]
    )
    monkeypatch.setattr(rag, "embed_texts", AsyncMock(return_value=([[1.0, 0.0]], "mock-provider")))

    result = await rag.retrieve_rag_context(stub_db, user_id=str(ObjectId()), query_text="python fastapi")

    assert len(result) == 1
    assert result[0]["provider"] == "lexical-overlap"


async def test_retrieve_rag_context_passes_source_type_filter_when_given(stub_db, monkeypatch):
    stub_db["rag_chunks"].set_find_results([])
    monkeypatch.setattr(rag, "embed_texts", AsyncMock(return_value=([[1.0, 0.0]], "mock-provider")))

    await rag.retrieve_rag_context(
        stub_db, user_id="user-1", query_text="python", source_types=["evidence", "resume"]
    )

    called_filter = stub_db["rag_chunks"].find.call_args.args[0]
    assert called_filter["source_type"] == {"$in": ["evidence", "resume"]}


async def test_retrieve_rag_context_dedupes_same_chunk_and_respects_limit(stub_db, monkeypatch):
    source_id = ObjectId()
    # Two stored docs that resolve to the exact same (source_type, source_id,
    # chunk_index) key should collapse to a single result in the output.
    stub_db["rag_chunks"].set_find_results(
        [
            {
                "source_type": "evidence",
                "source_id": source_id,
                "title": "Python Project",
                "text": "python",
                "embedding": [1.0, 0.0],
                "chunk_index": 0,
            },
            {
                "source_type": "evidence",
                "source_id": source_id,
                "title": "Python Project",
                "text": "python",
                "embedding": [1.0, 0.0],
                "chunk_index": 0,
            },
        ]
    )
    monkeypatch.setattr(rag, "embed_texts", AsyncMock(return_value=([[1.0, 0.0]], "mock-provider")))

    result = await rag.retrieve_rag_context(stub_db, user_id=str(ObjectId()), query_text="python", limit=5)

    assert len(result) == 1
