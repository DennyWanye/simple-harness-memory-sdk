"""Real old-wheel inputs, not current empty roots with rewritten metadata.

Run scripts/schema_upgrade_old_fixture.py first in each pinned OLD environment;
the ignored fixtures are intentionally not shipped as product-generated oracle.
"""

import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

import simple_harness_memory as m
from simple_harness_memory.core.errors import (
    MemoryCorruptionError,
    MemoryLegacySchemaUnsupported,
    MemoryWriterConflict,
)
from simple_harness_memory.migrations import migrate_human_memory_v7_to_v7_2
from tests.integration.test_cognitive_mutation_repository_v5 import _classification_policy

EVIDENCE = Path(__file__).parents[2] / ".local-test-evidence/2026-09-05/069-existing-data"
OLD = {
    "060": EVIDENCE / "nonempty-060-r1/old.db",
    "063": EVIDENCE / "nonempty-063-r4/old.db",
    "067": EVIDENCE / "nonempty-067-r1/old.db",
    "alter071": EVIDENCE / "official-alter-071.db",
}


@pytest.mark.parametrize("entry", ["builder", "migration"])
async def test_temporary_read_lock_is_writer_conflict_not_legacy(tmp_path, entry):
    """A real exclusive writer is not evidence of an unsupported schema."""
    path, backup = tmp_path / "memory.db", tmp_path / "backup.db"
    manager = await m.build_human_memory_v7(path)
    await manager.close()
    writer = sqlite3.connect(path, isolation_level=None)
    writer.execute("PRAGMA journal_mode=DELETE")
    before = path.read_bytes()
    writer.execute("BEGIN EXCLUSIVE")
    try:
        with pytest.raises(MemoryWriterConflict) as caught:
            if entry == "builder":
                await m.build_human_memory_v7(path)
            else:
                await migrate_human_memory_v7_to_v7_2(path, backup_path=backup)
        assert caught.value.code == "memory_second_writer_rejected"
        assert caught.value.__cause__.sqlite_errorcode == sqlite3.SQLITE_BUSY
        assert not backup.exists()
        assert path.read_bytes() == before
    finally:
        writer.execute("ROLLBACK")
        writer.close()
    manager = await m.build_human_memory_v7(path)
    await manager.close()
    assert await migrate_human_memory_v7_to_v7_2(path, backup_path=backup) is None
    assert not backup.exists()


def _copy(source, dest):
    assert source.is_file(), "Generate the exact old-wheel fixture first"
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as reader:
        with sqlite3.connect(dest) as target:
            reader.backup(target)


def _rows(path):
    from scripts.schema_upgrade_old_fixture import rows_snapshot

    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        return rows_snapshot(db)


@pytest.mark.parametrize("version", OLD)
async def test_real_nonempty_old_root_preserved_and_public_reopened(tmp_path, version):
    path, backup = tmp_path / "memory.db", tmp_path / "backup.db"
    _copy(OLD[version], path)
    before = _rows(path)
    assert len(before["cognitive_memory_heads"]["rows"]) == 1
    assert len(before["jobs"]["rows"]) == 2
    assert len(before["suppression_directives"]["rows"]) == 3
    old_init = before["initialization_receipts"]
    receipt = await migrate_human_memory_v7_to_v7_2(path, backup_path=backup)
    assert _rows(backup) == before
    after = _rows(path)
    assert after["initialization_receipts"] == old_init
    for table, body in before.items():
        names = body["columns"]
        projected = [
            [row[after[table]["columns"].index(c)] for c in names] for row in after[table]["rows"]
        ]
        if table == "schema_meta":
            projected = [row for row in projected if row[0] != "source_admission_upgrade_v1"]
        assert sorted(projected, key=str) == sorted(body["rows"], key=str), table
    assert receipt.backup_sha256 == hashlib.sha256(backup.read_bytes()).hexdigest()
    manager = await m.build_human_memory_v7(path, classification_policy=_classification_policy())
    try:
        init = manager.backend.initialization_receipt
        assert init.receipt_hash == receipt.original_initialization_receipt_hash
        from tests.integration.test_cognitive_mutation_repository_v5 import (
            _admitted,
            _disclosure,
            _principal,
        )

        env, admission = _admitted()
        env2, admission2 = _admitted(evidence_id="unaffected-user")
        visible = await manager.check_history_visibility(
            principal=_principal(),
            disclosure_context=_disclosure(),
            bindings=(
                m.HistoryEvidenceBinding(env, admission),
                m.HistoryEvidenceBinding(env2, admission2),
            ),
        )
        assert [item.visible for item in visible.items] == [False, True]
        pending = await manager.read_outbox(principal=_principal())
        assert len(pending.entries) >= 2
    finally:
        await manager.close()
    backup.rename(tmp_path / "moved-backup.db")
    replay = await migrate_human_memory_v7_to_v7_2(path, backup_path=backup)
    assert replay == receipt and not backup.exists()


def _bytes(path):
    return {
        suffix: p.read_bytes()
        for suffix in ("", "-wal")
        if (p := path.with_name(path.name + suffix)).exists()
    }


def _assert_same_committed_bytes(before, after):
    # SQLite mode=ro may create an empty WAL beside a WAL-mode database with no
    # sidecar. Never ignore an existing WAL byte or any newly introduced frame.
    assert after[""] == before[""]
    if "-wal" in before:
        assert after.get("-wal") == before["-wal"]
    else:
        assert after.get("-wal", b"") == b""


@pytest.mark.parametrize("point", ["after_backup", "after_ddl", "before_commit", "after_commit"])
async def test_real_process_death_boundary_and_exact_backup_retry(tmp_path, point):
    path, backup = tmp_path / "memory.db", tmp_path / "backup.db"
    _copy(OLD["063"], path)
    before = _rows(path)
    command = """
import asyncio,os,sys
from simple_harness_memory.migrations import schema_upgrade as u
def fault(point):
    if point == sys.argv[3]: os._exit(72)
u._fault = fault
asyncio.run(u.migrate_human_memory_v7_to_v7_2(sys.argv[1],backup_path=sys.argv[2]))
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", command, str(path), str(backup), point],
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 72, result.stderr.decode()
    assert backup.is_file() and _rows(backup) == before
    backup_bytes = backup.read_bytes()
    with sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True) as main:
        # COMMIT wasn't checkpointed: even the successful upgrade still has old main DDL.
        assert (
            main.execute(
                "SELECT 1 FROM sqlite_master WHERE name='source_admission_receipts'"
            ).fetchone()
            is None
        )
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as snapshot:
        marker = snapshot.execute(
            "SELECT value FROM schema_meta WHERE key='source_admission_upgrade_v1'"
        ).fetchone()
    if point == "after_commit":
        assert marker is not None
        first = json.loads(marker[0])
        # Open before migration replay. Marker+DDL only in committed WAL must suffice.
        manager = await m.build_human_memory_v7(
            path, classification_policy=_classification_policy()
        )
        await manager.close()
    else:
        assert marker is None and _rows(path) == before
        # Independent old installed wheel still opens the precommit root.
        old = EVIDENCE / "venv-063/bin/python"
        check = subprocess.run(
            [
                str(old),
                "-I",
                "-c",
                """
import asyncio,sys
from simple_harness_memory.backends.sqlite_v5 import SQLiteHumanMemoryBackend
async def main():
 b=SQLiteHumanMemoryBackend(sys.argv[1])
 try: await b.initialize()
 finally: await b.close()
asyncio.run(main())
""",
                str(path),
            ],
            capture_output=True,
            timeout=30,
        )
        assert check.returncode == 0, check.stderr.decode()
    receipt = await migrate_human_memory_v7_to_v7_2(path, backup_path=backup)
    assert backup.read_bytes() == backup_bytes
    if point == "after_commit":
        assert {**receipt.to_json(), "receipt_hash": receipt.receipt_hash} == first


@pytest.mark.parametrize("shm", ["present", "missing", "stale"])
async def test_committed_old_wal_is_preserved_without_checkpoint_or_shm_authority(tmp_path, shm):
    import shutil

    source = OLD["067"]
    path, backup = tmp_path / "memory.db", tmp_path / "backup.db"
    # Copy the closed-by-process-death triplet exactly: these are test fixture files.
    # Unlike SQLite backup, this deliberately retains the stale MAIN and real WAL.
    for suffix in ("", "-wal", "-shm"):
        p = source.with_name(source.name + suffix)
        if p.exists():
            shutil.copyfile(p, path.with_name(path.name + suffix))
    side = path.with_name(path.name + "-shm")
    if shm == "missing":
        side.unlink(missing_ok=True)
    elif shm == "stale":
        side.write_bytes(b"\0" * 32768)
    with sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True) as db:
        assert db.execute("SELECT COUNT(*) FROM cognitive_memory_heads").fetchone()[0] == 0
    expected = json.loads((source.parent / "rows.json").read_text())
    receipt = await migrate_human_memory_v7_to_v7_2(path, backup_path=backup)
    assert _rows(backup) == expected
    assert (
        receipt.preserved_old_columns_root_hash
        == json.loads((source.parent / "before.json").read_text())["old_columns_root"]
    )


@pytest.mark.parametrize("bad", ["partial-backup", "different-backup", "changed-state"])
async def test_leftover_backup_conflict_never_overwrites_source_or_backup(tmp_path, bad):
    path, backup = tmp_path / "memory.db", tmp_path / "backup.db"
    _copy(OLD["063"], path)
    if bad == "partial-backup":
        backup.write_bytes(b"partial")
    elif bad == "different-backup":
        _copy(OLD["067"], backup)
    else:
        _copy(path, backup)
        # Real subsequent old public work changes business state, same init identity.
        code = """
import asyncio,sys
from pathlib import Path
sys.path.insert(0,sys.argv[2])
from tests.integration.test_cognitive_mutation_repository_v5 import _admitted
from simple_harness_memory.backends.sqlite_v5 import SQLiteHumanMemoryBackend
async def main():
 b=SQLiteHumanMemoryBackend(sys.argv[1])
 try:
  await b.initialize()
  await b.ingest_committed_evidence(*_admitted(evidence_id='intervening-user'))
 finally: await b.close()
asyncio.run(main())
"""
        result = subprocess.run(
            [
                str(EVIDENCE / "venv-063/bin/python"),
                "-I",
                "-c",
                code,
                str(path),
                str(EVIDENCE / "source-063"),
            ],
            capture_output=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr.decode()
    a, b = _bytes(path), _bytes(backup)
    with pytest.raises(m.MemoryIdempotencyConflict, match="schema_upgrade_backup_conflict"):
        await migrate_human_memory_v7_to_v7_2(path, backup_path=backup)
    _assert_same_committed_bytes(a, _bytes(path))
    _assert_same_committed_bytes(b, _bytes(backup))


@pytest.mark.parametrize(
    "bad",
    [
        "extra-table",
        "wrong-trigger",
        "unknown-checksum",
        "corrupt-payload",
        "wrong-cursor",
        "future-marker",
    ],
)
async def test_invalid_old_roots_reject_before_backup_and_preserve_bytes(tmp_path, bad):
    path, backup = tmp_path / "memory.db", tmp_path / "backup.db"
    _copy(OLD["063"], path)
    with sqlite3.connect(path) as db:
        if bad == "extra-table":
            db.execute("CREATE TABLE user_extra(a)")
        elif bad == "wrong-trigger":
            db.execute("DROP TRIGGER suppression_directives_immutable_delete")
        elif bad == "unknown-checksum":
            db.execute("UPDATE schema_meta SET value=? WHERE key='schema_checksum'", ("f" * 64,))
        elif bad == "corrupt-payload":
            db.execute("UPDATE jobs SET payload='{}'")
        elif bad == "wrong-cursor":
            triggers = db.execute(
                "SELECT name,sql FROM sqlite_master WHERE type='trigger' "
                "AND tbl_name='audit_cursor_authority'"
            ).fetchall()
            for name, _ in triggers:
                db.execute(f'DROP TRIGGER "{name}"')
            db.execute("UPDATE audit_cursor_authority SET hmac_key_hex=?", ("00" * 32,))
            for _, sql in triggers:
                db.execute(sql)
        else:
            db.execute("INSERT INTO schema_meta VALUES('source_admission_upgrade_v2','{}')")
    before = _bytes(path)
    with pytest.raises((MemoryLegacySchemaUnsupported, MemoryCorruptionError, ValueError)):
        await migrate_human_memory_v7_to_v7_2(path, backup_path=backup)
    assert _bytes(path) == before and not backup.exists()


async def test_valid_current_schema_noop_and_missing_path_builder_boundary(tmp_path):
    path, backup = tmp_path / "memory.db", tmp_path / "backup.db"
    with pytest.raises(m.MemoryValidationError, match="schema_upgrade_paths_invalid"):
        await migrate_human_memory_v7_to_v7_2(path, backup_path=backup)
    assert not path.exists() and not backup.exists()
    manager = await m.build_human_memory_v7(path)
    init = manager.backend.initialization_receipt
    await manager.close()
    before = _rows(path)
    assert await migrate_human_memory_v7_to_v7_2(path, backup_path=backup) is None
    assert _rows(path) == before and not backup.exists()
    reopened = await m.build_human_memory_v7(path)
    assert reopened.backend.initialization_receipt == init
    await reopened.close()


async def test_historical_host_policy_reconstruction_does_not_change_runtime_admission(tmp_path):
    from dataclasses import replace

    from tests.integration.test_cognitive_mutation_repository_v5 import _admitted

    path = tmp_path / "custom-policy.db"
    policy = "host-approved-filter/v9"
    env, receipt = _admitted()
    env = replace(env, filter_policy_version=policy)
    receipt = replace(receipt, filter_policy_version=policy, envelope_hash=env.envelope_hash)
    kwargs = dict(supported_filter_policies=frozenset({policy}))
    manager = await m.build_human_memory_v7(path, **kwargs)
    await manager.ingest_committed_evidence(env, receipt)
    await manager.close()
    assert (
        await migrate_human_memory_v7_to_v7_2(path, backup_path=tmp_path / "unused.backup") is None
    )
    manager = await m.build_human_memory_v7(path, **kwargs)
    try:
        replay = await manager.ingest_committed_evidence(env, receipt)
        assert replay.evidence_id == env.evidence_id
        # Existing recorded policies were used ONLY in the discarded validation
        # clone; they cannot admit a new arbitrary policy into the real backend.
        other, other_receipt = _admitted(evidence_id="new-unsupported")
        with pytest.raises(m.MemoryValidationError, match="evidence_filter_policy_unsupported"):
            await manager.ingest_committed_evidence(other, other_receipt)
    finally:
        await manager.close()


async def test_extended_old_state_new_source_jobs_and_selected_sources_survive_reopen(tmp_path):
    """W4: historical root is NOT a perpetual seal on legitimate business writes."""
    from dataclasses import replace

    from simple_harness.runtime import SemanticMemoryPayload

    from scripts.source_only_public_consumer import _registration as assistant_source
    from tests.integration.test_cognitive_mutation_repository_v5 import (
        _admitted,
        _Authority,
        _disclosure,
        _operation,
        _plan,
        _principal,
        _span,
    )
    from tests.integration.test_durable_memory_jobs_v5 import TEST_WORKER_CONFIG, _Executor
    from tests.integration.test_short_horizon_repository_v5 import NOW

    path, backup = tmp_path / "memory.db", tmp_path / "backup.db"
    extended = EVIDENCE / "extended-067-r1"
    _copy(extended / "old.db", path)
    old = _rows(path)
    assert len(old["analysis_batches"]["rows"]) == 1
    assert len(old["accepted_analysis_plans"]["rows"]) == 1
    assert len(old["conversation_evidence_registrations"]["rows"]) == 11
    assert len(old["short_horizon_chunks"]["rows"]) == 1
    first = await migrate_human_memory_v7_to_v7_2(path, backup_path=backup)
    assert _rows(backup) == old
    binding = m.HistoryShortHorizonBinding(
        **json.loads((extended / "before.json").read_text())["short"]
    )
    env, admission = _admitted(evidence_id="post-upgrade-user")
    span = _span(env, admission)
    authority = _Authority(env, admission, span)
    executor = _Executor(None, no_mutation=True)
    kwargs = dict(
        clock=lambda: NOW + 20,
        classification_policy=_classification_policy(),
        evidence_authority=authority,
        analysis_delivery_authority=executor,
    )
    manager = await m.build_human_memory_v7(path, **kwargs)
    executor.backend = manager.backend
    try:
        sources = await manager.resolve_short_horizon_sources(
            principal=_principal(), disclosure_context=_disclosure(), bindings=(binding,)
        )
        assert sources.items[0].visible
        assert [ref.evidence_id for ref in sources.items[0].source_refs] == ["evidence-100"]
        reg, _ = assistant_source(2000)
        source_receipt = await manager.admit_evidence_source(
            principal=_principal(), envelope=reg.envelope, receipt=reg.admission_receipt
        )
        assert type(source_receipt) is m.EvidenceSourceAdmissionReceipt
        await manager.ingest_committed_evidence(env, admission)
        operation = replace(
            _operation(span),
            payload=SemanticMemoryPayload(
                "project:later", "response_style", "concise", ("default",)
            ),
        )
        applied = await manager.apply_memory_mutation_plan(
            principal=_principal(),
            scope=m.MemoryScope.personal("actor-1"),
            plan=_plan(
                env, operation, base_revision=2, plan_id="later-plan", idempotency_key="later-plan"
            ),
        )
        assert applied.outcome.value == "committed"
        runner = m.DurableMemoryJobRunner(
            manager.backend,
            executor,
            executor,
            TEST_WORKER_CONFIG,
            "successor-worker",
            lambda: NOW + 20,
        )
        outcomes = [str(await runner.run_once()) for _ in range(7)]
        assert outcomes == ["applied"] * 6 + ["idle"]
        assert executor.provider_calls == 6  # old applied pair was not analyzed again
        await manager.suppress(
            principal=_principal(),
            request=m.SuppressionRequest(
                "forget-selected-after-upgrade",
                "actor-1",
                m.SuppressionScopeKind.EVIDENCE,
                "evidence-100",
                "user_forget",
                NOW + 20,
            ),
        )
        denied = await manager.resolve_short_horizon_sources(
            principal=_principal(), disclosure_context=_disclosure(), bindings=(binding,)
        )
        assert not denied.items[0].visible and denied.items[0].source_refs == ()
    finally:
        await manager.close()
    changed = _rows(path)
    assert len(changed["source_admission_receipts"]["rows"]) == 1
    assert len(changed["jobs"]["rows"]) == len(old["jobs"]["rows"]) + 1  # USER only
    assert len(changed["cognitive_memory_heads"]["rows"]) == 2
    assert changed["initialization_receipts"] == old["initialization_receipts"]
    assert await migrate_human_memory_v7_to_v7_2(path, backup_path=backup) == first
    manager = await m.build_human_memory_v7(path, **kwargs)
    executor.backend = manager.backend
    try:
        assert (
            await manager.admit_evidence_source(
                principal=_principal(), envelope=reg.envelope, receipt=reg.admission_receipt
            )
            == source_receipt
        )
        assert (
            str(
                await m.DurableMemoryJobRunner(
                    manager.backend,
                    executor,
                    executor,
                    TEST_WORKER_CONFIG,
                    "reopened",
                    lambda: NOW + 20,
                ).run_once()
            )
            == "idle"
        )
        assert (
            not (
                await manager.resolve_short_horizon_sources(
                    principal=_principal(), disclosure_context=_disclosure(), bindings=(binding,)
                )
            )
            .items[0]
            .visible
        )
    finally:
        await manager.close()
    assert _rows(backup) == old
