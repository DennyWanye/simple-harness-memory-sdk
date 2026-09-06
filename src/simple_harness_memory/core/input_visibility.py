"""Current request input observations, never ordinary recall or output grants."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
import math
from typing import Protocol, Literal

from simple_harness import DisclosureContext
from simple_harness.runtime import AdmittedEvidenceAuthority
from simple_harness_memory.core.history import HistoryEvidenceBinding, HistoryVisibilitySnapshot, history_hash
from simple_harness_memory.core.history_sources import HistorySourceOriginReceipt
from simple_harness_memory.core.identity import MemoryPrincipal
from simple_harness_memory.core.operation_audit import _digest, _identifier

COMMON_INPUT_POLICY_HASH = "3963adb81d62aa5b64e95c6a7f1a4fb6d6dd76ce4390cb1ac4df9b72c0f6ed69"


@dataclass(frozen=True, slots=True)
class CurrentInputBindingV1:
    """One whole actual current USER item; no caller classification or grant."""
    turn_id: str
    request_id: str
    evidence: HistoryEvidenceBinding

    def __post_init__(self):
        _identifier(self.turn_id)
        _identifier(self.request_id)
        if type(self.evidence) is not HistoryEvidenceBinding:
            raise TypeError("current_input_evidence_binding_required")

    def to_json(self):
        return {"schema_version": 1, "turn_id": self.turn_id, "request_id": self.request_id,
            "evidence": self.evidence.to_json()}

    @property
    def binding_hash(self):
        return history_hash("memory.current-input.binding.v1", self.to_json())


@dataclass(frozen=True, slots=True)
class CurrentInputAuthorityV1:
    """Only an injected trusted Host port may return this exact admission fact.

    Host verifies actual current execution→turn, live policy head, original S1
    and explicit declaration. Computing this DTO's hash authenticates nothing.
    """
    binding_hash: str
    disclosure_context: DisclosureContext
    admitted: AdmittedEvidenceAuthority
    origin: HistorySourceOriginReceipt
    declaration_kind: Literal["current_user", "public_material"]
    admission_fact_hash: str
    turn_hash: str
    principal: MemoryPrincipal
    common_policy_hash: str = COMMON_INPUT_POLICY_HASH

    def __post_init__(self):
        for value in (self.binding_hash, self.admission_fact_hash, self.turn_hash, self.common_policy_hash):
            _digest(value)
        if (type(self.principal) is not MemoryPrincipal
                or type(self.admitted) is not AdmittedEvidenceAuthority
                or type(self.origin) is not HistorySourceOriginReceipt
                or type(self.disclosure_context) is not DisclosureContext
                or type(self.declaration_kind) is not str
                or self.declaration_kind not in {"current_user", "public_material"}
                or self.common_policy_hash != COMMON_INPUT_POLICY_HASH):
            raise ValueError("current_input_authority_invalid")

    @property
    def authority_hash(self):
        return history_hash("memory.current-input.authority.v1", {
            "principal": asdict(self.principal), "binding_hash": self.binding_hash, "disclosure": self.disclosure_context.to_json(),
            "item_authority": self.admitted.item_authority.authority_hash,
            "origin_hash": self.origin.origin_hash, "declaration_kind": self.declaration_kind,
            "admission_fact_hash": self.admission_fact_hash, "turn_hash": self.turn_hash,
            "common_policy_hash": self.common_policy_hash,
        })


class CurrentInputAuthorityPort(Protocol):
    async def resolve_current_input(self, *, principal: MemoryPrincipal,
        disclosure_context: DisclosureContext, binding: CurrentInputBindingV1,
    ) -> CurrentInputAuthorityV1 | None: ...


@dataclass(frozen=True, slots=True)
class CurrentInputVisibilityV1:
    binding_hash: str
    request_hash: str
    checked_at: float
    authority_epoch: int
    policy_hash: str
    invocation_input_allowed: bool
    reason: str
    declaration_kind: str | None
    authority_hash: str | None
    # This API evaluates model input, not final text generated for the recipient.
    final_audience_disclosure_authorized: bool = False
    schema_version: int = 1
    operation_observation: object | None = field(default=None, compare=False)
    history_visibility: HistoryVisibilitySnapshot | None = None

    def __post_init__(self):
        for value in (self.binding_hash, self.request_hash, self.policy_hash):
            _digest(value)
        if self.authority_hash is not None:
            _digest(self.authority_hash)
        if (type(self.invocation_input_allowed) is not bool
                or self.final_audience_disclosure_authorized is not False
                or type(self.schema_version) is not int or self.schema_version != 1
                or type(self.authority_epoch) is not int or self.authority_epoch < 0
                or type(self.checked_at) not in (float, int) or not math.isfinite(self.checked_at)
                or self.checked_at < 0 or not isinstance(self.reason, str)
                or self.declaration_kind not in (None, "current_user", "public_material")
                or (self.invocation_input_allowed and (
                    self.authority_hash is None or self.reason != "current_input_visible"))):
            raise ValueError("current_input_visibility_invalid")

    def to_json(self):
        return {key: (self.history_visibility.to_json() if self.history_visibility is not None else None)
            if key == "history_visibility" else getattr(self, key)
            for key in self.__dataclass_fields__ if key != "operation_observation"}

    @property
    def snapshot_hash(self):
        return history_hash("memory.current-input.visibility.v1", self.to_json())
