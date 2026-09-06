"""Bounded owner-only draft previews, never applicable recall or execution grants."""
from dataclasses import dataclass, field
from simple_harness.contracts import canonical_json
from simple_harness.runtime import ProcedureMemoryPayload, ProcedureRiskLevel
from simple_harness_memory.core.history import history_hash
from simple_harness_memory.core.lifecycle_results import _identifier, _revision, UNBOUND_PROCEDURE_APPLICABILITY


def _digest(value):
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("procedure_draft_digest_invalid")


@dataclass(frozen=True, slots=True)
class ProcedureDraftCandidate:
    memory_id: str
    revision: int
    name: str
    steps: tuple[str, ...]
    applicability: tuple[str, ...]
    risk_level: str
    lifecycle_state: str
    qualification_epoch: str
    applicability_fingerprint: str
    content_hash: str

    def __post_init__(self):
        _identifier(self.memory_id, "memory_id")
        _identifier(self.qualification_epoch, "qualification_epoch")
        _revision(self.revision, "revision")
        _digest(self.content_hash)
        if self.applicability_fingerprint != UNBOUND_PROCEDURE_APPLICABILITY:
            _digest(self.applicability_fingerprint)
        if self.lifecycle_state not in ("draft", "eligible_for_activation"):
            raise ValueError("procedure_draft_candidate_state")
        if (type(self.steps) is not tuple or not self.steps
                or type(self.applicability) is not tuple):
            raise ValueError("procedure_draft_candidate_steps")
        ProcedureMemoryPayload(self.name, self.applicability, self.steps, ProcedureRiskLevel(self.risk_level))

    @property
    def source_hash(self):
        return history_hash("memory.procedure.draft-candidate.v1", self.to_json())

    def to_json(self):
        return {key: list(value) if isinstance(value, tuple) else value
                for key in self.__dataclass_fields__ for value in (getattr(self, key),)}

    @classmethod
    def from_json(cls, value):
        if type(value) is not dict or set(value) != set(cls.__dataclass_fields__):
            raise ValueError("procedure_draft_candidate_shape")
        if type(value["steps"]) is not list or type(value["applicability"]) is not list:
            raise ValueError("procedure_draft_candidate_shape")
        result = cls(**{**value, "steps": tuple(value["steps"]), "applicability": tuple(value["applicability"])})
        if len(canonical_json(result.to_json()).encode()) > 32768:
            raise ValueError("procedure_draft_candidate_limit")
        return result


@dataclass(frozen=True, slots=True)
class ProcedureDraftPage:
    candidates: tuple[ProcedureDraftCandidate, ...]
    next_after: str | None
    scanned: int
    omitted_oversize: int = 0
    operation_observation: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if (type(self.candidates) is not tuple or len(self.candidates) > 8
                or any(type(c) is not ProcedureDraftCandidate for c in self.candidates)
                or len({c.memory_id for c in self.candidates}) != len(self.candidates)
                or type(self.scanned) is not int or not 0 <= self.scanned <= 128
                or type(self.omitted_oversize) is not int or not 0 <= self.omitted_oversize <= self.scanned
                or len(self.candidates) + self.omitted_oversize > self.scanned):
            raise ValueError("procedure_draft_page_invalid")
        if self.next_after is not None:
            _identifier(self.next_after, "next_after")

    def to_json(self):
        return {"candidates": [c.to_json() for c in self.candidates], "next_after": self.next_after,
                "scanned": self.scanned, "omitted_oversize": self.omitted_oversize}

    @property
    def source_hash(self):
        return history_hash("memory.procedure.draft-page.v1", self.to_json())
