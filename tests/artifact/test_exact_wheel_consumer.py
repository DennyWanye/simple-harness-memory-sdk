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
            import os
            import sqlite3
            from pathlib import Path

            import simple_harness_memory
            from simple_harness_memory import MemoryManager, __version__
            from simple_harness_memory.core.errors import HarnessIntegrationExtraRequired

            async def main():
                assert __version__ == "0.4.0"
                assert not hasattr(simple_harness_memory, "ConversationMemoryAdapter")
                path = Path("memory.db").resolve()
                manager = await MemoryManager.build(str(path))
                first = await manager.append_message(
                    "session-1", "user", "line1\\r\\nline2",
                    user_id="user-1", source_event_id="event-1",
                )
                replay = await manager.append_message(
                    "session-1", "user", "line1\\r\\nline2",
                    user_id="user-1", source_event_id="event-1",
                )
                assert replay.message_id == first.message_id
                assert await manager.recall("line1", user_id="user-1")
                try:
                    await manager.recall_for_turn(object())
                except HarnessIntegrationExtraRequired as error:
                    assert str(error) == "harness_integration_extra_required"
                else:
                    raise AssertionError("base wheel unexpectedly imported Harness")
                await manager.close()
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
