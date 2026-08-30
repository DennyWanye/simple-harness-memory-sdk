# SPDX-FileCopyrightText: 2026 DennyWanye
# SPDX-License-Identifier: BUSL-1.1

"""Authority-backed, bounded projection of recent primary-conversation evidence.

Raw evidence and Host conversation registrations are immutable authorities. This
module only builds and searches disposable projections: retention or suppression
may remove a chunk/vector/FTS row, but never the evidence or registration behind it.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import time
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, cast

import numpy as np
from simple_harness.contracts import FrozenJsonValue, JsonValue, canonical_json, thaw_json
from simple_harness.runtime import (
    ConversationEvidenceAuthorityVerifierPort,
    ConversationEvidenceMetadata,
    ConversationEvidenceRegistration,
    ConversationEvidenceRegistrationRef,
    verify_conversation_evidence_registration,
)

from simple_harness_memory.features.lexical import lexical_similarity

RECENT_CAUSAL_GROUP_LIMIT = 10
SHORT_HORIZON_RETENTION_SECONDS = 5 * 24 * 60 * 60
SHORT_HORIZON_HARD_DEADLINE_MS = 2_000


class ShortHorizonDegradationCode(StrEnum):
    VECTOR_DEGRADED = "VECTOR_DEGRADED"


class ShortHorizonIndexError(ValueError):
    """The derived short-horizon input violates its frozen contract."""


class StaleVectorGeneration(ShortHorizonIndexError):
    """The cache does not represent the repository's current generation."""


class VectorDeadlineExceeded(TimeoutError):
    """Short-horizon search did not complete inside the caller's deadline."""


def _bounded_non_blank(value: str, name: str, *, max_bytes: int = 16_384) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or "\x00" in value
        or len(value.encode("utf-8")) > max_bytes
    ):
        raise ShortHorizonIndexError(f"{name} must be non-blank, bounded, and contain no NUL")
    return value


def _digest(value: str, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ShortHorizonIndexError(f"{name} must be a lowercase SHA-256 digest")
    try:
        bytes.fromhex(value)
    except ValueError as exc:
        raise ShortHorizonIndexError(f"{name} must be a lowercase SHA-256 digest") from exc
    if value != value.lower():
        raise ShortHorizonIndexError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _finite_non_negative(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ShortHorizonIndexError(f"{name} must be finite and non-negative")
    if value < 0:
        raise ShortHorizonIndexError(f"{name} must be finite and non-negative")
    return float(value)


def _public_text_from_payload(payload: Mapping[str, FrozenJsonValue]) -> str:
    """Render only already-sanitized string leaves in stable JSON traversal order."""

    value = thaw_json(cast(FrozenJsonValue, payload))
    leaves: list[str] = []

    def visit(item: object) -> None:
        if isinstance(item, str):
            if item.strip():
                leaves.append(item)
            return
        if isinstance(item, Mapping):
            for key in sorted(item):
                visit(item[key])
            return
        if isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    rendered = "\n".join(leaves) if leaves else canonical_json(cast(JsonValue, value))
    return _bounded_non_blank(rendered, "sanitized public text", max_bytes=1_048_576)


class ShortHorizonProjectionAuthorityPort(
    ConversationEvidenceAuthorityVerifierPort, Protocol
):
    """Host/Memory authority required before evidence can enter a projection."""

    async def is_evidence_suppressed(self, *, evidence_id: str, subject: str) -> bool: ...


class _PinnedConversationVerifier:
    """Pin one authority result so verification cannot observe a changing resolver."""

    def __init__(self, registration: ConversationEvidenceRegistration) -> None:
        self._registration = registration

    async def resolve_conversation_registration(
        self, reference: ConversationEvidenceRegistrationRef
    ) -> ConversationEvidenceRegistration:
        return self._registration


@dataclass(frozen=True, slots=True)
class _VerifiedConversationItem:
    reference: ConversationEvidenceRegistrationRef
    registration: ConversationEvidenceRegistration
    metadata: ConversationEvidenceMetadata
    public_text: str
    suppressed: bool


async def _resolve_verified_item(
    reference: ConversationEvidenceRegistrationRef,
    authority: ShortHorizonProjectionAuthorityPort,
) -> _VerifiedConversationItem:
    if not isinstance(reference, ConversationEvidenceRegistrationRef):
        raise TypeError("short-horizon input must use ConversationEvidenceRegistrationRef")
    registration = await authority.resolve_conversation_registration(reference)
    if not isinstance(registration, ConversationEvidenceRegistration):
        raise TypeError("conversation authority returned an invalid registration")
    metadata = await verify_conversation_evidence_registration(
        reference, _PinnedConversationVerifier(registration)
    )
    suppressed = await authority.is_evidence_suppressed(
        evidence_id=registration.envelope.evidence_id,
        subject=metadata.subject,
    )
    if not isinstance(suppressed, bool):
        raise TypeError("suppression authority must return a boolean")
    return _VerifiedConversationItem(
        reference=reference,
        registration=registration,
        metadata=metadata,
        public_text=_public_text_from_payload(registration.envelope.sanitized_payload),
        suppressed=suppressed,
    )


@dataclass(frozen=True, slots=True)
class ShortHorizonChunk:
    """Rebuildable projection of one complete, authority-registered causal group."""

    chunk_ref: str
    content_hash: str
    subject: str
    primary_conversation_id: str
    causal_group_id: str
    causal_group_sequence: int
    registration_refs: tuple[ConversationEvidenceRegistrationRef, ...]
    evidence_refs: tuple[str, ...]
    envelope_hashes: tuple[str, ...]
    source_refs: tuple[str, ...]
    role_sequence: tuple[str, ...]
    content: str
    occurred_at: float
    expires_at: float
    task_scope_ids: tuple[str, ...]
    entity_refs: tuple[str, ...]
    tool_terminal_receipt_refs: tuple[str, ...]

    @property
    def byte_estimate(self) -> int:
        return len(self.content.encode("utf-8"))

    @property
    def token_estimate(self) -> int:
        # Deterministic conservative estimate; provider calibration belongs to S5.
        return max(1, (self.byte_estimate + 2) // 3)


def _validate_complete_group(items: Sequence[_VerifiedConversationItem]) -> None:
    metadata = tuple(item.metadata for item in items)
    first = metadata[0]
    expected = (
        first.subject,
        first.primary_conversation_id,
        first.causal_group_id,
        first.causal_group_sequence,
        first.group_item_count,
        first.ordered_group_manifest_hash,
    )
    if any(
        (
            item.subject,
            item.primary_conversation_id,
            item.causal_group_id,
            item.causal_group_sequence,
            item.group_item_count,
            item.ordered_group_manifest_hash,
        )
        != expected
        for item in metadata
    ):
        raise ShortHorizonIndexError("causal group authority metadata is inconsistent")
    ordinals = {item.item_ordinal for item in metadata}
    if ordinals != set(range(1, first.group_item_count + 1)):
        raise ShortHorizonIndexError("causal group registration is incomplete")
    evidence_ids = {item.registration.envelope.evidence_id for item in items}
    registration_ids = {item.registration.registration_id for item in items}
    if len(evidence_ids) != len(items) or len(registration_ids) != len(items):
        raise ShortHorizonIndexError("causal group contains duplicate authority registrations")


async def build_short_horizon_chunks(
    registration_refs: Sequence[ConversationEvidenceRegistrationRef],
    *,
    authority: ShortHorizonProjectionAuthorityPort,
    now: float,
    recent_group_limit: int = RECENT_CAUSAL_GROUP_LIMIT,
    retention_seconds: float = SHORT_HORIZON_RETENTION_SECONDS,
) -> tuple[ShortHorizonChunk, ...]:
    """Build eligible chunks after Host registration and suppression verification.

    The newest ``recent_group_limit`` complete causal groups remain in direct
    working context. Older groups are projected only through the inclusive
    five-day boundary. Any suppressed item suppresses its whole derived causal
    group so partial context cannot become misleading; raw evidence is untouched.
    """

    now = _finite_non_negative(now, "now")
    retention_seconds = _finite_non_negative(retention_seconds, "retention_seconds")
    if isinstance(recent_group_limit, bool) or not isinstance(recent_group_limit, int):
        raise ShortHorizonIndexError("recent_group_limit must be a non-negative integer")
    if recent_group_limit < 0:
        raise ShortHorizonIndexError("recent_group_limit must be a non-negative integer")
    if len({ref.registration_id for ref in registration_refs}) != len(registration_refs):
        raise ShortHorizonIndexError("registration references must be unique")

    resolved = [
        await _resolve_verified_item(reference, authority) for reference in registration_refs
    ]
    grouped: dict[tuple[str, str, str], list[_VerifiedConversationItem]] = defaultdict(list)
    for item in resolved:
        metadata = item.metadata
        grouped[
            (metadata.subject, metadata.primary_conversation_id, metadata.causal_group_id)
        ].append(item)

    complete: dict[tuple[str, str, str], tuple[_VerifiedConversationItem, ...]] = {}
    for key, raw_items in grouped.items():
        items = tuple(sorted(raw_items, key=lambda item: item.metadata.item_ordinal))
        _validate_complete_group(items)
        complete[key] = items

    recent: set[tuple[str, str, str]] = set()
    groups_by_conversation: dict[tuple[str, str], list[tuple[int, str]]] = defaultdict(list)
    for (subject, conversation_id, group_id), items in complete.items():
        groups_by_conversation[(subject, conversation_id)].append(
            (items[0].metadata.causal_group_sequence, group_id)
        )
    for (subject, conversation_id), groups in groups_by_conversation.items():
        ordered = sorted(groups, key=lambda value: (value[0], value[1]), reverse=True)
        recent.update(
            (subject, conversation_id, group_id)
            for _, group_id in ordered[:recent_group_limit]
        )

    chunks: list[ShortHorizonChunk] = []
    for key, items in complete.items():
        if key in recent or any(item.suppressed for item in items):
            continue
        metadata = items[0].metadata
        occurred_at = max(item.metadata.occurred_at for item in items)
        expires_at = occurred_at + retention_seconds
        if occurred_at > now or now > expires_at:
            continue
        content = "\n".join(
            f"{item.metadata.role.value}: {item.public_text}" for item in items
        )
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        payload = {
            "subject": metadata.subject,
            "primary_conversation_id": metadata.primary_conversation_id,
            "causal_group_id": metadata.causal_group_id,
            "causal_group_sequence": metadata.causal_group_sequence,
            "registration_hashes": [item.registration.registration_hash for item in items],
            "content_hash": content_hash,
        }
        chunk_hash = hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        chunks.append(
            ShortHorizonChunk(
                chunk_ref=f"short:{chunk_hash}",
                content_hash=content_hash,
                subject=metadata.subject,
                primary_conversation_id=metadata.primary_conversation_id,
                causal_group_id=metadata.causal_group_id,
                causal_group_sequence=metadata.causal_group_sequence,
                registration_refs=tuple(item.reference for item in items),
                evidence_refs=tuple(item.registration.envelope.evidence_id for item in items),
                envelope_hashes=tuple(item.registration.envelope.envelope_hash for item in items),
                source_refs=tuple(item.registration.envelope.source_ref for item in items),
                role_sequence=tuple(item.metadata.role.value for item in items),
                content=content,
                occurred_at=occurred_at,
                expires_at=expires_at,
                task_scope_ids=tuple(
                    dict.fromkeys(
                        item.metadata.task_scope_id
                        for item in items
                        if item.metadata.task_scope_id is not None
                    )
                ),
                entity_refs=tuple(
                    dict.fromkeys(entity for item in items for entity in item.metadata.entities)
                ),
                tool_terminal_receipt_refs=tuple(
                    dict.fromkeys(
                        item.metadata.tool_causal_link.terminal_receipt_id
                        for item in items
                        if item.metadata.tool_causal_link is not None
                    )
                ),
            )
        )
    return tuple(
        sorted(
            chunks,
            key=lambda item: (
                item.subject,
                item.primary_conversation_id,
                item.causal_group_sequence,
                item.chunk_ref,
            ),
        )
    )


@dataclass(frozen=True, slots=True)
class ShortHorizonSearchRow:
    memory_ref: str
    subject: str
    content: str
    occurred_at: float
    expires_at: float
    task_scope_ids: tuple[str, ...] = ()
    entity_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _bounded_non_blank(self.memory_ref, "memory_ref")
        _bounded_non_blank(self.subject, "subject")
        _bounded_non_blank(self.content, "content", max_bytes=1_048_576)
        occurred_at = _finite_non_negative(self.occurred_at, "occurred_at")
        expires_at = _finite_non_negative(self.expires_at, "expires_at")
        if expires_at <= occurred_at:
            raise ShortHorizonIndexError("expires_at must be after occurred_at")


@dataclass(frozen=True, slots=True)
class PermissionFilteredFtsCandidates:
    """Repository authority result for one exact disclosure context."""

    context_hash: str
    authority_receipt_hash: str
    rows: tuple[ShortHorizonSearchRow, ...]

    def __post_init__(self) -> None:
        _digest(self.context_hash, "context_hash")
        _digest(self.authority_receipt_hash, "authority_receipt_hash")
        rows = tuple(self.rows)
        if not all(isinstance(row, ShortHorizonSearchRow) for row in rows):
            raise TypeError("rows must contain ShortHorizonSearchRow values")
        if len({row.memory_ref for row in rows}) != len(rows):
            raise ShortHorizonIndexError("permission-filtered rows must be unique")
        object.__setattr__(self, "rows", rows)


class PermissionFilteredFtsAuthorityPort(Protocol):
    """Repository seam that applies identity/privacy/status/suppression before FTS."""

    async def permission_filtered_fts_candidates(
        self,
        *,
        query: str,
        disclosure_context_hash: str,
        active_generation_id: str,
        now: float,
    ) -> PermissionFilteredFtsCandidates: ...


@dataclass(frozen=True, slots=True)
class VectorSearchHit:
    memory_ref: str
    score: float


@dataclass(frozen=True, slots=True)
class ShortHorizonSearchResult:
    hits: tuple[VectorSearchHit, ...]
    active_generation_id: str
    used_generation_id: str | None
    fts_authority_receipt_hash: str | None
    degradation_code: ShortHorizonDegradationCode | None
    elapsed_ms: float


class ExactVectorGenerationCache:
    """Read-only numpy float32 exact-scan cache for exactly one generation."""

    __slots__ = ("generation_id", "lineage_id", "memory_refs", "_matrix", "_row_by_ref")

    def __init__(
        self,
        *,
        generation_id: str,
        lineage_id: str,
        memory_refs: Sequence[str],
        vectors: Sequence[Sequence[float]] | np.ndarray,
    ) -> None:
        _bounded_non_blank(generation_id, "generation_id")
        _bounded_non_blank(lineage_id, "lineage_id")
        refs = tuple(memory_refs)
        if not refs or len(set(refs)) != len(refs):
            raise ShortHorizonIndexError("memory_refs must be non-empty and unique")
        for ref in refs:
            _bounded_non_blank(ref, "memory_ref")
        matrix = np.asarray(vectors, dtype=np.float32)
        if matrix.ndim != 2 or matrix.shape[0] != len(refs) or matrix.shape[1] < 1:
            raise ShortHorizonIndexError("vectors must be a finite rows-by-dimension matrix")
        if not bool(np.isfinite(matrix).all()):
            raise ShortHorizonIndexError("vectors must contain only finite values")
        norms = np.linalg.norm(matrix, axis=1)
        if bool(np.any(norms == 0)):
            raise ShortHorizonIndexError("vectors must be non-zero")
        normalized = np.ascontiguousarray(matrix / norms[:, None], dtype=np.float32)
        normalized.flags.writeable = False
        self.generation_id = generation_id
        self.lineage_id = lineage_id
        self.memory_refs = refs
        self._matrix = normalized
        self._row_by_ref = {ref: index for index, ref in enumerate(refs)}

    @property
    def size_bytes(self) -> int:
        return int(self._matrix.nbytes)

    def exact_search(
        self,
        query_vector: Sequence[float],
        *,
        active_generation_id: str,
        eligible_refs: frozenset[str],
        limit: int,
        deadline_monotonic: float,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> tuple[VectorSearchHit, ...]:
        if active_generation_id != self.generation_id:
            raise StaleVectorGeneration("active generation differs from cached generation")
        if monotonic() >= deadline_monotonic:
            raise VectorDeadlineExceeded("vector deadline elapsed before scan")
        if isinstance(limit, bool) or limit < 1:
            raise ShortHorizonIndexError("limit must be positive")
        vector = np.asarray(query_vector, dtype=np.float32)
        if vector.ndim != 1 or vector.shape[0] != self._matrix.shape[1]:
            raise ShortHorizonIndexError("query vector dimension differs from cache")
        if not bool(np.isfinite(vector).all()):
            raise ShortHorizonIndexError("query vector must be finite")
        norm = float(np.linalg.norm(vector))
        if norm == 0:
            raise ShortHorizonIndexError("query vector must be non-zero")
        indices = [self._row_by_ref[ref] for ref in eligible_refs if ref in self._row_by_ref]
        if not indices:
            return ()
        scores = self._matrix[np.asarray(indices, dtype=np.intp)] @ (vector / norm)
        if monotonic() > deadline_monotonic:
            raise VectorDeadlineExceeded("vector scan exceeded deadline")
        ranked = sorted(
            (
                VectorSearchHit(self.memory_refs[index], float(score))
                for index, score in zip(indices, scores, strict=True)
            ),
            key=lambda hit: (-hit.score, hit.memory_ref),
        )
        return tuple(ranked[:limit])


async def search_short_horizon(
    query: str,
    *,
    query_vector: Sequence[float],
    active_generation_id: str,
    cache: ExactVectorGenerationCache | None,
    fts_authority: PermissionFilteredFtsAuthorityPort,
    disclosure_context_hash: str,
    now: float,
    limit: int,
    deadline_ms: int,
    monotonic: Callable[[], float] = time.monotonic,
) -> ShortHorizonSearchResult:
    """Search active vectors or degrade only through permission-filtered FTS rows."""

    _bounded_non_blank(query, "query")
    _bounded_non_blank(active_generation_id, "active_generation_id")
    _digest(disclosure_context_hash, "disclosure_context_hash")
    now = _finite_non_negative(now, "now")
    if isinstance(deadline_ms, bool) or not 1 <= deadline_ms <= SHORT_HORIZON_HARD_DEADLINE_MS:
        raise ShortHorizonIndexError("deadline_ms must be within the two-second hard deadline")
    if isinstance(limit, bool) or limit < 1:
        raise ShortHorizonIndexError("limit must be positive")

    started = monotonic()
    deadline = started + deadline_ms / 1_000
    try:
        candidates = await asyncio.wait_for(
            fts_authority.permission_filtered_fts_candidates(
                query=query,
                disclosure_context_hash=disclosure_context_hash,
                active_generation_id=active_generation_id,
                now=now,
            ),
            timeout=max(0.0, deadline - monotonic()),
        )
    except TimeoutError:
        return ShortHorizonSearchResult(
            hits=(),
            active_generation_id=active_generation_id,
            used_generation_id=None,
            fts_authority_receipt_hash=None,
            degradation_code=ShortHorizonDegradationCode.VECTOR_DEGRADED,
            elapsed_ms=max(0.0, (monotonic() - started) * 1_000),
        )
    if not isinstance(candidates, PermissionFilteredFtsCandidates):
        raise TypeError("FTS authority returned an invalid result")
    if candidates.context_hash != disclosure_context_hash:
        raise ShortHorizonIndexError("permission filter context differs from disclosure context")
    if any(row.expires_at < now for row in candidates.rows):
        raise ShortHorizonIndexError("permission authority returned expired short-horizon rows")

    eligible_refs = frozenset(row.memory_ref for row in candidates.rows)
    if cache is not None:
        try:
            vector_hits = cache.exact_search(
                query_vector,
                active_generation_id=active_generation_id,
                eligible_refs=eligible_refs,
                limit=limit,
                deadline_monotonic=deadline,
                monotonic=monotonic,
            )
            return ShortHorizonSearchResult(
                hits=vector_hits,
                active_generation_id=active_generation_id,
                used_generation_id=cache.generation_id,
                fts_authority_receipt_hash=candidates.authority_receipt_hash,
                degradation_code=None,
                elapsed_ms=max(0.0, (monotonic() - started) * 1_000),
            )
        except (StaleVectorGeneration, VectorDeadlineExceeded):
            pass

    hits: list[VectorSearchHit] = []
    for row in candidates.rows:
        if monotonic() >= deadline:
            break
        score = lexical_similarity(query, row.content)
        if score > 0:
            hits.append(VectorSearchHit(row.memory_ref, score))
    ranked = tuple(sorted(hits, key=lambda hit: (-hit.score, hit.memory_ref))[:limit])
    return ShortHorizonSearchResult(
        hits=ranked,
        active_generation_id=active_generation_id,
        used_generation_id=None,
        fts_authority_receipt_hash=candidates.authority_receipt_hash,
        degradation_code=ShortHorizonDegradationCode.VECTOR_DEGRADED,
        elapsed_ms=max(0.0, (monotonic() - started) * 1_000),
    )


__all__ = (
    "RECENT_CAUSAL_GROUP_LIMIT",
    "SHORT_HORIZON_HARD_DEADLINE_MS",
    "SHORT_HORIZON_RETENTION_SECONDS",
    "ExactVectorGenerationCache",
    "PermissionFilteredFtsAuthorityPort",
    "PermissionFilteredFtsCandidates",
    "ShortHorizonChunk",
    "ShortHorizonDegradationCode",
    "ShortHorizonIndexError",
    "ShortHorizonProjectionAuthorityPort",
    "ShortHorizonSearchResult",
    "ShortHorizonSearchRow",
    "StaleVectorGeneration",
    "VectorDeadlineExceeded",
    "VectorSearchHit",
    "build_short_horizon_chunks",
    "search_short_horizon",
)
