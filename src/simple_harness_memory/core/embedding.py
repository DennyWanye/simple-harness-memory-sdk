"""Persistence-neutral state helpers for two-generation embedding reindex."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from simple_harness_memory.embedders.base import EmbeddingLineage


class ReindexStatus(StrEnum):
    BUILDING = "building"
    ACTIVE = "active"
    RETIRED = "retired"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ReindexGeneration:
    generation_id: str
    lineage: EmbeddingLineage
    status: ReindexStatus = ReindexStatus.BUILDING
    cursor: str | None = None
    indexed_rows: int = 0
    expected_rows: int | None = None
    content_hash: str | None = None
    verification_hash: str | None = None
    sample_search_verified: bool = False

    def __post_init__(self) -> None:
        if not self.generation_id.strip():
            raise ValueError("generation_id must be non-empty")
        if self.indexed_rows < 0 or (self.expected_rows is not None and self.expected_rows < 0):
            raise ValueError("reindex row counts must be non-negative")


def advance_generation(
    generation: ReindexGeneration,
    *,
    cursor: str | None,
    indexed_rows: int,
    content_hash: str,
) -> ReindexGeneration:
    if generation.status is not ReindexStatus.BUILDING:
        raise ValueError("only a building generation can advance")
    if indexed_rows < generation.indexed_rows:
        raise ValueError("indexed_rows cannot move backwards")
    if not content_hash.strip():
        raise ValueError("content_hash must be non-empty")
    return replace(
        generation, cursor=cursor, indexed_rows=indexed_rows, content_hash=content_hash
    )


def verify_generation(
    generation: ReindexGeneration,
    *,
    expected_rows: int,
    verification_hash: str,
    sample_search_verified: bool,
) -> ReindexGeneration:
    if generation.status is not ReindexStatus.BUILDING:
        raise ValueError("only a building generation can be verified")
    if expected_rows != generation.indexed_rows:
        raise ValueError("reindex row count mismatch")
    if not verification_hash.strip() or verification_hash != generation.content_hash:
        raise ValueError("reindex content hash mismatch")
    if not sample_search_verified:
        raise ValueError("sample search verification failed")
    return replace(
        generation,
        expected_rows=expected_rows,
        verification_hash=verification_hash,
        sample_search_verified=True,
    )


def activate_generation(
    active: ReindexGeneration | None, building: ReindexGeneration
) -> tuple[ReindexGeneration | None, ReindexGeneration]:
    """Return the atomic state transition a storage adapter must commit together."""

    if building.status is not ReindexStatus.BUILDING:
        raise ValueError("candidate generation is not building")
    if (
        building.expected_rows is None
        or building.expected_rows != building.indexed_rows
        or building.verification_hash != building.content_hash
        or not building.sample_search_verified
    ):
        raise ValueError("candidate generation is not fully verified")
    if active is not None and active.status is not ReindexStatus.ACTIVE:
        raise ValueError("current generation is not active")
    retired = replace(active, status=ReindexStatus.RETIRED) if active is not None else None
    return retired, replace(building, status=ReindexStatus.ACTIVE)


def fail_generation(generation: ReindexGeneration) -> ReindexGeneration:
    if generation.status is not ReindexStatus.BUILDING:
        raise ValueError("only a building generation can fail")
    return replace(generation, status=ReindexStatus.FAILED)
