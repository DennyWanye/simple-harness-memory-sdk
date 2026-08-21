"""单元测试：遗忘曲线与数字孪生体。"""

from __future__ import annotations

import pytest

from simple_harness_memory.cognitive.decay import (
    bump_salience,
    decay_salience,
    retention,
    should_forget,
)
from simple_harness_memory.core.twin import (
    DigitalTwin,
    Goal,
    RelationshipGraph,
    SkillMap,
)

# ── 遗忘曲线 ─────────────────────────────────────────


def test_retention_zero_days() -> None:
    assert retention(0.02, 0.0) == 1.0


def test_retention_decreases_with_time() -> None:
    r7 = retention(0.02, 7)
    r30 = retention(0.02, 30)
    assert r7 > r30
    assert 0.0 < r30 < 1.0


def test_retention_zero_decay_rate_never_forgets() -> None:
    assert retention(0.0, 9999) == 1.0


def test_should_forget_long_time() -> None:
    # decay_rate=0.5 → 14天后 retention ≈ 0.0006
    assert should_forget(0.5, 14)


def test_should_not_forget_profile() -> None:
    # profile decay_rate=0.0 → 永不遗忘
    assert not should_forget(0.0, 9999)


def test_bump_salience_capped() -> None:
    assert bump_salience(0.98, 0.05) == 1.0
    assert bump_salience(0.5, 0.05) == pytest.approx(0.55)


def test_decay_salience() -> None:
    # 衰减后值应减小
    original = 0.8
    decayed = decay_salience(original, 0.02, 30)
    assert decayed < original
    assert decayed > 0.0


# ── 数字孪生体 ───────────────────────────────────────


def test_twin_default_state() -> None:
    twin = DigitalTwin()
    assert twin.subject == "user"
    assert twin.completeness == 0.0
    assert twin.profile.name is None


def test_twin_missing_profile_fields() -> None:
    twin = DigitalTwin()
    missing = twin.missing_profile_fields()
    assert "name" in missing
    assert "occupation" in missing


def test_twin_completeness_increases_with_profile() -> None:
    twin = DigitalTwin()
    twin.profile.name = "张三"
    twin.profile.occupation = "工程师"
    twin.profile.location = "北京"
    twin.profile.language = "zh"
    twin.recalculate_completeness()
    assert twin.completeness > 0.3  # profile 满分 → 至少 40%


def test_skill_map_upsert() -> None:
    sm = SkillMap()
    sk = sm.upsert("python", delta=0.2)
    assert sk.level == pytest.approx(0.5 + 0.2)
    assert sk.evidence_count == 1
    sm.upsert("python", delta=0.1)
    assert sm.skills["python"].evidence_count == 2


def test_relationship_graph_upsert() -> None:
    rg = RelationshipGraph()
    e = rg.upsert("Max", "pet", "owner")
    assert e.name == "Max"
    assert e.entity_type == "pet"
    assert "Max" in rg.entities


def test_active_goals_filter() -> None:
    twin = DigitalTwin()
    twin.goals = [
        Goal("g1", "学会 Rust", status="active"),
        Goal("g2", "完成项目", status="completed"),
    ]
    active = twin.active_goals()
    assert len(active) == 1
    assert active[0].goal_id == "g1"
