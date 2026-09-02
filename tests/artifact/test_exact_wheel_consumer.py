from __future__ import annotations

import os
import subprocess
import textwrap
import zipfile
from pathlib import Path


def test_exact_wheel_declares_typed_package(exact_wheel: Path) -> None:
    with zipfile.ZipFile(exact_wheel) as archive:
        assert "simple_harness_memory/py.typed" in archive.namelist()


def test_exact_wheel_in_clean_consumer(
    tmp_path: Path, exact_wheel: Path, exact_harness_wheel: Path
) -> None:
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
        (
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            str(exact_harness_wheel),
            str(exact_wheel),
        ),
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
            from simple_harness_memory.core.errors import (
                HarnessIntegrationExtraRequired,
                MemoryIdempotencyConflict,
            )

            class HarnessFreeFutureConsumerFixture:
                def __init__(self, manager, path):
                    self.manager = manager
                    self.path = path

                async def verify_authorized_share(self):
                    principal = MemoryPrincipal(
                        "deployment-a", "house-a", "actor-a", "explicit"
                    )
                    fact_id = await self.manager.remember_fact(
                        principal,
                        "Max is the user's pet",
                        source_event_id="share-fixture-1",
                        tier="identity",
                    )
                    assert await self.manager.read_fact(principal, fact_id) is not None
                    with sqlite3.connect(self.path) as connection:
                        stored_origin = connection.execute(
                            "SELECT deterministic_id FROM facts WHERE id=?", (fact_id,)
                        ).fetchone()[0]
                    origin = stored_origin or f"legacy-fact:{fact_id}"
                    projection = await self.manager.share_fact(principal, fact_id)
                    assert await self.manager.share_fact(principal, fact_id) == projection
                    for unauthorized in (
                        MemoryPrincipal("deployment-a", "house-a", "actor-b", "session-b"),
                        MemoryPrincipal("deployment-a", "house-b", "actor-a", "session-b"),
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
                            "house-a",
                        )
                    forget_event = "explicit-memory-action/v1/root/call-forget"
                    assert await self.manager.forget_fact(
                        fact_id, forget_event, principal=principal
                    )
                    assert await self.manager.forget_fact(
                        fact_id, forget_event, principal=principal
                    )
                    assert not await self.manager.forget_fact(
                        fact_id,
                        principal=principal,
                        source_event_id="explicit-memory-action/v1/root/later-forget",
                    )
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

                async def verify_explicit_fact(self):
                    principal = MemoryPrincipal("deployment-a", "house-a", "actor-a", "explicit")
                    fact_id = await self.manager.remember_fact(
                        principal, "Prefer concise replies", source_event_id="write-call-1",
                        salience=0.75, pinned=True, tier="long_term",
                    )
                    assert await self.manager.remember_fact(
                        principal, "Prefer concise replies", source_event_id="write-call-1",
                        salience=0.75, pinned=True, tier="long_term",
                    ) == fact_id
                    fact = await self.manager.read_fact(principal, fact_id)
                    assert fact is not None
                    assert (fact.id, fact.value, fact.category, fact.pinned) == (
                        fact_id, "Prefer concise replies", "learning", True,
                    )
                    other = MemoryPrincipal("deployment-a", "house-a", "actor-b", "other")
                    assert await self.manager.read_fact(other, fact_id) is None
                    try:
                        await self.manager.remember_fact(
                            principal, "Different", source_event_id="write-call-1",
                            salience=0.75, pinned=True, tier="long_term",
                        )
                    except MemoryIdempotencyConflict:
                        pass
                    else:
                        raise AssertionError("changed explicit fact replay did not conflict")
                    explicit_forget = "explicit-memory-action/v1/root/explicit-forget"
                    assert await self.manager.forget_fact(
                        fact_id, explicit_forget, principal=principal
                    )
                    assert await self.manager.forget_fact(
                        fact_id, explicit_forget, principal=principal
                    )
                    assert not await self.manager.forget_fact(
                        fact_id,
                        principal=principal,
                        source_event_id="explicit-memory-action/v1/root/explicit-no-op",
                    )
                    assert await self.manager.read_fact(principal, fact_id) is None
                    with sqlite3.connect(self.path) as connection:
                        assert connection.execute(
                            "SELECT COUNT(*), SUM(result) FROM explicit_forget_receipts "
                            "WHERE fact_id=?",
                            (fact_id,),
                        ).fetchone() == (2, 1)
                    assert await self.manager.remember_fact(
                        principal, "Prefer concise replies", source_event_id="write-call-1",
                        salience=0.75, pinned=True, tier="long_term",
                    ) == fact_id
                    assert await self.manager.read_fact(principal, fact_id) is None

            async def main():
                assert __version__ == "0.6.2"
                assert not hasattr(simple_harness_memory, "ConversationMemoryAdapter")
                assert not hasattr(MemoryManager, "delete_session")
                assert not hasattr(MemoryManager, "delete_old_sessions")
                assert not hasattr(MemoryManager, "delete_all")
                path = Path("memory.db").resolve()
                manager = await MemoryManager.build(str(path))
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
                await HarnessFreeFutureConsumerFixture(manager, path).verify_explicit_fact()
                await HarnessFreeFutureConsumerFixture(manager, path).verify_authorized_share()
                import simple_harness.observability
                assert simple_harness.observability.SCHEMA_VERSION == 1
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
        timeout=60,
    )
