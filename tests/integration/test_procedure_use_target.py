"""Public exact-revision metadata; no authority issuance or raw step disclosure."""
import hashlib
from dataclasses import replace
import pytest

from simple_harness_memory import MemoryScope, ProcedureUseTarget
from simple_harness_memory.core.errors import MemoryCorruptionError, MemoryWriterConflict
from simple_harness_memory.core.manager import MemoryManager
from .test_procedure_observation_repository_v5 import _setup, _principal


@pytest.mark.asyncio
async def test_public_use_target_exact_owner_revision_and_no_raw_steps(tmp_path):
    backend, authority, _, memory_id, revision = await _setup(tmp_path / "use.db", [20.0])
    manager = MemoryManager(backend, None)
    try:
        args = dict(principal=_principal(), scope=MemoryScope.personal("actor-1"),
                    memory_id=memory_id, revision=revision)
        target = await manager.read_procedure_use_target(**args)
        assert type(target) is ProcedureUseTarget
        assert target.step_hashes == tuple(hashlib.sha256(s.encode()).hexdigest() for s in ("review", "publish"))
        assert target.lifecycle_state == "draft"
        assert "steps" not in target.to_json()
        assert target == await manager.read_procedure_use_target(**args)
        assert authority.procedure_resolutions == 0
        with pytest.raises(MemoryWriterConflict):
            await manager.read_procedure_use_target(**{**args, "revision": revision + 1})
        other = replace(_principal(), actor_id="other-actor")
        with pytest.raises(MemoryWriterConflict):
            await manager.read_procedure_use_target(**{**args, "principal": other,
                                                      "scope": MemoryScope.personal(other.actor_id)})
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_public_use_target_rejects_modified_typed_payload(tmp_path):
    backend, _, _, memory_id, revision = await _setup(tmp_path / "tamper.db", [20.0])
    manager = MemoryManager(backend, None)
    try:
        # Deliberate corruption only in this temporary test database. Do not
        # weaken or patch the production reader to accommodate altered rows.
        async with backend.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='procedure_records'"
        ) as cursor:
            names = [row[0] for row in await cursor.fetchall()]
        for name in names:
            await backend.connection.execute('DROP TRIGGER "' + name.replace('"', '""') + '"')
        await backend.connection.execute("UPDATE procedure_records SET steps_json=? WHERE memory_id=? AND revision=?",
                                         ('["other step"]', memory_id, revision))
        await backend.connection.commit()
        with pytest.raises(MemoryCorruptionError, match="procedure use payload differs"):
            await manager.read_procedure_use_target(principal=_principal(), scope=MemoryScope.personal("actor-1"),
                                                    memory_id=memory_id, revision=revision)
    finally:
        await manager.close()
