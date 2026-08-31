#!/usr/bin/env python3
"""Throwaway executable spikes for the semantic-relation plan.

This proves two structural assumptions only. It is not production code and is
not delivery evidence for the public SDK behavior.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class Operation:
    operation_id: str
    kind: str
    memory_type: str
    dependencies: tuple[str, ...] = ()
    relation_endpoints: tuple[str, ...] = ()
    revision_target_type: str | None = None


def validate_relation_dag(operations: tuple[Operation, ...]) -> None:
    by_id: dict[str, Operation] = {}
    for operation in operations:
        if operation.revision_target_type is not None:
            assert operation.revision_target_type == operation.memory_type
        for dependency in operation.dependencies:
            assert dependency in by_id, "dependency must refer to an earlier operation"
        for endpoint_operation_id in operation.relation_endpoints:
            assert endpoint_operation_id in operation.dependencies
            producer = by_id.get(endpoint_operation_id)
            assert producer is not None, "relation endpoint producer must be earlier"
            assert producer.kind == "create", "relation endpoint producer must be CREATE"
        by_id[operation.operation_id] = operation


def endpoint_dag_spike() -> dict[str, object]:
    valid = (
        Operation("preference", "create", "semantic"),
        Operation("procedure", "create", "procedure"),
        Operation(
            "relation",
            "create",
            "semantic",
            dependencies=("preference", "procedure"),
            relation_endpoints=("preference", "procedure"),
        ),
    )
    validate_relation_dag(valid)
    rejected: list[str] = []
    invalid_cases = {
        "missing_dependency": (
            valid[0],
            valid[1],
            Operation(
                "relation", "create", "semantic",
                dependencies=("preference",),
                relation_endpoints=("preference", "procedure"),
            ),
        ),
        "forward_reference": (
            valid[0],
            Operation(
                "relation", "create", "semantic",
                dependencies=("preference", "procedure"),
                relation_endpoints=("preference", "procedure"),
            ),
            valid[1],
        ),
        "non_create_producer": (
            Operation("preference", "revise", "semantic", revision_target_type="semantic"),
            valid[1],
            valid[2],
        ),
        "revision_target_type_mismatch": (
            Operation("bad-revision", "revise", "semantic", revision_target_type="procedure"),
        ),
    }
    for name, case in invalid_cases.items():
        try:
            validate_relation_dag(case)
        except AssertionError:
            rejected.append(name)
    assert rejected == list(invalid_cases)
    return {
        "valid_cross_type_created_endpoints": True,
        "revision_target_same_type_rule_preserved": True,
        "rejected": rejected,
    }


def relation_domain_sqlite_spike() -> dict[str, object]:
    db = sqlite3.connect(":memory:")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(
        """
        CREATE TABLE revisions (
            memory_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            PRIMARY KEY(memory_id, revision)
        );
        CREATE TABLE relations (
            relation_id TEXT PRIMARY KEY,
            relation_domain TEXT NOT NULL,
            relation_kind TEXT NOT NULL,
            source_memory_id TEXT NOT NULL,
            source_revision INTEGER NOT NULL,
            target_memory_id TEXT NOT NULL,
            target_revision INTEGER NOT NULL,
            relation_memory_id TEXT,
            relation_memory_revision INTEGER,
            CHECK (
              (relation_domain='evolution'
               AND relation_kind IN ('amends','supersedes','contests','relates_to')
               AND relation_memory_id IS NULL AND relation_memory_revision IS NULL)
              OR
              (relation_domain='knowledge'
               AND relation_kind IN ('applies_to')
               AND relation_memory_id IS NOT NULL AND relation_memory_revision IS NOT NULL)
            ),
            FOREIGN KEY(source_memory_id, source_revision)
                REFERENCES revisions(memory_id, revision),
            FOREIGN KEY(target_memory_id, target_revision)
                REFERENCES revisions(memory_id, revision),
            FOREIGN KEY(relation_memory_id, relation_memory_revision)
                REFERENCES revisions(memory_id, revision)
        );
        """
    )
    db.executemany(
        "INSERT INTO revisions VALUES(?,?)",
        (("preference", 1), ("procedure", 1), ("relation-memory", 1)),
    )
    db.execute(
        "INSERT INTO relations VALUES(?,?,?,?,?,?,?,?,?)",
        ("evolution-row", "evolution", "relates_to", "preference", 1,
         "procedure", 1, None, None),
    )
    db.execute(
        "INSERT INTO relations VALUES(?,?,?,?,?,?,?,?,?)",
        ("knowledge-row", "knowledge", "applies_to", "preference", 1,
         "procedure", 1, "relation-memory", 1),
    )
    invalid = (
        ("knowledge-owner-null", "knowledge", "applies_to", None, None),
        ("evolution-owner-present", "evolution", "relates_to", "relation-memory", 1),
        ("knowledge-owner-missing-fk", "knowledge", "applies_to", "missing", 1),
    )
    rejected: list[str] = []
    for relation_id, domain, kind, owner_id, owner_revision in invalid:
        try:
            db.execute(
                "INSERT INTO relations VALUES(?,?,?,?,?,?,?,?,?)",
                (relation_id, domain, kind, "preference", 1, "procedure", 1,
                 owner_id, owner_revision),
            )
        except sqlite3.IntegrityError:
            rejected.append(relation_id)
    assert rejected == [item[0] for item in invalid]
    rows = db.execute(
        "SELECT relation_domain, relation_kind, relation_memory_id "
        "FROM relations ORDER BY relation_id"
    ).fetchall()
    assert rows == [
        ("evolution", "relates_to", None),
        ("knowledge", "applies_to", "relation-memory"),
    ]
    return {"accepted_rows": rows, "rejected": rejected}


def main() -> None:
    result = {
        "SPIKE-RELATION-ENDPOINT-DAG": endpoint_dag_spike(),
        "SPIKE-RELATION-DOMAIN-CHECK": relation_domain_sqlite_spike(),
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
