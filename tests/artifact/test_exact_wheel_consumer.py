from __future__ import annotations

import os
import subprocess
import textwrap
import zipfile
from pathlib import Path


def test_exact_wheel_declares_typed_package(exact_wheel: Path) -> None:
    with zipfile.ZipFile(exact_wheel) as archive:
        assert "simple_harness_memory/py.typed" in archive.namelist()


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
            from simple_harness_memory import (
                MemoryManager,
                MemoryOwnershipConflict,
                MemoryPrincipal,
                __version__,
            )
            from simple_harness_memory.core.errors import HarnessIntegrationExtraRequired

            class HarnessFreeFutureConsumerFixture:
                def __init__(self, manager, path):
                    self.manager = manager
                    self.path = path

                async def verify_authorized_share(self):
                    facts = await self.manager.get_facts(user_id="user-1")
                    assert facts and facts[0].id is not None
                    fact_id = facts[0].id
                    with sqlite3.connect(self.path) as connection:
                        stored_origin = connection.execute(
                            "SELECT deterministic_id FROM facts WHERE id=?", (fact_id,)
                        ).fetchone()[0]
                    origin = stored_origin or f"legacy-fact:{fact_id}"
                    principal = MemoryPrincipal("user-1", "user-1", "user-1", "session-1")
                    projection = await self.manager.share_fact(principal, fact_id)
                    assert await self.manager.share_fact(principal, fact_id) == projection
                    for unauthorized in (
                        MemoryPrincipal("user-1", "user-1", "actor-b", "session-b"),
                        MemoryPrincipal("user-1", "house-b", "user-1", "session-b"),
                    ):
                        try:
                            await self.manager.share_fact(unauthorized, fact_id)
                        except MemoryOwnershipConflict as error:
                            assert error.code == "memory_ownership_conflict"
                        else:
                            raise AssertionError("unauthorized share unexpectedly succeeded")
                    with sqlite3.connect(self.path) as connection:
                        rows = connection.execute(
                            "SELECT deterministic_id, projection_of, scope_kind, scope_owner "
                            "FROM facts WHERE deterministic_id=?",
                            (projection,),
                        ).fetchall()
                        assert len(rows) == 1
                        assert rows[0][1:] == (
                            origin,
                            "family",
                            "user-1",
                        )
                    assert await self.manager.forget_fact(fact_id, principal=principal)
                    with sqlite3.connect(self.path) as connection:
                        assert connection.execute(
                            "SELECT COUNT(*) FROM facts WHERE deterministic_id=? "
                            "OR projection_of=?",
                            (origin, origin),
                        ).fetchone()[0] == 0
                        assert connection.execute(
                            "SELECT COUNT(*) FROM fact_tombstones WHERE deterministic_id=?",
                            (origin,),
                        ).fetchone()[0] == 1

            async def main():
                assert __version__ == "0.4.0"
                assert not hasattr(simple_harness_memory, "ConversationMemoryAdapter")
                path = Path("memory.db").resolve()
                manager = await MemoryManager.build(str(path), enable_facts=True)
                first = await manager.append_message(
                    "session-1", "user", "line1\\r\\n我叫Max",
                    user_id="user-1", source_event_id="event-1",
                )
                replay = await manager.append_message(
                    "session-1", "user", "line1\\r\\n我叫Max",
                    user_id="user-1", source_event_id="event-1",
                )
                assert replay.message_id == first.message_id
                assert await manager.recall("line1", user_id="user-1")
                await HarnessFreeFutureConsumerFixture(manager, path).verify_authorized_share()
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
