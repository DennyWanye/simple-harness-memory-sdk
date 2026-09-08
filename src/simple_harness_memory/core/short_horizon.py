# SPDX-FileCopyrightText: 2026 DennyWanye
# SPDX-License-Identifier: BUSL-1.1

"""Authority-backed, bounded projection of recent primary-conversation evidence.

Raw evidence and Host conversation registrations are immutable authorities. This
module only builds and searches disposable projections: retention or suppression
may remove a chunk/vector/FTS row, but never the evidence or registration behind it.
"""

from __future__ import annotations

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
from simple_harness.contracts import FrozenJsonValue, thaw_json
from simple_harness.runtime import (
    EVIDENCE_NORMALIZATION_IDENTITY_UTF8_V1,
    ConversationEvidenceAuthorityVerifierPort,
    ConversationEvidenceMetadata,
    ConversationEvidenceRegistration,
    ConversationEvidenceRegistrationRef,
    ConversationEvidenceRole,
    InformationAttribute,
    PrivacyClass,
    verify_conversation_evidence_registration,
)

RECENT_CAUSAL_GROUP_LIMIT = 10
SHORT_HORIZON_RETENTION_SECONDS = 5 * 24 * 60 * 60
SHORT_HORIZON_HARD_DEADLINE_MS = 2_000
# 0.6.30（DECISION-2026-09-08-short-horizon-chunk-cap.md）：一条 chunk 的渲染内容
# （``role: public_text`` 行以 ``\n`` 连接）最多 2 048 个码点；超过的因果组按注册边界 →
# 段落 → 句子 → 空白 → 硬切（永不切在码点中间）确定性地切成多条内容寻址 chunk，
# 每因果组最多投影 8 段，之后的尾部不投影（审计记 ``truncated_group_count``）。
SHORT_HORIZON_CHUNK_MAX_CHARS = 2_048
SHORT_HORIZON_CHUNK_MAX_SEGMENTS = 8
# 分段 chunk 在 ``short_horizon_chunks.causal_group_id`` 列存的是投影键
# ``<causal_group_id>\x1f<k>/<K>``（未分段的组仍存裸 Host id，行形状与 0.6.29 逐字相同）；
# Host 注册的 ``causal_group_id`` 因此不得包含 U+001F（注册时 fail-closed）。
SHORT_HORIZON_PROJECTION_KEY_SEPARATOR = "\x1f"


class ShortHorizonDegradationCode(StrEnum):
    VECTOR_DEGRADED = "VECTOR_DEGRADED"
    NO_ACTIVE_GENERATION = "NO_ACTIVE_GENERATION"
    STALE_ACTIVE_GENERATION = "STALE_ACTIVE_GENERATION"
    DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"


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


def render_short_horizon_line(role: str, public_text: str) -> str:
    """The exact projected line for one registration item; frozen since S3 Task 4."""

    return f"{role}: {public_text}"


_PARAGRAPH_BOUNDARIES = frozenset("\n")
_SENTENCE_BOUNDARIES = frozenset("。！？!?")


def _preferred_cut(window: str, limit: int) -> int:
    """Cut position (1..limit) inside ``window`` preferring paragraph, sentence, whitespace.

    A boundary is only taken when the piece before it keeps at least half of the limit,
    so a stray newline near the start cannot produce a tiny fragment. Positions are
    Python ``str`` indices, i.e. Unicode code points: a cut can never land inside one.
    """

    floor = max(1, limit // 2)
    for is_boundary in (
        _PARAGRAPH_BOUNDARIES.__contains__,
        _SENTENCE_BOUNDARIES.__contains__,
        str.isspace,
    ):
        for index in range(limit - 1, floor - 2, -1):
            if is_boundary(window[index]):
                return index + 1
    return limit


def _split_text(text: str, limit: int) -> list[str]:
    """Partition ``text`` into pieces of at most ``limit`` code points (concatenation is exact)."""

    pieces: list[str] = []
    rest = text
    while len(rest) > limit:
        cut = _preferred_cut(rest[:limit], limit)
        pieces.append(rest[:cut])
        rest = rest[cut:]
    pieces.append(rest)
    return pieces


@dataclass(frozen=True, slots=True)
class ShortHorizonSplit:
    """Deterministic segmentation of one complete causal group's rendered content."""

    segments: tuple[str, ...]
    truncated: bool

    @property
    def segment_count(self) -> int:
        return len(self.segments)


def split_short_horizon_content(
    lines: Sequence[tuple[str, str]],
    *,
    max_chars: int | None = None,
    max_segments: int | None = None,
) -> ShortHorizonSplit:
    """Split ``(role, public_text)`` lines into chunk contents of at most ``max_chars`` code points.

    Invariants (pinned by tests): a group whose full rendering fits in ``max_chars`` yields
    exactly one segment equal to that rendering (so pre-0.6.30 chunk ids are unchanged);
    whole registration lines are packed first; an over-long line is cut at paragraph,
    then sentence, then whitespace boundaries, else hard-cut, never inside a code point;
    pieces of one line concatenate back to the original text; at most ``max_segments``
    segments are kept and ``truncated`` reports a dropped tail. Pure and process-independent.
    """

    # Defaults resolve at call time so the frozen constants stay the single authority.
    if max_chars is None:
        max_chars = SHORT_HORIZON_CHUNK_MAX_CHARS
    if max_segments is None:
        max_segments = SHORT_HORIZON_CHUNK_MAX_SEGMENTS
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 1:
        raise ShortHorizonIndexError("max_chars must be a positive integer")
    if isinstance(max_segments, bool) or not isinstance(max_segments, int) or max_segments < 1:
        raise ShortHorizonIndexError("max_segments must be a positive integer")
    segments: list[str] = []
    current: list[str] = []
    current_length = 0

    def emit(line: str) -> None:
        nonlocal current, current_length
        if current and current_length + 1 + len(line) > max_chars:
            segments.append("\n".join(current))
            current = []
            current_length = 0
        current.append(line)
        current_length = len(line) if current_length == 0 else current_length + 1 + len(line)

    for role, public_text in lines:
        line = render_short_horizon_line(role, public_text)
        if len(line) <= max_chars:
            emit(line)
            continue
        prefix_length = len(line) - len(public_text)
        for piece in _split_text(public_text, max(1, max_chars - prefix_length)):
            emit(render_short_horizon_line(role, piece))
    if current:
        segments.append("\n".join(current))
    truncated = len(segments) > max_segments
    return ShortHorizonSplit(tuple(segments[:max_segments]), truncated)


def short_horizon_projection_key(
    causal_group_id: str, segment_ordinal: int, segment_count: int
) -> str:
    """Projection-table key: the bare Host id when unsplit, else ``id\x1fk/K``."""

    if segment_count == 1:
        return causal_group_id
    return (
        f"{causal_group_id}{SHORT_HORIZON_PROJECTION_KEY_SEPARATOR}"
        f"{segment_ordinal}/{segment_count}"
    )


def parse_short_horizon_projection_key(key: str) -> tuple[str, int, int]:
    """Inverse of :func:`short_horizon_projection_key`; malformed keys fail closed."""

    causal_group_id, separator, suffix = key.rpartition(SHORT_HORIZON_PROJECTION_KEY_SEPARATOR)
    if not separator:
        return key, 1, 1
    ordinal_text, slash, count_text = suffix.partition("/")
    if (
        not causal_group_id
        or not slash
        or not ordinal_text.isdigit()
        or not count_text.isdigit()
        or SHORT_HORIZON_PROJECTION_KEY_SEPARATOR in causal_group_id
    ):
        raise ShortHorizonIndexError("short-horizon projection key is malformed")
    ordinal, count = int(ordinal_text), int(count_text)
    if count < 2 or not 1 <= ordinal <= count:
        raise ShortHorizonIndexError("short-horizon projection key is malformed")
    return causal_group_id, ordinal, count


def short_horizon_segment_payload_fields(
    segment_ordinal: int, segment_count: int
) -> dict[str, int]:
    """Extra ``chunk_id`` payload keys for split chunks; empty for unsplit groups (id stable)."""

    if segment_count == 1:
        return {}
    return {"segment_ordinal": segment_ordinal, "segment_count": segment_count}


@dataclass(frozen=True, slots=True)
class ShortHorizonProjectionRow:
    """What one stored chunk row must contain, re-derived from its complete causal group."""

    causal_group_id: str
    segment_ordinal: int
    segment_count: int
    content: str
    legacy_unsplit: bool


def resolve_short_horizon_projection_row(
    projection_key: str, lines: Sequence[tuple[str, str]]
) -> ShortHorizonProjectionRow:
    """Re-derive the expected content of a stored chunk row from its projection key.

    A bare key over a group that now splits is the pre-0.6.30 single-row shape: it stays
    valid (``legacy_unsplit=True``) until the next projection rebuild replaces it, so an
    upgraded database opens without being declared corrupt. Any other mismatch raises.
    """

    causal_group_id, ordinal, count = parse_short_horizon_projection_key(projection_key)
    split = split_short_horizon_content(lines)
    if count == 1:
        if split.segment_count == 1:
            return ShortHorizonProjectionRow(causal_group_id, 1, 1, split.segments[0], False)
        legacy = "\n".join(render_short_horizon_line(role, text) for role, text in lines)
        return ShortHorizonProjectionRow(causal_group_id, 1, 1, legacy, True)
    if split.segment_count != count:
        raise ShortHorizonIndexError("short-horizon projection key segment count differs")
    return ShortHorizonProjectionRow(
        causal_group_id, ordinal, count, split.segments[ordinal - 1], False
    )


def resolve_authorized_public_text(
    payload: Mapping[str, FrozenJsonValue], metadata: ConversationEvidenceMetadata
) -> str:
    """Resolve the one Host-authorized RFC 6901 string; never scan sibling leaves."""

    pointer = metadata.public_text_json_pointer
    expected_hash = metadata.public_text_hash
    normalization = metadata.public_text_normalization_version
    if pointer is None or expected_hash is None or normalization is None:
        raise ShortHorizonIndexError("conversation item has no authorized public text")
    current: object = thaw_json(cast(FrozenJsonValue, payload))
    for raw_token in pointer.split("/")[1:]:
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if token not in current:
                raise ShortHorizonIndexError("authorized public text pointer does not exist")
            current = current[token]
        elif isinstance(current, list):
            if not token.isdigit() or int(token) >= len(current):
                raise ShortHorizonIndexError("authorized public text array index is invalid")
            current = current[int(token)]
        else:
            raise ShortHorizonIndexError("authorized public text pointer traverses a scalar")
    if not isinstance(current, str):
        raise ShortHorizonIndexError("authorized public text pointer must resolve to a string")
    if normalization != EVIDENCE_NORMALIZATION_IDENTITY_UTF8_V1:
        raise ShortHorizonIndexError("authorized public text normalization is unsupported")
    # A tool-calling assistant may carry no text. Keep its exact authorized
    # bytes and ordinal; USER and every other non-blank contract stay strict.
    rendered = (
        current
        if current == "" and metadata.role is ConversationEvidenceRole.ASSISTANT
        else _bounded_non_blank(current, "authorized public text", max_bytes=1_048_576)
    )
    if hashlib.sha256(rendered.encode("utf-8")).hexdigest() != expected_hash:
        raise ShortHorizonIndexError("authorized public text hash differs")
    return rendered


class ShortHorizonProjectionAuthorityPort(ConversationEvidenceAuthorityVerifierPort, Protocol):
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
        public_text=resolve_authorized_public_text(
            registration.envelope.sanitized_payload, metadata
        ),
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
    effective_privacy_class: PrivacyClass
    information_attributes: tuple[InformationAttribute, ...]
    classification_authority_refs: tuple[str, ...]
    segment_ordinal: int = 1
    segment_count: int = 1

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
            (subject, conversation_id, group_id) for _, group_id in ordered[:recent_group_limit]
        )

    chunks: list[ShortHorizonChunk] = []
    for key, items in complete.items():
        if key in recent or any(item.suppressed for item in items):
            continue
        if not any(item.public_text.strip() for item in items):
            # Role labels alone are not searchable conversation content.
            continue
        metadata = items[0].metadata
        occurred_at = max(item.metadata.occurred_at for item in items)
        expires_at = occurred_at + retention_seconds
        if occurred_at > now or now > expires_at:
            continue
        split = split_short_horizon_content(
            [(item.metadata.role.value, item.public_text) for item in items]
        )
        privacy_rank = {
            PrivacyClass.PUBLIC: 0,
            PrivacyClass.PERSONAL: 1,
            PrivacyClass.SENSITIVE: 2,
            PrivacyClass.RESTRICTED: 3,
        }
        privacy_values = tuple(
            cast(PrivacyClass, item.metadata.effective_privacy_class) for item in items
        )
        effective_privacy_class = max(privacy_values, key=privacy_rank.__getitem__)
        information_attributes = tuple(
            sorted(
                {
                    attribute
                    for item in items
                    for attribute in cast(
                        tuple[InformationAttribute, ...], item.metadata.information_attributes
                    )
                },
                key=lambda attribute: attribute.value,
            )
        )
        classification_authority_refs = tuple(
            sorted({cast(str, item.metadata.classification_authority_ref) for item in items})
        )
        for segment_index, content in enumerate(split.segments, start=1):
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            payload = {
                "subject": metadata.subject,
                "primary_conversation_id": metadata.primary_conversation_id,
                "causal_group_id": metadata.causal_group_id,
                "causal_group_sequence": metadata.causal_group_sequence,
                "registration_hashes": [item.registration.registration_hash for item in items],
                "content_hash": content_hash,
                **short_horizon_segment_payload_fields(segment_index, split.segment_count),
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
                effective_privacy_class=effective_privacy_class,
                information_attributes=information_attributes,
                classification_authority_refs=classification_authority_refs,
                segment_ordinal=segment_index,
                segment_count=split.segment_count,
              )
            )
    return tuple(
        sorted(
            chunks,
            key=lambda item: (
                item.subject,
                item.primary_conversation_id,
                item.causal_group_sequence,
                item.segment_ordinal,
                item.chunk_ref,
            ),
        )
    )


@dataclass(frozen=True, slots=True)
class VectorSearchHit:
    memory_ref: str
    score: float


@dataclass(frozen=True, slots=True)
class ShortHorizonRecallHit:
    chunk_ref: str
    content: str
    content_hash: str
    score: float
    occurred_at: float
    effective_privacy_class: PrivacyClass
    information_attributes: tuple[InformationAttribute, ...]
    classification_authority_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ShortHorizonRecallResult:
    hits: tuple[ShortHorizonRecallHit, ...]
    audit_id: str
    eligible_count: int
    fts_count: int
    entity_time_count: int
    vector_count: int
    used_generation_id: str | None
    degradation_code: ShortHorizonDegradationCode | None


@dataclass(frozen=True, slots=True)
class ShortHorizonProjectionBuildResult:
    """0.6.30：``split_group_count`` 为本次被切成多段的因果组数，``truncated_group_count``
    为超过 ``SHORT_HORIZON_CHUNK_MAX_SEGMENTS`` 而丢弃尾段的因果组数（带默认值，位置构造不变）。"""

    projected_chunk_count: int
    removed_chunk_count: int
    audit_id: str
    split_group_count: int = 0
    truncated_group_count: int = 0


@dataclass(frozen=True, slots=True)
class ShortHorizonGenerationBuildResult:
    """One durable generation build attempt.

    0.6.27：``audit_id`` 可为 ``None``，``cas_miss`` 为 True 表示嵌入期间 chunk 清单变了、
    本次不激活（审计表只记录激活，故不落审计行）；下一 tick 会以新清单重建。
    """

    generation_id: str | None
    vector_count: int
    activated: bool
    replayed: bool
    audit_id: str | None
    cas_miss: bool = False


class _ExactVectorGenerationCache:
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

    @property
    def dimension(self) -> int:
        return int(self._matrix.shape[1])

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


__all__ = (
    "RECENT_CAUSAL_GROUP_LIMIT",
    "SHORT_HORIZON_CHUNK_MAX_CHARS",
    "SHORT_HORIZON_CHUNK_MAX_SEGMENTS",
    "SHORT_HORIZON_HARD_DEADLINE_MS",
    "SHORT_HORIZON_PROJECTION_KEY_SEPARATOR",
    "SHORT_HORIZON_RETENTION_SECONDS",
    "ShortHorizonChunk",
    "ShortHorizonDegradationCode",
    "ShortHorizonIndexError",
    "ShortHorizonProjectionAuthorityPort",
    "ShortHorizonProjectionBuildResult",
    "ShortHorizonProjectionRow",
    "ShortHorizonGenerationBuildResult",
    "ShortHorizonRecallHit",
    "ShortHorizonRecallResult",
    "ShortHorizonSplit",
    "build_short_horizon_chunks",
    "parse_short_horizon_projection_key",
    "render_short_horizon_line",
    "resolve_authorized_public_text",
    "resolve_short_horizon_projection_row",
    "short_horizon_projection_key",
    "short_horizon_segment_payload_fields",
    "split_short_horizon_content",
)
