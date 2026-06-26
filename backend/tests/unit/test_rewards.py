"""Unit tests for app/utils/rewards.py, mocking every Mongo call via stub_db."""

from __future__ import annotations

from datetime import datetime, timezone

from bson import ObjectId

from app.utils import rewards
from app.utils.rewards import (
    REWARD_COUNTER_KEYS,
    build_reward_achievements,
    build_reward_badges,
    calculate_reward_counters,
    empty_reward_counters,
    get_or_create_reward_doc,
    increment_reward_counter,
    normalize_reward_counters,
    normalize_unlock_records,
    refresh_reward_doc,
    reward_progress_counts,
    safe_increment_reward_counter,
    safe_sync_reward_counter,
    sync_reward_counter,
)

from .conftest import StubCursor


def test_empty_reward_counters_has_all_keys_zero():
    counters = empty_reward_counters()
    assert set(counters.keys()) == set(REWARD_COUNTER_KEYS)
    assert all(value == 0 for value in counters.values())


def test_normalize_reward_counters_handles_non_dict_input():
    assert normalize_reward_counters(None) == empty_reward_counters()
    assert normalize_reward_counters("garbage") == empty_reward_counters()


def test_normalize_reward_counters_clamps_negative_and_invalid_values():
    raw = {"evidence_saved": -5, "job_matches_run": "not-a-number", "profile_skills_confirmed": 7}
    result = normalize_reward_counters(raw)
    assert result["evidence_saved"] == 0
    assert result["job_matches_run"] == 0
    assert result["profile_skills_confirmed"] == 7


def test_normalize_unlock_records_filters_entries_without_key():
    raw = [{"key": "evidence_saved:bronze", "progress_value": 2}, {"progress_value": 9}, "not-a-dict"]
    result = normalize_unlock_records(raw)
    assert len(result) == 1
    assert result[0]["key"] == "evidence_saved:bronze"
    assert result[0]["progress_value"] == 2


def test_normalize_unlock_records_returns_empty_for_non_list():
    assert normalize_unlock_records(None) == []
    assert normalize_unlock_records({"key": "x"}) == []


def test_build_reward_achievements_zero_progress_is_locked():
    counters = empty_reward_counters()
    achievements = build_reward_achievements(counters)
    first = next(a for a in achievements if a["key"] == "evidence_saved")
    assert first["unlocked"] is False
    assert first["current_tier"] is None
    assert first["tier"] == "bronze"
    assert first["target_value"] == 1
    assert first["progress_pct"] == 0.0


def test_build_reward_achievements_max_progress_reaches_master_tier():
    counters = empty_reward_counters()
    counters["evidence_saved"] = 15
    achievements = build_reward_achievements(counters)
    first = next(a for a in achievements if a["key"] == "evidence_saved")
    assert first["unlocked"] is True
    assert first["current_tier"] == "master"
    assert first["next_tier"] is None
    assert first["progress_pct"] == 100.0


def test_build_reward_achievements_uses_unlocked_lookup_timestamp():
    fixed_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    counters = empty_reward_counters()
    counters["evidence_saved"] = 1
    achievements = build_reward_achievements(
        counters, unlocked_lookup={"evidence_saved:bronze": fixed_time}
    )
    first = next(a for a in achievements if a["key"] == "evidence_saved")
    bronze_step = next(step for step in first["tier_progress"] if step["tier"] == "bronze")
    assert bronze_step["unlocked"] is True
    assert bronze_step["unlocked_at"] == fixed_time


def test_build_reward_achievements_default_unlocked_at_when_no_lookup_entry():
    default_time = datetime(2026, 6, 22, tzinfo=timezone.utc)
    counters = empty_reward_counters()
    counters["evidence_saved"] = 1
    achievements = build_reward_achievements(counters, default_unlocked_at=default_time)
    first = next(a for a in achievements if a["key"] == "evidence_saved")
    bronze_step = next(step for step in first["tier_progress"] if step["tier"] == "bronze")
    assert bronze_step["unlocked_at"] == default_time


def test_reward_progress_counts_aggregates_unlock_totals():
    counters = empty_reward_counters()
    counters["evidence_saved"] = 15  # masters one badge fully
    achievements = build_reward_achievements(counters)
    summary = reward_progress_counts(achievements)
    assert summary["total_count"] == len(achievements)
    assert summary["unlocked_count"] == 1
    assert summary["mastered_badge_count"] == 1
    assert summary["tier_step_unlocked_count"] == 7  # all 7 tiers for that one badge
    assert summary["completion_pct"] > 0.0


def test_reward_progress_counts_zero_total_steps_returns_zero_pct():
    summary = reward_progress_counts([])
    assert summary["completion_pct"] == 0.0
    assert summary["total_count"] == 0


def test_build_reward_badges_returns_independent_copies():
    counters = empty_reward_counters()
    achievements = build_reward_achievements(counters)
    badges = build_reward_badges(achievements)
    assert badges == achievements
    badges[0]["title"] = "Mutated"
    assert achievements[0]["title"] != "Mutated"


async def test_calculate_reward_counters_combines_all_collections(stub_db):
    skill_a, skill_b = ObjectId(), ObjectId()

    stub_db["evidence"].count_documents.side_effect = [4, 1]
    stub_db["resume_skill_confirmations"].aggregate.side_effect = [
        StubCursor([{"n": 3}]),
        StubCursor([{"_id": skill_a}, {"_id": skill_b}]),
    ]
    stub_db["skills"].set_find_results(
        [
            {"_id": skill_a, "category": "Programming", "categories": []},
            {"_id": skill_b, "category": "", "categories": ["Data", "AI"]},
        ]
    )
    stub_db["resume_snapshots"].count_documents.return_value = 2
    stub_db["job_match_runs"].count_documents.return_value = 5
    stub_db["tailored_resumes"].count_documents.return_value = 7

    result = await calculate_reward_counters(stub_db, str(ObjectId()))

    assert result == {
        "evidence_saved": 4,
        "profile_skills_confirmed": 3,
        "skill_categories_covered": 3,
        "resume_snapshots_uploaded": 3,
        "job_matches_run": 5,
        "tailored_resumes_generated": 7,
    }


async def test_get_or_create_reward_doc_creates_when_missing(stub_db, monkeypatch):
    user_id = str(ObjectId())
    stub_db["user_rewards"].find_one.return_value = None
    fake_counters = normalize_reward_counters({"evidence_saved": 2})

    async def fake_calculate(_db, _user_id):
        return fake_counters

    monkeypatch.setattr(rewards, "calculate_reward_counters", fake_calculate)

    result = await get_or_create_reward_doc(stub_db, user_id)

    assert result["counters"] == fake_counters
    stub_db["user_rewards"].update_one.assert_called_once()


async def test_get_or_create_reward_doc_returns_existing_when_already_normalized(stub_db, monkeypatch):
    existing = {"user_id": ObjectId(), "counters": empty_reward_counters()}
    stub_db["user_rewards"].find_one.return_value = existing

    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("calculate_reward_counters should not be called when doc already exists")

    monkeypatch.setattr(rewards, "calculate_reward_counters", fail_if_called)

    result = await get_or_create_reward_doc(stub_db, str(ObjectId()))

    assert result is existing
    stub_db["user_rewards"].update_one.assert_not_called()


async def test_get_or_create_reward_doc_renormalizes_malformed_counters(stub_db, monkeypatch):
    existing = {"user_id": ObjectId(), "counters": {"evidence_saved": -3}}
    stub_db["user_rewards"].find_one.return_value = existing

    result = await get_or_create_reward_doc(stub_db, str(ObjectId()))

    assert result["counters"]["evidence_saved"] == 0
    stub_db["user_rewards"].update_one.assert_called_once()


async def test_refresh_reward_doc_no_change_skips_save(stub_db, monkeypatch):
    counters = normalize_reward_counters({"evidence_saved": 5})
    current_doc = {"counters": counters}

    async def fake_get_or_create(_db, _user_id):
        return current_doc

    async def fake_calculate(_db, _user_id):
        return counters

    monkeypatch.setattr(rewards, "get_or_create_reward_doc", fake_get_or_create)
    monkeypatch.setattr(rewards, "calculate_reward_counters", fake_calculate)

    result = await refresh_reward_doc(stub_db, str(ObjectId()))

    assert result is current_doc
    stub_db["user_rewards"].update_one.assert_not_called()


async def test_refresh_reward_doc_saves_when_counters_changed(stub_db, monkeypatch):
    old_counters = normalize_reward_counters({"evidence_saved": 5})
    new_counters = normalize_reward_counters({"evidence_saved": 9})
    current_doc = {"counters": old_counters}

    async def fake_get_or_create(_db, _user_id):
        return current_doc

    async def fake_calculate(_db, _user_id):
        return new_counters

    monkeypatch.setattr(rewards, "get_or_create_reward_doc", fake_get_or_create)
    monkeypatch.setattr(rewards, "calculate_reward_counters", fake_calculate)
    stub_db["user_rewards"].find_one.return_value = {"counters": old_counters, "unlocked": []}

    result = await refresh_reward_doc(stub_db, str(ObjectId()))

    assert result["counters"]["evidence_saved"] == 9
    stub_db["user_rewards"].update_one.assert_called_once()


async def test_increment_reward_counter_rejects_unknown_key(stub_db):
    try:
        await increment_reward_counter(stub_db, str(ObjectId()), "not_a_real_counter")
    except ValueError as exc:
        assert "not_a_real_counter" in str(exc)
    else:
        raise AssertionError("expected ValueError for unsupported counter key")


async def test_increment_reward_counter_adds_to_existing_value(stub_db, monkeypatch):
    user_id = str(ObjectId())
    counters = normalize_reward_counters({"evidence_saved": 2})

    async def fake_get_or_create(_db, _user_id):
        return {"counters": counters}

    monkeypatch.setattr(rewards, "get_or_create_reward_doc", fake_get_or_create)
    stub_db["user_rewards"].find_one.return_value = {"counters": counters, "unlocked": []}

    result = await increment_reward_counter(stub_db, user_id, "evidence_saved", amount=3)

    assert result["counters"]["evidence_saved"] == 5


async def test_sync_reward_counter_overwrites_value(stub_db, monkeypatch):
    user_id = str(ObjectId())
    counters = normalize_reward_counters({"job_matches_run": 2})

    async def fake_get_or_create(_db, _user_id):
        return {"counters": counters}

    monkeypatch.setattr(rewards, "get_or_create_reward_doc", fake_get_or_create)
    stub_db["user_rewards"].find_one.return_value = {"counters": counters, "unlocked": []}

    result = await sync_reward_counter(stub_db, user_id, "job_matches_run", 42)

    assert result["counters"]["job_matches_run"] == 42


async def test_safe_increment_reward_counter_returns_none_on_error(stub_db, monkeypatch):
    async def boom(*_args, **_kwargs):
        raise RuntimeError("mongo exploded")

    monkeypatch.setattr(rewards, "increment_reward_counter", boom)

    result = await safe_increment_reward_counter(stub_db, str(ObjectId()), "evidence_saved")

    assert result is None


async def test_safe_sync_reward_counter_returns_none_on_error(stub_db, monkeypatch):
    async def boom(*_args, **_kwargs):
        raise RuntimeError("mongo exploded")

    monkeypatch.setattr(rewards, "sync_reward_counter", boom)

    result = await safe_sync_reward_counter(stub_db, str(ObjectId()), "evidence_saved", 1)

    assert result is None
