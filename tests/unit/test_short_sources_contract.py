"""B independent vector fixed before implementation, no selection PASS claim."""

import json
from pathlib import Path


def test_short_sources_independent_vector():
    import simple_harness_memory as m

    vector = json.loads(
        (Path(__file__).parents[1] / "fixtures/schema-upgrade-v1/short-sources.json").read_text()
    )
    ref = m.ShortHorizonSourceRef(**vector["source"])
    item = m.ShortHorizonSourceItem(**{**vector["item"], "source_refs": (ref,)})
    snapshot = m.ShortHorizonSourceSnapshot(**{**vector["snapshot"], "items": (item,)})
    assert snapshot.to_json() == vector["snapshot"]
    assert snapshot.snapshot_hash == vector["snapshot_hash"]
