"""0.6.2 cutover：无 DDL 变化，schema 保持 v7.1；0.6.0 / 0.6.1 已写 DB 打开即用（S5b Task 5）。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from simple_harness_memory import __version__
from simple_harness_memory.backends.schema_v5 import (
    SCHEMA_CHECKSUM,
    SCHEMA_CHECKSUM_V7_0,
    SCHEMA_MINOR_VERSION,
    SCHEMA_VERSION,
    SCHEMA_VERSION_LABEL,
)
from simple_harness_memory.backends.sqlite_v5 import SQLiteHumanMemoryBackend
from tests.integration.test_memory_061_core import LINEAGE_A, _evidence
from tests.integration.test_memory_061_schema_v7_1 import _columns, _write_v7_0_database

# 0.6.1 定稿的 v7.1 DDL checksum；0.6.2 不改 DDL，故与当前 SCHEMA_CHECKSUM 相同。
SCHEMA_CHECKSUM_V7_1 = "c3d680ff5b1f55e6eb4134dd65054f50b5bce6e0cc721d5b19d4ab794a86c15b"


def test_0_6_2_keeps_schema_v7_1_without_ddl_change() -> None:
    assert __version__ == "0.6.2"
    assert (SCHEMA_VERSION, SCHEMA_MINOR_VERSION, SCHEMA_VERSION_LABEL) == (7, 1, "7.1")
    # 0.6.2 只修 decision 构造，不改 DDL：当前 checksum 钉死为 0.6.1 定稿的 v7.1 值。
    assert SCHEMA_CHECKSUM == SCHEMA_CHECKSUM_V7_1
    assert SCHEMA_CHECKSUM != SCHEMA_CHECKSUM_V7_0


@pytest.mark.asyncio
async def test_0_6_1_written_database_opens_unchanged_under_0_6_2(tmp_path: Path) -> None:
    """0.6.1（v7.1）写出的库被 0.6.2 打开：不迁移、receipt/meta 稳定、可继续 ingest。"""

    path = tmp_path / "v7-1.db"
    first = SQLiteHumanMemoryBackend(path, now=lambda: 20.0)
    receipt = await first.initialize()
    try:
        await first.ingest_committed_evidence(*_evidence(1), analysis_lineage=LINEAGE_A)
    finally:
        await first.close()
    columns_before = _columns(path, "evidence_envelopes")
    connection = sqlite3.connect(path, isolation_level=None)
    try:
        meta_before = dict(connection.execute("SELECT key,value FROM schema_meta").fetchall())
    finally:
        connection.close()
    assert meta_before["schema_checksum"] == SCHEMA_CHECKSUM

    reopened = SQLiteHumanMemoryBackend(path, now=lambda: 30.0)
    second = await reopened.initialize()
    try:
        assert second == receipt
        assert second.schema_checksum == SCHEMA_CHECKSUM
        assert second.schema_version == SCHEMA_VERSION
        async with reopened.connection.execute("SELECT key,value FROM schema_meta") as cursor:
            meta_after = {str(row[0]): str(row[1]) for row in await cursor.fetchall()}
        assert meta_after == meta_before
        ingestion = await reopened.ingest_committed_evidence(
            *_evidence(2), analysis_lineage=LINEAGE_A
        )
        assert ingestion.evidence_id == "evidence-2"
    finally:
        await reopened.close()
    assert _columns(path, "evidence_envelopes") == columns_before


@pytest.mark.asyncio
async def test_0_6_0_written_database_is_forward_migrated_to_v7_1_under_0_6_2(
    tmp_path: Path,
) -> None:
    """0.6.0（真实 v7.0 DDL）写出的库被 0.6.2 打开：一次前向加列到 v7.1（同 0.6.1 规则）。"""

    path = tmp_path / "v7-0.db"
    legacy = _write_v7_0_database(path)
    assert "analysis_lineage_json" not in _columns(path, "evidence_envelopes")
    backend = SQLiteHumanMemoryBackend(path, now=lambda: 20.0)
    receipt = await backend.initialize()
    try:
        assert receipt.schema_checksum == SCHEMA_CHECKSUM != SCHEMA_CHECKSUM_V7_0
        assert receipt.receipt_id == legacy["receipt_id"]
        async with backend.connection.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None and str(row[0]) == str(SCHEMA_VERSION)
    finally:
        await backend.close()
    assert _columns(path, "evidence_envelopes")[-1] == "analysis_lineage_json"
