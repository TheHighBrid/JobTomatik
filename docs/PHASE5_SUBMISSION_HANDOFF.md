# Phase 5: Tamper-Evident Submission Handoff

## Purpose

Phase 5 connects a completed bounded `AgentRun` to JobTomatik's existing supervised-submission workflow without allowing bounded orchestration to become submission consent.

The handoff dossier answers one narrow question:

> What exact bounded run, application, verified materials, task ledger, target, profile, résumé, cover letter, and approved answer-policy payload did the owner review before opening separate supervised preflight?

It does not answer:

> Did the owner authorize final submit?

That decision remains exclusively inside the existing supervised-submission approval system.

## Hard boundary

A handoff can:

- inspect one user-owned completed bounded run;
- verify the completed application-readiness task;
- hash the bounded task ledger;
- hash the latest verified cover letter and résumé summary;
- reuse the current exact submission snapshot hashes;
- report current supervised-preflight blockers;
- record handoff creation and local review as `ApplicationEvent` entries;
- route the owner to the exact Application Detail page.

A handoff cannot:

- create, validate, consume, revoke, or expire a `SubmissionApproval`;
- create or reserve a `SubmissionAttempt`;
- publish a Celery submission task;
- open or control a browser;
- contact an ATS;
- click a final-submit control;
- send recruiter outreach;
- enable global live submit or a platform pilot;
- promote adapter maturity;
- bypass CAPTCHA, MFA, login, identity, assessment, or anti-bot controls.

Every response and stored dossier retains:

```json
{
  "submission_authorized": false,
  "approval_issued": false,
  "queue_attempted": false
}
```

## Storage

No migration is introduced.

The immutable dossier snapshot and review metadata are stored under:

```text
AgentRun.run_context.submission_handoff
```

Application history receives two non-state-changing events:

- `bounded_submission_handoff_created`
- `bounded_submission_handoff_reviewed`

The events retain IDs and hashes only. Raw applicant answers, résumé contents, cover-letter contents, and profile fields are not copied into the handoff.

## Eligibility

A dossier can be created only when:

- the run belongs to the authenticated user;
- the run status is `completed`;
- `AgentRun.run_context.execution_control` already exists;
- inspection does not synthesize or initialize missing bounded-control metadata;
- execution scope is exactly `bounded_local_execution`;
- bounded approval state is `approved` or `not_required`;
- bounded execution retained `submission_authorized=false`;
- bounded execution retained `outreach_authorized=false`;
- the run was not cancelled;
- one application-readiness task exists and completed;
- that task retained `ready_for_separate_submission_preflight=true`;
- that task retained `submission_attempted=false`;
- that task retained `submission_authorized=false`;
- the readiness task has no blockers;
- the referenced application still belongs to the run owner and is not closed;
- the latest cover letter and résumé summary still exist and are `verified`;
- both verified materials have exact ID/version references in the bounded readiness output;
- their IDs and versions still match the bounded readiness output.

Missing control metadata, an unsatisfied bounded approval, or a missing readiness material reference blocks the handoff rather than being repaired or inferred.

## Exact hashes

The handoff records:

- handoff hash;
- bounded task-ledger hash;
- exact combined submission-payload hash;
- profile snapshot hash;
- résumé file hash;
- cover-letter hash;
- approved answer-policy payload hash;
- exact target-identity hash when required by the platform;
- material content, claims, warnings, and source-snapshot hashes.

No raw material or applicant-answer body is embedded in the dossier.

## Drift detection

Every inspection rebuilds the current candidate and compares it with the stored dossier.

Drift is reported when any retained boundary changes, including:

- task ledger or task output;
- profile snapshot;
- résumé file;
- cover letter;
- answer policies;
- exact target identity;
- combined payload;
- automation state;
- application target status;
- latest material IDs, versions, status, claims, warnings, source snapshot, or content.

A drifted dossier cannot be reviewed. It must be regenerated, which clears the previous review.

## Acknowledgments

Creation requires the exact phrase:

```text
CREATE SUBMISSION HANDOFF <run_id>
```

Local review requires a separate exact phrase:

```text
REVIEW SUBMISSION HANDOFF <run_id>
```

Neither phrase is accepted by the supervised-submission approval service. Neither grants final-submit permission.

## API

- `GET /api/intelligence/agent-runs/{run_id}/submission-handoff`
- `POST /api/intelligence/agent-runs/{run_id}/submission-handoff`
- `POST /api/intelligence/agent-runs/{run_id}/submission-handoff/review`

All routes are account-scoped. Cross-account run IDs return `404`.

## Handoff Review workspace

The new `/handoff-review` page provides:

- completed-run selection;
- live eligibility and drift inspection;
- explicit false submission/approval/queue indicators;
- exact retained hashes;
- current supervised-preflight readiness and blockers;
- exact-phrase dossier creation or refresh;
- exact-phrase local review;
- routing to the exact Application Detail page only after review.

Application Detail remains responsible for fresh supervised preflight and the existing short-lived one-time exact-payload approval.

## Validation contract

Regression coverage verifies:

- handoff creation and review leave `SubmissionApproval` count at zero;
- handoff creation and review leave `SubmissionAttempt` count at zero;
- exact acknowledgments are required;
- routes are account-scoped;
- missing readiness material references block eligibility;
- missing bounded-control metadata blocks eligibility without being synthesized;
- pending bounded approval blocks eligibility;
- cover-letter and combined-payload mutations trigger drift;
- events are retained without changing application state;
- UI copy explicitly separates review from final-submit approval;
- the reviewed dossier routes to the exact application;
- frontend production build, backend/browser suite, migrations, Android packaging, CodeQL, dependency audit, deployment defaults, adapter maturity, and release gates remain green.