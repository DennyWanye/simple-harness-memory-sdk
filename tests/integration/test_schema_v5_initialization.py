from __future__ import annotations

import asyncio
import hashlib
import os
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from simple_harness_memory.backends.schema_v5 import (
    REQUIRED_TABLES,
    SCHEMA_CHECKSUM,
    SCHEMA_EPOCH,
    SCHEMA_VERSION,
)
from simple_harness_memory.backends.sqlite import SQLiteMemoryBackend
from simple_harness_memory.backends.sqlite_v5 import (
    INITIALIZATION_FAULT_POINTS,
    SQLiteHumanMemoryBackend,
)
from simple_harness_memory.core.errors import (
    MemoryLegacySchemaUnsupported,
    MemoryWriterConflict,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _directory_state(path: Path) -> tuple[tuple[str, int, str], ...]:
    return tuple(
        (item.name, item.stat().st_mode, _sha256(item))
        for item in sorted(path.parent.iterdir())
        if item.is_file()
    )


@pytest.mark.asyncio
async def test_fresh_v7_schema_is_atomic_idempotent_and_reopens_same_receipt(
    tmp_path: Path,
) -> None:
    path = tmp_path / "human-memory.db"
    backend = SQLiteHumanMemoryBackend(path, now=lambda: 123.5)
    receipts = await asyncio.gather(*(backend.initialize() for _ in range(4)))
    assert len({receipt.receipt_hash for receipt in receipts}) == 1
    receipt = receipts[0]
    assert receipt.schema_version == SCHEMA_VERSION == 7
    assert receipt.schema_epoch == SCHEMA_EPOCH == "human-memory-v1"
    assert receipt.schema_checksum == SCHEMA_CHECKSUM
    assert receipt.created_at == 123.5
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    async with backend.connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ) as cursor:
        tables = {str(row[0]) for row in await cursor.fetchall()}
    assert REQUIRED_TABLES == tables
    async with backend.connection.execute("SELECT key,value FROM schema_meta") as cursor:
        meta = {str(row[0]): str(row[1]) for row in await cursor.fetchall()}
    assert meta == {
        "schema_version": "7",
        "schema_epoch": SCHEMA_EPOCH,
        "schema_checksum": SCHEMA_CHECKSUM,
        "initialization_receipt_id": receipt.receipt_id,
        "initialization_receipt_hash": receipt.receipt_hash,
    }
    await backend.close()

    reopened = SQLiteHumanMemoryBackend(path)
    replay = await reopened.initialize()
    assert replay == receipt
    async with reopened.connection.execute(
        "SELECT COUNT(*) FROM initialization_receipts"
    ) as cursor:
        row = await cursor.fetchone()
        assert row is not None and row[0] == 1
    await reopened.close()


@pytest.mark.asyncio
async def test_two_initializers_share_one_committed_root_and_one_live_writer(
    tmp_path: Path,
) -> None:
    path = tmp_path / "concurrent.db"
    first = SQLiteHumanMemoryBackend(path)
    second = SQLiteHumanMemoryBackend(path)
    results = await asyncio.gather(first.initialize(), second.initialize(), return_exceptions=True)
    receipts = [result for result in results if not isinstance(result, BaseException)]
    conflicts = [result for result in results if isinstance(result, MemoryWriterConflict)]
    assert len(receipts) == len(conflicts) == 1
    committed = receipts[0]
    assert not isinstance(committed, BaseException)
    await first.close()
    await second.close()

    reopened = SQLiteHumanMemoryBackend(path)
    assert await reopened.initialize() == committed
    await reopened.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault_point", INITIALIZATION_FAULT_POINTS)
async def test_every_v7_initialization_fault_reopens_to_one_valid_receipt(
    tmp_path: Path,
    fault_point: str,
) -> None:
    path = tmp_path / (fault_point.replace(".", "-") + ".db")
    fired = False

    def inject(point: str) -> None:
        nonlocal fired
        if point == fault_point and not fired:
            fired = True
            raise RuntimeError(f"fault:{point}")

    failed = SQLiteHumanMemoryBackend(path, fault_injector=inject)
    with pytest.raises(RuntimeError, match="fault:"):
        await failed.initialize()
    assert fired
    assert failed.initialization_receipt is None

    reopened = SQLiteHumanMemoryBackend(path)
    receipt = await reopened.initialize()
    assert receipt.schema_version == 7
    async with reopened.connection.execute(
        "SELECT COUNT(*) FROM initialization_receipts"
    ) as cursor:
        row = await cursor.fetchone()
        assert row is not None and row[0] == 1
    async with reopened.connection.execute("PRAGMA integrity_check") as cursor:
        row = await cursor.fetchone()
        assert row is not None and row[0] == "ok"
    await reopened.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_kind", ("v4", "unknown-meta", "unstamped", "not-sqlite"))
async def test_legacy_and_unknown_schema_are_rejected_without_any_mutation(
    tmp_path: Path,
    legacy_kind: str,
) -> None:
    path = tmp_path / f"{legacy_kind}.db"
    if legacy_kind == "v4":
        legacy = SQLiteMemoryBackend(str(path))
        await legacy.initialize()
        await legacy.close()
    elif legacy_kind == "not-sqlite":
        path.write_bytes(b"legacy-not-a-sqlite-database")
    else:
        connection = sqlite3.connect(path)
        if legacy_kind == "unknown-meta":
            connection.execute("CREATE TABLE schema_meta(key TEXT PRIMARY KEY,value TEXT)")
            connection.executemany(
                "INSERT INTO schema_meta VALUES(?,?)",
                (("schema_version", "999"), ("schema_checksum", "unknown")),
            )
        else:
            connection.execute("CREATE TABLE messages(id INTEGER PRIMARY KEY,content TEXT)")
            connection.execute("INSERT INTO messages(content) VALUES('legacy-canary')")
        connection.commit()
        connection.close()
    os.chmod(path, 0o644)
    before = _directory_state(path)
    before_mtime = path.stat().st_mtime_ns

    backend = SQLiteHumanMemoryBackend(path)
    with pytest.raises(MemoryLegacySchemaUnsupported) as error:
        await backend.initialize()
    assert error.value.code == "LEGACY_SCHEMA_UNSUPPORTED"
    assert str(error.value) == "LEGACY_SCHEMA_UNSUPPORTED"
    assert backend.initialization_receipt is None
    assert _directory_state(path) == before
    assert path.stat().st_mtime_ns == before_mtime
    assert stat.S_IMODE(path.stat().st_mode) == 0o644
    assert not path.with_name(path.name + "-wal").exists()
    assert not path.with_name(path.name + "-shm").exists()
    assert not path.with_name(path.name + ".writer.lock").exists() or legacy_kind == "v4"


@pytest.mark.asyncio
async def test_tampered_v7_is_rejected_read_only_before_wal_or_chmod(tmp_path: Path) -> None:
    path = tmp_path / "tampered-v7.db"
    backend = SQLiteHumanMemoryBackend(path)
    await backend.initialize()
    await backend.close()
    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE schema_meta SET value='tampered' WHERE key='schema_checksum'"
    )
    connection.commit()
    connection.close()
    os.chmod(path, 0o640)
    before = _directory_state(path)

    with pytest.raises(MemoryLegacySchemaUnsupported):
        await SQLiteHumanMemoryBackend(path).initialize()
    assert _directory_state(path) == before
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert not path.with_name(path.name + "-wal").exists()
    assert not path.with_name(path.name + "-shm").exists()


def test_process_exit_after_commit_reopens_the_same_single_receipt(tmp_path: Path) -> None:
    path = tmp_path / "killed.db"
    source_root = Path(__file__).resolve().parents[2] / "src"
    script = """
import asyncio
import os
import sys
from simple_harness_memory.backends.sqlite_v5 import SQLiteHumanMemoryBackend

async def main():
    backend = SQLiteHumanMemoryBackend(sys.argv[1], now=lambda: 456.0)
    await backend.initialize()
    os._exit(0)

asyncio.run(main())
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(source_root)
    completed = subprocess.run(
        (sys.executable, "-c", script, str(path)),
        env=environment,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 0

    async def reopen() -> None:
        backend = SQLiteHumanMemoryBackend(path)
        receipt = await backend.initialize()
        assert receipt.created_at == 456.0
        async with backend.connection.execute(
            "SELECT COUNT(*) FROM initialization_receipts"
        ) as cursor:
            row = await cursor.fetchone()
            assert row is not None and row[0] == 1
        await backend.close()

    asyncio.run(reopen())
