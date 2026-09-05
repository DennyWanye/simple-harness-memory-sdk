"""OA1 page/item/cursor literal vectors before reader implementation, stdlib only."""
import base64
import hashlib
import hmac
import json
from pathlib import Path


def c(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def h(domain, value):
    return hashlib.sha256(c({'domain': domain, 'payload': value}).encode()).hexdigest()


def main():
    item = dict(family='suppression', event_kind='directive', event_ref_hash='1'*64,
                operation_ref_hash='2'*64, attempt_ref_hash=None, occurred_at=40.0,
                outcome='committed', receipt_hash='3'*64, cognitive_effect='not_applicable',
                effect_receipt_hashes=[], committed_operation_ref_hashes=[])
    empty_root = h('memory.operation.audit.root.v1', [])
    query = dict(schema_version=1, requester_ref_hash='a'*64, target_ref_hash='b'*64,
                 access_receipt_hash='c'*64, expected=[], coverage_version='oa1.v1')
    cuts = [['suppression', 1, 'd'*64]]
    payload = dict(schema_version=1, query_hash=h('memory.operation.audit.query.v1', query),
                   cuts=cuts, support_root_hash='e'*64, offset=0)
    signature = hmac.new(bytes(range(32)), c({'domain':'memory.operation.audit.cursor.v1',
                        'payload':payload}).encode(), hashlib.sha256).hexdigest()
    token = base64.urlsafe_b64encode(c(dict(payload=payload,signature=signature)).encode()).decode()
    vector = dict(item=item,item_hash=h('memory.operation.audit.item.v1',item),
                  empty_root=empty_root, query=query, query_hash=payload['query_hash'],
                  cursor_payload=payload,cursor_hmac_key_hex=bytes(range(32)).hex(),
                  cursor_signature=signature,cursor_token=token)
    path=Path(__file__).parents[1]/'tests/fixtures/operation-audit-v1/page.json'
    path.write_text(json.dumps(vector,sort_keys=True,indent=2)+'\n')


if __name__ == '__main__':
    main()
