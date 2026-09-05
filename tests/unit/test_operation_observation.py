"""OA1 literal vector frozen before product implementation."""
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest


def test_independent_observation_vector():
    from simple_harness_memory import MemoryOperationObservationV1

    v = json.loads((Path(__file__).parents[1] / "fixtures/operation-audit-v1/observation.json").read_text())
    observation = MemoryOperationObservationV1(**v["observation"])
    assert observation.observation_hash == v["observation_hash"]
    assert observation.to_json() == v["observation"]
    with pytest.raises(FrozenInstanceError):
        observation.reason = "invented"
