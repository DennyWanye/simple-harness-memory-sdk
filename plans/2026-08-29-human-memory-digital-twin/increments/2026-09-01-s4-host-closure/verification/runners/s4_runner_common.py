#!/usr/bin/env python3
"""Shared black-box runner utilities for the S4 verification drafts.

The adapter supplied at execution time must expose only documented public Host
APIs. These utilities deliberately know nothing about product modules, tables,
or implementation objects.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_fixture(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "schema_version",
        "fixture_id",
        "subject",
        "wrong_principal",
        "data_format",
        "task_scopes",
        "search",
        "live_probe",
        "limits",
        "queue",
        "stable_errors",
        "critical_affected_api",
    }
    missing = sorted(required - value.keys())
    if missing:
        raise ValueError(f"fixture missing keys: {missing}")
    if value["task_scopes"]["a"]["event_count"] != 100000:
        raise ValueError("scope A must freeze exactly 100000 canonical events")
    if value["limits"] != {
        "readme_bytes": 16384,
        "status_bytes": 12288,
        "resume_package_bytes": 24576,
        "page_bytes": 32768,
        "evidence_events_per_page": 500,
    }:
        raise ValueError("frozen S4 byte/page limits changed")
    return value


def require_evidence_dir(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if ".local-test-evidence" not in resolved.parts:
        raise ValueError("artifact-dir must be inside an ignored .local-test-evidence directory")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def load_adapter(path: Path, fixture: dict[str, Any], artifact_dir: Path) -> tuple[Any, dict[str, str]]:
    adapter_path = path.expanduser().resolve()
    adapter_bytes = adapter_path.read_bytes()
    spec = importlib.util.spec_from_file_location("s4_public_only_adapter", adapter_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot import adapter: {adapter_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    factory = getattr(module, "create_adapter", None)
    if not callable(factory):
        raise ValueError("adapter must export create_adapter(*, fixture, artifact_dir)")
    adapter = factory(fixture=fixture, artifact_dir=artifact_dir)
    invoke = getattr(adapter, "invoke", None)
    if not callable(invoke):
        raise ValueError("adapter instance must expose invoke(operation, request) -> JSON object")
    return adapter, {"path": str(adapter_path), "sha256": sha256_bytes(adapter_bytes)}


def invoke(adapter: Any, operation: str, request: dict[str, Any]) -> dict[str, Any]:
    result = adapter.invoke(operation, request)
    if not isinstance(result, dict):
        raise AssertionError(f"{operation} returned non-object result")
    return result


def expect_ok(result: dict[str, Any], operation: str) -> dict[str, Any]:
    if result.get("ok") is not True:
        raise AssertionError(f"{operation} failed: {result.get('code') or result}")
    status = result.get("status")
    if isinstance(status, int) and status >= 500:
        raise AssertionError(f"{operation} returned server error {status}")
    return result


def expect_error(result: dict[str, Any], operation: str, expected_code: str) -> None:
    if result.get("ok") is not False or result.get("code") != expected_code:
        raise AssertionError(f"{operation}: expected {expected_code}, got {result}")
    status = result.get("status")
    if isinstance(status, int) and status >= 500:
        raise AssertionError(f"{operation}: stable rejection must not be 5xx")


def require_ref_or_receipt(result: dict[str, Any], operation: str) -> None:
    if not any(result.get(key) for key in ("ref", "receipt", "receipt_ref", "content_sha256")):
        raise AssertionError(f"{operation} omitted immutable ref/receipt/hash")


def write_result(artifact_dir: Path, name: str, payload: dict[str, Any]) -> Path:
    path = artifact_dir / name
    path.write_bytes(canonical_bytes(payload) + b"\n")
    return path


def resolve_placeholders(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        key = value[1:]
        if key not in context:
            raise KeyError(f"unresolved fixture placeholder: {value}")
        return context[key]
    if isinstance(value, list):
        return [resolve_placeholders(item, context) for item in value]
    if isinstance(value, dict):
        return {key: resolve_placeholders(item, context) for key, item in value.items()}
    return value
