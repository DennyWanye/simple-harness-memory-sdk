"""DigitalTwin — 用户的完整认知模型。

五个核心维度：
  profile      — 身份层（姓名/职业/位置）
  skills       — 认知层（技能图谱）
  preferences  — 情感层（偏好地图）
  relationships— 社交层（实体关系图）
  goals        — 动机层（目标与约束）
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ─────────────────────────────────────────────
# 子结构
# ─────────────────────────────────────────────


@dataclass
class UserProfile:
    """身份层：静态 / 缓变属性。"""

    name: str | None = None
    occupation: str | None = None
    location: str | None = None
    language: str | None = None
    timezone: str | None = None
    extra: dict[str, str] = field(default_factory=dict)


@dataclass
class Skill:
    """单项技能。"""

    name: str
    level: float = 0.5  # 0.0-1.0，从 Facts 累积推断
    evidence_count: int = 0  # 支撑该技能的 fact 数量
    last_updated: float | None = None


@dataclass
class SkillMap:
    """认知层：技能图谱。"""

    skills: dict[str, Skill] = field(default_factory=dict)

    def upsert(self, name: str, delta: float = 0.1) -> Skill:
        if name not in self.skills:
            self.skills[name] = Skill(name=name)
        sk = self.skills[name]
        sk.level = min(1.0, sk.level + delta)
        sk.evidence_count += 1
        return sk


@dataclass
class Preference:
    """单条偏好。"""

    key: str  # 如 "prefers_dark_theme"
    value: str  # 如 "true" / "tea"
    strength: float = 0.5  # 偏好强度 0.0-1.0
    evidence_count: int = 0


@dataclass
class PreferenceMap:
    """情感层：偏好地图。"""

    preferences: dict[str, Preference] = field(default_factory=dict)

    def upsert(self, key: str, value: str, strength_delta: float = 0.1) -> Preference:
        if key not in self.preferences:
            self.preferences[key] = Preference(key=key, value=value)
        pr = self.preferences[key]
        pr.value = value
        pr.strength = min(1.0, pr.strength + strength_delta)
        pr.evidence_count += 1
        return pr


@dataclass
class Entity:
    """关系图中的实体节点。"""

    name: str
    entity_type: str  # "person" | "pet" | "place" | "org" | "object"
    relation: str  # 与 subject 的关系，如 "pet" / "colleague"
    attributes: dict[str, str] = field(default_factory=dict)
    confidence: float = 0.5
    last_mentioned: float | None = None


@dataclass
class RelationshipGraph:
    """社交层：实体关系图（用 SQLite 实现，不引入图数据库）。"""

    entities: dict[str, Entity] = field(default_factory=dict)

    def upsert(self, name: str, entity_type: str, relation: str) -> Entity:
        if name not in self.entities:
            self.entities[name] = Entity(name=name, entity_type=entity_type, relation=relation)
        return self.entities[name]


@dataclass
class Goal:
    """动机层：单个目标。"""

    goal_id: str
    description: str
    deadline: str | None = None  # ISO date string
    status: str = "active"  # "active" | "completed" | "abandoned"
    priority: float = 0.5
    created_at: float | None = None


# ─────────────────────────────────────────────
# 数字孪生体主体
# ─────────────────────────────────────────────


@dataclass
class DigitalTwin:
    """用户的完整认知模型。

    由 Facts 自动构建，随对话持续更新。
    completeness 反映已知信息的丰富程度（0.0-1.0）。
    """

    subject: str = "user"

    # 五个核心维度
    profile: UserProfile = field(default_factory=UserProfile)
    skills: SkillMap = field(default_factory=SkillMap)
    preferences: PreferenceMap = field(default_factory=PreferenceMap)
    relationships: RelationshipGraph = field(default_factory=RelationshipGraph)
    goals: list[Goal] = field(default_factory=list)

    # 元数据
    completeness: float = 0.0  # 已知字段 / 期望字段
    confidence: float = 0.0  # 整体置信度（各 fact confidence 均值）
    last_updated: float | None = None

    def active_goals(self) -> list[Goal]:
        return [g for g in self.goals if g.status == "active"]

    def missing_profile_fields(self) -> list[str]:
        """返回 profile 中尚未填充的字段列表，用于主动追问。"""
        missing = []
        p = self.profile
        if not p.name:
            missing.append("name")
        if not p.occupation:
            missing.append("occupation")
        if not p.location:
            missing.append("location")
        if not p.language:
            missing.append("language")
        return missing

    def recalculate_completeness(self) -> None:
        """根据当前已知信息重新计算 completeness。"""
        total = 4  # profile 核心字段数
        filled = total - len(self.missing_profile_fields())
        skill_score = min(1.0, len(self.skills.skills) / 5)
        pref_score = min(1.0, len(self.preferences.preferences) / 5)
        rel_score = min(1.0, len(self.relationships.entities) / 3)
        goal_score = min(1.0, len(self.goals) / 2)
        self.completeness = round(
            (filled / total * 0.4)
            + (skill_score * 0.15)
            + (pref_score * 0.15)
            + (rel_score * 0.15)
            + (goal_score * 0.15),
            3,
        )
