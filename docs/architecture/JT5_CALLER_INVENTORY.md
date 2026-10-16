# JT5 caller inventory (GitHub search + file inspection, 2026-10-11)

**2026-10-16 correction:** the table below is a dated migration inventory, not
a current authorization to delete release controls. Ordinary JT5 Apply is
integrated through #704. Preserve `ALLOW_REAL_APPLICATION_SUBMIT` as an operational
release control; #706 corrects its missing API/worker enforcement. Re-run current
caller searches before deletion. Operator/recovery callers remain separately
scoped. See [current execution contract](JT5_SIMPLIFIED_APPLICATION_EXECUTION.md).

Search-derived inventory plus direct file inspection of production call sites.
Re-run repository-wide `rg` in CI before deleting code.

## Delete-set classification

| Class | Meaning |
|-------|---------|
| **DELETE after caller verification** | Redundant owner-facing approval ceremony and legacy pilot-lease dependencies on ordinary JT5 Apply; preserve global release controls |
| **KEEP** | Auth, ownership, duplicate/uncertain protection, evidence, browser isolation |
| **MIGRATE** | Callers that must switch to JT5 before the old path is removed |
| **DO NOT TOUCH YET** | Operator-assisted handoff (human final click) and recovery scripts that still use pilot flags as safety |

## Exact `validate_supervised_approval` sites

### Production (MIGRATE then DELETE from JT5 path)

| File | Role |
|------|------|
| `backend/app/services/supervised_submission.py` | Definition; expiration/timezone comparisons (Affirm incident root) |
| `backend/app/api/supervised_submissions.py` | `queue_supervised_submission` validates before `reserve_submission_attempt` |
| `backend/app/services/supervised_submission_integration.py` | Worker: validate **twice** (`consume=False` then `consume=True`) before browser |
| `backend/app/services/submission_integrity_integration.py` | Monkey-patches API + worker validators with binding-hash guard |

### Tests (MIGRATE/rewrite)

- `backend/tests/test_current_lever_operator_execution_lock.py`
- `backend/tests/test_supervised_submission_approval.py`
- `backend/tests/test_supervised_target_liveness.py`
- `backend/tests/test_submission_idempotency_assault.py`
- `backend/tests/test_supervised_lever_pilot_runtime_control.py`

## Approval issue / revoke sites

| Symbol | Production files |
|--------|------------------|
| `issue_supervised_approval` | `supervised_submission.py`, `supervised_submissions.py` API, guarded in `submission_integrity_integration.py` |
| `revoke_supervised_approval` | `supervised_submission.py`, `supervised_submissions.py` API |

## Worker gate installers (MIGRATE — keep install until legacy path retired)

- `backend/app/services/supervised_submission_integration.py` (`install_supervised_submission_task_gate`)
- Called from: `backend/app/celery_app.py`, `backend/app/main.py`, `backend/app/tasks/unattended.py`

## Pilot flag runtime sites

Flags: `greenhouse_supervised_pilot_enabled` / `GREENHOUSE_SUPERVISED_PILOT_ENABLED`,
`lever_supervised_pilot_enabled` / `LEVER_SUPERVISED_PILOT_ENABLED`.

### Production decision points (DELETE from JT5 path)

| File | Behavior |
|------|----------|
| `backend/app/config.py` | Settings definition |
| `backend/app/services/supervised_platforms.py` | Policy registry; `pilot_enabled(settings)` |
| `backend/app/services/supervised_submission.py` | Preflight blockers `*_pilot_disabled` |
| `backend/app/services/operator_assisted_submission.py` | Operator preflight pilot blockers |
| `backend/app/services/supervised_pilot_roster.py` | Roster readiness includes live-submit + pilot |
| `backend/app/services/recovery_gate2.py` | Fail-closed if pilot env true during recovery |

### Frontend / scripts / docs (MIGRATE consumers, not first delete)

- `frontend/src/supervisedPlatforms.js`, `frontend/src/components/SupervisedPilotRoster.jsx`
- `scripts/verify.sh`, `scripts/verify-onehost-handoff.sh`
- `backend/scripts/check_runtime_identity.py`, lever pilot scripts, compose/env examples, OPERATIONS_GUIDE

## Live-submit flag sites

Flag: `allow_real_application_submit` / `ALLOW_REAL_APPLICATION_SUBMIT`.

### Production (KEEP global release control; verify API and worker enforcement)

| File | Behavior |
|------|----------|
| `backend/app/config.py` | Definition |
| `backend/app/tasks/applications.py` | `LIVE_SUBMIT_BLOCKED_REASON` when false |
| `backend/app/services/supervised_submission.py` | Preflight `global_live_submit_disabled` |
| `backend/app/api/applications.py` | `_require_live_submit_enabled` on legacy submit |
| Additional policy, operator and scheduled-task callers | Reinspect current operations_policy, operator-assisted and scraping/handoff/unattended call sites before editing |

## JT5 path (integrated) and global release enforcement

Do not call redundant legacy approval ceremonies from ordinary JT5 Apply.
The global live-submit setting still applies at API reservation and worker entry;
that correction is pending #706. This is distinct from reactivating a pilot lease.

| Component | File |
|-----------|------|
| Decision gate | `backend/app/services/application_execution_gate.py` |
| Reservation | `backend/app/services/application_attempt_jt5.py` |
| Claim/finalize | `backend/app/services/application_attempt_lifecycle_jt5.py` |
| API | `backend/app/api/jt5_applications.py` |
| Worker | `backend/app/tasks/jt5_execution.py` |

## Cutover hazards

1. Legacy `POST .../approvals/{ref}/submit` still validates approval then publishes `submit_application_task` with `approval_reference` — worker re-validates. Replacing only the API leaves the worker gate.
2. `SubmissionAttempt.approval_reference` is still NOT NULL unique; JT5 uses synthetic `jt5-*` values until a schema migration drops the column.
3. Operator-assisted final click is a **different** product path (human clicks Submit). Do not delete it as part of JT5.
4. Do not touch live Affirm application #14. Coordinate #674 / #673 / #675.

## Acceptance before deleting legacy gates

- JT5 apply endpoint green in CI
- Worker never calls `validate_supervised_approval`
- Concurrent reserve → one attempt
- Confirmed / uncertain outcomes never auto-retry
- Backend and worker same image/revision

## Implementation status on this branch (2026-10-12)

| Component | Status |
|-----------|--------|
| Decision gate | Landed |
| Reservation + claim/finalize | Landed |
| `POST /api/applications/{id}/jt5/apply` | Landed (dispatches worker) |
| `GET /api/applications/{id}/jt5/status` | Landed |
| JT5 Celery worker (no approval/pilot) | Landed |
| Fail-closed browser outcome classification | Landed + form_filler normalizer |
| Stale reservation reconciliation | Landed |
| Exact-head CI workflow | Landed (`.github/workflows/jt5-exact-head.yml`) |
| Legacy approval path removal | **Not started** — keep until JT5 CI green and owner cutover |
| form_filler native `final_submit_attempted` field | Deferred; JT5 normalizer derives from `submit_clicked` / log |
| Live Affirm #14 | Untouched |

Do not delete `validate_supervised_approval` production call sites until the JT5 path is the only owner Apply surface and exact-head tests are green.
