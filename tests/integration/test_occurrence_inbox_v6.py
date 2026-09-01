# SPDX-FileCopyrightText: 2026 DennyWanye
# SPDX-License-Identifier: Apache-2.0

"""0.6 consumer contract: read-only occurrence inbox and outbox projections.

Injection goes through the production write path (``apply_prospective_signal``
with a test-injected signal authority resolver) — never raw DB seeding — so
every asserted row is production-shaped (S5a challenge ledger S5A-BR-F3).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from simple_harness.runtime import (
    ProspectiveLifecycleState,
    ProspectiveSignalKind,
)

from simple_harness_memory import (
    OccurrenceInboxEntryV1,
    OccurrenceInboxPageV1,
    OutboxPageV1,
)
from simple_harness_memory.core.errors import (
    MemoryOwnershipConflict,
    MemoryValidationError,
)
from simple_harness_memory.core.identity import MemoryPrincipal, MemoryScope
from tests.integration.test_cognitive_mutation_repository_v5 import _principal
from tests.integration.test_prospective_signal_repository_v5 import (
    _grant,
    _setup,
)


async def _matched_occurrence(tmp_path: Path):
    clock = [20.0]
    backend, authority, memory_id, revision, outbox_id, outbox_hash = await _setup(
        tmp_path / "inbox.db", clock
    )
    accepted = _grant(
        authority,
        memory_id=memory_id,
        revision=revision,
        kind=ProspectiveSignalKind.REGISTRATION_ACCEPTED,
        transition_from=ProspectiveLifecycleState.PENDING,
        transition_to=ProspectiveLifecycleState.PENDING,
        observed_at=20.0,
        outbox_id=outbox_id,
        outbox_hash=outbox_hash,
    )
    await backend.apply_prospective_signal(
        principal=_principal(), scope=MemoryScope.personal("actor-1"), reference=accepted
    )
    clock[0] = 30.0
    due = _grant(
        authority,
        memory_id=memory_id,
        revision=1,
        kind=ProspectiveSignalKind.TIME_DUE,
        transition_from=ProspectiveLifecycleState.PENDING,
        transition_to=ProspectiveLifecycleState.TRIGGERED,
        observed_at=30.0,
        signal_id="due-signal",
        receipt_id="due-receipt",
    )
    applied = await backend.apply_prospective_signal(
        principal=_principal(), scope=MemoryScope.personal("actor-1"), reference=due
    )
    return backend, memory_id, applied


@pytest.mark.asyncio
async def test_inbox_returns_production_shaped_matched_occurrence(
    tmp_path: Path,
) -> None:
    backend, memory_id, applied = await _matched_occurrence(tmp_path)
    try:
        page = await backend.read_occurrence_inbox(principal=_principal())
        assert isinstance(page, OccurrenceInboxPageV1)
        matched = [e for e in page.entries if e.outcome == "matched"]
        assert len(matched) == 1
        entry = matched[0]
        assert isinstance(entry, OccurrenceInboxEntryV1)
        assert entry.memory_id == memory_id
        assert entry.prospective_revision == 1
        # lifecycle_state is the CURRENT head state (TRIGGERED after apply).
        assert entry.lifecycle_state == ProspectiveLifecycleState.TRIGGERED.value
        assert entry.signal_kind == ProspectiveSignalKind.TIME_DUE.value
        assert entry.action_text == "send report"
        assert len(entry.occurrence_key) == 64
        assert len(entry.event_hash) == 64
        assert entry.effective_privacy_class == "personal"
        assert entry.event_ref

        # Stable ordering key is part of the returned shape; replay identical.
        replay = await backend.read_occurrence_inbox(principal=_principal())
        assert replay.entries == page.entries
        assert page.next_after is None

        # after-anchor pagination excludes the row itself.
        anchored = await backend.read_occurrence_inbox(
            principal=_principal(),
            after=(entry.occurred_at, entry.event_id),
        )
        assert entry.event_id not in {e.event_id for e in anchored.entries}
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_inbox_is_principal_scoped_and_validates_limits(
    tmp_path: Path,
) -> None:
    backend, _memory_id, _applied = await _matched_occurrence(tmp_path)
    try:
        stranger = MemoryPrincipal("deployment-1", "household-1", "actor-2", "session-9")
        with pytest.raises(MemoryOwnershipConflict):
            await backend.read_occurrence_inbox(principal=stranger)
        with pytest.raises(MemoryValidationError):
            await backend.read_occurrence_inbox(principal=_principal(), limit=0)
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_outbox_reader_is_read_only_projection(tmp_path: Path) -> None:
    backend, _memory_id, _applied = await _matched_occurrence(tmp_path)
    try:
        page = await backend.read_outbox(
            principal=_principal(),
            states=("pending", "claimed", "applied", "dead_letter"),
        )
        assert isinstance(page, OutboxPageV1)
        assert page.entries, "prospective registration must have an outbox row"
        topics = {e.topic for e in page.entries}
        assert "memory.prospective.registration.requested" in topics
        entry = next(
            e for e in page.entries
            if e.topic == "memory.prospective.registration.requested"
        )
        assert entry.state in {"pending", "claimed", "applied", "dead_letter"}
        assert len(entry.payload_hash) == 64
        replay = await backend.read_outbox(
            principal=_principal(),
            states=("pending", "claimed", "applied", "dead_letter"),
        )
        assert replay.entries == page.entries
        with pytest.raises(MemoryValidationError):
            await backend.read_outbox(principal=_principal(), states=("bogus",))
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_v7_facade_rejects_development_embedder(tmp_path: Path) -> None:
    from simple_harness_memory import build_human_memory_v7
    from simple_harness_memory.embedders.mock import HashEmbedder
    from simple_harness_memory.core.errors import (
        MemoryProductionConfigurationError,
    )

    with pytest.raises(MemoryProductionConfigurationError):
        await build_human_memory_v7(
            tmp_path / "guarded.db", short_horizon_embedder=HashEmbedder(32)
        )
    manager = await build_human_memory_v7(
        tmp_path / "allowed.db",
        short_horizon_embedder=HashEmbedder(32),
        allow_development_embedder=True,
    )
    await manager.close()


@pytest.mark.asyncio
async def test_inbox_marks_suppressed_memories(tmp_path: Path) -> None:
    from simple_harness_memory.core.suppression import (
        SuppressionRequest,
        SuppressionScopeKind,
    )

    backend, memory_id, _applied = await _matched_occurrence(tmp_path)
    try:
        await backend.suppress(
            SuppressionRequest(
                request_id="suppress-1",
                subject="actor-1",
                scope_kind=SuppressionScopeKind.MEMORY,
                scope_ref=memory_id,
                reason_code="user_requested_forgetting",
                requested_at=50.0,
            ),
            principal=_principal(),
        )
        page = await backend.read_occurrence_inbox(principal=_principal())
        matched = [e for e in page.entries if e.outcome == "matched"]
        assert matched and all(e.suppressed for e in matched)
    finally:
        await backend.close()
