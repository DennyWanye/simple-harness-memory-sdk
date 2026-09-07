"""Approved source-only oracle: real SQLite effects, never product-filled expectations."""

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest

import simple_harness_memory as m
from simple_harness_memory.backends.sqlite_v5 import SQLiteHumanMemoryBackend
from simple_harness_memory.core.errors import MemoryIdempotencyConflict, MemoryOwnershipConflict
from tests.integration.test_evidence_ingestion_v5 import _authority

PRINCIPAL = m.MemoryPrincipal("deployment-1", "household-1", "actor-1", "session-1")
PROHIBITED = (
    "jobs",
    "outbox",
    "job_attempts",
    "analysis_batches",
    "analysis_batch_members",
    "analysis_apply_heads",
    "accepted_analysis_plans",
    "cognitive_apply_heads",
    "cognitive_memory_heads",
    "cognitive_memory_revisions",
    "cognitive_evidence_spans",
    "memory_mutation_receipts",
)

OPEN = []


@pytest.fixture(autouse=True)
async def cleanup():
    yield
    for backend in OPEN:
        if backend._db is not None:
            await backend.close()
    OPEN.clear()


async def setup(path, *, clock=lambda: 20.0, fault=None):
    backend = SQLiteHumanMemoryBackend(path, now=clock, fault_injector=fault)
    OPEN.append(backend)
    await backend.initialize()
    await backend.register_principal_owner(PRINCIPAL, m.MemoryScope.personal("actor-1"))
    return backend, m.MemoryManager(backend, None)


async def counts(backend):
    async with backend.connection.execute("SELECT name FROM sqlite_master WHERE type='table'") as c:
        names = {row[0] for row in await c.fetchall()}
    result = {}
    for table in (
        *PROHIBITED,
        "evidence_envelopes",
        "source_admission_receipts",
        "ingestion_receipts",
    ):
        if table in names:
            async with backend.connection.execute(f"SELECT count(*) FROM {table}") as c:
                result[table] = (await c.fetchone())[0]
    return result


async def admit(manager, pair, principal=PRINCIPAL):
    return await manager.admit_evidence_source(
        principal=principal, envelope=pair[0], receipt=pair[1]
    )


def test_independent_receipt_vectors():
    vectors = json.loads(
        (Path(__file__).parents[1] / "fixtures/source-admission-v1.json").read_text()
    )
    for v in vectors:
        result = m.EvidenceSourceAdmissionReceipt(**v["payload"])
        assert result.to_json() == v["payload"]
        assert result.receipt_hash == v["receipt_hash"]
        from simple_harness_memory.backends.source_admission import source_receipt_id

        assert source_receipt_id(**v["id_input"]["payload"]) == v["payload"]["receipt_id"]
        for field in v["payload"]:
            if field == "schema_version":
                continue
            original = v["payload"][field]
            changed = (
                original + 1
                if isinstance(original, float)
                else ("e" * 64 if field.endswith("_hash") else original + "x")
            )
            assert replace(result, **{field: changed}).receipt_hash != v["receipt_hash"]
        assert not {"mutation_job_id", "outbox_id"} & result.to_json().keys()


async def test_source_fresh_replay_reopen_has_no_jobs_or_analysis_writes(tmp_path):
    path = tmp_path / "source.db"
    backend, manager = await setup(path)
    pair = _authority({"public_text": "actual source"})
    trace = []
    await backend.connection.set_trace_callback(trace.append)
    first = await admit(manager, pair)
    assert type(first) is m.EvidenceSourceAdmissionReceipt
    assert first.accepted_at == 20.0
    assert first.subject == PRINCIPAL.actor_id
    assert await admit(manager, pair) == first
    rows = await counts(backend)
    assert rows["evidence_envelopes"] == rows["source_admission_receipts"] == 1
    assert rows["ingestion_receipts"] == 0
    assert all(rows[t] == 0 for t in PROHIBITED if t in rows)
    writes = [
        sql.lower()
        for sql in trace
        if sql.lstrip().lower().startswith(("insert", "update", "delete"))
    ]
    assert not any(f" {table}" in sql for sql in writes for table in PROHIBITED)
    exported = await backend.export_ingested_evidence(pair[0].evidence_id)
    assert exported.ingestion_receipt == first
    await manager.close()
    backend, manager = await setup(path, clock=lambda: 99.0)
    assert await admit(manager, pair) == first
    assert await counts(backend) == rows
    await manager.close()


@pytest.mark.parametrize("first_mode", ["source", "full"])
@pytest.mark.parametrize("collision", ["exact", "source_ref", "evidence_id", "admission_id"])
async def test_cross_mode_each_shared_key_conflicts_without_writes(tmp_path, first_mode, collision):
    backend, manager = await setup(tmp_path / "mode.db")
    pair = _authority({"public_text": "original"})
    if first_mode == "source":
        await admit(manager, pair)
    else:
        old = await manager.ingest_committed_evidence(*pair)
        assert old.mutation_job_id and old.outbox_id
    before = await counts(backend)
    other = (
        pair
        if collision == "exact"
        else _authority(
            {"public_text": "changed"},
            source_ref=pair[0].source_ref if collision == "source_ref" else "different-ref",
            evidence_id=pair[0].evidence_id if collision == "evidence_id" else "different-evidence",
            receipt_id=pair[1].receipt_id if collision == "admission_id" else "different-admission",
        )
    )
    with pytest.raises(MemoryIdempotencyConflict, match="^evidence_admission_mode_conflict$"):
        if first_mode == "source":
            await manager.ingest_committed_evidence(*other)
        else:
            await admit(manager, other)
    assert await counts(backend) == before
    await manager.close()


async def test_same_mode_changed_host_receipt_and_principal_reject(tmp_path):
    backend, manager = await setup(tmp_path / "identity.db")
    pair = _authority({"public_text": "source"})
    await admit(manager, pair)
    before = await counts(backend)
    with pytest.raises(MemoryIdempotencyConflict):
        await admit(manager, (pair[0], replace(pair[1], admitted_at=11.0)))
    with pytest.raises(MemoryOwnershipConflict):
        await admit(manager, pair, replace(PRINCIPAL, deployment_id="wrong"))
    assert await counts(backend) == before
    await manager.close()


async def test_concurrent_same_source_exact_replay(tmp_path):
    backend, manager = await setup(tmp_path / "race.db")
    pair = _authority({"public_text": "source"})
    results = await asyncio.gather(*(admit(manager, pair) for _ in range(8)))
    assert all(x == results[0] for x in results)
    rows = await counts(backend)
    assert rows["source_admission_receipts"] == 1 and rows["jobs"] == rows["outbox"] == 0
    await manager.close()


@pytest.mark.parametrize(
    "point",
    [
        "source_admission.after_envelope",
        "source_admission.after_receipt",
        "source_admission.before_commit",
        "source_admission.after_commit",
    ],
)
async def test_fault_rollback_or_committed_exact_replay(tmp_path, point):
    control_backend, control_manager = await setup(tmp_path / "control.db")
    control_pair = _authority({"public_text": "source"})
    control = await admit(control_manager, control_pair)
    assert control.accepted_at == 20.0
    assert (
        await control_backend.export_ingested_evidence(control_pair[0].evidence_id)
    ).envelope == control_pair[0]
    control_rows = await counts(control_backend)
    assert control_rows["source_admission_receipts"] == 1
    assert control_rows["jobs"] == control_rows["outbox"] == 0
    path = tmp_path / "fault.db"
    fired = []

    def fault(name):
        if name == point and not fired:
            fired.append(name)
            raise RuntimeError("lost ACK" if name.endswith("after_commit") else "crash")

    backend, manager = await setup(path, fault=fault)
    pair = _authority({"public_text": "source"})
    with pytest.raises(RuntimeError):
        await admit(manager, pair)
    rows = await counts(backend)
    assert rows["source_admission_receipts"] == int(point.endswith("after_commit"))
    assert rows["jobs"] == rows["outbox"] == 0
    await manager.close()
    backend, manager = await setup(path, clock=lambda: 99.0)
    actual = await admit(manager, pair)
    assert actual.accepted_at == (20.0 if point.endswith("after_commit") else 99.0)
    if point.endswith("after_commit"):
        assert actual == control
    assert await admit(manager, pair) == actual
    await manager.close()


@pytest.mark.parametrize("collision", ["source_ref", "evidence_id", "admission_id"])
async def test_two_sqlite_connections_cross_mode_transaction_strength(tmp_path, collision):
    # Internal strength ONLY: public startup denies a second writer. No product lease changed.
    from simple_harness_memory.core.errors import MemoryWriterConflict

    path = tmp_path / "connections.db"
    first, one = await setup(path)
    second = SQLiteHumanMemoryBackend(path, now=lambda: 31.0)
    with pytest.raises(MemoryWriterConflict):
        await second.initialize()
    first._release_writer_lease()  # source-test-only controlled competing connections
    second, two = await setup(path, clock=lambda: 31.0)
    pair = _authority({"public_text": "source"})
    other = _authority(
        {"public_text": "full"},
        source_ref=pair[0].source_ref if collision == "source_ref" else "full-ref",
        evidence_id=pair[0].evidence_id if collision == "evidence_id" else "full-evidence",
        receipt_id=pair[1].receipt_id if collision == "admission_id" else "full-admission",
    )
    results = await asyncio.gather(
        admit(one, pair), two.ingest_committed_evidence(*other), return_exceptions=True
    )
    winners = [x for x in results if not isinstance(x, BaseException)]
    losers = [x for x in results if isinstance(x, BaseException)]
    assert len(winners) == len(losers) == 1
    assert type(losers[0]) is MemoryIdempotencyConflict
    assert str(losers[0]) == "evidence_admission_mode_conflict"
    rows = await counts(first)
    assert rows["evidence_envelopes"] == 1
    full_won = type(winners[0]) is m.EvidenceIngestionReceipt
    assert rows["jobs"] == rows["outbox"] == int(full_won)
    assert rows["source_admission_receipts"] == int(not full_won)
    assert winners[0].accepted_at == (31.0 if full_won else 20.0)
    if full_won:
        assert await two.ingest_committed_evidence(*other) == winners[0]
    else:
        assert await admit(one, pair) == winners[0]


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), -1.0])
async def test_invalid_clock_rejects_without_rows(tmp_path, value):
    from simple_harness_memory.core.errors import MemoryValidationError

    backend, manager = await setup(tmp_path / "clock.db")
    backend._now = lambda: value
    before = await counts(backend)
    with pytest.raises(MemoryValidationError):
        await admit(manager, _authority({"public_text": "source"}))
    assert await counts(backend) == before


@pytest.mark.parametrize("version", ["7.0", "7.1"])
async def test_old_database_rejected_read_only(tmp_path, version):
    import hashlib
    import sqlite3

    from simple_harness_memory.backends.schema_v5 import DDL_V7_0, DDL_V7_1
    from simple_harness_memory.core.errors import MemoryLegacySchemaUnsupported

    path = tmp_path / "old.db"
    with sqlite3.connect(path) as db:
        db.executescript(DDL_V7_0 if version == "7.0" else DDL_V7_1)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    backend = SQLiteHumanMemoryBackend(path)
    with pytest.raises(MemoryLegacySchemaUnsupported):
        await backend.initialize()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert not path.with_suffix(".db.writer.lock").exists()


async def test_source_only_span_does_not_acquire_full_mutation_admission(tmp_path):
    from simple_harness_memory.core.errors import MemoryValidationError
    from tests.integration.test_cognitive_mutation_repository_v5 import (
        _admitted,
        _Authority,
        _classification_policy,
        _operation,
        _plan,
        _prepared,
        _span,
    )

    pair = _admitted()
    span = _span(*pair)
    authority = _Authority(*pair, span)
    backend = SQLiteHumanMemoryBackend(
        tmp_path / "source-span.db",
        now=lambda: 20.0,
        evidence_authority=authority,
        memory_action_authority=authority,
        classification_policy=_classification_policy(),
    )
    OPEN.append(backend)
    await backend.initialize()
    await backend.register_principal_owner(PRINCIPAL, m.MemoryScope.personal("actor-1"))
    manager = m.MemoryManager(backend, None)
    await admit(manager, pair)
    with pytest.raises(MemoryValidationError):
        await manager.apply_memory_mutation_plan(
            principal=PRINCIPAL,
            scope=m.MemoryScope.personal("actor-1"),
            plan=_plan(pair[0], _operation(span)),
        )
    full, env, _, full_span, _ = await _prepared(tmp_path / "full-span.db")
    OPEN.append(full)
    result = await full.apply_memory_mutation_plan(
        principal=PRINCIPAL,
        scope=m.MemoryScope.personal("actor-1"),
        plan=_plan(env, _operation(full_span)),
    )
    assert result.receipt_ref is not None


async def test_source_registration_selected_short_history_suppress_reopen(tmp_path):
    from tests.integration.test_cognitive_mutation_repository_v5 import _classification_policy
    from tests.integration.test_short_horizon_repository_v5 import (
        NOW,
        _Authority,
        _disclosure,
        _registration,
    )

    registrations = tuple(_registration(i) for i in range(1, 12))
    kwargs = dict(
        clock=lambda: NOW,
        conversation_evidence_authority=_Authority(tuple(x[0] for x in registrations)),
        classification_policy=_classification_policy(),
    )
    path = tmp_path / "short.db"
    manager = await m.build_human_memory_v7(path, **kwargs)
    OPEN.append(manager.backend)
    await manager.register_principal_owner(PRINCIPAL, m.MemoryScope.personal("actor-1"))
    for reg, ref in registrations:
        await admit(manager, (reg.envelope, reg.admission_receipt))
        await manager.register_conversation_evidence(ref)
    build = await manager.rebuild_short_horizon_projection(principal=PRINCIPAL)
    assert build.projected_chunk_count == 1
    result = await manager.recall_short_horizon(
        principal=PRINCIPAL, query="Project alpha", disclosure_context=_disclosure()
    )
    assert len(result.hits) == 1
    assert result.hits[0].content == "user: Project alpha note 1"
    bindings = (
        m.HistoryShortHorizonBinding(
            result.audit_id, result.hits[0].chunk_ref, result.hits[0].content_hash
        ),
        m.HistoryEvidenceBinding(
            registrations[0][0].envelope, registrations[0][0].admission_receipt
        ),
    )
    snapshot = await manager.check_history_visibility(
        principal=PRINCIPAL, disclosure_context=_disclosure(), bindings=bindings
    )
    assert all(x.visible for x in snapshot.items)
    rows = await counts(manager.backend)
    assert rows["jobs"] == rows["outbox"] == 0
    await manager.suppress(
        principal=PRINCIPAL,
        request=m.SuppressionRequest(
            "forget-source",
            "actor-1",
            m.SuppressionScopeKind.EVIDENCE,
            "evidence-1",
            "user_forget",
            NOW,
        ),
    )
    snapshot = await manager.check_history_visibility(
        principal=PRINCIPAL, disclosure_context=_disclosure(), bindings=bindings
    )
    assert all(not x.visible for x in snapshot.items)
    await manager.close()
    reopened = await m.build_human_memory_v7(path, **kwargs)
    OPEN.append(reopened.backend)
    snapshot = await reopened.check_history_visibility(
        principal=PRINCIPAL, disclosure_context=_disclosure(), bindings=bindings
    )
    assert all(not x.visible for x in snapshot.items)


@pytest.mark.parametrize("tamper", ["receipt", "dual_mode"])
async def test_source_receipt_corruption_never_coalesced(tmp_path, tamper):
    from simple_harness_memory.core.errors import MemoryCorruptionError

    backend, manager = await setup(tmp_path / "corrupt.db")
    pair = _authority({"public_text": "source"})
    await admit(manager, pair)
    if tamper == "receipt":
        await backend.connection.execute("DROP TRIGGER source_admission_receipts_immutable_update")
        await backend.connection.execute(
            "UPDATE source_admission_receipts SET admission_receipt_json='{}'"
        )
    else:
        await backend.connection.execute(
            "INSERT INTO ingestion_receipts SELECT * FROM source_admission_receipts"
        )
    with pytest.raises((MemoryCorruptionError, TypeError, ValueError)):
        await backend._read_ingested_record(pair[0].evidence_id)
    # Corrupt DB is deliberately unsealable; close underlying test connection and release lease.
    await backend.connection.close()
    backend._db = None
    backend._release_writer_lease()


@pytest.mark.parametrize(
    "attack",
    [
        "bad_type",
        "wrong_subject",
        "bad_hash",
        "bad_receipt",
        "unregistered_owner",
        "unsupported_filter",
    ],
)
async def test_fresh_admission_attacks_reject_before_writes(tmp_path, attack):
    from simple_harness_memory.core.errors import MemoryValidationError

    backend, manager = await setup(tmp_path / "attack.db")
    pair = _authority({"public_text": "source"})
    principal = PRINCIPAL
    if attack == "bad_type":
        pair = (pair[0].to_json(), pair[1])
    elif attack == "wrong_subject":
        principal = replace(PRINCIPAL, actor_id="different")
    elif attack == "bad_hash":
        object.__setattr__(pair[0], "envelope_hash", "0" * 64)
    elif attack == "bad_receipt":
        object.__setattr__(pair[1], "envelope_hash", "0" * 64)
    elif attack == "unregistered_owner":
        principal = replace(PRINCIPAL, household_id="different")
    else:
        pair = _authority({"public_text": "source"}, filter_policy="unsupported")
    before = await counts(backend)
    with pytest.raises((TypeError, ValueError, MemoryValidationError, MemoryOwnershipConflict)):
        await admit(manager, pair, principal)
    assert await counts(backend) == before


async def test_memory_only_forget_keeps_source_child_and_original_user_after_reopen(tmp_path):
    """2026-09-07 决定：MEMORY 遗忘跨重开不隐藏原始 USER 证据及其 ASSISTANT 子证据；
    EVIDENCE 压制仍沿血缘隐藏两者（对照）。"""
    import simple_harness as h

    from tests.integration.test_cognitive_mutation_repository_v5 import (
        _classification_policy,
        _disclosure,
        _operation,
        _plan,
        _prepared,
    )

    path = tmp_path / "memory-forget.db"
    backend, parent, admission, span, _ = await _prepared(path)
    OPEN.append(backend)
    await backend.register_principal_owner(PRINCIPAL, m.MemoryScope.personal("actor-1"))
    manager = m.MemoryManager(backend, None)
    applied = await manager.apply_memory_mutation_plan(
        principal=PRINCIPAL,
        scope=m.MemoryScope.personal("actor-1"),
        plan=_plan(parent, _operation(span)),
    )
    view = await manager.get_memory_mutation_receipt_view(
        principal=PRINCIPAL, receipt_ref=applied.receipt_ref
    )
    child, receipt = _authority(
        {"public_text": "assistant cited original source"},
        evidence_id="assistant",
        source_ref="assistant-message",
        receipt_id="assistant-admission",
    )
    child = replace(
        child,
        source_kind=h.EvidenceSourceKind.ASSISTANT_MESSAGE,
        evidence_refs=(h.EvidenceRef(parent.evidence_id, parent.envelope_hash, 1),),
    )
    receipt = replace(receipt, envelope_hash=child.envelope_hash, evidence_refs=child.evidence_refs)
    await admit(manager, (child, receipt))
    bindings = (
        m.HistoryEvidenceBinding(child, receipt),
        m.HistoryEvidenceBinding(parent, admission),
    )
    snapshot = await manager.check_history_visibility(
        principal=PRINCIPAL, disclosure_context=_disclosure(), bindings=bindings
    )
    assert all(x.visible for x in snapshot.items)
    await manager.suppress(
        principal=PRINCIPAL,
        request=m.SuppressionRequest(
            "memory-forget",
            "actor-1",
            m.SuppressionScopeKind.MEMORY,
            view.operations[0].memory_id,
            "user_forget",
            20.0,
        ),
    )
    assert all(
        x.visible
        for x in (
            await manager.check_history_visibility(
                principal=PRINCIPAL, disclosure_context=_disclosure(), bindings=bindings
            )
        ).items
    )
    await manager.close()
    reopened = await m.build_human_memory_v7(path, classification_policy=_classification_policy())
    OPEN.append(reopened.backend)
    assert all(
        x.visible
        for x in (
            await reopened.check_history_visibility(
                principal=PRINCIPAL, disclosure_context=_disclosure(), bindings=bindings
            )
        ).items
    )
    await reopened.suppress(
        principal=PRINCIPAL,
        request=m.SuppressionRequest(
            "evidence-forget",
            "actor-1",
            m.SuppressionScopeKind.EVIDENCE,
            parent.evidence_id,
            "user_forget",
            20.0,
        ),
    )
    assert all(
        not x.visible
        for x in (
            await reopened.check_history_visibility(
                principal=PRINCIPAL, disclosure_context=_disclosure(), bindings=bindings
            )
        ).items
    )
