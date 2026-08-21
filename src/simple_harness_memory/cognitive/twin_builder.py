"""Digital Twin 构建与一致性检测。"""

from __future__ import annotations

from simple_harness_memory.core.models import SINGLE_VALUED_KEYS, Fact, FactConflict
from simple_harness_memory.core.twin import DigitalTwin, Goal


def build_twin_from_facts(facts, base=None, subject="user"):
    twin = base if base is not None else DigitalTwin(subject=subject)
    if twin.subject != subject:
        twin.subject = subject
    active = [f for f in facts if f.subject == subject and f.is_active]
    for fact in active:
        _apply_fact(twin, fact)
    if active:
        twin.confidence = round(sum(f.confidence for f in active) / len(active), 3)
    twin.recalculate_completeness()
    return twin


def _apply_fact(twin, fact):
    value = fact.value
    profile_fields = {
        "name": "name",
        "occupation": "occupation",
        "location": "location",
        "language": "language",
        "timezone": "timezone",
    }
    if fact.key in profile_fields and fact.category == "profile":
        if getattr(twin.profile, profile_fields[fact.key]) is None:
            setattr(twin.profile, profile_fields[fact.key], value)
        return
    if fact.category == "learning":
        twin.skills.upsert(value, delta=0.1 + 0.1 * fact.confidence)
        return
    if fact.category == "preference":
        key = fact.key
        existing = twin.preferences.preferences.get(key)
        if existing is not None and existing.value != value:
            key = f"{fact.key}:{value}"
        twin.preferences.upsert(key, value, strength_delta=0.1 + 0.1 * fact.confidence)
        return
    if fact.key == "pet_name":
        twin.relationships.upsert(value, entity_type="pet", relation="owner")
        return
    if fact.category == "goal":
        twin.goals.append(
            Goal(
                goal_id=f"goal-{len(twin.goals) + 1}", description=value, created_at=fact.created_at
            )
        )


def detect_fact_conflicts(facts):
    active = [f for f in facts if f.is_active]
    by_key: dict[tuple[str, str], list[Fact]] = {}
    for f in active:
        if f.key not in SINGLE_VALUED_KEYS:
            continue
        by_key.setdefault((f.subject, f.key), []).append(f)
    conflicts = []
    for (subject, key), items in by_key.items():
        values = sorted({i.value for i in items})
        if len(values) > 1:
            conflicts.append(
                FactConflict(
                    subject=subject, key=key, values=values, fact_ids=[i.id or 0 for i in items]
                )
            )
    return conflicts
