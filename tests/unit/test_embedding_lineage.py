from __future__ import annotations

import sys
from dataclasses import replace
from types import SimpleNamespace

import pytest

from simple_harness_memory.core.embedding import (
    ReindexGeneration,
    ReindexStatus,
    activate_generation,
    advance_generation,
    fail_generation,
    verify_generation,
)
from simple_harness_memory.core.errors import EmbeddingError
from simple_harness_memory.embedders import (
    EMBEDDING_FORMAT_FINGERPRINT,
    CloudEmbedder,
    EmbeddingLineage,
    HashEmbedder,
    get_production_embedder,
)
from simple_harness_memory.embedders.bge import BGEM3Embedder


def test_lineage_is_complete_and_fingerprint_is_stable() -> None:
    lineage = HashEmbedder(dim=64).lineage
    assert all(
        (
            lineage.kind,
            lineage.provider,
            lineage.model,
            lineage.revision,
            lineage.normalization,
            lineage.format_fingerprint,
        )
    )
    assert lineage.dimension == 64
    assert lineage.format_fingerprint == EMBEDDING_FORMAT_FINGERPRINT
    assert lineage.lineage_id == HashEmbedder(dim=64).lineage.lineage_id
    assert lineage.lineage_id != HashEmbedder(dim=128).lineage.lineage_id
    assert lineage.lineage_id != replace(lineage, revision="2").lineage_id


@pytest.mark.parametrize(
    "field",
    ["kind", "provider", "model", "revision", "normalization", "format_fingerprint"],
)
def test_lineage_rejects_empty_fields(field: str) -> None:
    values = {
        "kind": "cloud",
        "provider": "provider",
        "model": "model",
        "revision": "rev",
        "dimension": 2,
        "normalization": "provider-defined",
        "format_fingerprint": "json-float-array:v1",
    }
    values[field] = " "
    with pytest.raises(ValueError, match=field):
        EmbeddingLineage(**values)  # type: ignore[arg-type]


class _WrongDimensionClient:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0] for _ in texts]


@pytest.mark.asyncio
async def test_cloud_lineage_and_dimension_validation() -> None:
    embedder = CloudEmbedder(
        _WrongDimensionClient(),
        provider="acme",
        model="embed-v2",
        revision="2026-08-01",
        dim=2,
    )
    assert embedder.lineage.provider == "acme"
    assert embedder.lineage.revision == "2026-08-01"
    with pytest.raises(EmbeddingError, match="dimension mismatch"):
        await embedder.embed("hello")


def test_production_factory_rejects_implicit_and_development_embedders(tmp_path) -> None:
    with pytest.raises(ValueError, match="development-only"):
        get_production_embedder("hash", dim=32)
    with pytest.raises(ValueError, match="resource_path, model, and revision"):
        get_production_embedder("bge")
    with pytest.raises(ValueError, match="existing directory"):
        get_production_embedder(
            "bge",
            resource_path=str(tmp_path / "missing"),
            model="BAAI/bge-m3",
            revision="r1",
        )
    with pytest.raises(ValueError, match="provider and revision"):
        get_production_embedder(
            "cloud",
            base_url="https://example.invalid",
            api_key="secret",
            model="embed",
            dim=2,
        )


def test_bge_forces_local_only_and_records_revision(monkeypatch, tmp_path) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    class _FakeModel:
        def __init__(self, model_ref: str, **kwargs: object) -> None:
            calls.append((model_ref, kwargs))

        def get_sentence_embedding_dimension(self) -> int:
            return 3

    monkeypatch.setitem(
        sys.modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=_FakeModel)
    )
    embedder = BGEM3Embedder(tmp_path, revision="snapshot-abc")
    assert calls == [
        (
            str(tmp_path),
            {"device": None, "local_files_only": True, "revision": "snapshot-abc"},
        )
    ]
    assert embedder.lineage.revision == "snapshot-abc"
    assert embedder.lineage.dimension == 3


def test_two_generation_only_activates_fully_verified_candidate() -> None:
    lineage = HashEmbedder(dim=16).lineage
    old = replace(
        ReindexGeneration("old", lineage),
        status=ReindexStatus.ACTIVE,
        indexed_rows=2,
        expected_rows=2,
        content_hash="old-hash",
        verification_hash="old-hash",
        sample_search_verified=True,
    )
    building = advance_generation(
        ReindexGeneration("new", replace(lineage, revision="2")),
        cursor="page-2",
        indexed_rows=2,
        content_hash="new-hash",
    )
    with pytest.raises(ValueError, match="not fully verified"):
        activate_generation(old, building)

    verified = verify_generation(
        building,
        expected_rows=2,
        verification_hash="new-hash",
        sample_search_verified=True,
    )
    retired, active = activate_generation(old, verified)
    assert retired is not None and retired.status is ReindexStatus.RETIRED
    assert active.status is ReindexStatus.ACTIVE
    assert old.status is ReindexStatus.ACTIVE  # helpers are immutable; adapter commits atomically


def test_reindex_restart_cursor_and_failure_keep_old_active() -> None:
    lineage = HashEmbedder(dim=16).lineage
    old = replace(ReindexGeneration("old", lineage), status=ReindexStatus.ACTIVE)
    building = advance_generation(
        ReindexGeneration("new", replace(lineage, revision="2")),
        cursor="page-1",
        indexed_rows=10,
        content_hash="hash-1",
    )
    resumed = advance_generation(
        building, cursor="page-2", indexed_rows=20, content_hash="hash-2"
    )
    failed = fail_generation(resumed)
    assert resumed.cursor == "page-2"
    assert failed.status is ReindexStatus.FAILED
    assert old.status is ReindexStatus.ACTIVE
    with pytest.raises(ValueError, match="row count mismatch"):
        verify_generation(
            resumed,
            expected_rows=21,
            verification_hash="hash-2",
            sample_search_verified=True,
        )
