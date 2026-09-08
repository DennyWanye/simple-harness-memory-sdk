"""争议槽位文本：confirmation 门的词面判据只看「被争议的那一格」（0.6.31）。

S3 §5.3 只规定 contested 候选**只能**以完整 confirmation group 披露，从未把
group 排在普通候选之前；而冻结的 Harness ``RecallDecisionV4`` 又规定一次决定只能
携带 ``selected_items`` 或 ``confirmation_groups`` 之一。于是「group 何时进入决定」
就是「其它记忆何时被整体扣住」。0.6.30 及以前用 group 成员的**整个** payload 做词面
命中：``subject_entity`` / ``qualifiers`` 与同主题的兄弟记忆共享，任何提到该主题的
查询都会把整条召回车道黑洞掉（HM-TO-A6 事件 O / F-O-3）。

本模块把 group 的词面判据收窄到**槽位文本**：两名成员之间**取值不同**的公开字段
（这正是 §5.2 所说"被争议的内容"），再加上 semantic 的 ``predicate``（槽位名）。
只读公开 payload、纯函数、跨进程逐字确定；不进入任何 hash 域，也不改变公开 payload。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from simple_harness.contracts import canonical_json

from simple_harness_memory.features.cognitive_vector import cognitive_text_supplement

#: 争议槽位文本的格式版本；只影响词面门，不进入 manifest / hash 域。
CONFLICT_SLOT_TEXT_VERSION = 1

#: 每类记忆的「槽位名」字段：即使两名成员取值相同，也纳入槽位文本（它说明争的是哪一格）。
_SLOT_NAME_FIELDS: Mapping[str, tuple[str, ...]] = {
    "semantic": ("predicate",),
    "episode": (),
    "procedure": (),
    "prospective": (),
}


def contested_slot_text(
    memory_type: str,
    incumbent_payload: Mapping[str, Any],
    challenger_payload: Mapping[str, Any],
) -> str:
    """返回 group 的槽位文本（casefold 前的原文；调用方自行 casefold）。

    - 两名成员取值不同的顶层公开字段：以 ``{field: [incumbent, challenger]}`` 的
      canonical JSON 逐字段拼接；
    - semantic 额外拼入 ``predicate``（槽位名），无论是否相同；
    - prospective 的 ``trigger`` 不同时，追加两侧的确定性触发渲染
      （与 0.6.26 的词面/向量同源文本一致）；
    - 未知类型、非 Mapping 输入 → 空串（fail closed：词面门永不命中）。
    """

    if memory_type not in _SLOT_NAME_FIELDS:
        return ""
    if not isinstance(incumbent_payload, Mapping) or not isinstance(challenger_payload, Mapping):
        return ""
    parts: list[str] = []
    for field in sorted(set(incumbent_payload) | set(challenger_payload)):
        left = incumbent_payload.get(field)
        right = challenger_payload.get(field)
        if left != right:
            parts.append(canonical_json({field: [left, right]}))
    for field in _SLOT_NAME_FIELDS[memory_type]:
        value = incumbent_payload.get(field, challenger_payload.get(field))
        if isinstance(value, str) and value:
            parts.append(canonical_json({field: value}))
    if memory_type == "prospective" and incumbent_payload.get("trigger") != challenger_payload.get(
        "trigger"
    ):
        for payload in (incumbent_payload, challenger_payload):
            supplement = cognitive_text_supplement(memory_type, payload)
            if supplement:
                parts.append(supplement)
    return "\n".join(parts)


__all__ = ("CONFLICT_SLOT_TEXT_VERSION", "contested_slot_text")
