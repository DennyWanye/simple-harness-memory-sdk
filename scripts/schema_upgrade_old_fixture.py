"""Produce nonempty upgrade inputs with an exact OLD installed SDK, never current DDL.

Run with that wheel's isolated Python (-I). archived_source supplies only its tests'
Host authority factories; product imports must remain inside sys.prefix. SQL here
is SDK test instrumentation (WAL controls/catalog/old-column diagnostics), not Host.
The output directory is raw ignored evidence. --crash leaves committed WAL intact.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    )


def catalog(db):
    objects = [
        list(r)
        for r in db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name")
    ]
    tables = [r[1] for r in objects if r[0] == "table"]
    return {
        "objects": objects,
        "tables": {
            name: {
                pragma: [list(r) for r in db.execute(f'PRAGMA {pragma}("{name}")')]
                for pragma in ("table_xinfo", "index_list", "foreign_key_list")
            }
            for name in tables
        },
    }


def rows_snapshot(db):
    names = sorted(
        r[0]
        for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    )

    def encode(value):
        return {"blob_hex": value.hex()} if isinstance(value, bytes) else value

    return {
        name: {
            "columns": [r[1] for r in db.execute(f'PRAGMA table_info("{name}")')],
            "rows": sorted(
                ([encode(v) for v in r] for r in db.execute(f'SELECT * FROM "{name}"')),
                key=canonical,
            ),
        }
        for name in names
    }


async def produce(args):
    sys.path.insert(0, str(args.archived_source.resolve()))  # tests only; no src path
    from simple_harness.runtime import MemoryMutationApplyOutcome

    import simple_harness_memory as m
    from simple_harness_memory.core.suppression import (
        OrdinaryMemoryPurpose,
        SuppressionCandidate,
        SuppressionDecision,
    )
    from tests.integration.test_cognitive_mutation_repository_v5 import (
        _admitted,
        _operation,
        _plan,
        _prepared,
        _principal,
    )
    from tests.integration.test_typed_recall_v6 import _context, _recall_plan

    assert Path(m.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
    args.output.mkdir(parents=True, exist_ok=False)
    path = (args.output / "old.db").resolve()
    if args.extended:
        from simple_harness_memory.backends.sqlite_v5 import SQLiteHumanMemoryBackend
        from tests.integration.test_cognitive_mutation_repository_v5 import (
            _Authority,
            _classification_policy,
            _span,
        )
        from tests.integration.test_durable_memory_jobs_v5 import TEST_WORKER_CONFIG, _Executor
        from tests.integration.test_short_horizon_repository_v5 import (
            _Authority as ConversationAuthority,
        )
        from tests.integration.test_short_horizon_repository_v5 import (
            _disclosure,
            _registration,
        )

        env, admission = _admitted()
        span = _span(env, admission)
        executor = _Executor(None, no_mutation=True)
        pairs = tuple(_registration(i) for i in range(100, 111))
        backend = SQLiteHumanMemoryBackend(
            path,
            now=lambda: 1_000_000.0,
            evidence_authority=_Authority(env, admission, span),
            classification_policy=_classification_policy(),
            analysis_delivery_authority=executor,
            conversation_evidence_authority=ConversationAuthority(tuple(r for r, _ in pairs)),
        )
        executor.backend = backend
        await backend.initialize()
        await backend.ingest_committed_evidence(env, admission)
    else:
        backend, env, admission, span, _authority = await _prepared(path)
    try:
        # Establish old initialized+ingested main; ALL following business writes
        # remain in WAL in --crash mode. Never use this main-only view as oracle.
        await backend.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        await backend.connection.execute("PRAGMA wal_autocheckpoint=0")
        init = backend.initialization_receipt
        plan = _plan(env, _operation(span))
        applied = await backend.apply_memory_mutation_plan(
            principal=_principal(), scope=m.MemoryScope.personal("actor-1"), plan=plan
        )
        assert applied.outcome is MemoryMutationApplyOutcome.COMMITTED
        view = await backend.get_memory_mutation_receipt_view(
            principal=_principal(), receipt_ref=applied.receipt_ref
        )
        memory_id = view.operations[0].memory_id
        assert memory_id
        context = _context(expires_at=1_000_100.0 if args.extended else 100.0)
        recall_plan = _recall_plan(context, idempotency_key="old-observed-recall")
        recall = await backend.execute_typed_recall(
            principal=_principal(), context=context, plan=recall_plan
        )
        assert any(item.source_ref == memory_id for item in recall.decision.selected_items)
        replay = await backend.execute_typed_recall(
            principal=_principal(), context=context, plan=recall_plan
        )
        assert replay.result == recall.result and replay.decision == recall.decision
        other, other_admission = _admitted(evidence_id="unaffected-user")
        other_receipt = await backend.ingest_committed_evidence(other, other_admission)
        extra = {}
        if args.extended:
            runner = m.DurableMemoryJobRunner(
                backend,
                executor,
                executor,
                TEST_WORKER_CONFIG,
                "old-fixture-worker",
                lambda: 1_000_000.0,
            )
            assert str(await runner.run_once()) == "applied"
            assert executor.provider_calls == 1
            for registration, ref in pairs:
                await backend.ingest_committed_evidence(
                    registration.envelope, registration.admission_receipt
                )
                await backend.register_conversation_evidence(ref)
            built = await backend.rebuild_short_horizon_projection(principal=_principal())
            assert built.projected_chunk_count == 1
            short = await backend.recall_short_horizon(
                principal=_principal(), query="Project alpha", disclosure_context=_disclosure()
            )
            assert len(short.hits) == 1 and short.hits[0].content == "user: Project alpha note 100"
            extra = {
                "short": {
                    "audit_id": short.audit_id,
                    "chunk_ref": short.hits[0].chunk_ref,
                    "content_hash": short.hits[0].content_hash,
                },
                "old_analysis_provider_calls": executor.provider_calls,
            }
        decisions = []
        for kind, target in (
            (m.SuppressionScopeKind.MEMORY, memory_id),
            (m.SuppressionScopeKind.EVIDENCE, "evidence-1"),
            (m.SuppressionScopeKind.ENTITY, "user:self"),
        ):
            decision = await backend.suppress(
                m.SuppressionRequest(
                    "old-forget-" + kind.value, "actor-1", kind, target, "user_forget", 20.0
                ),
                principal=_principal(),
            )
            assert isinstance(decision, SuppressionDecision)
            decisions.append(decision)
        if args.extended:
            temporary = await backend.suppress(
                m.SuppressionRequest(
                    "old-temporary",
                    "actor-1",
                    m.SuppressionScopeKind.EVIDENCE,
                    "evidence-101",
                    "user_forget",
                    20.0,
                ),
                principal=_principal(),
            )
            revoked = await backend.revoke_suppression(
                m.SuppressionRevokeRequest(
                    "old-revocation", "actor-1", temporary.directive_id, "user_restore", 21.0
                ),
                principal=_principal(),
            )
            decisions.extend((temporary, revoked))
        candidate = SuppressionCandidate("actor-1", memory_id=memory_id)
        resolution = await backend.resolve_suppression(candidate, OrdinaryMemoryPurpose.READ)
        assert resolution.denied
        assert (await backend.read_ingested_evidence(other.evidence_id)).envelope == other
        pending = await backend.read_outbox(principal=_principal(), states=("pending",))
        assert len(pending.entries) >= 2
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
            db.execute("BEGIN")
            state = rows_snapshot(db)
            physical = catalog(db)
        with sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True) as db:
            main_cognitive_count = db.execute(
                "SELECT COUNT(*) FROM cognitive_memory_heads"
            ).fetchone()[0]
        assert main_cognitive_count == 0
        assert len(state["cognitive_memory_heads"]["rows"]) == 1
        assert len(state["jobs"]["rows"]) >= 2
        output = {
            "version": m.__version__,
            "product_origin": str(Path(m.__file__).resolve()),
            "initialization": {**init.to_json(), "receipt_hash": init.receipt_hash},
            "memory_id": memory_id,
            "principal": {
                "deployment_id": _principal().deployment_id,
                "household_id": _principal().household_id,
                "actor_id": _principal().actor_id,
                "session_id": _principal().session_id,
            },
            "history_inputs": [
                {"envelope": item.to_json(), "receipt": receipt.to_json()}
                for item, receipt in ((env, admission), (other, other_admission))
            ],
            "apply_result": applied.to_json(),
            "recall": {
                "decision": recall.decision.to_json(),
                "result": recall.result.to_json(),
                "context": context.to_json(),
                "plan": recall_plan.to_json(),
            },
            "suppression": [{**x.to_json(), "decision_hash": x.decision_hash} for x in decisions],
            "other_receipt": other_receipt.to_json(),
            "main_only_cognitive_count": main_cognitive_count,
            "wal_visible_cognitive_count": 1,
            "old_columns_root": hashlib.sha256(canonical(state).encode()).hexdigest(),
            "catalog_hash": hashlib.sha256(canonical(physical).encode()).hexdigest(),
            **extra,
        }
        for name, value in (
            ("before.json", output),
            ("rows.json", state),
            ("catalog.json", physical),
        ):
            p = args.output / name
            with p.open("w") as f:
                f.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
                f.flush()
                os.fsync(f.fileno())
        if args.crash:
            os._exit(0)  # successful committed OLD fixture, deliberately no close/checkpoint
    finally:
        await backend.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("archived_source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--crash", action="store_true")
    parser.add_argument("--extended", action="store_true")
    asyncio.run(produce(parser.parse_args()))
