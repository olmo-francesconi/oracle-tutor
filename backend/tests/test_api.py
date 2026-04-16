import hashlib
from pathlib import Path

import numpy as np

from ot_backend.api.admin_auth import create_admin_token
from ot_backend.api.routers.search import _CARD_TYPE_MAP, _FORMAT_MAP, _parse_code_filter
from ot_backend.core.database import SessionLocal
from ot_backend.core.models import (
    AnalyticsEvent,
    ClientErrorEvent,
    SemanticDataset,
    SemanticJob,
    SemanticModel,
    SemanticModelArtifact,
)
from ot_backend.semantic.artifacts import semantic_model_artifact_object_key
from ot_backend.semantic.base_model_catalog import get_semantic_base_model
from ot_backend.semantic.model_registry import bundle_model_directory


def _admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {create_admin_token()}"}


def _create_model_with_bundle_artifact(
    *,
    slug: str,
    bundle: bytes,
    base_model: str = "sentence-transformers/all-MiniLM-L6-v2",
    status: str = "uploaded",
    is_active: bool = False,
) -> str:
    with SessionLocal() as db:
        model = SemanticModel(
            slug=slug,
            base_model=base_model,
            status=status,
            is_active=is_active,
            embedding_dim=384,
        )
        db.add(model)
        db.commit()
        db.refresh(model)
        db.add(
            SemanticModelArtifact(
                model_id=model.id,
                artifact_kind="bundle_zip",
                object_key=semantic_model_artifact_object_key(model.id, "bundle_zip"),
                sha256=hashlib.sha256(bundle).hexdigest(),
                size_bytes=len(bundle),
                content_type="application/zip",
                metadata_json={"format": "zip"},
            )
        )
        db.commit()
        return model.id


def _create_dataset(*, slug: str, augmentation_mode: str = "none") -> str:
    with SessionLocal() as db:
        dataset = SemanticDataset(
            slug=slug,
            status="ready",
            augmentation_mode=augmentation_mode,
            source_semantic_data_version=1,
        )
        db.add(dataset)
        db.commit()
        db.refresh(dataset)
        return dataset.id


def _write_complete_bundle_root(root: Path) -> None:
    (root / "models" / "onnx" / "onnx").mkdir(parents=True, exist_ok=True)
    (root / "models" / "onnx" / "onnx" / "model.onnx").write_bytes(b"onnx")
    (root / "models" / "onnx" / "tokenizer.json").write_text("{}", encoding="utf-8")
    (root / "models" / "onnx" / "1_Pooling").mkdir(parents=True, exist_ok=True)
    (root / "models" / "onnx" / "1_Pooling" / "config.json").write_text(
        '{"pooling_mode_mean_tokens": true}',
        encoding="utf-8",
    )
    (root / "models" / "pytorch").mkdir(parents=True, exist_ok=True)
    (root / "models" / "pytorch" / "config.json").write_text("{}", encoding="utf-8")
    (root / "embeddings").mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        root / "embeddings" / "embeddings.npz",
        oracle_ids=np.array(["o1"]),
        face_ixs=np.array([0], dtype=np.int32),
        embeddings=np.array([[1.0] + [0.0] * 383], dtype=np.float32),
    )
    (root / "training").mkdir(parents=True, exist_ok=True)
    (root / "training" / "training-dataset.json").write_text(
        '{"version": 5, "face_texts": [{"oracle_id": "o1", "face_ix": 0, "name": "Shock", "text": "deal damage"}], "pair_ids": [], "direct_text_pairs": [], "simcse_examples": 0, "tag_pair_examples": 0, "tag_desc_pair_examples": 0, "template_query_examples": 0, "metadata": {"semantic_data_version": 1}}',
        encoding="utf-8",
    )
    (root / "eval").mkdir(parents=True, exist_ok=True)
    (root / "eval" / "eval.json").write_text(
        '{"version": 1, "summary": {"query_count": 1, "top1_hits": 1, "top3_hits": 1, "top5_hits": 1, "top1_rate": 1.0, "top3_rate": 1.0, "top5_rate": 1.0, "mrr": 1.0}, "queries": []}',
        encoding="utf-8",
    )
    (root / "config.json").write_text('{"epochs": 1}', encoding="utf-8")
    (root / "metrics.json").write_text('{"loss": 0.1}', encoding="utf-8")
    (root / "manifest.json").write_text(
        '{"version": 1, "bundle": {"has_onnx_model": true, "has_pytorch_model": true, "has_precomputed_embeddings": true, "has_training_dataset": true, "has_eval_json": true}, "source_semantic_data_version": 1, "dataset_metadata": {"semantic_data_version": 1}}',
        encoding="utf-8",
    )


def test_root(client):
    res = client.get("/")
    assert res.status_code == 200
    assert res.json() == {"service": "oracle-tutor-api"}


def test_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_openapi(client):
    res = client.get("/openapi.json")
    assert res.status_code == 200
    data = res.json()
    assert data["info"]["title"] == "oracle-tutor api"


def test_search(client):
    res = client.get("/search", params={"q": "sho", "limit": 10})
    assert res.status_code == 200
    names = [x["name"] for x in res.json()]
    assert "Shock" in names


def test_oracle_samples_include_terms_from_keywords_and_ability_words(client):
    res = client.get("/oracle-samples", params={"n": 60})
    assert res.status_code == 200
    data = res.json()
    assert "texts" in data
    assert "terms" in data
    assert "Deathtouch" in data["terms"]
    assert "Trample" in data["terms"]
    assert "Vigilance" in data["terms"]
    assert "Landfall" in data["terms"]


def test_search_returns_multiple_faces_for_multi_face_name_matches(client):
    res = client.get("/search", params={"q": "aang", "limit": 10})
    assert res.status_code == 200
    assert res.json() == [
        {
            "name": "Aang, at the Crossroads",
            "similarity": 1.0,
            "rank": 8,
            "oracle_id": "o8",
            "scryfall_id": "s8",
            "face_ix": 0,
            "image_side": "front",
        },
        {
            "name": "Aang, Destined Savior",
            "similarity": 1.0,
            "rank": 8,
            "oracle_id": "o8",
            "scryfall_id": "s8",
            "face_ix": 1,
            "image_side": "back",
        },
    ]


def test_similar_cards_includes_face_index(client, monkeypatch):
    class FakeSemanticIndex:
        def similar_to_face(self, *_args, **_kwargs):
            return [(("o2", 0), 0.95)]

    monkeypatch.setattr("ot_backend.api._semantic_index._get_semantic_index", lambda: FakeSemanticIndex())

    res = client.get("/similar-cards", params={"oracle_id": "o1", "face_ix": 0, "limit": 10})
    assert res.status_code == 200
    assert res.json() == {
        "items": [
            {
                "oracle_id": "o2",
                "scryfall_id": "s2",
                "face_ix": 0,
                "image_side": "front",
                "name": "Shock",
                "card_name": "Shock",
                "similarity": 0.95,
                "rank": 2,
                "type_line": "Instant",
                "mana_cost": None,
                "oracle_text": "Shock deals 2 damage to any target.",
                "power": None,
                "toughness": None,
                "colors": ["R"],
                "layout": "normal",
                "rarity": "common",
                "legalities": {},
                "uniqueness": None,
                "border_color": None,
                "set_code": "tst",
            }
        ],
        "has_more": False,
    }


def test_similar_cards_uses_shared_front_image_side_for_split_faces(client, monkeypatch):
    class FakeSemanticIndex:
        def search_oracle(self, *_args, **_kwargs):
            return [(("o6", 1), 0.91)]

    monkeypatch.setattr("ot_backend.api._semantic_index._get_semantic_index", lambda: FakeSemanticIndex())

    res = client.get("/similar-cards", params={"q": "tap draw", "limit": 10})
    assert res.status_code == 200
    assert res.json()["items"][0]["face_ix"] == 1
    assert res.json()["items"][0]["image_side"] == "front"
    assert res.json()["items"][0]["name"] == "Ice"


def test_similar_cards_uses_back_image_side_for_double_faced_back_face(client, monkeypatch):
    class FakeSemanticIndex:
        def search_oracle(self, *_args, **_kwargs):
            return [(("o7", 1), 0.89)]

    monkeypatch.setattr("ot_backend.api._semantic_index._get_semantic_index", lambda: FakeSemanticIndex())

    res = client.get("/similar-cards", params={"q": "werewolf", "limit": 10})
    assert res.status_code == 200
    assert res.json()["items"][0]["face_ix"] == 1
    assert res.json()["items"][0]["image_side"] == "back"
    assert res.json()["items"][0]["name"] == "Moonrage Brute"


def test_similar_cards_sets_has_more_when_more_results_exist(client, monkeypatch):
    class FakeSemanticIndex:
        def search_oracle(self, *_args, **_kwargs):
            return [(("o2", 0), 0.95), (("o1", 0), 0.9)]

    monkeypatch.setattr("ot_backend.api._semantic_index._get_semantic_index", lambda: FakeSemanticIndex())

    res = client.get("/similar-cards", params={"q": "shock", "limit": 1, "offset": 0})
    assert res.status_code == 200
    assert len(res.json()["items"]) == 1
    assert res.json()["has_more"] is True


def test_similar_cards_sets_has_more_false_on_last_page(client, monkeypatch):
    class FakeSemanticIndex:
        def search_oracle(self, *_args, **_kwargs):
            return [(("o2", 0), 0.95), (("o1", 0), 0.9)]

    monkeypatch.setattr("ot_backend.api._semantic_index._get_semantic_index", lambda: FakeSemanticIndex())

    res = client.get("/similar-cards", params={"q": "shock", "limit": 1, "offset": 1})
    assert res.status_code == 200
    assert len(res.json()["items"]) == 1
    assert res.json()["has_more"] is False


def test_compact_type_and_format_filters_decode_to_backend_values():
    assert _parse_code_filter("is", _CARD_TYPE_MAP, "card type") == ["instant", "sorcery"]
    assert _parse_code_filter("ml", _FORMAT_MAP, "format") == ["modern", "legacy"]


def test_similar_cards_rejects_duplicate_compact_format_codes(client):
    res = client.get("/similar-cards", params={"q": "shock", "format": "mm"})

    assert res.status_code == 422


def test_data_endpoints_return_503_while_schema_migrating(client, monkeypatch):
    monkeypatch.setattr("ot_backend.api._ensure_schema_ready._schema_ready", False)
    monkeypatch.setattr("ot_backend.api._ensure_schema_ready.wait_for_migration_ready", lambda **_: False)

    res = client.get("/search", params={"q": "shock"})
    assert res.status_code == 503


def test_client_error_telemetry_is_persisted(client):
    res = client.post(
        "/telemetry/client-error",
        json={
            "message": "render exploded",
            "name": "TypeError",
            "stack": "TypeError: render exploded",
            "context": {
                "source": "react.error-boundary",
                "route": "/search",
            },
            "url": "https://example.test/search?q=bolt",
            "userAgent": "Vitest Browser",
            "timestamp": "2026-03-28T12:00:00Z",
        },
    )

    assert res.status_code == 202
    assert res.json() == {"accepted": True}

    with SessionLocal() as db:
        event = db.query(ClientErrorEvent).one()

    assert event.error_name == "TypeError"
    assert event.message == "render exploded"
    assert event.source == "react.error-boundary"
    assert event.context == {
        "source": "react.error-boundary",
        "route": "/search",
    }


def test_analytics_telemetry_is_persisted(client):
    res = client.post(
        "/telemetry/analytics",
        json={
            "event": "filters_cleared",
            "props": {
                "previousKeys": ["format"],
                "queryLength": 5,
            },
            "url": "https://example.test/search?q=bolt",
            "userAgent": "Vitest Browser",
            "timestamp": "2026-03-28T12:00:00Z",
        },
    )

    assert res.status_code == 202
    assert res.json() == {"accepted": True}

    with SessionLocal() as db:
        event = db.query(AnalyticsEvent).one()

    assert event.event_name == "filters_cleared"
    assert event.props == {
        "previousKeys": ["format"],
        "queryLength": 5,
    }


def test_analytics_telemetry_rejects_invalid_event_name(client):
    res = client.post(
        "/telemetry/analytics",
        json={
            "event": "mystery_event",
            "props": {},
            "url": "https://example.test/search",
            "userAgent": "Vitest Browser",
        },
    )

    assert res.status_code == 422


def test_client_error_telemetry_rejects_oversized_context(client):
    res = client.post(
        "/telemetry/client-error",
        json={
            "message": "render exploded",
            "name": "TypeError",
            "context": {
                "payload": "x" * 9000,
            },
            "url": "https://example.test/search",
            "userAgent": "Vitest Browser",
        },
    )

    assert res.status_code == 413


def test_search_rejects_overlong_query(client):
    res = client.get("/search", params={"q": "x" * 201})

    assert res.status_code == 422


def test_similar_cards_rejects_overlong_query(client, monkeypatch):
    class FakeSemanticIndex:
        def search_oracle(self, *_args, **_kwargs):
            return []

    monkeypatch.setattr("ot_backend.api._semantic_index._get_semantic_index", lambda: FakeSemanticIndex())

    res = client.get("/similar-cards", params={"q": "x" * 201})

    assert res.status_code == 422


def test_telemetry_rejects_oversized_request_body(client):
    res = client.post(
        "/telemetry/client-error",
        content=b"x" * 40000,
        headers={"content-type": "application/json"},
    )

    assert res.status_code == 413


def test_rejects_disallowed_host_header(client):
    res = client.get("/health", headers={"host": "evil.example"})

    assert res.status_code == 400


def test_admin_semantic_model_routes_require_auth(client):
    res = client.get("/admin/semantic-models")

    assert res.status_code == 401


def test_admin_semantic_base_models_require_auth(client):
    res = client.get("/admin/semantic-base-models")

    assert res.status_code == 401


def test_admin_lists_allowed_semantic_base_models(client):
    res = client.get("/admin/semantic-base-models", headers=_admin_headers())

    assert res.status_code == 200
    payload = res.json()
    assert any(item["key"] == "mini-lm-l6-v2" for item in payload)


def test_admin_auth_token_returns_token_for_valid_password(client, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "swordfish")
    monkeypatch.setenv("ADMIN_JWT_SECRET", "top-secret-with-at-least-thirty-two-bytes")

    res = client.post("/admin/auth/token", json={"password": "swordfish"})

    assert res.status_code == 200
    payload = res.json()
    assert payload["access_token"]
    assert payload["token_type"] == "bearer"
    assert payload["expires_in"] == 28800


def test_admin_auth_token_rejects_invalid_password(client, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "swordfish")
    monkeypatch.setenv("ADMIN_JWT_SECRET", "top-secret-with-at-least-thirty-two-bytes")

    res = client.post("/admin/auth/token", json={"password": "wrong"})

    assert res.status_code == 401


def test_admin_auth_token_locks_out_ip_after_repeated_failures(client, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "swordfish")
    monkeypatch.setenv("ADMIN_JWT_SECRET", "top-secret-with-at-least-thirty-two-bytes")
    monkeypatch.setenv("ADMIN_LOGIN_MAX_FAILURES", "3")
    monkeypatch.setenv("ADMIN_LOGIN_LOCKOUT_SECONDS", "120")
    headers = {"X-Forwarded-For": "203.0.113.10"}

    for _ in range(3):
        res = client.post("/admin/auth/token", json={"password": "wrong"}, headers=headers)
        assert res.status_code == 401

    locked_res = client.post("/admin/auth/token", json={"password": "swordfish"}, headers=headers)

    assert locked_res.status_code == 429
    assert 1 <= int(locked_res.headers["Retry-After"]) <= 120
    assert "Too many failed admin login attempts" in locked_res.json()["detail"]


def test_admin_auth_token_success_resets_failure_count_for_ip(client, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "swordfish")
    monkeypatch.setenv("ADMIN_JWT_SECRET", "top-secret-with-at-least-thirty-two-bytes")
    monkeypatch.setenv("ADMIN_LOGIN_MAX_FAILURES", "3")
    monkeypatch.setenv("ADMIN_LOGIN_LOCKOUT_SECONDS", "120")
    headers = {"X-Forwarded-For": "198.51.100.20"}

    first_failure = client.post("/admin/auth/token", json={"password": "wrong"}, headers=headers)
    success = client.post("/admin/auth/token", json={"password": "swordfish"}, headers=headers)
    second_failure = client.post("/admin/auth/token", json={"password": "wrong"}, headers=headers)

    assert first_failure.status_code == 401
    assert success.status_code == 200
    assert second_failure.status_code == 401


def test_admin_auth_token_lockout_is_scoped_to_source_ip(client, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "swordfish")
    monkeypatch.setenv("ADMIN_JWT_SECRET", "top-secret-with-at-least-thirty-two-bytes")
    monkeypatch.setenv("ADMIN_LOGIN_MAX_FAILURES", "2")
    monkeypatch.setenv("ADMIN_LOGIN_LOCKOUT_SECONDS", "60")
    blocked_headers = {"X-Forwarded-For": "203.0.113.10"}
    other_headers = {"X-Forwarded-For": "203.0.113.11"}

    client.post("/admin/auth/token", json={"password": "wrong"}, headers=blocked_headers)
    client.post("/admin/auth/token", json={"password": "wrong"}, headers=blocked_headers)

    blocked_res = client.post("/admin/auth/token", json={"password": "swordfish"}, headers=blocked_headers)
    other_res = client.post("/admin/auth/token", json={"password": "swordfish"}, headers=other_headers)

    assert blocked_res.status_code == 429
    assert other_res.status_code == 200


def test_admin_auth_token_prefers_x_real_ip_over_forwarded_for(client, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "swordfish")
    monkeypatch.setenv("ADMIN_JWT_SECRET", "top-secret-with-at-least-thirty-two-bytes")
    monkeypatch.setenv("ADMIN_LOGIN_MAX_FAILURES", "2")
    monkeypatch.setenv("ADMIN_LOGIN_LOCKOUT_SECONDS", "60")

    spoofed_headers = {
        "X-Real-Ip": "198.51.100.44",
        "X-Forwarded-For": "203.0.113.250, 198.51.100.44",
    }
    victim_headers = {"X-Real-Ip": "203.0.113.250"}

    client.post("/admin/auth/token", json={"password": "wrong"}, headers=spoofed_headers)
    client.post("/admin/auth/token", json={"password": "wrong"}, headers=spoofed_headers)

    spoofed_res = client.post("/admin/auth/token", json={"password": "swordfish"}, headers=spoofed_headers)
    victim_res = client.post("/admin/auth/token", json={"password": "swordfish"}, headers=victim_headers)

    assert spoofed_res.status_code == 429
    assert victim_res.status_code == 200


def test_admin_auth_token_returns_503_when_unconfigured(client, monkeypatch):
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("ADMIN_JWT_SECRET", raising=False)

    res = client.post("/admin/auth/token", json={"password": "whatever"})

    assert res.status_code == 503


def test_admin_route_rejects_invalid_bearer_token(client):
    res = client.get("/admin/semantic-models", headers={"Authorization": "Bearer nope"})

    assert res.status_code == 401


def test_admin_register_and_list_semantic_models(client, monkeypatch, tmp_path):
    uploaded: dict[str, bytes] = {}
    monkeypatch.setattr(
        "ot_backend.semantic.artifacts.upload_artifact_bytes",
        lambda *, object_key, content_bytes, content_type: uploaded.__setitem__(object_key, content_bytes),
    )
    model_root = tmp_path / "semantic-model"
    _write_complete_bundle_root(model_root)
    bundle = bundle_model_directory(model_root)

    create_res = client.post(
        "/admin/semantic-models",
        params={"slug": "mini-lm", "base_model_key": "mini-lm-l6-v2"},
        headers=_admin_headers(),
        content=bundle,
    )

    assert create_res.status_code == 201
    created = create_res.json()
    assert created["slug"] == "mini-lm"
    assert created["base_model_key"] == "mini-lm-l6-v2"
    assert created["status"] == "uploaded"
    assert created["artifact_size_bytes"] == len(bundle)
    assert created["embedding_count"] == 0
    assert uploaded

    with SessionLocal() as db:
        model = db.get(SemanticModel, created["id"])
        assert model is not None
        artifacts = db.query(SemanticModelArtifact).filter(SemanticModelArtifact.model_id == model.id).all()
        bundle_artifact = next(artifact for artifact in artifacts if artifact.artifact_kind == "bundle_zip")
        assert bundle_artifact.object_key in uploaded
        assert {artifact.artifact_kind for artifact in artifacts} == {
            "bundle_zip",
            "training_dataset",
            "eval_json",
            "manifest_json",
        }

    list_res = client.get("/admin/semantic-models", headers=_admin_headers())

    assert list_res.status_code == 200
    assert list_res.json()[0]["id"] == created["id"]

    artifacts_res = client.get(f"/admin/semantic-models/{created['id']}/artifacts", headers=_admin_headers())

    assert artifacts_res.status_code == 200
    assert {artifact["artifact_kind"] for artifact in artifacts_res.json()} == {
        "bundle_zip",
        "training_dataset",
        "eval_json",
        "manifest_json",
    }


def test_admin_register_semantic_model_rejects_duplicate_slug(client, monkeypatch, tmp_path):
    monkeypatch.setattr("ot_backend.semantic.artifacts.upload_artifact_bytes", lambda **_kwargs: None)

    model_root = tmp_path / "semantic-model"
    _write_complete_bundle_root(model_root)
    bundle = bundle_model_directory(model_root)

    first_res = client.post(
        "/admin/semantic-models",
        params={"slug": "mini-lm", "base_model_key": "mini-lm-l6-v2"},
        headers=_admin_headers(),
        content=bundle,
    )
    second_res = client.post(
        "/admin/semantic-models",
        params={"slug": "mini-lm", "base_model_key": "mini-lm-l6-v2"},
        headers=_admin_headers(),
        content=bundle,
    )

    assert first_res.status_code == 201
    assert second_res.status_code == 409
    assert "already exists" in second_res.json()["detail"]


def test_admin_register_semantic_model_rejects_unknown_base_model_key(client, monkeypatch, tmp_path):
    monkeypatch.setattr("ot_backend.semantic.artifacts.upload_artifact_bytes", lambda **_kwargs: None)
    model_root = tmp_path / "semantic-model"
    _write_complete_bundle_root(model_root)
    bundle = bundle_model_directory(model_root)

    res = client.post(
        "/admin/semantic-models",
        params={"slug": "mini-lm", "base_model_key": "nope"},
        headers=_admin_headers(),
        content=bundle,
    )

    assert res.status_code == 400
    assert "Unknown semantic base model" in res.json()["detail"]


def test_admin_register_semantic_model_rejects_embedding_dimension_mismatch(client, monkeypatch, tmp_path):
    monkeypatch.setattr("ot_backend.semantic.artifacts.upload_artifact_bytes", lambda **_kwargs: None)
    model_root = tmp_path / "semantic-model"
    _write_complete_bundle_root(model_root)
    np.savez_compressed(
        model_root / "embeddings" / "embeddings.npz",
        oracle_ids=np.array(["o1"]),
        face_ixs=np.array([0], dtype=np.int32),
        embeddings=np.array([[1.0] + [0.0] * 767], dtype=np.float32),
    )
    bundle = bundle_model_directory(model_root)

    res = client.post(
        "/admin/semantic-models",
        params={"slug": "mini-lm", "base_model_key": "mini-lm-l6-v2"},
        headers=_admin_headers(),
        content=bundle,
    )

    assert res.status_code == 400
    assert "does not match expected dimension 384" in res.json()["detail"]


def test_admin_create_train_job_and_list_jobs(client, monkeypatch):
    dataset_id = _create_dataset(slug="dataset-1")

    create_res = client.post(
        "/admin/semantic-jobs/train",
        headers=_admin_headers(),
        json={
            "requested_by": "olmo",
            "dataset_id": dataset_id,
            "model_slug": "candidate-1",
            "base_model_key": "mini-lm-l6-v2",
            "skip_fine_tune": True,
            "epochs": 3,
            "batch_size": 8,
            "promote_after_register": True,
            "embed_batch_size": 128,
        },
    )

    assert create_res.status_code == 201
    created = create_res.json()
    assert created["job_type"] == "train"
    assert created["status"] == "pending"
    assert created["requested_by"] == "olmo"
    assert created["dataset_id"] == dataset_id
    assert created["payload_json"]["dataset_id"] == dataset_id
    assert created["payload_json"]["base_model_key"] == "mini-lm-l6-v2"
    assert created["payload_json"]["model_slug"] == "candidate-1"
    assert created["payload_json"]["base_model"] == get_semantic_base_model("mini-lm-l6-v2").base_model
    assert created["payload_json"]["skip_fine_tune"] is True

    list_res = client.get("/admin/semantic-jobs", headers=_admin_headers())

    assert list_res.status_code == 200
    assert list_res.json()[0]["id"] == created["id"]

    detail_res = client.get(f"/admin/semantic-jobs/{created['id']}", headers=_admin_headers())

    assert detail_res.status_code == 200
    assert detail_res.json()["payload_json"]["embed_batch_size"] == 128


def test_admin_train_options_reports_allowed_values(client):
    res = client.get("/admin/semantic-train-options", headers=_admin_headers())

    assert res.status_code == 200
    payload = res.json()
    assert payload["epoch_min"] == 1
    assert payload["epoch_max"] == 10
    assert payload["batch_size_options"] == [4, 8, 16, 32, 64, 128, 256]
    assert payload["embed_batch_size_options"] == [64, 128, 256, 512, 1024]
    assert [item["key"] for item in payload["augmentation_options"]] == [
        "tag_pairs",
        "tag_descriptions",
        "template_queries",
        "llm_queries",
    ]


def test_admin_create_train_job_rejects_invalid_batch_size(client):
    dataset_id = _create_dataset(slug="dataset-invalid-batch")

    res = client.post(
        "/admin/semantic-jobs/train",
        headers=_admin_headers(),
        json={
            "requested_by": "olmo",
            "dataset_id": dataset_id,
            "model_slug": "candidate-legacy",
            "base_model_key": "mini-lm-l6-v2",
            "skip_fine_tune": True,
            "epochs": 3,
            "batch_size": 12,
            "promote_after_register": False,
            "embed_batch_size": 128,
        },
    )

    assert res.status_code == 422


def test_admin_create_dataset_job_and_list_datasets(client):
    create_res = client.post(
        "/admin/semantic-jobs/dataset",
        headers=_admin_headers(),
        json={
            "requested_by": "olmo",
            "dataset_slug": "dataset-job-1",
            "augmentation_mode": "tag_pairs",
        },
    )

    assert create_res.status_code == 201
    created = create_res.json()
    assert created["job_type"] == "dataset"
    assert created["status"] == "pending"
    assert created["requested_by"] == "olmo"
    assert created["payload_json"]["dataset_slug"] == "dataset-job-1"
    assert created["payload_json"]["augmentation_mode"] == "tag_pairs"


def test_admin_create_dataset_job_rejects_invalid_augmentation_key(client):
    res = client.post(
        "/admin/semantic-jobs/dataset",
        headers=_admin_headers(),
        json={
            "requested_by": "olmo",
            "dataset_slug": "dataset-invalid-augmentation",
            "augmentation_mode": "mystery_mode",
        },
    )

    assert res.status_code == 422


def test_admin_create_train_job_rejects_removed_path_fields(client):
    dataset_id = _create_dataset(slug="dataset-removed-path")

    res = client.post(
        "/admin/semantic-jobs/train",
        headers=_admin_headers(),
        json={
            "requested_by": "olmo",
            "dataset_id": dataset_id,
            "model_slug": "candidate-legacy",
            "base_model_key": "mini-lm-l6-v2",
            "skip_fine_tune": True,
            "epochs": 3,
            "batch_size": 8,
            "promote_after_register": False,
            "embed_batch_size": 128,
            "dataset_path": "data/semantic/candidate-legacy-training-dataset.json",
        },
    )

    assert res.status_code == 422


def test_admin_create_train_job_rejects_unknown_base_model_key(client):
    dataset_id = _create_dataset(slug="dataset-unknown-base")

    res = client.post(
        "/admin/semantic-jobs/train",
        headers=_admin_headers(),
        json={
            "requested_by": "olmo",
            "dataset_id": dataset_id,
            "model_slug": "candidate-legacy",
            "base_model_key": "bogus",
            "skip_fine_tune": True,
            "epochs": 3,
            "batch_size": 8,
            "promote_after_register": False,
            "embed_batch_size": 128,
        },
    )

    assert res.status_code == 400
    assert "Unknown semantic base model" in res.json()["detail"]


def test_admin_promote_semantic_model_returns_accepted(client, monkeypatch):
    model_id = _create_model_with_bundle_artifact(slug="candidate", bundle=b"bundle-bytes")

    res = client.post(
        f"/admin/semantic-models/{model_id}/promote",
        headers=_admin_headers(),
        json={"requested_by": "olmo", "embed_batch_size": 128},
    )

    assert res.status_code == 202
    payload = res.json()
    assert payload["accepted"] is True
    assert payload["model_id"] == model_id
    assert payload["status"] == "pending"
    assert isinstance(payload["job_id"], str)

    with SessionLocal() as db:
        job = db.get(SemanticJob, payload["job_id"])
        assert job is not None
        assert job.job_type == "promote"
        assert job.model_id == model_id
        assert job.payload_json["embed_batch_size"] == 128


def test_admin_create_promote_job_returns_not_found_for_unknown_model(client, monkeypatch):
    res = client.post(
        "/admin/semantic-jobs/promote",
        headers=_admin_headers(),
        json={"requested_by": "olmo", "model_id": "missing-model", "embed_batch_size": 128},
    )

    assert res.status_code == 404


def test_admin_create_promote_job_returns_conflict_when_one_is_already_pending(client, monkeypatch):
    first_model_id = _create_model_with_bundle_artifact(slug="candidate-1", bundle=b"bundle-1")
    second_model_id = _create_model_with_bundle_artifact(slug="candidate-2", bundle=b"bundle-2")

    first_res = client.post(
        "/admin/semantic-jobs/promote",
        headers=_admin_headers(),
        json={"requested_by": "olmo", "model_id": first_model_id, "embed_batch_size": 128},
    )
    second_res = client.post(
        "/admin/semantic-jobs/promote",
        headers=_admin_headers(),
        json={"requested_by": "olmo", "model_id": second_model_id, "embed_batch_size": 128},
    )

    assert first_res.status_code == 201
    assert second_res.status_code == 409
    assert "already pending or running" in second_res.json()["detail"]
