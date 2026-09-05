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
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(",", ":"))


def catalog(db):
    objects = [list(r) for r in db.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"
    )]
    tables = [r[1] for r in objects if r[0] == "table"]
    return {"objects": objects, "tables": {
        name: {pragma: [list(r) for r in db.execute(f'PRAGMA {pragma}("{name}")')]
               for pragma in ("table_xinfo", "index_list", "foreign_key_list")}
        for name in tables}}


def rows_snapshot(db):
    names = sorted(r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ))
    def encode(value):
        return {"blob_hex": value.hex()} if isinstance(value, bytes) else value
    return {name: {
        "columns": [r[1] for r in db.execute(f'PRAGMA table_info("{name}")')],
        "rows": sorted(([encode(v) for v in r] for r in db.execute(f'SELECT * FROM "{name}"')),
                       key=canonical),
    } for name in names}


async def produce(args):
    sys.path.insert(0, str(args.archived_source.resolve()))  # tests only; no src path
    import simple_harness_memory as m
    from simple_harness.runtime import MemoryMutationApplyOutcome
    from simple_harness_memory.core.suppression import (
        OrdinaryMemoryPurpose, SuppressionCandidate, SuppressionDecision,
    )
    from tests.integration.test_cognitive_mutation_repository_v5 import (
        _admitted, _operation, _plan, _prepared, _principal,
    )
    from tests.integration.test_typed_recall_v6 import _context, _recall_plan

    assert Path(m.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
    args.output.mkdir(parents=True, exist_ok=False)
    path = (args.output / "old.db").resolve()
    backend, env, admission, span, _authority = await _prepared(path)
    try:
        # Establish old initialized+ingested main; ALL following business writes
        # remain in WAL in --crash mode. Never use this main-only view as oracle.
        await backend.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        await backend.connection.execute("PRAGMA wal_autocheckpoint=0")
        init = backend.initialization_receipt
        plan = _plan(env, _operation(span))
        applied = await backend.apply_memory_mutation_plan(
            principal=_principal(), scope=m.MemoryScope.personal("actor-1"), plan=plan)
        assert applied.outcome is MemoryMutationApplyOutcome.COMMITTED
        view = await backend.get_memory_mutation_receipt_view(
            principal=_principal(), receipt_ref=applied.receipt_ref)
        memory_id = view.operations[0].memory_id
        assert memory_id
        context = _context()
        recall_plan = _recall_plan(context, idempotency_key="old-observed-recall")
        recall = await backend.execute_typed_recall(
            principal=_principal(), context=context, plan=recall_plan)
        assert any(item.source_ref == memory_id for item in recall.decision.selected_items)
        replay = await backend.execute_typed_recall(
            principal=_principal(), context=context, plan=recall_plan)
        assert replay.result == recall.result and replay.decision == recall.decision
        other, other_admission = _admitted(evidence_id="unaffected-user")
        other_receipt = await backend.ingest_committed_evidence(other, other_admission)
        decisions = []
        for kind, target in ((m.SuppressionScopeKind.MEMORY, memory_id),
                             (m.SuppressionScopeKind.EVIDENCE, "evidence-1"),
                             (m.SuppressionScopeKind.ENTITY, "user:self")):
            decision = await backend.suppress(m.SuppressionRequest(
                "old-forget-" + kind.value, "actor-1", kind, target, "user_forget", 20.0),
                principal=_principal())
            assert isinstance(decision, SuppressionDecision)
            decisions.append(decision)
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
            main_cognitive_count = db.execute("SELECT COUNT(*) FROM cognitive_memory_heads").fetchone()[0]
        assert main_cognitive_count == 0
        assert len(state["cognitive_memory_heads"]["rows"]) == 1
        assert len(state["jobs"]["rows"]) >= 2
        output = {
            "version": m.__version__, "product_origin": str(Path(m.__file__).resolve()),
            "initialization": {**init.to_json(), "receipt_hash": init.receipt_hash},
            "memory_id": memory_id, "apply_result": applied.to_json(),
            "recall": {"decision": recall.decision.to_json(), "result": recall.result.to_json()},
            "suppression": [{**x.to_json(), "decision_hash": x.decision_hash} for x in decisions],
            "other_receipt": other_receipt.to_json(), "main_only_cognitive_count": main_cognitive_count,
            "wal_visible_cognitive_count": 1,
            "old_columns_root": hashlib.sha256(canonical(state).encode()).hexdigest(),
            "catalog_hash": hashlib.sha256(canonical(physical).encode()).hexdigest(),
        }
        for name, value in (("before.json", output), ("rows.json", state), ("catalog.json", physical)):
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
    asyncio.run(produce(parser.parse_args()))
