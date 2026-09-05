import json
from pathlib import Path


def test_page_item_literal_vector():
    from simple_harness_memory import OperationAuditItemV1

    v = json.loads((Path(__file__).parents[1]/'fixtures/operation-audit-v1/page.json').read_text())
    item = OperationAuditItemV1(**v['item'])
    assert item.to_json() == v['item']
    assert item.item_hash == v['item_hash']
