from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from simple_harness.contracts import canonical_json
from simple_harness.runtime import (
    ConflictStatus,
    EpistemicStatus,
    EvidenceActorRole,
    EvidenceProvenance,
    EvidenceSourceKind,
    EvidenceSupportKind,
    ExistingMemoryTarget,
    InformationAttribute,
    MemoryMutationKind,
    PrivacyClass,
    SemanticLifecycleState,
    SemanticMemoryPayload,
    ValidTimeInterval,
    VerificationState,
)

from simple_harness_memory.backends.sqlite_v5 import SQLiteHumanMemoryBackend
from simple_harness_memory.cognitive.twin_builder import TwinGraphView
from simple_harness_memory.core.errors import MemoryOwnershipConflict
from simple_harness_memory.core.identity import MemoryPrincipal, MemoryScope
from simple_harness_memory.core.manager import MemoryManager
from simple_harness_memory.core.port import MemoryBackend
from simple_harness_memory.core.suppression import (
    OrdinaryMemoryPurpose,
    SuppressionRequest,
    SuppressionRevokeRequest,
    SuppressionScopeKind,
)
from simple_harness_memory.world.port import WorldModelPort
from tests.integration.test_cognitive_mutation_repository_v5 import (
    _admitted,
    _operation,
    _plan,
    _prepared,
    _principal,
    _span,
    _with_action_authorities,
)


async def _memory_id(backend: SQLiteHumanMemoryBackend) -> str:
    async with backend.connection.execute(
        "SELECT memory_id FROM cognitive_memory_heads"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None
    return str(row[0])


def _manager(backend: SQLiteHumanMemoryBackend) -> MemoryManager:
    return MemoryManager(
        cast(MemoryBackend, backend),
        cast(WorldModelPort, object()),
    )


@pytest.mark.asyncio
async def test_graph_public_manager_updates_after_correction_forget_and_reopen(
    tmp_path: Path,
) -> None:
    path = tmp_path / "twin-graph-correction.db"
    backend, envelope, _receipt, span, authority = await _prepared(
        path, now=lambda: 20.0
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_plan(envelope, _operation(span)),
    )
    memory_id = await _memory_id(backend)

    initial = await _manager(backend).get_twin_graph_view(principal=_principal())
    assert len(initial.nodes) == 1
    assert initial.nodes[0].memory_id == memory_id
    assert initial.nodes[0].revision == 1
    assert initial.nodes[0].source_refs[0].evidence_ref_hash == hashlib.sha256(
        envelope.evidence_id.encode("utf-8")
    ).hexdigest()
    assert initial.nodes[0].can_correct is True
    assert initial.nodes[0].can_forget is True
    assert TwinGraphView.from_json(initial.to_json()) == initial
    with pytest.raises(MemoryOwnershipConflict):
        await backend.get_twin_graph_view(
            principal=MemoryPrincipal(
                "other-deployment", "household-1", "actor-1", "session-graph"
            )
        )

    correction_span = replace(
        span, support_kind=EvidenceSupportKind.EXPLICIT_USER_CORRECTION
    )
    correction = replace(
        _operation(correction_span),
        operation_id="correct-style",
        kind=MemoryMutationKind.REVISE,
        target=ExistingMemoryTarget(memory_id, 1),
        payload=SemanticMemoryPayload(
            "user:self", "response_style", "detailed", ("corrected",)
        ),
        reason_code="explicit_user_correction",
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_with_action_authorities(
            _plan(
                envelope,
                correction,
                base_revision=2,
                plan_id="correct-plan",
                idempotency_key="correct-key",
            ),
            authority,
        ),
    )
    corrected = await backend.get_twin_graph_view(principal=_principal())
    assert [(item.revision, item.label) for item in corrected.nodes] == [
        (2, 'user:self · response_style · "detailed"')
    ]
    assert corrected.edges == ()
    assert "concise" not in canonical_json(corrected.to_json())
    assert corrected.payload_hash != initial.payload_hash

    forget = replace(
        correction,
        operation_id="forget-style",
        kind=MemoryMutationKind.SUPPRESS,
        target=ExistingMemoryTarget(memory_id, 2),
        payload=None,
        lifecycle_state=SemanticLifecycleState.FORGOTTEN,
        reason_code="explicit_user_forget",
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_with_action_authorities(
            _plan(
                envelope,
                forget,
                base_revision=3,
                plan_id="forget-plan",
                idempotency_key="forget-key",
            ),
            authority,
            nonce_prefix="forget-nonce",
        ),
    )
    forgotten = await backend.get_twin_graph_view(principal=_principal())
    assert forgotten.nodes == ()
    assert forgotten.edges == ()
    assert "detailed" not in canonical_json(forgotten.to_json())
    await backend.close()

    reopened = SQLiteHumanMemoryBackend(path, now=lambda: 20.0)
    await reopened.initialize()
    rebuilt = await reopened.get_twin_graph_view(principal=_principal())
    assert rebuilt == forgotten
    assert TwinGraphView.from_json(rebuilt.to_json()).payload_hash == rebuilt.payload_hash
    await reopened.close()


@pytest.mark.asyncio
async def test_graph_projection_suppression_redaction_and_expiry_are_leak_free(
    tmp_path: Path,
) -> None:
    backend, envelope, _receipt, span, _authority = await _prepared(
        tmp_path / "twin-graph-view-policy.db", now=lambda: 20.0
    )
    operation = replace(
        _operation(
            span,
            privacy=PrivacyClass.SENSITIVE,
            attributes=(InformationAttribute.HEALTH,),
        ),
        payload=SemanticMemoryPayload(
            "user:self", "health_note", "sensitive-health-canary", ()
        ),
        valid_time_interval=ValidTimeInterval(None, 21.0),
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_plan(envelope, operation),
    )
    memory_id = await _memory_id(backend)

    redacted = await backend.get_twin_graph_view(principal=_principal())
    assert len(redacted.nodes) == 1
    assert redacted.nodes[0].redacted is True
    assert redacted.nodes[0].label == "Semantic memory"
    assert "sensitive-health-canary" not in canonical_json(redacted.to_json())

    restricted_operation = replace(
        _operation(
            span,
            operation_id="create-restricted",
            privacy=PrivacyClass.RESTRICTED,
            attributes=(InformationAttribute.IDENTITY,),
        ),
        payload=SemanticMemoryPayload(
            "user:self", "private_identity", "restricted-identity-canary", ()
        ),
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_plan(
            envelope,
            restricted_operation,
            base_revision=2,
            plan_id="restricted-plan",
            idempotency_key="restricted-key",
        ),
    )
    restricted_hidden = await backend.get_twin_graph_view(principal=_principal())
    assert len(restricted_hidden.nodes) == 1
    assert "restricted-identity-canary" not in canonical_json(restricted_hidden.to_json())

    suppression = await backend.suppress(
        SuppressionRequest(
            "hide-graph-memory",
            "actor-1",
            SuppressionScopeKind.MEMORY,
            memory_id,
            "user_forget",
            20.0,
            OrdinaryMemoryPurpose.PROJECTION,
        )
    )
    hidden = await backend.get_twin_graph_view(principal=_principal())
    assert hidden.nodes == ()
    assert "sensitive-health-canary" not in canonical_json(hidden.to_json())

    await backend.revoke_suppression(
        SuppressionRevokeRequest(
            "restore-graph-memory",
            "actor-1",
            suppression.directive_id,
            "user_restore",
            20.0,
        )
    )
    assert len((await backend.get_twin_graph_view(principal=_principal())).nodes) == 1

    backend._now = lambda: 21.0
    expired = await backend.get_twin_graph_view(principal=_principal())
    assert expired.nodes == ()
    assert "sensitive-health-canary" not in canonical_json(expired.to_json())
    await backend.close()


@pytest.mark.asyncio
async def test_graph_contested_group_is_complete_or_entirely_hidden(tmp_path: Path) -> None:
    backend, envelope, _receipt, span, authority = await _prepared(
        tmp_path / "twin-graph-conflict.db", now=lambda: 20.0
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_plan(envelope, _operation(span)),
    )
    memory_id = await _memory_id(backend)
    challenger_envelope, challenger_receipt = _admitted(evidence_id="evidence-2")
    challenger_span = _span(challenger_envelope, challenger_receipt)
    authority.register_admitted(
        challenger_envelope, challenger_receipt, challenger_span
    )
    await backend.ingest_committed_evidence(
        challenger_envelope, challenger_receipt
    )
    contest = replace(
        _operation(challenger_span),
        operation_id="contest-style",
        kind=MemoryMutationKind.CONTEST,
        target=ExistingMemoryTarget(memory_id, 1),
        payload=SemanticMemoryPayload(
            "user:self", "response_style", "verbose", ("challenger",)
        ),
        conflict_status=ConflictStatus.CONTESTED,
        reason_code="distinct_evidence_contest",
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_plan(
            challenger_envelope,
            contest,
            base_revision=2,
            plan_id="contest-plan",
            idempotency_key="contest-key",
        ),
    )

    contested = await backend.get_twin_graph_view(principal=_principal())
    assert len(contested.nodes) == 2
    assert all(item.status == "contested" for item in contested.nodes)
    assert [item.relation_kind for item in contested.edges] == ["contests"]
    assert [item.can_correct for item in contested.nodes] == [False, True]

    await backend.suppress(
        SuppressionRequest(
            "hide-challenger-evidence",
            "actor-1",
            SuppressionScopeKind.EVIDENCE,
            challenger_envelope.evidence_id,
            "user_forget",
            20.0,
            OrdinaryMemoryPurpose.PROJECTION,
        )
    )
    hidden = await backend.get_twin_graph_view(principal=_principal())
    assert hidden.nodes == ()
    assert hidden.edges == ()
    encoded = canonical_json(hidden.to_json())
    assert "concise" not in encoded
    assert "verbose" not in encoded
    await backend.close()


@pytest.mark.asyncio
async def test_graph_includes_non_authoritative_model_inference_as_display_only(
    tmp_path: Path,
) -> None:
    backend, _envelope, _receipt, _span_one, authority = await _prepared(
        tmp_path / "twin-graph-inference.db", now=lambda: 20.0
    )
    envelope, receipt = _admitted(
        source_kind=EvidenceSourceKind.ASSISTANT_MESSAGE,
        evidence_id="inference-evidence",
    )
    span = _span(
        envelope,
        receipt,
        actor_role=EvidenceActorRole.ASSISTANT,
        provenance=EvidenceProvenance.MODEL_OUTPUT,
        support_kind=EvidenceSupportKind.MODEL_INFERENCE,
    )
    authority.register_admitted(envelope, receipt, span)
    await backend.ingest_committed_evidence(envelope, receipt)
    inferred = replace(
        _operation(
            span,
            epistemic_status=EpistemicStatus.LLM_INFERENCE,
            verification_state=VerificationState.UNVERIFIED,
        ),
        operation_id="infer-preference",
        lifecycle_state=SemanticLifecycleState.CANDIDATE,
        reason_code="model_inference_candidate",
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_plan(
            envelope,
            inferred,
            plan_id="inference-plan",
            idempotency_key="inference-key",
        ),
    )
    view = await backend.get_twin_graph_view(
        principal=MemoryPrincipal(
            "deployment-1", "household-1", "actor-1", "session-graph"
        )
    )
    assert len(view.nodes) == 1
    assert view.nodes[0].status == "inferred"
    assert view.nodes[0].confidence == 0.35
    assert view.nodes[0].can_correct is True
    assert view.nodes[0].can_forget is True
    await backend.close()
