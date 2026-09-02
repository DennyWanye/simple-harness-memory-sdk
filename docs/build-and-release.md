<!--
SPDX-FileCopyrightText: 2026 Denny
SPDX-License-Identifier: BUSL-1.1
-->

# 0.6 candidate build and verification runbook

This is the current operator procedure for `simple-harness-memory-sdk` 0.6.2. The Task 6 boundary is
candidate-only: build and verify artifacts, but do not create or move a tag, push a release commit, upload
assets, or publish the candidate. `.github/workflows/release.yml` remains the read-only 0.5.1 historical
publisher and must not be used for 0.6.

## Current invariants

- Memory version is exactly `0.6.2`; base and `[harness]` metadata both require
  `simple-harness-sdk>=0.7,<0.8`.
- The Harness input is exact source commit `8f1027d2d64ca3a7e7a4d161833507eadac9552b`, built once as
  a 0.7.0 wheel with `SOURCE_DATE_EPOCH=315532800`; its required SHA-256 is
  `b9421ddf2b1d5a4a4a0920a2e878c1d3cf098ff6ef0af8975b9eb5c516037d7b`. Source tests use the same
  checkout through the frozen `uv.lock` source binding.
- Build Memory wheel and sdist once from one reviewed, clean commit. All artifact, clean-consumer and
  platform jobs consume those same bytes.
- `BUILD_INFO.txt`, `SHA256SUMS`, wheel metadata and source commit must agree.
- A dirty-worktree build may be used only as non-final validation evidence. It has no promotion authority.

## 1. Verify the frozen source inputs

```bash
MEMORY_REPO=/Users/denny/projects/simple-harness-memory-sdk
HARNESS_REPO=/Users/denny/projects/simple-harness-sdk-memory-program
HARNESS_COMMIT=8f1027d2d64ca3a7e7a4d161833507eadac9552b
CANDIDATE_COMMIT="$(git -C "$MEMORY_REPO" rev-parse HEAD)"

test -z "$(git -C "$MEMORY_REPO" status --short)"
test "$(git -C "$HARNESS_REPO" rev-parse HEAD)" = "$HARNESS_COMMIT"
uv sync --directory "$MEMORY_REPO" --frozen --group dev
uv run --directory "$MEMORY_REPO" --frozen --group dev python -c \
  'import importlib.metadata as m; assert m.version("simple-harness-sdk") == "0.7.0"'
```

If either exact-source assertion fails, stop. Do not substitute a sibling Harness 0.6.x checkout or let the
resolver fetch a different version.

## 2. Source and quality gates

```bash
cd "$MEMORY_REPO"
uv run --frozen --group dev pytest -q
uv run --frozen --group dev ruff check src tests
uv run --frozen --group dev mypy src tests
uv run --frozen --group dev ruff check scripts
uv run --frozen --group dev mypy --strict \
  scripts/harness_compatibility_consumer.py \
  scripts/verify_harness_compatibility.py \
  scripts/write_candidate_metadata.py
uvx --from "reuse>=5,<6" reuse lint
```

## 3. Build the exact Harness and Memory candidates

Run this only after `CANDIDATE_COMMIT` is reviewed and the Memory worktree is clean:

```bash
RELEASE_DIR="$(mktemp -d /Users/denny/projects/simple-harness-memory-candidate.XXXXXX)"
git -C "$MEMORY_REPO" worktree add --detach "$RELEASE_DIR" "$CANDIDATE_COMMIT"
cd "$RELEASE_DIR"

SOURCE_DATE_EPOCH=315532800 uv build --wheel --project "$HARNESS_REPO" --out-dir harness-dist
test "$(find harness-dist -maxdepth 1 -name 'simple_harness_sdk-0.7.0-*.whl' | wc -l)" = 1
echo "b9421ddf2b1d5a4a4a0920a2e878c1d3cf098ff6ef0af8975b9eb5c516037d7b  harness-dist/simple_harness_sdk-0.7.0-py3-none-any.whl" \
  | shasum -a 256 -c
uv build --out-dir candidate-dist
uvx --from "twine>=6.1,<7" twine check candidate-dist/*

BUILD_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
python scripts/write_candidate_metadata.py \
  --dist candidate-dist \
  --source-commit "$CANDIDATE_COMMIT" \
  --build-utc "$BUILD_UTC"

MEMORY_SDK_ARTIFACT_DIST=candidate-dist \
HARNESS_SDK_ARTIFACT_DIST=harness-dist \
MEMORY_SDK_CI_CANDIDATE=1 \
  uv run --frozen --group dev pytest -q tests/artifact
(cd candidate-dist && shasum -a 256 -c SHA256SUMS)
```

## 4. Clean consumer

```bash
cd "$RELEASE_DIR"
uv venv .candidate-venv --python 3.13
MEMORY_WHEEL="$(find candidate-dist -maxdepth 1 -name '*.whl' -print -quit)"
HARNESS_WHEEL="$(find harness-dist -maxdepth 1 -name '*.whl' -print -quit)"
uv pip install --python .candidate-venv/bin/python "$HARNESS_WHEEL" "$MEMORY_WHEEL"
.candidate-venv/bin/python -I - <<'PY'
import importlib.metadata as metadata
import inspect

from simple_harness_memory import MemoryManager, __version__

assert __version__ == "0.6.2"
assert metadata.version("simple-harness-sdk") == "0.7.0"
for name in ("enable_facts", "fact_extractor", "auto_extract_facts"):
    assert name not in inspect.signature(MemoryManager.build).parameters
assert not hasattr(MemoryManager, "delete_session")
assert not hasattr(MemoryManager, "delete_old_sessions")
assert not hasattr(MemoryManager, "delete_all")
PY
```

The CI candidate job additionally uploads the exact Memory and Harness artifacts once and reuses them for
Python 3.11/3.12/3.13, Windows x64, macOS ARM64 and Linux ARM64 checks. Because the Harness repository is
private, CI needs the `HARNESS_REPOSITORY_TOKEN` secret with read access. It falls back to `github.token`
only when that token already has cross-repository access; otherwise checkout fails closed and no candidate
job is skipped or marked successful.

## 5. Stop boundary and recordkeeping

Task 6 ends after candidate verification. Record source commit, exact Harness commit, commands, test totals,
artifact filenames and SHA-256 values. Do not invoke the release workflow, create a 0.6 tag, push, upload, or
publish. A later explicitly authorized release task must define a new 0.6 publisher contract before any such
action.

After retaining the candidate evidence outside Git, remove the detached worktree:

```bash
git -C "$MEMORY_REPO" worktree remove "$RELEASE_DIR"
```

## 0.6.1 candidate manifest（S5b Task 4a，2026-09-02）

候选构建口径：`uv build --no-sources`（本仓 worktree，源码提交 `eb81e54`，Python 3.12.14 / uv 0.12.8），
两次 clean build 到不同输出目录，字节一致：

| artifact | sha256（build 1 == build 2） |
|---|---|
| `simple_harness_memory_sdk-0.6.1-py3-none-any.whl` | `4b6c7bc665178d85340b80751d2216fd77821b0ae12f7a4c3281ae4fe9d2b5d6` |
| `simple_harness_memory_sdk-0.6.1.tar.gz` | `5ad351ec628f901b1659b93f5cc412dafbde30408dfe079f9351593a84e9c26e` |

未打 tag、未 push、未发布；Host `pyproject`/`vendor` pin 以 wheel sha256 fail-closed（Task 4 接线）。
schema v7.1 前向加列规则见 `CHANGELOG.md` [0.6.1] 与 `backends/schema_v5.py` 注释。

## Historical releases

The published 0.5.1 release and its Harness 0.4/0.5 receipts remain historical audit records in
`docs/integration-status.md` and `docs/harness-compatibility-*.json`. They do not define the 0.6 resolver,
candidate or publication contract.
