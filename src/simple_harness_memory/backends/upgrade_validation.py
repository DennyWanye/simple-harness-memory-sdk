"""Read-only canonical validation of a pinned schema-upgrade snapshot."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

import aiosqlite
from simple_harness.contracts import canonical_json

from simple_harness_memory.core.errors import MemoryCorruptionError


async def validate_snapshot(source: sqlite3.Connection, root: Any) -> None:
    from simple_harness_memory.backends.schema_v5 import SCHEMA_CHECKSUM
    from simple_harness_memory.backends.schema_v7_3 import SCHEMA_CHECKSUM as checksum_v7_3
    from simple_harness_memory.backends.schema_v7_4 import (
        COGNITIVE_VECTOR_DDL,
        SCHEMA_CHECKSUM as checksum_v7_4,
        ddl_statements as ddl_statements_v7_4,
    )
    from simple_harness_memory.backends.sqlite_v5 import SQLiteHumanMemoryBackend
    from simple_harness_memory.migrations.schema_upgrade import _columns, _ddl, _old_root

    clone = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
    try:
        columns = _columns(source)
        before = _old_root(source, columns)
        source.backup(clone)
        if root.marker is None and root.initialization.schema_checksum not in {
            SCHEMA_CHECKSUM, checksum_v7_3, checksum_v7_4,
        }:
            for statement in _ddl(root.catalog_id):
                clone.execute(statement)
        if getattr(root, "forwardable", False):
            # A 7.3 root is validated exactly as the open path will see it: the 7.4
            # additive tables are appended to the clone only (never to the source).
            for statement in ddl_statements_v7_4(COGNITIVE_VECTOR_DDL):
                clone.execute(statement)
        if _old_root(clone, columns) != before:
            raise MemoryCorruptionError("schema validation snapshot differs")
        clone.execute("PRAGMA query_only=ON")
        clone.execute("BEGIN")
        db = await aiosqlite.Connection(lambda: clone, iter_chunk_size=64)
        db.row_factory = aiosqlite.Row
        # Historical canonical reconstruction is not a new admission decision.
        # A Host may have admitted these records with its own configured policy
        # versions. Verify each immutable envelope/receipt agrees on its recorded
        # policy, without inventing a runtime allowlist or requiring Host callbacks
        # during an offline migration. The actual opened backend retains only the
        # caller's configured policies; no values from this clone escape to it.
        policies = frozenset(
            str(row[0])
            for row in clone.execute(
                "SELECT DISTINCT filter_policy_version FROM evidence_envelopes"
            )
        )
        backend = SQLiteHumanMemoryBackend(
            "validation-only-never-opened",
            **({"supported_filter_policies": policies} if policies else {}),
        )
        backend._db = db
        backend._receipt = root.initialization
        try:
            await validate_backend(backend)
        finally:
            await db.close()
    finally:
        clone.close()


async def validate_backend(backend: Any) -> None:
    from simple_harness_memory.backends.sqlite_v5 import _suppression_decision_from_row

    db = backend.connection
    await backend._validate_integrity()
    async with db.execute("SELECT evidence_id FROM evidence_envelopes") as cursor:
        evidence = await cursor.fetchall()
    for row in evidence:
        if await backend._read_ingested_record(str(row[0])) is None:
            raise MemoryCorruptionError("schema evidence receipt missing")
    async with db.execute("SELECT * FROM suppression_directives") as cursor:
        directives = await cursor.fetchall()
    for row in directives:
        decision = _suppression_decision_from_row(row)
        async with db.execute(
            "SELECT ordinal,target_kind,target_ref FROM suppression_targets WHERE directive_id=?",
            (decision.directive_id,),
        ) as cursor:
            targets = [tuple(item) for item in await cursor.fetchall()]
        if targets != [(1, decision.scope_kind.value, decision.scope_ref)]:
            raise MemoryCorruptionError("schema suppression target binding differs")
    async with db.execute("SELECT invocation_id FROM llm_invocations") as cursor:
        invocations = await cursor.fetchall()
    for row in invocations:
        await backend._read_invocation(str(row[0]))
        await backend._read_decisions(str(row[0]))
    async with db.execute("SELECT * FROM job_attempt_events") as cursor:
        events = await cursor.fetchall()
    for row in events:
        payload = {
            "schema_version": 1,
            **{key: row[key] for key in row.keys() if key != "event_hash"},
        }
        if hashlib.sha256(canonical_json(payload).encode()).hexdigest() != row["event_hash"]:
            raise MemoryCorruptionError("schema job event hash differs")
    async with db.execute("SELECT * FROM memory_mutation_receipts") as cursor:
        mutations = await cursor.fetchall()
    for row in mutations:
        await backend._decode_and_verify_mutation_receipt_row_unlocked(row)
    async with db.execute(
        "SELECT b.batch_id,a.lease_token,j.lease_expires_at FROM analysis_batches b "
        "LEFT JOIN analysis_batch_members m ON m.batch_id=b.batch_id AND m.ordinal=1 "
        "LEFT JOIN job_attempts a ON a.job_id=m.job_id AND a.attempt=m.job_attempt "
        "LEFT JOIN jobs j ON j.job_id=m.job_id"
    ) as cursor:
        batches = await cursor.fetchall()
    for row in batches:
        if row["lease_token"] is None:
            raise MemoryCorruptionError("schema analysis attempt missing")
        # This is a read reconstruction, not issuing a lease or admitting work.
        await backend._read_analysis_claim_unlocked(
            str(row["batch_id"]), str(row["lease_token"]), float(row["lease_expires_at"] or 0)
        )
    async with db.execute("SELECT * FROM jobs") as cursor:
        jobs = await cursor.fetchall()
    for row in jobs:
        payload = json.loads(row["payload"])
        record = await backend._read_ingested_record(str(row["evidence_watermark"]))
        if (
            record is None
            or payload
            != {
                "schema_version": 1,
                "evidence_id": record.envelope.evidence_id,
                "envelope_hash": record.envelope.envelope_hash,
                "source_hash": record.envelope.source_hash,
            }
            or row["principal_id"] != record.envelope.subject
        ):
            raise MemoryCorruptionError("schema analysis job evidence lineage differs")
    for table, payload_column, digest_column in (
        ("jobs", "payload", "payload_hash"),
        ("outbox", "payload", "payload_hash"),
        ("cognitive_memory_revisions", "content_json", "content_hash"),
    ):
        async with db.execute(
            f'SELECT "{payload_column}","{digest_column}" FROM "{table}"'
        ) as cursor:
            rows = await cursor.fetchall()
        for payload, digest in rows:
            text = payload.decode("utf-8") if isinstance(payload, bytes) else str(payload)
            if (
                canonical_json(json.loads(text)) != text
                or hashlib.sha256(text.encode()).hexdigest() != digest
            ):
                raise MemoryCorruptionError("schema canonical payload hash differs")
