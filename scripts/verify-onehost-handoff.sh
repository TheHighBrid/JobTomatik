#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"

export PYTHONPATH="${PYTHONPATH:-$BACKEND}"
export ALLOW_REAL_APPLICATION_SUBMIT=false
export AUTOPILOT_ENABLED=false
export GREENHOUSE_SUPERVISED_PILOT_ENABLED=false
export LEVER_SUPERVISED_PILOT_ENABLED=false
export ENABLE_RESUMABLE_HANDOFFS=false

: "${JOBTOMATIK_GATE3_EVIDENCE_DIR:=$ROOT/verification-artifacts/onehost-gate3-handoff}"
: "${HANDOFF_STORAGE_DIR:=$JOBTOMATIK_GATE3_EVIDENCE_DIR/handoff-sessions}"
export JOBTOMATIK_GATE3_EVIDENCE_DIR HANDOFF_STORAGE_DIR

mkdir -p "$JOBTOMATIK_GATE3_EVIDENCE_DIR" "$HANDOFF_STORAGE_DIR"

if git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  REVISION="$(git -C "$ROOT" rev-parse HEAD)"
else
  REVISION="unattested-local"
fi
export JOBTOMATIK_RUNTIME_REVISION="${JOBTOMATIK_RUNTIME_REVISION:-$REVISION}"

printf '%s\n' "$JOBTOMATIK_RUNTIME_REVISION" > "$JOBTOMATIK_GATE3_EVIDENCE_DIR/revision.txt"

cd "$BACKEND"
python -m pytest -q \
  tests/test_onehost_gate3_handoff.py \
  tests/test_handoff_submission_confirmation.py \
  tests/test_operator_assisted_submission.py \
  | tee "$JOBTOMATIK_GATE3_EVIDENCE_DIR/pytest.log"

python - <<'PY'
import json
import os
from pathlib import Path

root = Path(os.environ["JOBTOMATIK_GATE3_EVIDENCE_DIR"])
summary_path = root / "summary.json"
if not summary_path.exists():
    raise SystemExit("Gate 3 integration test did not retain summary.json")
summary = json.loads(summary_path.read_text(encoding="utf-8"))
if summary.get("verdict") != "PASS" or summary.get("violations"):
    raise SystemExit(f"Gate 3 retained summary is not PASS: {summary}")
summary["repository_revision"] = os.environ["JOBTOMATIK_RUNTIME_REVISION"]
summary["focused_test_log"] = "pytest.log"
summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
