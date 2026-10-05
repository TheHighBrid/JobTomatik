'use strict';
// Read-only exact-head receipt selection and one-use history checks for the
// Recovery Gate 2 proof-v2 workflow and its non-consuming preflight.
//
// Every function here only reads the GitHub API. API and pagination errors are
// never caught: they propagate and fail the calling step closed.

const PROOF_SCHEMA = 'jobtomatik.recovery.gate2.public-proof.v2';
const PROOF_WORKFLOW = 'recovery-gate2-public-v2.yml';
const RECEIPT_APP = 'github-actions';
const RECEIPT_BRANCH = 'main';
// Runs from these events execute the workflow definition committed on main at
// the run's head SHA. pull_request runs use merge-ref definitions/trees and are
// never receipts, even when their head_sha equals the main SHA.
const RECEIPT_EVENTS = Object.freeze(['push', 'workflow_dispatch', 'schedule']);
// Canonical producer for every required exact-head receipt. Order and names
// must equal REQUIRED_CHECKS in backend/scripts/run_recovery_gate2_v2.py.
const REQUIRED_PRODUCERS = Object.freeze({
  'synthetic-controls': '.github/workflows/recovery-gate2.yml',
  'proof-v2-controls': '.github/workflows/recovery-gate2-proof-v2.yml',
  'exact-head-acceptance': '.github/workflows/current-head-final-acceptance.yml',
  'pytest': '.github/workflows/backend-tests.yml',
  'owned-browser-compose-proof': '.github/workflows/onehost-fixture-gate.yml',
  'phase0-fastapi-celery-proof': '.github/workflows/onehost-api-celery-gate.yml',
  'backend-browser-migration': '.github/workflows/reproducible-verification.yml',
  'integrated-backend': '.github/workflows/post-merge-stabilization.yml',
  'fast-gate': '.github/workflows/reproducible-verification.yml',
  'dependency-audit': '.github/workflows/reproducible-verification.yml',
  'Analyze python': '.github/workflows/codeql.yml',
  'Analyze javascript-typescript': '.github/workflows/codeql.yml',
});
const REQUIRED_CHECKS = Object.freeze(Object.keys(REQUIRED_PRODUCERS));

function requireSha(sha) {
  if (typeof sha !== 'string' || !/^[0-9a-f]{40}$/.test(sha)) throw new Error('Invalid execution SHA');
  return sha;
}

function producerRun(check, sha, path, suites) {
  if (!check || check.head_sha !== sha) return null;
  if (!check.app || check.app.slug !== RECEIPT_APP) return null;
  const suiteId = check.check_suite && check.check_suite.id;
  const run = suites.get(suiteId);
  if (!run || run.head_sha !== sha || run.path !== path) return null;
  if (run.head_branch !== RECEIPT_BRANCH || !RECEIPT_EVENTS.includes(run.event)) return null;
  return run;
}

// Select, for every required check, the newest check run produced on the exact
// SHA by its canonical main workflow. The newest attempt must itself be a
// completed success: a newer queued, in-progress, failed or cancelled attempt
// (including a rerun or a later dispatch) is never masked by an older success.
async function collectReceipts({github, owner, repo, sha}) {
  requireSha(sha);
  const runs = await github.paginate(github.rest.actions.listWorkflowRunsForRepo,
    {owner, repo, head_sha: sha, per_page: 100});
  const suites = new Map();
  for (const run of runs) {
    if (run && run.head_sha === sha && Number.isInteger(run.check_suite_id)) suites.set(run.check_suite_id, run);
  }
  const checks = await github.paginate(github.rest.checks.listForRef,
    {owner, repo, ref: sha, filter: 'all', per_page: 100});
  const receipts = [];
  const missing = [];
  for (const name of REQUIRED_CHECKS) {
    const path = REQUIRED_PRODUCERS[name];
    const candidates = checks
      .filter(check => check && check.name === name && Number.isInteger(check.id))
      .map(check => ({check, run: producerRun(check, sha, path, suites)}))
      .filter(candidate => candidate.run)
      .sort((a, b) => b.check.id - a.check.id);
    const selected = candidates[0];
    if (!selected) {
      missing.push({name, workflow_path: path, reason: 'no eligible exact-head check run'});
      continue;
    }
    const {check, run} = selected;
    if (check.status !== 'completed' || check.conclusion !== 'success') {
      missing.push({name, workflow_path: path, check_id: check.id,
        reason: `newest eligible check run is ${check.status}/${check.conclusion || 'none'}`});
      continue;
    }
    receipts.push({name, id: check.id, head_sha: check.head_sha, status: check.status,
      conclusion: check.conclusion, url: check.details_url, app: check.app.slug,
      workflow_path: run.path, workflow_run_id: run.id, workflow_run_attempt: run.run_attempt,
      event: run.event, head_branch: run.head_branch});
  }
  return {sha, receipts, missing};
}

async function requireReceipts(options) {
  const result = await collectReceipts(options);
  if (result.missing.length) throw new Error(`Unproven exact-head prerequisite: ${result.missing[0].name}`);
  if (result.receipts.length !== REQUIRED_CHECKS.length) throw new Error('Canonical exact-head receipt set is incomplete');
  return result;
}

// Observe every run of the proof-v2 workflow. Any run, in any state, counts.
// total_count is read independently so a truncated pagination cannot hide a
// prior run.
async function proofWorkflowHistory({github, owner, repo}) {
  const first = await github.rest.actions.listWorkflowRuns(
    {owner, repo, workflow_id: PROOF_WORKFLOW, per_page: 100});
  const totalCount = first && first.data ? first.data.total_count : undefined;
  if (!Number.isInteger(totalCount) || totalCount < 0) throw new Error('Gate 2 proof-v2 workflow history is unreadable');
  const runs = await github.paginate(github.rest.actions.listWorkflowRuns,
    {owner, repo, workflow_id: PROOF_WORKFLOW, per_page: 100});
  if (runs.length < totalCount) throw new Error('Gate 2 proof-v2 workflow history pagination is incomplete');
  return {total_count: totalCount,
    runs: runs.map(run => ({id: run.id, run_attempt: run.run_attempt, status: run.status,
      conclusion: run.conclusion, event: run.event, head_branch: run.head_branch, head_sha: run.head_sha}))};
}

// First-attempt-only: the only run the proof-v2 workflow may ever have is the
// current one. Queued, in-progress, failed, cancelled and successful prior runs
// all consume the identity.
async function requireProofWorkflowUnused({github, owner, repo, runId}) {
  if (!Number.isInteger(runId) || runId <= 0) throw new Error('GitHub run ID missing');
  const history = await proofWorkflowHistory({github, owner, repo});
  if (history.total_count > 1 || history.runs.length > 1 || history.runs.some(run => run.id !== runId))
    throw new Error('Gate 2 proof-v2 workflow has already been used');
  return history;
}

module.exports = {
  PROOF_SCHEMA, PROOF_WORKFLOW, RECEIPT_APP, RECEIPT_BRANCH, RECEIPT_EVENTS,
  REQUIRED_PRODUCERS, REQUIRED_CHECKS, requireSha, collectReceipts, requireReceipts,
  proofWorkflowHistory, requireProofWorkflowUnused,
};
