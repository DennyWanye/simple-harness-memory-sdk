"""Reuse original field/SQL oracle with the new Host authority actually configured."""

import pytest

import simple_harness_memory as m
from tests.integration import test_public_recall_rejection as original


@pytest.mark.asyncio
async def test_public_capability_and_invalid_builder_authority_cannot_be_silently_ignored(tmp_path):
    assert type(m.MemoryManager.history_source_enforcement_version) is int
    assert m.MemoryManager.history_source_enforcement_version == 1
    path = tmp_path / "invalid.db"
    with pytest.raises(TypeError, match="HistorySourceAuthorityPort"):
        await m.build_human_memory_v7(path, history_source_authority=object())
    assert not path.exists()


@pytest.fixture
def configured_authority(monkeypatch):
    calls = []

    class Authority:
        async def resolve_history_source(self, **kwargs):
            calls.append("source")
            raise AssertionError("no relevant source should be requested")

        async def resolve_history_forget_cut(self, **kwargs):
            calls.append("cut")
            raise AssertionError("no relevant cut should be requested")

    async def build(*args, **kwargs):
        return await m.build_human_memory_v7(
            *args, **kwargs, history_source_authority=Authority(),
        )

    monkeypatch.setattr(original, "build_human_memory_v7", build)
    yield calls
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("field", original.FIELD_ATTACKS)
async def test_original_field_traps_with_history_authority(
    tmp_path, monkeypatch, configured_authority, field,
):
    await original.test_public_field_attack_has_zero_candidate_access(tmp_path, monkeypatch, field)


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["manager", "backend"])
@pytest.mark.parametrize("version", [5, True, "4", None, 4.0])
async def test_original_zero_sql_protocol_with_history_authority(
    tmp_path, configured_authority, entry, version,
):
    await original.test_public_protocol_admission_rejects_before_any_sql(tmp_path, entry, version)
