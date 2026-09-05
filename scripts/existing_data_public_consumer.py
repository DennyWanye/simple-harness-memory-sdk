"""Installed069 public consumer over actual OLD-wheel nonempty WAL inputs.

No SDK private imports, SQL, provider, UI, or rewritten expected product results.
Host S1 factories below are deterministic consumer inputs; not native Host proof.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

import simple_harness as h

import simple_harness_memory as m
from simple_harness_memory.migrations import migrate_human_memory_v7_to_v7_2

NOW = 1_000_020.0


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inputs():
    # Reuse only the public DTO input factories, never its old-version run/assertions.
    path = Path(__file__).with_name("source_only_public_consumer.py")
    spec = importlib.util.spec_from_file_location("source_inputs", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def run(args):
    assert m.__version__ == "0.6.9" and h.__version__ == "0.7.2"
    assert "PYTHONPATH" not in os.environ and "PYTHONHOME" not in os.environ
    if not args.source_smoke:
        assert sys.flags.isolated
        assert Path(m.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
        assert Path(h.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
    args.output.mkdir(parents=True, exist_ok=False)
    factory = inputs()
    stages, receipts = [], {}
    for original in args.old_fixtures:
        frozen = json.loads((original / "before.json").read_text())
        name = frozen["version"]
        folder = args.output / name
        folder.mkdir()
        path, backup = folder / "memory.db", folder / "memory.db.pre-schema-7.2.backup"
        for suffix in ("", "-wal", "-shm"):
            source = original / ("old.db" + suffix)
            if source.exists():
                shutil.copyfile(source, path.with_name(path.name + suffix))
        principal = m.MemoryPrincipal(**frozen["principal"])
        history = tuple(
            m.HistoryEvidenceBinding(
                h.SanitizedEvidenceEnvelope.from_json(item["envelope"]),
                h.SanitizedEvidenceReceipt.from_json(item["receipt"]),
            )
            for item in frozen["history_inputs"]
        )
        context = history[0].envelope.disclosure_context
        first = await migrate_human_memory_v7_to_v7_2(
            path,
            backup_path=backup,
            expected_initialization_receipt_hash=frozen["initialization"]["receipt_hash"],
        )
        assert first is not None
        assert first.preserved_old_columns_root_hash == frozen["old_columns_root"]
        assert (
            first.original_initialization_receipt_hash == frozen["initialization"]["receipt_hash"]
        )
        backup_hash = sha(backup)
        assert first.backup_sha256 == backup_hash
        kwargs = dict(
            clock=lambda: NOW,
            classification_policy=m.InformationClassificationPolicy(
                "memory-classification-policy",
                "1",
                "memory-policy-registry:classification/v1",
                h.PrivacyClass.PERSONAL,
                (),
            ),
        )
        manager = await m.build_human_memory_v7(path, **kwargs)
        try:
            observed = await manager.check_history_visibility(
                principal=principal, disclosure_context=context, bindings=history
            )
            assert [item.visible for item in observed.items] == [False, True], observed.to_json()
            pending = await manager.read_outbox(principal=principal)
            assert pending.entries
            reg, _ = factory._registration(2000)
            admitted = await manager.admit_evidence_source(
                principal=principal, envelope=reg.envelope, receipt=reg.admission_receipt
            )
            assert admitted.accepted_at == NOW
            assert "mutation_job_id" not in admitted.to_json()
            assert await manager.read_outbox(principal=principal) == pending
            # Real old recall input; unsupported integer protocol is rejected before
            # expiry/narrowing and carries only the scoped admission witness.
            try:
                await manager.execute_typed_recall(
                    principal=principal,
                    context=h.RecallContext.from_json(frozen["recall"]["context"]),
                    plan=h.RecallPlan.from_json(frozen["recall"]["plan"]),
                    harness_protocol=5,
                )
            except m.MemoryValidationError as exc:
                assert str(exc) == "typed_recall_protocol_unsupported"
                rejection = exc.rejection_receipt.to_json()
                assert rejection["stage"] == "protocol"
                assert rejection["candidate_query_started"] is False
            else:
                raise AssertionError("unsupported protocol admitted")
            if "short" in frozen:
                binding = m.HistoryShortHorizonBinding(**frozen["short"])
                sources = await manager.resolve_short_horizon_sources(
                    principal=principal, disclosure_context=context, bindings=(binding,)
                )
                assert sources.evaluated_at == NOW and sources.items[0].complete
                assert [ref.evidence_id for ref in sources.items[0].source_refs] == ["evidence-100"]
                forged = m.HistoryShortHorizonBinding(
                    "forged", binding.chunk_ref, binding.content_hash
                )
                denied = await manager.resolve_short_horizon_sources(
                    principal=principal, disclosure_context=context, bindings=(forged,)
                )
                assert not denied.items[0].visible and denied.items[0].source_refs == ()
                await manager.suppress(
                    principal=principal,
                    request=m.SuppressionRequest(
                        "installed-forget-selected",
                        principal.actor_id,
                        m.SuppressionScopeKind.EVIDENCE,
                        "evidence-100",
                        "user_forget",
                        NOW,
                    ),
                )
                denied = await manager.resolve_short_horizon_sources(
                    principal=principal, disclosure_context=context, bindings=(binding,)
                )
                assert not denied.items[0].visible and not denied.items[0].complete
                assert denied.items[0].source_refs == ()
        finally:
            await manager.close()
        assert await migrate_human_memory_v7_to_v7_2(path, backup_path=backup) == first
        assert sha(backup) == backup_hash
        manager = await m.build_human_memory_v7(path, **kwargs)
        try:
            assert (
                await manager.admit_evidence_source(
                    principal=principal, envelope=reg.envelope, receipt=reg.admission_receipt
                )
                == admitted
            )
            if "short" in frozen:
                denied = await manager.resolve_short_horizon_sources(
                    principal=principal, disclosure_context=context, bindings=(binding,)
                )
                assert not denied.items[0].visible and denied.items[0].source_refs == ()
        finally:
            await manager.close()
        assert await migrate_human_memory_v7_to_v7_2(path, backup_path=backup) == first
        assert sha(backup) == backup_hash
        receipts[name] = {**first.to_json(), "receipt_hash": first.receipt_hash}
        stages.append(name + ": old-WAL-upgrade/history/clock/source/rejection/reopen/exact-backup")
        if "short" in frozen:
            stages.append(name + ": actual-old-selected-sources/forge/forget/reopen-deny")
    fresh = args.output / "fresh.db"
    manager = await m.build_human_memory_v7(fresh, clock=lambda: NOW)
    await manager.close()
    assert (
        await migrate_human_memory_v7_to_v7_2(fresh, backup_path=args.output / "unused.backup")
        is None
    )
    assert not (args.output / "unused.backup").exists()
    stages.append("valid-current-7.2-noop-no-backup")
    result = dict(
        status="PASS",
        version=m.__version__,
        installed=not args.source_smoke,
        stages=stages,
        receipts=receipts,
        memory_origin=str(Path(m.__file__).resolve()),
        harness_origin=str(Path(h.__file__).resolve()),
    )
    (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": "PASS",
                "version": m.__version__,
                "stages": stages,
                "installed": not args.source_smoke,
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("old_fixtures", type=Path, nargs="+")
    parser.add_argument("--source-smoke", action="store_true")
    asyncio.run(run(parser.parse_args()))
