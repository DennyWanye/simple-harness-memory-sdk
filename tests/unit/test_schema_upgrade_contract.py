"""Independent pre-implementation receipt/catalog oracle; not migration acceptance."""

import hashlib
import json
from pathlib import Path

FIXTURES = Path(__file__).parents[1] / "fixtures/schema-upgrade-v1"


def test_upgrade_receipt_independent_unicode_vector():
    from simple_harness_memory.migrations import HumanMemorySchemaUpgradeReceipt

    vector = json.loads((FIXTURES / "receipt.json").read_text())
    receipt = HumanMemorySchemaUpgradeReceipt(**vector["payload"])
    assert receipt.receipt_hash == vector["receipt_hash"]
    assert receipt.to_json() == vector["payload"]
    encoded = json.dumps(
        {
            "domain": "memory.schema.source-admission-upgrade.receipt.v1",
            "payload": vector["payload"],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    assert hashlib.sha256(encoded).hexdigest() == vector["receipt_hash"]


def test_physical_catalog_pins_are_not_just_logical_checksums():
    pins = json.loads((FIXTURES / "catalog-pins.json").read_text())
    assert pins["fresh-7.1"] != pins["alter-7.1"]
    assert pins["fresh-7.0+source"] == pins["alter-7.1+source"]
    assert pins["fresh-7.1+source"] == pins["fresh-7.2"]


def test_new_domain_vectors():
    from simple_harness_memory.core.history import history_hash
    from simple_harness_memory.migrations.schema_upgrade import CATALOGS, _added_hash

    vectors = json.loads((FIXTURES / "domain-vectors.json").read_text())
    for vector in vectors:
        assert history_hash(vector["domain"], vector["payload"]) == vector["hash"]
    assert _added_hash(CATALOGS["fresh-7.0"]) == vectors[0]["hash"]
    assert _added_hash(CATALOGS["fresh-7.1"]) == vectors[1]["hash"]
