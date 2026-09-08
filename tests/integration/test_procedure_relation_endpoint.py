"""F-S1：观测提交的 Procedure 版本作为 semantic_relation 端点。

Procedure 只有走满三次独立成功观测才进入 ``active``/``reinforced``，才可能被召回、
才可能被分析车道当作关系端点下发。但观测提交走的是 ``_copy_cognitive_revision_unlocked``：
它逐字复制 content/隐私类/信息属性，**不**重新跑分类策略，因此新 revision 上没有
``cognitive_classification_decisions`` 行。0.6.34 的端点解析在 head revision 上直接查这张表，
于是对每一条「真的可用」的 Procedure 端点抛
``MemoryCorruptionError('relation endpoint classification is missing')``，整批分析死掉。

本文件把「分类决定由血缘上最近的已分类祖先 revision 承担」钉死，同时保留真正断裂血缘
（没有任何已分类祖先 / 祖先与端点的隐私类·属性·内容哈希不一致）仍然是 corruption。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from simple_harness.contracts import canonical_json
from simple_harness.runtime import (
    CreatedByOperationTarget,
    ExistingMemoryTarget,
    LongTermMemoryType,
    ProcedureLifecycleState,
    ProspectiveLifecycleState,
    ProspectiveSignalKind,
    RecallDecisionOutcome,
    RecallRetrievalMode,
    RecallSelectorDomain,
    SemanticRelationKind,
    SemanticRelationMemoryPayload,
)

from simple_harness_memory.backends.sqlite_v5 import SQLiteHumanMemoryBackend
from simple_harness_memory.core.errors import MemoryCorruptionError
from simple_harness_memory.core.identity import MemoryScope
from tests.integration.test_cognitive_mutation_repository_v5 import (
    _classification_policy,
    _operation,
    _plan,
    _prepared,
    _principal,
    _tamper_immutable_table,
)
from tests.integration.test_procedure_observation_repository_v5 import _grant, _setup
from tests.integration.test_prospective_signal_repository_v5 import _grant as prospective_grant
from tests.integration.test_prospective_signal_repository_v5 import (
    _operation as prospective_operation,
)
from tests.integration.test_prospective_signal_repository_v5 import _ProspectiveAuthority
from tests.integration.test_typed_recall_v6 import _context, _recall_plan

_RELATION_EVIDENCE_INDEX = 6


async def _active_procedure(
    path: Path, clock: list[float]
) -> tuple[SQLiteHumanMemoryBackend, object, list, str, int]:
    """Drive one Procedure to ``active`` through three real observation commits."""

    backend, authority, evidence, memory_id, revision = await _setup(path, clock)
    transitions = (
        (1, ProcedureLifecycleState.DRAFT, ProcedureLifecycleState.DRAFT),
        (3, ProcedureLifecycleState.DRAFT, ProcedureLifecycleState.ELIGIBLE_FOR_ACTIVATION),
        (4, ProcedureLifecycleState.ELIGIBLE_FOR_ACTIVATION, ProcedureLifecycleState.ACTIVE),
    )
    for offset, (index, transition_from, transition_to) in enumerate(transitions):
        reference = _grant(
            authority,
            evidence,
            memory_id=memory_id,
            revision=revision + offset,
            index=index,
            transition_from=transition_from,
            transition_to=transition_to,
        )
        result = await backend.record_procedure_observation(
            principal=_principal(),
            scope=MemoryScope.personal("actor-1"),
            reference=reference,
        )
    assert result.lifecycle_state is ProcedureLifecycleState.ACTIVE
    assert result.committed_revision == revision + 3
    return backend, authority, evidence, memory_id, result.committed_revision


async def _apply_head(backend: SQLiteHumanMemoryBackend) -> int:
    async with backend.connection.execute(
        "SELECT revision FROM cognitive_apply_heads WHERE principal_id='actor-1'"
    ) as cursor:
        row = await cursor.fetchone()
    return 1 if row is None else int(row[0])


def _relation_plan(evidence, *, memory_id: str, revision: int, base_revision: int):
    envelope, _receipt, span = evidence[_RELATION_EVIDENCE_INDEX - 1]
    source = _operation(span, operation_id="create-source")
    relation = replace(
        _operation(span, operation_id="create-relation", depends_on=(source.operation_id,)),
        payload=SemanticRelationMemoryPayload(
            SemanticRelationKind.APPLIES_TO,
            CreatedByOperationTarget(source.operation_id),
            ExistingMemoryTarget(memory_id, revision),
        ),
    )
    return _plan(
        envelope,
        source,
        relation,
        base_revision=base_revision,
        plan_id="procedure-endpoint-plan",
        idempotency_key="procedure-endpoint-key",
    )


def _reopen(path: Path, authority: object, clock: list[float]) -> SQLiteHumanMemoryBackend:
    return SQLiteHumanMemoryBackend(
        path,
        now=lambda: clock[0],
        evidence_authority=authority,
        conversation_evidence_authority=authority,
        procedure_observation_authority=authority,
        memory_action_authority=authority,
        classification_policy=_classification_policy(),
    )


async def _classification_revisions(backend: SQLiteHumanMemoryBackend, memory_id: str):
    async with backend.connection.execute(
        "SELECT memory_revision FROM cognitive_classification_decisions "
        "WHERE memory_id=? ORDER BY memory_revision",
        (memory_id,),
    ) as cursor:
        return tuple(int(row[0]) for row in await cursor.fetchall())


@pytest.mark.asyncio
async def test_observation_committed_procedure_endpoint_resolves_and_projects_edge(
    tmp_path: Path,
) -> None:
    """复现 F-S1 并钉死修复：head 是观测提交出来的 revision 4，分类行只有 revision 1。"""

    clock = [20.0]
    path = tmp_path / "procedure-endpoint.db"
    backend, _authority, evidence, procedure_id, procedure_revision = await _active_procedure(
        path, clock
    )
    try:
        # 事故现场的形状：head revision 4，分类行只有 revision 1，证据 span 逐版复制。
        assert procedure_revision == 4
        assert await _classification_revisions(backend, procedure_id) == (1,)
        async with backend.connection.execute(
            "SELECT COUNT(*) FROM cognitive_evidence_spans WHERE memory_id=? AND revision=?",
            (procedure_id, procedure_revision),
        ) as cursor:
            assert int((await cursor.fetchone())[0]) >= 1  # type: ignore[index]

        plan = _relation_plan(
            evidence,
            memory_id=procedure_id,
            revision=procedure_revision,
            base_revision=await _apply_head(backend),
        )
        # 0.6.34 在这里抛 MemoryCorruptionError('relation endpoint classification is missing')。
        await backend.apply_memory_mutation_plan(
            principal=_principal(), scope=MemoryScope.personal("actor-1"), plan=plan
        )

        async with backend.connection.execute(
            "SELECT relation_domain,source_memory_id,relation_kind,target_memory_id,"
            "target_revision FROM cognitive_relations"
        ) as cursor:
            rows = tuple(await cursor.fetchall())
        assert len(rows) == 1
        relation_row = rows[0]
        assert str(relation_row["relation_domain"]) == "knowledge"
        assert str(relation_row["relation_kind"]) == "applies_to"
        assert str(relation_row["target_memory_id"]) == procedure_id
        assert int(relation_row["target_revision"]) == procedure_revision
        source_id = str(relation_row["source_memory_id"])

        # 观测提交不产生新的分类行：修复只改读，不改写。
        assert await _classification_revisions(backend, procedure_id) == (1,)

        graph = await backend.get_twin_graph_view(principal=_principal())
        assert len(graph.edges) == 1
        edge = graph.edges[0]
        assert edge.relation_kind == "applies_to"
        assert edge.source_node_id == f"{source_id}@1"
        assert edge.target_node_id == f"{procedure_id}@{procedure_revision}"
        node_ids = {node.node_id for node in graph.nodes}
        assert {edge.source_node_id, edge.target_node_id} <= node_ids
    finally:
        await backend.close()

    reopened = SQLiteHumanMemoryBackend(path)
    try:
        await reopened.initialize()
        reopened_graph = await reopened.get_twin_graph_view(principal=_principal())
        assert reopened_graph.edges == graph.edges
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_relation_endpoint_procedure_is_typed_recallable_at_the_same_revision(
    tmp_path: Path,
) -> None:
    """端点必须是「真的能被召回的那一版」：typed recall 与关系边指向同一个 exact revision。"""

    clock = [20.0]
    backend, _authority, evidence, procedure_id, procedure_revision = await _active_procedure(
        tmp_path / "procedure-endpoint-recall.db", clock
    )
    try:
        plan = _relation_plan(
            evidence,
            memory_id=procedure_id,
            revision=procedure_revision,
            base_revision=await _apply_head(backend),
        )
        await backend.apply_memory_mutation_plan(
            principal=_principal(), scope=MemoryScope.personal("actor-1"), plan=plan
        )
        async with backend.connection.execute(
            "SELECT applicability_fingerprint FROM procedure_records "
            "WHERE memory_id=? AND revision=?",
            (procedure_id, procedure_revision),
        ) as cursor:
            fingerprint = str((await cursor.fetchone())[0])  # type: ignore[index]
        context = _context(
            query="publish report",
            memory_types=(LongTermMemoryType.PROCEDURE,),
            selectors=(RecallSelectorDomain.MEMORY_TYPE,),
            modes=(RecallRetrievalMode.FULL_TEXT,),
            procedure_applicability_fingerprints=(fingerprint,),
        )
        execution = await backend.execute_typed_recall(
            principal=_principal(),
            context=context,
            plan=_recall_plan(context, idempotency_key="procedure-endpoint-recall"),
        )
        assert execution.decision.outcome is RecallDecisionOutcome.RECALL
        recalled = {
            (str(item.selected_item.source_ref), int(item.selected_item.source_revision))
            for item in execution.result.items
        }
        # 载荷断言：召回回来的 exact revision 必须与**落库的那条边**指向同一版，
        # 而不是与同一个 Python 变量比较——否则删掉上面的 apply 用例照样绿。
        async with backend.connection.execute(
            "SELECT target_memory_id,target_revision FROM cognitive_relations"
        ) as cursor:
            edge_rows = tuple(await cursor.fetchall())
        assert len(edge_rows) == 1
        edge_endpoint = (str(edge_rows[0][0]), int(edge_rows[0][1]))
        assert edge_endpoint in recalled
        assert edge_endpoint == (procedure_id, procedure_revision)
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_relation_endpoint_without_any_classified_ancestor_stays_corrupt(
    tmp_path: Path,
) -> None:
    """血缘上一条分类决定都没有 = 真损坏，仍然 MemoryCorruptionError（语句与 0.6.34 逐字相同）。

    这是本文件唯一一处在**打开的连接上**篡改的用例，理由在用例末尾自证：这样的库
    根本重开不了（收据复核先一步 fail closed），所以「关掉→篡改→重开」在这条形状上
    不可达。用例把这一点也断言下来，顺带说明为什么 teardown 不能走正常 close。
    """

    clock = [20.0]
    path = tmp_path / "procedure-endpoint-unclassified.db"
    backend, authority, evidence, procedure_id, procedure_revision = await _active_procedure(
        path, clock
    )
    plan = _relation_plan(
        evidence,
        memory_id=procedure_id,
        revision=procedure_revision,
        base_revision=await _apply_head(backend),
    )
    # 整条分类链一起摘掉（先子后父，避免留下悬空引用），
    # 模拟「血缘上一条已分类祖先都没有」的真损坏库。
    for table, statement in (
        (
            "cognitive_classification_evidence_authorities",
            "DELETE FROM cognitive_classification_evidence_authorities "
            "WHERE classification_decision_id IN (SELECT classification_decision_id "
            f"FROM cognitive_classification_decisions WHERE memory_id='{procedure_id}')",
        ),
        (
            "memory_mutation_decisions",
            "DELETE FROM memory_mutation_decisions "
            "WHERE classification_decision_id IN (SELECT classification_decision_id "
            f"FROM cognitive_classification_decisions WHERE memory_id='{procedure_id}')",
        ),
        (
            "cognitive_classification_decisions",
            f"DELETE FROM cognitive_classification_decisions WHERE memory_id='{procedure_id}'",
        ),
    ):
        _tamper_immutable_table(path, table, statement)
    try:
        with pytest.raises(MemoryCorruptionError, match="classification is missing"):
            await backend.apply_memory_mutation_plan(
                principal=_principal(), scope=MemoryScope.personal("actor-1"), plan=plan
            )
        async with backend.connection.execute(
            "SELECT COUNT(*) FROM cognitive_relations"
        ) as cursor:
            assert int((await cursor.fetchone())[0]) == 0  # type: ignore[index]
    finally:
        # 正常 close 会跑完整性校验，而这个库是故意损坏的：直接释放连接。
        await backend.connection.close()
    # 纵深：这样的库连打开都不该成功——分类链复核在端点解析之前就 fail closed。
    reopened = _reopen(path, authority, clock)
    with pytest.raises(MemoryCorruptionError):
        await reopened.initialize()


@pytest.mark.asyncio
async def test_relation_endpoint_whose_decision_no_longer_describes_it_is_corrupt(
    tmp_path: Path,
) -> None:
    """管辖决定的 effective 分类不再描述端点这一版（属性被改写）= 真损坏，不许继承。"""

    clock = [20.0]
    path = tmp_path / "procedure-endpoint-drifted.db"
    backend, authority, evidence, procedure_id, procedure_revision = await _active_procedure(
        path, clock
    )
    async with backend.connection.execute(
        "SELECT information_attributes_json FROM cognitive_memory_revisions "
        "WHERE memory_id=? AND revision=?",
        (procedure_id, procedure_revision),
    ) as cursor:
        attributes = json.loads(str((await cursor.fetchone())[0]))  # type: ignore[index]
    assert attributes == ["work"]
    plan = _relation_plan(
        evidence,
        memory_id=procedure_id,
        revision=procedure_revision,
        base_revision=await _apply_head(backend),
    )
    await backend.close()
    _tamper_immutable_table(
        path,
        "cognitive_memory_revisions",
        "UPDATE cognitive_memory_revisions SET information_attributes_json='[\"health\"]' "
        f"WHERE memory_id='{procedure_id}' AND revision={procedure_revision}",
    )
    reopened = _reopen(path, authority, clock)
    try:
        await reopened.initialize()
        with pytest.raises(MemoryCorruptionError, match="endpoint classification differs"):
            await reopened.apply_memory_mutation_plan(
                principal=_principal(), scope=MemoryScope.personal("actor-1"), plan=plan
            )
        async with reopened.connection.execute(
            "SELECT COUNT(*) FROM cognitive_relations"
        ) as cursor:
            assert int((await cursor.fetchone())[0]) == 0  # type: ignore[index]
    finally:
        await reopened.connection.close()


@pytest.mark.asyncio
async def test_relation_endpoint_content_forked_from_its_classified_ancestor_is_corrupt(
    tmp_path: Path,
) -> None:
    """伪造的「复制后代」：内容与 hash 一致地改掉，但已不是那条已分类 revision 的复制。

    这正是继承路径新增的那道校验要挡住的对手——它必须先绕过不可变触发器，
    再把 content_json 与 content_hash 改成自洽的一对（否则更早的内容门就先报错）。
    """

    clock = [20.0]
    path = tmp_path / "procedure-endpoint-forked.db"
    backend, authority, evidence, procedure_id, procedure_revision = await _active_procedure(
        path, clock
    )
    async with backend.connection.execute(
        "SELECT content_json FROM cognitive_memory_revisions "
        "WHERE memory_id=? AND revision=?",
        (procedure_id, procedure_revision),
    ) as cursor:
        content = json.loads(str((await cursor.fetchone())[0]))  # type: ignore[index]
    content["name"] = "publish report (forked)"
    forked_json = canonical_json(content)
    forked_hash = hashlib.sha256(forked_json.encode("utf-8")).hexdigest()
    plan = _relation_plan(
        evidence,
        memory_id=procedure_id,
        revision=procedure_revision,
        base_revision=await _apply_head(backend),
    )
    await backend.close()
    _tamper_immutable_table(
        path,
        "cognitive_memory_revisions",
        "UPDATE cognitive_memory_revisions SET "
        f"content_json='{forked_json.replace(chr(39), chr(39) * 2)}',"
        f"content_hash='{forked_hash}' "
        f"WHERE memory_id='{procedure_id}' AND revision={procedure_revision}",
    )
    reopened = _reopen(path, authority, clock)
    try:
        await reopened.initialize()
        with pytest.raises(MemoryCorruptionError, match="classification lineage differs"):
            await reopened.apply_memory_mutation_plan(
                principal=_principal(), scope=MemoryScope.personal("actor-1"), plan=plan
            )
        async with reopened.connection.execute(
            "SELECT COUNT(*) FROM cognitive_relations"
        ) as cursor:
            assert int((await cursor.fetchone())[0]) == 0  # type: ignore[index]
    finally:
        await reopened.connection.close()


@pytest.mark.asyncio
async def test_signal_committed_prospective_endpoint_resolves_and_projects_edge(
    tmp_path: Path,
) -> None:
    """同一条继承路径对 Prospective 同样成立：信号提交出来的 revision 2 是合法端点。

    ``apply_prospective_signal`` 的 APPLIED 分支与 Procedure 观测提交共用
    ``_copy_cognitive_revision_unlocked``，因此 0.6.34 上任何**已被触发**的 Prospective
    端点同样会抛 `classification is missing`；今天 Host 下发的 Prospective 端点都还停在
    revision 1，所以没有撞上。这条用例把那条尚未被真实流量走到的路一并钉死。
    """

    clock = [20.0]
    path = tmp_path / "prospective-endpoint.db"
    seed, envelope, receipt, span, evidence_authority = await _prepared(
        path.with_suffix(".seed"), now=lambda: clock[0]
    )
    await seed.close()
    authority = _ProspectiveAuthority(evidence_authority)
    backend = SQLiteHumanMemoryBackend(
        path,
        now=lambda: clock[0],
        evidence_authority=authority,
        prospective_signal_authority=authority,
        memory_action_authority=authority,
        classification_policy=_classification_policy(),
    )
    try:
        await backend.initialize()
        await backend.ingest_committed_evidence(envelope, receipt)
        await backend.apply_memory_mutation_plan(
            principal=_principal(),
            scope=MemoryScope.personal("actor-1"),
            plan=_plan(envelope, prospective_operation(span)),
        )
        async with backend.connection.execute(
            "SELECT h.memory_id,h.current_revision,o.outbox_id,o.payload_hash "
            "FROM cognitive_memory_heads h JOIN outbox o ON o.principal_id=h.principal_id "
            "WHERE o.topic='memory.prospective.registration.requested'"
        ) as cursor:
            head = await cursor.fetchone()
        assert head is not None
        prospective_id, prospective_revision = str(head[0]), int(head[1])
        outbox_id, outbox_hash = str(head[2]), str(head[3])

        accepted = prospective_grant(
            authority,
            memory_id=prospective_id,
            revision=prospective_revision,
            kind=ProspectiveSignalKind.REGISTRATION_ACCEPTED,
            transition_from=ProspectiveLifecycleState.PENDING,
            transition_to=ProspectiveLifecycleState.PENDING,
            observed_at=20.0,
            outbox_id=outbox_id,
            outbox_hash=outbox_hash,
        )
        await backend.apply_prospective_signal(
            principal=_principal(),
            scope=MemoryScope.personal("actor-1"),
            reference=accepted,
        )

        clock[0] = 30.0
        due = prospective_grant(
            authority,
            memory_id=prospective_id,
            revision=prospective_revision,
            kind=ProspectiveSignalKind.TIME_DUE,
            transition_from=ProspectiveLifecycleState.PENDING,
            transition_to=ProspectiveLifecycleState.TRIGGERED,
            observed_at=30.0,
            signal_id="due-signal",
            receipt_id="due-receipt",
        )
        applied = await backend.apply_prospective_signal(
            principal=_principal(), scope=MemoryScope.personal("actor-1"), reference=due
        )
        assert applied.lifecycle_state is ProspectiveLifecycleState.TRIGGERED
        triggered_revision = applied.committed_revision
        assert triggered_revision == prospective_revision + 1
        # 事故现场的 Prospective 变体：head 前进了，分类行仍然只有 revision 1。
        assert await _classification_revisions(backend, prospective_id) == (1,)

        source = _operation(span, operation_id="create-source")
        relation = replace(
            _operation(span, operation_id="create-relation", depends_on=(source.operation_id,)),
            payload=SemanticRelationMemoryPayload(
                SemanticRelationKind.APPLIES_TO,
                CreatedByOperationTarget(source.operation_id),
                ExistingMemoryTarget(prospective_id, triggered_revision),
            ),
        )
        await backend.apply_memory_mutation_plan(
            principal=_principal(),
            scope=MemoryScope.personal("actor-1"),
            plan=_plan(
                envelope,
                source,
                relation,
                base_revision=await _apply_head(backend),
                plan_id="prospective-endpoint-plan",
                idempotency_key="prospective-endpoint-key",
            ),
        )
        async with backend.connection.execute(
            "SELECT target_memory_id,target_revision,relation_kind FROM cognitive_relations"
        ) as cursor:
            rows = tuple(await cursor.fetchall())
        assert len(rows) == 1
        assert (str(rows[0][0]), int(rows[0][1]), str(rows[0][2])) == (
            prospective_id,
            triggered_revision,
            "applies_to",
        )
        graph = await backend.get_twin_graph_view(principal=_principal())
        assert len(graph.edges) == 1
        assert graph.edges[0].target_node_id == f"{prospective_id}@{triggered_revision}"
        assert graph.edges[0].target_node_id in {node.node_id for node in graph.nodes}
        assert await _classification_revisions(backend, prospective_id) == (1,)
    finally:
        await backend.close()
