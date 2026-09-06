"""Bounded stdlib acceptance. Invoke through the shared resource runner only."""

import argparse
import json
import re
import shutil
import subprocess
import sys
import unittest
from collections import Counter
from dataclasses import asdict, replace
from pathlib import Path

from . import compiler as c
from .contracts import CorpusError, RecentMessage, project_authored_conversation

ARTIFACT_ROOT: Path


class CorpusAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = c.REPO_ROOT / c.SOURCE_REL
        cls.documents = c.load_sources(cls.source)
        cls.cases = [case for name, text in cls.documents.items() if name[:2].isdigit()
                     for case in c.parse_document(name, text)]
        cls.by_id = {case.case_id: case for case in cls.cases}

    def test_01_original_member_hashes_and_240_order(self):
        self.assertEqual([case.case_id for case in self.cases], [
            f"C{category:02}-{row:02}" for category in range(1, 13) for row in range(1, 21)
        ])
        self.assertEqual(len(Counter(case.category for case in self.cases)), 12)
        self.assertEqual(set(Counter(case.category for case in self.cases).values()), {20})
        rows = re.findall(r"^\| ([^|]+\.md) \| `([0-9a-f]{64})` \|$",
                          self.documents["总索引.md"], re.M)
        self.assertEqual(dict(rows), c.MEMBER_SHA256)
        canonical = "".join(f"{name}\t{digest}\n" for name, digest in sorted(rows))
        self.assertEqual(c.sha256(canonical.encode()),
                         "2a69f5712991f665eafed67d5457f7d6b8484885ab186927b57f5a7014c576d1")

    def test_02_labels_preserve_original_class_contract(self):
        expected = [
            (["semantic"], False, True, "无", False),
            (["semantic"], False, True, "无", False),
            (["episode", "semantic"], False, True, "无", False),
            (["episode", "prospective"], False, True, "无", False),
            ([], False, True, "无", True),
            (["semantic", "procedure"], False, True, "无", False),
            ([], True, True, "无", False),
            ([], True, False, "suppression", False),
            ([], True, False, "state-eligibility", False),
            ([], True, False, "state-eligibility", False),
            ([], True, False, "time-eligibility", False),
            ([], True, False, "recipient-purpose", False),
        ]
        keys = ("required_types", "no_recall", "privacy_allowed", "hard_trigger",
                "requires_task_scope_search")
        for case in self.cases:
            with self.subTest(case=case.case_id):
                self.assertEqual(tuple(case.labels[k] for k in keys),
                                 expected[int(case.case_id[1:3]) - 1])

    def test_03_clocks_and_c07_real_history_plan(self):
        for case in self.cases:
            expected = ("2026-09-30T18:00:00+08:00" if case.case_id == "C04-15"
                        else "2026-09-06T10:00:00+08:00")
            self.assertEqual(case.initial_input.scenario_clock.instant, expected)
            self.assertEqual(case.initial_input.scenario_clock.timezone, "Asia/Shanghai")
        for case_id, user, assistant in (
            ("C07-06", "红盒放钥匙，蓝盒放卡片。", "收到，钥匙在红盒，卡片在蓝盒。"),
            ("C07-14", "书架第二层留空。", "收到，第二层留空。"),
        ):
            value = self.by_id[case_id].initial_input
            self.assertEqual(value.recent_messages,
                             (RecentMessage(1, "user", user), RecentMessage(2, "assistant", assistant)))
            messages = project_authored_conversation(value)
            self.assertEqual([m["role"] for m in messages], ["user", "assistant", "user"])
            self.assertEqual(messages[-1]["content"], value.current_user_message)

    def test_04_followups_are_22_scheduled_rows_not_initial_messages(self):
        task_cases = [case for case in self.cases if case.category == "task"]
        self.assertEqual(sum(len(case.scripted_followup) for case in task_cases), 22)
        for case in task_cases:
            self.assertEqual(len(case.scripted_followup),
                             2 if case.case_id in {"C05-16", "C05-20"} else 1)
            value = asdict(case.initial_input)
            self.assertNotIn("scripted_followup", value)
            for row in case.scripted_followup:
                self.assertNotIn(row.user_message, c.json_bytes(value).decode())
        self.assertEqual(self.by_id["C05-18"].scripted_followup[0].fixture_action,
                         "append_predefined_current_revision")
        self.assertIn("2026年8月", self.by_id["C05-15"].setup_source_text)

    def test_05_all_gold_replacements_leave_inputs_setup_schedule_unchanged(self):
        for filename, text in self.documents.items():
            if not filename[:2].isdigit():
                continue
            mutated = re.sub(r"(?m)^(\*\*gold（仅计分端）：\*\*) .*",
                             r"\1 GOLD_MUTATION_SENTINEL", text)
            # Also perturb inherited labels: they must never select prompt/tools/clock.
            mutated = mutated.replace("no_recall=true", "no_recall=false")
            original = c.parse_document(filename, text)
            changed = c.parse_document(filename, mutated)
            for before, after in zip(original, changed, strict=True):
                self.assertEqual(c.json_bytes(asdict(before.initial_input)),
                                 c.json_bytes(asdict(after.initial_input)))
                self.assertEqual(before.setup_source_text, after.setup_source_text)
                self.assertEqual(before.scripted_followup, after.scripted_followup)
                self.assertEqual(after.oracle_source_text, "GOLD_MUTATION_SENTINEL")

    def test_06_setup_replacements_do_not_build_input(self):
        for filename, text in self.documents.items():
            if not filename[:2].isdigit():
                continue
            mutated = re.sub(r"(?m)^(\*\*setup（[^\n]+）：\*\*) .*",
                             r"\1 SETUP_MUTATION_SENTINEL", text)
            for before, after in zip(c.parse_document(filename, text),
                                     c.parse_document(filename, mutated), strict=True):
                self.assertEqual(before.initial_input, after.initial_input)
                self.assertEqual(after.setup_source_text, "SETUP_MUTATION_SENTINEL")
                self.assertEqual(before.oracle_source_text, after.oracle_source_text)

    def test_07_followup_replacements_do_not_enter_first_turn(self):
        filename = "05-task.md"
        text = self.documents[filename]
        mutated = re.sub(r"(?m)^\| f[12] \| .*\|$", lambda m: "|".join(
            m[0].split("|")[:4] + [" FOLLOWUP_MUTATION_SENTINEL "] + m[0].split("|")[5:]
        ), text)
        for before, after in zip(c.parse_document(filename, text),
                                 c.parse_document(filename, mutated), strict=True):
            self.assertEqual(before.initial_input, after.initial_input)
            self.assertTrue(all(f.user_message == "FOLLOWUP_MUTATION_SENTINEL"
                                for f in after.scripted_followup))
            self.assertEqual(before.oracle_source_text, after.oracle_source_text)

    def test_08_unresolved_21_inputs_refuse_projection(self):
        blocked = []
        for case in self.cases:
            if case.initial_input.unresolved_source_text is not None:
                blocked.append(case.case_id)
                self.assertIsNone(case.initial_input.current_user_message)
                with self.assertRaises(CorpusError):
                    project_authored_conversation(case.initial_input)
            else:
                self.assertEqual(project_authored_conversation(case.initial_input)[-1]["role"],
                                 "user")
        self.assertEqual(blocked, ["C05-07"] + [f"C12-{i:02}" for i in range(1, 21)])
        with self.assertRaises(TypeError):
            project_authored_conversation(self.cases[0])

    def test_09_unknown_duplicate_or_missing_fields_rejected(self):
        filename = "01-exact.md"
        text = self.documents[filename]
        variants = [
            text.replace("**provider_input（初始可见）：**", "**unknown_input（初始可见）：**", 1),
            text.replace("C01-02｜", "C01-01｜", 1),
            text.replace("**setup（模型初始不可见）：**", "**gold（仅计分端）：**", 1),
            text.replace("**provider_input（初始可见）：**", "**provider_input（未知角色）：**", 1),
            text + "\nUNACCOUNTED_TRAILER\n",
        ]
        for value in variants:
            with self.subTest(variant=variants.index(value)), self.assertRaises(CorpusError):
                c.parse_document(filename, value)

    def test_10_bad_history_schedule_and_clock_rejected(self):
        variants = [
            ("07-no-match.md", "| 1 | user |", "| 1 | system |"),
            ("07-no-match.md", "| 2 | assistant |", "| 3 | assistant |"),
            ("05-task.md", "| f1 | candidate_preview_then_turn_terminal |",
             "| f1 | guessed_candidate_from_gold |"),
            ("05-task.md", "| followup_id | after_event |", "| followup_id | broken |"),
            ("04-time.md", "10:00:00+08:00；timezone=Asia/Shanghai",
             "10:00:00+00:00；timezone=Asia/Shanghai"),
        ]
        for filename, old, new in variants:
            self.assertIn(old, self.documents[filename])
            with self.subTest(file=filename, mutation=new), self.assertRaises(CorpusError):
                c.parse_document(filename, self.documents[filename].replace(old, new, 1))

    def test_11_repeat_compilation_and_blocked_setup_outputs(self):
        first, second = c.compile_source(self.source), c.compile_source(self.source)
        self.assertEqual(first, second)
        manifest = json.loads(first["manifest.json"])
        self.assertEqual(manifest["case_count"], 240)
        self.assertEqual(manifest["unresolved_input_count"], 21)
        self.assertEqual((manifest["ready_count"], manifest["executed_count"]), (0, 0))
        self.assertEqual(manifest["quality_result"], "NOT_RUN")
        for line in first["setup/cases.jsonl"].splitlines():
            row = json.loads(line)
            self.assertIsNone(row["seed_operations"])
            self.assertFalse(row["ready"])
            self.assertFalse(row["executed"])
        for line in first["input/initial-input.jsonl"].splitlines():
            self.assertEqual(set(json.loads(line)), {
                "scenario_clock", "recent_messages", "current_user_message", "unresolved_source_text"
            })
        self.assertEqual(json.loads(first["audit/source-documents.json"]), self.documents)

    def test_12_fingerprint_change_and_extra_member_rejected(self):
        copy = ARTIFACT_ROOT / "mutated-source"
        shutil.copytree(self.source, copy)
        target = copy / "01-exact.md"
        original = target.read_bytes()
        target.write_bytes(original + b"\n")
        with self.assertRaisesRegex(CorpusError, "fingerprint mismatch"):
            c.compile_source(copy)
        target.write_bytes(original)
        extra = copy / "extra.md"
        extra.write_text("not a formal case\n")
        with self.assertRaisesRegex(CorpusError, "inventory changed"):
            c.compile_source(copy)

    def test_13_write_rejects_existing_outside_or_unexpected_member(self):
        artifacts = c.compile_source(self.source)
        target = ARTIFACT_ROOT / "write-once"
        c.write_artifacts(artifacts, target)
        with self.assertRaises(FileExistsError):
            c.write_artifacts(artifacts, target)
        with self.assertRaises(CorpusError):
            c.write_artifacts(artifacts, self.source / "must-not-be-created")
        bad = dict(artifacts)
        bad["../../must-not-be-created.md"] = b"invalid"
        with self.assertRaises(CorpusError):
            c.write_artifacts(bad, ARTIFACT_ROOT / "bad-output")
        self.assertFalse((ARTIFACT_ROOT / "bad-output").exists())

    def test_14_cli_compiles_twice_identically_and_preserves_sources(self):
        outputs = [ARTIFACT_ROOT / "cli-one", ARTIFACT_ROOT / "cli-two"]
        for output in outputs:
            result = subprocess.run(
                [sys.executable, "-B", "-m", "scripts.corpus_runtime_input", "--output", str(output)],
                cwd=c.REPO_ROOT, text=True, capture_output=True, timeout=25,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("ready=0", result.stdout)
        for path in outputs[0].rglob("*"):
            if path.is_file():
                self.assertEqual(path.read_bytes(), (outputs[1] / path.relative_to(outputs[0])).read_bytes())
        self.assertEqual(c.load_sources(self.source), self.documents)

    def test_15_single_formal_c12_world_and_no_case_metadata_in_projection(self):
        case = self.by_id["C12-20"]
        self.assertIn("A", case.setup_source_text)
        self.assertEqual(sum(c.case_id == "C12-20" for c in self.cases), 1)
        for case in self.cases:
            if case.initial_input.unresolved_source_text is None:
                payload = c.json_bytes(project_authored_conversation(case.initial_input)).decode()
                self.assertNotIn(case.case_id, payload)
                self.assertNotIn("oracle_source_text", payload)
                self.assertNotIn("required_types", payload)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", required=True, type=Path)
    parser.add_argument("--case", action="append", choices=[
        name for name in dir(CorpusAcceptance) if name.startswith("test_")
    ], help="Run only named acceptance cases after a directed correction")
    args = parser.parse_args()
    ARTIFACT_ROOT = args.artifacts.resolve()
    if not ARTIFACT_ROOT.is_relative_to((c.REPO_ROOT / ".local-test-evidence").resolve()):
        parser.error("artifacts must remain ignored in this worktree")
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=False)
    print(f"Python {sys.version.split()[0]}; stdlib-only source acceptance; model NOT_RUN", flush=True)
    suite = (unittest.TestSuite(CorpusAcceptance(name) for name in args.case)
             if args.case else unittest.defaultTestLoader.loadTestsFromTestCase(CorpusAcceptance))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    (ARTIFACT_ROOT / "acceptance-summary.json").write_bytes(c.json_bytes({
        "tests_run": result.testsRun, "failures": len(result.failures),
        "errors": len(result.errors), "successful": result.wasSuccessful(),
        "selected_cases": args.case,
        "scope": "compiler_source_contract_only", "model_quality": "NOT_RUN",
    }))
    raise SystemExit(0 if result.wasSuccessful() else 1)
