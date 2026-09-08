"""F-S1b：`check_history_visibility` 的离线 Procedure 适用性入口（0.6.36）。

0.6.35 之前 `backends/history_visibility.py` 对 `_validate_recall_context_use_sources_unlocked`
写死 `procedure_applicability_fingerprints=frozenset()`（注释：*never reuse old runtime
fingerprints*），于是任何 Procedure 来源在这道门上恒为 `RECALL_AUTHORITY_STALE`
→ `history_source_stale`。Host 分析车道用它复核关系端点候选，因此只能在下发之前按名扣下
所有 Procedure 端点（`sdk_procedure_endpoint_unresolvable`），A6-6 的 Procedure 形态不可达。

本文件钉死这次扩面的两半：

* **缺省不变**——不提供 attestation 时，行为与收据 JSON 与 0.6.35 逐字相同（Procedure 仍 stale，
  快照里连键都不多一个）；
* **提供时最窄**——只影响 `HistoryRecallBinding` 的来源复核，且 caller 提供的指纹必须被
  Memory 自己的 `procedure_observations` 审计佐证（成功、可归因），provenance 与逐条命中
  写进快照收据。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
import simple_harness as h
from simple_harness.runtime import (
    LongTermMemoryType,
    RecallDecisionOutcome,
    RecallRetrievalMode,
    RecallSelectorDomain,
)

import simple_harness_memory as m
from simple_harness_memory.core.errors import MemoryCorruptionError, MemoryValidationError
from simple_harness_memory.core.identity import MemoryScope
from tests.integration.test_cognitive_mutation_repository_v5 import (
    _disclosure,
    _operation,
    _plan,
    _principal,
    _tamper_immutable_table,
)
from tests.integration.test_procedure_relation_endpoint import (
    _active_procedure,
    _apply_head,
    _reopen,
)
from tests.integration.test_typed_recall_v6 import _context, _recall_plan

PROVENANCE = m.ProcedureApplicabilityProvenance.APPLIED_USE_FINGERPRINTS


async def _fingerprint(backend, memory_id: str, revision: int) -> str:
    async with backend.connection.execute(
        "SELECT applicability_fingerprint FROM procedure_records WHERE memory_id=? AND revision=?",
        (memory_id, revision),
    ) as cursor:
        return str((await cursor.fetchone())[0])  # type: ignore[index]


async def _procedure_binding(backend, fingerprint: str, *, key: str):
    """The exact durable typed-recall item a Host analysis lane would bind."""

    context = _context(
        query="publish report",
        memory_types=(LongTermMemoryType.PROCEDURE,),
        selectors=(RecallSelectorDomain.MEMORY_TYPE,),
        modes=(RecallRetrievalMode.FULL_TEXT,),
        procedure_applicability_fingerprints=(fingerprint,),
    )
    execution = await backend.execute_typed_recall(
        principal=_principal(), context=context, plan=_recall_plan(context, idempotency_key=key)
    )
    assert execution.decision.outcome is RecallDecisionOutcome.RECALL
    assert len(execution.result.items) == 1
    item = execution.result.items[0]
    binding = m.HistoryRecallBinding(
        execution.result.result_id,
        execution.result.result_hash,
        item.selected_item.item_id,
        item.result_item_hash,
    )
    return binding, item


async def _check(backend, *bindings, attestation=None):
    kwargs = {} if attestation is None else {"procedure_applicability": attestation}
    return await backend.check_history_visibility(
        principal=_principal(),
        disclosure_context=_disclosure(),
        bindings=tuple(bindings),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_procedure_recall_binding_stays_stale_without_an_attestation(tmp_path: Path) -> None:
    """缺省行为逐字保留：没有 attestation，Procedure 仍然 stale，收据 JSON 不多一个键。"""

    clock = [20.0]
    backend, _authority, _evidence, memory_id, revision = await _active_procedure(
        tmp_path / "applicability-default.db", clock
    )
    try:
        fingerprint = await _fingerprint(backend, memory_id, revision)
        binding, _item = await _procedure_binding(backend, fingerprint, key="default-recall")
        snapshot = await _check(backend, binding)
        assert [(x.visible, x.reason) for x in snapshot.items] == [(False, "history_source_stale")]
        # 0.6.35 的收据形状：既没有字段值，也没有键。
        assert snapshot.procedure_applicability is None
        assert "procedure_applicability" not in snapshot.to_json()
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_attested_applied_use_fingerprints_admit_the_procedure_binding(
    tmp_path: Path,
) -> None:
    """F-S1b 的正面用例：同一条绑定，带 attestation 就可见，且 provenance 入收据。"""

    clock = [20.0]
    backend, _authority, _evidence, memory_id, revision = await _active_procedure(
        tmp_path / "applicability-admit.db", clock
    )
    try:
        fingerprint = await _fingerprint(backend, memory_id, revision)
        binding, _item = await _procedure_binding(backend, fingerprint, key="admit-recall")
        attestation = m.ProcedureApplicabilityAttestation(PROVENANCE, (fingerprint,))
        snapshot = await _check(backend, binding, attestation=attestation)
        assert [(x.visible, x.reason) for x in snapshot.items] == [(True, "history_visible")]

        receipt = snapshot.procedure_applicability
        assert receipt is not None
        assert receipt.provenance == "applied_use_fingerprints"
        assert receipt.attestation_hash == attestation.attestation_hash
        assert receipt.fingerprint_count == 1
        # 逐条命中：这条绑定之所以可见，就是因为这份 attestation。
        assert receipt.admitted_binding_hashes == (snapshot.items[0].binding_hash,)
        assert snapshot.to_json()["procedure_applicability"] == receipt.to_json()

        # 确定性：同一时钟、同一请求两次调用逐字相同（含 request_hash 与 snapshot_hash）。
        again = await _check(backend, binding, attestation=attestation)
        assert again.to_json() == snapshot.to_json()
        assert again.snapshot_hash == snapshot.snapshot_hash
        # 而请求哈希确实把 attestation 算了进去：不带的那次不是同一个请求。
        bare = await _check(backend, binding)
        assert bare.request_hash != snapshot.request_hash
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_attestation_without_the_endpoint_fingerprint_admits_nothing(
    tmp_path: Path,
) -> None:
    """指纹对不上就不放行，收据仍然如实记下「提交过 attestation，但一条都没放行」。"""

    clock = [20.0]
    backend, _authority, _evidence, memory_id, revision = await _active_procedure(
        tmp_path / "applicability-wrong.db", clock
    )
    try:
        fingerprint = await _fingerprint(backend, memory_id, revision)
        binding, _item = await _procedure_binding(backend, fingerprint, key="wrong-recall")
        other = m.ProcedureApplicabilityAttestation(PROVENANCE, ("some-other-fingerprint",))
        snapshot = await _check(backend, binding, attestation=other)
        assert [(x.visible, x.reason) for x in snapshot.items] == [(False, "history_source_stale")]
        assert snapshot.procedure_applicability is not None
        assert snapshot.procedure_applicability.admitted_binding_hashes == ()
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_attestation_memorys_own_observation_audit_does_not_corroborate_is_refused(
    tmp_path: Path,
) -> None:
    """caller 说了不算：指纹还必须被 Memory 自己消费过的成功可归因观测佐证。

    健康库上这一条恒成立——bound fingerprint 只能由观测提交写入——所以要单独量出它，
    只能把 ``procedure_observations`` 改掉。本文件唯一在**打开的连接上**篡改的用例，
    理由在末尾自证：这样的库根本重开不了（观测审计链复核 fail closed），
    「关掉→篡改→重开」在这条形状上不可达。这同时也是 (c) 这道门站得住的根据：
    佐证来源本身被链锚定，改不动而不被发现。
    """

    clock = [20.0]
    path = tmp_path / "applicability-uncorroborated.db"
    backend, authority, _evidence, memory_id, revision = await _active_procedure(path, clock)
    fingerprint = await _fingerprint(backend, memory_id, revision)
    binding, _item = await _procedure_binding(backend, fingerprint, key="uncorroborated-recall")
    attestation = m.ProcedureApplicabilityAttestation(PROVENANCE, (fingerprint,))
    # 篡改之前，同一条绑定带 attestation 是可见的。
    assert (await _check(backend, binding, attestation=attestation)).items[0].visible

    # 三条观测都改成另一个指纹：procedure_records 不动，于是 caller 提交的那个指纹
    # 仍然与端点这一版逐字相等（(b) 通过），但没有任何一条观测背书它（(c) 不通过）。
    _tamper_immutable_table(
        path,
        "procedure_observations",
        "UPDATE procedure_observations SET applicability_fingerprint='drifted-fingerprint'",
    )
    try:
        snapshot = await _check(backend, binding, attestation=attestation)
        assert [(x.visible, x.reason) for x in snapshot.items] == [(False, "history_source_stale")]
        assert snapshot.procedure_applicability is not None
        assert snapshot.procedure_applicability.admitted_binding_hashes == ()
    finally:
        # 正常 close 会跑完整性校验，而这个库是故意损坏的：直接释放连接。
        await backend.connection.close()
    reopened = _reopen(path, authority, clock)
    with pytest.raises(MemoryCorruptionError, match="procedure observation columns differ"):
        await reopened.initialize()


@pytest.mark.asyncio
async def test_attestation_never_touches_non_procedure_bindings(tmp_path: Path) -> None:
    """扩面只作用于 Procedure：同一批里的 semantic 绑定逐字不受影响，也不进命中清单。"""

    clock = [20.0]
    backend, _authority, evidence, memory_id, revision = await _active_procedure(
        tmp_path / "applicability-scope.db", clock
    )
    try:
        envelope, _receipt, span = evidence[6]
        await backend.apply_memory_mutation_plan(
            principal=_principal(),
            scope=MemoryScope.personal("actor-1"),
            plan=_plan(
                envelope,
                _operation(span, operation_id="scope-semantic-operation"),
                base_revision=await _apply_head(backend),
                plan_id="scope-semantic-plan",
                idempotency_key="scope-semantic-key",
            ),
        )
        semantic_context = _context(memory_types=(LongTermMemoryType.SEMANTIC,))
        semantic = await backend.execute_typed_recall(
            principal=_principal(),
            context=semantic_context,
            plan=_recall_plan(semantic_context, idempotency_key="scope-semantic"),
        )
        assert semantic.result.items
        item = semantic.result.items[0]
        semantic_binding = m.HistoryRecallBinding(
            semantic.result.result_id,
            semantic.result.result_hash,
            item.selected_item.item_id,
            item.result_item_hash,
        )
        fingerprint = await _fingerprint(backend, memory_id, revision)
        procedure_binding, _procedure_item = await _procedure_binding(
            backend, fingerprint, key="scope-procedure"
        )
        attestation = m.ProcedureApplicabilityAttestation(PROVENANCE, (fingerprint,))

        bare = await _check(backend, semantic_binding)
        attested = await _check(
            backend, semantic_binding, procedure_binding, attestation=attestation
        )
        # 逐字同结果：同一条 semantic 绑定的 item JSON 与到期时间都不因 attestation 而变。
        assert bare.items[0].to_json() == attested.items[0].to_json()
        assert bare.items[0].reason == "history_visible"
        assert bare.valid_until == attested.valid_until
        assert attested.items[1].visible
        # 只有 Procedure 那一条进命中清单。
        assert attested.procedure_applicability is not None
        assert attested.procedure_applicability.admitted_binding_hashes == (
            attested.items[1].binding_hash,
        )
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_attestation_is_rejected_on_the_current_input_entry_point(tmp_path: Path) -> None:
    """当前输入观察入口本来就不授予普通披露，绝不能变成 Procedure 的第二道门。"""

    from simple_harness_memory.backends.history_visibility import check_history_visibility

    clock = [20.0]
    backend, _authority, evidence, memory_id, revision = await _active_procedure(
        tmp_path / "applicability-current-input.db", clock
    )
    try:
        fingerprint = await _fingerprint(backend, memory_id, revision)
        binding, _item = await _procedure_binding(backend, fingerprint, key="current-input-recall")
        attestation = m.ProcedureApplicabilityAttestation(PROVENANCE, (fingerprint,))
        envelope, receipt, _span = evidence[0]
        evidence_binding = m.HistoryEvidenceBinding(envelope, receipt)
        with pytest.raises(MemoryValidationError) as excinfo:
            await check_history_visibility(
                backend,
                principal=_principal(),
                disclosure_context=_disclosure(),
                bindings=(evidence_binding,),
                procedure_applicability=attestation,
                _current_input=(evidence_binding, "a" * 64),
            )
        assert str(excinfo.value) == "history_current_input_rejects_procedure_applicability"

        # 非 canonical 类型同样在门口就被拒（与 principal/disclosure 同一纪律）。
        with pytest.raises(TypeError):
            await _check(backend, binding, attestation=(fingerprint,))
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_attestation_is_disclosure_bound_like_every_other_history_check(
    tmp_path: Path,
) -> None:
    """attestation 不绕过任何既有门：披露不允许时 Procedure 仍然不可见。"""

    clock = [20.0]
    backend, _authority, _evidence, memory_id, revision = await _active_procedure(
        tmp_path / "applicability-disclosure.db", clock
    )
    try:
        fingerprint = await _fingerprint(backend, memory_id, revision)
        binding, _item = await _procedure_binding(backend, fingerprint, key="disclosure-recall")
        attestation = m.ProcedureApplicabilityAttestation(PROVENANCE, (fingerprint,))
        stale = replace(_disclosure(), generation=h.DisclosureGeneration.STALE)
        snapshot = await backend.check_history_visibility(
            principal=_principal(),
            disclosure_context=stale,
            bindings=(binding,),
            procedure_applicability=attestation,
        )
        assert not snapshot.items[0].visible
        assert snapshot.procedure_applicability is not None
        assert snapshot.procedure_applicability.admitted_binding_hashes == ()
    finally:
        await backend.close()


def test_attestation_canonical_form_is_fail_closed() -> None:
    """构造期就把非 canonical 形状挡住：收据哈希必须由集合唯一决定。"""

    assert m.ProcedureApplicabilityAttestation(PROVENANCE, ("a", "b")).fingerprints == ("a", "b")
    for bad in (
        ("b", "a"),  # 未排序
        ("a", "a"),  # 重复
        (),  # 空集合应当直接不提交 attestation
        tuple(f"f{i:04d}" for i in range(257)),  # 越界
    ):
        with pytest.raises(ValueError):  # MemoryValidationError 也是 ValueError
            m.ProcedureApplicabilityAttestation(PROVENANCE, bad)
    with pytest.raises(ValueError):
        m.ProcedureApplicabilityAttestation("applied_use_fingerprints", ("a",))
    with pytest.raises(MemoryValidationError):  # _identifier 的形状拒绝
        m.ProcedureApplicabilityAttestation(PROVENANCE, ("",))
    with pytest.raises(ValueError):
        m.ProcedureApplicabilityAttestation(PROVENANCE, ["a"])
    # 同一集合两次构造哈希逐字相同，不同集合不同。
    one = m.ProcedureApplicabilityAttestation(PROVENANCE, ("a", "b"))
    assert one.attestation_hash == m.ProcedureApplicabilityAttestation(
        PROVENANCE, ("a", "b")
    ).attestation_hash
    assert one.attestation_hash != m.ProcedureApplicabilityAttestation(
        PROVENANCE, ("a",)
    ).attestation_hash


@pytest.mark.asyncio
async def test_manager_facade_forwards_only_when_supplied(tmp_path: Path) -> None:
    """公共 facade：不提供时不向后端传这个 kwarg，早于 0.6.36 的后端因此照常工作。"""

    clock = [20.0]
    backend, _authority, _evidence, memory_id, revision = await _active_procedure(
        tmp_path / "applicability-facade.db", clock
    )
    try:
        fingerprint = await _fingerprint(backend, memory_id, revision)
        binding, _item = await _procedure_binding(backend, fingerprint, key="facade-recall")
        manager = m.MemoryManager(backend, None)
        seen: list[tuple[str, ...]] = []
        original = backend.check_history_visibility

        async def spy(**kwargs):
            seen.append(tuple(sorted(kwargs)))
            return await original(**kwargs)

        backend.check_history_visibility = spy  # type: ignore[method-assign]
        try:
            plain = await manager.check_history_visibility(
                principal=_principal(),
                disclosure_context=_disclosure(),
                bindings=(binding,),
            )
            attested = await manager.check_history_visibility(
                principal=_principal(),
                disclosure_context=_disclosure(),
                bindings=(binding,),
                procedure_applicability=m.ProcedureApplicabilityAttestation(
                    PROVENANCE, (fingerprint,)
                ),
            )
        finally:
            backend.check_history_visibility = original  # type: ignore[method-assign]
        assert seen == [
            ("bindings", "disclosure_context", "principal"),
            ("bindings", "disclosure_context", "principal", "procedure_applicability"),
        ]
        assert not plain.items[0].visible
        assert attested.items[0].visible
    finally:
        await backend.close()
