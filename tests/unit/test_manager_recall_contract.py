import inspect

import pytest

from simple_harness_memory import MemoryManager


def test_manager_recall_lifecycle_has_explicit_public_signatures() -> None:
    expected = {
        "recall_bounded": (
            "self",
            "query",
            "user_id",
            "session_id",
            "context_query_id",
            "query_hash",
            "max_results",
            "max_bytes",
            "timeout_seconds",
        ),
        "release_recall_result": (
            "self",
            "user_id",
            "context_query_id",
            "result_hash",
        ),
        "cleanup_recall_results": ("self", "user_id", "now", "limit"),
    }
    for name, parameters in expected.items():
        signature = inspect.signature(getattr(MemoryManager, name))
        assert tuple(signature.parameters) == parameters
        assert all(
            parameter.kind is not inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )
        for core_name in parameters[2:]:
            assert (
                signature.parameters[core_name].kind
                is inspect.Parameter.KEYWORD_ONLY
            )


@pytest.mark.asyncio
async def test_manager_recall_lifecycle_forwards_explicit_identity() -> None:
    manager = await MemoryManager.build()
    result = await manager.recall_bounded(
        "query",
        user_id="user-1",
        session_id="session-1",
        context_query_id="query-1",
        max_results=2,
        max_bytes=1024,
        timeout_seconds=1.0,
    )
    await manager.release_recall_result(
        user_id="user-1",
        context_query_id="query-1",
        result_hash=result.result_hash,
    )
    assert await manager.cleanup_recall_results(
        user_id="user-1", now=10**12, limit=1
    ) == 1
    await manager.close()
