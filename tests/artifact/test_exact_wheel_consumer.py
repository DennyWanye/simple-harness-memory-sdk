from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path


def test_exact_wheel_in_clean_consumer(tmp_path: Path, exact_wheel: Path) -> None:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    venv = tmp_path / "consumer-venv"
    subprocess.run(
        ("uv", "venv", "--python", "3.11", str(venv)),
        check=True,
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run(
        ("uv", "pip", "install", "--python", str(python), str(exact_wheel)),
        check=True,
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )
    consumer = tmp_path / "consumer.py"
    consumer.write_text(
        textwrap.dedent(
            """
            import asyncio
            import hashlib
            import json
            import os
            import sqlite3
            from pathlib import Path

            from simple_harness_memory import (
                ConversationMemoryAdapter,
                ConversationMemoryApplyStatus,
                ConversationMemoryIntent,
                ConversationMemoryRecallQuery,
                ConversationMemoryRole,
                __version__,
            )
            from simple_harness_memory.backends.sqlite import SQLiteMemoryBackend

            async def main():
                assert __version__ == "0.3.0"
                path = Path("memory.db").resolve()
                backend = SQLiteMemoryBackend(str(path))
                await backend.initialize()
                adapter = ConversationMemoryAdapter(backend, close_backend=False)
                intent = ConversationMemoryIntent(
                    "event-1", "user-1", "session-1",
                    ConversationMemoryRole.USER, "line1\\r\\nline2",
                )
                first = await adapter.apply(intent)
                replay = await adapter.apply(intent)
                assert first.status is ConversationMemoryApplyStatus.APPLIED
                assert replay.status is ConversationMemoryApplyStatus.ALREADY_APPLIED
                assert replay.record_id == first.record_id
                query = ConversationMemoryRecallQuery.create(
                    context_query_id="query-1",
                    user_id="user-1",
                    session_id="session-1",
                    query_text="line1",
                    max_items=4,
                    max_bytes=4096,
                    timeout_seconds=1.0,
                )
                result = await adapter.recall_bounded(query)
                payload = json.dumps(
                    result.payload, ensure_ascii=False, allow_nan=False,
                    separators=(",", ":"), sort_keys=True,
                ).encode("utf-8")
                assert result.byte_count == len(payload)
                assert result.result_hash == hashlib.sha256(payload).hexdigest()
                await adapter.release(
                    user_id="user-1",
                    context_query_id="query-1",
                    result_hash=result.result_hash,
                )
                await adapter.release(
                    user_id="user-1",
                    context_query_id="query-1",
                    result_hash=result.result_hash,
                )
                await adapter.close()
                await backend.close()
                assert os.stat(path).st_mode & 0o777 == 0o600
                with sqlite3.connect(path) as connection:
                    assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
                    assert not connection.execute("PRAGMA foreign_key_check").fetchall()

            asyncio.run(main())
            """
        ),
        encoding="utf-8",
    )
    subprocess.run(
        (str(python), "-I", str(consumer)),
        check=True,
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )
