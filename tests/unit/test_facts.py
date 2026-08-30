import pytest

from tests.fixtures.legacy_facts import LegacyRegexFactExtractor


@pytest.mark.asyncio
async def test_extract_pet_and_preference():
    ext = LegacyRegexFactExtractor()
    facts = await ext.extract("我养了一只叫Max的狗，很喜欢吃披萨", role="user", message_id=1)
    assert any(f.key == "pet_name" and f.value == "Max" for f in facts)
    assert any(f.key == "prefers" for f in facts)


@pytest.mark.asyncio
async def test_no_extract_for_assistant():
    ext = LegacyRegexFactExtractor()
    assert await ext.extract("我养了一只猫", role="assistant") == []
