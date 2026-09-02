"""MemoryManager — explicit-user facade over a backend and world model."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from simple_harness_memory.config import MemoryResourceBounds
from simple_harness_memory.core.audit import (
    AuditAccessAuthorityPort,
    AuditAccessAuthorityRefV1,
    AuditAggregateMetricsV1,
    AuditTraceCursor,
    AuditTracePage,
    AuditTraceQuery,
    CanonicalStateManifestAccessV1,
)
from simple_harness_memory.core.errors import (
    HarnessIntegrationExtraRequired,
    MemoryIdempotencyConflict,
    MemoryOwnershipConflict,
    MemoryProductionConfigurationError,
)
from simple_harness_memory.core.evidence import EvidenceIngestionReceipt, IngestedEvidenceRecord
from simple_harness_memory.core.identity import (
    ExportPage,
    MemoryPrincipal,
    MemoryScope,
    PrincipalRegistrationReceipt,
    PrivacyReceipt,
    ScopeKind,
)
from simple_harness_memory.core.models import Fact
from simple_harness_memory.core.mutation_receipts import MemoryMutationReceiptView
from simple_harness_memory.core.mutations import InformationClassificationPolicy
from simple_harness_memory.core.observability import CorrelationInput, MemoryObservability
from simple_harness_memory.core.port import CognitiveMemoryBackend, MemoryBackend
from simple_harness_memory.core.suppression import (
    SealedAuditAccessReceipt,
    SuppressionDecision,
    SuppressionRequest,
    SuppressionRevokeRequest,
)
from simple_harness_memory.world.port import WorldModelPort

if TYPE_CHECKING:
    from simple_harness import (
        CommittedTurn,
        CommittedTurnReceipt,
        DisclosureContext,
        MemoryMutationApplyReceiptRef,
        MemoryMutationApplyResult,
        MemoryMutationPlan,
        MemoryRecallRequest,
        MemoryRecallResult,
        MemoryReleaseRequest,
        RecallContext,
        RecallContextUseAuthorizationRequestV1,
        RecallContextUseReceiptV1,
        RecallPlan,
        RecallResultPageRequestV1,
        RecallResultPageV1,
        SanitizedEvidenceEnvelope,
        SanitizedEvidenceReceipt,
    )

    from simple_harness_memory.cognitive.twin_builder import TwinGraphView
    from simple_harness_memory.core.jobs import AnalysisLineage
    from simple_harness_memory.core.recall import TypedRecallExecution
    from simple_harness_memory.core.short_horizon import (
        ShortHorizonGenerationBuildResult,
        ShortHorizonProjectionBuildResult,
        ShortHorizonRecallResult,
    )

logger = structlog.get_logger("simple_harness_memory.core.manager")


class _NullWorldModel(WorldModelPort):
    async def get_temporal_context(self):
        from simple_harness_memory.world.temporal import build_temporal_context

        return build_temporal_context()

    async def get_recent_events(self, days=3):
        return []

    async def get_weather(self, location):
        return None

    async def check_knowledge_boundary(self, query):
        return None

    async def get_personalized_news(self, interests, categories=None):
        return []


class MemoryManager:
    def __init__(
        self,
        backend: MemoryBackend | CognitiveMemoryBackend,
        world: WorldModelPort,
        *,
        observability_sink=None,
        correlation: CorrelationInput = None,
        observability: MemoryObservability | None = None,
    ) -> None:
        self._backend: Any = backend
        self.world = world
        self._closed = False
        inherited = getattr(backend, "observability", None)
        self._observability = observability or (
            inherited
            if observability_sink is None and correlation is None and inherited is not None
            else MemoryObservability(observability_sink, correlation)
        )
        setter = getattr(backend, "set_observability", None)
        if callable(setter):
            setter(self._observability)

    @property
    def backend(self) -> MemoryBackend | CognitiveMemoryBackend:
        return self._backend

    async def ingest_committed_evidence(
        self,
        envelope: SanitizedEvidenceEnvelope,
        receipt: SanitizedEvidenceReceipt,
        *,
        analysis_lineage: AnalysisLineage | None = None,
    ) -> EvidenceIngestionReceipt:
        if analysis_lineage is None:
            return await self._backend.ingest_committed_evidence(envelope, receipt)
        return await self._backend.ingest_committed_evidence(
            envelope, receipt, analysis_lineage=analysis_lineage
        )

    async def register_conversation_evidence(self, reference: object) -> object:
        return await self._backend.register_conversation_evidence(reference)

    async def apply_memory_mutation_plan(
        self,
        *,
        principal: MemoryPrincipal,
        scope: MemoryScope,
        plan: MemoryMutationPlan,
    ) -> MemoryMutationApplyResult:
        return await self._backend.apply_memory_mutation_plan(
            principal=principal, scope=scope, plan=plan
        )

    async def get_memory_mutation_receipt_view(
        self,
        *,
        principal: MemoryPrincipal,
        receipt_ref: MemoryMutationApplyReceiptRef,
    ) -> MemoryMutationReceiptView:
        """Return exact committed operation bindings for one owned receipt."""

        return await self._backend.get_memory_mutation_receipt_view(
            principal=principal,
            receipt_ref=receipt_ref,
        )

    async def suppress(
        self, *, principal: MemoryPrincipal, request: SuppressionRequest
    ) -> SuppressionDecision:
        return await self._backend.suppress(request, principal=principal)

    async def revoke_suppression(
        self, *, principal: MemoryPrincipal, request: SuppressionRevokeRequest
    ) -> SuppressionDecision:
        return await self._backend.revoke_suppression(request, principal=principal)

    async def authorize_audit_access(
        self,
        *,
        principal: MemoryPrincipal,
        authority_ref: AuditAccessAuthorityRefV1,
    ) -> SealedAuditAccessReceipt:
        return await self._backend.authorize_audit_access(
            principal=principal, authority_ref=authority_ref
        )

    async def export_audit_trace(
        self,
        *,
        principal: MemoryPrincipal,
        query: AuditTraceQuery,
        limit: int = 20,
        cursor: AuditTraceCursor | None = None,
    ) -> AuditTracePage:
        return await self._backend.export_audit_trace(
            query, principal=principal, limit=limit, cursor=cursor
        )

    async def export_sealed_audit_trace(
        self,
        *,
        requester: MemoryPrincipal,
        query: AuditTraceQuery,
        access_receipt: SealedAuditAccessReceipt,
        limit: int = 20,
        cursor: AuditTraceCursor | None = None,
    ) -> AuditTracePage:
        return await self._backend.export_sealed_audit_trace(
            query,
            access_receipt,
            requester=requester,
            limit=limit,
            cursor=cursor,
        )

    async def export_sealed_evidence(
        self,
        *,
        requester: MemoryPrincipal,
        evidence_id: str,
        access_receipt: SealedAuditAccessReceipt,
    ) -> IngestedEvidenceRecord:
        return await self._backend.export_sealed_evidence(
            evidence_id,
            access_receipt,
            requester=requester,
        )

    async def get_audit_aggregate_metrics(
        self, *, principal: MemoryPrincipal
    ) -> AuditAggregateMetricsV1:
        return await self._backend.get_audit_aggregate_metrics(principal=principal)

    async def export_canonical_state_manifest(
        self,
        *,
        requester: MemoryPrincipal,
        target_principal: MemoryPrincipal,
        access_receipt: SealedAuditAccessReceipt,
    ) -> CanonicalStateManifestAccessV1:
        return await self._backend.export_canonical_state_manifest(
            requester=requester,
            target_principal=target_principal,
            access_receipt=access_receipt,
        )

    async def recall_short_horizon(
        self,
        *,
        principal: MemoryPrincipal,
        query: str,
        disclosure_context: DisclosureContext,
        limit: int = 10,
        deadline_ms: int = 2_000,
        now: float | None = None,
    ) -> ShortHorizonRecallResult:
        """Recall short-horizon context without exposing vector generations or caches."""

        operation = getattr(self._backend, "recall_short_horizon")
        return await operation(
            principal=principal,
            query=query,
            disclosure_context=disclosure_context,
            limit=limit,
            deadline_ms=deadline_ms,
            now=now,
        )

    async def execute_typed_recall(
        self,
        *,
        principal: MemoryPrincipal,
        context: RecallContext,
        plan: RecallPlan,
        now: float | None = None,
    ) -> TypedRecallExecution:
        operation = getattr(self._backend, "execute_typed_recall")
        return await operation(principal=principal, context=context, plan=plan, now=now)

    async def read_occurrence_inbox(
        self,
        *,
        principal: MemoryPrincipal,
        after: tuple[float, str] | None = None,
        limit: int = 100,
    ):
        """Read-only prospective occurrence inbox (0.6 frozen consumer contract)."""

        operation = getattr(self._backend, "read_occurrence_inbox")
        return await operation(principal=principal, after=after, limit=limit)

    async def register_principal_owner(
        self, principal: MemoryPrincipal, scope: MemoryScope
    ) -> PrincipalRegistrationReceipt:
        """幂等登记 subject 的属主形状（deployment/household）；重复调用返回同一回执。"""

        operation = getattr(self._backend, "register_principal_owner", None)
        if operation is None:
            raise RuntimeError("backend does not support principal owner registration")
        result: PrincipalRegistrationReceipt = await operation(principal, scope)
        return result

    async def read_outbox(
        self,
        *,
        principal: MemoryPrincipal,
        states: tuple[str, ...] = ("pending",),
        after: tuple[float, str] | None = None,
        limit: int = 100,
    ):
        """Read-only durable outbox projection; consumers never claim rows."""

        operation = getattr(self._backend, "read_outbox")
        return await operation(
            principal=principal, states=states, after=after, limit=limit
        )

    async def page_typed_recall_result(
        self,
        *,
        principal: MemoryPrincipal,
        request: RecallResultPageRequestV1,
    ) -> RecallResultPageV1:
        operation = getattr(self._backend, "page_typed_recall_result")
        return await operation(principal=principal, request=request)

    async def authorize_recall_context_use(
        self,
        *,
        principal: MemoryPrincipal,
        request: RecallContextUseAuthorizationRequestV1,
        now: float | None = None,
    ) -> RecallContextUseReceiptV1:
        operation = getattr(self._backend, "authorize_recall_context_use")
        return await operation(principal=principal, request=request, now=now)

    async def get_twin_graph_view(
        self, *, principal: MemoryPrincipal
    ) -> TwinGraphView:
        """Build the display-only cognitive graph; never an Agent context input."""

        operation = getattr(self._backend, "get_twin_graph_view")
        return await operation(principal=principal)

    async def rebuild_short_horizon_projection(
        self, *, principal: MemoryPrincipal, now: float | None = None
    ) -> ShortHorizonProjectionBuildResult:
        operation = getattr(self._backend, "rebuild_short_horizon_projection")
        return await operation(principal=principal, now=now)

    async def rebuild_short_horizon_generation(
        self, *, now: float | None = None
    ) -> ShortHorizonGenerationBuildResult:
        operation = getattr(self._backend, "rebuild_short_horizon_generation")
        return await operation(now=now)

    @classmethod
    async def build(
        cls,
        db_path=None,
        *,
        enable_world_model=False,
        backend=None,
        embedder=None,
        reranker=None,
        summarizer=None,
        world=None,
        bounds: MemoryResourceBounds | None = None,
        observability_sink=None,
        correlation: CorrelationInput = None,
    ):
        if isinstance(embedder, str):
            from simple_harness_memory.embedders.factory import get_embedder

            embedder = get_embedder(embedder)
        if backend is None:
            kwargs = {
                "embedder": embedder,
                "reranker": reranker,
                "summarizer": summarizer,
                "bounds": bounds,
                "observability_sink": observability_sink,
                "correlation": correlation,
            }
            if db_path is not None:
                from simple_harness_memory.backends.sqlite import SQLiteMemoryBackend

                backend = SQLiteMemoryBackend(db_path, **kwargs)
            else:
                from simple_harness_memory.backends.mock import MockMemoryBackend

                backend = MockMemoryBackend(**kwargs)
        observer = getattr(backend, "observability", None)
        if observer is None or observability_sink is not None or correlation is not None:
            observer = MemoryObservability(observability_sink, correlation)
            setter = getattr(backend, "set_observability", None)
            if callable(setter):
                setter(observer)
        await backend.initialize()
        if world is not None:
            world_model = world
        elif enable_world_model:
            from simple_harness_memory.world.model import WorldModel

            world_model = WorldModel()
        else:
            world_model = _NullWorldModel()
        logger.info(
            "memory.manager_built",
            backend_type=type(backend).__name__,
            enable_world_model=enable_world_model,
        )
        return cls(
            backend=backend,
            world=world_model,
            observability=observer,
        )

    @classmethod
    async def build_human_memory_v7(
        cls,
        db_path: str | Path,
        *,
        analysis_delivery_authority: object | None = None,
        evidence_authority: object | None = None,
        conversation_evidence_authority: object | None = None,
        classification_policy: InformationClassificationPolicy | None = None,
        memory_action_authority: object | None = None,
        procedure_observation_authority: object | None = None,
        prospective_signal_authority: object | None = None,
        audit_access_authority: AuditAccessAuthorityPort | None = None,
        short_horizon_embedder: Any | None = None,
        world: WorldModelPort | None = None,
        allow_development_embedder: bool = False,
        supported_filter_policies: frozenset[str] | None = None,
    ) -> MemoryManager:
        """Build the fresh-only schema-v7 backend behind the complete public facade.

        ``supported_filter_policies`` 透传 backend；``None`` 保持默认（仅
        ``credential-filter/v1``）。Host 组合传入自己的 sanitizer 策略集合。
        """

        if (
            not allow_development_embedder
            and getattr(short_horizon_embedder, "kind", None) in {"hash", "mock"}
        ):
            # Production composition must never run on deterministic test
            # embeddings; tests opt in explicitly.
            raise MemoryProductionConfigurationError(
                "memory_development_embedder_forbidden"
            )
        from simple_harness_memory.backends.sqlite_v5 import SQLiteHumanMemoryBackend

        backend_kwargs: dict[str, Any] = {}
        if supported_filter_policies is not None:
            backend_kwargs["supported_filter_policies"] = frozenset(supported_filter_policies)
        backend = SQLiteHumanMemoryBackend(
            db_path,
            analysis_delivery_authority=analysis_delivery_authority,
            evidence_authority=evidence_authority,
            conversation_evidence_authority=conversation_evidence_authority,
            classification_policy=classification_policy,
            memory_action_authority=memory_action_authority,
            procedure_observation_authority=procedure_observation_authority,
            prospective_signal_authority=prospective_signal_authority,
            audit_access_authority=audit_access_authority,
            short_horizon_embedder=short_horizon_embedder,
            **backend_kwargs,
        )
        await backend.initialize()
        return cls(backend, world or _NullWorldModel())

    @classmethod
    async def build_human_memory_v6(
        cls,
        db_path: str | Path,
        **kwargs: Any,
    ) -> MemoryManager:
        """Compatibility alias for :meth:`build_human_memory_v7`."""

        return await cls.build_human_memory_v7(db_path, **kwargs)

    @classmethod
    async def build_development(
        cls,
        db_path=None,
        *,
        observability_sink=None,
        correlation: CorrelationInput = None,
        **kwargs,
    ):
        """Explicit development builder; deterministic hash embeddings are allowed."""

        return await cls.build(
            db_path,
            observability_sink=observability_sink,
            correlation=correlation,
            **kwargs,
        )

    @classmethod
    async def build_production(
        cls,
        db_path,
        *,
        embedder=None,
        resource_path=None,
        observability_sink=None,
        correlation: CorrelationInput = None,
        **kwargs,
    ):
        """Build with an explicit production embedder and pre-resolved local resources."""

        if embedder is None or isinstance(embedder, str):
            raise MemoryProductionConfigurationError()
        if getattr(embedder, "kind", None) in {"hash", "mock"}:
            raise MemoryProductionConfigurationError()
        if resource_path is None:
            raise MemoryProductionConfigurationError("memory_embedding_resource_unavailable")
        pinned_resource = Path(resource_path)
        if not pinned_resource.is_absolute() or not pinned_resource.exists():
            raise MemoryProductionConfigurationError("memory_embedding_resource_unavailable")
        manager = await cls.build(
            db_path,
            embedder=embedder,
            observability_sink=observability_sink,
            correlation=correlation,
            **kwargs,
        )
        try:
            await manager.ensure_embeddings()
        except Exception:
            logger.warning(
                "memory.embedding_catchup_degraded",
                stable_code="memory_embedding_catchup_degraded",
            )
        return manager

    @staticmethod
    def _harness() -> Any:
        try:
            import simple_harness
        except ImportError as exc:
            raise HarnessIntegrationExtraRequired() from exc
        return simple_harness

    @staticmethod
    def _principal(identity: object) -> MemoryPrincipal:
        return MemoryPrincipal(
            str(getattr(identity, "deployment_id")),
            str(getattr(identity, "household_id")),
            str(getattr(identity, "actor_id")),
            str(getattr(identity, "session_id")),
        )

    @staticmethod
    def _scope(scope: object) -> MemoryScope:
        return MemoryScope(
            ScopeKind(str(getattr(getattr(scope, "kind"), "value", getattr(scope, "kind")))),
            str(getattr(scope, "owner_id")),
        )

    async def recall_for_turn(self, request: MemoryRecallRequest) -> MemoryRecallResult:
        """Implement the canonical AgentMemoryPort without a consumer adapter."""

        harness = self._harness()
        principal = self._principal(request.identity)
        scopes = tuple(self._scope(scope) for scope in request.scopes)
        started = time.monotonic()
        self._observability.emit(
            "memory.recall.accepted",
            operation="recall",
            outcome="accepted",
            entity_id=request.query_id,
            session_id=principal.session_id,
            attributes={"stage": "accepted"},
        )
        self._observability.emit(
            "memory.recall.started",
            operation="recall",
            outcome="started",
            entity_id=request.query_id,
            session_id=principal.session_id,
            attributes={"stage": "started"},
        )
        try:
            recall = getattr(self._backend, "agent_recall")
            async with asyncio.timeout(request.bounds.deadline_seconds):
                payload, fence, replayed = await recall(
                    principal=principal,
                    scopes=scopes,
                    query_id=request.query_id,
                    query_hash=request.query_hash,
                    query_text=request.query_text,
                    max_items=request.bounds.max_items,
                    max_bytes=request.bounds.max_bytes,
                )
        except MemoryIdempotencyConflict as exc:
            self._emit_failure(
                "recall", request.query_id, principal.session_id, "memory_conflict", started
            )
            raise harness.AgentMemoryError(harness.AgentMemoryErrorCode.CONFLICT) from exc
        except MemoryOwnershipConflict as exc:
            self._emit_failure(
                "recall", request.query_id, principal.session_id, "memory_permanent", started
            )
            raise harness.AgentMemoryError(harness.AgentMemoryErrorCode.PERMANENT) from exc
        except TimeoutError as exc:
            fence = getattr(self._backend, "agent_failure_fence", lambda: None)()
            self._emit_failure(
                "recall", request.query_id, principal.session_id, "memory_timeout", started
            )
            raise harness.AgentMemoryError(
                harness.AgentMemoryErrorCode.TIMEOUT, write_fence=fence
            ) from exc
        except AttributeError as exc:
            self._emit_failure(
                "recall", request.query_id, principal.session_id, "memory_permanent", started
            )
            raise harness.AgentMemoryError(harness.AgentMemoryErrorCode.PERMANENT) from exc
        except Exception as exc:
            fence = getattr(self._backend, "agent_failure_fence", lambda: None)()
            self._emit_failure(
                "recall", request.query_id, principal.session_id, "memory_transient", started
            )
            raise harness.AgentMemoryError(
                harness.AgentMemoryErrorCode.TRANSIENT, write_fence=fence
            ) from exc
        items = payload.get("items", [])
        assert isinstance(items, list)
        status = (
            harness.MemoryRecallStatus.TRUNCATED
            if payload.get("truncated")
            else (harness.MemoryRecallStatus.READY if items else harness.MemoryRecallStatus.EMPTY)
        )
        byte_count = len(
            json.dumps(
                payload,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        result = harness.MemoryRecallResult(
            request.query_id,
            request.query_hash,
            f"memory-recall/v1/{request.query_id}",
            payload,
            status,
            len(items),
            byte_count,
            fence,
        )
        if replayed:
            self._observability.emit(
                "memory.recall.replayed",
                operation="recall",
                outcome="succeeded",
                entity_id=request.query_id,
                session_id=principal.session_id,
                attributes={"stage": "replay", "replayed": True},
            )
        if status.value in {"empty", "truncated"}:
            self._observability.emit(
                "memory.recall.degraded",
                operation="recall",
                outcome="degraded",
                entity_id=request.query_id,
                session_id=principal.session_id,
                attributes={
                    "stage": "selection",
                    "recall_status": status.value,
                    "selected_count": len(items),
                },
                severity="warning",
            )
        self._observability.emit(
            "memory.recall.succeeded",
            operation="recall",
            outcome="succeeded",
            entity_id=request.query_id,
            session_id=principal.session_id,
            attributes={
                "stage": "completed",
                "recall_status": status.value,
                "selected_count": len(items),
                "duration_ms": max(0.0, (time.monotonic() - started) * 1000.0),
            },
        )
        logger.info(
            "memory.agent_recall",
            principal_id=principal.opaque_id,
            item_count=len(items),
            byte_count=byte_count,
            stable_code=status.value,
        )
        return result

    async def release_recall(self, request: MemoryReleaseRequest) -> None:
        harness = self._harness()
        started = time.monotonic()
        try:
            release = getattr(self._backend, "agent_release")
            await release(
                query_id=request.query_id,
                query_hash=request.query_hash,
                result_hash=request.result_hash,
            )
            self._observability.emit(
                "memory.recall.released",
                operation="recall_release",
                outcome="succeeded",
                entity_id=request.query_id,
                attributes={"stage": "released"},
            )
        except MemoryIdempotencyConflict as exc:
            self._emit_failure("recall_release", request.query_id, None, "memory_conflict", started)
            raise harness.AgentMemoryError(harness.AgentMemoryErrorCode.CONFLICT) from exc
        except Exception as exc:
            self._emit_failure(
                "recall_release", request.query_id, None, "memory_transient", started
            )
            raise harness.AgentMemoryError(harness.AgentMemoryErrorCode.TRANSIENT) from exc

    async def record_committed_turn(self, request: CommittedTurn) -> CommittedTurnReceipt:
        harness = self._harness()
        principal = self._principal(request.identity)
        scope = self._scope(request.write_scope)
        started = time.monotonic()
        try:
            record = getattr(self._backend, "agent_record_turn")
            status_value, receipt_id = await record(
                principal=principal,
                scope=scope,
                turn_id=request.turn_id,
                payload_hash=request.payload_hash,
                user_text=request.user_text,
                assistant_text=request.assistant_text,
                write_fence=request.write_fence,
                turn_started_at=request.turn_started_at,
            )
        except MemoryIdempotencyConflict as exc:
            self._emit_failure(
                "committed_turn",
                request.turn_id,
                principal.session_id,
                "memory_conflict",
                started,
            )
            raise harness.AgentMemoryError(harness.AgentMemoryErrorCode.CONFLICT) from exc
        except MemoryOwnershipConflict as exc:
            self._emit_failure(
                "committed_turn",
                request.turn_id,
                principal.session_id,
                "memory_permanent",
                started,
            )
            raise harness.AgentMemoryError(harness.AgentMemoryErrorCode.PERMANENT) from exc
        except TimeoutError as exc:
            self._emit_failure(
                "committed_turn",
                request.turn_id,
                principal.session_id,
                "memory_timeout",
                started,
            )
            raise harness.AgentMemoryError(harness.AgentMemoryErrorCode.TIMEOUT) from exc
        except Exception as exc:
            self._emit_failure(
                "committed_turn",
                request.turn_id,
                principal.session_id,
                "memory_transient",
                started,
            )
            raise harness.AgentMemoryError(harness.AgentMemoryErrorCode.TRANSIENT) from exc
        if status_value in {"applied", "already_applied"}:
            try:
                await self.ensure_embeddings()
            except Exception:
                logger.warning(
                    "memory.embedding_incremental_degraded",
                    stable_code="memory_embedding_incremental_degraded",
                )
        status = harness.CommittedTurnStatus(status_value)
        event_name = {
            "already_applied": "memory.committed_turn.replayed",
            "rejected_erased": "memory.committed_turn.rejected",
        }.get(status_value, "memory.committed_turn.applied")
        self._observability.emit(
            event_name,
            operation="committed_turn",
            outcome="dropped" if status_value == "rejected_erased" else "succeeded",
            entity_id=request.turn_id,
            session_id=principal.session_id,
            attributes={
                "stage": status_value,
                "replayed": status_value == "already_applied",
                "duration_ms": max(0.0, (time.monotonic() - started) * 1000.0),
                "error_code": (
                    "memory_rejected_erased" if status_value == "rejected_erased" else None
                ),
            },
            severity="warning" if status_value == "rejected_erased" else "info",
        )
        logger.info(
            "memory.committed_turn",
            principal_id=principal.opaque_id,
            turn_id=request.turn_id,
            stable_code=status.value,
        )
        return harness.CommittedTurnReceipt(
            request.turn_id, request.payload_hash, status, receipt_id
        )

    def _emit_failure(
        self,
        operation: str,
        entity_id: str,
        session_id: str | None,
        error_code: str,
        started: float,
    ) -> None:
        self._observability.emit(
            f"memory.{operation}.failed",
            operation=operation,
            outcome="failed",
            entity_id=entity_id,
            session_id=session_id,
            attributes={
                "stage": "failed",
                "error_code": error_code,
                "duration_ms": max(0.0, (time.monotonic() - started) * 1000.0),
            },
            severity="error",
        )

    async def diagnostics_snapshot(self) -> dict[str, object]:
        """Return bounded aggregate health without reading business payload columns."""

        if self._closed:
            return {
                "schema_version": 1,
                "sdk_version": "0.6.0",
                "component": "memory",
                "lifecycle": "closed",
                "health": "closed",
                "storage": await self._backend.diagnostics_snapshot(),
                "observability": dict(self._observability.snapshot()),
            }
        try:
            storage = await asyncio.wait_for(self._backend.diagnostics_snapshot(), timeout=0.25)
        except BaseException:
            storage = {"health": "degraded", "error_code": "memory_snapshot_unavailable"}
        observer = dict(self._observability.snapshot())
        health = (
            "degraded"
            if storage.get("health") == "degraded" or observer.get("health") == "degraded"
            else "healthy"
        )
        return {
            "schema_version": 1,
            "sdk_version": "0.6.0",
            "component": "memory",
            "lifecycle": "open",
            "health": health,
            "storage": storage,
            "observability": observer,
        }

    async def export_principal(
        self,
        principal: MemoryPrincipal,
        *,
        scopes: tuple[MemoryScope, ...] | None = None,
        cursor: int = 0,
        limit: int = 100,
    ) -> ExportPage:
        selected = scopes or (
            MemoryScope.personal(principal.actor_id),
            MemoryScope.family(principal.household_id),
        )
        records, next_cursor = await getattr(self._backend, "agent_export")(
            principal, selected, cursor=cursor, limit=limit
        )
        return ExportPage(
            "simple-harness-memory/export/v1",
            tuple(records),
            None if next_cursor is None else str(next_cursor),
        )

    async def delete_principal(self, principal: MemoryPrincipal) -> PrivacyReceipt:
        return await self.delete_scope(
            principal,
            (
                MemoryScope.personal(principal.actor_id),
                MemoryScope.family(principal.household_id),
            ),
        )

    async def delete_scope(
        self, principal: MemoryPrincipal, scopes: tuple[MemoryScope, ...]
    ) -> PrivacyReceipt:
        counts = await getattr(self._backend, "agent_delete_scopes")(principal, scopes)
        logger.info(
            "memory.privacy_delete",
            principal_id=principal.opaque_id,
            message_count=int(counts["messages"]),
            fact_count=int(counts["facts"]),
            stable_code="deleted",
        )
        return PrivacyReceipt(
            str(counts["receipt_id"]),
            int(counts["messages"]),
            int(counts["facts"]),
            int(counts["snapshots"]),
            int(counts["jobs"]),
        )

    async def share_fact(self, principal: MemoryPrincipal, fact_id: int) -> str:
        return await getattr(self._backend, "agent_share_fact")(principal, fact_id)

    async def remember_fact(
        self,
        principal: MemoryPrincipal,
        content: str,
        *,
        source_event_id: str,
        payload_hash: str | None = None,
        salience: float = 0.5,
        pinned: bool = False,
        tier: str = "auto",
    ) -> int:
        """Idempotently persist an explicit personal fact and return its exact fact ID."""

        return await getattr(self._backend, "agent_remember_fact")(
            principal,
            content,
            source_event_id=source_event_id,
            payload_hash=payload_hash,
            salience=salience,
            pinned=pinned,
            tier=tier,
        )

    async def read_fact(self, principal: MemoryPrincipal, fact_id: int) -> Fact | None:
        """Read an active personal fact only when it belongs to the trusted principal."""

        return await getattr(self._backend, "agent_read_fact")(principal, fact_id)

    async def list_facts(
        self,
        principal: MemoryPrincipal,
        *,
        subject: str | None = None,
        category: str | None = None,
        limit: int = 200,
    ) -> list[Fact]:
        """List active personal facts owned by a trusted principal.

        This is the identity-safe read surface for consumer fact-management UIs.
        It deliberately excludes household projections; consumers must use an
        explicitly authorized sharing/read flow for broader scopes.
        """

        return await getattr(self._backend, "agent_list_facts")(
            principal,
            subject=subject,
            category=category,
            limit=limit,
        )

    async def append_message(
        self,
        session_id,
        role,
        content,
        *,
        user_id,
        source_event_id,
        payload_hash=None,
        salience=0.0,
        decay_rate=0.02,
    ):
        return await self._backend.append_message(
            session_id,
            role,
            content,
            user_id=user_id,
            source_event_id=source_event_id,
            payload_hash=payload_hash,
            salience=salience,
            decay_rate=decay_rate,
        )

    async def get_recent_messages(self, session_id, limit=20, *, user_id):
        return await self._backend.get_recent_messages(session_id, limit, user_id=user_id)

    async def get_message(self, message_id, *, user_id):
        return await self._backend.get_message(message_id, user_id=user_id)

    async def get_facts(
        self,
        subject="user",
        category=None,
        active_only=True,
        *,
        user_id,
        limit=None,
    ):
        return await self._backend.get_facts(
            subject,
            category,
            active_only,
            user_id=user_id,
            limit=limit,
        )

    async def forget_fact(
        self,
        fact_id,
        reason="",
        *,
        user_id=None,
        principal: MemoryPrincipal | None = None,
        source_event_id: str | None = None,
        payload_hash: str | None = None,
    ):
        if principal is not None:
            if source_event_id is not None and reason and source_event_id != reason:
                raise MemoryIdempotencyConflict()
            action_id = source_event_id or reason or f"forget-fact/v1/{fact_id}"
            return await getattr(self._backend, "agent_forget_fact")(
                principal,
                fact_id,
                source_event_id=action_id,
                payload_hash=payload_hash,
            )
        if user_id is None:
            raise TypeError("user_id or principal is required")
        return await self._backend.forget_fact(fact_id, reason, user_id=user_id)

    async def recall(self, query, session_id=None, limit=10, *, user_id):
        return await self._backend.recall(query, session_id, limit, user_id=user_id)

    async def recall_bounded(
        self,
        query,
        *,
        user_id,
        session_id,
        context_query_id,
        query_hash=None,
        max_results=None,
        max_bytes=None,
        timeout_seconds=None,
    ):
        return await self._backend.recall_bounded(
            query,
            user_id=user_id,
            session_id=session_id,
            context_query_id=context_query_id,
            query_hash=query_hash,
            max_results=max_results,
            max_bytes=max_bytes,
            timeout_seconds=timeout_seconds,
        )

    async def release_recall_result(
        self,
        *,
        user_id,
        context_query_id,
        result_hash,
    ):
        return await self._backend.release_recall_result(
            user_id=user_id,
            context_query_id=context_query_id,
            result_hash=result_hash,
        )

    async def cleanup_recall_results(
        self,
        *,
        user_id,
        now=None,
        limit=None,
    ):
        cleaned = await self._backend.cleanup_recall_results(
            user_id=user_id,
            now=now,
            limit=limit,
        )
        self._observability.emit(
            "memory.recall.cleanup",
            operation="recall_cleanup",
            outcome="succeeded",
            entity_id=user_id,
            attributes={"stage": "cleanup", "selected_count": cleaned},
        )
        return cleaned

    async def recall_and_reinforce(self, query, session_id=None, limit=10, *, user_id):
        return await self._backend.recall_and_reinforce(query, session_id, limit, user_id=user_id)

    async def vector_search(self, query, limit=20, *, user_id):
        return await self._backend.vector_search(query, limit, user_id=user_id)

    async def get_digital_twin(self, subject="user", *, user_id):
        return await self._backend.get_digital_twin(subject, user_id=user_id)

    async def update_digital_twin(self, twin, *, user_id):
        await self._backend.update_digital_twin(twin, user_id=user_id)

    async def suggest_questions(self, subject="user", *, user_id):
        return await self._backend.suggest_questions(subject, user_id=user_id)

    async def detect_inconsistencies(self, subject="user", *, user_id):
        return await self._backend.detect_inconsistencies(subject, user_id=user_id)

    async def daily_decay(self, *, user_id, limit=None):
        return await self._backend.daily_decay(user_id=user_id, limit=limit)

    async def summarize_old_sessions(self, older_than_days=7, max_sessions=5, *, user_id):
        return await self._backend.summarize_old_sessions(
            older_than_days, max_sessions, user_id=user_id
        )

    async def record_workspace_action(self, session_id, action_type, payload, *, user_id):
        await self._backend.record_workspace_action(
            session_id, action_type, payload, user_id=user_id
        )

    async def reindex(self, embedder=None, *, user_id, limit=None):
        return await self._backend.reindex(embedder, user_id=user_id, limit=limit)

    async def reindex_generation(self, embedder=None, *, page_size=None):
        operation = getattr(self._backend, "reindex_generation", None)
        if operation is None:
            raise RuntimeError("backend does not support embedding generations")
        return await operation(embedder, page_size=page_size)

    async def ensure_embeddings(self, *, page_size=None):
        """Create or catch up the active vector generation when the backend supports it."""

        operation = getattr(self._backend, "ensure_embedding_generation", None)
        if operation is None:
            return None
        return await operation(page_size=page_size)

    async def checkpoint(self, *, deadline_seconds=5.0):
        operation = getattr(self._backend, "checkpoint", None)
        if operation is None:
            raise RuntimeError("backend does not support checkpoints")
        return await operation(deadline_seconds=deadline_seconds)

    async def backup(self, destination):
        operation = getattr(self._backend, "backup", None)
        if operation is None:
            raise RuntimeError("backend does not support backups")
        return await operation(destination)

    async def restore_backup(self, backup):
        """Restore this manager's SQLite path after it has been explicitly closed."""

        if not self._closed:
            raise RuntimeError("memory_restore_requires_closed_manager")
        from simple_harness_memory.backends.sqlite import SQLiteMemoryBackend

        if not isinstance(self._backend, SQLiteMemoryBackend):
            raise RuntimeError("backend does not support restore")
        return await asyncio.to_thread(
            SQLiteMemoryBackend.restore_backup_sync, backup, self._backend._db_path
        )

    async def record_procedure_observation(self, *, principal, scope, reference):
        operation = getattr(self._backend, "record_procedure_observation", None)
        if operation is None:
            raise RuntimeError("backend does not support Procedure observations")
        return await operation(principal=principal, scope=scope, reference=reference)

    async def apply_prospective_signal(self, *, principal, scope, reference):
        operation = getattr(self._backend, "apply_prospective_signal", None)
        if operation is None:
            raise RuntimeError("backend does not support Prospective signals")
        return await operation(principal=principal, scope=scope, reference=reference)

    async def close(self):
        await self._backend.close()
        self._closed = True
        self._observability.close()
        logger.info("memory.manager_closed", backend_type=type(self._backend).__name__)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()


async def build_human_memory_v7(
    db_path: str | Path, **kwargs: Any
) -> MemoryManager:
    """Public production-consistent constructor for the fresh schema-v7 backend."""

    return await MemoryManager.build_human_memory_v7(db_path, **kwargs)


async def build_human_memory_v6(
    db_path: str | Path, **kwargs: Any
) -> MemoryManager:
    """Compatibility alias for :func:`build_human_memory_v7`."""

    return await build_human_memory_v7(db_path, **kwargs)
