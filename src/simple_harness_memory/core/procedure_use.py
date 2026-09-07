"""Owner-scoped Procedure execution metadata; contains no step text or grant."""
from dataclasses import dataclass, field
import hashlib
from simple_harness.contracts import canonical_json
from simple_harness.runtime import ProcedureLifecycleState, ProcedureRiskLevel, ProcedureHazard
from simple_harness_memory.core.errors import MemoryValidationError
from simple_harness_memory.core.lifecycle_results import (
    _identifier, _revision, UNBOUND_PROCEDURE_APPLICABILITY,
)


PROCEDURE_OBSERVATION_RECOVERY_VERSION = 1


@dataclass(frozen=True, slots=True)
class ProcedureUseTarget:
    memory_id: str
    revision: int
    lifecycle_state: str
    risk_level: str
    qualification_epoch: str
    applicability_fingerprint: str
    bound_hazard: str | None
    step_hashes: tuple[str, ...]
    operation_observation: object | None = field(default=None, repr=False, compare=False)
    source_hash: str = field(init=False)

    def __post_init__(self):
        _identifier(self.memory_id, "memory_id")
        _identifier(self.qualification_epoch, "qualification_epoch")
        _revision(self.revision, "revision")
        ProcedureLifecycleState(self.lifecycle_state)
        ProcedureRiskLevel(self.risk_level)
        if self.bound_hazard is not None:
            ProcedureHazard(self.bound_hazard)
        def digest(value):
            return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
        if (self.applicability_fingerprint != UNBOUND_PROCEDURE_APPLICABILITY
                and not digest(self.applicability_fingerprint)):
            raise MemoryValidationError("procedure_use_applicability_invalid")
        if (type(self.step_hashes) is not tuple or not 1 <= len(self.step_hashes) <= 16
                or not all(digest(value) for value in self.step_hashes)):
            raise MemoryValidationError("procedure_use_step_hashes_invalid")
        object.__setattr__(self, "source_hash", hashlib.sha256(canonical_json({
            "domain": "memory.procedure-use-target.v1", "value": self.to_json(),
        }).encode()).hexdigest())

    def to_json(self):
        return {"memory_id": self.memory_id, "revision": self.revision,
                "lifecycle_state": self.lifecycle_state, "risk_level": self.risk_level,
                "qualification_epoch": self.qualification_epoch,
                "applicability_fingerprint": self.applicability_fingerprint,
                "bound_hazard": self.bound_hazard, "step_hashes": list(self.step_hashes)}
