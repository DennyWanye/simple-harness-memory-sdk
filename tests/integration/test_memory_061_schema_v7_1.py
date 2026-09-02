"""schema v7 → v7.1：0.6.0 已写 DB 打开时前向加列（0.6.1）。"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from pathlib import Path

import pytest

from simple_harness_memory.backends.schema_v5 import (
    DDL,
    DDL_V7_0,
    SCHEMA_CHECKSUM,
    SCHEMA_CHECKSUM_V7_0,
    SCHEMA_EPOCH,
    SCHEMA_MINOR_VERSION,
    SCHEMA_VERSION,
    SCHEMA_VERSION_LABEL,
    V7_1_ADDED_COLUMNS,
    ddl_statements,
)
from simple_harness_memory.backends.sqlite_v5 import SQLiteHumanMemoryBackend
from simple_harness_memory.core.errors import MemoryLegacySchemaUnsupported
from tests.integration.test_memory_061_core import LINEAGE_A, _evidence


def _legacy_receipt_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_v7_0_database(path: Path) -> dict[str, object]:
    """用 0.6.0 的真实 DDL（无新列）建库并写入其 receipt/meta。"""

    hmac_key = secrets.token_bytes(32)
    receipt = {
        "receipt_id": "init-v7-0",
        "schema_version": SCHEMA_VERSION,
        "schema_epoch": SCHEMA_EPOCH,
        "schema_checksum": SCHEMA_CHECKSUM_V7_0,
        "audit_cursor_authority_hash": hashlib.sha256(hmac_key).hexdigest(),
        "created_at": 12.5,
    }
    receipt_hash = _legacy_receipt_hash(receipt)
    connection = sqlite3.connect(path, isolation_level=None)
    try:
        connection.execute("BEGIN IMMEDIATE")
        for statement in ddl_statements(DDL_V7_0):
            connection.execute(statement)
        connection.execute(
            "INSERT INTO audit_cursor_authority(singleton,hmac_key_hex) VALUES(1,?)",
            (hmac_key.hex(),),
        )
        connection.execute(
            "INSERT INTO initialization_receipts(singleton,receipt_id,schema_version,"
            "schema_epoch,schema_checksum,audit_cursor_authority_hash,created_at,receipt_hash) "
            "VALUES(1,?,?,?,?,?,?,?)",
            (
                receipt["receipt_id"],
                receipt["schema_version"],
                receipt["schema_epoch"],
                receipt["schema_checksum"],
                receipt["audit_cursor_authority_hash"],
                receipt["created_at"],
                receipt_hash,
            ),
        )
        connection.executemany(
            "INSERT INTO schema_meta(key,value) VALUES(?,?)",
            (
                ("schema_version", str(SCHEMA_VERSION)),
                ("schema_epoch", SCHEMA_EPOCH),
                ("schema_checksum", SCHEMA_CHECKSUM_V7_0),
                ("initialization_receipt_id", str(receipt["receipt_id"])),
                ("initialization_receipt_hash", receipt_hash),
            ),
        )
        connection.execute("COMMIT")
    finally:
        connection.close()
    return {**receipt, "receipt_hash": receipt_hash}


def _columns(path: Path, table: str) -> list[str]:
    connection = sqlite3.connect(path)
    try:
        return [str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")]
    finally:
        connection.close()


def test_schema_v7_1_constants_and_v7_0_ddl_are_pinned() -> None:
    assert (SCHEMA_VERSION, SCHEMA_MINOR_VERSION, SCHEMA_VERSION_LABEL) == (7, 1, "7.1")
    assert hashlib.sha256(DDL.encode("utf-8")).hexdigest() == SCHEMA_CHECKSUM
    assert hashlib.sha256(DDL_V7_0.encode("utf-8")).hexdigest() == SCHEMA_CHECKSUM_V7_0
    assert SCHEMA_CHECKSUM != SCHEMA_CHECKSUM_V7_0
    assert V7_1_ADDED_COLUMNS == (("evidence_envelopes", "analysis_lineage_json", "BLOB"),)
    assert "analysis_lineage_json" in DDL and "analysis_lineage_json" not in DDL_V7_0


@pytest.mark.asyncio
async def test_v7_0_database_is_forward_migrated_on_open(tmp_path: Path) -> None:
    path = tmp_path / "v7-0.db"
    legacy = _write_v7_0_database(path)
    assert "analysis_lineage_json" not in _columns(path, "evidence_envelopes")

    backend = SQLiteHumanMemoryBackend(path, now=lambda: 20.0)
    receipt = await backend.initialize()
    try:
        # 规则：迁移后按新 checksum 校验；receipt_id/created_at/cursor authority 不变，hash 重算。
        assert receipt.schema_checksum == SCHEMA_CHECKSUM
        assert receipt.schema_version == SCHEMA_VERSION
        assert receipt.receipt_id == legacy["receipt_id"]
        assert receipt.created_at == legacy["created_at"]
        assert receipt.audit_cursor_authority_hash == legacy["audit_cursor_authority_hash"]
        assert receipt.receipt_hash != legacy["receipt_hash"]
        async with backend.connection.execute("SELECT key,value FROM schema_meta") as cursor:
            meta = {str(row[0]): str(row[1]) for row in await cursor.fetchall()}
        assert meta["schema_checksum"] == SCHEMA_CHECKSUM
        assert meta["initialization_receipt_hash"] == receipt.receipt_hash
        assert meta["schema_version"] == "7"
        async with backend.connection.execute(
            "SELECT schema_checksum,receipt_hash FROM initialization_receipts"
        ) as cursor:
            stored = await cursor.fetchone()
        assert stored is not None and tuple(stored) == (SCHEMA_CHECKSUM, receipt.receipt_hash)
        # 迁移后的库可按 0.6.1 口径 ingest（含 lineage）。
        ingestion = await backend.ingest_committed_evidence(
            *_evidence(1), analysis_lineage=LINEAGE_A
        )
        assert ingestion.evidence_id == "evidence-1"
    finally:
        await backend.close()
    assert _columns(path, "evidence_envelopes")[-1] == "analysis_lineage_json"

    # 第二次打开：已是 v7.1，不再迁移，receipt 稳定。
    reopened = SQLiteHumanMemoryBackend(path, now=lambda: 30.0)
    second = await reopened.initialize()
    try:
        assert second == receipt
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_fresh_v7_1_and_migrated_v7_0_share_column_layout(tmp_path: Path) -> None:
    fresh_path = tmp_path / "fresh.db"
    fresh = SQLiteHumanMemoryBackend(fresh_path, now=lambda: 20.0)
    await fresh.initialize()
    await fresh.close()
    migrated_path = tmp_path / "migrated.db"
    _write_v7_0_database(migrated_path)
    migrated = SQLiteHumanMemoryBackend(migrated_path, now=lambda: 20.0)
    await migrated.initialize()
    await migrated.close()
    assert _columns(fresh_path, "evidence_envelopes") == _columns(
        migrated_path, "evidence_envelopes"
    )


@pytest.mark.asyncio
async def test_unknown_checksum_still_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "unknown.db"
    _write_v7_0_database(path)
    connection = sqlite3.connect(path, isolation_level=None)
    try:
        connection.execute("UPDATE schema_meta SET value='tampered' WHERE key='schema_checksum'")
    finally:
        connection.close()
    backend = SQLiteHumanMemoryBackend(path, now=lambda: 20.0)
    with pytest.raises(MemoryLegacySchemaUnsupported):
        await backend.initialize()
