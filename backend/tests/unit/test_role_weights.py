"""Unit tests for app/utils/role_weights.py, mocking every Mongo call via stub_db."""

from __future__ import annotations

from bson import ObjectId

from app.utils.role_weights import refresh_role_weights


async def test_refresh_role_weights_returns_empty_list_for_blank_role_id(stub_db):
    result = await refresh_role_weights(stub_db, "")
    assert result == []
    stub_db["roles"].find_one.assert_not_called()


async def test_refresh_role_weights_returns_empty_list_for_invalid_role_id(stub_db):
    result = await refresh_role_weights(stub_db, "not-a-valid-object-id")
    assert result == []
    stub_db["roles"].find_one.assert_not_called()


async def test_refresh_role_weights_no_jobs_writes_empty_weights(stub_db):
    role_id = ObjectId()
    stub_db["roles"].find_one.return_value = {"_id": role_id, "name": "ML Engineer"}
    stub_db["jobs"].set_find_results([])

    result = await refresh_role_weights(stub_db, str(role_id))

    assert result == []
    update_args, update_kwargs = stub_db["role_skill_weights"].update_one.call_args
    filter_arg, update_doc_arg = update_args
    assert filter_arg == {"role_id": role_id}
    assert update_doc_arg["$set"]["weights"] == []
    assert update_doc_arg["$set"]["role_name"] == "ML Engineer"
    assert update_kwargs.get("upsert") is True


async def test_refresh_role_weights_computes_weighted_skill_counts(stub_db):
    role_id = ObjectId()
    skill_a = ObjectId()
    skill_b = ObjectId()

    stub_db["roles"].find_one.return_value = {"_id": role_id, "name": "Data Scientist"}
    stub_db["jobs"].set_find_results(
        [
            {"required_skill_ids": [skill_a, skill_b]},
            {"required_skill_ids": [skill_a]},
            {"required_skill_ids": [skill_a]},
            {"required_skill_ids": []},
        ]
    )
    stub_db["skills"].set_find_results(
        [
            {"_id": skill_a, "name": "Python"},
            {"_id": skill_b, "name": "SQL"},
        ]
    )

    result = await refresh_role_weights(stub_db, str(role_id))

    by_id = {entry["skill_id"]: entry for entry in result}
    assert by_id[str(skill_a)]["weight"] == 3 / 4
    assert by_id[str(skill_a)]["skill_name"] == "Python"
    assert by_id[str(skill_b)]["weight"] == 1 / 4
    assert by_id[str(skill_b)]["skill_name"] == "SQL"
    # Ranked by descending count, so skill_a (count 3) comes before skill_b (count 1).
    assert [entry["skill_id"] for entry in result] == [str(skill_a), str(skill_b)]


async def test_refresh_role_weights_handles_missing_role_doc_gracefully(stub_db):
    role_id = ObjectId()
    stub_db["roles"].find_one.return_value = None
    stub_db["jobs"].set_find_results([])

    result = await refresh_role_weights(stub_db, str(role_id))

    assert result == []
    _filter_arg, update_doc_arg = stub_db["role_skill_weights"].update_one.call_args.args
    assert update_doc_arg["$set"]["role_name"] == ""


async def test_refresh_role_weights_ignores_unparseable_skill_ids_in_jobs(stub_db):
    role_id = ObjectId()
    valid_skill = ObjectId()
    stub_db["roles"].find_one.return_value = {"_id": role_id, "name": "Role"}
    stub_db["jobs"].set_find_results(
        [{"required_skill_ids": [valid_skill, None, ""]}]
    )
    stub_db["skills"].set_find_results([{"_id": valid_skill, "name": "Python"}])

    result = await refresh_role_weights(stub_db, str(role_id))

    assert len(result) == 1
    assert result[0]["skill_id"] == str(valid_skill)
    assert result[0]["weight"] == 1.0
