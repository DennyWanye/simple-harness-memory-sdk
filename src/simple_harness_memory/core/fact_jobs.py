"""Durable, leased fact-extraction worker for committed turns."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Protocol

import structlog

from simple_harness_memory.core.models import Fact
from simple_harness_memory.core.observability import MemoryObservability

logger = structlog.get_logger("simple_harness_memory.core.fact_jobs")


class _FactExtractor(Protocol):
    async def extract(self, content: str, **kwargs: object) -> list[Fact]: ...


class FactJobWorker:
    def __init__(
        self,
        backend: object,
        extractor: _FactExtractor,
        observability: MemoryObservability | None = None,
    ) -> None:
        self._backend = backend
        self._extractor = extractor
        self._wake = asyncio.Event()
        self._closing = False
        self._task: asyncio.Task[None] | None = None
        self._observability = observability or getattr(backend, "observability")

    async def start(self) -> None:
        if self._task is not None:
            return
        recover = getattr(self._backend, "recover_fact_jobs")
        recovered = await recover()
        if isinstance(recovered, int) and recovered:
            self._observability.emit(
                "memory.fact_job.recovered",
                operation="fact_job",
                outcome="succeeded",
                entity_id=f"recovery:{recovered}",
                attributes={
                    "stage": "recovered",
                    "recovery_result": "requeued",
                    "selected_count": recovered,
                    "replayed": True,
                    "history_complete": False,
                },
            )
        self._task = asyncio.create_task(self._run(), name="memory-fact-worker")
        self._wake.set()

    def notify(self) -> None:
        self._wake.set()

    @property
    def lineage(self) -> str:
        explicit = getattr(self._extractor, "lineage", None)
        if isinstance(explicit, str) and explicit:
            return explicit
        version = getattr(self._extractor, "version", "1")
        return f"{type(self._extractor).__module__}.{type(self._extractor).__qualname__}:{version}"

    async def drain_once(self) -> bool:
        claim = getattr(self._backend, "claim_fact_job")
        job = await claim()
        if job is None:
            return False
        entity_id = str(job["job_id"])
        session_id = str(job.get("session_id") or "") or None
        self._observability.emit(
            "memory.fact_job.claimed",
            operation="fact_job",
            outcome="started",
            entity_id=entity_id,
            session_id=session_id,
            attributes={
                "stage": "claimed",
                "attempt": int(job.get("attempts") or 0),
            },
        )
        try:
            facts = await self._extractor.extract(
                str(job["payload"]),
                role="user",
                message_id=int(job["source_msg_id"]),
                created_at=float(job["created_at"]),
                subject="user",
                user_id=str(job["actor_id"]),
            )
            apply_job = getattr(self._backend, "apply_fact_job")
            status = await apply_job(job, list(facts), extractor_lineage=self.lineage)
            event_name = {
                "applied": "memory.fact_job.applied",
                "erased": "memory.fact_job.erased",
                "lost_lease": "memory.fact_job.lost_lease",
            }.get(status, "memory.fact_job.failed")
            self._observability.emit(
                event_name,
                operation="fact_job",
                outcome=("succeeded" if status == "applied" else "dropped"),
                entity_id=entity_id,
                session_id=session_id,
                attributes={
                    "stage": status,
                    "attempt": int(job.get("attempts") or 0),
                    "selected_count": len(facts),
                    "error_code": None if status == "applied" else f"memory_fact_job_{status}",
                },
                severity="info" if status == "applied" else "warning",
            )
            logger.info(
                "memory.fact_job_settled",
                job_id=str(job["job_id"]),
                fact_count=len(facts),
                stable_code=status,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            fail = getattr(self._backend, "fail_fact_job")
            state = await fail(job, stable_code="fact_extraction_failed")
            terminal = state == "dead_letter"
            self._observability.emit(
                "memory.fact_job.dead_letter" if terminal else "memory.fact_job.retrying",
                operation="fact_job",
                outcome="terminal" if terminal else "retrying",
                entity_id=entity_id,
                session_id=session_id,
                attributes={
                    "stage": state if isinstance(state, str) else "retrying",
                    "attempt": int(job.get("attempts") or 0),
                    "retry_count": int(job.get("attempts") or 0),
                    "error_code": "fact_extraction_failed",
                },
                severity="error" if terminal else "warning",
            )
            logger.warning(
                "memory.fact_job_failed",
                job_id=str(job["job_id"]),
                stable_code="fact_extraction_failed",
            )
        return True

    async def _run(self) -> None:
        while not self._closing:
            self._wake.clear()
            while not self._closing and await self.drain_once():
                pass
            if not self._closing:
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=1.0)
                except TimeoutError:
                    pass

    async def close(self, *, timeout: float = 2.0) -> None:
        if self._task is None:
            return
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline and await self.drain_once():
            pass
        self._closing = True
        self._wake.set()
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None


__all__ = ("FactJobWorker",)
