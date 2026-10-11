# JT5 caller inventory (GitHub default branch search, 2026-10-11)

This is a **search-derived inventory**, not proof that every dynamic import, generated file, or historical branch has been enumerated. Re-run repository-wide `rg` in CI before deleting code.

## Exact approval validator references
Production:
- `backend/app/services/supervised_submission.py`: definition and internal validator.
- `backend/app/api/supervised_submissions.py`: approval-based queue endpoint.
- `backend/app/services/supervised_submission_integration.py`: worker validation before browser execution.
- `backend/app/services/submission_integrity_integration.py`: monkey-patched guarded validator.

Tests:
- `backend/tests/test_current_lever_operator_execution_lock.py`
- `backend/tests/test_supervised_submission_approval.py`
- `backend/tests/test_supervised_target_liveness.py`
- `backend/tests/test_submission_idempotency_assault.py`
- `backend/tests/test_supervised_lever_pilot_runtime_control.py`

## Approval issuer references
- `backend/app/services/supervised_submission.py`
- `backend/app/services/submission_integrity_integration.py`
- `backend/app/api/supervised_submissions.py`
- `backend/tests/test_supervised_target_liveness.py`
- `.github/workflows/day39-current-lever-intake-gate.yml`

## Worker gate installer references
- `backend/app/services/supervised_submission_integration.py`
- `backend/app/celery_app.py`
- `backend/app/main.py`
- `backend/app/tasks/unattended.py`

## Pilot flag runtime sites
Greenhouse:
- `backend/app/config.py`
- `backend/app/services/supervised_platforms.py`
- `backend/app/services/supervised_pilot_roster.py`
- `backend/app/services/greenhouse_oh1_preflight.py`
- `backend/app/services/recovery_gate2.py`
- `frontend/src/supervisedPlatforms.js`
- `frontend/src/components/SupervisedPilotRoster.jsx`
- `backend/scripts/check_runtime_identity.py`

Lever additionally:
- `backend/app/services/operator_assisted_handoff_integration.py`
- `backend/scripts/lever_supervised_pilot_runtime.py`
- `backend/scripts/prepare_lever_promotion_lane_state.py`
- `backend/scripts/run_lever_phase_a_handoff.py`

The flags also occur in Docker Compose files, example env files, documentation, verification scripts, workflows and many tests. These are **migration consumers**, not safe-to-delete files.

## Live-submit flag production sites
- `backend/app/config.py`
- `backend/app/api/applications.py`
- `backend/app/tasks/applications.py`
- `backend/app/services/operations_policy.py`
- `backend/app/services/supervised_submission.py`
- `backend/app/services/operator_assisted_final_action.py`
- `backend/app/services/operator_assisted_handoff_integration.py`
- `backend/app/tasks/scraping.py`
- `backend/app/tasks/handoffs.py`
- `backend/app/tasks/unattended.py`
- plus operational/recovery/shadow/certification services and many test/CI/documentation consumers.

## Cutover hazard
The existing `POST /api/applications/{app_id}/submit` calls `submit_application_task.delay(...)` after `_require_live_submit_enabled`. The worker task is wrapped by supervised submission integration. Replacing only the API would leave the old worker approval gate in place. Keep legacy paths intact until the new API, task, claim/finalize semantics and tests are green.

## Coordination
Do not touch live Affirm application #14. Coordinate #674 browser-profile lifecycle and #673 failed-dry-run browser retention. #675 approval timezone fix remains independently relevant to legacy code until full cutover.
