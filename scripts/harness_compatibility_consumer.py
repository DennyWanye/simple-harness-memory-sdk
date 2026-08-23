#!/usr/bin/env python3
"""Black-box Agent Memory compatibility checks for an isolated wheel pair."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import importlib.metadata
import json
import sqlite3
from pathlib import Path
from typing import Any

import simple_harness
from simple_harness import (
    AgentIdentity,
    AgentMemoryErrorCode,
    CommittedTurn,
    CommittedTurnReceipt,
    CommittedTurnStatus,
    ConsumerRuntimePolicies,
    ConsumerRuntimePorts,
    ConversationTurnInput,
    MemoryRecallBounds,
    MemoryRecallRequest,
    MemoryRecallResult,
    MemoryRecallStatus,
    MemoryReleaseRequest,
    MemoryScopeRef,
    Message,
    MessageRole,
    RunClient,
    RunId,
    Runtime,
    build_consumer_runtime,
)
from simple_harness.observability import SCHEMA_VERSION as OBSERVABILITY_SCHEMA_VERSION
from simple_harness.providers import ProviderRequest, ProviderResponse
from simple_harness.runtime import AuthorizationRequest, AuthorizationResult
from simple_harness.tools import ToolCall, ToolResult

import simple_harness_memory
from simple_harness_memory import MemoryManager
from simple_harness_memory.embedders import CloudEmbedder


class _DeterministicEmbeddingClient:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [
            [
                float(sum(text.encode("utf-8")) % 101) / 100.0,
                float((len(text.encode("utf-8")) * 17) % 97) / 100.0,
            ]
            for text in texts
        ]


def _cloud_embedder() -> CloudEmbedder:
    return CloudEmbedder(
        _DeterministicEmbeddingClient(),
        model="compatibility-cloud-model",
        dim=2,
        provider="compatibility-provider",
        revision="compatibility-revision-v1",
        retries=0,
    )


class _DeterministicProvider:
    def __init__(self) -> None:
        self.requests: list[ProviderRequest] = []

    async def invoke(self, request: ProviderRequest, *, cancel) -> ProviderResponse:  # type: ignore[no-untyped-def]
        del cancel
        self.requests.append(request)
        return ProviderResponse(
            request.request_id,
            Message(MessageRole.ASSISTANT, "compatibility answer"),
            model="compatibility-model",
            finish_reason="stop",
        )


class _NoopTools:
    async def execute(self, call: ToolCall, context) -> ToolResult:  # type: ignore[no-untyped-def]
        raise AssertionError((call, context))


class _AllowAuthorization:
    async def request_authorization(self, request: AuthorizationRequest) -> AuthorizationResult:
        del request
        return AuthorizationResult("allow")


def _field_names(value: Any) -> tuple[str, ...]:
    return tuple(field.name for field in dataclasses.fields(value))


def _assert_public_contract() -> None:
    expected_exports = {
        "AgentIdentity",
        "AgentMemoryError",
        "AgentMemoryErrorCode",
        "AgentMemoryPort",
        "CommittedTurn",
        "CommittedTurnReceipt",
        "CommittedTurnStatus",
        "MemoryRecallBounds",
        "MemoryRecallRequest",
        "MemoryRecallResult",
        "MemoryRecallStatus",
        "MemoryReleaseRequest",
        "MemoryScopeKind",
        "MemoryScopeRef",
    }
    assert expected_exports.issubset(simple_harness.__all__)
    assert OBSERVABILITY_SCHEMA_VERSION == 1
    assert _field_names(AgentIdentity) == (
        "deployment_id",
        "household_id",
        "actor_id",
        "session_id",
    )
    assert _field_names(MemoryRecallRequest) == (
        "query_id",
        "turn_id",
        "identity",
        "scopes",
        "query_text",
        "bounds",
        "turn_started_at",
        "query_hash",
    )
    assert _field_names(MemoryRecallResult) == (
        "query_id",
        "query_hash",
        "result_id",
        "payload",
        "status",
        "item_count",
        "byte_count",
        "write_fence",
        "result_hash",
    )
    assert _field_names(MemoryReleaseRequest) == (
        "query_id",
        "query_hash",
        "result_id",
        "result_hash",
        "write_fence",
    )
    assert _field_names(CommittedTurn) == (
        "turn_id",
        "identity",
        "user_text",
        "assistant_text",
        "write_scope",
        "write_fence",
        "turn_started_at",
        "payload_hash",
    )
    assert _field_names(CommittedTurnReceipt) == (
        "turn_id",
        "payload_hash",
        "status",
        "receipt_id",
    )
    assert [value.value for value in MemoryRecallStatus] == ["ready", "empty", "truncated"]
    assert [value.value for value in CommittedTurnStatus] == [
        "applied",
        "already_applied",
        "rejected_erased",
        "conflict",
    ]
    assert [value.value for value in AgentMemoryErrorCode] == [
        "memory_transient",
        "memory_timeout",
        "memory_corrupt_result",
        "memory_conflict",
        "memory_permanent",
    ]


def _recall_request(identity: AgentIdentity, *, query_id: str, text: str) -> MemoryRecallRequest:
    request = MemoryRecallRequest(
        query_id,
        f"turn-for-{query_id}",
        identity,
        (
            MemoryScopeRef.personal(identity.actor_id),
            MemoryScopeRef.family(identity.household_id),
        ),
        text,
        MemoryRecallBounds(),
        1.0,
    )
    assert request.canonical_payload()["protocol"] == (
        "simple-harness-agent-memory/recall-request/v1"
    )
    return request


async def _verify_direct_port(root: Path) -> None:
    path = root / "direct-memory.db"
    alice = AgentIdentity("compat-deployment", "home-a", "alice", "alice-session")
    bob = AgentIdentity("compat-deployment", "home-a", "bob", "bob-session")
    manager = await MemoryManager.build(path, embedder=_cloud_embedder())
    initial = await manager.recall_for_turn(
        _recall_request(alice, query_id="alice-initial", text="private preference")
    )
    assert isinstance(initial, MemoryRecallResult)
    assert initial.status in {MemoryRecallStatus.EMPTY, MemoryRecallStatus.READY}
    await manager.release_recall(
        MemoryReleaseRequest(
            initial.query_id,
            initial.query_hash,
            initial.result_id,
            initial.result_hash,
            initial.write_fence,
        )
    )
    alice_turn = CommittedTurn(
        "alice-turn",
        alice,
        "alice private preference",
        "alice private answer",
        MemoryScopeRef.personal("alice"),
        initial.write_fence,
        1.0,
    )
    assert alice_turn.canonical_payload()["protocol"] == (
        "simple-harness-agent-memory/committed-turn/v1"
    )
    first = await manager.record_committed_turn(alice_turn)
    replay = await manager.record_committed_turn(alice_turn)
    assert first.status is CommittedTurnStatus.APPLIED
    assert replay.status is CommittedTurnStatus.ALREADY_APPLIED
    assert replay.receipt_id == first.receipt_id
    bob_turn = CommittedTurn(
        "bob-turn",
        bob,
        "bob secret marker",
        "bob secret answer",
        MemoryScopeRef.personal("bob"),
        None,
        2.0,
    )
    assert (await manager.record_committed_turn(bob_turn)).status is CommittedTurnStatus.APPLIED
    isolated = await manager.recall_for_turn(
        _recall_request(alice, query_id="alice-isolation", text="bob secret marker")
    )
    assert "bob secret" not in repr(isolated.payload)
    await manager.close()

    reopened = await MemoryManager.build(path, embedder=_cloud_embedder())
    assert (await reopened.record_committed_turn(alice_turn)).status is (
        CommittedTurnStatus.ALREADY_APPLIED
    )
    await reopened.close()
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM turn_receipts").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 4
        assert connection.execute(
            "SELECT COUNT(*) FROM messages WHERE actor_id='alice'"
        ).fetchone()[0] == 2
        assert connection.execute(
            "SELECT COUNT(*) FROM messages WHERE actor_id='bob'"
        ).fetchone()[0] == 2
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()


async def _build_runtime(
    execution_path: Path,
    memory: MemoryManager,
    provider: _DeterministicProvider,
) -> Runtime:
    return await build_consumer_runtime(
        ConsumerRuntimePorts(
            provider=provider,
            tool_executor=_NoopTools(),
            authorization=_AllowAuthorization(),
            database_path=str(execution_path),
            memory=memory,
            policies=ConsumerRuntimePolicies.local_default(),
        )
    )


async def _verify_harness_lifecycle(root: Path) -> None:
    execution_path = root / "execution.db"
    memory_path = root / "runtime-memory.db"
    memory = await MemoryManager.build(memory_path, embedder=_cloud_embedder())
    identity = AgentIdentity("compat-deployment", "home-a", "alice", "runtime-session")
    provider = _DeterministicProvider()
    runtime = await _build_runtime(execution_path, memory, provider)
    async with runtime:
        client = RunClient(runtime)
        value = ConversationTurnInput(
            identity,
            Message(MessageRole.USER, "remember the compatibility marker"),
            "remember the compatibility marker",
        )
        await client.start_conversation(value, run_id=RunId("compat-run"))
        await runtime.wait_idle(RunId("compat-run"))
        await client.start_conversation(value, run_id=RunId("compat-run"))
        await runtime.wait_idle(RunId("compat-run"))
    assert len(provider.requests) == 1

    with sqlite3.connect(execution_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM context_preparation_staging WHERE state='consumed'"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_outbox WHERE state='applied'"
        ).fetchone()[0] == 1
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
    with sqlite3.connect(memory_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM turn_receipts").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 2

    restarted_provider = _DeterministicProvider()
    restarted = await _build_runtime(execution_path, memory, restarted_provider)
    async with restarted:
        await RunClient(restarted).start_conversation(value, run_id=RunId("compat-run"))
        await restarted.wait_idle(RunId("compat-run"))
    assert restarted_provider.requests == []
    await memory.close()
    with sqlite3.connect(execution_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM memory_outbox").fetchone()[0] == 1
    with sqlite3.connect(memory_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM turn_receipts").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 2


async def _main(args: argparse.Namespace) -> None:
    assert importlib.metadata.version("simple-harness-sdk") == args.expected_harness_version
    assert importlib.metadata.version("simple-harness-memory-sdk") == args.expected_memory_version
    assert simple_harness_memory.__version__ == args.expected_memory_version
    assert "site-packages" in str(Path(simple_harness.__file__).resolve())
    assert "site-packages" in str(Path(simple_harness_memory.__file__).resolve())
    _assert_public_contract()
    args.work_dir.mkdir(parents=True, exist_ok=False)
    await _verify_direct_port(args.work_dir)
    await _verify_harness_lifecycle(args.work_dir)
    print(
        json.dumps(
            {
                "harness_version": args.expected_harness_version,
                "memory_version": args.expected_memory_version,
                "result": "pass",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-harness-version", required=True)
    parser.add_argument("--expected-memory-version", required=True)
    parser.add_argument("--work-dir", required=True, type=Path)
    asyncio.run(_main(parser.parse_args()))
