#!/usr/bin/env python3
"""Generate the deterministic, unreviewed human-memory recall candidate corpus."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CORPUS = ROOT / "recall-candidates.jsonl"
MANIFEST = ROOT / "manifest.json"
NOW = 1_788_105_600.0
LABEL_SOURCE = "AI_DRAFT_UNREVIEWED"
QUALITY_GATE = "NOT_RUN/BLOCKED"

ENTITIES = (
    "Atlas", "Beacon", "Cedar", "Delta", "Ember",
    "Falcon", "Ginkgo", "Harbor", "Indigo", "Juniper",
)


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fixture(
    ref: str,
    kind: str,
    content: str,
    *,
    revision: int = 1,
    status: str = "active",
    privacy: str = "personal",
    attributes: tuple[str, ...] = ("preference",),
    task_scope: str | None = None,
    valid_from: float | None = NOW - 86_400,
    valid_to: float | None = None,
    suppressed: bool = False,
    cross_task: bool = False,
) -> dict[str, Any]:
    return {
        "ref": ref,
        "source_kind": kind,
        "content": content,
        "content_hash": digest(content),
        "revision": revision,
        "lifecycle_status": status,
        "privacy_class": privacy,
        "information_attributes": list(attributes),
        "task_scope_id": task_scope,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "suppressed": suppressed,
        "cross_task": cross_task,
    }


def context(i: int, entity: str, *, purpose: str = "task_execution") -> dict[str, Any]:
    return {
        "identity": {
            "deployment_id": "deployment-local-1",
            "household_id": "household-1",
            "actor_id": "user-1",
        },
        "subject": "user-1",
        "run_id": f"run-quality-{i:03d}",
        "current_task_scope_id": f"task-current-{i % 3}",
        "task_goal": f"完成 {entity} 相关任务",
        "task_phase": ("planning", "execution", "review")[i % 3],
        "recipient": {"kind": "self", "recipient_id": "user-1"},
        "purpose": purpose,
        "environment": {"os": "macos", "tool": "simple_harness", "version": "0.6"},
        "entities": [entity],
        "event_constraints": [],
        "time_constraints": {"now": NOW, "lookback_days": 30},
        "budget": {"max_items": 4, "max_bytes": 4096, "max_tokens": 900},
    }


def scenario(
    family: str,
    i: int,
    query: str,
    fixtures: list[dict[str, Any]],
    *,
    required: tuple[str, ...],
    selected: tuple[str, ...] = (),
    outcome: str = "RECALL",
    privacy_decision: str = "ALLOW",
    privacy_reason: str = "eligible_for_disclosure",
    hard_trigger: bool = False,
    reason: str,
    confirmation: tuple[str, ...] = (),
    context_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entity = ENTITIES[i]
    ctx = context(i, entity)
    ctx["run_id"] = f"run-{family}-{i:02d}"
    if context_overrides:
        ctx.update(context_overrides)
    refs = [item["ref"] for item in fixtures]
    return {
        "corpus_schema_version": "human-memory-recall-candidate/v1",
        "scenario_id": f"hmrq-{family}-{i:02d}",
        "family": family,
        "query": query,
        "structured_context": ctx,
        "memory_fixtures": fixtures,
        "memory_refs": refs,
        "expected_required_types": list(required),
        "expected_selected_refs": list(selected),
        "expected_confirmation_candidate_refs": list(confirmation),
        "expected_outcome": outcome,
        "expected_privacy_outcome": {
            "decision": privacy_decision,
            "reason_code": privacy_reason,
        },
        "hard_trigger": hard_trigger,
        "design_reason": reason,
        "label_source": LABEL_SOURCE,
        "quality_gate": QUALITY_GATE,
    }


def build(family: str, i: int) -> dict[str, Any]:
    e = ENTITIES[i]
    cur = f"task-current-{i % 3}"
    other = f"task-archive-{i}"
    a = f"mem:{family}:{i}:a"
    b = f"mem:{family}:{i}:b"
    c = f"mem:{family}:{i}:c"

    if family == "no_recall_chitchat":
        fs = [fixture(a, "semantic", f"{e} 项目的发布约束", task_scope=other)]
        return scenario(family, i, f"你好，今天过得怎么样？编号 {i}", fs, required=(), outcome="NO_RECALL", reason="寒暄不需要长期记忆，避免无意义召回。")
    if family == "semantic_active":
        fs = [fixture(a, "semantic", f"用户偏好 {e} 报告使用简洁中文"), fixture(b, "episode", f"曾经浏览过 {e} 报告", task_scope=other)]
        return scenario(family, i, f"按我的习惯写一份 {e} 报告", fs, required=("semantic",), selected=(a,), reason="稳定偏好应召回当前 active Semantic，而非偶发经历。")
    if family == "episode_event":
        fs = [fixture(a, "episode", f"上次 {e} 部署失败并因端口冲突回滚", task_scope=other), fixture(b, "semantic", f"{e} 使用 Python", task_scope=other)]
        return scenario(family, i, f"上次 {e} 部署出了什么问题？", fs, required=("episode",), selected=(a,), reason="询问过去具体事件，需要 Episode 的行动与结果。")
    if family == "procedure_active":
        fs = [fixture(a, "procedure", f"处理 {e} 发布时先备份、校验 SHA、再部署", status="active"), fixture(b, "procedure", f"旧的 {e} 发布步骤", status="superseded")]
        return scenario(family, i, f"现在发布 {e}，按我的流程来", fs, required=("procedure",), selected=(a,), hard_trigger=True, reason="明确执行任务命中 active Procedure，旧版本不得使用。")
    if family == "prospective_pending":
        fs = [fixture(a, "prospective", f"{e} 构建完成后提醒更新变更日志", status="pending", attributes=("goal",)), fixture(b, "semantic", f"用户关注 {e}")]
        return scenario(family, i, f"我还有哪些与 {e} 有关的待办提醒？", fs, required=("prospective",), selected=(a,), hard_trigger=True, reason="明确询问未来待办，应召回 pending Prospective。")
    if family == "short_horizon_recent":
        fs = [fixture(a, "short_horizon", f"五分钟前讨论了 {e} 参数 --safe-mode", task_scope=cur, valid_from=NOW-300, valid_to=NOW+5*86_400), fixture(b, "semantic", f"{e} 的一般说明")]
        return scenario(family, i, f"刚才关于 {e} 的参数是什么？", fs, required=("short_horizon",), selected=(a,), reason="最近十组之外但五天内的对话由 Short-Horizon 补回。")
    if family == "task_scope_continue":
        fs = [fixture(a, "task_scope", f"{e} 任务已完成步骤 1-3，下一步运行集成测试", status="active", task_scope=other, attributes=("goal",)), fixture(b, "episode", f"{e} 的一次无关讨论", task_scope="task-other")]
        return scenario(family, i, f"继续之前的 {e} 任务", fs, required=("task_scope",), selected=(a,), hard_trigger=True, reason="继续任务是 TaskScope 打开硬触发，需返回可恢复档案。")
    if family == "cross_type_personalized_plan":
        fs = [fixture(a, "semantic", f"用户偏好 {e} 方案控制成本"), fixture(b, "procedure", f"制定 {e} 方案时先列风险再估算成本", status="active"), fixture(c, "prospective", f"月底复查 {e} 预算", status="pending", attributes=("goal",))]
        return scenario(family, i, f"帮我规划 {e} 的下一步并照我的方式做", fs, required=("semantic", "procedure", "prospective"), selected=(a,b,c), hard_trigger=True, reason="个性化规划需要偏好、做事方式和未完成未来意图的跨类型融合。")
    if family == "contested_confirmation":
        fs = [fixture(a, "semantic", f"{e} 的默认区域是上海", status="contested"), fixture(b, "semantic", f"{e} 的默认区域是东京", status="contested")]
        return scenario(family, i, f"{e} 当前默认区域是什么？", fs, required=("semantic",), outcome="NEEDS_USER_CONFIRMATION", confirmation=(a,b), reason="同一事实存在双方合格冲突，不能单边选择。")
    if family == "suppression_deny":
        fs = [fixture(a, "semantic", f"用户曾要求记住 {e} 私人偏好", suppressed=True), fixture(b, "episode", f"包含 {e} 的旧对话", suppressed=True)]
        return scenario(family, i, f"告诉我关于 {e} 的旧偏好", fs, required=("semantic",), outcome="NO_RECALL", privacy_decision="DENY", privacy_reason="suppression_gate", reason=" suppression 对证据和记忆均先于候选生成，不泄露其存在。")
    if family == "privacy_recipient_deny":
        fs = [fixture(a, "semantic", f"用户的 {e} 医疗偏好", privacy="sensitive", attributes=("health",))]
        return scenario(family, i, f"把我的 {e} 医疗偏好发给群聊", fs, required=("semantic",), outcome="NO_RECALL", privacy_decision="DENY", privacy_reason="recipient_not_authorized", reason="敏感信息不能披露给未授权群聊接收者。", context_overrides={"recipient":{"kind":"group","recipient_id":"public-group"}})
    if family == "privacy_purpose_deny":
        fs = [fixture(a, "semantic", f"用户的 {e} 财务信息", privacy="sensitive", attributes=("financial",))]
        return scenario(family, i, f"用 {e} 财务信息做广告画像", fs, required=("semantic",), outcome="NO_RECALL", privacy_decision="DENY", privacy_reason="purpose_not_authorized", reason="目的不符合原始授权，资格门应拒绝。", context_overrides={"purpose":"advertising_profile"})
    if family == "expired_validity":
        fs = [fixture(a, "semantic", f"{e} 临时办公地址", valid_to=NOW-1), fixture(b, "semantic", f"{e} 当前办公地址", valid_from=NOW-100, valid_to=None)]
        return scenario(family, i, f"{e} 当前办公地址是什么？", fs, required=("semantic",), selected=(b,), reason="过期 valid-time 值必须过滤，只召回当前有效值。")
    if family == "active_revision":
        fs = [fixture(a, "semantic", f"{e} 使用旧 API v1", revision=1, status="superseded"), fixture(b, "semantic", f"{e} 使用新 API v2", revision=2, status="active")]
        return scenario(family, i, f"{e} 现在使用哪个 API？", fs, required=("semantic",), selected=(b,), reason="信息变化后只用 active revision，旧 revision 仅保留审计。")
    if family == "procedure_status_deny":
        fs = [fixture(a, "procedure", f"尚未验证的 {e} 自动删除流程", status="draft", attributes=("preference",)), fixture(b, "semantic", f"{e} 删除具有高风险")]
        return scenario(family, i, f"直接执行 {e} 自动删除流程", fs, required=("procedure",), outcome="NO_RECALL", privacy_decision="DENY", privacy_reason="lifecycle_status_gate", hard_trigger=True, reason="draft 且高风险的 Procedure 不可作为执行上下文。")
    if family == "prospective_terminal":
        fs = [fixture(a, "prospective", f"提醒提交 {e} 报告", status="completed", attributes=("goal",)), fixture(b, "prospective", f"提醒复查 {e} 报告", status="expired", attributes=("goal",))]
        return scenario(family, i, f"现在是否还要提醒我提交 {e} 报告？", fs, required=("prospective",), outcome="NO_RECALL", privacy_decision="ALLOW", privacy_reason="eligible_but_terminal_status", reason="completed/expired Prospective 不应作为当前待办召回。")
    if family == "budget_minimal":
        fs = [fixture(a, "semantic", f"{e} 首要硬约束是预算不超过 100 元"), fixture(b, "episode", f"上次 {e} 花费 90 元"), fixture(c, "semantic", f"{e} 次要偏好为蓝色")]
        return scenario(family, i, f"给我一句话说明 {e} 的最重要约束", fs, required=("semantic",), selected=(a,), reason="预算限制 max_items=1 时只选最小充分的硬约束。", context_overrides={"budget":{"max_items":1,"max_bytes":512,"max_tokens":100}})
    if family == "cross_task_semantic":
        fs = [fixture(a, "semantic", f"用户所有项目都要求 {e} 输出可审计日志", task_scope=other, cross_task=True), fixture(b, "episode", f"另一个任务曾提到 {e}", task_scope=other, cross_task=True)]
        return scenario(family, i, f"这个新任务的 {e} 输出有什么全局要求？", fs, required=("semantic",), selected=(a,), reason="全局有效 Semantic 可跨 TaskScope 使用并记录来源。")
    if family == "cross_task_procedure":
        fs = [fixture(a, "procedure", f"所有 {e} 测试都先跑确定性协议测试", status="active", task_scope=other, cross_task=True), fixture(b, "procedure", f"仅旧项目适用的 {e} 步骤", status="inapplicable", task_scope=other)]
        return scenario(family, i, f"在新任务里测试 {e} 应先做什么？", fs, required=("procedure",), selected=(a,), reason="适用性匹配的 active Procedure 可以跨任务召回。")
    if family == "raw_evidence_quote":
        fs = [fixture(a, "raw_evidence", f"用户原话：{e} 发布窗口定在周五 18:00", privacy="personal", attributes=("goal",)), fixture(b, "semantic", f"{e} 通常周五发布")]
        return scenario(family, i, f"我关于 {e} 发布窗口的原话是什么？", fs, required=("raw_evidence",), selected=(a,), hard_trigger=True, reason="要求原话属于证据读取，不应以 Semantic 摘要冒充。", context_overrides={"purpose":"user_requested_quote"})
    if family == "working_context_only":
        fs = [fixture(a, "semantic", f"{e} 的长期背景", task_scope=other)]
        return scenario(family, i, f"把我上一句里的 {e} 改成粗体", fs, required=(), outcome="NO_RECALL", reason="当前工作记忆已包含上一句，不应重复召回长期存储。")
    if family == "entity_affinity":
        fs = [fixture(a, "short_horizon", f"昨天讨论 {e} 时决定使用端口 {8200+i}", task_scope=other, valid_to=NOW+4*86_400, cross_task=True), fixture(b, "short_horizon", "昨天讨论另一个项目使用端口 9999", task_scope=other, valid_to=NOW+4*86_400, cross_task=True)]
        return scenario(family, i, f"{e} 决定使用哪个端口？", fs, required=("short_horizon",), selected=(a,), reason="跨任务相似文本需要实体亲和度消歧。")
    if family == "temporal_episode":
        fs = [fixture(a, "episode", f"三天前完成 {e} 第一阶段", task_scope=other, valid_from=NOW-3*86_400), fixture(b, "episode", f"三个月前启动 {e}", task_scope=other, valid_from=NOW-90*86_400)]
        return scenario(family, i, f"{e} 最近完成了哪个阶段？", fs, required=("episode",), selected=(a,), reason="显式最近时间约束应优先符合窗口的 Episode。", context_overrides={"time_constraints":{"now":NOW,"lookback_days":7}})
    if family == "hard_trigger_composite":
        fs = [fixture(a, "procedure", f"{e} 发布必须先运行检查清单", status="active"), fixture(b, "prospective", f"{e} 发布成功后提醒更新变更日志", status="pending", attributes=("goal",)), fixture(c, "semantic", f"{e} 发布不得跳过审计")]
        return scenario(family, i, f"现在开始发布 {e}", fs, required=("procedure","prospective","semantic"), selected=(a,b,c), hard_trigger=True, reason="开始执行是硬触发，需要过程规则、未来触发意图和全局硬约束。")
    raise AssertionError(f"unknown family: {family}")


FAMILIES = (
    "no_recall_chitchat", "semantic_active", "episode_event", "procedure_active",
    "prospective_pending", "short_horizon_recent", "task_scope_continue",
    "cross_type_personalized_plan", "contested_confirmation", "suppression_deny",
    "privacy_recipient_deny", "privacy_purpose_deny", "expired_validity",
    "active_revision", "procedure_status_deny", "prospective_terminal",
    "budget_minimal", "cross_task_semantic", "cross_task_procedure",
    "raw_evidence_quote", "working_context_only", "entity_affinity",
    "temporal_episode", "hard_trigger_composite",
)


def stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    required = Counter(t for row in rows for t in row["expected_required_types"])
    privacy = Counter(row["expected_privacy_outcome"]["decision"] for row in rows)
    return {
        "by_family": dict(sorted(Counter(row["family"] for row in rows).items())),
        "by_outcome": dict(sorted(Counter(row["expected_outcome"] for row in rows).items())),
        "by_required_type": dict(sorted(required.items())),
        "by_privacy_decision": dict(sorted(privacy.items())),
        "hard_trigger": dict(sorted(Counter(str(row["hard_trigger"]).lower() for row in rows).items())),
    }


def main() -> None:
    rows = [build(family, i) for family in FAMILIES for i in range(len(ENTITIES))]
    encoded = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for row in rows
    ).encode("utf-8")
    CORPUS.write_bytes(encoded)
    manifest = {
        "manifest_schema_version": "human-memory-recall-corpus-manifest/v1",
        "artifact": CORPUS.name,
        "count": len(rows),
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "label_source": LABEL_SOURCE,
        "quality_gate": QUALITY_GATE,
        "deterministic_generator": Path(__file__).name,
        "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "companion_sha256": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in ("README.md", "validate_corpus.py")
        },
        "stats": stats(rows),
        "notes": [
            "This is an AI-generated candidate set awaiting independent human review.",
            "No real main-model recall evaluation was executed.",
            "Working Memory is first-class Context rather than a durable table; the four long-term stores are Episode, Semantic, Procedure, and Prospective. TaskScope is a separate durable task archive, Short-Horizon is a disposable projection, and raw evidence is the permanent audit source.",
        ],
    }
    MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
