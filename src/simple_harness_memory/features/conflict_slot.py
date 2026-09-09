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

0.6.37（HM-TO-A6 事件 V / F-V-2，``DECISION-2026-09-09-contested-group-admission-basis.md``）：
0.6.31 的收窄把"这一格争的是什么"留下了，却把"这一格属于谁、在什么条件下成立"整段拿掉了。
run-9 的证据形状是：槽位文本 ``{"object_value":["Python 3.13","3.12"]}`` /
``{"predicate":"proofreading_script_python_version"}`` 里**一个 CJK 字符都没有**，
于是纯中文的用户原句永远词面准入不了，而该 head 的 ``qualifiers``（"在做资料校对时"）
才是用户真正会说出口的那几个字。因此**冲突组的准入基底**扩展为
``contested_slot_text`` ∪ 该 group 所属 head 当前 revision 的 ``subject_entity`` /
``qualifiers``（``contested_admission_text``）。扩展**只对冲突组生效**：普通 item 车道的
词面准入不变（0.6.31 防的是共享 ``subject_entity``/``qualifiers`` 的**兄弟记忆**互相污染，
而一个 group 只有一个 head，不存在兄弟）。head 无向量世代时词面是唯一车道，扩展同样生效。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from simple_harness.contracts import canonical_json

from simple_harness_memory.features.cognitive_vector import cognitive_text_supplement

#: 争议槽位文本的格式版本；只影响词面门，不进入 manifest / hash 域。
CONFLICT_SLOT_TEXT_VERSION = 1

#: 冲突组词面**准入基底**的格式版本（0.6.37）。槽位文本本身未变，故
#: ``CONFLICT_SLOT_TEXT_VERSION`` 保持 1；准入基底是"槽位文本 + head 上下文"的合成，
#: 单独编号。同样只影响词面门，不进入 manifest / hash 域。
CONFLICT_ADMISSION_TEXT_VERSION = 1

#: head 上下文字段（0.6.37）：group 所属 head 当前 revision 的"属于谁 / 在什么条件下成立"。
#: 今天只有 semantic 的公开 payload 带这两个字段，其余类型取不到即为空（不臆造语义）。
CONTESTED_HEAD_CONTEXT_FIELDS: tuple[str, ...] = ("subject_entity", "qualifiers")

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


def contested_head_context_text(
    memory_type: str, head_payload: Mapping[str, Any] | None
) -> str:
    """返回 group 所属 head 当前 revision 的上下文文本（casefold 前的原文）。

    只取 ``CONTESTED_HEAD_CONTEXT_FIELDS``（``subject_entity`` / ``qualifiers``），
    以 ``{field: value}`` 的 canonical JSON 逐字段拼接；字段缺失或为 ``None`` 则跳过。
    未知类型、非 Mapping 输入 → 空串（fail closed：词面门永不因此命中）。
    """

    if memory_type not in _SLOT_NAME_FIELDS or not isinstance(head_payload, Mapping):
        return ""
    parts: list[str] = []
    for field in CONTESTED_HEAD_CONTEXT_FIELDS:
        value = head_payload.get(field)
        if value is None:
            continue
        parts.append(canonical_json({field: value}))
    return "\n".join(parts)


def contested_admission_text(
    memory_type: str,
    incumbent_payload: Mapping[str, Any],
    challenger_payload: Mapping[str, Any],
    *,
    head_payload: Mapping[str, Any] | None = None,
) -> str:
    """冲突组的词面**准入基底**（0.6.37 / F-V-2）：槽位文本 ∪ head 上下文。

    ``head_payload`` 是该 group 所属 head **当前 revision** 的公开 payload（即
    challenger 那一版；``cognitive_memory_heads.current_revision`` 与
    ``cognitive_conflict_groups.challenger_revision`` 相等是 confirmation 收集的
    查询前提）。传 ``None`` 即退回 0.6.31 的槽位文本，行为逐字不变。

    只读**公开** payload（已过隐私门与抑制门），因此这条扩展不会让任何一个字
    绕过 §5.2；它只决定"这个组这次算不算相关"，不改变披露内容。
    """

    slot = contested_slot_text(memory_type, incumbent_payload, challenger_payload)
    head = contested_head_context_text(memory_type, head_payload)
    return "\n".join(part for part in (slot, head) if part)


__all__ = (
    "CONFLICT_ADMISSION_TEXT_VERSION",
    "CONFLICT_SLOT_TEXT_VERSION",
    "CONTESTED_HEAD_CONTEXT_FIELDS",
    "contested_admission_text",
    "contested_head_context_text",
    "contested_slot_text",
)
