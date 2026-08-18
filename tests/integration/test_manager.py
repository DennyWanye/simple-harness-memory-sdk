import pytest

from simple_harness_memory import MemoryManager


@pytest.mark.asyncio
async def test_manager_mock_end_to_end():
    m = await MemoryManager.build()
    await m.append_message("s1", "user", "我养了一只叫Max的狗")
    assert len(await m.recall("Max")) >= 1
    assert await m.get_digital_twin() is not None
    assert (await m.world.get_temporal_context()).date_str
    await m.close()


@pytest.mark.asyncio
async def test_manager_sqlite_with_facts(tmp_path):
    m = await MemoryManager.build(str(tmp_path / "m.db"), enable_facts=True, enable_world_model=True)
    await m.append_message("s1", "user", "我养了一只叫Max的狗，很喜欢吃披萨")
    assert any(f.key == "pet_name" for f in await m.get_facts())
    await m.close()
