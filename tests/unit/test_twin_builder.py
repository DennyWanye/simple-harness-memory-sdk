import time

from simple_harness_memory.cognitive.twin_builder import (
    build_twin_from_facts,
    detect_fact_conflicts,
)
from simple_harness_memory.core.models import Fact


def _fact(fact_id, key, value, category):
    return Fact(
        id=fact_id, user_id="u1", subject="user", key=key, value=value, category=category,
        confidence=0.8, evidence="", source_msg_id=1, created_at=time.time(),
    )


def test_build_twin_from_facts():
    facts = [
        _fact(1, "name", "张三", "profile"),
        _fact(2, "location", "北京", "profile"),
        _fact(3, "skill", "python", "learning"),
        _fact(4, "prefers", "茶", "preference"),
        _fact(5, "pet_name", "Max", "profile"),
    ]
    twin = build_twin_from_facts(facts)
    assert twin.profile.name == "张三"
    assert twin.profile.location == "北京"
    assert "python" in twin.skills.skills
    assert twin.relationships.entities["Max"].entity_type == "pet"


def test_detect_conflicts():
    facts = [_fact(1, "name", "张三", "profile"), _fact(2, "name", "李四", "profile")]
    conflicts = detect_fact_conflicts(facts)
    assert len(conflicts) == 1
    assert conflicts[0].key == "name"
    assert set(conflicts[0].values) == {"张三", "李四"}
