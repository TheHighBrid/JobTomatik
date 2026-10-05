"""Synthetic-only tests for the separately authorized Gate 2 public proof-v2 contract."""
import json
import os
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest
import yaml

from app.services import recovery_gate2 as gate
from scripts import run_recovery_gate2_v2 as v2


# Deterministic synthetic execution identity. Workflow-context tests must never
# depend on the live checkout: production provenance() intentionally rejects a
# dirty tree, and the full suite may legitimately leave temporary files behind.
SYNTHETIC_EXECUTION_SHA = "0123456789abcdef0123456789abcdef01234567"
SYNTHETIC_SOURCE_SHA256 = "5" * 64
SYNTHETIC_WORKFLOW_REF = f"TheHighBrid/JobTomatik/{v2.WORKFLOW_PATH}@refs/heads/main"
RECEIPT_HELPER_PATH = ".github/scripts/gate2_proof_v2_receipts.cjs"
PREFLIGHT_WORKFLOW_PATH = ".github/workflows/recovery-gate2-proof-v2-preflight.yml"
PROOF_CONTROLS_WORKFLOW_PATH = ".github/workflows/recovery-gate2-proof-v2.yml"
WORKSPACE_EXPRESSION = "${{ github.workspace }}"


def _stub_provenance(monkeypatch, git_sha: str = SYNTHETIC_EXECUTION_SHA, error: Exception | None = None):
    """Replace the v2 module's provenance binding with a deterministic attestation."""
    calls = []

    def synthetic_provenance() -> dict:
        calls.append(True)
        if error is not None:
            raise error
        return {
            "git_sha": git_sha,
            "inputs": {"backend/app/services/recovery_gate2.py": "6" * 64},
            "python": "synthetic",
            "playwright": "synthetic",
            "source_sha256": SYNTHETIC_SOURCE_SHA256,
        }

    monkeypatch.setattr(v2, "provenance", synthetic_provenance)
    return calls


def _workflow_env(monkeypatch, sha: str = SYNTHETIC_EXECUTION_SHA) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_SHA", sha)
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_RUN_ID", "12345")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_WORKFLOW_REF", SYNTHETIC_WORKFLOW_REF)


def _receipts(sha: str, run_id: int) -> dict:
    return {
        "schema": v2.PROOF_SCHEMA,
        "proof_id": v2.AUTHORIZED_PROOF_ID,
        "target_url": v2.AUTHORIZED_TARGET_URL,
        "sha": sha,
        "run_id": run_id,
        "receipts": [
            {"name": name, "id": index + 1, "head_sha": sha,
             "status": "completed", "conclusion": "success", "url": "https://example.test/check"}
            for index, name in enumerate(v2.REQUIRED_CHECKS)
        ],
    }


def test_authorized_inputs_are_exact():
    v2.validate_authorized_inputs(v2.AUTHORIZED_PROOF_ID, v2.AUTHORIZED_TARGET_URL)
    with pytest.raises(RuntimeError, match="proof identity"):
        v2.validate_authorized_inputs("gate2-public-proof-v2-other", v2.AUTHORIZED_TARGET_URL)
    with pytest.raises(RuntimeError, match="target"):
        v2.validate_authorized_inputs(v2.AUTHORIZED_PROOF_ID,
                                      "https://job-boards.greenhouse.io/gitlab/jobs/8860302003")


def test_proof_v2_reservation_is_one_use_and_separate_from_v1_attempt(tmp_path):
    ledger = tmp_path / "ledger.sqlite"
    target = gate.identity(v2.AUTHORIZED_TARGET_URL)
    legacy = gate.claim_attempt(ledger, target)
    proof = v2.reserve_proof(ledger, v2.AUTHORIZED_PROOF_ID, v2.AUTHORIZED_TARGET_URL)
    assert legacy["duplicate_rejected"] is True
    assert proof["target_key"] == v2.proof_target_key(v2.AUTHORIZED_PROOF_ID, v2.AUTHORIZED_TARGET_URL)
    with pytest.raises(sqlite3.IntegrityError):
        v2.reserve_proof(ledger, v2.AUTHORIZED_PROOF_ID, v2.AUTHORIZED_TARGET_URL)
    with sqlite3.connect(ledger) as database:
        assert database.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 1
        assert database.execute("SELECT COUNT(*) FROM proof_runs").fetchone()[0] == 1


def test_workflow_context_requires_first_attempt_main_and_exact_head(monkeypatch):
    head = SYNTHETIC_EXECUTION_SHA
    calls = _stub_provenance(monkeypatch, head)
    _workflow_env(monkeypatch, head)
    context = v2.workflow_context(head)
    assert context == {
        "run_id": 12345,
        "run_attempt": 1,
        "workflow_ref": SYNTHETIC_WORKFLOW_REF,
        "execution_sha": head,
        "source_sha256": SYNTHETIC_SOURCE_SHA256,
    }
    assert len(calls) == 1
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    with pytest.raises(RuntimeError, match="reruns"):
        v2.workflow_context(head)
    assert len(calls) == 1, "rerun must be rejected before source attestation"


@pytest.mark.parametrize(("variable", "value", "message"), [
    ("GITHUB_ACTIONS", None, "must run in GitHub Actions"),
    ("GITHUB_ACTIONS", "false", "must run in GitHub Actions"),
    ("GITHUB_SHA", "f" * 40, "Workflow SHA differs"),
    ("GITHUB_SHA", None, "Workflow SHA differs"),
    ("GITHUB_REF", "refs/heads/sol56/gate2-proof-v2-consolidation", "must dispatch from main"),
    ("GITHUB_REF", "refs/pull/645/merge", "must dispatch from main"),
    ("GITHUB_RUN_ID", None, "run ID missing"),
    ("GITHUB_RUN_ID", "0", "run ID missing"),
    ("GITHUB_RUN_ID", "abc", "run ID missing"),
    ("GITHUB_RUN_ATTEMPT", None, "reruns are prohibited"),
    ("GITHUB_RUN_ATTEMPT", "3", "reruns are prohibited"),
    ("GITHUB_WORKFLOW_REF", None, "Unexpected Gate 2 proof-v2 workflow ref"),
    ("GITHUB_WORKFLOW_REF",
     f"TheHighBrid/JobTomatik/{v2.WORKFLOW_PATH}@refs/heads/sol56/gate2-proof-v2-consolidation",
     "Unexpected Gate 2 proof-v2 workflow ref"),
    ("GITHUB_WORKFLOW_REF",
     "TheHighBrid/JobTomatik/.github/workflows/recovery-gate2-public.yml@refs/heads/main",
     "Unexpected Gate 2 proof-v2 workflow ref"),
])
def test_workflow_context_rejects_each_invalid_environment_before_attestation(
    monkeypatch, variable, value, message,
):
    calls = _stub_provenance(monkeypatch)
    _workflow_env(monkeypatch)
    if value is None:
        monkeypatch.delenv(variable)
    else:
        monkeypatch.setenv(variable, value)
    with pytest.raises(RuntimeError, match=message):
        v2.workflow_context(SYNTHETIC_EXECUTION_SHA)
    assert calls == []


@pytest.mark.parametrize("execution_sha", ["", "abc", "0123456789ABCDEF0123456789ABCDEF01234567", "0" * 39, "0" * 41])
def test_workflow_context_rejects_malformed_execution_sha(monkeypatch, execution_sha):
    calls = _stub_provenance(monkeypatch)
    _workflow_env(monkeypatch, execution_sha)
    with pytest.raises(RuntimeError, match="Invalid execution SHA"):
        v2.workflow_context(execution_sha)
    assert calls == []


def test_workflow_context_rejects_checkout_that_differs_from_execution_sha(monkeypatch):
    calls = _stub_provenance(monkeypatch, git_sha="f" * 40)
    _workflow_env(monkeypatch)
    with pytest.raises(RuntimeError, match="Checked-out source differs"):
        v2.workflow_context(SYNTHETIC_EXECUTION_SHA)
    assert len(calls) == 1


def test_workflow_context_propagates_source_attestation_failure(monkeypatch):
    _stub_provenance(monkeypatch, error=RuntimeError("Gate 2 requires a clean committed checkout"))
    _workflow_env(monkeypatch)
    with pytest.raises(RuntimeError, match="clean committed checkout"):
        v2.workflow_context(SYNTHETIC_EXECUTION_SHA)


def test_production_provenance_still_rejects_dirty_checkout(monkeypatch, tmp_path):
    """Exercise the real attestation against an isolated repository, never the live checkout."""
    git = shutil.which("git")
    if not git:
        pytest.skip("git executable unavailable")
    repo = tmp_path / "repo"
    (repo / "backend/app").mkdir(parents=True)
    (repo / "backend/scripts").mkdir(parents=True)
    (repo / "backend/app/module.py").write_text("VALUE = 1\n")

    def run(*args):
        return subprocess.check_output([git, "-C", str(repo), *args])

    run("init", "-q")
    run("add", "-A")
    run("-c", "user.name=synthetic", "-c", "user.email=synthetic@example.invalid",
        "-c", "commit.gpgsign=false", "commit", "-q", "-m", "synthetic")
    monkeypatch.setattr(gate, "ROOT", repo)
    clean = gate.provenance()
    assert clean["git_sha"] == run("rev-parse", "HEAD").decode().strip()
    assert set(clean["inputs"]) == {"backend/app/module.py"}
    (repo / "untracked.txt").write_text("dirty\n")
    with pytest.raises(RuntimeError, match="clean committed checkout"):
        gate.provenance()
    (repo / "untracked.txt").unlink()
    (repo / "backend/app/module.py").write_text("VALUE = 2\n")
    with pytest.raises(RuntimeError, match="clean committed checkout"):
        gate.provenance()


def test_ci_receipts_require_complete_exact_head_set(tmp_path):
    sha = "a" * 40
    path = tmp_path / "receipts.json"
    path.write_text(json.dumps(_receipts(sha, 77)))
    data = v2.load_ci_receipts(
        path, sha, v2.AUTHORIZED_PROOF_ID, v2.AUTHORIZED_TARGET_URL, 77
    )
    assert len(data["receipts"]) == len(v2.REQUIRED_CHECKS)
    broken = _receipts(sha, 77)
    broken["receipts"] = [item for item in broken["receipts"] if item["name"] != "Analyze python"]
    path.write_text(json.dumps(broken))
    with pytest.raises(RuntimeError, match="incomplete"):
        v2.load_ci_receipts(path, sha, v2.AUTHORIZED_PROOF_ID, v2.AUTHORIZED_TARGET_URL, 77)


def test_proof_metadata_requires_retained_ci_and_proof_reservation(tmp_path):
    sha = "b" * 40
    run_id = 88
    receipts = _receipts(sha, run_id)
    receipts_path = tmp_path / "ci-prerequisites.json"
    receipts_path.write_text(json.dumps(receipts))
    ledger = tmp_path / "ledger.sqlite"
    v2.reserve_proof(ledger, v2.AUTHORIZED_PROOF_ID, v2.AUTHORIZED_TARGET_URL)
    record = {
        "source": {"git_sha": sha},
        "proof_v2": {
            "schema": v2.PROOF_SCHEMA,
            "proof_id": v2.AUTHORIZED_PROOF_ID,
            "target_url": v2.AUTHORIZED_TARGET_URL,
            "target_key": v2.proof_target_key(v2.AUTHORIZED_PROOF_ID, v2.AUTHORIZED_TARGET_URL),
            "execution_sha": sha,
            "github_run_id": run_id,
            "github_run_attempt": 1,
            "github_workflow_ref":
                f"TheHighBrid/JobTomatik/{v2.WORKFLOW_PATH}@refs/heads/main",
            "ci_receipts_sha256": gate.digest(receipts_path.read_bytes()),
        },
    }
    assert v2.proof_metadata_errors(record, tmp_path) == []
    record["proof_v2"]["github_run_attempt"] = 2
    assert "proof-v2 rerun evidence is invalid" in v2.proof_metadata_errors(record, tmp_path)


def test_current_source_attestation_fails_closed(monkeypatch):
    recorded = {"git_sha": "a" * 40, "source_sha256": "1" * 64, "inputs": {"x.py": "2" * 64}}
    monkeypatch.setattr(v2, "provenance", lambda: dict(recorded))
    assert v2._current_source_errors({"source": recorded}) == []
    monkeypatch.setattr(v2, "provenance", lambda: {**recorded, "git_sha": "b" * 40})
    assert v2._current_source_errors({"source": recorded}) == [
        "Executed source differs from the reviewed Git checkout"
    ]


def test_v2_workflow_is_separate_from_consumed_v1_and_requires_codeql():
    root = Path(gate.ROOT)
    v1 = (root / ".github/workflows/recovery-gate2-public.yml").read_text()
    v2_text = (root / v2.WORKFLOW_PATH).read_text()
    helper = (root / RECEIPT_HELPER_PATH).read_text()
    assert "sol61/gate2-public-proof" in v1
    assert "on:\n  create:" in v1
    assert "workflow_dispatch:" in v2_text
    assert "on:\n  create:" not in v2_text
    assert v2.AUTHORIZED_PROOF_ID in v2_text
    assert v2.AUTHORIZED_TARGET_URL in v2_text
    assert "GITHUB_RUN_ATTEMPT" in v2_text
    assert RECEIPT_HELPER_PATH in v2_text
    assert "requireProofWorkflowUnused" in v2_text
    assert "PROOF_WORKFLOW = 'recovery-gate2-public-v2.yml'" in helper
    assert "'proof-v2-controls'" in helper
    assert "'Analyze python'" in helper
    assert "'Analyze javascript-typescript'" in helper
    assert "--proof-id" in v2_text
    assert "--execution-sha" in v2_text


def test_dispatch_inputs_are_not_interpolated_inside_shell_commands():
    workflow = (Path(gate.ROOT) / v2.WORKFLOW_PATH).read_text()
    assert 'DISPATCH_EXECUTION_SHA: ${{ inputs.execution_sha }}' in workflow
    assert 'DISPATCH_PROOF_ID: ${{ inputs.proof_id }}' in workflow
    assert 'DISPATCH_TARGET_URL: ${{ inputs.target_url }}' in workflow
    assert '--url "${{ inputs.target_url }}"' not in workflow
    assert '--proof-id "${{ inputs.proof_id }}"' not in workflow
    assert '--execution-sha "${{ inputs.execution_sha }}"' not in workflow
    assert '--url "$DISPATCH_TARGET_URL"' in workflow
    assert '--proof-id "$DISPATCH_PROOF_ID"' in workflow
    assert '--execution-sha "$DISPATCH_EXECUTION_SHA"' in workflow


def test_every_required_receipt_has_a_main_push_producer():
    root = Path(gate.ROOT)
    producers = {
        ".github/workflows/recovery-gate2.yml": ("synthetic-controls",),
        ".github/workflows/recovery-gate2-proof-v2.yml": ("proof-v2-controls",),
        ".github/workflows/current-head-final-acceptance.yml": ("exact-head-acceptance",),
        ".github/workflows/backend-tests.yml": ("pytest",),
        ".github/workflows/onehost-fixture-gate.yml": ("owned-browser-compose-proof",),
        ".github/workflows/onehost-api-celery-gate.yml": ("phase0-fastapi-celery-proof",),
        ".github/workflows/reproducible-verification.yml": (
            "backend-browser-migration", "fast-gate", "dependency-audit",
        ),
        ".github/workflows/post-merge-stabilization.yml": ("integrated-backend",),
    }
    produced = set()
    for path, checks in producers.items():
        workflow = (root / path).read_text()
        assert "push:" in workflow and "main" in workflow, path
        for check in checks:
            assert f"{check}:" in workflow, f"{check} missing from {path}"
            produced.add(check)
    codeql = (root / ".github/workflows/codeql.yml").read_text()
    assert "push:" in codeql and "main" in codeql
    assert "python" in codeql and "javascript-typescript" in codeql
    produced.update({"Analyze python", "Analyze javascript-typescript"})
    assert produced == set(v2.REQUIRED_CHECKS)


def test_v1_runner_and_public_workflow_remain_unchanged_in_role():
    root = Path(gate.ROOT)
    runner = (root / "backend/scripts/run_recovery_gate2.py").read_text()
    workflow = (root / ".github/workflows/recovery-gate2-public.yml").read_text()
    assert "--review" in runner and "run_gate" in runner
    assert "Recovery Gate 2 single public proof" in workflow
    assert "sol61/gate2-public-proof" in workflow


# ---------------------------------------------------------------------------
# W1: fresh-runner topology. A GitHub-hosted runner starts with an empty
# workspace; a `run` step cannot start in a repo-relative directory (for example
# a job default of `backend`) until actions/checkout has created it. For the
# one-use proof-v2 workflow such a failure would also consume its history.
# ---------------------------------------------------------------------------


def _workflow(relative: str) -> dict:
    return yaml.safe_load((Path(gate.ROOT) / relative).read_text())


def _triggers(workflow: dict) -> dict:
    # PyYAML (YAML 1.1) parses the bare key `on` as boolean True.
    triggers = workflow.get("on", workflow.get(True))
    if isinstance(triggers, str):
        return {triggers: None}
    if isinstance(triggers, list):
        return {name: None for name in triggers}
    return triggers or {}


def _default_working_directory(workflow: dict, job: dict):
    for scope in (job, workflow):
        directory = ((scope.get("defaults") or {}).get("run") or {}).get("working-directory")
        if directory is not None:
            return directory
    return None


def _is_checkout(step: dict) -> bool:
    return str(step.get("uses", "")).startswith("actions/checkout@")


def _precheckout_violations(workflow: dict) -> list[str]:
    violations = []
    for job_id, job in (workflow.get("jobs") or {}).items():
        default = _default_working_directory(workflow, job)
        for index, step in enumerate(job.get("steps") or []):
            if _is_checkout(step):
                break
            if str(step.get("uses", "")).startswith("./"):
                violations.append(f"{job_id}[{index}] uses a local action before checkout")
            if "run" not in step or step.get("continue-on-error") is True:
                continue
            directory = step.get("working-directory", default)
            if directory is not None and directory != WORKSPACE_EXPRESSION:
                violations.append(f"{job_id}[{index}] {step.get('name')!r} starts in {directory!r} before checkout")
    return violations


def test_no_workflow_run_step_starts_in_a_repo_directory_before_checkout():
    """Fails on 5b71fc2: proof-v2 step 0 inherited `defaults.run.working-directory: backend`."""
    workflows = sorted((Path(gate.ROOT) / ".github/workflows").glob("*.y*ml"))
    assert workflows
    violations = {}
    for path in workflows:
        found = _precheckout_violations(yaml.safe_load(path.read_text()))
        if found:
            violations[path.name] = found
    assert violations == {}


def test_precheckout_scan_detects_the_original_inherited_backend_default():
    broken = {
        "jobs": {"public-proof-v2": {
            "defaults": {"run": {"working-directory": "backend"}},
            "steps": [
                {"name": "Reject reruns and non-main dispatches", "shell": "bash",
                 "run": 'test "$GITHUB_RUN_ATTEMPT" = "1"'},
                {"uses": "actions/checkout@v7"},
            ],
        }},
    }
    assert _precheckout_violations(broken) == [
        "public-proof-v2[0] 'Reject reruns and non-main dispatches' starts in 'backend' before checkout"
    ]
    broken["jobs"]["public-proof-v2"]["steps"][0]["working-directory"] = WORKSPACE_EXPRESSION
    assert _precheckout_violations(broken) == []


def _proof_steps() -> list[dict]:
    workflow = _workflow(v2.WORKFLOW_PATH)
    assert list(workflow["jobs"]) == ["public-proof-v2"]
    return workflow["jobs"]["public-proof-v2"]["steps"]


def _step_index(steps: list[dict], predicate) -> int:
    matches = [index for index, step in enumerate(steps) if predicate(step)]
    assert len(matches) == 1, matches
    return matches[0]


def test_proof_v2_guard_runs_from_workspace_and_binds_inputs_before_checkout():
    workflow = _workflow(v2.WORKFLOW_PATH)
    job = workflow["jobs"]["public-proof-v2"]
    steps = job["steps"]
    checkout = _step_index(steps, _is_checkout)
    guard = steps[0]
    assert checkout == 1, "exactly one guard step must precede checkout"
    assert guard["shell"] == "bash"
    assert guard["working-directory"] == WORKSPACE_EXPRESSION
    assert "continue-on-error" not in guard and "if" not in guard
    script = guard["run"]
    assert script.lstrip().startswith("set -euo pipefail")
    for fragment in (
        '"$GITHUB_RUN_ATTEMPT" == "1"',
        '"$GITHUB_REF" == "refs/heads/main"',
        '"$DISPATCH_EXECUTION_SHA" =~ ^[0-9a-f]{40}$',
        '"$DISPATCH_EXECUTION_SHA" == "$GITHUB_SHA"',
        '"$DISPATCH_PROOF_ID" == "$AUTHORIZED_PROOF_ID"',
        '"$DISPATCH_TARGET_URL" == "$AUTHORIZED_TARGET_URL"',
    ):
        assert fragment in script
    assert "${{" not in script, "dispatch inputs must reach the guard only through env"
    assert steps[checkout]["with"]["ref"] == "${{ inputs.execution_sha }}"
    assert job["defaults"]["run"]["working-directory"] == "backend"
    assert job["env"]["AUTHORIZED_PROOF_ID"] == v2.AUTHORIZED_PROOF_ID
    assert job["env"]["AUTHORIZED_TARGET_URL"] == v2.AUTHORIZED_TARGET_URL
    assert not any(step.get("continue-on-error") for step in steps)


def _run_guard(tmp_path: Path, **overrides) -> subprocess.CompletedProcess:
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash unavailable")
    sha = "c" * 40
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": sha,
        "DISPATCH_EXECUTION_SHA": sha,
        "DISPATCH_PROOF_ID": v2.AUTHORIZED_PROOF_ID,
        "DISPATCH_TARGET_URL": v2.AUTHORIZED_TARGET_URL,
        "AUTHORIZED_PROOF_ID": v2.AUTHORIZED_PROOF_ID,
        "AUTHORIZED_TARGET_URL": v2.AUTHORIZED_TARGET_URL,
    }
    env.update(overrides)
    workspace = tmp_path / "fresh-workspace"
    workspace.mkdir(exist_ok=True)
    assert not any(workspace.iterdir()), "simulated fresh runner workspace must be empty"
    return subprocess.run([bash, "-c", _proof_steps()[0]["run"]], cwd=workspace, env=env,
                          capture_output=True, text=True, timeout=30)


def test_proof_v2_guard_passes_in_an_empty_fresh_workspace(tmp_path):
    result = _run_guard(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(("overrides", "message"), [
    ({"GITHUB_RUN_ATTEMPT": "2"}, "reruns are prohibited"),
    ({"GITHUB_RUN_ATTEMPT": ""}, "reruns are prohibited"),
    ({"GITHUB_REF": "refs/heads/sol56/gate2-proof-v2-consolidation"}, "must dispatch from main"),
    ({"GITHUB_REF": "refs/pull/645/merge"}, "must dispatch from main"),
    ({"DISPATCH_EXECUTION_SHA": "C" * 40, "GITHUB_SHA": "C" * 40}, "Invalid execution SHA"),
    ({"DISPATCH_EXECUTION_SHA": "c" * 39}, "Invalid execution SHA"),
    ({"DISPATCH_EXECUTION_SHA": "c" * 40 + "\nd"}, "Invalid execution SHA"),
    ({"GITHUB_SHA": "d" * 40}, "differs from dispatched main SHA"),
    ({"DISPATCH_PROOF_ID": "gate2-public-proof-v2-other"}, "Unapproved Gate 2 proof identity"),
    ({"DISPATCH_TARGET_URL": "https://job-boards.greenhouse.io/gitlab/jobs/8860302003"}, "Unapproved Gate 2 target"),
])
def test_proof_v2_guard_rejects_before_checkout(tmp_path, overrides, message):
    result = _run_guard(tmp_path, **overrides)
    assert result.returncode != 0
    assert message in result.stdout


def test_proof_v2_receipts_are_checked_by_shared_helper_after_exact_checkout():
    steps = _proof_steps()
    checkout = _step_index(steps, _is_checkout)
    script_index = _step_index(steps, lambda step: str(step.get("uses", "")).startswith("actions/github-script@"))
    runner = _step_index(steps, lambda step: "--ci-receipts" in str(step.get("run", "")))
    assert checkout < script_index < runner
    script = steps[script_index]["with"]["script"]
    assert "if (sha !== context.sha)" in script
    assert "'rev-parse', 'HEAD'" in script and "if (head !== sha)" in script
    assert f"/{RECEIPT_HELPER_PATH}`)" in script
    assert script.index("gate2.requireReceipts(") < script.index("gate2.requireProofWorkflowUnused(")
    assert "runId: context.runId" in script
    assert "gate2-ci-prerequisites-v2.json" in script
    # Single source of truth: no inline receipt list or bespoke selection logic.
    assert "listForRef" not in script and "listWorkflowRuns" not in script
    for name in v2.REQUIRED_CHECKS:
        assert f'"{name}"' not in script


# ---------------------------------------------------------------------------
# W2: exact-head receipt liveness. Every REQUIRED_CHECK must be producible on
# any current main SHA regardless of which paths the merge touched.
# ---------------------------------------------------------------------------


def _helper_producers() -> dict:
    text = (Path(gate.ROOT) / RECEIPT_HELPER_PATH).read_text()
    block = re.search(r"REQUIRED_PRODUCERS = Object\.freeze\(\{(.*?)\}\);", text, re.S)
    assert block, "REQUIRED_PRODUCERS block missing"
    pairs = re.findall(r"^\s*'([^']+)':\s*'([^']+)',\s*$", block.group(1), re.M)
    return dict(pairs)


def _job_check_names(job_id: str, job: dict) -> list[str]:
    name = str(job.get("name", job_id))
    match = re.search(r"\$\{\{\s*matrix\.([A-Za-z0-9_-]+)\s*\}\}", name)
    if not match:
        return [name]
    values = ((job.get("strategy") or {}).get("matrix") or {}).get(match.group(1)) or []
    return [name.replace(match.group(0), str(value)) for value in values]


def test_required_check_lists_are_identical_everywhere():
    producers = _helper_producers()
    assert tuple(producers) == v2.REQUIRED_CHECKS
    contract = (Path(gate.ROOT) / "docs/operations/GATE2_PROOF_V2_CONTRACT.md").read_text()
    section = contract.split("## Exact-head prerequisites", 1)[1].split("\n## ", 1)[0]
    assert tuple(re.findall(r"^- `([^`]+)`", section, re.M)) == v2.REQUIRED_CHECKS


def test_every_required_check_has_one_dispatchable_unconditional_main_producer():
    """Fails on 5b71fc2: synthetic-controls, proof-v2-controls and pytest had no workflow_dispatch."""
    root = Path(gate.ROOT)
    producers = _helper_producers()
    produced = {}
    for path in sorted((root / ".github/workflows").glob("*.y*ml")):
        workflow = yaml.safe_load(path.read_text())
        for job_id, job in (workflow.get("jobs") or {}).items():
            for name in _job_check_names(job_id, job):
                if name in producers:
                    produced.setdefault(name, []).append((f".github/workflows/{path.name}", job_id, job))
    missing_dispatch = []
    for name, expected in producers.items():
        assert [entry[0] for entry in produced.get(name, [])] == [expected], name
        _, job_id, job = produced[name][0]
        triggers = _triggers(_workflow(expected))
        push = triggers.get("push") or {}
        assert push.get("branches") == ["main"], expected
        assert "branches-ignore" not in push and "tags" not in push, expected
        if "workflow_dispatch" not in triggers:
            missing_dispatch.append(expected)
        assert (triggers.get("workflow_dispatch") or {}).get("inputs") is None, expected
        assert "if" not in job, f"{job_id} must not be skippable on push/dispatch"
        assert "needs" not in job, f"{job_id} must not depend on another job"
    assert missing_dispatch == []


def test_workflow_dispatch_producers_check_out_the_dispatched_main_sha():
    for path in sorted(set(_helper_producers().values())):
        workflow = _workflow(path)
        for job in workflow["jobs"].values():
            for step in job.get("steps") or []:
                if _is_checkout(step):
                    ref = (step.get("with") or {}).get("ref")
                    assert ref is None or ref.endswith("github.sha }}"), (path, ref)


def test_proof_controls_require_node_backed_helper_tests_and_rehearse_fresh_runner():
    workflow = _workflow(PROOF_CONTROLS_WORKFLOW_PATH)
    triggers = _triggers(workflow)
    for event in ("pull_request", "push"):
        paths = triggers[event]["paths"]
        for watched in (RECEIPT_HELPER_PATH, PREFLIGHT_WORKFLOW_PATH, v2.WORKFLOW_PATH):
            assert watched in paths, (event, watched)
    controls = workflow["jobs"]["proof-v2-controls"]
    assert controls["env"]["REQUIRE_NODE_WORKFLOW_TESTS"] == "1"
    rehearsal = workflow["jobs"]["proof-v2-fresh-runner-rehearsal"]
    assert rehearsal["defaults"]["run"]["working-directory"] == "backend"
    steps = rehearsal["steps"]
    checkout = _step_index(steps, _is_checkout)
    negative, guard = steps[0], steps[1]
    assert checkout == 2
    assert negative["continue-on-error"] is True and "working-directory" not in negative
    assert guard["working-directory"] == WORKSPACE_EXPRESSION
    assert guard["env"]["INHERITED_OUTCOME"] == f"${{{{ steps.{negative['id']}.outcome }}}}"
    assert 'test "$INHERITED_OUTCOME" = "failure"' in guard["run"]
    assert "test ! -e backend" in guard["run"]
    assert rehearsal["permissions"] == {"contents": "read", "checks": "read", "actions": "read"}
    smoke = steps[checkout + 2]
    assert smoke["uses"] == "actions/github-script@v9"
    assert f"/{RECEIPT_HELPER_PATH}`)" in smoke["with"]["script"]
    assert "receipts.length !== 0" in smoke["with"]["script"]


def test_preflight_is_read_only_non_consuming_and_uses_identical_logic():
    workflow = _workflow(PREFLIGHT_WORKFLOW_PATH)
    assert list(_triggers(workflow)) == ["workflow_dispatch"]
    assert workflow["permissions"] == {"contents": "read", "checks": "read", "actions": "read"}
    jobs = workflow["jobs"]
    assert list(jobs) == ["proof-v2-receipt-preflight"]
    assert "proof-v2-receipt-preflight" not in v2.REQUIRED_CHECKS
    text = (Path(gate.ROOT) / PREFLIGHT_WORKFLOW_PATH).read_text()
    assert f"/{RECEIPT_HELPER_PATH}`)" in text
    assert "gate2.collectReceipts(" in text and "gate2.proofWorkflowHistory(" in text
    for forbidden in ("createWorkflowDispatch", "reRunWorkflow", "requireProofWorkflowUnused",
                      "run_recovery_gate2", "greenhouse.io", ": write"):
        assert forbidden not in text, forbidden
    assert _precheckout_violations(workflow) == []


# ---------------------------------------------------------------------------
# Receipt selection and one-use history semantics, executed with node against a
# mocked, paginating GitHub API (local simulation; no network).
# ---------------------------------------------------------------------------

NODE_HARNESS = r"""
const fs = require('fs');
const scenario = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const gate2 = require(process.argv[2]);
const calls = [];
function pager(name, key, items, totalOverride) {
  return async (params) => {
    const page = params.page || 1;
    calls.push({name, params});
    if ((scenario.fail || {})[name] === page) throw new Error(`HTTP 502 from ${name} page ${page}`);
    const size = params.per_page || 30;
    const slice = items.slice((page - 1) * size, page * size);
    const total = totalOverride === undefined || totalOverride === null ? items.length : totalOverride;
    return {data: {total_count: total, [key]: slice}};
  };
}
const github = {
  rest: {
    actions: {
      listWorkflowRunsForRepo: pager('listWorkflowRunsForRepo', 'workflow_runs', scenario.workflow_runs || []),
      listWorkflowRuns: pager('listWorkflowRuns', 'workflow_runs', scenario.proof_runs || [], scenario.proof_total_count),
    },
    checks: {listForRef: pager('listForRef', 'check_runs', scenario.check_runs || [])},
  },
  async paginate(method, params) {
    const out = [];
    for (let page = 1; ; page += 1) {
      const {data} = await method({...params, page});
      const items = data.check_runs || data.workflow_runs || [];
      out.push(...items);
      if (items.length < params.per_page) return out;
    }
  },
};
(async () => {
  try {
    const result = await gate2[scenario.fn]({github, owner: 'TheHighBrid', repo: 'JobTomatik', ...scenario.args});
    process.stdout.write(JSON.stringify({ok: true, result, calls}));
  } catch (error) {
    process.stdout.write(JSON.stringify({ok: false, error: String(error.message), calls}));
  }
})();
"""

RECEIPT_SHA = "e" * 40
OTHER_SHA = "f" * 40


def _node(tmp_path: Path, scenario: dict) -> dict:
    node = shutil.which("node")
    if not node:
        if os.getenv("REQUIRE_NODE_WORKFLOW_TESTS") == "1":
            pytest.fail("node is required for proof-v2 workflow helper tests")
        pytest.skip("node unavailable")
    harness = tmp_path / "harness.cjs"
    harness.write_text(NODE_HARNESS)
    data = tmp_path / "scenario.json"
    data.write_text(json.dumps(scenario))
    helper = Path(gate.ROOT) / RECEIPT_HELPER_PATH
    completed = subprocess.run([node, str(harness), str(helper), str(data)],
                               capture_output=True, text=True, timeout=60, check=True)
    return json.loads(completed.stdout)


def _receipt_world(sha: str = RECEIPT_SHA) -> dict:
    producers = _helper_producers()
    runs = {}
    for offset, path in enumerate(sorted(set(producers.values()))):
        runs[path] = {"id": 9000 + offset, "path": path, "event": "push", "head_branch": "main",
                      "head_sha": sha, "check_suite_id": 5000 + offset, "run_attempt": 1,
                      "status": "completed", "conclusion": "success"}
    checks = [
        {"id": 100 + index, "name": name, "head_sha": sha, "status": "completed", "conclusion": "success",
         "app": {"slug": "github-actions"}, "check_suite": {"id": runs[path]["check_suite_id"]},
         "details_url": f"https://github.com/TheHighBrid/JobTomatik/runs/{100 + index}"}
        for index, (name, path) in enumerate(producers.items())
    ]
    return {"fn": "collectReceipts", "args": {"sha": sha}, "workflow_runs": list(runs.values()),
            "check_runs": checks, "_runs": runs}


def _scenario(world: dict) -> dict:
    return {key: value for key, value in world.items() if not key.startswith("_")}


def _add_check(world: dict, name: str, check_id: int, *, status="completed", conclusion="success",
               suite=None, sha=RECEIPT_SHA, app="github-actions") -> None:
    path = _helper_producers()[name]
    world["check_runs"].append({
        "id": check_id, "name": name, "head_sha": sha, "status": status, "conclusion": conclusion,
        "app": {"slug": app}, "check_suite": {"id": suite or world["_runs"][path]["check_suite_id"]},
        "details_url": "https://example.test/check"})


def _add_run(world: dict, suite: int, path: str, **fields) -> None:
    run = {"id": suite + 70000, "path": path, "event": "push", "head_branch": "main",
           "head_sha": RECEIPT_SHA, "check_suite_id": suite, "run_attempt": 1}
    run.update(fields)
    world["workflow_runs"].append(run)


def test_receipt_helper_selects_complete_exact_head_set_with_producer_binding(tmp_path):
    output = _node(tmp_path, _scenario(_receipt_world()))
    assert output["ok"], output
    result = output["result"]
    assert result["missing"] == []
    assert [item["name"] for item in result["receipts"]] == list(v2.REQUIRED_CHECKS)
    for item in result["receipts"]:
        assert item["head_sha"] == RECEIPT_SHA and item["event"] == "push"
        assert item["head_branch"] == "main" and item["app"] == "github-actions"
        assert item["workflow_path"] == _helper_producers()[item["name"]]
    names = {call["name"]: call["params"] for call in output["calls"]}
    assert names["listForRef"]["filter"] == "all" and names["listForRef"]["ref"] == RECEIPT_SHA
    assert names["listWorkflowRunsForRepo"]["head_sha"] == RECEIPT_SHA


def test_helper_receipts_are_accepted_by_the_python_receipt_validator(tmp_path):
    output = _node(tmp_path, {**_scenario(_receipt_world()), "fn": "requireReceipts"})
    assert output["ok"], output
    path = tmp_path / "gate2-ci-prerequisites-v2.json"
    path.write_text(json.dumps({"schema": v2.PROOF_SCHEMA, "proof_id": v2.AUTHORIZED_PROOF_ID,
                                "target_url": v2.AUTHORIZED_TARGET_URL, "sha": RECEIPT_SHA, "run_id": 4242,
                                "receipts": output["result"]["receipts"],
                                "proof_workflow_history": {"total_count": 1, "runs": [{"id": 4242}]}}))
    data = v2.load_ci_receipts(path, RECEIPT_SHA, v2.AUTHORIZED_PROOF_ID, v2.AUTHORIZED_TARGET_URL, 4242)
    assert len(data["receipts"]) == len(v2.REQUIRED_CHECKS)


def test_receipt_helper_paginates_across_many_pages(tmp_path):
    world = _receipt_world()
    noise = [{"id": 10_000 + index, "name": f"unrelated-{index}", "head_sha": RECEIPT_SHA,
              "status": "completed", "conclusion": "success", "app": {"slug": "github-actions"},
              "check_suite": {"id": 1}} for index in range(250)]
    world["check_runs"] = noise + world["check_runs"]
    world["workflow_runs"] = [{"id": 20_000 + index, "path": ".github/workflows/x.yml", "event": "push",
                               "head_branch": "main", "head_sha": RECEIPT_SHA, "check_suite_id": 30_000 + index}
                              for index in range(205)] + world["workflow_runs"]
    output = _node(tmp_path, _scenario(world))
    assert output["ok"] and output["result"]["missing"] == [], output
    pages = [call["params"]["page"] for call in output["calls"] if call["name"] == "listForRef"]
    assert pages == [1, 2, 3]


@pytest.mark.parametrize(("api", "page"), [
    ("listForRef", 1), ("listForRef", 2), ("listWorkflowRunsForRepo", 1), ("listWorkflowRunsForRepo", 3),
])
def test_receipt_helper_api_failures_fail_closed(tmp_path, api, page):
    world = _receipt_world()
    world["check_runs"] += [{"id": 50_000 + i, "name": "noise", "head_sha": RECEIPT_SHA, "status": "completed",
                             "conclusion": "success", "app": {"slug": "github-actions"},
                             "check_suite": {"id": 1}} for i in range(250)]
    world["workflow_runs"] += [{"id": 60_000 + i, "path": "noise", "event": "push", "head_branch": "main",
                                "head_sha": RECEIPT_SHA, "check_suite_id": 61_000 + i} for i in range(250)]
    world["fail"] = {api: page}
    for fn in ("collectReceipts", "requireReceipts"):
        output = _node(tmp_path, {**_scenario(world), "fn": fn})
        assert output["ok"] is False and "HTTP 502" in output["error"], output


def _mutated(kind: str) -> tuple[dict, str]:
    world = _receipt_world()
    name = "pytest"
    path = _helper_producers()[name]
    if kind in {"queued", "in_progress"}:
        _add_check(world, name, 900, status=kind, conclusion=None)
    elif kind in {"failure", "cancelled", "timed_out", "skipped", "neutral", "action_required"}:
        world["check_runs"] = [c for c in world["check_runs"] if c["name"] != name]
        _add_check(world, name, 900, conclusion=kind)
    elif kind == "failed_rerun_after_success":
        _add_check(world, name, 900, conclusion="failure")
    elif kind == "newer_dispatch_in_progress":
        _add_run(world, 777, path, event="workflow_dispatch")
        _add_check(world, name, 900, status="in_progress", conclusion=None, suite=777)
    elif kind == "stale_sha_only":
        world["check_runs"] = [c for c in world["check_runs"] if c["name"] != name]
        _add_check(world, name, 900, sha=OTHER_SHA)
    elif kind == "pull_request_event_only":
        world["check_runs"] = [c for c in world["check_runs"] if c["name"] != name]
        _add_run(world, 778, path, event="pull_request")
        _add_check(world, name, 900, suite=778)
    elif kind == "wrong_workflow_only":
        world["check_runs"] = [c for c in world["check_runs"] if c["name"] != name]
        _add_run(world, 779, ".github/workflows/day30-policy-queue-gate.yml")
        _add_check(world, name, 900, suite=779)
    elif kind == "non_main_branch_only":
        world["check_runs"] = [c for c in world["check_runs"] if c["name"] != name]
        _add_run(world, 780, path, event="workflow_dispatch", head_branch="sol56/gate2-proof-v2-consolidation")
        _add_check(world, name, 900, suite=780)
    elif kind == "foreign_app_only":
        world["check_runs"] = [c for c in world["check_runs"] if c["name"] != name]
        _add_check(world, name, 900, app="third-party-ci")
    elif kind == "unknown_suite_only":
        world["check_runs"] = [c for c in world["check_runs"] if c["name"] != name]
        _add_check(world, name, 900, suite=424242)
    elif kind == "missing":
        world["check_runs"] = [c for c in world["check_runs"] if c["name"] != name]
    else:  # pragma: no cover - parametrization guard
        raise AssertionError(kind)
    return world, name


@pytest.mark.parametrize("kind", [
    "queued", "in_progress", "failure", "cancelled", "timed_out", "skipped", "neutral", "action_required",
    "failed_rerun_after_success", "newer_dispatch_in_progress", "stale_sha_only", "pull_request_event_only",
    "wrong_workflow_only", "non_main_branch_only", "foreign_app_only", "unknown_suite_only", "missing",
])
def test_receipt_helper_rejects_unproven_or_stale_receipts(tmp_path, kind):
    world, name = _mutated(kind)
    collected = _node(tmp_path, _scenario(world))
    assert collected["ok"], collected
    assert [item["name"] for item in collected["result"]["missing"]] == [name]
    assert name not in [item["name"] for item in collected["result"]["receipts"]]
    required = _node(tmp_path, {**_scenario(world), "fn": "requireReceipts"})
    assert required == {**required, "ok": False, "error": f"Unproven exact-head prerequisite: {name}"}


@pytest.mark.parametrize(("event", "attempt"), [("workflow_dispatch", 1), ("push", 2), ("schedule", 1)])
def test_receipt_helper_accepts_newest_successful_main_attempt(tmp_path, event, attempt):
    world = _receipt_world()
    path = _helper_producers()["pytest"]
    world["check_runs"] = [c for c in world["check_runs"] if c["name"] != "pytest"]
    _add_check(world, "pytest", 800, conclusion="failure")
    _add_run(world, 781, path, event=event, run_attempt=attempt)
    _add_check(world, "pytest", 901, suite=781)
    output = _node(tmp_path, _scenario(world))
    assert output["ok"] and output["result"]["missing"] == [], output
    selected = {item["name"]: item for item in output["result"]["receipts"]}["pytest"]
    assert (selected["id"], selected["event"], selected["workflow_run_attempt"]) == (901, event, attempt)


@pytest.mark.parametrize("sha", ["", "E" * 40, "e" * 39, "e" * 41, None])
def test_receipt_helper_rejects_malformed_sha_before_api_calls(tmp_path, sha):
    output = _node(tmp_path, {"fn": "collectReceipts", "args": {"sha": sha}})
    assert output["ok"] is False and output["error"] == "Invalid execution SHA"
    assert output["calls"] == []


def _proof_run(run_id: int, status="completed", conclusion="failure") -> dict:
    return {"id": run_id, "run_attempt": 1, "status": status, "conclusion": conclusion,
            "event": "workflow_dispatch", "head_branch": "main", "head_sha": RECEIPT_SHA}


@pytest.mark.parametrize(("runs", "total"), [([], 0), ([_proof_run(4242, "in_progress", None)], 1)])
def test_proof_history_allows_only_the_current_first_run(tmp_path, runs, total):
    output = _node(tmp_path, {"fn": "requireProofWorkflowUnused", "args": {"runId": 4242},
                              "proof_runs": runs, "proof_total_count": total})
    assert output["ok"], output
    workflow_ids = {call["params"]["workflow_id"] for call in output["calls"]}
    assert workflow_ids == {"recovery-gate2-public-v2.yml"}


@pytest.mark.parametrize("prior", [
    _proof_run(1, "queued", None), _proof_run(1, "in_progress", None), _proof_run(1, "completed", "failure"),
    _proof_run(1, "completed", "cancelled"), _proof_run(1, "completed", "success"),
    _proof_run(1, "completed", "startup_failure"),
])
def test_proof_history_any_prior_run_in_any_state_burns_identity(tmp_path, prior):
    output = _node(tmp_path, {"fn": "requireProofWorkflowUnused", "args": {"runId": 4242},
                              "proof_runs": [prior, _proof_run(4242, "in_progress", None)]})
    assert output == {**output, "ok": False, "error": "Gate 2 proof-v2 workflow has already been used"}


def test_proof_history_rejects_duplicate_listing_of_the_current_run(tmp_path):
    output = _node(tmp_path, {"fn": "requireProofWorkflowUnused", "args": {"runId": 4242},
                              "proof_runs": [_proof_run(4242), _proof_run(4242)]})
    assert output["ok"] is False and "already been used" in output["error"]


def test_proof_history_many_prior_runs_across_pages_burn_identity(tmp_path):
    runs = [_proof_run(index + 1) for index in range(150)] + [_proof_run(4242, "in_progress", None)]
    output = _node(tmp_path, {"fn": "requireProofWorkflowUnused", "args": {"runId": 4242}, "proof_runs": runs})
    assert output["ok"] is False and "already been used" in output["error"]


@pytest.mark.parametrize(("runs", "total", "message"), [
    ([_proof_run(4242, "in_progress", None)], 2, "pagination is incomplete"),
    ([], 1, "pagination is incomplete"),
    ([], None, "unreadable"),
])
def test_proof_history_truncated_or_unreadable_pagination_fails_closed(tmp_path, runs, total, message):
    scenario = {"fn": "requireProofWorkflowUnused", "args": {"runId": 4242}, "proof_runs": runs,
                "proof_total_count": total if total is not None else "unknown"}
    output = _node(tmp_path, scenario)
    assert output["ok"] is False and message in output["error"], output


@pytest.mark.parametrize("page", [1, 2])
def test_proof_history_api_failure_fails_closed(tmp_path, page):
    runs = [_proof_run(4242, "in_progress", None)] + [_proof_run(10 + i) for i in range(120)]
    output = _node(tmp_path, {"fn": "requireProofWorkflowUnused", "args": {"runId": 4242},
                              "proof_runs": runs, "fail": {"listWorkflowRuns": page}})
    assert output["ok"] is False and "HTTP 502" in output["error"], output


@pytest.mark.parametrize("run_id", [0, -1, None, "4242"])
def test_proof_history_requires_a_valid_current_run_id(tmp_path, run_id):
    output = _node(tmp_path, {"fn": "requireProofWorkflowUnused", "args": {"runId": run_id}})
    assert output["ok"] is False and output["error"] == "GitHub run ID missing"
    assert output["calls"] == []
