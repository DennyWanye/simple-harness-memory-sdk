"""DISPOSABLE spike A3: PROJECT_EFFECT tool gating through the real SDK 0.7.1
ReActLoop + the Host's real ProductRunContextAuthority / ProductRuntimeDecisionSink /
ProductTaskExecutionAuthority / ContextRouteToolService.

Harness copied (not imported) from
backend/tests/sdk_adapters/test_s5a_milestone_route_loop.py, extended with a
`write_file` tool classified PROJECT_EFFECT / route REQUIRED / task-scope REQUIRED.
"""

from __future__ import annotations

import contextvars
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from simple_harness import (
    WorkspaceBindingAuthorizationChannel,
    WorkspaceBindingAuthorizationDecision,
    WorkspaceBindingProposal,
)
from simple_harness.contracts import CallId, RequestId, RunId, freeze_json, thaw_json
from simple_harness.contracts.messages import Message, MessageRole
from simple_harness.execution.budget import BudgetSnapshot
from simple_harness.execution.effects import TaskExecutionEnvelope
from simple_harness.execution.fences import RunFenceLease
from simple_harness.execution.uow import ExecutionLease, WorkflowCheckpoint
from simple_harness.providers import (
    CancelToken,
    ProviderResponse,
    ProviderToolCall,
    ProviderToolSpec,
)
from simple_harness.runtime.context import ContextSnapshot
from simple_harness.runtime.drivers.react_loop import (
    AgentLoopCollaborator,
    EffectBatchExecutor,
    ReActLoop,
    ReActRunInput,
)
from simple_harness.runtime.kernel import RuntimeServices
from simple_harness.runtime.termination import TerminationLimits
from simple_harness.tools import ToolResult
from simple_harness.tools.executor import EffectExecution
from simple_harness.tools.runtime_catalog import (
    ToolEffectClass,
    ToolExecutionPolicy,
    ToolRouteRequirement,
    ToolTaskScopeRequirement,
)

from deskpet.memory.human_memory_service import (
    AuthenticatedHostSnapshot,
    CreateTaskScopeRequest,
    HumanMemoryHostService,
)
from deskpet.memory.schema import dispatch_startup_epoch
from deskpet.sdk_adapters.context_authority import (
    ContextRouteLedgerStore,
    ProductRunContextAuthority,
    ProductRuntimeDecisionSink,
)
from deskpet.sdk_adapters.context_route import (
    CONTEXT_ROUTE_SCHEMA,
    TASK_SCOPE_SEARCH_SCHEMA,
    ContextRouteToolService,
)
from deskpet.sdk_adapters.task_execution import (
    ProductTaskExecutionAuthority,
    TaskExecutionAuthorityError,
)
from deskpet.task_scope.workspace_bindings import (
    ManualWorkspaceChallengeAuthorityCheck,
    ManualWorkspaceDecisionAuthorityCheck,
    WorkspaceBindingAuthorityStore,
    WorkspaceBindingError,
    canonical_workspace_root,
)

RUN = RunId("run-spike-a3")
LEASE = ExecutionLease(RUN.value, "runtime.kernel", "worker-1", 1, 100.0)
FENCE = RunFenceLease(RUN, 1, "worker-1", 1)

_tool_context_var: contextvars.ContextVar = contextvars.ContextVar(
    "spike_a3_tool_context", default=None
)

WRITE_FILE_SCHEMA = {
    "type": "object",
    "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
    "required": ["path", "content"],
}


# --- harness ports (copied from the Host milestone test) --------------------


class HarnessContext:
    def __init__(self, first_message: str) -> None:
        self.messages = [Message(role=MessageRole.USER, content=first_message)]
        self.revision = 1

    def load(self, run_id: RunId) -> ContextSnapshot:
        del run_id
        return ContextSnapshot(self.revision, tuple(self.messages))

    def append(self, run_id, lease, expected_revision, append_id, entries):
        del run_id, lease, append_id
        assert expected_revision == self.revision
        self.messages.extend(entries)
        self.revision += 1
        return ContextSnapshot(self.revision, tuple(self.messages))


class HarnessCheckpoint:
    def __init__(self) -> None:
        self.value = None

    def read_react_checkpoint(self, run_id):
        del run_id
        return self.value

    def cas_react_checkpoint(
        self, *, run_id, lease, expected_version, checkpoint, checkpoint_hash,
        now, fault=None,
    ):
        del fault, now
        current = None if self.value is None else self.value.version
        assert expected_version == current
        version = 1 if current is None else current + 1
        self.value = WorkflowCheckpoint(
            run_id,
            "react.termination.v1",
            freeze_json(checkpoint),
            checkpoint_hash,
            lease.epoch,
            version,
        )
        return self.value


class ScriptedProvider:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.calls = []

    def read_provider_budget(self, run_id: RunId) -> BudgetSnapshot:
        del run_id
        return BudgetSnapshot()

    async def invoke(self, run_id, request, *, cancel, execution_lease):
        self.calls.append(request)
        template = self.responses.pop(0)
        if isinstance(template, BaseException):
            raise template
        return ProviderResponse(
            request_id=request.request_id,
            message=template.message,
            tool_calls=template.tool_calls,
            model=template.model,
            finish_reason=template.finish_reason,
        )


class RouteExposure:
    """Host tool specs/policies: the two S5a tools + a PROJECT_EFFECT write_file."""

    def restore(self, run_id, checkpoint) -> None:
        del run_id, checkpoint

    def provider_specs(self, run_id) -> tuple[ProviderToolSpec, ...]:
        del run_id
        return (
            ProviderToolSpec("context_route", "Route Context", CONTEXT_ROUTE_SCHEMA),
            ProviderToolSpec(
                "task_scope_search", "Search task scopes", TASK_SCOPE_SEARCH_SCHEMA
            ),
            ProviderToolSpec("write_file", "Write a project file", WRITE_FILE_SCHEMA),
        )

    def execution_policy(self, run_id, provider_name) -> ToolExecutionPolicy:
        del run_id
        if provider_name == "context_route":
            return ToolExecutionPolicy(
                "builtin:context_route",
                "a" * 64,
                ToolEffectClass.CONTEXT_CONTROL,
                ToolRouteRequirement.FORBIDDEN,
                ToolTaskScopeRequirement.FORBIDDEN,
            )
        if provider_name == "write_file":
            # The A3 classification under test.
            return ToolExecutionPolicy(
                "builtin:write_file",
                "d" * 64,
                ToolEffectClass.PROJECT_EFFECT,
                ToolRouteRequirement.REQUIRED,
                ToolTaskScopeRequirement.REQUIRED,
            )
        return ToolExecutionPolicy(
            "builtin:task_scope_search",
            "b" * 64,
            ToolEffectClass.NON_PROJECT_EFFECT,
            ToolRouteRequirement.OPTIONAL,
            ToolTaskScopeRequirement.OPTIONAL,
        )

    def observe_tool_result(self, run_id, tool_name, result) -> None:
        del run_id, tool_name, result

    def checkpoint(self, run_id):
        del run_id
        return {"catalog_fingerprint": "c" * 64}


class RouteToolEffects:
    """Bridge the loop's effect execution onto the real route tool service
    plus a spike-local write_file handler that records what it received."""

    def __init__(self, service: ContextRouteToolService) -> None:
        self.service = service
        self.calls: list[str] = []
        self.write_file_calls: list[dict] = []

    async def execute(self, **values):
        call = values["call"]
        context = values["context"]
        self.calls.append(call.name)
        token = _tool_context_var.set(context)
        try:
            if call.name == "context_route":
                raw = await self.service.handle_context_route(call.arguments)
            elif call.name == "task_scope_search":
                raw = await self.service.handle_task_scope_search(call.arguments)
            elif call.name == "write_file":
                self.write_file_calls.append(
                    {
                        "arguments": dict(call.arguments),
                        "context": context,
                        "envelope": context.task_execution_envelope,
                    }
                )
                raw = {"ok": True, "written": True}
            else:
                raise AssertionError(f"unexpected tool {call.name}")
        finally:
            _tool_context_var.reset(token)
        if isinstance(raw, dict) and (raw.get("ok") is False or raw.get("error")):
            error = raw.get("error") or {}
            result = ToolResult.failed(
                call.call_id,
                str(error.get("code") or "tool_failed"),
                str(error.get("code") or "tool failed"),
            )
        else:
            result = ToolResult.succeeded(call.call_id, raw)
        return EffectExecution(effect=None, result=result)


class _NoopReconciliation:
    async def observe(self, invocation):
        raise AssertionError("provider reconciliation must not run in this lane")


class CountingTaskExecutionAuthority:
    """Wrap the real Host authority to count/record issue_envelope calls."""

    def __init__(self, inner: ProductTaskExecutionAuthority) -> None:
        self.inner = inner
        self.requests: list = []
        self.envelopes: list = []
        self.errors: list = []

    async def issue_envelope(self, request):
        self.requests.append(request)
        try:
            envelope = await self.inner.issue_envelope(request)
        except Exception as exc:  # noqa: BLE001 - record then re-raise
            self.errors.append(exc)
            raise
        self.envelopes.append(envelope)
        return envelope


def _loop() -> ReActLoop:
    return ReActLoop(
        collaborator=AgentLoopCollaborator(
            limits=TerminationLimits(6, 12, 60, 10000, 3)
        ),
        effects=EffectBatchExecutor(),
        clock=lambda: 1.0,
    )


def _answer(content: str) -> ProviderResponse:
    return ProviderResponse(
        request_id=RequestId("fixture"),
        message=Message(role=MessageRole.ASSISTANT, content=content),
        model="model-1",
        finish_reason="stop",
    )


def _tool_call(name: str, arguments: dict, raw_id: str = "raw-1") -> ProviderResponse:
    return ProviderResponse(
        request_id=RequestId("fixture"),
        message=Message(role=MessageRole.ASSISTANT, content="calling"),
        tool_calls=(ProviderToolCall(CallId(raw_id), name, arguments),),
        model="model-1",
        finish_reason="tool_calls",
    )


def _tool_calls(*calls: tuple[str, dict, str]) -> ProviderResponse:
    return ProviderResponse(
        request_id=RequestId("fixture"),
        message=Message(role=MessageRole.ASSISTANT, content="calling"),
        tool_calls=tuple(
            ProviderToolCall(CallId(raw_id), name, args) for name, args, raw_id in calls
        ),
        model="model-1",
        finish_reason="tool_calls",
    )


AUTH = AuthenticatedHostSnapshot(
    subject="deskpet-local-owner-v1",
    principal_id="local-control-channel",
    authority_ref="host:validated-control-channel:v1",
)


class _ManualAuthority:
    def __init__(self) -> None:
        self.evidence: dict = {}
        self.interactions: dict = {}

    def trust_challenge(self, check) -> None:
        self.evidence[check.authorization_evidence_id] = check

    def trust_decision(self, check) -> None:
        self.interactions[check.challenge.interaction_event_id] = check

    async def verify_manual_challenge(self, check) -> None:
        if self.evidence.get(check.authorization_evidence_id) != check:
            raise WorkspaceBindingError(
                "workspace_binding_manual_evidence_not_durable"
            )

    async def verify_manual_decision(self, check) -> None:
        if self.interactions.get(check.challenge.interaction_event_id) != check:
            raise WorkspaceBindingError(
                "workspace_binding_manual_interaction_not_durable"
            )


async def _bind_scope_root(db_path: Path, scope_id: str, root: Path) -> None:
    authority = _ManualAuthority()
    store = WorkspaceBindingAuthorityStore(
        db_path,
        configured_workspace_root=root.parent,
        clock_millis=lambda: 1500,
        manual_authorization_authority=authority,
    )
    proposal = WorkspaceBindingProposal(
        f"proposal-{scope_id}",
        RUN.value,
        AUTH.subject,
        scope_id,
        canonical_workspace_root(root, root_id=f"root-{scope_id}"),
        0,
        f"append-{scope_id}",
    )
    check = ManualWorkspaceChallengeAuthorityCheck(
        proposal,
        f"nonce-{scope_id}",
        WorkspaceBindingAuthorizationChannel.USER_CONFIRMATION,
        f"evidence-{scope_id}",
        "a" * 64,
        f"interaction-{scope_id}",
        1000,
        1100,
        2000,
    )
    authority.trust_challenge(check)
    challenge = await store.issue_manual_challenge(
        proposal,
        authorization_nonce=check.authorization_nonce,
        authorization_channel=check.authorization_channel,
        authorization_evidence_id=check.authorization_evidence_id,
        authorization_evidence_hash=check.authorization_evidence_hash,
        interaction_event_id=check.interaction_event_id,
        issued_at_millis=check.issued_at_millis,
        not_before_millis=check.not_before_millis,
        expires_at_millis=check.expires_at_millis,
    )
    decision_check = ManualWorkspaceDecisionAuthorityCheck(
        challenge,
        AUTH.subject,
        WorkspaceBindingAuthorizationDecision.ALLOW,
        1200,
    )
    authority.trust_decision(decision_check)
    decision = await store.record_manual_decision(
        challenge,
        decided_by_actor_id=decision_check.decided_by_actor_id,
        decision=decision_check.decision,
        decided_at_millis=decision_check.decided_at_millis,
    )
    grant = await store.verify_manual_authorization(proposal, challenge, decision)
    await store.append_binding(proposal, grant)


@pytest_asyncio.fixture()
async def milestone(tmp_path: Path):
    db_path = tmp_path / "state.db"
    startup = await dispatch_startup_epoch(db_path, approved_fresh_lane=True)
    service = HumanMemoryHostService(db_path, auth=AUTH, startup=startup)
    factory = SimpleNamespace(bind=lambda auth, **kw: service)

    context = HarnessContext("继续以前的 A")
    checkpoint = HarnessCheckpoint()
    ledger = ContextRouteLedgerStore(db_path)
    exposure = RouteExposure()
    ports = SimpleNamespace(
        context=context,
        react_checkpoint=SimpleNamespace(
            read_start_snapshot=lambda run_id: {
                "input": {
                    "context_metadata": {"budget": {"context_window": 32768}}
                }
            }
        ),
    )
    route_service = ContextRouteToolService(
        service_factory_getter=lambda: factory,
        binding_store_factory=lambda: WorkspaceBindingAuthorityStore(db_path),
        binding_append_getter=lambda: None,
        ledger=ledger,
        tool_context_getter=lambda: _tool_context_var.get(),
    )
    effects = RouteToolEffects(route_service)
    authority = ProductRunContextAuthority(
        ports_resolver=lambda: ports,
        exposure_resolver=lambda run_id: exposure,
        ledger=ledger,
    )
    sink = ProductRuntimeDecisionSink(ledger=ledger)
    return SimpleNamespace(
        db_path=db_path,
        ledger=ledger,
        service=service,
        context=context,
        checkpoint=checkpoint,
        effects=effects,
        exposure=exposure,
        authority=authority,
        sink=sink,
    )


def _real_root_resolver(db_path: Path):
    """Host-realistic resolver: exact single root from the S4 binding head."""

    async def resolve(receipt):
        store = WorkspaceBindingAuthorityStore(db_path)
        head = await store.current_receipt(receipt.task_scope_id)
        assert head.binding_set_revision == receipt.binding_set_revision
        assert head.receipt_id == receipt.binding_set_receipt_id
        assert head.receipt_hash == receipt.binding_set_receipt_hash
        assert len(head.root_identity_hashes) == 1
        return head.appended_root.root_id, head.root_identity_hashes[0]

    return resolve


def _services(milestone, provider, task_authority) -> RuntimeServices:
    noop = object()
    return RuntimeServices(
        provider=provider,
        tools=milestone.effects,
        authorization=noop,
        context=milestone.context,
        delivery=noop,
        tool_reconciliation=noop,
        reconciliation=noop,
        provider_reconciliation=_NoopReconciliation(),
        react_checkpoint=milestone.checkpoint,
        run_context_authority=milestone.authority,
        runtime_decision_sink=milestone.sink,
        task_execution_authority=task_authority,
    )


async def _run(milestone, provider, task_authority) -> object:
    return await _loop().run(
        ReActRunInput(RUN, RequestId("request-1"), tool_exposure=milestone.exposure),
        services=_services(milestone, provider, task_authority),
        execution_lease=LEASE,
        run_fence=FENCE,
        cancel=CancelToken(),
        initial_messages=(),
    )


def _rows(db_path: Path, sql: str, *params):
    with sqlite3.connect(db_path) as db:
        return db.execute(sql, params).fetchall()


def _tool_messages(milestone, name: str) -> list[str]:
    return [
        str(m.content)
        for m in milestone.context.messages
        if m.role is MessageRole.TOOL and m.name == name
    ]


async def _make_bound_scope(milestone, tmp_path: Path) -> str:
    created = await milestone.service.create_task_scope(
        CreateTaskScopeRequest(
            "task-a", "任务 A", "写完 A 的季度报告，下一步补图表", "create-a"
        )
    )
    scope_id = str(created["scope_ref"])
    await milestone.service.rebuild_derived(scope_id)
    workspace = tmp_path / "workspace" / "root-a"
    workspace.mkdir(parents=True)
    await _bind_scope_root(milestone.db_path, scope_id, workspace)
    return scope_id


# ---------------------------------------------------------------------------
# (a) routed_standalone: PROJECT_EFFECT write_file must not reach the handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_write_file_in_routed_standalone(milestone) -> None:
    task_authority = CountingTaskExecutionAuthority(
        ProductTaskExecutionAuthority(root_resolver=_real_root_resolver(milestone.db_path))
    )
    provider = ScriptedProvider(
        [
            _tool_call("context_route", {"route": "direct_standalone"}, raw_id="raw-route"),
            _tool_call("write_file", {"path": "a.txt", "content": "x"}, raw_id="raw-write"),
            _answer("done"),
        ]
    )
    outcome = {"exception": None, "result": None}
    try:
        outcome["result"] = await _run(milestone, provider, task_authority)
    except Exception as exc:  # noqa: BLE001 - spike: record the actual behaviour
        outcome["exception"] = exc

    print("\n[A] exception:", repr(outcome["exception"]))
    print("[A] handler calls:", milestone.effects.calls)
    print("[A] write_file handler invocations:", len(milestone.effects.write_file_calls))
    print("[A] issue_envelope requests:", len(task_authority.requests),
          "errors:", [str(e) for e in task_authority.errors])
    print("[A] write_file tool messages:", _tool_messages(milestone, "write_file"))
    checkpoint = dict(thaw_json(milestone.checkpoint.value.checkpoint))
    print("[A] checkpoint route_state:", checkpoint.get("route_state"),
          "phase:", checkpoint.get("phase"))

    # Hard invariant of A3(a): the Host tool handler is never invoked.
    assert milestone.effects.write_file_calls == []
    assert "write_file" not in milestone.effects.calls
    # Observed shape (see RESULT.md): the SDK does NOT emit a model-visible
    # ROUTE_BARRIER_NOT_OBSERVED rejection in routed_standalone; instead the
    # Host authority fails closed with an exception that escapes the loop.
    assert outcome["exception"] is not None, "expected fail-closed exception"
    assert isinstance(outcome["exception"], TaskExecutionAuthorityError)
    assert "sdk_task_execution_route_authority_missing" in str(outcome["exception"])
    assert [r.tool_name for r in task_authority.requests] == ["context_route", "write_file"]
    assert [str(e) for e in task_authority.errors] == ["sdk_task_execution_route_authority_missing"]
    assert _tool_messages(milestone, "write_file") == []


@pytest.mark.asyncio
async def test_a2_write_file_unrouted_is_model_visible_rejection(milestone) -> None:
    """Variant: write_file on the very first turn (UNROUTED) -> preflight rejection."""

    task_authority = CountingTaskExecutionAuthority(
        ProductTaskExecutionAuthority(root_resolver=_real_root_resolver(milestone.db_path))
    )
    provider = ScriptedProvider(
        [
            _tool_call("write_file", {"path": "a.txt", "content": "x"}, raw_id="raw-write"),
            _answer("done"),
        ]
    )
    result = await _run(milestone, provider, task_authority)
    messages = _tool_messages(milestone, "write_file")
    print("\n[A2] write_file tool messages:", messages)
    print("[A2] handler calls:", milestone.effects.calls,
          "issue_envelope requests:", len(task_authority.requests))
    assert milestone.effects.write_file_calls == []
    assert task_authority.requests == []
    assert len(messages) == 1 and "ROUTE_BARRIER_NOT_OBSERVED" in messages[0]
    assert result.termination.route_state == "routed_standalone"


@pytest.mark.asyncio
async def test_a3_same_batch_route_and_write_is_rejected(milestone) -> None:
    task_authority = CountingTaskExecutionAuthority(
        ProductTaskExecutionAuthority(root_resolver=_real_root_resolver(milestone.db_path))
    )
    provider = ScriptedProvider(
        [
            _tool_calls(
                ("context_route", {"route": "direct_standalone"}, "raw-route"),
                ("write_file", {"path": "a.txt", "content": "x"}, "raw-write"),
            ),
            _answer("done"),
        ]
    )
    result = await _run(milestone, provider, task_authority)
    messages = _tool_messages(milestone, "write_file")
    print("\n[A3-same-batch] write_file tool messages:", messages)
    assert milestone.effects.calls == ["context_route"]
    assert [r.tool_name for r in task_authority.requests] == ["context_route"]
    assert len(messages) == 1 and "ROUTE_BARRIER_NOT_OBSERVED" in messages[0]
    assert result.termination.route_state == "routed_standalone"


# ---------------------------------------------------------------------------
# (b) routed_task + root_resolver: envelope reaches the handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b_write_file_in_routed_task_receives_envelope(milestone, tmp_path) -> None:
    scope_id = await _make_bound_scope(milestone, tmp_path)
    task_authority = CountingTaskExecutionAuthority(
        ProductTaskExecutionAuthority(root_resolver=_real_root_resolver(milestone.db_path))
    )
    provider = ScriptedProvider(
        [
            _tool_call(
                "context_route",
                {"route": "resume_existing", "task_scope_id": scope_id},
                raw_id="raw-route",
            ),
            _tool_call("write_file", {"path": "a.txt", "content": "x"}, raw_id="raw-write"),
            _tool_call("write_file", {"path": "b.txt", "content": "y"}, raw_id="raw-write-2"),
            _answer("done"),
        ]
    )
    result = await _run(milestone, provider, task_authority)

    assert result.termination.route_state == "routed_task"
    assert milestone.effects.calls == ["context_route", "write_file", "write_file"]
    head = await WorkspaceBindingAuthorityStore(milestone.db_path).current_receipt(scope_id)

    # issue_envelope is called once per tool call that has a policy (incl.
    # context_route itself, which is CONTEXT_CONTROL -> no task fields).
    tool_names = [r.tool_name for r in task_authority.requests]
    print("\n[B] issue_envelope tool_names:", tool_names)
    assert tool_names == ["context_route", "write_file", "write_file"]

    assert len(milestone.effects.write_file_calls) == 2
    for record in milestone.effects.write_file_calls:
        envelope = record["envelope"]
        context = record["context"]
        assert isinstance(envelope, TaskExecutionEnvelope)
        assert context.task_execution_envelope is envelope
        assert context.call_id == envelope.call_id
        assert context.effect_id == envelope.effect_id
        print("[B] envelope:", envelope.to_json())
        assert envelope.tool_name == "write_file"
        assert envelope.capability_id == "builtin:write_file"
        assert envelope.capability_fingerprint == "d" * 64
        # six TaskScope fields
        assert envelope.task_scope_id == scope_id
        assert envelope.root_id == head.appended_root.root_id == f"root-{scope_id}"
        assert envelope.root_identity_hash == head.root_identity_hashes[0]
        assert envelope.binding_set_revision == head.binding_set_revision
        assert envelope.binding_set_receipt_id == head.receipt_id
        assert envelope.binding_set_receipt_hash == head.receipt_hash
        assert envelope.idempotency_key == envelope.effect_id.value
        # route receipt lineage
        checkpoint = dict(thaw_json(milestone.checkpoint.value.checkpoint))
        route_receipt = dict(checkpoint["route_receipt"])
        assert envelope.route_receipt_id == route_receipt["receipt_id"]
        assert envelope.route_receipt_hash == checkpoint["route_receipt_hash"]

    # Bonus: the Host S4 store accepts this exact envelope against the frozen
    # route receipt (the check a real ProductEffectExecutor/handler would run).
    from simple_harness.execution.context_authority import ContextRouteReceipt

    frozen_receipt = ContextRouteReceipt.from_json(
        dict(thaw_json(milestone.checkpoint.value.checkpoint))["route_receipt"]
    )
    authority = await WorkspaceBindingAuthorityStore(
        milestone.db_path
    ).verify_task_execution_envelope(
        milestone.effects.write_file_calls[0]["envelope"], frozen_receipt
    )
    print("[B] verify_task_execution_envelope ->", authority.root.root_id,
          authority.binding_set_revision)
    assert authority.task_scope_id == scope_id


# ---------------------------------------------------------------------------
# (c) model-supplied authority fields are forbidden
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "forbidden_key",
    ["task_execution_envelope", "binding_set_revision"],
)
async def test_c_model_authority_field_forbidden(milestone, tmp_path, forbidden_key) -> None:
    scope_id = await _make_bound_scope(milestone, tmp_path)
    task_authority = CountingTaskExecutionAuthority(
        ProductTaskExecutionAuthority(root_resolver=_real_root_resolver(milestone.db_path))
    )
    provider = ScriptedProvider(
        [
            _tool_call(
                "context_route",
                {"route": "resume_existing", "task_scope_id": scope_id},
                raw_id="raw-route",
            ),
            _tool_call(
                "write_file",
                {"path": "a.txt", "content": "x", forbidden_key: "forged"},
                raw_id="raw-write",
            ),
            _answer("done"),
        ]
    )
    result = await _run(milestone, provider, task_authority)
    messages = _tool_messages(milestone, "write_file")
    print(f"\n[C:{forbidden_key}] write_file tool messages:", messages)
    assert result.termination.route_state == "routed_task"
    assert milestone.effects.calls == ["context_route"]
    assert milestone.effects.write_file_calls == []
    assert [r.tool_name for r in task_authority.requests] == ["context_route"]
    assert len(messages) == 1 and "MODEL_AUTHORITY_FIELD_FORBIDDEN" in messages[0]


# ---------------------------------------------------------------------------
# (d) root_resolver=None -> fail closed, handler never invoked
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_d_root_resolver_none_fails_closed(milestone, tmp_path) -> None:
    scope_id = await _make_bound_scope(milestone, tmp_path)
    task_authority = CountingTaskExecutionAuthority(ProductTaskExecutionAuthority())
    provider = ScriptedProvider(
        [
            _tool_call(
                "context_route",
                {"route": "resume_existing", "task_scope_id": scope_id},
                raw_id="raw-route",
            ),
            _tool_call("write_file", {"path": "a.txt", "content": "x"}, raw_id="raw-write"),
            _answer("done"),
        ]
    )
    with pytest.raises(TaskExecutionAuthorityError) as excinfo:
        await _run(milestone, provider, task_authority)
    print("\n[D] exception:", repr(excinfo.value))
    print("[D] handler calls:", milestone.effects.calls)
    assert "sdk_task_execution_root_authority_unavailable" in str(excinfo.value)
    assert milestone.effects.calls == ["context_route"]
    assert milestone.effects.write_file_calls == []
    assert [r.tool_name for r in task_authority.requests] == ["context_route", "write_file"]
    assert _tool_messages(milestone, "write_file") == []


# ===========================================================================
# Specialist extension (cluster-effect-gate-exposure) — DISPOSABLE
# ===========================================================================

import os

from simple_harness.tools.runtime_catalog import (
    CatalogRunToolExposure,
    ExecutableToolRecord,
    RuntimeToolCatalog,
    RuntimeToolCatalogError,
    ToolExposureMode,
)


class HidingExposure(RouteExposure):
    """Per-turn hiding: provider_specs omits write_file, catalog policy kept."""

    def __init__(self, hide: frozenset[str]) -> None:
        self.hide = hide

    def provider_specs(self, run_id):
        return tuple(s for s in super().provider_specs(run_id) if s.name not in self.hide)


def _real_catalog_exposure(*, include_write_file: bool, deferred_write_file: bool):
    rev = "e" * 64
    records = [
        ExecutableToolRecord(
            capability_id="builtin:context_route", namespace="builtin",
            source="simple_harness", source_revision=rev,
            exposure_mode=ToolExposureMode.DIRECT, provider_name="context_route",
            description="Route Context", input_schema=CONTEXT_ROUTE_SCHEMA,
            effect_class=ToolEffectClass.CONTEXT_CONTROL,
            route_requirement=ToolRouteRequirement.FORBIDDEN,
            task_scope_requirement=ToolTaskScopeRequirement.FORBIDDEN,
        ),
        ExecutableToolRecord(
            capability_id="builtin:task_scope_search", namespace="builtin",
            source="simple_harness", source_revision=rev,
            exposure_mode=ToolExposureMode.DIRECT, provider_name="task_scope_search",
            description="Search task scopes", input_schema=TASK_SCOPE_SEARCH_SCHEMA,
        ),
    ]
    if include_write_file:
        records.append(
            ExecutableToolRecord(
                capability_id="builtin:write_file", namespace="builtin",
                source="simple_harness", source_revision=rev,
                exposure_mode=(
                    ToolExposureMode.DEFERRED if deferred_write_file else ToolExposureMode.DIRECT
                ),
                provider_name="write_file", description="Write a project file",
                input_schema=WRITE_FILE_SCHEMA,
                effect_class=ToolEffectClass.PROJECT_EFFECT,
                route_requirement=ToolRouteRequirement.REQUIRED,
                task_scope_requirement=ToolTaskScopeRequirement.REQUIRED,
            )
        )
    return CatalogRunToolExposure(RuntimeToolCatalog(records, generation=1))


def _with_exposure(milestone, exposure):
    ports = SimpleNamespace(
        context=milestone.context,
        react_checkpoint=SimpleNamespace(
            read_start_snapshot=lambda run_id: {
                "input": {"context_metadata": {"budget": {"context_window": 32768}}}
            }
        ),
    )
    authority = ProductRunContextAuthority(
        ports_resolver=lambda: ports,
        exposure_resolver=lambda run_id: exposure,
        ledger=milestone.ledger,
    )
    return SimpleNamespace(**{**vars(milestone), "exposure": exposure, "authority": authority})


def _plan_root_resolver(db_path: Path):
    """Plan Task 1 ② semantics: exact immutable receipt, never the live head."""

    async def resolve(receipt):
        store = WorkspaceBindingAuthorityStore(db_path)
        exact = await store.exact_receipt(
            task_scope_id=receipt.task_scope_id,
            binding_set_revision=receipt.binding_set_revision,
            binding_set_receipt_id=receipt.binding_set_receipt_id,
            binding_set_receipt_hash=receipt.binding_set_receipt_hash,
        )
        if len(exact.root_identity_hashes) != 1:
            raise TaskExecutionAuthorityError("sdk_task_execution_root_authority_unavailable")
        return exact.appended_root.root_id, exact.root_identity_hashes[0]

    return resolve


async def _append_root(db_path: Path, scope_id: str, root: Path, *, base_revision: int, tag: str) -> None:
    authority = _ManualAuthority()
    store = WorkspaceBindingAuthorityStore(
        db_path, configured_workspace_root=root.parent, clock_millis=lambda: 1500,
        manual_authorization_authority=authority,
    )
    proposal = WorkspaceBindingProposal(
        f"proposal-{scope_id}-{tag}", RUN.value, AUTH.subject, scope_id,
        canonical_workspace_root(root, root_id=f"root-{scope_id}-{tag}"),
        base_revision, f"append-{scope_id}-{tag}",
    )
    check = ManualWorkspaceChallengeAuthorityCheck(
        proposal, f"nonce-{scope_id}-{tag}",
        WorkspaceBindingAuthorizationChannel.USER_CONFIRMATION,
        f"evidence-{scope_id}-{tag}", "b" * 64, f"interaction-{scope_id}-{tag}",
        1000, 1100, 2000,
    )
    authority.trust_challenge(check)
    challenge = await store.issue_manual_challenge(
        proposal, authorization_nonce=check.authorization_nonce,
        authorization_channel=check.authorization_channel,
        authorization_evidence_id=check.authorization_evidence_id,
        authorization_evidence_hash=check.authorization_evidence_hash,
        interaction_event_id=check.interaction_event_id,
        issued_at_millis=check.issued_at_millis, not_before_millis=check.not_before_millis,
        expires_at_millis=check.expires_at_millis,
    )
    decision_check = ManualWorkspaceDecisionAuthorityCheck(
        challenge, AUTH.subject, WorkspaceBindingAuthorizationDecision.ALLOW, 1200
    )
    authority.trust_decision(decision_check)
    decision = await store.record_manual_decision(
        challenge, decided_by_actor_id=decision_check.decided_by_actor_id,
        decision=decision_check.decision, decided_at_millis=decision_check.decided_at_millis,
    )
    grant = await store.verify_manual_authorization(proposal, challenge, decision)
    await store.append_binding(proposal, grant)


async def _run_capture(m, provider, task_authority):
    out = {"exception": None, "result": None}
    try:
        out["result"] = await _run(m, provider, task_authority)
    except Exception as exc:  # noqa: BLE001 - spike records behaviour
        out["exception"] = exc
    return out


def _checkpoint(m):
    return dict(thaw_json(m.checkpoint.value.checkpoint)) if m.checkpoint.value else {}


# --- E1: per-turn hiding (Host-side provider_specs filter) does not change
#         the standalone outcome: still a Host exception, not a rejection.


@pytest.mark.asyncio
async def test_e1_hidden_from_provider_specs_routed_standalone(milestone) -> None:
    m = _with_exposure(milestone, HidingExposure(frozenset({"write_file"})))
    task_authority = CountingTaskExecutionAuthority(
        ProductTaskExecutionAuthority(root_resolver=_plan_root_resolver(m.db_path))
    )
    provider = ScriptedProvider([
        _tool_call("context_route", {"route": "direct_standalone"}, raw_id="raw-route"),
        _tool_call("write_file", {"path": "a.txt", "content": "x"}, raw_id="raw-write"),
        _answer("done"),
    ])
    out = await _run_capture(m, provider, task_authority)
    specs = [s.name for s in m.exposure.provider_specs(RUN)]
    print("\n[E1] provider_specs:", specs)
    print("[E1] exception:", repr(out["exception"]))
    print("[E1] handler calls:", m.effects.calls, "issue_envelope:", [r.tool_name for r in task_authority.requests])
    print("[E1] write_file TOOL msgs:", _tool_messages(m, "write_file"))
    cp = _checkpoint(m)
    print("[E1] checkpoint:", cp.get("route_state"), cp.get("phase"))
    assert "write_file" not in specs
    assert m.effects.write_file_calls == []
    assert isinstance(out["exception"], TaskExecutionAuthorityError)
    assert "sdk_task_execution_route_authority_missing" in str(out["exception"])
    assert _tool_messages(m, "write_file") == []


# --- E2: real SDK CatalogRunToolExposure: hidden (DEFERRED / absent) tool call


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "variant,include,deferred,first_route",
    [
        ("deferred-standalone", True, True, "direct_standalone"),
        ("deferred-unrouted", True, True, None),
        ("absent-standalone", False, False, "direct_standalone"),
        ("deferred-routed_task", True, True, "resume_existing"),
    ],
)
async def test_e2_real_catalog_hidden_tool_call(milestone, tmp_path, variant, include, deferred, first_route) -> None:
    m = _with_exposure(milestone, _real_catalog_exposure(include_write_file=include, deferred_write_file=deferred))
    task_authority = CountingTaskExecutionAuthority(
        ProductTaskExecutionAuthority(root_resolver=_plan_root_resolver(m.db_path))
    )
    responses = []
    if first_route == "resume_existing":
        scope_id = await _make_bound_scope(m, tmp_path)
        responses.append(_tool_call("context_route", {"route": "resume_existing", "task_scope_id": scope_id}, raw_id="raw-route"))
    elif first_route is not None:
        responses.append(_tool_call("context_route", {"route": first_route}, raw_id="raw-route"))
    responses += [
        _tool_call("write_file", {"path": "a.txt", "content": "x"}, raw_id="raw-write"),
        _answer("done"),
    ]
    provider = ScriptedProvider(responses)
    out = await _run_capture(m, provider, task_authority)
    specs = [s.name for s in m.exposure.provider_specs(RUN)]
    cp = _checkpoint(m)
    print(f"\n[E2:{variant}] provider_specs:", specs)
    print(f"[E2:{variant}] exception:", repr(out["exception"]), "code:", getattr(out["exception"], "code", None))
    print(f"[E2:{variant}] handler calls:", m.effects.calls, "issue_envelope:", [r.tool_name for r in task_authority.requests])
    print(f"[E2:{variant}] write_file TOOL msgs:", _tool_messages(m, "write_file"))
    print(f"[E2:{variant}] checkpoint:", cp.get("route_state"), cp.get("phase"), "provider calls:", len(provider.calls))
    assert "write_file" not in specs
    assert m.effects.write_file_calls == []
    assert isinstance(out["exception"], RuntimeToolCatalogError)
    assert out["exception"].code == "catalog_execution_policy_unavailable"
    assert not any(r.tool_name == "write_file" for r in task_authority.requests)
    assert _tool_messages(m, "write_file") == []


# --- E3: same-Run re-route to another TaskScope switches the envelope root.


@pytest.mark.asyncio
async def test_e3_reroute_to_other_scope_switches_envelope_root(milestone, tmp_path) -> None:
    scope_a = await _make_bound_scope(milestone, tmp_path)
    created = await milestone.service.create_task_scope(
        CreateTaskScopeRequest("task-b", "任务 B", "B 的目标", "create-b")
    )
    scope_b = str(created["scope_ref"])
    await milestone.service.rebuild_derived(scope_b)
    root_b = tmp_path / "workspace" / "root-b"
    root_b.mkdir(parents=True)
    await _bind_scope_root(milestone.db_path, scope_b, root_b)
    task_authority = CountingTaskExecutionAuthority(
        ProductTaskExecutionAuthority(root_resolver=_plan_root_resolver(milestone.db_path))
    )
    provider = ScriptedProvider([
        _tool_call("context_route", {"route": "resume_existing", "task_scope_id": scope_a}, raw_id="raw-route-a"),
        _tool_call("write_file", {"path": "a.txt", "content": "x"}, raw_id="raw-write-a"),
        _tool_call("context_route", {"route": "resume_existing", "task_scope_id": scope_b}, raw_id="raw-route-b"),
        _tool_call("write_file", {"path": "b.txt", "content": "y"}, raw_id="raw-write-b"),
        _answer("done"),
    ])
    out = await _run_capture(milestone, provider, task_authority)
    print("\n[E3] exception:", repr(out["exception"]))
    print("[E3] handler calls:", milestone.effects.calls)
    envs = [rec["envelope"] for rec in milestone.effects.write_file_calls]
    for e in envs:
        print("[E3] envelope scope/root/rev:", e.task_scope_id, e.root_id, e.binding_set_revision, e.route_receipt_id)
    cp = _checkpoint(milestone)
    print("[E3] final route_state:", cp.get("route_state"), "route task_scope:", (cp.get("route_receipt") or {}).get("task_scope_id"))
    assert out["exception"] is None
    assert len(envs) == 2
    assert envs[0].task_scope_id == scope_a and envs[1].task_scope_id == scope_b
    assert envs[0].root_id != envs[1].root_id
    assert out["result"].termination.route_state == "routed_task"


# --- E4: binding append mid-Run (TC-HM-09 step 3): stale route receipt stays valid.


@pytest.mark.asyncio
async def test_e4_append_root_mid_run_stale_receipt_still_executes(milestone, tmp_path) -> None:
    scope_id = await _make_bound_scope(milestone, tmp_path)
    store = WorkspaceBindingAuthorityStore(milestone.db_path)
    head1 = await store.current_receipt(scope_id)
    task_authority = CountingTaskExecutionAuthority(
        ProductTaskExecutionAuthority(root_resolver=_plan_root_resolver(milestone.db_path))
    )
    appended = {"done": False}
    root2 = tmp_path / "workspace" / "root-a2"
    root2.mkdir(parents=True)

    class AppendingProvider(ScriptedProvider):
        async def invoke(self, run_id, request, *, cancel, execution_lease):
            # Between the route turn and the write turn, Manual append root #2.
            if len(self.calls) == 1 and not appended["done"]:
                await _append_root(milestone.db_path, scope_id, root2, base_revision=head1.binding_set_revision, tag="r2")
                appended["done"] = True
            return await super().invoke(run_id, request, cancel=cancel, execution_lease=execution_lease)

    provider = AppendingProvider([
        _tool_call("context_route", {"route": "resume_existing", "task_scope_id": scope_id}, raw_id="raw-route"),
        _tool_call("write_file", {"path": "a.txt", "content": "x"}, raw_id="raw-write"),
        _answer("done"),
    ])
    out = await _run_capture(milestone, provider, task_authority)
    head2 = await store.current_receipt(scope_id)
    print("\n[E4] exception:", repr(out["exception"]))
    print("[E4] head before/after:", head1.binding_set_revision, "->", head2.binding_set_revision, "roots:", len(head2.root_identity_hashes))
    envs = [rec["envelope"] for rec in milestone.effects.write_file_calls]
    print("[E4] envelope revision/root:", [(e.binding_set_revision, e.root_id) for e in envs])
    assert out["exception"] is None
    assert head2.binding_set_revision == head1.binding_set_revision + 1
    assert len(head2.root_identity_hashes) == 2
    assert len(envs) == 1 and envs[0].binding_set_revision == head1.binding_set_revision
    from simple_harness.execution.context_authority import ContextRouteReceipt
    frozen = ContextRouteReceipt.from_json(_checkpoint(milestone)["route_receipt"])
    authority = await store.verify_task_execution_envelope(envs[0], frozen)
    print("[E4] verify_task_execution_envelope (stale rev vs head) ->", authority.binding_set_revision, "ACCEPTED")
    # A head-equality resolver (spike A3 style) would instead fail closed:
    strict = _real_root_resolver(milestone.db_path)
    try:
        await strict(frozen)
        strict_outcome = "accepted"
    except AssertionError:
        strict_outcome = "AssertionError(head != receipt)"
    print("[E4] head-equality resolver ->", strict_outcome)


# --- E5: filesystem drift reason codes from the real S4 store re-verification.


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", ["rename_away", "replace_same_path", "symlink_same_path"])
async def test_e5_inode_drift_reason_codes(milestone, tmp_path, drift) -> None:
    scope_id = await _make_bound_scope(milestone, tmp_path)
    store = WorkspaceBindingAuthorityStore(milestone.db_path)
    task_authority = CountingTaskExecutionAuthority(
        ProductTaskExecutionAuthority(root_resolver=_plan_root_resolver(milestone.db_path))
    )
    workspace = tmp_path / "workspace" / "root-a"
    provider = ScriptedProvider([
        _tool_call("context_route", {"route": "resume_existing", "task_scope_id": scope_id}, raw_id="raw-route"),
        _tool_call("write_file", {"path": "a.txt", "content": "x"}, raw_id="raw-write"),
        _answer("done"),
    ])
    out = await _run_capture(milestone, provider, task_authority)
    assert out["exception"] is None
    envelope = milestone.effects.write_file_calls[0]["envelope"]
    from simple_harness.execution.context_authority import ContextRouteReceipt
    frozen = ContextRouteReceipt.from_json(_checkpoint(milestone)["route_receipt"])
    moved = tmp_path / "workspace" / "moved-a"
    os.rename(workspace, moved)
    if drift == "replace_same_path":
        workspace.mkdir()
    elif drift == "symlink_same_path":
        os.symlink(moved, workspace)
    try:
        await store.verify_task_execution_envelope(envelope, frozen)
        code = "ACCEPTED"
    except WorkspaceBindingError as exc:
        code = exc.code
    print(f"\n[E5:{drift}] verify_task_execution_envelope ->", code)
    # The envelope itself was issued from the exact receipt only: no inode check
    # at issue time (plan resolver = exact_receipt).  The drift is caught only by
    # the Host per-effect re-verification, never by the SDK.
    assert code != "ACCEPTED"
    assert code in {"workspace_root_unavailable", "workspace_root_identity_drift", "workspace_root_not_canonical"}
