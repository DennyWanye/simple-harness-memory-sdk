"""SPIKE A1 (disposable): post-turn closure invocation through the Host's real
ProductProviderAdapter, rebuilt from a Run-binding-like snapshot, against the real
provider in llm_runtime.json. Asserts a structured task_scope_update tool call comes
back with a TaskScopeMutationPlan-shaped payload. API key never printed."""
import asyncio, json, sys, time, hashlib
from pathlib import Path
from types import SimpleNamespace
import httpx
from simple_harness.contracts.identity import RequestId
from simple_harness.contracts.messages import Message, MessageRole
from simple_harness.providers.base import ProviderRequest, ProviderToolSpec, CancelToken
from deskpet.sdk_adapters.provider import ProductProviderAdapter
from simple_harness import thaw_json

RUNTIME = json.loads((Path.home() / "Library/Application Support/com.dennywanye.simpleharness/llm_runtime.json").read_text())

class Registry:  # spike-only stand-in for LLMProviderRegistry (same Protocol)
    def get_entry(self, provider_id):
        return SimpleNamespace(enabled=True, model=RUNTIME["model"], models=(), base_url=RUNTIME["base_url"], config_revision=1, incarnation_id="spike-inc")
    def resolve_api_key(self, provider_id):
        return RUNTIME["api_key"]

TOOL = ProviderToolSpec(
    name="task_scope_update",
    description="Submit the TaskScope semantic closure for this turn: either a mutation plan describing what materially changed (goal/phase/completed/changed/next action) or an explicit no_mutation with a closure_reason. Every operation must cite evidence_refs from the provided list.",
    parameters={
        "type": "object", "additionalProperties": False,
        "required": ["outcome", "base_revision", "evidence_refs", "idempotency_key"],
        "properties": {
            "outcome": {"type": "string", "enum": ["mutate", "no_mutation"]},
            "base_revision": {"type": "integer"},
            "closure_reason": {"type": "string"},
            "evidence_refs": {"type": "array", "items": {"type": "string"}},
            "idempotency_key": {"type": "string"},
            "operations": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                "required": ["operation_id", "kind", "value", "reason_code", "evidence_refs"],
                "properties": {
                    "operation_id": {"type": "string"},
                    "kind": {"type": "string", "enum": ["status.update", "phase.update", "completed.append", "changed.append", "next_action.update", "checkpoint.request", "task.complete"]},
                    "value": {"type": "string"},
                    "reason_code": {"type": "string"},
                    "evidence_refs": {"type": "array", "items": {"type": "string"}}}}}}})

SYSTEM = ("你是桌面工作台的主模型。这一轮你已经替用户完成了工作并写好了最终回答，但任务档案还没有收口。"
          "现在只允许调用 task_scope_update 一次：如果客观事件表明任务状态/进度/下一步发生了实质变化，提交 outcome=mutate 并逐项引用 evidence_refs；"
          "如果没有实质变化，提交 outcome=no_mutation 并给 closure_reason。不要输出其他内容，不要重复最终回答。")
OBS = {
    "task_scope": {"task_scope_id": "ts-readme-bump", "title": "发布 1.2.0", "current_revision": 7,
                    "status": "in_progress", "next_action": "更新 README 版本号并跑测试"},
    "staged_final_answer": "已把 README.md 里的版本号从 1.1.3 改成 1.2.0，并确认测试全部通过（42 passed）。",
    "objective_events": [
        {"evidence_ref": "ev-file-0091", "kind": "host.file", "summary": "write_file README.md: '1.1.3' -> '1.2.0' (1 line changed)"},
        {"evidence_ref": "ev-test-0092", "kind": "host.test", "summary": "run_shell pytest -q: 42 passed, exit 0"}],
    "allowed_evidence_refs": ["ev-file-0091", "ev-test-0092"]}

async def main():
    adapter = ProductProviderAdapter(Registry(), provider_id="spike-provider", client=httpx.AsyncClient(timeout=120),
                                     price_resolver=lambda p, m: (1000, 2000, "spike-price-v1"), model=RUNTIME["model"], model_params={})
    print("target:", adapter.target.provider_id, adapter.target.model, adapter.target.endpoint_identity[:12])
    req = ProviderRequest(request_id=RequestId("spike-a1-closure-1"),
                          messages=(Message(role=MessageRole.SYSTEM, content=SYSTEM),
                                    Message(role=MessageRole.USER, content="[closure observation]\n" + json.dumps(OBS, ensure_ascii=False, indent=1))),
                          tools=(TOOL,), max_output_tokens=800)
    t0 = time.monotonic()
    resp = await adapter.invoke(req, cancel=CancelToken())
    dt = time.monotonic() - t0
    print(f"elapsed={dt:.1f}s finish={resp.finish_reason} model={resp.model} usage={resp.usage}")
    print("assistant_text:", repr(resp.message.content)[:200])
    print("tool_calls:", len(resp.tool_calls))
    ok = False
    for call in resp.tool_calls:
        args = thaw_json(call.arguments)
        print(json.dumps({"name": call.name, "arguments": args}, ensure_ascii=False, indent=1))
        refs = set(args.get("evidence_refs", [])) | {r for op in args.get("operations", []) for r in op.get("evidence_refs", [])}
        ok = (call.name == "task_scope_update" and args.get("outcome") in ("mutate", "no_mutation")
              and args.get("base_revision") == 7 and refs and refs <= set(OBS["allowed_evidence_refs"])
              and (args["outcome"] == "no_mutation" or args.get("operations")))
    print("A1_VERDICT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1

sys.exit(asyncio.run(main()))
