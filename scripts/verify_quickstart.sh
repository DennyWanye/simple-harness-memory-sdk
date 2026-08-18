#!/usr/bin/env bash
# verify_quickstart.sh — memory SDK release gate: run the README quickstart verbatim.
#
# Steps:
#   1. Create a clean venv with a Python >= 3.11 interpreter.
#   2. `pip install -e .` (base install, no extras).
#   3. Extract the single plain ```python block from README.md VERBATIM and
#      execute it against the installed package. The script carries no
#      "paraphrased" copy of the example — if the README lies, this gate goes red.
#   4. Emit structured PASS/FAIL per step; exit 0 only if every step passed.
#
# Usage:
#   ./scripts/verify_quickstart.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
README="$REPO_ROOT/README.md"

FAILED=0
WORK="$(mktemp -d /tmp/simple-harness-memory-verify.XXXXXX)"

say()  { printf '%s\n' "$*"; }
step() { say ""; say "== STEP: $1"; }
pass() { say "PASS: $1"; }
fail() { say "FAIL: $1"; FAILED=1; }

cleanup() {
  if [ "$FAILED" -eq 0 ]; then
    rm -rf "$WORK"
  else
    say "Work directory preserved for debugging: $WORK"
  fi
}
trap cleanup EXIT

# --- locate a Python >= 3.11 ------------------------------------------------
find_python() {
  local p
  for p in python3 python3.13 python3.12 python3.11; do
    if command -v "$p" >/dev/null 2>&1; then
      if "$p" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
        printf '%s\n' "$p"
        return 0
      fi
    fi
  done
  return 1
}

step "locate Python >= 3.11"
PYTHON="$(find_python)"
if [ -n "$PYTHON" ]; then
  pass "python interpreter: $PYTHON ($("$PYTHON" -c 'import sys; print(sys.version.split()[0])'))"
else
  fail "no Python >= 3.11 found on PATH"
  say ""; say "RESULT: FAIL"; exit 1
fi

# --- Step 1: clean venv ------------------------------------------------------
step "create clean venv"
if "$PYTHON" -m venv "$WORK/venv"; then
  pass "venv"
else
  fail "venv"
  say ""; say "RESULT: FAIL"; exit 1
fi
VENV_PY="$WORK/venv/bin/python"

# --- Step 2: base install ----------------------------------------------------
step "pip install -e . (base install, no extras)"
if (cd "$REPO_ROOT" && "$VENV_PY" -m pip install -q -e .); then
  pass "install"
else
  fail "install"
fi

# --- Step 3: extract the quickstart python block -----------------------------
step "extract quickstart python block from README.md"

PY_BLOCK_COUNT="$(grep -c '^```python$' "$README" || true)"
if [ "$PY_BLOCK_COUNT" != "1" ]; then
  fail "README must contain exactly one plain \`\`\`python block, found $PY_BLOCK_COUNT"
fi

awk '/^```python$/{flag=1;next} /^```/{if(flag)flag=0} flag' "$README" > "$WORK/quickstart.py"

if [ ! -s "$WORK/quickstart.py" ]; then
  fail "extracted python block is empty"
fi

# --- Step 4: execute verbatim ------------------------------------------------
if [ "$FAILED" -eq 0 ]; then
  step "execute quickstart python block verbatim"
  if (cd "$WORK" && "$VENV_PY" "$WORK/quickstart.py"); then
    pass "quickstart python block runs (append + recall + facts)"
  else
    fail "quickstart python block execution"
  fi
fi

# --- Result ------------------------------------------------------------------
say ""
if [ "$FAILED" -eq 0 ]; then
  say "RESULT: PASS"
  exit 0
else
  say "RESULT: FAIL"
  exit 1
fi
