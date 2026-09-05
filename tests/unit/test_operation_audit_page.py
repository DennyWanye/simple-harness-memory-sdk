import json
from pathlib import Path


def test_page_item_literal_vector():
    from simple_harness_memory import OperationAuditItemV1

    v = json.loads(
        (Path(__file__).parents[1] / "fixtures/operation-audit-v1/page.json").read_text()
    )
    item = OperationAuditItemV1(**v["item"])
    assert item.to_json() == v["item"]
    assert item.item_hash == v["item_hash"]


def test_original_independent_root_query_and_hmac_vectors():
    from types import SimpleNamespace

    from simple_harness_memory.backends.operation_audit import _cursor, _root, _sign
    from simple_harness_memory.core.operation_audit import _hash

    v = json.loads(
        (Path(__file__).parents[1] / "fixtures/operation-audit-v1/page.json").read_text()
    )
    backend = SimpleNamespace(_audit_cursor_hmac_key=bytes.fromhex(v["cursor_hmac_key_hex"]))
    assert _root([]) == v["empty_root"]
    assert _hash("memory.operation.audit.query.v1", v["query"]) == v["query_hash"]
    assert _sign(backend, v["cursor_payload"]) == v["cursor_signature"]
    assert _cursor(backend, v["cursor_payload"]).token == v["cursor_token"]
