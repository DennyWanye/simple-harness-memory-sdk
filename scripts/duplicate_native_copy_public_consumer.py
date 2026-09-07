"""Public read-only behavior on a disposable native DB copy and exact Host S1 inputs.

The caller copies main/WAL/SHM and exports exact Host S1 pairs before invoking this.
No SDK SQL, source-origin invention, suppression writes, provider, or native app.
SQLite may checkpoint the disposable copy; the original is never opened by this script.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

import simple_harness as h

import simple_harness_memory as m
from simple_harness_memory.migrations import migrate_human_memory_v7_to_v7_2


async def run(args):
    assert sys.flags.isolated and "PYTHONPATH" not in os.environ
    assert m.__version__ == "0.6.10"
    assert Path(m.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
    data = json.loads(args.inputs.read_text())
    principal = m.MemoryPrincipal(**data["principal"])
    bindings = tuple(
        m.HistoryEvidenceBinding(
            h.SanitizedEvidenceEnvelope.from_json(item["envelope"]),
            h.SanitizedEvidenceReceipt.from_json(item["receipt"]),
        )
        for item in data["bindings"]
    )
    context = replace(
        bindings[0].envelope.disclosure_context,
        run_id="actual-installed-copy-history-read",
        purpose=h.DisclosurePurpose.USER_REVIEW,
    )
    kwargs = dict(
        supported_filter_policies=frozenset(data["supported_filter_policies"]),
        classification_policy=m.InformationClassificationPolicy(
            "deskpet-host-classification",
            "1",
            "host:classification/v1",
            h.PrivacyClass.PERSONAL,
            (),
        ),
    )
    upgrade = await migrate_human_memory_v7_to_v7_2(
        args.database,
        backup_path=args.database.with_suffix(".pre-schema-7.2.backup"),
    )
    snapshots = []
    for _ in range(2):
        manager = await m.build_human_memory_v7(args.database, **kwargs)
        try:
            result = await manager.check_history_visibility(
                principal=principal,
                disclosure_context=context,
                bindings=bindings,
            )
            assert [x.visible for x in result.items] == [False, False, False]
            assert result.items[0].reason == "history_source_cut_unverifiable"
            snapshots.append(result.to_json())
        finally:
            await manager.close()
    assert snapshots[0]["policy_hash"] == snapshots[1]["policy_hash"]
    result = dict(
        status="PASS",
        version=m.__version__,
        installed=True,
        input_sha256=hashlib.sha256(args.inputs.read_bytes()).hexdigest(),
        stages=["native-copy-existing-v1-legacy-refusal", "reopen-same-policy"],
        snapshots=snapshots,
        migration=None if upgrade is None else upgrade.to_json(),
        original_opened=False,
        original_native_loop_pass=False,
    )
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k not in {"snapshots", "migration"}}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("inputs", type=Path)
    parser.add_argument("output", type=Path)
    asyncio.run(run(parser.parse_args()))
