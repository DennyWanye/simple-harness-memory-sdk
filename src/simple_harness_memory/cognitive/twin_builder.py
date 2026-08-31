"""Display-only Digital Twin projections and legacy Fact aggregation.

The graph types in this module are a read model over canonical cognitive
records.  They deliberately have no conversion to recall candidates, context
fragments, tool inputs, or action authority.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from dataclasses import dataclass, field

from simple_harness.contracts import JsonValue, canonical_json

from simple_harness_memory.core.errors import MemoryValidationError
from simple_harness_memory.core.models import SINGLE_VALUED_KEYS, Fact, FactConflict
from simple_harness_memory.core.twin import DigitalTwin, Goal

_ACTIVE_LIFECYCLES: dict[str, frozenset[str]] = {
    "episode": frozenset({"active", "amended", "disputed"}),
    "semantic": frozenset({"active"}),
    "procedure": frozenset({"active", "reinforced"}),
    "prospective": frozenset({"pending", "triggered", "in_progress", "rescheduled"}),
}
_INFERRED_LIFECYCLES = frozenset({"candidate", "draft"})
_MEMORY_TYPES = frozenset(_ACTIVE_LIFECYCLES)
_RELATION_KINDS = frozenset(
    {"amends", "supersedes", "contests", "supports", "relates_to"}
)
_CONFIDENCE_BASE = {
    "explicit_user": 0.95,
    "verified_external": 0.9,
    "observed_behavior": 0.75,
    "llm_inference": 0.5,
    "unknown": 0.25,
}
_CONFIDENCE_ADJUSTMENT = {
    "unverified": -0.15,
    "source_bound": 0.0,
    "user_confirmed": 0.05,
    "source_verified": 0.05,
    "repeated_observation": 0.1,
}


def _identifier(value: object, name: str, *, max_bytes: int = 4096) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or "\x00" in value
        or len(value.encode("utf-8")) > max_bytes
    ):
        raise MemoryValidationError(f"{name}_invalid")
    return value


def _digest(value: object, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise MemoryValidationError(f"{name}_invalid")
    try:
        bytes.fromhex(value)
    except ValueError as exc:
        raise MemoryValidationError(f"{name}_invalid") from exc
    return value


def _timestamp(value: object, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < 0
    ):
        raise MemoryValidationError(f"{name}_invalid")
    return float(value)


def _positive_revision(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise MemoryValidationError("twin_graph_revision_invalid")
    return value


def _schema_version(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value != 1:
        raise MemoryValidationError("twin_graph_schema_unsupported")
    return value


def _hash(domain: str, value: JsonValue) -> str:
    payload = f"{domain}\n{canonical_json(value)}".encode()
    return hashlib.sha256(payload).hexdigest()


def _bounded_display_text(value: str, *, maximum_bytes: int) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        return "Memory"
    encoded = normalized.encode("utf-8")
    if len(encoded) <= maximum_bytes:
        return normalized
    suffix = "…"
    budget = maximum_bytes - len(suffix.encode("utf-8"))
    return encoded[:budget].decode("utf-8", errors="ignore").rstrip() + suffix


@dataclass(frozen=True, slots=True)
class TwinGraphSourceRef:
    evidence_ref_hash: str
    span_ref_hash: str
    source_kind: str
    quote_hash: str

    def __post_init__(self) -> None:
        _digest(self.evidence_ref_hash, "twin_graph_evidence_ref_hash")
        _digest(self.span_ref_hash, "twin_graph_span_ref_hash")
        _identifier(self.source_kind, "twin_graph_source_kind")
        _digest(self.quote_hash, "twin_graph_quote_hash")

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "evidence_ref_hash": self.evidence_ref_hash,
            "span_ref_hash": self.span_ref_hash,
            "source_kind": self.source_kind,
            "quote_hash": self.quote_hash,
        }

    @classmethod
    def from_json(cls, value: Mapping[str, object]) -> TwinGraphSourceRef:
        if set(value) != {
            "evidence_ref_hash",
            "span_ref_hash",
            "source_kind",
            "quote_hash",
        }:
            raise MemoryValidationError("twin_graph_source_ref_keys_invalid")
        return cls(
            _digest(value["evidence_ref_hash"], "twin_graph_evidence_ref_hash"),
            _digest(value["span_ref_hash"], "twin_graph_span_ref_hash"),
            _identifier(value["source_kind"], "twin_graph_source_kind"),
            _digest(value["quote_hash"], "twin_graph_quote_hash"),
        )


@dataclass(frozen=True, slots=True)
class TwinGraphNode:
    node_id: str
    memory_id: str
    revision: int
    memory_type: str
    status: str
    lifecycle_state: str
    epistemic_status: str
    conflict_status: str
    verification_state: str
    confidence: float
    confidence_basis: tuple[str, ...]
    label: str
    tooltip: str
    content_hash: str
    source_refs: tuple[TwinGraphSourceRef, ...]
    can_correct: bool
    can_forget: bool
    redacted: bool
    node_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for value, name in (
            (self.node_id, "twin_graph_node_id"),
            (self.memory_id, "twin_graph_memory_id"),
            (self.status, "twin_graph_status"),
            (self.lifecycle_state, "twin_graph_lifecycle"),
            (self.epistemic_status, "twin_graph_epistemic_status"),
            (self.conflict_status, "twin_graph_conflict_status"),
            (self.verification_state, "twin_graph_verification_state"),
            (self.label, "twin_graph_label"),
            (self.tooltip, "twin_graph_tooltip"),
        ):
            _identifier(value, name)
        _positive_revision(self.revision)
        if self.memory_type not in _MEMORY_TYPES:
            raise MemoryValidationError("twin_graph_memory_type_invalid")
        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not math.isfinite(float(self.confidence))
            or not 0 <= float(self.confidence) <= 1
        ):
            raise MemoryValidationError("twin_graph_confidence_invalid")
        object.__setattr__(self, "confidence", round(float(self.confidence), 3))
        basis = tuple(
            _identifier(item, "twin_graph_confidence_basis")
            for item in self.confidence_basis
        )
        if not basis or len(basis) != len(set(basis)):
            raise MemoryValidationError("twin_graph_confidence_basis_invalid")
        object.__setattr__(self, "confidence_basis", basis)
        _digest(self.content_hash, "twin_graph_content_hash")
        refs = tuple(
            sorted(
                self.source_refs,
                key=lambda item: (item.evidence_ref_hash, item.span_ref_hash),
            )
        )
        if not refs or len(
            {(item.evidence_ref_hash, item.span_ref_hash) for item in refs}
        ) != len(refs):
            raise MemoryValidationError("twin_graph_source_refs_invalid")
        object.__setattr__(self, "source_refs", refs)
        if not all(
            isinstance(value, bool)
            for value in (self.can_correct, self.can_forget, self.redacted)
        ):
            raise MemoryValidationError("twin_graph_node_flags_invalid")
        object.__setattr__(
            self,
            "node_hash",
            _hash("simple-harness-memory/twin-graph-node/v1", self._payload_json()),
        )

    def _payload_json(self) -> dict[str, JsonValue]:
        return {
            "node_id": self.node_id,
            "memory_id": self.memory_id,
            "revision": self.revision,
            "memory_type": self.memory_type,
            "status": self.status,
            "lifecycle_state": self.lifecycle_state,
            "epistemic_status": self.epistemic_status,
            "conflict_status": self.conflict_status,
            "verification_state": self.verification_state,
            "confidence": self.confidence,
            "confidence_basis": list(self.confidence_basis),
            "label": self.label,
            "tooltip": self.tooltip,
            "content_hash": self.content_hash,
            "source_refs": [item.to_json() for item in self.source_refs],
            "can_correct": self.can_correct,
            "can_forget": self.can_forget,
            "redacted": self.redacted,
        }

    def to_json(self) -> dict[str, JsonValue]:
        return {**self._payload_json(), "node_hash": self.node_hash}

    @classmethod
    def from_json(cls, value: Mapping[str, object]) -> TwinGraphNode:
        expected = {
            "node_id", "memory_id", "revision", "memory_type", "status",
            "lifecycle_state", "epistemic_status", "conflict_status",
            "verification_state", "confidence", "confidence_basis", "label",
            "tooltip", "content_hash", "source_refs", "can_correct", "can_forget",
            "redacted", "node_hash",
        }
        if set(value) != expected:
            raise MemoryValidationError("twin_graph_node_keys_invalid")
        raw_refs = value["source_refs"]
        raw_basis = value["confidence_basis"]
        if not isinstance(raw_refs, list) or not all(isinstance(item, dict) for item in raw_refs):
            raise MemoryValidationError("twin_graph_source_refs_invalid")
        if not isinstance(raw_basis, list) or not all(isinstance(item, str) for item in raw_basis):
            raise MemoryValidationError("twin_graph_confidence_basis_invalid")
        node = cls(
            _identifier(value["node_id"], "twin_graph_node_id"),
            _identifier(value["memory_id"], "twin_graph_memory_id"),
            _positive_revision(value["revision"]),
            _identifier(value["memory_type"], "twin_graph_memory_type"),
            _identifier(value["status"], "twin_graph_status"),
            _identifier(value["lifecycle_state"], "twin_graph_lifecycle"),
            _identifier(value["epistemic_status"], "twin_graph_epistemic_status"),
            _identifier(value["conflict_status"], "twin_graph_conflict_status"),
            _identifier(value["verification_state"], "twin_graph_verification_state"),
            float(value["confidence"]),  # type: ignore[arg-type]
            tuple(raw_basis),
            _identifier(value["label"], "twin_graph_label"),
            _identifier(value["tooltip"], "twin_graph_tooltip"),
            _digest(value["content_hash"], "twin_graph_content_hash"),
            tuple(TwinGraphSourceRef.from_json(item) for item in raw_refs),
            value["can_correct"],  # type: ignore[arg-type]
            value["can_forget"],  # type: ignore[arg-type]
            value["redacted"],  # type: ignore[arg-type]
        )
        if node.node_hash != _digest(value["node_hash"], "twin_graph_node_hash"):
            raise MemoryValidationError("twin_graph_node_hash_differs")
        return node


@dataclass(frozen=True, slots=True)
class TwinGraphEdge:
    edge_id: str
    relation_kind: str
    source_node_id: str
    target_node_id: str
    label: str
    relation_hash: str
    edge_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for value, name in (
            (self.edge_id, "twin_graph_edge_id"),
            (self.source_node_id, "twin_graph_source_node_id"),
            (self.target_node_id, "twin_graph_target_node_id"),
            (self.label, "twin_graph_edge_label"),
        ):
            _identifier(value, name)
        if self.source_node_id == self.target_node_id:
            raise MemoryValidationError("twin_graph_self_edge_invalid")
        if self.relation_kind not in _RELATION_KINDS or self.label != self.relation_kind:
            raise MemoryValidationError("twin_graph_relation_kind_invalid")
        _digest(self.relation_hash, "twin_graph_relation_hash")
        object.__setattr__(
            self,
            "edge_hash",
            _hash("simple-harness-memory/twin-graph-edge/v1", self._payload_json()),
        )

    def _payload_json(self) -> dict[str, JsonValue]:
        return {
            "edge_id": self.edge_id,
            "relation_kind": self.relation_kind,
            "source_node_id": self.source_node_id,
            "target_node_id": self.target_node_id,
            "label": self.label,
            "relation_hash": self.relation_hash,
        }

    def to_json(self) -> dict[str, JsonValue]:
        return {**self._payload_json(), "edge_hash": self.edge_hash}

    @classmethod
    def from_json(cls, value: Mapping[str, object]) -> TwinGraphEdge:
        expected = {
            "edge_id", "relation_kind", "source_node_id", "target_node_id",
            "label", "relation_hash", "edge_hash",
        }
        if set(value) != expected:
            raise MemoryValidationError("twin_graph_edge_keys_invalid")
        edge = cls(
            _identifier(value["edge_id"], "twin_graph_edge_id"),
            _identifier(value["relation_kind"], "twin_graph_relation_kind"),
            _identifier(value["source_node_id"], "twin_graph_source_node_id"),
            _identifier(value["target_node_id"], "twin_graph_target_node_id"),
            _identifier(value["label"], "twin_graph_edge_label"),
            _digest(value["relation_hash"], "twin_graph_relation_hash"),
        )
        if edge.edge_hash != _digest(value["edge_hash"], "twin_graph_edge_hash"):
            raise MemoryValidationError("twin_graph_edge_hash_differs")
        return edge


@dataclass(frozen=True, slots=True)
class TwinGraphView:
    view_id: str
    subject: str
    generated_at: float
    nodes: tuple[TwinGraphNode, ...]
    edges: tuple[TwinGraphEdge, ...]
    schema_version: int = 1
    payload_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _identifier(self.view_id, "twin_graph_view_id")
        _identifier(self.subject, "twin_graph_subject")
        object.__setattr__(self, "generated_at", _timestamp(self.generated_at, "generated_at"))
        if self.schema_version != 1:
            raise MemoryValidationError("twin_graph_schema_unsupported")
        nodes = tuple(sorted(self.nodes, key=lambda item: item.node_id))
        edges = tuple(sorted(self.edges, key=lambda item: item.edge_id))
        if not all(isinstance(item, TwinGraphNode) for item in nodes) or len(
            {item.node_id for item in nodes}
        ) != len(nodes):
            raise MemoryValidationError("twin_graph_nodes_invalid")
        node_ids = {item.node_id for item in nodes}
        if (
            not all(isinstance(item, TwinGraphEdge) for item in edges)
            or len({item.edge_id for item in edges}) != len(edges)
            or any(
                item.source_node_id not in node_ids or item.target_node_id not in node_ids
                for item in edges
            )
        ):
            raise MemoryValidationError("twin_graph_edges_invalid")
        object.__setattr__(self, "nodes", nodes)
        object.__setattr__(self, "edges", edges)
        object.__setattr__(
            self,
            "payload_hash",
            _hash("simple-harness-memory/twin-graph-view/v1", self._payload_json()),
        )

    def _payload_json(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "view_id": self.view_id,
            "subject": self.subject,
            "generated_at": self.generated_at,
            "nodes": [item.to_json() for item in self.nodes],
            "edges": [item.to_json() for item in self.edges],
        }

    def to_json(self) -> dict[str, JsonValue]:
        return {**self._payload_json(), "payload_hash": self.payload_hash}

    @classmethod
    def from_json(cls, value: Mapping[str, object]) -> TwinGraphView:
        if set(value) != {
            "schema_version", "view_id", "subject", "generated_at", "nodes",
            "edges", "payload_hash",
        }:
            raise MemoryValidationError("twin_graph_view_keys_invalid")
        raw_nodes = value["nodes"]
        raw_edges = value["edges"]
        if not isinstance(raw_nodes, list) or not all(isinstance(item, dict) for item in raw_nodes):
            raise MemoryValidationError("twin_graph_nodes_invalid")
        if not isinstance(raw_edges, list) or not all(isinstance(item, dict) for item in raw_edges):
            raise MemoryValidationError("twin_graph_edges_invalid")
        view = cls(
            _identifier(value["view_id"], "twin_graph_view_id"),
            _identifier(value["subject"], "twin_graph_subject"),
            _timestamp(value["generated_at"], "generated_at"),
            tuple(TwinGraphNode.from_json(item) for item in raw_nodes),
            tuple(TwinGraphEdge.from_json(item) for item in raw_edges),
            _schema_version(value["schema_version"]),
        )
        if view.payload_hash != _digest(value["payload_hash"], "twin_graph_payload_hash"):
            raise MemoryValidationError("twin_graph_payload_hash_differs")
        return view


@dataclass(frozen=True, slots=True)
class TwinGraphRecordInput:
    memory_id: str
    revision: int
    head_revision: int
    memory_type: str
    lifecycle_state: str
    epistemic_status: str
    conflict_status: str
    verification_state: str
    valid_from: float | None
    valid_to: float | None
    content: Mapping[str, JsonValue]
    content_hash: str
    source_refs: tuple[TwinGraphSourceRef, ...]
    conflict_group_id: str | None = None
    suppressed: bool = False
    redact_content: bool = False

    @property
    def node_id(self) -> str:
        return f"{self.memory_id}@{self.revision}"


@dataclass(frozen=True, slots=True)
class TwinGraphRelationInput:
    relation_id: str
    relation_kind: str
    source_memory_id: str
    source_revision: int
    target_memory_id: str
    target_revision: int
    relation_hash: str


def _record_visible(record: TwinGraphRecordInput, generated_at: float) -> bool:
    if record.suppressed:
        return False
    if record.valid_from is not None and generated_at < record.valid_from:
        return False
    if record.valid_to is not None and generated_at >= record.valid_to:
        return False
    inferred = (
        record.epistemic_status == "llm_inference"
        and record.lifecycle_state in _INFERRED_LIFECYCLES
    )
    active = record.lifecycle_state in _ACTIVE_LIFECYCLES.get(record.memory_type, ())
    return active or inferred


def _node_status(record: TwinGraphRecordInput) -> str:
    if record.conflict_group_id is not None or record.conflict_status == "contested":
        return "contested"
    if record.epistemic_status == "llm_inference":
        return "inferred"
    return record.lifecycle_state


def _node_confidence(record: TwinGraphRecordInput) -> tuple[float, tuple[str, ...]]:
    base = _CONFIDENCE_BASE.get(record.epistemic_status, 0.25)
    adjustment = _CONFIDENCE_ADJUSTMENT.get(record.verification_state, -0.15)
    effective_conflict = (
        "contested" if record.conflict_group_id is not None else record.conflict_status
    )
    conflict_penalty = -0.15 if effective_conflict == "contested" else 0.0
    confidence = round(min(1.0, max(0.05, base + adjustment + conflict_penalty)), 3)
    return confidence, (
        f"epistemic:{record.epistemic_status}",
        f"verification:{record.verification_state}",
        f"conflict:{effective_conflict}",
    )


def _node_label(record: TwinGraphRecordInput) -> str:
    if record.redact_content:
        return f"{record.memory_type.title()} memory"
    content = record.content
    if record.memory_type == "episode":
        value = content.get("title", "Episode")
    elif record.memory_type == "semantic":
        subject = str(content.get("subject_entity", "Entity"))
        predicate = str(content.get("predicate", "relation"))
        object_value = canonical_json(content.get("object_value"))
        value = f"{subject} · {predicate} · {object_value}"
    elif record.memory_type == "procedure":
        value = content.get("name", "Procedure")
    else:
        value = content.get("action", "Prospective memory")
    return _bounded_display_text(str(value), maximum_bytes=512)


def build_twin_graph_view(
    *,
    subject: str,
    generated_at: float,
    records: tuple[TwinGraphRecordInput, ...],
    relations: tuple[TwinGraphRelationInput, ...],
) -> TwinGraphView:
    """Build a deterministic display projection from canonical record rows.

    An unresolved conflict group is atomic: if either exact member is hidden,
    expired, malformed, or suppressed, neither member nor its edge is emitted.
    """

    _identifier(subject, "twin_graph_subject")
    current_time = _timestamp(generated_at, "generated_at")
    visible = {
        record.node_id: record
        for record in records
        if _record_visible(record, current_time)
        and (
            record.revision == record.head_revision
            or record.conflict_group_id is not None
        )
    }
    groups: dict[str, tuple[TwinGraphRecordInput, ...]] = {}
    for group_id in sorted(
        {item.conflict_group_id for item in records if item.conflict_group_id is not None}
    ):
        assert group_id is not None
        groups[group_id] = tuple(
            sorted(
                (item for item in records if item.conflict_group_id == group_id),
                key=lambda item: item.revision,
            )
        )
    for members in groups.values():
        complete = (
            len(members) == 2
            and len({item.node_id for item in members}) == 2
            and all(item.node_id in visible for item in members)
            and sum(item.revision == item.head_revision for item in members) == 1
        )
        if not complete:
            for member in members:
                visible.pop(member.node_id, None)

    nodes: list[TwinGraphNode] = []
    for record in visible.values():
        confidence, confidence_basis = _node_confidence(record)
        status = _node_status(record)
        nodes.append(
            TwinGraphNode(
                record.node_id,
                record.memory_id,
                record.revision,
                record.memory_type,
                status,
                record.lifecycle_state,
                record.epistemic_status,
                (
                    "contested"
                    if record.conflict_group_id is not None
                    else record.conflict_status
                ),
                record.verification_state,
                confidence,
                confidence_basis,
                _node_label(record),
                _bounded_display_text(
                    f"{record.memory_type} · {status} · confidence {confidence:.3f}",
                    maximum_bytes=512,
                ),
                record.content_hash,
                record.source_refs,
                record.revision == record.head_revision,
                record.revision == record.head_revision,
                record.redact_content,
            )
        )
    visible_ids = {item.node_id for item in nodes}
    edges = tuple(
        TwinGraphEdge(
            item.relation_id,
            item.relation_kind,
            f"{item.source_memory_id}@{item.source_revision}",
            f"{item.target_memory_id}@{item.target_revision}",
            item.relation_kind,
            item.relation_hash,
        )
        for item in relations
        if f"{item.source_memory_id}@{item.source_revision}" in visible_ids
        and f"{item.target_memory_id}@{item.target_revision}" in visible_ids
    )
    return TwinGraphView(
        f"twin-graph:{subject}",
        subject,
        current_time,
        tuple(nodes),
        edges,
    )


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
