"""Memory-specific projection onto the shared Harness observability runtime."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from typing import TypeAlias

from simple_harness.observability import (
    CorrelationContext,
    ObservabilityRuntime,
    ObservabilitySink,
    Outcome,
    Severity,
)

CorrelationFactory: TypeAlias = Callable[[str, str | None], CorrelationContext]
CorrelationInput: TypeAlias = CorrelationContext | CorrelationFactory | None


def _opaque(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class MemoryObservability:
    """Failure-isolated event projection; never participates in business authority."""

    def __init__(
        self,
        sink: ObservabilitySink | None = None,
        correlation: CorrelationInput = None,
        *,
        runtime: ObservabilityRuntime | None = None,
    ) -> None:
        self.runtime = runtime or ObservabilityRuntime(sink)
        self._correlation = correlation

    def context(self, entity_id: str, session_id: str | None = None) -> CorrelationContext:
        configured = self._correlation
        if isinstance(configured, CorrelationContext):
            return configured
        if callable(configured):
            try:
                result = configured(entity_id, session_id)
                if isinstance(result, CorrelationContext):
                    return result
            except BaseException:
                pass
        trace_source = session_id or entity_id
        return CorrelationContext(
            trace_id=_opaque(f"memory:trace:{trace_source}"),
            root_id=_opaque(f"memory:root:{entity_id}"),
            operation_id=_opaque(f"memory:operation:{entity_id}"),
        )

    def emit(
        self,
        event_name: str,
        *,
        operation: str,
        outcome: Outcome | str,
        entity_id: str,
        session_id: str | None = None,
        attributes: Mapping[str, object] | None = None,
        severity: Severity | str = Severity.INFO,
    ) -> bool:
        safe_id = _opaque(f"memory:entity:{entity_id}")
        values: dict[str, object] = {"entity_id": safe_id}
        if attributes:
            values.update(attributes)
        return self.runtime.emit_transition(
            event_name,
            component="memory",
            operation=operation,
            outcome=outcome,
            correlation=self.context(entity_id, session_id),
            attributes=values,
            severity=severity,
        )

    def snapshot(self) -> Mapping[str, object]:
        return self.runtime.diagnostics_snapshot()

    def close(self) -> bool:
        return self.runtime.close()


__all__ = ("CorrelationFactory", "CorrelationInput", "MemoryObservability")
