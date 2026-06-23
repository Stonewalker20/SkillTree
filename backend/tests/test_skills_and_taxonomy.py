"""Tests for skill catalog behavior, custom skills, and taxonomy operations."""

from bson import ObjectId
from app.core.auth import now_utc

def test_skill_crud_and_taxonomy_routes(test_context):
    client = test_context["client"]
    headers = test_context["headers"]
    db = test_context["db"]

    listed = client.get("/skills/", headers=headers)
    assert listed.status_code == 200
    assert any(skill["name"] == "Python" for skill in listed.json())

    created = client.post(
        "/skills/",
        headers=headers,
        json={"name": "FastAPI", "category": "Backend", "aliases": ["fast api"], "tags": ["python"]},
    )
    assert created.status_code == 200
    skill_id = created.json()["id"]

    non_admin_update = client.patch(f"/skills/{skill_id}", headers=headers, json={"proficiency": 4})
    assert non_admin_update.status_code == 403

    aliases = client.put(f"/taxonomy/aliases/{skill_id}", headers=headers, json={"aliases": ["fastapi", "fast apis"]})
    assert aliases.status_code == 200
    assert aliases.json()["aliases"]

    relation = client.post(
        "/taxonomy/relations",
        headers=headers,
        json={"from_skill_id": test_context["skill_python"], "to_skill_id": skill_id, "relation_type": "related_to"},
    )
    assert relation.status_code == 200

    relations = client.get("/taxonomy/relations", headers=headers, params={"skill_id": test_context["skill_python"]})
    assert relations.status_code == 200
    assert len(relations.json()) == 1

    created_ml = client.post(
        "/skills/",
        headers=headers,
        json={"name": "Machine Learning Ops", "category": "ML Platform", "aliases": ["ml ops"], "tags": ["ml"]},
    )
    assert created_ml.status_code == 200
    mlops_id = created_ml.json()["id"]

    relation_two = client.post(
        "/taxonomy/relations",
        headers=headers,
        json={"from_skill_id": skill_id, "to_skill_id": mlops_id, "relation_type": "related_to"},
    )
    assert relation_two.status_code == 200

    db["evidence"].docs.append(
        {
            "_id": ObjectId(),
            "user_id": ObjectId(test_context["user_id"]),
            "type": "project",
            "title": "Python ML delivery",
            "source": "manual-entry",
            "text_excerpt": "Built Python and ML automation",
            "skill_ids": [ObjectId(test_context["skill_python"]), ObjectId(test_context["skill_ml"])],
            "origin": "user",
            "created_at": now_utc(),
            "updated_at": now_utc(),
        }
    )

    graph = client.get(
        f"/taxonomy/graph/{test_context['skill_python']}",
        headers=headers,
        params={"depth": 2, "limit": 5, "include_inferred": "true"},
    )
    assert graph.status_code == 200
    payload = graph.json()
    assert payload["root_skill_id"] == test_context["skill_python"]
    assert any(node["skill_id"] == skill_id for node in payload["nodes"])
    assert any(edge["edge_type"] == "explicit" for edge in payload["edges"])
    assert any(edge["edge_type"] == "evidence_cooccurrence" for edge in payload["edges"])

    deleted = client.delete(f"/skills/{skill_id}", headers=headers)
    assert deleted.status_code == 403
    deleted_ml = client.delete(f"/skills/{mlops_id}", headers=headers)
    assert deleted_ml.status_code == 403

    db["users"].docs[0]["role"] = "admin"

    admin_skill_list = client.get("/admin/skills", headers=headers)
    assert admin_skill_list.status_code == 200
    assert any(entry["id"] == skill_id for entry in admin_skill_list.json())

    updated = client.patch(f"/skills/{skill_id}", headers=headers, json={"aliases": ["Fast APIs"], "proficiency": 4})
    assert updated.status_code == 200
    assert updated.json()["proficiency"] == 4

    deleted = client.delete(f"/skills/{skill_id}", headers=headers)
    assert deleted.status_code == 200
    deleted_ml = client.delete(f"/skills/{mlops_id}", headers=headers)
    assert deleted_ml.status_code == 200


def test_skill_extraction_and_gap_endpoints(test_context):
    client = test_context["client"]
    headers = test_context["headers"]
    db = test_context["db"]

    snapshot_id = db["resume_snapshots"].docs[0]["_id"] if db["resume_snapshots"].docs else None
    if snapshot_id is None:
        db["resume_snapshots"].docs.append(
            {
                "_id": __import__("bson").ObjectId(),
                "user_id": __import__("bson").ObjectId(test_context["user_id"]),
                "raw_text": "Python ML FastAPI " * 20,
                "created_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            }
        )
        snapshot_id = db["resume_snapshots"].docs[0]["_id"]

    extracted = client.post(f"/skills/extract/skills/{snapshot_id}", headers=headers)
    assert extracted.status_code == 200
    assert extracted.json()["extracted"]
    assert all(0.0 <= float(item["confidence"]) <= 1.0 for item in extracted.json()["extracted"])

    gaps = client.get("/skills/gaps", headers=headers)
    assert gaps.status_code == 200
    assert isinstance(gaps.json(), list)


def test_extract_skills_rejects_other_users_snapshot(test_context):
    client = test_context["client"]
    db = test_context["db"]

    snapshot_id = db["resume_snapshots"].docs[0]["_id"] if db["resume_snapshots"].docs else None
    if snapshot_id is None:
        db["resume_snapshots"].docs.append(
            {
                "_id": ObjectId(),
                "user_id": ObjectId(test_context["user_id"]),
                "raw_text": "Python ML FastAPI " * 20,
                "created_at": now_utc(),
            }
        )
        snapshot_id = db["resume_snapshots"].docs[0]["_id"]

    other_user_id = ObjectId()
    seeded_user = db["users"].docs[0]
    db["users"].docs.append(
        {
            "_id": other_user_id,
            "email": "other@example.com",
            "username": "other-user",
            "password_salt": seeded_user["password_salt"],
            "password_hash": seeded_user["password_hash"],
            "role": "user",
            "subscription_status": "active",
            "subscription_plan": "pro",
            "created_at": now_utc(),
        }
    )
    db["sessions"].docs.append(
        {
            "_id": ObjectId(),
            "user_id": other_user_id,
            "token": "other-token",
            "created_at": db["sessions"].docs[0]["created_at"],
            "expires_at": db["sessions"].docs[0]["expires_at"],
        }
    )
    other_headers = {"Authorization": "Bearer other-token"}

    extracted = client.post(f"/skills/extract/skills/{snapshot_id}", headers=other_headers)
    assert extracted.status_code == 404


def test_skill_trajectory_returns_clustered_career_paths(test_context):
    client = test_context["client"]
    headers = test_context["headers"]

    client.post(
        "/skills/confirmations/",
        headers=headers,
        json={
            "resume_snapshot_id": None,
            "confirmed": [
                {"skill_id": test_context["skill_python"], "proficiency": 4},
                {"skill_id": test_context["skill_ml"], "proficiency": 4},
            ],
            "rejected": [],
            "edited": [],
        },
    )
    client.post(
        "/evidence/",
        headers=headers,
        json={
            "user_id": test_context["user_id"],
            "type": "project",
            "title": "ML Platform",
            "source": "manual-entry",
            "text_excerpt": "Built Python ML services and analytics jobs.",
            "skill_ids": [test_context["skill_python"], test_context["skill_ml"]],
            "origin": "user",
        },
    )

    response = client.get("/taxonomy/trajectory", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["clusters"]
    assert payload["career_paths"]
    assert payload["career_paths"][0]["role_name"] == "ML Engineer"
    assert payload["career_paths"][0]["matched_skills"]
    assert payload["learning_path"]
    assert payload["learning_path"][0]["target_skills"]

    skill_detail = client.get("/taxonomy/learning-path/skill/ML", headers=headers)
    assert skill_detail.status_code == 200
    assert skill_detail.json()["skill_name"] == "ML"


def test_skill_trajectory_includes_multiple_roles_from_object_role_refs(test_context):
    client = test_context["client"]
    headers = test_context["headers"]
    db = test_context["db"]

    analytics_role_id = ObjectId()
    db["roles"].docs.append(
        {
            "_id": analytics_role_id,
            "name": "Analytics Engineer",
            "description": "Build reporting pipelines and analytics models.",
            "created_at": now_utc(),
            "updated_at": now_utc(),
        }
    )
    db["role_skill_weights"].docs = []
    db["jobs"].docs = [
        {
            "_id": ObjectId(),
            "title": "ML Engineer Job",
            "moderation_status": "approved",
            "role_ids": [ObjectId(test_context["role_id"])],
            "required_skill_ids": [ObjectId(test_context["skill_python"]), ObjectId(test_context["skill_ml"])],
            "created_at": now_utc(),
            "updated_at": now_utc(),
        },
        {
            "_id": ObjectId(),
            "title": "Analytics Engineer Job",
            "moderation_status": "approved",
            "role_ids": [analytics_role_id],
            "required_skill_ids": [ObjectId(test_context["skill_python"])],
            "created_at": now_utc(),
            "updated_at": now_utc(),
        },
    ]

    client.post(
        "/skills/confirmations/",
        headers=headers,
        json={
            "resume_snapshot_id": None,
            "confirmed": [
                {"skill_id": test_context["skill_python"], "proficiency": 4},
                {"skill_id": test_context["skill_ml"], "proficiency": 4},
            ],
            "rejected": [],
            "edited": [],
        },
    )

    response = client.get("/taxonomy/trajectory", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    role_names = {entry["role_name"] for entry in payload["career_paths"]}
    assert "ML Engineer" in role_names
    assert "Analytics Engineer" in role_names
    assert len(payload["career_paths"]) >= 2


def test_create_skill_does_not_auto_add_short_initialism_aliases(test_context):
    client = test_context["client"]
    headers = test_context["headers"]

    created = client.post(
        "/skills/",
        headers=headers,
        json={"name": "Marketing Leadership", "category": "Business"},
    )
    assert created.status_code == 200
    assert "ML" not in created.json()["aliases"]
