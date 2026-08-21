import pytest

from simple_harness_memory import MemoryManager


@pytest.mark.asyncio
async def test_manager_mock_end_to_end():
    m = await MemoryManager.build()
    await m.append_message(
        "s1", "user", "我养了一只叫Max的狗",
        user_id="u1", source_event_id="manager-1",
    )
    assert len(await m.recall("Max", user_id="u1")) >= 1
    assert await m.get_digital_twin(user_id="u1") is not None
    assert (await m.world.get_temporal_context()).date_str
    await m.close()


@pytest.mark.asyncio
async def test_manager_sqlite_with_facts(tmp_path):
    m = await MemoryManager.build(str(tmp_path / "m.db"), enable_facts=True, enable_world_model=True)
    await m.append_message(
        "s1", "user", "我养了一只叫Max的狗，很喜欢吃披萨",
        user_id="u1", source_event_id="manager-2",
    )
    assert any(f.key == "pet_name" for f in await m.get_facts(user_id="u1"))
    await m.close()


@pytest.mark.asyncio
async def test_manager_embedder_kind():
    m = await MemoryManager.build(embedder="hash")
    await m.append_message(
        "s1", "user", "我养了一只猫",
        user_id="u1", source_event_id="manager-3",
    )
    assert len(await m.recall("猫", user_id="u1")) >= 1
    await m.close()
