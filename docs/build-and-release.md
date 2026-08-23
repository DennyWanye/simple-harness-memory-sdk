<!--
SPDX-FileCopyrightText: 2026 Denny
SPDX-License-Identifier: BUSL-1.1
-->

# Build and release runbook

This is the authoritative operator procedure for building and distributing
`simple-harness-memory-sdk`. Build authority is local. GitHub Releases may host the exact frozen
bytes for AIPhone and other consumers, but must never rebuild them.

## Invariants

- Release Harness SDK first; Memory requires Harness SDK `>=0.4,<0.6` as a base dependency and
  keeps the same range for `[harness]`.
- Build once from the exact candidate commit in a clean detached worktree.
- The version tag, `BUILD_INFO.txt`, wheel metadata, and source commit must agree.
- Publish the wheel, sdist, `SHA256SUMS`, and `BUILD_INFO.txt` together.
- Never overwrite a published asset or move a published tag; issue a new version instead.
- Do not treat a GitHub Actions artifact as permanent distribution storage.

## Prerequisites

- Git and authenticated GitHub CLI (`gh auth status`).
- `uv` and Python 3.11–3.13.
- A clean repository and candidate commit already merged to `main`.
- The compatible Harness wheel available for joint consumer testing.

## 1. Freeze the candidate

The values below prepare the current 0.5.1 candidate. Freeze `CANDIDATE_COMMIT` from the reviewed,
clean release-identity commit before creating the tag.

```bash
MEMORY_REPO=/Users/denny/projects/simple-harness-memory-sdk
HARNESS_REPO=/Users/denny/projects/simple-harness-sdk
RELEASE_TAG=v0.5.1
CANDIDATE_COMMIT="$(git -C "$MEMORY_REPO" rev-parse main)"

git -C "$MEMORY_REPO" status --short
test -z "$(git -C "$MEMORY_REPO" status --short)"
git -C "$MEMORY_REPO" merge-base --is-ancestor "$CANDIDATE_COMMIT" main
```

For a new version, create the annotated tag locally only after review:

```bash
git -C "$MEMORY_REPO" tag -a "$RELEASE_TAG" "$CANDIDATE_COMMIT" \
  -m "simple-harness-memory-sdk ${RELEASE_TAG#v}"
```

Do not move an existing tag.

After creating the local tag, verify it before building:

```bash
test "$(git -C "$MEMORY_REPO" rev-parse "$RELEASE_TAG^{}")" = "$CANDIDATE_COMMIT"
```

## 2. Build once in a clean worktree

```bash
RELEASE_DIR="$(mktemp -d /Users/denny/projects/simple-harness-memory-release.XXXXXX)"
git -C "$MEMORY_REPO" worktree add --detach "$RELEASE_DIR" "$CANDIDATE_COMMIT"
cd "$RELEASE_DIR"

uv sync --frozen --group dev
uv run --frozen --group dev pytest -q
uv run --frozen --group dev ruff check src tests
uv run --frozen --group dev mypy src tests
uvx --from "reuse>=5,<6" reuse lint

uv build --out-dir candidate-dist
uvx --from "twine>=6.1,<7" twine check candidate-dist/*
BUILD_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
uv run python scripts/write_candidate_metadata.py \
  --dist candidate-dist \
  --source-commit "$CANDIDATE_COMMIT" \
  --build-utc "$BUILD_UTC"
MEMORY_SDK_ARTIFACT_DIST=candidate-dist \
MEMORY_SDK_CI_CANDIDATE=1 \
  uv run --frozen --group dev pytest -q tests/artifact
(cd candidate-dist && shasum -a 256 -c SHA256SUMS)

uv venv .candidate-venv --python 3.13
uv pip install --python .candidate-venv/bin/python candidate-dist/*.whl
.candidate-venv/bin/python -I -c \
  'import simple_harness_memory; print(simple_harness_memory.__version__)'
```

For the official Agent Memory combinations, run `scripts/verify_harness_compatibility.py` separately
against the released Harness 0.4.0 wheel and the exact Harness 0.5.0 candidate (then release) wheel.
Pass each wheel path, expected version, and SHA-256 explicitly. The script creates a clean venv,
installs only those wheel bytes, and runs the consumer with `python -I`; sibling editable source is
not release proof. The Harness 0.5.0 candidate cell is complete, but the exact final release/download-back
cell remains pending. Do not publish Memory 0.5.1 until it passes; never record a missing cell as PASS.

The current successful Harness 0.5 candidate run is recorded in
`docs/harness-compatibility-candidate-0.5.1-ac2e2add.json`. It supersedes the historical
`docs/harness-compatibility-candidate-0.5.1.json`, whose candidate was withdrawn and has no promotion
authority. Neither receipt replaces the final Harness release/download-back cell; both contain no
local paths or Memory content.

`candidate-dist/` is now the frozen local publication set. Preserve these exact bytes and do not
rebuild the same version at upload time.

## 3. Publish the tag and frozen assets

```bash
git -C "$MEMORY_REPO" push origin main "refs/tags/$RELEASE_TAG"

gh release create "$RELEASE_TAG" \
  "$RELEASE_DIR"/candidate-dist/*.whl \
  "$RELEASE_DIR"/candidate-dist/*.tar.gz \
  "$RELEASE_DIR"/candidate-dist/SHA256SUMS \
  "$RELEASE_DIR"/candidate-dist/BUILD_INFO.txt \
  --repo DennyWanye/simple-harness-memory-sdk \
  --verify-tag \
  --title "simple-harness-memory-sdk $RELEASE_TAG" \
  --notes "Locally built and verified frozen Memory SDK artifacts."
```

GitHub is only the download channel. Do not run the repository's build job during publication,
and do not use `gh release upload --clobber`.

## 4. Download-back verification

```bash
VERIFY_DIR="$(mktemp -d /tmp/simple-harness-memory-download.XXXXXX)"
gh release download "$RELEASE_TAG" \
  --repo DennyWanye/simple-harness-memory-sdk \
  --dir "$VERIFY_DIR"
(cd "$VERIFY_DIR" && shasum -a 256 -c SHA256SUMS)
cmp "$RELEASE_DIR/candidate-dist/BUILD_INFO.txt" "$VERIFY_DIR/BUILD_INFO.txt"
```

## 5. Consumer URL and AIPhone handoff

The stable wheel URL is:

```text
https://github.com/DennyWanye/simple-harness-memory-sdk/releases/download/<tag>/<wheel-filename>
```

AIPhone must pin both SDKs by exact Release URL and SHA-256. It must then update its expected
distribution versions, provenance/candidate manifests, hashed requirements, offline wheelhouse,
`uv.lock`, composition code, and candidate tests. A successful URL download alone does not prove
AIPhone integration.

Never use `latest`, a branch archive, or an unversioned URL for a production candidate.

## 6. Cleanup and recordkeeping

After retaining the frozen local publication set and verifying downloaded bytes:

```bash
git -C "$MEMORY_REPO" worktree remove "$RELEASE_DIR"
```

Update `README.md`, `docs/integration-status.md`, and `ARCHITECTURE/ARCHITECTURE.md` with the tag,
source commit, wheel SHA-256, test result, and Release URL. Do not commit generated distributions,
credentials, logs, databases, or raw test evidence.
