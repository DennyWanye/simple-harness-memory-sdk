import asyncio, sys, importlib.metadata, faulthandler
faulthandler.dump_traceback_later(60, exit=True)
from pathlib import Path
sys.path.insert(0, "/Users/taiwan/PROJECTS/SimplaHarness/simple-harness-memory-sdk")
from tests.integration.test_prospective_signal_repository_v5 import _setup, _grant, _principal
from simple_harness.runtime import ProspectiveSignalKind as K, ProspectiveLifecycleState as S
from simple_harness_memory.core.identity import MemoryScope

async def main():
    print("wheel:", importlib.metadata.version("simple-harness-memory-sdk"))
    clock=[20.0]
    backend, auth, mid, rev, obx, obh = await _setup(Path("probe.db"), clock)
    scope=MemoryScope.personal("actor-1")
    async def apply(ref):
        return await backend.apply_prospective_signal(principal=_principal(), scope=scope, reference=ref)
    async def q(sql,*p):
        async with backend.connection.execute(sql,p) as c: return [tuple(r) for r in await c.fetchall()]
    try:
        a=_grant(auth, memory_id=mid, revision=rev, kind=K.REGISTRATION_ACCEPTED, transition_from=S.PENDING, transition_to=S.PENDING, observed_at=20.0, outbox_id=obx, outbox_hash=obh, signal_id="acc-1")
        r1=await apply(a); r2=await apply(a)
        print("A1 same-ref replay:", r1.outcome.value, r2.outcome.value, "equal=", r1==r2, "resolutions=", auth.resolutions)
        clock[0]=21.0
        a2=_grant(auth, memory_id=mid, revision=rev, kind=K.REGISTRATION_ACCEPTED, transition_from=S.PENDING, transition_to=S.PENDING, observed_at=21.0, outbox_id=obx, outbox_hash=obh, signal_id="acc-2")
        try:
            r3=await apply(a2); print("A2 new-identity re-ack:", r3.outcome.value, r3.reason_code)
        except Exception as e:
            print("A2 new-identity re-ack RAISED:", type(e).__name__, e)
        print("   scheduler_registrations rows:", await q("SELECT state,registration_revision,substr(outbox_id,1,20) FROM prospective_scheduler_registrations WHERE memory_id=?", mid))
        clock[0]=30.0
        d=_grant(auth, memory_id=mid, revision=1, kind=K.TIME_DUE, transition_from=S.PENDING, transition_to=S.TRIGGERED, observed_at=30.0, signal_id="due-1", receipt_id="due-r1")
        b1=await apply(d); print("B1 TIME_DUE:", b1.outcome.value, b1.lifecycle_state.value, "rev", b1.committed_revision)
        print("B1 same-ref replay equal:", (await apply(d))==b1)
        clock[0]=31.0
        d2=_grant(auth, memory_id=mid, revision=1, kind=K.TIME_DUE, transition_from=S.PENDING, transition_to=S.TRIGGERED, observed_at=31.0, signal_id="due-2", receipt_id="due-r2")
        try:
            b2=await apply(d2); print("B2 TIME_DUE new-identity replay:", b2.outcome.value, b2.reason_code, b2.lifecycle_state.value)
        except Exception as e:
            print("B2 RAISED:", type(e).__name__, e)
        print("   trigger_events:", await q("SELECT outcome,signal_kind,substr(occurrence_key,1,8),prospective_revision FROM prospective_trigger_events WHERE memory_id=? ORDER BY occurred_at", mid))
        page=await backend.read_occurrence_inbox(principal=_principal())
        print("   inbox:", [(e.outcome,e.lifecycle_state,e.occurrence_key[:8]) for e in page.entries])
        print("C outbox:", await q("SELECT topic,state FROM outbox ORDER BY created_at"))
        print("D signal kinds:", [k.value for k in K])
        clock[0]=40.0
        ex=_grant(auth, memory_id=mid, revision=2, kind=K.EXPIRED, transition_from=S.TRIGGERED, transition_to=S.EXPIRED, observed_at=40.0, signal_id="exp-1", receipt_id="exp-r1")
        try:
            e1=await apply(ex); print("E EXPIRED from TRIGGERED:", e1.outcome.value, e1.lifecycle_state.value, e1.reason_code)
        except Exception as e:
            print("E EXPIRED RAISED:", type(e).__name__, e)
        page=await backend.read_occurrence_inbox(principal=_principal())
        print("   inbox after expire:", [(e.outcome,e.lifecycle_state,e.signal_kind) for e in page.entries])
    finally:
        await backend.close()
asyncio.run(main())
