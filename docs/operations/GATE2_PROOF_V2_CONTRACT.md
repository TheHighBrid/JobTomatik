# Recovery Gate 2 public proof-v2 contract

This document defines the replacement execution contract after the original one-use public proof was consumed by run `37173569727`.

## Purpose

Proof-v2 preserves the original failed public evidence and execution mechanism unchanged while introducing a separately reviewable, separately identifiable one-use proof path.

The public target remains:

`https://job-boards.greenhouse.io/gitlab/jobs/8860302002`

The code-reviewed proof identity is:

`gate2-public-proof-v2-20261004`

Changing either value requires another reviewed repository change. The workflow does not substitute a target automatically.

## Immutable v1 evidence

The original workflow `.github/workflows/recovery-gate2-public.yml`, its consumed branch trigger, run `37173569727`, retained artifact, ledger and verdict remain historical evidence. Proof-v2 does not delete, rename, rerun, rewrite or reinterpret them.

## Proof-v2 execution mechanism

`.github/workflows/recovery-gate2-public-v2.yml` is a new workflow identity. It uses `workflow_dispatch` and requires the operator to provide all three exact values:

- reviewed `execution_sha`;
- `gate2-public-proof-v2-20261004`;
- the exact approved Greenhouse target URL above.

The workflow accepts only a first-attempt dispatch from `main`. It rejects any previous distinct run of the proof-v2 workflow. Reruns are rejected.

### Fresh-runner pre-checkout guard

A GitHub-hosted runner starts with an empty workspace, so `backend/` does not exist until `actions/checkout` runs. The first guard step therefore runs from `${{ github.workspace }}` instead of inheriting the job's `backend` default working directory, which would fail before any check could run.

Before checkout, the guard rejects:

- a run attempt other than `1`;
- a ref other than `refs/heads/main`;
- an execution SHA that is malformed or differs from `GITHUB_SHA`;
- a proof identity or target that differs from the code-reviewed values.

Only after that does the job check out the validated SHA. The authorization step then confirms that the checked-out `HEAD` equals the execution SHA, and loads the shared helper `.github/scripts/gate2_proof_v2_receipts.cjs` from that same commit.

A structural regression covers every workflow: no `run` step may start in a repository-relative directory before checkout. A non-consuming rehearsal job in `recovery-gate2-proof-v2.yml` exercises the same topology on a real fresh runner.

The workflow must not be dispatched until integration review explicitly releases the public proof.

## Exact-head prerequisites

Before browser execution, the workflow requires successful check receipts on the exact execution SHA for:

- `synthetic-controls`
- `proof-v2-controls`
- `exact-head-acceptance`
- `pytest`
- `owned-browser-compose-proof`
- `phase0-fastapi-celery-proof`
- `backend-browser-migration`
- `integrated-backend`
- `fast-gate`
- `dependency-audit`
- `Analyze python`
- `Analyze javascript-typescript`

The receipt set is retained in the evidence artifact and independently revalidated by the proof-v2 reviewer. `proof-v2-controls` is produced by `.github/workflows/recovery-gate2-proof-v2.yml` and exercises the replacement execution contract directly.

### Receipt selection

The shared helper defines the canonical producer workflow for each required name. That map must equal `REQUIRED_CHECKS` in `backend/scripts/run_recovery_gate2_v2.py`. A check run is eligible as a receipt only if all of the following hold:

- its `head_sha` equals the execution SHA;
- it comes from the `github-actions` app;
- its check suite belongs to the canonical producer workflow;
- that workflow run is on `main` and was started by a `push`, `workflow_dispatch` or `schedule` event.

`pull_request` runs are never receipts, even when their head SHA equals the main SHA.

The newest eligible check run must itself be a completed success. A newer queued, in-progress, failed or cancelled attempt is never masked by an older success. GitHub API and pagination errors propagate and fail closed.

The one-use history check counts every proof-v2 run in any state. It cross-checks the paginated run list against the independently returned `total_count`, so a truncated page cannot hide a prior run.

### Receipt liveness on any main SHA

Every required producer runs on push to `main` and also exposes `workflow_dispatch`. Push path filters therefore cannot strand a receipt: a missing receipt on the current main SHA can always be produced by dispatching its producer with `--ref main`.

Before any proof-v2 dispatch, run the read-only `.github/workflows/recovery-gate2-proof-v2-preflight.yml` on `main`. It uses the identical helper to report every missing receipt, which producer to dispatch, and whether proof-v2 history is already non-empty. It is a separate workflow identity, so it never consumes proof-v2 history, and it never dispatches, reruns or contacts an ATS.

## Duplicate and one-use scope

The existing Gate 2 runner still reserves the target plus fixed synthetic profile in the `attempts` table for within-proof duplicate protection.

Proof-v2 additionally reserves the code-reviewed proof identity in `proof_runs`. Its target key binds the proof identity to the normalized Greenhouse board/job identity. The retained ledger therefore contains both the original application-attempt reservation and the proof-v2 reservation.

The workflow-level one-use rule prevents a second accepted proof-v2 workflow run. The ledger independently prevents reuse of the same proof identity inside the same retained proof ledger.

A future separately authorized retry must use a new reviewed proof identity and a new reviewed workflow contract. It must not reset or overwrite v1 or v2 evidence.

## Fail-closed execution

Proof-v2 delegates browser behavior to the reviewed Gate 2 runner. Existing invariants remain unchanged:

- synthetic identity only;
- `dry_run=True`;
- final-submit DOM guards;
- POST/other mutation blocking;
- WebSocket blocking;
- exact telemetry abort reconciliation;
- passive invisible reCAPTCHA observation only;
- interactive CAPTCHA, Cloudflare, hCaptcha, MFA, login, identity and security boundaries stop before filling;
- exact target identity before filling;
- production Greenhouse adapter and filler evidence;
- retained trace, HTML diagnostics, field readbacks, ledger and teardown evidence;
- independent machine-readable review.

No CAPTCHA interaction, final submission, automatic retry or target substitution is permitted.

## Integration sequencing

The proof-v2 consolidation branch is based on #644 exact head `b3747437efb21a4d0754e0b9bbe7a25ae8644f84`, whose ancestry contains #641, original reviewed #642 head `f94b4e749e58e4e53f8bde40cf9cc10975ba820e`, #643 and #644.

Current #642 later diverged to `fb2cab44ba726939934c21d13c457583db9eab6c` with overlapping Cloudflare/pipefail changes. That divergent head is not the consolidation base and must not be blindly merged into the clean successor chain.

The consolidation pull request targets `main` so main-based canonical checks, including CodeQL, can produce exact-head receipts before any release decision.

## Status

Repository engineering only. No public Greenhouse execution is authorized or performed by this contract. Gate 2 remains `NOT_PROVEN` until a separately released proof-v2 run produces complete retained evidence and independent adjudication returns PASS.
