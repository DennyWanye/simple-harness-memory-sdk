"""Product-neutral public ports for the memory SDK."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Protocol

from simple_harness.runtime import (
    DisclosureContext,
    MemoryMutationApplyResult,
    MemoryMutationPlan,
    ProcedureObservationAuthorityRef,
    ProspectiveSignalAuthorityRef,
    RecallContext,
    RecallPlan,
)

if TYPE_CHECKING:
    from simple_harness.runtime import (
        RecallContextUseAuthorizationRequestV1,
        RecallContextUseReceiptV1,
        RecallResultPageRequestV1,
        RecallResultPageV1,
    )

from simple_harness_memory.cognitive.twin_builder import TwinGraphView
from simple_harness_memory.core.audit import (
    AuditAccessAuthorityRefV1,
    AuditAggregateMetricsV1,
    AuditTraceCursor,
    AuditTracePage,
    AuditTraceQuery,
    CanonicalStateManifestAccessV1,
)
from simple_harness_memory.core.evidence import EvidenceIngestionReceipt
from simple_harness_memory.core.identity import MemoryPrincipal, MemoryScope
from simple_harness_memory.core.lifecycle_results import (
    ProcedureObservationApplyResult,
    ProspectiveSignalApplyResult,
)
from simple_harness_memory.core.models import (
    BoundedRecallResult,
    Fact,
    FactConflict,
    Hit,
    MemoryApplyResult,
    Message,
)
from simple_harness_memory.core.recall import TypedRecallExecution
from simple_harness_memory.core.short_horizon import (
    ShortHorizonGenerationBuildResult,
    ShortHorizonProjectionBuildResult,
    ShortHorizonRecallResult,
)
from simple_harness_memory.core.suppression import (
    SealedAuditAccessReceipt,
    SuppressionDecision,
    SuppressionRequest,
    SuppressionRevokeRequest,
)
from simple_harness_memory.core.twin import DigitalTwin


class MemoryBackend(ABC):
    """Memory backend contract with explicit, immutable user ownership."""

    @abstractmethod
    async def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        user_id: str,
        source_event_id: str,
        payload_hash: str | None = None,
        salience: float = 0.0,
        decay_rate: float = 0.02,
    ) -> MemoryApplyResult: ...

    @abstractmethod
    async def get_recent_messages(
        self,
        session_id: str,
        limit: int = 20,
        *,
        user_id: str,
    ) -> list[Message]: ...

    @abstractmethod
    async def get_message(self, message_id: int, *, user_id: str) -> Message | None: ...

    @abstractmethod
    async def get_facts(
        self,
        subject: str = "user",
        category: str | None = None,
        active_only: bool = True,
        *,
        user_id: str,
        limit: int | None = None,
    ) -> list[Fact]: ...

    @abstractmethod
    async def forget_fact(self, fact_id: int, reason: str = "", *, user_id: str) -> bool: ...

    @abstractmethod
    async def get_digital_twin(
        self,
        subject: str = "user",
        *,
        user_id: str,
    ) -> DigitalTwin: ...

    @abstractmethod
    async def update_digital_twin(self, twin: DigitalTwin, *, user_id: str) -> None: ...

    @abstractmethod
    async def suggest_questions(
        self,
        subject: str = "user",
        *,
        user_id: str,
    ) -> list[str]: ...

    @abstractmethod
    async def detect_inconsistencies(
        self,
        subject: str = "user",
        *,
        user_id: str,
    ) -> list[FactConflict]: ...

    @abstractmethod
    async def recall(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 10,
        *,
        user_id: str,
    ) -> list[Hit]: ...

    @abstractmethod
    async def recall_bounded(
        self,
        query: str,
        *,
        user_id: str,
        session_id: str,
        context_query_id: str,
        query_hash: str | None = None,
        max_results: int | None = None,
        max_bytes: int | None = None,
        timeout_seconds: float | None = None,
    ) -> BoundedRecallResult: ...

    @abstractmethod
    async def release_recall_result(
        self,
        *,
        user_id: str,
        context_query_id: str,
        result_hash: str,
    ) -> None: ...

    @abstractmethod
    async def cleanup_recall_results(
        self,
        *,
        user_id: str,
        now: float | None = None,
        limit: int | None = None,
    ) -> int: ...

    @abstractmethod
    async def recall_and_reinforce(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 10,
        *,
        user_id: str,
    ) -> list[Hit]: ...

    @abstractmethod
    async def vector_search(
        self,
        query: str,
        limit: int = 20,
        *,
        user_id: str,
    ) -> list[Hit]: ...

    @abstractmethod
    async def daily_decay(
        self,
        *,
        user_id: str,
        limit: int | None = None,
    ) -> dict[str, int]: ...

    @abstractmethod
    async def summarize_old_sessions(
        self,
        older_than_days: int = 7,
        max_sessions: int = 5,
        *,
        user_id: str,
    ) -> dict[str, int]: ...

    @abstractmethod
    async def record_workspace_action(
        self,
        session_id: str,
        action_type: str,
        payload: dict,
        *,
        user_id: str,
    ) -> None: ...

    @abstractmethod
    async def reindex(
        self,
        embedder=None,
        *,
        user_id: str,
        limit: int | None = None,
    ) -> int: ...

    async def initialize(self) -> None:
        """Initialize the backend."""

    async def close(self) -> None:
        """Close the backend."""

    async def diagnostics_snapshot(self) -> dict[str, object]:
        """Return bounded aggregate operational health."""

        return {"health": "healthy"}

    async def __aenter__(self) -> MemoryBackend:
        await self.initialize()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()


class AgentMemoryBackend(Protocol):
    """Internal v4 backend surface consumed by the direct AgentMemory integration."""

    async def agent_recall(
        self,
        *,
        principal: MemoryPrincipal,
        scopes: tuple[MemoryScope, ...],
        query_id: str,
        query_hash: str,
        query_text: str,
        max_items: int,
        max_bytes: int,
    ) -> tuple[dict[str, object], str, bool]: ...

    async def agent_record_turn(
        self,
        *,
        principal: MemoryPrincipal,
        scope: MemoryScope,
        turn_id: str,
        payload_hash: str,
        user_text: str,
        assistant_text: str,
        write_fence: str | None,
        turn_started_at: float,
    ) -> tuple[str, str]: ...

    async def agent_export(
        self,
        principal: MemoryPrincipal,
        scopes: tuple[MemoryScope, ...],
        *,
        cursor: int = 0,
        limit: int = 100,
    ) -> tuple[list[dict[str, object]], int | None]: ...

    async def agent_delete_scopes(
        self, principal: MemoryPrincipal, scopes: tuple[MemoryScope, ...]
    ) -> dict[str, int | str]: ...


class CognitiveMemoryBackend(Protocol):
    """Strict v5 cognitive write boundary, separate from the legacy backend.

    Implementations own identity/evidence/suppression/revision/idempotency
    authority and must apply the exact Harness plan as one transaction.  The
    pure compiler in :mod:`simple_harness_memory.core.mutations` is not an
    authority substitute.
    """

    async def apply_memory_mutation_plan(
        self,
        *,
        principal: MemoryPrincipal,
        scope: MemoryScope,
        plan: MemoryMutationPlan,
    ) -> MemoryMutationApplyResult: ...

    async def ingest_committed_evidence(
        self, envelope: object, receipt: object
    ) -> EvidenceIngestionReceipt: ...

    async def register_conversation_evidence(self, reference: object) -> object: ...

    async def suppress(
        self,
        request: SuppressionRequest,
        *,
        principal: MemoryPrincipal | None = None,
    ) -> SuppressionDecision: ...

    async def revoke_suppression(
        self,
        request: SuppressionRevokeRequest,
        *,
        principal: MemoryPrincipal | None = None,
    ) -> SuppressionDecision: ...

    async def record_procedure_observation(
        self,
        *,
        principal: MemoryPrincipal,
        scope: MemoryScope,
        reference: ProcedureObservationAuthorityRef,
    ) -> ProcedureObservationApplyResult: ...

    async def apply_prospective_signal(
        self,
        *,
        principal: MemoryPrincipal,
        scope: MemoryScope,
        reference: ProspectiveSignalAuthorityRef,
    ) -> ProspectiveSignalApplyResult: ...

    async def rebuild_short_horizon_projection(
        self, *, principal: MemoryPrincipal, now: float | None = None
    ) -> ShortHorizonProjectionBuildResult: ...

    async def rebuild_short_horizon_generation(
        self, *, now: float | None = None
    ) -> ShortHorizonGenerationBuildResult: ...

    async def recall_short_horizon(
        self,
        *,
        principal: MemoryPrincipal,
        query: str,
        disclosure_context: DisclosureContext,
        limit: int = 10,
        deadline_ms: int = 2_000,
        now: float | None = None,
    ) -> ShortHorizonRecallResult: ...

    async def cleanup_short_horizon(
        self, *, principal: MemoryPrincipal, now: float | None = None
    ) -> int: ...

    async def execute_typed_recall(
        self,
        *,
        principal: MemoryPrincipal,
        context: RecallContext,
        plan: RecallPlan,
        now: float | None = None,
    ) -> TypedRecallExecution: ...

    async def page_typed_recall_result(
        self,
        *,
        principal: MemoryPrincipal,
        request: RecallResultPageRequestV1,
    ) -> RecallResultPageV1: ...

    async def authorize_recall_context_use(
        self,
        *,
        principal: MemoryPrincipal,
        request: RecallContextUseAuthorizationRequestV1,
        now: float | None = None,
    ) -> RecallContextUseReceiptV1: ...

    async def get_twin_graph_view(
        self, *, principal: MemoryPrincipal
    ) -> TwinGraphView: ...

    async def authorize_audit_access(
        self,
        *,
        principal: MemoryPrincipal,
        authority_ref: AuditAccessAuthorityRefV1,
    ) -> SealedAuditAccessReceipt: ...

    async def export_audit_trace(
        self,
        query: AuditTraceQuery,
        *,
        principal: MemoryPrincipal | None = None,
        limit: int = 20,
        cursor: AuditTraceCursor | None = None,
    ) -> AuditTracePage: ...

    async def export_sealed_audit_trace(
        self,
        query: AuditTraceQuery,
        access_receipt: SealedAuditAccessReceipt,
        *,
        principal: MemoryPrincipal | None = None,
        limit: int = 20,
        cursor: AuditTraceCursor | None = None,
    ) -> AuditTracePage: ...

    async def get_audit_aggregate_metrics(
        self, *, principal: MemoryPrincipal
    ) -> AuditAggregateMetricsV1: ...

    async def export_canonical_state_manifest(
        self,
        *,
        requester: MemoryPrincipal,
        target_principal: MemoryPrincipal,
        access_receipt: SealedAuditAccessReceipt,
    ) -> CanonicalStateManifestAccessV1: ...
