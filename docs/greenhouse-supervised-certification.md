# Greenhouse Supervised Certification Protocol

This protocol governs the promotion of the Greenhouse adapter from `dry_run` to `human_reviewed_submit`.

It does not authorize unattended submission. It does not authorize CAPTCHA, anti-bot, MFA, login, assessment, or identity-verification bypass.

Tracking issue: #24
Roadmap: #13

## 1. Release boundary

The Greenhouse adapter remains `dry_run` until every required gate in this document has passed and an explicit approval reference has been recorded in the canonical adapter manifest.

Promotion under this protocol is limited to:

`human_reviewed_submit`

Promotion to `certified_autonomous` is outside this protocol.

## 2. Required evidence set

### Representative dry runs

Complete at least 30 dry runs across different employers.

The sample should cover, where available:

- hosted and embedded Greenhouse forms
- single-step and multi-step forms
- custom text questions
- native selects and custom comboboxes
- radio buttons and checkboxes
- multi-select controls
- dynamically revealed questions
- work authorization and sponsorship
- privacy and consent
- voluntary demographic sections
- résumé and cover-letter uploads
- validation failures
- CAPTCHA or anti-bot handoff

Every dry run must stop before final submission and record `final_submit_clicked=false`.

### Supervised real submissions

After the 30-run dry-run matrix is accepted, complete at least 10 supervised real submissions.

Each real submission requires approval for the exact employer, role, application URL, résumé, cover letter, and answer payload.

## 3. Run record schema

Record the following for every dry run and supervised submission:

```yaml
run_id:
mode: dry_run | supervised_real_submission
started_at:
completed_at:
employer:
role:
board_token:
job_id:
application_url:
adapter_version:
framework_version:
operator:
approval_reference:
profile_snapshot_hash:
resume_hash:
cover_letter_hash:
answer_payload_hash:
controls_discovered:
controls_filled:
controls_skipped:
controls_blocked:
policies_used:
uploads_verified:
validation_errors:
handoff_reason:
handoff_boundary:
pre_submit_state:
final_url:
final_submit_clicked:
confirmation_evidence_type:
confirmation_evidence_reference:
final_status:
duplicate_guard_verified:
notes:
```

## 4. Pre-submission checklist

Before a supervised real submission:

- [ ] Exact employer, role, and URL were approved.
- [ ] Selected résumé was reviewed.
- [ ] Selected cover letter was reviewed.
- [ ] Answer payload was reviewed.
- [ ] No unresolved required-answer policy remains.
- [ ] Sensitive and legal answers come from explicit approved policy.
- [ ] Duplicate lookup returned no prior submission.
- [ ] Idempotency key is present and unique.
- [ ] Greenhouse is the detected adapter.
- [ ] Platform kill switch is available.
- [ ] Failure and uncertain-submission recovery path is ready.
- [ ] CAPTCHA, MFA, login, assessment, and identity boundaries will route to manual review.

## 5. Confirmation evidence

A submit-button click is not sufficient evidence.

Acceptable evidence includes one or more of:

- platform-specific confirmation page
- success banner with stable selector and expected text
- application or candidate identifier
- redirected application-history record
- matching confirmation email
- downloadable receipt or completed-application record

If evidence is insufficient, the application must become `submission_uncertain`, never `submitted`.

## 6. Promotion gates

Greenhouse may be promoted to `human_reviewed_submit` only when all of the following are true:

- [ ] 30 representative dry runs completed.
- [ ] 10 supervised real submissions completed.
- [ ] Zero false `submitted` records.
- [ ] Zero duplicate submissions.
- [ ] Every successful submission has concrete confirmation evidence.
- [ ] Every uncertain result became `submission_uncertain`.
- [ ] Every unsupported required control routed to manual review.
- [ ] Duplicate prevention was independently verified.
- [ ] Confirmation evidence was independently reviewed.
- [ ] Supervised pilot report was retained.
- [ ] Explicit approval reference was recorded.

## 7. Prohibited actions

- Never use the synthetic certification identity for a real application.
- Never infer demographic, legal, authorization, sponsorship, consent, or identity answers.
- Never bypass CAPTCHA, anti-bot, MFA, login, assessment, or identity verification.
- Never submit without explicit approval.
- Never submit twice.
- Never mark an uncertain outcome successful.
- Never broaden the release to autonomous submission through this protocol.

## 8. Progress ledger

| Run | Mode | Employer | Role | Outcome | Evidence | Reviewed |
|---:|---|---|---|---|---|---|
| 1 |  |  |  |  |  |  |
| 2 |  |  |  |  |  |  |
| 3 |  |  |  |  |  |  |
| 4 |  |  |  |  |  |  |
| 5 |  |  |  |  |  |  |
| 6 |  |  |  |  |  |  |
| 7 |  |  |  |  |  |  |
| 8 |  |  |  |  |  |  |
| 9 |  |  |  |  |  |  |
| 10 |  |  |  |  |  |  |
| 11 |  |  |  |  |  |  |
| 12 |  |  |  |  |  |  |
| 13 |  |  |  |  |  |  |
| 14 |  |  |  |  |  |  |
| 15 |  |  |  |  |  |  |
| 16 |  |  |  |  |  |  |
| 17 |  |  |  |  |  |  |
| 18 |  |  |  |  |  |  |
| 19 |  |  |  |  |  |  |
| 20 |  |  |  |  |  |  |
| 21 |  |  |  |  |  |  |
| 22 |  |  |  |  |  |  |
| 23 |  |  |  |  |  |  |
| 24 |  |  |  |  |  |  |
| 25 |  |  |  |  |  |  |
| 26 |  |  |  |  |  |  |
| 27 |  |  |  |  |  |  |
| 28 |  |  |  |  |  |  |
| 29 |  |  |  |  |  |  |
| 30 |  |  |  |  |  |  |
| 31 | supervised |  |  |  |  |  |
| 32 | supervised |  |  |  |  |  |
| 33 | supervised |  |  |  |  |  |
| 34 | supervised |  |  |  |  |  |
| 35 | supervised |  |  |  |  |  |
| 36 | supervised |  |  |  |  |  |
| 37 | supervised |  |  |  |  |  |
| 38 | supervised |  |  |  |  |  |
| 39 | supervised |  |  |  |  |  |
| 40 | supervised |  |  |  |  |  |
