"""Strict, deterministic r4 Markdown compiler. Uses only the standard library.

Compiling is source extraction, never execution readiness. The production entry
point pins original bytes; parse_document is exposed separately for future
in-memory parser/noninterference tests, not as a CLI fingerprint bypass.
"""

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from .contracts import (
    CorpusError,
    InitialInput,
    RecentMessage,
    ScenarioClock,
    ScriptedFollowup,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_REL = Path(
    "plans/2026-08-29-human-memory-digital-twin/quality/recall-corpus-candidate/"
    "review-zh/successor-12x20"
)
BATCH = "successor-12x20-r4-20260906"
BATCH_SHA256 = "2a69f5712991f665eafed67d5457f7d6b8484885ab186927b57f5a7014c576d1"
INDEX_SHA256 = "56aaf1f52bb15222e4cbcfb693e904d0ea4b773b90e93f952aafa7bfbb228eb3"
MEMBER_SHA256 = {
    "01-exact.md": "f40faead2d85c89d3c5b5f9d3c593a6ae28af530785c918f3681e38097fa0ac7",
    "02-semantic.md": "bd5c3a9d12553f812ba159f9f631d08f35e1b9085562d35cfb4dc99bc3cc5517",
    "03-entity.md": "ded61c11125569d49d1ab0c5e9c1d3c9a51ec25c881610b4cb2f4f8d03d50281",
    "04-time.md": "f26129a86e0d14182b4e18ea58efa289dfb6db0da20299d88af47e3d6a52ecbf",
    "05-task.md": "baac30993526a4dcbcceca8a3d957ecd536d880afff5ef50b41dbc459a41c659",
    "06-cross-scope.md": "2fae2667c1bc24a5ab5d7d685c8e086e6c3491dc530d895ed0fd2b6d051420e1",
    "07-no-match.md": "ccb071fd13ba789006d478d50d2ec80f0453dfe709985f3005f1267fd4da3009",
    "08-suppressed.md": "0904f15157bef5da768049ce777c9dfd852256b380bad1bcdefbc28143e56261",
    "09-superseded.md": "e9c23e7d436638257058cfc59b88d79f15275dd6bdc20136861a1f5350237f74",
    "10-contested-not-required.md": "73a37f6e332c832c2d7100ebe57a89154388671f124f1b0bc9da830e8d033c1d",
    "11-expired.md": "9aba2bd9eafa94a8c265d0fd546417809780b6870f526ee2359b235deb6fee45",
    "12-recipient-private.md": "306756b08a9cffc95d92db5b04f7058e43ad3f2a092fbcd04f4939633a074f69",
    "逐类20条件.md": "72594733c8e6fc077b471fd781955b56bb88ec7ecc094135a52f2da1b6dd4367",
}
DEFAULT_CLOCK = ScenarioClock("2026-09-06T10:00:00+08:00", "Asia/Shanghai")
POLICY_MARKER = "**所有样例共用的可信披露规则（来自独立Host配置，初始可见，不能从gold生成）：**"
CASE_HEADING = re.compile(r"^## (C\d{2}-\d{2})｜([^\n]+)$", re.M)
FIELD = re.compile(r"^\*\*([a-z_]+)（([^\n]+)）：\*\*[ \t]*(.*)$", re.M)
LABELS = re.compile(
    r"^本类(?:继承gold：|gold统一继承：)required_types=(空|[a-z,]+)；"
    r"no_recall=(true|false)；privacy_allowed=(true|false)；"
    r"hard_trigger=([^；]+)；requires_task_scope_search=(true|false)。", re.M
)
NORMAL_FOOTER = (
    "本文件20条；gold是期望，不是实测结果。零查询、零披露、后台gate是否执行"
    "必须分别由真实trace核对。"
)
TASK_FOOTER = (
    "计数：20个逻辑样例，20个首轮字段，22条固定followup（两例各两条）；"
    "不因此计成42个质量样例。"
)
FIELD_ANNOTATIONS = {
    "setup": {"模型初始不可见", "非初始可见，设置端"},
    "provider_input": {"初始可见", "结构化初始输入"},
    "provider_input_first_turn": {"初始可见"},
    "scripted_followup": {"非初始可见，runner调度数据，不是gold"},
    "recent_messages": {"角色/顺序显式，进入真实最近历史"},
    "current_user_message": {"当前用户消息"},
    "scenario_clock": {"设置端，非用户文本/非gold"},
    "gold": {"仅计分端"},
}


@dataclass(frozen=True)
class Case:
    case_id: str
    category: str
    condition: str
    source_file: str
    source_line: int
    setup_source_text: str
    clock_source_text: str | None
    initial_input: InitialInput
    scripted_followup: tuple[ScriptedFollowup, ...]
    labels: dict[str, object]
    oracle_source_text: str


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n").encode("utf-8")


def table(text: str, columns: tuple[str, ...]) -> list[dict[str, str]]:
    """Only the explicit r4 pipe-table subset, never a natural-language split."""
    lines = text.strip().splitlines()
    cells = []
    for line in lines:
        if not (line.startswith("|") and line.endswith("|")) or "\\|" in line:
            raise CorpusError("unsupported table line/escaped pipe")
        row = [cell.strip() for cell in line[1:-1].split("|")]
        if len(row) != len(columns) or any(not cell for cell in row):
            raise CorpusError("table width/empty cell mismatch")
        cells.append(row)
    if len(cells) < 3 or tuple(cells[0]) != columns:
        raise CorpusError("missing table header or data")
    if any(not re.fullmatch(r":?-+:?", cell) for cell in cells[1]):
        raise CorpusError("invalid table separator")
    return [dict(zip(columns, row, strict=True)) for row in cells[2:]]


def one_line(value: str, field: str) -> str:
    if not value or "\n" in value:
        raise CorpusError(f"{field}: expected one nonempty authored line")
    return value


def parse_fields(body: str) -> dict[str, str]:
    matches = list(FIELD.finditer(body))
    if not matches or body[:matches[0].start()].strip():
        raise CorpusError("unaccounted text before fields")
    fields: dict[str, str] = {}
    for i, match in enumerate(matches):
        name, annotation, _ = match.groups()
        if name in fields or annotation not in FIELD_ANNOTATIONS.get(name, set()):
            raise CorpusError(f"duplicate/unsupported field: {name}")
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        # Start at group 3 to retain same-line text AND subsequent table lines.
        fields[name] = body[match.start(3):end].strip()
    return fields


def parse_clock(source: str | None) -> ScenarioClock:
    if source is None:
        return DEFAULT_CLOCK
    match = re.fullmatch(
        r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d)；"
        r"timezone=([A-Za-z_/]+)。[^\n]+", source
    )
    if not match:
        raise CorpusError("unsupported scenario_clock declaration")
    return ScenarioClock(*match.groups())


def parse_followups(source: str, case_id: str) -> tuple[ScriptedFollowup, ...]:
    rows = table(source, (
        "followup_id", "after_event", "fixture_action", "user_message", "on_unmet"
    ))
    expected_count = 2 if case_id in {"C05-16", "C05-20"} else 1
    if len(rows) != expected_count:
        raise CorpusError("unexpected followup count")
    for i, row in enumerate(rows, 1):
        expected_event = "candidate_preview_then_turn_terminal"
        if i == 2:
            expected_event = (
                "new_candidate_preview_after_f1_then_turn_terminal"
                if case_id == "C05-16" else "assistant_turn_terminal_after_f1"
            )
        expected_action = (
            "append_predefined_current_revision" if case_id == "C05-18" else "none"
        )
        if (row["followup_id"] != f"f{i}" or row["after_event"] != expected_event
                or row["fixture_action"] != expected_action
                or row["on_unmet"] != "record_unmet_and_stop_no_rescue"):
            raise CorpusError("unsupported followup event/action/order")
    return tuple(ScriptedFollowup(**row) for row in rows)


def parse_document(filename: str, text: str) -> tuple[Case, ...]:
    """Parse explicit source fields. Gold is never passed to input construction."""
    if filename not in MEMBER_SHA256 or not filename[:2].isdigit():
        raise CorpusError("unknown class member")
    number, category = filename.removesuffix(".md").split("-", 1)
    headings = list(CASE_HEADING.finditer(text))
    expected_ids = [f"C{number}-{i:02}" for i in range(1, 21)]
    if [m[1] for m in headings] != expected_ids:
        raise CorpusError(f"{filename}: expected exactly 20 ordered unique IDs")
    inherited = list(LABELS.finditer(text[:headings[0].start()]))
    if len(inherited) != 1:
        raise CorpusError(f"{filename}: expected one inherited label declaration")
    types, no_recall, privacy, hard, task = inherited[0].groups()
    labels: dict[str, object] = {
        "required_types": [] if types == "空" else types.split(","),
        "no_recall": no_recall == "true",
        "privacy_allowed": privacy == "true",
        "hard_trigger": hard,
        "requires_task_scope_search": task == "true",
    }
    footer = TASK_FOOTER if number == "05" else NORMAL_FOOTER
    if not text.rstrip().endswith("\n\n" + footer):
        raise CorpusError(f"{filename}: unsupported footer")
    content_end = text.rfind("\n\n" + footer)
    cases = []
    for i, heading in enumerate(headings):
        case_id, condition = heading.groups()
        end = headings[i + 1].start() if i + 1 < len(headings) else content_end
        try:
            fields = parse_fields(text[heading.end():end])
            is_history = case_id in {"C07-06", "C07-14"}
            expected_fields = ["setup", "provider_input", "gold"]
            if number == "04":
                expected_fields.insert(0, "scenario_clock")
            if number == "05":
                expected_fields = [
                    "setup", "provider_input_first_turn", "scripted_followup", "gold"
                ]
            if is_history:
                expected_fields = [
                    "setup", "provider_input", "recent_messages", "current_user_message", "gold"
                ]
            if list(fields) != expected_fields:
                raise CorpusError("field names/order differ from explicit r4 layout")
            clock = parse_clock(fields.get("scenario_clock"))
            history: tuple[RecentMessage, ...] = ()
            unresolved = None
            if is_history:
                if fields["provider_input"]:
                    raise CorpusError("structured input marker must have no scalar body")
                rows = table(fields["recent_messages"], ("ordinal", "role", "content"))
                if [(r["ordinal"], r["role"]) for r in rows] != [
                    ("1", "user"), ("2", "assistant")
                ]:
                    raise CorpusError("expected explicit user/assistant causal pair")
                history = (
                    RecentMessage(1, "user", rows[0]["content"]),
                    RecentMessage(2, "assistant", rows[1]["content"]),
                )
                current = one_line(fields["current_user_message"], "current_user_message")
            else:
                key = "provider_input_first_turn" if number == "05" else "provider_input"
                current = one_line(fields[key], key)
                if number == "12" or case_id == "C05-07":
                    # These fields mix host-authoritative prose with user prose.
                    # No implicit role split, trust elevation, or enum fabrication.
                    unresolved, current = current, None
            initial = InitialInput(clock, history, current, unresolved)
            followups = (
                parse_followups(fields["scripted_followup"], case_id) if number == "05" else ()
            )
            cases.append(Case(
                case_id=case_id, category=category, condition=condition,
                source_file=filename, source_line=text.count("\n", 0, heading.start()) + 1,
                setup_source_text=one_line(fields["setup"], "setup"),
                clock_source_text=fields.get("scenario_clock"),
                initial_input=initial, scripted_followup=followups,
                labels=dict(labels), oracle_source_text=one_line(fields["gold"], "gold"),
            ))
        except (ValueError, KeyError) as exc:
            raise CorpusError(f"{case_id}: {exc}") from exc
    return tuple(cases)


def load_sources(source: Path) -> dict[str, str]:
    expected = {**MEMBER_SHA256, "总索引.md": INDEX_SHA256}
    if {p.name for p in source.glob("*.md")} != set(expected):
        raise CorpusError("source Markdown member inventory changed")
    documents = {}
    for filename, digest in sorted(expected.items()):
        path = source / filename
        if path.is_symlink():
            raise CorpusError(f"symlink source member: {filename}")
        data = path.read_bytes()
        if sha256(data) != digest:
            raise CorpusError(f"source fingerprint mismatch: {filename}")
        documents[filename] = data.decode("utf-8")
    canonical = "".join(f"{name}\t{digest}\n" for name, digest in sorted(MEMBER_SHA256.items()))
    if sha256(canonical.encode("utf-8")) != BATCH_SHA256:
        raise CorpusError("compiler's batch pin is inconsistent")
    return documents


def common_setup(index: str) -> dict[str, object]:
    if index.count(POLICY_MARKER) != 1:
        raise CorpusError("missing/ambiguous shared policy marker")
    tail = index.split(POLICY_MARKER, 1)[1]
    policy = tail.strip().split("\n\n", 1)[0]
    if not policy.startswith("> ") or "\n" in policy:
        raise CorpusError("unsupported shared policy block")
    if f"默认scenario_clock为{DEFAULT_CLOCK.instant}" not in index:
        raise CorpusError("default fixture clock changed")
    return {
        "default_scenario_clock": asdict(DEFAULT_CLOCK),
        "policy_source_text": policy[2:],
        "policy_state": "REQUIRES_REAL_HOST_CONFIGURATION_AND_PROJECTION",
        "public_setup_state": "NOT_IMPLEMENTED",
        "authority_receipt": None,
    }


def compile_source(source: Path) -> dict[str, bytes]:
    """Read pinned MD; return disjoint deterministic files without writing/running."""
    documents = load_sources(source)
    cases = [case for name, text in documents.items() if name[:2].isdigit()
             for case in parse_document(name, text)]
    conditions = re.findall(r"^\| (C\d{2}-\d{2}) \| ([^|\n]+) \|$",
                            documents["逐类20条件.md"], re.M)
    if conditions != [(case.case_id, case.condition) for case in cases]:
        raise CorpusError("condition table and case headings differ")
    if len(cases) != 240 or sum(len(c.scripted_followup) for c in cases) != 22:
        raise CorpusError("r4 case/followup total changed")
    artifacts: dict[str, bytes] = {}
    inputs, setups, schedules, oracles, catalog = [], [], [], [], []
    for ordinal, case in enumerate(cases, 1):
        blockers = ["PUBLIC_SETUP_NOT_IMPLEMENTED", "TRUSTED_POLICY_ADAPTER_NOT_IMPLEMENTED",
                    "THREE_LAYER_CLOCK_ADAPTER_NOT_IMPLEMENTED"]
        if case.initial_input.unresolved_source_text is not None:
            blockers.append("EXPLICIT_TRUSTED_CONTEXT_USER_SPLIT_REQUIRED")
        if case.initial_input.recent_messages:
            blockers.append("REAL_RECENT_HISTORY_ADAPTER_NOT_IMPLEMENTED")
        if case.scripted_followup:
            blockers.append("REAL_FOLLOWUP_EVENT_ADAPTER_NOT_IMPLEMENTED")
        if case.case_id == "C05-18":
            blockers.append("PUBLIC_REVISION_FIXTURE_ACTION_NOT_IMPLEMENTED")
        # Parallel JSONL rows use a separate catalog: no class/ID/condition/oracle
        # hash or source filename goes into the authored input payload.
        inputs.append(asdict(case.initial_input))
        setups.append({
            "setup_source_text": case.setup_source_text,
            "scenario_clock": asdict(case.initial_input.scenario_clock),
            "clock_source_text": case.clock_source_text,
            "seed_operations": None, "public_setup_state": "NOT_IMPLEMENTED",
            "ready": False, "executed": False, "blocking_reasons": blockers,
        })
        schedules.append({"scripted_followup": [asdict(f) for f in case.scripted_followup],
                          "scheduler_state": "NOT_IMPLEMENTED"})
        oracles.append({"labels": case.labels, "oracle_source_text": case.oracle_source_text,
                        "scoring_state": "NOT_IMPLEMENTED"})
        catalog.append({"row_ordinal": ordinal, "case_id": case.case_id,
                        "category": case.category, "condition": case.condition,
                        "source_file": case.source_file, "source_line": case.source_line})
    for filename, rows in (
        ("input/initial-input.jsonl", inputs), ("setup/cases.jsonl", setups),
        ("scheduler/cases.jsonl", schedules), ("oracle/cases.jsonl", oracles),
        ("audit/catalog.jsonl", catalog),
    ):
        artifacts[filename] = b"".join(json_bytes(row) for row in rows)
    artifacts["setup/common.json"] = json_bytes(common_setup(documents["总索引.md"]))
    # Full source archive is audit-only, includes gold, and must never be loaded
    # into any Provider request/context or setup authority configuration.
    artifacts["audit/source-documents.json"] = json_bytes(documents)
    artifacts["manifest.json"] = json_bytes({
        "schema_version": "corpus-runtime-input/v1", "batch": BATCH,
        "batch_sha256": BATCH_SHA256, "source_members": MEMBER_SHA256,
        "index_sha256": INDEX_SHA256,
        "compiler_sha256": {p.name: sha256(p.read_bytes()) for p in sorted(
            Path(__file__).parent.glob("*.py"))},
        "files": {name: sha256(data) for name, data in sorted(artifacts.items())},
        "case_count": len(cases), "scripted_followup_count": 22,
        "category_counts": {c.category: sum(x.category == c.category for x in cases)
                            for c in cases},
        "compilation_state": "SOURCE_ONLY", "ready_count": 0, "executed_count": 0,
        "unresolved_input_count": sum(c.initial_input.unresolved_source_text is not None
                                      for c in cases),
        "runtime_state": "BLOCKED_PUBLIC_ADAPTERS", "quality_result": "NOT_RUN",
    })
    return artifacts


def write_artifacts(artifacts: dict[str, bytes], output: Path) -> None:
    """Fresh ignored output only; manifest is the last completion marker."""
    expected_names = {
        "input/initial-input.jsonl", "setup/cases.jsonl", "setup/common.json",
        "scheduler/cases.jsonl", "oracle/cases.jsonl", "audit/catalog.jsonl",
        "audit/source-documents.json", "manifest.json",
    }
    if set(artifacts) != expected_names or any(
        not isinstance(data, bytes) for data in artifacts.values()
    ):
        raise CorpusError("unexpected output members or non-byte artifact")
    ignored = (REPO_ROOT / ".local-test-evidence").resolve()
    target = output.resolve()
    if target == ignored or not target.is_relative_to(ignored):
        raise CorpusError("output must be a new directory inside .local-test-evidence")
    # No overwrites or merging with a partial earlier compilation.
    target.mkdir(parents=True, exist_ok=False)
    for name in [n for n in sorted(artifacts) if n != "manifest.json"] + ["manifest.json"]:
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(artifacts[name])


def main() -> int:
    parser = argparse.ArgumentParser(description="r4源文档编译；不执行公共setup或模型")
    parser.add_argument("--source", type=Path, default=REPO_ROOT / SOURCE_REL)
    parser.add_argument("--output", type=Path, default=(
        REPO_ROOT / ".local-test-evidence/corpus-runtime-input" / BATCH
    ))
    args = parser.parse_args()
    try:
        artifacts = compile_source(args.source)
        write_artifacts(artifacts, args.output)
    except (OSError, ValueError) as exc:
        print(f"编译未完成：{exc}", file=sys.stderr)
        return 2
    print("已提取240条源规格、22条后续轮；ready=0，executed=0，质量=NOT_RUN。")
    return 0
