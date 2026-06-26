"""Lightweight Mongo-call mocks for isolated unit tests.

StubCollection/StubDatabase do NOT simulate Mongo query semantics (that's
what tests/fake_mongo.py is for, used by the route-level integration tests).
Instead every method is an unittest.mock.AsyncMock/MagicMock whose return
value a test configures explicitly. This keeps the tests under tests/unit/
true unit tests: they assert that a function under test calls Mongo the way
it should and reacts correctly to whatever Mongo hands back, without caring
how a real (or fake) database would actually answer a query.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


class StubCursor:
    """Chainable stand-in for the cursor returned by find()/aggregate()."""

    def __init__(self, docs: list[dict] | None = None):
        self._docs = list(docs or [])

    def sort(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def skip(self, *_args, **_kwargs):
        return self

    async def to_list(self, length: int | None = None):
        if length is None:
            return list(self._docs)
        return list(self._docs[:length])

    def __aiter__(self):
        self._iter = iter(list(self._docs))
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


class StubCollection:
    """A Mongo collection double with one AsyncMock/MagicMock per method.

    Tests configure behavior directly, e.g.:
        db["jobs"].find_one.return_value = {...}
        db["jobs"].set_find_results([{...}, {...}])
        db["jobs"].count_documents.return_value = 3
    and assert on calls via db["jobs"].update_one.call_args / await_args.
    """

    def __init__(self, name: str = "stub"):
        self.name = name
        self.find = MagicMock(return_value=StubCursor([]))
        self.aggregate = MagicMock(return_value=StubCursor([]))
        self.find_one = AsyncMock(return_value=None)
        self.insert_one = AsyncMock(return_value=MagicMock(inserted_id=None))
        self.update_one = AsyncMock(return_value=MagicMock(matched_count=1, modified_count=1, upserted_id=None))
        self.update_many = AsyncMock(return_value=MagicMock(matched_count=0, modified_count=0))
        self.delete_one = AsyncMock(return_value=MagicMock(deleted_count=0))
        self.delete_many = AsyncMock(return_value=MagicMock(deleted_count=0))
        self.count_documents = AsyncMock(return_value=0)
        self.distinct = AsyncMock(return_value=[])
        self.create_index = AsyncMock(return_value=None)

    def set_find_results(self, docs: list[dict]) -> None:
        self.find = MagicMock(return_value=StubCursor(docs))

    def set_aggregate_results(self, docs: list[dict]) -> None:
        self.aggregate = MagicMock(return_value=StubCursor(docs))


class StubDatabase:
    """A dict-like Mongo database double; `db["collection"]` lazily creates a StubCollection."""

    def __init__(self):
        self._collections: dict[str, StubCollection] = {}

    def __getitem__(self, name: str) -> StubCollection:
        if name not in self._collections:
            self._collections[name] = StubCollection(name)
        return self._collections[name]


@pytest.fixture()
def stub_db() -> StubDatabase:
    return StubDatabase()
